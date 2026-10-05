# -*- coding: utf-8 -*-
"""行事曆「收款登錄」「應收到期提醒」（2026-10-05 使用者裁示，兩種都預設關）。Google 用假行事曆（tests/_fake_gcal.py）。

- 純函式 events_for_change：新增／改日期／收款／取消收款／刪期別 ⇒ 該 upsert 或 delete 哪一種、沒變不產生
- 三條寫入路徑（整包存 PATCH case-record、出納標記 PATCH payment/{idx}、半解鎖審核套用的重播）都會推
- 開關關閉 ⇒ 完全不打 Google；孤兒（期別刪除、事件已被手動刪除）不留尸、不報錯；標題不含金額
"""
import json

from tests import _fake_gcal
from tests._requires import requires_module

pytestmark = requires_module("case", "款項期別在 M01 案件的 data_json")

NO = "MQ-RCCAL-001"


def _it(i=1, **kw):
    d = {"id": i, "type": "訂金款", "pct": 30, "amount": 31500, "received": False, "receivedAt": "", "expectedReceiptDate": ""}
    d.update(kw)
    return d


# ── 純函式：差異判斷 ──────────────────────────────────────────────────────

def _ev(old, new):
    from modules.case import receipt_calendar as rc
    return [(op, code, ident) for op, code, ident, _x in rc.events_for_change(old, new)]


def test_no_change_no_events():
    a = [_it(expectedReceiptDate="2031-06-01"), _it(2, received=True, receivedAt="2031-05-01")]
    assert _ev(a, json.loads(json.dumps(a))) == []


def test_new_due_date_upserts_due():
    assert _ev([_it()], [_it(expectedReceiptDate="2031-06-01")]) == [("upsert", "receivable_due", "1")]


def test_due_date_change_upserts_again_and_clear_deletes():
    old = [_it(expectedReceiptDate="2031-06-01")]
    assert _ev(old, [_it(expectedReceiptDate="2031-06-15")]) == [("upsert", "receivable_due", "1")]
    assert _ev(old, [_it(expectedReceiptDate="")]) == [("delete", "receivable_due", "1")]


def test_received_logs_receipt_and_withdraws_due():
    old = [_it(expectedReceiptDate="2031-06-01")]
    new = [_it(expectedReceiptDate="2031-06-01", received=True, receivedAt="2031-05-30")]
    assert sorted(_ev(old, new)) == [("delete", "receivable_due", "1"), ("upsert", "receipt_logged", "1")]


def test_receipt_edit_updates_and_cancel_deletes_and_restores_due():
    rcv = _it(expectedReceiptDate="2031-06-01", received=True, receivedAt="2031-05-30", actualAmount=31000)
    assert _ev([rcv], [dict(rcv, receivedAt="2031-05-31")]) == [("upsert", "receipt_logged", "1")]
    assert _ev([rcv], [dict(rcv, actualAmount=30000)]) == [], "實收金額不在事件裡 ⇒ 不觸發（2026-10-05 起事件不含金額）"
    cancelled = _it(expectedReceiptDate="2031-06-01")
    assert sorted(_ev([rcv], [cancelled])) == [("delete", "receipt_logged", "1"), ("upsert", "receivable_due", "1")]


def test_removed_period_withdraws_both_kinds():
    old = [_it(1, expectedReceiptDate="2031-06-01"), _it(2, received=True, receivedAt="2031-05-01")]
    assert sorted(_ev(old, [])) == [("delete", "receipt_logged", "2"), ("delete", "receivable_due", "1")]


def test_received_without_valid_date_and_invalid_due_dates_are_ignored():
    assert _ev([_it()], [_it(received=True, receivedAt="")]) == []
    assert _ev([_it()], [_it(expectedReceiptDate="下個月")]) == []
    assert _ev([_it()], [_it(expectedReceiptDate="2031-02-30")]) == []


def test_period_without_id_is_not_pushed():
    new = [dict(_it(), id=None, expectedReceiptDate="2031-06-01")]
    assert _ev([], new) == []


# ── 端點：三條寫入路徑 ─────────────────────────────────────────────────────

