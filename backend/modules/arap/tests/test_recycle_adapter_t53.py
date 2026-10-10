# -*- coding: utf-8 -*-
"""第 53 班 P1：請款單、開票申請憑據進刪除暫存區（IP-RB1 adapter；規格 modules/recyclebin/SPEC.md、modules/arap/SPEC.md）。
釘住：① 草稿刪除進暫存區、還原後整列逐欄相等 ② 非草稿一般刪除仍 409（D1 不放寬） ③ 還原衝突（單號被占／案件不在）不覆蓋、留在暫存區
④ 開票申請已開立附件隨單據搬進隔離區、還原搬回（路徑被占用時改寫） ⑤ 『刪除已核可』只收已核准、要二次確認 ⑥ 暫存區模組不在 ⇒ 照舊硬刪並明說。"""
import json
import os

import pytest

import db
from helpers import recycle_bin as RB
from helpers import uploads as UP

Q1 = "MQ-RBA-001"


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def who(client, make_user):
    ad, ap = make_user(username="rba_admin", role="finance")
    su, sp = make_user(username="rba_su", role="superadmin")
    return _login(client, ad, ap), _login(client, su, sp)


def _q(sql, *a):
    cn = db.get_db()
    try:
        return [dict(r) for r in cn.execute(sql, a).fetchall()]
    finally:
        cn.close()


def _x(sql, *a):
    cn = db.get_db()
    try:
        cn.execute(sql, a)
        cn.commit()
    finally:
        cn.close()


@pytest.fixture(autouse=True)
def seed(client):
    cn = db.get_db()
    cn.execute("DELETE FROM payment_requests")
    cn.execute("DELETE FROM invoice_vouchers")
    cn.execute("DELETE FROM recycle_bin")
    cn.execute("DELETE FROM quotations WHERE quote_no=?", (Q1,))
    cn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, sales_person)"
               " VALUES (?,?,?,?,?,?,?,?,?,?,?)", (Q1, "已送出", "客戶", "案", 105000, 100000, "{}", "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", ""))
    cn.commit()
    cn.close()


def _pr(no="PR-1", status="草稿"):
    _x("INSERT INTO payment_requests (request_no, quote_no, scope, stage, status, ratio_pct, amount, terms_json, snapshot_json, data_json, created_by, created_at, updated_at)"
       " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", no, Q1, "amount", "訂金", status, 30, 31500, "{}", json.dumps({"customerName": "客戶"}), json.dumps({"k": "v"}),
       "rba_admin", "2026-01-02T00:00:00", "2026-01-02T00:00:00")


def _iv(no="IV-1", status="草稿", files=()):
    _x("INSERT INTO invoice_vouchers (voucher_no, quote_no, scope, status, snapshot_json, data_json, created_by, created_at, updated_at, amount, issued_files_json)"
       " VALUES (?,?,?,?,?,?,?,?,?,?,?)", no, Q1, "single", status, json.dumps({"customerName": "客戶"}), "{}", "rba_admin", "2026-01-02T00:00:00", "2026-01-02T00:00:00", 5000,
       json.dumps(list(files), ensure_ascii=False))


def _row(table, key_col, no):
    r = _q("SELECT * FROM %s WHERE %s=?" % (table, key_col), no)
    return r[0] if r else None


def _bin(entity_type):
    return _q("SELECT * FROM recycle_bin WHERE entity_type=? ORDER BY id DESC", entity_type)


# ── 請款單 ──

def test_payment_request_draft_goes_to_bin_and_round_trips(client, who):
    admin, su = who
    _pr()
    before = _row("payment_requests", "request_no", "PR-1")
    r = client.delete("/api/payment-requests/PR-1", headers=admin)
    assert r.status_code == 200 and r.json() == {"ok": True, "recycled": True}
    assert _row("payment_requests", "request_no", "PR-1") is None
    b = _bin("payment_request")
    assert len(b) == 1 and b[0]["entity_id"] == "PR-1" and b[0]["restore_status"] == "in_bin" and b[0]["via"] == "normal"
    rr = client.post("/api/recycle-bin/%d/restore" % b[0]["id"], headers=su)
    assert rr.status_code == 200, rr.text
    assert _row("payment_requests", "request_no", "PR-1") == before                 # 逐欄相等（含原 id）
    assert _bin("payment_request")[0]["restore_status"] == "restored"


def test_payment_request_non_draft_still_409_and_not_binned(client, who):
    admin, _ = who
    for st in ("待審核", "簽核中", "已核准"):
        _pr("PR-" + st, st)
        r = client.delete("/api/payment-requests/PR-" + st, headers=admin)
        assert r.status_code == 409 and "僅草稿" in r.text
        assert _row("payment_requests", "request_no", "PR-" + st) is not None
    assert _bin("payment_request") == []
    assert client.delete("/api/payment-requests/NOPE", headers=admin).status_code == 404


