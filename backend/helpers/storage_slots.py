# -*- coding: utf-8 -*-
"""儲存／上傳「位置代號」登錄表與插槽政策（BP-4 S1；設計 docs/platform/plans/BP4-STORAGE-NOTIFY-DESIGN.md §3）。

[單位] helper:storage_slots    [層] L1    [穩定度] 契約
[公開介面] DANGEROUS_EXTS, DOC_CODES, HARD_EXTS, LEGACY_READONLY, LOCATION_CODES, Location, SLOT_EXTS, STAGING_PREFIX, SlotPolicy,
    builtin_policy, enabled, policy, resolve_code
[不變式] ①旗標 `builder_slots.enabled`（設定中心，預設 0）關閉時，`policy()` 只回**內建政策**＝由 `helpers.uploads` 今天的常數導出；
    `save_document_files(policy=None)` 的行為與路徑與先前逐位元相同（守門：tests/test_storage_slots_parity_2026_10_14.py）。
    ②位置代號由程式登錄，管理者不能新增；副檔名只能落在 `HARD_EXTS` 之內（硬底線，插槽只能縮小）。
    ③讀取授權不在這裡：每個代號對應的 `uploads.path_access` 提供者仍是唯一的讀取關卡（沒有提供者＝讀不到）。
[契約題] backend/tests/test_storage_slots_parity_2026_10_14.py
[注意] S1 只有內建政策與唯讀登錄；管理者宣告的插槽（`attachment_slot` 定義）在 S2 加入。
"""
from dataclasses import dataclass, field

from helpers import uploads as _up

#: 硬底線：任何插槽都不可能收這個集合以外的副檔名（= 今天各資料夾放行範圍的聯集；不含 html／svg／js／exe／壓縮檔…）。
HARD_EXTS = frozenset({".jpg", ".jpeg", ".png", ".pdf", ".heic", ".heif", ".docx", ".xlsx", ".doc", ".xls"})
#: 檔名中段出現這些副檔名（例：`a.exe.pdf`）一律拒絕（雙副檔名）。只套用在帶政策的上傳（`policy is not None`）。
DANGEROUS_EXTS = frozenset({".exe", ".bat", ".cmd", ".com", ".scr", ".js", ".vbs", ".ps1", ".py", ".php", ".aspx", ".dll", ".lnk", ".html", ".htm", ".svg",
                            ".docm", ".xlsm", ".jar", ".msi", ".hta", ".wsf", ".sh", ".reg"})
#: 管理者宣告的插槽**可以選**的副檔名（v1）＝硬底線去掉舊版 OLE 格式（.doc／.xls，可帶巨集）與 iPhone 原檔（.heic／.heif）。
#: 內建政策（例：傳票附件仍收 doc／xls、額外支出仍收 heic／heif）不受影響；要讓插槽也能選，得明確標示為放寬（目前決定不開放）。
SLOT_EXTS = HARD_EXTS - frozenset({".doc", ".xls", ".heic", ".heif"})


@dataclass(frozen=True)
class Location:
    """登錄表的一列。`managed`＝走 `save_document_files`（可由插槽管理）；False＝自有存檔邏輯，只列出、不管理。"""
    code: str
    label: str
    owner: str                    # 擁有模組（讀取授權的提供者所在；空字串＝沒有提供者的專屬端點）
    managed: bool = True
    note: str = ""


def _L(code, label, owner, managed=True, note=""):
    return code, Location(code, label, owner, managed, note)


#: 位置代號 ⇒ 登錄。key＝今天寫在各端點的 `subfolder` 字串（盤點 §1.2）。程式登錄，UI 不可新增。
LOCATION_CODES = dict([
    _L("quotations", "報價單回簽", "case"),
    _L("quotation_payment_items", "收款項目發票", "case"),
    _L("quotation_materials", "材料附件", "case"),
    _L("quotation_materials_invoices", "材料發票", "case"),
    _L("case_updates", "案件動態附件", "case"),
    _L("case_extra_expense", "額外支出", "case"),
    _L("completion_notes", "完工單簽回", "case"),
    _L("shipping_notes", "出貨單簽回", "supply"),
    _L("invoice_vouchers", "開票申請憑據", "arap"),
    _L("contractor_dispatches", "承攬商派工附件", "subcontract"),
    _L("contractor_dispatch_invoices", "承攬商派工發票", "subcontract"),
    _L("dev_logs", "業務開發記錄", "crm"),
    _L("custom_records", "自訂模組檔案欄", "core"),
    _L("voucher_attachments", "傳票附件", "", note="傳票附件有自己的讀取端點（沒有 path_access 提供者）"),
    # 不經 save_document_files、自有存檔邏輯：只列出，不受插槽管理（設計 §3.5）
    _L("projects", "工作日誌／專案照片", "core", managed=False, note="GPS／浮水印處理，自有端點"),
    _L("payslips", "勞報單簽回檔", "payroll", managed=False, note="自有存檔與歸檔路徑"),
    _L("branding", "品牌圖檔", "", managed=False, note="僅超級管理員、自有大小與格式上限"),
])

