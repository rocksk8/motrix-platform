# -*- coding: utf-8 -*-
"""使用者上傳的 .xlsx 的「小檔案展開」守門：預掃（真的 XML 解析，不靠 regex）＋ 子行程隔離解析（硬逾時、記憶體上限）。

[單位] helper:xlsx_guard      [層] L1        [穩定度] 契約（改介面照 §C-7 升版）
[公開介面] Limits, DEFAULT, with_limits, XlsxRejected, XlsxBusy, col_letters, col_number, new_deadline, check_deadline,
  read_upload, check_zip, sheet_part, prescan_sheet, guard, load, rows, slot, read_rows
[不變式] 一個幾十 KB 的 xlsx 可以宣告 1,048,576 列 × 16,384 欄、塞一百萬個只有格式的空格、藏一個 XFD 欄的儲存格讓 openpyxl 把每列補到 16384 欄、
  styles.xml 放 40 萬個 xf、工作表後面接 25MB 的 mergeCell：zip 比例／解壓總量擋不住，openpyxl 的 load_workbook 是一次阻塞呼叫、deadline 打不斷它。所以三層：
  ① **預掃** `guard()`：zip 結構（無巨集、解壓總量、壓縮比）、workbook／styles／共用字串／每張工作表 XML 的大小上限、styles 的 xf 數、
    所有工作表（含隱藏）的**儲存格總數／欄數／列號／列標籤數**。用 ElementTree 串流解析（iterparse），所以屬性有空白、單引號、`>`、
    命名空間前綴（`<x:c>`）都躲不掉；rels 的目標路徑要 normpath、跑出壓縮檔外或不存在 ⇒ 拒絕（不是「略過」）；含 DOCTYPE／ENTITY ⇒ 拒絕
  ② **讀取** `rows()`：唯讀模式＋`reset_dimensions()`＋`max_col=limits.max_cols`（openpyxl 自己截寬，不管 XML 怎麼寫）＋deadline／列數上限
  ③ **隔離** `read_rows()`（匯入端點該用的入口）：真正的解析（預掃＋openpyxl）在**獨立子行程**裡跑，父行程只收 JSON 結果：
    硬逾時（deadline＋margin，到了直接殺）、記憶體上限（Windows：Job Object；POSIX：RLIMIT_AS）、結果大小上限；
    子行程炸掉／被殺／逾時 ⇒ 主服務不卡、不爆（預掃有漏洞也一樣）。同時解析件數由 `slot()` 限制（滿了 XlsxBusy ⇒ 429）
  所有拒絕都丟 XlsxRejected（訊息是白話、可直接給使用者看）⇒ 呼叫端轉 400；XlsxBusy 是它的子類 ⇒ 429（先接）
[注意] 這支只管「檔案有沒有可能炸」，不管內容語意（欄位對應、公式注入等是各匯入端自己的事）。
  子行程用 `python -I -c <boot> <本檔路徑>` 啟動並以「檔案路徑」載入本檔（不 import helpers 套件，所以本檔只能依賴標準庫＋openpyxl，
  不可 import 專案其他模組）；父子之間只傳 JSON（不用 pickle：子行程處理的是不可信檔案，不能讓它回傳可執行的物件）。
  async 端點用 run_in_threadpool 呼叫 read_rows（它會阻塞到子行程結束）。環境變數 MOTRIX_XLSX_INPROCESS=1 可退回行程內解析（除錯用，不隔離）。
[契約題] tests/test_xlsx_guard_2026_11_13.py
"""
import datetime as _dt
import decimal as _decimal
import io
import json
import os
import posixpath
import subprocess
import sys
import threading
import time
import zipfile
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace


@dataclass(frozen=True)
class Limits:
    max_bytes: int = 5 << 20            # 檔案本身大小（read_upload 用）
    max_unzipped: int = 40 << 20        # 整個 zip 解壓後總量
    max_ratio: int = 1000               # 單一檔案壓縮比上限（只在該檔 > 1MB 時才算）
    max_cells: int = 250_000            # 所有工作表的儲存格（含只有格式的空格）總數
    max_cols: int = 50                  # 欄數上限（任何一格的欄超過就拒）
    max_rownum: int = 100_000           # 列號上限
    max_row_tags: int = 50_000          # 一張工作表裡出現的 <row> 數（含空白列）
    max_sheet_xml: int = 12 << 20       # 單張工作表 XML 解壓後大小（5000 列 × 40 欄的真檔約 6～10MB）
    max_shared_strings: int = 10 << 20  # sharedStrings.xml
    max_styles_xml: int = 5 << 20       # styles.xml
    max_workbook_xml: int = 1 << 20     # workbook.xml 與各 .rels
    max_xf: int = 50_000                # styles.xml 裡的 <xf> 數（真檔通常數百～數千）
    max_sheets: int = 50                # 工作表數
    max_depth: int = 64                 # 工作表 XML 的巢狀深度（真檔約 6 層；幾百萬層巢狀會讓解析吃掉大量記憶體）
    max_waiting: int = 4                # slot() 最多幾條執行緒排隊等名額；再多立刻 XlsxBusy（不讓排隊把共用執行緒池占滿）
    deadline_seconds: float = 10.0      # 整個解析的時間上限（子行程內的軟上限）
    hard_margin: float = 5.0            # 硬上限＝deadline_seconds＋hard_margin：到了父行程直接殺子行程
    max_concurrent: int = 2             # 同時解析數（slot 用）
    max_child_memory: int = 768 << 20   # 子行程記憶體上限
    max_result_bytes: int = 64 << 20    # 子行程回傳結果的大小上限


DEFAULT = Limits()


class XlsxRejected(ValueError):
    """檔案不合格／太大／太花時間；訊息是白話，可直接顯示給使用者（呼叫端轉 400）。"""


class XlsxBusy(XlsxRejected):
    """同時解析的人太多（呼叫端轉 429）。"""


def _limits_from(d):
    """欄位名 ⇒ 值 的字典（`asdict(Limits)` 的樣子）轉成 Limits：逐欄覆寫 DEFAULT（不用 ** 傳參數；不認得的欄位名 ⇒ 同 `replace` 的 TypeError／ValueError）。"""
    lim = DEFAULT
    for k, v in d.items():
        lim = replace(lim, **{k: v})
    return lim


def with_limits(**kw):
    """DEFAULT 的覆寫版：with_limits(max_bytes=10<<20)。"""
    return _limits_from(kw)


def col_letters(n):
    out = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out or "A"


def col_number(letters):
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


def new_deadline(limits=DEFAULT):
    return time.monotonic() + limits.deadline_seconds


def check_deadline(deadline, limits=DEFAULT):
    if deadline is not None and time.monotonic() > deadline:
        raise XlsxRejected("檔案處理太久了（超過 %d 秒）。請減少列數或欄數，或拆成多個檔案" % limits.deadline_seconds)


async def read_upload(upload, limits=DEFAULT):
    """FastAPI UploadFile → bytes；超過 limits.max_bytes 就停（不把整個大檔讀進記憶體）。"""
    buf = bytearray()
    while True:
        chunk = await upload.read(1 << 20)
        if not chunk:
            break
        buf += chunk
        if len(buf) > limits.max_bytes:
            raise XlsxRejected("檔案太大了（上限 %d MB）" % max(1, limits.max_bytes >> 20))
    return bytes(buf)


# ───────────────────────── ① 預掃 ─────────────────────────

_NOT_XLSX = "這個檔案不是有效的 Excel（.xlsx）檔，請用 Excel 另存成 .xlsx 再上傳"
_BAD_STRUCT = "這個檔案的工作表結構讀不出來，請用 Excel 另存成 .xlsx 再上傳"


def check_zip(data, limits=DEFAULT):
    """zip 結構檢查，回 ZipFile：不是 xlsx／含巨集／解開後太大或壓縮比異常 ⇒ XlsxRejected。"""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise XlsxRejected(_NOT_XLSX)
    names = z.namelist()
    if any(n.lower().endswith("vbaproject.bin") for n in names):
        raise XlsxRejected("不收含巨集的檔案（.xlsm）。請另存成一般的 .xlsx 再上傳")
    if "xl/workbook.xml" not in names:
        raise XlsxRejected(_NOT_XLSX)
    total = 0
    for zi in z.infolist():
        total += zi.file_size
        if total > limits.max_unzipped or (
                zi.compress_size and zi.file_size / max(zi.compress_size, 1) > limits.max_ratio and zi.file_size > (1 << 20)):
            raise XlsxRejected("檔案解開後太大，無法處理（可能是壓縮炸彈或內含過大的圖片）")
    return z


def _local(tag):
    return tag.rpartition("}")[2]