def _seed(items=None, deal_tag="已成案", semi=0, no=NO):
    import db
    items = [_it()] if items is None else items
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM quotations WHERE quote_no=?", (no,))
        conn.execute("INSERT INTO quotations (quote_no, customer_name, project_name, status, deal_tag, case_semi_unlocked, total, pretax,"
                     " data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (no, "甲客戶", "甲案", "已送出", deal_tag, semi, 105000, 100000,
                      json.dumps({"caseRecord": {"payment": {"items": items}}}), "2026-01-01T00:00:00", "2026-01-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _items(no=NO):
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (no,)).fetchone()
    finally:
        conn.close()
    return json.loads(row["data_json"])["caseRecord"]["payment"]["items"]


def _login(client, make_user, name="rccal_sa", role="superadmin"):
    u, p = make_user(username=name, role=role)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _setup(monkeypatch, events):
    from modules.case.api import quotations as q
    cal = _fake_gcal.install(monkeypatch)
    _fake_gcal.sync_spawn(monkeypatch, q)
    _fake_gcal.set_events(events=events)
    return cal


def _save_case_record(client, h, items, no=NO):
    r = client.patch(f"/api/quotations/{no}/case-record", headers=h, json={"case_record": {"payment": {"items": items}}})
    assert r.status_code == 200, r.text


def _by_prefix(cal, prefix):
    return [e for e in cal.events.values() if e["summary"].startswith(prefix)]


def test_off_by_default_nothing_sent(client, make_user, monkeypatch):
    cal = _setup(monkeypatch, None)
    _seed()
    h = _login(client, make_user)
    _save_case_record(client, h, [_it(expectedReceiptDate="2031-06-01")])
    r = client.patch(f"/api/quotations/{NO}/payment/0", headers=h,
                     json={"received": True, "receivedAt": "2031-05-30", "actualAmount": 31500, "itemId": 1})
    assert r.status_code == 200, r.text
    assert cal.calls == []


def test_case_record_save_creates_moves_and_removes_due_event(client, make_user, monkeypatch):
    cal = _setup(monkeypatch, {"receivable_due": True})
    _seed()
    h = _login(client, make_user)
    _save_case_record(client, h, [_it(expectedReceiptDate="2031-06-01")])
    (ev,) = cal.events.values()
    assert ev["summary"] == "應收到期 — MQ-RCCAL-001（甲客戶）訂金款"
    assert ev["start"] == {"date": "2031-06-01"} and "預計收款日：2031-06-01" in ev["description"]
    assert not any(x in ev["summary"] + ev["description"] for x in ("31,500", "31500", "NT$")), "事件不含任何金額（標題與說明）"
    _save_case_record(client, h, [_it(expectedReceiptDate="2031-06-20")])          # 改日期 ⇒ 同一筆移動，不新增
    assert len(cal.events) == 1 and list(cal.events.values())[0]["start"] == {"date": "2031-06-20"}
    n = len(cal.calls)
    _save_case_record(client, h, [_it(expectedReceiptDate="2031-06-20")])          # 沒變 ⇒ 不打 Google
    assert len(cal.calls) == n
    _save_case_record(client, h, [_it(expectedReceiptDate="")])                    # 清空 ⇒ 刪
    assert cal.events == {}


def test_mark_payment_logs_receipt_and_deletes_due(client, make_user, monkeypatch):
    cal = _setup(monkeypatch, {"receipt_logged": True, "receivable_due": True})
    _seed([_it(expectedReceiptDate="2031-06-01")])
    h = _login(client, make_user)
    _save_case_record(client, h, [_it(expectedReceiptDate="2031-06-02")])
    assert len(_by_prefix(cal, "應收到期")) == 1
    r = client.patch(f"/api/quotations/{NO}/payment/0", headers=h,
                     json={"received": True, "receivedAt": "2031-05-30", "actualAmount": 31000, "feeAmount": 500,
                           "bankAccountName": "玉山帳戶", "itemId": 1})
    assert r.status_code == 200, r.text
    assert _by_prefix(cal, "應收到期") == [], "收到款 ⇒ 到期提醒收回"
    (rc,) = _by_prefix(cal, "收款登錄")
    assert rc["summary"] == "收款登錄 — MQ-RCCAL-001（甲客戶）訂金款"
    assert rc["start"] == {"date": "2031-05-30"}
    d = rc["description"]
    assert "入帳帳戶：玉山帳戶" in d and "收款日：2031-05-30" in d
    assert not any(x in rc["summary"] + d for x in ("31,000", "31000", "500", "31,500", "NT$", "實收", "應收", "手續費")), "事件不含任何金額"
    # 取消收款 ⇒ 收款事件刪、到期提醒（有預計日）回來
    r = client.patch(f"/api/quotations/{NO}/payment/0", headers=h, json={"received": False, "receivedAt": "", "itemId": 1})
    assert r.status_code == 200, r.text
    assert _by_prefix(cal, "收款登錄") == [] and len(_by_prefix(cal, "應收到期")) == 1


