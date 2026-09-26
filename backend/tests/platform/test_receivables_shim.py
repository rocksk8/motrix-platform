"""L1 薄殼 `helpers/receivables.py`（淘汰中，下一個主版號刪除）：只准轉呼叫 M05 的 provider（主持裁示 2026-09-26，M05 搬遷 (a)）。

① 靜態：不 import 任何 `modules.*`、不讀表（沒有 SQL、`.execute`、`get_db`、`import db`）、
   每一支公開函式（round_half_up_invoice 除外）都呼叫 `registry.single_provider("receivables.…")`
② 行為（M05 不在，模擬拿掉 provider）：`collect_income_items` ⇒ `[]`；`collect_tax_invoices` ⇒ 404 並明說
③ 行為（M05 在）：轉呼叫的就是 provider 的結果（同一份資料）
反向控制：掃描器對一段「import 模組」「自己讀表」「不經 provider 回空值」的原始碼報得出來。
"""
import ast
from pathlib import Path

import pytest

from tests.platform.test_tax_calc_contract import table_access

SHIM = Path(__file__).resolve().parents[2] / "helpers" / "receivables.py"
CAPS = {"collect_income_items": "receivables.income_items", "collect_tax_invoices": "receivables.tax_invoices"}


def shim_violations(src):
    """清單＝違規。"""
    tree = ast.parse(src)
    bad = []
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("modules"):
            bad.append("import %s" % n.module)
        if isinstance(n, ast.Import):
            bad += ["import %s" % a.name for a in n.names if a.name.startswith("modules")]
    bad += ["讀表：%s" % x for x in table_access(src)]
    funcs = {f.name: f for f in tree.body if isinstance(f, ast.FunctionDef)}
    for name, cap in CAPS.items():
        f = funcs.get(name)
        if f is None:
            bad.append("缺少 %s（刪除要等下一個主版號）" % name)
            continue
        calls = [c for c in ast.walk(f) if isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "single_provider"
                 and c.args and isinstance(c.args[0], ast.Constant) and c.args[0].value == cap]
        if not calls:
            bad.append("%s 沒有轉呼叫 provider %s" % (name, cap))
    return bad


def test_shim_only_delegates_to_the_providers():
    assert shim_violations(SHIM.read_text(encoding="utf-8")) == []


def test_rc_shim_scanner_catches_imports_sql_and_missing_delegation():
    bad_src = ('from modules.arap.receivables import collect_income_items as _x\n'
               'from db import get_db\n'
               'def collect_income_items(d0, d1, department_id=None):\n'
               '    return get_db().execute("SELECT data_json FROM quotations").fetchall()\n'
               'def collect_tax_invoices(year=None, month=None):\n'
               '    return []\n')
    got = shim_violations(bad_src)
    assert "import modules.arap.receivables" in got
    assert any(g.startswith("讀表：") for g in got)
    assert "collect_income_items 沒有轉呼叫 provider receivables.income_items" in got
    assert "collect_tax_invoices 沒有轉呼叫 provider receivables.tax_invoices" in got
    assert "缺少 collect_tax_invoices（刪除要等下一個主版號）" in shim_violations("def collect_income_items(a, b):\n    pass\n")


def _drop(monkeypatch, *caps):
    from core import registry
    orig_single = registry.single_provider
    monkeypatch.setattr(registry, "single_provider", lambda cap: None if cap in caps else orig_single(cap))


def test_shim_when_m05_is_absent(client, monkeypatch):
    from fastapi import HTTPException
    from helpers import receivables as r
    _drop(monkeypatch, *CAPS.values())
    assert r.collect_income_items("2026-01-01", "2026-12-31") == []
    with pytest.raises(HTTPException) as e:
        r.collect_tax_invoices(2026, 9)
    assert e.value.status_code == 404 and e.value.detail == r.RECEIVABLES_MISSING and "應收應付模組未安裝" in r.RECEIVABLES_MISSING


def test_shim_when_m05_is_present_returns_the_providers_answer(client):
    from core import registry, source_tree
    if not source_tree.module_installed("modules/arap/"):
        pytest.skip("M05 不在這個安裝包（PLAYBOOK §B-11）⇒ 沒有 provider 可比；⚠ skip 不是驗過")
    from helpers import receivables as r
    seen = {}

    def fake(tag):
        def f(*a):
            seen[tag] = a
            return ["from-provider-" + tag]
        return f
    import pytest as _pt
    mp = _pt.MonkeyPatch()
    try:
        orig = registry.single_provider
        mp.setattr(registry, "single_provider",
                   lambda cap: fake(cap) if cap in CAPS.values() else orig(cap))
        assert r.collect_income_items("2026-01-01", "2026-01-31", 3) == ["from-provider-receivables.income_items"]
        assert seen["receivables.income_items"] == ("2026-01-01", "2026-01-31", 3)
        assert r.collect_tax_invoices(2026, 1) == ["from-provider-receivables.tax_invoices"]
        assert seen["receivables.tax_invoices"] == (2026, 1)
    finally:
        mp.undo()
    # 真的 provider 有登記（模組在時）
    assert registry.single_provider("receivables.income_items") is not None
    assert registry.single_provider("receivables.tax_invoices") is not None
