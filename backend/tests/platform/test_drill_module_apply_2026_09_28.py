"""B55 S6：演練工具 tools/platform/drill_module_apply.py 的純邏輯（不起服務、不跑 ps1）。

- 演練副本只改寫 $ProdRoot／$Port 兩行（稽核 D DB-S2）；多一行、少一行、找不到 ⇒ 拒絕
- 演練 B／C 的模組改動：B 只有「uvicorn 已載入」才丟例外（乾跑載得起來）；C 多一支回未完成原因的 migration
"""
import ast
import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("_drill_b55", REPO / "tools" / "platform" / "drill_module_apply.py")
DR = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(DR)

PS1 = '''# apply_module_update
$ApplyModuleScriptVersion = "2026-09-28a"
$ProdRoot = "C:\\Users\\Motrix\\Desktop\\V9.0"
$Port = 666
$AutostartTaskName = "MOTRIX ERP Server Autostart"
Write-Host "x"
'''


def test_rewrite_changes_only_two_lines():
    new, changed = DR.rewrite_ps1(PS1, r"C:\T\motrix-drill-b55\x\install", 6755)
    assert len(changed) == 2
    assert '$ProdRoot = "C:\\T\\motrix-drill-b55\\x\\install"' in new and "$Port = 6755" in new
    diff = [(a, b) for a, b in zip(PS1.splitlines(), new.splitlines()) if a != b]
    assert len(diff) == 2 and all(a.startswith(("$ProdRoot", "$Port")) for a, _ in diff)
    assert '$AutostartTaskName = "MOTRIX ERP Server Autostart"' in new, "其他行一律不動"


@pytest.mark.parametrize("text, why", [
    (PS1.replace("$Port = 666\n", ""), "少了 $Port"),
    (PS1 + "$ProdRoot = \"D:\\x\"\n", "兩行 $ProdRoot"),
])
def test_rewrite_refuses_unexpected_shapes(text, why):
    with pytest.raises(DR.DrillError):
        DR.rewrite_ps1(text, r"C:\T\x", 6755)


@pytest.fixture()
def wt(tmp_path):
    """演練 worktree 的替身：只複製 tender_radar 與它的頁面。"""
    m = REPO / "backend" / "modules" / DR.KEY
    shutil.copytree(m, tmp_path / "backend" / "modules" / DR.KEY, ignore=shutil.ignore_patterns("__pycache__", "tests"))
    pages = tmp_path / ("frontend/" + "pages")          # 合成 worktree 的頁面目錄（資料，不是讀 repo 的頁面）
    pages.mkdir(parents=True)
    import json
    for pg in json.loads((m / "module.json").read_text(encoding="utf-8"))["pages"]:
        src = next((REPO / "frontend").rglob(pg["path"]), None) or next(m.rglob(pg["path"]))
        shutil.copy2(src, pages / pg["path"])
    return tmp_path


@pytest.mark.parametrize("variant", ["A", "B", "C"])
def test_variants_bump_version_and_stay_valid_python(wt, variant):
    import json
    before = json.loads((wt / "backend" / "modules" / DR.KEY / "module.json").read_text(encoding="utf-8"))["version"]
    ver = DR.make_variant(wt, variant)
    after = json.loads((wt / "backend" / "modules" / DR.KEY / "module.json").read_text(encoding="utf-8"))["version"]
    assert after == ver != before
    init = (wt / "backend" / "modules" / DR.KEY / "__init__.py").read_text(encoding="utf-8")
    ast.parse(init)
    if variant == "B":
        assert "'uvicorn' in _drill_sys.modules" in init
    if variant == "C":
        assert "migrations=[(1, _drill_not_now)]" in init and "return 'B55" in init


def test_variant_b_loads_without_uvicorn_and_fails_with_it(wt, monkeypatch):
    """B 的關鍵：乾跑（沒有 uvicorn）載得起來 ⇒ 過得了步驟 5；真的啟動（有 uvicorn）載入失敗 ⇒ 健檢抓到。"""
    DR.make_variant(wt, "B")
    code = compile((wt / "backend" / "modules" / DR.KEY / "__init__.py").read_text(encoding="utf-8").split("\nfrom ")[0],
                   "init_head", "exec")
    monkeypatch.delitem(sys.modules, "uvicorn", raising=False)
    exec(code, {})                                           # 沒有 uvicorn ⇒ 不丟
    monkeypatch.setitem(sys.modules, "uvicorn", object())
    with pytest.raises(RuntimeError, match="演練 B"):
        exec(code, {})


def test_variant_bumps_above_the_installed_version(wt):
    """同一個演練安裝連續跑多場：前一場成功後已是新版 ⇒ 下一場要再往上升（否則 preflight not_higher，演練 B 沒跑到回滾）。"""
    import json
    cur = json.loads((wt / "backend" / "modules" / DR.KEY / "module.json").read_text(encoding="utf-8"))["version"]
    ahead = DR._bump(cur)
    ver = DR.make_variant(wt, "B", ahead)
    assert DR._vkey(ver) > DR._vkey(ahead)