def test_receipt_event_is_idempotent_across_resaves(client, make_user, monkeypatch):
    cal = _setup(monkeypatch, {"receipt_logged": True})
    _seed()
    h = _login(client, make_user)
    body = {"received": True, "receivedAt": "2031-05-30", "actualAmount": 31500, "itemId": 1}
    assert client.patch(f"/api/quotations/{NO}/payment/0", headers=h, json=body).status_code == 200
    assert client.patch(f"/api/quotations/{NO}/payment/0", headers=h, json=dict(body, receivedAt="2031-05-31")).status_code == 200
    (ev,) = cal.events.values()
    assert ev["start"] == {"date": "2031-05-31"}, "改收款日 ⇒ 更新同一筆，不重複建立"


def test_removed_period_and_manually_deleted_event_leave_no_orphans_or_errors(client, make_user, monkeypatch):
    cal = _setup(monkeypatch, {"receivable_due": True, "receipt_logged": True})
    _seed()
    h = _login(client, make_user)
    _save_case_record(client, h, [_it(1, expectedReceiptDate="2031-06-01"), _it(2, expectedReceiptDate="2031-07-01")])
    assert len(cal.events) == 2
    _save_case_record(client, h, [_it(1, expectedReceiptDate="2031-06-01")])        # 刪掉第 2 期
    assert [e["start"]["date"] for e in cal.events.values()] == ["2031-06-01"]
    cal.events.clear()                                                              # 使用者在 Google 手動刪掉
    _save_case_record(client, h, [_it(1, expectedReceiptDate="2031-06-09")])        # 改日期 ⇒ 找不到就重建，不報錯
    assert [e["start"]["date"] for e in cal.events.values()] == ["2031-06-09"]
    _save_case_record(client, h, [_it(1, received=True, receivedAt="2031-06-09")])  # 收款 ⇒ 刪到期＋建收款
    _save_case_record(client, h, [])                                                # 期別整個刪掉 ⇒ 全收回
    assert cal.events == {}
    _save_case_record(client, h, [])                                                # 事件已不存在 ⇒ 安靜略過
    assert cal.events == {}


def test_global_switch_off_blocks_even_deletes(client, make_user, monkeypatch):
    cal = _setup(monkeypatch, {"receivable_due": True})
    _seed([_it(expectedReceiptDate="2031-06-01")])
    h = _login(client, make_user)
    _fake_gcal.set_events(events={"receivable_due": True}, enabled=False)
    _save_case_record(client, h, [_it(expectedReceiptDate="")])
    assert cal.calls == []


def test_semi_unlock_approve_replay_pushes_for_payment_mark(client, make_user, monkeypatch):
    cal = _setup(monkeypatch, {"receipt_logged": True, "receivable_due": True})
    _seed([_it(expectedReceiptDate="2031-06-01")], deal_tag="已結案", semi=1)
    h = _login(client, make_user, "rccal_cash", "admin")
    r = client.patch(f"/api/quotations/{NO}/payment/0", headers=h,
                     json={"received": True, "receivedAt": "2031-05-30", "actualAmount": 31500, "itemId": 1})
    assert r.status_code == 200 and r.json().get("pending"), r.text
    assert cal.calls == [], "排進審核佇列時還沒生效，不可以先推"
    sa = _login(client, make_user, "rccal_sa2", "superadmin")
    r = client.post(f"/api/case-changes/{r.json()['changeRequestId']}/approve", headers=sa)
    assert r.status_code == 200, r.text
    assert len(_by_prefix(cal, "收款登錄")) == 1 and _by_prefix(cal, "應收到期") == []


