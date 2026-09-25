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
- 正對照與反向控制：用合成文字（不綁任何 L2 模組）；另驗範圍不是空的（掃描對象消失時不可以默默變綠）。
"""
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
