# -*- coding: utf-8 -*-
"""BP-4 S4：完工單的兩個事件發佈行（`completion_note.attachment_added`／`completion_note.state_changed`）。

發佈在各自的 commit 之後；payload 欄位與宣告一致；旗標關（預設）時發佈不產生任何通知（訂閱者什麼都不做）。
"""
import io

import pytest

from core import events as EV
from tests._requires import requires_module
from tests.test_completion_notes_2026_09_12 import BASE, _auth, _create, _login, _make_case, _single_tier_flow

pytestmark = requires_module("case", "本檔的題打 M01（案件）的端點")


@pytest.fixture()
def seen():
    got = []
    state = EV.snapshot()
    for n in ("completion_note.attachment_added", "completion_note.state_changed"):
        EV.subscribe(n, lambda p, n=n: got.append((n, p)), "test_cn_events")
    yield got
    EV.restore(state)


def test_state_events_follow_the_approval_round_trip(client, make_user, seen):
    author, apw = make_user(username="cne_a", role="admin")
    approver, ppw = make_user(username="cne_ap", role="superadmin")
    token = _login(client, author, apw)
    _make_case()
    _single_tier_flow(approver)
    note_no = _create(client, token)
    assert client.post(f"{BASE}/{note_no}/submit", headers=_auth(token)).status_code == 200
    atoken = _login(client, approver, ppw)
    assert client.post(f"{BASE}/{note_no}/approve", headers=_auth(atoken), json={}).status_code == 200
    assert client.post(f"{BASE}/{note_no}/revoke-approval", headers=_auth(atoken), json={"note": "x"}).status_code == 200
    got = [(p["from"], p["to"], p["by"]) for n, p in seen if n == "completion_note.state_changed"]
    assert got == [("草稿", "待審核", "cne_a"), ("待審核", "已核准", "cne_ap"), ("已核准", "草稿", "cne_ap")]
    assert all(p["noteNo"] == note_no and p["quoteNo"] for n, p in seen if n == "completion_note.state_changed")


def test_reject_publishes_the_return_to_draft(client, make_user, seen):
    author, apw = make_user(username="cne_a2", role="admin")
    approver, ppw = make_user(username="cne_ap2", role="superadmin")
    token = _login(client, author, apw)
    _make_case()
    _single_tier_flow(approver)
    note_no = _create(client, token)
    client.post(f"{BASE}/{note_no}/submit", headers=_auth(token))
    r = client.post(f"{BASE}/{note_no}/reject", headers=_auth(_login(client, approver, ppw)), json={"note": "補測試報告"})
    assert r.status_code == 200, r.text
    assert [(p["from"], p["to"]) for n, p in seen if n == "completion_note.state_changed"][-1] == ("待審核", "草稿")


def test_attachment_upload_publishes_after_commit(client, make_user, seen):
    username, password = make_user(username="cne_f", role="admin")
    token = _login(client, username, password)
    _make_case()
    note_no = _create(client, token)
    r = client.post(f"{BASE}/{note_no}/signed-files", headers=_auth(token),
                    files={"files": ("signed.png", io.BytesIO(b"\x89PNG\r\n\x1a\n fake"), "image/png")})
    assert r.status_code == 201, r.text
    ev = [p for n, p in seen if n == "completion_note.attachment_added"]
    assert len(ev) == 1 and ev[0]["noteNo"] == note_no and ev[0]["slot"] == "signed" and ev[0]["by"] == "cne_f" and ev[0]["quoteNo"]


def test_publishing_with_the_flag_off_creates_no_notifications(client, make_user, seen):
    import db
    username, password = make_user(username="cne_off", role="admin")
    token = _login(client, username, password)
    _make_case()
    note_no = _create(client, token)
    conn = db.get_db()
    try:
        n0 = conn.execute("SELECT COUNT(*) c FROM notifications WHERE type='notify_action'").fetchone()["c"]
        client.post(f"{BASE}/{note_no}/submit", headers=_auth(token))
        assert conn.execute("SELECT COUNT(*) c FROM notifications WHERE type='notify_action'").fetchone()["c"] == n0
    finally:
        conn.close()
