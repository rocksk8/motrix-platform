# -*- coding: utf-8 -*-
"""第 53 班 P1：外包工班的刪除暫存區 adapter（承攬商派發、承攬商匯款申請）。

重點：① 還原來回一致（單據列＋子表列＋附件逐欄相等）② 刪除規則不放寬（審核中／已核准／已有匯款申請、非草稿仍 409，沒有任何東西進暫存區）
③ 還原衝突（單號被占用、承攬商／報價單不見、勞報單不見）④ 列表遮罩（JSON 字串裡的銀行帳號）⑤ 暫存區模組缺席 ⇒ 照舊刪並明說 ⑥ 『刪除已核可』走暫存區的最高管理者入口。
"""
import itertools
import json
import os

import pytest

import db
from core import registry
from helpers import recycle_bin as RB
from helpers import uploads as UP
from modules.payroll.tests.test_payslip_person_link_t48 import _auth, _login, _person, _q, _x   # noqa: F401

_N = itertools.count(1)
Q = "MQ-RB53-001"


@pytest.fixture
def who(client, make_user):
    su, sp = make_user(username="rb53_su", role="superadmin")
    ad, ap = make_user(username="rb53_admin", role="admin")
    return _auth(_login(client, su, sp)), _auth(_login(client, ad, ap))


