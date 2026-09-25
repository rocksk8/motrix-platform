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


def test_upgrade_filled_profile_reproduces_v9_output_byte_for_byte(client, tmp_path):
    """升級補空值之後，聯絡資料那幾處與 V9 寫死的字串逐位元組相同（V9：reports.py:66、network_plan_export.py:19-20、:370、:381）。"""
    import json as _json
    import sqlite3
    from core import upgrade as U
    from helpers.settings import _set_setting
    from helpers.company_identity import contact_line, footer_line, name_pair
    db = str(tmp_path / "v9.db")
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE system_settings (key TEXT PRIMARY KEY, value_json TEXT, updated_at TEXT)")
    c.execute("INSERT INTO system_settings VALUES ('company_profile', ?, '')",
              (_json.dumps({"name": "允碩整合集創股份有限公司", "tax_id": "60575481"}),))
    c.commit()
    c.close()
    U.fill_company_profile_blanks(db)
    c = sqlite3.connect(db)
    filled = _json.loads(c.execute("SELECT value_json FROM system_settings").fetchone()[0])
    c.close()
    _set_setting("company_profile", {**filled, "locations": []})
    assert contact_line() == "統一編號 60575481 ｜ Tel: 04-3610-6566 ｜ info@miactw.com"
    assert contact_line("　｜　", "統一編號：", "電話：") == "統一編號：60575481　｜　電話：04-3610-6566　｜　info@miactw.com"
    assert footer_line() == ("MOTRIX Synergy Integration Corp. 允碩整合集創 ｜ info@miactw.com ｜ "
                             "Tel: 04-3610-6566 ｜ 統一編號: 60575481")
    assert name_pair() == "MOTRIX Synergy Integration Corp. 允碩整合集創"


def test_upgrade_alias_table_matches_company_identity():
    """升級工具判斷「已有值」用的別名，必須與 company_identity 實際讀的別名相同（否則補了也讀不到）。"""
    from core import upgrade as U
    from helpers import company_identity as ci
    for field, aliases in U._PROFILE_ALIASES.items():
        assert tuple(ci._PROFILE_ALIASES[field]) == tuple(aliases), field


@pytest.mark.parametrize("contact", ["Tel: 04-3610-6566｜info@miactw.com", "04-1234 ｜ a@b.c", "只有電話 02-9", "x@y.z", ""])
def test_upgrade_and_identity_split_contact_info_the_same_way(contact):
    from core import upgrade as U
    from helpers import company_identity as ci
    assert U._contact_info_parts({"contact_info": contact}) == ci.contact_info_parts({"contact_info": contact})


def test_top_level_settings_fields_reach_the_documents(client):
    """設定頁最上方「公司名稱／統一編號／聯絡方式」（name／tax_id／contact_info）只填這一區，單據也要印得出來。"""
    from helpers.settings import _set_setting
    from helpers.company_identity import location_identity
    _set_setting("company_profile", {"name": "新客戶股份有限公司", "tax_id": "12345678",
                                     "contact_info": "Tel: 02-2222-3333｜hi@new.example", "locations": []})
    ident = location_identity()
    assert (ident["company_name"], ident["tax_id"], ident["phone"], ident["email"]) ==         ("新客戶股份有限公司", "12345678", "02-2222-3333", "hi@new.example")


def test_location_fields_still_win_over_top_level(client):
    from helpers.settings import _set_setting
    from helpers.company_identity import location_identity
    _set_setting("company_profile", {"name": "舊名", "contact_info": "Tel: 1｜old@x.y",
                                     "locations": [{"id": "L1", "company_name": "據點名", "phone": "9", "email": "loc@x.y"}]})
    ident = location_identity()
    assert (ident["company_name"], ident["phone"], ident["email"]) == ("據點名", "9", "loc@x.y")
