# -*- coding: utf-8 -*-
"""M01 案件的附件來源（`attachments.for_document` 提供者；主持裁示 M06-b，2026-09-26）。

案件底下六類已上傳檔案的位置只有 M01 知道（其中三類在 `quotations.data_json` 的 caseRecord 陣列裡）：

| 來源類型 | 位置 | `doc_no` |
|---|---|---|
| quotation_signed | `quotations.signed_files_json` | 案件編號 |
| case_update | `case_updates.files_json`（一個案件多列，併起來） | 案件編號 |
| payment_item | caseRecord.payment.items[i].invoiceFiles | `案件編號_i` |
| material | caseRecord.materials[i].files | `案件編號_i` |
| material_invoice | caseRecord.materials[i].invoiceFiles | `案件編號_i` |
| extra_expense | `case_extra_expenses.files_json` | id |

~~M01 尚未搬進 modules/ ⇒ 以 `registry.provide()` 在匯入時登記~~〔更正（M01-PLAN §3-8 ③）：M01 已搬進 modules/case，改由 ModuleSpec.providers 宣告〕；
M01 搬遷時改寫進 `ModuleSpec.providers`（M01-PLAN，同 CA-O3）。

權限（稽核 D AT-M1，主持裁示 (b)）：每一類都先確認使用者看得到那張案件（`case_documents_readable`），
看不到 ⇒ raise `AttachmentNotVisible`（取用方：列清單時不列、帶入／預覽 403）。
"""
import json
from urllib.parse import quote

from helpers.case_access import case_documents_readable, case_owner_readable, case_page_readable
from helpers.uploads import AttachmentNotVisible, AttachmentSourceError, files_from_json_column


def _quote_and_index(doc_no):
    """`{quote_no}_{idx}` 拆成 `(quote_no, idx)`。拆不出來回 `(doc_no, None)`。
    ⚠️ 從**右邊**切：報價單號本身含 `-` 不含 `_`，而索引一定在最後一段。"""
    base, sep, tail = (doc_no or "").rpartition("_")
    if sep and tail.isdigit():
        return base, int(tail)
    return doc_no, None


def _case_record(conn, quote_no):
    row = conn.execute("SELECT data_json FROM quotations WHERE quote_no = ?", (quote_no,)).fetchone()
    if row is None:
        return {}
    try:
        return (json.loads(row["data_json"] or "{}") or {}).get("caseRecord") or {}
    except (TypeError, ValueError):
        raise AttachmentSourceError("案件「%s」的資料格式不正確，無法帶入。" % quote_no)


#: `doc_no` 是 `{案件編號}_{索引}` 的那幾類（項目在 caseRecord 的陣列裡）：(外層鍵, 陣列鍵, 檔案鍵)
_INDEXED = {
    "payment_item": ("payment", "items", "invoiceFiles"),
    "material": (None, "materials", "files"),
    "material_invoice": (None, "materials", "invoiceFiles"),
}


def _items(cr, outer, key):
    return ((cr.get(outer) or {}).get(key) if outer else cr.get(key)) or []


def _quote_of(conn, source_type, doc_no):
    """這一筆來源屬於哪一張案件；來源不存在 ⇒ None。"""
    if source_type in ("quotation_signed", "case_update"):
        return doc_no
    if source_type in _INDEXED:
        return _quote_and_index(doc_no)[0]
    if source_type == "extra_expense":
        row = conn.execute("SELECT quote_no FROM case_extra_expenses WHERE id = ?", (doc_no,)).fetchone()
        return row["quote_no"] if row else None
    raise AttachmentSourceError("不支援的附件來源「%s」。" % source_type)


#: 每一類用**原單據自己的讀取規則**（稽核 D AT-M1b：附件的可見範圍不可以比原單據寬）
#:   extra_expense ⇒ 額外支出各端點的 `_guard_case` ＝ `case_owner_readable`（不放行 case_manage）
#:   存在報價單上的四類 ⇒ 案件頁 `get_quotation` 的 `case_page_readable`（scope="read"：放行 cashier、不放行 case_manage；AT-M1c）
#:   case_update   ⇒ 案件動態端點的 `guard_case_access(allow_module="case_manage")` ＝ `case_documents_readable`
_READ_RULE = {"extra_expense": case_owner_readable,
              "quotation_signed": case_page_readable, "payment_item": case_page_readable,
              "material": case_page_readable, "material_invoice": case_page_readable}


