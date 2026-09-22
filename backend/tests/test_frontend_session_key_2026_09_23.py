# -*- coding: utf-8 -*-
"""前端讀登入 session **只能有一個鍵名**。

A 派工 2026-09-23：使用者開科目樹撞到 **401**，而**我那一題抓不到它**。

```
我寫的    直接打 API、帶 token => 200      ⇒ **端點是對的**
沒有人走的  **頁面自己那支 fetch**          ⇒ 前端取錯鍵名而全綠
```
🔑 〈證據的適用範圍〉：綠燈是真的，**而它證明的是另一件事**。
☠️ 而那個缺陷不會報錯：`localStorage.getItem('token')` 回 `null`
   ⇒ 送出 `Bearer ` ⇒ **401** ⇒ 頁面一片空白。

---

# 📏 實測（我自己量的，不是照 A 的數字）

```
'motrix_session'   **74** 次   <= 全站的形狀
'token'             **0** 次   <= B 已修；我讀到時是 1 次且在註解裡，而複查時那段註解也改寫掉了
'motrix_theme' 等   非 auth 的鍵，不在本題範圍
```

# ⚠️ 而掃描器**必須剝掉註解** —— 而這一條我要標明它的證據只有合成的

☠️ 不剝的話，這道守門會**罰寫下解釋的人**，而最糟的後果不是誤報，
   是**他會刪掉那段解釋讓守門閉嘴**。
📌 今晚同一個形狀已經發生過一次（傳票 ④ 的結構絆線，B 抓到的）。

## 🔴 而我原本在這裡引用了一個**現在不存在**的實例

```
我讀到時  account-items.js 的註解逐字寫著 `localStorage.getItem('token')`
我複查時  **B 已經把那段註解改寫掉了**（現在寫「不是一個同名的獨立鍵」）
⇒ 不剝註解掃 B 的檔，命中 0 => **那個實例證明不了任何事**
```
🔑 〈量測比變化慢＝輸出一印出來就過期〉：我沒有推論錯，**我引用的東西動了**。
⇒ ⇒ 剝註解的證據**只有下面那題的合成自檢**，而我不把它寫成「B 的檔證明了它」。
⚙️ 而 B 會**預先避開**這個形狀（他被同一種絆線咬過一次）——
   那表示這道守門的誤報**永遠不會被觀測到**，它只會靜靜改變別人怎麼寫註解。
"""
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent
_FRONTEND = _ROOT / "frontend"

#: 全站唯一的 session 鍵名。
SESSION_KEY = "motrix_session"

#: 看起來像「登入用」而**不是** `motrix_session` 的鍵名。
#: ⚠️ 只列這幾個 —— `motrix_theme` 那類不是 auth，列進來就是假陽性。
FORBIDDEN = ("token", "auth", "jwt", "access_token", "accessToken",
             "session", "motrix_token", "authorization")


def _js_sources():
    files = sorted(_FRONTEND.glob("js/*.js")) + sorted(_FRONTEND.glob("pages/*.html"))
    assert files, (
        "`frontend/js/*.js` 與 `frontend/pages/*.html` 一個都掃不到 ——\n"
        + "☠️ **一份掃不到的檔案與一份乾淨的檔案，在結果上長得一樣。**")
    return files


def _blank_comments(src):
    """把 `//…` 與 `/*…*/` 抹成等長空白（行號與欄位都不變）。

    🔴 **不剝的話這道守門會罰寫下解釋的人。**
    ⚠️ 而這句話的證據是**合成的**（見檔頭）：我原本引用的那段真實註解，
       複查時已經被 B 改寫掉了。
    ⚠️ 用等長空白不是刪掉：**行號要對得上**，否則訊息指錯行。
    ⚙️ 而字串不剝 —— `localStorage.getItem('token')` 裡的 `'token'` **就是字串**，
       剝掉它這道守門就什麼都看不到了。
    """
    out = list(src)
    i, n = 0, len(src)
    in_s = None
    while i < n:
        ch = src[i]
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
            for k in range(i, j):
                out[k] = " "
            i = j
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, j):
                if out[k] != "\n":
                    out[k] = " "
            i = j
            continue
        i += 1
    return "".join(out)


def _bad_keys(src):
    """回傳 `(行號, 鍵名, 該行)` —— 讀了不該讀的 localStorage 鍵。"""
    code = _blank_comments(src)
    pat = re.compile(
        r"""localStorage\s*\.\s*(?:get|set|remove)Item\s*\(\s*(['"])([^'"]+)\1""")
    hits = []
    for i, line in enumerate(code.splitlines(), 1):
        for m in pat.finditer(line):
            key = m.group(2)
            if key in FORBIDDEN:
                hits.append((i, key, line.strip()))
    return hits