def _quotation(quote=Q):
    _x("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag,"
       " sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (quote, "已送出", "客", "案", 1, 1, "{}", "2031-01-01T00:00:00", "2031-01-01T00:00:00", "已成案", "", "[]"))


def _dispatch(client, h, quote=Q, personnel=None):
    _quotation(quote)
    r = client.post("/api/vendor-contractors", headers=h, json={"name": "廠商RB%d" % next(_N), "data": {}})
    assert r.status_code == 201, r.text
    body = {"quote_no": quote, "vendor_id": r.json()["id"], "status": "completed", "payable_date": "2031-08-01", "personnel_json": personnel or [],
            "items_json": [{"description": "測試品項", "qty": 1, "unit": "式", "unitPrice": 10000, "amount": 10000}]}
    r = client.post("/api/contractor-dispatches", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"], body["vendor_id"]


def _voucher(client, h, did):
    r = client.post("/api/contractor-vouchers", headers=h, json={"dispatch_id": did})
    assert r.status_code == 201, r.text
    return r.json()["voucher_no"]


def _row(table, key, val):
    rows = _q("SELECT * FROM %s WHERE %s=?" % (table, key), (val,))
    return rows[0] if rows else None


def _put_files(did, names=("a.pdf", "b.pdf"), col="files_json"):
    metas = []
    for n in names:
        rel = "contractor_dispatches/%s/%s" % (did, n)
        p = os.path.join(UP.UPLOADS_ROOT, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(b"%PDF-1.4 " + n.encode())
        metas.append({"id": n[:1], "filename": n, "path": rel, "size": 12, "mime": "application/pdf", "uploadedBy": "t", "uploadedAt": "2031-01-01"})
    _x("UPDATE contractor_dispatches SET %s=? WHERE id=?" % col, (json.dumps(metas), did))
    return metas


def _abs(rel):
    return os.path.join(UP.UPLOADS_ROOT, *rel.split("/"))


def _restore(client, su, bin_id):
    return client.post("/api/recycle-bin/%s/restore" % bin_id, headers=su)


# ── 派發 ──────────────────────────────────────────────────────────────────────
def test_dispatch_delete_goes_to_bin_and_restore_round_trips_row_children_and_files(client, who):
    su, ad = who
    pid = _person("王小明")
    did, _ = _dispatch(client, ad, personnel=[{"id": pid, "name": "王小明", "amount": 500, "note": "x"}])
    _put_files(did)
    _x("INSERT INTO payslips (slip_no, contractor_id, contractor_name, status, created_at, updated_at) VALUES ('PS-RB-1', ?, '王小明', '草稿', '2031-01-01', '2031-01-01')", (pid,))
    _x("INSERT INTO payslip_dispatch_links (slip_no, dispatch_id, voucher_no, note, created_by, created_at) VALUES ('PS-RB-1', ?, '', 'n', 'u', '2031-01-01')", (did,))
    _x("INSERT INTO dispatch_file_delete_requests (dispatch_id, file_id, quote_no, filename, reason) VALUES (?, 'a', ?, 'a.pdf', 'r')", (did, Q))
    before = (_row("contractor_dispatches", "id", did), _q("SELECT * FROM payslip_dispatch_links WHERE dispatch_id=?", (did,)), _q("SELECT * FROM dispatch_file_delete_requests WHERE dispatch_id=?", (did,)))
    metas = json.loads(before[0]["files_json"])

    r = client.delete("/api/contractor-dispatches/%d" % did, headers=ad)
    assert r.status_code == 200 and r.json()["binned"] is True, r.text
    bid = r.json()["binId"]
    assert _row("contractor_dispatches", "id", did) is None
    assert _q("SELECT * FROM payslip_dispatch_links WHERE dispatch_id=?", (did,)) == [] and _q("SELECT * FROM dispatch_file_delete_requests WHERE dispatch_id=?", (did,)) == []
    assert all(not os.path.exists(_abs(m["path"])) for m in metas), "附件已搬進隔離區"

    assert _restore(client, ad, bid).status_code == 403, "只有最高管理者能還原"
    rr = _restore(client, su, bid)
    assert rr.status_code == 200, rr.text
    after = (_row("contractor_dispatches", "id", did), _q("SELECT * FROM payslip_dispatch_links WHERE dispatch_id=?", (did,)), _q("SELECT * FROM dispatch_file_delete_requests WHERE dispatch_id=?", (did,)))
    assert after == before, "還原後單據列、勞報單連結、附件刪除申請逐欄相同"
    assert all(os.path.exists(_abs(m["path"])) for m in metas)


def test_dispatch_rules_are_not_relaxed_and_nothing_is_binned(client, who):
    su, ad = who
    d1, _ = _dispatch(client, ad)
    _x("UPDATE contractor_dispatches SET approval_status='已核准' WHERE id=?", (d1,))
    for st in ("待審核", "簽核中", "已核准"):
        _x("UPDATE contractor_dispatches SET approval_status=? WHERE id=?", (st, d1))
        for h in (ad, su):
            r = client.delete("/api/contractor-dispatches/%d" % d1, headers=h)
            assert r.status_code == 409, (st, r.text)
    d2, _ = _dispatch(client, ad, quote="MQ-RB53-002")
    no = _voucher(client, su, d2)
    assert client.delete("/api/contractor-dispatches/%d" % d2, headers=ad).status_code == 409, "有匯款申請"
    _x("UPDATE contractor_payment_vouchers SET voided_at='2031-01-01', status='已作廢' WHERE voucher_no=?", (no,))
    r = client.delete("/api/contractor-dispatches/%d" % d2, headers=ad)
    assert r.status_code == 409 and "作廢" in r.text, "作廢的申請仍留存紀錄（原本會在 FK 上 500）"
    assert _q("SELECT COUNT(*) n FROM recycle_bin")[0]["n"] == 0
    assert _row("contractor_dispatches", "id", d1) and _row("contractor_dispatches", "id", d2)


def test_approved_dispatch_only_through_superadmin_bin_entry_with_impact(client, who):
    su, ad = who
    did, _ = _dispatch(client, ad)
    _x("UPDATE contractor_dispatches SET approval_status='已核准', completion_status='已核准' WHERE id=?", (did,))
    imp = client.get("/api/recycle-bin/impact?entity_type=contractor_dispatch&entity_id=%d" % did, headers=su).json()
    assert imp["supported"] is True and {i["kind"] for i in imp["impact"]} >= {"approved", "completion"}
    body = {"entity_type": "contractor_dispatch", "entity_id": str(did), "confirm": True, "confirm_text": str(did), "reason": "測試"}
    assert client.post("/api/recycle-bin/delete-approved", headers=ad, json=body).status_code in (401, 403)
    r = client.post("/api/recycle-bin/delete-approved", headers=su, json=body)
    assert r.status_code == 200, r.text
    assert _row("contractor_dispatches", "id", did) is None
    assert _restore(client, su, r.json()["bin_id"]).status_code == 200
    assert _row("contractor_dispatches", "id", did)["approval_status"] == "已核准", "還原原樣（含核准狀態）"
    no = _voucher(client, su, did)
    assert client.get("/api/recycle-bin/impact?entity_type=contractor_dispatch&entity_id=%d" % did, headers=su).json()["supported"] is False
    r = client.post("/api/recycle-bin/delete-approved", headers=su, json=body)
    assert r.status_code in (409, 400) and _row("contractor_dispatches", "id", did), r.text


def test_dispatch_restore_conflicts(client, who):
    su, ad = who
    did, _ = _dispatch(client, ad)
    code = "DP-20311001-0001"
    _x("UPDATE contractor_dispatches SET doc_code=? WHERE id=?", (code, did))
    bid = client.delete("/api/contractor-dispatches/%d" % did, headers=ad).json()["binId"]
    d2, _ = _dispatch(client, ad, quote="MQ-RB53-003")
    _x("UPDATE contractor_dispatches SET doc_code=? WHERE id=?", (code, d2))                  # 取號是 MAX+1：刪掉最後一張後，新單會拿到同一個號
    r = _restore(client, su, bid)
    assert r.status_code == 200 and r.json()["renumbered"] is True and any(code in n for n in r.json()["notes"]), r.text
    assert _row("contractor_dispatches", "id", did)["doc_code"] != code and _row("contractor_dispatches", "id", d2)["doc_code"] == code, "既有的不動"

    d3, vid = _dispatch(client, ad, quote="MQ-RB53-004")
    vendor = _row("contractor_dispatches", "id", d3)["vendor_id"]
    b3 = client.delete("/api/contractor-dispatches/%d" % d3, headers=ad).json()["binId"]
    _x("DELETE FROM vendor_contractors WHERE id=?", (vendor,))
    r = _restore(client, su, b3)
    assert r.status_code in (409, 400) and "承攬商" in r.text and _row("recycle_bin", "id", b3)["restore_status"] == "restore_failed" and _row("contractor_dispatches", "id", d3) is None
    assert _row("recycle_bin", "id", b3)["restore_status"] == "restore_failed"

    d4, _ = _dispatch(client, ad, quote="MQ-RB53-005")
    b4 = client.delete("/api/contractor-dispatches/%d" % d4, headers=ad).json()["binId"]
    _x("DELETE FROM quotations WHERE quote_no='MQ-RB53-005'")
    r = _restore(client, su, b4)
    assert r.status_code in (409, 400) and "報價單" in r.text and _row("recycle_bin", "id", b4)["restore_status"] == "restore_failed" and _row("contractor_dispatches", "id", d4) is None


def test_restore_skips_links_to_payslips_that_no_longer_exist(client, who):
    su, ad = who
    pid = _person("李四")
    did, _ = _dispatch(client, ad)
    _x("INSERT INTO payslips (slip_no, contractor_id, contractor_name, status, created_at, updated_at) VALUES ('PS-RB-2', ?, '李四', '草稿', '2031-01-01', '2031-01-01')", (pid,))
    _x("INSERT INTO payslip_dispatch_links (slip_no, dispatch_id, created_at) VALUES ('PS-RB-2', ?, '2031-01-01')", (did,))
    bid = client.delete("/api/contractor-dispatches/%d" % did, headers=ad).json()["binId"]
    _x("DELETE FROM payslips WHERE slip_no='PS-RB-2'")
    r = _restore(client, su, bid)
    assert r.status_code == 200 and any("PS-RB-2" in n for n in r.json()["notes"]), r.text
    assert _q("SELECT * FROM payslip_dispatch_links WHERE dispatch_id=?", (did,)) == []


# ── 匯款申請 ──────────────────────────────────────────────────────────────────
def test_voucher_delete_restore_round_trip_and_numbering_conflict(client, who):
    su, ad = who
    did, _ = _dispatch(client, ad)
    no = _voucher(client, su, did)
    before = _row("contractor_payment_vouchers", "voucher_no", no)
    r = client.delete("/api/contractor-vouchers/%s" % no, headers=su)
    assert r.status_code == 200 and r.json()["binned"] is True, r.text
    bid = r.json()["binId"]
    assert _row("contractor_payment_vouchers", "voucher_no", no) is None
    rr = _restore(client, su, bid)
    assert rr.status_code == 200 and rr.json()["renumbered"] is False, rr.text
    assert _row("contractor_payment_vouchers", "voucher_no", no) == before

    r = client.delete("/api/contractor-vouchers/%s" % no, headers=su)
    bid = r.json()["binId"]
    no2 = _voucher(client, su, did)                                    # 新申請的單號依現行取號政策（單號不重發 ⇒ 不同於 no；舊政策可能同號——測試不依賴）
    rr = _restore(client, su, bid)
    assert rr.status_code in (409, 400), "同派發同款別已有有效申請 ⇒ 衝突，不覆蓋"
    assert _row("recycle_bin", "id", bid)["restore_status"] == "restore_failed"
    _x("UPDATE contractor_payment_vouchers SET voided_at='2031-01-01', status='已作廢' WHERE voucher_no=?", (no2,))
    # 單號衝突路徑：直接放一張同單號、已作廢的申請（不占有效名額）⇒ 還原時換新號並回報
    if no2 == no:                                                      # 舊取號政策下新單會拿到同號：先改掉，免得和下面刻意放的同號列撞唯一鍵
        _x("UPDATE contractor_payment_vouchers SET voucher_no='PV-TEST-0002' WHERE voucher_no=?", (no2,))
        no2 = "PV-TEST-0002"
    row = {k: v for k, v in _row("contractor_payment_vouchers", "voucher_no", no2).items() if k != "id"}
    row["voucher_no"] = no
    cols = list(row)
    _x("INSERT INTO contractor_payment_vouchers (%s) VALUES (%s)" % (",".join(cols), ",".join("?" * len(cols))), tuple(row[c] for c in cols))
    rr = _restore(client, su, bid)
    assert rr.status_code == 200 and rr.json()["renumbered"] is True and any(no in n for n in rr.json()["notes"]), rr.text
    assert _row("contractor_payment_vouchers", "voucher_no", no)["voided_at"] == "2031-01-01", "同單號的既有申請不動"


def test_voucher_rules_not_relaxed_and_approved_entry(client, who):
    su, ad = who
    did, _ = _dispatch(client, ad)
    no = _voucher(client, su, did)
    _x("UPDATE contractor_payment_vouchers SET status='已核准' WHERE voucher_no=?", (no,))
    for h, code in ((ad, 403), (su, 409)):                                 # 匯款申請的端點只給財務／最高管理者（現行規則）
        assert client.delete("/api/contractor-vouchers/%s" % no, headers=h).status_code == code
    assert _q("SELECT COUNT(*) n FROM recycle_bin")[0]["n"] == 0
    body = {"entity_type": "contractor_voucher", "entity_id": no, "confirm": True, "confirm_text": no, "reason": "測試"}
    _x("UPDATE contractor_payment_vouchers SET is_paid=1, paid_at='2031-01-02' WHERE voucher_no=?", (no,))
    imp = client.get("/api/recycle-bin/impact?entity_type=contractor_voucher&entity_id=%s" % no, headers=su).json()
    assert imp["supported"] is False and any(i["kind"] == "paid" and i["blocking"] for i in imp["impact"])
    assert client.post("/api/recycle-bin/delete-approved", headers=su, json=body).status_code in (409, 400)
    _x("UPDATE contractor_payment_vouchers SET is_paid=0, paid_at='' WHERE voucher_no=?", (no,))
    r = client.post("/api/recycle-bin/delete-approved", headers=su, json=body)
    assert r.status_code == 200, r.text
    assert _restore(client, su, r.json()["bin_id"]).status_code == 200
    assert _row("contractor_payment_vouchers", "voucher_no", no)["status"] == "已核准"


def test_voucher_restore_needs_its_dispatch(client, who):
    su, ad = who
    did, _ = _dispatch(client, ad)
    no = _voucher(client, su, did)
    bid = client.delete("/api/contractor-vouchers/%s" % no, headers=su).json()["binId"]
    bd = client.delete("/api/contractor-dispatches/%d" % did, headers=ad).json()["binId"]       # 派發沒有申請了才刪得掉
    r = _restore(client, su, bid)
    assert r.status_code in (409, 400) and "派發" in r.text and _row("recycle_bin", "id", bid)["restore_status"] == "restore_failed"
    assert _restore(client, su, bd).status_code == 200
    assert _restore(client, su, bid).status_code == 200 and _row("contractor_payment_vouchers", "voucher_no", no)


# ── 遮罩／缺席 ────────────────────────────────────────────────────────────────
def test_list_view_masks_bank_account_inside_json_string_columns(client, who):
    su, ad = who
    did, _ = _dispatch(client, ad)
    no = _voucher(client, su, did)
    secret = "012345678901234"
    snap = json.dumps({"vendorName": "V", "bankAccountNumber": secret, "personnel": [{"name": "P", "bankAccountNumber": secret, "bankPassbookImage": "x/y.jpg"}]})
    _x("UPDATE contractor_payment_vouchers SET snapshot_json=? WHERE voucher_no=?", (snap, no))
    _x("UPDATE contractor_payment_vouchers SET status='草稿' WHERE voucher_no=?", (no,))
    bid = client.delete("/api/contractor-vouchers/%s" % no, headers=su).json()["binId"]
    d = client.get("/api/recycle-bin/%s" % bid, headers=su)
    assert d.status_code == 200 and secret not in d.text and "x/y.jpg" not in d.text, "列表／詳情不得出現銀行帳號與存簿影本路徑"
    assert RB.MASK in d.text
    assert _restore(client, su, bid).status_code == 200
    assert secret in _row("contractor_payment_vouchers", "voucher_no", no)["snapshot_json"], "還原用原文"


def test_bin_module_absent_falls_back_to_old_delete_and_says_so(client, who, monkeypatch):
    su, ad = who
    did, _ = _dispatch(client, ad)
    no_d = _voucher(client, su, did)
    real = registry.single_provider
    monkeypatch.setattr(registry, "single_provider", lambda cap, *a, **k: None if cap == RB.CAP_DELETE else real(cap, *a, **k))
    r = client.delete("/api/contractor-vouchers/%s" % no_d, headers=su)
    assert r.status_code == 200 and r.json()["binned"] is False and "永久刪除" in r.json()["notice"]
    assert _row("contractor_payment_vouchers", "voucher_no", no_d) is None
    d2, _ = _dispatch(client, ad, quote="MQ-RB53-006")
    _x("UPDATE contractor_dispatches SET approval_status='已核准' WHERE id=?", (d2,))
    assert client.delete("/api/contractor-dispatches/%d" % d2, headers=ad).status_code == 409, "缺席時規則一樣"
    _x("UPDATE contractor_dispatches SET approval_status='草稿' WHERE id=?", (d2,))
    r = client.delete("/api/contractor-dispatches/%d" % d2, headers=ad)
    assert r.status_code == 200 and r.json()["binned"] is False and _row("contractor_dispatches", "id", d2) is None
    assert _q("SELECT COUNT(*) n FROM recycle_bin")[0]["n"] == 0


# ── commit 之後的後續動作（L1 hook adapter.after_commit：行事曆『付款待辦』事件、簽核通知）─────────────
def _notes(ref, types):
    ph = ",".join("?" * len(types))
    return _q("SELECT * FROM notifications WHERE ref_id=? AND type IN (%s)" % ph, (ref, *types))


def test_approved_voucher_calendar_event_is_withdrawn_on_delete_and_rebuilt_on_restore(client, who, monkeypatch):
    from tests import _fake_gcal
    from modules.subcontract import payable_due as PD
    su, ad = who
    cal = _fake_gcal.install(monkeypatch)
    _fake_gcal.sync_spawn(monkeypatch, PD)
    _fake_gcal.set_events(events={"payable_due": True})
    did, _ = _dispatch(client, ad)
    r = client.post("/api/contractor-vouchers", headers=su, json={"dispatch_id": did, "planned_pay_date": "2031-07-15"})
    assert r.status_code == 201, r.text
    no = r.json()["voucher_no"]
    _x("UPDATE contractor_payment_vouchers SET status='已核准' WHERE voucher_no=?", (no,))
    PD.fire(no)
    assert len(cal.events) == 1
    _x("INSERT INTO notifications (username, type, ref_id, ref_label, message, is_read, created_at) VALUES ('rb53_su','contractor_voucher_approval_request',?,'x','m',0,'2031-01-01')", (no,))
    body = {"entity_type": "contractor_voucher", "entity_id": no, "confirm": True, "confirm_text": no, "reason": "測試"}
    r = client.post("/api/recycle-bin/delete-approved", headers=su, json=body)
    assert r.status_code == 200, r.text
    assert cal.events == {}, "刪除已核准的申請 ⇒ commit 後收回付款待辦事件"
    assert _notes(no, ["contractor_voucher_approval_request"]) == [], "簽核通知一併清掉"
    assert _restore(client, su, r.json()["bin_id"]).status_code == 200
    assert len(cal.events) == 1, "還原 ⇒ commit 後依現況重建事件"


def test_dispatch_in_review_deleted_via_approved_path_clears_approver_notifications(client, who):
    from helpers import _notify
    su, ad = who
    did, _ = _dispatch(client, ad)
    _x("UPDATE contractor_dispatches SET approval_status='待審核' WHERE id=?", (did,))
    _notify("rb53_su", "dispatch_approval_request", str(did), Q, "需要您簽核")
    assert len(_notes(str(did), ["dispatch_approval_request"])) == 1
    body = {"entity_type": "contractor_dispatch", "entity_id": str(did), "confirm": True, "confirm_text": str(did), "reason": "測試"}
    assert client.post("/api/recycle-bin/delete-approved", headers=su, json=body).status_code == 200
    assert _notes(str(did), ["dispatch_approval_request"]) == []


def test_hook_runs_after_endpoint_delete_and_not_when_the_action_fails(client, who, monkeypatch):
    from modules.subcontract import payable_due as PD
    su, ad = who
    fired = []
    monkeypatch.setattr(PD, "fire", lambda no: fired.append(no))
    did, _ = _dispatch(client, ad)
    no = _voucher(client, su, did)
    r = client.delete("/api/contractor-vouchers/%s" % no, headers=su)
    assert r.status_code == 200 and fired == [no], "端點自己 commit 之後呼叫 hook"
    bid = r.json()["binId"]
    no2 = _voucher(client, su, did)                                    # 同派發又有一張有效申請 ⇒ 還原衝突（單號是否相同依取號政策，測試不依賴）
    fired.clear()
    assert _restore(client, su, bid).status_code in (409, 400)
    assert fired == [], "還原失敗（回滾）⇒ 不執行 commit 後動作"
    r = client.delete("/api/contractor-vouchers/%s" % no2, headers=ad)
    assert r.status_code == 403 and fired == [], "被拒絕的刪除 ⇒ 不執行"


def test_restore_with_already_existing_payslip_link_skips_it_with_a_note(client, who):
    su, ad = who
    pid = _person("趙六")
    did, _ = _dispatch(client, ad)
    _x("INSERT INTO payslips (slip_no, contractor_id, contractor_name, status, created_at, updated_at) VALUES ('PS-RB-3', ?, '趙六', '草稿', '2031-01-01', '2031-01-01')", (pid,))
    _x("INSERT INTO payslip_dispatch_links (slip_no, dispatch_id, created_at) VALUES ('PS-RB-3', ?, '2031-01-01')", (did,))
    bid = client.delete("/api/contractor-dispatches/%d" % did, headers=ad).json()["binId"]
    _x("INSERT INTO payslip_dispatch_links (slip_no, dispatch_id, created_at) VALUES ('PS-RB-3', ?, '2031-02-02')", (did,))      # 派發不在期間又被連了一次
    r = _restore(client, su, bid)
    assert r.status_code == 200 and any("PS-RB-3" in n for n in r.json()["notes"]), r.text
    assert len(_q("SELECT * FROM payslip_dispatch_links WHERE dispatch_id=?", (did,))) == 1


def test_payslip_links_go_through_the_payroll_provider_and_degrade_without_it(client, who, monkeypatch):
    """模組邊界：連結表只由薪資獎金寫入——外包工班的 adapter 經提供者 `payslip.dispatch_links` 刪除／放回；提供者不在 ⇒ 不碰連結表並註記。"""
    su, ad = who
    pid = _person("孫七")
    did, _ = _dispatch(client, ad)
    _x("INSERT INTO payslips (slip_no, contractor_id, contractor_name, status, created_at, updated_at) VALUES ('PS-RB-4', ?, '孫七', '草稿', '2031-01-01', '2031-01-01')", (pid,))
    _x("INSERT INTO payslip_dispatch_links (slip_no, dispatch_id, created_at) VALUES ('PS-RB-4', ?, '2031-01-01')", (did,))
    calls = []
    real = registry.single_provider

    class Spy:
        def __init__(self, inner):
            self.inner = inner

        def __getattr__(self, name):
            fn = getattr(self.inner, name)
            return (lambda *a, **k: calls.append(name) or fn(*a, **k)) if name in ("delete_for_dispatch", "restore_rows") else fn
    monkeypatch.setattr(registry, "single_provider", lambda cap, *a, **k: Spy(real(cap, *a, **k)) if cap == "payslip.dispatch_links" else real(cap, *a, **k))
    bid = client.delete("/api/contractor-dispatches/%d" % did, headers=ad).json()["binId"]
    assert calls == ["delete_for_dispatch"] and _q("SELECT * FROM payslip_dispatch_links WHERE dispatch_id=?", (did,)) == []
    assert _restore(client, su, bid).status_code == 200
    assert calls == ["delete_for_dispatch", "restore_rows"] and len(_q("SELECT * FROM payslip_dispatch_links WHERE dispatch_id=?", (did,))) == 1
    # 提供者不在：刪除不碰連結表、還原註記略過
    monkeypatch.setattr(registry, "single_provider", lambda cap, *a, **k: None if cap == "payslip.dispatch_links" else real(cap, *a, **k))
    _x("DELETE FROM payslip_dispatch_links WHERE dispatch_id=?", (did,))
    bid = client.delete("/api/contractor-dispatches/%d" % did, headers=ad).json()["binId"]
    r = _restore(client, su, bid)
    assert r.status_code == 200 and _q("SELECT * FROM payslip_dispatch_links WHERE dispatch_id=?", (did,)) == []
