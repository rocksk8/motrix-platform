# -*- coding: utf-8 -*-
"""下載檔名的單一來源（A7 第一期；設計 DOWNLOAD-FILENAME-CASE-T56.md r6）。

[單位] helper:download_name    [層] L1    [穩定度] 契約
[公開介面] build、content_disposition、DownloadName、DOC_TYPES、TOKENS
[不變式]
  ① 檔名**永不含金額**：版面是程式內的固定預設組（`_LAYOUTS`），可用標籤只有 `TOKENS`（案件編號、案件名、客戶名、文件類型、單號、日期）；
     沒有任何金額欄，設定不能加。
  ② **案件名／客戶名只在呼叫者讀得到該案件時才放**（`case_access.case_download_label`，與 `GET /api/quotations/{no}` 同一支規則）；
     `user` 為 None（排程、郵件等無使用者情境）、查不到案件、M01 不在 ⇒ 一律降級（fail closed）。
  ③ 淨化底線：Windows 非法字元、控制字元、Unicode 格式字元（Cf，例如 U+202E 覆寫、零寬字元）、保留名稱、前後空白與結尾的點、
     UTF-8 位元組上限（255 − 副檔名）；標頭的 ASCII 退路一定可用 latin-1 編碼；`filename*` 依 RFC 8187 百分比編碼。
  ④ 任何例外 ⇒ 回今天的檔名（`{單號}.{副檔名}`），下載不會因為命名失敗而失敗；log 不記檔名內容。
  ⑤ 設定取自 `settings_registry` 的 `download_name` 群組，**延遲匯入、受保護**：模組缺席或讀不到 ⇒ 用本檔的常數預設（＝設定預設）。
  ⑥ 純函式部分（`_clean`、`_fit`、`_ascii_fallback`、`_rfc8187`）不碰資料庫與設定。
"""
import logging
import re
import unicodedata
from urllib.parse import quote as _urlquote

logger = logging.getLogger(__name__)

#: 檔名可用的標籤（白名單；沒有任何金額欄——改這裡等於改安全底線，守門測試鎖定）
TOKENS = ("case_no", "case_name", "customer", "doc_type", "doc_no", "date")

#: 文件類型穩定鍵 → 預設用語（顯示用語可在設定改，鍵不變）
DOC_TYPES = {
    "quotation": "報價單", "quotation_version": "報價單存檔版本", "close_report": "結案報表", "execution_report": "專案執行報告",
    "completion": "完工單", "expense_form": "費用單", "shipping": "出貨單", "payment_request": "請款單",
    "invoice_voucher": "開票申請", "contractor_voucher": "承攬商傳票", "payslip": "勞報單", "bonus_award": "獎金分配單",
    "voucher": "傳票",
}

#: 版面預設組（設定 `name_layout` 的值 → 標籤順序）
_LAYOUTS = {
    0: ("case_no", "case_name", "doc_type", "doc_no"),     # 預設：案件編號_案件名_文件類型_單號
    1: ("case_no", "doc_type", "doc_no"),
    2: ("doc_type", "doc_no"),
    3: ("doc_no",),                                         # 今天的檔名（只有單號）
}
_SEPARATORS = {0: "_", 1: "-", 2: " "}

#: 設定預設（＝使用者決定；與 helpers/settings_groups.py 的 download_name 群組逐項相同，守門測試鎖定）
DEFAULTS = {
    "name_layout": 0, "separator": 0, "case_name_source": 0, "no_access": 1, "payslip_show_name": 1,
    "case_name_max_chars": 20, "total_max_chars": 100, "add_date": 0,
}
for _k, _v in DOC_TYPES.items():
    DEFAULTS["label_" + _k] = _v

_MAX_BYTES = 255            # 單一檔名的 UTF-8 位元組上限（扣掉副檔名）
_ILLEGAL = {"\\": "＼", "/": "／", ":": "：", "*": "＊", "?": "？", '"': "＂", "<": "＜", ">": "＞", "|": "｜"}
_RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])$", re.I)
_EXT_OK = re.compile(r"^[A-Za-z0-9]{1,8}$")
_ATTR_SAFE = "!#$&+-.^_`|~"          # RFC 8187 attr-char 中除英數外的字元


