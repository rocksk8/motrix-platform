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


#: 每一類來源由哪一個模組提供（`attachments.for_document`，主持裁示 M06-b）——只用在「模組不在」時說出是誰不在。
#: 誰在場以登錄表為準（`_providers()`）；這張表只負責缺席時的那一句話。
_SOURCE_OWNERS = {
    "quotation_signed": ("case", "案件", "報價單回簽檔"),
    "case_update": ("case", "案件", "案件動態"),
    "payment_item": ("case", "案件", "收款項目發票影本"),
    "material": ("case", "案件", "叫料附件"),
    "material_invoice": ("case", "案件", "叫料發票／包裝清單"),
    "extra_expense": ("case", "案件", "額外支出"),
    "invoice_voucher": ("arap", "應收應付", "開票申請"),
    "contractor_dispatch": ("subcontract", "外包工班", "派工單"),
    "contractor_invoice": ("subcontract", "外包工班", "承攬商發票"),
}


def _providers():
    """在場的附件來源：{來源類型: 提供者}。每次呼叫都查登錄表（模組啟停後不留舊值）。"""
    from core import registry
    out = {}
    for prov in registry.providers("attachments.for_document").values():
        for st in getattr(prov, "SOURCE_TYPES", ()):
            out[st] = prov
    return out


def _absent_message(st, action):
    owner = _SOURCE_OWNERS.get(st, ("", st, st))
    return "%s模組未安裝，%s%s附件。" % (owner[1], action, owner[2])


def unavailable_sources():
    """白名單裡、提供者不在的類型 ⇒ `[{category, reason}]`（每個缺席模組一筆；畫面照列，不跟「沒有附件」混在一起）。"""
    present = _providers()
    missing = {}
    for st in SOURCE_TYPES:
        if st not in present:
            key, label, what = _SOURCE_OWNERS.get(st, (st, st, st))
            missing.setdefault(key, (label, []))[1].append(what)
    return [{"category": key, "reason": "%s模組未安裝：%s的附件沒有列出" % (label, "、".join(whats))}
            for key, (label, whats) in sorted(missing.items())]


def source_files(conn, source_type, doc_no, user):
    """某一個來源底下的檔案 metadata 陣列（經擁有模組的 `attachments.for_document` 提供者）。

    ```
    提供者不在            => 400「XX模組未安裝，無法帶入YY附件」（不回空清單：那與「沒有附件」一模一樣）
    看不到原單據          => 403（稽核 D AT-M1：只列、只預覽、只帶入使用者看得到的原單據的附件）
    來源資料壞掉／編號不全 => 400（提供者的 AttachmentSourceError，原句）
    單據不存在            => []
    ```
    """
    if source_type not in SOURCE_TYPES:
        # 🔑 走到這裡代表白名單與呼叫端分岔了 —— 讓它**吵**，不要回空清單。
        raise HTTPException(400, "不支援的附件來源「%s」。" % source_type)
    prov = _providers().get(source_type)
    if prov is None:
        raise HTTPException(400, _absent_message(source_type, "無法帶入"))
    try:
        return prov.files(conn, source_type, doc_no, user)
    except _uploads.AttachmentNotVisible:
        raise HTTPException(403, "你沒有權限查看這筆附件的原單據。")
    except _uploads.AttachmentSourceError as e:
        raise HTTPException(400, str(e))


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


def resolve_picks(conn, picks, user):
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
        files = source_files(conn, st, doc_no, user)
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


#: 一個案件底下，每一類的 `doc_no` 怎麼從案件編號查出來 ⇒ 由該類的提供者回答（`doc_nos_for_case`）。
#: ⚠️ `contractor_dispatch` 與 `contractor_invoice` 共用同一個 `doc_no`（同一張派工單的兩個欄位）
#:    ⇒ 清單的鍵必須是 **`(type, docNo)`**，只用 `docNo` 去重會把兩組併成一組，而少的那一組不會報錯。
#: 🔑 「白名單每一類都有人提供」原本是 import 時的 assert；改成守門題
#:    `tests/platform/test_attachments_providers.py`（模組可以不在，不能在載入時就壞）。
_CASE_SCOPED = tuple(SOURCE_TYPES)


def _case_doc_nos(conn, source_type, quote_no, user, providers=None, hidden=None):
    """這一類在這個案件底下有哪些 `doc_no`；提供者不在 ⇒ []（缺席由 `unavailable_sources()` 另外說）；
    看不到（全部或部分）⇒ 只回看得到的，並把「這一類沒列出幾個附件」加進 `hidden`（dict：類別 ⇒ 個數），
    由 `hidden_sources()` 明說（不可以靜默少列）。"""
    prov = (providers if providers is not None else _providers()).get(source_type)
    if prov is None:
        return []
    try:
        return prov.doc_nos_for_case(conn, source_type, quote_no, user)
    except _uploads.AttachmentNotVisible as e:
        if hidden is not None and e.hidden:
            hidden[source_type] = hidden.get(source_type, 0) + e.hidden
        return e.visible
    except _uploads.AttachmentSourceError as e:
        raise HTTPException(400, str(e))


