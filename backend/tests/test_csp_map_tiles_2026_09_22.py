"""CSP 必須讓 OSM 圖磚過，**而且不可以用「全部放行」的方式讓它過**。

## 現況（A 實測，我複核過 `main.py:415-425`）

```
img-src 'self' data: blob:
而 frontend/pages/map.html 用的是
    https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png
```
🔴 ⇒ **按下「開啟地圖」會是一片灰，圖磚全部被 CSP 擋掉。**

## ☠️ 而錯誤訊息會把人導向完全錯誤的方向

B 的 `tileerror` 提示會說「**底圖需要網路連線，這台機器可能沒有對外連線**」——
**那個診斷是錯的**：機器連得出去，是同源政策擋的。

🔑 **一個會講錯原因的錯誤訊息，比沒有訊息更難查** ——
沒有訊息的人會去查；拿到錯訊息的人會去查一件沒有壞的事。

📌 **而那句話在 CSP 修好之後仍然會說謊**，只是改成「CSP 哪天被改回去」的時候。
⇒ **真正擋住它的不是改那句話，是下面第一題本身。**
**一個會講錯原因的錯誤訊息，它的守門不在訊息裡。**

## ⚠️ 觀測點：真的打一次、讀回應標頭

**不讀 `main.py` 的 `_CSP` 字串常數** —— 那是「載入 ≠ 跑到」：
常數改對了而 middleware 沒套上去，讀常數的測試會全綠。
（`main.py:429` 的 `security_headers` 套在**所有回應**上，所以打哪個端點都拿得到。）
"""
import re

import pytest

#: 公開端點，不需要登入 —— 而 CSP 是 middleware 套的，跟有沒有登入無關。
PROBE_PATH = "/api/ping"

TILE_HOST_PATTERN = "tile.openstreetmap.org"

#: `img-src` 原本就有的那三項，**一個都不可以掉**。
REQUIRED_IMG_SOURCES = ("'self'", "data:", "blob:")


def _csp(client):
    r = client.get(PROBE_PATH)
    assert r.status_code == 200, f"{PROBE_PATH} 回 {r.status_code}"
    csp = r.headers.get("Content-Security-Policy")
    assert csp, (
        "回應裡沒有 Content-Security-Policy 標頭 —— "
        "`security_headers` middleware 沒有套上去。\n"
        "⚠️ 這比 `img-src` 寫錯嚴重：整份 CSP 都不存在。"
    )
    return csp


def _img_src(csp):
    m = re.search(r"img-src([^;]*)", csp)
    assert m, f"CSP 裡沒有 `img-src` 指令：{csp!r}"
    return m.group(1).strip()


def test_csp_allows_openstreetmap_tiles(client):
    """🔴 `img-src` 必須允許 OSM 的圖磚主機。

    **單一主機**（`https://tile.openstreetmap.org`，OSM 條款建議的形式）
    或**萬用子網域**（`https://*.tile.openstreetmap.org`，舊形式）都可以，
    但必須有一個 —— 見函式內那段說明：**我第一版把今天的實作細節寫成了不變量。**
    """
    img_src = _img_src(_csp(client))
    assert TILE_HOST_PATTERN in img_src, (
        f"`img-src` 不允許 OSM 圖磚：{img_src!r}\n"
        "⇒ 地圖會是一片灰，而畫面上的提示會說「可能沒有對外連線」——"
        "**那個診斷是錯的**，機器連得出去，是同源政策擋的。"
    )
    # 🔴 **我第一版在這裡埋了一個衝突，自己抓到的。**
    # 原本寫的是「**必須**是萬用字元子網域」（`https://*.tile.openstreetmap.org`）。
    # ⚠️ 而 OSM 的條款說 `{s}` 那種子網域形式是**舊的、隨時可能撤除**，
    #    正確的是單一主機 `https://tile.openstreetmap.org/{z}/{x}/{y}.png`
    # ⇒ B 照條款改掉 URL 之後，CSP 會**收窄**成單一主機名，
    #   而我那個斷言會**紅** —— **紅在一個比原本更好的實作上。**
    #
    # 🔑 **我把「今天的實作細節」寫成了不變量。** 真正的不變量是
    #    「OSM 圖磚過得去，而且沒有放行任何多餘的東西」——
    #    子網域形式是那個不變量今天的長相，不是它本身。
    #   （同一句今晚已經用過一次：釘住「它看起來要跟什麼一樣」，
    #    比釘住「它應該是哪個數字」耐用。）
    wildcard = re.search(r"https://\*\.tile\.openstreetmap\.org", img_src)
    single = re.search(r"https://tile\.openstreetmap\.org", img_src)
    assert wildcard or single, (
        f"`img-src` 裡沒有可用的 OSM 來源：{img_src!r}\n"
        "⇒ 單一主機（`https://tile.openstreetmap.org`，條款建議）"
        "或萬用子網域（`https://*.tile.openstreetmap.org`，舊形式）都可以，"
        "但必須有一個。"
    )


