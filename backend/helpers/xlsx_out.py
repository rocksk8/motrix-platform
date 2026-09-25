# -*- coding: utf-8 -*-
"""L1 輸出：Excel 樣式、公式注入防護、匯出速率限制（ROADMAP A8／DEPENDENCY-MAP §3 #10 #13）。

原本放在 `routers/reports.py`（M08），而 M05 cashier、M06 accounting_export 為了這幾支
直接 import M08 的 router ⇒ L2 互相依賴。內容逐字搬移，行為不變（搬移前後同資料的 xlsx
值與樣式逐格相同）。

🔴 匯出冷卻的 dict **只有這一份、只有這一個名字**：報表、出納、T100 共用同一個冷卻
（與搬移前相同）。測試每題重置它：`tests/conftest.py` 的 `client` fixture 指名這裡的
`_export_times`——不在 reports 留同名 alias，否則重置的是別名、冷卻照留（〈守門守的對象被搬走〉）。
"""
import threading
import time

from fastapi import HTTPException
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

EXCEL_COOLDOWN = 5   # seconds — fast generation, just prevent double-clicks
PDF_COOLDOWN   = 30  # seconds — Edge headless is resource-intensive
_export_times: dict = {}
_export_lock = threading.Lock()


def check_export_rate(user_id: int, fmt: str) -> None:
    """Raise 429 if this user exported this format within the cooldown window."""
    cooldown = PDF_COOLDOWN if fmt == "pdf" else EXCEL_COOLDOWN
    with _export_lock:
        key = (user_id, fmt)
        last = _export_times.get(key, 0.0)
        wait = cooldown - (time.monotonic() - last)
        if wait > 0:
            raise HTTPException(429, f"請等待 {int(wait) + 1} 秒後再次匯出")
        _export_times[key] = time.monotonic()


def xl_style(wb):
    """Return reusable style factory."""
    def f(bold=False, size=9, color="000000", wrap=False, italic=False):
        return Font(name="微軟正黑體", bold=bold, size=size, color=color, italic=italic)
    def fill(hex_color):
        return PatternFill("solid", fgColor=hex_color)
    def border():
        s = Side(style="thin", color="D1D5DB")
        return Border(left=s, right=s, top=s, bottom=s)
    def al(h="left", v="center", wrap=False):
        return Alignment(horizontal=h, vertical=v, wrap_text=wrap)
    return f, fill, border, al


# openpyxl 會把「開頭是 =/+/-/@ 的字串」自動當成公式寫入（Cell.value 的
# bind_value() 行為），不是單純字面字串——只要使用者能在客戶名稱/專案名稱/
# 款項備注/發票號碼/承攬商名稱/料件名稱等任一自由文字欄位填入
# `=HYPERLINK(...)` 或舊式 DDE payload，之後任何人匯出本報表 Excel 並在
# Excel 開啟，就可能觸發公式/連結（CWE-1236，CSV/Formula Injection 同類
# 手法對 xlsx 一樣有效）。PDF/HTML 路徑已經用 html.escape() 處理過這類風險
# （見 reports._build_report_html() 的 esc()），這裡比照同樣的防禦精神，把觸發字元
# 開頭的字串前面補一個單引號讓 openpyxl 存成純文字。
XL_FORMULA_TRIGGERS = ("=", "+", "-", "@")


def xl_safe(val):
    if isinstance(val, str) and val[:1] in XL_FORMULA_TRIGGERS:
        return "'" + val
    return val


def set_row(ws, row_idx, values, font=None, fill=None, border=None, aligns=None, height=None):
    for ci, val in enumerate(values, 1):
        cell = ws.cell(row=row_idx, column=ci, value=xl_safe(val))
        if font:   cell.font   = font
        if fill:   cell.fill   = fill
        if border: cell.border = border
        if aligns and ci - 1 < len(aligns):
            cell.alignment = aligns[ci - 1]
        elif aligns and len(aligns) == 1:
            cell.alignment = aligns[0]
    if height:
        ws.row_dimensions[row_idx].height = height
