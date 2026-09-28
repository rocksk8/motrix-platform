# -*- coding: utf-8 -*-
"""backend/tools/apply_module_update.ps1（B55 單一模組更新包 §1.3；S5）的靜態守門。

照 test_apply_plan 的做法（函式本體逐項驗、逐字比對、值域雙向）：
① DB-S1＝U-M1②：共用函式與 apply_update.ps1 逐字相同（改一個字元 ⇒ 紅）；Emit-Result 只多「補模組欄位」那一行；
   server.log 掃描核心逐字相同；$ProdRoot／$Port 與 apply_update 相同、沒有演練繞過分支。
② 順序：鎖 → 預檢 → DB 快照 → 乾跑（疊加樹，finally 刪）→ 停服 → 換檔 → 重啟 → 健檢（ping＋載入狀態＋log）；
   回滾：停服 → 模組回滾 → DB 另存再寫回 → 重啟；F13 先停用模組才重啟、停用失敗不重啟。
③ status 全在儀表板值域；設計 §2 的新 status 都有出口；每個 Fail 都給了 status（不靠預設 unknown）。
④ AH-O7：腳本內容雜湊與 apply_module_update.version.json 一致。
"""
import hashlib
import json
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import pytest

_TOOLS = Path(__file__).resolve().parents[2] / "tools"
NEW = "apply_module_update.ps1"
SHARED = ("Test-Ping", "Fail", "Info", "Warn", "Ok", "Enter-InstallLock", "Exit-InstallLock", "Write-ResultFile",
          "Backup-DatabasesOnline", "Invoke-Py", "Stop-InstallService", "Start-InstallService", "Get-StartupRange")
NEW_STATUSES = {"module_preflight_failed", "module_load_dryrun_failed", "module_copy_failed",
                "module_unhealthy_rolled_back", "module_restore_failed"}


def _src(name):
    return (_TOOLS / name).read_text(encoding="utf-8-sig").replace("\r\n", "\n")


def _fn(text, name):
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("function %s" % name) and (len(line) == len("function %s" % name) or line[len("function %s" % name)] in " ("):
            if line.rstrip().endswith("}"):
                return line
            for j in range(i + 1, len(lines)):
                if lines[j] == "}":
                    return "\n".join(lines[i:j + 1])
    return None


def _code(text):
    return "\n".join(l for l in text.split("\n") if not l.lstrip().startswith("#"))


# ── ① 逐字 ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", SHARED)
def test_shared_functions_are_verbatim_copies_of_apply_update(name):
    a, n = _fn(_src("apply_update.ps1"), name), _fn(_src(NEW), name)
    assert a is not None and n is not None, "%s 在其中一支找不到（改名要兩邊一起改）" % name
    assert a == n, "%s：apply_module_update.ps1 與 apply_update.ps1 不同步（DB-S1 逐字複製）" % name


def test_emit_result_differs_only_by_the_module_fields_line():
    a, n = _fn(_src("apply_update.ps1"), "Emit-Result"), _fn(_src(NEW), "Emit-Result")
    assert "    Add-ModuleResultFields" in n.split("\n")
    assert a == "\n".join(l for l in n.split("\n") if l != "    Add-ModuleResultFields")


def test_log_scan_core_is_verbatim():
    start = "    $cleanedLines = New-Object System.Collections.Generic.List[string]"
    end = '    $logErrors = $cleanedLines | Select-String -Pattern "Traceback|ERROR" -SimpleMatch:$false'

    def seg(t):
        i = t.index(start)
        return t[i:t.index(end, i) + len(end)]
    assert seg(_src("apply_update.ps1")) == seg(_src(NEW))


def test_prod_root_and_port_are_the_same_lines_and_there_is_no_bypass():
    a, n = _src("apply_update.ps1"), _src(NEW)
    for pat in (r'^\$ProdRoot = .*$', r'^\$Port = .*$'):
        assert re.search(pat, a, re.M).group(0) == re.search(pat, n, re.M).group(0)
    code = _code(n)
    assert "$env:MOTRIX" not in code, "不可以用環境變數改正式機路徑（演練走複製改寫兩行，§7）"
    assert not re.search(r"\[string\]\$ProdRoot|\[int\]\$Port", code), "不可以把正式機路徑／port 做成參數"


