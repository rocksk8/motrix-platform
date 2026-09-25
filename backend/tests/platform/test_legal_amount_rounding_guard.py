# -*- coding: utf-8 -*-
"""守門（MODULE-GUIDE §11；稽核 D-1，2026-09-26）：法規金額的捨入只能走 L1 `helpers.legal_params`。

成因：勞報單補充保費用了 Python 內建 `round()`（銀行家捨入：round(738.5) == 738），前端用
`Math.round(gross * rate)`（浮點乘積）⇒ 20,000～2,000,000 之間 99 個金額前後端差 1 元，而健保署規定四捨五入。
U4 獎金是第二個算補充保費的模組，照抄就會再錯一次。

- 範圍（Python）：`core.source_tree.product_files()` 裡**讀法規參數**（呼叫 `rules_for_date`／`rules_by_version`／
  `load_versions`）的檔案，唯一來源 `helpers/legal_params.py` 除外。禁止 `round(`、`math.floor(`、`math.ceil(`
  ⇒ 改用 `legal_params.round_half_up`（四捨五入）／`legal_params.floor_amount`（捨去）。
- 範圍（前端）：frontend 的 .html／.js 裡**讀法規參數**（呼叫 `/tax-rules` 端點）的檔案，
  `static/legal-round.js` 除外。禁止 `Math.round(`／`Math.floor(`／`Math.ceil(`／`Math.trunc(`
  ⇒ 改用 `MotrixLegalRound.halfUp`／`.floor`。
- 擴大範圍（X-VAT，2026-09-26）：開票、請款、報價、外包稅額、成本精算、叫料的金額計算——明確的檔案清單
  `MONEY_PY_FILES`／`MONEY_JS_FILES`（見檔案後段），禁止 `round(`／`Math.round(`；非金額標 `/* 非金額 */`。
- 正對照與反向控制：用合成文字（不綁任何 L2 模組）；另驗範圍不是空的（掃描對象消失時不可以默默變綠）。
"""
import ast
import re

from core import source_tree

FRONTEND = source_tree.BACKEND.parent / "frontend"

PY_ALLOWED = {"helpers/legal_params.py"}
JS_ALLOWED = {"static/legal-round.js"}

_PY_READS_RULES = re.compile(r"\b(rules_for_date|rules_by_version|load_versions)\s*\(")
_PY_FORBIDDEN = re.compile(r"(?<![\w.])round\s*\(|\bmath\.(floor|ceil)\s*\(")
_JS_READS_RULES = re.compile(r"/tax-rules\b")
_JS_FORBIDDEN = re.compile(r"\bMath\.(round|floor|ceil|trunc)\s*\(")


def _strip_py(line: str) -> str:
    return re.split(r"(?:^|\s)#", line, maxsplit=1)[0]


def _strip_js(line: str) -> str:
    # 只把「行首或空白之後」的 // 當註解（`https://…` 不截斷——稽核 O-3 指出的粗略剝除）
    return re.split(r"(?:^|\s)//", line, maxsplit=1)[0]


def py_hits(text: str) -> list:
    """讀法規參數的 Python 原始碼裡，直接捨入的行。沒有讀法規參數 ⇒ 不在範圍（[]）。"""
    if not _PY_READS_RULES.search("\n".join(_strip_py(x) for x in text.splitlines())):
        return []
    return [(i, ln.strip()[:120]) for i, ln in enumerate(text.splitlines(), 1)
            if _PY_FORBIDDEN.search(_strip_py(ln))]


def js_hits(text: str) -> list:
    if not _JS_READS_RULES.search(text):
        return []
    return [(i, ln.strip()[:120]) for i, ln in enumerate(text.splitlines(), 1)
            if _JS_FORBIDDEN.search(_strip_js(ln))]


def _py_scope():
    return [p for p in source_tree.product_files()
            if source_tree.rel(p) not in PY_ALLOWED
            and _PY_READS_RULES.search(p.read_text(encoding="utf-8"))]


def _js_scope():
    out = []
    for p in sorted(list(FRONTEND.rglob("*.html")) + list(FRONTEND.rglob("*.js"))):
        rel = p.relative_to(FRONTEND).as_posix()
        if "vendor" in p.parts or rel in JS_ALLOWED:
            continue
        t = p.read_text(encoding="utf-8", errors="replace")
        if _JS_READS_RULES.search(t):
            out.append((rel, t))
    return out


# ── 正對照／反向控制（合成文字） ─────────────────────────────────────────────────

def test_positive_control_python_rounding_in_a_rules_reader_is_caught():
    src = "rules = lp.rules_for_date(vs, d)\nnhi = round(base * rules['nhi']['rate'])\n"
    assert py_hits(src), "讀法規參數又直接 round() ⇒ 要抓到"
    assert py_hits("r = lp.load_versions()\ntax = math.floor(g * 0.05)\n")
    assert py_hits("r = lp.rules_by_version(vs, '2026')\nx = math.ceil(g * r['nhi']['rate'])\n")


