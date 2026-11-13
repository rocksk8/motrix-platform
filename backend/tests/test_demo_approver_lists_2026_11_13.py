# -*- coding: utf-8 -*-
"""展示帳號 `demo`（role=superadmin、active=1）不出現在「等誰簽核」名單、不收簽核／知會通知，也不能決定審核（2026-11-13，PM 裁示 A＋B）。

事實：`demo` 的請求靠 Bearer token 的 `DEMO_` 前綴被導到隔離的展示庫（main.py 中介層 `set_demo_mode(token.startswith(DEMO_TOKEN_PREFIX))`），
真實庫裡它只是一列 users（role=superadmin）——但這一列會被各處「列出所有最高管理者」的查詢撈到：
  A 把它算成另一位簽核人（custom_def_review 的簽核層、backup_monitor 的雙人核准）；B 把它列進「等誰簽核」、寄未讀通知給它。
修法：全部改走 `config_ledger.real_superadmins()`（不含 demo）。本檔鎖：各名單不含 demo、真人仍在；demo 不能決定審核；
以及守門——真實庫裡就算有 `DEMO_` 開頭的 session，也永遠不會用它登入真實庫。
"""
import json

import pytest


@pytest.fixture(autouse=True)
def _db_ready(client):
    return client


def _demo():
    import db
    c = db.get_db()
    try:
        if not c.execute("SELECT 1 FROM users WHERE username='demo'").fetchone():
            c.execute("INSERT INTO users (username, password_hash, display_name, role, modules, active, created_at, must_change_password) "
                      "VALUES ('demo', 'x', '展示帳號', 'superadmin', '[]', 1, '2026-01-01T00:00:00', 1)")
        c.commit()
    finally:
        c.close()


def _only_real(make_user, *names):
    """真實庫只留這幾位真人最高管理者在職（其餘停用），再加一個在職的 demo。"""
    import db
    for n in names:
        make_user(username=n, role="superadmin")
    _demo()
    c = db.get_db()
    try:
        c.execute("UPDATE users SET active=0 WHERE role='superadmin' AND username<>'demo' AND username NOT IN (%s)" % ",".join("?" * len(names)), names)
        c.commit()
    finally:
        c.close()


# ── 守門：DEMO_ token 到不了真實庫 ──────────────────────────────────────────────────
def test_a_demo_prefixed_session_in_the_real_db_never_authenticates(client, make_user):
    import db
    u, p = make_user(username="dm_real", role="superadmin")
    token = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer " + token}).status_code == 200
    c = db.get_db()
    try:
        c.execute("UPDATE sessions SET token=? WHERE token=?", ("DEMO_" + token, token))
        c.commit()
    finally:
        c.close()
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer DEMO_" + token})
    assert r.status_code == 401, "DEMO_ 前綴的 token 被導到展示庫，真實庫裡的 session 不能拿它通過驗證：%s" % r.text
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer " + token}).status_code == 401      # 原 token 那列已被改名


def test_demo_mode_routes_get_db_to_the_isolated_file():
    import db
    db.set_demo_mode(True)
    try:
        assert db.is_demo_mode() is True
        conn = db.get_db()
        try:
            path = conn.execute("PRAGMA database_list").fetchone()[2]
        finally:
            conn.close()
        assert path.replace("\\", "/").lower() == str(db.DEMO_DB_PATH).replace("\\", "/").lower() != str(db.DB_PATH).replace("\\", "/").lower()
    finally:
        db.set_demo_mode(False)


# ── B：名單與通知不含 demo ───────────────────────────────────────────────────────────
def _names_from(fn_path, attr):
    import importlib
    return getattr(importlib.import_module(fn_path), attr)


@pytest.mark.parametrize("module,attr", [
    ("modules.accounting.api.ledger_requests", "_supers"),
    ("modules.accounting.api.vouchers", "_superadmin_usernames"),
    ("modules.recyclebin.service", "superadmins"),
    ("modules.case.content_fp", "_superadmins"),
])
def test_superadmin_recipient_lists_exclude_demo(make_user, module, attr):
    import db
    pytest.importorskip(module)
    _only_real(make_user, "dm_a", "dm_b")
    fn = _names_from(module, attr)
    c = db.get_db()
    try:
        got = list(fn(c))
    finally:
        c.close()
    assert sorted(got) == ["dm_a", "dm_b"], got


