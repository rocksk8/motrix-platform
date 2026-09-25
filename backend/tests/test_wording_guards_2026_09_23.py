# -*- coding: utf-8 -*-
"""`WD1` · 通知文案的守門（`docs/windows/SPEC-WD1-WORDING.md`）。

# 🔴🔴 `GW3` 是一條**給我的禁令**，不是一道守門

```
**不可以寫關鍵字黑名單題。**
① 誤判  引用**使用者原話**的地方會被判成違規
        （規格第 12 行就是使用者原話，任何黑名單都會命中它）
② 漏判  口語**不是由某幾個詞構成的，是語域**
        ⇒ 換一批詞照樣口語，而守門說它過了 ⇒ **假綠燈**
```
🔑 ⇒ **本檔沒有任何一題讀那些字**。守門只管「**位置**」，語氣由人審。
📌 這段話是那條禁令的載體 —— 下一個想加「不可以出現『喔』『囉』」的人
   會先讀到它。

# ⚙️ 而這道守門擋不到的那一側，規格要求寫出來

```
有人把一句**口語**的文案**放進**常數區 => 守門照樣綠
```
⇒ 它把問題從「散在 1924 行」縮小成「一份清單」，**不是消滅它**。
⇒ 配一條**人的規則**：新增或修改 `WORDING` 的 commit，**diff 必須被讀過**。

# ⚠️ 範圍那條線：**寫給誰看的**

```
✅ 在範圍  會**離開這台機器到非維護者手上**的字
           `intro=`／`note=`／`title=`、畫面文案、`HTTPException` detail、PDF 文字
❌ 不在範圍 **程式碼註解與 docstring** —— 那是寫給維護者的，
           **口語在那裡是優點**
```
🔴 **不可以用「檔名是不是 `*_notify.py`」當範圍** —— 那會把 docstring 一起掃進去，
   **而它們正是這個 repo 最有價值的部分**。
⇒ 用 `ast`：關鍵字引數的**值**在範圍；docstring 是 `def`／module 的第一個
  `ast.Expr` **不在範圍**；`#` 註解 `ast` 根本看不到 ⇒ **天然排除**。
📌 `email_notify.py` 裡兩者**混在同一個函式**：docstring 很口語而那是優點，
   `intro` 口語才是問題。
"""
import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: `GW1` 要掃的關鍵字引數 —— 它們的值**會離開這台機器**。
TEXT_KWARGS = ("intro", "note", "title")

#: `GW1` 的基準：**0**。
#: 🔴 **不要寫成「不高於上一包」** —— 那會把今天的欠帳當成明天的基準
#:    （今天實測 45 處 `intro=` ＋ 12 處 `note=`，改完要歸零）。
GW1_BASELINE = 0

#: 掃描範圍：會送出文案的那幾支。⚠️ **不是**「檔名含 notify」。
#: 模組搬出去的通知一併列入（守門對象不可以被搬走）。
SCAN_FILES = ("helpers/email_notify.py", "modules/tender_radar/notify.py")

#: `GW2`：異常／失敗類通知要答的四個問題。
FOUR_FIELDS = ("what", "impact", "system", "action")


def _wording():
    """`WORDING` 常數區。還不存在時**明說它是 `WD1` 的前提**。"""
    p = ROOT / "helpers" / "wording.py"
    if not p.is_file():
        pytest.fail(
            "`helpers/wording.py` 還不存在 —— `WD1` 的常數區沒有建。\n"
            + "📌 `§2`：把文案搬到一個地方，讓守門只管**位置**，人只管**語氣**。\n"
            + "⚠️ 刻意 **fail 不 skip**：skip 會永久略過而沒有人發現。")
    import importlib
    return importlib.import_module("helpers.wording")


def _inline_text_kwargs(path):
    """回 `[(行號, 關鍵字, 前 30 字)]` —— 值是**字面字串**的那些。

    ⚠️ 只看**關鍵字引數的值**：
    ```
    docstring  是 def／module 的第一個 ast.Expr  => **不在這裡**
    # 註解     ast 根本看不到                    => **天然排除**
    ```
    🔑 ⇒ 這把尺**結構上不可能**掃到寫給維護者的字。
    """
    src = path.read_text(encoding="utf-8", errors="replace")
    out = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg not in TEXT_KWARGS:
                continue
            v = kw.value
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                out.append((v.lineno, kw.arg, v.value[:30]))
            elif isinstance(v, ast.JoinedStr):
                # f-string：它的**常數片段**一樣會離開這台機器
                lits = "".join(p.value for p in v.values
                               if isinstance(p, ast.Constant)
                               and isinstance(p.value, str))
                if lits.strip():
                    out.append((v.lineno, kw.arg, lits[:30]))
    return out


