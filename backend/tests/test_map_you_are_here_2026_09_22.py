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


#: JS 裡長得像「函式名(引數) {」但其實是控制結構的字。
_JS_KEYWORDS = frozenset({"if", "for", "while", "switch", "catch",
                          "with", "function", "return", "else", "do"})

_METHOD_HEAD = re.compile(r"([A-Za-z_$][\w$]*)\s*\([^()]*\)\s*$")


def _strip_js_comments(src):
    """把 `//` 與 `/* */` 換成等長的空白（位移不變，行號還對得上）。

    ⚠️ 字串與樣板字面值裡的 `//` 不算註解，所以引號要先吃掉。
    """
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c in "'\"`":
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            out.append(src[i:j + 1])
            i = j + 1
        elif src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(" " * (j - i))
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _methods(src):
    """`{方法名: 方法本體}` —— 用大括號配對切，不是用行數或字元數切。"""
    found = {}
    depth_stack = []
    for k, ch in enumerate(src):
        if ch == "{":
            head = src[max(0, k - 90):k]
            m = _METHOD_HEAD.search(head)
            name = m.group(1) if m and m.group(1) not in _JS_KEYWORDS else None
            depth_stack.append((name, k))
        elif ch == "}" and depth_stack:
            name, start = depth_stack.pop()
            if name and name not in found:
                found[name] = src[start:k + 1]
    return found


def _draw_section(text):
    """畫圖那一段 ＝ **所有會動到 `this._map` 的方法，串起來**。

    ## 🔴 2026-09-22 FX9（A 裁）：錨點從「字元窗」換成「函式邊界」

    原本是 `text.find("setView")` 往後數 **3000 字元**。
    ☠️ **那道判準卡了 B 五次，而每一次它都是靠搬動程式碼的位置變綠的。**
    > B 的原話：**「我每一次都是靠搬動程式碼的位置來讓它綠 —— 那是我在遷就判準。」**

    🔑 A 的裁定：**判準要能回答「這一段屬於哪個函式」，
    而不是「它離某個字串多遠」** ——
    ☠️ 後者會在**任何人加一段註解**的時候改變答案，**而註解不改變行為**。
    📌 **一個會被註解長度左右的守門，量的是排版不是行為。**

    ## ☠️ 而我實測發現它比「脆」更糟：**它當時錨在一段註解上**

    ```
    map.html:694   // `_draw_section()` 錨在 `setView` 往後數 3000 字元，
    map.html:698   this._map = window.L.map('mp-canvas').setView(...)
    ```
    `text.find("setView")` 命中的是**第 694 行那句註解**，不是第 698 行的呼叫。
    ⇒ 那個 3000 字元的窗是從一句「解釋這個判準很脆」的註解開始數的。

    ## 📌 而它給的是**假綠燈**：`userPos` 根本不在 `_draw()` 裡

    實測（把註解剝掉、用大括號配對切）：
    ```
    _draw      建立地圖、setView            ← 沒有 userPos
    _drawUser  畫「你在這裡」               ← userPos 在這裡
    _fitAll    fitBounds                    ← 也有 userPos
    ```
    ⇒ 舊判準會綠，**是因為那 3000 字元跨過了方法邊界**，
    🔑 **不是因為它驗到了「使用者的位置被畫在地圖上」。**

    ## 🔑 新判準是一個**性質**，不是一份名單

    「會動到 `this._map` 的方法」⇒ B 改方法名不會讓題目壞掉
    （`invalidateSize` → `_syncMapSize` 那次就是被名字咬到的），
    ⚠️ 而把 `userPos` 搬到一個不碰地圖的按鈕處理器裡 ⇒ **題目會紅**，
    **而那正是這幾題要擋的事。**

    ## ⚠️ 只留**最內層**的那些，而這一條是我自己的反向控制抓到的

    第一版寫成「所有含 `this._map` 的方法」⇒ ☠️ **最外層的 `mapPage()`
    把整個元件都包在裡面，它當然含 `this._map`** ⇒ 聯集等於整份檔案
    ⇒ **判準又變回 grep 了**，而 UB1 會再一次假綠。
    🔑 〈判準的寬窄都會騙人〉：**我在修一個太寬的判準時，寫出了一個更寬的。**
    📌 抓到它的是這個檔最底下那題（搬到不碰地圖的方法裡要看不見）——
    **一個反向控制在它保護的東西被改寫時，當場發揮了作用。**
    """
    clean = _strip_js_comments(text)
    hits = {name: body for name, body in _methods(clean).items()
            if "this._map" in body}
    # ⚠️ 丟掉的是**外層**：一個方法若把另一個命中的方法整個包在裡面，
    #    它就不是「畫圖的那一段」，它是「裝著畫圖那幾段的容器」。
    # ☠️ 我第一版把條件寫反（丟掉內層）⇒ 只剩最外層的 `mapPage()`
    #    ⇒ 判準等於整份檔案，而三題當場紅了 —— **反向控制又抓到一次。**
    bodies = [body for name, body in hits.items()
              if not any(other is not body and other in body
                         for other in hits.values())]
    assert bodies, (
        "`map.html` 裡找不到任何會動到 `this._map` 的方法 —— 這個檔的結構變了。\n"
        "☠️ 一個切不出東西的切法，會讓下面每一題**安靜地紅**，"
        "而紅的理由跟它們要驗的事無關。"
    )
    return "\n".join(bodies)


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


