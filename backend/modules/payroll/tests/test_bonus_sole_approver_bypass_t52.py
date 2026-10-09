# -*- coding: utf-8 -*-
"""第 52 班（使用者裁示）：獎金分潤整條簽核鏈**只有一位簽核人**時，不在簽核層內的最高管理者可以代核——必須填原因，強制寫稽核（誰、哪張、略過哪位簽核人、原因），並通知其他最高管理者（站內＋信）。

釘住：① 沒填原因 ⇒ 403 且什麼都不寫 ② 填原因 ⇒ 核准、簽核紀錄／編修紀錄／audit_log 都有（含原因）③ 其他最高管理者（含原簽核人）收到站內通知與信，操作者自己不收
④ 送審人不能用這條路自核 ⑤ 鏈上不只一位簽核人 ⇒ 不開放 ⑥ 層內簽核人照常核准（不留代核痕跡）⑦ 稽核寫入失敗 ⇒ 整個核准回滾（強制稽核）。
"""
import json

import pytest

from modules.payroll.tests.test_bonus_case_api_2026_09_24 import (  # noqa: F401
    people, _seed_case, _create, _members_spec, _auth, _login, _set_flow)
from modules.payroll.tests.test_bonus_case_multi_approver_tier_2026_09_25 import _award, _flow


