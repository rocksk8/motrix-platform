# -*- coding: utf-8 -*-
"""叫料審核的寫入閘（31-C S3）：`case-record` 後門關閉、新列／實質變更／刪除規則、物流旗標只能對著已核准的叫料單、已付欄位閘、$0 叫料單、
後盾（`save_quotation_json`）與靜態守門 G-M1。

走真實 HTTP。案件 `data_json.caseRecord` 先種：兩筆舊單叫料（沒有審核單）＋兩筆物流項目。每個「被拒」都驗：資料庫值沒變、**其餘欄位照存**、
回應 `rejected[]` 有逐項原因。
"""
import json
import re
from pathlib import Path

import pytest

from tests._requires import skip_module_unless

skip_module_unless("case", "本檔全部是 M01 的叫料審核")

NO = "MQ-MATG-001"



_MAKE_USER_DEFAULT_ROLE = "superadmin"      # 第42班：財務／出納不再有 admin 直通；舊題的「預設 admin 操作者」改用 superadmin（見 conftest.make_user）


@pytest.fixture(autouse=True)
def _po_rule_off(monkeypatch):
    """本檔測的是別的規則；33-M1「新申請必須帶採購單／送審必須有已核准採購單」另有 test_material_po_required_2026_10_03.py。"""
    from modules.case import material_approval as _MA
    monkeypatch.setattr(_MA, "PO_REQUIRED", False)

def _q(sql, args=()):
    import db
    conn = db.get_db()
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _x(sql, args=()):
    import db
    conn = db.get_db()
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _uid(username):
    return _q("SELECT id FROM users WHERE username=?", (username,))[0]["id"]


def _order(item, name="交換器", qty=2, price=1500, **kw):
    o = {"itemId": item, "itemName": name, "quantity": qty, "unit": "台", "unitPrice": price, "totalPrice": qty * price,
         "paidStatus": "pending", "paidAmount": 0, "paidDate": "", "notes": "", "supplierId": 1}
    o.update(kw)
    return o


def _seed(assigned=()):
    cr = {"materialOrders": [_order("L1"), _order("L2", "路由器", 1, 5000)],
          "materials": [{"id": 101, "name": "交換器", "qty": 2, "ordered": False, "arrived": False, "devices": []},
                        {"id": 102, "name": "路由器", "qty": 1, "ordered": True, "arrived": False, "devices": []}],
          "contract": {"note": "原合約備註"}}
    _x("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
       " deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
       (NO, "已送出", "閘客", "閘專案", 100000, 95238, json.dumps({"dealTag": "已成案", "caseRecord": cr}), "2026-01-01T00:00:00",
        "2026-01-01T00:00:00", "已成案", "", json.dumps(list(assigned))))


def _cr():
    return json.loads(_q("SELECT data_json FROM quotations WHERE quote_no=?", (NO,))[0]["data_json"])["caseRecord"]


def _flow(tiers):
    _x("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
       ("unified_approval_flow", json.dumps({"tiers": tiers, "includeSubmitterManagerTier": False}), "2026-01-01T00:00:00"))


def _status(item):
    r = _q("SELECT status FROM case_material_approvals WHERE quote_no=? AND item_id=?", (NO, item))
    return r[0]["status"] if r else ""


def _put_cr(client, h, **changes):
    """模擬案件頁整包存檔：以目前資料庫的 caseRecord 為底，套上 changes（整個鍵取代）。"""
    cr = _cr()
    cr.update(changes)
    return client.patch("/api/quotations/%s/case-record" % NO, json={"case_record": cr}, headers=h)


@pytest.fixture
def world(client, make_user):
    eng, ep = make_user(username="mg_eng", role="sales")                       # 案件成員，非 admin、無 project_manage
    adm, ap = make_user(username="mg_adm", role="superadmin")
    boss, bp = make_user(username="mg_boss", role="sales")
    _seed(assigned=[_uid(eng)])
    return {"eng": _login(client, eng, ep), "adm": _login(client, adm, ap), "boss": _login(client, boss, bp), "boss_name": boss}


