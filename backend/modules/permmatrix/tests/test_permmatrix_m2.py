# -*- coding: utf-8 -*-
"""權限矩陣框架 P0 里程碑 2：矩陣資料表、提供者、服務層（覆寫／個人覆寫／代理／24 小時待生效／版本回溯）。規格 modules/permmatrix/SPEC.md（PMX1…）。"""
import json
from datetime import datetime, timedelta

import pytest

import db
from core import capabilities as C
from helpers import auth as A
from helpers import perm as P
from modules.permmatrix import service as S

def _d(key, label, legacy, **kw):
    return dict(key=key, label=label, desc=label + "（測試用的一句話說明）", impact="勾選後可以" + label + "（測試用的影響說明）", legacy=legacy, **kw)


DECLS = [
    _d("zz.doc.view", "檢視測試單", {"module": "payslip"}),
    _d("zz.doc.edit", "修改測試單", {"role": ["admin"]}),
    _d("zz.doc.submit", "送出測試單", {"role": ["admin"]}),
    _d("zz.doc.approve", "核准測試單", {"superadmin": True}),
    _d("zz.doc.pay", "付款測試單", {"role": ["admin"]}),
    _d("zz.doc.config", "設定測試單", {"role": ["admin"]}, delegable=False),
]
CAPS, PROBLEMS = C.collect({"zz": {"capabilities": DECLS}}, valid_roles=A.VALID_ROLES)
SU = {"id": 1, "username": "root", "display_name": "root", "role": "superadmin"}


@pytest.fixture(autouse=True)
def _env(client, monkeypatch):
    assert not PROBLEMS, PROBLEMS
    monkeypatch.setattr(C, "all_caps", lambda: dict(CAPS))
    monkeypatch.setattr(C, "get", lambda k: CAPS.get(k))
    monkeypatch.setattr(C, "signature", lambda: "m2-test")
    monkeypatch.setattr(A, "_finance_mode", lambda: "off")
    monkeypatch.setattr(P, "_source", None)
    monkeypatch.setattr(P, "_provider", lambda: S.load_matrix)
    P.invalidate()
    yield
    P.invalidate()


@pytest.fixture
def conn():
    c = db.get_db()
    yield c
    c.close()


def _mk(make_user, name, role, modules=()):
    make_user(username=name, role=role, modules=list(modules))
    c = db.get_db()
    try:
        return dict(c.execute("SELECT id, username, display_name, role, modules FROM users WHERE username=?", (name,)).fetchone())
    finally:
        c.close()


def _rows(conn, sql, args=()):
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def test_empty_tables_give_exactly_the_seed_and_a_failing_provider_falls_back_to_the_seed(conn, monkeypatch):
    seed = P.seed_from_legacy(CAPS)
    m = S.load_matrix(seed)
    assert m.role_grants == seed.role_grants and m.allow == {} and m.deny == {} and m.delegations == {}
    monkeypatch.setattr(P, "_provider", lambda: (lambda s: (_ for _ in ()).throw(RuntimeError("db down"))))
    P.invalidate()
    assert P.matrix().role_grants == seed.role_grants, "讀不到資料表 ⇒ 退回種子（=今天的行為）"


def test_low_risk_grant_is_immediate_versioned_audited_and_reverting_to_seed_deletes_the_row(conn, make_user):
    fin = _mk(make_user, "pm_fin", "finance")
    assert not P.can(fin, "zz.doc.edit")
    r = S.set_role_cap(conn, SU, "finance", "zz.doc.edit", True, "財務協助修改")
    assert r["changed"] and P.can(fin, "zz.doc.edit"), "財務欄勾選 ⇒ 他就能做（不改程式）"
    assert _rows(conn, "SELECT role, cap, granted FROM perm_role_caps") == [{"role": "finance", "cap": "zz.doc.edit", "granted": 1}]
    assert len(_rows(conn, "SELECT id FROM perm_versions")) == 1
    a = _rows(conn, "SELECT detail, username FROM audit_log WHERE action='permmatrix.role_cap.set'")
    assert len(a) == 1 and json.loads(a[0]["detail"]) | {} and json.loads(a[0]["detail"])["new"] is True and a[0]["username"] == "root"
    S.set_role_cap(conn, SU, "finance", "zz.doc.edit", False, "改回")
    assert _rows(conn, "SELECT * FROM perm_role_caps") == [] and not P.can(fin, "zz.doc.edit"), "回到種子預設＝刪覆寫列"
    assert S.set_role_cap(conn, SU, "finance", "zz.doc.edit", False)["changed"] is False


