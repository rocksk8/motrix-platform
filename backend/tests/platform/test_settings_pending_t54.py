# -*- coding: utf-8 -*-
"""第 54 班 Train A：風險欄位的 24 小時待生效（requires_pending）＋部署零行為變更的凍結基準。"""
import json
import os
from datetime import datetime, timedelta

import pytest

from db import get_db
from helpers import config_ledger as L
from helpers import settings_groups  # noqa: F401
from helpers import settings_registry as R

BASELINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings_deploy_baseline.json")


@pytest.fixture()
def conn(client):
    c = get_db()
    R.invalidate()
    R.register_group("zz_pending_t54", "待生效測試", [
        R.SettingDef("limit", "int", 100, min=1, max=1000, risk="money", requires_pending=True),
        R.SettingDef("note_days", "int", 7, min=1, max=30, risk="ops"),
    ], risk="money")
    yield c
    R._GROUPS.pop("zz_pending_t54", None)
    c.close()
    R.invalidate()


def test_risky_field_waits_24h_then_materializes(conn):
    out = R.publish("zz_pending_t54", {"limit": 200}, reason="調高", user="admin", conn=conn)
    assert out["pending"] and out["changed"] is False
    assert R.get("zz_pending_t54", "limit", conn=conn) == 100                 # 還沒生效
    rows = L.pending(conn, "setting:zz_pending_t54")
    assert len(rows) == 1 and rows[0]["effective_at"] > datetime.now().isoformat()
    later = (datetime.now() + timedelta(hours=25)).isoformat(timespec="seconds")
    assert R.get_group("zz_pending_t54", conn=conn, now=later)["limit"] == 200   # 讀取時判斷：到期即生效，不靠排程
    done = R.materialize_due(conn, now=later)
    conn.commit()
    assert done == 1 and R.get("zz_pending_t54", "limit", conn=conn) == 200
    assert L.pending(conn, "setting:zz_pending_t54") == []


def test_cancel_pending(conn):
    R.publish("zz_pending_t54", {"limit": 300}, reason="x", user="admin", conn=conn)
    cid = L.pending(conn, "setting:zz_pending_t54")[0]["id"]
    assert L.cancel(conn, cid, "admin", "撤銷") is True
    conn.commit()
    later = (datetime.now() + timedelta(hours=48)).isoformat(timespec="seconds")
    assert R.get_group("zz_pending_t54", conn=conn, now=later)["limit"] == 100


def test_mixed_publish_immediate_part_applies_now(conn):
    out = R.publish("zz_pending_t54", {"limit": 150, "note_days": 9}, reason="x", user="admin", conn=conn)
    assert out["changed"] and len(out["pending"]) == 1
    assert R.get("zz_pending_t54", "note_days", conn=conn) == 9 and R.get("zz_pending_t54", "limit", conn=conn) == 100


def test_newer_request_supersedes_older(conn):
    R.publish("zz_pending_t54", {"limit": 150}, reason="a", user="admin", conn=conn)
    R.publish("zz_pending_t54", {"limit": 160}, reason="b", user="admin", conn=conn)
    rows = L.pending(conn, "setting:zz_pending_t54")
    assert [r["new"] for r in rows] == [160]


def test_pending_api_list_and_cancel(client, make_user):
    username, password = make_user(username="pend_sa", role="superadmin")
    tok = client.post("/api/auth/login", json={"username": username, "password": password}).json()["token"]
    h = {"Authorization": "Bearer " + tok}
    assert client.get("/api/settings-center/pending", headers=h).json()["pending"] == []
    assert client.post("/api/settings-center/pending/999999/cancel", json={"reason": "x"}, headers=h).status_code == 404


def test_deploy_baseline_frozen():
    """部署零行為變更：每個登錄群組的預設值與範圍等於凍結基準（改動＝行為變更，要同步改基準並走裁示）；沒有任何欄位預設 requires_pending。"""
    frozen = json.load(open(BASELINE, encoding="utf-8"))
    now = {g: {f["key"]: [f["default"], f["min"], f["max"], f["clamp"]] for f in m["fields"]} for g, m in R.groups().items()
           if not g.startswith("zz_")}
    assert now == frozen["groups"]


def test_no_definition_rows_after_boot(client):
    c = get_db()
    try:
        assert c.execute("SELECT COUNT(*) FROM ui_definitions WHERE kind='setting_group'").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM config_changes").fetchone()[0] == 0
    finally:
        c.close()


def test_defaults_equal_legacy_constants():
    import archive
    from helpers import audit, uploads
    r = R.get_group("retention")
    for k, v in archive._BACKUP_RETENTION_DEFAULT.items():
        assert r[k] == v
    assert r["notification_keep_days"] == audit.NOTIFICATION_RETENTION_DAYS
    u = R.get_group("uploads")
    assert u["max_file_mb"] * 1024 * 1024 == uploads._DEFAULT_MAX_FILE_SIZE
    lim = uploads.UPLOAD_LIMITS_BY_SUBFOLDER["case_extra_expense"]
    assert (u["case_extra_expense_max_files"], u["case_extra_expense_max_request_mb"] * 1024 * 1024) == (lim["max_files"], lim["max_request_bytes"])
