# -*- coding: utf-8 -*-
"""S6（0d）：`caseRecord.materials` 的寫入點靜態守門。認列（poLink）靠 `material_guard.enforce` 這道閘；
新增任何『把卡片寫進 caseRecord.materials』的程式都必須先判斷它最後是否走 `save_quotation_json`（漏斗會再過一次閘），並更新下面的清單。"""
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3]
PAT = re.compile(r"""setdefault\(\s*["']materials["']|\[\s*["']materials["']\s*\]\s*(=(?!=)|\.append|\+=)""")
#: {檔案: 次數}——全部最後都存回 quotations（案件記錄 PATCH／上傳附件／匯入卡片），漏斗 `save_quotation_json` 會過閘
ALLOWED = {"modules/case/material_guard.py": 1, "modules/case/api/quotations.py": 5}


def _sites():
    out = {}
    for f in BACKEND.rglob("*.py"):
        rel = f.relative_to(BACKEND).as_posix()
        if "/tests/" in "/" + rel or rel.startswith(("tests/", "migrations_frozen/", "tools/")):
            continue
        n = len(PAT.findall(f.read_text(encoding="utf-8", errors="replace")))
        if n:
            out[rel] = n
    return out


def test_only_known_code_writes_cards_into_case_record_materials():
    assert _sites() == ALLOWED, "caseRecord.materials 出現新的寫入點：請確認它走 save_quotation_json 並更新清單"


def test_the_write_funnel_runs_the_material_gate():
    src = (BACKEND / "modules/case/quotations.py").read_text(encoding="utf-8")
    body = src[src.index("def save_quotation_json"):]
    assert "_mg.enforce(conn, quote_no, data, actor)" in body[:6000]