def _scan_dtd(blob):
    up = blob.upper()
    if b"<!DOCTYPE" in up or b"<!ENTITY" in up:
        raise XlsxRejected("這個檔案的內容格式不正常，無法讀取")


def _no_dtd(blob):
    """整個部件（小 XML）或串流的第一塊：含 DOCTYPE／ENTITY ⇒ 拒絕；xlsx 的 XML 一律是 UTF-8，UTF-16 之類（逐位元組掃不到）也拒絕。"""
    if blob[:2] in (b"\xff\xfe", b"\xfe\xff") or b"\x00" in blob[:4]:
        raise XlsxRejected("這個檔案的內容格式不正常，無法讀取")
    _scan_dtd(blob)


def _small_xml(z, name, cap):
    """讀一個小 XML 部件並解析成 Element：超過 cap／含 DTD／格式錯 ⇒ XlsxRejected。"""
    try:
        info = z.getinfo(name)
    except KeyError:
        raise XlsxRejected(_BAD_STRUCT)
    if info.file_size > cap:
        raise XlsxRejected("這個檔案的內容太大了（%s），請拆成多個檔案或另存成一般的 .xlsx" % name)
    blob = z.read(info)
    _no_dtd(blob)                                    # 小部件整份掃（不只檔頭：DOCTYPE 可以藏在很長的註解後面）
    try:
        return ET.fromstring(blob)
    except ET.ParseError:
        raise XlsxRejected(_BAD_STRUCT)


def _sheet_parts(z, limits=DEFAULT):
    """workbook.xml＋rels ⇒ [(名稱, zip 內 XML 路徑, state)]。目標路徑做 normpath；跑出壓縮檔外或不存在 ⇒ XlsxRejected。"""
    wb = _small_xml(z, "xl/workbook.xml", limits.max_workbook_xml)
    rels_name = "xl/_rels/workbook.xml.rels"
    rels = _small_xml(z, rels_name, limits.max_workbook_xml)
    targets = {}
    for el in rels.iter():
        if _local(el.tag) == "Relationship" and el.get("TargetMode") != "External":
            tgt = el.get("Target", "")
            path = tgt.lstrip("/") if tgt.startswith("/") else posixpath.normpath(posixpath.join("xl", tgt))
            targets[el.get("Id")] = path
    names = set(z.namelist())
    out = []
    for el in wb.iter():
        if _local(el.tag) != "sheet":
            continue
        rid = next((v for k, v in el.attrib.items() if _local(k) == "id"), None)
        path = targets.get(rid)
        if path is None or path.startswith("..") or path.startswith("/") or path not in names:
            raise XlsxRejected(_BAD_STRUCT)
        out.append(((el.get("name") or "").strip(), path, el.get("state") or "visible"))
        if len(out) > limits.max_sheets:
            raise XlsxRejected("這個檔案的工作表太多了（上限 %d 張）" % limits.max_sheets)
    if not out:
        raise XlsxRejected(_BAD_STRUCT)
    return out


def sheet_part(z, sheet_title, limits=DEFAULT):
    """工作表名稱 ⇒ zip 內 XML 路徑；找不到回 None。"""
    for name, part, _state in _sheet_parts(z, limits):
        if name == sheet_title.strip():
            return part
    return None


class _Chain:
    """先吐出已讀的檔頭、再接原串流（讓 iterparse 能從頭讀）。"""

    def __init__(self, head, fh):
        self._head, self._fh = head, fh
        self._tail = b""                                 # 上一塊的結尾（DOCTYPE 字串跨塊也掃得到）

    def _check(self, out):
        if out:
            _scan_dtd(self._tail + out)
            self._tail = out[-12:]
        return out

    def read(self, n=-1):
        if self._head:
            if n is None or n < 0:
                out, self._head = self._head + self._fh.read(), b""
                return self._check(out)
            out, self._head = self._head[:n], self._head[n:]
            if len(out) < n:
                out += self._fh.read(n - len(out))
            return self._check(out)
        return self._check(self._fh.read(n))


def _events(z, info, deadline, limits):
    """串流解析一個部件，產出 (event, elem)；每 2048 個事件檢查一次 deadline；含 DTD／格式錯 ⇒ XlsxRejected。"""
    with z.open(info) as fh:
        head = fh.read(4096)
        _no_dtd(head)
        n = 0
        try:
            for ev in ET.iterparse(_Chain(head, fh), events=("start", "end")):
                n += 1
                if n & 2047 == 0:
                    check_deadline(deadline, limits)
                yield ev
        except ET.ParseError:
            raise XlsxRejected("這個工作表的內容格式不正常，無法讀取")


