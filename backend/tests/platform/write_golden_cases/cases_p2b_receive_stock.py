# -*- coding: utf-8 -*-
"""T85 一條龍 P2b：一站式到貨端點的金標案例。先用 setup 建一張已核准的材料申請，再記錄**成功形狀**（耗材登載：不需入庫權限、不寫序號）。
入庫／直送／超收／權限降級／撤銷與回滾由 tests/test_onepipe_p2b_receive_wizard_2026_11_14.py 逐項斷言。"""
import json

_QN = "MQ-GOLDEN-P2B"


def _setup(conn):
    order = {"itemId": "g1", "itemName": "金標材料", "quantity": 5, "unit": "台", "unitPrice": 100, "totalPrice": 500, "poDocCode": "PO-GOLD", "supplierId": None}
    data = {"dealTag": "已成案", "caseRecord": {"materialOrders": [order]}}
    conn.execute("INSERT OR REPLACE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, sales_person, assigned_user_ids)"
                 " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                 (_QN, "已送出", "金標客戶", "金標專案", 1000, 952, json.dumps(data), "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "", "[]"))
    conn.execute("DELETE FROM case_material_approvals WHERE quote_no=?", (_QN,))
    conn.execute("INSERT INTO case_material_approvals (quote_no, item_id, doc_code, status, received_on) VALUES (?,?,?,?,?)", (_QN, "g1", "MR-GOLD-1", "已核准", ""))


CASES = [
    {"key": "POST /api/quotations/{quote_no}/material-orders/{item_id}/receive-stock",
     "url": "/api/quotations/%s/material-orders/g1/receive-stock" % _QN,
     "body": {"qty": 2, "mode": "consumable", "receivedOn": "2026-11-10"}, "setup": _setup},
]
WAIVE = {}
