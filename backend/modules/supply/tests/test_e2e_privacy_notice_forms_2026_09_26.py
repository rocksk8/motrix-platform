"""供應商聯絡人的個資告知（M03 頁面）e2e。

2026-09-26 自 `backend/tests/test_e2e_privacy_notice_forms_2026_09_26.py` 移入（PLAYBOOK §B-11：拿掉本模組時這些題跟著消失）。
"""
import pytest

pytest.importorskip("playwright.sync_api")
from helpers import privacy_notice as pn  # noqa: E402
from tests.test_e2e_privacy_notice_forms_2026_09_26 import ROOT, _ready, _tok  # noqa: E402,F401


@pytest.mark.e2e
def test_supplier_contact_notice_records_and_unchecked_does_not_block(live_server, make_user, new_page, login_as, client):
    u = make_user(username="pne_su", role="superadmin")
    h = _tok(client, u)
    sid = client.post("/api/suppliers", json={"name": "告知測試供應商", "data": {"contacts": [
        {"id": 501, "name": "甲窗口"}, {"id": 502, "name": "乙窗口"}]}}, headers=h).json()["id"]
    page = new_page()
    login_as(page, u)
    page.goto(live_server + "/pages/suppliers.html")
    _ready(page, f"{ROOT}.suppliers.length > 0 && {ROOT}.privacyNotice")
    page.evaluate(f"() => {ROOT}.openEdit({ROOT}.suppliers.find(s => s.id === {sid}))")
    rows = page.locator("[data-privacy-card] [data-privacy-contact]")
    rows.nth(1).locator("[data-privacy-missing]").wait_for(state="visible", timeout=10000)
    rows.nth(0).locator("input[data-privacy-ack]").check()          # 只勾第一位
    page.evaluate(f"() => {ROOT}.saveSupplier()")
    page.wait_for_function(f"() => !{ROOT}.showModal", timeout=10000)
    assert pn.get_ack("supplier_contact", f"{sid}:501")["byUsername"] == "pne_su"
    assert pn.get_ack("supplier_contact", f"{sid}:502") is None, "沒勾的那一位不可以被記錄（而且存檔沒被擋）"