def test_rc_the_extractor_sees_a_one_character_drift():
    n = _src(NEW)
    fa = _fn(n, "Stop-InstallService")
    assert fa and _fn(n.replace("$hops -lt 6", "$hops -lt 7", 1), "Stop-InstallService") != fa


# ── ② 順序 ──────────────────────────────────────────────────────────────

def _split_rollback(code):
    """（套用那一條, 回滾模式那一段）：回滾模式是 `if ($Rollback) {` 到下一個第 0 欄的 `}`（B55F-M1）。"""
    i = code.index("\nif ($Rollback) {\n") + 1
    j = code.index("\n}\n", i) + 3
    return code[:i] + code[j:], code[i:j]


def _main_flow():
    """套用那一條（不含回滾模式那一段）。"""
    code = _code(_src(NEW))
    return _split_rollback(code[code.index('Write-Host "::PROTOCOL:: v=2"'):])[0]


def _rollback_flow():
    code = _code(_src(NEW))
    return _split_rollback(code[code.index('Write-Host "::PROTOCOL:: v=2"'):])[1]


def test_main_flow_order():
    m = _main_flow()
    marks = ["Enter-InstallLock", '"preflight"', "Backup-DatabasesOnline $dbSnapDir", '"overlay"',
             "--expect-module", "Stop-InstallService", '"apply"', "Start-InstallService", "Test-ModuleHealth"]
    idx = [m.index(x) for x in marks]
    assert idx == sorted(idx), list(zip(marks, idx))


def test_dry_run_temp_trees_are_removed_in_finally():
    m = _main_flow()
    seg = m[m.index('"overlay"'):m.index("Stop-InstallService")]
    fin = seg[seg.index("} finally {"):]
    assert "Remove-Item $ovDir -Recurse" in fin and "Remove-Item $ovDbDir -Recurse" in fin


def test_auto_rollback_order():
    m = _main_flow()
    rb = m[m.index('Info "[7/7] 自動回滾..."'):]
    marks = ["Stop-InstallService", "Invoke-ModuleRollback", "Restore-Databases $dbSnapDir", "Start-InstallService"]
    idx = [rb.index(x) for x in marks]
    assert idx == sorted(idx), list(zip(marks, idx))


def test_db_restore_saves_pre_rollback_before_overwriting():
    f = _fn(_src(NEW), "Restore-Databases")
    assert f.index("Backup-DatabasesOnline") < f.index("Copy-Item $snap $dst")
    assert "return $false" in f[:f.index("Copy-Item $snap $dst")], "另存失敗 ⇒ 不覆寫"


def test_f13_disables_the_module_before_restarting_and_does_not_restart_when_disable_fails():
    f = _fn(_src(NEW), "Fail-DisableModule")
    assert f.index('"disable"') < f.index("Start-InstallService"), "先停用才重啟（DB-S5）"
    fail_idx = f.index('"module_restore_failed"')
    assert fail_idx < f.index("Start-InstallService"), "停用寫入失敗的出口在重啟之前（不重啟）"
    assert 'Wait-ModuleState $script:ModuleKey $null "disabled"' in f
    # 兩個出口（停用失敗不重啟／停用後重啟）都是 module_restore_failed（突變 S4：只改第二個曾經沒被抓到）
    exits = re.findall(r'Fail\s+".*?"\s+"([a-z_]+)"', f, re.S)
    assert len(exits) == 2 and set(exits) == {"module_restore_failed"}, exits


def test_health_check_has_both_layers_beyond_ping():
    f = _fn(_src(NEW), "Test-ModuleHealth")
    assert f.index("Test-Ping") < f.index('Wait-ModuleState $key $version "loaded"') < f.index("Get-LogCheck")


