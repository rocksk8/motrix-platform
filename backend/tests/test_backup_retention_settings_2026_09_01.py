"""備份保留天數可調整設定（使用者要求「備份次數跟週期可調整避免檔案過大」，
2026-09-01）——見 archive.py::_backup_retention()（system_settings.backup_retention，
預設值 cloud_daily_keep_days=1825／5年，其餘沿用原本寫死的值）+
routers/system.py 的 GET/PATCH /api/settings/backup-retention。"""


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_backup_retention_default_is_five_years_daily(client):
    """未曾設定過時，_backup_retention() 回傳的預設值就是使用者要求的
    5年（1825天）雲端每日備份，不需要先手動存一次設定才生效。"""
    import archive
    retention = archive._backup_retention()
    assert retention["cloud_daily_keep_days"] == 1825
    assert retention["cloud_weekly_keep_days"] == 730
    assert retention["local_db_keep_days"] == 30
    assert retention["audit_log_keep_days"] == 730


def test_get_backup_retention_requires_superadmin(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    r = client.get("/api/settings/backup-retention", headers=_auth(token))
    assert r.status_code == 403, r.text


def test_patch_backup_retention_requires_superadmin(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    r = client.patch(
        "/api/settings/backup-retention", headers=_auth(token),
        json={"local_db_keep_days": 30, "cloud_daily_keep_days": 1825,
              "cloud_weekly_keep_days": 730, "audit_log_keep_days": 730},
    )
    assert r.status_code == 403, r.text


def test_patch_backup_retention_updates_and_persists(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)

    g = client.get("/api/settings/backup-retention", headers=_auth(token))
    assert g.status_code == 200, g.text
    assert g.json()["cloud_daily_keep_days"] == 1825

    p = client.patch(
        "/api/settings/backup-retention", headers=_auth(token),
        json={"local_db_keep_days": 14, "cloud_daily_keep_days": 90,
              "cloud_weekly_keep_days": 365, "audit_log_keep_days": 365},
    )
    assert p.status_code == 200, p.text

    g2 = client.get("/api/settings/backup-retention", headers=_auth(token))
    body = g2.json()
    assert body["local_db_keep_days"] == 14
    assert body["cloud_daily_keep_days"] == 90
    assert body["cloud_weekly_keep_days"] == 365
    assert body["audit_log_keep_days"] == 365

    import archive
    assert archive._backup_retention()["cloud_daily_keep_days"] == 90


def test_patch_backup_retention_rejects_out_of_range(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    r = client.patch(
        "/api/settings/backup-retention", headers=_auth(token),
        json={"local_db_keep_days": 0, "cloud_daily_keep_days": 1825,
              "cloud_weekly_keep_days": 730, "audit_log_keep_days": 730},
    )
    assert r.status_code == 400, r.text
    r2 = client.patch(
        "/api/settings/backup-retention", headers=_auth(token),
        json={"local_db_keep_days": 30, "cloud_daily_keep_days": 99999,
              "cloud_weekly_keep_days": 730, "audit_log_keep_days": 730},
    )
    assert r2.status_code == 400, r2.text
