# -*- coding: utf-8 -*-
"""傳票附件（`JV3`）的**來源解析**與**複製**。

施工圖：`docs/windows/SPEC-JV3-ATTACHMENTS.md`。

# 🔴 帶入 ＝ **複製檔案**，不是引用

```
引用（只存路徑）  => 別人刪掉來源附件 ⇒ **一張已過帳傳票的憑證消失**
複製             => 多佔空間，而憑證留得住
```
⚠️ 而「禁止刪除來源」這一招在這裡**不成立**（科目那邊可以是因為實作路徑不同）：
```
account_items  刪除走 SQL        => CREATE TRIGGER … RAISE(ABORT) 擋得到 ✅
附件           刪除走 os.remove() => **沒有任何 DB TRIGGER 攔得到** ❌
```

# ☠️ 這份對照表是**逐一開 `PRAGMA table_info` 對過的**，不是照抄規格

規格第一版把 `quotations` 的欄位寫成 `files_json`，而那個欄位**不存在**
（實際是 `signed_files_json`，語意也更窄：那是報價單**回簽檔**）。
🔑 錯一個的症狀是「**那一類的清單永遠是空的，而它不會報錯**」——
   畫面上看起來像「這個案件沒有那一類附件」，不像一個缺陷。
📌 而 `PRAGMA table_info` 是權威，`db.py` 的原始碼不是：用 regex 開視窗掃
   原始碼會跨到隔壁的 `CREATE TABLE`，**拿到一份混了別張表而看起來很完整的清單**。
"""
import json
import os
import shutil
import uuid

from fastapi import HTTPException

# 🔴 **整個模組 import，不要 `from … import UPLOADS_ROOT`。**
#
# ```
# from helpers.uploads import UPLOADS_ROOT   <= 在**這支被 import 的當下**取值
# conftest 之後 monkeypatch 那個常數          => 改的是 helpers.uploads 的屬性
#                                            => **我手上這一份不會變**
# ```
# ☠️ 症狀：`save_document_files()` 把檔存到被導向的暫存目錄，而這裡去
#    **真正的 `uploads/`** 找 ⇒ 「檔案不存在」⇒ 帶入整批被拒、作廢重開複製 0 筆
#    —— 而那三支的訊息都指向「來源檔不見了」，**看起來像資料的問題**。
# 🔑 而正式機上同樣成立：任何**在執行期重新指定**那個常數的做法都會失效。
# ⇒ 一律 `_uploads.UPLOADS_ROOT`，在**用到的那一刻**才取。
import helpers.uploads as _uploads
from helpers.uploads import _effective_subfolder

#: 帶入來源的白名單。**一份可以數的清單**，不可以散在 if/elif 裡 ——
#: 散著的話「少一類」永遠不會有人發現。
#:
#: ⚠️ `voucher` 不在這裡：它**只由作廢重開的複製產生**，
#:    使用者不能主動從一張傳票帶入另一張傳票。
SOURCE_TYPES = (
    "quotation_signed",     # 報價單回簽檔
    "case_update",          # 案件動態
    "payment_item",         # 收款項目的發票影本
    "material",             # 叫料清單的附件
    "material_invoice",     # 叫料清單的發票／包裝清單
    "extra_expense",        # 案件額外支出
    "invoice_voucher",      # 開票申請
    "contractor_dispatch",  # 承攬商派工
    "contractor_invoice",   # 承攬商發票
)

#: 作廢重開複製時填的來源型別。
COPY_SOURCE_TYPE = "voucher"

#: 🔴 **明著排除的**，不是漏掉的。
#:
#: ```
#: completion_note / shipping_note / dev_log   不是會計憑證
#: pending_case_change                         **待核准的暫存附件**
#: ```
#: ☠️ 最後一個帶進傳票 ＝ 讓一個**還沒核准**的東西變成憑證。
#:    依據 `case_extra_expenses.py:629` 逐字：「核准前不會出現在正式附件清單」。
EXCLUDED_SOURCES = ("completion_note", "shipping_note", "dev_log",
                    "pending_case_change")

#: `save_document_files()` 產出的 metadata 有七個鍵；來源資料**可能缺其中幾個**。
#: 📌 實查（2026-09-23 開發機）：六個來源欄位裡的檔案 metadata **總筆數 1**，
#:    而那一筆只有 `filename／id／path` ⇒ **樣本數 1，不足以推論既有資料的形狀**。
#: ⇒ 所以這裡決定的是「不完整時做什麼」，不是「怎麼相容」。
_OPTIONAL_META = ("size", "mime", "uploadedBy", "uploadedAt")