def test_rollback_passes_this_run_stamp():
    n = _code(_src(NEW))
    assert '"--stamp", $script:ModStamp' in n
    assert '"--backup", $script:ModStamp' in _fn(_src(NEW), "Invoke-ModuleRollback")


# ── ③ status ────────────────────────────────────────────────────────────

def _dashboard_domain():
    import ast
    tree = ast.parse((_TOOLS / "deploy_dashboard.py").read_text(encoding="utf-8"))
    domain = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") in ("_STATUS_SUCCEEDED", "_STATUS_FAILED")
                                                for t in node.targets):
            domain |= {c.value for c in ast.walk(node.value) if isinstance(c, ast.Constant) and isinstance(c.value, str)}
    return domain


def _statuses():
    code = _code(_src(NEW))
    # Fail／Emit-Result 的字面 status，加上「$變數 = if (…) { "a" } else { "b" }」再交給 Fail 的那兩處
    lit = set(re.findall(r'(?:Fail\s+.*?|Emit-Result\s+)"([a-z_]+)"', code))
    for line in code.split("\n"):
        if re.match(r'\s*\$(?:failStatus|st) = if ', line):
            lit |= set(re.findall(r'\{ "([a-z_]+)" \}', line))
    m = re.search(r'^\$PreflightStatus = @\{(.*?)\}', code, re.M)
    lit |= set(re.findall(r'= "([a-z_]+)"', m.group(1)))       # 預檢 code 對照表的值（交給 Fail 的 status）
    return lit


def test_every_status_is_in_the_dashboard_domain_and_every_new_one_has_an_exit():
    domain, st = _dashboard_domain(), _statuses()
    assert {"success", "unhandled_exception"} <= st and len(st) >= 12, sorted(st)
    pending = set() if _e4_merged() else E4_STATUSES      # E4 合回前那兩個由 E4 自己加進值域（見 ⑥）
    assert not (st - domain - pending), sorted(st - domain - pending)
    assert NEW_STATUSES <= st, "設計 §2 的新 status 沒有出口：%s" % sorted(NEW_STATUSES - st)
    assert NEW_STATUSES <= domain
    assert "made_up_status" not in domain                          # 反向控制


def test_every_fail_call_names_its_status():
    code = _code(_src(NEW))
    body = code[code.index("function Fail-DisableModule"):]
    bad = [l.strip() for l in body.split("\n")
           if re.match(r'\s*(if .*\{\s*)?Fail\s+"', l) and not re.search(r'"\s+(\$[a-zA-Z]+|"[a-z_]+")\s*\}?\s*$', l)]
    assert not bad, "Fail 沒給 status（會變 unknown）：%s" % bad


# ── ④ 版本登記 ──────────────────────────────────────────────────────────

def test_script_change_requires_a_version_decision():
    reg = json.loads((_TOOLS / "apply_module_update.version.json").read_text(encoding="utf-8"))
    raw = (_TOOLS / NEW).read_bytes()
    code = raw.decode("utf-8-sig")
    m = re.search(r'^\$ApplyModuleScriptVersion = "([^"]+)"', code, re.M)
    assert m and m.group(1) == reg["version"]
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    digest = hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()
    assert digest == reg["sha256"], "apply_module_update.ps1 內容變了：更新 version.json 的 sha256 成 %s" % digest


@pytest.mark.skipif(not shutil.which("powershell"), reason="沒有 Windows PowerShell")
def test_script_parses_without_errors():
    ps = ("$e=$null;$t=$null;[void][System.Management.Automation.Language.Parser]::ParseFile('%s',[ref]$t,[ref]$e);"
          "Write-Output $e.Count") % str(_TOOLS / NEW)
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=120)
    assert r.stdout.strip().splitlines()[-1] == "0", r.stdout + r.stderr


# ── ⑤ 與 module_update.py --json 的 code 表對齊（B，MODULE-UPDATE-DELIVERY §10）──
# 稽核 D S5A-M1：原本這裡手抄一份 §10 的 code（B 18e66f7b），B 後來加的 code 沒跟上 ⇒ 自動回滾遇到時服務停著。
# 根治：code 一律從 §10 表抓（B 的 test_every_code_is_documented_for_the_ps1 釘住「程式每個 code 都在表上」），
# 這裡釘反向：「表上每個 code 在 ps1 恰好屬於一組處置」——缺、多、重複都紅，不再手抄。