class DownloadName:
    """`.name`＝Unicode 乾淨檔名；`.header`＝完整 Content-Disposition 值；`.headers()`＝可直接放進 Response 的 dict。"""
    __slots__ = ("name", "header")

    def __init__(self, name, header):
        self.name, self.header = name, header

    def headers(self):
        return {"Content-Disposition": self.header}

    def __repr__(self):
        return "DownloadName(%r)" % (self.name,)


# ── 純函式 ────────────────────────────────────────────────────────────────────

def _clean(s) -> str:
    """單一欄位的淨化：NFC、非法字元換全形、控制字元換空白、格式字元（Cf）與其他不可見字元移除、全形空白→半形、
    連續空白合一、去前後空白、結尾的點與空白、開頭的點。"""
    s = unicodedata.normalize("NFC", "" if s is None else str(s))
    out = []
    for ch in s:
        if ch in _ILLEGAL:
            out.append(_ILLEGAL[ch])
            continue
        if ch == "　":
            out.append(" ")
            continue
        cat = unicodedata.category(ch)
        if cat == "Cc" or cat in ("Zl", "Zp"):
            out.append(" ")
        elif cat in ("Cf", "Cs", "Co", "Cn"):
            continue
        else:
            out.append(ch)
    s = re.sub(r"\s+", " ", "".join(out)).strip()
    return s.rstrip(". ").lstrip(".").strip()


def _clean_ext(ext) -> str:
    e = str(ext or "").lstrip(".")
    return e if _EXT_OK.match(e) else ""


def _utf8_len(s: str) -> int:
    return len(s.encode("utf-8"))


def _fit(parts, sep, max_chars, max_bytes):
    """把標籤串成主檔名並限制長度。`parts`＝[{"k","t","shrink","drop"}]。
    順序：先逐字縮短可縮的欄位（案件名），再移除可移除的欄位（由後往前），最後才硬截斷；單號與副檔名在前兩步絕不動。"""
    parts = [dict(p) for p in parts if p.get("t")]

    def joined():
        return sep.join(p["t"] for p in parts)

    def too_long():
        j = joined()
        return len(j) > max_chars or _utf8_len(j) > max_bytes

    while too_long():
        shr = next((p for p in parts if p.get("shrink") and p["t"]), None)
        if shr is not None:
            shr["t"] = shr["t"][:-1].rstrip(". ")
            if not shr["t"]:
                parts.remove(shr)
            continue
        drp = next((p for p in reversed(parts) if p.get("drop")), None)
        if drp is not None:
            parts.remove(drp)
            continue
        break
    s = joined()
    if len(s) > max_chars or _utf8_len(s) > max_bytes:          # 硬截斷：從尾端、依字元邊界
        while s and (len(s) > max_chars or _utf8_len(s) > max_bytes):
            s = s[:-1]
        s = s.rstrip(". ")
    return s


def _ascii_fallback(name: str) -> str:
    """標頭 `filename="…"` 用的退路：只含可顯示 ASCII（latin-1 一定可編碼），雙引號、反斜線、百分號與非 ASCII 換 `_`；全是底線時用 `download`＋ASCII 副檔名。"""
    out = []
    for ch in name:
        o = ord(ch)
        out.append(ch if 32 <= o < 127 and ch not in '"' + chr(92) + '%' else "_")
    s = "".join(out)
    if s.strip("_ ."):
        return s
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    return "download" + ("." + ext if ext.isascii() and ext.isalnum() else "")


def _rfc8187(name: str) -> str:
    return _urlquote(name.encode("utf-8"), safe=_ATTR_SAFE)


def _fit_name_bytes(name: str, max_bytes: int = _MAX_BYTES) -> str:
    """整個檔名（含副檔名）的 UTF-8 位元組不超過 255：超過就從主檔名尾端依字元邊界截短，副檔名保留。
    給 `content_disposition()` 用（外部直接傳入的名稱，如各類報表，也要守這條底線；`build()` 自己已依副檔名預留）。"""
    if _utf8_len(name) <= max_bytes:
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot or not _EXT_OK.match(ext):
        stem, ext = name, ""
    tail = ("." + ext) if ext else ""
    stem = stem[:]
    while stem and _utf8_len(stem + tail) > max_bytes:
        stem = stem[:-1]
    stem = stem.rstrip(". ")
    return (stem or "download") + tail


