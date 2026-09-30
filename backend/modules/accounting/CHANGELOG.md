# 會計 更新紀錄

## 1.0.11 — 2026-09-30（暫用號，列車取號；wip/w2-voucher-office）
- 傳票附件開放 Word／Excel（使用者裁示）：docx／xlsx／doc／xls 也可上傳（jpg／png／pdf 保留；exe 等其他格式仍拒）；放行只限傳票附件（L1 `helpers/uploads.py::_EXTRA_EXTS_BY_SUBFOLDER`，函式簽章不動），單檔 20MB 上限沿用；三個上傳入口（主頁面、預覽窗、來源清單為空）的檔案選擇器與提示同步。
- 匯出「含附件」PDF：Word／Excel 不併入，只在最後一頁列檔名（既有「未能併入」規則）；附件標籤改「不會併入 PDF（只列檔名）」。下載一律 `attachment` 且檔名正確（含中文）。

## 1.0.10 — 2026-09-30（暫用號，列車取號；wip/w2-report-cash）
- T100 收款傳票：客戶內扣手續費時「借 銀行(入帳＝含稅−手續費)＋借 收款手續費支出／貸 銷貨收入＋銷項稅額」，借貸相等；沒有手續費時與舊版完全相同。設定新增選填 `receiptFeeAccount`（收款手續費支出科目，出納頁 T100 設定可填；沒填時匯出檔頭提示）。
## 1.0.9 — 2026-09-30（暫用號，列車取號；W1 wip/w1-remit-fee）
- 稽核補修：T100 承攬商付款傳票排除「差額待審核」（核可後才進、退回則整筆消失），對齊 accounting_export 註解
- W1 出納匯款手續費（暫用號，列車取號）：T100 承攬商付款傳票：承攬商費用＝實付金額（舊資料＝應付）、手續費另借「匯款手續費支出」（設定 `remitFeeAccount`，選填；沒填 ⇒ 匯出檔頁尾列出缺科目）、銀行存款貸方＝實付＋手續費（借貸相等）
## 1.0.8 — 2026-09-30（暫用號，列車取號；wip/w2-voucher-dash-2，W2 交叉稽核 S2／S4）
- S4：`POST /api/vouchers/{id}/attachments`（上傳與帶入兩種形態）只允許草稿（`can_edit`），與刪除同一條規則；離開草稿的傳票回 400（原本除作廢外不看狀態，加了也刪不掉）。作廢重開（JV24）走內部複製，不受影響。
- S2：`bringIn` 新傳票自動存檔期間 `uploading` 保持鎖定；存檔中（busy）不插入。連點不再出現「傳票尚未儲存」假錯誤、也不會重複帶入。

## 1.0.7 — 2026-09-30（暫用號，列車取號；W2 wip/w2-voucher-dash）
- 傳票「帶入附件」：新傳票尚未存檔（沒有 id）時，`bringIn` 以前靜默 return ⇒ 按了沒反應；改為自動先存成草稿（存檔失敗才在附件區顯示原因），再帶入。後端契約不動（附件掛傳票 id）
- 傳票預覽窗（草稿）新增「從電腦上傳檔案」入口；分錄下方來源清單為空時，同處提示可直接上傳。離開草稿後來源區塊與上傳入口本來就不出現（設計，非缺陷）

## 1.0.6 — 2026-09-29（暫用號，列車取號；wip/payslip-void-signed）
- 新增提供者 `voucher.by_no`（IP-4 追加）：以傳票單號查 `{id, voucher_no, status, voided}`，不存在 ⇒ None；唯讀。勞報單出納付款回填傳票單號時驗證用（M07 不直接讀 `vouchers_all`）。

## 1.0.5 — 2026-09-28（暫用號，列車取號；E4 wip/e-company-gate-impl 第三段）
- 本公司資料設定閘門第二道（COMPANY-SETUP-GATE §5；D CG5-M1）：傳票 PDF 的公司抬頭改走 L1 `company_identity.company_name()`（主要據點與別名都認，且先過第二道：未設定／判定失敗 ⇒ 428，不產生）；原本只讀 `company_profile["name"]`

