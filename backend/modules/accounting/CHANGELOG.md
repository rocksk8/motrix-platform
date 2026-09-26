# 會計 更新紀錄

## 1.0.0 — 2026-09-26（A，M06 搬遷；未發版，搬遷各步驟併在這一段；列車取號）
- 模組化：自 `routers/{vouchers,accounting_export,account_items}.py` 搬入 `api/`、`helpers/{voucher,voucher_pdf,voucher_template,voucher_attachments}.py` 搬入模組根（PLAYBOOK §B；M06-PLAN）
- 提供者改由 `ModuleSpec.providers` 宣告：IP-2 `voucher.draft`／`voucher.account_check`、IP-3 `accounting.settings`、IP-4 `voucher.void_draft`／`voucher.status`、IP-22（暫定號）`voucher.by_case`
- 選單（傳票、會計科目）自 L1 `core/menu_l1.json` 移進 `module.json` 的 pages[].menu（模組不在 ⇒ 側欄不出現）
- 規格：JV1～JV36 在本模組 `SPEC.md`（主持裁示 M06-e）
- 附件來源（IP-21，a-attachments-4～6 帶入）：依原單據自己的讀取規則；因權限沒列出只說類別＋個數；整個案件看不到照「不存在」回
- `vouchers` 是 VIEW：module.json 另列 `views`（不備份、不分類）