#: 待核准變更的暫存前綴（`_pending_case_changes/{id}`）：實體資料夾是前綴，政策取自它最後要併入的目標代號。
STAGING_PREFIX = "_pending_case_changes"
#: 只讀的舊資料夾（額外支出舊版附件）：不再寫入，仍可讀。
LEGACY_READONLY = ("quotation_settlement_extra",)

#: 單據類型 ⇒ 位置代號（引擎登錄，**不接受使用者輸入**）
DOC_CODES = {
    "quotation": "quotations", "completion_note": "completion_notes", "shipping_note": "shipping_notes",
    "invoice_voucher": "invoice_vouchers", "contractor_dispatch": "contractor_dispatches",
    "case_update": "case_updates", "case_extra_expense": "case_extra_expense", "dev_log": "dev_logs",
    "custom_record": "custom_records", "voucher": "voucher_attachments",
}


@dataclass(frozen=True)
class SlotPolicy:
    """解析後的不可變政策。`subfolder`／`slot` 只有管理者宣告的插槽才有（S2）；內建政策兩者皆空。

    ⚠ 帶政策的上傳（`save_document_files(policy=...)`）會**開啟雙副檔名拒絕**（`a.exe.pdf`），`policy=None` 沒有——所以內建「簽回單」改用政策
    上傳時比今天略嚴；同一性測試（tests/test_storage_slots_parity_2026_10_14.py）只涵蓋 `policy=None` 與內建政策在一般檔名下相同。"""
    code: str
    folder: str
    accept: frozenset
    max_files: int = 0              # 每張單據累計上限；0＝不另限（只受單檔上限）
    max_request_bytes: int = 0      # 一次請求合計；0＝不另限
    max_file_bytes: int = 0         # 單檔上限（位元組）；0＝只受平台上限（設定中心 uploads.max_file_mb）
    subfolder: str = ""
    slot: str = ""
    builtin: bool = True
    notes: tuple = field(default_factory=tuple)


def enabled(conn=None) -> bool:
    """旗標 `builder_slots.enabled` **且** `builder_governance.enabled` 都開才算開（沒有治理層＝放寬沒有核准、發布沒有預覽把關，所以不開）；
    任一個讀不到一律當關（與其他建構器旗標同一規則）。"""
    try:
        from helpers import settings_groups, settings_registry as R      # noqa: F401
        return int(R.get("builder_slots", "enabled", conn=conn)) == 1 and int(R.get("builder_governance", "enabled", conn=conn)) == 1
    except Exception:                                               # noqa: BLE001
        return False


def resolve_code(subfolder: str) -> str:
    """實際寫入的子資料夾字串 ⇒ 位置代號（待核准暫存前綴 ⇒ 前綴本身）。不認得 ⇒ ''。"""
    s = str(subfolder or "")
    head = s.split("/", 1)[0]
    if head == STAGING_PREFIX:
        return STAGING_PREFIX
    return head if head in LOCATION_CODES or head in LEGACY_READONLY else ""


def builtin_policy(code: str) -> SlotPolicy:
    """今天的行為：副檔名＝`_ALLOWED_EXTS ∪ _EXTRA_EXTS_BY_SUBFOLDER[code]`，上限＝`limits_for(code)`。**即時**讀 uploads 的常數
    （測試覆寫縫隙照舊有效）；不認得的代號也回同一套規則（與 `save_document_files` 對任意 subfolder 字串的行為一致）。"""
    lim = _up.limits_for(code)
    accept = frozenset(_up._ALLOWED_EXTS | _up._EXTRA_EXTS_BY_SUBFOLDER.get(code, set()))     # noqa: SLF001
    return SlotPolicy(code=code, folder=code, accept=accept,
                      max_files=int(lim.get("max_files") or 0), max_request_bytes=int(lim.get("max_request_bytes") or 0))


def policy(doc_type: str, slot_key: str = "", conn=None) -> SlotPolicy:
    """單據類型（＋插槽鍵）⇒ 政策。旗標關閉或內建鍵 ⇒ 內建政策；單據類型不認得 ⇒ KeyError（不猜）。
    旗標開啟且給了管理者宣告的插槽鍵 ⇒ 已發布定義的政策（找不到 ⇒ LookupError）。**不檢查上傳者權限**——要檢查請用
    `helpers.attachment_slots.slot_policy(conn, doc_type, slot_key, user)`。"""
    code = DOC_CODES[doc_type]
    if slot_key in ("", "signed") or not enabled(conn):
        if slot_key not in ("", "signed"):
            raise LookupError("附件種類未開放：%s" % slot_key)
        return builtin_policy(code)
    from helpers import attachment_slots as AS
    s = next((x for x in AS.published_slots(conn, doc_type) if x.get("key") == slot_key), None)
    if s is None or s.get("disabled"):
        raise LookupError("沒有這個附件種類：%s" % slot_key)
    return AS._policy_of(doc_type, s)                                  # noqa: SLF001
