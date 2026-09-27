# -*- coding: utf-8 -*-
"""`JV16②` · 預覽 modal 內、iframe 外側，列出附件並可點開。

使用者原話：「傳票部分，上傳檔案在預覽中要顯示」。

# 🔴 為什麼在 iframe 外側，不要去改 `preview_html()`

`build_html()` 的 `<img src="file:///...">` 是**給伺服器上的 Edge 印
PDF 用的絕對路徑**——使用者的瀏覽器連不到伺服器檔案系統，塞進 iframe
只會是一堆破圖。那個理由現在仍然成立，本檔的題**不驗 iframe 裡面有
附件**，只驗 modal 內、iframe 外面有一份可點開的附件清單。

# 🔴 `<img src>`／`<a href>` 帶不了 `Authorization` header

☠️ 最省力的錯法是把 token 塞進 query string（`JV16①` 的 `⑤`）——
本檔從**前端**這一側再釘一次同一件事：原始碼裡不可以出現把 token／
session 值接進 `attachments/.../` 這個路徑的字串組合。

# ⚠️ 本檔全部是**靜態檢查**（讀 `.html`／`.js` 原始碼）

這個功能今天完全不存在（附件列在主頁面是純文字 `<span>`，modal 裡沒有
任何附件相關內容），沒有 DOM 可以用 Playwright 互動——用靜態檢查釘
「有沒有把它放進去」這件事本身，不釘確切的標記／類別名稱（那是實作
細節，改了退回改本檔）。
"""
import pathlib
import re
from core import source_tree

ROOT = pathlib.Path(__file__).resolve().parents[4]


def _voucher_html():
    return source_tree.page_file("voucher.html").read_text(
        encoding="utf-8", errors="replace")


def _voucher_js():
    return (ROOT / "frontend" / "js" / "voucher.js").read_text(
        encoding="utf-8", errors="replace")


def _strip_comments(html):
    return re.sub(r"<!--.*?-->", lambda m: " " * len(m.group(0)), html,
                  flags=re.S)


def _modal_slice(html):
    """`previewOpen` 那個 modal 的 HTML 片段（本頁最後一個 modal）。"""
    return html[html.index('x-show="previewOpen"'):]


def _iframe_slice(modal):
    """modal 片段裡，`<iframe ...></iframe>` 那一段本身。"""
    m = re.search(r"<iframe\b.*?</iframe>", modal, re.S)
    assert m, "modal 裡找不到 `<iframe>` —— 前置不對，先看 `JV10` 那一段。"
    return m.group(0)


# ══════════════════════════════════════════════════════════════════════
# ① 附件清單要出現在 modal 內、iframe 外
# ══════════════════════════════════════════════════════════════════════

def test_jv16_the_preview_modal_lists_the_attachments():
    """🔴🔴 **核心：預覽 modal 裡（iframe 外側）要看得到附件清單。**

    ⚙️ 判準：modal 片段裡，**扣掉 iframe 本身那一段之後**，還要能找到
    走訪 `attachments` 陣列的痕跡（`x-for="... in attachments"` 或等價
    寫法）——不釘確切的 class／id，那是版面細節。
    """
    html = _strip_comments(_voucher_html())
    modal = _modal_slice(html)
    iframe = _iframe_slice(modal)
    modal_outside_iframe = modal.replace(iframe, "")

    has_attachment_loop = bool(re.search(
        r'x-for="[^"]*\bin\s+attachments\b[^"]*"', modal_outside_iframe))
    assert has_attachment_loop, (
        "預覽 modal 裡（iframe 外側）找不到走訪 `attachments` 的痕跡。\n"
        + "☠️ 使用者打開預覽，看不到這張傳票有哪些附件——\n"
          "   附件上傳得進去、列得出來（在主頁面）、刪得掉、能併進 PDF，\n"
          "   **就是在預覽視窗裡看不到**。")


