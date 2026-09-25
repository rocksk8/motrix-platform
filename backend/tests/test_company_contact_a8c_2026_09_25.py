# -*- coding: utf-8 -*-
"""ROADMAP A8c：寫死的公司聯絡資料（統編／電話／email／英文名）改從 company_identity 取。

搬移前後以一次性比對驗證（commit 訊息記錄）：company_profile 填入原本寫死的值時，
營運報表 xlsx／html、網路規劃 xlsx／html、拓樸頁 5 種輸出逐位元組相同（時間戳遮罩）。
這裡釘的是搬移後要一直成立的性質。
"""
import io
from pathlib import Path

import openpyxl
import pytest

BACKEND = Path(__file__).resolve().parent.parent
OURS = {"company_name": "允碩整合集創股份有限公司", "company_name_en": "MOTRIX Synergy Integration Corp.",
        "tax_id": "60575481", "phone": "04-3610-6566", "email": "info@miactw.com"}


@pytest.mark.parametrize("rel", ["routers/reports.py", "network_plan_export.py", "pdf_gen.py"])
def test_no_hardcoded_company_contacts_left(rel):
    src = (BACKEND / rel).read_text(encoding="utf-8")
    for needle in ("60575481", "3610-6566", "miactw", "MOTRIX Synergy", "_COMPANY2"):
        assert needle not in src, (rel, needle)


def test_lines_match_the_old_hardcoded_format_when_filled():
    from helpers.company_identity import contact_line, footer_line, name_pair
    assert contact_line(ident=OURS) == "統一編號 60575481 ｜ Tel: 04-3610-6566 ｜ info@miactw.com"
    assert contact_line("　｜　", "統一編號：", "電話：", ident=OURS) == \
        "統一編號：60575481　｜　電話：04-3610-6566　｜　info@miactw.com"
    assert footer_line(OURS) == \
        "MOTRIX Synergy Integration Corp. 允碩整合集創 ｜ info@miactw.com ｜ Tel: 04-3610-6566 ｜ 統一編號: 60575481"
    assert name_pair(OURS) == "MOTRIX Synergy Integration Corp. 允碩整合集創"


def test_empty_or_partial_profile_leaves_no_dangling_separators():
    from helpers.company_identity import contact_line, footer_line, name_pair
    empty = {k: "" for k in OURS}
    assert contact_line(ident=empty) == "" and footer_line(empty) == "" and name_pair(empty) == ""
    partial = {**empty, "company_name": "某某有限公司", "phone": "02-1234"}
    assert contact_line(ident=partial) == "Tel: 02-1234"
    assert footer_line(partial) == "某某 ｜ Tel: 02-1234"


def test_pdf_gen_uses_the_single_short_name():
    import pdf_gen
    from helpers.company_identity import short_name
    assert pdf_gen._short_name is short_name


def test_empty_profile_writes_none_not_empty_string(client):
    """openpyxl 的空字串會產生非法 inlineStr（Excel 開檔要修復）⇒ 空白一律寫 None。"""
    from helpers.settings import _set_setting, _get_setting
    import network_plan_export as npe
    prof = _get_setting("company_profile", {}) or {}
    _set_setting("company_profile", {**prof, "companyName": "", "companyNameEn": "", "taxId": "",
                                      "phone": "", "email": "", "locations": []})
    wb = openpyxl.load_workbook(io.BytesIO(npe.build_plan_excel({"name": "x", "data": {}})))
    assert wb["封面"]["A1"].value is None and wb["封面"]["A2"].value is None
