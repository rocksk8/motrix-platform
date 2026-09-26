"""L1 `helpers/tax_calc.py` 的契約（主持核准「T」，2026-09-26）：稅額純函式自 M01 下沉。

① 不讀表：沒有 `import db`／`get_db`、沒有 `.execute(`、沒有 SQL 字串
② 不 import M01：modules.case.quotations／recognition／quote_terms／case_deadlines／case_stage_tasks、routers.*、modules.*
③ 別名：`modules.case.quotations` 與 `helpers` 的同名名稱是 tax_calc 的同一個物件（不是複本——複本會各自演進）
④ 行為：應稅 5% 四捨五入、零稅率／免稅 0、舊 1～4% 標 legacy、收款項金額首期吸收尾差、沖銷折未稅
正對照：①② 的掃描器對一段刻意違規的原始碼要報得出來（不然「沒違規」可能只是掃描器壞了）。
"""
import ast
from pathlib import Path

import pytest

TAX_CALC = Path(__file__).resolve().parents[2] / "helpers" / "tax_calc.py"
NAMES = ("TAX_TYPES", "TAX_TYPE_LABELS", "LEGAL_TAX_RATE", "LEGACY_TAX_NOTE",
         "quote_tax_type", "tax_split", "_invoice_amount", "invoice_amounts", "payment_item_amounts")
M01_MODULES = ("modules.case.quotations", "modules.case.recognition", "modules.case.quote_terms",
               "modules.case.case_deadlines", "modules.case.case_stage_tasks")
_SQL = ("SELECT ", "INSERT ", "UPDATE ", "DELETE ", "FROM ")


def _docstrings(tree):
    out = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            out.add(id(body[0].value))
    return out


def table_access(src):
    """原始碼裡讀寫表的跡象（清單＝違規）。docstring 裡提到 SQL 字眼不算。"""
    tree = ast.parse(src)
    docs = _docstrings(tree)
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out += ["import " + a.name for a in n.names if a.name == "db"]
        elif isinstance(n, ast.ImportFrom) and (n.module or "") == "db":
            out.append("from db import")
        elif isinstance(n, ast.Attribute) and n.attr in ("execute", "executemany", "executescript"):
            out.append("." + n.attr)
        elif isinstance(n, ast.Name) and n.id == "get_db":
            out.append("get_db")
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs                 and any(n.value.upper().lstrip().startswith(k) for k in _SQL):
            out.append("SQL " + n.value[:30])
    return out


def m01_imports(src):
    out = []
    for n in ast.walk(ast.parse(src)):
        mods = []
        if isinstance(n, ast.Import):
            mods = [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            mods = [n.module or ""]
            if (n.module or "") == "helpers":
                mods += ["helpers." + a.name for a in n.names]
        out += [m for m in mods if m in M01_MODULES or m.startswith(("routers", "modules"))]
    return out


def test_tax_calc_reads_no_table():
    assert table_access(TAX_CALC.read_text(encoding="utf-8")) == []


def test_tax_calc_imports_no_m01():
    assert m01_imports(TAX_CALC.read_text(encoding="utf-8")) == []


def test_scanners_positive_control():
    """掃描器對已知的違規報得出來（正對照；不綁任何真實模組）。"""
    bad = ('def f(q):\n    from db import get_db\n    conn = get_db()\n'
           '    return conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (q,))\n')
    got = table_access(bad)
    assert "from db import" in got and "get_db" in got and ".execute" in got and any(g.startswith("SQL") for g in got), got
    assert table_access('def f():\n    """SELECT 只是說明文字"""\n    return 1\n') == []    # 反向控制：docstring 不算
    assert m01_imports("from modules.case.quotations import x\nfrom modules.case import recognition\nimport modules.case.api.quotations\n") == \
        ["modules.case.quotations", "modules.case", "modules.case.api.quotations"]   # M01 ② 起在 modules/case
    assert m01_imports("from helpers.legal_params import round_half_up\n") == []


@pytest.mark.parametrize("name", NAMES)
def test_old_location_is_an_alias_of_the_l1_object(name):
    from helpers import tax_calc
    from modules.case import quotations
    assert getattr(quotations, name) is getattr(tax_calc, name), name


def test_helpers_package_reexports_the_l1_object():
    import helpers
    from helpers import tax_calc
    assert helpers.payment_item_amounts is tax_calc.payment_item_amounts


def test_behaviour():
    from helpers import tax_calc as t
    assert t.quote_tax_type({}) == "taxable"
    assert t.quote_tax_type({"taxRate": 0}) == "exempt"
    assert t.quote_tax_type({"taxRate": 3}) == "legacy"
    assert t.quote_tax_type({"taxType": "zero", "taxRate": 5}) == "zero"
    assert t.tax_split(10010, "taxable") == (10010, 501)           # 500.5 ⇒ 501（四捨五入，不是銀行家捨入）
    assert t.tax_split(10000, "exempt") == (10000, 0)
    with pytest.raises(ValueError):
        t.tax_split(100, "legacy")
    assert t.invoice_amounts({"invoicePretax": "1000", "invoiceTax": 50}) == (1000, 50)
    assert t.invoice_amounts({"invoicePretax": 1000}) is None
    items = [{"pct": 30}, {"pct": 30}, {"pct": 40}]
    assert t.payment_item_amounts(10001, items) == [3001, 3000, 4000]  # 首期吸收尾差，合計＝總價
    assert t.payment_item_amounts(10500, [{"amount": 10500, "taxExempt": True}], pretax=10000) == [10000]
    assert t.payment_item_amounts(10500, [{"amount": 10500, "taxExempt": True}], pretax=10000,
                                  apply_tax_exempt=False) == [10500]
