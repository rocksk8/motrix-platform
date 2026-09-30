# -*- coding: utf-8 -*-
"""共用檔案預覽元件（static/file-preview.js，P1）的行為題——元件單獨在空白頁載入，不依賴任何業務頁：
內嵌規則（副檔名＋mime 雙重符合；SVG／偽裝一律不內嵌）、blob 指定 type 與 revoke、競態丟棄、鍵盤（Esc／←→／Tab）與焦點回原處、
actions 的動態文字與停用、錯誤狀態、另開新分頁、withMime。"""
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")

JS = Path(__file__).resolve().parents[2] / "frontend" / "static" / "file-preview.js"

PROBE = """
window.__pv = { types: {}, revoked: [] }
const _c = URL.createObjectURL.bind(URL), _r = URL.revokeObjectURL.bind(URL)
URL.createObjectURL = (b) => { const u = _c(b); window.__pv.types[u] = b.type; return u }
URL.revokeObjectURL = (u) => { window.__pv.revoked.push(u); return _r(u) }
window.PNG = new Uint8Array([137,80,78,71,13,10,26,10,1,2,3,4]).buffer
window.PDF = new TextEncoder().encode('%PDF-1.4 x').buffer
"""


def _page(new_context):
    page = new_context().new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.set_content("<html><body><button id='opener'>開</button></body></html>")
    page.evaluate(PROBE)
    page.add_script_tag(path=str(JS))
    return page, errors


@pytest.mark.e2e
def test_kind_is_extension_and_mime_together_and_never_embeds_svg_or_html(new_context):
    page, errors = _page(new_context)
    got = page.evaluate("""() => { const k = MotrixFilePreview.kind; return [
      k({filename: 'a.png', mime: 'image/png'}), k({filename: 'a.jpg', mime: 'image/jpeg'}), k({filename: 'a.pdf', mime: 'application/pdf'}),
      k({filename: '偽裝.png', mime: 'image/svg+xml'}), k({filename: 'a.svg', mime: 'image/svg+xml'}), k({filename: 'a.html', mime: 'application/pdf'}),
      k({filename: 'a.png', mime: ''}), k({filename: 'a.xlsx', mime: 'application/vnd.ms-excel'}), k({filename: 'a.docx'}), k({filename: 'noext', mime: 'image/png'}),
      k({filename: 'A.PNG', mime: 'IMAGE/PNG; charset=x'})] }""")
    assert got == ["image", "image", "pdf", "download", "download", "download", "download", "sheet", "doc", "download", "image"]
    assert page.evaluate("() => MotrixFilePreview.withMime({path: 'x/y/z.PDF'})") == {"path": "x/y/z.PDF", "filename": "z.PDF", "mime": "application/pdf"}
    assert page.evaluate("() => MotrixFilePreview.kind(MotrixFilePreview.withMime({path: 'x/evil.svg'}))") == "download"   # 補 mime 只補白名單內的副檔名
    assert not errors, errors


@pytest.mark.e2e
def test_image_embeds_with_our_blob_type_closes_with_escape_revokes_and_returns_focus(new_context):
    page, errors = _page(new_context)
    page.focus("#opener")
    page.evaluate("""() => MotrixFilePreview.open({ items: [{filename: 'a.png', mime: 'image/png', size: 12}], fetchBlob: async () => window.PNG,
                                                    opener: document.getElementById('opener') })""")
    page.wait_for_selector('[data-testid="file-preview-img"]', state="visible", timeout=5000)
    src = page.get_attribute('[data-testid="file-preview-img"]', "src")
    assert src.startswith("blob:") and page.evaluate("u => window.__pv.types[u]", src) == "image/png"      # 用我們判定的 type，不用回應標頭
    assert page.locator('[data-testid="file-preview-prev"]').count() == 0                                 # 單檔沒有 ◀ ▶
    assert page.locator('[data-testid="file-preview-download"]').count() == 1
    page.keyboard.press("Escape")
    page.wait_for_selector('[data-testid="file-preview"]', state="detached", timeout=3000)
    assert page.evaluate("u => window.__pv.revoked.includes(u)", src)                                      # 關閉 ⇒ revoke
    page.wait_for_function("() => document.activeElement && document.activeElement.id === 'opener'", timeout=3000)
    assert not errors, errors