def _quote_and_index(doc_no):
    """`{quote_no}_{idx}` 拆成 `(quote_no, idx)`。拆不出來回 `(doc_no, None)`。

    ⚠️ 從**右邊**切：報價單號本身含 `-` 不含 `_`，而索引一定在最後一段。
    """
    base, sep, tail = (doc_no or "").rpartition("_")
    if sep and tail.isdigit():
        return base, int(tail)
    return doc_no, None


def _json_col(conn, table, key_col, key, col):
    row = conn.execute("SELECT %s AS v FROM %s WHERE %s = ?" % (col, table, key_col),
                       (key,)).fetchone()
    if row is None:
        return []
    try:
        return json.loads(row["v"] or "[]") or []
    except (TypeError, ValueError):
        # ⚠️ 壞掉的 JSON **不要吞成空清單** —— 吞掉之後「這裡沒有附件」與
        #    「這裡的資料壞了」在畫面上一模一樣。
        raise HTTPException(400, "來源「%s」的附件資料格式不正確，無法帶入。" % table)


def _case_record(conn, quote_no):
    row = conn.execute("SELECT data_json FROM quotations WHERE quote_no = ?",
                       (quote_no,)).fetchone()
    if row is None:
        return {}
    try:
        return (json.loads(row["data_json"] or "{}") or {}).get("caseRecord") or {}
    except (TypeError, ValueError):
        raise HTTPException(400, "案件「%s」的資料格式不正確，無法帶入。" % quote_no)


def source_files(conn, source_type, doc_no):
    """某一個來源底下的檔案 metadata 陣列。找不到來源就回空清單。

    ## 🔴 三個來源在 `quotations.data_json` 的陣列**裡面**

    ```
    payment_item      caseRecord.payment.items[idx].invoiceFiles
    material          caseRecord.materials[idx].files
    material_invoice  caseRecord.materials[idx].invoiceFiles
    ```
    ⚠️ 「購料」**不在** `material_orders`（那張表 0 處 `files_json`）——
       它掛在報價單底下的材料明細。☠️ 找錯地方會做出一個**永遠是空的清單，
       而它不會報錯**。
    """
    if source_type == "quotation_signed":
        return _json_col(conn, "quotations", "quote_no", doc_no,
                         "signed_files_json")
    if source_type == "case_update":
        # 一個案件有很多則動態 ⇒ 全部併起來（`file_id` 本來就唯一）。
        out = []
        for row in conn.execute(
                "SELECT files_json FROM case_updates WHERE quote_no = ?", (doc_no,)):
            try:
                out += json.loads(row["files_json"] or "[]") or []
            except (TypeError, ValueError):
                raise HTTPException(400, "案件動態的附件資料格式不正確，無法帶入。")
        return out
    if source_type in ("payment_item", "material", "material_invoice"):
        quote_no, idx = _quote_and_index(doc_no)
        if idx is None:
            raise HTTPException(
                400, "來源編號「%s」缺少項目索引（應為「案件編號_序號」）。" % doc_no)
        cr = _case_record(conn, quote_no)
        if source_type == "payment_item":
            arr = ((cr.get("payment") or {}).get("items") or [])
            key = "invoiceFiles"
        else:
            arr = cr.get("materials") or []
            key = "files" if source_type == "material" else "invoiceFiles"
        if idx < 0 or idx >= len(arr):
            return []
        return (arr[idx] or {}).get(key) or []
    if source_type == "extra_expense":
        return _json_col(conn, "case_extra_expenses", "id", doc_no, "files_json")
    if source_type == "invoice_voucher":
        return _json_col(conn, "invoice_vouchers", "voucher_no", doc_no,
                         "issued_files_json")
    if source_type == "contractor_dispatch":
        return _json_col(conn, "contractor_dispatches", "id", doc_no, "files_json")
    if source_type == "contractor_invoice":
        return _json_col(conn, "contractor_dispatches", "id", doc_no,
                         "invoice_files_json")
    # 🔑 走到這裡代表白名單與這支 if 鏈分岔了 —— 讓它**吵**，不要回空清單。
    raise HTTPException(400, "不支援的附件來源「%s」。" % source_type)


def abs_path(rel):
    """`uploads/` 相對路徑 -> 絕對路徑，並**擋住跳出上傳根目錄**。

    ☠️ 來源路徑雖然來自資料庫而不是請求，仍然要擋：
       資料庫裡的值是**很久以前某一次請求寫進去的**。
    """
    p = os.path.realpath(os.path.join(_uploads.UPLOADS_ROOT, str(rel or "").lstrip("/\\")))
    root = os.path.realpath(_uploads.UPLOADS_ROOT)
    if p != root and not p.startswith(root + os.sep):
        raise HTTPException(400, "附件路徑不合法。")
    return p