def test_config_change_notice_skips_demo(make_user):
    import db
    from helpers import config_ledger as L
    _only_real(make_user, "dm_c", "dm_d")
    c = db.get_db()
    try:
        L._notify_others(c, "dm_c", "retention", "k", "none", "settings-center.html", "2026-11-13T00:00:00", "測試通知")
        c.commit()
        who = sorted(r[0] for r in c.execute("SELECT username FROM notifications WHERE type='config_change'").fetchall())
    finally:
        c.close()
    assert who == ["dm_d"], who


def test_org_chain_notice_list_excludes_demo(make_user):
    import db
    from helpers import tiered_approval as T
    _only_real(make_user, "dm_e", "dm_f")
    c = db.get_db()
    try:
        got = T.org_chain_notice_usernames(c, [{"order": 0, "approvers": [{"username": "dm_e"}]}], "dm_e")
    finally:
        c.close()
    assert got == ["dm_f"], got


def test_queue_approver_list_of_custom_def_excludes_demo(make_user):
    import db
    from helpers import custom_def_review as R
    _only_real(make_user, "dm_g", "dm_h")
    c = db.get_db()
    try:
        tiers = R._with_superadmins(c, None, "dm_g")
    finally:
        c.close()
    assert [a["username"] for t in tiers for a in t["approvers"]] == ["dm_h"]
    # 申請人是唯一真人 ⇒ 沒有人可列（不能列一個永遠不會簽的 demo）
    c = db.get_db()
    try:
        c.execute("UPDATE users SET active=0 WHERE username='dm_h'")
        c.commit()
        tiers = R._with_superadmins(c, None, "dm_g")
    finally:
        c.close()
    assert [a["username"] for t in tiers for a in t["approvers"]] == []


def test_demo_cannot_decide_a_custom_def_review(make_user):
    import db
    from helpers import custom_def_review as R
    _only_real(make_user, "dm_i", "dm_j")
    row = {"submitted_by": "dm_i", "decision_json": json.dumps({"approval": {"requestedBy": "dm_i", "tiers": []}})}
    c = db.get_db()
    try:
        ok_demo, status, msg = R._can_decide(c, row, {"username": "demo", "role": "superadmin"})
        ok_real, _s, _m = R._can_decide(c, row, {"username": "dm_j", "role": "superadmin"})
    finally:
        c.close()
    assert ok_demo is False and status == 403 and "展示帳號" in msg
    assert ok_real is True


def test_contact_info_field_warns_that_everyone_can_see_it():
    """公司資料「聯絡方式」欄會顯示給所有使用者（/api/settings/company-profile/public）：欄位旁寫明別填銀行資料（hichan-12 L）。"""
    from core import source_tree
    html = source_tree.page_file("company-profile-settings.html").read_text(encoding="utf-8")
    i = html.index('x-model="cfg.contact_info"')
    assert "此欄會顯示給所有使用者，請勿填銀行資料" in html[i:i + 600]


# ── 傳票最後一層：真人在 ⇒ 不含 demo；庫裡只剩 demo（隔離的展示庫）⇒ demo 當這一層，不是整層消失 ──────────
def _final_tier_usernames():
    import db
    from modules.accounting.api import voucher_common as vc
    c = db.get_db()
    try:
        tiers = vc.with_final_superadmin_tier(c, [])
    finally:
        c.close()
    return [a["username"] for a in tiers[-1]["approvers"]] if tiers else None


def test_final_voucher_tier_lists_only_real_superadmins_when_one_exists(make_user):
    _only_real(make_user, "dm_final_real")
    assert _final_tier_usernames() == ["dm_final_real"]


def test_final_voucher_tier_falls_back_to_demo_when_it_is_the_only_superadmin(make_user):
    import db
    _demo()
    c = db.get_db()
    try:
        c.execute("UPDATE users SET active=0 WHERE role='superadmin' AND username<>'demo'")
        c.commit()
    finally:
        c.close()
    assert _final_tier_usernames() == ["demo"], "展示庫只有 demo：最後一層要在（展示環境看得到真實流程）"