def prescan_sheet(z, part, limits=DEFAULT, deadline=None, cells_so_far=0):
    """用 XML 解析器串流掃一張工作表，只數東西、不讀內容：格數、列數、最大列號、超過欄上限的格。
    超過任何上限就丟 XlsxRejected。回傳這張表的儲存格數。cells_so_far＝先前工作表已數到的格數（上限是全部合計）。"""
    try:
        info = z.getinfo(part)
    except KeyError:
        raise XlsxRejected(_BAD_STRUCT)
    if info.file_size > limits.max_sheet_xml:
        raise XlsxRejected("這個工作表的內容太大了，請刪掉多餘的空白列、欄與格式再上傳（或拆成多個檔案）")
    cells = rows = 0
    prev_row = prev_col = 0
    root = sheetdata = None
    depth = 0
    for ev, el in _events(z, info, deadline, limits):
        tag = _local(el.tag)
        if ev == "start":
            depth += 1
            if depth > limits.max_depth:
                raise XlsxRejected("這個工作表的內容格式不正常，無法讀取")
            if root is None:
                root = el
            if tag == "sheetData":
                sheetdata = el
            elif tag == "row":
                rows += 1
                r = el.get("r")
                if r is not None:
                    if not r.strip().isdigit():
                        raise XlsxRejected("這個工作表的內容格式不正常，無法讀取")
                    rn = int(r)
                else:
                    rn = prev_row + 1
                prev_row, prev_col = rn, 0
                if rows > limits.max_row_tags or rn > limits.max_rownum:
                    raise XlsxRejected("這個工作表的列太多或資料放得太下面了（上限約 %d 列）。請刪掉多餘的空白列再上傳，或拆成多個檔案"
                                       % limits.max_rownum)
            elif tag == "c":
                cells += 1
                ref = (el.get("r") or "").strip()
                if ref:
                    letters = ref.rstrip("0123456789")
                    if not letters.isalpha() or len(letters) > 3:
                        raise XlsxRejected("這個工作表的內容格式不正常，無法讀取")
                    col = col_number(letters)
                else:
                    letters, col = None, prev_col + 1
                prev_col = col
                if col > limits.max_cols:
                    raise XlsxRejected("第 %d 列的「%s 欄」有內容或格式，超過欄位上限 %d 欄（到 %s 欄）。請刪掉多餘的欄再上傳，或確認檔案是依範本填的"
                                       % (prev_row, (letters or col_letters(col)).upper(), limits.max_cols, col_letters(limits.max_cols)))
                if cells_so_far + cells > limits.max_cells:
                    raise XlsxRejected("這個檔案的儲存格太多了（超過 %d 格）。請刪掉多餘的空白列、欄與格式，或拆成多個檔案" % limits.max_cells)
        else:                                        # end：釋放記憶體
            depth -= 1
            if tag == "row" and sheetdata is not None:
                el.clear()
                try:
                    sheetdata.remove(el)
                except ValueError:
                    pass
            elif tag not in ("sheetData", "worksheet"):
                el.clear()
    return cells


def _prescan_styles(z, limits, deadline):
    try:
        info = z.getinfo("xl/styles.xml")
    except KeyError:
        return
    if info.file_size > limits.max_styles_xml:
        raise XlsxRejected("這個檔案的格式資訊太多了（styles），請用 Excel 另存成新的 .xlsx 再上傳")
    xf = 0
    for ev, el in _events(z, info, deadline, limits):
        if ev == "start" and _local(el.tag) == "xf":
            xf += 1
            if xf > limits.max_xf:
                raise XlsxRejected("這個檔案的儲存格格式太多了，請用 Excel 另存成新的 .xlsx 再上傳")
        elif ev == "end":
            el.clear()


