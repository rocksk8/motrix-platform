# -*- coding: utf-8 -*-
"""第 40 班：完結精算要求報價單已成案（deal_tag）。這些測試用的 W 夾具報價單沒有成案狀態，所以在要完結的測試檔裡 import 這個 autouse 夾具，
把報價單標為已成案（只改成案狀態，其餘資料不動）。"""
import json

import pytest

import db
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO


@pytest.fixture(autouse=True)
def quote_is_won(W):
    cn = db.get_db()
    try:
        d = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        d["dealTag"] = "已成案"
        cn.execute("UPDATE quotations SET data_json=?, deal_tag='已成案' WHERE quote_no=?", (json.dumps(d), NO))
        cn.commit()
    finally:
        cn.close()