@pytest.mark.e2e
def test_svg_disguised_as_png_and_docx_are_cards_with_download_not_embedded(new_context):
    page, errors = _page(new_context)
    for name, mime in (("偽裝.png", "image/svg+xml"), ("圖示.svg", "image/svg+xml"), ("報價.xlsx", ""), ("說明.docx", "")):
        page.evaluate("""([n, m]) => MotrixFilePreview.open({ items: [{filename: n, mime: m, size: 2048}], fetchBlob: async () => { window.__fetched = (window.__fetched || 0) + 1; return window.PNG } })""", [name, mime])
        page.wait_for_selector("[data-fp-card]", state="visible", timeout=5000)
        assert page.locator('[data-testid="file-preview-img"]').count() == 0 and page.locator('[data-testid="file-preview-pdf"]').count() == 0
        assert "請下載後開啟" in page.locator("[data-fp-card]").inner_text() and name in page.locator("[data-fp-card]").inner_text()
        page.click('[data-testid="file-preview-close"]')
    assert (page.evaluate("() => window.__fetched") or 0) == 0, "不內嵌的類型不該先把整個檔抓下來"
    assert not errors, errors


@pytest.mark.e2e
def test_arrow_keys_step_and_a_slow_first_response_never_overwrites_the_second(new_context):
    page, errors = _page(new_context)
    page.evaluate("""() => {
      window.__order = []
      MotrixFilePreview.open({ items: [{filename: 'a.png', mime: 'image/png'}, {filename: 'b.pdf', mime: 'application/pdf'}, {filename: 'c.png', mime: 'image/png'}],
        fetchBlob: (it) => { window.__order.push(it.filename); return new Promise(r => setTimeout(() => r(it.filename === 'a.png' ? window.PNG : window.PDF), it.filename === 'b.pdf' ? 500 : 10)) } })
    }""")
    page.wait_for_selector('[data-testid="file-preview-img"]', state="visible", timeout=5000)
    page.keyboard.press("ArrowRight")                        # → b.pdf（慢 500ms）
    page.keyboard.press("ArrowRight")                        # 馬上 → c.png（快）
    page.wait_for_selector('[data-testid="file-preview-img"]', state="visible", timeout=5000)
    page.wait_for_timeout(800)                                # 等慢的那個回來：必須被丟掉
    assert page.locator('[data-testid="file-preview-pdf"]').count() == 0
    assert "c.png" in page.locator(".modal-head__title").inner_text() and "3 / 3" in page.locator(".modal-head__title").inner_text()
    src = page.get_attribute('[data-testid="file-preview-img"]', "src")
    assert page.evaluate("u => window.__pv.types[u]", src) == "image/png"
    assert page.evaluate("u => window.__pv.revoked.filter(x => x !== u).length >= 1", src)                 # 切走的舊 blob 都 revoke 了
    page.keyboard.press("ArrowRight")                        # 循環回第 1 個
    page.wait_for_function("() => document.querySelector('.modal-head__title').innerText.includes('1 / 3')", timeout=3000)
    page.keyboard.press("ArrowLeft")
    page.wait_for_function("() => document.querySelector('.modal-head__title').innerText.includes('3 / 3')", timeout=3000)
    assert not errors, errors