def guard(data, limits=DEFAULT, sheets=None, deadline=None):
    """預掃全套（行程內），回 ZipFile。sheets＝只掃這些名稱的工作表（None＝全部，含隱藏的）。
    **會把整份檔案掃一遍 XML，吃 CPU 最多 limits.deadline_seconds**：匯入端點請用 read_rows（子行程隔離）。"""
    check_deadline(deadline, limits)
    z = check_zip(data, limits)
    try:
        if z.getinfo("xl/sharedStrings.xml").file_size > limits.max_shared_strings:
            raise XlsxRejected("這個檔案的文字內容太多了，請拆成多個檔案")
    except KeyError:
        pass
    parts = _sheet_parts(z, limits)
    _prescan_styles(z, limits, deadline)
    want = None if sheets is None else {s.strip() for s in sheets}
    total = 0
    for name, part, _state in parts:
        if want is not None and name not in want:
            continue
        check_deadline(deadline, limits)
        total += prescan_sheet(z, part, limits, deadline, total)
    return z


# ───────────────────────── ② 讀取（行程內） ─────────────────────────

def _open_workbook(data, data_only):
    try:
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=data_only)
    except Exception as exc:                                  # noqa: BLE001
        raise XlsxRejected("這個檔案讀不出來（%s）。請用 Excel 另存成 .xlsx 再上傳" % type(exc).__name__)
    for ws in wb.worksheets:
        reset = getattr(ws, "reset_dimensions", None)
        if reset:
            reset()
    return wb


def load(data, limits=DEFAULT, sheets=None, data_only=True, deadline=None):
    """guard() ＋ openpyxl 唯讀開檔（read_only=True），並對每張工作表 reset_dimensions()（不信宣告範圍）。
    **行程內**：load_workbook 是一次阻塞呼叫，deadline 打不斷它——匯入端點請用 read_rows（子行程隔離）。
    回 Workbook；呼叫端用完要 wb.close()。"""
    guard(data, limits, sheets=sheets, deadline=deadline)
    return _open_workbook(data, data_only)


_ITER_ROWS_KEYS = frozenset(("min_row", "max_row", "min_col", "max_col", "values_only"))


def rows(ws, deadline=None, limits=DEFAULT, max_rows=None, header_rows=0, **kw):
    """ws.iter_rows(min_row, max_row, min_col, max_col, values_only) 的守門版（`**kw` 只收這五個同名同義的關鍵字，逐一明列傳給 iter_rows）：每 256 列檢查 deadline；讀超過 max_rows 列（含空白列）就丟 XlsxRejected；
    max_col 預設 limits.max_cols（openpyxl 自己截寬／補到這個寬度，不管 XML 怎麼寫——所以每列都剛好 max_cols 欄）。
    header_rows＝max_rows 裡有幾列是表頭（只影響訊息：顯示「上限 max_rows-header_rows 列」資料列）。"""
    unknown = sorted(set(kw) - _ITER_ROWS_KEYS)
    if unknown:
        raise TypeError("rows() 不認得的參數：%s" % ", ".join(unknown))
    for i, row in enumerate(ws.iter_rows(min_row=kw.get("min_row"), max_row=kw.get("max_row"), min_col=kw.get("min_col"),
                                         max_col=kw.get("max_col", limits.max_cols), values_only=kw.get("values_only", False)),
                            start=1):
        if i & 255 == 0:
            check_deadline(deadline, limits)
        if max_rows is not None and i > max_rows:
            raise XlsxRejected("檔案的列數太多了（上限 %d 列），請拆成多個檔案" % (max_rows - header_rows))
        yield row


_SLOTS = {}
_SLOTS_LOCK = threading.Lock()


@contextmanager
def slot(name="xlsx", limits=DEFAULT, wait=5.0):
    """限制同時解析的數量（同一個 name 共用額度）；等不到就丟 XlsxBusy。"""
    with _SLOTS_LOCK:
        st = _SLOTS.get((name, limits.max_concurrent))
        if st is None:
            st = _SLOTS[(name, limits.max_concurrent)] = [threading.BoundedSemaphore(limits.max_concurrent), 0]
    sem = st[0]
    if not sem.acquire(blocking=False):
        with _SLOTS_LOCK:
            if st[1] >= limits.max_waiting:              # 排隊的執行緒太多 ⇒ 立刻拒絕（否則一個人連發 40 個匯入會把共用執行緒池停 5 秒）
                raise XlsxBusy("目前有其他人正在匯入檔案，請稍等幾秒再試")
            st[1] += 1
        try:
            got = sem.acquire(timeout=wait)
        finally:
            with _SLOTS_LOCK:
                st[1] -= 1
        if not got:
            raise XlsxBusy("目前有其他人正在匯入檔案，請稍等幾秒再試")
    try:
        yield
    finally:
        sem.release()


