# -*- coding: utf-8 -*-
"""`MD1` · **行內標記把編號拆開** —— `grep` 回 0 而那句話存在。

A `§118`／`§119`（`e26f995`）縮範圍後的兩小題：
```
(a) 圍欄區塊裡，編號被行內標記拆開（`UI**10**`）        => 紅
    ⚠️ 而 `**UI10**`（標記在**外面**）是合法的 => **不可以一起擋掉**
(b) 🔴 自己寫的字串再用窄 pattern 去比對它              => 紅
```

---

# 🔴 我量了現況，而**唯一的兩個命中是描述這個規則的那兩行本身**

```
docs/windows/STATE.md :28610   probe = 'UI**10** DB1'
docs/windows/SCOPE.md :241     (a) 圓欄裡編號被標記拆開（`UI**10**`）=> 紅
```
🔑 ⇒ 一道天真的 `MD1(a)` **會在它自己的規格上亮紅燈**。
📌 ⇒ 所以它需要一份**有理由、且會爛掉時自己紅**的白名單，不是一個更寬的 pattern
   （更寬的 pattern 會連 `**UI10**` 一起擋掉，而那是合法寫法）。

# 🔴 而掃描範圍我第一版訂錯了 —— **我整份排除 `STATE.md`**

```
我的理由  它是敘事紀錄，本來就會描述失效模式 => 每次 A 記錄一次就紅一次
我標的代價 STATE.md 裡一個真的被拆開的編號，抓不到
```
☠️ **而 A 指出那個代價比我標的大得多**：
```
_declared_where() 讀的就是 STATE.md（SPEC = STATE.md）
=> 排除它 = **在「編號宣告的唯一所在地」把這道守門關掉**
```
🔑 我的顧慮是真的，我的處置是錯的 —— **兩者不衝突，我只是沒有找第三條路。**
⇒ A 裁：**掃 `STATE.md`，只掃宣告形狀的行**（`- ` ／ `| ` ／ `## `），
   散文／圍欄／引用區塊不掃 ⇒ 記錄失效模式的地方不會紅。
✅ 實測：`STATE.md` 4,046 行宣告形狀的行，**命中 0** ⇒ 零誤報。
📌 判準寫死：**守門看的範圍 == 解析器看的範圍**，不多不少。

# 📌 順帶：`SCOPE.md:241` 原本逐字是「**圓**欄」不是「**圍**欄」

`grep "圍欄"` 找不到那一行 —— 🔑 **同一族的第四個載體：看起來對的字。**
（`U+5713 圓` vs `U+570D 圍`。A 已修，`c9c29b3`，兩處；他掃過 `docs/` 沒有第三處。）
"""
import hashlib
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent

#: 掃描範圍，**每一份各自對齊讀它的那支解析器**（A 2026-09-23 裁）。
#:
#: 🔑 判準：**守門看的範圍 == 解析器看的範圍**，不多不少。
#: ```
#: "fence"  程式碼圍欄裡     <= test_spec_coverage._scope_sections() 讀 SCOPE.md 的圍欄
#: "decl"   宣告形狀的行     <= _declared_where() 讀 STATE.md 的 `- ` / `| ` / `## `
#: ```
#: ⚠️ 我第一版**整份排除 `STATE.md`**，理由是「它是敘事紀錄，本來就會描述失效模式」。
#: ☠️ 而 A 指出那個排除的代價比我標的大得多：
#: ```
#: 我標的   STATE.md 裡一個真的被拆開的編號，抓不到
#: 而實際   **_declared_where() 讀的就是 STATE.md**（SPEC = STATE.md）
#:          => 排除它 = 在「編號宣告的唯一所在地」把這道守門關掉
#: ```
#: 📌 ⇒ 第三條路：**掃 `STATE.md`，只掃宣告形狀的行**。
#:    散文／圍欄／引用區塊不掃 ⇒ 記錄失效模式的地方不會紅。
#: ✅ 我實測過：`STATE.md` 4,046 行宣告形狀的行，**命中 0** ⇒ 零誤報。
SCANNED = (
    ("docs/windows/SCOPE.md", "fence"),
    ("docs/windows/STATE.md", "decl"),
    # ⚠️ 下面三份**沒有解析器在讀** —— 掃它們是為了**人**（B 照施工圖實作、會 grep 它）。
    #    所以判準不是「對齊解析器」，是「對齊讀者會用的動作」。
    ("docs/windows/SPEC-VOUCHER.md", "fence"),
    ("docs/windows/SPEC-VOUCHER-HISTORY.md", "fence"),
    ("MULTIWIN-PROTOCOL.md", "fence"),
)

