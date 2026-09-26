# 稽核：C 的 M01-PLAN §3-7——approval.queue_items／approval.reassign／approval.detail（wip/c-approval-2 49dcb781；合回前）（D 稽核，2026-09-26 18:12）

> 完整稽核：權限、個資、模組搬遷前置。稽核者 D 沒有寫過任何受稽核的程式碼。
> 對象：`a56f33e4..49dcb781`，3 commits；299aed61 到 49dcb781 是快轉。內容：
> - 待簽清單、角標、轉簽、詳情四件事，改由各單據模組提供：M04 承攬商匯款、M05 開票與請款、M03 出貨單、傳票、獎金、自訂模組、完工單。
> - M01 只做彙整、每案權限、案件抬頭、金額遮蔽。
> - 共用形狀下沉 L1 `helpers/approval_queue.py`；CORE 1.39。

## 0. 結論

- **必修 2、觀察 1**。
- 轉簽權限沒有放寬；detail 的每案權限與金額遮蔽，規則與舊版一致；突變 6/7 紅。

## 1. 實測

| 項目 | 結果 |
|---|---|
| 基準：tests/platform＋簽核相關 31 檔（`-n 4`） | 1525 過、1 紅（sidebar，已知） |
| 基準：簽核相關 e2e 8 檔（`-n 2`） | 30 過 |
| 轉簽權限（主持重點①） | 新舊都是 `_require_user(..., require_superadmin=True)`；可轉簽的 7 類與舊的 `_REASSIGN_TABLES` 相同。突變 AP1「不限 superadmin」⇒ 紅 |
| 模組不在（主持重點②） | 轉簽：沒有提供者 ⇒ 400「此類型不支援轉簽（或該單據的模組未安裝）」；清單：該類不列，`reassignTypes` 不含它。§B-11 結果見 AP-M1 |
| 角標與清單一致（主持重點③） | `/count` 與清單用同一個 `_queue_provider_items(conn)`。突變 AP5「角標不算提供者項目」⇒ 紅（5 題） |
| 出貨單改成提供者（主持重點④） | `routers/shipping_notes.py` 提供 queue_items、detail、reassign（`DataJsonApproval("shipping_notes", "note_no")`） |
| detail 的每案權限 | 各提供者回傳的 `approvalRaw` 來源與舊分支相同（contractor／invoice／payment 用 data_json，shipping 用 data_json），`_guard_queue_detail` 在回傳之前執行。突變 AP6「provider 類型不做每案權限」⇒ 紅 |
| 金額遮蔽 | 突變 AP3「金額一律可見」⇒ 紅 |
| data:image 過濾 | 突變 AP4「存簿不限 data:image」⇒ 紅 |
| 轉簽遇到讀不出來的簽核鏈 | 突變 AP7「吞成空鏈」⇒ 紅 |
| §B-11：D2 刪 `modules/arap`；tests/platform＋簽核與 arap 相關的 76 檔 | 非 e2e：1798 過、30 skip、**6 紅＝允許 5＋1 ⇒ AP-M1**；e2e：37 過、4 skip；不帶旗標的 `--collect-only`：1875 題、無收集錯誤 |

## 2. 發現

### 必修

**AP-M1　`test_every_approval_doc_type_is_in_both_queue_endpoints` 在 M05 不在時紅（本包造成，違反 §C-6）**
- 錯誤訊息：佇列與角標都「找不到 `['invoice_voucher', 'payment_request']`」。
- 原因：`tools/check_approval_queue_coverage.py` 是掃來源碼找提供者。改動前，這兩類的 SQL 寫在 M01 的 quotations.py 裡，arap 在不在都掃得到；本包把它們移到 `modules/arap` 的提供者，模組拿掉就掃不到。
- 列車現在只跑 core-only 與真刪（使用者裁示「全量等開發完成才跑」），這一題會在列車上紅。
- 修法：覆蓋檢查對「擁有模組沒安裝」的類型改列為「不適用」，並說出原因；例如 `APPROVAL_DOC_TYPES` 對到擁有模組、用 `module_installed` 判斷。另外保留一個正對照：模組在時一定要找到。

