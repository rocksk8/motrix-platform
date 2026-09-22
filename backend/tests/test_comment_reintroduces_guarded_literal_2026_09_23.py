# -*- coding: utf-8 -*-
"""`QA2` · **註解裡不可以重新引入被守門 grep 的字面值**。

A 派工 `cf8ebad`：
```
成因：B 說這是第八次；規則已在 §6 而它下一個小時照樣踩 => **它需要工具不是記得**
⚠️ 反向控制：誘餌（故意留著、標明不可刪）必須被抓到
⚠️ 而 C 那道絆線的誤報**永遠不會被觀測到**（B 會預先避開）
   => QA2 要能分辨「沒有人違規」與「沒有人敢那樣寫」，寫不出來就明著標
```

---

# 🔴 A 點的那一格我**做不到**，所以我明著標

```
要分辨的兩件事
  ① 沒有人違規            => 掃描結果 0
  ② **沒有人敢那樣寫**    => 掃描結果**也是 0**
```
☠️ 兩者在**目前這棵樹上**的輸出完全相同 ⇒ **一次掃描分不出來**。
🔑 而它們不是同一種東西：
```
① 守門有效
② 守門在**收租**：它改變了別人怎麼寫註解，而那個改變不留痕跡
   （刪掉／改寫一段解釋，`git log` 上看起來只是「整理文件」）
```

## ⇒ 我能做到的是**把它變成看得見的**，不是分辨它

```
⚙️ 誘餌       故意留一段「合法而長得像違規」的註解 => **必須不被抓到**
              => 它證明這道守門**允許人寫解釋**
🔴 而分辨 ①② 需要的是**歷史**：`git log -S` 看那些字面值是不是曾經在註解裡出現過又消失
   ⇒ 那是一次性的調查，不是一道守門（〈量它不等於修它〉：先量，別急著修）
```
📌 ⇒ **本檔不宣稱它分得出 ①②。** 那一格由人做一次調查，我把指令寫在下面那題裡。
"""
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent
_BACKEND = _ROOT / "backend"

#: 被守門 grep 的字面值 ⇒ `字面值 -> (守它的那道題, 為什麼註解裡寫它會出事)`。
#: 🔴 **只列真的有守門在 grep 的**，不列假想的。
GUARDED = {
    "JOIN account_items": (
        "test_voucher_freeze_2026_09_23.py::test_no_voucher_print_path_joins…",
        "④ 凍結的結構絆線掃 routers/helpers 的 voucher 檔"),
    "localStorage.getItem('token')": (
        "test_frontend_session_key_2026_09_23.py",
        "session 鍵名不變量掃 frontend/js 與 pages"),
}

#: 那幾道守門**實際掃描**的檔案。註解裡寫那個字面值只有在這些檔裡才有後果。
SCANNED = {
    "JOIN account_items": [
        _BACKEND / "helpers" / "voucher.py",
        _BACKEND / "routers" / "vouchers.py",
    ],
    "localStorage.getItem('token')": (
        sorted((_ROOT / "frontend" / "js").glob("*.js"))
        + sorted((_ROOT / "frontend" / "pages").glob("*.html"))),
}


def _comment_spans_py(src):
    """`#` 之後到行尾，以及 docstring —— 回傳 `(行號, 內容)`。"""
    import io
    import tokenize
    out = []
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except Exception:                                      # noqa: BLE001
        return out
    for t in toks:
        if t.type in (tokenize.COMMENT, tokenize.STRING):
            out.append((t.start[0], t.string))
    return out


def _comment_spans_js(src):
    out, i, n, in_s = [], 0, len(src), None
    line = 1
    while i < n:
        ch = src[i]
        if ch == "\n":
            line += 1
            i += 1
            continue
        if in_s:
            if ch == "\\":
                i += 2
                continue
            if ch == in_s:
                in_s = None
            i += 1
            continue
        if ch in "\"'`":
            in_s = ch
            i += 1
            continue
        if src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append((line, src[i:j]))
            i = j
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append((line, src[i:j]))
            line += src.count("\n", i, j)
            i = j
            continue
        i += 1
    return out


def _spans(path):
    src = path.read_text(encoding="utf-8", errors="replace")
    return (_comment_spans_py(src) if path.suffix == ".py"
            else _comment_spans_js(src))


