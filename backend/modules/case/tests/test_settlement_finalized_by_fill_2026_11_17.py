# -*- coding: utf-8 -*-
"""完結精算時用戶端沒帶完結人／完結時間（舊頁面、腳本）⇒ 伺服器以操作者與當下時間補上；用戶端有帶的維持原值（結案報表「完結人：—」的根因之一）。"""
import json

import db
from modules.case.tests.test_settlement_finalize_recheck_2026_10_03 import URL, _finalize, _page_payload  # noqa: F401
from modules.case.tests.test_material_link_booking_2026_10_02 import _approved_po, _order, _won_case  # noqa: F401
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W, _ln, _mk, _submit  # noqa: F401
from modules.case.tests._t40_won import quote_is_won  # noqa: F401


def _saved():
    cn = db.get_db()
    try:
        return json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])["settlement"]
    finally:
        cn.close()


def test_missing_finalized_by_and_at_are_filled_by_the_server(W):
    c, h = W
    st = _page_payload(c, h)
    assert "finalizedBy" not in st and "finalizedAt" not in st
    assert _finalize(c, h, st).status_code == 200
    s = _saved()
    assert s["finalizedBy"] and s["finalizedAt"][:4] == "2026"


def test_values_sent_by_the_client_are_kept(W):
    c, h = W
    st = _page_payload(c, h)
    st.update(finalizedBy="頁面帶的人", finalizedAt="2026-08-02T17:30:00.000Z")
    assert _finalize(c, h, st).status_code == 200
    s = _saved()
    assert s["finalizedBy"] == "頁面帶的人" and s["finalizedAt"] == "2026-08-02T17:30:00.000Z"
