# -*- coding: utf-8 -*-
"""展示帳號 `demo`（role=superadmin、active=1）不算「另一位最高管理者」（2026-11-13，hichan-12 審查 INFO ③、PM 派工）。

事實：放寬類設定變更「有其他在職最高管理者 ⇒ 要其中一位核准；只有申請人一位 ⇒ 原因＋確認期間＋警告」。
全新安裝的展示帳號是 active=1 的 superadmin，被算成第二位 ⇒ 只有一位真人最高管理者的公司，放寬變更永遠等一個不會來的核准（卡死）。
修法：`config_ledger.real_superadmins()`（不含 `demo`）取代各處「有沒有另一位最高管理者」的計數：設定中心（plan／publish）、
角色對應與權限矩陣的雙人核准、無簽核層時的自簽逃生條款、設定頁「建議再設一位」。通知／簽核人名單（誰能簽）不動：展示庫裡 demo 本來就是唯一的簽核人。
"""
import pytest

GROUP, FIELD = "retention", "local_db_keep_days"       # 30 → 更小＝放寬（loosen=down）


def _set_superadmins(active_names):
    """測試庫裡的最高管理者只留 active_names 那幾位在職（其餘 superadmin 一律停用）；demo 若不在就建一列。"""
    import db
    c = db.get_db()
    try:
        if "demo" in active_names and not c.execute("SELECT 1 FROM users WHERE username='demo'").fetchone():
            c.execute("INSERT INTO users (username, password_hash, display_name, role, modules, active, created_at, must_change_password) "
                      "VALUES ('demo', 'x', '展示帳號', 'superadmin', '[]', 1, '2026-01-01T00:00:00', 1)")
        c.execute("UPDATE users SET active=0 WHERE role='superadmin'")
        for n in active_names:
            c.execute("UPDATE users SET active=1, role='superadmin' WHERE username=?", (n,))
        c.commit()
    finally:
        c.close()


@pytest.fixture(autouse=True)
def _db_ready(client):
    """`client` 會建好隔離的測試庫（make_user 直接寫 users 表，需要庫已存在）。"""
    return client


@pytest.fixture()
def two_real(make_user):
    make_user(username="real_a", role="superadmin")
    make_user(username="real_b", role="superadmin")


def _loosen(user):
    import db
    from helpers import settings_registry as SR
    c = db.get_db()
    try:
        res = SR.publish(GROUP, {FIELD: 20}, user=user, reason="test", conn=c)
        SR.invalidate()
        plan = SR.plan(GROUP, {FIELD: 10}, user=user, conn=c)
    finally:
        c.close()
    return res, plan


def test_helper_excludes_demo_inactive_and_the_excluded_user(make_user):
    make_user(username="real_a", role="superadmin")
    make_user(username="real_b", role="superadmin")
    _set_superadmins(["real_a", "real_b", "demo"])
    import db
    from helpers import config_ledger as L
    c = db.get_db()
    try:
        assert L.real_superadmins(c) == ["real_a", "real_b"]
        assert L.real_superadmins(c, exclude="real_a") == ["real_b"]
        assert L.real_superadmins(c, exclude="demo") == ["real_a", "real_b"]
    finally:
        c.close()


def test_one_real_superadmin_plus_active_demo_falls_back_to_confirm_period_not_stuck(make_user):
    """核心：一位真人＋demo ⇒ 放寬變更不要求第二位核准（approvalsRequired 0），而是原因＋確認期間＋警告。"""
    make_user(username="real_a", role="superadmin")
    _set_superadmins(["real_a", "demo"])
    res, plan = _loosen("real_a")
    assert res["pending"] and res["pending"][0]["approvalsRequired"] == 0, res["pending"]
    assert plan["otherSuperadmins"] == 0


def test_two_real_superadmins_still_require_the_second_approval(two_real):
    """正對照：有第二位真人 ⇒ 仍然要核准（少了這題，『一律不要求』會讓上一題綠）。"""
    _set_superadmins(["real_a", "real_b", "demo"])
    res, plan = _loosen("real_a")
    assert res["pending"] and res["pending"][0]["approvalsRequired"] == 1, res["pending"]
    assert plan["otherSuperadmins"] == 1