S10_DOC = Path(__file__).resolve().parents[3] / "docs" / "platform" / "MODULE-UPDATE-DELIVERY.md"
B55_WAIT = ("等 B55 合回（wip/b-module-delivery-2）：本樹還沒有 MODULE-UPDATE-DELIVERY.md ⇒ §10 對照在合回那一班生效"
            "（合回那一班的列車長要確認這幾格是 passed，不是 skip）")
#: ps1 的四組處置（apply_module_update.ps1 開頭）
GROUPS = ("ApplyUntouchedCodes", "ApplyInFlightCodes", "RestoreFailedCodes", "RollbackRefusedCodes")


def _parse_s10(text):
    """§10 的 code 值域表：`## 10.` 到下一個 `## ` 之間，第一欄是 `code` 的列。"""
    i = text.index("\n## 10.")
    j = text.find("\n## ", i + 1)
    sec = text[i:j if j > 0 else len(text)]
    return set(re.findall(r"^\|\s*`([a-z_]+)`\s*\|", sec, re.M))


def _s10_codes():
    if not S10_DOC.exists():
        pytest.skip(B55_WAIT)
    return _parse_s10(S10_DOC.read_text(encoding="utf-8"))


def _ps_list(name):
    code = _code(_src(NEW))
    m = re.search(r'^\$%s = @\((.*?)\)' % name, code, re.M | re.S)
    assert m, "ps1 沒有 $%s" % name
    return set(re.findall(r'"([a-z_]+)"', m.group(1)))


def _groups():
    return {g: _ps_list(g) for g in GROUPS}


def _disposition_problems(codes, groups):
    n = Counter(c for g in groups.values() for c in g)
    dup = sorted(c for c, k in n.items() if k > 1)
    handled = set(n)
    return {"missing": sorted(codes - handled), "extra": sorted(handled - codes), "dup": dup}


def test_s10_parser_sees_known_codes():
    """正對照：抓得到表頭之後的列、抓得到最後加的那幾個（抓不到 ⇒ 下面的比對是空的在比）。"""
    codes = _s10_codes()
    assert {"pkg_invalid", "backup_corrupt", "interrupted_apply_pending", "interrupted_not_latest", "unexpected"} <= codes, sorted(codes)
    assert len(codes) >= 20, sorted(codes)


def test_every_s10_code_has_exactly_one_disposition():
    problems = _disposition_problems(_s10_codes(), _groups())
    assert problems == {"missing": [], "extra": [], "dup": []}, (
        "§10 的 code 與 ps1 的四組處置（%s）不一致：%s ⇒ 在 apply_module_update.ps1 開頭把 code 歸到一組" % (", ".join(GROUPS), problems))


def test_reverse_control_a_new_s10_code_is_caught():
    """反向控制：§10 多一列 ⇒ 比對抓得到（題目不是對什麼都綠）；同一個 code 放兩組 ⇒ 抓得到。"""
    doc = ("# x\n\n## 10. 輸出\n\n| code | 子命令 | 意思 | ps1 |\n|---|---|---|---|\n"
           "| `backup_corrupt` | rollback | 壞 | F13 |\n| `brand_new_code` | apply | 新 | ? |\n\n## 11. 下一節\n| `not_this` | x |\n")
    codes = _parse_s10(doc)
    assert codes == {"backup_corrupt", "brand_new_code"}
    groups = {"A": {"backup_corrupt"}, "B": {"backup_corrupt"}}
    assert _disposition_problems(codes, groups) == {"missing": ["brand_new_code"], "extra": [], "dup": ["backup_corrupt"]}