def test_an_unrelated_save_is_untouched_and_creates_no_approval_rows(client, world):
    r = _put_cr(client, world["eng"], contract={"note": "改了合約備註"})
    assert r.status_code == 200 and "rejected" not in r.json(), r.text
    cr = _cr()
    assert cr["contract"] == {"note": "改了合約備註"} and cr["materialOrders"] == [_order("L1"), _order("L2", "路由器", 1, 5000)]
    assert _q("SELECT COUNT(*) AS n FROM case_material_approvals")[0]["n"] == 0            # 舊單沒被碰


def test_a_plain_member_cannot_change_orders_through_case_record_but_the_rest_saves(client, world):
    new = _cr()["materialOrders"] + [_order("N1", "新品", 1, 100)]
    new[0]["unitPrice"], new[0]["totalPrice"] = 1, 2                                         # 同時偷改舊單單價
    new[1]["paidStatus"], new[1]["paidAmount"], new[1]["paidDate"] = "paid", 5000, "2031-03-05"   # 並標記已付
    r = _put_cr(client, world["eng"], materialOrders=new, contract={"note": "同一次存檔的其他欄位"})
    assert r.status_code == 200, r.text
    rej = r.json()["rejected"]
    assert {(x["itemId"], x["code"]) for x in rej} == {("L1", "no_permission"), ("L2", "no_permission"), ("N1", "no_permission")}, rej
    cr = _cr()
    assert cr["materialOrders"] == [_order("L1"), _order("L2", "路由器", 1, 5000)]           # 叫料完全沒變
    assert cr["contract"] == {"note": "同一次存檔的其他欄位"}                                     # 其餘照存
    assert _q("SELECT COUNT(*) AS n FROM case_material_approvals")[0]["n"] == 0


def test_admin_adds_validates_and_substantive_edits_follow_the_approval_state(client, world):
    new = _cr()["materialOrders"] + [_order("N1", "新品", 1, 100)]
    bad = _order("N2", "壞列", 2, 100)
    bad["totalPrice"] = 999                                                                  # 小計對不上
    r = _put_cr(client, world["adm"], materialOrders=new + [bad])
    assert r.status_code == 200, r.text
    assert [(x["itemId"], x["code"]) for x in r.json()["rejected"]] == [("N2", "invalid")]
    assert [o["itemId"] for o in _cr()["materialOrders"]] == ["L1", "L2", "N1"]
    assert _status("N1") == "草稿" and _q("SELECT doc_code FROM case_material_approvals WHERE item_id='N1'")[0]["doc_code"].startswith("MO-")
    # 舊單被實質編輯 ⇒ 建草稿（要先送審）
    edit = _cr()["materialOrders"]
    edit[0]["unitPrice"], edit[0]["totalPrice"] = 1600, 3200
    assert "rejected" not in _put_cr(client, world["adm"], materialOrders=edit).json()
    assert _cr()["materialOrders"][0]["unitPrice"] == 1600 and _status("L1") == "草稿"
    # 送審（沒設簽核層 ⇒ 已核准）→ 再改價 ⇒ 回草稿、版本 +1
    _flow([])
    assert client.post("/api/quotations/%s/material-orders/L1/submit" % NO, headers=world["adm"]).json()["status"] == "已核准"
    edit = _cr()["materialOrders"]
    edit[0]["unitPrice"], edit[0]["totalPrice"] = 1700, 3400
    assert "rejected" not in _put_cr(client, world["adm"], materialOrders=edit).json()
    row = _q("SELECT status, version, content_hash FROM case_material_approvals WHERE item_id='L1'")[0]
    assert (row["status"], row["version"], row["content_hash"]) == ("草稿", 2, "")
    # 審核中的叫料單不可改內容（該列維持原值；其他列照存）
    _flow([{"order": 0, "approvers": [{"username": world["boss_name"], "displayName": "主管"}]}])
    assert client.post("/api/quotations/%s/material-orders/L1/submit" % NO, headers=world["adm"]).json()["status"] == "待審核"
    edit = _cr()["materialOrders"]
    edit[0]["unitPrice"], edit[0]["totalPrice"] = 9, 18
    edit[1]["notes"] = "備註可以改"
    r = _put_cr(client, world["adm"], materialOrders=edit)
    assert [(x["itemId"], x["code"]) for x in r.json()["rejected"]] == [("L1", "in_approval")]
    cr = _cr()["materialOrders"]
    assert cr[0]["unitPrice"] == 1700 and cr[1]["notes"] == "備註可以改"


