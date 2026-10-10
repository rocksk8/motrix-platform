# -*- coding: utf-8 -*-
"""第 54 班：勞報單簽核卡死（使用者回報「只有最高管理者能送簽核，但送出後不能自己簽第一層，系統卡死」）。

成因：Q-S6（第 47 班）送審人有簽核層時不得自核；若當層排序最前的未簽核人**就是送審人**，其他最高管理者不在層內（或要等送審人先簽）⇒ 沒有人簽得了。
修法（比照獎金分潤第 52 班的 `_sole_approver_bypass`，但條件更貼近成因）：另一位最高管理者可帶**必填原因**代核——
強制稽核 `payslip.approve_bypass`（與核准同一個交易）、簽核紀錄留『誰代誰為什麼』、通知其他最高管理者；送審人永遠不可自核。
"""
import json

from modules.payroll.tests.test_payslip_approval_t46 import _archive_tmp, _clear_flow, _flow, _q, _status, _su  # noqa: F401  (_archive_tmp 是 autouse fixture)
from modules.payroll.tests.test_payslip_edit_guard_2026_08_28 import _insert_payslip

_MAKE_USER_DEFAULT_ROLE = "superadmin"


def _appr(no):
    return json.loads(_q("SELECT approval_json FROM payslips WHERE slip_no=?", (no,))[0]["approval_json"])


def _approve(client, no, h, **body):
    return client.post("/api/payslips/%s/approve" % no, json=body, headers=h)


def _x(sql, args=()):
    from modules.payroll.tests.test_payslip_approval_t46 import _x as _xx
    _xx(sql, args)


def _x_deactivate(username):
    from modules.payroll.tests.test_payslip_approval_t46 import _x
    _x("UPDATE users SET active=0 WHERE username=?", (username,))


