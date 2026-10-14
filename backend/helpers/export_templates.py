# -*- coding: utf-8 -*-
"""匯出範本（BP-3 R0/R1）：宣告式的欄位／標籤／順序（＋頁首頁尾／浮水印文字），套在『已登記的匯出』上；發布前預覽。

[單位] helper:export_templates    [層] L1    [穩定度] 實作
[公開介面] CAPS, FIELD, GROUP, KIND, LABEL_MAX, MAX_COLUMNS, OFF_REASON, PRESET_TEXTS, RESERVED_WATERMARK, TEXT_MAX, WATERMARK_MAX, WATERMARK_PRESETS, apply_pdf_text, apply_print_text, decorate_pdf, default_template, definition_problems, disabled_sheets, effective_columns, enabled, enabled_sheets, ensure_kind, preview, register_export, registered, render_csv_rows, render_rows, resolve
[不變式] 設定 `builder_exports.enabled`（預設 0＝關）關著時：`resolve()` 一律回 None（端點走今天寫死的路徑，輸出逐位元相同）；發布驗證擋；預覽端點 404。
    範本只收宣告式資料：欄位 id 必須在該匯出的**欄位目錄**裡（模組登記，不由使用者定義）、文字是純文字（無占位符、無運算式、無控制／雙向字元），
    **範本不能新增資料**——欄位值一律來自端點今天的查詢與遮蔽；標 `money`（或有 `visible`）的欄位在輸出端再問一次權限，沒權限 ⇒ 整欄省略（遮蔽優先）。
    寫進試算表／CSV 的每個儲存格仍經 `helpers.xlsx_out` 的中和函式。
[契約題] tests/platform/test_export_templates_bp3.py
[注意] 新增一個 kind `export_template`（key＝匯出代號，scope＝company）；版本／差異／還原／帳本／發布前預覽全部沿用定義文件庫與治理層。
"""
import re
import unicodedata

from core import definitions as D
from helpers.xlsx_out import csv_safe, xl_safe_xlsx

GROUP = "builder_exports"
FIELD = "enabled"
KIND = "export_template"
OFF_REASON = "自訂匯出尚未開放（設定中心：自訂匯出）"
MAX_COLUMNS = 40
LABEL_MAX = 20
TEXT_MAX = 60
WATERMARK_MAX = 40
#: 各格式能放哪些版面文字（CSV 沒有頁首頁尾／浮水印：不是『忽略』，是驗證直接拒絕，免得使用者以為有）
CAPS = {"csv": frozenset(), "xlsx": frozenset({"header", "footer"}), "pdf": frozenset({"header", "footer", "watermark"})}
_TOP_KEYS = {"version", "format", "columns", "header", "footer", "watermark", "sheets"}
#: 頁首／頁尾／浮水印文字（v1）：只能從白名單挑，不收自由文字（客戶可見文件上的文字不能由一個人隨手寫）。
PRESET_TEXTS = ("內部資料", "機密", "草稿", "僅供參考", "內部使用", "請勿外流", "僅限內部傳閱", "列印後請妥善保管")
WATERMARK_PRESETS = ("內部資料", "機密", "草稿", "僅供參考", "內部使用")
#: 看起來是空白或會被隱形的字元（Hangul filler、Braille blank 等；其餘 Cc/Cf/Zl/Zp/Co/Cs 以字元類別擋）
_FILLERS = frozenset("\u115f\u1160\u3164\uffa0\u2800\u180e\u034f\u061c\u17b4\u17b5\u00ad\u2060")
#: 控制字元、雙向覆寫／隔離、零寬、BOM；尖括號、&、引號、反斜線、花括號（占位符）一律不收
_BAD_CHARS = re.compile("[<>&\"'`\\\\{}\x00-\x1f\x7f​-‏‪-‮⁦-⁩﻿]")
_TRIGGERS = ("=", "+", "-", "@")
#: 官方狀態詞：頁首／頁尾／浮水印都不得含（狀態字樣只由程式依單據真實狀態產生）。比對在『只留字母與數字的骨架』上（NFKC＋casefold），
#: 所以插空白、全形、隱形字元都繞不過。
RESERVED_WATERMARK = ("正本", "副本", "已核准", "已核可", "核准", "核可", "簽核完成", "已付款", "已收款", "已簽回", "已簽收", "作廢", "作废",
                      "approved", "paid", "original", "void", "signed", "final")

_EXPORTS: dict = {}


