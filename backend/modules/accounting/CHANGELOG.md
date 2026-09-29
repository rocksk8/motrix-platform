# 會計 更新紀錄

## 1.0.7 — 2026-09-30（暫用號，列車取號；wip/w2-report-cash）
- T100 收款傳票：客戶內扣手續費時「借 銀行(入帳＝含稅−手續費)＋借 收款手續費支出／貸 銷貨收入＋銷項稅額」，借貸相等；沒有手續費時與舊版完全相同。設定新增選填 `receiptFeeAccount`（收款手續費支出科目，出納頁 T100 設定可填；沒填時匯出檔頭提示）。

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