def test_deleting_rows_follows_the_state(client, world):
    _flow([])
    new = _cr()["materialOrders"] + [_order("N1", "新品", 1, 100)]
    _put_cr(client, world["adm"], materialOrders=new)
    assert client.post("/api/quotations/%s/material-orders/L1/submit" % NO, headers=world["adm"]).status_code == 200      # L1 已核准
    keep = [o for o in _cr()["materialOrders"] if o["itemId"] not in ("L1", "N1", "L2")]                                     # 全部刪掉
    r = _put_cr(client, world["adm"], materialOrders=keep)
    assert [(x["itemId"], x["code"]) for x in r.json()["rejected"]] == [("L1", "delete_blocked")]
    assert [o["itemId"] for o in _cr()["materialOrders"]] == ["L1"]                          # 已核准的留著；舊單 L2 與草稿 N1 刪掉了
    assert _status("N1") == "" and _status("L1") == "已核准"                                  # 草稿的審核單跟著刪


def test_physical_flags_tick_only_against_an_approved_order_and_arrival_needs_a_receipt(client, world):
    mats = _cr()["materials"]
    mats[0]["ordered"] = True                                                                 # 沒有連結 ⇒ 被拒
    r = _put_cr(client, world["eng"], materials=mats, contract={"note": "x"})
    assert [(x["itemId"], x["field"], x["code"]) for x in r.json()["rejected"]] == [("101", "ordered", "order_not_approved")]
    assert _cr()["materials"][0]["ordered"] is False and _cr()["contract"] == {"note": "x"}
    # 連結到一張已核准的叫料單 ⇒ 可以
    _flow([])
    assert client.post("/api/quotations/%s/material-orders/L1/submit" % NO, headers=world["adm"]).status_code == 200
    mats = _cr()["materials"]
    mats[0].update({"ordered": True, "orderItemId": "L1"})
    assert "rejected" not in _put_cr(client, world["eng"], materials=mats).json()
    assert _cr()["materials"][0]["ordered"] is True and _cr()["materials"][0]["orderItemId"] == "L1"
    # 到料：沒有到貨確認 ⇒ 被拒，序號也不進來
    mats = _cr()["materials"]
    mats[0].update({"arrived": True, "devices": [{"sn": "SN-1", "mac": "AA"}]})
    r = _put_cr(client, world["eng"], materials=mats)
    assert [(x["field"], x["code"]) for x in r.json()["rejected"]] == [("arrived", "receipt_missing")]
    assert _cr()["materials"][0]["arrived"] is False and _cr()["materials"][0]["devices"] == []
    # 記錄到貨確認後 ⇒ 可以
    assert client.post("/api/quotations/%s/material-orders/L1/receive" % NO, json={"receivedOn": "2031-03-05"}, headers=world["eng"]).status_code == 200
    assert "rejected" not in _put_cr(client, world["eng"], materials=mats).json()
    assert _cr()["materials"][0]["arrived"] is True and _cr()["materials"][0]["devices"] == [{"sn": "SN-1", "mac": "AA"}]
    # 連到不存在的叫料單 ⇒ 被拒
    mats = _cr()["materials"]
    mats[1]["orderItemId"] = "NOPE"
    assert [(x["field"], x["code"]) for x in _put_cr(client, world["eng"], materials=mats).json()["rejected"]] == [("orderItemId", "bad_link")]


def test_new_orders_must_name_a_supplier_but_legacy_rows_are_not_forced(client, world, monkeypatch):
    """設計 §3.4／Q2：新建的叫料單必填 `supplierId`（匯款申請憑它帶出供應商）；舊單不溯及既往（開匯款申請時再選）。旗標關掉時不擋。"""
    from modules.case import material_approval as MA
    assert MA.SUPPLIER_REQUIRED_ON_NEW is True
    new = _cr()["materialOrders"] + [_order("S1", "有供應商", 1, 100), _order("S2", "沒供應商", 1, 100, supplierId=None), _order("S3", "壞供應商", 1, 100, supplierId="x")]
    r = _put_cr(client, world["adm"], materialOrders=new)
    assert sorted((x["itemId"], x["field"], x["code"]) for x in r.json()["rejected"]) == [("S2", "supplierId", "supplier_required"), ("S3", "supplierId", "supplier_required")]
    assert [o["itemId"] for o in _cr()["materialOrders"]] == ["L1", "L2", "S1"]               # 只拒有問題的；既有的列不重新檢查供應商
    assert _status("S1") == "草稿" and _status("S2") == ""                                      # 被拒的沒有留審核單
    monkeypatch.setattr(MA, "SUPPLIER_REQUIRED_ON_NEW", False)
    new = _cr()["materialOrders"] + [_order("S4", "旗標關", 1, 100, supplierId=None)]
    assert "rejected" not in _put_cr(client, world["adm"], materialOrders=new).json()


