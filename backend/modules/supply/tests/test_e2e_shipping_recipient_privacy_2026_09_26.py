"""出貨單收件人的個資告知，畫面端（稽核 D PN-M1、PN-S2）。

- 換了收件人並存檔 ⇒ 重新打開，區塊顯示「尚未記錄個資告知」（不可以拿前一位的紀錄冒充；D 的突變 PNJS 原本存活）
- 勾「已告知收件人」再存檔 ⇒ 伺服器記錄的是**存檔後**那一位；重新打開顯示已告知
觀測點：伺服器的紀錄（API）與區塊上的 data-privacy-missing／data-privacy-acked。點的是真正的欄位、勾選框與儲存鈕。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402
from tests.test_privacy_notice_forms_2026_09_26 import _insert_quote  # noqa: E402
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')

NO = "PN-SH-E2E"
DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"
CARD = '[data-privacy-subject="shipping_recipient"]'


def _api(client, h, method, path, **kw):
    r = getattr(client, method)(path, headers=h, **kw)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _open_note(page, base, u):
    inject_login(page, base, u[0], u[1])
    page.goto(f"{base}/pages/case-management.html?q={NO}&tab=shipping")
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}'"
                           f" && {DATA_JS}.shippingNotes.length === 1", timeout=20000)
    page.locator("button", has_text="編輯").first.click()
    page.locator(CARD).wait_for(state="visible", timeout=8000)
    page.wait_for_function(f"() => {DATA_JS}.showShippingModal && {DATA_JS}.editShippingNoteNo", timeout=8000)


def _wait_saved(page):
    page.wait_for_function(f"() => !{DATA_JS}.shippingSaving && !{DATA_JS}.showShippingModal", timeout=10000)


@pytest.mark.e2e
def test_changing_the_recipient_shows_missing_and_ack_records_the_saved_one(live_server, make_user, e2e_browser, client):
    u = make_user(username="pn_sh_e2e", role="superadmin")
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u[0], "password": u[1]}).json()["token"]}
    _insert_quote(NO)
    note = _api(client, h, "post", "/api/shipping-notes", json={"quote_no": NO, "recipient": "甲收件"})["note_no"]
    _api(client, h, "post", f"/api/shipping-notes/{note}/privacy-notice/ack", json={"subject": "甲收件"})

    page = e2e_browser.new_context().new_page()
    _open_note(page, live_server, u)
    card = page.locator(CARD)
    card.locator("[data-privacy-acked]").wait_for(state="visible", timeout=8000)       # 甲已告知

    # 換成乙並存檔（沒有勾已告知）
    page.locator('input[x-model="shippingForm.recipient"]').fill("乙收件")
    page.locator("button", has_text="儲存出貨單").click()
    _wait_saved(page)
    page.reload()
    _open_note(page, live_server, u)
    card = page.locator(CARD)
    card.locator("[data-privacy-missing]").wait_for(state="visible", timeout=8000)
    assert card.locator("[data-privacy-acked]").count() == 0, "乙沒有紀錄，不可以顯示甲的「已告知」"

    # 勾已告知、存檔 ⇒ 記錄的是乙
    card.locator("[data-privacy-ack]").check()
    page.locator("button", has_text="儲存出貨單").click()
    _wait_saved(page)
    acks = _api(client, h, "get", f"/api/shipping-notes/{note}/privacy-notice")["acks"]
    assert set(acks) == {"甲收件", "乙收件"}, acks
    page.reload()
    _open_note(page, live_server, u)
    page.locator(CARD).locator("[data-privacy-acked]").wait_for(state="visible", timeout=8000)
