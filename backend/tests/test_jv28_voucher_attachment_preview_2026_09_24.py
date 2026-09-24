# -*- coding: utf-8 -*-
"""`JV28` · 傳票附件要能預覽，不能只有檔名（`docs/windows/SPEC-JV28-ATTACHMENT-PREVIEW.md`）。

使用者逐字：「在傳票上，已上傳檔案要能夠預覽，只有名稱無法辨別」。

§5 驗收（觀測點打在**畫面上真的看得到的東西**）：
① 點編輯頁的圖片附件 ⇒ 頁內 modal，`<img>` 的 `naturalWidth > 0`
② 點 PDF ⇒ modal 內 iframe 的 src 是 blob、那個 blob 的 type 是 pdf
③ 圖片附件在清單上有縮圖（`naturalWidth > 0`）
④ `.svg`、以及偽裝成 `.png` 而 mime 是 `image/svg+xml` 的 ⇒ **不內嵌**，只有下載鈕
⑤ 預覽窗（JV16 那份）點附件 ⇒ 同一個頁內 modal，**popup 事件 0 次**
⑥ 關閉 modal 後 blob URL 已 revoke（對它 fetch 會失敗）
⑦ 無權限帳號取檔 ⇒ 403（凍結組：既有權限不退）
"""
import io
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

pytest.importorskip("playwright.sync_api")

from test_voucher_preview_export_feedback_2026_09_23 import (  # noqa: E402
    _login, _create_voucher, _open_preview,
)

MODAL = '[data-testid="voucher-att-preview"]'
IMG = '[data-testid="voucher-att-preview-img"]'
PDF = '[data-testid="voucher-att-preview-pdf"]'
DOWNLOAD = '[data-testid="voucher-att-download"]'
OPEN = '[data-testid="voucher-att-open"]'
THUMB = '[data-testid="voucher-att-thumb"]'

_SVG = (b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
        b'<script>window.__jv28_pwned=1</script><rect width="10" height="10"/></svg>')


#: ⚙️ 探針：記下每一個 blob URL 的 type，與哪些被 revoke 了。
#: ⚠️ 不可以用 `fetch(blobURL)` 去驗：這個站的 CSP 是 `connect-src 'self'`，
#:    fetch blob: 會被擋（Failed to fetch）—— 第一版就是這樣紅在自己的探針上，
#:    而產品碼（img-src／frame-src 都允許 blob:）是好的。
_BLOB_PROBE = """
(() => {
  window.__jv28 = { types: {}, revoked: [] };
  const c = URL.createObjectURL.bind(URL), r = URL.revokeObjectURL.bind(URL);
  URL.createObjectURL = (b) => { const u = c(b); window.__jv28.types[u] = b && b.type; return u; };
  URL.revokeObjectURL = (u) => { window.__jv28.revoked.push(u); return r(u); };
})();
"""


def _png_bytes():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _setup(page, live_server, make_user, uname):
    u, p = make_user(username=uname, role="superadmin", modules=["cashier"])
    _login(page, live_server, u, p)
    token = page.evaluate("() => JSON.parse(localStorage.getItem('motrix_session')).token")
    vid = _create_voucher(page, live_server, token)
    return token, vid


def _upload(page, live_server, token, vid, name, mime, data):
    r = page.request.post(
        f"{live_server}/api/vouchers/{vid}/attachments",
        headers={"Authorization": "Bearer " + token},
        multipart={"files": {"name": name, "mimeType": mime, "buffer": data}})
    assert r.ok, r.text()


def _open_page(page, live_server, vid):
    page.goto(f"{live_server}/pages/voucher.html?id={vid}")
    page.wait_for_function(
        "() => document.querySelector('[x-data]') "
        "&& Alpine.$data(document.querySelector('[x-data]')).id", timeout=15000)


@pytest.mark.e2e
def test_jv28_clicking_an_image_opens_an_in_page_preview(live_server, make_user, e2e_browser):
    browser = e2e_browser
    page = browser.new_page()
    token, vid = _setup(page, live_server, make_user, "jv28_img")
    _upload(page, live_server, token, vid, "發票.png", "image/png", _png_bytes())
    _open_page(page, live_server, vid)
    page.click(OPEN + ':has-text("發票.png")', timeout=10000)
    page.wait_for_selector(IMG, state="visible", timeout=10000)
    w = page.eval_on_selector(IMG, "el => el.complete ? el.naturalWidth : new Promise("
                                   "r => el.onload = () => r(el.naturalWidth))")
    assert w > 0, "預覽 modal 裡的圖片沒有載入（naturalWidth=%r）" % w


