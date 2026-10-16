# -*- coding: utf-8 -*-
"""T69 SO-S2：刪除暫存區保留天數是設定 `recycle_bin.retention_days`（預設 30、7～365）。
權限與核准一律走真實帳號＋HTTP（設定中心路由）；不 monkeypatch 權限函式。"""
from datetime import datetime, timedelta

import pytest

import db
from helpers import config_ledger as L
from helpers import recycle_bin as RB
from helpers import settings_groups  # noqa: F401
from helpers import settings_registry as SR
from modules.recyclebin import jobs, service as S
from modules.recyclebin.tests.test_recyclebin_p0_t53 import _delete, _doc, _login, _q, env  # noqa: F401  (env＝autouse 合成 adapter)

URL = "/api/settings-center/groups/recycle_bin"


@pytest.fixture(autouse=True)
def _reset_setting():
    SR.invalidate()
    yield
    SR.invalidate()          # 設定帳本只增不刪：各題用「目前值」當基準，不依賴先後順序（default 題要在最前面）


@pytest.fixture
def two_su(client, make_user):
    a, ap = make_user(username="rt_su1", role="superadmin")
    b, bp = make_user(username="rt_su2", role="superadmin")
    c, cp = make_user(username="rt_admin", role="admin")
    return _login(client, a, ap), _login(client, b, bp), _login(client, c, cp), {"username": a, "display_name": a, "role": "superadmin"}


def _days(res):
    row = _q("SELECT deleted_at, purge_after FROM recycle_bin WHERE id=?", res["bin_id"])[0]
    return (datetime.fromisoformat(row["purge_after"]) - datetime.fromisoformat(row["deleted_at"])).total_seconds() / 86400


def test_default_is_30_and_matches_the_old_hardcoded_behaviour(client, two_su):
    su1, _su2, _ad, user = two_su
    f = {x["key"]: x for x in SR.groups()["recycle_bin"]["fields"]}["retention_days"]
    assert (f["default"], f["min"], f["max"], f["loosen"]) == (30, 7, 365, "down")
    assert RB.RETENTION_DAYS == 30 == S.retention_days()
    _doc("T1")
    assert abs(_days(_delete("T1", user)) - 30) < 0.001
    dt = datetime(2026, 10, 17, 9, 30, 0)
    assert S.purge_after_for(dt) == (dt + timedelta(days=RB.RETENTION_DAYS)).isoformat(timespec="seconds")      # 舊公式逐字相同
    assert client.get("/api/recycle-bin/status", headers=su1).json()["retentionDays"] == 30


def test_lengthening_is_immediate_and_changes_only_later_deletions(client, two_su):
    su1, _su2, _ad, user = two_su
    base = S.retention_days()
    new = base + 30
    _doc("L0")
    before = _delete("L0", user)
    r = client.post(URL, json={"values": {"retention_days": new}, "reason": "延長保存"}, headers=su1)
    assert r.status_code == 200 and not r.json().get("pending"), r.text
    assert S.retention_days() == new
    _doc("L1")
    assert abs(_days(_delete("L1", user)) - new) < 0.001
    assert abs(_days(before) - base) < 0.001, "已在暫存區的項目到期日不回頭改寫"
    assert client.get("/api/recycle-bin/status", headers=su1).json()["retentionDays"] == new


def test_shortening_needs_the_second_superadmin_and_the_confirm_period(client, two_su):
    su1, su2, _ad, user = two_su
    cur = S.retention_days() + 20
    assert client.post(URL, json={"values": {"retention_days": cur}, "reason": "先延長"}, headers=su1).status_code == 200
    r = client.post(URL, json={"values": {"retention_days": 14}, "reason": "縮短保存"}, headers=su1)
    assert r.status_code == 200 and r.json().get("pending"), r.text
    assert S.retention_days() == cur, "縮短不會立刻生效"
    cn = db.get_db()
    try:
        rows = L.pending(cn, "setting:recycle_bin")
    finally:
        cn.close()
    assert len(rows) == 1
    cid = rows[0]["id"]
    _doc("S1")
    assert abs(_days(_delete("S1", user)) - cur) < 0.001, "待生效期間新刪除的仍用舊天數"
    assert client.post("/api/settings-center/pending/%d/approve" % cid, json={}, headers=su1).status_code == 409, "提出者自己不能核准"
    assert client.post("/api/settings-center/pending/%d/approve" % cid, json={"reason": "同意"}, headers=su2).status_code == 200
    later = (datetime.now() + timedelta(days=30)).isoformat(timespec="seconds")
    assert S.retention_days() == cur, "核准了但確認期間還沒過"
    cn = db.get_db()
    try:
        assert SR.materialize_due(cn, now=later)
        cn.commit()
    finally:
        cn.close()
    SR.invalidate()
    assert S.retention_days() == 14
    _doc("S2")
    assert abs(_days(_delete("S2", user)) - 14) < 0.001
    assert abs(_days(_q_res("S1")) - cur) < 0.001, "先前刪除的項目不受縮短影響"


