"""簽核佇列：獎金分潤不可以預告「一次簽完」——後端的獎金簽核本來就不做連簽。

☠️ 2026-09-25（hichan-8d 做 EX-SIGN 時發現）：佇列對獎金分潤照樣算 selfCascadeTiers，
同一人連任兩層時確認視窗寫「確認後將一併完成這 2 層簽核（不需要再簽一次）」，
但 approve_case_bonus 不處理 cascade ⇒ 實際只簽了一層，第二層還要再簽一次。
hichan-0a 裁：最小修——佇列對獎金分潤不預告（前端與後端行為一致），不改獎金簽核本身。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

from tests.test_e2e_approval_reassign_ui_2026_09_14 import _login  # noqa: E402,F401
from modules.payroll.tests.test_bonus_case_api_2026_09_24 import (  # noqa: E402,F401
    people, _seed_case, _create, _members_spec, _auth, _set_flow)

NO = "MQ-BQC-001"


def _award():
    import db
    c = db.get_db()
    try:
        a = dict(c.execute("SELECT status, approval_json FROM bonus_case_awards WHERE quote_no=?", (NO,)).fetchone())
        a["appr"] = json.loads(a["approval_json"] or "{}")
        return a
    finally:
        c.close()


@pytest.mark.e2e
def test_bonus_award_in_queue_does_not_promise_signing_two_tiers(live_server, client, people):
    _set_flow(["bc_sa2"])
    import db
    c = db.get_db()
    try:
        c.execute("UPDATE system_settings SET value_json=? WHERE key='bonus_approval_flow'", (json.dumps(
            {"includeSubmitterManagerTier": False, "tiers": [
                {"order": 0, "approvers": [{"username": "bc_sa2", "display_name": "bc_sa2"}]},
                {"order": 1, "approvers": [{"username": "bc_sa2", "display_name": "bc_sa2"}]}]}),))
        c.commit()
    finally:
        c.close()
    _seed_case(NO, net=100000)
    assert _create(client, people["bc_sa"], NO, members=_members_spec()).status_code == 200
    assert client.post("/api/bonus/cases/%s/submit" % NO, headers=_auth(people["bc_sa"])).status_code == 200

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_context().new_page()
            messages = []

            def _on_dialog(d):
                messages.append((d.type, d.message))
                d.accept()
            page.on("dialog", _on_dialog)
            _login(page, live_server, "bc_sa2", "Test-Pass-123")
            page.goto(f"{live_server}/pages/approval-queue.html")
            page.wait_for_selector(f"text={NO}", timeout=15000)
            page.click(f"text={NO}")
            btn = page.locator('button.btn-approve:visible').first
            btn.wait_for(state="visible", timeout=10000)
            with page.expect_response(lambda r: "/api/bonus/cases/%s/approve" % NO in r.url, timeout=15000) as resp:
                btn.click()
            body = json.loads(resp.value.request.post_data or "{}")
            confirms = [m for t, m in messages if t == "confirm"]
            assert confirms, messages
            assert "一併完成" not in confirms[0], "獎金分潤不做連簽，確認視窗不可以預告：%r" % confirms[0]
            assert body.get("cascade") in (False, None)
        finally:
            browser.close()
    a = _award()
    assert a["status"] == "待審核" and int(a["appr"]["currentTier"]) == 1, "簽一次只前進一層"
