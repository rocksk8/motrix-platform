"""規格裡的編號 ⇄ 測試檔裡真的寫出來的題 —— 兩邊對不上就紅。

## 這支的由來：**「我裁示了」被當成「它存在了」**

2026-09-21：A 連續兩次對我與 B 說「SL17／SL18 已加」。
**它們從來沒有被寫出來。** 沒有人說謊 —— 裁示確實發生了，
**而「有人真的把它寫成一題」那一步沒有任何東西在守。**

> 🔑 **決定與落地之間那一步是隱形的**，因為兩邊各自都留下了痕跡
> （規格裡有條文、測試檔裡有很多題），**只有「它們對不對得上」沒有留下痕跡。**

⚠️ 照〈修作法不要修結果〉：補寫那兩題只是修結果。
**這一支才是修作法** —— 它讓「裁示了卻沒寫」這件事**下次不可能安靜地發生**。

## ⚠️ 這支守門**只驗「有沒有人寫出一題」，不驗「那一題對不對」**

一個 `def test_sl17_...(): pass` 就能讓它綠。
🔑 **它是覆蓋率的下界，不是覆蓋率。**
⇒ **不要把它的綠燈當成「規格被驗過了」** —— 那是 A 結案時要看的，不是這裡。

## ⚠️ 反向控制：它可以靠「把規格裡的編號刪掉」變綠

那是真的，而且**無法從這一側擋住**（規格檔不是我的地盤）。
⇒ 所以有 `test_the_spec_still_declares_the_numbers_we_know_about`：
**已知存在過的編號不可以從規格裡消失。**
📌 那一題把「刪條文」這條捷徑從**安靜**變成**要動兩個檔**。
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
SPEC = REPO / "docs" / "windows" / "STATE.md"
TESTS = Path(__file__).resolve().parent

#: 規格裡宣告一條驗收條件的樣子：`- **SL3.**` / `- **D20.**` / `- **M14.**`
# ⚠️ 粗體是**可有可無**的：規格裡兩種寫法都有（`- **SL17.**` 與 `- N1. 🔴 ...`）。
#    我第一版強制要粗體 ⇒ **漏掉 26 條**（整個 N 系列與 R 系列），
#    而漏掉的那些會跑到「只存在於測試」那一邊，讓第三題看起來爆掉。
# 🔑 **判準的形狀決定了你看得見什麼** —— 今天第三次，這次是我自己的守門。
_DECLARED = re.compile(r"^\s*-\s+~*\*{0,2}([A-Z]{1,2}\d{1,2}[a-z]?)\.\*{0,2}", re.M)

#: 測試函式名裡的編號：`def test_sl3_...` / `def test_d20b_...`
_IMPLEMENTED = re.compile(r"^def test_([a-z]{1,2}\d{1,2}[a-z]?)_", re.M)

#: 🔴 **明文豁免**：驗不到的條文，每一條都要寫出「為什麼」。
#: ⚠️ 這張表是這支守門唯一的逃生口，所以它必須難用：
#:    加一筆要寫理由，而理由會被 A 在結案時讀到。
EXEMPT = {
    "SL8":  "已撤銷（類別錯置：那是⑥的收斂條件，不是一支測試）",
    "SL11": "驗的是 docstring 的內容 —— 沒有任何測試能驗註解",
    "SL12": "前端是 UI 結構不是文案，要使用者目視",
    "SL14": "同 SL11，要改的是註解的理由",
    "SL15": "規格裡沒有這一條（編號跳號）",
    "M10":  "OSM 圖磚需要外網，是已知限制不是行為",
    "M11":  "距離只到縣市中心點 —— 畫面上的說明文字，人工驗收",
    "M15":  "Google Console 的來源限制提醒 —— 畫面文字，人工驗收",
    "U6":   "拿正式機備份複本真的跑一次升級 —— 人工，A 做",
}

#: 已知存在過的編號（反向控制用）。**只增不減。**
KNOWN = {"SL1", "SL3", "SL16", "SL17", "SL18", "SL19", "D20", "M1", "U1"}


def _declared():
    text = SPEC.read_text(encoding="utf-8")
    return {m.group(1).upper() for m in _DECLARED.finditer(text)}


def _implemented():
    found = set()
    for path in sorted(TESTS.glob("test_*.py")):
        for m in _IMPLEMENTED.finditer(path.read_text(encoding="utf-8")):
            found.add(m.group(1).upper())
    return found


def test_every_declared_condition_has_a_test():
    """🔴 規格裡宣告的每一條，都要有一支 `def test_<編號>_...`。

    ⚠️ **這一題現在應該是紅的**，而且要指名 `SL17`／`SL18`
    （A 兩次說「已加」而從來沒被寫出來的那兩條）。
    🔑 **如果它是綠的，那就表示它沒在驗它該驗的東西。**
    """
    declared = _declared()
    assert len(declared) > 30, (
        f"只從規格裡解析出 {len(declared)} 條驗收條件 —— 那個 regex 八成失效了。\n"
        "⚠️ **解析器壞掉時這支守門會安靜地全綠**，所以先驗它有沒有讀到東西。"
    )
    missing = sorted(declared - _implemented() - set(EXEMPT))
    assert not missing, (
        "這些條件在規格裡宣告了，而**沒有任何一支測試以它命名**：\n  "
        + "\n  ".join(missing)
        + "\n\n⇒ 要嘛寫一題，要嘛加進 EXEMPT 並寫出為什麼驗不到。\n"
        "⚠️ 加進 EXEMPT 不是把它變綠 —— 那張表 A 結案時會讀。"
    )


def test_the_spec_still_declares_the_numbers_we_know_about():
    """反向控制：**已知存在過的編號不可以從規格裡消失。**

    ⚠️ 沒有這一題，上一題可以靠「**把條文從規格裡刪掉**」變綠 ——
    而那個動作**在測試這一側完全看不見**。

    📌 它擋不住有決心的人（規格檔不是我的地盤），
    但它把那條捷徑從**安靜**變成**要動兩個檔**，而第二個檔會紅。
    🔑 **守門擋不住的東西，至少要讓它留下痕跡。**
    """
    declared = _declared()
    vanished = sorted(KNOWN - declared)
    assert not vanished, (
        f"這些編號以前在規格裡、現在不見了：{vanished}\n"
        "⇒ 若是條文被刪，請同時把它從 KNOWN 拿掉並說明；"
        "若是編號改了，兩邊要一起改。"
    )


def test_no_test_claims_a_number_the_spec_never_declared():
    """反過來：測試宣稱驗了某一條，而規格裡沒有那一條。

    ⚠️ 這通常不是錯 —— 我自己就加過 `SL3b`／`D20b` 這種**規格沒有、
    而我認為必要的對照組**。所以這一題**不強制**兩邊相等，
    只把差集**印出來**，讓 A 結案時看得到我加了哪些規格外的題。

    🔑 **一題永遠綠的測試若只是為了印東西，那它應該是一份報告不是一題測試** ——
    我留著它是因為 `-q` 的輸出不會顯示 print，**而失敗訊息會**。
    ⇒ 所以它的斷言是「差集不可以大到離譜」：真的爆掉時才需要有人看。
    """
    declared = _declared()
    # 對照組（`SL3b`／`D20b`）不算「規格外」：它們的本體編號在規格裡。
    extra = sorted(
        n for n in _implemented() - declared - set(EXEMPT)
        if not (n[-1].isalpha() and n[:-1] in declared)
    )
    assert len(extra) < 25, (
        f"有 {len(extra)} 個編號只存在於測試、不存在於規格：{extra}\n"
        "⇒ 若它們是對照組（像 SL3b／D20b），那是對的；"
        "若是規格被改動而測試沒跟上，兩邊要對齊。"
    )