def test_revoking_a_seeded_grant_is_immediate(conn, make_user):
    adm = _mk(make_user, "pm_adm", "admin")
    assert P.can(adm, "zz.doc.edit")
    S.set_role_cap(conn, SU, "admin", "zz.doc.edit", False, "暫時收回")
    assert not P.can(adm, "zz.doc.edit") and _rows(conn, "SELECT granted FROM perm_role_caps") == [{"granted": 0}]
    S.set_role_cap(conn, SU, "admin", "zz.doc.edit", True)
    assert _rows(conn, "SELECT * FROM perm_role_caps") == [] and P.can(adm, "zz.doc.edit"), "恢復種子預設不需 24 小時"


def test_high_risk_grant_needs_a_reason_waits_24h_can_be_cancelled_and_activates_on_read(conn, make_user, monkeypatch):
    fin = _mk(make_user, "pm_fin", "finance")
    boss = _mk(make_user, "pm_boss", "superadmin")
    with pytest.raises(S.PermError) as e:
        S.set_role_cap(conn, SU, "finance", "zz.doc.pay", True, "好")
    assert "原因" in str(e.value)
    r = S.set_role_cap(conn, SU, "finance", "zz.doc.pay", True, "月底結帳需要財務付款")
    assert r["pending"] and not P.can(fin, "zz.doc.pay"), "24 小時內不生效"
    assert _rows(conn, "SELECT * FROM perm_role_caps") == []
    told = {x["username"] for x in _rows(conn, "SELECT username FROM notifications WHERE type='perm_grant_pending'")}
    assert "pm_boss" in told and "root" not in told, "通知其他最高管理者（不含申請人）"
    # 撤銷
    S.cancel_pending(conn, boss, r["id"], "還不需要")
    assert _rows(conn, "SELECT state FROM perm_pending") == [{"state": "cancelled"}]
    monkeypatch.setattr(S, "_now", lambda: datetime.now() + timedelta(hours=30))
    P.invalidate()
    assert not P.can(fin, "zz.doc.pay"), "已撤銷的到期也不生效"
    monkeypatch.setattr(S, "_now", lambda: datetime.now())
    # 再申請、到期自動生效（讀取時判斷）
    r2 = S.set_role_cap(conn, SU, "finance", "zz.doc.pay", True, "月底結帳需要財務付款")
    assert r2["pending"] and not P.can(fin, "zz.doc.pay")
    monkeypatch.setattr(S, "_now", lambda: datetime.now() + timedelta(hours=25))
    P.invalidate()
    assert P.can(fin, "zz.doc.pay"), "到期後第一次讀取就轉為生效，不靠排程"
    assert _rows(conn, "SELECT state, resolved_by FROM perm_pending WHERE id=?", (r2["id"],)) == [{"state": "active", "resolved_by": "system"}]
    assert _rows(conn, "SELECT granted FROM perm_role_caps") == [{"granted": 1}]
    assert _rows(conn, "SELECT 1 FROM audit_log WHERE action='permmatrix.pending.activate'")
    assert S.activate_due(conn, datetime.now() + timedelta(hours=26)) == 0, "冪等"
    with pytest.raises(S.PermError):
        S.cancel_pending(conn, boss, r2["id"], "太晚")


def test_guards_non_delegable_non_superadmin_actor_and_superadmin_target(conn, make_user):
    adm = _mk(make_user, "pm_adm", "admin")
    sup = _mk(make_user, "pm_sup", "superadmin")
    with pytest.raises(S.PermError):
        S.set_role_cap(conn, SU, "finance", "zz.doc.config", True, "試試看呀呀")
    with pytest.raises(S.PermError):
        S.set_user_override(conn, SU, adm["id"], "zz.doc.config", "allow", "試試看呀呀")
    with pytest.raises(S.PermError) as e:
        S.set_role_cap(conn, adm, "finance", "zz.doc.edit", True, "我自己來")
    assert e.value.status == 403
    with pytest.raises(S.PermError):
        S.set_user_override(conn, SU, sup["id"], "zz.doc.edit", "deny", "最高管理者")
    with pytest.raises(S.PermError):
        S.set_role_cap(conn, SU, "superadmin", "zz.doc.edit", False, "不行")
    with pytest.raises(S.PermError):
        S.set_role_cap(conn, SU, "finance", "zz.nope.view", True, "沒有這個")


