# -*- coding: utf-8 -*-
"""第 46 班：勞報單頁面送審流程 e2e（草稿 → 送審 → 待審核 → 簽核／退回）。

驗：送審後狀態標籤與面板切到「待審核」（送審人看得到簽核按鈕但後端擋——此處只驗簽核人流程）；簽核人在自己的頁面按「簽核」⇒ 已核准；
退回要填原因（瀏覽器提示框）⇒ 回草稿、可再送審。後端權限與狀態機另有 API 測試；這裡驗頁面按鈕真的接得上。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from modules.payroll.api import payslips as payslips_api  # noqa: E402
from modules.payroll.tests.test_payslip_edit_guard_2026_08_28 import _insert_payslip  # noqa: E402
from tests._e2e_login import inject_login  # noqa: E402


@pytest.fixture()
def world(client, make_user, tmp_path, monkeypatch):
    import db
    monkeypatch.setattr(payslips_api, "_archive_dir", lambda: str(tmp_path / "payslip_archive"))
    req = make_user(username="ps_e2e_req", role="superadmin")
    apr = make_user(username="ps_e2e_apr", role="superadmin")
    flow = {"includeSubmitterManagerTier": False,
            "tiers": [{"order": 0, "approvers": [{"username": "ps_e2e_apr", "display_name": "ps_e2e_apr"}]}]}
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) "
                     "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                     ("payslip_approval_flow", json.dumps(flow), "2031-01-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()
    _insert_payslip("PS-203101-901")
    _insert_payslip("PS-203101-902")
    return req, apr


def _status(no):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT status FROM payslips WHERE slip_no=?", (no,)).fetchone()["status"]
    finally:
        conn.close()


def _open_detail(page, live_server, user, no):
    inject_login(page, live_server, user[0], user[1])
    page.goto("%s/pages/payslips.html" % live_server)
    page.locator("tr", has_text=no).first.click(timeout=30000)


@pytest.mark.e2e
def test_submit_then_approver_approves_from_the_page(live_server, world, new_context):
    req, apr = world
    p1 = new_context(viewport={"width": 1440, "height": 900}).new_page()
    _open_detail(p1, live_server, req, "PS-203101-901")
    p1.get_by_test_id("ps-submit").click(timeout=15000)
    p1.get_by_test_id("ps-review-note").wait_for(state="visible", timeout=15000)
    assert _status("PS-203101-901") == "待審核"
    p2 = new_context(viewport={"width": 1440, "height": 900}).new_page()
    _open_detail(p2, live_server, apr, "PS-203101-901")
    p2.get_by_test_id("ps-approve").click(timeout=15000)
    p2.get_by_test_id("ps-approved-note").wait_for(state="visible", timeout=15000)
    assert _status("PS-203101-901") == "已核准"


@pytest.mark.e2e
def test_reject_needs_a_reason_and_returns_to_draft(live_server, world, new_context):
    req, apr = world
    p1 = new_context(viewport={"width": 1440, "height": 900}).new_page()
    _open_detail(p1, live_server, req, "PS-203101-902")
    p1.get_by_test_id("ps-submit").click(timeout=15000)
    p1.get_by_test_id("ps-review-note").wait_for(state="visible", timeout=15000)
    p2 = new_context(viewport={"width": 1440, "height": 900}).new_page()
    _open_detail(p2, live_server, apr, "PS-203101-902")
    p2.once("dialog", lambda d: d.dismiss())                                  # 不填原因 ⇒ 不送出
    p2.get_by_test_id("ps-reject").click(timeout=15000)
    assert _status("PS-203101-902") == "待審核"
    p2.once("dialog", lambda d: d.accept("資料不齊"))
    p2.get_by_test_id("ps-reject").click(timeout=15000)
    p2.get_by_test_id("ps-submit").wait_for(state="visible", timeout=15000)   # 回草稿 ⇒ 又出現「送審」
    assert _status("PS-203101-902") == "草稿"


@pytest.mark.e2e
def test_submit_button_is_hidden_for_a_payslip_module_holder_who_is_not_superadmin(live_server, world, make_user, new_context):
    """送審只有最高管理者能按（伺服器 403 才是真守門）；持勞報單模組的一般人員打開草稿看不到「送審」。"""
    staff = make_user(username="ps_e2e_staff", role="user", modules=["payslip"], legacy_finance_flag=False)
    req, _apr = world
    p = new_context(viewport={"width": 1440, "height": 900}).new_page()
    _open_detail(p, live_server, staff, "PS-203101-901")
    p.wait_for_selector("[data-testid=ps-edit]", state="attached", timeout=15000)     # 詳情已開（草稿可編輯）
    assert p.get_by_test_id("ps-submit").count() == 1 and not p.get_by_test_id("ps-submit").is_visible()
    p2 = new_context(viewport={"width": 1440, "height": 900}).new_page()
    _open_detail(p2, live_server, req, "PS-203101-901")
    p2.get_by_test_id("ps-submit").wait_for(state="visible", timeout=15000)           # 最高管理者仍看得到