def content_disposition(name: str, inline: bool = False) -> str:
    """`attachment; filename="{ASCII 退路}"; filename*=UTF-8''{RFC 8187}`。`name` 應已淨化；仍會再過一次 `_clean` 以防外部傳入。"""
    safe = _fit_name_bytes(_clean(name) or "download")
    return '%s; filename="%s"; filename*=UTF-8\'\'%s' % ("inline" if inline else "attachment", _ascii_fallback(safe), _rfc8187(safe))


def _protect_reserved(stem: str) -> str:
    base = stem.split(".", 1)[0].strip(" .")
    return "_" + stem if _RESERVED.match(base) else stem


def _fallback(doc_no, quote_no, ext, inline) -> "DownloadName":
    """今天的檔名：`{單號}.{副檔名}`（單號也要淨化）。"""
    e = _clean_ext(ext)
    stem = _clean(doc_no or quote_no) or "download"
    name = _protect_reserved(stem) + ("." + e if e else "")
    return DownloadName(name, content_disposition(name, inline))


# ── 設定與案件資料（受保護）──────────────────────────────────────────────────

def _settings() -> dict:
    """`download_name` 群組的有效值；取不到（模組缺席、資料庫錯誤）⇒ 常數預設。型別不符的欄位退回預設。"""
    cfg = dict(DEFAULTS)
    try:
        from helpers import settings_registry as R            # 延遲匯入（不在模組載入時依賴登錄）
        vals = R.get_group("download_name")
    except Exception:                                          # noqa: BLE001 — 設定讀取不可拖垮下載
        return cfg
    for k, dv in DEFAULTS.items():
        v = vals.get(k) if isinstance(vals, dict) else None
        if isinstance(dv, str):
            if isinstance(v, str) and 1 <= len(v.strip()) <= 10:
                cfg[k] = v.strip()
        elif isinstance(v, int) and not isinstance(v, bool):
            cfg[k] = v
    return cfg


def _case_label(conn, quote_no, user):
    """(可見, 專案名, 客戶名)。`user` 為 None 或查不到 ⇒ (False, "", "")——名稱由呼叫端的可見度決定要不要放。"""
    if not quote_no:
        return False, "", ""
    from helpers.case_access import case_download_label
    own = conn is None
    if own:
        from db import get_db
        conn = get_db()
    try:
        info = case_download_label(conn, quote_no, user)
    finally:
        if own:
            conn.close()
    return bool(info.get("readable")), info.get("project") or "", info.get("customer") or ""


# ── 公開 ──────────────────────────────────────────────────────────────────────

def build(doc_type, *, quote_no=None, doc_no=None, ext="pdf", user=None, conn=None, extra=None, inline=False) -> DownloadName:
    """產生下載檔名與 Content-Disposition。

    `doc_type`＝`DOC_TYPES` 的穩定鍵；`quote_no`＝案件編號（可無）；`doc_no`＝單據編號；`user`＝下載者（None ⇒ 降級，不放案件名）。
    `extra`（選填 dict）：`variant="internal"`（文件類型加「（內部）」）、`suffix`（接在單號後的固定文字，例：存檔事件與日期）、
    `date`（YYYYMMDD 或 YYYY-MM-DD，設定「加日期」時使用）、勞報單專用：`contractor`（承攬人）、`contractor_allowed`（**端點已確認呼叫者有權看
    這張勞報單才傳 True**）、`nth`（第 N 次）。任何例外 ⇒ 今天的檔名。"""
    try:
        return _build(doc_type, quote_no, doc_no, ext, user, conn, extra or {}, inline)
    except Exception:                                          # noqa: BLE001 — 命名失敗不可讓下載失敗
        logger.warning("download_name: 命名失敗，改用單號（doc_type=%s）", doc_type, exc_info=True)
        return _fallback(doc_no, quote_no, ext, inline)