**AP-M2　「沒有金額權限的人看不到存簿圖片」沒有任何題驗（主持重點：存簿不可外洩）**
- 突變 AP2：拿掉 `out["files"] = [f for f in out["files"] if f.get("id") != "passbook"]` ⇒ 70 題全綠。
- 存簿封面屬 F2（MODULE-GUIDE §3.2：協力廠商帳戶一律當個資）。能通過每案權限、但沒有財務檢視權的人，例如該案業務或協作者，會拿到 `dataUrl`。
- 舊版就有同一行、也同樣沒有題驗，不是本包造成的；但本包把這類改由提供者組裝，過濾現在依賴提供者用 `id == "passbook"` 這個約定。提供者改個 id，過濾就會靜默失效。
- 建議修法：
  - 補一題：造一張帶 `bankPassbookImage` 的承攬商匯款申請，讓「該案業務、非財務、非簽核人」取 detail，斷言 files 裡沒有 dataUrl，也沒有 passbook。再加正對照：簽核人或財務看得到。
  - 過濾改用結構判斷，例如任何帶 `dataUrl` 的檔案，不要只靠 id 字串。

### 觀察

- **AP-O1**：`reassign_approval` 裡「`tiers = _active_tiers(appr)`／`if not tiers: raise`」連寫了兩次，無害，是重複的程式碼。

## 3. 回覆欄

| # | 回覆 | commit | D 確認 |
|---|---|---|---|
| AP-M1 | | | |
| AP-M2 | | | |

## 4. 複核：C 整疊 rebase 到第九班之後（c-m05b-3 … c-approval-3 6cdc0ed0；D 19:36）

**① range-diff**（舊 \`c98e43d0..49dcb781\` ⇔ 新 \`f0587058..6cdc0ed0\`；排除產生檔、CHANGELOG、registry 版號、module.json、l1 snapshot 之後比對）：
- T 的 4 個 commit 已在 platform，因此從疊裡消失。
- 標「=」的 commit 內容完全相同；標「!」的差異全是 rebase 衝突的解法：
  - 第九班把 inventory、shipping_notes 搬進 \`modules/supply\` ⇒ main.py 的 import、題目路徑、出貨單提供者改由 supply 的 ModuleSpec 宣告。
  - T100 notice 併入第九班的 IP-20（\`_t100_notice()\` 多列一項 receivables）。
  - 題目改成從 \`modules.arap.api\` import，並加上 M05 不在時 importorskip。
  - KNOWN_L1 說明更新。
- 新增的 commit：
  - 3 個 rebase chore（core_bump 1.39～1.42、產生檔重產）。
  - d1ba5b21：cashier 選單自 \`core/menu_l1.json\` 移進 arap module.json 的 \`pages[].menu\`，並把 A 的兩個淘汰別名登記進 deprecations.json（M5-M1 交會解掉）。
  - 37c6aeda：AP-M1／AP-M2 的修正。
- 沒有看到超出上述範圍的產品碼改動。

**② AP-M1**：\`check_approval_queue_coverage\` 加 \`_OWNER_MODULE\`（contractor_voucher→subcontract、invoice_voucher／payment_request→arap、bonus→payroll、6cdc0ed0 補 shipping_note→supply），擁有模組的 module.json 不在 ⇒ 列「不適用」並說明。
- D2 實測（6cdc0ed0）：arap 在 ⇒ 21 過；**刪 arap ⇒ 16 過、5 skip**（開票申請題寫明 M05 不在），覆蓋檢查不再紅。
- 突變 AP1b「不適用失效」⇒ 紅。⇒ **AP-M1 關閉（37c6aeda／6cdc0ed0）**。

**AP-M2**：新題 \`test_case_sales_without_money_rights_gets_no_passbook\`：該案業務拿不到 passbook 也拿不到 dataUrl；簽核人拿得到。過濾改為「有 dataUrl 或 id==passbook」。
- 突變 AP2b「不遮存簿」⇒ 紅。⇒ **AP-M2 關閉（37c6aeda）**。
- 觀察 **AP-O2**：突變 AP2c「只看 id、不看 dataUrl」存活。現有題的存簿 id 就是 passbook，所以「提供者改 id 仍擋得住」這層結構判斷沒有題驗；建議合成一個 id 不同、但帶 dataUrl 的檔案。
- 觀察 **AP-O3**：\`test_unreadable_chain_is_refused\`（AP7）掛在 M05 的 iv_setup 上，M05 不在時 L1 \`DataJsonApproval\` 的 fail-closed 沒有題驗。