def _used_map(conn):
    """`{(source_type, source_doc_no, source_file_id): [{voucherNo, voucherId,
    usedAt}, …]}`——**一次查詢**，不逐筆查（一個案件可能有幾十個候選憑證）。

    `JV18`（依據使用者 2026-09-23 裁示）：

    ```
    va.deleted_at = ''        軟刪的帶入不算「已使用」（同既有的附件讀取慣例）
    v.voided_at   = ''        已作廢的傳票不算「已使用」——作廢重開是合法
                               流程，複製到新單的那一列 source_* 若也算，
                               每次作廢重開都會讓憑證被標記兩次，其中一次
                               指向一張不存在的帳
    source_* != ''            **三個欄位一起排除空字串**（§2c 後果一）：
                               直接上傳的那幾列 source_* 全是空字串，
                               互相之間三個欄位逐一比對都會相等，若不是
                               用三元組一起比對，會讓一個從未被帶入的候選
                               憑證被誤標成已使用——這是假的紅字，比沒做
                               還糟（使用者會開始不相信這個標記）
    ```
    """
    return _live_uses(
        conn,
        "voucher_attachments va JOIN vouchers_all v ON v.id = va.voucher_id",
        ("va.source_type", "va.source_doc_no", "va.source_file_id"),
        "va.uploaded_at",
        extra_where="va.deleted_at = ''")


def _live_uses(conn, from_sql, key_cols, when_col, extra_where=""):
    """「這個來源被哪幾張傳票用過」的**共用判定**（`JV18` 紅字標記／`JV21` 支出項擋重複）。

    ```
    v.voided_at = ''      已作廢的傳票不算（作廢重開是合法流程）
    每一個來源鍵欄 != ''  空字串不算——沒有來源的列彼此不可以被判成「同一個」
    ```
    回 `{(鍵…): [{voucherNo, voucherId, usedAt}, …]}`（新到舊）。**一次查詢**。
    ⚠️ 兩個呼叫端的差別只在「從哪張表、哪幾欄當鍵」；規則只有這一份。
    """
    cols = ", ".join("%s AS k%d" % (c, i) for i, c in enumerate(key_cols))
    where = ["v.voided_at = ''"] + ["%s != ''" % c for c in key_cols]
    if extra_where:
        where.append(extra_where)
    out = {}
    for row in conn.execute(
            "SELECT %s, %s AS used_at, v.id AS voucher_id, v.voucher_no FROM %s WHERE %s"
            % (cols, when_col, from_sql, " AND ".join(where))):
        key = tuple(row["k%d" % i] for i in range(len(key_cols)))
        out.setdefault(key, []).append({
            "voucherNo": row["voucher_no"],
            "voucherId": row["voucher_id"],
            "usedAt": row["used_at"] or "",
        })
    for entries in out.values():
        entries.sort(key=lambda e: e["usedAt"], reverse=True)
    return out


#: `JV21`：分錄帶入後「只能用一次」的支出來源（案件 `case` 不在內：本來就可以被多張傳票引用）。
EXPENSE_LINE_SOURCES = ("extra_expense", "contractor_dispatch")


def expense_line_uses(conn):
    """`JV21`：`{(source_type, source_key): [{voucherNo, voucherId, usedAt}, …]}`——支出項被哪幾張
    **未作廢**傳票的分錄帶入過。與附件紅字標記同一套判定（`_live_uses`）。

    ⚠️ 已知限制：`JV36` 之前的分錄沒有記來源（`source_key` 空）⇒ 偵測不到，不回填。
    """
    types = ", ".join("'%s'" % t for t in EXPENSE_LINE_SOURCES)
    return _live_uses(
        conn,
        "voucher_lines vl JOIN vouchers_all v ON v.id = vl.voucher_id",
        ("vl.source_type", "vl.source_key"),
        "v.created_at",
        extra_where="vl.source_type IN (%s)" % types)


def hidden_sources(hidden):
    """因權限沒列出的附件 ⇒ 畫面要顯示的說明（形狀同 `unavailable_sources()` 再加 `count`；主持裁示 2026-09-26）：
    任何來源因權限沒列出都要明說（會計不可以以為「沒有」而漏掉），但**只說類別與個數**——
    不帶單號、檔名、金額或任何內容，否則明說本身就是外洩。"""
    return [{"category": "hidden:" + st,          # 前綴：與 unavailable 並列顯示時 key 不撞
             "count": n,
             "reason": "%s：%d 個附件因權限無法顯示（不是沒有）。" % (_SOURCE_OWNERS.get(st, ("", st, st))[2], n)}
            for st, n in (hidden or {}).items() if n]