def test_demo_only_as_the_other_superadmin_does_not_count_in_plan_either(make_user):
    make_user(username="real_a", role="superadmin")
    _set_superadmins(["real_a", "demo"])
    _res, plan = _loosen("real_a")
    assert plan["otherSuperadmins"] == 0 and not any(f.get("kind") == "pending_approval" for f in plan["fields"])


def test_self_approval_escape_clause_ignores_demo(make_user):
    """無簽核層時申請人自簽：唯一的真人最高管理者（旁邊只有 demo）要能放行，否則永久卡死；有第二位真人仍要擋。"""
    import db
    from helpers import tiered_approval as T
    make_user(username="real_a", role="superadmin")
    make_user(username="real_b", role="superadmin")
    c = db.get_db()
    try:
        _set_superadmins(["real_a", "demo"])
        assert T.check_no_tier_self_approval(c, {"requestedBy": "real_a"}, {"username": "real_a", "role": "superadmin"}) is None
        _set_superadmins(["real_a", "real_b", "demo"])
        assert T.check_no_tier_self_approval(c, {"requestedBy": "real_a"}, {"username": "real_a", "role": "superadmin"})
    finally:
        c.close()


def test_company_setup_status_counts_only_real_superadmins(client, make_user):
    """設定頁「只有一位最高管理者，建議再設一位」：demo 不算，否則真人只有一位時提示不出現。"""
    make_user(username="real_a", role="superadmin")
    _set_superadmins(["real_a", "demo"])
    r = client.post("/api/auth/login", json={"username": "real_a", "password": "Test-Pass-123"})
    assert r.status_code == 200, r.text
    h = {"Authorization": "Bearer " + r.json()["token"]}
    st = client.get("/api/settings/company-setup/status", headers=h)
    assert st.status_code == 200, st.text
    assert st.json().get("superadminCount") == 1, st.json()


def test_no_remaining_second_approver_count_includes_demo():
    """守門：『有沒有另一位最高管理者』的計數不准再各寫一份含 demo 的 SQL——走 config_ledger.real_superadmins。
    （掃設定中心、權限矩陣、帳務角色對應、公司設定狀態這幾個決定「要不要第二位」的檔；tiered_approval 的自簽逃生條款由上一題直接驗，它另一處是簽核人名單，不在此列。）"""
    import re
    from core import source_tree
    root = source_tree.BACKEND
    needle = re.compile(r"role\s*=\s*'superadmin'[^\n]*username\s*(?:<>|!=)\s*\?|username\s*(?:<>|!=)\s*\?[^\n]*role\s*=\s*'superadmin'")
    files = ["helpers/settings_registry.py", "modules/permmatrix/service.py",
             "modules/accounting/api/ledger_reports.py", "routers/system.py"]
    bad = []
    for rel in files:
        text = (root / rel).read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if needle.search(line):
                bad.append("%s:%d %s" % (rel, i, line.strip()[:110]))
    assert not bad, "這些地方自己數『另一位最高管理者』且沒排除展示帳號（改用 config_ledger.real_superadmins）：" + chr(10) + chr(10).join(bad)


def _review_state(submitter, mode="on"):
    import db
    from helpers import custom_def_review as R
    c = db.get_db()
    try:
        R.set_review_settings(c, mode=mode)
        c.commit()
        return R.review_state(c, submitter)
    finally:
        c.close()


def test_custom_module_review_one_real_superadmin_plus_demo_publishes_directly(make_user):
    """審核模式「開」、沒指定審核人：預設審核人＝申請人以外的最高管理者。只有一位真人（旁邊有 demo）⇒ 不啟用審核（直接發布），
    不是等一個不會來的 demo（hichan-12 M1）。"""
    make_user(username="real_a", role="superadmin")
    _set_superadmins(["real_a", "demo"])
    st = _review_state("real_a")
    assert st["active"] is False and st["reviewers"] == [] and "沒有申請人以外的審核人" in st["reason"], st


def test_custom_module_review_two_real_superadmins_review_by_the_other_real_one(two_real):
    _set_superadmins(["real_a", "real_b", "demo"])
    st = _review_state("real_a")
    assert st["active"] is True and [r["username"] for r in st["reviewers"]] == ["real_b"], st
