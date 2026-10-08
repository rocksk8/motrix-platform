# -*- coding: utf-8 -*-
"""第 48 班：Q-S6（有簽核層時送審人不得自核）的「簽核層只列送審人」情境——記錄實際行為。

結論（本檔釘住）：
  1. `setting_to_active_tiers` 不會把送審人從層裡剔除（手動挑的簽核人原樣保留）；
  2. 送審人不能自核（Q-S6）；另一位在職最高管理者「不在層內」也不能核准（check_approve_permission 只認當層簽核人，403）；
  3. 因此這張單**核准路徑上沒有人**——但不是永久卡死：任一最高管理者（含非層內者）都可退回成草稿，
     由『另一位最高管理者』重新送審（送審人換人⇒不再是自核），或管理員先改簽核設定再重送。
建議見 docs/platform/plans/S6-SOLE-APPROVER-T48.md。
"""
import json

import pytest

from modules.payroll.api import payslips as payslips_api
from modules.payroll.tests.test_payslip_approval_t46 import _clear_flow, _flow, _q, _status, _su
from modules.payroll.tests.test_payslip_edit_guard_2026_08_28 import _insert_payslip


@pytest.fixture(autouse=True)
def _archive_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(payslips_api, "_archive_dir", lambda: str(tmp_path / "payslip_archive"))


def test_setting_to_active_tiers_keeps_the_requester_in_a_manual_tier(client, make_user):
    import db
    from helpers.tiered_approval import setting_to_active_tiers
    make_user(username="t48s6_a", role="superadmin")
    setting = {"includeSubmitterManagerTier": False, "tiers": [{"order": 0, "approvers": [{"username": "t48s6_a", "display_name": "a"}]}]}
    conn = db.get_db()
    try:
        tiers = setting_to_active_tiers(setting, conn, "t48s6_a")
    finally:
        conn.close()
    assert [[a["username"] for a in t["approvers"]] for t in tiers] == [["t48s6_a"]], "送審人沒有被剔除（所以 Q-S6 會讓這層沒人能核）"


def test_tier_lists_only_submitter_other_superadmin_cannot_approve_but_anyone_can_return_and_other_resubmits(client, make_user):
    ua, ha = _su(client, make_user, "t48s6_req")
    ub, hb = _su(client, make_user, "t48s6_other")
    _flow([ua])                                                         # 層裡只有送審人
    _insert_payslip("PS-204801-801")
    assert client.post("/api/payslips/PS-204801-801/submit", headers=ha).json()["status"] == "待審核"
    # 送審人：Q-S6 擋
    r = client.post("/api/payslips/PS-204801-801/approve", headers=ha)
    assert r.status_code == 403 and "不得自行審核" in r.text, r.text
    # 另一位最高管理者（不在層內）：也不能核准
    r = client.post("/api/payslips/PS-204801-801/approve", headers=hb)
    assert r.status_code == 403 and "此層需由以下人員簽核" in r.text, r.text
    assert _status("PS-204801-801") == "待審核"
    # 出路一：層外的最高管理者可以退回（check_reject_permission 放行 superadmin）
    assert client.post("/api/payslips/PS-204801-801/reject", headers=hb, json={"reason": "送審人是唯一簽核人，改由我送審"}).status_code == 200
    assert _status("PS-204801-801") == "草稿"
    # 出路二：由另一位最高管理者重新送審 ⇒ 送審人≠簽核人，原簽核人可以正常核准
    assert client.post("/api/payslips/PS-204801-801/submit", headers=hb).json()["status"] == "待審核"
    r = client.post("/api/payslips/PS-204801-801/approve", headers=ha)
    assert r.status_code == 200 and r.json()["status"] == "已核准", r.text
    appr = json.loads(_q("SELECT approval_json FROM payslips WHERE slip_no='PS-204801-801'")[0]["approval_json"])
    assert appr["requestedBy"] == ub
    _clear_flow()


def test_same_submitter_resubmitting_after_return_deadlocks_again(client, make_user):
    ua, ha = _su(client, make_user, "t48s6_req2")
    ub, hb = _su(client, make_user, "t48s6_other2")
    _flow([ua])
    _insert_payslip("PS-204801-802")
    client.post("/api/payslips/PS-204801-802/submit", headers=ha)
    client.post("/api/payslips/PS-204801-802/reject", headers=ha, json={"reason": "x"})
    assert client.post("/api/payslips/PS-204801-802/submit", headers=ha).json()["status"] == "待審核"      # 同一人重送：簽核鏈重新解析，仍只有他
    assert client.post("/api/payslips/PS-204801-802/approve", headers=ha).status_code == 403
    assert client.post("/api/payslips/PS-204801-802/approve", headers=hb).status_code == 403
    _clear_flow()