# ══════════════════════════════════════════════════════════════════════
# GW1：呼叫端不可以有行內文案
# ══════════════════════════════════════════════════════════════════════

#: 🔴 `WD1`（`GW1`／`GW2`）：**使用者 2026-09-24 裁示的唯一例外**——
#:    「WD1 先 xfail，併入平台化」（表單作答，hichan-0a 轉達；見
#:    `docs/windows/HANDOFF-PENDING-2026-09-23.md`「🟢 路線裁示」）。
#: ⚠️ strict=True：`helpers/wording.py` 做好、這三題轉綠的那一刻會**紅**（XPASS），
#:    提醒把這個標記拿掉 —— 不是讓它永遠安靜。
#: ⚠️ 只標這三支；本檔其餘的題（正對照、量尺）照常必須綠。
_WD1_DEFERRED = pytest.mark.xfail(
    strict=True,
    reason="WD1（GW1/GW2）：使用者 2026-09-24 裁示先 xfail，併入平台化「內容層」設計；"
           "helpers/wording.py 尚未建立")


@_WD1_DEFERRED
def test_gw1_no_caller_carries_its_own_wording():
    """🔴 **`GW1`：`intro=`／`note=`／`title=` 的值不可以是字面字串。**

    📌 守門驗的是「**文案有沒有被收進那份清單**」，不是「它寫得好不好」——
       **後者沒有人有辦法自動判定，而前者可以。**
    🔴 基準是 **0**，不是「不高於上一包」——
       ☠️ 那會把**今天的欠帳當成明天的基準**，而欠帳會在那條線底下永遠活著。
    """
    offenders = []
    scanned = 0
    for rel in SCAN_FILES:
        p = ROOT / rel
        if not p.is_file():
            pytest.fail("`%s` 不見了 —— **退回給我**改掃描範圍。" % rel)
        scanned += 1
        for line, kw, head in _inline_text_kwargs(p):
            offenders.append("%s:%d  %s=%r" % (rel, line, kw, head))

    assert scanned, "一個檔都沒掃到 —— **尺量不到東西**。"
    assert len(offenders) == GW1_BASELINE, (
        "有 %d 處行內文案（基準 %d）：\n" % (len(offenders), GW1_BASELINE)
        + "".join("    %s\n" % o for o in offenders[:12])
        + ("    …另外 %d 處\n" % (len(offenders) - 12)
           if len(offenders) > 12 else "")
        + "📌 `§2`：搬進 `helpers/wording.py` 的 `WORDING`，\n"
          "   呼叫端寫 `intro=WORDING[\"tender.fetch_failed.intro\"]`。\n"
        + "🔑 這道守門**完全不讀那些字** ⇒ 零誤判；\n"
          "   而語氣變成一份可以一次讀完的清單，由人審閱。")


def test_gw1_a_wording_reference_is_not_flagged(tmp_path):
    """⚙️ **正對照：指向常數區的呼叫**必須綠**，字面值必須紅。**

    ☠️ 少了它，一把「什麼都不報」的尺也會讓上一題綠。
    ⚠️ 而 f-string 也要抓得到：`intro=f"抓取失敗：{name}"` 的常數片段
       **一樣會離開這台機器**。
    """
    good = tmp_path / "good.py"
    good.write_text(
        '"""這個 docstring 很口語，而那是**優點** —— 它是寫給維護者的。"""\n'
        "from helpers.wording import WORDING\n"
        "send(intro=WORDING['x.intro'], note=WORDING['x.note'])\n",
        encoding="utf-8")
    assert _inline_text_kwargs(good) == [], (
        "指向常數區的呼叫被判成違規：%r —— **太寬**。\n"
        % _inline_text_kwargs(good)
        + "⚠️ 特別注意那個 docstring：它**不可以**被掃到。")

    bad = tmp_path / "bad.py"
    bad.write_text(
        "send(intro='這通常不需要處理喔')\n"
        'send(note=f"抓取失敗：{name}")\n',
        encoding="utf-8")
    hits = {kw for _l, kw, _h in _inline_text_kwargs(bad)}
    assert hits == {"intro", "note"}, (
        "沒抓到字面值／f-string：%r —— **太窄**。" % _inline_text_kwargs(bad))