# ───────────────────────── ③ 子行程隔離 ─────────────────────────

def _enc(v):
    """儲存格值 ⇒ JSON 可傳的值（日期等加標籤，父行程還原）。"""
    if v is None or isinstance(v, (str, bool, int)):
        return v
    if isinstance(v, float):
        return v if v == v and v not in (float("inf"), float("-inf")) else str(v)
    if isinstance(v, _dt.datetime):
        return {"__t": "dt", "v": v.isoformat()}
    if isinstance(v, _dt.date):
        return {"__t": "d", "v": v.isoformat()}
    if isinstance(v, _dt.time):
        return {"__t": "t", "v": v.isoformat()}
    if isinstance(v, _dt.timedelta):
        return {"__t": "td", "v": v.total_seconds()}
    if isinstance(v, _decimal.Decimal):
        return {"__t": "dec", "v": str(v)}
    return str(v)


def _dec(v):
    if isinstance(v, dict) and "__t" in v:
        t, x = v["__t"], v["v"]
        if t == "dt":
            return _dt.datetime.fromisoformat(x)
        if t == "d":
            return _dt.date.fromisoformat(x)
        if t == "t":
            return _dt.time.fromisoformat(x)
        if t == "td":
            return _dt.timedelta(seconds=x)
        if t == "dec":
            return _decimal.Decimal(x)
    return v


def _pick_sheets(wb, sheets, pick):
    if sheets:
        want = {s.strip() for s in sheets}
        return [ws for ws in wb.worksheets if ws.title.strip() in want]
    if pick:
        visible = [ws for ws in wb.worksheets if getattr(ws, "sheet_state", "visible") == "visible"]
        prefer = (pick.get("prefer") or "").strip()
        exclude = {x.strip() for x in (pick.get("exclude") or [])}
        chosen = next((ws for ws in visible if prefer and ws.title.strip() == prefer), None)
        if chosen is None:
            chosen = next((ws for ws in visible if ws.title.strip() not in exclude), None)
        return [chosen] if chosen is not None else []
    return [wb.active] if wb.active is not None else []


def _extract(data, limits, req):
    """（子行程內跑）預掃＋讀取 ⇒ JSON 可傳的結果。req＝{sheets, pick, max_rows, with_types, data_only}。"""
    deadline = new_deadline(limits)
    guard(data, limits, deadline=deadline)
    wb = _open_workbook(data, req.get("data_only", True))
    try:
        titles = list(wb.sheetnames)
        out, budget = [], limits.max_result_bytes
        with_types = req.get("with_types") is True      # req＝父行程組的內部字典（read_rows 的 with_types 是真布林），不是請求本文；子行程不能 import helpers.validation（會拉進整個 fastapi／helpers），所以嚴格比對 True
        for ws in _pick_sheets(wb, req.get("sheets"), req.get("pick")):
            body = []
            for row in rows(ws, deadline=deadline, limits=limits, max_rows=req.get("max_rows"),
                            header_rows=req.get("header_rows", 0), values_only=not with_types):
                if with_types:
                    cells = [[_enc(getattr(c, "value", None)), getattr(c, "data_type", "n")] for c in row]
                    while cells and cells[-1][0] is None:
                        cells.pop()
                else:
                    cells = [_enc(v) for v in row]
                    while cells and cells[-1] is None:
                        cells.pop()
                budget -= 16 + sum(len(str(c)) + 4 for c in cells)
                if budget < 0:
                    raise XlsxRejected("檔案的內容太多了，請拆成多個檔案")
                body.append(cells)
            out.append({"name": ws.title, "rows": body})
        return {"titles": titles, "sheets": out}
    finally:
        try:
            wb.close()
        except Exception:                                     # noqa: BLE001
            pass