def describe_missing(meta):
    """這一筆 metadata 缺了哪幾個**非必要**欄位。回欄位名清單。

    🔴 缺欄位 ⇒ **照樣複製，缺的留空，而在回應裡回報**。
    ☠️ 靜默補預設值的後果：傳票上顯示一個看起來正常的上傳者與時間，
       **而那是我們編的**。
    """
    return [k for k in _OPTIONAL_META if not (meta or {}).get(k)]


def resolve_picks(conn, picks):
    """把 `[{type, docNo, fileId}]` 解析成可以複製的清單。

    ## 🔴 **先把全部來源檔檢查完，再開始複製**

    ☠️ 邊複製邊檢查的話，第三筆失敗時**前兩筆已經落地了** ——
       而回應說失敗 ⇒ 使用者重試 ⇒ 前兩筆變成兩份。
    🔑 拒絕的路徑上不可以留下副作用。

    ## 🔴 實體檔不存在 ⇒ **整批拒絕 400**，明說哪一筆

    ☠️ 跳過它的後果：使用者以為附件帶進來了，
       **過帳之後才發現那張憑證從來沒存在過**。
    ⚠️ 而它不是理論情況：開發機上唯一一筆既有 metadata 的 `path`
       就指向一個不存在的檔。
    """
    resolved = []
    for i, pick in enumerate(picks or (), start=1):
        st = ((pick or {}).get("type") or "").strip()
        doc_no = str((pick or {}).get("docNo") or "").strip()
        file_id = str((pick or {}).get("fileId") or "").strip()
        if st in EXCLUDED_SOURCES:
            raise HTTPException(
                400, "「%s」不是會計憑證來源，不可以帶入傳票。" % st)
        if st not in SOURCE_TYPES:
            raise HTTPException(400, "不支援的附件來源「%s」。" % st)
        if not doc_no or not file_id:
            raise HTTPException(400, "第 %d 筆帶入缺少來源編號或檔案編號。" % i)
        files = source_files(conn, st, doc_no)
        meta = next((f for f in files
                     if str((f or {}).get("id") or "") == file_id), None)
        if meta is None:
            raise HTTPException(
                400, "在來源「%s／%s」裡找不到檔案 %s。" % (st, doc_no, file_id))
        src = abs_path(meta.get("path"))
        if not os.path.isfile(src):
            raise HTTPException(
                400, "來源檔案已經不存在：%s（%s／%s）。"
                     "請確認該筆附件還在，或改用直接上傳。"
                     % (meta.get("filename") or meta.get("name") or file_id,
                        st, doc_no))
        resolved.append({
            "source_type": st,
            "source_doc_no": doc_no,
            "source_file_id": file_id,
            "src": src,
            "meta": meta,
            "missing": describe_missing(meta),
        })
    return resolved


def copy_into(voucher_id, src_abs, filename, subfolder="voucher_attachments"):
    """把一個實體檔複製進這張傳票的目錄。回 `(file_id, rel_path, size)`。

    ## 🔴 路徑用 `voucher_id`，**不可以含單號**

    ☠️ 退回升版之後單號變 `-R1`，含單號的路徑會指向一個**不存在的資料夾**
       —— 而它不報錯，只是附件消失。

    ## 🔴 每一次都**產生新的 `file_id`**，而且**真的複製 bytes**

    ```
    idx_vatt_file 是 UNIQUE
      擋得住  同一個 file_id 出現在兩列
      擋不住  兩列各自有 file_id，而 path 指向**同一個實體檔**
    ```
    ☠️ 共用實體檔的失敗方式很安靜：在新單刪掉一個附件**成功了**，
       而少掉的是一張已作廢傳票的憑證 —— 沒有人會在當下發現。
    """
    sub = _effective_subfolder(subfolder)
    dest_dir = os.path.join(_uploads.UPLOADS_ROOT, sub, str(voucher_id))
    os.makedirs(dest_dir, exist_ok=True)
    ext = os.path.splitext(filename or "")[1].lower()
    fname = uuid.uuid4().hex[:16] + ext
    shutil.copyfile(src_abs, os.path.join(dest_dir, fname))
    rel = "%s/%s/%s" % (sub, voucher_id, fname)
    return uuid.uuid4().hex[:8], rel, os.path.getsize(os.path.join(dest_dir, fname))


