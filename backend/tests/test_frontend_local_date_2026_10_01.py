# -*- coding: utf-8 -*-
"""前端日期棘輪（使用者 2026-10-01）：不准再用 UTC 日期當「今天」。

`new Date().toISOString().slice(0, 10)`／`.split('T')[0]`／`.substring(0, 10)` 取的是 **UTC** 日期；台灣 UTC+8，每天 00:00–08:00
會得到前一天（報價單 MQ-202610-002 在 10/01 01:03 建立、報價日期卻是 2026-09-30）。日期一律走 `static/motrix-date.js` 的
`MotrixDate`（本地時區）。真正的時間戳（`at: new Date().toISOString()`）不在此限——規則只抓「取出日期／月份的那一刀」。

另外：用到 `MotrixDate` 的頁面（含它載入的 frontend/js/*.js）必須載入 `static/motrix-date.js`。
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FRONT = os.path.join(ROOT, "frontend")

#: 取 UTC 日期／月份的寫法（逐一列舉，避免誤傷 toISOString() 當時間戳）
BAD = [
    re.compile(r"toISOString\(\)\s*\.\s*slice\(\s*0\s*,\s*(?:7|10)\s*\)"),
    re.compile(r"toISOString\(\)\s*\.\s*substring\(\s*0\s*,\s*(?:7|10)\s*\)"),
    re.compile(r"toISOString\(\)\s*\.\s*split\(\s*['\"]T['\"]\s*\)"),
    re.compile(r"toJSON\(\)\s*\.\s*slice\(\s*0\s*,\s*(?:7|10)\s*\)"),
]

#: 允許的檔案 ⇒ 理由（只准寫「為什麼它是對的」）
ALLOWED = {
    "frontend/static/motrix-date.js": "說明文字裡舉舊寫法當反例（註解）；程式本身不用",
}


def _files():
    for base, dirs, names in os.walk(FRONT):
        dirs[:] = [d for d in dirs if d != "vendor" and d != "node_modules" and d != "fonts"]
        for n in names:
            if n.endswith((".html", ".js")):
                yield os.path.join(base, n)


def _rel(p):
    return os.path.relpath(p, ROOT).replace(os.sep, "/")


def _read(p):
    with open(p, encoding="utf-8-sig", errors="replace") as f:
        return f.read()


def scan(sources):
    """{相對路徑: 原始碼} ⇒ [問題字串]。"""
    out = []
    for rel, src in sorted(sources.items()):
        if rel in ALLOWED:
            continue
        for i, line in enumerate(src.split("\n"), 1):
            if any(b.search(line) for b in BAD):
                out.append("%s:%d 用 UTC 日期當日期：%s ⇒ 改用 MotrixDate.today()／ymd()（static/motrix-date.js）" % (rel, i, line.strip()[:90]))
    return out


def test_no_utc_date_slicing_in_the_frontend():
    srcs = {_rel(p): _read(p) for p in _files()}
    assert srcs, "沒掃到任何前端檔（路徑錯？）"
    probs = scan(srcs)
    assert not probs, "前端還有用 UTC 日期當日期的寫法（台灣 00:00–08:00 會變前一天）：\n" + "\n".join(probs[:30])


def test_allowlist_entries_still_exist_and_still_need_it():
    for rel in ALLOWED:
        p = os.path.join(ROOT, rel)
        assert os.path.isfile(p), "白名單的檔案不在了：%s" % rel
        assert any(b.search(_read(p)) for b in BAD), "白名單的 %s 已經沒有那個寫法了 ⇒ 從 ALLOWED 刪掉" % rel


def test_pages_using_motrix_date_load_the_script():
    """頁面（或它載入的 frontend/js/*.js）用了 MotrixDate ⇒ 頁面一定要有 `<script src=…motrix-date.js>`。"""
    js_dir = os.path.join(FRONT, "js")
    js_using = {n for n in os.listdir(js_dir) if n.endswith(".js") and "MotrixDate" in _read(os.path.join(js_dir, n))}
    pages_dir = os.path.join(FRONT, "pages")
    missing = []
    for n in sorted(os.listdir(pages_dir)):
        if not n.endswith(".html"):
            continue
        s = _read(os.path.join(pages_dir, n))
        uses = "MotrixDate" in s or any(re.search(r'src="[^"]*/' + re.escape(j) + r'[^"]*"', s) for j in js_using)
        if uses and "motrix-date.js" not in s:
            missing.append(n)
    assert not missing, "這些頁面用了 MotrixDate 卻沒載入 static/motrix-date.js：%s" % missing


def test_motrix_date_is_loaded_right_after_auth_guard_and_before_any_inline_use():
    """載入順序：motrix-date.js 要在 auth-guard.js 之後、任何 Alpine／內嵌用法之前（head 裡）。"""
    pages_dir = os.path.join(FRONT, "pages")
    bad = []
    for n in sorted(os.listdir(pages_dir)):
        if not n.endswith(".html"):
            continue
        s = _read(os.path.join(pages_dir, n))
        if "motrix-date.js" not in s:
            continue
        i, j = s.find("auth-guard.js"), s.find("motrix-date.js")
        k = s.find("alpine")
        if not (0 <= i < j) or (k >= 0 and j > k):
            bad.append(n)
    assert not bad, "motrix-date.js 的載入順序不對（要在 auth-guard.js 之後、Alpine 之前）：%s" % bad


def test_reverse_controls_the_scanner_sees_the_old_patterns():
    """反向控制：舊寫法各種形狀都必須被抓到；時間戳用法與新寫法不可被誤抓。"""
    bad_srcs = {
        "a.html": "x = new Date().toISOString().slice(0, 10)",
        "b.js": "const t = d.toISOString().slice(0,7)",
        "c.js": "y = new Date().toISOString().split('T')[0]",
        "d.js": "z = new Date().toISOString()\n  .slice(0, 10)".replace("\n  ", ""),
        "e.js": "w = x.toJSON().slice(0,10)",
    }
    for rel, src in bad_srcs.items():
        assert scan({rel: src}), rel
    ok_srcs = {"f.js": "entry = { at: new Date().toISOString() }", "g.js": "d = MotrixDate.today()", "h.js": "s = v.paidAt.slice(0,10)"}
    for rel, src in ok_srcs.items():
        assert scan({rel: src}) == [], rel
    assert scan({"frontend/static/motrix-date.js": "// new Date().toISOString().slice(0, 10)"}) == []      # 白名單