def test_the_frontend_reads_the_session_from_one_key_only():
    """🔴 **前端讀登入 session 只能用 `motrix_session` 這個鍵。**

    ```
    localStorage.getItem('token')  => 回 **null**（那個鍵不存在）
                                   => 送出 `Bearer ` => **401**
                                   => 頁面一片空白，而**沒有任何錯誤訊息**
    ```
    ☠️ 而它在測試裡看不出來：直接打 API 帶 token 是 200 ——
       **端點是對的，錯的是頁面怎麼拿 token。**
    🔑 這一題釘的是**不變量**（全站同一個鍵），不是「那一支修好了」：
       釘後者的話，下一支新頁面照樣會再取錯一次。
    """
    bad = []
    for p in _js_sources():
        for ln, key, text in _bad_keys(p.read_text(encoding="utf-8", errors="replace")):
            bad.append("%s:%d  `%s`\n      %s"
                       % (p.relative_to(_ROOT).as_posix(), ln, key, text[:70]))
    assert not bad, (
        "有前端檔案讀了 `%s` 以外的登入鍵：\n  " % SESSION_KEY + "\n  ".join(bad)
        + "\n☠️ 那個鍵**不存在** ⇒ `getItem` 回 `null` ⇒ 送出 `Bearer `\n"
          "   ⇒ **401，而頁面一片空白、沒有任何錯誤訊息**。\n"
        + "✅ 全站的形狀是：`JSON.parse(localStorage.getItem('%s') || '{}').token`"
          % SESSION_KEY)


def test_the_session_key_really_is_the_one_the_rest_of_the_site_uses():
    """⚙️ **正對照：`motrix_session` 必須真的被大量使用。**

    ☠️ 少了它，把 `SESSION_KEY` 打錯（或全站改用別的鍵）之後，
       上面那題**照樣綠** —— 它只檢查「有沒有用禁用的鍵」。
    🔑 而它同時證明**掃描器讀得到真檔案**：若 `_js_sources()` 讀錯目錄，
       這一題會紅，而上面那題會**為了錯的理由綠**。
    """
    n = sum(p.read_text(encoding="utf-8", errors="replace").count(SESSION_KEY)
            for p in _js_sources())
    assert n > 40, (
        "`%s` 在前端只出現 %d 次（我量到 74）——\n" % (SESSION_KEY, n)
        + "🔑 要嘛全站換了鍵名（**那上面那題的禁用清單要重寫**），"
          "要嘛我掃錯目錄。")


def test_the_scanner_ignores_comments_but_not_code():
    """⚙️ **儀器自檢：註解裡提到不算，程式碼裡用了才算。**

    ☠️ 不剝註解的話，這道守門會**罰寫下解釋的人** ——
      而最糟的後果不是誤報，是**他會刪掉那段解釋讓守門閉嘴**。
    📌 今晚同一個形狀已經發生過一次（傳票 ④ 的結構絆線，也是 B 抓到的）。
    ⚠️ **本題是這件事唯一的證據** —— 我原本引用 `account-items.js` 的一段註解，
       而複查時 B 已經把它改寫掉了（見檔頭）。合成輸入不會被別人改掉。

    ⚙️ 而另一半同樣要驗：**字串不可以一起剝掉** ——
       `getItem('token')` 裡的 `'token'` 就是一個字串，剝了就什麼都看不到。
    """
    in_code = "const t = localStorage.getItem('token')\n"
    assert _bad_keys(in_code), (
        "掃描器看不到程式碼裡的 `getItem('token')` ——\n"
        + "☠️ **儀器壞了**（最可能是連字串一起剝掉了）⇒ 上面那題的綠不可信。")

    in_line_comment = "// 我原本寫 localStorage.getItem('token') —— 它不會報錯\n"
    assert not _bad_keys(in_line_comment), (
        "掃描器亮在 `//` 註解上 —— **它會罰寫下解釋的人**。")

    in_block_comment = "/* 舊寫法：localStorage.getItem('token') */\nvar x = 1\n"
    assert not _bad_keys(in_block_comment), (
        "掃描器亮在 `/* */` 註解上 —— **它會罰寫下解釋的人**。")

    ok_key = "const s = localStorage.getItem('motrix_session')\n"
    assert not _bad_keys(ok_key), (
        "掃描器把正確的鍵 `%s` 報成缺陷 ——\n" % SESSION_KEY
        + "☠️ 那個方向會讓人去改一段寫對的碼。")

    # ⚙️ 行號要對得上：註解抹成等長空白而不是刪掉。
    two = "// 註解 localStorage.getItem('token')\nconst t = localStorage.getItem('jwt')\n"
    hits = _bad_keys(two)
    assert hits and hits[0][0] == 2, (
        "命中回報在第 %r 行，而它在第 2 行 ——\n"
        % ([h[0] for h in hits] or None)
        + "☠️ 抹註解時把行數弄掉了 ⇒ **訊息會指錯行**。")
