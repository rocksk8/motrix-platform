# -*- coding: utf-8 -*-
"""第 47 班政策題（使用者裁示，經 node-d8 轉述 2026-10-08）：Q-S6 有簽核層時送審人不得自核（唯一在職最高管理者例外）。"""
import json

import pytest

from modules.payroll.api import payslips as payslips_api
from modules.payroll.tests.test_payslip_approval_t46 import _clear_flow, _flow, _q, _status, _su, _x
from modules.payroll.tests.test_payslip_edit_guard_2026_08_28 import _auth, _insert_payslip, _login

_MAKE_USER_DEFAULT_ROLE = "superadmin"


@pytest.fixture(autouse=True)
def _archive_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(payslips_api, "_archive_dir", lambda: str(tmp_path / "payslip_archive"))


def _only_active_superadmin(name):
    """讓 `name` 成為全公司唯一在職的最高管理者（其他最高管理者停用）。"""
    _x("UPDATE users SET active=0 WHERE role='superadmin' AND username!=?", (name,))


# ── Q-S6 ─────────────────────────────────────────────────────────────────────────────────────────
def test_submitter_cannot_approve_own_payslip_when_tiers_exist_and_another_superadmin_is_active(client, make_user):
    ua, ha = _su(client, make_user, "t47p_req")
    ub, hb = _su(client, make_user, "t47p_other")
    _flow([ua], [ub])                                                  # 簽核層裡列了送審人自己
    _insert_payslip("PS-203101-901")
    assert client.post("/api/payslips/PS-203101-901/submit", headers=ha).json()["status"] == "待審核"
    r = client.post("/api/payslips/PS-203101-901/approve", headers=ha)
    assert r.status_code == 403 and "不得自行審核" in r.text, r.text
    assert _status("PS-203101-901") == "待審核"
    appr = json.loads(_q("SELECT approval_json FROM payslips WHERE slip_no='PS-203101-901'")[0]["approval_json"])
    assert [x["action"] for x in appr["history"]] == ["submit"], "被擋的簽核不留簽核紀錄"
    # 不會永久卡死：送審人（也是當層簽核人）可以退回，回草稿後重新處理
    assert client.post("/api/payslips/PS-203101-901/reject", headers=ha, json={"reason": "改由他人簽"}).status_code == 200
    assert _status("PS-203101-901") == "草稿"
    _clear_flow()


def test_sole_active_superadmin_may_approve_own_payslip_with_tiers(client, make_user):
    ua, ha = _su(client, make_user, "t47p_solo")
    _only_active_superadmin(ua)
    _flow([ua])
    _insert_payslip("PS-203101-902")
    assert client.post("/api/payslips/PS-203101-902/submit", headers=ha).json()["status"] == "待審核"
    r = client.post("/api/payslips/PS-203101-902/approve", headers=ha)
    assert r.status_code == 200 and r.json()["status"] == "已核准", "唯一在職最高管理者例外（否則整條流程永久卡死）"
    _clear_flow()


def test_other_superadmin_in_the_chain_still_approves_normally(client, make_user):
    ua, ha = _su(client, make_user, "t47p_req2")
    ub, hb = _su(client, make_user, "t47p_t1")
    _flow([ub])
    _insert_payslip("PS-203101-903")
    client.post("/api/payslips/PS-203101-903/submit", headers=ha)
    r = client.post("/api/payslips/PS-203101-903/approve", headers=hb)
    assert r.status_code == 200 and r.json()["status"] == "已核准", r.text
    _clear_flow()
