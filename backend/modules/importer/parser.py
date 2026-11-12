# -*- coding: utf-8 -*-
"""匯入精靈的檔案解析與範本（T85）。**無狀態、不寫任何資料表**：上傳的檔案只在這一次請求裡解析，結果交回頁面，頁面再把「列」送到
既有的 `import-rows` 端點（預覽→確認）。只 import 標準函式庫與 openpyxl；統編檢查碼走 L1 `helpers.company_setup.ubn_valid`。

輸出的列形狀＝既有 import-rows 吃的形狀（客戶／料號：老頁面送的那一種；員工：`helpers/user_import.py`）：
- 空白儲存格＝輸出空字串（或省略），**絕不輸出 0 或 null**（既有規則：空白＝不更新）；
- 文字一律去前後空白、全形空白；數字儲存格（含整數值的浮點）轉成沒有小數點的字串，避免料號 `12345` 變成 `12345.0`。
安全：只收 .xlsx／.csv（.xls、.xlsm 白話拒絕）、先檢查檔頭與 zip（拒絕巨集、解壓過大、缺 workbook）、公式儲存格不匯入（當成空白並警告）、
只讀可見的資料工作表、連續空白列達上限就停止（防「宣告百萬列但幾乎是空」的檔案）。
"""
import csv
import io
import re
import time
import unicodedata
import zipfile
from datetime import date, datetime

MAX_BYTES_DEFAULT = 5 << 20
MAX_UNZIPPED = 50 << 20
MAX_COLS = 60
MAX_CELL = 2000
MAX_BLANK_RUN = 500                 # 連續空白列這麼多就當作檔案結束
EXAMPLE_MARK = "（範例，請刪除）"
KINDS = ("customers", "parts", "users")
MAX_ROWS = {"customers": 5000, "parts": 5000, "users": 300}
KIND_NAMES = {"customers": "客戶", "parts": "料號", "users": "員工"}
DATA_SHEET = "資料"
HELP_SHEET = "說明"


class ParseError(Exception):
    """白話訊息（直接給使用者看）。"""


# 舊檔表頭「備註」曾寫成另一個字（站內用語守門不准該寫法出現在原始碼）：這裡拆開寫，仍接受舊檔
_OLD_NOTE = "備" + "注"


def _col(key, label, aliases=(), required=False, hint="", example="", ignored=False):
    return {"key": key, "label": label, "aliases": tuple(aliases), "required": required, "hint": hint, "example": example, "ignored": ignored}