#: 宣告形狀：`_DECLARED_BULLET`／`_DECLARED_TABLE`／`_DECLARED_HEADING` 看的那些起頭。
_DECL_START = re.compile(r"^(?:- |\| |#{2,4} )")

#: 行內標記。`~~` 要排在 `*` 前面，否則 `**` 會先被 `*` 吃掉半個。
_MARKS = ("**", "~~", "*", "`", "_")

#: 編號被標記拆開的形狀：`UI**10**` 的前半、`GC1**a**` 的後半。
_SPLIT = re.compile(
    r"[A-Z]{1,2}(?:\*\*|~~|\*|`|_)\d|\d(?:\*\*|~~|\*|`|_)[a-z]\b")


def _fenced_lines(text):
    """只回**程式碼圍欄裡**的行 `(行號, 內容)`。

    📌 圍欄是既有解析器（`test_spec_coverage._scope_sections`）用的同一條界線 ——
       ⚠️ 用不同的界線的話，我守的就不是它讀的那份東西。
    """
    out, inside = [], False
    for i, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("```"):
            inside = not inside
            continue
        if inside:
            out.append((i, line))
    return out


def _decl_lines(text):
    """只回**宣告形狀的行**（`- ` ／ `| ` ／ `## `），圍欄與引用區塊不算。

    📌 那是 `_declared_where()` 唯一會看的那些行。
    ⚠️ 引用區塊（`> `）排除：它是**在轉述別人的話**，而轉述裡的編號不是宣告。
    """
    out, inside = [], False
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if s.startswith("```"):
            inside = not inside
            continue
        if inside or s.startswith(">"):
            continue
        if _DECL_START.match(s):
            out.append((i, line))
    return out


_MODES = {"fence": _fenced_lines, "decl": _decl_lines}


def _key(rel, line):
    """白名單的鍵：**檔名 ＋ 該行內容的雜湊**，不是行號。

    ☠️ 用行號的話，`STATE.md` 長一行就全部失效 ——
       而失效的樣子是「白名單條目對不上 ⇒ 紅」，**每天都紅**。
    🔑 〈不要用會動的名字〉：行號在共用工作目錄裡是會動的名字。
    """
    h = hashlib.sha256(line.strip().encode("utf-8")).hexdigest()[:12]
    return "%s:%s" % (rel, h)


#: 已知的**例外**：它們在**描述**這個失效模式，不是在犯它。
#: ⚠️ 每一筆都要有理由；而**條目對不上任何一行時這道守門會紅**（見反向控制）。
ALLOW = {
    _key("docs/windows/SCOPE.md",
         "(a) 圍欄裡編號被標記拆開（`UI**10**`）=> 紅"):
        "A 在 SCOPE.md 定義 MD1(a) 時舉的反例本身。"
        "（⚠️ 2026-09-23 換過一次鍵：A 把「圓欄」修成「圍欄」"
        "=> 舊鍵對不上 => **反向控制正確地紅了**，這就是它存在的理由。）",
    # 🔑 A 在 `STATE.md` 的表格列**宣告 `MD1` 本身**，而那一列要舉 `UI**10**` 當反例。
    # ☠️ ⇒ 這道守門第二次亮在「描述它自己的那一行」上 —— 而兩次都是對的。
    _key("docs/windows/STATE.md",
         "| **MD1** | 圓欄／宣告行裡的編號不可被行內標記拆開（`UI**10**`）；"
         "且正規化不可剥過頭生出幽靈編號 |"):
        "A 在 STATE.md 宣告 MD1 的表格列，其中的 `UI**10**` 是反例本身。"
        "⚠️ 這一列還帶著兩個同形異碼（圓 U+5713 應為 圍 U+570D、"
        "剥 U+5265 應為 剝 U+525D），已回報 A —— 他修的話這個鍵會對不上，"
        "而**那正是反向控制該做的事**。",
}


def _scan():
    hits, missing_files = [], []
    for rel, mode in SCANNED:
        p = _ROOT / rel
        if not p.exists():
            missing_files.append(rel)
            continue
        for ln, line in _MODES[mode](p.read_text(encoding="utf-8")):
            for m in _SPLIT.finditer(line):
                hits.append((rel, ln, m.group(0), line.strip(), _key(rel, line)))
    return hits, missing_files


# ══════════════════════════════════════════════════════════════════════
# (a) 圍欄裡不可以有被拆開的編號
# ══════════════════════════════════════════════════════════════════════

