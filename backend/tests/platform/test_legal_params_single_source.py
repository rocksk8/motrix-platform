# -*- coding: utf-8 -*-
"""守門（MODULE-GUIDE §11；CUSTOMIZATION-SPEC §9.1）：法規數字只能出現在 L1 法規參數服務。

扣繳起扣標準、補充保費費率、最低工資每年會變；寫死在模組裡 ⇒ 跨年時只改到一處（BENCHMARK §7 第一項的成因：
勞報單的規則原本寫死在 `modules/payroll/api/payslips.py`，修改舊單還會用當下的規則重算）。

- 範圍：`core.source_tree.product_files()`（全部產品碼）＋ frontend 的 .html／.js。
- 允許：`helpers/legal_params.py`（唯一來源）、`db.py`（V9 凍結的種子 `tax_rules`，只准新增、不改）。
- 正對照：掃描函式對一段合成文字要抓得到（不綁任何 L2 模組）。
"""
import re
from pathlib import Path

from core import source_tree

#: 115 年版的法規數字（改年度時，新的數字也只能出現在 legal_params）
LEGAL_NUMBERS = ("90501", "29500", "0.0211", "20010")
_PAT = re.compile(r"(?<![\d.])(" + "|".join(re.escape(n) for n in LEGAL_NUMBERS) + r")(?![\d])")
ALLOWED = {"helpers/legal_params.py", "db.py"}
FRONTEND = source_tree.BACKEND.parent / "frontend"


def hits(text: str) -> list:
    """去掉註解之後的法規數字。"""
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        # 稽核 O-3（2026-09-26）：原本一行裡只要有 `//`（例如 "https://…"）就截斷，後面的程式碼看不到
        #   ⇒ 只把「行首或空白之後」的 # 與 // 當註解
        code = re.split(r"(?:^|\s)(?:#|//)", line, maxsplit=1)[0]
        if _PAT.search(code):
            out.append((i, line.strip()[:120]))
    return out


def test_positive_control_the_scanner_finds_a_hard_coded_threshold():
    assert hits('rules = {"thresholds": {"50": 29500}}')
    assert hits("rate = 0.0211")
    assert not hits("# 註解裡的 29500 不算")
    assert not hits("x = 295001")
    assert hits('const u = "https://x"; const th = 29500'), "`https://` 之後的程式碼也要看得到"
    assert not hits("const a = 1  // 29500 是註解")


def test_legal_numbers_live_only_in_the_legal_params_service():
    bad = []
    for p in source_tree.product_files():
        rel = source_tree.rel(p)
        if rel in ALLOWED:
            continue
        for ln, s in hits(p.read_text(encoding="utf-8")):
            bad.append(f"backend/{rel}:{ln}: {s}")
    for p in sorted(list(FRONTEND.rglob("*.html")) + list(FRONTEND.rglob("*.js"))):
        if "vendor" in p.parts:
            continue
        for ln, s in hits(p.read_text(encoding="utf-8", errors="replace")):
            bad.append(f"frontend/{p.relative_to(FRONTEND).as_posix()}:{ln}: {s}")
    assert not bad, "法規數字要從 helpers.legal_params 取（依生效日版本化），不可以寫死：\n" + "\n".join(bad)
