# -*- coding: utf-8 -*-
"""本公司資料設定閘門：本機 CLI 與 apply_update.ps1 的預檢／套用後檢查（COMPANY-SETUP-GATE §6.3；CG2-S3、CG3-M1）。

CLI 以子行程真的執行（不 import main）；ps1 以「抽出 Invoke-CompanySetupCli 函式＋假的 CLI」在 powershell 裡執行，
驗 fail closed：當掉／非零／逾時／輸出壞／configured null 一律不放行。
"""
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from helpers import company_setup as cs
from tests.test_company_setup_core_2026_09_28 import GOOD, _db, _root

BACKEND = Path(__file__).resolve().parents[1]
CLI = BACKEND / "tools" / "company_setup_cli.py"
PS1 = BACKEND / "tools" / "apply_update.ps1"


def run_cli(*args):
    r = subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True, encoding="utf-8",
                       timeout=60)
    line = [l for l in r.stdout.splitlines() if l.strip().startswith("{")][-1]
    return r.returncode, json.loads(line)


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def test_cli_status_preflight_and_no_write(tmp_path):
    conn, root = _db(tmp_path, GOOD), _root(tmp_path)
    conn.close()
    db = str(tmp_path / "t.db")
    code, out = run_cli("status", "--db", db, "--root", root)
    assert code == 3 and out["reason"] == "no_record" and out["allowed"] is False
    before = _sha(db)
    code, out = run_cli("ensure-install-id", "--root", root)
    assert code == 0 and out["created"] is True
    code, out = run_cli("preflight", "--db", db, "--root", root)                  # 模擬 backfill ⇒ 會通過
    assert code == 0 and out["allowed"] is True and out["via"] == "upgrade_backfill"
    assert _sha(db) == before, "預檢不可以寫正式庫"
    code, out = run_cli("status", "--db", db, "--root", root)                     # 仍未寫 ⇒ status 仍未設定
    assert code == 3


def test_cli_status_error_is_null_and_exit_2(tmp_path):
    conn, root = _db(tmp_path), _root(tmp_path)
    conn.execute("INSERT INTO system_settings VALUES ('company_profile', '{bad json', 'x')")
    conn.commit()
    conn.close()
    code, out = run_cli("status", "--db", str(tmp_path / "t.db"), "--root", root)
    assert code == 2 and out["configured"] is None and out["reason"] == "status_error"


def test_cli_output_is_utf8_even_on_a_legacy_console(tmp_path):
    """正式機主控台是 cp950：CLI 必須自己輸出 UTF-8（ps1 以 UTF-8 讀），中文訊息不可以變亂碼。"""
    import os
    env = dict(os.environ, PYTHONIOENCODING="cp950")
    r = subprocess.run([sys.executable, str(CLI), "grace", "--root", str(tmp_path), "--hours", "99", "--reason", "x"],
                       capture_output=True, env=env, timeout=60)
    assert json.loads(r.stdout.decode("utf-8"))["error"].startswith("--hours 必須在")


def test_cli_grace_limits(tmp_path):
    conn, root = _db(tmp_path, GOOD), _root(tmp_path)
    conn.close()
    assert run_cli("grace", "--root", root, "--hours", "73", "--reason", "x")[0] == 2
    assert run_cli("grace", "--root", root, "--hours", "72", "--reason", " ")[0] == 2
    code, out = run_cli("grace", "--root", root, "--hours", "72", "--reason", "最高管理員出差")
    assert code == 0
    code, out = run_cli("status", "--db", str(tmp_path / "t.db"), "--root", root)
    assert code == 0 and out["configured"] is False and out["grace"] is True


# ── apply_update.ps1：靜態 ─────────────────────────────────────────────────────

def _ps1():
    return PS1.read_text(encoding="utf-8-sig")


def _param_block(text):
    m = re.search(r"^param\s*\((.*?)^\)", text, re.S | re.M)
    return m.group(1) if m else ""


def skip_preflight_params(text):
    """正式機 ps1 的參數裡「略過預檢」這一類（CG3-M1）：名稱含 skip／bypass／no 且含 preflight／company／gate。"""
    names = re.findall(r"\$([A-Za-z_]\w*)", _param_block(text))
    return [n for n in names if re.search(r"skip|bypass|^no", n, re.I) and re.search(r"preflight|company|gate|setup", n, re.I)]


