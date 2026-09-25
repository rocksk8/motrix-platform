# 模組串接點登記（INTEGRATION-POINTS）

> 每一個跨組串接點都登記在這裡。L2 模組之間不可以直接 `import` 對方的程式（CORE-SPEC §2）；
> 需要對方的能力時，由擁有方公開一個串接點，使用方只依賴這裡寫下的契約。
> 判斷準則：**對方不在時，使用方要能少一項資訊，而不是壞掉。**

每一筆都要寫明六件事：

| 欄位 | 意思 |
|---|---|
| 形式 | provider（`core.registry`）／事件／HTTP… |
| 語法 | 提供方怎麼登記、使用方怎麼取用（可以直接複製的那一行） |
| 回傳 | 形狀與使用方實際讀的欄位 |
| 對方不在時 | 使用方的退化行為（必須可用，只少資訊） |
| 契約版本 | 目前版本；欄位只准加，改名／刪除要升版 |
| 守門 | 哪一題測試會在契約被破壞時變紅 |

---

## IP-1　`dispatch.row`：派工單列序列化（M04 → M01、M06）

對應 DEPENDENCY-MAP §3 #7、#8、#9（ROADMAP A6）。原本 `helpers/recognition.py`（M01）、
`routers/vouchers.py`（M06）直接 import `routers.vendor_contractors._dispatch_row`（M04 私有函式）；
`routers/reports.py`（M08）import 了但沒有呼叫，已刪除。

| 欄位 | 內容 |
|---|---|
| 提供方 | M04 外包工班：`routers/vendor_contractors.py::_dispatch_row` |
| 使用方 | M01 `helpers/recognition.py::dispatch_entries`（應計派工成本，營運報表支出用）；M06 `routers/vouchers.py::_case_expense_sources`（傳票摘要來源的承攬商派工） |
| 形式 | provider，單一提供者（`core.registry`）。M04 尚未搬進 `modules/`，暫以 `registry.provide()` 在匯入時登記；搬遷後改寫進 `ModuleSpec.providers`，這一行刪除 |
| 語法 | 提供：`_registry.provide("dispatch.row", "subcontract", _dispatch_row)`<br>取用：`fn = registry.single_provider("dispatch.row")`；`None` ⇒ 退化。兩個以上提供者 ⇒ `RuntimeError`（兩份實作在搶，不隨便挑） |
| 回傳 | `fn(row: sqlite3.Row) -> dict`。`row` 是 `contractor_dispatches` 一列（可 JOIN `vendor_contractors.name AS vendor_name`）。使用方讀的欄位：`id`、`quoteNo`、`vendorName`、`scope`、`items`、`personnel`、`totalAmount`、`personnelTotal`、`grandTotal`（含稅承攬商費用＋外包人員）、`invoiceNo`、`acceptedAt` |
| 對方不在時 | recognition：應計派工回 `[]` 並記 WARNING ⇒ 營運報表少了承攬商這一類支出，其餘照常。現金口徑讀匯款申請快照，不受影響。<br>vouchers：案件支出來源只剩額外支出，不列承攬商派工。<br>皆不丟例外 |
| 契約版本 | 1（2026-09-25） |
| 守門 | `backend/tests/platform/test_dispatch_connector.py`：①提供者存在且回傳含全部使用欄位 ②registry 重複／多提供者規則 ③**反向控制**：同一批資料先確認派工那一類非空，拿掉提供者後三處照常回結果、只少派工 ④全 backend 不再有人 `import _dispatch_row`。突變驗證：拿掉退化判斷、拿掉 M04 登記、vouchers 不看提供者，三者皆轉紅 |

**尚未處理（不在 A6 範圍）**：`routers/reports.py::_live_dispatch_totals_by_quote` 自己又算了一次
grandTotal（直接讀 `contractor_dispatches`，沒有經過 `_dispatch_row`）。這是同一算法的第二份實作，
也是 M08 直接讀 M04 的表；應改用 IP-1，另開題。