# ══════════════════════════════════════════════════════════════════════
# FX9 的反向控制 · A 明著要求的兩個方向（⏳ 這裡需要一個編號）
# ══════════════════════════════════════════════════════════════════════
#
# A 的裁定原話：
# > 「在 `_fitAll()` **裡面**加一段長註解 ⇒ 題目仍然要綠；
# >   把 `fitBounds` 搬到 `_fitAll()` **外面** ⇒ 題目要紅。」
#
# 📌 兩個方向都要，而且要用**合成**的頁面 ——
# 拿真的 `map.html` 去試，只能試「它現在是什麼樣」。

_FAKE_PAGE = """
<script>
function mapPage() {
  return {
    _draw() {
      this._map = window.L.map('c').setView([0, 0], 7)
%(comment)s
      this._drawUser()
    },
    _drawUser() {
      %(user_line)s
    },
    _elsewhere() {
      %(other_line)s
    },
  }
}
</script>
"""


def _fake(comment="", user_line="const x = 1", other_line="const y = 2"):
    return _FAKE_PAGE % {"comment": comment, "user_line": user_line,
                         "other_line": other_line}


def test_a_long_comment_inside_the_method_does_not_move_the_boundary():
    """📏 **方向一：在方法裡面塞 5,000 字的註解 ⇒ 判準不受影響。**

    ☠️ 舊的 3000 字元窗在這裡會直接失效 —— 註解把程式碼擠出窗外。
    🔑 **而註解不改變行為**，所以一個被註解長度左右的判準，量的是排版。
    """
    long_comment = "\n".join("      // " + "x" * 60 for _ in range(90))
    section = _draw_section(_fake(
        comment=long_comment,
        user_line="this._map.addLayer(userPos)"))
    assert "userPos" in section, (
        "一段長註解把 `userPos` 擠出判準範圍了 —— 那正是 FX9 要修掉的毛病。"
    )
    assert len(long_comment) > 3000, (
        f"這個量尺自己失效了：註解只有 {len(long_comment)} 字元，"
        "撐不破舊的 3000 字元窗 ⇒ 上面那個斷言證明不了任何事。"
    )


def test_code_moved_out_of_a_map_touching_method_falls_outside():
    """📏 **方向二：搬到一個不碰地圖的方法裡 ⇒ 判準看不見它（該紅）。**

    🔑 這一半才是這道守門的價值：
    ☠️ `userPos` 出現在按鈕處理器、標頭、距離欄裡**都不算「畫在地圖上」**，
    而整份檔案 `grep userPos` 一定找得到 —— **那就是判準太寬的樣子。**
    """
    inside = _draw_section(_fake(user_line="this._map.addLayer(userPos)"))
    assert "userPos" in inside, "前提不成立：放在碰地圖的方法裡應該要看得見"

    outside = _draw_section(_fake(
        user_line="this._map.addLayer(marker)",
        other_line="console.log(userPos)"))
    assert "userPos" not in outside, (
        "`userPos` 搬到一個不碰 `this._map` 的方法裡，判準卻還看得見它 ——\n"
        "⇒ 那道判準等於在 grep 整份檔案。"
    )


def test_the_boundary_finder_ignores_control_structures():
    """📏 `if (...) {` 長得像「函式名(引數) {」—— 不可以被當成一個方法。

    ⚠️ 我的原型第一版就把 `fitBounds` 的外層算成一個叫 `if` 的「方法」，
    ☠️ 而那會讓判準切出一個只有 176 字元的片段，**比整個方法小得多**。
    🔑 〈判準的寬窄都會騙人〉的窄那一側：切得太小 ⇒ 什麼都找不到 ⇒ 全紅，
    而全紅的理由跟題目要驗的事無關。
    """
    src = _strip_js_comments(_fake(user_line="if (a) { this._map.pan(userPos) }"))
    names = set(_methods(src))
    assert "if" not in names, f"控制結構被當成方法了：{sorted(names)}"
    assert {"_draw", "_drawUser", "_elsewhere"} <= names, (
        f"真正的方法沒有被切出來：{sorted(names)}"
    )