def test_qa2_no_comment_reintroduces_a_guarded_literal():
    """🔴 `QA2` **被守門 grep 的字面值，不可以出現在它掃描的那些檔的註解裡。**

    ☠️ 症狀是**紅燈指著一段寫對的碼**，而那一段正是在解釋「為什麼不那樣寫」：
    ```
    // ☠️ 我原本寫 localStorage.getItem('token') —— 它不會報錯，只是回 null
    ```
    🔑 B 說這是**第八次** —— 而規則已經寫進 `§6` 了。
       ⇒ 〈修作法不要修結果〉：**它需要工具不是記得。**

    ⚠️ 而正確的長期處置是**兩邊都做**：
    ```
    守門那一側  剝掉註解再比對（我已經做了兩道）
    寫碼這一側  **不要在被掃的檔裡逐字重寫那個字面值**
    ```
    📌 只做前者的話，下一道新守門忘了剝註解就再踩一次。
    """
    bad = []
    for literal, files in SCANNED.items():
        who, why = GUARDED[literal]
        for p in files:
            if not p.exists():
                continue
            for ln, text in _spans(p):
                if literal in text:
                    bad.append("%s:%d\n      %s\n      （守它的是 %s）"
                               % (p.relative_to(_ROOT).as_posix(), ln,
                                  text.strip().splitlines()[0][:66], who))
    assert not bad, (
        "註解裡重新引入了被守門 grep 的字面值：\n  " + "\n  ".join(bad)
        + "\n☠️ 那會讓那道守門**亮在一段寫對的碼上** ——\n"
          "   而最糟的後果不是誤報，是**寫的人會刪掉那段解釋讓守門閉嘴**。\n"
        + "✅ 換一種講法（描述它，不要逐字重寫它）就可以了。")


def test_qa2_a_legitimate_explanation_is_not_flagged():
    """⚙️ **誘餌：一段「合法而長得像違規」的註解必須不被抓到。**

    ☠️ 少了它，這道守門可以靠**把描述寫得更嚴**變綠 ——
       而那就變成「不准解釋」，比原本的問題更糟。
    ⚙️ 誘餌用**合成字串**不是 repo 裡真的那一行：
       釘在真實例上的正對照，會在那一行被改掉的那天失效
       （今晚已經發生過一次：我引用的一段真註解，複查時已被 B 改寫）。
    """
    ok = "# 這裡刻意不去連接 account_items 取名稱 —— 見 §六(3)"
    assert not any(lit in ok for lit in GUARDED), (
        "合法的解釋被判成違規：%r ——\n" % ok
        + "☠️ 那會變成「不准解釋」，比原本的問題更糟。")

    bait = "# 舊寫法：JOIN account_items ai ON ai.code = l.account_code"
    assert any(lit in bait for lit in GUARDED), (
        "掃描器看不到誘餌 %r —— **儀器壞了** ⇒ 上一題的綠不可信。" % bait)


def test_qa2_the_guard_cannot_tell_compliance_from_self_censorship():
    """⚠️ **明著標出這道守門分不出的那一件事**（A 要求）。

    ```
    ① 沒有人違規          => 掃描結果 0
    ② **沒有人敢那樣寫**  => 掃描結果**也是 0**
    ```
    🔑 兩者在這棵樹上的輸出**完全相同** ⇒ 一次掃描分不出來。

    ## 🔴 我用歷史查過了，而**歷史也答不出來**

    ```
    $ git log --oneline -S "localStorage.getItem('token')" -- frontend/
      cefd6a5 fix(B): 科目樹頁面取不到 token 導致 401
      d8ce924 feat(B): FN1 會計科目樹頁面
    $ git show cefd6a5 -- frontend/js/account-items.js
      -  headers: { Authorization: 'Bearer ' + (localStorage.getItem('token') || '') },
    $ git log --oneline -S "JOIN account_items" -- backend/helpers backend/routers
      （空）
    ```
    ⇒ 那個字面值在**已提交的歷史**裡只當過**程式碼**（就是那個 bug），
      **從來沒有以註解的形式出現過。**

    ☠️ **而我親眼看過一次自我審查** —— B 在工作樹上寫了一段解釋它的註解，
       我複查時他已經改寫掉了。**那一次沒有進過任何一個 commit。**
    🔑 ⇒ `git log -S` **查不到它**：自我審查發生在提交之前。
    📌 ⇒ 結論比原本更強：**這道守門的誤報不但現在量不到，連事後也考古不到。**

    ⚠️ 而 ② 不是「大家很守規矩」，它是這道守門在**收租**：
       它改變了別人怎麼寫註解，而那個改變**連 git 都沒有。**

    ⚙️ 本題**永遠綠** —— 它存在的理由是讓這段話**在檔案裡**，
       而不是只在某一則訊息裡（〈散文對工具是隱形的〉：訊息會漏）。
    ⚠️ 而它不是一個藉口：**上面那題該做的事它做得到**（誘餌證明過）。
    """
    assert GUARDED, "被守的字面值清單是空的 —— 那樣整個 QA2 沒有對象。"
    assert set(GUARDED) == set(SCANNED), (
        "`GUARDED` 與 `SCANNED` 的鍵對不上：%s vs %s\n"
        % (sorted(GUARDED), sorted(SCANNED))
        + "☠️ 列了一個字面值而沒說它掃哪些檔 ⇒ **那一筆永遠是綠的**。")
    for literal, files in SCANNED.items():
        assert any(p.exists() for p in files), (
            "`%r` 宣稱掃的檔案一個都不存在：%s\n"
            % (literal, [p.name for p in files])
            + "☠️ **掃不到的檔案與乾淨的檔案，在結果上長得一樣。**")