def test_personal_deny_wins_and_personal_allow_adds_for_low_risk(conn, make_user):
    adm = _mk(make_user, "pm_adm", "admin")
    vwr = _mk(make_user, "pm_vwr", "viewer")
    S.set_user_override(conn, SU, adm["id"], "zz.doc.edit", "deny", "暫停")
    assert not P.can(adm, "zz.doc.edit") and P.explain(adm, "zz.doc.edit")["via"] == "deny"
    S.clear_user_override(conn, SU, adm["id"], "zz.doc.edit", "恢復")
    assert P.can(adm, "zz.doc.edit")
    assert not P.can(vwr, "zz.doc.submit")
    S.set_user_override(conn, SU, vwr["id"], "zz.doc.submit", "allow", "專案需要")
    assert P.can(vwr, "zz.doc.submit") and P.explain(vwr, "zz.doc.submit")["via"] == "allow", "『某個人可以做某件事』只勾他一個"
    r = S.set_user_override(conn, SU, vwr["id"], "zz.doc.pay", "allow", "付款也給他看看")
    assert r["pending"] and not P.can(vwr, "zz.doc.pay"), "高風險個人允許要 24 小時"


def test_restore_version_replays_the_difference_through_the_normal_rules(conn, make_user):
    fin = _mk(make_user, "pm_fin", "finance")
    S.set_role_cap(conn, SU, "finance", "zz.doc.edit", True, "一")
    v1 = _rows(conn, "SELECT id FROM perm_versions ORDER BY id")[-1]["id"]
    S.set_role_cap(conn, SU, "finance", "zz.doc.submit", True, "二")
    S.set_role_cap(conn, SU, "admin", "zz.doc.edit", False, "三")
    assert P.can(fin, "zz.doc.submit")
    res = S.restore_version(conn, SU, v1, "回到第一版")
    assert res["applied"] == 2 and res["pending"] == 0
    assert P.can(fin, "zz.doc.edit") and not P.can(fin, "zz.doc.submit")
    assert _rows(conn, "SELECT role, cap, granted FROM perm_role_caps") == [{"role": "finance", "cap": "zz.doc.edit", "granted": 1}]
    assert len(S.list_versions(conn)) >= 4, "歷史不改，每一步都是新版本"
    with pytest.raises(S.PermError):
        S.restore_version(conn, SU, 99999, "沒有這版")


def test_delegation_low_risk_self_service_then_acting_as_then_revoke(conn, make_user):
    boss = _mk(make_user, "pm_boss", "admin")
    dlg = _mk(make_user, "pm_dlg", "viewer")
    other = _mk(make_user, "pm_other", "viewer")
    assert not P.can(dlg, "zz.doc.edit")
    with pytest.raises(S.PermError) as e:
        S.create_delegation(conn, other, "pm_boss", "pm_dlg", "caps", caps=["zz.doc.edit"], valid_from="2000-01-01", valid_to="2099-12-31", reason="我替他設")
    assert e.value.status == 403, "不是委派人本人、也不是最高管理者"
    r = S.create_delegation(conn, boss, "pm_boss", "pm_dlg", "caps", caps=["zz.doc.edit"], valid_from="2000-01-01", valid_to="2099-12-31", reason="出差")
    assert r["ok"] and P.can(dlg, "zz.doc.edit") and P.acting_as(dlg, "zz.doc.edit") == "pm_boss"
    assert not P.can(dlg, "zz.doc.submit"), "範圍外不給"
    with pytest.raises(S.PermError) as e2:
        S.revoke_delegation(conn, other, r["id"], "亂撤")
    assert e2.value.status == 403
    S.revoke_delegation(conn, boss, r["id"], "回來了")
    assert not P.can(dlg, "zz.doc.edit")
    assert _rows(conn, "SELECT state FROM perm_delegations") == [{"state": "revoked"}]
    with pytest.raises(S.PermError):
        S.revoke_delegation(conn, boss, r["id"], "再撤")


