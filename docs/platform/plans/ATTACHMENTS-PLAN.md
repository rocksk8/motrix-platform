# `attachments.for_document` 步驟表（A，2026-09-26 草稿；開工基底＝第八班合回後的 origin/platform，分支 `wip/a-attachments`）

> 依據：主持裁示 M06-b（RUN-PLAN §5 D1 段）：傳票附件的來源讀取改由各單據擁有模組提供，獨立一包、排在 M01 前置；M06 搬遷時先保留直讀並登記例外、附到期守門（M06-PLAN §5）。
> 量測：`helpers/voucher_attachments.py`（M06，514 行）於 origin/platform 3e017154。

## 0. 現況：傳票帶入附件（`JV3`／`JV18`／`JV36`）直讀九類來源

| 來源類型（`SOURCE_TYPES`） | 表.欄位 | 擁有模組 | `doc_no` 的形狀 |
|---|---|---|---|
| `quotation_signed` | `quotations.signed_files_json` | M01 case | 案件編號 |
| `case_update` | `case_updates.files_json`（一個案件多列，併起來） | M01 | 案件編號 |
| `payment_item` | `quotations.data_json` → `caseRecord.payment.items[i].invoiceFiles` | M01 | `案件編號_i` |
| `material` | `quotations.data_json` → `caseRecord.materials[i].files` | M01 | `案件編號_i` |
| `material_invoice` | 同上 `.invoiceFiles` | M01 | `案件編號_i` |
| `extra_expense` | `case_extra_expenses.files_json` | M01 | id |
| `invoice_voucher` | `invoice_vouchers.issued_files_json` | M05 arap | 開票單號 |
| `contractor_dispatch` | `contractor_dispatches.files_json` | M04 subcontract | 派工單 id |
| `contractor_invoice` | `contractor_dispatches.invoice_files_json` | M04 | 派工單 id（與上一類同鍵，清單鍵是 `(type, docNo)`） |

- 明著排除（不是會計憑證）：`completion_note`、`shipping_note`（M03）、`dev_log`（M02）、`pending_case_change`（待核准暫存）——**維持在 M06**，這是 M06 的政策，不是擁有者的事
- 自訂模組（custom，P8）：欄位型別沒有「檔案」（`helpers/custom_fields.TYPES`）⇒ 目前沒有附件來源；日後加檔案欄位時，由自訂模組登記同一個提供者
- 另外兩類讀取**不在本包**：`_used_map`／`expense_line_uses` 讀的是 M06 自己的 `voucher_attachments`／`voucher_lines`／`vouchers_all`

## 1. 提供者介面（capability `attachments.for_document`，多提供者、以模組 key 區分）

```python
class _Attachments:                       # 每個擁有模組一個
    SOURCE_TYPES = ("invoice_voucher",)   # 這個模組擁有的來源類型（不可與別的提供者重疊）
    LABEL = "應收應付"                     # 不在時的說明用

    @staticmethod
    def doc_nos_for_case(conn, source_type, quote_no) -> list[str]: ...
    @staticmethod
    def files(conn, source_type, doc_no) -> list[dict]:
        """檔案 metadata（save_document_files 的形狀）。單據不存在 ⇒ []；JSON 壞掉 ⇒ raise AttachmentsUnreadable（不吞成 []）"""
```

- 在**呼叫端的連線**上讀、唯讀；檔案實體位置不變（`helpers.uploads`，L1），複製進傳票仍由 M06 做（JV3「帶入＝複製」不變）
- `AttachmentsUnreadable` 放 L1（`helpers/uploads.py` 旁，純例外），M06 轉成 400「來源資料格式不正確」，文字照舊
- M06 端：`source_files()`／`_case_doc_nos()` 改成查「哪一個提供者擁有這個 type」再呼叫；白名單 `SOURCE_TYPES` 與排除清單留在 M06；import 時的 assert（三份對照表聯集＝白名單）改成守門題：**提供者宣告的 type 聯集 ⊆ 白名單、且兩兩不重疊**

| 提供者 | 放在哪 | 宣告方式 |
|---|---|---|
| M01 case（6 類） | `helpers/case_attachments.py`（M01 helper；M01 搬遷時隨模組走） | M01 尚未搬 ⇒ `registry.provide()`；M01 搬遷時改 `ModuleSpec.providers`（C 的 M01-PLAN 加一列） |
| M04 subcontract（2 類） | `modules/subcontract/attachments.py` | `ModuleSpec.providers`（改到 C 的模組 ⇒ 先在 RUN-PLAN §6 講） |
| M05 arap（1 類） | M05 已合回 ⇒ `modules/arap/attachments.py`；未合回 ⇒ `routers/invoice_vouchers.py` 旁先以 `registry.provide()` 登記 | 同上 |

## 2. 模組不在時（明說，不靜默略過）

| 情境 | 行為 |
|---|---|
| 列候選（`case_attachments`、`line_source_files`） | 只列在場提供者的類型；回應加 `notice`：「外包工班模組未安裝：派工單與承攬商發票的附件沒有列出」（每個缺席提供者一句，以「；」並列）；傳票頁附件選取區顯示 |
| 帶入（`resolve_picks`）選到缺席模組的類型 | 400「外包工班模組未安裝，無法帶入派工單附件」——**整批擋**（同現行「檔案不存在整批擋」） |
| 已帶入的附件 | 不受影響（已複製進傳票）；作廢重開的複製走傳票自己的附件，不經提供者 |
| 摘要來源預覽（`JV36`，`contractor_dispatch`） | M04 不在 ⇒ 400「外包工班模組未安裝」（不是「不支援的摘要來源」） |