def test_reverse_control_python():
    # 走 L1 函式 ⇒ 不算
    assert not py_hits("rules = lp.rules_for_date(vs, d)\nnhi = lp.round_half_up(base, rules['nhi']['rate'])\n")
    # 不讀法規參數的檔案（例：報價的營業稅）⇒ 不在範圍
    assert not py_hits("amt = round(total * pct / 100)\n")
    # 註解裡提到的不算；方法呼叫 x.round( 不算
    assert not py_hits("r = lp.load_versions()\n# 以前用 round(base * rate)\nq = d.round(2)\n")


def test_positive_and_reverse_control_js():
    page = "fetch(`${API}/tax-rules?date=x`)\nconst n = Math.round(gross * rate)\n"
    assert js_hits(page)
    assert js_hits("fetch('/api/tax-rules')\nconst t = Math.floor(g * r)\n")
    assert not js_hits("fetch('/api/tax-rules')\nconst n = MotrixLegalRound.halfUp(gross, rate)\n")
    assert not js_hits("const n = Math.round(x)\n"), "不讀法規參數的頁面不在範圍"
    assert not js_hits("fetch('/api/tax-rules')\n// 舊寫法 Math.round(gross * rate)\n")
    assert js_hits("fetch('https://x/api/tax-rules')\nconst u = 'https://a'; const n = Math.round(g * r)\n"), \
        "`https://` 之後的程式碼也要看得到"


def test_scope_is_not_empty():
    """讀法規參數的檔案一個都掃不到 ⇒ 守門失去對象，不可以默默變綠（不綁特定模組）。"""
    assert _py_scope(), "找不到任何呼叫 rules_for_date／load_versions 的產品碼"
    assert _js_scope(), "找不到任何呼叫 /tax-rules 的前端檔案"


# ── 實際掃描 ────────────────────────────────────────────────────────────────────

def test_legal_amounts_are_rounded_only_by_the_legal_params_service():
    bad = []
    for p in _py_scope():
        for ln, s in py_hits(p.read_text(encoding="utf-8")):
            bad.append(f"backend/{source_tree.rel(p)}:{ln}: {s}")
    for rel, t in _js_scope():
        for ln, s in js_hits(t):
            bad.append(f"frontend/{rel}:{ln}: {s}")
    assert not bad, ("法規金額要用 helpers.legal_params.round_half_up／floor_amount（前端 MotrixLegalRound），"
                     "不可以直接 round()／math.floor()／Math.round()：\n" + "\n".join(bad))


# ── 擴大範圍：開票、請款、報價、外包稅額、成本精算的金額計算（X-VAT，2026-09-26）────────────────
#
# 成因：開票申請（invoice_vouchers）與請款單用內建 round() 換算未稅／含稅（銀行家捨入：10.5 ⇒ 10），
#   報價收款期別 payment_item_amounts 也是（10,015 × 30% ＝ 3,004.5 ⇒ 後端 3,004、畫面 3,005）；
#   外包派發稅額後端 round()、前端 Math.round() ⇒ 10,010 × 5% ＝ 500.5 兩邊差 1 元。
#   這些檔**不讀法規參數**，上面的範圍掃不到 ⇒ 用明確的檔案清單。
# - Python：清單內的檔不可以呼叫內建 round()（AST 判斷，docstring／註解裡的字不算），也不可以自己
#   import ROUND_HALF_UP 另做一套 ⇒ 一律 `legal_params.round_half_up`。
# - 前端：清單內的檔不可以 Math.round( ⇒ 一律 `MotrixLegalRound.halfUp`。非金額（例：檔案大小 KB）要在
#   同一行用註解標 `/* 非金額 */`——標記＝有人做過決定，不是豁免清單。
# - 用到 MotrixLegalRound 的頁面（含載入 case-management-*.js 的頁面）必須載入 static/legal-round.js。
# - 清單裡的檔不存在 ⇒ 紅（檔案搬進模組時要跟著改清單，不可以默默失去對象）。
MONEY_PY_FILES = (
    "routers/invoice_vouchers.py", "routers/payment_requests.py", "helpers/quotations.py",
    "modules/subcontract/api/contractor_vouchers.py", "modules/subcontract/api/vendor_contractors.py",   # 2026-09-26 外包工班搬進模組
)
MONEY_JS_FILES = (
    "pages/quotation-form.html", "pages/payment-request-form.html", "pages/settlement.html",
    "js/case-management-fin.js", "js/case-management-dispatch.js", "js/case-management-xexp.js",
    "js/case-management-exec.js",
)
_NOT_MONEY = re.compile(r"/\*\s*非金額\s*\*/|//\s*非金額")
_LEGAL_ROUND_TAG = re.compile(r'<script\s+src="\.\./static/legal-round\.js"\s*>')


