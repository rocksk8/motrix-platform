"""每月營運報表收件人可設定（2026-08-27）：取代原本寫死只寄 superadmin 的規則。
GET/PUT /api/settings/monthly-report-recipients（backend/routers/system.py）+
_monthly_report_recipient_emails()（backend/helpers/email_notify.py）的行為切分：
設定值從未寫入過 → 沿用舊行為（寄給 superadmin）；寫入過一次（即使是空清單）→
完全依設定值決定收件人。"""
import db


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _set_email(username, email):
    conn = db.get_db()
    try:
        conn.execute("UPDATE users SET email=? WHERE username=?", (email, username))
        conn.commit()
    finally:
        conn.close()


def test_put_requires_superadmin(client, make_user):
    admin_user, admin_pw = make_user(username="admin1", role="admin")
    admin_token = _login(client, admin_user, admin_pw)
    r = client.put("/api/settings/monthly-report-recipients", headers=_auth(admin_token),
                   json={"userIds": [1]})
    assert r.status_code == 403, r.text


def test_get_default_empty(client, make_user):
    sa_user, sa_pw = make_user(username="sa1", role="superadmin")
    token = _login(client, sa_user, sa_pw)
    r = client.get("/api/settings/monthly-report-recipients", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json() == {"userIds": []}


def test_never_configured_falls_back_to_superadmin(client, make_user):
    from helpers.email_notify import _monthly_report_recipient_emails
    sa_user, sa_pw = make_user(username="sa2", role="superadmin")
    _set_email("sa2", "sa2@example.com")
    assert _monthly_report_recipient_emails() == ["sa2@example.com"]


def test_configured_list_fully_replaces_superadmin(client, make_user):
    from helpers.email_notify import _monthly_report_recipient_emails

    sa_user, sa_pw = make_user(username="sa3", role="superadmin")
    _set_email("sa3", "sa3@example.com")
    picked_user, _ = make_user(username="picked", role="engineer")
    _set_email("picked", "picked@example.com")

    sa_token = _login(client, sa_user, sa_pw)
    conn = db.get_db()
    try:
        picked_id = conn.execute("SELECT id FROM users WHERE username='picked'").fetchone()["id"]
    finally:
        conn.close()

    r = client.put("/api/settings/monthly-report-recipients", headers=_auth(sa_token),
                    json={"userIds": [picked_id]})
    assert r.status_code == 200, r.text

    assert _monthly_report_recipient_emails() == ["picked@example.com"]


def test_saving_empty_list_stops_all_recipients(client, make_user):
    from helpers.email_notify import _monthly_report_recipient_emails

    sa_user, sa_pw = make_user(username="sa4", role="superadmin")
    _set_email("sa4", "sa4@example.com")
    sa_token = _login(client, sa_user, sa_pw)

    r = client.put("/api/settings/monthly-report-recipients", headers=_auth(sa_token),
                    json={"userIds": []})
    assert r.status_code == 200, r.text

    assert _monthly_report_recipient_emails() == []