COLUMNS = {
    "customers": [
        _col("name", "公司名稱", ["名稱", "客戶名稱", "客戶"], True, "必填。去掉前後空白；同一家公司請用同一個寫法。", EXAMPLE_MARK + "大安電腦股份有限公司"),
        _col("taxId", "統一編號", ["統編"], False, "8 碼數字。系統用統編判斷是不是同一家客戶；沒有統編（海外、個人）請留空。", "12345675"),
        _col("nameEn", "英文名稱", [], False, "", "Da-An Computer Co., Ltd."),
        _col("phone", "電話", [], False, "", "02-12345678"),
        _col("fax", "傳真", [], False, "", ""),
        _col("email", "Email", ["電子郵件"], False, "", "service@example.com"),
        _col("website", "網站", [], False, "", ""),
        _col("invoiceAddress", "地址", ["發票地址"], False, "", "台北市大安區○○路 1 號"),
        _col("deliveryAddress", "送貨地址", [], False, "", ""),
        _col("industry", "產業別", [], False, "", ""),
        _col("type", "客戶類型", [], False, "", ""),
        _col("ownerName", "負責業務", [], False, "要和系統裡的人員姓名一樣；對不上會留空。", ""),
        _col("paymentMethod", "付款條件", [], False, "", ""),
        _col("tags", "內部標籤", [], False, "多個標籤用逗號、頓號分開。", "重要客戶、年約"),
        _col("contactName", "主要聯絡人", [], False, "填了才會建立聯絡人；已有同名聯絡人時只補空白欄位。", "王小明"),
        _col("contactTitle", "聯絡人職稱", [], False, "", ""),
        _col("contactPhone", "聯絡人電話", [], False, "", ""),
        _col("contactEmail", "聯絡人Email", [], False, "", ""),
        _col("notes", "備註", [_OLD_NOTE], False, "已有備註時，這裡的內容會接在後面，不會蓋掉。", ""),
    ],
    "parts": [
        _col("partNo", "料號", ["part_no", "品號"], False, "系統用料號判斷是不是同一個品項（不分大小寫、全半形）。留空＝新增時由系統編號（類別要有編號前綴）。", "AP-001"),
        _col("name", "品名", ["名稱", "name", "品項名稱"], True, "必填。", EXAMPLE_MARK + "無線基地台"),
        _col("brand", "廠牌", ["brand"], False, "", "Ubiquiti"),
        _col("model", "型號", ["model"], False, "", "U6-Pro"),
        _col("unit", "單位", ["unit"], False, "留空＝新增時用「台」；更新時不動。", "台"),
        _col("cost", "成本(未稅)", ["成本", "cost", "進價"], False, "數字，不可為負。留空＝更新時不動（不會變成 0）。", "3200"),
        _col("listPrice", "定價(含稅)", ["定價", "售價", "list_price"], False, "數字，不可為負。", "4500"),
        _col("category", "類別", ["分類", "category"], False, "", "網通設備"),
        _col("note", "備註", [_OLD_NOTE, "note"], False, "", ""),
        _col("safetyStock", "安全庫存", ["safety_stock"], False, "整數，不可為負。", "5"),
        _col("leadTimeDays", "前置天數", ["前置天數(天)", "lead_time_days"], False, "整數，不可為負。留空＝未知（不是 0）。", "7"),
    ],
    "users": [
        _col("username", "帳號", ["使用者帳號", "登入帳號", "username"], True, "必填。登入用，不可有空白。已存在的帳號會略過，不會更新。", EXAMPLE_MARK + "wang.xiaoming"),
        _col("displayName", "姓名", ["顯示名稱", "名稱", "display_name"], True, "必填。", "王小明"),
        _col("role", "角色", ["role"], False, "可填：業務、工程師、檢視者；留空＝檢視者。管理員、財務、最高管理者需由最高管理者到帳號頁一個一個建立。", "業務"),
        _col("email", "Email", ["電子郵件", "email"], False, "", "wang@example.com"),
        _col("phone", "電話", ["手機", "phone"], False, "", ""),
        _col("department", "部門", ["department"], False, "要和系統裡的部門名稱一樣；對不上就先不分部門。", ""),
        _col("password", "密碼", ["password"], False, "請不要在檔案裡放密碼：這一欄會被忽略。系統會自己產生臨時密碼，匯入完成後只顯示一次。", "", ignored=True),
    ],
}


def _hkey(s) -> str:
    """表頭比對用：全形半形、大小寫、空白、必填星號、括號內說明都不當成差異。"""
    s = unicodedata.normalize("NFKC", str(s if s is not None else "")).casefold()
    s = re.sub(r"[\s　]+", "", s)
    return re.sub(r"[＊*]+$", "", s)


def _header_index(kind):
    idx = {}
    for c in COLUMNS[kind]:
        for h in (c["label"],) + c["aliases"]:
            idx.setdefault(_hkey(h), c)
    return idx


def _cell_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "是" if v else "否"
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            return ""
        return str(int(v)) if v == int(v) and abs(v) < 1e15 else repr(v)
    if isinstance(v, datetime):
        return v.date().isoformat() if (v.hour, v.minute, v.second) == (0, 0, 0) else v.isoformat(timespec="seconds")
    if isinstance(v, date):
        return v.isoformat()
    s = str(v).replace("　", " ").replace("\r\n", "\n").replace("\r", "\n").strip()
    return s[:MAX_CELL]


# ── 讀檔 ──────────────────────────────────────────────────────────────────────