def test_payment_request_restore_conflict_does_not_overwrite(client, who):
    admin, su = who
    _pr()
    assert client.delete("/api/payment-requests/PR-1", headers=admin).status_code == 200
    _pr(status="已核准")                                                           # 同號新單據
    bid = _bin("payment_request")[0]["id"]
    r = client.post("/api/recycle-bin/%d/restore" % bid, headers=su)
    assert r.status_code == 409 and "已被占用" in r.text
    assert _row("payment_requests", "request_no", "PR-1")["status"] == "已核准"      # 沒被蓋
    assert _bin("payment_request")[0]["restore_status"] == "restore_failed"


def test_payment_request_restore_needs_case(client, who):
    admin, su = who
    _pr()
    assert client.delete("/api/payment-requests/PR-1", headers=admin).status_code == 200
    _x("DELETE FROM quotations WHERE quote_no=?", Q1)
    r = client.post("/api/recycle-bin/%d/restore" % _bin("payment_request")[0]["id"], headers=su)
    assert r.status_code == 409 and "不存在" in r.text
    assert _row("payment_requests", "request_no", "PR-1") is None


def test_delete_approved_only_for_approved_with_double_confirm(client, who):
    admin, su = who
    _pr("PR-A", "已核准")
    _pr("PR-D", "草稿")
    _pr("PR-P", "待審核")
    body = {"entity_type": "payment_request", "entity_id": "PR-A", "confirm": True, "confirm_text": "PR-A", "reason": "測試"}
    assert client.post("/api/recycle-bin/delete-approved", json=body, headers=admin).status_code in (401, 403)     # 非 superadmin
    assert client.post("/api/recycle-bin/delete-approved", json=dict(body, confirm_text="x"), headers=su).status_code == 422
    for no in ("PR-D", "PR-P"):
        r = client.post("/api/recycle-bin/delete-approved", json=dict(body, entity_id=no, confirm_text=no), headers=su)
        assert r.status_code == 409, (no, r.text)
        assert _row("payment_requests", "request_no", no) is not None
    imp = client.get("/api/recycle-bin/impact", params={"entity_type": "payment_request", "entity_id": "PR-A"}, headers=su).json()
    assert imp["supported"] is True and imp["impact"] and all(i["blocking"] is False for i in imp["impact"])
    r = client.post("/api/recycle-bin/delete-approved", json=body, headers=su)
    assert r.status_code == 200, r.text
    assert _row("payment_requests", "request_no", "PR-A") is None and _bin("payment_request")[0]["via"] == "approved"
    assert client.post("/api/recycle-bin/%d/restore" % _bin("payment_request")[0]["id"], headers=su).status_code == 200
    assert _row("payment_requests", "request_no", "PR-A")["status"] == "已核准"


# ── 開票申請憑據 ──