@pytest.mark.parametrize("source", REQUIRED_IMG_SOURCES)
def test_csp_img_src_keeps_its_existing_sources(client, source):
    """`img-src` 原本那三項一個都不可以掉。

    ⚠️ 為圖磚放行時最順手的改法是**整行重寫**，而重寫時漏掉 `blob:`
    會讓 PDF 預覽與簽名圖失效 —— 那**不在地圖頁上**，
    🔑 **所以修地圖的人不會看到自己弄壞了什麼。**
    """
    img_src = _img_src(_csp(client))
    assert source in img_src, (
        f"`img-src` 少了 {source}：{img_src!r}\n"
        "⇒ 那會打掉地圖頁以外的東西（`data:`／`blob:` 用在 PDF 預覽與簽名圖），"
        "而修地圖的人不會看到。"
    )


def test_csp_img_src_is_not_opened_up_to_everything(client):
    """🔴🔴 **`img-src` 不可以變成 `*`。**

    🔑 **沒有這一題，「把 `img-src` 改成 `*`」會讓上面兩題全綠** ——
    而那是最省事也最糟的修法：它讓任何網站的圖片都能被載入，
    而 CSP 存在的理由就是不讓那件事發生。

    ⚠️ 而它的症狀是**沒有症狀**：地圖會動、PDF 會動、一切正常，
    **直到有人用一張外部圖片做追蹤或內容注入。**
    """
    img_src = _img_src(_csp(client))
    tokens = img_src.split()
    assert "*" not in tokens, (
        f"`img-src` 被放寬成 `*`：{img_src!r}\n"
        "⇒ 任何網站的圖片都能載入。這會讓上面兩題全綠而 CSP 形同虛設，"
        "**而且沒有任何症狀** —— 直到有人用外部圖片做追蹤或內容注入。"
    )
    assert "https:" not in tokens, (
        f"`img-src` 被放寬成整個 `https:`：{img_src!r}\n"
        "⇒ 比 `*` 好一點，但仍然是「任何 HTTPS 網站」。要的是那一個網域。"
    )


def test_csp_other_directives_are_not_collateral_damage(client):
    """對照組：**改 `img-src` 不可以順手動到別的指令。**

    ⚠️ 上面三題只看 `img-src` ⇒ 一個「整份 CSP 重寫」的修法可以讓它們全綠，
    **而把 `object-src 'none'` 或 `frame-ancestors 'self'` 弄丟。**
    🔑 **只驗你要改的那一行，等於沒有驗「你只改了那一行」。**
    """
    csp = _csp(client)
    for directive in ("default-src 'self'", "object-src 'none'",
                      "frame-ancestors 'self'", "connect-src 'self'"):
        assert directive in csp, (
            f"CSP 少了 `{directive}`：{csp!r}\n"
            "⇒ 為了讓地圖過而整份重寫時掉的。這幾項跟地圖無關，"
            "所以修地圖的人不會發現。"
        )


# ══════════════════════════════════════════════════════════════════════
# R1～R3 · `Referrer-Policy`：**只為地圖頁放寬，其餘不動**
# ══════════════════════════════════════════════════════════════════════
#
# ## 🔴 真正的根因（A／B 實測，同一 IP 同一時間）
#
#     瀏覽器UA ＋ Referer   →  33,914 bytes  ✅ 真圖磚
#     瀏覽器UA 無 Referer   →   6,987 bytes  ❌ 封鎖圖
#     MOTRIX UA 無 Referer  →  33,923 bytes  ✅ 真圖磚
#
# ⇒ 觸發封鎖的是「**瀏覽器 UA ＋ 沒有 Referer**」這個**組合**。
# 🔴 **而 Referer 是我們自己拿掉的**：`main.py:439` `Referrer-Policy: same-origin`
#    ⇒ 跨網域一律不送 ⇒ OSM 收到一個「像瀏覽器、卻不說自己從哪來」的請求。
#
# OSM 條款逐字禁止這件事：
#     *You must not: Set a restrictive Referrer-Policy that prevents the
#      HTTP Referer header being sent.*
#
# ## ⚠️ 而這裡放寬的是**隱私設定**，所以鑑別力比上一批更重要
#
# 只釘第一題的話，**「整站改成 `unsafe-url`」會讓它綠** ——
# 而那是**把一個全站的隱私設定拆掉，去換一張底圖**。
# 🔑 又是那句：**只驗你要改的那一行，等於沒有驗「你只改了那一行」** ——
# 而這一次改錯方向的代價是**使用者正在看哪一筆標案會被送給第三方**。