def test_delegation_cannot_escalate_and_risky_scopes_need_superadmin_and_24h(conn, make_user):
    boss = _mk(make_user, "pm_boss", "admin")
    dlg = _mk(make_user, "pm_dlg", "viewer")
    with pytest.raises(S.PermError) as e:
        S.create_delegation(conn, SU, "pm_dlg", "pm_boss", "caps", caps=["zz.doc.edit"], reason="viewer 沒有這個能力")
    assert "升權" in str(e.value)
    with pytest.raises(S.PermError):
        S.create_delegation(conn, SU, "pm_boss", "pm_dlg", "caps", caps=["zz.doc.config"], reason="不可委派的")
    with pytest.raises(S.PermError) as e2:
        S.create_delegation(conn, boss, "pm_boss", "pm_dlg", "caps", caps=["zz.doc.pay"], reason="自己建高風險")
    assert e2.value.status == 403
    r = S.create_delegation(conn, SU, "pm_boss", "pm_dlg", "caps", caps=["zz.doc.pay", "zz.doc.edit"], reason="月底付款由他代理")
    assert r["pending"] and not P.can(dlg, "zz.doc.pay") and not P.can(dlg, "zz.doc.edit"), "含高風險 ⇒ 整筆 24 小時後才生效"
    assert _rows(conn, "SELECT * FROM perm_delegations") == []
    S.cancel_pending(conn, {"id": 9, "username": "pm_other_admin", "role": "superadmin"}, r["id"], "不需要了")
    assert _rows(conn, "SELECT state FROM perm_pending") == [{"state": "cancelled"}]


def test_pending_delegation_activates_and_is_superseded_if_the_delegator_lost_the_capability(conn, make_user, monkeypatch):
    boss = _mk(make_user, "pm_boss", "admin")
    dlg = _mk(make_user, "pm_dlg", "viewer")
    r1 = S.create_delegation(conn, SU, "pm_boss", "pm_dlg", "caps", caps=["zz.doc.pay"], reason="月底付款由他代理")
    S.set_role_cap(conn, SU, "admin", "zz.doc.pay", False, "收回")                     # 委派人在等待期間失去這項能力
    monkeypatch.setattr(S, "_now", lambda: datetime.now() + timedelta(hours=25))
    P.invalidate()
    assert not P.can(dlg, "zz.doc.pay")
    assert _rows(conn, "SELECT state FROM perm_pending WHERE id=?", (r1["id"],)) == [{"state": "superseded"}]
    monkeypatch.setattr(S, "_now", lambda: datetime.now())
    S.set_role_cap(conn, SU, "admin", "zz.doc.pay", True, "")
    r2 = S.create_delegation(conn, SU, "pm_boss", "pm_dlg", "caps", caps=["zz.doc.pay"], reason="月底付款由他代理")
    monkeypatch.setattr(S, "_now", lambda: datetime.now() + timedelta(hours=25))
    P.invalidate()
    assert P.can(dlg, "zz.doc.pay") and P.acting_as(dlg, "zz.doc.pay") == "pm_boss"
    assert _rows(conn, "SELECT state FROM perm_pending WHERE id=?", (r2["id"],)) == [{"state": "active"}]
    assert len(_rows(conn, "SELECT * FROM perm_delegations WHERE state='active'")) == 1


