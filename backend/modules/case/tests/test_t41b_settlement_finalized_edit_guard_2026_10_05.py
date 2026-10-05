# -*- coding: utf-8 -*-
"""第 41 班補洞（第 40 班獨立探針 S4）：已完結的成本精算，非超級管理員不可重新修改（settlement_api 的 403）。
突變 S4＝拿掉 `existing_settlement.status == finalized and role != superadmin` 的檢查 ⇒ 原本沒有任何測試變紅。
"""
import json

import db
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W, _login  # noqa: F401
from modules.case.tests.test_settlement_finalize_integrity_2026_10_03 import URL, _status, case, page_payload  # noqa: F401
from modules.case.tests._t40_won import quote_is_won  # noqa: F401  第 40 班：完結要已成案（autouse）


def _saved():
    cn = db.get_db()
    try:
        return json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
    finally:
        cn.close()


def test_non_superadmin_cannot_edit_a_finalized_settlement_even_with_a_reason(case, make_user):
    c, h = case
    r = c.put(URL, json={"settlement": page_payload(c, h)}, headers=h)
    assert r.status_code == 200 and _status() == "finalized", r.text[:200]
    frozen = json.dumps(_saved()["settlement"], sort_keys=True, ensure_ascii=False)

    u, p = make_user(username="t41b_fin", role="finance")                        # 第42班：精算只限財務角色／superadmin；財務過得了案件與財務檢視閘，只缺 superadmin
    ah = _login(c, u, p)
    draft = page_payload(c, ah)
    draft["status"] = "draft"
    for st in (draft, page_payload(c, ah)):                                     # 重新開啟成草稿、再存成完結——都不行
        r = c.put(URL, json={"settlement": st, "reason": "想改一下"}, headers=ah)
        assert r.status_code == 403 and "超級管理員" in r.json()["detail"], (r.status_code, r.text[:200])
    assert _status() == "finalized"
    assert json.dumps(_saved()["settlement"], sort_keys=True, ensure_ascii=False) == frozen, "被拒絕的修改不可以動到凍結的精算"

    reopen = page_payload(c, h)                                                 # 對照：superadmin 帶理由仍可重新開啟
    reopen["status"] = "draft"
    assert c.put(URL, json={"settlement": reopen, "reason": "發票補開"}, headers=h).status_code == 200
    assert _status() == "draft"