def test_md1_a_no_identifier_inside_a_fence_is_split_by_inline_markup():
    """🔴 `MD1(a)` **圍欄裡的編號不可以被行內標記拆開。**

    ```
    UI**10**   => 解析器看到的是 'DB1'，**UI10 消失而不會有任何錯誤**
    **UI10**   => ✅ 合法，解析得出來
    ```
    ☠️ 而消失的那個編號**不會出現在「缺題」那一欄** ——
       假陰性長得跟「都做完了」一模一樣。
    ⚠️ 目前是**0 個實例**（那兩個命中是在描述這個規則）⇒ 這一題的價值是**預防**：
       🔑 它讓這一類寫法**在被寫進去的那一次**就紅，而不是在某天有人發現少了一個編號時。
    """
    hits, missing = _scan()
    assert not missing, (
        "掃描範圍裡有檔案不存在：%s\n" % missing
        + "☠️ **一份掃不到的檔案與一份乾淨的檔案，在結果上長得一樣**。")

    bad = [h for h in hits if h[4] not in ALLOW]
    assert not bad, (
        "圍欄裡有被行內標記拆開的編號：\n  "
        + "\n  ".join("%s:%d  %r\n      %s" % (r, ln, m, txt[:70])
                      for r, ln, m, txt, _k in bad)
        + "\n☠️ 解析器會**跳過**那個編號，而且不報錯 —— "
          "它不會出現在「缺題」那一欄。\n"
        + "⚠️ 若那一行是在**描述**這個失效模式（而不是犯它），"
          "請把它的鍵加進 `ALLOW` 並寫理由：\n"
        + "\n".join("    %r: \"…\"," % h[4] for h in bad[:3]))


def test_md1_a_the_allowlist_does_not_rot():
    """⚙️ **反向控制：`ALLOW` 裡對不上任何一行的條目 => 紅。**

    ☠️ 少了它，這道守門可以靠**把每一個命中都加進白名單**變綠 ——
       而那時它看起來跟「一個實例都沒有」一模一樣。
    🔑 〈守門要驗有沒有人做過決定〉配的反向控制：
       **能被加進去的東西，必須也能被要求拿出來。**
    """
    hits, _missing = _scan()
    live = {h[4] for h in hits}
    stale = sorted(k for k in ALLOW if k not in live)
    assert not stale, (
        "`ALLOW` 有 %d 筆對不上任何一行：\n  " % len(stale)
        + "\n  ".join("%s  —— 理由：%s" % (k, ALLOW[k]) for k in stale)
        + "\n⇒ 那一行已經被改掉或刪掉了 ⇒ **請把這幾筆拿掉**。\n"
          "⚠️ 留著的話，下一個被加進去的例外會混在一堆過期條目裡，"
          "**而沒有人分得出哪些還算數**。")


def test_md1_a_the_scanner_catches_a_split_and_spares_a_wrapped_one():
    """⚙️ **儀器自檢：現在就該綠。**

    ☠️ 目前**0 個真實例** ⇒ 上面那題是綠的，而它綠可能有兩個理由：
    ```
    ① 真的沒有被拆開的編號          ✅
    ② **我的掃描器什麼都看不到**    ☠️
    ```
    🔑 ⇒ 用合成輸入分辨它們。⚠️ 誘餌是**合成的**不是 repo 裡真的那一行 ——
       釘在真實例上的正對照，會在那一行被改掉的那天失效。

    ⚙️ 而「**不可以擋到合法寫法**」那一半同樣要驗：
       `**UI10**`（標記在外面）解析得出來，擋掉它就是〈擋太早會讓功能不能用〉。
    """
    caught = "```\nTHIS: UI**10** DB1\n```"
    assert _SPLIT.search(_fenced_lines(caught)[0][1]), (
        "掃描器看不到 `UI**10**` —— **儀器壞了** ⇒ 上面那題的綠不可信。")

    for legal in ("**UI10** DB1", "`UI10` DB1", "UI10 DB1", "~~UI10~~ DB1"):
        block = "```\nTHIS: %s\n```" % legal
        assert not _SPLIT.search(_fenced_lines(block)[0][1]), (
            "掃描器把合法寫法 %r 報成缺陷 ——\n" % legal
            + "☠️ 那個方向更糟：**它會讓人去改一段寫對的文件**，"
              "而 `**UI10**` 解析得出來。")

    outside = "UI**10** 這一行不在圍欄裡"
    assert not _fenced_lines(outside), (
        "圍欄外的行也被收進來了 —— **範圍比解析器大** ⇒ 會報出解析器根本不看的東西。")


# ══════════════════════════════════════════════════════════════════════
# (b) 解析 .md 的守門，要先正規化再比對
# ══════════════════════════════════════════════════════════════════════

_SPEC_COVERAGE = "test_spec_coverage_2026_09_21"


def _fake_scope(tmp_path, body):
    p = tmp_path / "SCOPE.md"
    p.write_text("## THIS\n\n```\n%s\n```\n" % body, encoding="utf-8")
    return p