def test_semi_unlock_approve_replay_pushes_for_case_record_update(client, make_user, monkeypatch):
    cal = _setup(monkeypatch, {"receivable_due": True})
    _seed([_it()], deal_tag="已結案", semi=1)
    req = _login(client, make_user, "rccal_adm3", "admin")
    sa = _login(client, make_user, "rccal_sa3", "superadmin")
    r = client.patch(f"/api/quotations/{NO}/case-record", headers=req,
                     json={"case_record": {"payment": {"items": [_it(expectedReceiptDate="2031-06-01")]}}})
    assert r.status_code == 200 and r.json().get("pending"), r.text
    assert cal.calls == []
    r = client.post(f"/api/case-changes/{r.json()['changeRequestId']}/approve", headers=sa)
    assert r.status_code == 200, r.text
    (ev,) = cal.events.values()
    assert ev["start"] == {"date": "2031-06-01"}


def test_push_failure_never_breaks_the_save(client, make_user, monkeypatch):
    _setup(monkeypatch, {"receivable_due": True})

    def boom(*a, **k):
        raise RuntimeError("Google 掛了")
    from helpers import google_calendar as gc
    monkeypatch.setattr(gc, "_events_call", boom)
    _seed()
    h = _login(client, make_user)
    _save_case_record(client, h, [_it(expectedReceiptDate="2031-06-01")])          # 200 即可（_save 內已 assert）
    assert _items()[0]["expectedReceiptDate"] == "2031-06-01"


def test_type_switch_off_after_creation_keeps_event_and_sends_nothing(client, make_user, monkeypatch):
    """開著時建立 ⇒ 事件種類關掉 ⇒ 之後收款：不碰 Google、既有事件保留（開關語意：關掉不刪已建立的）。"""
    cal = _setup(monkeypatch, {"receivable_due": True})
    _seed()
    h = _login(client, make_user)
    _save_case_record(client, h, [_it(expectedReceiptDate="2031-06-01")])
    assert len(cal.events) == 1
    _fake_gcal.set_events(events={"receivable_due": False})
    n = len(cal.calls)
    _save_case_record(client, h, [_it(expectedReceiptDate="2031-06-09")])
    _save_case_record(client, h, [_it(received=True, receivedAt="2031-06-09")])
    assert len(cal.calls) == n and len(cal.events) == 1


def test_label_and_account_change_refresh_the_event_but_amounts_do_not():
    """事件內容＝日期／款項名稱／入帳帳戶（不含金額）：這些變了才產生 upsert；金額、百分比、備註變動不觸發（金額不在事件裡，不必同步）。"""
    due = _it(expectedReceiptDate="2031-06-01")
    assert _ev([due], [dict(due, type="尾款")]) == [("upsert", "receivable_due", "1")]
    assert _ev([due], [dict(due, amount=40000, pct=50)]) == [], "金額不在事件內容裡"
    rcv = _it(received=True, receivedAt="2031-05-30", actualAmount=31500, bankAccountName="甲帳戶")
    assert _ev([rcv], [dict(rcv, type="尾款")]) == [("upsert", "receipt_logged", "1")]
    assert _ev([rcv], [dict(rcv, bankAccountName="乙帳戶")]) == [("upsert", "receipt_logged", "1")]
    for k, v in (("amount", 40000), ("actualAmount", 30000), ("feeAmount", 50), ("pct", 70), ("note", "只改備註")):
        assert _ev([rcv], [dict(rcv, **{k: v})]) == [], k


def test_new_types_describe_the_no_backfill_rule():
    from helpers import google_calendar as gc
    by = {t["code"]: t for t in gc.event_types()}
    for c in ("receipt_logged", "receivable_due", "payable_due"):
        assert "只對開啟後的變更生效" in by[c]["description"], c


def test_received_flag_not_the_date_decides_receipt_state():
    """突變守門（稽核 T41）：收款狀態看 `received` 旗標，不是 receivedAt 有沒有值。
    取消收款（旗標關掉、receivedAt 還留著）⇒ 收款事件刪、有預計日就回到到期提醒；只有日期沒有旗標 ⇒ 不產生收款事件。"""
    d = "2031-05-30"
    old = [_it(received=True, receivedAt=d, expectedReceiptDate="2031-06-01")]
    new = [_it(received=False, receivedAt=d, expectedReceiptDate="2031-06-01")]
    assert sorted(_ev(old, new)) == [("delete", "receipt_logged", "1"), ("upsert", "receivable_due", "1")]
    assert _ev(old, [_it(received=False, receivedAt=d)]) == [("delete", "receipt_logged", "1")]
    assert _ev([_it()], [_it(received=False, receivedAt=d)]) == [], "只有 receivedAt、沒有 received ⇒ 沒有收款事件"
    assert _ev([], [_it(received=False, receivedAt=d)]) == []
