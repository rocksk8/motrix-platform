# -*- coding: utf-8 -*-
"""前端 JS 的分號自動補入（ASI）陷阱守門（T83 紅燈：sidebar.js 的 `_setMenuState('pending')` 後面接 `(window.motrixBootFetch || fetch)(…)`）。

專案的 JS 不寫行尾分號。下一行以 `(` 或 `[` 開頭、而上一行是「一個完整的運算式」（結尾是識別字、`)`、`]`、字串、數字、`++`／`--`）時，
JS **不會**補分號——兩行被解析成同一個運算式：

    _setMenuState('pending')
    (window.motrixBootFetch || fetch)('/api/platform/menu', …)     // ⇒ _setMenuState('pending')(window…) ⇒ TypeError

結果整個選單排版在真的瀏覽器裡都不會套用（e2e 全紅，單元測試與靜態斷言看不到）。這支守門逐行掃 frontend/static、frontend/js 與頁面的行內 `<script>`：
每一個「以 `(`／`[` 開頭的程式行」，它前一個有內容的程式行必須是「語句已經結束或還在等下文」的結尾——`;` `{` `}` `,` `(` `[` `=` `:` `?` `&&` `||` `=>` 與二元運算子，
或 `return`／`else` 等關鍵字（`return` 後換行會補分號，本來就安全）。修法：在 `(`／`[` 開頭的那一行最前面加 `;`（`;(window.motrixBootFetch || fetch)(…)`），或把上一行補分號。

守門的判準是「上一行的結尾」，不是「下一行的樣子」；字串、註解、範本字串、行內 script 的行號都先處理過（正對照見最後兩題）。
"""
import re
from pathlib import Path

import pytest

from core import paths as _paths

FRONTEND = Path(_paths.FRONTEND_DIR)

#: 上一行以這些結尾 ⇒ 語句已結束或還在等下文，下一行以 ( / [ 開頭是安全的
_SAFE_END = (";", "{", "}", ",", "(", "[", "=", ":", "?", "&", "|", "+", "-", "*", "/", "%", "<", ">", "!", "^", "~")
_SAFE_WORD = re.compile(r"(?:^|[^\w$.])(?:return|else|do|typeof|void|new|delete|in|of|case|throw|yield|await|instanceof)$")


def _code_lines(text):
    """把 JS 文字轉成「只剩程式」的行（行數不變）：註解拿掉、字串／範本字串內容換成 `S`。不處理 regex 字面值（掃描器可能被其中的引號騙過 ⇒ 見 _REGEX_NOTE）。"""
    out, cur = [], []
    i, n = 0, len(text)
    state = None                                          # None | "'" | '"' | "`" | "//" | "/*"
    while i < n:
        ch = text[i]
        two = text[i:i + 2]
        if ch == "\n":
            if state in ("//", "'", '"'):
                state = None                              # 單行字串／註解在換行結束（字串裡的續行 `\` 另算）
            out.append("".join(cur))
            cur = []
            i += 1
            continue
        if state is None:
            if two == "//":
                state = "//"; i += 2; continue
            if two == "/*":
                state = "/*"; i += 2; continue
            if ch in ("'", '"', "`"):
                state = ch; cur.append("S"); i += 1; continue
            cur.append(ch)
        elif state == "//":
            pass
        elif state == "/*":
            if two == "*/":
                state = None; i += 2; continue
        else:                                             # 字串／範本字串
            if ch == "\\":
                i += 2; continue
            if ch == state:
                state = None
        i += 1
    out.append("".join(cur))
    return out


def _inline_scripts(html):
    """頁面的行內 `<script>`（沒有 src）：回 [(起始行號, 內文)]；內文前補空行，讓行號與原檔一致。"""
    res = []
    for m in re.finditer(r"<script(?P<attrs>[^>]*)>(?P<body>.*?)</script>", html, re.S | re.I):
        if re.search(r"\bsrc\s*=", m.group("attrs"), re.I):
            continue
        if re.search(r"type\s*=\s*[\"'](?!text/javascript|module)", m.group("attrs"), re.I):
            continue                                      # application/json、text/template 等不是程式
        line0 = html.count("\n", 0, m.start("body"))
        res.append((line0, "\n" * line0 + m.group("body")))
    return res


