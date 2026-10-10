# -*- coding: utf-8 -*-
"""第 54 班 Train A：設定登錄、讀取、發布、變更明細（config_ledger）。"""
import json

import pytest

from core import definitions as D
from db import get_db
from helpers import config_ledger as L
from helpers import settings_groups  # noqa: F401  登錄群組
from helpers import settings_registry as R


@pytest.fixture()
def conn(client):
    c = get_db()
    R.invalidate()
    yield c
    c.close()
    R.invalidate()


def test_defaults_without_rows(conn):
    assert R.get("retention", "audit_log_keep_days") == 1825
    assert R.get("retention", "local_db_keep_days") == 30
    assert R.get("uploads", "max_file_mb") == 20
    assert conn.execute("SELECT COUNT(*) FROM ui_definitions WHERE kind='setting_group'").fetchone()[0] == 0


def test_legacy_dual_read(conn):
    conn.execute("INSERT OR REPLACE INTO system_settings (key, value_json, updated_at) VALUES ('backup_retention', ?, 'x')",
                 (json.dumps({"local_db_keep_days": 45, "audit_log_keep_days": 100}),))
    conn.commit()
    R.invalidate()
    assert R.get("retention", "local_db_keep_days") == 45
    assert R.get("retention", "audit_log_keep_days") == 365         # 讀取時夾到下限


def test_publish_writes_ledger_audit_and_legacy(conn):
    out = R.publish("retention", {"local_db_keep_days": 40}, reason="測試", user="admin", conn=conn)
    assert out["changed"] and out["version"] == 1
    assert R.get("retention", "local_db_keep_days") == 40
    rows = L.history(conn, "setting", "retention")
    assert [(r["field"], r["old"], r["new"], r["state"]) for r in rows] == [("local_db_keep_days", 30, 40, "immediate")]
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='settings.retention.update'").fetchone()[0] == 1
    legacy = json.loads(conn.execute("SELECT value_json FROM system_settings WHERE key='backup_retention'").fetchone()[0])
    assert legacy["local_db_keep_days"] == 40
    assert "notification_keep_days" not in legacy


def test_no_change_no_version(conn):
    assert R.publish("retention", {"local_db_keep_days": 30}, user="admin", conn=conn)["changed"] is False
    assert D.get(conn, "setting_group", "retention", "company") is None


def test_validation_rejects(conn):
    with pytest.raises(R.SettingError):
        R.publish("retention", {"audit_log_keep_days": 100}, user="admin", conn=conn)
    with pytest.raises(R.SettingError):
        R.publish("retention", {"local_db_keep_days": 0}, user="admin", conn=conn)
    with pytest.raises(R.SettingError):
        R.publish("retention", {"nope": 1}, user="admin", conn=conn)
    with pytest.raises(R.SettingError):
        R.publish("uploads", {"max_file_mb": True}, user="admin", conn=conn)


def test_bad_stored_value_falls_back(conn):
    R.publish("uploads", {"max_file_mb": 30}, user="x", conn=conn)
    conn.execute("UPDATE ui_definitions SET body_json=? WHERE kind='setting_group' AND key='uploads'",
                 (json.dumps({"group": "uploads", "values": {"max_file_mb": "abc"}}),))
    conn.commit()
    R.invalidate()
    assert R.get("uploads", "max_file_mb") == 20


def test_defaults_only_env(conn, monkeypatch):
    R.publish("uploads", {"max_file_mb": 30}, user="admin", conn=conn)
    assert R.get("uploads", "max_file_mb") == 30
    monkeypatch.setenv("MOTRIX_SETTINGS_DEFAULTS_ONLY", "1")
    assert R.get("uploads", "max_file_mb") == 20


def test_ledger_immutable_and_events(conn):
    r = L.record(conn, "setting:x", "x", [{"field": "a", "old": 1, "new": 2}], "why", "u", effective_at="2999-01-01T00:00:00")
    conn.commit()
    cid = r["ids"][0]
    assert L.state_of(conn, cid) == "pending"
    assert L.in_effect(L.history(conn, "setting:x")[0], "2000-01-01T00:00:00") is False
    assert L.cancel(conn, cid, "u") is True and L.state_of(conn, cid) == "cancelled"
    assert L.cancel(conn, cid, "u") is False
    conn.commit()
    with pytest.raises(Exception):
        conn.execute("UPDATE config_changes SET new_json='9' WHERE id=?", (cid,))
    with pytest.raises(Exception):
        conn.execute("DELETE FROM config_change_events")


