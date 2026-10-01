# -*- coding: utf-8 -*-
"""檔案中心「開啟檔案」（FHB9）：結果列的主動作＝直接開上傳的檔案（新分頁、blob、位元組相同）；「前往原單據」降為次要連結。
取不到（已刪除／無權限）⇒ 明確訊息、不留空白分頁；沒有新的取檔路徑（仍是 /api/attachments/open，使用者自己的 token）。"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests.test_attachments_open_2026_09_30 import PNG, Q, world  # noqa: E402,F401  (world 是 fixture)
from tests.test_e2e_filehub_2026_09_30 import _png, _seed_valid_signed  # noqa: E402


def _boss_on_center(make_user, new_context, live_server, query="?q=sign.png&date_from="):
    boss = make_user(username="fco_boss", role="superadmin", modules=[])
    ctx = new_context()
    page = ctx.new_page()
    inject_login(page, live_server, boss[0], boss[1])
    page.goto(live_server + "/pages/file-center.html" + query)
    page.wait_for_selector("[data-fc-open]", state="visible", timeout=15000)
    return ctx, page


@pytest.mark.e2e
def test_fhb9_open_file_opens_the_uploaded_bytes_in_a_new_tab_and_stays_on_the_page(live_server, make_user, new_context, client, world):
    _H, _note, _f = world
    ctx, page = _boss_on_center(make_user, new_context, live_server)
    here = page.url
    page.evaluate("() => { window.__blobs = []; const c = URL.createObjectURL.bind(URL); "
                  "URL.createObjectURL = (b) => { window.__blobs.push(b); return c(b) } }")
    with ctx.expect_page() as pi:
        page.locator("[data-fc-open]").first.click()
    tab = pi.value
    tab.wait_for_function("() => location.href.startsWith('blob:')", timeout=15000)
    got = page.evaluate("async () => { const b = window.__blobs[0]; "                       # 頁面建立、新分頁導向的那個 blob
                        "return { type: b.type, bytes: Array.from(new Uint8Array(await b.arrayBuffer())) } }")
    assert got["type"] == "image/png" and bytes(got["bytes"]) == PNG        # 開的是上傳的那個檔，不是單據頁
    assert page.url == here and not page.locator("[data-fc-open-msg]").is_visible()


@pytest.mark.e2e
@pytest.mark.parametrize("status,word", [(404, "刪除"), (403, "權限")])
def test_fhb9_unopenable_file_shows_a_clear_message_and_leaves_no_blank_tab(live_server, make_user, new_context, client, world, status, word):
    ctx, page = _boss_on_center(make_user, new_context, live_server)
    page.route("**/api/attachments/open*", lambda r: r.fulfill(status=status, content_type="application/json", body='{"detail":"檔案不存在"}'))
    n = len(ctx.pages)
    page.locator("[data-fc-open]").first.click()
    page.wait_for_selector("[data-fc-open-msg]", state="visible", timeout=10000)
    assert word in page.locator("[data-fc-open-msg]").inner_text() and "sign.png" in page.locator("[data-fc-open-msg]").inner_text()
    page.wait_for_function("(n) => true", arg=n)
    assert len(ctx.pages) == n, "失敗後不得留下空白分頁"


@pytest.mark.e2e
def test_fhb9_secondary_link_still_goes_to_the_source_document(live_server, make_user, new_context, client, world):
    _H, note_no, _f = world
    ctx, page = _boss_on_center(make_user, new_context, live_server)
    link = page.locator("[data-fc-origin]").first
    assert "原單據" in link.inner_text() and link.get_attribute("href")
    link.click()
    page.wait_for_function("() => !location.pathname.endsWith('file-center.html')", timeout=15000)
