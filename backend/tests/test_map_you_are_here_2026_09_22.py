"""§3u 第二節 · 「你在這裡」要畫在地圖上（UB1–UB5）。

> **使用者回報：按了「使用我的位置」，而地圖上沒有出現我。**

---

# 🔴 現況（A 查出、我逐行複核過 `frontend/pages/map.html`）

```
:461   usePosition()  把座標存進 userPos
:494   送出時放進 X-Map-Position 標頭
:431   userAccuracyM 只餵「離你多遠」那一欄
:548   this._map.setView(centre, ...)        ← 視野裡沒有「你」
:563   L.marker([office.lat, office.lon])    ← 只畫辦公室
:577   L.marker([p.lat, p.lon], { icon })    ← 只畫各資料集的點
```
⇒ **`userPos` 從來沒有被畫上去。**

📌 A 自己認的那一句值得留著：
> **§3n 的規格只寫了「距離」沒寫「標記」** ——
> **從使用者的角度那是同一件事，從規格的角度是兩件，而我只寫了其中一件。**

---

# ⚠️ 這一節我驗得到什麼、驗不到什麼

**UB1–UB5 全部是 Leaflet 的渲染行為**，後端一行都碰不到。
⇒ 我只做得到**樣板的結構檢查**，而它：

| 擋得住 | 擋不住 |
|---|---|
| **根本沒做**（今天就是這個狀態） | 做了但畫錯位置／顏色沒區別／圓的半徑算錯 |
| 之後有人把它整段刪掉 | 之後有人把它改壞但關鍵字還在 |

🔑 **它答的是「有沒有被寫出來」，不是「有沒有被渲染成那樣」。**
（今天我已經因為同一種工具誤報過一次 —— U5c 把註解裡的 `DROP TABLE` 當真，
而 R10b 的錨點抓到呼叫端不是定義。）

📌 **真正的驗收是目視，而且只有正式機驗得完整**：
開發機是 HTTP ⇒ **瀏覽器只在 `localhost` 給定位權限**。
⚠️ 我**沒有**把 UB1–UB5 放進規格覆蓋率守門的 `EXEMPT` ——
它們有題，放進去就會多出一列**指不到東西的豁免**，而那種列讀起來像一個決定。
**「真正的驗收是目視」這句話寫在這裡，不寫在豁免表裡。**
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

PAGE = (Path(__file__).resolve().parent.parent.parent
        / "frontend" / "pages" / "map.html")


@pytest.fixture(scope="module")
def page():
    assert PAGE.exists(), f"找不到 {PAGE}"
    return PAGE.read_text(encoding="utf-8")


def _draw_section(text):
    """畫圖那一段（從建立地圖到函式結尾）。

    ⚠️ 錨在 `setView` 而不是整份檔案 —— 整份檔案找得到 `userPos`
    （它在按鈕、在標頭、在距離欄），**而那些都不是「畫在地圖上」**。
    🔑 判準要挑得到「被執行的那一份」：R10b 今天就是錨錯了位置。
    """
    i = text.find("setView")
    assert i >= 0, "`map.html` 裡找不到 `setView` —— 這個檔的結構變了"
    return text[i:i + 3000]


# ══════════════════════════════════════════════════════════════════════
# UB1 / UB3 · 畫一個「你在這裡」，而且和別的點不一樣
# ══════════════════════════════════════════════════════════════════════

def test_ub1_the_user_position_is_drawn_on_the_map(page):
    """🟡 UB1：地圖上要畫一個「你在這裡」的標記。

    ⚠️ 結構檢查（見檔頭）。它擋得住的是**今天這個狀態：根本沒畫**。
    📌 錨在畫圖那一段 —— 整份檔案找得到 `userPos`（按鈕／標頭／距離欄），
    而那些都不是「畫在地圖上」。
    """
    section = _draw_section(page)
    assert re.search(r"userPos", section), (
        "畫圖那一段裡完全沒有用到 `userPos` ——\n"
        "⇒ 使用者按了「使用我的位置」，而地圖上不會出現他。\n"
        "（`userPos` 目前只餵「離你多遠」那一欄。）"
    )


def test_ub1b_the_user_marker_is_visually_distinct(page):
    """🟡 UB1b：「你」要和其他資料集的點**明顯不同**，不可以只差一個字。

    ☠️ 一張圖上有標案、客戶、供應商、辦公室、以及「你」——
    全部長一樣的話，**多畫一個點等於沒有畫**：使用者找不到自己。
    📌 判準刻意寬：接受**自訂圖示**或**不同顏色的圓**其中之一，
    ⚠️ 不釘顏色也不釘圖示檔名（那是設計，不是不變量）。
    """
    section = _draw_section(page)
    has_user = "userPos" in section
    assert has_user, "前提不成立：畫圖那一段裡沒有 `userPos`（見 UB1）"

    idx = section.find("userPos")
    window = section[max(0, idx - 300):idx + 600]
    distinct = any(k in window for k in
                   ("icon", "divIcon", "circleMarker", "color", "className"))
    assert distinct, (
        "「你在這裡」用的是預設標記，跟其他點長得一樣：\n"
        f"{window[:220]}\n"
        "⇒ 一張圖上有標案／客戶／供應商／辦公室，全部同一個圖釘的話，"
        "**多畫一個等於沒有畫**。"
    )


# ══════════════════════════════════════════════════════════════════════
# UB2 · 精度圓
# ══════════════════════════════════════════════════════════════════════

def test_ub2_an_accuracy_circle_is_drawn_with_the_real_radius(page):
    """🔴 UB2：要畫出**精度圓**，半徑用 `accuracy`（公尺）。

    🔑 **這是 §3n「距離與誤差綁在一起」在地圖上的版本。**
    ☠️ 一個圖釘不帶它的誤差，就會被當成「**我就在這裡**」——
    而桌機用 IP 定位時，那個誤差可能是**數十公里**。
    📌 今晚第五次同一件事：**一個位置資訊不帶它的可信度，就會被當成事實。**

    ⚠️ 半徑要用**真的那個數字**，不可以寫死一個好看的圈 ——
    寫死的話它就變成裝飾，而**裝飾比沒有更糟**（它宣稱了一個精度）。
    """
    section = _draw_section(page)
    assert "circle" in section.lower(), (
        "畫圖那一段裡沒有任何圓（`L.circle`／`circleMarker`）——\n"
        "⇒ 沒有精度圓，那個圖釘會被當成「我就在這裡」。"
    )
    idx = section.lower().find("circle")
    window = section[idx:idx + 400]
    assert "accuracy" in window, (
        f"畫了圓，而半徑沒有用到 `accuracy`：\n{window[:220]}\n"
        "⇒ 寫死半徑的圓是裝飾，而它宣稱了一個不是量出來的精度。"
    )


# ══════════════════════════════════════════════════════════════════════
# UB4 · 取消定位要清乾淨
# ══════════════════════════════════════════════════════════════════════

def test_ub4_clearing_the_position_removes_what_was_drawn(page):
    """🔴 UB4 反向控制：**取消定位 ⇒ 標記與精度圓都要消失。**

    ☠️ 少了這一題，一個「**畫上去就不再清除**」的實作會讓 UB1／UB2 全綠 ——
    而畫面上會留著一個**上一次的位置**，使用者以為那是現在的自己。
    🔑 〈降級之後它還是會動〉：它不會報錯，只是那個點是舊的。

    📌 錨在 `clearPosition` 的**定義**（不是按鈕上的呼叫）。
    """
    m = re.search(r"clearPosition\s*\([^)]*\)\s*\{", page)
    assert m, "`map.html` 裡找不到 `clearPosition()` 的定義"
    body = page[m.end():m.end() + 600]
    assert re.search(r"remove|clearLayers|removeLayer", body), (
        f"`clearPosition()` 沒有把畫上去的東西移除：\n{body[:220]}\n"
        "⇒ 取消定位之後，上一次的位置還留在圖上。"
    )


# ══════════════════════════════════════════════════════════════════════
# UB5 · 初始視野要看得到「你」
# ══════════════════════════════════════════════════════════════════════

def test_ub5_the_initial_view_includes_the_user(page):
    """🔴 UB5：地圖的初始視野要把「你」也框進去。

    🔑 **畫出來與看得到是兩件事。**
    ☠️ 現況是 `setView(centre, 8)` —— 一個固定的中心與縮放。
    使用者在高雄而辦公室在台中的話，**那個標記在畫面外**，
    而他會以為「按了沒反應」——**跟 UB1 的症狀一模一樣，而成因完全不同。**

    📌 判準：有 `fitBounds`（或等價的把多個點框起來的做法）。
    ⚠️ 不釘 padding／maxZoom 那些參數 —— 那是調校，不是不變量。
    """
    section = _draw_section(page)
    assert "fitBounds" in section or "flyToBounds" in section, (
        "地圖仍然用固定的 `setView(centre, …)` ——\n"
        "⇒ 使用者的位置可能落在畫面外，而症狀是「按了沒反應」，"
        "跟「根本沒畫」長得一模一樣。"
    )


# ══════════════════════════════════════════════════════════════════════
# 量尺：先證明這個檔真的讀得到東西
# ══════════════════════════════════════════════════════════════════════

def test_ub0_the_page_and_the_anchor_are_both_findable(page):
    """🔴 量尺：**先證明錨點抓得到東西。**

    ⚠️ `map.html` 改名、`setView` 被換掉、或檔案讀成空字串時，
    上面每一題都會**安靜地變好過**或以奇怪的方式紅。
    🔑 今天 R10b 就是錨錯位置 ——**錨點本身要有人驗。**
    """
    assert len(page) > 5000, f"`map.html` 只有 {len(page)} 字元 —— 讀錯檔了？"
    section = _draw_section(page)
    assert len(section) > 500, "畫圖那一段太短，錨點大概抓錯位置了"
    assert "L.marker" in section or "marker(" in section, (
        "畫圖那一段裡沒有任何 `marker` —— 那就不是畫圖的那一段"
    )


def test_ub3_the_user_marker_is_not_only_in_the_list_column(page):
    """🔴 UB3：**地圖展開之後要看得到「你」** —— 不可以只存在於清單那一欄。

    ☠️ 現況正是這個：`userAccuracyM` 只餵「離你多遠」那一欄（`map.html:431`），
    而地圖上沒有任何東西代表使用者。
    🔑 **「有這個資料」與「看得到它」是兩件事**，
    而使用者按下按鈕之後看的是**地圖**不是表格那一欄。

    📌 這一題與 UB1 的差別：UB1 驗「有沒有畫」，這一題驗
    **「畫的那一段跟清單那一段不是同一段」** —— 也就是它真的進了地圖圖層。
    """
    section = _draw_section(page)
    assert "userPos" in section, (
        "畫圖那一段裡沒有 `userPos` —— 它只存在於清單／標頭那一側。\n"
        "⇒ 使用者按下按鈕之後看的是地圖，不是表格那一欄。"
    )
    assert "addTo" in section[section.find("userPos"):
                              section.find("userPos") + 500], (
        "`userPos` 出現在畫圖那一段，但沒有 `addTo(...)` ——\n"
        "⇒ 算出來了而沒有加進地圖圖層。"
    )
