"""出貨單收件人的個資蒐集告知（稽核 D PN-M1；主持裁示 2026-09-26：比照手動輸入的聯絡人，要告知）。

需要 M03（出貨單端點）⇒ 放在模組裡、沿用原檔名（PLAYBOOK §B-11）。規則同報價單／完工單的告知：
只接受已存檔的收件人（不同 ⇒ 409）、鍵含姓名（換人要重新告知）、紀錄只蓋一次、寫稽核；讀與寫都照出貨單的案件權限。
"""
from helpers import privacy_notice as pn
from tests.test_privacy_notice_forms_2026_09_26 import _audit_count, _hdr, _insert_quote


def _note(client, h, quote_no, recipient):
    r = client.post("/api/shipping-notes", json={"quote_no": quote_no, "recipient": recipient,
                                                 "delivery_address": "台中市西屯區測試路 1 號"}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["note_no"]


def test_shipping_recipient_ack_only_for_the_saved_recipient(client, make_user):
    h = _hdr(client, make_user, username="pn_ship_root")
    _insert_quote("PN-SH-001")
    no = _note(client, h, "PN-SH-001", "王收件")
    base = f"/api/shipping-notes/{no}/privacy-notice"
    assert client.get(base, headers=h).json()["acks"] == {}
    assert client.post(base + "/ack", json={"subject": "別人"}, headers=h).status_code == 409
    r1 = client.post(base + "/ack", json={"subject": "王收件"}, headers=h)
    assert r1.status_code == 200 and r1.json()["created"] is True, r1.text
    assert r1.json()["ack"]["noticeHash"] == pn.notice_hash(pn.current_purpose_notice("contact"))
    r2 = client.post(base + "/ack", json={"subject": "王收件"}, headers=h)
    assert r2.json()["created"] is False and r2.json()["ack"] == r1.json()["ack"]
    assert client.get(base, headers=h).json()["acks"] == {"王收件": r1.json()["ack"]}
    assert pn.get_ack("shipping_recipient", f"{no}:王收件") == r1.json()["ack"]
    assert _audit_count("shipping_note.privacy_notice_ack", no) == 1
    assert client.post("/api/shipping-notes/NO-SUCH/privacy-notice/ack", json={"subject": "王收件"},
                       headers=h).status_code == 404


def test_changing_the_recipient_needs_a_new_notice(client, make_user):
    h = _hdr(client, make_user, username="pn_ship_chg")
    _insert_quote("PN-SH-002")
    no = _note(client, h, "PN-SH-002", "甲收件")
    base = f"/api/shipping-notes/{no}/privacy-notice"
    assert client.post(base + "/ack", json={"subject": "甲收件"}, headers=h).status_code == 200
    r = client.put(f"/api/shipping-notes/{no}", json={"quote_no": "PN-SH-002", "recipient": "乙收件"}, headers=h)
    assert r.status_code == 200, r.text
    acks = client.get(base, headers=h).json()["acks"]
    assert "乙收件" not in acks and "甲收件" in acks, acks          # 新收件人還沒有紀錄；畫面顯示「尚未記錄」
    assert client.post(base + "/ack", json={"subject": "甲收件"}, headers=h).status_code == 409


def test_shipping_recipient_privacy_endpoints_refuse_outsiders(client, make_user):
    h = _hdr(client, make_user, username="pn_ship_own")
    _insert_quote("PN-SH-003")
    no = _note(client, h, "PN-SH-003", "丙收件")
    # 外人＝不是案件成員、也沒有案件管理模組（權限同出貨單清單：guard_case_access(..., allow_module="case_manage")）
    u, p = make_user(username="pn_ship_out", role="engineer", modules=["dashboard"])
    out = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}
    base = f"/api/shipping-notes/{no}/privacy-notice"
    assert client.get(base, headers=out).status_code == 404   # M01-O1：看不到＝不存在（同一個 404）
    assert client.post(base + "/ack", json={"subject": "丙收件"}, headers=out).status_code == 403
    assert pn.get_ack("shipping_recipient", f"{no}:丙收件") in (None, {})