def hazards(js_text):
    """回 [(行號, 上一行結尾, 本行開頭)]：本行以 ( 或 [ 開頭，而上一個有內容的程式行不是安全結尾。"""
    lines = _code_lines(js_text)
    bad = []
    prev = ""
    for no, raw in enumerate(lines, 1):
        s = raw.strip()
        if not s:
            continue
        if s[0] in "([" and prev:
            safe = prev.endswith(_SAFE_END) and not prev.endswith(("++", "--")) or bool(_SAFE_WORD.search(prev))
            if not safe:
                bad.append((no, prev[-40:], s[:50]))
        prev = s
    return bad


def _files():
    for d in ("static", "js"):
        for p in sorted((FRONTEND / d).glob("*.js")):
            yield p
    from core import source_tree
    for p in source_tree.page_files():                    # frontend/pages ∪ modules/*/pages
        yield p


def _scan(p):
    text = p.read_text(encoding="utf-8", errors="replace")
    if p.suffix == ".html":
        return [h for _l, body in _inline_scripts(text) for h in hazards(body)]
    return hazards(text)


def test_no_line_starting_with_paren_or_bracket_follows_a_complete_expression():
    found = {}
    for p in _files():
        if "vendor" in p.parts:
            continue
        h = _scan(p)
        if h:
            found[p.relative_to(FRONTEND).as_posix()] = h
    assert not found, "下一行以 ( 或 [ 開頭、上一行沒有結尾分號 ⇒ 兩行會被黏成同一個運算式（在該行最前面加 `;`）：\n" + "\n".join(
        "  %s:%d  …%s ⏎ %s" % (f, no, a, b) for f, hs in found.items() for no, a, b in hs)


def test_the_scan_really_covers_the_files_it_claims():
    """前提：掃得到檔案，且 sidebar.js 在其中（守門不可以因為路徑不對而空綠）。"""
    names = {p.name for p in _files()}
    assert "sidebar.js" in names and "auth-guard.js" in names and len(names) > 100, len(names)


# ── 正對照：掃描器抓得到真的陷阱，也放過安全的寫法 ───────────────────────────
def test_positive_control_flags_the_exact_sidebar_pattern():
    snippet = "function f() {\n  var my = ++seq\n  _setMenuState('pending')\n  (window.motrixBootFetch || fetch)('/api/x', {})\n}\n"
    assert [h[0] for h in hazards(snippet)] == [4]
    assert [h[0] for h in hazards("a = b\n[1, 2].forEach(f)\n")] == [2]
    assert [h[0] for h in hazards("i++\n(f)()\n")] == [2]
    assert [h[0] for h in hazards("x = 'a;'\n(f)()\n")] == [2], "字串裡的分號不算結尾"
    assert [h[0] for h in hazards("foo() // 註解;\n(f)()\n")] == [2], "註解裡的分號不算結尾"


def test_scanner_lets_safe_patterns_through():
    ok = [
        "a()\n;(f || g)()\n",                               # 開頭分號
        "a();\n(f || g)()\n",                               # 上一行有分號
        "if (!s) return\n(f || g)('/x')\n",                 # return 後換行會補分號
        "try { x() }\ncatch (e) { y = {} }\n(f || g)()\n",  # 區塊結尾
        "var a = [\n  1,\n  2\n]\n",                         # 行首的 ] 不算（只看 ( 與 [ 開頭）
        "foo(1,\n  (2 + 3),\n  [4])\n",                      # 引數換行
        "x = a ||\n  (b && c)\n",                            # 運算子結尾
        "const t = `\n(not code)\n`\n(f)()\n".replace("`\n(f)()", "`;\n(f)()"),   # 範本字串內的行不是程式
        "/* ( */\n(f)()\n",                                  # 開頭是註解的行不算
    ]
    for src in ok:
        assert hazards(src) == [], (src, hazards(src))
