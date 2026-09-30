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


# ══════════════════════════════════════════════════════════════════════════════
# 匯出稽核＋PDF 姊妹端點（使用者規則 2026-09-30，第 27 班）
#   「每一個 Excel 匯出都要同時提供 PDF；每一次匯出都要留紀錄。」
#
# - `@export_logged("xlsx", module=…, name=…)`：包在 xlsx 匯出端點外，成功後寫一筆稽核（action `export.xlsx`）；
#   detail 只有 module／name／篩選摘要／列數，**不含任何個資值**（`summarize_filters`：只留數字、布林、短 ASCII 字串；其餘只記「<text:N>」「<list:N>」）。
# - `add_pdf_sibling(router, path, handler, …)`：註冊 xlsx 端點的 PDF 姊妹：用**同一個處理函式**（同參數、同篩選、同權限、同資料）
#   取得 xlsx，再把每個分頁轉成 HTML 表格，走既有的 Edge headless（`pdf_gen.html_to_pdf_bytes`）；套用公司資料第二道閘門（`require_for_output`）；
#   寫 `export.pdf` 稽核；PDF 冷卻 30 秒。姊妹不消耗 xlsx 的 5 秒冷卻。
# - 守門：tests/platform/test_export_pdf_and_audit_2026_09_30.py（AST）——每個回 xlsx 的端點都要有 export_logged 與 PDF 姊妹。
# ══════════════════════════════════════════════════════════════════════════════
import contextvars
import functools
import html as _html
import inspect
import io as _io
import re as _re
from datetime import date as _date, datetime as _datetime

_SKIP_EXCEL_RATE = contextvars.ContextVar("motrix_skip_excel_rate", default=False)
_SAFE_SCALAR = _re.compile(r"^[A-Za-z0-9_\-./:+]{0,40}$")
_FILTER_SKIP = {"authorization", "request", "response", "conn"}
PDF_MAX_ROWS = 4000            # 每個分頁最多轉幾列（防超大 PDF）
XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_check_export_rate_orig = check_export_rate


def check_export_rate(user_id: int, fmt: str) -> None:            # noqa: F811 — 包一層：PDF 姊妹呼叫 xlsx 處理函式時略過 xlsx 冷卻
    if fmt != "pdf" and _SKIP_EXCEL_RATE.get():
        return
    _check_export_rate_orig(user_id, fmt)


def summarize_filters(params) -> dict:
    """篩選條件摘要（寫進稽核）：數字／布林原樣；短 ASCII 字串（日期、代碼、期別）原樣；其他字串只記長度；清單只記筆數；dict 攤平成 `父.子`。
    ⇒ 不會把姓名、統編、備註等自由文字寫進稽核。"""
    out = {}

    def walk(prefix, v):
        if v is None or prefix.split(".")[-1] in _FILTER_SKIP:
            return
        if hasattr(v, "model_dump"):
            v = v.model_dump()
        if isinstance(v, dict):
            for k2, v2 in v.items():
                walk((prefix + "." if prefix else "") + str(k2), v2)
        elif isinstance(v, (bool, int, float)):
            out[prefix] = v
        elif isinstance(v, str):
            out[prefix] = v if _SAFE_SCALAR.match(v) else "<text:%d>" % len(v)
        elif isinstance(v, (list, tuple, set)):
            out[prefix] = "<list:%d>" % len(v)
    for k, v in (params or {}).items():
        walk(str(k), v)
    return out


def _response_bytes(resp):
    body = getattr(resp, "body", None)
    return bytes(body) if isinstance(body, (bytes, bytearray)) else None


def count_xlsx_rows(data) -> int:
    """xlsx 全部分頁的列數（唯讀模式；失敗 ⇒ 0）。"""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(_io.BytesIO(data), read_only=True)
        try:
            return sum(int(ws.max_row or 0) for ws in wb.worksheets)
        finally:
            wb.close()
    except Exception:                                           # noqa: BLE001
        return 0


def log_export(authorization, fmt: str, module: str, name: str, filters=None, rows=None, label: str = "") -> None:
    """寫一筆匯出稽核：action `export.xlsx`／`export.pdf`。永不丟例外（`_audit` 自己吞）。"""
    from helpers.audit import _audit
    from helpers.auth import _tok
    detail = {"module": module, "format": fmt, "filters": summarize_filters(filters), "rows": rows}
    _audit(_tok(authorization), "export." + fmt, "export", name, label or name, detail)


