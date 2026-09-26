# 會計 更新紀錄

## 1.0.1 — 2026-09-26（A，wip/a-m06-4：稽核 D M06-M1／M2／S1／S2＋a' 到期；列車取號）
- 傳票摘要的承攬商派工改走 IP-15 成本檢視 `dispatch.cost_for_case`（B 的 b-ip15-cost）：不再讀 M04 的派工表；外包人員改列「外包人員 N 人」（主持裁示）；讀不到成本（403）⇒ 明說
- 案件的傳票（by-case）派工那一段的 id 也來自成本檢視
- 傳票摘要的「案件」清單改走 M01 的 IP-96 `case.summary`（到期守門觸發）：只列看得到的案件，回應 notes 與畫面都註明範圍
- 到期守門：a' 與 a 的 quotations 到期刪除，剩 case_extra_expenses（等 case.extra_expenses）
- 題：拿掉本模組時多紅的 5 題逐題處理（搬進本模組或改驗 M06 不在時的行為）

## 1.0.0 — 2026-09-26（A，M06 搬遷；未發版，搬遷各步驟併在這一段；列車取號）
- 模組化：自 `routers/{vouchers,accounting_export,account_items}.py` 搬入 `api/`、`helpers/{voucher,voucher_pdf,voucher_template,voucher_attachments}.py` 搬入模組根（PLAYBOOK §B；M06-PLAN）
- 提供者改由 `ModuleSpec.providers` 宣告：IP-2 `voucher.draft`／`voucher.account_check`、IP-3 `accounting.settings`、IP-4 `voucher.void_draft`／`voucher.status`、IP-22（暫定號）`voucher.by_case`
- 選單（傳票、會計科目）自 L1 `core/menu_l1.json` 移進 `module.json` 的 pages[].menu（模組不在 ⇒ 側欄不出現）
- 規格：JV1～JV36 在本模組 `SPEC.md`（主持裁示 M06-e）
- 附件來源（IP-21，a-attachments-4～6 帶入）：依原單據自己的讀取規則；因權限沒列出只說類別＋個數；整個案件看不到照「不存在」回
- `vouchers` 是 VIEW：module.json 另列 `views`（不備份、不分類）
