"""T84：專案執行報告「二、材料申請」讀的是材料卡真正有的鍵（舊版讀 spec／status／eta——材料卡沒有這三個鍵，
規格永遠空白、狀態與預計到貨永遠「—」，也沒讀 materialOrders；ONEPIPE-PREWORK-FINDINGS §1b）。
只測純 Python 組裝（不需 Edge）。報告不得帶任何金額。"""
import json

from tests._requires import requires_module

pytestmark = requires_module("case", "本檔讀寫 M01（案件）的資料；M01 不在時沒有對象")

QNO = "MQ-T84-001"


def _seed(client, data_json, approvals=()):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (QNO, "已送出", "測試客戶", "測試專案", 100000, 95238, json.dumps(data_json, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"))
        for item_id, status, received_on in approvals:
            conn.execute(
                "INSERT INTO case_material_approvals (quote_no, item_id, status, received_on) VALUES (?,?,?,?)",
                (QNO, item_id, status, received_on))
        conn.commit()
    finally:
        conn.close()


def test_material_cards_show_spec_qty_unit_status_and_arrival_date(client):
    _seed(client, {"caseRecord": {"materials": [
        {"id": "m1", "name": "交換器", "model": "SG-2410", "qty": 3, "unit": "台", "ordered": True, "arrived": True,
         "poLink": {"key": "k", "arrivedOn": "2026-11-12"}},
        {"id": "m2", "name": "網路線", "model": "Cat6 305m", "qty": 2.0, "unit": "箱", "ordered": True, "arrived": False},
        {"id": "m3", "name": "機櫃", "qty": "1", "unit": "", "ordered": False, "arrived": False, "poLink": None},
        {"id": "m4", "name": "匯入料件", "spec": "舊鍵規格", "qty": 1, "unit": "個"},
    ]}})
    from pdf_gen import _project_execution_report_data, _build_project_execution_report_html
    data = _project_execution_report_data(QNO)
    by = {m["name"]: m for m in data["materials"]}
    assert by["交換器"] == {"name": "交換器", "spec": "SG-2410", "qty": "3 台", "status": "已到料", "arrivedOn": "2026-11-12"}
    assert by["網路線"]["spec"] == "Cat6 305m" and by["網路線"]["qty"] == "2 箱" and by["網路線"]["status"] == "已申購"
    assert by["匯入料件"]["spec"] == "舊鍵規格", "model 沒有時退回舊鍵 spec（匯入／手改資料）"
    assert by["機櫃"]["status"] == "待申購" and by["機櫃"]["arrivedOn"] == "" and by["機櫃"]["qty"] == "1"
    html = _build_project_execution_report_html(data)
    for needle in ("SG-2410", "Cat6 305m", "已到料", "已申購", "待申購", "2026-11-12", "到貨日"):
        assert needle in html, needle
    assert "預計到貨" not in html, "材料卡沒有預計到貨這個鍵，欄位已改成實際有的『到貨日』"


def test_material_orders_are_listed_with_approval_status_and_receipt_and_no_money(client):
    _seed(client, {"caseRecord": {"materials": [], "materialOrders": [
        {"itemId": "o1", "itemName": "攝影機", "quantity": 4, "unit": "台", "unitPrice": 98765, "totalPrice": 395060,
         "paidStatus": "paid", "paidAmount": 395060},
        {"itemId": "o2", "itemName": "支架", "quantity": 4, "unit": "組", "unitPrice": 424242, "totalPrice": 1696968,
         "paidStatus": "pending", "paidAmount": 0},
        {"itemId": "o3", "itemName": "舊單項目", "quantity": 1, "unit": "式", "unitPrice": 400000, "totalPrice": 400000,
         "paidStatus": "pending", "paidAmount": 0},
    ]}}, approvals=[("o1", "已核准", "2026-11-10"), ("o2", "簽核中", "")])
    from pdf_gen import _project_execution_report_data, _build_project_execution_report_html
    data = _project_execution_report_data(QNO)
    by = {o["name"]: o for o in data["materialOrders"]}
    assert by["攝影機"] == {"name": "攝影機", "qty": "4 台", "status": "已核准", "receivedOn": "2026-11-10"}
    assert by["支架"]["status"] == "簽核中" and by["支架"]["receivedOn"] == ""
    assert by["舊單項目"]["status"] == "（未走簽核）"
    html = _build_project_execution_report_html(data)
    for needle in ("材料申請單（簽核）", "攝影機", "已核准", "2026-11-10", "簽核中"):
        assert needle in html, needle
    for money in ("98765", "395060", "424242", "1696968", "400000"):
        assert money not in html and money not in json.dumps(data), "報告不得帶金額：%s" % money


def test_no_materials_at_all_keeps_the_empty_row_and_no_orders_table(client):
    _seed(client, {"caseRecord": {}})
    from pdf_gen import _project_execution_report_data, _build_project_execution_report_html
    data = _project_execution_report_data(QNO)
    assert data["materials"] == [] and data["materialOrders"] == []
    html = _build_project_execution_report_html(data)
    assert "無材料申請資料" in html and "材料申請單（簽核）" not in html