def export_logged(fmt: str, module: str, name: str, label: str = ""):
    """匯出端點的稽核裝飾器（同步／非同步都可）。端點必須回 `Response`（有 `.body` bytes）；串流回應請改回 `Response`。"""
    def deco(fn):
        def _after(resp, kw):
            data = _response_bytes(resp)
            log_export(kw.get("authorization"), fmt, module, name, kw, count_xlsx_rows(data) if (data and fmt == "xlsx") else None, label)
        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def wrapper(*a, **kw):
                resp = await fn(*a, **kw)
                _after(resp, kw)
                return resp
        else:
            @functools.wraps(fn)
            def wrapper(*a, **kw):
                resp = fn(*a, **kw)
                _after(resp, kw)
                return resp
        wrapper.__export_inner__ = fn
        wrapper.__export_meta__ = {"fmt": fmt, "module": module, "name": name}
        return wrapper
    return deco


def _decimals(nf) -> int:
    m = _re.search(r"\.(0+)", nf or "")
    return len(m.group(1)) if m else 0


def _fmt_cell(v, nf):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "是" if v else "否"
    if isinstance(v, (_datetime, _date)):
        return v.strftime("%Y-%m-%d %H:%M") if isinstance(v, _datetime) and (v.hour or v.minute) else v.strftime("%Y-%m-%d")
    if isinstance(v, (int, float)):
        nf = nf or ""
        dec = _decimals(nf)
        if "%" in nf:
            return "%.*f%%" % (dec, v * 100)
        if "," in nf:
            return "{:,.{d}f}".format(v, d=dec)
        if isinstance(v, int) or float(v).is_integer():
            return str(int(v))
        return "%.10g" % v
    return str(v)


def xlsx_to_html(data: bytes, title: str = "", max_rows: int = PDF_MAX_ROWS) -> str:
    """把 xlsx 的每個分頁轉成 HTML 表格（值、粗體、底色、對齊、合併儲存格、欄寬）。用在 PDF 姊妹。"""
    import openpyxl
    from openpyxl.utils import get_column_letter
    wb = openpyxl.load_workbook(_io.BytesIO(data))
    esc = _html.escape
    parts = ['<!doctype html><html><head><meta charset="utf-8"><style>'
             '@page{size:A4 landscape;margin:8mm}body{font-family:"Microsoft JhengHei","微軟正黑體",sans-serif;font-size:8pt;color:#111}'
             'h1{font-size:12pt;margin:0 0 2px}h2{font-size:10pt;margin:10px 0 4px;page-break-after:avoid}.meta{color:#666;font-size:7pt;margin-bottom:6px}'
             'table{border-collapse:collapse;width:100%;table-layout:auto}td{border:1px solid #d1d5db;padding:1px 3px;vertical-align:middle;word-break:break-all}'
             '.sheet{page-break-inside:auto}tr{page-break-inside:avoid}.trunc{color:#b45309;font-size:7pt;margin-top:3px}</style></head><body>']
    parts.append("<h1>%s</h1><div class='meta'>匯出時間 %s</div>" % (esc(title or "匯出"), _datetime.now().strftime("%Y-%m-%d %H:%M")))
    for ws in wb.worksheets:
        if ws.sheet_state != "visible":
            continue
        covered, spans = set(), {}
        for rng in ws.merged_cells.ranges:
            spans[(rng.min_row, rng.min_col)] = (rng.max_row - rng.min_row + 1, rng.max_col - rng.min_col + 1)
            for r in range(rng.min_row, rng.max_row + 1):
                for c in range(rng.min_col, rng.max_col + 1):
                    if (r, c) != (rng.min_row, rng.min_col):
                        covered.add((r, c))
        span_rows = {k[0] for k in spans}
        maxc = ws.max_column or 1
        widths = []
        for c in range(1, maxc + 1):
            letter = get_column_letter(c)
            w = ws.column_dimensions[letter].width if letter in ws.column_dimensions else None
            widths.append(float(w) if w else 10.0)
        tot = sum(widths) or 1.0
        parts.append("<div class='sheet'><h2>%s</h2><table><colgroup>%s</colgroup>" % (
            esc(ws.title), "".join("<col style='width:%.1f%%'>" % (100.0 * w / tot) for w in widths)))
        shown = 0
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row):
            if shown >= max_rows:
                break
            if all(c.value in (None, "") for c in row) and row[0].row not in span_rows:
                continue
            shown += 1
            tds = []
            for c in row:
                if (c.row, c.column) in covered:
                    continue
                rs, cs = spans.get((c.row, c.column), (1, 1))
                st = []
                if c.font is not None and c.font.b:
                    st.append("font-weight:bold")
                try:
                    if c.fill is not None and c.fill.fill_type == "solid":
                        rgb = c.fill.fgColor.rgb
                        if isinstance(rgb, str) and len(rgb) in (6, 8):
                            st.append("background:#%s" % rgb[-6:])
                except Exception:                                # noqa: BLE001
                    pass
                al = c.alignment.horizontal if c.alignment is not None else None
                if al in ("right", "center"):
                    st.append("text-align:" + al)
                elif isinstance(c.value, (int, float)) and not isinstance(c.value, bool):
                    st.append("text-align:right")
                txt = esc(_fmt_cell(c.value, c.number_format)).replace("\n", "<br>")
                tds.append("<td%s%s%s>%s</td>" % (" rowspan=%d" % rs if rs > 1 else "", " colspan=%d" % cs if cs > 1 else "",
                                                  " style='%s'" % ";".join(st) if st else "", txt))
            parts.append("<tr>%s</tr>" % "".join(tds))
        parts.append("</table>")
        if shown >= max_rows and ws.max_row > max_rows:
            parts.append("<div class='trunc'>（此分頁只列前 %d 列；完整資料請下載 Excel）</div>" % max_rows)
        parts.append("</div>")
    parts.append("</body></html>")
    return "".join(parts)


