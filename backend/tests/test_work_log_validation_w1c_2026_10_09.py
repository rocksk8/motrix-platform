# -*- coding: utf-8 -*-
"""W1c 端點稽核：工作日誌 POST／PUT 的型別與範圍檢查——壞值要 422，不是 500，也不能把壞資料寫進庫。

原本：`float("abc")` ⇒ 500；`content` 不是字串 ⇒ `AttributeError` 500；不存在的 `user_id` 寫進去（日誌從此沒有主人）；
`PUT` 直接把 body 的值寫進欄位（`hours: "abc"`、`log_date: "昨天"`、`content: 123`）。
"""
import db


def _hdr(client, make_user, name="wl_a"):
    make_user(username=name, role="admin", modules=["work_log"])
    r = client.post("/api/auth/login", json={"username": name, "password": "Test-Pass-123"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _uid(name):
    c = db.get_db()
    try:
        return c.execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()["id"]
    finally:
        c.close()


def _row(wid):
    c = db.get_db()
    try:
        return dict(c.execute("SELECT * FROM work_logs WHERE id=?", (wid,)).fetchone())
    finally:
        c.close()


def _count():
    c = db.get_db()
    try:
        return c.execute("SELECT COUNT(*) FROM work_logs").fetchone()[0]
    finally:
        c.close()


def test_create_valid_still_works_and_defaults_hours(client, make_user):
    h = _hdr(client, make_user)
    uid = _uid("wl_a")
    r = client.post("/api/work-logs", json={"log_date": "2026-10-09", "user_id": str(uid), "content": " 巡檢 "}, headers=h)
    assert r.status_code == 200, r.text
    row = _row(r.json()["id"])
    assert row["content"] == "巡檢" and row["hours"] == 8.0 and row["user_id"] == uid and row["log_date"] == "2026-10-09"
    r = client.post("/api/work-logs", json={"log_date": "2026-10-09", "user_id": uid, "content": "x", "hours": "2.5", "case_no": " Q1 "}, headers=h)
    assert r.status_code == 200 and _row(r.json()["id"])["hours"] == 2.5 and _row(r.json()["id"])["case_no"] == "Q1"


def test_create_rejects_bad_values_with_4xx_and_writes_nothing(client, make_user):
    h = _hdr(client, make_user)
    uid = _uid("wl_a")
    base = {"log_date": "2026-10-09", "user_id": uid, "content": "x", "hours": 1}
    n = _count()
    bad = [dict(base, hours="abc"), dict(base, hours=-1), dict(base, hours=True), dict(base, hours=float("1e999") if False else 10 ** 6),
           dict(base, content=123), dict(base, content=["x"]), dict(base, log_date="昨天"), dict(base, log_date="2026/10/09"), dict(base, log_date=20261009),
           dict(base, user_id=999999), dict(base, user_id="x"), dict(base, user_id=True), dict(base, case_no=5), dict(base, contact_type={"a": 1})]
    for body in bad:
        r = client.post("/api/work-logs", json=body, headers=h)
        assert 400 <= r.status_code < 500, (body, r.status_code, r.text[:120])
    assert _count() == n, "壞值不可寫進庫"
    # 缺欄位／空白內容維持原本的 400
    for body in ({"user_id": uid, "content": "x"}, {"log_date": "2026-10-09", "content": "x"}, dict(base, content="   ")):
        assert client.post("/api/work-logs", json=body, headers=h).status_code == 400, body


def test_update_validates_and_leaves_the_row_untouched_on_error(client, make_user):
    h = _hdr(client, make_user)
    uid = _uid("wl_a")
    wid = client.post("/api/work-logs", json={"log_date": "2026-10-09", "user_id": uid, "content": "原", "hours": 3}, headers=h).json()["id"]
    before = _row(wid)
    for body in ({"hours": "abc"}, {"hours": -5}, {"log_date": "昨天"}, {"content": 123}, {"content": "  "}, {"user_id": 999999}, {"case_no": 7}):
        r = client.put("/api/work-logs/%d" % wid, json=body, headers=h)
        assert 400 <= r.status_code < 500, (body, r.status_code, r.text[:120])
        assert _row(wid) == before, body
    r = client.put("/api/work-logs/%d" % wid, json={"hours": "4.5", "content": " 新 ", "contact_type": " 現場拜訪 "}, headers=h)
    assert r.status_code == 200, r.text
    row = _row(wid)
    assert row["hours"] == 4.5 and row["content"] == "新" and row["contact_type"] == "現場拜訪"
    assert client.put("/api/work-logs/%d" % wid, json={}, headers=h).status_code == 200, "沒有欄位 ⇒ 照舊直接 ok"