def test_jv16_the_attachment_list_is_not_inside_the_iframe():
    """⚙️ **正對照：`_iframe_slice()` 真的切得出 iframe 那一段。**

    ☠️ 少了它，上一題若因為 `_iframe_slice()` 傳回空字串（例如 iframe
    的寫法改了、正則匹配不到）而**沒有真的扣掉 iframe 內容**，
    那一題的「iframe 外側」範圍其實是整個 modal，量不到「在不在 iframe
    外」這件事，只量得到「在不在 modal 裡」。
    """
    html = _strip_comments(_voucher_html())
    modal = _modal_slice(html)
    iframe = _iframe_slice(modal)
    assert "srcdoc" in iframe or "previewHtml" in iframe, (
        "切出來的『iframe 那一段』裡沒有 `srcdoc`／`previewHtml`——\n"
        "這支探針切錯了東西，上一題的『扣掉 iframe』沒有意義。")
    assert len(iframe) < len(modal), (
        "iframe 那一段的長度**不小於**整個 modal，代表切出來的其實是整包，\n"
        "上一題『扣掉 iframe 之後』等於什麼都沒扣。")


# ══════════════════════════════════════════════════════════════════════
# ② 每個附件可以點開，而不可以把憑證塞進 URL
# ══════════════════════════════════════════════════════════════════════

def test_jv16_no_credential_is_spliced_into_an_attachment_url():
    """🔴🔴 **`⑤`：原始碼裡不可以把 token／session 值接進附件路徑。**

    ```
    <img src>／<a href> 帶不了 Authorization header
    => 最省力的寫法是把 token 放進 query string
    ☠️ 而 uvicorn access log 會把整串網址寫進 logs/server.log
    ```
    ⚙️ 判準：掃 `voucher.js`／`voucher.html`，找「把某個看起來像憑證的
    變數，字串接進含 `attachments` 的路徑」這種形狀——
    不是找不到某一個特定變數名，是找**這一類**寫法。
    """
    js = _voucher_js()
    html = _strip_comments(_voucher_html())
    src = js + "\n" + html

    suspicious = re.findall(
        r"attachments/[^\"'`]*\$\{[^}]*(?:token|session|auth)[^}]*\}"
        r"|attachments/[^\"'`]*['\"]\s*\+\s*[^;,)]*"
        r"(?:token|session\.token|this\.session)",
        src, re.I)
    assert not suspicious, (
        "原始碼裡把憑證接進了附件路徑：%r\n" % suspicious[:3]
        + "☠️ 那條網址會被 uvicorn access log 永久記錄在 `logs/server.log`，\n"
          "   撿到記錄檔的人等於撿到那個帳號的存取權。\n"
        + "🔑 正確做法：JS 用 `fetch` 帶 `Authorization` header 取回 blob，\n"
          "   再指給 `<img>`／`<a>`（`URL.createObjectURL(blob)`）。")


def test_jv16_the_detector_would_catch_a_real_leak():
    """⚙️ **正對照：上面那把尺認得出真的洩漏寫法嗎？**

    ☠️ 認不出來的話，上一題是一句永遠成立的空話。
    """
    leak_examples = (
        'src="/api/vouchers/${id}/attachments/${fid}?token=${this.session.token}"',
        "href = '/api/vouchers/' + id + '/attachments/' + fid + '?token=' + session.token",
    )
    pattern = (
        r"attachments/[^\"'`]*\$\{[^}]*(?:token|session|auth)[^}]*\}"
        r"|attachments/[^\"'`]*['\"]\s*\+\s*[^;,)]*"
        r"(?:token|session\.token|this\.session)")
    for example in leak_examples:
        assert re.search(pattern, example, re.I), (
            "沒認出真的洩漏寫法：%r —— 判準太窄。" % example)

    clean_example = (
        "const r = await fetch(url, {headers: this._auth()})\n"
        "const blob = await r.blob()\n"
        "img.src = URL.createObjectURL(blob)")
    assert not re.search(pattern, clean_example, re.I), (
        "正確的 fetch+blob 寫法被誤判成洩漏——判準太寬。")