def _worker_main():
    """子行程進入點：stdin ＝ 一行 JSON 標頭 ＋ n 位元組檔案；stdout ＝ 一個 JSON 結果。"""
    out = sys.stdout.buffer
    try:
        inp = sys.stdin.buffer
        hdr = json.loads(inp.readline().decode("utf-8"))
        limits = _limits_from(hdr["limits"])
        try:                                                   # POSIX 的記憶體上限（Windows 由父行程用 Job Object 設）
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (limits.max_child_memory, limits.max_child_memory))
        except Exception:                                      # noqa: BLE001
            pass
        data = b""
        while len(data) < hdr["n"]:
            chunk = inp.read(hdr["n"] - len(data))
            if not chunk:
                break
            data += chunk
        payload = {"ok": True, "result": _extract(data, limits, hdr["req"])}
    except XlsxRejected as e:
        payload = {"ok": False, "kind": "rejected", "message": str(e)}
    except MemoryError:
        payload = {"ok": False, "kind": "rejected", "message": "這個檔案處理時用掉太多記憶體，請減少內容或拆成多個檔案"}
    except Exception as e:                                     # noqa: BLE001
        payload = {"ok": False, "kind": "error", "message": type(e).__name__}
    out.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    out.flush()


_BOOT = ("import importlib.util,sys,json;p=sys.argv[1];sys.path.extend(json.loads(sys.argv[2]));"
         "s=importlib.util.spec_from_file_location('xlsx_guard_worker',p);m=importlib.util.module_from_spec(s);"
         "sys.modules['xlsx_guard_worker']=m;s.loader.exec_module(m);m._worker_main()")


_WARNED = set()


def _warn_once(key, msg):
    if key in _WARNED:
        return
    _WARNED.add(key)
    try:
        import logging
        logging.getLogger("xlsx_guard").warning(msg)
    except Exception:                                                   # noqa: BLE001
        pass


def _child_python():
    """子行程要用哪支 python：虛擬環境（venv／uv）的 python.exe 只是轉接殼，真正的直譯器是它的孫行程——
    記憶體上限、殺行程都得穿過殼才算數。所以虛擬環境下改用底層的真直譯器，並把 site-packages 路徑用 argv 帶過去（-I 不吃 PYTHONPATH）。
    回 (執行檔, 要補進 sys.path 的目錄)。"""
    exe = sys.executable
    base = getattr(sys, "_base_executable", None)
    if sys.prefix != getattr(sys, "base_prefix", sys.prefix) and base and os.path.isfile(base) \
            and os.path.normcase(os.path.abspath(base)) != os.path.normcase(os.path.abspath(exe)):
        paths = [p for p in sys.path if p and os.path.isdir(p) and "site-packages" in p.replace("\\", "/")]
        if paths:
            return base, paths
    return exe, []


def _kill_tree(proc):
    """殺子行程與它底下所有行程（Windows 用 taskkill /T；其他平台殺本體）。"""
    if os.name == "nt" and proc.poll() is None:
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=5,
                           creationflags=0x08000000)
        except Exception:                                               # noqa: BLE001
            pass
    try:
        proc.kill()
    except OSError:
        pass


def _win_job(pid, mem_bytes):
    """Windows：建 Job Object（單一行程記憶體上限＋關閉時殺掉），把子行程放進去。回 handle（用完要 CloseHandle）；
    失敗回 None（會記一次警告：這時沒有記憶體上限，只剩硬逾時與預掃）。"""
    job = _win_job_inner(pid, mem_bytes)
    if job is None:
        _warn_once("job", "xlsx_guard: 無法建立 Job Object，匯入子行程沒有記憶體上限（仍有預掃與硬逾時）")
    return job