@pytest.mark.e2e
def test_jv28_clicking_a_pdf_embeds_it_as_a_pdf_blob(live_server, make_user, e2e_browser):
    browser = e2e_browser
    page = browser.new_page()
    page.add_init_script(_BLOB_PROBE)
    token, vid = _setup(page, live_server, make_user, "jv28_pdf")
    _upload(page, live_server, token, vid, "請款單.pdf", "application/pdf",
            b"%PDF-1.4\n%jv28\n")
    _open_page(page, live_server, vid)
    page.click(OPEN + ':has-text("請款單.pdf")', timeout=10000)
    page.wait_for_selector(PDF, state="visible", timeout=10000)
    src = page.get_attribute(PDF, "src") or ""
    assert src.startswith("blob:"), "PDF 預覽的 src 不是 blob：%r" % src
    btype = page.evaluate("u => window.__jv28.types[u]", src)
    assert btype == "application/pdf", "blob 的 type 是 %r，不是 application/pdf" % btype


@pytest.mark.e2e
def test_jv28_image_attachments_show_a_thumbnail_in_the_list(live_server, make_user, e2e_browser):
    browser = e2e_browser
    page = browser.new_page()
    token, vid = _setup(page, live_server, make_user, "jv28_thumb")
    _upload(page, live_server, token, vid, "現場照.png", "image/png", _png_bytes())
    _upload(page, live_server, token, vid, "合約.pdf", "application/pdf", b"%PDF-1.4\n")
    _open_page(page, live_server, vid)
    page.wait_for_selector(THUMB, state="visible", timeout=10000)
    widths = page.eval_on_selector_all(
        THUMB, "els => Promise.all(els.map(el => el.complete ? el.naturalWidth : "
               "new Promise(r => el.onload = () => r(el.naturalWidth))))")
    assert widths and all(w > 0 for w in widths), "縮圖沒有載入：%r" % widths
    assert len(widths) == 1, "只有圖片該有縮圖（PDF 不該有），實得 %d 個" % len(widths)


def _seed_real_svg(vid):
    """`.svg` 過不了上傳白名單 ⇒ 直接種一列＋一個真的檔（帶入他處附件時仍可能出現這種檔）。"""
    import db
    from helpers.uploads import UPLOADS_ROOT
    rel = "voucher_attachments/%s/jv28seed.svg" % vid
    full = os.path.join(UPLOADS_ROOT, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as f:
        f.write(_SVG)
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO voucher_attachments (voucher_id, file_id, filename, path, size, mime,"
            " source_type, source_doc_no, source_file_id, uploaded_by, uploaded_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (vid, "jv28svg1", "圖示.svg", rel, len(_SVG), "image/svg+xml", "", "", "",
             "seed", "2026-09-24T00:00:00"))
        conn.commit()
    finally:
        conn.close()


@pytest.mark.e2e
def test_jv28_svg_is_never_embedded_only_offered_for_download(live_server, make_user, e2e_browser):
    browser = e2e_browser
    page = browser.new_page()
    token, vid = _setup(page, live_server, make_user, "jv28_svg")
    # 偽裝：副檔名 .png、而伺服器存的 mime 是 image/svg+xml（mime 取自上傳者宣稱的 content-type）
    _upload(page, live_server, token, vid, "偽裝.png", "image/svg+xml", _SVG)
    _seed_real_svg(vid)
    _open_page(page, live_server, vid)
    for name in ("偽裝.png", "圖示.svg"):
        page.click(OPEN + ':has-text("%s")' % name, timeout=10000)
        page.wait_for_selector(DOWNLOAD, state="visible", timeout=10000)
        assert not page.is_visible(IMG), "%s 被當成圖片內嵌了" % name
        assert not page.is_visible(PDF), "%s 被內嵌進 iframe 了" % name
        page.click('[data-testid="voucher-att-close"]')
    assert page.evaluate("() => window.__jv28_pwned") is None, "SVG 裡的腳本被執行了"


