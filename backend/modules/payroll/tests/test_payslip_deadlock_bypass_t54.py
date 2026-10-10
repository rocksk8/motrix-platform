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


def test_two_person_tier_where_requester_is_first_pending_is_also_unstuck(client, make_user):
    ua, ha = _su(client, make_user, "ps54_a")
    ub, hb = _su(client, make_user, "ps54_b")
    _flow([ua, ub])                                                                   # 同層兩人、送審人排第一（B 要等 A 先簽）
    _insert_payslip("PS-203102-004")
    _submit(client, "PS-203102-004", ha)
    assert "請填寫原因" in _approve(client, "PS-203102-004", hb).text
    r = _approve(client, "PS-203102-004", hb, reason="A 無法簽核")
    assert r.status_code == 200 and r.json()["status"] == "待審核"                    # 代 A 簽了 A 的格；B 自己那格還沒簽
    r = _approve(client, "PS-203102-004", hb)
    assert r.status_code == 200 and r.json()["status"] == "已核准"


def test_two_tiers_first_is_requester_second_is_other(client, make_user):
    ua, ha = _su(client, make_user, "ps54_a")
    ub, hb = _su(client, make_user, "ps54_b")
    _flow([ua], [ub])
    _insert_payslip("PS-203102-005")
    _submit(client, "PS-203102-005", ha)
    assert _approve(client, "PS-203102-005", hb, reason="代核第一層").json()["status"] == "待審核"
    assert _approve(client, "PS-203102-005", hb).json()["status"] == "已核准"          # 第二層 B 本來就是簽核人，不需要原因


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


def test_sole_approver_chain_absent_approver_can_be_bypassed_like_bonus(client, make_user):
    ua, ha = _su(client, make_user, "ps54_a")
    ub, hb = _su(client, make_user, "ps54_b")
    uc, _ = _su(client, make_user, "ps54_c")
    _flow([uc])                                                                       # 整條鏈只有 C 一位（例如 C 休假）
    _insert_payslip("PS-203102-007")
    _submit(client, "PS-203102-007", ha)
    assert _approve(client, "PS-203102-007", hb).status_code == 403
    r = _approve(client, "PS-203102-007", hb, reason="C 離職交接中")
    assert r.status_code == 200 and r.json()["status"] == "已核准" and _appr("PS-203102-007")["bypass"]["forApprover"] == uc


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