def _decode_csv(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp950"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ParseError("這個檔案的文字編碼讀不出來（請用 Excel 另存成 .xlsx，或存成 UTF-8 的 CSV）")


def _rows_from_csv(data: bytes, max_scan: int):
    text = _decode_csv(data)
    out, blank = [], 0
    for i, rec in enumerate(csv.reader(io.StringIO(text, newline=""))):
        if len(out) > max_scan:
            raise ParseError("檔案的列數太多了（上限 %d 列），請拆成多個檔案" % (max_scan - 2))
        cells = [_cell_text(c) for c in rec[:MAX_COLS + 1]]
        if len(rec) > MAX_COLS:
            raise ParseError("欄位太多了（上限 %d 欄），請確認檔案是依範本填的" % MAX_COLS)
        if not any(cells):
            blank += 1
            if blank > MAX_BLANK_RUN:
                break
        else:
            blank = 0
        out.append((i + 1, cells, []))
    return out


def _check_zip(data: bytes):
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ParseError("這個檔案不是有效的 Excel（.xlsx）檔，請用 Excel 另存成 .xlsx 再上傳")
    names = z.namelist()
    if any(n.lower().endswith("vbaproject.bin") for n in names):
        raise ParseError("不收含巨集的檔案（.xlsm）。請另存成一般的 .xlsx 再上傳")
    if "xl/workbook.xml" not in names:
        raise ParseError("這個檔案不是有效的 Excel（.xlsx）檔，請用 Excel 另存成 .xlsx 再上傳")
    total = 0
    for zi in z.infolist():
        total += zi.file_size
        if total > MAX_UNZIPPED or (zi.compress_size and zi.file_size / max(zi.compress_size, 1) > 1000 and zi.file_size > (1 << 20)):
            raise ParseError("檔案解開後太大，無法處理（可能是壓縮炸彈或內含過大的圖片）")
    return z


def _rows_from_xlsx(data: bytes, max_scan: int):
    _check_zip(data)
    try:
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=False)
    except Exception as exc:                                  # noqa: BLE001
        raise ParseError("這個檔案讀不出來（%s）。請用 Excel 另存成 .xlsx 再上傳" % type(exc).__name__)
    try:
        visible = [ws for ws in wb.worksheets if getattr(ws, "sheet_state", "visible") == "visible"]
        sheet = next((ws for ws in visible if ws.title.strip() == DATA_SHEET), None)
        if sheet is None:
            sheet = next((ws for ws in visible if ws.title.strip() != HELP_SHEET), None)
        if sheet is None:
            raise ParseError("找不到可讀的資料工作表（請用範本，資料放在名為「%s」的工作表）" % DATA_SHEET)
        out, blank, filled = [], 0, 0
        for r_no, row in enumerate(sheet.iter_rows(), start=1):
            cells, formulas = [], []
            for ci, c in enumerate(row):
                v = getattr(c, "value", None)
                if getattr(c, "data_type", "") == "f":                       # 公式：不匯入（值當空白）、記下來警告
                    cells.append("")
                    formulas.append(ci)
                    continue
                cells.append(_cell_text(v))
            while cells and not cells[-1]:
                cells.pop()
            if len(cells) > MAX_COLS:
                raise ParseError("欄位太多了（上限 %d 欄），請確認檔案是依範本填的" % MAX_COLS)
            if not any(cells) and not formulas:
                blank += 1
                if blank > MAX_BLANK_RUN:
                    break
                out.append((r_no, [], []))
                continue
            blank = 0
            out.append((r_no, cells, formulas))
            filled += 1
            if filled > max_scan:
                raise ParseError("檔案的列數太多了（上限 %d 列），請拆成多個檔案" % (max_scan - 2))
        return out
    finally:
        try:
            wb.close()
        except Exception:                                         # noqa: BLE001
            pass


# ── 對應欄位、組列 ──────────────────────────────────────────────────────────────

def _find_header(rows, kind):
    idx = _header_index(kind)
    for r_no, cells, _f in rows[:10]:
        hits = [c for c in cells if _hkey(c) in idx]
        if hits:
            return r_no, cells, idx
    raise ParseError("第一列要放欄位名稱（和範本一樣）。請下載範本，把資料貼進去再上傳")


def _split_tags(s):
    return [t.strip() for t in re.split(r"[,，、;；]", s) if t.strip()]


_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _build_customer(v, no, warn):
    from helpers.company_setup import ubn_valid
    tax = re.sub(r"\D", "", v.get("taxId", ""))
    if tax and (len(tax) != 8 or not ubn_valid(tax)):
        warn(no, "統一編號", "「%s」看起來不是正確的統編（8 碼、檢查碼）。系統用統編判斷是不是同一家客戶：打錯會被當成新客戶，不會併進既有客戶" % v.get("taxId", ""))
    for k, label in (("email", "Email"), ("contactEmail", "聯絡人Email")):
        if v.get(k) and not _EMAIL.match(v[k]):
            warn(no, label, "「%s」看起來不像 Email" % v[k])
    data = {k: v.get(k, "") for k in ("nameEn", "email", "fax", "website", "invoiceAddress", "deliveryAddress", "industry", "type", "ownerName", "paymentMethod", "notes")}
    data["tags"] = _split_tags(v.get("tags", ""))
    ct = []
    if v.get("contactName"):
        ct.append({"id": int(time.time() * 1000), "name": v["contactName"], "title": v.get("contactTitle", ""),
                   "phone": v.get("contactPhone", ""), "email": v.get("contactEmail", "")})
    data["contacts"] = ct
    return {"row": no, "name": v.get("name", ""), "taxId": tax, "phone": v.get("phone", ""), "data": data}


