"""2026-08-28 資訊安全優化：高權限帳號（superadmin/admin）閒置逾時縮短為 2 小時。

系統原本就有全域 8 小時閒置自動登出機制（main.py::auth_middleware，DB v17
last_active 欄位，2026-07-21 上線）——這輪一開始誤以為完全沒有這個機制、
在 helpers/auth.py 另外疊了一份重複邏輯，後來發現 main.py 早就做了才改成
在既有機制上依角色套用不同門檻（is_high_priv 分支），而不是新增第二套獨立機制。
"""
from datetime import datetime, timedelta


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _set_last_active(token, minutes_ago):
    import db
    conn = db.get_db()
    try:
        stale = (datetime.now() - timedelta(minutes=minutes_ago)).isoformat()
        conn.execute("UPDATE sessions SET last_active=? WHERE token=?", (stale, token))
        conn.commit()
    finally:
        conn.close()


def test_admin_idle_timeout_after_2_hours(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    r0 = client.get("/api/audit-log", headers=_auth(token))
    assert r0.status_code == 200, r0.text

    _set_last_active(token, minutes_ago=121)  # 超過 2 小時門檻
    r1 = client.get("/api/audit-log", headers=_auth(token))
    assert r1.status_code == 401, r1.text
    assert "2 小時" in r1.json()["detail"]

    # session 應已被刪除，之後同一個 token 一律視為過期
    r2 = client.get("/api/audit-log", headers=_auth(token))
    assert r2.status_code == 401, r2.text


def test_admin_within_2_hour_window_stays_valid(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _set_last_active(token, minutes_ago=119)  # 未超過門檻
    r = client.get("/api/audit-log", headers=_auth(token))
    assert r.status_code == 200, r.text


def test_superadmin_idle_timeout_also_uses_2_hour_limit(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    _set_last_active(token, minutes_ago=130)
    r = client.get("/api/audit-log", headers=_auth(token))
    assert r.status_code == 401, r.text
    assert "2 小時" in r.json()["detail"]


def test_non_admin_role_keeps_original_8_hour_limit(client, make_user):
    """sales/engineer/viewer 沿用原本的 8 小時門檻，不受這次新增的 2 小時限制——
    閒置 5 小時（超過 2 小時但未達 8 小時）應該仍然有效。"""
    username, password = make_user(role="sales")
    token = _login(client, username, password)
    _set_last_active(token, minutes_ago=300)  # 5 小時：> 2hr 但 < 8hr
    r = client.get("/api/auth/me", headers=_auth(token))
    assert r.status_code == 200, r.text


def test_non_admin_role_still_expires_after_8_hours(client, make_user):
    """既有全域 8 小時機制對一般角色仍然生效，這次改動沒有意外放寬它。"""
    username, password = make_user(role="sales")
    token = _login(client, username, password)
    _set_last_active(token, minutes_ago=500)  # > 8 小時
    r = client.get("/api/auth/me", headers=_auth(token))
    assert r.status_code == 401, r.text
    assert "8 小時" in r.json()["detail"]
