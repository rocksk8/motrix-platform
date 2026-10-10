# -*- coding: utf-8 -*-
"""第 53 班 P1（案件模組）：報價單／額外支出（請購單／採購單）／完工單／材料申請 的刪除暫存區 adapter。
釘住：①刪除端點進暫存區（資料列＋名下資料＋附件）且回應帶 binned ②還原後逐欄相等、附件回原位 ③現行刪除規則不放寬（非草稿照舊 403／409）
④『刪除已核可』只有 superadmin、有下游紀錄（已付款、掛著其他單據、有匯款申請）明確拒絕 ⑤衝突／父層不在 ⑥暫存區模組不在 ⇒ 照舊硬刪並明說。"""
import json
import os

import pytest

import db
from helpers import recycle_bin as RB
from helpers import uploads as UP


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def who(client, make_user):
    su, sp = make_user(username="rbc_su", role="superadmin")
    ad, ap = make_user(username="rbc_admin", role="admin")
    return _login(client, su, sp), _login(client, ad, ap)


@pytest.fixture(autouse=True)
def _clean_bin(client):
    yield
    cn = db.get_db()
    cn.execute("DELETE FROM recycle_bin")
    cn.commit()
    cn.close()


def _q(sql, args=()):
    cn = db.get_db()
    try:
        return [dict(r) for r in cn.execute(sql, args).fetchall()]
    finally:
        cn.close()


def _x(sql, args=()):
    cn = db.get_db()
    try:
        cur = cn.execute(sql, args)
        cn.commit()
        return cur.lastrowid
    finally:
        cn.close()