def _typed_expense_masked(conn, doc_no, user) -> bool:
    """費用單據（kind≠''）的金額遮蔽（使用者 2026-10-01：只有申請人、簽核人、出納／財務、管理員以上看得到金額）：
    案件的一般讀者讀不到它的附件（發票／收據影像與檔名就是金額）。舊版額外支出（kind=''）不受影響。
    開檔（`files`）、路徑存取（`_CasePathAccess`）、搜尋／計數（P3）三處共用這一支，避免「搜得到卻開不了」或反過來。"""
    try:
        eid = int(doc_no)
    except (TypeError, ValueError):
        return False
    row = conn.execute("SELECT * FROM case_extra_expenses WHERE id = ?", (eid,)).fetchone()
    if row is None or not (row["kind"] or ""):
        return False
    from modules.case.api import case_extra_expenses as _xe          # 延後載入：避免 import 循環
    return not _xe._amount_viewer(conn, row, user)


def _require_readable(conn, source_type, quote_no, user):
    if not _READ_RULE.get(source_type, case_documents_readable)(conn, quote_no, user):
        raise AttachmentNotVisible()


class _CaseAttachments:
    LABEL = "案件"
    SOURCE_TYPES = ("quotation_signed", "case_update", "payment_item", "material", "material_invoice",
                    "extra_expense")

    @staticmethod
    def doc_nos_for_case(conn, source_type, quote_no, user):
        docs = _CaseAttachments._docs(conn, source_type, quote_no)
        if not _READ_RULE.get(source_type, case_documents_readable)(conn, quote_no, user):
            # 看不到：只回「沒列出幾個附件」（數字），不帶單號與內容（主持裁示 2026-09-26）
            raise AttachmentNotVisible(hidden=sum(_count(conn, source_type, d) for d in docs))
        return docs

    @staticmethod
    def _docs(conn, source_type, quote_no):
        if source_type in ("quotation_signed", "case_update"):
            return [quote_no]
        if source_type in _INDEXED:
            outer, key, _ = _INDEXED[source_type]
            return ["%s_%d" % (quote_no, i) for i in range(len(_items(_case_record(conn, quote_no), outer, key)))]
        if source_type == "extra_expense":
            return [str(r["k"]) for r in conn.execute(
                "SELECT id AS k FROM case_extra_expenses WHERE quote_no = ? ORDER BY id", (quote_no,))]
        raise AttachmentSourceError("不支援的附件來源「%s」。" % source_type)

    @staticmethod
    def files(conn, source_type, doc_no, user):
        quote_no = _quote_of(conn, source_type, doc_no)
        if quote_no is None or conn.execute("SELECT 1 FROM quotations WHERE quote_no = ?", (quote_no,)).fetchone() is None:
            return []                                     # 來源不存在（契約：[]）
        _require_readable(conn, source_type, quote_no, user)
        if source_type == "extra_expense" and _typed_expense_masked(conn, doc_no, user):
            raise AttachmentNotVisible()                  # 費用單據的附件＝金額：非申請人／簽核人／出納財務／管理員看不到
        return _read(conn, source_type, doc_no)


def _count(conn, source_type, doc_no):
    """看不到的那一筆有幾個附件（只給 hidden 的數字用；壞資料算 1：至少有東西沒列出）。"""
    try:
        return len(_read(conn, source_type, doc_no) or [])
    except AttachmentSourceError:
        return 1


def _read(conn, source_type, doc_no):
    """讀一筆來源的附件 metadata（**不查權限**：只給已查過權限的 `files()` 與只算數字的 `_count()` 用）。"""
    if source_type == "quotation_signed":
        return files_from_json_column(conn, "quotations", "quote_no", doc_no, "signed_files_json")
    if source_type == "case_update":
        out = []
        for row in conn.execute("SELECT files_json FROM case_updates WHERE quote_no = ?", (doc_no,)):
            try:
                out += json.loads(row["files_json"] or "[]") or []
            except (TypeError, ValueError):
                raise AttachmentSourceError("案件動態的附件資料格式不正確，無法帶入。")
        return out
    if source_type in _INDEXED:
        quote_no, idx = _quote_and_index(doc_no)
        if idx is None:
            raise AttachmentSourceError("來源編號「%s」缺少項目索引（應為「案件編號_序號」）。" % doc_no)
        outer, key, fkey = _INDEXED[source_type]
        arr = _items(_case_record(conn, quote_no), outer, key)
        if idx < 0 or idx >= len(arr):
            return []
        return (arr[idx] or {}).get(fkey) or []
    if source_type == "extra_expense":
        return files_from_json_column(conn, "case_extra_expenses", "id", doc_no, "files_json")
    raise AttachmentSourceError("不支援的附件來源「%s」。" % source_type)