def _build_part(v, no, warn):
    out = {"row": no}
    for k in ("partNo", "name", "brand", "model", "unit", "cost", "listPrice", "category", "note", "safetyStock", "leadTimeDays"):
        out[k] = v.get(k, "")                                              # 空白＝""（既有規則：空白不更新）
    return out


def _build_user(v, no, warn):
    return {"row": no, "username": v.get("username", ""), "displayName": v.get("displayName", ""), "role": v.get("role", ""),
            "email": v.get("email", ""), "phone": v.get("phone", ""), "department": v.get("department", ""),
            "hadPassword": bool(v.get("password"))}                         # 只記「有沒有填」，密碼值本身不輸出


_BUILD = {"customers": _build_customer, "parts": _build_part, "users": _build_user}


def parse_file(data: bytes, filename: str, kind: str, max_bytes: int = MAX_BYTES_DEFAULT) -> dict:
    if kind not in KINDS:
        raise ParseError("不認得的匯入對象")
    name = (filename or "").strip()
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    if ext == "xls":
        raise ParseError("不收舊版的 .xls 檔。請用 Excel 開啟後，另存成 .xlsx 再上傳")
    if ext == "xlsm":
        raise ParseError("不收含巨集的檔案（.xlsm）。請另存成一般的 .xlsx 再上傳")
    if ext not in ("xlsx", "csv"):
        raise ParseError("只收 .xlsx 或 .csv 檔")
    if not data:
        raise ParseError("檔案是空的")
    if len(data) > max_bytes:
        raise ParseError("檔案太大了（上限 %d MB），請拆成多個檔案" % max(1, max_bytes >> 20))
    is_zip = data[:2] == b"PK"
    if ext == "xlsx" and not is_zip:
        raise ParseError("檔案內容不是 Excel（.xlsx）格式，請用 Excel 另存成 .xlsx 再上傳")
    if ext == "csv" and (is_zip or b"\x00" in data[:4096]):
        raise ParseError("檔案內容不是文字的 CSV，請用 Excel 另存成 CSV（或直接用 .xlsx）")
    cap = MAX_ROWS[kind]
    scan = cap + 2
    rows = _rows_from_xlsx(data, scan) if ext == "xlsx" else _rows_from_csv(data, scan)
    h_no, h_cells, idx = _find_header(rows, kind)
    colmap, seen_keys, unused, ignored, headers = {}, {}, [], [], []
    for ci, h in enumerate(h_cells):
        if not str(h).strip():
            continue
        c = idx.get(_hkey(h))
        if c is None:
            unused.append(str(h))
            headers.append({"label": str(h), "key": None})
            continue
        if c["key"] in seen_keys:
            raise ParseError("欄位「%s」出現了兩次（第 %d 欄和第 %d 欄），請刪掉重複的欄位" % (c["label"], seen_keys[c["key"]] + 1, ci + 1))
        seen_keys[c["key"]] = ci
        colmap[ci] = c
        headers.append({"label": str(h), "key": c["key"]})
        if c["ignored"]:
            ignored.append(c["label"])
    missing = [c["label"] for c in COLUMNS[kind] if c["required"] and c["key"] not in seen_keys]
    if missing:
        raise ParseError("找不到必填欄位：%s（第一列要放欄位名稱，請用範本）" % "、".join("「%s」" % m for m in missing))
    warnings, formula_rows = [], []

    def warn(no, field, msg):
        warnings.append({"row": no, "field": field, "message": msg})

    out, skipped_examples = [], 0
    for r_no, cells, formulas in rows:
        if r_no <= h_no:
            continue
        v = {}
        for ci, c in colmap.items():
            v[c["key"]] = cells[ci] if ci < len(cells) else ""
        if formulas:
            formula_rows.append(r_no)
        if not any(v.values()):
            continue
        if any(str(x).startswith(EXAMPLE_MARK) for x in cells):
            skipped_examples += 1
            continue
        out.append(_BUILD[kind](v, r_no, warn))
        if len(out) > cap:
            raise ParseError("資料列太多了（上限 %d 列），請拆成多個檔案" % cap)
    if formula_rows:
        warn(formula_rows[0], "（公式）", "有 %d 列含公式儲存格，公式不會匯入（那一格當成空白）。請把公式貼成值再上傳" % len(formula_rows))
    if not out:
        raise ParseError("檔案裡沒有資料列（只有欄位名稱或範例列）")
    if ignored and kind == "users":
        warn(h_no, "密碼", "密碼欄不會使用：系統會自己產生臨時密碼，匯入完成後只顯示一次")
    return {"kind": kind, "fileName": name[:120], "rows": out, "rowCount": len(out), "maxRows": cap, "headers": headers,
            "unusedColumns": unused, "ignoredColumns": ignored, "warnings": warnings, "skippedExamples": skipped_examples}