def _submit(client, no, h):
    r = client.post("/api/payslips/%s/submit" % no, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "待審核", r.text


def test_the_reported_deadlock_is_reproduced_without_a_reason(client, make_user):
    ua, ha = _su(client, make_user, "ps54_a")
    ub, hb = _su(client, make_user, "ps54_b")
    _flow([ua])                                                                       # 第一層就是送審人自己
    _insert_payslip("PS-203102-001")
    _submit(client, "PS-203102-001", ha)
    r = _approve(client, "PS-203102-001", ha)
    assert r.status_code == 403 and "不得自行審核" in r.text                           # 使用者看到的：自己簽不了
    r = _approve(client, "PS-203102-001", hb)                                         # 另一位最高管理者：不填原因 ⇒ 仍擋，但訊息說明怎麼做
    assert r.status_code == 403 and "請填寫原因" in r.text and ua in r.text
    assert _status("PS-203102-001") == "待審核"


def test_other_superadmin_can_bypass_with_reason_audited_and_notified(client, make_user):
    ua, ha = _su(client, make_user, "ps54_a")
    ub, hb = _su(client, make_user, "ps54_b")
    uc, hc = _su(client, make_user, "ps54_c")
    _flow([ua])
    _insert_payslip("PS-203102-002")
    _submit(client, "PS-203102-002", ha)
    r = _approve(client, "PS-203102-002", hb, reason="  出差中，已電話確認  ")
    assert r.status_code == 200 and r.json()["status"] == "已核准", r.text
    appr = _appr("PS-203102-002")
    assert appr["bypass"]["by"] == ub and appr["bypass"]["forApprover"] == ua and appr["bypass"]["reason"] == "出差中，已電話確認"
    assert appr["tiers"][0]["approvers"][0]["bypass"]["by"] == ub
    last = appr["history"][-1]
    assert last["action"] == "approve_bypass" and ua in last["comment"] and "出差中" in last["comment"]
    rows = _q("SELECT * FROM audit_log WHERE action='payslip.approve_bypass'")
    assert len(rows) == 1 and rows[0]["username"] == ub and rows[0]["target_id"] == "PS-203102-002"
    assert rows[0]["ref_no"] == "PS-203102-002"                                       # 單號歷史搜尋靠 ref_no（與 `_audit` 同一個推導函式）
    d = json.loads(rows[0]["detail"])
    assert d["forApprover"] == ua and d["reason"] == "出差中，已電話確認" and d["requestedBy"] == ua
    got = sorted(r["username"] for r in _q("SELECT username FROM notifications WHERE type='payslip_approver_bypass' AND ref_id=?", ("PS-203102-002",)))
    assert ua in got and uc in got and ub not in got                                  # 其他最高管理者（含被代的人）都知會，操作者本人不用


def test_requester_can_never_self_approve_even_with_a_reason(client, make_user):
    ua, ha = _su(client, make_user, "ps54_a")
    _su(client, make_user, "ps54_b")
    _flow([ua])
    _insert_payslip("PS-203102-003")
    _submit(client, "PS-203102-003", ha)
    r = _approve(client, "PS-203102-003", ha, reason="我自己核")
    assert r.status_code == 403
    assert _status("PS-203102-003") == "待審核" and not _q("SELECT 1 FROM audit_log WHERE action='payslip.approve_bypass'")


def test_two_person_tier_chain_member_cannot_bypass_only_an_outsider_can(client, make_user):
    ua, ha = _su(client, make_user, "ps54_a")
    ub, hb = _su(client, make_user, "ps54_b")
    ux, hx = _su(client, make_user, "ps54_x")
    _flow([ua, ub])                                                                   # 同層兩人、送審人排第一（B 要等 A 先簽）
    _insert_payslip("PS-203102-004")
    _submit(client, "PS-203102-004", ha)
    r = _approve(client, "PS-203102-004", hb, reason="A 無法簽核")                       # 1d 稽核：B 是鏈上的人 ⇒ 不能代 A 簽一格再簽自己那一格
    assert r.status_code == 403 and _status("PS-203102-004") == "待審核" and not _q("SELECT 1 FROM audit_log WHERE action='payslip.approve_bypass'")
    assert "請填寫原因" in _approve(client, "PS-203102-004", hx).text                    # 鏈外的 X：要原因
    r = _approve(client, "PS-203102-004", hx, reason="A 是送審人")
    assert r.status_code == 200 and r.json()["status"] == "待審核"                    # X 代 A 簽了 A 的格；B 自己那格還沒簽
    r = _approve(client, "PS-203102-004", hb)                                         # B 照常簽自己的格
    assert r.status_code == 200 and r.json()["status"] == "已核准"
    rows = _q("SELECT username FROM audit_log WHERE action='payslip.approve_bypass'")
    assert [x["username"] for x in rows] == [ux]


def test_two_tiers_chain_member_cannot_bypass_first_tier_outsider_can(client, make_user):
    ua, ha = _su(client, make_user, "ps54_a")
    ub, hb = _su(client, make_user, "ps54_b")
    ux, hx = _su(client, make_user, "ps54_x")
    _flow([ua], [ub])
    _insert_payslip("PS-203102-005")
    _submit(client, "PS-203102-005", ha)
    assert _approve(client, "PS-203102-005", hb, reason="代核第一層").status_code == 403    # B 是第二層簽核人：不能再代簽第一層
    assert _approve(client, "PS-203102-005", hx, reason="代核第一層").json()["status"] == "待審核"
    assert _approve(client, "PS-203102-005", hb).json()["status"] == "已核准"          # 第二層 B 本來就是簽核人，不需要原因


def test_active_delegate_of_a_chain_member_cannot_bypass(client, make_user):
    ua, ha = _su(client, make_user, "ps54_a")
    ub, hb = _su(client, make_user, "ps54_b")
    ud, hd = _su(client, make_user, "ps54_d")
    _flow([ua], [ub])
    _x("INSERT INTO approval_delegates (delegator_username, delegate_username, start_date, end_date, active, created_by, created_at, updated_at)"
       " VALUES (?,?,?,?,1,?,?,?)", (ub, ud, "2020-01-01", "2099-12-31", ub, "2026-01-01T00:00:00", "2026-01-01T00:00:00"))
    _insert_payslip("PS-203102-011")
    _submit(client, "PS-203102-011", ha)
    r = _approve(client, "PS-203102-011", hd, reason="我是 B 的代理人，想代 A 簽")      # D 是鏈上 B 的有效代理人 ⇒ 等同鏈上的人
    assert r.status_code == 403 and _status("PS-203102-011") == "待審核"


def test_no_bypass_when_the_blocked_approver_is_not_the_requester(client, make_user):
    ua, ha = _su(client, make_user, "ps54_a")
    ub, hb = _su(client, make_user, "ps54_b")
    uc, _ = _su(client, make_user, "ps54_c")
    ud, _ = _su(client, make_user, "ps54_d")
    _flow([uc], [ud])                                                                 # 送審人 A 不在鏈上；第一層是 C（正常、沒卡）
    _insert_payslip("PS-203102-006")
    _submit(client, "PS-203102-006", ha)
    r = _approve(client, "PS-203102-006", hb, reason="我想代 C 簽")
    assert r.status_code == 403 and "此層需由以下人員簽核" in r.text                    # 兩位以上簽核人、送審人不是卡點 ⇒ 不給繞過
    assert _status("PS-203102-006") == "待審核" and not _q("SELECT 1 FROM audit_log WHERE action='payslip.approve_bypass'")


def test_active_sole_approver_cannot_be_overridden_but_a_deactivated_one_can(client, make_user):
    ua, ha = _su(client, make_user, "ps54_a")
    ub, hb = _su(client, make_user, "ps54_b")
    uc, hc = _su(client, make_user, "ps54_c")
    _flow([uc])                                                                       # 整條鏈只有 C 一位
    _insert_payslip("PS-203102-007")
    _submit(client, "PS-203102-007", ha)
    assert _approve(client, "PS-203102-007", hb).status_code == 403
    r = _approve(client, "PS-203102-007", hb, reason="C 休假")                           # C 在職：他自己能簽（缺席走轉簽），不給覆寫（有錢有扣繳）
    assert r.status_code == 403 and _status("PS-203102-007") == "待審核" and not _q("SELECT 1 FROM audit_log WHERE action='payslip.approve_bypass'")
    _x_deactivate(uc)                                                                 # C 離職／帳號停用 ⇒ 單據真的卡死 ⇒ 可代核
    r = _approve(client, "PS-203102-007", hb, reason="C 離職交接中")
    assert r.status_code == 200 and r.json()["status"] == "已核准" and _appr("PS-203102-007")["bypass"]["forApprover"] == uc


def test_same_person_cannot_provide_two_signatures_via_bypass(client, make_user):
    ua, ha = _su(client, make_user, "ps54_a")
    us, hs = _su(client, make_user, "ps54_s")
    _flow([ua], [us])                                                                 # 第二層是送審人 S 本人；A 簽完第一層後第二層卡在 S 身上
    _insert_payslip("PS-203102-010")
    _submit(client, "PS-203102-010", hs)
    assert _approve(client, "PS-203102-010", ha).json()["status"] == "待審核"          # A 簽第一層
    r = _approve(client, "PS-203102-010", ha, reason="我再代 S 簽第二層")               # A 已經簽過一格 ⇒ 不能再代核第二格
    assert r.status_code == 403 and _status("PS-203102-010") == "待審核"
    ub, hb = _su(client, make_user, "ps54_b2")                                         # 另一位沒簽過的最高管理者可以
    r = _approve(client, "PS-203102-010", hb, reason="S 是送審人不能簽")
    assert r.status_code == 200 and r.json()["status"] == "已核准"
    assert not _q("SELECT 1 FROM audit_log WHERE action='payslip.approve_bypass' AND username=?", (ua,))


def test_non_superadmin_cannot_bypass(client, make_user):
    ua, ha = _su(client, make_user, "ps54_a")
    _flow([ua])
    u, p = make_user(username="ps54_fin", role="finance")
    from modules.payroll.tests.test_payslip_edit_guard_2026_08_28 import _auth, _login
    hf = _auth(_login(client, u, p))
    _insert_payslip("PS-203102-008")
    _submit(client, "PS-203102-008", ha)
    assert _approve(client, "PS-203102-008", hf, reason="x").status_code == 403
    assert _status("PS-203102-008") == "待審核"


def test_normal_approval_is_unchanged_and_not_marked_as_bypass(client, make_user):
    ua, ha = _su(client, make_user, "ps54_a")
    ub, hb = _su(client, make_user, "ps54_b")
    _flow([ub])
    _insert_payslip("PS-203102-009")
    _submit(client, "PS-203102-009", ha)
    assert _approve(client, "PS-203102-009", hb, reason="多帶原因也不算代核").json()["status"] == "已核准"
    appr = _appr("PS-203102-009")
    assert "bypass" not in appr and appr["history"][-1]["action"] == "approve"
    assert not _q("SELECT 1 FROM audit_log WHERE action='payslip.approve_bypass'")
    _clear_flow()