#: 額外支出的**舊版**附件資料夾（DB v75 之前：精算頁 `settlement.extraItems[]` 的附件，鍵＝`{案件編號}_{舊陣列索引}`）。
#: v75 只搬 metadata、沒搬檔案，所以正式機的額外支出列（`files_json`）至今仍指向這個資料夾。索引是當年的陣列位置、不是現在的列 id，
#: 所以**只綁案件**（鍵的案件編號＝那一列的 quote_no），不比索引；別的案件的路徑一律不收。
LEGACY_EXTRA_FOLDER = "quotation_settlement_extra"

def _lists_path(files_json, rel: str) -> bool:
    """這個額外支出的 `files_json` 有沒有**恰好**列了 `rel` 這個路徑（壞 JSON ⇒ 沒有）。"""
    try:
        files = json.loads(files_json or "[]")
    except (TypeError, ValueError):
        return False
    return any(isinstance(f, dict) and f.get("path") == rel for f in (files if isinstance(files, list) else []))


class _CasePathAccess:
    """`uploads.path_access`（IP-104，2026-09-30 P0）：M01 存的上傳檔 ⇒ 擁有單據 ⇒ 那張單據自己的讀取規則。

    | 資料夾 | 其餘各段 | 規則 |
    |---|---|---|
    | quotations／quotation_payment_items／quotation_materials／quotation_materials_invoices／case_updates／case_extra_expense | `單號/檔名` | 同 `_READ_RULE`（附件提供者；可見範圍＝原單據） |
    | quotation_settlement_extra（額外支出的舊版資料夾） | `案件編號_舊索引/檔名` | 只綁案件：該案某筆額外支出的 files_json 真的列了這個路徑 ∧ 額外支出的讀取規則 |
    | completion_notes | `完工單號/檔名` | 完工單清單 `guard_case_access(allow_module="case_manage")`＝`case_documents_readable` |
    | _pending_case_changes | `變更id/案件編號_序號/檔名` | 變更申請存在且屬於該案 ∧（申請人本人 ∨ 案件頁規則 `case_page_readable`） |
    """
    _FOLDER_SOURCE = {"quotations": "quotation_signed", "quotation_payment_items": "payment_item",
                      "quotation_materials": "material", "quotation_materials_invoices": "material_invoice",
                      "case_updates": "case_update", "case_extra_expense": "extra_expense",
                      LEGACY_EXTRA_FOLDER: "extra_expense_legacy"}
    FOLDERS = tuple(_FOLDER_SOURCE) + ("completion_notes", "_pending_case_changes")

    @staticmethod
    def readable(conn, folder, rest, user):
        if folder == "_pending_case_changes":
            if len(rest) != 3 or not rest[0].isdigit():
                return False
            quote_no, idx = _quote_and_index(rest[1])
            row = conn.execute("SELECT quote_no, requested_by FROM case_change_requests WHERE id = ?",
                               (int(rest[0]),)).fetchone()
            if idx is None or row is None or row["quote_no"] != quote_no:
                return False
            return (bool(row["requested_by"]) and row["requested_by"] == user.get("username")) \
                or case_page_readable(conn, quote_no, user)
        if len(rest) != 2:
            return False
        key = rest[0]
        if folder == "completion_notes":
            row = conn.execute("SELECT quote_no FROM completion_notes WHERE note_no = ?", (key,)).fetchone()
            return bool(row) and case_documents_readable(conn, row["quote_no"], user)
        st = _CasePathAccess._FOLDER_SOURCE.get(folder)
        if st in ("quotation_signed", "case_update"):
            quote_no = key
        elif st in _INDEXED:
            quote_no, idx = _quote_and_index(key)
            if idx is None:
                return False
        elif st == "extra_expense_legacy":                # 舊版 `{案件編號}_{舊索引}`：只綁案件——該案的某筆額外支出的 files_json 真的列了這個路徑
            quote_no, idx = _quote_and_index(key)
            if idx is None:
                return False
            rel = "%s/%s/%s" % (folder, key, rest[1])
            rows = conn.execute("SELECT files_json FROM case_extra_expenses WHERE quote_no = ?", (quote_no,)).fetchall()
            if not any(_lists_path(r["files_json"], rel) for r in rows):     # 逐筆解析、比對完整路徑（不是子字串：前綴同名的檔不算列出）
                return False
            st = "extra_expense"
        elif st == "extra_expense":                       # `{案件編號}_{額外支出 id}`：那一列要真的掛在該案
            quote_no, eid = _quote_and_index(key)
            if eid is None or conn.execute("SELECT 1 FROM case_extra_expenses WHERE id = ? AND quote_no = ?",
                                           (eid, quote_no)).fetchone() is None:
                return False
            if _typed_expense_masked(conn, eid, user):
                return False                              # 費用單據的附件＝金額（同 `_CaseAttachments.files`）
        else:
            return False
        return bool(_READ_RULE.get(st, case_documents_readable)(conn, quote_no, user))