def _build(doc_type, quote_no, doc_no, ext, user, conn, extra, inline):
    cfg = _settings()
    sep = _SEPARATORS.get(cfg["separator"], "_")
    layout = _LAYOUTS.get(cfg["name_layout"], _LAYOUTS[0])
    e = _clean_ext(ext)

    label = _clean(cfg.get("label_" + doc_type) or DOC_TYPES.get(doc_type) or doc_type)
    if extra.get("variant") == "internal":
        label = label + "（內部）"
    no = _clean(doc_no)

    case_no, case_name = "", ""
    if quote_no and ("case_no" in layout or "case_name" in layout):
        readable, project, customer = _case_label(conn, quote_no, user)
        mode = cfg["no_access"]                                 # 0 兩者都省略｜1 保留編號省略名稱（預設）｜2 顯示案件名
        known_user = user is not None
        may_name = known_user and (readable or mode == 2) and readable is not None
        # 沒有使用者（排程／郵件）一律不放名稱；無權限且選「兩者都省略」連案件編號也省略
        if known_user and not readable and mode == 0:
            case_no = ""
        else:
            case_no = _clean(quote_no)
        if may_name and "case_name" in layout:
            src = cfg["case_name_source"]                       # 0 專案名稱｜1 兩者｜2 客戶名稱
            p, c = _clean(project), _clean(customer)
            if src == 2:
                case_name = c or p
            elif src == 1:
                case_name = (p + "（" + c + "）") if (p and c) else (p or c)
            else:
                case_name = p
            case_name = case_name[: max(0, int(cfg["case_name_max_chars"]))].rstrip(". ")

    if case_no and case_no == no:             # 報價單的單號就是案件編號：不重複寫兩次
        case_no = ""

    date_s = ""
    d = str(extra.get("date") or "")
    if d and (cfg["add_date"] or doc_type == "payslip"):
        date_s = re.sub(r"[^0-9]", "", d)[:8]

    parts = []
    for tok in layout:
        if tok == "case_no":
            parts.append({"k": tok, "t": case_no, "drop": False})
        elif tok == "case_name":
            parts.append({"k": tok, "t": case_name, "shrink": True})
        elif tok == "doc_type":
            parts.append({"k": tok, "t": label})
        elif tok == "doc_no":
            parts.append({"k": tok, "t": no})
    if cfg["add_date"] and date_s and doc_type != "payslip":
        i = next((j for j, p in enumerate(parts) if p["k"] == "doc_no"), len(parts))
        parts.insert(i, {"k": "date", "t": date_s, "drop": True})
    if suffix := _clean(extra.get("suffix")):
        parts.append({"k": "suffix", "t": suffix, "drop": True})

    if doc_type == "payslip":
        # 勞報單：保留今天的「承攬人＋日期（無則單號）＋第 N 次」，只在前面加案件欄位
        tail = []
        if extra.get("contractor_allowed") and cfg["payslip_show_name"] == 1 and extra.get("contractor"):
            tail.append({"k": "contractor", "t": _clean(extra.get("contractor"))})
        tail.append({"k": "dateorno", "t": date_s or no})
        nth = _clean(extra.get("nth"))
        if nth:
            tail.append({"k": "nth", "t": nth if nth.startswith("第") else "第%s次" % nth, "drop": True})
        head = [p for p in parts if p["k"] in ("case_no", "case_name", "doc_type")]
        if not any(p["k"] == "doc_type" for p in head):
            head.append({"k": "doc_type", "t": label})
        parts = head + tail

    max_chars = max(1, int(cfg["total_max_chars"]))
    max_bytes = _MAX_BYTES - (_utf8_len("." + e) if e else 0)
    stem = _fit(parts, sep, max_chars, max_bytes)
    if not stem:
        stem = _clean(label + sep + no if no else label) or "download"
        stem = _fit([{"k": "x", "t": stem}], sep, max_chars, max_bytes) or "download"
    stem = _protect_reserved(stem)
    if _utf8_len(stem) > max_bytes:                             # 保留名稱前綴後再次確認
        stem = _fit([{"k": "x", "t": stem}], sep, max_chars, max_bytes)
    name = stem + ("." + e if e else "")
    return DownloadName(name, content_disposition(name, inline))
