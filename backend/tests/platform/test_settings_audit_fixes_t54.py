# -*- coding: utf-8 -*-
"""第 54 班 Train A：ab 非作者稽核（e8f34bfa4）4 項必修＋2 項次要的回歸題。每題在修正前為紅、修正後為綠。"""
from datetime import datetime, timedelta

import pytest

from db import get_db
from helpers import config_ledger as L
from helpers import settings_groups  # noqa: F401
from helpers import settings_registry as R


def _later(days=8):
    return (datetime.now() + timedelta(days=days)).isoformat(timespec="seconds")


def _hdr(client, make_user, name="afx_sa"):
    username, password = make_user(username=name, role="superadmin")
    tok = client.post("/api/auth/login", json={"username": username, "password": password}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _ok(c, out):
    """第二位最高管理者核准所有要核准的待生效項（資料庫裡有幾位最高管理者不固定，測試不依賴它）。"""
    for p in out["pending"]:
        if p["approvalsRequired"]:
            assert L.approve(c, p["id"], "afx_b")["ok"]
    c.commit()
    return out


@pytest.fixture()
def grp(client, make_user):
    make_user(username="afx_b", role="superadmin")
    c = get_db()
    R.invalidate()
    R.register_group("zz_afx_t54", "稽核修正測試群組", [
        R.SettingDef("cap", "int", 10, min=1, max=1000, risk="security", loosen="up", question="上限要設多少？", label="上限",
                     help="測試用的上限。", impact="影響之後的操作，調大屬放寬。", risk_text="調大後門檻變低。"),
        R.SettingDef("keep", "int", 0, min=0, max=100, risk="ops", loosen="down", zero_is_max=True, question="要保留幾份？（0＝不清理）", label="保留份數",
                     help="0 代表永久保留。", impact="縮短會提早刪除。"),
    ], help="測試用的設定群組。", risk="security")
    yield c
    R._GROUPS.pop("zz_afx_t54", None)
    R.clear_edition_bounds()
    c.close()
    R.invalidate()


# --- 必修 1：確認期間來自設定（預設 7 天、下限 1 天） --------------------------------

def test_confirm_period_default_is_7_days(grp):
    assert R.get("change_control", "confirm_period_days", conn=grp) == 7
    out = _ok(grp, R.publish("zz_afx_t54", {"cap": 50}, reason="放寬", user="afx_a", conn=grp))
    eff = datetime.fromisoformat(out["pending"][0]["effectiveAt"])
    assert timedelta(days=6, hours=23) < eff - datetime.now() < timedelta(days=7, minutes=5)
    assert R.get("zz_afx_t54", "cap", conn=grp, now=_later(3)) == 10          # 3 天後仍未生效
    assert R.get("zz_afx_t54", "cap", conn=grp, now=_later(8)) == 50          # 沒有第二位最高管理者可核准 ⇒ 等滿確認期間即生效


def test_confirm_period_is_configurable_with_floor_1_day(grp):
    with pytest.raises(R.SettingError):
        R.publish("change_control", {"confirm_period_days": 0}, user="afx_a", conn=grp)
    _ok(grp, R.publish("change_control", {"confirm_period_days": 2}, reason="縮短", user="afx_a", conn=grp))    # 縮短＝放寬 ⇒ 先等目前的 7 天
    assert R.get("change_control", "confirm_period_days", conn=grp) == 7
    assert R.materialize_due(grp, now=_later(8)) == 1
    assert R.get("change_control", "confirm_period_days", conn=grp) == 2
    out = R.publish("zz_afx_t54", {"cap": 50}, reason="放寬", user="afx_a", conn=grp)
    eff = datetime.fromisoformat(out["pending"][0]["effectiveAt"])
    assert timedelta(days=1, hours=23) < eff - datetime.now() < timedelta(days=2, minutes=5)


# --- 必修 2：越小越寬鬆的欄位（保存期限、容量）縮短／放寬要走待生效 ---------------------

def test_retention_shortening_is_pending_lengthening_is_immediate(grp):
    out = R.publish("retention", {"audit_log_keep_days": 400}, reason="縮短", user="afx_a", conn=grp)
    assert out["changed"] is False and out["pending"] and R.get("retention", "audit_log_keep_days", conn=grp) == 1825
    out = R.publish("retention", {"audit_log_keep_days": 3000}, reason="延長", user="afx_a", conn=grp)
    assert out["changed"] is True and R.get("retention", "audit_log_keep_days", conn=grp) == 3000
    assert R.publish("retention", {"local_db_keep_days": 10}, reason="縮短", user="afx_a", conn=grp)["pending"]


def test_zero_means_forever_is_widest(grp):
    assert _ok(grp, R.publish("zz_afx_t54", {"keep": 30}, reason="縮短", user="afx_a", conn=grp))["pending"]       # 0（永久）→ 30 ＝ 縮短 ⇒ 待生效
    R.materialize_due(grp, now=_later(8))
    grp.commit()
    assert R.get("zz_afx_t54", "keep", conn=grp) == 30
    out = R.publish("zz_afx_t54", {"keep": 0}, reason="改永久", user="afx_a", conn=grp)             # 30 → 0（永久）＝ 延長 ⇒ 立即
    assert out["changed"] is True and R.get("zz_afx_t54", "keep", conn=grp) == 0


def test_uploads_larger_is_loosening(grp):
    assert R.publish("uploads", {"max_file_mb": 100}, reason="放寬", user="afx_a", conn=grp)["pending"]
    assert R.publish("uploads", {"max_file_mb": 5}, reason="收緊", user="afx_a", conn=grp)["changed"] is True


def test_every_size_and_retention_field_declares_loosen_direction():
    for gk in ("retention", "uploads"):
        for f in R.groups()[gk]["fields"]:
            assert f["loosen"] in ("up", "down"), "%s.%s 沒有宣告放寬方向" % (gk, f["key"])


def test_legacy_retention_endpoint_goes_through_ledger(client, make_user):
    h = _hdr(client, make_user)
    r = client.patch("/api/settings/backup-retention", json={"audit_log_keep_days": 400}, headers=h)
    assert r.status_code == 200 and r.json()["pending"]
    assert client.get("/api/settings/backup-retention", headers=h).json()["audit_log_keep_days"] == 1825
    r = client.patch("/api/settings/backup-retention", json={"audit_log_keep_days": 3000}, headers=h)
    assert r.status_code == 200 and not r.json()["pending"]
    assert client.get("/api/settings/backup-retention", headers=h).json()["audit_log_keep_days"] == 3000


# --- 必修 3：收緊要取代同欄位較舊的待生效放寬 ---------------------------------------

def test_tightening_supersedes_older_pending_loosening(grp):
    R.publish("zz_afx_t54", {"cap": 20}, reason="放寬", user="afx_a", conn=grp)
    out = R.publish("zz_afx_t54", {"cap": 5}, reason="收緊", user="afx_a", conn=grp)
    assert out["changed"] is True and L.pending(grp, "setting:zz_afx_t54") == []
    assert R.get("zz_afx_t54", "cap", conn=grp, now=_later(30)) == 5          # 修正前：舊的 20 到期後蓋過 5


def test_resubmitting_current_value_cancels_pending(grp):
    R.publish("zz_afx_t54", {"cap": 20}, reason="放寬", user="afx_a", conn=grp)
    out = R.publish("zz_afx_t54", {"cap": 10}, reason="不放寬了", user="afx_a", conn=grp)
    assert out["changed"] is False and out["superseded"] == 1 and L.pending(grp, "setting:zz_afx_t54") == []
    assert R.get("zz_afx_t54", "cap", conn=grp, now=_later(30)) == 10


# --- 必修 4：撤銷／核准同交易寫稽核、先拿寫鎖 ------------------------------------------

def _make_pending(client, h):
    r = client.post("/api/settings-center/groups/retention", json={"values": {"audit_log_keep_days": 500}, "reason": "縮短"}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()["pending"][0]["id"]


def test_cancel_audit_is_in_same_transaction(client, make_user, monkeypatch):
    h = _hdr(client, make_user)
    cid = _make_pending(client, h)

    def boom(*a, **k):
        raise RuntimeError("audit down")
    with monkeypatch.context() as m:
        m.setattr(L, "audit_event", boom)
        with pytest.raises(Exception):
            client.post("/api/settings-center/pending/%d/cancel" % cid, json={"reason": "x"}, headers=h)
    c = get_db()
    try:
        assert L.state_of(c, cid) == "pending"                                  # 稽核寫不進去 ⇒ 撤銷整個回復（修正前：已 commit）
    finally:
        c.close()
    assert client.post("/api/settings-center/pending/%d/cancel" % cid, json={"reason": "x"}, headers=h).status_code == 200
    c = get_db()
    try:
        assert c.execute("SELECT COUNT(*) FROM audit_log WHERE action='settings.retention.pending_cancel'").fetchone()[0] == 1
        assert client.post("/api/settings-center/pending/%d/cancel" % cid, json={}, headers=h).status_code == 409
        assert c.execute("SELECT COUNT(*) FROM audit_log WHERE action='settings.retention.pending_cancel'").fetchone()[0] == 1
    finally:
        c.close()


def test_approve_audit_is_in_same_transaction_and_no_double_vote(client, make_user, monkeypatch):
    ha = _hdr(client, make_user, "afx_a")
    hb = _hdr(client, make_user, "afx_b")
    cid = _make_pending(client, ha)
    c = get_db()
    try:
        assert c.execute("SELECT approvals_required FROM config_changes WHERE id=?", (cid,)).fetchone()[0] == 1
    finally:
        c.close()

    def boom(*a, **k):
        raise RuntimeError("audit down")
    with monkeypatch.context() as m:
        m.setattr(L, "audit_event", boom)
        with pytest.raises(Exception):
            client.post("/api/settings-center/pending/%d/approve" % cid, json={}, headers=hb)
    c = get_db()
    try:
        assert L._approvals(c, [cid])[cid] == []                                # 票也回復
    finally:
        c.close()
    assert client.post("/api/settings-center/pending/%d/approve" % cid, json={}, headers=hb).json()["approvals"] == 1
    assert client.post("/api/settings-center/pending/%d/approve" % cid, json={}, headers=hb).status_code == 409


# --- 次要 ---------------------------------------------------------------------------

def test_pending_list_returns_approvals_and_required(client, make_user):
    ha = _hdr(client, make_user, "afx_a")
    hb = _hdr(client, make_user, "afx_b")
    cid = _make_pending(client, ha)
    row = [p for p in client.get("/api/settings-center/pending", headers=ha).json()["pending"] if p["id"] == cid][0]
    assert row["required"] == 1 and row["approvals"] == []
    client.post("/api/settings-center/pending/%d/approve" % cid, json={}, headers=hb)
    row = [p for p in client.get("/api/settings-center/pending", headers=ha).json()["pending"] if p["id"] == cid][0]
    assert row["approvals"] == ["afx_b"]


def test_materialize_revalidates_against_edition_bounds(grp):
    cid = _ok(grp, R.publish("zz_afx_t54", {"cap": 100}, reason="放寬", user="afx_a", conn=grp))["pending"][0]["id"]
    R.set_edition_bounds("zz_afx_t54", "cap", max=50)                           # 送出之後，版本邊界收緊
    assert R.get("zz_afx_t54", "cap", conn=grp, now=_later(8)) == 10             # 讀取也不套用超出邊界的待生效值
    assert R.materialize_due(grp, now=_later(8)) == 0
    grp.commit()
    assert L.state_of(grp, cid) == "cancelled" and R.get("zz_afx_t54", "cap", conn=grp) == 10


def test_company_profile_page_tells_user_when_change_is_only_pending():
    """舊保存期限頁：縮短只是「已送出、N 天後生效」，不能顯示成「設定已儲存」；文字白話、不顯示代碼。"""
    import os
    html = open(os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend", "pages", "company-profile-settings.html"), encoding="utf-8").read()
    i = html.index("async _saveSetting(")
    body = html[i:i + 2500]
    assert "d.pending" in body and "effectiveAt" in body                      # N 取自實際的待生效項
    assert "天後生效" in body and "需另一位最高管理者確認" in body and "已送出" in body
    for code in ("approvalsRequired}", "pending}", "confirm_period_days"):
        assert "${" + code not in body and code not in body.split("this[prefix + 'Msg'] = `")[1].split("`")[0]
