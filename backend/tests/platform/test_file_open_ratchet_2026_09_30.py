# -*- coding: utf-8 -*-
"""附件預覽棘輪（P1，proposal-attachments-search-preview.md §7）：前端頁面與腳本不可以再用 `window.open(` 開檔案——
不論是 `createObjectURL` 的 blob 或 `/api/uploads/…?pt=` 的簽章連結；一律用共用元件 `MotrixFilePreview`
（static/file-preview.js）。P1 之後次數 ＝ 0，只准維持 0。

例外（明列，每一條寫理由）：
- `static/file-preview.js` 的 `openInNewTab`：出納勞報單簽回檔要保留「另開新分頁」；`window.open('', '_blank')` 必須在使用者手勢內同步呼叫，
  所以先開空白分頁、取到檔再導向 blob（只有 image／pdf）。它是元件的一部分，不是各頁自己實作。

正對照：量尺要抓得到合成的違規寫法；元件被各頁真的載入（每個用到 MotrixFilePreview 的頁面都有 script 標籤）。"""
import re
from pathlib import Path

_WINDOW_OPEN = re.compile(r"window\.open\(")
_FILE_HINT = re.compile(r"createObjectURL|/api/uploads/|uploads/\$\{|photo-token")
ALLOWED = {"frontend/static/file-preview.js"}


def violations(src, rel="x"):
    """原始碼 ⇒ [(行號, 片段)]：`window.open(` 後 200 字內出現 createObjectURL／uploads 路徑／photo-token。"""
    out = []
    for m in _WINDOW_OPEN.finditer(src):
        tail = src[m.start(): m.start() + 200]
        if _FILE_HINT.search(tail):
            out.append((src.count("\n", 0, m.start()) + 1, tail.split("\n")[0].strip()[:100]))
    return out


FRONTEND = Path(__file__).resolve().parents[3] / "frontend"      # tests/platform → tests → backend → repo


def _frontend_files():
    for base in ("pages", "js", "static"):
        for p in (FRONTEND / base).rglob("*"):
            if p.suffix in (".html", ".js") and "vendor" not in p.parts:
                yield p


def test_no_frontend_code_opens_files_with_window_open():
    bad, n = [], 0
    for p in _frontend_files():
        rel = "frontend/" + p.relative_to(FRONTEND).as_posix()
        if rel in ALLOWED:
            continue
        n += 1
        for line, frag in violations(p.read_text(encoding="utf-8"), rel):
            bad.append("%s:%d %s" % (rel, line, frag))
    assert n > 30, "量尺壞了：只掃到 %d 個檔" % n
    assert not bad, "用 window.open 開檔案（改用 MotrixFilePreview.openFile）：\n  " + "\n  ".join(bad)


def test_rc_ratchet_catches_the_old_patterns():
    blob = "window.open(URL.createObjectURL(await r.blob()), '_blank')"
    tok = "window.open(`/api/uploads/${file.path}?pt=${encodeURIComponent(token)}`, '_blank')"
    ok = "window.open('https://example.com/help', '_blank')"
    assert violations(blob) and violations(tok) and not violations(ok)


def test_every_page_using_the_component_loads_it():
    missing, using = [], 0
    for p in _frontend_files():
        if p.suffix != ".html":
            continue
        src = p.read_text(encoding="utf-8")
        js_src = ""
        for m in re.finditer(r'<script[^>]+src="\.\./js/([^"?]+)', src):       # 頁面載入的 ../js/*.js 也算（例：cashier.js）
            jp = FRONTEND / "js" / m.group(1)
            if jp.exists():
                js_src += jp.read_text(encoding="utf-8")
        if "MotrixFilePreview" in src.replace("static/file-preview.js", "") or "MotrixFilePreview" in js_src:
            using += 1
            if "static/file-preview.js" not in src:
                missing.append(p.name)
    assert using >= 8, "量尺壞了：只找到 %d 個用元件的頁面" % using
    assert not missing, "用了 MotrixFilePreview 卻沒載入 static/file-preview.js：%s" % missing