def enabled(conn=None) -> bool:
    """fail-closed：讀不到設定 ⇒ 關。**自訂匯出必須同時開啟『建構器治理』（`builder_governance.enabled`）才生效**——
    放寬（新增欄位、新增或改變頁首頁尾浮水印文字）要靠治理管線的第二位最高管理者核准與發布前預覽雜湊；治理沒開就沒有這兩道把關，所以不讓它生效。"""
    try:
        from helpers import settings_registry as SR
        if not bool(int(SR.get(GROUP, FIELD, conn=conn))):
            return False
        return int(SR.get("builder_governance", "enabled", conn=conn)) == 1
    except Exception:                                        # noqa: BLE001
        return False


# ── 匯出目錄（模組登記；使用者不能新增）────────────────────────────────────
def register_export(export_id, *, label, formats, columns, sample_rows, rows_provider=None, lock_labels=False, caps=None, sample_html=None, sheets=None):
    """登記一個可套範本的匯出。`columns`＝有序 `[{id, label, money?, visible?}]`（順序與標籤＝今天寫死的預設）；
    `lock_labels=True`：欄位標題必須等於目錄標題（這個匯出的檔案會被匯入回來，匯入靠表頭文字對應，不能改名；欄位仍可省略、換順序）。
    `columns=[]` 只允許 pdf-only 的匯出（版面固定、只能加頁首／頁尾／浮水印文字＝decorOnly）；`caps`＝這個匯出實際允許的版面文字（預設依格式；用來縮窄，例：只開頁尾與浮水印）；
    `sample_html`＝decorOnly 預覽用的樣本頁 HTML。
    `sheets`＝工作表目錄 `[{id, label, required?, money?}]`（營運報表這類『整份報表由多張表組成』的匯出）：範本只能選『要哪幾張』（目錄的子集、順序固定＝目錄順序、必選的不能拿掉），
    不能改名、不能改內容；此時 `columns` 必須是空的、不允許頁首／頁尾／浮水印（caps 固定為空）。`money:true`＝含金額的工作表（把它加回來屬放寬）。
    `visible(user)->bool`：有它或 `money:true` 的欄位在輸出端再驗權限（`money` 沒有 `visible` ⇒ 一律不顯示＝fail-closed）；
    `sample_rows`＝預覽用樣本列（`[{col_id: value}]`，不碰真實資料）；`rows_provider(conn, viewer, n)->[{col_id: value}]`＝『可見的真實列』。"""
    if not re.match(r"^[a-z][a-z0-9_:.\-]{0,79}$", export_id or ""):
        raise ValueError("匯出代號不合法：%r" % (export_id,))
    if export_id in _EXPORTS:
        return                                                # 模組重複載入（測試）時冪等
    bad = set(formats) - set(CAPS)
    if bad:
        raise ValueError("不認得的格式：%s" % sorted(bad))
    if sheets:
        if columns:
            raise ValueError("工作表型的匯出不能同時有欄位目錄")
        ids = [x["id"] for x in sheets]
        if len(set(ids)) != len(ids) or not all(re.match(r"^[a-z][a-z0-9_]{0,29}$", i) for i in ids):
            raise ValueError("工作表代號重複或不合法：%s" % ids)
        if not any(x.get("required") for x in sheets):
            raise ValueError("工作表目錄至少要有一張必選")
        caps = ()                                                 # 工作表型不收頁首／頁尾／浮水印
    elif not columns and tuple(formats) != ("pdf",):
        raise ValueError("只有 pdf-only 的匯出可以沒有欄位目錄")
    if caps is not None and set(caps) - CAPS[formats[0]]:
        raise ValueError("caps 超出格式能力：%s" % sorted(set(caps) - CAPS[formats[0]]))
    seen = set()
    for c in columns:
        if c["id"] in seen:
            raise ValueError("欄位目錄重複：%s" % c["id"])
        seen.add(c["id"])
    _EXPORTS[export_id] = {"label": label, "formats": tuple(formats), "columns": [dict(c) for c in columns],
                           "sample_rows": list(sample_rows), "rows_provider": rows_provider, "lock_labels": bool(lock_labels),
                           "caps": frozenset(caps) if caps is not None else None, "sample_html": sample_html,
                           "sheets": [{"id": x["id"], "label": x["label"], "required": bool(x.get("required")), "money": bool(x.get("money"))} for x in (sheets or [])]}