def test_gw1_the_scanner_cannot_see_docstrings_or_comments(tmp_path):
    """⚙️ **範圍那條線要證明得出來，不是宣稱。**

    ```
    ✅ 在範圍  關鍵字引數的**值**
    ❌ 不在範圍 docstring（第一個 `ast.Expr`）／`#` 註解
    ```
    🔴 用「檔名含 notify」當範圍的話會把 docstring 一起掃進去 ——
       **而它們正是這個 repo 最有價值的部分。**
    """
    p = tmp_path / "mixed.py"
    p.write_text(
        '"""模組 docstring：intro="這句話在 docstring 裡" —— 不可以被抓到。"""\n'
        "# 註解：note='這句話在註解裡'，ast 根本看不到它\n"
        "def f():\n"
        '    """函式 docstring：title="也不可以"。"""\n'
        "    return 1\n",
        encoding="utf-8")
    assert _inline_text_kwargs(p) == [], (
        "掃到了 docstring 或註解裡的字：%r\n" % _inline_text_kwargs(p)
        + "☠️ 那些是寫給**維護者**的，**口語在那裡是優點**。")


# ══════════════════════════════════════════════════════════════════════
# GW2：異常類四格齊全
# ══════════════════════════════════════════════════════════════════════

@_WD1_DEFERRED
def test_gw2_the_error_wordings_are_listed_not_guessed():
    """🔴 **`GW2` 的前提：哪些算「異常類」要有一張明確清單。**

    ⚠️ 規格逐字：**不要用「函式名字裡有 `failed`」去猜**。
    ☠️ 用猜的話，漏掉的永遠是**沒有人想到的那一個** ——
       而〈守門要驗有沒有人做過決定〉：清單本身就是那個決定。
    """
    w = _wording()
    listed = getattr(w, "ERROR_WORDING_KEYS", None)
    assert listed is not None, (
        "`helpers/wording.py` 沒有 `ERROR_WORDING_KEYS` ——\n"
        + "📌 那是「哪些通知算異常類」的**明確清單**。\n"
        + "⚠️ 用別的名字**退回給我**；而**不要**改成從名字猜。")
    assert listed, (
        "`ERROR_WORDING_KEYS` 是空的 —— **尺量不到東西**，下一題不算數。")
    missing = [k for k in listed if k not in getattr(w, "WORDING", {})]
    assert not missing, (
        "清單上有 %d 個 key 不在 `WORDING` 裡：%r" % (len(missing), missing))


@_WD1_DEFERRED
def test_gw2_every_error_wording_answers_all_four_questions():
    """🔴 **`GW2`：異常類的四格 `what`／`impact`／`system`／`action` 都要非空。**

    ```
    what    發生了什麼
    impact  對使用者的影響
    system  系統會做什麼
    action  人要不要動、什麼時候
    ```
    ☠️ **`action` 留空與寫「無須人工介入」是兩回事** ——
       留空的人**不知道該不該動**，而**不知道該不該動的人會去問人**。
    """
    w = _wording()
    words = getattr(w, "WORDING", {})
    bad = []
    for key in getattr(w, "ERROR_WORDING_KEYS", ()):
        entry = words.get(key) or {}
        for f in FOUR_FIELDS:
            if not str(entry.get(f) or "").strip():
                bad.append("%s.%s" % (key, f))
    assert not bad, (
        "有 %d 格是空的：\n" % len(bad)
        + "".join("    %s\n" % b for b in bad[:12])
        + "☠️ `action` 留空與寫「無須人工介入」是**兩回事** ——\n"
          "   留空的人不知道該不該動，**而不知道該不該動的人會去問人**。")


def test_gw2_clearing_a_field_really_turns_it_red():
    """⚙️ **正對照：把 `impact` 清空，上一題必須紅。**

    ☠️ 少了它，一個「清單是空的」或「欄位名拼錯」的實作也會讓上一題綠 ——
       而那時它什麼都沒驗。
    ⚙️ 這一題**不碰產品**：它把同一段判定邏輯套在一份合成的 `WORDING` 上。
    """
    def _check(words, keys):
        bad = []
        for key in keys:
            entry = words.get(key) or {}
            for f in FOUR_FIELDS:
                if not str(entry.get(f) or "").strip():
                    bad.append("%s.%s" % (key, f))
        return bad

    full = {"x": {f: "有寫" for f in FOUR_FIELDS}}
    assert _check(full, ["x"]) == [], "四格齊全的被判成缺 —— **太寬**。"

    for f in FOUR_FIELDS:
        holed = {"x": dict(full["x"], **{f: ""})}
        assert _check(holed, ["x"]) == ["x.%s" % f], (
            "把 `%s` 清空而判定沒有抓到：%r —— **太窄**。"
            % (f, _check(holed, ["x"])))

    blank = {"x": dict(full["x"], action="   ")}
    assert _check(blank, ["x"]) == ["x.action"], (
        "只填空白的 `action` 被當成有寫 —— 空白不是答案。")