def test_zero_amount_order_goes_through_the_same_flow(client, world):
    _flow([])
    new = _cr()["materialOrders"] + [_order("Z0", "客供料", 1, 0)]
    assert "rejected" not in _put_cr(client, world["adm"], materialOrders=new).json()
    assert _cr()["materialOrders"][-1]["totalPrice"] == 0 and _status("Z0") == "草稿"
    assert client.post("/api/quotations/%s/material-orders/Z0/submit" % NO, headers=world["adm"]).json()["status"] == "已核准"


def test_paid_fields_are_locked_by_default_and_open_only_when_the_flag_is_off(client, world, monkeypatch):
    """匯款切片落地後預設鎖（`PAID_VIA_REMITTANCE_ONLY=True`）；旗標關掉時才照舊可登記（守門題兩個值都測，並釘死預設值）。"""
    from modules.case import material_approval as MA
    assert MA.PAID_VIA_REMITTANCE_ONLY is True                                               # 31-C 不能帶著 False 出貨
    monkeypatch.setattr(MA, "PAID_VIA_REMITTANCE_ONLY", False)
    edit = _cr()["materialOrders"]
    edit[1].update({"paidStatus": "paid", "paidAmount": 5000, "paidDate": "2031-03-05"})
    assert "rejected" not in _put_cr(client, world["adm"], materialOrders=edit).json()      # 旗標關：照舊可登記
    assert _cr()["materialOrders"][1]["paidStatus"] == "paid"
    monkeypatch.setattr(MA, "PAID_VIA_REMITTANCE_ONLY", True)
    edit = _cr()["materialOrders"]
    edit[0].update({"paidStatus": "paid", "paidAmount": 3000, "paidDate": "2031-03-06"})     # 舊單 L1 也不能直接標已付
    edit.append(_order("N9", "新品", 1, 100, paidStatus="paid", paidAmount=100, paidDate="2031-03-06"))
    r = _put_cr(client, world["adm"], materialOrders=edit)
    codes = sorted((x["itemId"], x["field"], x["code"]) for x in r.json()["rejected"])
    assert ("L1", "paidStatus", "paid_via_remittance") in codes and ("N9", "paidStatus", "paid_via_remittance") in codes, codes
    cr = _cr()["materialOrders"]
    assert cr[0]["paidStatus"] == "pending" and [o for o in cr if o["itemId"] == "N9"][0]["paidStatus"] == "pending"
    assert cr[1]["paidStatus"] == "paid"                                                     # 已付的歷史不動


def test_unpaid_rows_saved_back_with_null_paid_fields_are_not_a_paid_edit(client, world):
    """前端存檔時未付款的 paidDate 送 null、資料庫存空字串：這不是「改已付欄位」，不可被旗標誤擋。"""
    edit = _cr()["materialOrders"]
    for o in edit:
        o["paidDate"] = None
    edit[0]["notes"] = "只改備註"
    r = _put_cr(client, world["adm"], materialOrders=edit)
    assert r.status_code == 200 and "rejected" not in r.json(), r.text
    assert _cr()["materialOrders"][0]["notes"] == "只改備註"