def test_prod_script_has_no_parameter_to_skip_the_preflight():
    assert _param_block(_ps1()), "找不到 param(...) 區塊（寫法變了 ⇒ 守門失效，改抽取方式）"
    assert skip_preflight_params(_ps1()) == []
    planted = _ps1().replace("param(", "param(\n    [switch]$SkipCompanySetupPreflight,", 1)
    assert skip_preflight_params(planted) == ["SkipCompanySetupPreflight"]         # 正對照


def test_preflight_runs_before_the_service_stops_and_post_check_rolls_back():
    code = "\n".join(l for l in _ps1().splitlines() if not l.lstrip().startswith("#"))
    pre = code.find('@("preflight"')
    first_stop_call = min(i for i in (m.start() for m in re.finditer(r"^\s*\$null = Stop-InstallService|^\s*Stop-InstallService\s*$", code, re.M)))
    assert 0 < pre < first_stop_call, "預檢必須在第一次停服之前"
    assert '"refused_company_setup"' in code and 'Emit-Result "company_setup_rolled_back" 1' in code
    # 結果真的決定行為：$gatePre／$gatePost 來自 Invoke-CompanySetupCli；不允許 ⇒ 拒絕／判成健康檢查失敗
    assert re.search(r'^\s*\$gatePre = Invoke-CompanySetupCli \$gateCli @\("preflight"', code, re.M), "預檢沒有真的呼叫 CLI"
    m = re.search(r"if \(-not \$gatePre\.Allowed\) \{(.*?)\n    \}", code, re.S)
    assert m and '"refused_company_setup"' in m.group(1) and "Fail" in m.group(1), "預檢不允許時沒有拒絕"
    assert re.search(r'^\s*\$gatePost = Invoke-CompanySetupCli .*"status"', code, re.M), "套用後檢查沒有真的呼叫 CLI"
    assert re.search(r"if \(-not \$gatePost\.Allowed\) \{\s*\$companyGateFailed = \$true\s*\$healthy = \$false", code), \
        "套用後檢查不允許時沒有判成健康檢查失敗"
    assert re.search(r"elseif \(\$SkipAutoRollback -and -not \$companyGateFailed\)", code), "-SkipAutoRollback 不可以留下閘門失敗的新版"
    # 預檢用包裡的新版、套用後用安裝目錄的
    assert re.search(r'\$gateCli = Join-Path \$PackagePath "backend\\tools\\company_setup_cli\.py"', code)
    assert re.search(r'Join-Path \$BackendDir "tools\\company_setup_cli\.py"', code)


def test_new_statuses_are_in_the_dashboard_failure_set():
    import importlib.util
    sys.path.insert(0, str(BACKEND / "tools"))
    spec = importlib.util.spec_from_file_location("dd", BACKEND / "tools" / "deploy_dashboard.py")
    dd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dd)
    for s in ("refused_company_setup", "company_setup_rolled_back"):
        assert s in dd._STATUS_FAILED
    emitted = set(re.findall(r'"(refused_company_setup|company_setup_rolled_back)"', _ps1()))
    assert emitted == {"refused_company_setup", "company_setup_rolled_back"}


# ── apply_update.ps1：Invoke-CompanySetupCli 行為（fail closed） ────────────────

def _ps_function(text, name):
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("function %s" % name):
            for j in range(i + 1, len(lines)):
                if lines[j] == "}":
                    return "\n".join(lines[i:j + 1])
    return None


FAKES = {
    "ok": 'print(\'{"allowed": true, "configured": true, "reason": "configured"}\')',
    "not_configured": 'import sys; print(\'{"allowed": false, "configured": false, "reason": "no_record"}\'); sys.exit(3)',
    "null": 'import sys; print(\'{"allowed": false, "configured": null, "reason": "status_error"}\'); sys.exit(2)',
    # 結束碼 0、allowed 也寫 true，但 configured 是 null（判定失敗）⇒ 仍不可以放行（CG2-S3：null＝拒絕）
    "null_exit0": 'print(\'{"allowed": true, "configured": null, "reason": "status_error"}\')',
    "lying_exit": 'import sys; print(\'{"allowed": true, "configured": true, "reason": "configured"}\'); sys.exit(1)',
    "bad_output": 'print("Traceback: something")',
    "crash": 'raise SystemExit(9)',
    "slow": 'import time; time.sleep(30); print(\'{"allowed": true, "configured": true}\')',
}


