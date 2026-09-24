# -*- coding: utf-8 -*-
"""`JV25` · `JV19` 修好「訊息看不到」之後，換來「預覽本體看不清楚」。

使用者原話：「傳票預覽的顯示高度過小」。

# 🔴 這是 `JV19` 的副作用，不是新缺陷

```
JV19 之前  .vc-preview-frame{height:72vh}（固定值）
           => 附件清單與訊息被擠到可視範圍外（JV19 回報的那個洞）
JV19 之後  B 改成 flex：.vc-preview-frame{flex:1 1 auto;min-height:220px}
           .vc-preview-atts{flex:0 0 auto}（附件清單「優先拿到自己需要的高度」）
           => 🔴 附件一多，iframe 被壓到只剩 min-height 那條底線
```
📌〈防護的副作用落在盲側〉：修好了「看不到訊息」，換來「看不清楚內容」——
訊息（`attErr`／`attMsg`）與附件清單目前都擠在 `.vc-preview-atts` 裡，
與 iframe 搶的是**同一份**由 `.modal-body{flex:1;overflow-y:auto}`
（`style.css:1497`）分配下來的高度，而 `.modal-box{max-height:calc(100dvh
- 2rem)}` 只在內容真的多到超過視窗時才會讓這個競爭浮現。

# ⚙️ 動工前先重現（照抄 `JV19` 的方法論：先量真實座標，不是先猜）

```
1280×800 視窗，Playwright 實測 `.modal-body`／`[data-testid=
"voucher-preview-frame"]` 的 getBoundingClientRect()：

  0 附件   boxHeight=337.6  frameHeight=219.1  ratio=0.649
  1 附件   boxHeight=328.4  frameHeight=220.0  ratio=0.670
  10 附件  boxHeight=607.0  frameHeight=216.7  ratio=0.357   <= 明顯退化
  10 附件＋按下匯出、失敗訊息出現：
           boxHeight=616.4  frameHeight=220.0  ratio=0.357   <= 訊息出現前後幾乎不變
```
🔑 真正的成因不是「附件擠壓 iframe 的瞬間」，是 **iframe 本身從來沒有
真的用 `flex-grow` 拿到超過 `min-height:220px` 的空間**——只有當
`.modal-body` 被 `.modal-box` 的 `max-height` 頂住、被迫內部捲動時，
`.vc-preview-atts`（不會縮）與 iframe（會縮到底線）搶固定空間的效果
才會顯現：附件越多，`.modal-body` 越早撞頂，iframe 掉到底線的情況
越明顯——這與使用者「顯示高度過小」的觀察一致。

⚠️ 而「訊息出現時才縮」這個坑，實測**目前不成立**（見上面第 4 組
數字，比例前後幾乎沒變）——iframe 在有訊息與沒訊息時都已經在
`min-height` 底線，沒有額外可縮的空間了。本檔仍然把它寫成一個
負對照（guard），防的是修法本身引入這個新坑（例如改成「有訊息時才
把 iframe 高度砍半讓訊息一定看得到」這種條件式高度）。

# 🔑 對照組：`JV19` 的三題不可以退回

`JV19`（`test_voucher_preview_export_feedback_2026_09_23.py`）釘的是
「訊息看不看得到」，本檔釘的是「iframe 看不看得清楚」——**同一塊版面
的兩個維度**，修 `JV25` 時若把訊息搬回固定位置卻又讓它重新蓋住/裁切
iframe，或反過來為了讓 iframe 變大而把訊息擠出可視範圍，兩份題**都要
跑過**才算真的修好，不是其中一份綠了就結案。
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

from test_voucher_preview_export_feedback_2026_09_23 import (  # noqa: E402
    live_server, _login, _create_voucher, _open_preview,
)

#: A 給的例子——今天量到的最壞情況只有 0.357，離這個門檻還差一截。
_MIN_RATIO = 0.6

#: 附件從 1 筆到 10 筆，比例不可以掉超過這個量——這是「真正要防的」那一格
#: （A 原話：高度不可以跟著附件數量走），比死釘一個絕對門檻更耐用。
_MAX_RATIO_DROP = 0.15



def _rendered(page):
    """PERF #6：等 Alpine 把這次狀態變化畫完（nextTick）＋瀏覽器實際畫出兩個影格。
    ⚠️ 只適用於沒有 CSS transition 的元素（有 transition 的要等轉場落定）。"""
    page.evaluate("() => new Promise(r => (window.Alpine ? Alpine.nextTick : (f => f()))(() => requestAnimationFrame(() => requestAnimationFrame(r))))")

def _upload_n(page, live_server, token, vid, n):
    for i in range(n):
        r = page.request.post(
            f"{live_server}/api/vouchers/{vid}/attachments",
            headers={"Authorization": "Bearer " + token},
            multipart={"files": {
                "name": "jv25-%d.pdf" % i,
                "mimeType": "application/pdf",
                "buffer": b"%PDF-1.4 jv25",
            }})
        assert r.ok, r.text()


def _settled(page, timeout_ms=3000):
    """等到 iframe 高度**連續兩次量到一樣**才回傳那一次的量測。

    🔴 2026-09-24（hichan-61）：`.modal-overlay` 有 `x-transition`（開啟時縮放動畫），
       而 `getBoundingClientRect()` **算進 transform** ⇒ 開啟後立刻量，量到的是
       動畫中途縮小的框（實測 374.2 ≈ 380 × 0.985）。「按下匯出前後差 5.8px」
       其實是「動畫前後」，不是「訊息前後」—— 探針與被測對象糾纏。
    ⚠️ 不用固定 sleep：固定等待在慢機器上照樣會量到動畫中途。
    """
    last = None
    waited = 0
    while waited <= timeout_ms:
        cur = _measure(page)
        if last and cur.get("found") and abs(cur["frameHeight"] - last["frameHeight"]) < 0.1:
            return cur
        last = cur
        page.wait_for_timeout(150)
        waited += 150
    return last


def _measure(page):
    """`.modal-body`／iframe 的實際幾何高度。`found=False` 代表選擇器不對，
    不是「比例不夠」——呼叫端要先斷言 `found`，免得比例斷言紅在錯的原因上。
    """
    return page.evaluate(
        """() => {
            const box = document.querySelector('.modal-body')
            const frame = document.querySelector(
                '[data-testid="voucher-preview-frame"]')
            if (!box || !frame) return {found: false}
            const br = box.getBoundingClientRect()
            const fr = frame.getBoundingClientRect()
            return {found: true, boxHeight: br.height,
                    frameHeight: fr.height, ratio: fr.height / br.height}
        }""")


# ══════════════════════════════════════════════════════════════════════
# ① 核心：附件很多時，iframe 不可以被壓到只剩底線
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.e2e
def test_jv25_iframe_keeps_a_healthy_share_of_height_with_many_attachments(
        live_server, make_user):
    """🔴🔴 **核心：10 筆附件時，iframe 高度仍要佔 `.modal-body` 六成以上。**

    ⚙️ 已實測重現（見檔頭）：10 筆附件時 `ratio=0.357`，遠低於這個門檻——
    附件清單把 `.modal-body` 撐到撞上 `.modal-box` 的 `max-height`，
    iframe 被壓到只剩 `min-height:220px` 那條底線。
    """
    username, password = make_user(username="jv25_many", role="superadmin",
                                   modules=["cashier"])
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        try:
            _login(page, live_server, username, password)
            token = page.evaluate(
                "() => JSON.parse(localStorage.getItem('motrix_session'))"
                ".token")
            vid = _create_voucher(page, live_server, token)
            _upload_n(page, live_server, token, vid, 10)
            _open_preview(page, live_server, token, vid)

            m = _measure(page)
            assert m.get("found"), "量不到 `.modal-body` 或預覽 iframe——退回改選擇器。"
            assert m["ratio"] >= _MIN_RATIO, (
                "10 筆附件時，iframe 只佔 `.modal-body` 高度的 %.1f%%"
                "（門檻 %.0f%%）：%r\n" % (m["ratio"] * 100, _MIN_RATIO * 100, m)
                + "☠️ 使用者要預覽一張傳票，畫面上留給它的空間只剩一條窄縫。")
        finally:
            browser.close()


# ══════════════════════════════════════════════════════════════════════
# ② 真正要防的：比例不可以隨附件數量惡化
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.e2e
def test_jv25_the_ratio_does_not_degrade_as_attachment_count_grows(
        live_server, make_user):
    """🔴🔴 **附件從 1 筆長到 10 筆，iframe 佔比不可以掉超過 %.0f 個百分點。**

    🔑 這一題比上一題更耐用——不管修法把絕對比例調到多高，都不可以是
    「附件少的時候比例正常、附件一多就崩」這種**看資料量決定表現**的
    修法。A 原話：「高度不可以跟著附件數量走」。
    """ % (_MAX_RATIO_DROP * 100)
    username, password = make_user(username="jv25_stable", role="superadmin",
                                   modules=["cashier"])
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        try:
            _login(page, live_server, username, password)
            token = page.evaluate(
                "() => JSON.parse(localStorage.getItem('motrix_session'))"
                ".token")

            v_few = _create_voucher(page, live_server, token)
            _upload_n(page, live_server, token, v_few, 1)
            _open_preview(page, live_server, token, v_few)
            few = _measure(page)
            assert few.get("found"), "量不到（少附件那組）——退回改選擇器。"

            v_many = _create_voucher(page, live_server, token)
            _upload_n(page, live_server, token, v_many, 10)
            _open_preview(page, live_server, token, v_many)
            many = _measure(page)
            assert many.get("found"), "量不到（多附件那組）——退回改選擇器。"

            drop = few["ratio"] - many["ratio"]
            assert drop <= _MAX_RATIO_DROP, (
                "附件從 1 筆長到 10 筆，iframe 佔比從 %.1f%% 掉到 %.1f%%"
                "（掉了 %.1f 個百分點，門檻 %.0f）：\n少附件=%r\n多附件=%r\n"
                % (few["ratio"] * 100, many["ratio"] * 100, drop * 100,
                   _MAX_RATIO_DROP * 100, few, many)
                + "☠️ 這代表 iframe 的可視大小取決於**這張傳票剛好有幾筆附件**，\n"
                  "   不是一個穩定的版面。")
        finally:
            browser.close()


# ══════════════════════════════════════════════════════════════════════
# ③ 負對照：iframe 高度不可以隨訊息有無而跳動
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.e2e
def test_jv25_iframe_height_is_stable_before_and_after_the_export_message_appears(
        live_server, make_user):
    """🔴🔴 **匯出訊息出現前後，iframe 高度不可以變——釘「不變」，不是「差 ≤5px」。**

    # 🔴 2026-09-23 改判準：門檻是會被調的數字，「不變」是不變量

    這題原本寫成 `diff <= 5`（負對照，當時實測沒問題）。全量重跑後
    量到 10 附件情境下 `374.2 → 380.0`（差 5.8px），若只是把門檻鬆到
    6，下一次換一個稍高一點的訊息還是會撞，而且沒有人會記得今天這輪
    ——使用者原話是「傳票預覽的顯示高度過小」，任何讓 iframe 跳動或
    縮小的修法都是在反向修正他抱怨過的那件事，所以正確的判準是**高度
    根本不該因為這則訊息而改變**，不是「改變量要小一點」。

    ## ⚙️ 機制（已定位，寫給修的人看）

    ```
    attErr 是 x-if（不是 x-show）⇒ 匯出失敗時**新插入**一個 .vc-err 節點
    到 .vc-preview-atts 裡；10 個附件已經把 .__rows 撐到 max-height:130px
    .vc-preview-atts{flex:0 0 auto}    照單全收新增高度（+63px）
    .vc-preview-frame{flex:1 1 auto;min-height:380px}  是唯一的彈性項
      ⇒ 正常 flex 分配下它該縮，但縮不過 min-height:380px 這條線，
        於是被頂住往上長到剛好 380（本例是 374.2 → 380.0）
    ```
    ⚠️ 而按下去之前的 374.2 本身已經低於 iframe 自己的 `min-height:380px`
    ——這件事目前沒有追下去，**修完之後若它還在，代表修的不是同一件事**。

    🔑 這題現在**應該是紅的**，直到訊息被移出這個 flex 競爭（例如疊在
    iframe 上方不占版位）或 `.vc-preview-atts` 也被限制高度為止——負對照
    的角色已經被下面 `test_jv25_...` 這支正式接手，本題轉正成**核心題**。
    """
    username, password = make_user(username="jv25_jump", role="superadmin",
                                   modules=["cashier"])
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        try:
            _login(page, live_server, username, password)
            token = page.evaluate(
                "() => JSON.parse(localStorage.getItem('motrix_session'))"
                ".token")
            vid = _create_voucher(page, live_server, token)
            _upload_n(page, live_server, token, vid, 10)
            _open_preview(page, live_server, token, vid)

            before = _settled(page)
            assert before.get("found"), "量不到（按匯出前）——退回改選擇器。"

            page.click('.modal-foot button:has-text("匯出 PDF")'
                      ':not(:has-text("含附件"))')
            # PERF #6：原本固定等 800ms ⇒ 等匯出開始又結束（exporting 由 true 回到 false）
            page.wait_for_function("() => !Alpine.$data(document.querySelector('[x-data]')).exporting", timeout=30000)
            _rendered(page)

            after = _settled(page)
            assert after.get("found"), "量不到（按匯出後）——退回改選擇器。"
            # ⚙️ 量尺：訊息**真的出現了**。少了這一行，匯出若沒有產生任何訊息，
            #    「高度不變」就是在比較兩個一模一樣的畫面（空綠）。
            n_msg = page.locator(".vc-preview-atts .vc-err, .vc-preview-atts .vc-ok").count()
            assert n_msg >= 1, "按下匯出之後 modal 裡沒有出現任何訊息 —— 這一題量不到它要量的東西"

            diff = abs(after["frameHeight"] - before["frameHeight"])
            # ⚠️ 不用 0：容忍次像素的浮點捲動誤差（<1px），但不放寬到
            #    足以蓋掉這次量到的 5.8px 真實跳動。
            assert diff < 1, (
                "按下匯出、失敗訊息出現前後，iframe 高度從 %.1f 變成 %.1f"
                "（差 %.1f px）：\n" % (before["frameHeight"],
                                     after["frameHeight"], diff)
                + "☠️ 使用者正在看那張紙，畫面在按下去的瞬間跳動——\n"
                + "   這正是他原話「顯示高度過小」的反面案例：\n"
                + "   `.vc-preview-atts`（flex:0 0 auto，照單全收訊息高度）\n"
                + "   與 `.vc-preview-frame`（flex:1 1 auto;min-height:380px）\n"
                + "   搶同一份 `.modal-body` 配額，訊息一出現配額就被擠壓，\n"
                + "   而 iframe 撞到自己的 min-height 只能被頂著長大。")
        finally:
            browser.close()