#: 各類檔案存檔時的資料夾（`save_document_files` 第一個參數；路徑 `<資料夾>/<單據鍵>/<檔名>`）
_CATALOG_FOLDER = {"quotation_signed": "quotations", "case_update": "case_updates", "payment_item": "quotation_payment_items",
                   "material": "quotation_materials", "material_invoice": "quotation_materials_invoices",
                   "extra_expense": "case_extra_expense", "completion_note": "completion_notes"}


def _path_bound_to_doc(conn, source_type, doc_no, entry):
    """被提供的檔案路徑必須屬於這張單據自己的資料夾（W3：不信 JSON 欄裡的路徑）。
    報價單回簽、案件動態、完工單＝單號全等；收付款／材料／材料發票＝同一案件（索引可能因刪除項目而位移，只比案件）；
    額外支出＝`<案件>_<id>` 全等。"""
    from helpers.uploads import upload_path_key
    key = upload_path_key(entry, _CATALOG_FOLDER[source_type])
    if key is None and source_type == "extra_expense":
        legacy = upload_path_key(entry, LEGACY_EXTRA_FOLDER)          # 舊版資料夾：只綁案件
        if legacy is None:
            return False
        quote_no = _quote_of(conn, source_type, doc_no)
        base, idx = _quote_and_index(legacy)
        return quote_no is not None and idx is not None and base == quote_no
    if key is None:
        return False
    if source_type in ("quotation_signed", "case_update", "completion_note"):
        return key == str(doc_no)
    quote_no = _quote_of(conn, source_type, doc_no)
    if source_type == "extra_expense":
        return quote_no is not None and key == "%s_%s" % (quote_no, doc_no)
    return quote_no is not None and _quote_and_index(key)[0] == quote_no