MAP_PAGE = "/pages/map.html"
#: 對照頁：任何一個**不是地圖**的頁面都該維持原本的嚴格設定。
CONTROL_PAGE = "/pages/tender-radar.html"

STRICT_DEFAULT = "same-origin"
#: 只送來源（`https://erp.example.com/`），**不送完整路徑**。
RECOMMENDED_FOR_MAP = "strict-origin-when-cross-origin"


def _referrer_policy(client, path):
    r = client.get(path)
    assert r.status_code == 200, f"{path} 回 {r.status_code}"
    value = r.headers.get("Referrer-Policy")
    assert value, f"{path} 的回應沒有 `Referrer-Policy` 標頭"
    return value.strip().lower()


def test_r1_the_map_page_sends_a_referer_to_osm(client):
    """🔴 R1：**地圖頁的 `Referrer-Policy` 不可以是 `same-origin`。**

    `same-origin` ⇒ 跨網域一律不送 Referer ⇒ OSM 收到一個
    「像瀏覽器、卻不說自己從哪來」的請求 ⇒ **回封鎖圖**。
    而那張圖是 **HTTP 200 的合法 PNG** —— 前端沒有任何辦法自己發現。
    """
    policy = _referrer_policy(client, MAP_PAGE)
    assert policy != STRICT_DEFAULT, (
        f"地圖頁的 `Referrer-Policy` 還是 `{STRICT_DEFAULT}` —— "
        "跨網域不送 Referer，而 OSM 會回一張「Access blocked」的圖磚（HTTP 200）。\n"
        "⇒ 建議 `strict-origin-when-cross-origin`：只送來源、不送完整路徑。"
    )


def test_r2_every_other_page_keeps_the_strict_policy(client):
    """🔴 R2：**其餘頁面仍然是 `same-origin`。**

    ⚠️ 那是**全站的隱私設定**，不可以為了一張底圖整站放寬。
    🔑 沒有這一題，「把 middleware 那一行直接改掉」會讓 R1 綠 ——
    **而那會讓每一個頁面都開始對外洩漏它的來源。**
    """
    policy = _referrer_policy(client, CONTROL_PAGE)
    assert policy == STRICT_DEFAULT, (
        f"`{CONTROL_PAGE}` 的 `Referrer-Policy` 變成 {policy!r} —— "
        f"應該仍是 `{STRICT_DEFAULT}`。\n"
        "⇒ 為了地圖而整站放寬，是拿全站的隱私去換一張底圖。"
    )


def test_r2b_api_responses_keep_the_strict_policy(client):
    """R2 的第二個對照：**API 回應也要維持嚴格。**

    ⚠️ 只看頁面的話，一個「對所有 HTML 放寬」的實作會讓 R2 綠。
    📌 而 API 的路徑本身就帶資訊（`/api/quotations/MQ-2026-001`）——
    **那比頁面路徑更敏感。**
    """
    policy = _referrer_policy(client, "/api/ping")
    assert policy == STRICT_DEFAULT, (
        f"API 回應的 `Referrer-Policy` 變成 {policy!r} —— 應該仍是 `{STRICT_DEFAULT}`"
    )


def test_r3_the_map_page_does_not_leak_the_full_path(client):
    """🔴🔴 R3：地圖頁**不可以是 `unsafe-url`**（或任何會送出完整路徑的值）。

    `unsafe-url` 會把**完整網址**送給 OSM —— 包含
    **使用者正在看哪一筆標案**、哪一個案件、哪一個客戶。

    🔑 這一題與 R1 是**同一條線的兩端**：
    R1 要求「送得夠多，讓 OSM 認得我們」，
    **R3 要求「送得夠少，不要把使用者在看什麼也一起送出去」。**
    ⚠️ 只有 R1 的話，最省事的修法（`unsafe-url`）會通過 ——
    **而它把一個隱私問題換成一個更大的隱私問題。**
    """
    policy = _referrer_policy(client, MAP_PAGE)
    forbidden = {"unsafe-url", "no-referrer-when-downgrade", "origin-when-cross-origin"}
    assert policy not in forbidden, (
        f"地圖頁的 `Referrer-Policy` 是 {policy!r} —— 它會送出**完整路徑**。\n"
        "⇒ OSM 會知道使用者正在看哪一筆標案。要的是只送來源："
        f"`{RECOMMENDED_FOR_MAP}`。"
    )
    assert "origin" in policy, (
        f"地圖頁的 `Referrer-Policy` 是 {policy!r} —— "
        f"看起來既不送來源也不安全。建議 `{RECOMMENDED_FOR_MAP}`。"
    )