@pytest.mark.skipif(sys.platform != "win32", reason="apply_update.ps1 只在 Windows 正式機執行")
@pytest.mark.parametrize("case,allowed,reason", [
    ("ok", True, "configured"), ("not_configured", False, "no_record"), ("null", False, "status_error"),
    ("null_exit0", False, "status_error"),
    ("lying_exit", False, "configured"), ("bad_output", False, "bad_output"), ("crash", False, "bad_output"),
    ("slow", False, "timeout"), ("missing", False, "tool_missing"),
])
def test_invoke_company_setup_cli_fails_closed(tmp_path, case, allowed, reason):
    fn = _ps_function(_ps1(), "Invoke-CompanySetupCli")
    assert fn, "找不到 Invoke-CompanySetupCli"
    fake = tmp_path / ("fake_%s.py" % case)
    if case != "missing":
        fake.write_text(FAKES[case], encoding="utf-8")
    script = tmp_path / "t.ps1"
    script.write_text("$ErrorActionPreference = 'Stop'\n" + fn + "\n"
                      "$r = Invoke-CompanySetupCli '%s' @('status', '--db', 'x') 3\n"
                      "Write-Output (\"RESULT allowed=\" + $r.Allowed + \" reason=\" + $r.Reason)\n" % fake,
                      encoding="utf-8-sig")
    env = dict(__import__("os").environ)
    env["PATH"] = str(Path(sys.executable).parent) + ";" + env.get("PATH", "")      # python ＝ 本 venv
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90, env=env)
    line = [l for l in r.stdout.splitlines() if l.startswith("RESULT")]
    assert line, r.stdout + r.stderr
    assert line[-1] == "RESULT allowed=%s reason=%s" % (allowed, reason), line[-1]


# ── CG2-M1：三個安裝設定檔在刪除計畫／執行／cleanup／快照外清理之後逐位元組不變 ──

GATE_FILES = ("backend/.install_identity", "backend/company_confirmation.sig", "backend/company_setup_grace.json")


def test_gate_files_survive_apply_plan_execute_and_cleanups(tmp_path):
    import importlib.util
    import json as _json
    from core import upgrade as _upgrade
    spec = importlib.util.spec_from_file_location("apply_plan_cg", BACKEND / "tools" / "apply_plan.py")
    ap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ap)
    ap._upgrade = _upgrade
    ap._license_check = lambda manifest: (True, "")
    pkg, root = tmp_path / "pkg", tmp_path / "root"

    def w(base, rel, text):
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    for rel in ("backend/main.py", "backend/brand_new.py"):
        w(pkg, rel, "new")
    w(pkg, "deploy_manifest.json", _json.dumps({"commit": "c2"}))
    w(pkg, "backend/modules.lock.json", _json.dumps({"lock_version": 1, "kind": "full_package", "product": "t",
                                                       "modules": {}, "excluded": [], "removed_pages": []}))
    w(root, "backend/main.py", "old")
    for rel in GATE_FILES:
        w(root, rel, "gate-" + rel)
    # 惡意／錯誤 baseline：把三檔列成「上一版的程式」
    w(root, ap.BASELINE_REL, _json.dumps({"commit": "c1", "files": ["backend/main.py", *GATE_FILES]}))
    before = {rel: _sha(root / rel) for rel in GATE_FILES}
    plan = ap.make_plan(str(root), str(pkg), 200)
    listed = {d["path"] if isinstance(d, dict) else d for d in plan["delete"]}
    assert not (listed & set(GATE_FILES)), listed
    ap.execute(str(root), str(pkg), plan)
    ap.cleanup_added(str(root), str(pkg), plan)
    snap = tmp_path / "snap"
    (snap / "backend").mkdir(parents=True)
    ap.cleanup_not_in_snapshot(str(root), str(pkg), str(snap), max_files=500)
    assert {rel: _sha(root / rel) for rel in GATE_FILES} == before
    for rel in GATE_FILES:
        assert _upgrade.classify(rel) == "config"