def money_py_hits(src: str) -> list:
    """內建 round() 的呼叫、自己 import ROUND_HALF_UP 的行。"""
    out = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "round":
            out.append(node.lineno)
        elif isinstance(node, ast.ImportFrom) and node.module == "decimal" \
                and any(a.name.startswith("ROUND_") for a in node.names):
            out.append(node.lineno)
    return sorted(out)


def money_js_hits(text: str) -> list:
    return [(i, ln.strip()[:120]) for i, ln in enumerate(text.splitlines(), 1)
            if re.search(r"\bMath\.round\s*\(", _strip_js(ln)) and not _NOT_MONEY.search(ln)]


def page_needs_legal_round(html: str, js_texts: dict) -> bool:
    """頁面本身或它載入的 case-management-*.js 用到 MotrixLegalRound ⇒ True。"""
    if "MotrixLegalRound" in html:
        return True
    for name in re.findall(r'<script\s+src="\.\./js/([\w.-]+\.js)"', html):
        if "MotrixLegalRound" in js_texts.get(name, ""):
            return True
    return False


def test_money_positive_control_python():
    assert money_py_hits("x = round(a * b / c)\n") == [1]
    assert money_py_hits("def f():\n    return {'t': round(t)}\n") == [2]
    assert money_py_hits("from decimal import Decimal, ROUND_HALF_UP\n") == [1], "自己另做一套四捨五入也要擋"


def test_money_reverse_control_python():
    assert not money_py_hits("x = round_half_up(a * b / c)\n")
    assert not money_py_hits('"""round(490.5) == 490"""\n# round(x)\ny = d.round(2)\n'), \
        "docstring、註解、方法呼叫不算"
    assert not money_py_hits("from decimal import Decimal\n")


def test_money_positive_and_reverse_control_js():
    assert money_js_hits("const t = Math.round(pretax * rate)\n")
    assert money_js_hits("x-text=\"Math.round(n).toLocaleString()\"\n")
    assert not money_js_hits("const t = MotrixLegalRound.halfUp(pretax, rate)\n")
    assert not money_js_hits("// 舊寫法 Math.round(pretax * rate)\n")
    assert not money_js_hits("' KB' + Math.round(v.size/1024 /* 非金額 */)\n"), "標了非金額 ⇒ 不算"
    assert money_js_hits("Math.round(v.size/1024) // 金額\n"), "要寫的是「非金額」，其他註解不算"


def test_money_page_script_tag_control():
    js = {"case-management-fin.js": "MotrixLegalRound.halfUp(x)", "case-management-list.js": "x"}
    assert page_needs_legal_round('<script src="../js/case-management-fin.js"></script>', js)
    assert not page_needs_legal_round('<script src="../js/case-management-list.js"></script>', js)
    assert page_needs_legal_round("const t = MotrixLegalRound.halfUp(a, b)", {})


def test_money_scope_files_exist():
    missing = [f"backend/{f}" for f in MONEY_PY_FILES if not (source_tree.BACKEND / f).exists()]
    missing += [f"frontend/{f}" for f in MONEY_JS_FILES if not (FRONTEND / f).exists()]
    assert not missing, "守門清單裡的檔不見了（搬進模組了？請同步更新 MONEY_*_FILES）：\n" + "\n".join(missing)


def test_invoice_quote_and_payment_amounts_use_the_shared_half_up():
    bad = []
    for f in MONEY_PY_FILES:
        p = source_tree.BACKEND / f
        for ln in money_py_hits(p.read_text(encoding="utf-8")):
            bad.append(f"backend/{f}:{ln}")
    for f in MONEY_JS_FILES:
        for ln, s in money_js_hits((FRONTEND / f).read_text(encoding="utf-8")):
            bad.append(f"frontend/{f}:{ln}: {s}")
    assert not bad, ("開票／請款／報價／外包稅額／成本精算的金額要用 legal_params.round_half_up"
                     "（前端 MotrixLegalRound.halfUp），不可以直接 round()／Math.round()"
                     "（非金額請在同一行標 /* 非金額 */）：\n" + "\n".join(bad))


def test_pages_using_the_shared_rounding_load_legal_round_js():
    js_texts = {p.name: p.read_text(encoding="utf-8") for p in (FRONTEND / "js").glob("*.js")}
    pages = source_tree.page_files()   # 頁面位置一律經 source_tree（C1；列車 train/0926-0415 交會）
    assert pages
    bad = [p.name for p in pages
           if page_needs_legal_round(p.read_text(encoding="utf-8"), js_texts)
           and not _LEGAL_ROUND_TAG.search(p.read_text(encoding="utf-8"))]
    assert not bad, "用到 MotrixLegalRound 卻沒有載入 ../static/legal-round.js（執行時 ReferenceError）：" + ", ".join(bad)