@pytest.mark.e2e
def test_actions_have_dynamic_labels_enabled_state_refresh_and_errors_show_as_status(new_context):
    page, errors = _page(new_context)
    page.evaluate("""() => {
      window.__state = { brought: false, runs: 0 }
      MotrixFilePreview.open({ items: [{filename: 'a.png', mime: 'image/png'}], download: false, fetchBlob: async () => window.PNG,
        actions: [
          { label: '取消', testid: 'att-pv-cancel', ghost: true, run: () => MotrixFilePreview.close() },
          { label: (it) => window.__state.brought ? '已帶入' : '帶入附件', testid: 'att-pv-bring', enabled: (it) => !window.__state.brought,
            run: () => { window.__state.runs++; if (window.__state.runs === 1) throw new Error('帶入失敗了'); window.__state.brought = true; MotrixFilePreview.refresh() } }
        ] })
    }""")
    page.wait_for_selector('[data-testid="att-pv-bring"]', state="visible", timeout=5000)
    assert page.locator('[data-testid="file-preview-download"]').count() == 0                              # download:false
    assert page.evaluate("() => document.activeElement.getAttribute('data-testid')") == "att-pv-cancel"     # 焦點先落在「取消」
    page.click('[data-testid="att-pv-bring"]')
    page.wait_for_selector(".fp-status.vc-err", state="visible", timeout=3000)
    assert "帶入失敗了" in page.locator(".fp-status").inner_text()
    page.click('[data-testid="att-pv-bring"]')
    page.wait_for_function("() => document.querySelector('[data-testid=att-pv-bring]').innerText === '已帶入'", timeout=3000)
    assert page.locator('[data-testid="att-pv-bring"]').is_disabled()
    page.click('[data-testid="att-pv-cancel"]')
    page.wait_for_selector('[data-testid="file-preview"]', state="detached", timeout=3000)
    assert page.locator(".fp-status").count() == 0
    assert not errors, errors


@pytest.mark.e2e
def test_tab_stays_inside_the_window_and_a_fetch_failure_shows_an_error_not_a_blank(new_context):
    page, errors = _page(new_context)
    page.evaluate("""() => MotrixFilePreview.open({ items: [{filename: 'a.png', mime: 'image/png'}], fetchBlob: async () => { throw new Error('HTTP 403') } })""")
    page.wait_for_selector(".fp-err", state="visible", timeout=3000)
    assert "HTTP 403" in page.locator(".fp-err").inner_text() and page.locator('[data-testid="file-preview-img"]').count() == 0
    for _ in range(6):
        page.keyboard.press("Tab")
        assert page.evaluate("() => document.querySelector('[data-testid=\"file-preview\"]').contains(document.activeElement)")
    assert not errors, errors


@pytest.mark.e2e
def test_open_in_new_tab_navigates_a_blank_tab_to_the_blob_only_for_image_or_pdf(new_context):
    page, errors = _page(new_context)
    res = page.evaluate("""async () => {
      const opened = []
      window.open = () => { const w = { location: '', closed: false, close() { this.closed = true } }; opened.push(w); return w }
      await MotrixFilePreview.openInNewTab({filename: 'x.pdf', mime: 'application/pdf'}, async () => window.PDF)
      let rejected = ''
      try { await MotrixFilePreview.openInNewTab({filename: 'x.svg', mime: 'image/svg+xml'}, async () => window.PNG) } catch (e) { rejected = e.message }
      let failed = ''
      try { await MotrixFilePreview.openInNewTab({filename: 'y.png', mime: 'image/png'}, async () => { throw new Error('boom') }) } catch (e) { failed = e.message }
      return { n: opened.length, loc: String(opened[0].location), type: window.__pv.types[String(opened[0].location)], rejected, failed, secondClosed: opened[1].closed }
    }""")
    assert res["n"] == 2 and res["loc"].startswith("blob:") and res["type"] == "application/pdf"
    assert "下載後開啟" in res["rejected"]                                                                  # svg：連空白分頁都不開
    assert res["failed"] == "boom" and res["secondClosed"] is True                                         # 取檔失敗 ⇒ 空白分頁關掉
    assert not errors, errors
