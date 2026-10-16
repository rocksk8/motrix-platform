# -*- coding: utf-8 -*-
"""T69 管銷分攤預設比率 `overhead.default_pct`（使用者裁示：預設 25 變成設定；調低＝放寬＝第二位最高管理者核准＋確認期間，調高立即生效）。

真實帳號＋HTTP：不 patch 權限／可見度。判準
① 預設等值：沒動過 ⇒ 25（舊入口、設定中心、PG.default_pct、PDF 預設都是 25）
② 調高立即生效，且舊鍵 `overhead_default_pct` 同值（雙寫等值：舊入口／設定中心兩條入口各驗一次）
③ 調低兩條入口都是待核准（沒有繞過）：現值不變、舊鍵不變；申請人不能自己核准；第二位核准且到時之後才生效，舊鍵隨生效同步
④ 上線前已存在的舊鍵值（例如 20）原樣沿用，不被預設 25 蓋掉
⑤ 壞值：舊鍵是字串 ⇒ 25；超過 1 位小數／超出 0～100 被拒
⑥ 非最高管理者打舊入口 403
"""
import json
from datetime import datetime, timedelta

import pytest

import db
from helpers import settings_registry as SR
from modules.case import profit_guard as PG


def _login(client, make_user, name, role="superadmin"):
    u, p = make_user(username=name, role=role)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def two_su(client, make_user):
    return _login(client, make_user, "ohp_sa1"), _login(client, make_user, "ohp_sa2")


def _legacy():
    c = db.get_db()
    try:
        r = c.execute("SELECT value_json FROM system_settings WHERE key='overhead_default_pct'").fetchone()
        return json.loads(r[0]) if r else None
    finally:
        c.close()


def _center(client, h):
    r = client.get("/api/settings-center/groups/overhead", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _center_value(client, h):
    d = _center(client, h)
    vals = d.get("values") or d.get("effective") or {}
    return vals.get("default_pct")


def _old_get(client, h):
    return client.get("/api/overhead/settings", headers=h).json()["defaultPct"]


def _future():
    return (datetime.now() + timedelta(days=60)).isoformat(timespec="seconds")


def test_default_is_25_everywhere_when_untouched(client, two_su):
    sa1, _ = two_su
    assert _old_get(client, sa1) == 25 and PG.default_pct() == 25 and _center_value(client, sa1) == 25
    import pdf_gen
    assert pdf_gen.default_overhead_pct() == 25.0
    assert _legacy() is None                                   # 沒動過 ⇒ 不產生舊鍵列


def test_raise_via_old_entrance_is_immediate_and_legacy_key_matches(client, two_su):
    sa1, _ = two_su
    r = client.put("/api/overhead/settings", json={"defaultPct": 30, "reason": "年度調整管銷預設"}, headers=sa1)
    assert r.status_code == 200 and r.json()["defaultPct"] == 30 and r.json()["pending"] == [], r.text
    assert PG.default_pct() == 30 and _center_value(client, sa1) == 30 and _old_get(client, sa1) == 30
    assert _legacy() == 30                                      # 雙寫等值
    import pdf_gen
    assert pdf_gen.default_overhead_pct() == 30.0


def test_raise_via_settings_center_is_immediate_and_old_entrance_agrees(client, two_su):
    sa1, _ = two_su
    r = client.post("/api/settings-center/groups/overhead", headers=sa1, json={"values": {"default_pct": 27.5}, "reason": "測試調高"})
    assert r.status_code == 200, r.text
    assert PG.default_pct() == 27.5 and _old_get(client, sa1) == 27.5 and _legacy() == 27.5
    assert not (r.json().get("pending") or [])


def test_lower_via_old_entrance_is_pending_not_effective_and_needs_the_second_superadmin(client, two_su):
    sa1, sa2 = two_su
    r = client.put("/api/overhead/settings", json={"defaultPct": 20, "reason": "降低管銷預設"}, headers=sa1)
    assert r.status_code == 200, r.text
    pend = r.json()["pending"]
    assert pend and [p["approvalsRequired"] for p in pend] == [1], "調低是放寬：要第二位最高管理者核准"
    assert r.json()["defaultPct"] == 25 and PG.default_pct() == 25 and _old_get(client, sa1) == 25
    assert _legacy() is None, "待生效期間舊鍵不動（舊程式回滾時看到的仍是現值）"
    pid = pend[0]["id"]
    own = client.post("/api/settings-center/pending/%d/approve" % pid, headers=sa1, json={"reason": "自己核准自己"})
    assert own.status_code >= 400 or own.json().get("ok") is False, "申請人不能核准自己的"
    assert PG.default_pct() == 25
    ok = client.post("/api/settings-center/pending/%d/approve" % pid, headers=sa2, json={"reason": "同意降低"})
    assert ok.status_code == 200, ok.text
    assert SR.get("overhead", "default_pct") == 25, "核准了但確認期間還沒到 ⇒ 仍是舊值"
    assert SR.get("overhead", "default_pct", now=_future()) == 20, "確認期間之後生效"
    SR.materialize_due(now=_future())
    assert _legacy() == 20, "到時生效時舊鍵同步（雙寫等值）"


def test_lower_via_settings_center_cannot_bypass_the_second_approver(client, two_su):
    sa1, _ = two_su
    r = client.post("/api/settings-center/groups/overhead", headers=sa1, json={"values": {"default_pct": 15}, "reason": "測試調低"})
    assert r.status_code == 200, r.text
    assert r.json()["pending"] and r.json()["pending"][0]["approvalsRequired"] == 1
    assert PG.default_pct() == 25 and _old_get(client, sa1) == 25 and _legacy() is None


def test_value_stored_before_the_upgrade_is_kept_not_reset_to_25(client, two_su):
    sa1, _ = two_su
    c = db.get_db()
    try:
        c.execute("INSERT INTO system_settings(key, value_json, updated_at) VALUES('overhead_default_pct','20','x') "
                  "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json")
        c.commit()
    finally:
        c.close()
    SR.invalidate("overhead")
    assert PG.default_pct() == 20 and _old_get(client, sa1) == 20 and _center_value(client, sa1) == 20


def test_bad_stored_value_falls_back_to_25_and_bad_input_is_rejected(client, two_su):
    sa1, _ = two_su
    c = db.get_db()
    try:
        c.execute("INSERT INTO system_settings(key, value_json, updated_at) VALUES('overhead_default_pct','\"x\"','x') "
                  "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json")
        c.commit()
    finally:
        c.close()
    SR.invalidate("overhead")
    assert PG.default_pct() == 25
    assert client.put("/api/overhead/settings", json={"defaultPct": 20.55}, headers=sa1).status_code == 422
    assert client.put("/api/overhead/settings", json={"defaultPct": 120}, headers=sa1).status_code == 422
    r = client.post("/api/settings-center/groups/overhead", headers=sa1, json={"values": {"default_pct": 12.34}, "reason": "太多小數"})
    assert r.status_code == 400, r.text


def test_non_superadmin_is_refused_on_the_old_entrance(client, make_user, two_su):
    ad = _login(client, make_user, "ohp_admin", role="admin")
    assert client.put("/api/overhead/settings", json={"defaultPct": 30}, headers=ad).status_code == 403
    assert PG.default_pct() == 25