def case_attachments(conn, quote_no, user, hidden=None):
    """一個案件底下所有**可帶入**的憑證。回 `[{type, docNo, fileId, filename, …}]`。

    ⚠️ 實體檔不存在的那幾筆**照樣列出來並標記** ——
    ☠️ 濾掉的話，使用者會覺得「那張發票我明明傳過」而畫面上什麼都沒有；
       列出來並標「檔案已遺失」，他至少知道要去哪裡重傳。
    📌 而真的按下帶入時**會被擋**（`resolve_picks()` 整批 400）——
       兩層的職責不同：這一層**說實話**，那一層**擋住錯誤的結果**。

    🔴 `JV18`（依據使用者 2026-09-23 裁示）：每一筆再帶三個欄位——
    `used`／`usedAt`／`usedBy`，說出這個候選憑證有沒有被別張傳票帶入過、
    什麼時候、被哪幾張。**`usedBy` 列出全部，不是只列最近一張**——只列
    最近一張會把重複入帳的那一筆藏起來，而重複入帳正是這個功能要防的事。
    **已使用的排在清單最後**，依 `usedAt` 新到舊；未使用的維持原有順序。
    ⚠️ 這裡**只標記，不擋**——已計算的憑證仍然可以再被帶入（使用者原話
    是「備註」不是「擋住」，擋住會把作廢重開那條合法路踩死）。

    `hidden`（dict）：因權限沒列出的附件個數（類別 ⇒ 個數）記在這裡，呼叫端用 `hidden_sources()` 明說。
    """
    used_map = _used_map(conn)
    providers = _providers()
    out = []
    for st in _CASE_SCOPED:
        if st not in providers:
            continue                      # 模組不在：這一類不列，`unavailable_sources()` 說明（不跟「沒有」混在一起）
        for doc_no in _case_doc_nos(conn, st, quote_no, user, providers, hidden):
            for meta in source_files(conn, st, doc_no, user) or ():
                out.append(_candidate(st, doc_no, meta, used_map))
    return _unused_first(out)


def _candidate(st, doc_no, meta, used_map):
    """一個可帶入的候選檔（`case_attachments()` 與 `line_source_files()` 共用同一份形狀）。"""
    name = (meta or {}).get("filename") or (meta or {}).get("name") or ""
    # ⚠️ 兩種「不能用」**不是同一件事**，訊息要分得出來：
    #    路徑不合法（abs_path 擋下）／檔案不在磁碟上。
    # ☠️ 一律說「檔案已遺失」的話，使用者會去找一個**從來沒有遺失**
    #    的檔 —— 那是一句通順而錯的話（同 `JV9` 那一族）。
    reason = ""
    try:
        exists = os.path.isfile(abs_path((meta or {}).get("path")))
        if not exists:
            reason = "檔案已遺失"
    except HTTPException:
        exists, reason = False, "附件路徑不合法"
    file_id = str((meta or {}).get("id") or "")
    used_by = used_map.get((st, doc_no, file_id)) or []
    return {
        "type": st,
        "docNo": doc_no,
        "fileId": file_id,
        "filename": name,
        "mime": (meta or {}).get("mime") or "",
        # 2026-09-25：傳票來源預覽視窗下方顯示「上傳日期」（沒有就空字串，畫面不顯示那一段）
        "uploadedAt": (meta or {}).get("uploadedAt") or "",
        "exists": exists,
        "reason": reason,
        "missing": describe_missing(meta),
        "used": bool(used_by),
        "usedAt": used_by[0]["usedAt"] if used_by else "",
        "usedBy": used_by,
    }


def _unused_first(out):
    unused = [x for x in out if not x["used"]]
    used = [x for x in out if x["used"]]
    used.sort(key=lambda x: x["usedAt"], reverse=True)
    return unused + used


#: `JV36`：分錄可以連帶的三種來源（A 裁示：預覽端點也只接受這三種）。
LINE_SOURCES = ("case", "extra_expense", "contractor_dispatch")


def line_source_files(conn, source_type, source_key, user, hidden=None):
    """`JV36`：某一行摘要的來源 XXX「本身的已上傳檔案」。

    🔴 範圍**逐字等於** `resolve_picks()` 帶得進來的範圍（A 裁示：不可以更寬）——
       每一筆的 `type` 都在 `SOURCE_TYPES` 內，`docNo` 就是 `source_files()` 的鍵：
    ```
    case                 case_attachments(quote_no)（頁籤區「已上傳檔案」同一份）
    extra_expense        source_files('extra_expense', id)
    contractor_dispatch  source_files('contractor_dispatch', id) ＋ ('contractor_invoice', id)
    ```
    """
    if source_type not in LINE_SOURCES:
        raise HTTPException(400, "不支援的摘要來源「%s」。" % source_type)
    key = str(source_key or "").strip()
    if not key:
        raise HTTPException(400, "缺少摘要來源的編號。")
    if source_type == "case":
        return case_attachments(conn, key, user, hidden)
    pairs = ([("extra_expense", key)] if source_type == "extra_expense"
             else [("contractor_dispatch", key), ("contractor_invoice", key)])
    used_map = _used_map(conn)
    return _unused_first([_candidate(st, doc_no, meta, used_map)
                          for st, doc_no in pairs
                          for meta in (source_files(conn, st, doc_no, user) or ())])