## 3. voucher_attachments 直讀改走提供者（逐處）

| # | 位置 | 現在 | 改成 |
|---|---|---|---|
| 1 | `source_files()` quotation_signed／case_update／payment_item／material／material_invoice | 直讀 quotations、case_updates | M01 提供者 `files()` |
| 2 | `source_files()` extra_expense | 直讀 case_extra_expenses | M01 |
| 3 | `source_files()` invoice_voucher | 直讀 invoice_vouchers | M05 |
| 4 | `source_files()` contractor_dispatch／contractor_invoice | 直讀 contractor_dispatches | M04 |
| 5 | `_case_record()` | 直讀 quotations.data_json | 移進 M01 提供者（M06 不再需要） |
| 6 | `_case_doc_nos()` + `_CASE_DOC_NO_SQL`／`_IS_QUOTE`／`_INDEXED` | 三份對照表直讀四張表 | 各提供者 `doc_nos_for_case()`；三份表隨之刪除 |
| 7 | `line_source_files()` 的 `LINE_SOURCES` 對應 | 硬寫 type | 不變（仍是 M06 的政策），缺席時見 §2 |

改完之後 `helpers/voucher_attachments.py` 對別組表的 SQL＝0（守門驗）。

## 4. 到期守門與其他守門

- M06-PLAN §5 的 `KNOWN_ACCOUNTING_FOREIGN_READS` 裡 `voucher_attachments.py` 那一列：**本包合回後就是 0 筆** ⇒ 那一列在 M06 搬遷時不需要登記；若 M06 先搬、本包後到，那一列由 `test_accounting_foreign_reads_expire_when_the_provider_exists` 在本包合回那一班轉紅，提醒刪除
- 新守門（`backend/tests/platform/test_attachments_providers.py`）：
  - `test_voucher_attachments_reads_no_foreign_tables`：`dep_scan.sql_tables` 掃 voucher_attachments，只准讀 M06 自己的表（正對照：合成檔讀 `contractor_dispatches` ⇒ 紅）
  - `test_providers_cover_the_whitelist_without_overlap`：在場提供者 type 聯集 ⊆ `SOURCE_TYPES`、兩兩不重疊；全部模組在 ⇒ 聯集＝白名單（缺一類 ⇒ 紅，取代原本 import 時的 assert）
  - `test_absent_provider_says_so`（合成：拿掉一個提供者 ⇒ 候選清單少那幾類、`notice` 有那一句、帶入 400）
- 既有 JV3／JV18／JV36 的題：需要 M04／M05 在的那幾題，依 §B-11 搬進各模組或依 `module_installed` 略過

## 5. 步驟（依序）

1. 第八班合回後 `git worktree add ..\MOTRIX-PLATFORM-A14 -b wip/a-attachments origin/platform`；重量 §0（有變先更新本表）；RUN-PLAN §6 記一筆「會改 subcontract、arap（加提供者檔＋ModuleSpec 一列）」
2. L1：`AttachmentsUnreadable`；INTEGRATION-POINTS 新節（暫定號，列車定號）
3. 三個提供者（M01、M04、M05），各自單元題（正對照＋壞 JSON 丟例外＋單據不存在回 []）
4. M06 `voucher_attachments` 改走提供者（§3），刪三份對照表；§2 的 notice／400
5. 前端：傳票頁附件選取區顯示 `notice`（e2e：拿掉 M04 提供者 ⇒ 看得到那一句）
6. 守門（§4）＋突變：提供者重疊、缺席不說、缺席照帶、壞 JSON 吞成 []、M06 殘留直讀
7. 驗證：差異題＋tests/platform＋傳票頁 e2e（e2e -n 2）；§B-11：分別拿掉 subcontract、arap 各一輪（`--continue-on-collection-errors`）
8. 推送、月台登記（動到 C 的兩個模組、M01 helper，列在月台列）

## 6. 風險／要先問的

- M01 提供者放在 `helpers/case_attachments.py`（M01 helper）而不是 L1：M01 搬遷時隨模組走；需要 C 的 M01-PLAN 加一列（改 ModuleSpec 宣告）
- `payment_item`／`material*` 讀的是 `quotations.data_json` 內部結構——提供者化之後這個結構只有 M01 知道，是本包的主要價值；但 C 的 M01 前置若同時改 caseRecord 形狀，要先對齊（開工時看 c-m01-* 的改動）
- 預估：約 4～5 小時（三個提供者＋M06 改寫＋守門＋兩輪反向控制）；開工時回報死線

## 7. 待辦（本包順帶）

- [x] ~~C 的 `docs/platform/deprecations.json`（c-m05b）合回後，登記 `helpers.voucher` 的兩個淘汰別名，`remove_at_major`＝2（主持 2026-09-26）：
  - `helpers.voucher.parse_approval_json` ⇒ 改用 `helpers.tiered_approval.parse_approval_json`
  - `helpers.voucher.VoucherChainUnreadable` ⇒ 改用 `helpers.tiered_approval.ApprovalChainUnreadable`（別名名稱是 VoucherChainUnreadable，L1 本名是 ApprovalChainUnreadable）~~
  〔更正（主持 2026-09-26）：改由 C 的 c-m05b-2（第十班）一併登記，本包不做〕