def test_activate_due(conn):
    r = L.record(conn, "setting:x", "x", [{"field": "a", "old": 1, "new": 2}], "", "u", effective_at="2020-01-01T00:00:00")
    assert L.activate_due(conn, "2021-01-01T00:00:00") == r["ids"]
    assert L.state_of(conn, r["ids"][0]) == "activated"


def test_high_risk_notifies_other_superadmins_only(conn, make_user):
    make_user("sa_actor", role="superadmin")
    make_user("sa_other", role="superadmin")
    L.record(conn, "setting:retention", "retention", [{"field": "audit_log_keep_days", "old": 1825, "new": 400}], "縮短", "sa_actor", risk="legal")
    conn.commit()
    who = {r[0] for r in conn.execute("SELECT username FROM notifications WHERE type='config_change'").fetchall()}
    assert "sa_other" in who and "sa_actor" not in who


# --- API ---------------------------------------------------------------

def _hdr(client, make_user, role="superadmin", name="sc_" ):
    username, password = make_user(username=name + role, role=role)
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_api_anonymous_blocked(client):
    for m, u in (("get", "/api/settings-center/groups"), ("get", "/api/settings-center/groups/retention"),
                 ("post", "/api/settings-center/groups/retention"), ("get", "/api/settings-center/public?groups=uploads")):
        assert getattr(client, m)(u).status_code in (401, 403), u


def test_api_list_save_and_history(client, make_user):
    h = _hdr(client, make_user)
    r = client.get("/api/settings-center/groups", headers=h)
    assert r.status_code == 200
    assert {g["group"] for g in r.json()["groups"]} >= {"retention", "uploads"}
    assert client.post("/api/settings-center/groups/uploads", json={"values": {"max_file_mb": 25}}, headers=h).status_code == 400   # 缺原因
    bad = client.post("/api/settings-center/groups/retention", json={"values": {"audit_log_keep_days": 100}, "reason": "x"}, headers=h)
    assert bad.status_code == 400
    ok = client.post("/api/settings-center/groups/uploads", json={"values": {"max_file_mb": 25}, "reason": "測試"}, headers=h)
    assert ok.status_code == 200 and ok.json()["changed"] is True
    d = client.get("/api/settings-center/groups/uploads", headers=h).json()
    assert d["values"]["max_file_mb"] == 25 and d["history"][0]["field"] == "max_file_mb" and d["history"][0]["reason"] == "測試"
    assert client.get("/api/settings-center/groups/nope", headers=h).status_code == 404


def test_api_public_visibility(client, make_user):
    hs = _hdr(client, make_user)
    ha = _hdr(client, make_user, role="admin")
    assert client.get("/api/settings-center/public?groups=uploads", headers=ha).json()["groups"]["uploads"]["max_file_mb"] == 20
    assert client.get("/api/settings-center/public?groups=retention", headers=ha).status_code == 403
    assert client.get("/api/settings-center/public?groups=retention", headers=hs).status_code == 200
    assert client.get("/api/settings-center/groups", headers=ha).status_code == 403


def test_legacy_patch_floor_and_dual_write(client, make_user):
    h = _hdr(client, make_user)
    low = client.patch("/api/settings/backup-retention", json={"audit_log_keep_days": 100}, headers=h)
    assert low.status_code == 400
    ok = client.patch("/api/settings/backup-retention", json={"local_db_keep_days": 44}, headers=h)
    assert ok.status_code == 200
    got = client.get("/api/settings/backup-retention", headers=h).json()
    assert got["local_db_keep_days"] == 44 and set(got) == {"local_db_keep_days", "cloud_daily_keep_days", "cloud_weekly_keep_days",
                                                         "cloud_monthly_keep_days", "local_pre_update_keep", "audit_log_keep_days"}
    assert client.get("/api/settings-center/groups/retention", headers=h).json()["values"]["local_db_keep_days"] == 44