def _q_res(no):
    return {"bin_id": _q("SELECT id FROM recycle_bin WHERE entity_id=?", no)[0]["id"]}


def test_non_superadmin_cannot_change_it_and_bounds_are_enforced(client, two_su):
    su1, _su2, ad, _u = two_su
    keep = S.retention_days()
    assert client.post(URL, json={"values": {"retention_days": keep + 1}, "reason": "x"}, headers=ad).status_code in (401, 403)
    for bad in (0, 6, 366, 1000, "abc"):
        r = client.post(URL, json={"values": {"retention_days": bad}, "reason": "x"}, headers=su1)
        assert r.status_code == 400, (bad, r.text)
    assert S.retention_days() == keep


def test_unreadable_setting_falls_back_to_30(monkeypatch):
    monkeypatch.setattr(SR, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert S.retention_days() == 30
    monkeypatch.setattr(SR, "get", lambda *a, **k: 3)
    assert S.retention_days() == 30, "不合法的值也不採用"


def test_daily_job_notice_uses_the_setting(client, two_su):
    su1, _su2, _ad, user = two_su
    n = S.retention_days() + 5
    assert client.post(URL, json={"values": {"retention_days": n}, "reason": "調整"}, headers=su1).status_code == 200
    _doc("J1")
    res = _delete("J1", user)
    cn = db.get_db()
    cn.execute("UPDATE recycle_bin SET purge_after=? WHERE id=?", ((datetime.now() - timedelta(days=1)).isoformat(timespec="seconds"), res["bin_id"]))
    cn.commit()
    cn.close()
    assert jobs.run_daily()["purged"] == 1
    notes = _q("SELECT * FROM notifications WHERE type='recyclebin_daily'")
    assert notes and any("超過 %d 天" % n in str(dict(x)) for x in notes)


def test_approved_delete_notice_uses_the_setting(client, two_su):
    su1, _su2, _ad, _u = two_su
    n = S.retention_days() + 3
    assert client.post(URL, json={"values": {"retention_days": n}, "reason": "調整"}, headers=su1).status_code == 200
    _doc("AP1", status="已核准")
    r = client.post("/api/recycle-bin/delete-approved", headers=su1,
                    json={"entity_type": "rbn_doc", "entity_id": "AP1", "confirm": True, "confirm_text": "AP1", "reason": "測試"})
    assert r.status_code in (200, 201), r.text
    notes = _q("SELECT * FROM notifications WHERE type='recyclebin_delete_approved' AND username=?", "rt_su2")
    assert notes and any("%d 天內可還原" % n in str(dict(x)) for x in notes)


def test_single_superadmin_shortening_is_pending_with_a_clear_warning(client, two_su, make_user):
    """只有一位最高管理者：縮短不能讓自己核准自己 ⇒ 改為『原因＋確認期間』，回應要明說；確認期間後才生效。"""
    solo, solo_pw = make_user(username="rt_solo", role="superadmin")
    su = _login(client, solo, solo_pw)
    cn = db.get_db()
    others = [r[0] for r in cn.execute("SELECT id FROM users WHERE role='superadmin' AND active=1 AND username<>?", (solo,)).fetchall()]
    try:
        for i in others:
            cn.execute("UPDATE users SET active=0 WHERE id=?", (i,))
        cn.commit()
        cur = S.retention_days() + 20
        assert client.post(URL, json={"values": {"retention_days": cur}, "reason": "先延長"}, headers=su).status_code == 200
        r = client.post(URL, json={"values": {"retention_days": 10}, "reason": "縮短保存"}, headers=su)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["pending"] and all(p["approvalsRequired"] == 0 for p in d["pending"]), d
        assert any("只有一位最高管理者" in w for w in d["warnings"]), d
        assert S.retention_days() == cur, "確認期間內不生效"
        later = (datetime.now() + timedelta(days=30)).isoformat(timespec="seconds")
        cn2 = db.get_db()
        try:
            assert SR.materialize_due(cn2, now=later)
            cn2.commit()
        finally:
            cn2.close()
        SR.invalidate()
        assert S.retention_days() == 10
    finally:
        for i in others:
            cn.execute("UPDATE users SET active=1 WHERE id=?", (i,))
        cn.commit()
        cn.close()
