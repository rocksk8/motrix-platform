"""不經 save_quotation_json、直接 `UPDATE quotations SET … data_json=?` 的路徑也不可以蓋掉空窗內的寫入（lost update C 組，2026-09-25）。

範圍：update_status、recall_quotation、reject_quotation、create_quotation（送審時補寫 approval）、
google_calendar.push_event_for_quotation_won（讀完 → 呼叫 Google 建事件 → 寫回 event id）。
探針（SQL 層）：把 get_db 換成代理連線，在它執行第一個 `UPDATE quotations … data_json` **之前**另開連線、
照正確寫法拿寫鎖、在 data_json 加 `_probe`。以列 id 定位（reject 會改單號）。
  修正前 ⇒ 探針先寫進去，接著被整包蓋掉（紅）；修正後 ⇒ 探針卡在寫鎖上，之後才寫進去（綠）。
"""
import json
import threading

import pytest

import db as _db
import modules.case.api.quotations as q
from tests.test_case_money_mask_2026_09_24 import NO, _login, _seed

_REAL_GET_DB = _db.get_db


def _probe_by_id(row_id):
    conn = _REAL_GET_DB()
    try:
        conn.execute("BEGIN IMMEDIATE")
        r = conn.execute("SELECT data_json FROM quotations WHERE id=?", (row_id,)).fetchone()
        d = json.loads(r[0] or "{}")
        d["_probe"] = "寫在空窗裡"
        conn.execute("UPDATE quotations SET data_json=? WHERE id=?", (json.dumps(d, ensure_ascii=False), row_id))
        conn.commit()
    finally:
        conn.close()


class _GapConn:
    def __init__(self, conn, state):
        self._c, self._s = conn, state

    def execute(self, sql, params=(), *a, **k):
        st = self._s
        if (st["armed"] and not st["fired"] and isinstance(sql, str)
                and "UPDATE quotations" in sql and "data_json" in sql):
            st["fired"] = True
            no = params[-1]
            rid = _REAL_GET_DB().execute("SELECT id FROM quotations WHERE quote_no=?", (no,)).fetchone()[0]
            st["row_id"] = rid
            t = threading.Thread(target=_probe_by_id, args=(rid,))
            t.start()
            t.join(2)                       # 修正後探針等寫鎖 ⇒ 不可以無限等
            st["thread"] = t
        return self._c.execute(sql, params, *a, **k)

    def __getattr__(self, name):
        return getattr(self._c, name)


@pytest.fixture()
def gap(monkeypatch):
    st = {"armed": False, "fired": False}

    def _get_db(*a, **k):
        return _GapConn(_REAL_GET_DB(*a, **k), st)
    monkeypatch.setattr(q, "get_db", _get_db)
    monkeypatch.setattr(_db, "get_db", _get_db)     # google_calendar 在函式內 from db import get_db
    return st


def _row(row_id):
    conn = _REAL_GET_DB()
    try:
        r = conn.execute("SELECT status, data_json FROM quotations WHERE id=?", (row_id,)).fetchone()
        return r["status"], json.loads(r["data_json"] or "{}")
    finally:
        conn.close()


def _finish(st):
    assert st["fired"], "探針沒有插進空窗（被測路徑變了）"
    st["thread"].join(40)
    return _row(st["row_id"])


def test_update_status(client, make_user, gap):
    u, pw = make_user(username="dw_status", role="superadmin")
    _seed(assigned=[], status="草稿")              # 只有「離開／回到草稿」才會寫 data_json（地點快照）
    h = _login(client, u, pw)
    gap["armed"] = True
    r = client.patch(f"/api/quotations/{NO}/status", headers=h, json={"status": "已送出"})
    assert r.status_code == 200, r.text
    status, d = _finish(gap)
    assert d.get("_probe") == "寫在空窗裡", "整包寫回蓋掉了空窗裡的寫入"
    assert status == "已送出"


def _pending(no, approver, requester="sales_x"):
    from tests.test_approval_reassign_history_2026_09_14 import _seed_quote_pending
    _seed_quote_pending(no, approver)
    conn = _REAL_GET_DB()
    try:
        d = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (no,)).fetchone()[0])
        d["approval"]["requestedBy"] = requester
        conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), no))
        conn.commit()
    finally:
        conn.close()


def test_recall(client, make_user, gap):
    u, pw = make_user(username="dw_recall", role="admin")
    _pending("MQ-DW-RCL", "someone_else", requester=u)
    h = _login(client, u, pw)
    gap["armed"] = True
    r = client.post("/api/quotations/MQ-DW-RCL/recall", headers=h)
    assert r.status_code == 200, r.text
    status, d = _finish(gap)
    assert d.get("_probe") == "寫在空窗裡", "整包寫回蓋掉了空窗裡的寫入"
    assert status == "草稿"


def test_reject(client, make_user, gap):
    u, pw = make_user(username="dw_reject", role="superadmin")
    _pending("MQ-DW-REJ", u)
    h = _login(client, u, pw)
    gap["armed"] = True
    r = client.post("/api/quotations/MQ-DW-REJ/reject", headers=h, json={"note": "探針退回"})
    assert r.status_code == 200, r.text
    status, d = _finish(gap)
    assert d.get("_probe") == "寫在空窗裡", "整包寫回蓋掉了空窗裡的寫入"
    assert status == "草稿"


def test_create_submitted_quotation(client, make_user, gap):
    from tests.test_org_chain_approval_2026_09_15 import _org, _set_dept, _uid, _unified_flow
    me, pw = make_user(username="dw_create", role="admin")
    mgr, _ = make_user(username="dw_mgr", role="admin")
    _, dept = _org(dept_manager=_uid(mgr), div_manager=_uid(mgr))
    _set_dept(me, dept)
    _unified_flow()
    h = _login(client, me, pw)
    gap["armed"] = True
    r = client.post("/api/quotations", headers=h, json={
        "status": "待審核",
        "data": {"customerName": "探針客戶", "projectName": "探針案", "items": [{"description": "品項"}],
                 "approval": {"requestedBy": me, "requestedByDisplay": me, "requestedAt": "2026-09-25T02:00:00"}}})
    assert r.status_code == 201, r.text
    _, d = _finish(gap)
    assert d.get("_probe") == "寫在空窗裡", "整包寫回蓋掉了空窗裡的寫入"
    assert (d.get("approval") or {}).get("tiers"), "送審的簽核層級沒有寫進去"


def test_google_calendar_event_id(client, gap, monkeypatch):
    import helpers.google_calendar as gc
    _seed(assigned=[])
    monkeypatch.setattr(gc, "_create_event_with_retry", lambda *a, **k: "evt-probe")   # 不連外
    gap["armed"] = True
    gc.push_event_for_quotation_won(NO)
    _, d = _finish(gap)
    assert d.get("_probe") == "寫在空窗裡", "寫回 event id 時蓋掉了空窗裡的寫入"
    assert d.get("googleCalendarEventId") == "evt-probe"
