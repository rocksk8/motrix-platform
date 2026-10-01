# -*- coding: utf-8 -*-
"""登入的「待簽核」橫幅每次登入都跳、但已經簽過（使用者 2026-10-01 回報）。

根因：橫幅數字原本＝「未讀的 approval_request 通知列」，而報價單核准／退回／拒絕都沒把那些列標已讀，
所以已簽過的項目永遠算「待簽」。修法：(1) 橫幅改讀真實待簽數 `/api/approval-queue/count`（前端，e2e 驗）；
(2) 報價單核准時只標自己的列已讀、退回／拒絕時標整張單的列已讀（本檔驗）。
正向控制：沒簽之前列是未讀（否則「簽完是已讀」可以靠「一律已讀」變綠）；同層另一位簽核人的列在我簽完之後仍未讀。
"""
from tests._requires import requires_module  # noqa: E402
import json

import pytest
pytestmark = requires_module("case", "本檔打 M01 的報價單簽核端點")

NO = "MQ-202610-901"


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _seed(client, make_user, two_in_tier=False):
    import db
    from helpers.audit import _notify
    me, pw = make_user(username="ans_me", role="admin")
    other, opw = make_user(username="ans_other", role="admin")
    req, _ = make_user(username="ans_req", role="admin")
    approvers = [{"username": me, "displayName": me, "status": "pending"}]
    if two_in_tier:
        approvers.append({"username": other, "displayName": other, "status": "pending"})
    appr = {"requestedBy": req, "requestedByDisplay": req, "requestedAt": "2026-10-01T01:00:00", "currentTier": 0,
            "tiers": [{"approvers": approvers}]}
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, data_json, created_at, updated_at) "
                     "VALUES (?,?,?,?,?,?,?,?)",
                     (NO, "待審核", "客戶", "專案", 1000, json.dumps({"approval": appr}, ensure_ascii=False),
                      "2026-10-01", "2026-10-01"))
        conn.commit()
    finally:
        conn.close()
    for u in [me] + ([other] if two_in_tier else []):
        _notify(u, "approval_request", NO, NO, "待簽核")
    return _login(client, me, pw), _login(client, other, opw), me, other


def _unread_requests(client, headers):
    items = client.get("/api/notifications/mine", headers=headers).json()["items"]
    return [i for i in items if i["type"] == "approval_request" and not i["is_read"]]


def test_notice_unread_before_signing_then_read_after_approve(client, make_user):
    h_me, _h_other, _me, _other = _seed(client, make_user)
    assert len(_unread_requests(client, h_me)) == 1                       # 正向控制：簽之前確實是未讀
    assert client.get("/api/approval-queue/count", headers=h_me).json()["count"] == 1
    r = client.post("/api/quotations/%s/approve" % NO, headers=h_me, json={})
    assert r.status_code == 200, r.text
    assert client.get("/api/approval-queue/count", headers=h_me).json()["count"] == 0
    assert _unread_requests(client, h_me) == [], "簽過了，待簽核通知列還是未讀 ⇒ 橫幅每次登入再跳一次"


def test_approve_only_clears_my_own_notice_not_a_peers(client, make_user):
    h_me, h_other, _me, _other = _seed(client, make_user, two_in_tier=True)
    assert client.post("/api/quotations/%s/approve" % NO, headers=h_me, json={}).status_code == 200
    assert _unread_requests(client, h_me) == []
    assert len(_unread_requests(client, h_other)) == 1                    # 同層另一位還沒簽，他的通知仍有效


def test_return_clears_everyones_notice(client, make_user):
    h_me, h_other, _me, _other = _seed(client, make_user, two_in_tier=True)
    r = client.post("/api/quotations/%s/reject" % NO, headers=h_me, json={"note": "請補資料"})
    assert r.status_code == 200, r.text
    assert _unread_requests(client, h_me) == [] and _unread_requests(client, h_other) == []


def test_reject_final_clears_everyones_notice(client, make_user):
    h_me, h_other, _me, _other = _seed(client, make_user, two_in_tier=True)
    r = client.post("/api/quotations/%s/reject-final" % NO, headers=h_me, json={"note": "不核准"})
    assert r.status_code == 200, r.text
    assert _unread_requests(client, h_me) == [] and _unread_requests(client, h_other) == []
