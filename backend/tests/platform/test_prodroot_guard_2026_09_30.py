# -*- coding: utf-8 -*-
"""部署腳本的安裝目錄守門（docs/platform/PRODROOT-GUARD-DESIGN.md）：三路徑演練＋反向控制。真的用 Windows PowerShell 5.1 執行腳本。

- p1 自用（own）：腳本原樣；在別的目錄執行 ⇒ 被寫死路徑守門擋下（`not_prod_machine`）；演練慣例（只改寫 $ProdRoot／$Port 兩行）⇒ 放行。
- p2 客戶（sale，剪段後的腳本）：由腳本位置推得安裝目錄，守門 = 有 .install_identity、無 .git、無開發／演練標記、.install_port 合法。
- p3 過渡／不變：own 腳本相對加標記之前的版本，去掉新增的標記與說明行後逐字相同（行為不變的證明）。
結果看腳本印出的 `::RESULT:: … status=…`：守門擋下 ⇒ not_prod_machine／rollback_not_prod_machine；放行 ⇒ 後面別的狀態（本題不關心）。
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
import deid_project as P  # noqa: E402

PS = shutil.which("powershell.exe") or shutil.which("powershell")
pytestmark = pytest.mark.skipif(not PS, reason="需要 Windows PowerShell（部署腳本只在 Windows 上跑）")
CFG = P.load_config()
TOOLS = REPO / "backend" / "tools"
SCRIPTS = {  # 腳本 ⇒ (額外參數, 守門擋下時的狀態)
    "apply_update.ps1": (["-CheckOnly", "-Yes"], "not_prod_machine"),
    "rollback_update.ps1": (["-SnapshotTimestamp", "20200101_000000", "-Yes"], "rollback_not_prod_machine"),
    "apply_module_update.ps1": (["-PackagePath", "C:\\nope", "-Yes"], "not_prod_machine"),
}


def _install(tmp_path, sale, name="inst"):
    """在 tmp 建 <根>\\backend\\tools\\，放腳本（sale ⇒ 套用剪段）＋ _install_root.ps1。"""
    root = tmp_path / name
    tools = root / "backend" / "tools"
    tools.mkdir(parents=True)
    for fn in list(SCRIPTS) + ["_install_root.ps1"]:
        shutil.copyfile(TOOLS / fn, tools / fn)
    if sale:
        cuts = [c for c in CFG["cuts"] if c["path"].startswith("backend/tools/") and c["path"].endswith(tuple(SCRIPTS))]
        # apply_cuts 用「相對包根」的路徑
        P.apply_cuts(root, cuts)
    return root


def _identity(root):
    (root / "backend" / ".install_identity").write_text("x", encoding="utf-8")


def _run(root, script):
    extra, _blocked = SCRIPTS[script]
    r = subprocess.run([PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(root / "backend" / "tools" / script), *extra],
                       capture_output=True, timeout=180, cwd=str(root))
    out = (r.stdout + r.stderr).decode("utf-8", "replace")
    m = re.findall(r"::RESULT:: v=2 status=(\S+)", out)
    return (m[-1] if m else None), out


def _blocked(status, script):
    return status == SCRIPTS[script][1]


# ── p2 客戶（sale） ─────────────────────────────────────────────────────────────────

def test_p2_a_customer_install_passes_the_guard_for_all_three_scripts(tmp_path):
    root = _install(tmp_path, sale=True)
    _identity(root)
    for script in SCRIPTS:
        status, out = _run(root, script)
        assert status and not _blocked(status, script), (script, status, out[-300:])


@pytest.mark.parametrize("script", list(SCRIPTS))
def test_p2_reverse_controls_each_refusal_reason(tmp_path, script):
    cases = {
        "no_identity": lambda r: None,
        "git_dir": lambda r: (_identity(r), (r / ".git").mkdir()),
        "backend_git": lambda r: (_identity(r), (r / "backend" / ".git").mkdir()),
        "no_email_send": lambda r: (_identity(r), (r / ".no_email_send").write_text("x")),
        "no_cloud_archive": lambda r: (_identity(r), (r / ".no_cloud_archive").write_text("x")),
        "bad_port_text": lambda r: (_identity(r), (r / "backend" / ".install_port").write_text("66x6")),
        "port_zero": lambda r: (_identity(r), (r / "backend" / ".install_port").write_text("0")),
        "port_too_big": lambda r: (_identity(r), (r / "backend" / ".install_port").write_text("70000")),
    }
    for name, setup in cases.items():
        root = _install(tmp_path, sale=True, name="i_" + name)
        setup(root)
        status, out = _run(root, script)
        assert _blocked(status, script), (name, script, status, out[-300:])


def test_p2_a_good_install_port_file_is_accepted(tmp_path):
    root = _install(tmp_path, sale=True)
    _identity(root)
    (root / "backend" / ".install_port").write_text("6766\n", encoding="utf-8")
    status, out = _run(root, "apply_update.ps1")
    assert not _blocked(status, "apply_update.ps1"), out[-300:]
    assert "6766" in out, "健康檢查網址應該用 .install_port 的埠"


def test_p2_helper_returns_root_port_and_error_as_documented(tmp_path):
    root = tmp_path / "h"
    (root / "backend" / "tools").mkdir(parents=True)
    shutil.copyfile(TOOLS / "_install_root.ps1", root / "backend" / "tools" / "_install_root.ps1")
    (root / "backend" / ".install_identity").write_text("x")
    cmd = ". '%s'; $r = Resolve-InstallRoot '%s'; Write-Output ('ROOT=' + $r.Root); Write-Output ('PORT=' + $r.Port); Write-Output ('ERR=' + $r.Error)" % (
        root / "backend" / "tools" / "_install_root.ps1", root / "backend" / "tools")
    out = subprocess.run([PS, "-NoProfile", "-Command", cmd], capture_output=True, timeout=60).stdout.decode("utf-8", "replace")
    lines = [ln.strip() for ln in out.strip().splitlines()]
    assert "ROOT=" + str(root) in lines and "PORT=666" in lines and lines[-1] == "ERR=", lines


# ── p1 自用（own） ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("script", list(SCRIPTS))
def test_p1_own_scripts_still_refuse_a_directory_that_is_not_the_hardcoded_install(tmp_path, script):
    root = _install(tmp_path, sale=False)
    _identity(root)                                   # 就算條件都對，寫死路徑的守門照擋
    status, out = _run(root, script)
    assert _blocked(status, script), (script, status, out[-300:])


@pytest.mark.parametrize("script", list(SCRIPTS))
def test_p1_own_drill_convention_two_line_rewrite_still_passes(tmp_path, script):
    root = _install(tmp_path, sale=False)
    p = root / "backend" / "tools" / script
    raw = p.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    new, changed = _rewrite(text, root)
    assert len(changed) == 2
    p.write_bytes((b"\xef\xbb\xbf" if bom else b"") + new.encode("utf-8"))
    status, out = _run(root, script)
    assert status and not _blocked(status, script), (script, status, out[-300:])


def _rewrite(text, root):
    """與 tools/platform/drill_module_apply.rewrite_ps1 相同的慣例：只改 $ProdRoot／$Port 兩行。"""
    import drill_module_apply as DR
    return DR.rewrite_ps1(text, root, 6755)


# ── p3 不變 ────────────────────────────────────────────────────────────────────────

MARKED = ["backend/tools/apply_update.ps1", "backend/tools/rollback_update.ps1", "backend/tools/apply_module_update.ps1", "backend/setup_autostart_task.ps1"]


def _strip_markers(text):
    out = []
    for ln in text.split("\n"):
        s = ln.strip("\r")
        if s.startswith(("# >>> OWN-ONLY:", "# <<< OWN-ONLY:")) or s.startswith("# 去識別化（sale 包）：下面這段是本公司安裝的寫死路徑"):
            continue
        out.append(ln)
    return "\n".join(out)


@pytest.mark.parametrize("rel", MARKED)
def test_p3_own_scripts_equal_the_pre_marker_blob_once_markers_are_stripped(rel):
    base = "dc948c89"           # 加標記之前的提交（wip/w3-deid-s4）
    r = subprocess.run(["git", "-C", str(REPO), "show", "%s:%s" % (base, rel)], capture_output=True)
    if r.returncode != 0:
        pytest.skip("這棵樹沒有基準提交 %s（淺 clone？）" % base)
    old = r.stdout.decode("utf-8-sig").replace("\r\n", "\n")
    now = (REPO / rel).read_bytes().decode("utf-8-sig").replace("\r\n", "\n")
    assert _strip_markers(now) == old, "%s：除了 OWN-ONLY 標記與說明行，自用腳本不可以有任何差異" % rel


def test_every_marked_region_is_cut_in_the_sale_config_and_nothing_else_is_marked():
    cut_keys = {(c["path"], c["name"]) for c in CFG["cuts"]}
    for rel in MARKED:
        text = (REPO / rel).read_text(encoding="utf-8-sig")
        names = re.findall(r"# >>> OWN-ONLY:(\S+)", text)
        assert names and all((rel, n) in cut_keys for n in names), (rel, names)


def test_sale_scripts_no_longer_contain_the_hardcoded_install_path(tmp_path):
    root = _install(tmp_path, sale=True)
    for fn in SCRIPTS:
        text = (root / "backend" / "tools" / fn).read_text(encoding="utf-8-sig")
        assert "C:\\Users\\Motrix" not in text and "OWN-ONLY" not in text, fn