def _win_job_inner(pid, mem_bytes):
    try:
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)

        class _Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

        class _IoCounters(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("a", "b", "c", "d", "e", "f")]

        class _Ext(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", _Basic), ("IoInfo", _IoCounters), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]
        k.CreateJobObjectW.restype = wintypes.HANDLE
        k.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k.OpenProcess.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        job = k.CreateJobObjectW(None, None)
        if not job:
            return None
        info = _Ext()
        info.BasicLimitInformation.LimitFlags = 0x100 | 0x2000          # PROCESS_MEMORY | KILL_ON_JOB_CLOSE
        info.ProcessMemoryLimit = mem_bytes
        if not k.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            k.CloseHandle(job)
            return None
        hp = k.OpenProcess(0x0100 | 0x0001, False, pid)               # SET_QUOTA | TERMINATE
        if not hp:
            k.CloseHandle(job)
            return None
        ok = k.AssignProcessToJobObject(job, hp)
        k.CloseHandle(hp)
        if not ok:
            k.CloseHandle(job)
            return None
        return job
    except Exception:                                                   # noqa: BLE001
        return None


def _win_close(job):
    try:
        import ctypes
        ctypes.WinDLL("kernel32").CloseHandle(job)
    except Exception:                                                   # noqa: BLE001
        pass


def _run_child(data, limits, req):
    hdr = json.dumps({"limits": asdict(limits), "req": req, "n": len(data)}).encode("utf-8") + b"\n"
    creationflags = 0x08000000 if os.name == "nt" else 0                # CREATE_NO_WINDOW（POSIX 只接受 0）
    # numpy（openpyxl 會順手 import）的 OpenBLAS 一啟動就預留約 750MB 的 commit（工作集只有 30MB）：不壓成單執行緒的話，
    # 記憶體上限（按 commit 算）要設到 1GB 以上才跑得起來，等於沒有上限。
    env = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    exe, extra_paths = _child_python()
    proc = subprocess.Popen([exe, "-I", "-X", "utf8", "-c", _BOOT, os.path.abspath(__file__), json.dumps(extra_paths)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
                            creationflags=creationflags)
    job = _win_job(proc.pid, limits.max_child_memory) if os.name == "nt" else None
    try:
        try:
            stdout, _ = proc.communicate(hdr + data, timeout=max(0.0, limits.deadline_seconds + limits.hard_margin))
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            proc.communicate()
            raise XlsxRejected("檔案處理太久了（超過 %d 秒）。請減少列數或欄數，或拆成多個檔案" % limits.deadline_seconds)
        except OSError:
            _kill_tree(proc)
            proc.communicate()
            raise XlsxRejected("這個檔案讀不出來，請用 Excel 另存成 .xlsx 再上傳")
    finally:
        if proc.poll() is None:
            _kill_tree(proc)
            proc.wait()
        if job:
            _win_close(job)
    if len(stdout) > limits.max_result_bytes + (1 << 20):
        raise XlsxRejected("檔案的內容太多了，請拆成多個檔案")
    try:
        payload = json.loads(stdout.decode("utf-8"))
    except Exception:                                                   # noqa: BLE001
        # 沒有結果＝子行程被殺（記憶體上限）或崩潰
        raise XlsxRejected("這個檔案處理失敗（可能內容太多或格式不正常），請用 Excel 另存成 .xlsx 或拆成多個檔案再上傳")
    if not payload.get("ok"):
        if payload.get("kind") == "rejected":
            raise XlsxRejected(payload["message"])
        raise XlsxRejected("這個檔案讀不出來（%s）。請用 Excel 另存成 .xlsx 再上傳" % payload.get("message", ""))
    return payload["result"]


def read_rows(data, limits=DEFAULT, *, sheets=None, pick=None, max_rows=None, header_rows=0, with_types=False,
              data_only=True, slot_name="xlsx", isolated=None):
    """匯入端點的入口：在**子行程**裡做預掃＋讀取（硬逾時、記憶體上限），回
      {"titles": [所有工作表名稱], "sheets": [{"name": 工作表名稱, "rows": [[儲存格值…]…]}…]}
    選哪些工作表：sheets＝名稱清單；pick＝{"prefer": "資料", "exclude": ["說明"]}（可見的工作表裡優先 prefer、否則第一張不在 exclude 的）；
    都不給＝使用中的那張。rows 每列已去掉尾端的空格（None）；with_types=True 時每格是 [值, 型別]（型別 'f'＝公式、'n'＝數字、's'＝文字…；
    data_only=False 才看得到公式）。日期／Decimal 等已還原成 Python 物件。max_rows＝每張表最多讀幾列（含表頭；超過 ⇒ XlsxRejected）。
    同時解析數由 slot 限制（XlsxBusy）。這個函式會阻塞到子行程結束：async 端點要用 run_in_threadpool。"""
    check_zip(data, limits)                                             # 便宜的結構檢查先在父行程做（不用為明顯壞檔開子行程）
    req = {"sheets": list(sheets) if sheets else None, "pick": pick, "max_rows": max_rows, "header_rows": header_rows,
           "with_types": with_types, "data_only": data_only}
    if isolated is None:
        isolated = os.environ.get("MOTRIX_XLSX_INPROCESS") != "1"
    with slot(slot_name, limits):
        res = _run_child(data, limits, req) if isolated else _extract(data, limits, req)
    for sh in res["sheets"]:
        if with_types:
            sh["rows"] = [[[_dec(c[0]), c[1]] for c in row] for row in sh["rows"]]
        else:
            sh["rows"] = [[_dec(c) for c in row] for row in sh["rows"]]
    return res