@pytest.mark.e2e
def test_jv28_the_preview_window_list_opens_the_same_in_page_modal_without_popups(
        live_server, make_user, e2e_browser):
    browser = e2e_browser
    page = browser.new_page()
    popups = []
    page.on("popup", lambda p: popups.append(p))
    token, vid = _setup(page, live_server, make_user, "jv28_popup")
    _upload(page, live_server, token, vid, "收據.png", "image/png", _png_bytes())
    _open_preview(page, live_server, token, vid)
    page.click('.vc-preview-atts a.vc-att__name:has-text("收據.png")', timeout=10000)
    # PERF #6：原本固定等 1.5 秒 ⇒ 等頁內預覽圖出現（正確行為的終點）。
    # 錯的寫法（開新分頁）時圖不會出現 ⇒ 等滿 10 秒，那段時間內 popup 早就被數到，下面照樣紅。
    try:
        page.wait_for_selector(IMG, state="visible", timeout=10000)
    except Exception:
        pass
    # ⚙️ 先數 popup（量尺：HEAD 上 window.open 的那一次要被數到），再看頁內 modal。
    assert popups == [], "點附件開了 %d 個新分頁／彈出視窗" % len(popups)
    page.wait_for_selector(IMG, state="visible", timeout=10000)


@pytest.mark.e2e
def test_jv28_closing_the_modal_revokes_the_blob_url(live_server, make_user, e2e_browser):
    browser = e2e_browser
    page = browser.new_page()
    page.add_init_script(_BLOB_PROBE)
    token, vid = _setup(page, live_server, make_user, "jv28_revoke")
    _upload(page, live_server, token, vid, "單據.png", "image/png", _png_bytes())
    _open_page(page, live_server, vid)
    page.click(OPEN + ':has-text("單據.png")', timeout=10000)
    page.wait_for_selector(IMG, state="visible", timeout=10000)
    src = page.get_attribute(IMG, "src")
    assert src and src.startswith("blob:"), src
    assert page.evaluate("u => u in window.__jv28.types", src), (
        "量尺：探針沒記到這個 blob —— 下面的斷言量不到東西")
    assert not page.evaluate("u => window.__jv28.revoked.includes(u)", src), (
        "量尺：還沒關就被 revoke 了（畫面上的圖會是破的）")
    page.click('[data-testid="voucher-att-close"]')
    # PERF #6：原本固定等 0.3 秒 ⇒ 等 revoke 被記到（最多 3 秒；沒記到就交給下面的斷言）
    try:
        page.wait_for_function("u => window.__jv28.revoked.includes(u)", arg=src, timeout=3000)
    except Exception:
        pass
    assert page.evaluate("u => window.__jv28.revoked.includes(u)", src), (
        "關閉 modal 之後 blob URL 沒有 revoke —— 每開一次就累積一份")


def test_jv28_an_account_without_voucher_access_cannot_fetch_an_attachment(client, make_user):
    """⑦ 凍結組：取檔權限不因這一輪改前端而變（沿用 `_require_voucher_access`）。"""
    u, p = make_user(username="jv28_owner", role="superadmin", modules=["cashier"])
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    hdr = {"Authorization": "Bearer " + tok}
    r = client.post("/api/vouchers", headers=hdr, json={
        "summary": "JV28", "lines": [{"account_code": "1113", "debit": 1, "credit": 0},
                                     {"account_code": "4111", "debit": 0, "credit": 1}]})
    vid = r.json()["id"]
    up = client.post("/api/vouchers/%s/attachments" % vid, headers=hdr,
                     files={"files": ("x.png", io.BytesIO(_png_bytes()), "image/png")})
    fid = up.json()["attachments"][0]["file_id"]
    u2, p2 = make_user(username="jv28_outsider", role="user", modules=["reports"])
    tok2 = client.post("/api/auth/login", json={"username": u2, "password": p2}).json()["token"]
    r2 = client.get("/api/vouchers/%s/attachments/%s" % (vid, fid),
                    headers={"Authorization": "Bearer " + tok2})
    assert r2.status_code == 403, "沒有出納模組的人取得到傳票附件：%s" % r2.status_code