def test_dedicated_endpoint_reports_rejections_and_invoice_date_is_frozen_in_approval(client, world):
    _flow([{"order": 0, "approvers": [{"username": world["boss_name"], "displayName": "主管"}]}])
    assert client.post("/api/quotations/%s/material-orders/L1/submit" % NO, headers=world["adm"]).json()["status"] == "待審核"
    rows = _cr()["materialOrders"]
    rows[0]["unitPrice"], rows[0]["totalPrice"] = 7, 14
    r = client.patch("/api/quotations/%s/material-orders" % NO, json={"materialOrders": rows}, headers=world["adm"])
    assert r.status_code == 200, r.text
    assert [(x["itemId"], x["code"]) for x in r.json()["rejected"]] == [("L1", "in_approval")]
    assert _cr()["materialOrders"][0]["unitPrice"] == 1500
    r = client.patch("/api/quotations/%s/material-orders/L1/invoice-date" % NO, json={"invoiceDate": "2031-04-01"}, headers=world["adm"])
    assert r.status_code == 409
    rows = _cr()["materialOrders"]
    rows[0]["invoiceDate"] = "2031-04-01"                                                    # 案件存檔路徑也一樣：審核中不可改發票日
    r = _put_cr(client, world["adm"], materialOrders=rows)
    assert [(x["itemId"], x["field"], x["code"]) for x in r.json()["rejected"]] == [("L1", "invoiceDate", "in_approval")]
    assert _cr()["materialOrders"][0].get("invoiceDate", "") == ""
    r = client.patch("/api/quotations/%s/material-orders/L2/invoice-date" % NO, json={"invoiceDate": "2031-04-01"}, headers=world["adm"])
    assert r.status_code == 200                                                              # 舊單的發票日照舊可登


def test_backstop_in_save_quotation_json_is_idempotent_and_catches_other_writers(client, world, monkeypatch):
    """沒有呼叫端點層的閘，直接走寫入漏斗 `save_quotation_json` 也繞不過去（後盾）；而已過閘的資料再過一次不會有改動。"""
    import db
    from modules.case import material_guard as MG
    from modules.case import material_approval as MA
    from core.txn import begin_write
    from modules.case.quotations import save_quotation_json
    monkeypatch.setattr(MA, "PAID_VIA_REMITTANCE_ONLY", True)
    conn = db.get_db()
    try:
        begin_write(conn)                                                                    # 先拿寫鎖再讀 data_json（save_quotation_json 的 lost-update 守門）
        data = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        data["caseRecord"]["materialOrders"][0].update({"paidStatus": "paid", "paidAmount": 3000, "paidDate": "2031-03-06"})
        data["caseRecord"]["materials"][0]["ordered"] = True
        save_quotation_json(conn, NO, data)                                                  # 沒有 actor：系統路徑，但不變式照樣強制
        conn.commit()
        saved = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])["caseRecord"]
        assert saved["materialOrders"][0]["paidStatus"] == "pending" and saved["materials"][0]["ordered"] is False
        again = json.loads(json.dumps(saved))
        begin_write(conn)
        assert MG.enforce(conn, NO, {"caseRecord": again}) == [] and again == saved          # 冪等
        conn.rollback()
    finally:
        conn.close()


def test_static_guard_g_m1_only_the_gate_writes_orders_and_flags():
    """G-M1：`modules/case`（非測試）裡寫 `materialOrders` 的地方只准是閘與專屬端點（且專屬端點寫入後馬上過閘）；沒有任何地方指派 `ordered`／`arrived`；
    寫入漏斗 `save_quotation_json` 一定呼叫閘。"""
    root = Path(__file__).resolve().parents[1]
    allowed_files = {"material_guard.py", "material_orders.py", "recognition.py", "material_approvals.py"}
    hits = {}
    for p in root.rglob("*.py"):
        rel = p.relative_to(root).as_posix()
        if rel.startswith("tests/") or "/tests/" in rel or "migrations/" in rel:
            continue
        txt = p.read_text(encoding="utf-8")
        if re.search(r"""materialOrders""", txt) and p.name not in allowed_files:
            # 只准在註解／字串說明裡提到（不可有指派）
            assert not re.search(r"""\[["']materialOrders["']\]\s*=|setdefault\(["']materialOrders["']|["']materialOrders["']\s*:\s*\[""", txt), rel
        hits[rel] = txt
    for rel, txt in hits.items():
        assert not re.search(r"""\[["'](ordered|arrived)["']\]\s*=""", txt), "後端不應指派物流旗標：" + rel
    mo = hits["api/material_orders.py"]
    i = mo.index('data["caseRecord"]["materialOrders"] = ')
    assert "MG.enforce(" in mo[i:i + 600], "專屬端點寫入叫料後必須馬上過閘"
    qj = hits["quotations.py"]
    j = qj.index("def save_quotation_json")
    assert "_mg.enforce(" in qj[j:j + 1800], "寫入漏斗必須呼叫叫料閘"
