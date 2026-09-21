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
    """🔴 `img-src` 必須允許 `https://*.tile.openstreetmap.org`。

    ⚠️ **必須是萬用字元子網域**，不是單一主機名：
    Leaflet 的 `{s}` 會在 `a`／`b`／`c` 之間輪替
    ⇒ 釘單一主機名的話，**寫對了你看不出來，寫錯了你也抓不到**
    （`a.tile...` 過了而 `b.tile...` 被擋 ⇒ 地圖**一部分**是灰的，
    而那看起來像網路不穩）。
    """
    img_src = _img_src(_csp(client))
    assert TILE_HOST_PATTERN in img_src, (
        f"`img-src` 不允許 OSM 圖磚：{img_src!r}\n"
        "⇒ 地圖會是一片灰，而畫面上的提示會說「可能沒有對外連線」——"
        "**那個診斷是錯的**，機器連得出去，是同源政策擋的。"
    )
    assert re.search(r"https://\*\.tile\.openstreetmap\.org", img_src), (
        f"`img-src` 裡的 OSM 來源不是萬用字元子網域：{img_src!r}\n"
        "⚠️ Leaflet 的 `{s}` 會輪替 a/b/c ⇒ 釘單一主機名的話，"
        "地圖會有一部分是灰的，而那看起來像網路不穩。"
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