def _q(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


@pytest.fixture
def sa3(client, make_user):
    u = make_user(username="bc_sa3", role="superadmin")
    return _login(client, u[0], u[1])


def _submitted(client, people, no, tiers):
    """bc_sa 建立並送審；tiers＝簽核層設定（每層一串帳號）。"""
    _set_flow(["bc_sa2"])
    _flow(*tiers)
    _seed_case(no, net=100000)
    assert _create(client, people["bc_sa"], no, members=_members_spec()).status_code == 200
    r = client.post("/api/bonus/cases/%s/submit" % no, headers=_auth(people["bc_sa"]))
    assert r.status_code == 200, r.text


def _approve(client, tok, no, **body):
    return client.post("/api/bonus/cases/%s/approve" % no, headers=_auth(tok), json=body)


def test_outside_superadmin_needs_a_reason_and_nothing_is_written_without_it(client, people, sa3):
    _submitted(client, people, "MQ-BY52-001", [["bc_sa2"]])
    r = _approve(client, sa3, "MQ-BY52-001")
    assert r.status_code == 403 and "請填寫原因" in r.text and "bc_sa2" in r.text, r.text
    r = _approve(client, sa3, "MQ-BY52-001", reason="   ")
    assert r.status_code == 403
    a = _award("MQ-BY52-001")
    assert a["status"] == "待審核" and "bypass" not in a["appr"]
    assert _q("SELECT 1 FROM audit_log WHERE action='bonus.case.approve_bypass'") == []


def test_bypass_with_reason_approves_and_leaves_audit_history_and_notifies_the_others(client, people, sa3, monkeypatch):
    sent = []
    import modules.payroll.bonus_notify as bn
    monkeypatch.setattr(bn._en, "send_registered", lambda key, **kw: sent.append((key, kw)) or True)
    _submitted(client, people, "MQ-BY52-002", [["bc_sa2"]])
    r = _approve(client, sa3, "MQ-BY52-002", reason="簽核人休假、客戶今天要發放")
    assert r.status_code == 200 and r.json()["status"] == "待發放", r.text
    a = _award("MQ-BY52-002")
    assert a["appr"]["bypass"]["by"] == "bc_sa3" and a["appr"]["bypass"]["forApprover"] == "bc_sa2" and "休假" in a["appr"]["bypass"]["reason"]
    assert a["appr"]["tiers"][0]["approvers"][0]["status"] == "approved"
    log = _q("SELECT changes_json FROM bonus_case_award_edit_log WHERE award_id=? AND action='approve_bypass'", (a["id"],))
    assert len(log) == 1 and "休假" in log[0]["changes_json"]
    au = _q("SELECT username, target_id, detail FROM audit_log WHERE action='bonus.case.approve_bypass'")
    assert len(au) == 1 and au[0]["username"] == "bc_sa3" and au[0]["target_id"] == "MQ-BY52-002"
    d = json.loads(au[0]["detail"])
    assert d["tierApprover"] == "bc_sa2" and d["tierBypassed"] is True and "休假" in d["reason"] and d["award"] == "MQ-BY52-002"
    # 站內通知：其他最高管理者（含原簽核人與送審人）都收到，操作者不收
    got = {r["username"] for r in _q("SELECT username FROM notifications WHERE type='bonus_approver_bypass' AND ref_id='MQ-BY52-002'")}
    assert {"bc_sa", "bc_sa2"} <= got and "bc_sa3" not in got, got
    mails = [kw for key, kw in sent if key == "bonus_approver_bypass"]
    assert len(mails) == 1 and "bc_sa3" not in mails[0]["usernames"] and "bc_sa2" in mails[0]["usernames"]
    assert any("休假" in str(v) for v in mails[0]["rows"][-1])


def test_the_submitter_cannot_use_the_bypass_to_approve_their_own_award(client, people):
    _submitted(client, people, "MQ-BY52-003", [["bc_sa2"]])
    r = _approve(client, people["bc_sa"], "MQ-BY52-003", reason="我自己核")
    assert r.status_code == 403 and _award("MQ-BY52-003")["status"] == "待審核"


def test_a_chain_with_more_than_one_approver_has_no_bypass(client, people, sa3):
    _set_flow(["bc_sa2"])
    _flow(["bc_sa2"], ["bc_sa"])                                   # 兩層、各一人 ⇒ 合計兩位簽核人
    _seed_case("MQ-BY52-004", net=100000)
    assert _create(client, people["bc_sa"], "MQ-BY52-004", members=_members_spec()).status_code == 200
    r = client.post("/api/bonus/cases/MQ-BY52-004/submit", headers=_auth(people["bc_sa"]))
    assert r.status_code == 200, r.text
    r = _approve(client, sa3, "MQ-BY52-004", reason="想代核")
    assert r.status_code == 403 and "bypass" not in _award("MQ-BY52-004")["appr"]


def test_the_listed_approver_approves_normally_without_any_bypass_trace(client, people):
    _submitted(client, people, "MQ-BY52-005", [["bc_sa2"]])
    r = _approve(client, people["bc_sa2"], "MQ-BY52-005")
    assert r.status_code == 200 and r.json()["status"] == "待發放"
    assert "bypass" not in _award("MQ-BY52-005")["appr"]
    assert _q("SELECT 1 FROM audit_log WHERE action='bonus.case.approve_bypass'") == []
    assert _q("SELECT 1 FROM notifications WHERE type='bonus_approver_bypass'") == []


def test_non_superadmin_is_still_refused(client, people):
    _submitted(client, people, "MQ-BY52-006", [["bc_sa2"]])
    r = _approve(client, people["bc_other"], "MQ-BY52-006", reason="x")
    assert r.status_code == 403 and _award("MQ-BY52-006")["status"] == "待審核"


def test_audit_write_failure_rolls_the_whole_approval_back(client, people, sa3, monkeypatch):
    from modules.payroll.api import bonus as bonus_api

    def boom(*a, **k):
        raise RuntimeError("audit down")
    monkeypatch.setattr(bonus_api, "_audit_in_txn", boom)
    _submitted(client, people, "MQ-BY52-007", [["bc_sa2"]])
    try:
        r = _approve(client, sa3, "MQ-BY52-007", reason="強制稽核測試")
        assert r.status_code >= 500
    except RuntimeError:
        pass                                                            # TestClient 可能直接把例外丟出來
    a = _award("MQ-BY52-007")
    assert a["status"] == "待審核" and "bypass" not in a["appr"], "稽核寫不進去，核准不可以成立"
    assert _q("SELECT 1 FROM bonus_case_award_edit_log WHERE award_id=? AND action IN ('approve','approve_bypass')", (a["id"],)) == []


def test_mail_rows_escape_free_text_reason_and_names(client, people, sa3, monkeypatch):
    sent = []
    import modules.payroll.bonus_notify as bn
    monkeypatch.setattr(bn._en, "send_registered", lambda key, **kw: sent.append((key, kw)) or True)
    _submitted(client, people, "MQ-BY52-008", [["bc_sa2"]])
    r = _approve(client, sa3, "MQ-BY52-008", reason="<script>alert(1)</script> & 急件")
    assert r.status_code == 200, r.text
    kw = [kw for key, kw in sent if key == "bonus_approver_bypass"][0]
    why = dict(kw["rows"])["原因"]
    assert "<script>" not in why and "&lt;script&gt;" in why and "&amp;" in why
    assert all("<" not in str(v) for _k, v in kw["rows"]) and "<" not in kw["note"]
