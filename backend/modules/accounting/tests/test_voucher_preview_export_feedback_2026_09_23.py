# -*- coding: utf-8 -*-
"""`JV19` · 從預覽視窗按匯出，訊息要出現在視窗裡，不是背景。

使用者原話：
```
「未送審或是簽核完成的傳票，點選匯出PDF的錯誤通知在背景，沒有在視窗上」
```

# ⚙️ 動工前先重現，不是先寫題——三種可能成因分辨結果

```
甲 modal 裡那一段根本沒渲染        —— **失敗訊息不是這個**；成功訊息**是**
乙 有渲染，而它在可捲動區域下方   —— **失敗訊息是這個，已用 Playwright
                                     實測到具體座標**
丙 modal 是後來才加的（JV16②）    —— 已排除：JV16②③／JV17 今天都已經
                                     落地（本檔動工時重跑過，皆綠），
                                     使用者的觀察與現在的程式碼一致
```

## 🔴 失敗訊息（`attErr`）：情境**乙**，已用具體座標重現

```
1280×800 視窗、草稿傳票、預覽視窗內按「匯出 PDF」：
  attErr = "這張傳票尚未簽核完成，還差主管簽核，暫不能匯出。"（訊息本身是對的）
  errTop=787.98 / errBottom=828.38      <= 元素的實際位置
  bodyTop=80 / bodyBottom=696.4 / bodyClientHeight=616   <= 可視範圍
  bodyScrollHeight=762                  <= 內容比可視範圍高 146px
  iframeHeight=576                      <= 光是 iframe 就佔了可視範圍的大半
  isWithinBodyVisible: False            <= 訊息在可捲動區域**外**
```
🔑 成因：`.vc-preview-frame{height:72vh}` 是固定值，而 modal 的可視高度
是**彈性**的（`.modal-body{flex:1}`，扣掉 head／foot 後才知道剩多少）——
iframe 加上附件清單，內容高度很容易超過可視範圍，而**附件清單與錯誤
訊息都排在 iframe 後面**，一超過就被推到捲動區域外。

## 🔴 成功訊息（`attMsg`）：情境**甲**，比失敗訊息更嚴重——**根本沒有渲染點**

```
pages/voucher.html
  主頁面（396-400）  <template x-if="attErr">…</template>
                     <template x-if="attMsg">…</template>   <= 兩個都有
  modal 內（518-541） <template x-if="attErr">…</template>  <= 只有這一個
                     ⇒ attMsg 在 modal 裡**完全沒有對應的 DOM 節點**
```
⇒ 使用者從預覽視窗按「匯出 PDF」**成功**時，`this.attMsg = '已匯出。'`
被設定，而 modal 裡沒有任何地方會顯示它——不是「捲不到」，是「壓根
沒印出來」，症狀比失敗訊息更純粹的「在背景」。

# ⚙️ 判準：釘「使用者看得到」，不是「節點存在」

`x-if` 節點存在於 DOM 只回答得了「有沒有寫程式碼」，回答不了「使用者
看不看得到」——這正是使用者抱怨的那件事。本檔用 Playwright 量**實際
幾何位置**（是否落在可捲動祖先目前顯示的範圍內），不是 `count() > 0`。

# ⚠️ 對照組：主頁面的渲染點不可以被順手拿掉

`JV17` 之後主頁面已經沒有匯出按鈕了，但主頁面**還有別的路徑會設
`attErr`／`attMsg`**（上傳附件、刪除附件、帶入附件——見 `voucher.js`
170/201/230 行），這些操作仍然在主頁面進行，不透過預覽視窗。修
`JV19` 時若把主頁面那兩個 `x-if` 節點清掉，會讓那幾個操作的回饋
無家可歸。
"""
import json
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")

import uvicorn
from tests._e2e_login import inject_login  # noqa: E402
from tests._ports import free_safe_port
from core import source_tree

_LINES = [{"account_code": "1113", "debit": 1000, "credit": 0},
         {"account_code": "4111", "debit": 0, "credit": 1000}]



