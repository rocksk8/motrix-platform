# -*- coding: utf-8 -*-
"""附件目錄 P3 — 畫面（＋預覽）：檔案中心頁與案件頁「全部附件」頁籤。
檔案中心：條件寫進網址、預設近 90 天（可改）、分類樹帶命中數且點了會篩、點列用共用預覽元件（圖片內嵌、Esc 關）、沒有權限的人看不到別案的檔；
案件頁：檔案中心在才出現頁籤，列出本案件的檔、點檔預覽。"""
import struct
import zlib

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests.test_attachments_open_2026_09_30 import Q, _login, world  # noqa: E402,F401  (world 是 fixture)


def _png():
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b"")


def _seed_valid_signed(client, H, name="valid.png"):
    r = client.post("/api/quotations/%s/signed-files" % Q, headers=H["ct_admin"], files=[("files", (name, _png(), "image/png"))])
    assert r.status_code in (200, 201), r.text


@pytest.mark.e2e
def test_file_center_search_filters_url_default_range_and_preview(live_server, make_user, new_context, client, world):
    H, note_no, f = world
    _seed_valid_signed(client, H)
    boss = make_user(username="fc_e2e_boss", role="superadmin", modules=[])
    page = new_context().new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, boss[0], boss[1])

    # 沒有任何條件 ⇒ 預設近 90 天（畫面標出、可改成全部時間）
    page.goto(live_server + "/pages/file-center.html")
    page.wait_for_selector("#fc-default-range", state="visible", timeout=15000)
    assert page.locator("#fc-from").input_value() != ""
    page.click("#fc-all-time")
    page.wait_for_selector("#fc-default-range", state="hidden", timeout=5000)
    page.wait_for_selector("#fc-table", state="visible", timeout=15000)

    # 關鍵字 ⇒ 結果篩小、條件進網址（可分享、不含憑證）
    page.fill("#fc-q", "valid")
    page.click("#fc-search")
    page.wait_for_function("() => document.querySelectorAll('#fc-table tbody tr').length === 1", timeout=10000)
    assert "q=valid" in page.evaluate("() => location.search") and "token" not in page.evaluate("() => location.href").lower()
    assert page.locator("#fc-table tbody tr").first.inner_text().count("valid.png") == 1

    # 點列 ⇒ 共用預覽元件：圖片內嵌；Esc 關
    page.locator("#fc-table tbody tr").first.click()
    page.wait_for_selector('[data-testid="file-preview-img"]', state="visible", timeout=15000)
    page.keyboard.press("Escape")
    page.wait_for_selector('[data-testid="file-preview"]', state="detached", timeout=5000)

    # 分類樹：帶命中數、點了只剩那一類
    page.fill("#fc-q", "")
    page.click("#fc-search")
    page.wait_for_selector('[data-fc-cat="completion_note"]', timeout=10000)
    assert page.locator('[data-fc-cat="completion_note"] small').inner_text().strip().isdigit()
    page.click('[data-fc-cat="completion_note"]')
    page.wait_for_function("() => [...document.querySelectorAll('#fc-table tbody tr')].every(r => r.innerText.includes('完工單')) "
                           "&& document.querySelectorAll('#fc-table tbody tr').length >= 1", timeout=10000)
    assert "types=completion_note" in page.evaluate("() => location.search")
    assert not errors, errors


@pytest.mark.e2e
def test_file_center_page_shows_nothing_of_other_cases_to_a_user_without_access(live_server, make_user, new_context, client, world):
    H, _, _ = world
    _seed_valid_signed(client, H)
    u, p = make_user(username="fc_e2e_out", role="sales", modules=["file_center"])       # 有檔案中心，但不是該案的人
    page = new_context().new_page()
    inject_login(page, live_server, u, p)
    page.goto(live_server + "/pages/file-center.html?quote_no=" + Q)
    page.wait_for_selector("#fc-none", state="visible", timeout=15000)
    assert page.locator("#fc-table tbody tr").count() == 0
    text = page.locator("body").inner_text()
    assert "valid.png" not in text and "sign.png" not in text


@pytest.mark.e2e
def test_case_page_has_an_all_attachments_tab_that_lists_and_previews_this_cases_files(live_server, make_user, new_context, client, world):
    H, note_no, f = world
    _seed_valid_signed(client, H)
    boss = make_user(username="fc_e2e_case", role="superadmin", modules=[])
    page = new_context().new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, boss[0], boss[1])
    page.goto(live_server + "/pages/case-management.html?q=" + Q)
    page.wait_for_selector('[data-testid="cm-tab-allfiles"]', state="visible", timeout=25000)       # 檔案中心在 ⇒ 頁籤出現
    page.click('[data-testid="cm-tab-allfiles"]')
    page.wait_for_selector('[data-testid="cm-allfiles"] [data-allfiles-row]', timeout=15000)
    names = page.locator('[data-testid="cm-allfiles"] tbody').inner_text()
    assert "valid.png" in names and "sign.png" in names
    row = page.locator('[data-testid="cm-allfiles"] tr', has_text="valid.png").first
    row.click()
    page.wait_for_selector('[data-testid="file-preview-img"]', state="visible", timeout=15000)
    page.keyboard.press("Escape")
    page.wait_for_selector('[data-testid="file-preview"]', state="detached", timeout=5000)
    assert not errors, errors