def _spec_coverage_module():
    """用**檔案路徑**載入那一支，不靠 `sys.path`。

    ⚠️ `import test_spec_coverage_2026_09_21` 會 `ModuleNotFoundError` ——
       `backend/tests/` 不是一個套件，pytest 自己有另一套載入方式。
    🔑 而那種紅的訊息會指向「模組不存在」，讀起來像**那支守門被刪了**。
    """
    import importlib.util
    path = Path(__file__).resolve().parent / (_SPEC_COVERAGE + ".py")
    assert path.exists(), (
        "找不到 `%s` —— 它是**唯一一支真的在解析 `.md` 的守門**"
        "（`SCOPE.read_text()` 兩處）。\n" % path.name
        + "⚠️ 檔名改了 **退回給我**；而它若真的被刪了，`MD1(b)` 就沒有對象了。")
    spec = importlib.util.spec_from_file_location("_md1b_target", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _parse_with(monkeypatch, tmp_path, body):
    mod = _spec_coverage_module()
    monkeypatch.setattr(mod, "SCOPE", _fake_scope(tmp_path, body))
    return mod._scope_sections()["THIS"]


def test_md1_b_the_scope_parser_still_sees_a_split_identifier(monkeypatch,
                                                             tmp_path):
    """🔴🔴 `MD1(b)` **解析 `SCOPE.md` 的那支守門，要先剝掉行內標記再比對。**

    ```
    餵它  'UI**10** DB1'
    現況  解析出 ['DB1']        <= **UI10 消失，而不報錯**
    ```
    ☠️ 那個編號從此**不在任何一份清單上** —— 而打包關門讀的正是這份清單
       ⇒ 它會說「這一包該全綠的都綠了」，**而少算了一個**。
    🔑 〈散文對工具是隱形的〉第六種：**寫對了地方，而字被拆開。**

    ⚙️ 兩個正對照都在下面那一題：**合法寫法本來就看得到**（證明我的假檔能被解析），
       而少了它，一個「永遠回空」的解析器也會讓這一題紅 —— 紅得理直氣壯而理由是假的。
    """
    got = _parse_with(monkeypatch, tmp_path, "UI**10** DB1")
    assert "UI10" in got, (
        "解析 `UI**10** DB1` 得到 %s —— **`UI10` 不見了**。\n" % sorted(got)
        + "☠️ 它從此不在任何一份清單上，而打包關門讀的正是這份清單。\n"
        + "⇒ 需要一支共用的正規化：比對前剝掉 `**` `*` `` ` `` `~~` `_`。\n"
          "⚠️ 名字可以換（**退回給我**），而它必須在**讀進來之後、比對之前**。")


def test_md1_b_the_probe_itself_parses_a_legal_line(monkeypatch, tmp_path):
    """⚙️ **正對照：合法寫法本來就解析得出來。**

    ☠️ 少了它，上一題可能紅在**我的假 `SCOPE.md` 根本沒被解析** ——
       而訊息會說「`UI10` 不見了」，**那句話是對的而理由是假的**。
    🔑 〈探針與被測對象糾纏〉：訊息的指向是我當初的假設，不是這次的證據。
    """
    got = _parse_with(monkeypatch, tmp_path, "**UI10** DB1")
    assert {"UI10", "DB1"} <= got, (
        "連合法寫法都解析不出來（得到 %s）——\n" % sorted(got)
        + "**我的假 SCOPE.md 沒有被當成 `THIS` 區塊解析** ⇒ 上一題的紅不可信。")


def test_md1_b_normalising_must_not_invent_identifiers(monkeypatch, tmp_path):
    """⚙️ **反向控制：剝掉標記之後不可以多出編號來。**

    ☠️ 一支剝得太用力的正規化會把不相干的東西黏成編號：
    ```
    '看 UI 的 10 分鐘'  ——若把空白也一起吃掉—— => 'UI10'
    ```
    🔑 而那個方向的後果是**幽靈編號**：清單上出現一個沒有人建立過的項目，
       而它永遠找不到對應的題 ⇒ **守門每天紅，理由是假的。**
    📌 這一題現在就該綠，而它在 `MD1(b)` 實作之後才真正開始工作。
    """
    got = _parse_with(monkeypatch, tmp_path, "看 UI 的 10 分鐘，還有 DB1")
    assert "UI10" not in got, (
        "從「看 UI 的 10 分鐘」解析出了 `UI10` ——\n"
        + "☠️ 正規化剝過頭 ⇒ **幽靈編號**：清單上出現一個沒有人建立過的項目，"
          "而它永遠找不到對應的題。")
    assert "DB1" in got, (
        "連 `DB1` 都沒解析出來（得到 %s）—— 這一題的對照失效。" % sorted(got))
