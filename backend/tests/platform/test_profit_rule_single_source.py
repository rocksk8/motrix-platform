# -*- coding: utf-8 -*-
"""守門（第 48 班 S1）：管銷分攤／公益捐款的算式只能寫在利潤規則（helpers/profit_rules.py ＋ static/profit-rules.js）。

抓兩種寫法：① 管銷樣式 `halfUp(…, 0.10)`／`round_half_up(…, 0.10)`（舊口徑的 10% 字面值）；② 前端 `adminCost =` 賦值。
過渡清單 `TRANSITIONAL`（S1 時前端三個頁面還沒改接規則，S3 改接後必須清空——清單內的檔案出現次數要『剛好等於』登記數，
多一處或少一處都紅，少一處＝已改接，請把登記數減掉）。正對照：掃描函式對合成文字要抓得到。
"""
import re
from pathlib import Path

from core import source_tree

FRONTEND = source_tree.BACKEND.parent / "frontend"
ALLOWED = {"helpers/profit_rules.py"}
#: 過渡登記：{前端相對路徑: 登記的出現次數}
TRANSITIONAL = {}                              # S3 已清空（頁面都改呼叫 MotrixProfitRules）；日後有過渡需求才再登記
_PATS = (re.compile(r"(?:halfUp|round_half_up)\([^()]*,\s*0?\.10\)"),
         re.compile(r"\badminCost\s*=(?!=)(?!\s*MotrixProfitRules\.)"))


def hits(text: str) -> list:
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        code = re.split(r"(?:^|\s)(?:#|//)", line, maxsplit=1)[0]
        if any(p.search(code) for p in _PATS):
            out.append((i, line.strip()[:120]))
    return out


def test_positive_control_the_scanner_finds_the_legacy_overhead_expressions():
    assert hits("const adminCost       = MotrixLegalRound.halfUp(pretax, 0.10)")
    assert hits("admin = round_half_up(pretax, 0.10)")
    assert hits("adminCost = x")
    assert not hits("const adminCost = MotrixProfitRules.adminCost(a, b, c, d)"), "呼叫規則不算違規"
    assert not hits("if (a.adminCost == null) y()")
    assert not hits("# admin = round_half_up(pretax, 0.10)  註解不算")
    assert not hits("x = round_half_up(a, 0.105)")


def test_overhead_formula_lives_only_in_the_profit_rules():
    bad = []
    for p in source_tree.product_files():
        rel = source_tree.rel(p)
        if rel in ALLOWED:
            continue
        for ln, s in hits(p.read_text(encoding="utf-8")):
            bad.append(f"backend/{rel}:{ln}: {s}")
    seen = {}
    for p in sorted(list(FRONTEND.rglob("*.html")) + list(FRONTEND.rglob("*.js"))):
        rel = p.relative_to(FRONTEND).as_posix()
        if "vendor" in p.parts or rel == "static/profit-rules.js":
            continue
        found = hits(p.read_text(encoding="utf-8", errors="replace"))
        if rel in TRANSITIONAL:
            seen[rel] = len(found)
        else:
            bad.extend(f"frontend/{rel}:{ln}: {s}" for ln, s in found)
    for rel, n in TRANSITIONAL.items():
        if seen.get(rel) != n:
            bad.append(f"frontend/{rel}: 過渡登記 {n} 處，實際 {seen.get(rel)} 處（改接規則後請同步調整 TRANSITIONAL）")
    assert not bad, "管銷／公益金算式要呼叫 profit_rules，不可以另寫一份：\n" + "\n".join(bad)