def test_s5a_m1_rollback_refusals_disable_the_module_instead_of_leaving_the_service_down():
    """D S5A-M1：「回滾拒絕、一檔不動」⇒ 與 F13 同：停用模組再重啟；apply 回 interrupted_apply_pending ⇒ 沒動檔。"""
    g = _groups()
    assert {"module_changed", "state_changed", "base_changed", "interrupted_not_latest"} <= g["RollbackRefusedCodes"]
    assert "interrupted_apply_pending" in g["ApplyUntouchedCodes"]
    rb = _fn(_src(NEW), "Invoke-ModuleRollback")
    assert "($RestoreFailedCodes + $RollbackRefusedCodes) -contains $code" in rb
    assert "$script:RollbackCode = $code" in rb
    m = _code(_src(NEW))
    assert m.count("if ($rb.NeedsDisable) { Fail-DisableModule $rb.Code }") == 2, "F9 與自動回滾兩處"
    assert "rollback_code" in _fn(_src(NEW), "Add-ModuleResultFields"), "結果檔帶回滾的 code"


def test_apply_refused_before_touching_restarts_the_service_before_failing():
    m = _main_flow()
    seg = m[m.index("if ($ApplyUntouchedCodes -contains $apCode)"):]
    seg = seg[:seg.index("Fail ")]
    assert "Start-InstallService" in seg and '$script:ProdState = "not_applied"' in seg


def test_apply_failed_restored_skips_the_second_rollback():
    m = _main_flow()
    i = m.index('if ($apCode -ne "apply_failed_restored")')
    assert i < m.index("$rb = Invoke-ModuleRollback", i)


# ── ⑥ E4 本公司資料設定閘門（wip/e-company-gate-impl db551e01；主持裁示：兩道＋逐字）──

E4_WAIT = "等 E4 合回（wip/e-company-gate-impl）：apply_update.ps1 還沒有 Invoke-CompanySetupCli，逐字比對在合回那一班生效"
E4_STATUSES = {"refused_company_setup", "company_setup_rolled_back"}


def _e4_merged():
    return _fn(_src("apply_update.ps1"), "Invoke-CompanySetupCli") is not None


def test_company_setup_cli_is_present_in_the_module_script():
    """不論 E4 合回與否，模組腳本都要有它（apply_update 有而模組腳本沒有 ⇒ 紅，不是 skip）。"""
    assert _fn(_src(NEW), "Invoke-CompanySetupCli") is not None


def test_company_setup_cli_is_verbatim_once_e4_is_merged():
    if not _e4_merged():
        pytest.skip(E4_WAIT)
    assert _fn(_src("apply_update.ps1"), "Invoke-CompanySetupCli") == _fn(_src(NEW), "Invoke-CompanySetupCli")


def test_company_gate_call_sites_and_order():
    m = _main_flow()
    pre = m.index('Invoke-CompanySetupCli $gateCli @("preflight"')
    assert m.index('"ensure-install-id"') < pre < m.index("Backup-DatabasesOnline $dbSnapDir") < m.index("Stop-InstallService")
    post = m.index('Invoke-CompanySetupCli $gateCli @("status"')
    assert m.index("Test-ModuleHealth $script:ModuleKey $script:ToVersion") < post < m.index('Emit-Result "success" 0')
    assert "if ($SkipAutoRollback -and -not $companyGateFailed)" in m, "閘門失敗不適用 -SkipAutoRollback"
    assert '"company_setup_rolled_back"' in m and '"refused_company_setup"' in m
    assert r'$gateCli = Join-Path $BackendDir "tools\company_setup_cli.py"' in m, "模組包不帶 tools ⇒ 用安裝目錄那份"


def test_e4_statuses_are_in_the_domain_once_e4_is_merged():
    domain = _dashboard_domain()
    if not (E4_STATUSES <= domain):
        assert not _e4_merged(), "apply_update 已有 Invoke-CompanySetupCli（E4 已合回）而儀表板值域沒有 %s" % sorted(E4_STATUSES - domain)
        pytest.skip(E4_WAIT)
    assert E4_STATUSES <= _statuses()


# ── ⑦ 模組載入字串：本次啟動那一段、UTF-8（B 演練 A：已載入早於 Uvicorn running on；PS 5.1 預設 ANSI 讀）──

