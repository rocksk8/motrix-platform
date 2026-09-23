# -*- coding: utf-8 -*-
"""`JV17` · 匯出鈕只能在「預覽」視窗內按到。

使用者原話：
```
「傳票部分，上傳檔案在預覽中要顯示，網頁下方的預覽右邊兩個匯出PDF跟
  匯出PDF(含附件)這兩個不顯示，這兩個只顯示於預覽窗口內，避免人員
  不確認就直接按匯出」
```

# ⚙️ 現況（實查，`frontend/pages/voucher.html`）

```
主頁面（要拿掉）  data-testid="voucher-pdf"              匯出 PDF
                 data-testid="voucher-pdf-attachments"   匯出 PDF（含附件）
主頁面（留著）    data-testid="voucher-preview"           預覽
預覽 modal 內（本來就在，留著）
                 兩顆同文字的按鈕（`modal-foot` 裡，緊接 `previewOpen`
                 那個 modal），沒有 data-testid，@click 都是 `exportPdf(...)`
```

# 🔴 對照組（A 明著警告）：既有 `JV10`／`JV11` 題有沒有打**主頁面**那顆鈕

實查 `grep -rl "voucher-pdf" backend/tests/*.py`：**0 支命中**。
`JV5`／`JV9`／`JV10`／`JV11` 全部走 `client.get(PDF % vid)` 直接打後端
端點，沒有一支透過 Playwright 點擊前端按鈕來觸發匯出 —— **不需要改任何
既有測試**，閘門本身也沒有變。`test_jv5_the_page_has_both_export_actions`
只靜態掃 `voucher.js` 有沒有 `pdf-download`／`with_attachments` 的字樣，
與按鈕搬到哪裡無關，同樣不受影響。

# 🔴 第二個匯出入口：查過，**沒有**（我第一版查錯，這裡留著更正）

第一版用 `grep "vouchers/.*pdf-download"` 掃 `case-management.js`，
命中 7 處，一度以為那是第二入口——**而那是 `contractor-vouchers`／
`invoice-vouchers`，字串裡剛好含有 `vouchers` 這個子字串，跟本檔的
會計傳票 `/api/vouchers/` 是不同資源**。改用精確的 `api/vouchers/`
（前面沒有 `contractor-`／`invoice-`）重查：只有 `voucher.js:300`
一處呼叫 `pdf-download`，只有 `voucher.html` 一個頁面引用 `voucher.js`
做這件事。⇒ 沒有第二個匯出入口，不需要另外回報 A 裁。

# ⚠️ 本檔只寫**結構**（按鈕在不在哪裡），不寫「按下去會匯出」的行為

那個行為（`exportPdf()` 會不會走到後端、閘門擋不擋得住）已經被
`JV5`／`JV9`／`JV10`／`JV11` 用直打後端的方式驗過，本檔不重覆驗證同一件
事，只驗**入口的位置**——這正是這一批唯一改變的東西。
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _voucher_html():
    return (ROOT / "frontend" / "pages" / "voucher.html").read_text(
        encoding="utf-8", errors="replace")


def _strip_comments(html):
    return re.sub(r"<!--.*?-->", lambda m: " " * len(m.group(0)), html,
                  flags=re.S)


def _modal_body(html):
    """`previewOpen` 那個 modal 的 HTML 片段（含 `modal-foot`）。

    ⚙️ 用 `x-show="previewOpen"` 那個 `<div class="modal-overlay">` 當起點，
       抓到下一個**同層級** `</div>` 收尾的 modal-overlay 為止——
       這裡簡化成「抓到檔案結尾前最後一個 `</div>` 區塊」，因為這是
       這個檔案裡最後一個 modal。若檔案結構改了，退回改本檔的擷取法。
    """
    start = html.index('x-show="previewOpen"')
    return html[start:]


# ══════════════════════════════════════════════════════════════════════
# 主頁面：兩顆匯出鈕不可以再出現
# ══════════════════════════════════════════════════════════════════════

def test_jv17_the_export_buttons_are_gone_from_the_main_page():
    """🔴🔴 **核心：主頁面（modal 外）不可以再有匯出鈕。**

    ⚙️ 判準是 `data-testid`（技術識別碼），不是按鈕文字——中文文案
    可能被 `WD1`／`EM1` 這類措辭守門改掉，釘文字會在別人做對事情時紅。
    """
    html = _strip_comments(_voucher_html())
    modal = _modal_body(html)
    outside = html[:html.index('x-show="previewOpen"')]

    for testid in ("voucher-pdf", "voucher-pdf-attachments"):
        assert 'data-testid="%s"' % testid not in outside, (
            "主頁面（modal 外）裡還找得到 `data-testid=\"%s\"` 的匯出鈕。\n"
            % testid
            + "☠️ 使用者不用先看預覽就能直接按下去匯出，\n"
              "   而這正是使用者要擋的：「避免人員不確認就直接按匯出」。")


def test_jv17_the_preview_button_still_exists_on_the_main_page():
    """⚙️ **正對照：「預覽」入口不可以被一起拿掉。**

    ☠️ 少了它，一個「把整個匯出區塊都刪掉」的過度實作也會讓上一題綠——
       而那樣使用者連預覽的入口都沒有了。
    """
    html = _strip_comments(_voucher_html())
    outside = html[:html.index('x-show="previewOpen"')]
    assert 'data-testid="voucher-preview"' in outside, (
        "主頁面找不到 `data-testid=\"voucher-preview\"`（「預覽」按鈕）。\n"
        + "☠️ 拿掉匯出鈕的同時，把預覽入口也一起清掉了——\n"
          "   使用者現在**沒有任何方式**可以看到或匯出這張傳票。")


# ══════════════════════════════════════════════════════════════════════
# 預覽 modal 內：兩顆匯出鈕要留著
# ══════════════════════════════════════════════════════════════════════

def test_jv17_the_export_buttons_still_exist_inside_the_preview_modal():
    """🔴 **正對照：預覽 modal 內的兩顆匯出鈕本來就在，不可以被一起清掉。**

    ⚠️ modal 內這兩顆**沒有** `data-testid`（實查現況），釘 `@click` 的
    呼叫式（`exportPdf(false)` / `exportPdf(true)`）——那是行為不是文字，
    比對按鈕上的中文字樣更不容易被無關的改動誤傷。
    """
    html = _strip_comments(_voucher_html())
    modal = _modal_body(html)
    assert "exportPdf(false)" in modal, (
        "預覽 modal 裡找不到呼叫 `exportPdf(false)` 的按鈕（「匯出 PDF」）。\n"
        + "☠️ 使用者現在**完全按不到**匯出——連預覽窗內的入口都不見了。")
    assert "exportPdf(true)" in modal, (
        "預覽 modal 裡找不到呼叫 `exportPdf(true)` 的按鈕（「匯出 PDF（含附件）」）。")


def test_jv17_the_modal_export_buttons_are_not_the_ones_removed_from_the_page():
    """⚙️ **這一題的探針自我驗證：`_modal_body()` 抓對範圍了嗎。**

    ☠️ 若 `_modal_body()` 不小心把整個檔案都當成「modal 內」，
       上面兩題會對**任何位置**的 `exportPdf` 呼叫都判定成立，
       包括主頁面被拿掉之前殘留的那兩顆——那時題目量不到「搬家」這件事，
       只量得到「頁面裡還存在這串呼叫」。
    """
    html = _strip_comments(_voucher_html())
    modal_start = html.index('x-show="previewOpen"')
    outside = html[:modal_start]
    # 正對照材料：`openPreview()` 只應該在 modal **外**被呼叫（觸發預覽的
    # 那顆按鈕在主頁面上）——用它確認 `outside` 這一段真的抓到了主頁面內容。
    assert "openPreview()" in outside, (
        "`_modal_body()` 切出來的『modal 外』片段裡找不到 `openPreview()`——\n"
        "這支探針切錯範圍了，上面兩題的結論不可信，先修這裡。")