def registered() -> dict:
    """⇒ {export_id: {label, formats, columns:[{id,label,money}]}}（不含 callable）。"""
    return {k: {"label": v["label"], "formats": list(v["formats"]), "lockLabels": v["lock_labels"],
                "caps": {f: sorted(v["caps"] if v["caps"] is not None else CAPS[f]) for f in v["formats"]}, "decorOnly": not v["columns"] and not v["sheets"],
                "sheets": [dict(x) for x in v["sheets"]],
                "columns": [{"id": c["id"], "label": c["label"], "money": bool(c.get("money") or c.get("visible"))} for c in v["columns"]]}
            for k, v in sorted(_EXPORTS.items())}


def default_template(export_id) -> dict:
    spec = _EXPORTS[export_id]
    if spec["sheets"]:                                             # 工作表型：預設＝全部工作表（與今天的報表相同）
        return {"version": 1, "format": spec["formats"][0], "sheets": [x["id"] for x in spec["sheets"]]}
    if not spec["columns"]:
        return {"version": 1, "format": spec["formats"][0], "footer": {"text": "內部資料"}}
    return {"version": 1, "format": spec["formats"][0], "columns": [{"id": c["id"], "label": c["label"]} for c in spec["columns"]]}


# ── 驗證 ──────────────────────────────────────────────────────────────────
def _skeleton(v):
    return "".join(ch for ch in unicodedata.normalize("NFKC", v).casefold() if ch.isalnum())


def _reserved_hit(v):
    sk = _skeleton(v)
    return [w for w in RESERVED_WATERMARK if _skeleton(w) in sk]