_PS = shutil.which("powershell.exe") or shutil.which("powershell")


def _log_check(tmp_path, lines, key="tender_radar", version="1.3.4"):
    """實際執行模組 ps1 的 Get-LogCheck（連同逐字共用的 Get-StartupRange），對一份 UTF-8 無 BOM 的 server.log。"""
    if not _PS:
        pytest.skip("需要 Windows PowerShell")
    (tmp_path / "logs").mkdir(exist_ok=True)
    (tmp_path / "logs" / "server.log").write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))
    text = _src(NEW)
    body = "\n".join([
        "$ErrorActionPreference = 'Stop'",
        "function Info($msg) { }",
        _fn(text, "Get-StartupRange"),
        _fn(text, "Get-LogCheck"),
        "$BackendDir = '%s'" % str(tmp_path).replace("'", "''"),
        "$lc = Get-LogCheck '%s' '%s'" % (key, version),
        "Write-Output ('RESULT ' + (@{ loaded = [bool]$lc.Loaded; not_loaded = [bool]$lc.NotLoaded; boot = [bool]$lc.Boot;"
        " errors = @($lc.Errors).Count } | ConvertTo-Json -Compress))",
    ])
    script = tmp_path / "harness.ps1"
    script.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
    r = subprocess.run([_PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)], capture_output=True, timeout=60)
    out = r.stdout.decode("utf-8", "replace")
    line = [l for l in out.splitlines() if l.startswith("RESULT ")]
    assert r.returncode == 0 and line, (out, r.stderr.decode("utf-8", "replace"))
    return json.loads(line[-1][len("RESULT "):])


def _boot(ver, loaded=True):
    return (["[2026/09/28 週一 21:57:15.20] MOTRIX ERP starting... "]
            + (["INFO:core.loader:模組 tender_radar %s 已載入" % ver] if loaded else ["INFO:core.loader:模組 tender_radar 未載入：壞了"])
            + ["INFO:     Started server process [4242]", "INFO:     Application startup complete.",
               "INFO:     Uvicorn running on https://0.0.0.0:666 (Press CTRL+C to quit)",
               'INFO:     127.0.0.1:50001 - "GET /api/ping HTTP/1.1" 200 OK'])


_STOPPED = ["[2026/09/28 週一 21:57:10.12] MOTRIX ERP stopped (exit code 1). restart in 5s... "]


def test_loaded_line_before_uvicorn_running_counts_as_loaded(tmp_path):
    """B 演練 A 的真實順序：「已載入」在 Uvicorn running on 之前 ⇒ 判載入（舊碼：ANSI 讀 ⇒ 判沒載入而自動回滾）。"""
    d = _log_check(tmp_path, _boot("1.3.3") + _STOPPED + _boot("1.3.4"))
    assert d == {"loaded": True, "not_loaded": False, "boot": True, "errors": 0}, d


def test_reverse_control_this_start_without_the_loaded_line_is_not_loaded(tmp_path):
    d = _log_check(tmp_path, _boot("1.3.3") + _STOPPED + _boot("1.3.4", loaded=False))
    assert d["loaded"] is False and d["not_loaded"] is True, d


def test_rollback_check_does_not_see_the_previous_process_line(tmp_path):
    """回滾後查舊版本 1.3.3：上一個行程（套用前）印過「1.3.3 已載入」，這次啟動沒有 ⇒ 不可以判載入（整段 tail 會假綠）。"""
    d = _log_check(tmp_path, _boot("1.3.3") + _STOPPED + _boot("1.3.4"), version="1.3.3")
    assert d["loaded"] is False, d


def test_no_start_marker_is_cannot_verify(tmp_path):
    d = _log_check(tmp_path, [l for l in _boot("1.3.4") if "MOTRIX ERP starting" not in l])
    assert d["boot"] is False and d["loaded"] is False, d
    h = _fn(_src(NEW), "Test-ModuleHealth")
    assert h.index("if (-not $lc.Boot)") < h.index("if ($lc.NotLoaded -or -not $lc.Loaded)")