#: 一個案件底下，每一類的 `doc_no` **怎麼從案件編號查出來**。
#:
#: 🔴 四類的 `doc_no` **不是案件編號**，而這四類原本整個選不到：
#: ```
#: extra_expense        自己的 id
#: invoice_voucher      開票申請單號
#: contractor_dispatch  派工 id
#: contractor_invoice   派工 id   <= **與上一個完全相同**
#: ```
#: ☠️ 選不到的症狀是「這個案件的**承攬商發票**帶不進來」，
#:    而畫面上看起來只是「沒有那一類」—— **不像一個缺陷**。
#: ✅ 而修法很便宜：那四類的表**都有 `quote_no` 欄** ⇒ 一句 SELECT 就涵蓋得到，
#:    **不需要新的選取介面**。
#:
#: ⚠️ 最後兩類共用**同一個 `doc_no`**（同一張派工單的兩個欄位）
#:    ⇒ 清單的鍵必須是 **`(type, docNo)`**，只用 `docNo` 去重會把兩組併成一組
#:    ☠️ 而少的那一組不會報錯：那張派工單還在，**只是少了一半**。
_CASE_DOC_NO_SQL = {
    "extra_expense":
        "SELECT id AS k FROM case_extra_expenses WHERE quote_no = ? ORDER BY id",
    "invoice_voucher":
        "SELECT voucher_no AS k FROM invoice_vouchers WHERE quote_no = ? ORDER BY id",
    "contractor_dispatch":
        "SELECT id AS k FROM contractor_dispatches WHERE quote_no = ? ORDER BY id",
    "contractor_invoice":
        "SELECT id AS k FROM contractor_dispatches WHERE quote_no = ? ORDER BY id",
}

#: `doc_no` **就是案件編號**的那幾類。
_CASE_DOC_NO_IS_QUOTE = ("quotation_signed", "case_update")

#: `doc_no` 是 `{案件編號}_{索引}` 的那幾類（項目在 `data_json` 的陣列裡）。
_CASE_DOC_NO_INDEXED = {
    "payment_item": ("payment", "items"),
    "material": (None, "materials"),
    "material_invoice": (None, "materials"),
}

#: 一個案件底下**找得到附件的那幾類** —— 現在是**全部九類**。
#: ⚙️ 它是算出來的，而下面那個 assert 在 import 時就會吵：
#:    三份對照表的聯集必須剛好等於 `SOURCE_TYPES`。
#: 🔑 少一類的症狀是「那一類永遠是空的清單，**而它不會報錯**」
#:    ⇒ 讓它在**載入模組**的時候就壞，不要等到使用者發現。
_CASE_SCOPED = tuple(SOURCE_TYPES)
assert set(_CASE_SCOPED) == (set(_CASE_DOC_NO_IS_QUOTE)
                             | set(_CASE_DOC_NO_INDEXED)
                             | set(_CASE_DOC_NO_SQL)), (
    "三份 doc_no 對照表的聯集與 SOURCE_TYPES 對不上。")


def _case_doc_nos(conn, source_type, quote_no):
    """這一類在這個案件底下有哪些 `doc_no`。

    ⚠️ 三種形狀各走各的路，**而它們不可以合成一條** ——
       合起來的話，加一類新來源時要先猜它屬於哪一種。
    """
    if source_type in _CASE_DOC_NO_IS_QUOTE:
        return [quote_no]
    if source_type in _CASE_DOC_NO_INDEXED:
        outer, key = _CASE_DOC_NO_INDEXED[source_type]
        cr = _case_record(conn, quote_no)
        arr = (cr.get(outer) or {}).get(key) if outer else cr.get(key)
        return ["%s_%d" % (quote_no, i) for i in range(len(arr or []))]
    sql = _CASE_DOC_NO_SQL[source_type]
    return [str(r["k"]) for r in conn.execute(sql, (quote_no,))]


def case_attachments(conn, quote_no):
    """一個案件底下所有**可帶入**的憑證。回 `[{type, docNo, fileId, filename, …}]`。

    ⚠️ 實體檔不存在的那幾筆**照樣列出來並標記** ——
    ☠️ 濾掉的話，使用者會覺得「那張發票我明明傳過」而畫面上什麼都沒有；
       列出來並標「檔案已遺失」，他至少知道要去哪裡重傳。
    📌 而真的按下帶入時**會被擋**（`resolve_picks()` 整批 400）——
       兩層的職責不同：這一層**說實話**，那一層**擋住錯誤的結果**。
    """
    out = []
    for st in _CASE_SCOPED:
        for doc_no in _case_doc_nos(conn, st, quote_no):
            for meta in source_files(conn, st, doc_no) or ():
                name = (meta or {}).get("filename") or (meta or {}).get("name") or ""
                try:
                    exists = os.path.isfile(abs_path((meta or {}).get("path")))
                except HTTPException:
                    exists = False
                out.append({
                    "type": st,
                    "docNo": doc_no,
                    "fileId": str((meta or {}).get("id") or ""),
                    "filename": name,
                    "exists": exists,
                    "missing": describe_missing(meta),
                })
    return out