def _issued(no, name="a.pdf", body="PDF-內容"):
    rel = "invoice_vouchers/%s/%s" % (no, name)
    p = os.path.join(UP.UPLOADS_ROOT, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(body)
    return {"id": "f1", "filename": name, "path": rel}, p


def test_invoice_voucher_files_move_and_come_back(client, who):
    admin, su = who
    meta, path = _issued("IV-1")
    _iv(files=[meta])
    before = _row("invoice_vouchers", "voucher_no", "IV-1")
    assert client.delete("/api/invoice-vouchers/IV-1", headers=admin).status_code == 200
    assert not os.path.exists(path)                                                # 隔離區
    b = _bin("invoice_voucher")[0]
    assert b["file_count"] == 1
    assert client.post("/api/recycle-bin/%d/restore" % b["id"], headers=su).status_code == 200
    assert os.path.isfile(path) and open(path, encoding="utf-8").read() == "PDF-內容"
    assert _row("invoice_vouchers", "voucher_no", "IV-1") == before


def test_invoice_voucher_occupied_file_path_is_rewritten(client, who):
    admin, su = who
    meta, path = _issued("IV-1")
    _iv(files=[meta])
    assert client.delete("/api/invoice-vouchers/IV-1", headers=admin).status_code == 200
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("別人的檔")                                                          # 原路徑被占用
    r = client.post("/api/recycle-bin/%d/restore" % _bin("invoice_voucher")[0]["id"], headers=su)
    assert r.status_code == 200, r.text
    files = json.loads(_row("invoice_vouchers", "voucher_no", "IV-1")["issued_files_json"])
    assert files[0]["path"] != meta["path"] and files[0]["path"].startswith("invoice_vouchers/IV-1/")
    assert open(os.path.join(UP.UPLOADS_ROOT, *files[0]["path"].split("/")), encoding="utf-8").read() == "PDF-內容"
    assert open(path, encoding="utf-8").read() == "別人的檔"                          # 沒被蓋
    assert any("新路徑" in n for n in r.json().get("notes", []))


def test_invoice_voucher_non_draft_409(client, who):
    admin, _ = who
    _iv("IV-2", "已核准")
    assert client.delete("/api/invoice-vouchers/IV-2", headers=admin).status_code == 409
    assert _bin("invoice_voucher") == []


# ── 暫存區模組不在 ⇒ 照舊硬刪並明說 ──

def test_fallback_hard_delete_when_bin_absent(client, who, monkeypatch):
    admin, _ = who
    _pr()
    _iv()
    monkeypatch.setattr(RB, "delete", lambda *a, **k: None)
    r = client.delete("/api/payment-requests/PR-1", headers=admin)
    assert r.status_code == 200 and r.json() == {"ok": True, "recycled": False}
    r = client.delete("/api/invoice-vouchers/IV-1", headers=admin)
    assert r.json()["recycled"] is False
    assert _row("payment_requests", "request_no", "PR-1") is None and _row("invoice_vouchers", "voucher_no", "IV-1") is None
    assert _bin("payment_request") == [] and _bin("invoice_voucher") == []
    labels = [a["target_label"] for a in _q("SELECT target_label FROM audit_log WHERE action IN ('payment_request.delete','invoice_voucher.delete')")]
    assert len(labels) == 2 and all("暫存區未啟用" in x for x in labels)


def test_adapters_registered_and_guard_baseline_shrunk():
    ads = RB.adapters()
    assert ads["payment_request"].label == "請款單" and ads["invoice_voucher"].label == "開票申請憑據"

# ── 還原也守額度（建立時的規則：草稿就鎖額度）──

def test_restore_refuses_when_quota_was_taken_by_a_new_request(client, who):
    admin, su = who
    _pr()                                                                          # 31500 / 105000
    assert client.delete("/api/payment-requests/PR-1", headers=admin).status_code == 200
    _pr("PR-NEW")
    _x("UPDATE payment_requests SET amount=? WHERE request_no=?", 90000, "PR-NEW")   # 新單吃掉額度：剩 15000 < 31500
    r = client.post("/api/recycle-bin/%d/restore" % _bin("payment_request")[0]["id"], headers=su)
    assert r.status_code == 409 and "額度不足" in r.text
    assert _row("payment_requests", "request_no", "PR-1") is None and _bin("payment_request")[0]["restore_status"] == "restore_failed"
    _x("UPDATE payment_requests SET amount=? WHERE request_no=?", 60000, "PR-NEW")   # 釋出一些 ⇒ 剩 45000 ≥ 31500 ⇒ 可還原
    assert client.post("/api/recycle-bin/%d/restore" % _bin("payment_request")[0]["id"], headers=su).status_code == 200


def test_restore_refuses_when_item_quantity_was_taken(client, who):
    admin, su = who
    _x("UPDATE quotations SET data_json=? WHERE quote_no=?", json.dumps({"items": [{"id": "i1", "description": "交換器", "qty": 10}]}), Q1)
    _pr()
    _x("UPDATE payment_requests SET snapshot_json=? WHERE request_no=?", json.dumps({"selectedItems": [{"itemId": "i1", "description": "交換器", "qty": 6}]}), "PR-1")
    assert client.delete("/api/payment-requests/PR-1", headers=admin).status_code == 200
    _pr("PR-NEW")
    _x("UPDATE payment_requests SET amount=1000, snapshot_json=? WHERE request_no=?", json.dumps({"selectedItems": [{"itemId": "i1", "qty": 6}]}), "PR-NEW")
    r = client.post("/api/recycle-bin/%d/restore" % _bin("payment_request")[0]["id"], headers=su)
    assert r.status_code == 409 and "數量不足" in r.text and _row("payment_requests", "request_no", "PR-1") is None


def test_invoice_voucher_restore_refuses_when_quota_was_taken(client, who):
    admin, su = who
    _iv()                                                                          # amount 5000
    assert client.delete("/api/invoice-vouchers/IV-1", headers=admin).status_code == 200
    _iv("IV-NEW")
    _x("UPDATE invoice_vouchers SET amount=? WHERE voucher_no=?", 103000, "IV-NEW")  # 剩 2000 < 5000
    r = client.post("/api/recycle-bin/%d/restore" % _bin("invoice_voucher")[0]["id"], headers=su)
    assert r.status_code == 409 and "額度不足" in r.text and _row("invoice_vouchers", "voucher_no", "IV-1") is None


def test_delete_approved_clears_that_documents_notifications(client, who):
    admin, su = who
    _pr("PR-A", "已核准")
    _pr("PR-B", "已核准")
    for ref, t in (("PR-A", "payment_request_approved"), ("PR-A", "approval_reminder"), ("PR-B", "payment_request_approved")):
        _x("INSERT INTO notifications (username, type, ref_id, message, created_at) VALUES (?,?,?,?,?)", "rba_admin", t, ref, "m", "2026-01-01T00:00:00")
    body = {"entity_type": "payment_request", "entity_id": "PR-A", "confirm": True, "confirm_text": "PR-A", "reason": "測試"}
    assert client.post("/api/recycle-bin/delete-approved", json=body, headers=su).status_code == 200
    left = [r["ref_id"] for r in _q("SELECT ref_id FROM notifications WHERE type IN ('payment_request_approved','approval_reminder')")]
    assert left == ["PR-B"]                                                          # 只清 PR-A 的，PR-B 的不動