def test_doc_type_scope_and_policy_option_and_date_validation(conn, make_user, monkeypatch):
    boss = _mk(make_user, "pm_boss", "admin")
    dlg = _mk(make_user, "pm_dlg", "viewer")
    with pytest.raises(S.PermError):
        S.create_delegation(conn, SU, "pm_boss", "pm_dlg", "doc_types", doc_types=["zz.nothing"], reason="沒有這個類型")
    with pytest.raises(S.PermError):
        S.create_delegation(conn, SU, "pm_boss", "pm_dlg", "caps", caps=["zz.doc.edit"], valid_from="2031-02-01", valid_to="2031-01-01", reason="日期顛倒")
    with pytest.raises(S.PermError):
        S.create_delegation(conn, SU, "pm_boss", "pm_dlg", "caps", caps=["zz.doc.edit"], valid_from="明天", reason="日期格式")
    monkeypatch.setattr(S, "delegation_policy", lambda: {**S.POLICY_DEFAULT, "selfDelegateNonRisky": False})
    with pytest.raises(S.PermError) as e:
        S.create_delegation(conn, boss, "pm_boss", "pm_dlg", "caps", caps=["zz.doc.edit"], reason="政策關掉了")
    assert e.value.status == 403, "『本人可替自己建非風險代理』是可調的選項（預設＝今天的行為）"
    assert S.POLICY_DEFAULT == {"selfDelegateNonRisky": True, "delegationAdditive": True, "concurrentRoleExpiry": "optional"}


# ── 白話預覽（影響面板）與一鍵復原 ──────────────────────────────────────────────────────
def test_preview_role_cap_explains_who_is_affected_when_and_whether_it_can_be_undone(conn, make_user):
    _mk(make_user, "pv_fin1", "finance")
    _mk(make_user, "pv_fin2", "finance")
    p = S.preview_role_cap(conn, "finance", "zz.doc.edit", True)
    assert p["sentence"] == "財務可以修改測試單" and p["changed"] and p["users"] >= 2 and "位使用者" in p["usersText"]
    assert p["effective"] == "儲存後立即生效" and not p["pending"] and p["reversible"] and "一鍵復原" in p["reversibleText"]
    assert "不受影響" in p["appliesTo"] and p["risk"] == "" and p["question"] == "財務可以修改測試單嗎？"
    hi = S.preview_role_cap(conn, "finance", "zz.doc.pay", True)
    assert hi["pending"] and "24 小時" in hi["effective"] and "高風險" in hi["risk"]
    same = S.preview_role_cap(conn, "admin", "zz.doc.edit", True)
    assert same["changed"] is False and same["users"] == 0, "已經是這樣 ⇒ 沒有影響"
    for text in (p["sentence"], p["impact"], p["usersText"], p["appliesTo"], hi["risk"], hi["effective"]):
        assert "zz.doc" not in text and "allow" not in text and "deny" not in text, "畫面不露出代碼"


def test_preview_delegation_gives_the_plain_confirmation_sentence(conn, make_user):
    _mk(make_user, "pv_boss", "admin")
    _mk(make_user, "pv_dlg", "viewer")
    p = S.preview_delegation(conn, "pv_boss", "pv_dlg", ["zz.doc.edit"], "2031-11-30")
    assert p["sentence"].startswith("你即將讓") and "代理" in p["sentence"] and "修改測試單" in p["sentence"] and "11/30" in p["sentence"] and "立即生效" in p["sentence"]
    risky = S.preview_delegation(conn, "pv_boss", "pv_dlg", ["zz.doc.pay"], "2031-11-30")
    assert risky["pending"] and "24 小時後生效" in risky["sentence"] and "高風險" in risky["risk"]
    with pytest.raises(S.PermError):
        S.preview_delegation(conn, "pv_boss", "pv_dlg", [], "")


def test_one_click_undo_walks_back_one_step_each_time(conn, make_user):
    fin = _mk(make_user, "pv_fin", "finance")
    with pytest.raises(S.PermError):
        S.undo_last_change(conn, SU)
    S.set_role_cap(conn, SU, "finance", "zz.doc.edit", True, "一")
    S.set_role_cap(conn, SU, "finance", "zz.doc.submit", True, "二")
    assert P.can(fin, "zz.doc.edit") and P.can(fin, "zz.doc.submit")
    S.undo_last_change(conn, SU)
    assert P.can(fin, "zz.doc.edit") and not P.can(fin, "zz.doc.submit"), "復原最後一步"
    S.undo_last_change(conn, SU)
    assert not P.can(fin, "zz.doc.edit"), "再按一次回到更早的狀態"
    with pytest.raises(S.PermError) as e:
        S.undo_last_change(conn, {"username": "x", "role": "admin"})
    assert e.value.status == 403