def _text_problem(v, limit, what, presets=None):
    """欄位標題（自由文字，`presets=None`）與頁首／頁尾／浮水印（`presets`＝白名單，只能挑）共用。"""
    if not isinstance(v, str) or not v.strip():
        return "%s必須是不空白的文字" % what
    if len(v) > limit:
        return "%s最多 %d 字" % (what, limit)
    if any(unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp", "Co", "Cs") or ch in _FILLERS for ch in v):
        return "%s不可含控制、隱形、雙向或私用字元" % what
    if _BAD_CHARS.search(v):
        return "%s不可含 < > & 引號、反斜線、花括號（不支援占位符）或控制／雙向字元" % what
    if v.lstrip()[:1] in _TRIGGERS:
        return "%s不可以 = + - @ 開頭" % what
    if presets is not None:
        hit = _reserved_hit(v)
        if hit:
            return "%s不可含官方狀態字樣：%s（狀態字樣只由系統依單據真實狀態產生）" % (what, "、".join(hit))
        if v not in presets:
            return "%s請從預設清單挑選：%s" % (what, "、".join(presets))
    return ""


def definition_problems(key, body) -> list:
    """⇒ `[{path, message}]`（空＝通過）。不看旗標（旗標由 `_kind_validator` 管）。"""
    spec = _EXPORTS.get(key)
    if spec is None:
        return [{"path": "", "message": "不是已登記的匯出：%r" % (key,)}]
    if not isinstance(body, dict):
        return [{"path": "", "message": "範本必須是物件"}]
    out = [{"path": k, "message": "不認得的鍵：%s" % k} for k in body if k not in _TOP_KEYS]
    if body.get("version") != 1 or isinstance(body.get("version"), bool):
        out.append({"path": "version", "message": "version 必須是 1"})
    fmt = body.get("format")
    if fmt not in spec["formats"]:
        out.append({"path": "format", "message": "這個匯出只支援：%s" % "、".join(spec["formats"])})
        caps = frozenset()
    else:
        caps = spec["caps"] if spec["caps"] is not None else CAPS[fmt]
    cols = body.get("columns")
    ids = {c["id"] for c in spec["columns"]}
    if "sheets" in body and not spec["sheets"]:
        out.append({"path": "sheets", "message": "這個匯出沒有工作表可選"})
    if spec["sheets"]:                                                   # 工作表型：只能選要哪幾張
        if cols:
            out.append({"path": "columns", "message": "這個匯出由多張工作表組成，只能選要哪幾張，沒有欄位可選"})
        sh = body.get("sheets")
        cat = [x["id"] for x in spec["sheets"]]
        if not isinstance(sh, list) or not sh or not all(isinstance(x, str) for x in sh):
            out.append({"path": "sheets", "message": "sheets 必須是不空的字串清單（工作表代號）"})
        else:
            bad = [x for x in sh if x not in cat]
            if bad:
                out.append({"path": "sheets", "message": "不在這個匯出的工作表目錄裡：%s" % "、".join(map(str, bad))})
            elif len(set(sh)) != len(sh):
                out.append({"path": "sheets", "message": "工作表重複"})
            else:
                miss = [x["label"] for x in spec["sheets"] if x["required"] and x["id"] not in sh]
                if miss:
                    out.append({"path": "sheets", "message": "必選的工作表不能拿掉：%s" % "、".join(miss)})
                if sh != [c for c in cat if c in sh]:
                    out.append({"path": "sheets", "message": "工作表順序固定（依目錄順序），不能調換"})
    elif not spec["columns"]:                                            # decorOnly：版面固定，沒有欄位可選
        if cols:
            out.append({"path": "columns", "message": "這個匯出的版面是固定的，只能加頁首／頁尾／浮水印文字，沒有欄位可選"})
        if not any(k in body for k in ("header", "footer", "watermark")):
            out.append({"path": "", "message": "至少要設定一項：頁首、頁尾或浮水印文字"})
    elif not isinstance(cols, list) or not cols:
        out.append({"path": "columns", "message": "columns 必須是不空的清單"})
    else:
        if len(cols) > MAX_COLUMNS:
            out.append({"path": "columns", "message": "最多 %d 欄" % MAX_COLUMNS})
        seen = set()
        labels = set()
        for i, c in enumerate(cols):
            p = "columns[%d]" % i
            if not isinstance(c, dict):
                out.append({"path": p, "message": "欄位必須是物件"})
                continue
            out.extend({"path": "%s.%s" % (p, k), "message": "不認得的鍵：%s（欄位只有 id、label；沒有公式、格式碼或自訂來源）" % k} for k in c if k not in ("id", "label"))
            if c.get("id") not in ids:
                out.append({"path": p + ".id", "message": "不在這個匯出的欄位目錄裡：%r" % (c.get("id"),)})
            elif c["id"] in seen:
                out.append({"path": p + ".id", "message": "欄位重複：%s" % c["id"]})
            seen.add(c.get("id"))
            msg = _text_problem(c.get("label"), LABEL_MAX, "欄位標題")
            if not msg and spec["lock_labels"] and c.get("id") in ids and c["label"] != next(x["label"] for x in spec["columns"] if x["id"] == c["id"]):
                msg = "這個匯出的檔案會被匯入回來（靠表頭文字對應），欄位標題不能改名"
            if msg:
                out.append({"path": p + ".label", "message": msg})
            elif c["label"].strip() in labels:
                out.append({"path": p + ".label", "message": "欄位標題重複：%s" % c["label"]})
            else:
                labels.add(c["label"].strip())
    for part, limit in (("header", TEXT_MAX), ("footer", TEXT_MAX), ("watermark", WATERMARK_MAX)):
        if part not in body:
            continue
        v = body[part]
        if part not in caps and fmt in spec["formats"]:
            out.append({"path": part, "message": "%s沒有%s" % (("%s格式" % fmt.upper()) if spec["caps"] is None else "這個匯出", {"header": "頁首", "footer": "頁尾", "watermark": "浮水印"}[part])})
            continue
        if not isinstance(v, dict):
            out.append({"path": part, "message": "%s必須是物件（只有 text）" % part})
            continue
        out.extend({"path": "%s.%s" % (part, k), "message": "不認得的鍵：%s" % k} for k in v if k != "text")
        msg = _text_problem(v.get("text"), limit, {"header": "頁首文字", "footer": "頁尾文字", "watermark": "浮水印文字"}[part],
                            WATERMARK_PRESETS if part == "watermark" else PRESET_TEXTS)
        if msg:
            out.append({"path": part + ".text", "message": msg})
    return out


def _kind_validator(body, key):
    if not enabled():
        return [{"path": "", "message": OFF_REASON}]
    return definition_problems(key, body)


def ensure_kind():
    """惰性登記 kind（旗標關＝不登記，`/api/definition-kinds` 與今天相同）。旗標開啟後，第一次有人碰到定義介面時才登記（definitions／治理路由會呼叫）。"""
    if KIND not in D.kinds() and enabled():
        try:
            D.register_kind(KIND, label="匯出範本", validator=_kind_validator)
        except ValueError:                                   # 並行登記 ⇒ 已存在
            pass
    return KIND in D.kinds()


# ── 執行期 ────────────────────────────────────────────────────────────────
def resolve(export_id, conn=None):
    """⇒ 已發布且仍合法的範本，或 None（旗標關、沒有已發布、不合法、任何錯誤 ⇒ None＝端點走今天寫死的路徑）。"""
    if export_id not in _EXPORTS or not enabled(conn):
        return None
    ensure_kind()
    try:
        from db import get_db
        own = conn is None
        c = conn if conn is not None else get_db()
        try:
            r = D.get(c, KIND, export_id, "company")
        finally:
            if own:
                c.close()
        body = (r or {}).get("body")
        if not body or definition_problems(export_id, body):
            return None
        return body
    except Exception:                                        # noqa: BLE001
        return None


def effective_columns(export_id, template, user):
    """⇒ (欄位清單 `[{id,label}]`, 省略清單 `[{id, reason}]`)。遮蔽優先：money／有 visible 的欄位在這裡再驗一次權限。"""
    spec = _EXPORTS[export_id]
    byid = {c["id"]: c for c in spec["columns"]}
    cols, omitted = [], []
    for c in template["columns"]:
        d = byid[c["id"]]
        if d.get("money") or d.get("visible"):
            fn = d.get("visible")
            try:
                ok = bool(fn(user)) if fn else False
            except Exception:                                # noqa: BLE001  驗權限出錯 ⇒ 不顯示
                ok = False
            if not ok:
                omitted.append({"id": c["id"], "reason": "這位使用者沒有這個欄位的檢視權限"})
                continue
        cols.append({"id": c["id"], "label": c["label"]})
    return cols, omitted


def render_rows(export_id, template, rows, user):
    """⇒ `(table, omitted)`：第一列是標題；每個儲存格經該格式的中和函式（csv ⇒ `csv_safe`；xlsx ⇒ `xl_safe_xlsx`）。
    `rows`＝`[{col_id: value}]`（端點今天的查詢結果，已依檢視者遮蔽）。"""
    safe = xl_safe_xlsx if template.get("format") == "xlsx" else csv_safe
    cols, omitted = effective_columns(export_id, template, user)
    out = [[safe(c["label"]) for c in cols]]
    for r in rows:
        out.append([safe(r.get(c["id"])) for c in cols])
    return out, omitted


def render_csv_rows(export_id, template, rows, user):
    """CSV 版（保留既有呼叫端）；等同 `render_rows`。"""
    return render_rows(export_id, template, rows, user)


def apply_print_text(ws, template):
    """xlsx 的頁首／頁尾＝列印頁首頁尾（不佔儲存格，資料區位置不變）；文字已通過驗證（無 & 等控制字元）。"""
    for part, target in (("header", "oddHeader"), ("footer", "oddFooter")):
        t = (template.get(part) or {}).get("text")
        if t:
            getattr(ws, target).center.text = t


_PDF_CSS = ("<style>.mx-wm,.mx-ft,.mx-hd{position:fixed;left:0;width:100%;text-align:center;pointer-events:none}"
            ".mx-wm{top:42%;font-size:64pt;font-weight:bold;color:rgba(0,0,0,.08);transform:rotate(-30deg);white-space:nowrap;z-index:0}"
            ".mx-hd,.mx-ft{font-size:8pt;color:#666;z-index:1}.mx-hd{top:1mm}.mx-ft{bottom:1mm}</style>")


def apply_pdf_text(html, template):
    """PDF 的頁首／頁尾／浮水印：只收已通過驗證的純文字，輸出一律跳脫；浮水印在內容下層、淺灰、透明度固定 ≤ 20%、角度固定；
    程式產生的『尚未核准』橫幅、公司抬頭與法定欄位由各 builder 自己負責，不受這裡影響（這裡只插入固定樣式的小區塊）。"""
    from helpers.doc_template import attr_esc
    parts = []
    for key, cls in (("watermark", "mx-wm"), ("header", "mx-hd"), ("footer", "mx-ft")):
        t = (template.get(key) or {}).get("text")
        if t:
            parts.append('<div class="%s">%s</div>' % (cls, attr_esc(t)))
    if not parts:
        return html
    block = _PDF_CSS + "".join(parts)
    m = re.search(r"<body[^>]*>", html, re.I)
    return html[:m.end()] + block + html[m.end():] if m else block + html


def decorate_pdf(export_id, html, conn=None):
    """PDF builder 的掛鉤：旗標關／沒有已發布範本 ⇒ 原樣回傳同一個字串物件（輸出逐位元相同）。"""
    tpl = resolve(export_id, conn)
    return html if tpl is None else apply_pdf_text(html, tpl)


def enabled_sheets(export_id, conn=None):
    """工作表型匯出的執行期掛鉤：⇒ `None`（全部工作表＝今天的輸出：旗標關／沒有已發布範本／不是工作表型／任何錯誤）或已選工作表代號的 frozenset（含必選）。"""
    spec = _EXPORTS.get(export_id)
    if not spec or not spec["sheets"]:
        return None
    tpl = resolve(export_id, conn)
    if tpl is None or not isinstance(tpl.get("sheets"), list):
        return None
    sel = {x for x in tpl["sheets"] if isinstance(x, str)}
    return frozenset(sel | {x["id"] for x in spec["sheets"] if x["required"]})


def disabled_sheets(export_id, conn=None) -> list:
    """沒被選到的工作表代號（依目錄順序）；全部都要 ⇒ `[]`。"""
    sel = enabled_sheets(export_id, conn)
    if sel is None:
        return []
    return [x["id"] for x in _EXPORTS[export_id]["sheets"] if x["id"] not in sel]


def preview(conn, caller, body, export_id, username=None, sample="sample", n=20):
    """草稿預覽（唯讀、不寫任何資料、不計匯出次數）：以某位使用者（預設＝呼叫者）的權限算出實際會輸出的標題與前 n 列。
    ⇒ `{user, role, format, columns, rows, omitted, warnings, sample}`；草稿不合法 ⇒ ValueError(problems)；找不到使用者 ⇒ LookupError。"""
    if export_id not in _EXPORTS:
        raise LookupError("不是已登記的匯出")
    probs = definition_problems(export_id, body)
    if probs:
        raise ValueError(probs)
    if username:
        row = conn.execute("SELECT id, username, role, modules FROM users WHERE username=? AND active=1", (str(username),)).fetchone()
        if not row:
            raise LookupError("找不到這位使用者")
        viewer = {"id": row["id"], "username": row["username"], "role": row["role"], "modules": row["modules"]}
    else:
        viewer = caller
    n = max(1, min(int(n or 20), 50))
    spec = _EXPORTS[export_id]
    warnings = []
    if spec["sheets"]:                                         # 工作表型：列出會出現哪些工作表（不產生實際檔案）
        chosen = set(body.get("sheets") or [])
        sheets = [{"id": x["id"], "label": x["label"], "on": x["id"] in chosen or x["required"], "required": x["required"], "money": x["money"]} for x in spec["sheets"]]
        off = [x["label"] for x in sheets if not x["on"]]
        if off:
            warnings.append("以下工作表不會出現在報表（Excel、PDF、月報郵件都一樣）：%s。重新加回含金額的工作表需要第二位最高管理者核准。" % "、".join(off))
        return {"user": viewer.get("username"), "role": viewer.get("role"), "format": body["format"], "sheets": sheets, "columns": [], "rows": [],
                "omitted": [], "warnings": warnings, "sample": "sample", "header": None, "footer": None}
    if not spec["columns"]:                                   # decorOnly（PDF）：只提供樣本頁預覽；實際文件發布後下載確認
        base = spec["sample_html"] or "<!doctype html><html><body><h2>預覽樣本頁</h2><p>實際文件的內容與版面不受這些文字影響。</p></body></html>"
        return {"user": viewer.get("username"), "role": viewer.get("role"), "format": body["format"], "decorOnly": True,
                "html": apply_pdf_text(base, body), "columns": [], "rows": [], "omitted": [], "sample": "sample",
                "warnings": ["PDF 只提供樣本頁預覽（證明文字放在哪裡）；實際文件請在發布後下載確認。程式產生的橫幅與法定欄位不受影響。"],
                "header": (body.get("header") or {}).get("text"), "footer": (body.get("footer") or {}).get("text"),
                "watermark": (body.get("watermark") or {}).get("text")}
    if sample == "visible":
        prov = spec["rows_provider"]
        rows = list(prov(conn, viewer, n))[:n] if prov else []
        if not rows:
            warnings.append("這位使用者目前沒有可預覽的真實資料；改看樣本列。")
            rows = spec["sample_rows"][:n]
            sample = "sample"
    else:
        rows = spec["sample_rows"][:n]
    table, omitted = render_rows(export_id, body, rows, viewer)
    if omitted:
        warnings.append("有 %d 個欄位因這位使用者沒有檢視權限而不會出現。" % len(omitted))
    return {"user": viewer.get("username"), "role": viewer.get("role"), "format": body["format"],
            "columns": table[0], "rows": table[1:], "omitted": omitted, "warnings": warnings, "sample": sample,
            "header": (body.get("header") or {}).get("text"), "footer": (body.get("footer") or {}).get("text")}