def _pdf_filename(resp, fallback: str) -> str:
    cd = (getattr(resp, "headers", None) or {}).get("content-disposition", "") or ""
    m = _re.search(r"filename\*=UTF-8''([^;]+)", cd)
    from urllib.parse import quote, unquote
    name = unquote(m.group(1)) if m else fallback
    name = _re.sub(r"\.xlsx$", "", name, flags=_re.I) + ".pdf"
    return quote(name)


def add_pdf_sibling(router, path: str, handler, *, module: str, name: str, title: str = "", method: str = "GET"):
    """註冊 xlsx 端點的 PDF 姊妹（見本節說明）。`handler` 是被 `@export_logged("xlsx", …)` 包過的 xlsx 端點函式。"""
    inner = getattr(handler, "__export_inner__", handler)

    def _finish(resp, kw):
        from fastapi import HTTPException
        from fastapi.responses import Response
        from helpers.auth import _require_user
        data = _response_bytes(resp)
        if not data:
            raise HTTPException(500, "匯出失敗：沒有取得 Excel 內容")
        user = _require_user(kw.get("authorization"))
        check_export_rate(user["id"], "pdf")
        from helpers.company_identity import require_for_output
        require_for_output()                                    # 公司資料第二道閘門（與其他 PDF 輸出一致）
        html = xlsx_to_html(data, title or name)
        try:
            import pdf_gen
            pdf = pdf_gen.html_to_pdf_bytes(html)
        except RuntimeError as e:
            raise HTTPException(503, str(e))
        except ValueError as e:
            raise HTTPException(500, str(e))
        log_export(kw.get("authorization"), "pdf", module, name, kw, count_xlsx_rows(data))
        return Response(pdf, media_type="application/pdf",
                        headers={"Content-Disposition": "attachment; filename*=UTF-8''" + _pdf_filename(resp, name)})

    if inspect.iscoroutinefunction(inner):
        @functools.wraps(inner)
        async def pdf_handler(*a, **kw):
            tok = _SKIP_EXCEL_RATE.set(True)
            try:
                resp = await inner(*a, **kw)
            finally:
                _SKIP_EXCEL_RATE.reset(tok)
            return _finish(resp, kw)
    else:
        @functools.wraps(inner)
        def pdf_handler(*a, **kw):
            tok = _SKIP_EXCEL_RATE.set(True)
            try:
                resp = inner(*a, **kw)
            finally:
                _SKIP_EXCEL_RATE.reset(tok)
            return _finish(resp, kw)
    pdf_handler.__name__ = inner.__name__ + "_pdf"
    pdf_handler.__qualname__ = inner.__qualname__ + "_pdf"
    pdf_handler.__doc__ = "PDF 姊妹：與 %s 同一個處理函式（同參數、同權限、同資料）。" % inner.__name__
    router.add_api_route(path, pdf_handler, methods=[method])
    return pdf_handler