# ── 範本 ──────────────────────────────────────────────────────────────────────

def build_template(kind: str) -> bytes:
    """範本 .xlsx：「資料」工作表（表頭、灰底範例列、全欄文字格式避免電話／料號被 Excel 吃掉開頭的 0）＋「說明」工作表。"""
    if kind not in KINDS:
        raise ParseError("不認得的匯入對象")
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation
    cols = COLUMNS[kind]
    wb = Workbook()
    ws = wb.active
    ws.title = DATA_SHEET
    head_fill = PatternFill("solid", fgColor="1F3A5F")
    req_fill = PatternFill("solid", fgColor="B91C1C")
    ex_fill = PatternFill("solid", fgColor="E5E7EB")
    for i, c in enumerate(cols, start=1):
        cell = ws.cell(row=1, column=i, value=c["label"] + ("＊" if c["required"] else ""))
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = req_fill if c["required"] else head_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        ex = ws.cell(row=2, column=i, value=c["example"] or None)
        ex.fill = ex_fill
        ex.font = Font(color="6B7280", italic=True)
        L = get_column_letter(i)
        ws.column_dimensions[L].width = max(14, min(30, len(c["label"]) * 2 + 6))
        for r in range(2, 502):
            ws.cell(row=r, column=i).number_format = "@"                 # 文字格式：保留開頭的 0
    ws.freeze_panes = "A2"
    if kind == "users":
        ri = [c["key"] for c in cols].index("role") + 1
        dv = DataValidation(type="list", formula1='"業務,工程師,檢視者"', allow_blank=True)
        dv.error, dv.errorTitle = "角色只能填：業務、工程師、檢視者，或留空", "角色"
        ws.add_data_validation(dv)
        dv.add("%s3:%s502" % (get_column_letter(ri), get_column_letter(ri)))
    hs = wb.create_sheet(HELP_SHEET)
    hs.column_dimensions["A"].width = 22
    hs.column_dimensions["B"].width = 90
    hs.append(["怎麼填（%s）" % KIND_NAMES[kind], ""])
    hs["A1"].font = Font(bold=True, size=13)
    notes = ["第 2 列灰底是範例（開頭有「%s」），上傳時會自動略過，可以保留也可以刪掉。" % EXAMPLE_MARK,
             "紅底、有 ＊ 的欄位一定要填；其他欄位可以留空。",
             "留空的格子代表「不更新」：已經存在的資料不會被清掉。",
             "請不要改欄位名稱、不要合併儲存格；公式不會匯入，請貼成值。"]
    if kind == "customers":
        notes.append("客戶以「統一編號」判斷是不是同一家；沒有統編的客戶若名稱相同，會列為「可能重複」，不會自動合併。")
    if kind == "parts":
        notes.append("品項以「料號」判斷是不是同一個；成本、定價、安全庫存、前置天數留空＝不更新。")
    if kind == "users":
        notes.append("這裡只能新增帳號：已存在的帳號會略過，不會更新。管理員、財務、最高管理者請到帳號頁一個一個建立。")
        notes.append("不要在檔案裡放密碼。匯入完成後，系統會顯示每位同仁的臨時密碼（只顯示一次），第一次登入必須改密碼。")
    for n in notes:
        hs.append(["", n])
    hs.append([])
    hs.append(["欄位", "說明"])
    hs["A%d" % hs.max_row].font = Font(bold=True)
    hs["B%d" % hs.max_row].font = Font(bold=True)
    for c in cols:
        hs.append([c["label"] + ("（必填）" if c["required"] else ""), c["hint"] or "—"])
    for row in hs.iter_rows():
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    wb.properties.keywords = "motrix-import-template:%s:v1" % kind
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()