class _CaseCatalog:
    """`attachments.catalog`（契約 v1，2026-09-30 P2）：M01 的文件類附件。權限＝擁有單據自己的讀取規則
    （同 `_CaseAttachments` 的 `_READ_RULE`／完工單清單規則 `case_documents_readable`），不另寫第二份。
    待核准暫存檔（`_pending_case_changes`、額外支出變更申請）不進目錄（設計 Q6：未核准的不是正式檔案）。"""
    CATEGORIES = {
        "quotation_signed": {"label": "報價單回簽", "doc": "報價單", "module": "案件"},
        "case_update": {"label": "案件動態附件", "doc": "案件動態", "module": "案件"},
        "payment_item": {"label": "收付款項目發票", "doc": "案件收付款", "module": "案件"},
        "material": {"label": "材料附件", "doc": "案件材料", "module": "案件"},
        "material_invoice": {"label": "材料發票", "doc": "案件材料", "module": "案件"},
        "extra_expense": {"label": "額外支出／請款附件", "doc": "額外支出", "module": "案件"},
        "completion_note": {"label": "完工單回簽", "doc": "完工單", "module": "案件"},
    }

    @staticmethod
    def open(conn, user, source_type, doc_no, file_id):
        from helpers.uploads import opened_upload_file, pick_file
        if source_type == "completion_note":
            row = conn.execute("SELECT quote_no, signed_files_json FROM completion_notes WHERE note_no = ?",
                               (doc_no,)).fetchone()
            if row is None:
                return None
            if not case_documents_readable(conn, row["quote_no"], user):
                raise AttachmentNotVisible()
            try:
                files = json.loads(row["signed_files_json"] or "[]") or []
            except (TypeError, ValueError):
                raise AttachmentSourceError("完工單「%s」的附件資料格式不正確。" % doc_no)
        else:
            files = _CaseAttachments.files(conn, source_type, doc_no, user)      # 看不到 ⇒ AttachmentNotVisible
        entry = pick_file(files, file_id)
        if entry is None or not _path_bound_to_doc(conn, source_type, doc_no, entry):
            return None                                          # 路徑不屬於這張單據 ⇒ 當作沒有這個檔
        return opened_upload_file(entry)

    # ── 搜尋（附件目錄 P3）：權限沿用上面 open() 同一批規則（doc_nos_for_case＝各類 _READ_RULE；完工單＝case_documents_readable）──
    _LIKE = "%\"path\"%"

    @staticmethod
    def _candidates(conn, crit):
        """有檔案的案件單號（SQL 只做「有沒有 path」的粗篩；篩檔名／日期等在 Python）。指定 quote_no ⇒ 只那一案。"""
        if crit["quote_no"]:
            return [crit["quote_no"]]
        like = _CaseCatalog._LIKE
        qs = set()
        for sql in ("SELECT quote_no FROM quotations WHERE signed_files_json LIKE ? OR data_json LIKE ?",
                    "SELECT DISTINCT quote_no FROM case_updates WHERE files_json LIKE ?",
                    "SELECT DISTINCT quote_no FROM case_extra_expenses WHERE files_json LIKE ?",
                    "SELECT DISTINCT quote_no FROM completion_notes WHERE signed_files_json LIKE ?"):
            n = sql.count("?")
            qs.update(r[0] for r in conn.execute(sql, (like,) * n).fetchall() if r[0])
        return sorted(qs)

    @staticmethod
    def _collect(conn, user, crit):
        from helpers import attachment_search as S
        cands = _CaseCatalog._candidates(conn, crit)
        names = S.case_names(conn, cands)
        items = []
        for qn in cands:
            cust, proj = names.get(qn, ("", ""))
            if crit["customer"] and crit["customer"].lower() not in cust.lower():
                continue
            link = "case-management.html?q=" + quote(qn, safe="")
            for st, meta in _CaseCatalog.CATEGORIES.items():
                if st == "completion_note":
                    if not case_documents_readable(conn, qn, user):
                        continue
                    for row in conn.execute("SELECT note_no, signed_files_json FROM completion_notes WHERE quote_no = ?", (qn,)).fetchall():
                        try:
                            files = json.loads(row["signed_files_json"] or "[]") or []
                        except (TypeError, ValueError):
                            continue
                        for f in files:
                            if not _path_bound_to_doc(conn, st, row["note_no"], f):
                                continue                   # 與 open() 同一道：路徑綁單據
                            items.append(S.make_item(st, row["note_no"], "%s %s" % (meta["doc"], row["note_no"]), f,
                                                     quote_no=qn, customer=cust, project=proj, link=link))
                    continue
                try:
                    docs = _CaseAttachments.doc_nos_for_case(conn, st, qn, user)
                except AttachmentNotVisible:
                    continue                                   # 看不到的不列、也不回個數（設計 §8 Q3）
                except AttachmentSourceError:
                    continue                                   # 壞資料：搜尋略過（開檔端點會說出原因）
                for d in docs:
                    if st == "extra_expense" and _typed_expense_masked(conn, d, user):
                        continue                           # 與 open() 同一道：費用單據的附件對遮蔽金額的人不列、不計數
                    try:
                        files = _read(conn, st, d)
                    except AttachmentSourceError:
                        continue
                    for f in files or []:
                        if not _path_bound_to_doc(conn, st, d, f):
                            continue                       # 與 open() 同一道：路徑綁單據
                        items.append(S.make_item(st, d, "%s %s" % (meta["doc"], d), f, quote_no=qn, customer=cust, project=proj, link=link))
        return items

    @staticmethod
    def search(conn, user, crit):
        from helpers import attachment_search as S
        c = S.normalize_crit(crit)
        return S.finish(_CaseCatalog._collect(conn, user, c), c)

    @staticmethod
    def count(conn, user, crit):
        from helpers import attachment_search as S
        c = S.normalize_crit(crit)
        return S.count_by_type(_CaseCatalog._collect(conn, user, c), c)


from core import registry as _registry  # noqa: E402