def _rendered(page):
    """PERF #6：等 Alpine 把這次狀態變化畫完（nextTick）＋瀏覽器實際畫出兩個影格。
    ⚠️ 只適用於沒有 CSS transition 的元素（有 transition 的要等轉場落定）。"""
    page.evaluate("() => new Promise(r => (window.Alpine ? Alpine.nextTick : (f => f()))(() => requestAnimationFrame(() => requestAnimationFrame(r))))")



def _login(page, base_url, username, password):
    return inject_login(page, base_url, username, password)


def _create_voucher(page, live_server, token):
    resp = page.request.post(
        f"{live_server}/api/vouchers",
        headers={"Authorization": "Bearer " + token,
                "Content-Type": "application/json"},
        data=json.dumps({"summary": "JV19 測試", "lines": _LINES}))
    assert resp.ok, resp.text()
    return resp.json()["id"]


def _open_preview(page, live_server, token, vid):
    page.goto(f"{live_server}/pages/voucher.html?id={vid}")
    page.wait_for_function(
        "() => document.querySelector('[x-data]') "
        "&& Alpine.$data(document.querySelector('[x-data]')).id",
        timeout=15000)
    page.click('[data-testid="voucher-preview"]')
    page.wait_for_selector('[data-testid="voucher-preview-frame"]',
                           state="visible", timeout=10000)


def _element_visible_within_scroll_area(page, el_selector, container_selector):
    """`el_selector` 是否落在 `container_selector`（可捲動祖先）**目前顯示**
    的範圍內——不是問元素在不在 DOM 裡，是問使用者**現在**看不看得到。
    """
    return page.evaluate(
        """([elSel, boxSel]) => {
            const el = document.querySelector(elSel)
            const box = document.querySelector(boxSel)
            if (!el || !box) return {found: false}
            const er = el.getBoundingClientRect()
            const br = box.getBoundingClientRect()
            const visible = er.height > 0 && er.width > 0
                && er.top >= br.top && er.bottom <= br.bottom
                && er.top >= 0 && er.bottom <= window.innerHeight
            return {found: true, visible: visible,
                    errTop: er.top, errBottom: er.bottom,
                    boxTop: br.top, boxBottom: br.bottom}
        }""", [el_selector, container_selector])


@pytest.mark.e2e
def test_jv19_export_failure_message_is_visible_inside_the_preview(
        live_server, make_user, e2e_browser):
    """🔴🔴 **核心：草稿傳票在預覽視窗按匯出，失敗訊息要在可視範圍內。**

    ⚙️ 已實測重現（見檔頭）：1280×800 視窗下，訊息落在可捲動區域外
    （`errTop=787.98` 而可視範圍只到 `696.4`）。這一題把那次重現釘成
    迴歸測試。
    """
    username, password = make_user(username="jv19_fail", role="superadmin",
                                   modules=["cashier"])
    browser = e2e_browser
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    token = _login(page, live_server, username, password)["token"]   # PERF #5：注入登入後頁面停在空白頁，token 取回傳值
    vid = _create_voucher(page, live_server, token)
    _open_preview(page, live_server, token, vid)

    page.click('.modal-foot button:has-text("匯出 PDF")'
              ':not(:has-text("含附件"))')
    # PERF #6：原本固定等 800ms ⇒ 等匯出開始又結束（exporting 由 true 回到 false）
    page.wait_for_function("() => !Alpine.$data(document.querySelector('[x-data]')).exporting", timeout=30000)
    _rendered(page)

    result = _element_visible_within_scroll_area(
        page, ".vc-preview-atts .vc-err", ".modal-body")
    assert result.get("found"), (
        "modal 裡找不到 `.vc-preview-atts .vc-err` 這個節點——\n"
        "退回改本檔的選擇器。")
    assert result.get("visible"), (
        "失敗訊息**存在於 DOM，而使用者目前看不到**：%r\n" % result
        + "☠️ 使用者按下匯出、系統擋下來並說明原因，\n"
          "   而那句話落在需要往下捲的區域——對使用者而言，\n"
          "   這與『什麼都沒發生』是同一件事。")


