"""§3x · 地圖標記不見了：Leaflet 認為地圖是 `0 × 0`（XA1–XA4）。

> **使用者貼了截圖：「這邊要顯示旗示標註位置」，而 177 個可定位的點，
> 圖上一個標記都沒有。**（畫面上的紫線是 OSM 自己的行政界線。）

---

# 🔴 根因（A 在瀏覽器實測，真的用滑鼠點按鈕）

```
m.getSize()    →  0 × 0
container      →  1206 × 460
m.getBounds()  →  "120.7187,23.5881,120.7187,23.5881"   ← 左上＝右下
invalidateSize() 之後 → 1205 × 458，一切正常
```

---

# ☠️☠️ 這一條是「兩個觀測互相吻合而兩個都錯」的極端版

A 一開始量的是**標記的 DOM transform** 與 **`m.latLngToLayerPoint()`**，
兩個**一直吻合** ⇒ 判斷「標記沒問題」。

🔑 **它們吻合是必然的：兩邊共用同一個錯的 `_size`。**
而**圖磚是照容器的真實像素在鋪** ⇒ 兩套座標系各自都自洽，
**只有肉眼看得出來標記壓在錯的地方。**

📌 那與我今天那六次假綠燈同族，而這一次連「換一個觀測點」都救不了 ——
**因為兩個觀測點在同一個錯誤的下游。**

---

# ⚠️⚠️ 驗收條件有三條，而**第三條我驗不到**

| | 誰驗 |
|---|---|
| 1 `invalidateSize()` 在對的位置被呼叫 | ✅ 本檔（靜態） |
| 2 `ResizeObserver` 綁上且關圖時解除 | ✅ 本檔（靜態） |
| 3 🔴 **肉眼在截圖上確認標記壓在對的城市上** | ❌ **本檔驗不到** —— A 派 D 用瀏覽器做 |

🔑 **第 1、2 條綠不等於好了。**
☠️ 它們證明的是「程式碼裡有那幾個呼叫、順序對」，
**而根因的症狀（標記畫在錯的地方）在那兩條之外。**
📌 A 的原話：**「不要讓下一個人以為兩條綠就等於好了。」**

---

# 🔴 而這四題全是靜態文字檢查，所以判準必須釘「順序」與「呼叫者」

A 的警告值得逐字留著：
> **`invalidateSize` 出現在註解裡、出現在一個沒有人呼叫的函式裡、
> 出現在錯的順序上，你的題都會綠。**
> **沒有反向控制的話，你的題證明的是「這個字串在檔案裡」，
> 而那本來就是真的。**

⇒ 兩道處置：
1. **每一題比索引**（誰在誰之前），不是「有沒有出現」
2. 🔴 **`test_xa0_*` 是給我自己的檢查器做的反向控制** ——
   餵一段**順序寫反**的合成程式碼，那個檢查器**必須拒絕它**。
   📌 沒有 XA0，XA1–XA4 的綠燈只代表「B 的檔案裡有那些字」。
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

PAGE = (Path(__file__).resolve().parent.parent.parent
        / "frontend" / "pages" / "map.html")

#: 註解與字串裡的出現**不算**。
#: ⚠️ 這是 U5c 今天教的：文字比對會把註解裡的 `DROP TABLE` 當成真的。
_COMMENT = re.compile(r"^\s*(//|/\*|\*|#)", re.M)


def _strip_comments(text):
    """把整行註解拿掉。**行內註解留著**（`code()  // 說明` 那種）。

    ⚠️ 這不是一個 JS parser，它擋得住「整段說明文字裡提到那個名字」，
    擋不住「行內註解裡寫了 `invalidateSize()`」。
    🔑 **我把它的射程寫出來，不要讓它看起來比實際更強。**
    """
    return "\n".join(
        "" if _COMMENT.match(line) else line
        for line in text.splitlines()
    )


def _body(text, name):
    """抓某個方法的**主體**（4 空白縮排的 Alpine 物件方法）。

    🔑 錨在方法主體而不是整份檔案 —— 今天 R10b 就是錨在整份檔案上，
    抓到的是呼叫端不是定義。
    """
    m = re.search(r"^ {4}(?:async )?" + re.escape(name) + r"\s*\(", text, re.M)
    assert m, f"`map.html` 裡找不到 `{name}()` 的定義"
    rest = text[m.end():]
    nxt = re.search(r"^ {4}(?:async )?[a-zA-Z_$][\w$]*\s*\(", rest, re.M)
    return rest[:nxt.start()] if nxt else rest


def _order_ok(text, *needles):
    """那幾個字串是否**依序**出現。回 `(ok, 說明)`。

    📌 用 `find(needle, offset)` 逐個往後推 —— 只要有一個找不到，
    或者找到的位置比前一個早，就是不合格。
    """
    offset, seen = 0, []
    for needle in needles:
        i = text.find(needle, offset)
        if i < 0:
            return False, f"找不到 `{needle}`（或它出現在 `{needles[0]}` 之前）"
        seen.append((needle, i))
        offset = i + len(needle)
    return True, " → ".join(f"{n}@{i}" for n, i in seen)


@pytest.fixture(scope="module")
def page():
    assert PAGE.exists(), f"找不到 {PAGE}"
    text = PAGE.read_text(encoding="utf-8")
    assert len(text) > 5000, f"`map.html` 只有 {len(text)} 字元 —— 讀錯檔了？"
    return _strip_comments(text)


# ══════════════════════════════════════════════════════════════════════
# XA0 · 🔴 給我自己的檢查器做的反向控制
# ══════════════════════════════════════════════════════════════════════

def test_xa0_the_order_checker_rejects_the_wrong_order():
    """🔴🔴 XA0：**順序寫反時，`_order_ok` 必須拒絕。**

    ## ☠️ 沒有這一題，XA1–XA4 證明的是「這些字在檔案裡」

    而那本來就是真的 —— A 明講了：
    > **`invalidateSize` 出現在註解裡、出現在一個沒有人呼叫的函式裡、
    > 出現在錯的順序上，你的題都會綠。**

    📌 所以這一題餵**合成**的程式碼（不讀 `map.html`）：
    🔑 讀 `map.html` 的話，這個反向控制會跟著它一起壞。
    """
    good = "const m = L.map('x')\nm.invalidateSize()\nthis._redraw()\n"
    bad = "const m = L.map('x')\nthis._redraw()\nm.invalidateSize()\n"
    missing = "const m = L.map('x')\nthis._redraw()\n"

    ok, detail = _order_ok(good, "L.map(", "invalidateSize", "_redraw")
    assert ok, f"順序正確的樣本被拒絕了：{detail}"

    ok, _ = _order_ok(bad, "L.map(", "invalidateSize", "_redraw")
    assert not ok, (
        "順序**寫反**的樣本通過了檢查 ——\n"
        "⇒ 那個檢查器只在確認「這些字都在」，而 XA1–XA4 的綠燈沒有意義。"
    )

    ok, _ = _order_ok(missing, "L.map(", "invalidateSize", "_redraw")
    assert not ok, "少了 `invalidateSize` 的樣本也通過了檢查"


def test_xa0c_the_order_check_rejects_the_real_file_with_the_lines_swapped(
        page):
    """🔴🔴 XA0c：**把真實檔案裡那兩行對調，XA1 必須紅。**

    ## 為什麼合成樣本不夠

    XA0 證明的是「`_order_ok` 這支函式會拒絕錯的順序」。
    ⚠️ 而它**沒有**證明「XA1 套在 `map.html` 的真實結構上會拒絕」——
    🔑 中間還有 `_body()` 的切片、註解清除、以及我挑的那三個 needle
    **會不會剛好在檔案裡有第二個出現位置**（那樣順序就永遠成立）。

    📌 所以這一題拿**真實檔案的 `_draw` 主體**，程式化地把
    `_syncMapSize()` 那一行搬到 `_redraw()` **之後**，
    再跑一次 XA1 用的同一個判準 —— **它必須紅**。
    ⚠️ 我不動磁碟上的檔案（那是 B 的地盤，而它正在寫）。
    """
    body = _body(page, "_draw")
    call = "this._syncMapSize()"
    if call not in body:
        pytest.skip("實作沒有用 `_syncMapSize()` 具名包裝，XA0 的合成樣本已涵蓋")

    ok, detail = _order_ok(body, "L.map(", "_syncMapSize", "_redraw")
    assert ok, f"前提不成立：真實檔案本來就不合格（{detail}）"

    # 把那一行拿掉，重新插在 `_redraw()` 之後
    stripped = body.replace(call, "", 1)
    i = stripped.find("this._redraw()")
    assert i >= 0, "切片裡找不到 `this._redraw()` —— `_body()` 抓錯範圍了"
    swapped = (stripped[:i + len("this._redraw()")] + "\n      " + call
               + stripped[i + len("this._redraw()"):])

    ok, _ = _order_ok(swapped, "L.map(", "_syncMapSize", "_redraw")
    assert not ok, (
        "把 `_syncMapSize()` 搬到 `_redraw()` 之後，判準仍然說「合格」——\n"
        "⇒ XA1 的綠燈只代表「這三個字都在 `_draw()` 裡」，"
        "而它們本來就都在。\n"
        "☠️ 那個順序錯了的話症狀完全一樣（Leaflet 拿 0×0 去算標記位置）。"
    )


def test_xa0b_the_comment_stripper_actually_strips(page):
    """🔴 XA0b：**整行註解裡的字不算。**

    ⚠️ U5c 今天就是這樣誤報的：`DROP TABLE` 只出現在註解裡，而我判它違規。
    📌 這一題證明 `_strip_comments` 真的在動 ——
    🔑 而它同時把那個工具的**射程**寫出來：行內註解**留著**，
    所以 `code()  // invalidateSize()` 仍然會被算進去。
    """
    sample = "// invalidateSize() 在這裡只是說明\nconst a = 1\n"
    assert "invalidateSize" not in _strip_comments(sample), (
        "整行註解沒有被拿掉 —— 那個檢查器會把說明文字當成程式碼。"
    )
    assert "const a = 1" in _strip_comments(sample), "把程式碼一起刪掉了"
    assert "invalidateSize" in page, (
        "`map.html` 去掉註解之後完全沒有 `invalidateSize` —— "
        "那不是註解問題，是它真的沒有被呼叫（見 XA1）"
    )


# ══════════════════════════════════════════════════════════════════════
# XA1 · invalidateSize 的位置
# ══════════════════════════════════════════════════════════════════════

def test_xa1_invalidate_size_runs_after_the_map_is_created_and_before_redraw(
        page):
    """🔴 XA1：`_draw()` 裡，`L.map(...)` **之後**、`_redraw()` **之前**
    要有 `invalidateSize()`（可以透過 `_syncMapSize()` 這種具名包裝）。

    ☠️ 順序反了的話症狀**完全一樣**：Leaflet 仍然拿著 `0 × 0`
    去算 `_redraw()` 裡每一個標記的位置。
    🔑 **「有呼叫」與「在對的時候呼叫」在畫面上分不出來**，
    而那正是 A 要我比索引不要比存在的理由。
    """
    body = _body(page, "_draw")
    ok, detail = _order_ok(body, "L.map(", "_syncMapSize", "_redraw")
    if not ok:
        ok, detail = _order_ok(body, "L.map(", "invalidateSize", "_redraw")
    assert ok, (
        f"`_draw()` 裡的順序不對：{detail}\n"
        "⇒ 要的是 `L.map(...)` → `invalidateSize()`（或 `_syncMapSize()`）"
        " → `_redraw()`。\n"
        "☠️ 順序反了的話 Leaflet 仍然拿 0×0 去算每一個標記的位置，"
        "而症狀完全一樣。"
    )


def test_xa1b_the_sync_helper_really_calls_invalidate_size(page):
    """🔴 XA1b：那個具名包裝**裡面真的叫得到 `invalidateSize`**。

    ☠️ 少了這一題，XA1 可以靠「有一支叫 `_syncMapSize()` 的空函式」變綠 ——
    🔑 **一個名字取得對而什麼都不做的函式，是最難發現的那一種。**
    📌 〈兩個都對而路不存在〉的鄰居：這次是「路存在而路上什麼都沒有」。
    """
    if "_syncMapSize" not in page:
        pytest.skip("沒有用具名包裝，XA1 已直接驗 invalidateSize")
    body = _body(page, "_syncMapSize")
    assert "invalidateSize" in body, (
        f"`_syncMapSize()` 裡面沒有 `invalidateSize`：\n{body[:240]}"
    )


# ══════════════════════════════════════════════════════════════════════
# XA2 · ResizeObserver 綁上，而且關圖時解除
# ══════════════════════════════════════════════════════════════════════

def test_xa2_a_resize_observer_reacts_by_invalidating_the_size(page):
    """🔴 XA2：有 `ResizeObserver`，**而它的 callback 裡真的叫 `invalidateSize`**。

    📌 為什麼需要它：`invalidateSize()` 只修**當下**那一次。
    容器之後再變（視窗縮放、側邊欄收合、分頁切回來）⇒ **同一個缺陷會回來**，
    ⚠️ 而那一次沒有人會想到是同一個原因。

    🔑 判準是「callback 裡有」不是「檔案裡有」—— A 明講的那一條。
    """
    assert "ResizeObserver" in page, (
        "`map.html` 裡沒有 `ResizeObserver` ——\n"
        "⇒ 容器之後再變大小時，同一個缺陷會回來。"
    )
    i = page.find("new ResizeObserver")
    assert i >= 0, "找到了 `ResizeObserver` 這個字，但沒有 `new ResizeObserver(`"
    window = page[i:i + 400]

    # 🔴 **接受具名包裝，不只接受字面的 `invalidateSize`。**
    #
    # 我第一版只認 `invalidateSize` ⇒ 而 B 的 callback 叫的是
    # `this._syncMapSize()`（那支裡面才呼叫 `invalidateSize`）
    # ⇒ **一個更好的實作在我的題上變紅。**
    #
    # 🔑 今天第 N 次同一個機會（CSP 的萬用子網域／連線洩漏的 `with`／
    #    P14 的 precision 值／R10b 的錨點）：**我把今天的寫法寫成不變量。**
    # 📌 而具名包裝**確實比直接呼叫好**：它同時設 `mapSizeWasZero` 旗標
    #    並重新 `_fitAll()`。⇒ 釘的是「**callback 會重新同步尺寸**」，
    #    而「它怎麼做」由 XA1b 保證（那支包裝裡真的有 `invalidateSize`）。
    resyncs = ("invalidateSize", "_syncMapSize")
    assert any(k in window for k in resyncs), (
        f"`ResizeObserver` 的 callback 裡沒有重新同步尺寸"
        f"（找 {resyncs} 都沒有）：\n{window[:240]}\n"
        "⇒ 觀察器綁上了而什麼都沒做。"
    )


def test_xa2b_the_observer_is_disconnected_when_the_map_closes(page):
    """🔴 XA2b：**關圖時 `disconnect()`** —— 而且要在關圖那支函式裡。

    ☠️ 不解除的話那個觀察器會留在記憶體裡，
    而**下一次開圖會再綁一個** ⇒ 開關幾次之後每次縮放都觸發好幾個 callback。
    🔑 判準是「在 `closeMap()` 裡」不是「檔案裡有 `disconnect`」——
    ⚠️ 檔案裡任何一處都算的話，寫在一支沒有人呼叫的清理函式裡也會綠。
    """
    body = _body(page, "closeMap")
    assert "disconnect" in body, (
        f"`closeMap()` 裡沒有 `disconnect()`：\n{body[:240]}\n"
        "⇒ 觀察器會留著，而下一次開圖會再綁一個。"
    )


# ══════════════════════════════════════════════════════════════════════
# XA3 · 退化時要留痕跡
# ══════════════════════════════════════════════════════════════════════

def test_xa3_a_zero_sized_map_leaves_a_trace(page):
    """🔴 XA3：`getSize()` 是 0 時要**留痕跡**（`mapSizeWasZero`）。

    ## ☠️ 這一題是這一節最重要的一條，而理由是今天整晚的主題

    `invalidateSize()` 修好了症狀 ⇒ **而它同時讓那個成因變成隱形的。**
    🔑 〈防護的副作用落在盲側〉：**加防護時要問「它擋不到的那一側會不會更難看見」。**

    📌 若哪天 `invalidateSize()` 也救不了（例如容器真的是 0 × 0，
    因為某個 CSS 改動），畫面上又會是「一個標記都沒有」，
    ⚠️ **而這一次連 A 的瀏覽器實測都會看到一個「已經修好」的程式碼。**
    ⇒ 所以要有一個**旗標**說「我剛剛遇到 0 × 0」。
    """
    assert "mapSizeWasZero" in page, (
        "沒有 `mapSizeWasZero` 這個旗標 ——\n"
        "⇒ `invalidateSize()` 修好症狀的同時，把成因變成隱形的。"
    )
    body = _body(page, "_syncMapSize") if "_syncMapSize" in page \
        else _body(page, "_draw")
    ok, detail = _order_ok(body, "getSize", "mapSizeWasZero")
    assert ok, (
        f"那個旗標不是從 `getSize()` 的結果推出來的：{detail}\n"
        "⇒ 一個不看實際尺寸就設定的旗標，說的不是它宣稱的那件事。"
    )


# ══════════════════════════════════════════════════════════════════════
# XA4 · openMap 要排在 refresh 之後
# ══════════════════════════════════════════════════════════════════════

def test_xa4_the_map_opens_only_after_the_data_arrives(page):
    """🔴 XA4：`init()` 裡 `openMap()` 要在 **`await refresh()` 之後**。

    ☠️ 反過來的話 `_fitAll()` 會在**還沒有點**的時候跑
    ⇒ 它會框一個空的範圍，而使用者看到的是一張**縮到世界級**的地圖。
    🔑 **那個症狀跟「標記畫錯位置」在使用者那一側是同一句話：**
    **「我的點呢？」**

    📌 比索引，不是比存在 —— 兩個都在檔案裡是必然的。
    """
    body = _body(page, "init")
    ok, detail = _order_ok(body, "refresh(", "openMap(")
    assert ok, (
        f"`init()` 裡 `openMap()` 沒有排在 `refresh()` 之後：{detail}\n"
        "⇒ `_fitAll()` 會在還沒有點的時候跑，框出一個空範圍。"
    )
    assert "await" in body[:body.find("openMap(")], (
        "`refresh()` 前面沒有 `await` ——\n"
        "⇒ 它不會等資料回來，順序寫對了也沒有用。"
    )


def test_xa4b_the_tile_error_signals_are_still_there(page):
    """🔴 XA4b：`tileerror` 與 `tilesBlocked` 的訊號**仍然在**。

    ⚠️ 這一題防的是「順手清掉」：改 `_draw()` 的時候最容易一起動到
    圖磚那一段，而那兩個訊號是今晚 §3m 建立的
    —— ☠️ **OSM 封鎖時回 HTTP 200 而內容是拒絕，瀏覽器不觸發 error**
    ⇒ 前端唯一的線索就是那兩個。
    🔑 〈已知的代價 vs 要修的東西〉：一個被順手刪掉的訊號，
    **不會有人發現它不見了**。
    """
    for name in ("tileerror", "tilesBlocked"):
        assert name in page, (
            f"`map.html` 裡的 `{name}` 不見了 ——\n"
            "⇒ OSM 封鎖時前端唯一的線索就是那兩個訊號。"
        )


# ══════════════════════════════════════════════════════════════════════
# XA5 · 自動開圖要「自己會停」
# ══════════════════════════════════════════════════════════════════════
#
# 🔑 A 的理由：**封閉網路不是「偶爾失敗」，是每次都失敗。**
# ☠️ 自動開圖把「一次失敗」變成「**每次進頁都失敗**」，
#    而每一次的代價是一個敲不到的對外連線。
# 📌 〈告警必須有速率上限〉的同一條：**自動的東西必須自己會停，
#    設計時就要想失控怎麼關掉。**
#
# ⚠️ B 的原始觀察要留著：「以前是使用者按了才連 openstreetmap.org，
#    現在是每次開這一頁都連。」
#    **使用者說「正式機都長期開著」—— 那是他那台機器的理由，不是通則。**


def test_xa5_a_tile_failure_is_remembered(page):
    """🔴 XA5：偵測到 `tileerror` ⇒ **記起來**（跨頁面存活）。

    📌 判準是「`tileerror` 的處理裡會去寫那個記憶」，
    ⚠️ 不釘 `localStorage` 的鍵名（那是實作細節）——
    🔑 只釘「它有被記下來」，而**記在哪由 B 決定**。
    """
    i = page.find("'tileerror'")
    if i < 0:
        i = page.find('"tileerror"')
    assert i >= 0, "`map.html` 裡找不到 `tileerror` 的處理"
    window = page[i:i + 300]
    assert "TileFailure" in window or "localStorage" in window, (
        f"`tileerror` 的處理裡沒有把失敗記起來：\n{window[:200]}\n"
        "⇒ 下一次進這一頁仍然會自動開，而封閉網路每次都失敗。"
    )


def test_xa5b_a_remembered_failure_stops_the_auto_open(page):
    """🔴🔴 XA5b：**記得上次失敗 ⇒ 下一次不自動開。**

    ☠️ 這一題是斷路器的本體。少了它，XA5 只證明「有寫入」，
    🔑 而**「記下來了」與「記下來有用」是兩件事** ——
    那正是今晚反覆出現的〈證據的適用範圍〉。

    📌 判準：`init()` 裡自動開圖那一步**被那個記憶擋著**
    （`_tileFailedBefore()` 或等價的檢查出現在 `openMap()` 呼叫之前）。
    """
    body = _body(page, "init")
    ok, detail = _order_ok(body, "TileFailedBefore", "openMap(")
    if not ok:
        ok, detail = _order_ok(body, "localStorage", "openMap(")
    assert ok, (
        f"`init()` 裡自動開圖那一步沒有被「上次失敗」擋著：{detail}\n"
        "☠️ 封閉網路每次都失敗 ⇒ 每次進頁都會再敲一次連不到的對外連線。"
    )


def test_xa5c_a_successful_tile_clears_the_flag(page):
    """🔴🔴 XA5c 反向控制：**載得到圖磚 ⇒ 把旗標清掉。**

    ☠️ 少了這一題，一個「**一旦失敗就永遠手動**」的實作會讓 XA5b 綠 ——
    而網路修好之後它**永遠不會自己好**，
    🔑 而使用者不會知道要去哪裡按重設 —— 他只會覺得「地圖以前會自己開」。

    📌 〈降級之後它還是會動〉的鏡像：這次是**降級之後它不會自己回來**。
    """
    i = page.find("'tileload'")
    if i < 0:
        i = page.find('"tileload"')
    assert i >= 0, (
        "`map.html` 裡沒有 `tileload` 的處理 ——\n"
        "⇒ 網路修好之後那個旗標永遠不會被清掉，地圖永遠不再自動開。"
    )
    window = page[i:i + 300]
    assert "TileFailure" in window or "removeItem" in window, (
        f"`tileload` 的處理裡沒有清掉那個旗標：\n{window[:200]}"
    )


def test_xa5d_an_unreadable_storage_does_not_disable_the_map(page):
    """🔴 XA5d：`localStorage` **讀不到**（無痕視窗）⇒ 當成「沒失敗」。

    🔑 **「讀不到偏好」不是「不要開地圖」。**
    ☠️ 反過來的話，**每一個用無痕視窗的人都會看到一張不會自己開的地圖**，
    而畫面上不會說原因 —— 他會以為功能壞了。
    📌 〈null 不等於 0〉的同一族：**「取不到值」與「值是 true」是兩件事。**

    ⚠️ 判準是「讀取被 `try` 包著，而 `catch` 回的是**不擋**」——
    我只驗那個 `catch` 存在且回 `false`／`return` 之類的放行，
    **驗不到它在真的無痕視窗裡的行為**（那要瀏覽器）。
    """
    m = re.search(r"_tileFailedBefore\s*\([^)]*\)\s*\{", page)
    assert m, "`map.html` 裡找不到 `_tileFailedBefore()` 的定義"
    body = page[m.end():m.end() + 400]
    assert "catch" in body, (
        f"讀 `localStorage` 沒有被 `try/catch` 包著：\n{body[:200]}\n"
        "⇒ 無痕視窗會丟例外，而那會讓整支 `init()` 掛掉。"
    )
    tail = body[body.find("catch"):body.find("catch") + 120]
    assert "false" in tail or "return" in tail, (
        f"`catch` 裡沒有放行：\n{tail}\n"
        "🔑 「讀不到偏好」不是「不要開地圖」。"
    )