## 1.0.4 — 2026-09-27 23:02（暫用號；H10 品牌設定，主持派工）
- 頁面的分頁圖示（favicon）改讀 `/api/system/branding/favicon`（L1 品牌設定，可在公司資料設定更換；沒上傳回預設圖）：`voucher.html`、`account-items.html`

## 1.0.3 — 2026-09-27（第十三班列車取號；c-approval-l1-4，稽核 D QJ-M1）
- 待簽佇列提供者 `_queue_items`：傳票的簽核 JSON 改經 L1 `approval_raw_of` 逐筆解析（原本 `tier_fields` 直接吞 `approval_json`，壞的一筆解不出來就當成空字典 {}⇒ 列給每個 superadmin、角標多計 1，核准時才丟例外）；解析不了 ⇒ 跳過那一筆＋ERROR（寫單號不寫內容）

## 1.0.2 — 2026-09-26（A，wip/a-m06-5：主持裁示對齊 AT6-O1；列車取號）
- 傳票摘要的「案件」清單改帶 IP-96 用途 `purpose="voucher_link"`：有傳票權限（cashier／finance）列全部案件、只拿摘要欄位（權限判斷在 L1）；範圍與現行相同（JV7）
- 撤回 1.0.1 的範圍註明（回應 notes 與畫面）；M01 不在時的「案件模組未安裝」說明保留

## 1.0.1 — 2026-09-26（A，wip/a-m06-4：稽核 D M06-M1／M2／S1／S2＋a' 到期；列車取號）
- 傳票摘要的承攬商派工改走 IP-15 成本檢視 `dispatch.cost_for_case`（B 的 b-ip15-cost）：不再讀 M04 的派工表；外包人員改列「外包人員 N 人」（主持裁示）；讀不到成本（403）⇒ 明說
- 案件的傳票（by-case）派工那一段的 id 也來自成本檢視
- ~~傳票摘要的「案件」清單改走 M01 的 IP-96 `case.summary`（到期守門觸發）：只列看得到的案件，回應 notes 與畫面都註明範圍~~ 〔更正（1.0.2）：縮小範圍違反 AT6-O1 裁示（JV7 照現行：有傳票權限列全部案件）⇒ 改帶用途 voucher_link，範圍註明撤回〕
- 到期守門：a' 與 a 的 quotations 到期刪除，剩 case_extra_expenses（等 case.extra_expenses）
- 題：拿掉本模組時多紅的 5 題逐題處理（搬進本模組或改驗 M06 不在時的行為）

## 1.0.0 — 2026-09-26（A，M06 搬遷；未發版，搬遷各步驟併在這一段；列車取號）
- 模組化：自 `routers/{vouchers,accounting_export,account_items}.py` 搬入 `api/`、`helpers/{voucher,voucher_pdf,voucher_template,voucher_attachments}.py` 搬入模組根（PLAYBOOK §B；M06-PLAN）
- 提供者改由 `ModuleSpec.providers` 宣告：IP-2 `voucher.draft`／`voucher.account_check`、IP-3 `accounting.settings`、IP-4 `voucher.void_draft`／`voucher.status`、IP-22（暫定號）`voucher.by_case`
- 選單（傳票、會計科目）自 L1 `core/menu_l1.json` 移進 `module.json` 的 pages[].menu（模組不在 ⇒ 側欄不出現）
- 規格：JV1～JV36 在本模組 `SPEC.md`（主持裁示 M06-e）
- 附件來源（IP-21，a-attachments-4～6 帶入）：依原單據自己的讀取規則；因權限沒列出只說類別＋個數；整個案件看不到照「不存在」回
- `vouchers` 是 VIEW：module.json 另列 `views`（不備份、不分類）