@pytest.mark.e2e
def test_jv19_export_success_message_is_visible_inside_the_preview(
        live_server, make_user, e2e_browser):
    """🔴🔴 **`②`：成功那一側也要看得到，不只驗失敗。**

    ```
    pages/voucher.html 518-541（modal 內）
      只有 <template x-if="attErr"> ，**沒有對應 attMsg 的節點**
    ```
    ⚙️ 這一題比上一題更基本：失敗訊息至少**渲染了**（只是捲不到），
    成功訊息**連渲染都沒有**——只驗失敗的話，這一半的洞永遠不會被抓到。
    """
    username, password = make_user(username="jv19_ok", role="superadmin",
                                   modules=["cashier"])
    browser = e2e_browser
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    token = _login(page, live_server, username, password)["token"]   # PERF #5：注入登入後頁面停在空白頁，token 取回傳值
    vid = _create_voucher(page, live_server, token)
    for step in ("submit", "approve", "approve"):
        r = page.request.post(
            f"{live_server}/api/vouchers/{vid}/{step}",
            headers={"Authorization": "Bearer " + token,
                    "Content-Type": "application/json"},
            data="{}")
        assert r.ok, (step, r.text())
    _open_preview(page, live_server, token, vid)

    page.click('.modal-foot button:has-text("匯出 PDF")'
              ':not(:has-text("含附件"))')
    # 🔴 **與失敗案例不同的等待時間**：草稿被擋在 approval_done()
    #    的閘門，PDF 產生根本沒開始，幾乎立刻回應；已核准的單
    #    真的會走 Edge headless 產 PDF（本會話其他題實測過
    #    single-digit 秒等級），固定 800ms 量不到，要等
    #    `exporting` 變回 `false`。
    page.wait_for_function(
        "() => !Alpine.$data(document.querySelector('[x-data]'))"
        ".exporting",
        timeout=30000)
    _rendered(page)   # PERF #6：原本固定等 300ms

    att_msg = page.evaluate(
        "() => Alpine.$data(document.querySelector('[x-data]'))"
        ".attMsg")
    assert att_msg, (
        "匯出成功了，而 `attMsg` 是空的——前置不對，先看這一格。")

    found_in_modal = page.evaluate(
        """() => {
            const box = document.querySelector('.modal-box')
            if (!box) return false
            return Array.from(box.querySelectorAll('*')).some(
                el => el.textContent && el.textContent.trim() !== ''
                && el.children.length === 0
                && el.textContent.includes('已匯出'))
        }""")
    assert found_in_modal, (
        "`attMsg`（%r）已核准的傳票匯出成功，"
        "而 modal 裡完全找不到顯示它的地方——\n" % att_msg
        + "☠️ `voucher.html` 的 modal 片段只有 `attErr` 的 "
          "`<template x-if>`，沒有對應 `attMsg` 的節點：\n"
          "   使用者按下匯出、系統成功了，而視窗裡**什麼都沒有**，\n"
          "   比失敗訊息『捲不到』更徹底——是『壓根沒印出來』。")


def test_jv19_the_main_page_feedback_slots_are_not_removed():
    """⚙️ **對照組：主頁面的 `attErr`／`attMsg` 渲染點不可以被順手拿掉。**

    `JV17` 之後主頁面沒有匯出按鈕了，但上傳附件／刪除附件／帶入附件
    （`voucher.js` 170／201／230 行）仍然在主頁面操作，不透過預覽視窗。
    修 `JV19` 時若把主頁面那兩個 `x-if` 節點也清掉，這幾個操作的回饋
    會無家可歸——那是另一個新洞，不是這次要修的範圍。
    """
    import pathlib
    html = source_tree.page_file("voucher.html").read_text(
        encoding="utf-8", errors="replace")
    modal_start = html.index('x-show="previewOpen"')
    outside = html[:modal_start]
    assert 'x-if="attErr"' in outside, (
        "主頁面（modal 外）找不到 `attErr` 的渲染點——\n"
        "上傳／刪除／帶入附件的失敗訊息現在沒有地方顯示。")
    assert 'x-if="attMsg"' in outside, (
        "主頁面（modal 外）找不到 `attMsg` 的渲染點——\n"
        "上傳／刪除／帶入附件的成功訊息現在沒有地方顯示。")
