# -*- coding: utf-8 -*-
"""PDF 內嵌腳本註冊表（H2-a）：渲染硬化的 CSP `script-src` **只**認這裡登記的腳本（預先算好的 SHA-256），不再掃最終 HTML。

[單位] helper:pdf_scripts    [層] L1    [穩定度] 實作
[公開介面] FIT_A4_MULTI, FIT_A4_SINGLE, NETPLAN_FIT, PAYSLIP, SCRIPTS, allowed_hashes, hash_of, inner_text
[不變式] 每一支腳本都是**靜態文字**（沒有任何單據資料夾進腳本）；常數是完整的 `<script>…</script>` 標籤字串，builder 以 `+` 串接，輸出與改版前逐位元相同。
    新增內嵌腳本＝在這裡登記（守門題：builder 檔案裡不得再出現未登記的 `<script` 字面值；預覽專用的腳本不經 Edge，列在守門題的白名單）。
[契約題] tests/test_pdf_hardening_h2_2026_10_14.py
"""
import base64
import hashlib
import re

FIT_A4_MULTI = '<script>\nwindow.addEventListener("load",function(){\n  var r=document.getElementById("root");if(!r)return;\n  var A4H=Math.round(267/25.4*96);\n  var h=r.scrollHeight;\n  if(h>A4H){var s=A4H/h;if(s>=0.70){document.body.style.zoom=s.toFixed(4);}}\n});\n</script>'

FIT_A4_SINGLE = '<script>window.addEventListener("load",function(){var r=document.getElementById("root");if(!r)return;var A4H=Math.round(267/25.4*96);var h=r.scrollHeight;if(h>A4H){var s=A4H/h;if(s>=0.70){document.body.style.zoom=s.toFixed(4);}}});</script>'

PAYSLIP = '<script>\nwindow.addEventListener("load",function(){\n  var r=document.getElementById("root");if(!r)return;\n  var A4H=Math.round(297/25.4*96);\n  var h=r.scrollHeight;\n  if(h>A4H){var s=A4H/h;if(s>=0.50){r.style.zoom=s.toFixed(4);}}\n});\n</script>'

NETPLAN_FIT = '<script>\nfunction fitPageToContent() {\n  var board = document.querySelector(".board");\n  var wrap = document.querySelector(".wrap");\n  if (board && wrap) {\n    wrap.style.maxWidth = Math.ceil(board.getBoundingClientRect().width) + "px";\n  }\n  var w = Math.ceil(document.documentElement.scrollWidth);\n  var h = Math.ceil(document.documentElement.scrollHeight) + 16;\n  var style = document.createElement("style");\n  style.textContent = "@page { size: " + w + "px " + h + "px; margin: 0; } body { margin: 0; }";\n  document.head.appendChild(style);\n}\nvar loaded = new Promise(function (res) {\n  if (document.readyState === "complete") res();\n  else window.addEventListener("load", res);\n});\nvar fontsReady = (document.fonts && document.fonts.ready) ? document.fonts.ready : Promise.resolve();\nPromise.all([loaded, fontsReady]).then(fitPageToContent);\n</script>'

#: 名稱 ⇒ 完整標籤
SCRIPTS = {"fit_a4_multi": FIT_A4_MULTI, "fit_a4_single": FIT_A4_SINGLE, "payslip": PAYSLIP, "netplan_fit": NETPLAN_FIT}


def inner_text(tag: str) -> str:
    """`<script>…</script>` 標籤的內文（瀏覽器算雜湊的就是這段文字）。"""
    m = re.fullmatch(r"<script>(.*)</script>", tag, re.S)
    return m.group(1) if m else ""


def hash_of(inner: str) -> str:
    """CSP 的雜湊來源表達式：`'sha256-<base64>'`。"""
    return "'sha256-%s'" % base64.b64encode(hashlib.sha256(inner.encode("utf-8")).digest()).decode("ascii")


def allowed_hashes() -> list:
    """已登記腳本的 CSP 雜湊（依名稱排序，穩定）。"""
    return [hash_of(inner_text(SCRIPTS[k])) for k in sorted(SCRIPTS)]
