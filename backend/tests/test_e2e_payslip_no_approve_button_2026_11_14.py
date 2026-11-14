# -*- coding: utf-8 -*-
"""T86 U10：沒有簽核權限的人（非最高管理者）看不到「簽核／退回」鈕；最高管理者照舊看得到。
正式機 90 天內非最高管理者按核准 403 ×4：按鈕本來就只有最高管理者能成功，現在不給非最高管理者看。"""
import pytest

pytest.importorskip("playwright.sync_api")

from modules.payroll.tests.test_payslip_edit_guard_2026_08_28 import _insert_payslip  # noqa: E402
from tests._e2e_login import inject_login  # noqa: E402


def _to_review(no):
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE payslips SET status='待審核' WHERE slip_no=?", (no,))
        conn.commit()
    finally:
        conn.close()


def _open(page, live_server, user, no):
    inject_login(page, live_server, user[0], user[1])
    page.goto("%s/pages/payslips.html" % live_server)
    page.locator("tr", has_text=no).first.click(timeout=30000)
    page.get_by_test_id("ps-review-note").wait_for(state="visible", timeout=15000)


@pytest.mark.e2e
def test_module_holder_sees_note_but_no_approve_or_reject(live_server, make_user, new_context):
    no = "PS-203101-931"
    _insert_payslip(no)
    _to_review(no)
    fin = make_user(username="ps_na_fin", role="finance", modules=["payslip"])
    page = new_context(viewport={"width": 1440, "height": 900}).new_page()
    _open(page, live_server, fin, no)
    assert "只有最高管理者" in page.get_by_test_id("ps-review-note").inner_text()
    assert page.get_by_test_id("ps-approve").is_hidden()
    assert page.get_by_test_id("ps-reject").is_hidden()


@pytest.mark.e2e
def test_superadmin_still_sees_approve_and_reject(live_server, make_user, new_context):
    no = "PS-203101-932"
    _insert_payslip(no)
    _to_review(no)
    root = make_user(username="ps_na_root", role="superadmin")
    page = new_context(viewport={"width": 1440, "height": 900}).new_page()
    _open(page, live_server, root, no)
    page.get_by_test_id("ps-approve").wait_for(state="visible", timeout=10000)
    page.get_by_test_id("ps-reject").wait_for(state="visible", timeout=10000)
