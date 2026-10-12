# -*- coding: utf-8 -*-
"""S1-1（2026-10-13）：設定群組是『受管 kind』——通用定義端點不能直接改它（否則單一最高管理者可繞過 放寬→待生效→第二人核准 與變更明細）；
另鎖定 `config_ledger.restore_version` 的順序（先撤舊待生效、再寫還原結果；否則還原成較寬鬆的舊值會被自己撤銷）。"""
from datetime import datetime, timedelta

import pytest

from core import definitions as D
from db import get_db
from helpers import config_ledger as L
from helpers import settings_groups  # noqa: F401  登錄群組
from helpers import settings_registry as R

GROUP = "retention"
FIELD = "audit_log_keep_days"          # 縮短＝放寬（loosen='down'），下限 365


def _hdr(client, make_user, name):
    username, password = make_user(username=name, role="superadmin")
    tok = client.post("/api/auth/login", json={"username": username, "password": password}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _later(days=30):
    return (datetime.now() + timedelta(days=days)).isoformat(timespec="seconds")


def _counts(c):
    return (c.execute("SELECT COUNT(*) FROM config_changes").fetchone()[0],
            c.execute("SELECT COUNT(*) FROM ui_definitions WHERE kind=?", (R.KIND,)).fetchone()[0])


def test_generic_definition_writes_to_setting_group_are_refused(client, make_user):
    h = _hdr(client, make_user, "s11_a")
    c = get_db()
    try:
        before = _counts(c)
        body = {"group": GROUP, "values": {FIELD: 365}}
        r = client.put("/api/definitions/%s/%s/draft" % (R.KIND, GROUP), json={"body": body}, headers=h)
        assert r.status_code == 409 and "設定中心" in r.json()["detail"]
        assert client.post("/api/definitions/%s/%s/publish" % (R.KIND, GROUP), json={"note": "x"}, headers=h).status_code == 409
        assert client.post("/api/definitions/%s/%s/restore/1" % (R.KIND, GROUP), json={}, headers=h).status_code == 409
        assert client.delete("/api/definitions/%s/%s/draft" % (R.KIND, GROUP), headers=h).status_code == 409
        assert _counts(c) == before                                              # 沒有任何定義列、沒有任何變更明細
        assert R.get(GROUP, FIELD, conn=c) == 1825                               # 值沒動
    finally:
        c.close()


def test_non_superadmin_still_gets_403_not_409(client, make_user):
    username, password = make_user(username="s11_user", role="admin")
    tok = client.post("/api/auth/login", json={"username": username, "password": password}).json()["token"]
    h = {"Authorization": "Bearer " + tok}
    assert client.post("/api/definitions/%s/%s/publish" % (R.KIND, GROUP), json={}, headers=h).status_code == 403


def test_settings_center_remains_the_write_path_and_reads_stay_open(client, make_user):
    h = _hdr(client, make_user, "s11_b")
    r = client.post("/api/settings-center/groups/%s" % GROUP, json={"values": {"local_db_keep_days": 40}, "reason": "測試"}, headers=h)
    assert r.status_code == 200 and r.json()["changed"] is True
    # 版本與差異（GET）仍可用——設定中心的『版本』頁要靠它們
    g = client.get("/api/definitions/%s/%s" % (R.KIND, GROUP), headers=h)
    assert g.status_code == 200 and g.json()["latest"]["body"]["values"]["local_db_keep_days"] == 40 and g.json()["versions"]
    assert client.get("/api/definitions/%s/%s/diff?a=default&b=latest" % (R.KIND, GROUP), headers=h).status_code == 200
    assert client.get("/api/definitions/%s" % R.KIND, headers=h).status_code == 200


def test_other_kinds_are_not_affected(client, make_user):
    h = _hdr(client, make_user, "s11_c")
    other = [k for k in D.kinds() if k != R.KIND][0]
    r = client.delete("/api/definitions/%s/zz_no_such_key/draft" % other, headers=h)
    assert r.status_code != 409                                                  # 照舊：沒有草稿 ⇒ 404（或該 kind 自己的 400）


# --- config_ledger.restore_version 的順序 ----------------------------------------------------

@pytest.fixture()
def seq(client, make_user):
    make_user(username="s11_x", role="superadmin")
    make_user(username="s11_y", role="superadmin")
    c = get_db()
    R.invalidate()
    yield c
    c.close()
    R.invalidate()


def _approve_and_activate(c, out, approver="s11_y"):
    for p in out["pending"]:
        if p["approvalsRequired"]:
            assert L.approve(c, p["id"], approver)["ok"]
    c.commit()
    R.materialize_due(c, now=_later())
    c.commit()
    R.invalidate()


def _latest_version(c):
    return D.get(c, R.KIND, GROUP, R.SCOPE)["version"]


def test_restore_to_a_looser_old_value_leaves_a_live_pending_item(seq):
    c = seq
    R.publish(GROUP, {FIELD: 2000}, reason="延長", user="s11_x", conn=c)                      # 延長＝收緊，立即
    out = R.publish(GROUP, {FIELD: 400}, reason="縮短", user="s11_x", conn=c)                  # 縮短＝放寬，待生效＋核准
    assert out["pending"] and out["changed"] is False
    _approve_and_activate(c, out)
    v_loose = _latest_version(c)
    assert R.get(GROUP, FIELD, conn=c) == 400
    R.publish(GROUP, {FIELD: 3000}, reason="再延長", user="s11_x", conn=c)                    # 回到較緊
    assert R.get(GROUP, FIELD, conn=c) == 3000

    L.restore_version(c, "setting:" + GROUP, GROUP, v_loose, "s11_x", "回復到較鬆的舊版")
    c.commit()
    R.invalidate()
    live = [p for p in L.pending(c, "setting:" + GROUP) if p["field"] == FIELD]
    assert live and live[0]["new"] == 400                                                      # 修正前：被緊接著的撤銷一起撤掉 ⇒ []
    assert L.state_of(c, live[0]["id"]) == "pending"
    assert R.get(GROUP, FIELD, conn=c) == 3000                                                 # 放寬不立即生效


def test_restore_to_a_tighter_old_value_is_immediate_and_cancels_older_pending(seq):
    c = seq
    R.publish(GROUP, {FIELD: 3000}, reason="延長", user="s11_x", conn=c)
    v_tight = _latest_version(c)
    out = R.publish(GROUP, {FIELD: 400}, reason="縮短", user="s11_x", conn=c)
    _approve_and_activate(c, out)
    assert R.get(GROUP, FIELD, conn=c) == 400
    older = R.publish(GROUP, {FIELD: 365}, reason="再縮短", user="s11_x", conn=c)["pending"][0]["id"]   # 一筆還在等的放寬

    L.restore_version(c, "setting:" + GROUP, GROUP, v_tight, "s11_x", "回復到較緊的舊版")
    c.commit()
    R.invalidate()
    assert R.get(GROUP, FIELD, conn=c) == 3000                                                 # 收緊立即生效
    assert L.state_of(c, older) in ("cancelled", "superseded")                                 # 舊的待生效項不會事後蓋過還原結果
    assert [p for p in L.pending(c, "setting:" + GROUP) if p["field"] == FIELD] == []