def _file(rel, text="x"):
    full = os.path.join(UP.UPLOADS_ROOT, *rel.split("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(text)
    return full


def _quote(qn, status="草稿", data=None, **kw):
    _x("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at, deal_tag, sales_person, signed_files_json)"
       " VALUES (?,?,?,?,?,?,?,?,?,?)",
       (qn, status, kw.get("customer", "暫存客戶"), "專案", json.dumps(data or {}, ensure_ascii=False), "2026-10-01", "2026-10-01", kw.get("deal_tag", ""), "",
        json.dumps(kw.get("signed", []))))


def _bin_rows():
    return _q("SELECT * FROM recycle_bin ORDER BY id")


# ── 額外支出 ────────────────────────────────────────────────────────────────────
def _expense(qn, status="草稿", rel=None, **kw):
    files = [{"id": "f1", "filename": "a.txt", "path": rel}] if rel else []
    return _x("INSERT INTO case_extra_expenses (quote_no, category, description, qty, unit, unit_cost, total_cost, expense_date, status, created_by, created_at, updated_at,"
              " files_json, paid_date) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (qn, "雜支", kw.get("desc", "測試支出"), 1, "式", 100, 100, "2026-10-01", status, "rbc_su", "2026-10-01", "2026-10-01", json.dumps(files), kw.get("paid", "")))


def test_extra_expense_delete_goes_to_the_bin_and_restores_identically(client, who):
    su, _ = who
    _quote("MQ-RBC-001")
    rel = "rbc/ee/a.txt"
    full = _file(rel)
    eid = _expense("MQ-RBC-001", rel=rel)
    before = _q("SELECT * FROM case_extra_expenses WHERE id=?", (eid,))[0]
    r = client.delete("/api/quotations/MQ-RBC-001/extra-expenses/%d" % eid, headers=su)
    assert r.status_code == 200 and r.json() == {"ok": True}, r.text
    assert _q("SELECT 1 FROM case_extra_expenses WHERE id=?", (eid,)) == [] and not os.path.exists(full) and not os.path.isdir(os.path.dirname(full))
    b = _bin_rows()
    assert len(b) == 1 and b[0]["entity_type"] == "extra_expense" and b[0]["entity_id"] == str(eid) and b[0]["file_count"] == 1
    r = client.post("/api/recycle-bin/%d/restore" % b[0]["id"], headers=su)
    assert r.status_code == 200, r.text
    after = _q("SELECT * FROM case_extra_expenses WHERE id=?", (eid,))[0]
    assert after == before and os.path.isfile(full)


def test_extra_expense_rules_not_relaxed_and_approved_path_is_superadmin_only(client, who):
    su, ad = who
    _quote("MQ-RBC-002")
    eid = _expense("MQ-RBC-002", status="已核准")
    r = client.delete("/api/quotations/MQ-RBC-002/extra-expenses/%d" % eid, headers=su)
    assert r.status_code == 409 and _q("SELECT 1 FROM case_extra_expenses WHERE id=?", (eid,)) != []
    body = {"entity_type": "extra_expense", "entity_id": str(eid), "confirm": True, "confirm_text": str(eid), "reason": "誤開"}
    assert client.post("/api/recycle-bin/delete-approved", headers=ad, json=body).status_code == 403
    r = client.post("/api/recycle-bin/delete-approved", headers=su, json=body)
    assert r.status_code == 200, r.text
    assert _q("SELECT 1 FROM case_extra_expenses WHERE id=?", (eid,)) == [] and _bin_rows()[0]["via"] == "approved"
    paid = _expense("MQ-RBC-002", status="已核准", paid="2026-10-05")
    body.update(entity_id=str(paid), confirm_text=str(paid))
    r = client.post("/api/recycle-bin/delete-approved", headers=su, json=body)
    assert r.status_code in (400, 409) and "付款" in r.text and _q("SELECT 1 FROM case_extra_expenses WHERE id=?", (paid,)) != []


def test_extra_expense_restore_needs_its_quotation_and_free_id(client, who):
    su, _ = who
    _quote("MQ-RBC-003")
    eid = _expense("MQ-RBC-003")
    assert client.delete("/api/quotations/MQ-RBC-003/extra-expenses/%d" % eid, headers=su).status_code == 200
    _x("DELETE FROM quotations WHERE quote_no='MQ-RBC-003'")
    bid = _bin_rows()[0]["id"]
    r = client.post("/api/recycle-bin/%d/restore" % bid, headers=su)
    assert r.status_code in (400, 409) and "不在了" in r.text, r.text
    _quote("MQ-RBC-003")
    _x("INSERT INTO case_extra_expenses (id, quote_no, category, description, total_cost, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
       (eid, "MQ-RBC-003", "x", "占用", 1, "草稿", "2026-10-01", "2026-10-01"))
    r = client.post("/api/recycle-bin/%d/restore" % bid, headers=su)
    assert r.status_code in (400, 409) and "占用" in r.text, r.text


def test_extra_expense_without_bin_module_hard_deletes_and_says_so(client, who, monkeypatch):
    su, _ = who
    _quote("MQ-RBC-004")
    rel = "rbc/ee/b.txt"
    full = _file(rel)
    eid = _expense("MQ-RBC-004", rel=rel)
    monkeypatch.setattr(RB, "delete", lambda *a, **k: None)
    r = client.delete("/api/quotations/MQ-RBC-004/extra-expenses/%d" % eid, headers=su)
    assert r.status_code == 200 and r.json()["binned"] is False and "無法還原" in r.json()["notice"], r.text
    assert _q("SELECT 1 FROM case_extra_expenses WHERE id=?", (eid,)) == [] and not os.path.exists(full) and _bin_rows() == []


# ── 完工單 ──────────────────────────────────────────────────────────────────────
def _note(no, qn, status="草稿", rel=None, **kw):
    files = [{"id": "s1", "filename": "s.pdf", "path": rel}] if rel else []
    _x("INSERT INTO completion_notes (note_no, quote_no, status, customer_name, items_json, data_json, created_by, created_at, updated_at, signed_files_json, is_signed, completion_date)"
       " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
       (no, qn, status, "客戶", "[]", "{}", "rbc_su", "2026-10-01", "2026-10-01", json.dumps(files), 1 if rel else 0, kw.get("done", "")))


def test_completion_note_round_trip_conflict_and_rules(client, who):
    su, ad = who
    _quote("MQ-RBC-010")
    rel = "rbc/cn/s.pdf"
    full = _file(rel)
    _note("CN-RBC-1", "MQ-RBC-010", rel=rel)
    before = _q("SELECT * FROM completion_notes WHERE note_no='CN-RBC-1'")[0]
    r = client.delete("/api/completion-notes/CN-RBC-1", headers=su)
    assert r.status_code == 200 and r.json() == {"ok": True}, r.text
    assert _q("SELECT 1 FROM completion_notes WHERE note_no='CN-RBC-1'") == [] and not os.path.exists(full)
    bid = _bin_rows()[0]["id"]
    _note("CN-RBC-1", "MQ-RBC-010")                                    # 單號被占用 ⇒ 不覆蓋
    r = client.post("/api/recycle-bin/%d/restore" % bid, headers=su)
    assert r.status_code in (400, 409) and "占用" in r.text
    assert _q("SELECT 1 FROM recycle_bin WHERE id=? AND restore_status='restore_failed'", (bid,)) != [] and not os.path.exists(full)
    _x("DELETE FROM completion_notes WHERE note_no='CN-RBC-1'")
    assert client.post("/api/recycle-bin/%d/restore" % bid, headers=su).status_code == 200
    assert _q("SELECT * FROM completion_notes WHERE note_no='CN-RBC-1'")[0] == before and os.path.isfile(full)
    _note("CN-RBC-2", "MQ-RBC-010", status="已核准", done="2026-10-02")
    assert client.delete("/api/completion-notes/CN-RBC-2", headers=su).status_code == 409           # 僅草稿（D1 不放寬）
    body = {"entity_type": "completion_note", "entity_id": "CN-RBC-2", "confirm": True, "confirm_text": "CN-RBC-2"}
    assert client.post("/api/recycle-bin/delete-approved", headers=ad, json=body).status_code == 403
    assert client.post("/api/recycle-bin/delete-approved", headers=su, json=body).status_code == 200
    d = client.get("/api/recycle-bin/%d" % _bin_rows()[-1]["id"], headers=su).json()
    assert any(i["kind"] == "warranty" for i in d["impact"])


# ── 報價單 ──────────────────────────────────────────────────────────────────────
def test_quotation_delete_takes_stages_updates_and_files_and_restores_identically(client, who):
    su, _ = who
    rel = "rbc/q/signed.pdf"
    full = _file(rel)
    upl = "rbc/q/upd.txt"
    full2 = _file(upl)
    _quote("MQ-RBC-020", signed=[{"id": "sg", "filename": "signed.pdf", "path": rel}])
    sid = _x("INSERT INTO case_stages (quote_no, label, sort_order, created_at, updated_at) VALUES (?,?,?,?,?)", ("MQ-RBC-020", "施工", 1, "2026-10-01", "2026-10-01"))
    _x("INSERT INTO case_stage_visits (stage_id, visit_date, visit_people, note, created_at) VALUES (?,?,?,?,?)", (sid, "2026-10-02", "[]", "巡", "2026-10-02"))
    _x("INSERT INTO case_updates (quote_no, author, content, type, created_at, files_json) VALUES (?,?,?,?,?,?)",
       ("MQ-RBC-020", "rbc_su", "進度", "note", "2026-10-02", json.dumps([{"id": "u1", "path": upl, "filename": "upd.txt"}])))
    snap = {t: _q("SELECT * FROM %s" % t) for t in ("quotations", "case_stages", "case_stage_visits", "case_updates")}
    r = client.delete("/api/quotations/MQ-RBC-020", headers=su)
    assert r.status_code == 200 and r.json() == {"ok": True}, r.text
    for t in snap:
        assert _q("SELECT 1 FROM %s" % t) == [], t
    assert not os.path.exists(full) and not os.path.exists(full2)
    b = _bin_rows()[0]
    assert b["entity_type"] == "quotation" and b["file_count"] == 2
    assert client.post("/api/recycle-bin/%d/restore" % b["id"], headers=su).status_code == 200
    for t, rows in snap.items():
        assert _q("SELECT * FROM %s" % t) == rows, t
    assert os.path.isfile(full) and os.path.isfile(full2)


def test_quotation_non_draft_still_refused_and_approved_path_refuses_dependents(client, who):
    su, ad = who
    _quote("MQ-RBC-021", status="已核准")
    assert client.delete("/api/quotations/MQ-RBC-021", headers=su).status_code == 403
    body = {"entity_type": "quotation", "entity_id": "MQ-RBC-021", "confirm": True, "confirm_text": "MQ-RBC-021"}
    assert client.post("/api/recycle-bin/delete-approved", headers=ad, json=body).status_code == 403
    _expense("MQ-RBC-021")
    r = client.post("/api/recycle-bin/delete-approved", headers=su, json=body)
    assert r.status_code in (400, 409) and "額外支出" in r.text and _q("SELECT 1 FROM quotations WHERE quote_no='MQ-RBC-021'") != []
    _x("DELETE FROM case_extra_expenses WHERE quote_no='MQ-RBC-021'")
    assert client.post("/api/recycle-bin/delete-approved", headers=su, json=body).status_code == 200
    _quote("MQ-RBC-022", status="已結案", deal_tag="已結案")
    body.update(entity_id="MQ-RBC-022", confirm_text="MQ-RBC-022")
    r = client.post("/api/recycle-bin/delete-approved", headers=su, json=body)
    assert r.status_code in (400, 409) and "結案" in r.text


def test_quotation_without_bin_module_keeps_the_old_row_only_delete(client, who, monkeypatch):
    su, _ = who
    _quote("MQ-RBC-023")
    _x("INSERT INTO case_stages (quote_no, label, sort_order, created_at, updated_at) VALUES (?,?,?,?,?)", ("MQ-RBC-023", "施工", 1, "2026-10-01", "2026-10-01"))
    monkeypatch.setattr(RB, "delete", lambda *a, **k: None)
    r = client.delete("/api/quotations/MQ-RBC-023", headers=su)
    assert r.status_code == 200 and r.json()["binned"] is False and "無法還原" in r.json()["notice"], r.text
    assert _q("SELECT 1 FROM quotations WHERE quote_no='MQ-RBC-023'") == [] and _q("SELECT 1 FROM case_stages WHERE quote_no='MQ-RBC-023'") != []


# ── 材料申請（報價單存檔 diff 的隱性刪除）──────────────────────────────────────────────
def _material_case(qn, status, with_payment=False):
    order = {"itemId": "mo-1", "itemName": "交換器", "quantity": 2, "unit": "台", "unitPrice": 100, "totalPrice": 200, "supplierId": None, "poDocCode": "", "_saved": True}
    data = {"caseRecord": {"materialOrders": [order], "materials": [{"id": "m1", "name": "交換器", "orderItemId": "mo-1"}]}}
    _quote(qn, status="已送出", data=data)
    if status is not None:
        _x("INSERT INTO case_material_approvals (quote_no, item_id, doc_code, status, created_at, updated_at) VALUES (?,?,?,?,?,?)", (qn, "mo-1", "MR-RBC", status, "2026-10-01", "2026-10-01"))
    return order


def test_material_order_removed_by_save_diff_goes_to_the_bin_and_restores(client, who):
    from modules.case import material_guard as MG
    su, _ = who
    order = _material_case("MQ-RBC-030", "草稿")
    appr_before = _q("SELECT * FROM case_material_approvals")[0]
    cn = db.get_db()
    try:
        data = {"caseRecord": {"materialOrders": [], "materials": []}}
        rej = []
        old = MG._gate_orders(cn, "MQ-RBC-030", [order], [], {"username": "rbc_su", "role": "superadmin", "id": 1}, rej)
        cn.commit()
    finally:
        cn.close()
    assert rej == [] and old == [] and _q("SELECT 1 FROM case_material_approvals") == []
    b = _bin_rows()
    assert len(b) == 1 and b[0]["entity_type"] == "material_order" and b[0]["entity_id"] == "MQ-RBC-030|mo-1" and b[0]["parent_id"] == ""
    # 存檔本身把那一列從 JSON 拿掉（這裡模擬）；adapter 的 delete_in_tx 也已經拿掉，冪等
    assert json.loads(_q("SELECT data_json FROM quotations WHERE quote_no='MQ-RBC-030'")[0]["data_json"])["caseRecord"]["materialOrders"] == []
    assert client.post("/api/recycle-bin/%d/restore" % b[0]["id"], headers=su).status_code == 200
    got = json.loads(_q("SELECT data_json FROM quotations WHERE quote_no='MQ-RBC-030'")[0]["data_json"])["caseRecord"]["materialOrders"]
    assert got == [order] and _q("SELECT * FROM case_material_approvals")[0] == appr_before


def test_material_order_blocked_cases_keep_old_messages_and_approved_path(client, who):
    from modules.case import material_guard as MG
    su, ad = who
    order = _material_case("MQ-RBC-031", "已核准")
    cn = db.get_db()
    try:
        rej = []
        out = MG._gate_orders(cn, "MQ-RBC-031", [order], [], {"username": "rbc_su", "role": "superadmin", "id": 1}, rej)
    finally:
        cn.close()
    assert out == [order] and rej and "不可刪除" in json.dumps(rej, ensure_ascii=False) and _bin_rows() == []
    body = {"entity_type": "material_order", "entity_id": "MQ-RBC-031|mo-1", "confirm": True, "confirm_text": "MQ-RBC-031|mo-1"}
    assert client.post("/api/recycle-bin/delete-approved", headers=ad, json=body).status_code == 403
    _x("INSERT INTO case_material_payments (quote_no, item_id, status, created_at, updated_at) VALUES (?,?,?,?,?)", ("MQ-RBC-031", "mo-1", "待付款", "2026-10-01", "2026-10-01"))
    r = client.post("/api/recycle-bin/delete-approved", headers=su, json=body)
    assert r.status_code in (400, 409) and "匯款" in r.text and _q("SELECT 1 FROM case_material_approvals") != []
    _x("DELETE FROM case_material_payments WHERE quote_no='MQ-RBC-031'")
    r = client.post("/api/recycle-bin/delete-approved", headers=su, json=body)
    assert r.status_code == 200, r.text
    assert json.loads(_q("SELECT data_json FROM quotations WHERE quote_no='MQ-RBC-031'")[0]["data_json"])["caseRecord"]["materialOrders"] == []
    assert _q("SELECT 1 FROM case_material_approvals") == []


def test_legacy_material_order_without_approval_row_is_binned_too(client, who):
    from modules.case import material_guard as MG
    su, _ = who
    order = _material_case("MQ-RBC-032", None)
    cn = db.get_db()
    try:
        rej = []
        assert MG._gate_orders(cn, "MQ-RBC-032", [order], [], {"username": "rbc_su", "role": "superadmin", "id": 1}, rej) == []
        cn.commit()
    finally:
        cn.close()
    b = _bin_rows()
    assert len(b) == 1 and b[0]["entity_id"] == "MQ-RBC-032|mo-1"
    assert client.post("/api/recycle-bin/%d/restore" % b[0]["id"], headers=su).status_code == 200
    assert json.loads(_q("SELECT data_json FROM quotations WHERE quote_no='MQ-RBC-032'")[0]["data_json"])["caseRecord"]["materialOrders"] == [order]


def test_adapters_are_registered_by_the_case_module():
    ads = RB.adapters()
    assert {"quotation", "extra_expense", "completion_note", "material_order"} <= set(ads)
    assert all(ads[k].label for k in ads)
