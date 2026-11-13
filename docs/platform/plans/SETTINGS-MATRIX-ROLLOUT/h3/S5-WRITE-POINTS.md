# S5 調查：§15 四個「加變更管制」項目現在的寫入點（唯讀盤點；hichan-3，2026-11-13，基底＝origin/feat/settings-matrix-rollout 的 backend/）

結論先講：四項**沒有一項能直接宣告成現有 registry 群組**。registry 的 `SettingDef` 只有 `int/float/bool/str`（`settings_registry.py:32 _TYPES`），一個群組只有**一個** `legacy_key`（單一 dict 鍵或純量鍵，`register_group(..., legacy_key=)`）。下表是各項的實際儲存形狀與落差。所有舊端點都只有「最高管理者＋整包寫入＋一筆稽核」，沒有等待期、沒有第二人。

| 項目 | 端點（檔:行） | 儲存位置 | 形狀 | 讀取端（誰吃這個值） | 能否直接進 registry | 落差 |
|---|---|---|---|---|---|---|
| 傳票科目（憑證帳戶＝獎金傳票科目） | GET／PUT `/cases/voucher-accounts`（`modules/payroll/api/bonus.py:1575／:1590`） | `system_settings` 的 **5 個獨立純量鍵**：`bonus_case_voucher_expense_code`／`_payable_code`／`_withholding_code`／`_nhi_code`／`_bank_code`（`modules/payroll/bonus_vouchers.py:25 ACCOUNT_SLOTS`，預設 6111／2191／2252／2252／1113） | 5 個字串 | `bonus_vouchers.configured_accounts(conn)`（`bonus_vouchers.py:34`；`bonus_correction.py:182／:225`、傳票草稿 `:108`） | 5 個 `str` 欄位可（一個群組 `bonus_voucher`） | 單群組只有一個 `legacy_key`，但這 5 個是 5 個不同鍵 → 需要「舊儲存位置轉接器」（讀：5 鍵→欄位；寫：欄位→5 鍵）。PUT 現在先驗「科目存在且未停用」（`account_problem`），一個不合格整批不寫 → 這個檢查要搬進群組的 `cross_check`。放寬方向？科目代號沒有大小方向，需 h4 的 §15 addendum 決定（建議：任何變更都走「只等待」或「等待加核准」二選一，不分方向）。 |
| 扣繳參數 | GET／PUT `/api/legal-params/tax-rules`（`routers/legal_params.py:18／:74`） | `system_settings` 鍵 `tax_rules_versions`＝**版本陣列**（`helpers/legal_params.py:19 VERSIONS_KEY`；`load_versions`:421、`save_versions`:437；舊鍵 `tax_rules`） | list of dict（每版含生效日、各所得類別費率與門檻） | `lp.load_versions()` 共 9 處（勞報單扣繳、獎金扣繳、補充保費…） | **不行**（結構是版本陣列，型別非純量） | 需要新做「版本草稿」套用變更管制：已有自己的保護——已生效版本鎖定（`frozen_changes`:226）、`validate_versions`、最低工資＝補充保費門檻。建議不把它塞進 registry 欄位，而是：新增版本（生效日在未來）本身已是「等待」；只在「儲存新版本／修改尚未生效版本」時加確認視窗＋變更紀錄＋通知，是否需第二人由 addendum 決定。放寬方向難定義（費率調低？門檻調高？）。 |
| T100 科目代號 | GET／PUT `/api/settings/t100-export-config`（`modules/accounting/api/accounting_export.py:221／:238`；PUT 要最高管理者，GET 要財務權限） | `system_settings` 鍵 `t100_export_config`＝**巢狀 dict**：`bankAccounts`（list of {name, acctCode}）、`defaultBankAccountCode`、`salesRevenueAccount`、`outputTaxAccount`、`contractorExpenseAccount`、`remitFeeAccount`、`receiptFeeAccount`、傳票別、`inventoryExpenseAccounts`（{分類: 代號}，鍵隨料件分類動態增加）（`_t100_config`:128） | 巢狀 dict＋清單 | `_t100_config()`；`bonus.py:1560` 出納選銀行（走 IP-3 `accounting.settings`） | **不行**（清單＋動態鍵） | 需要「清單型群組」或轉接器：registry 沒有 list／dict 型別。PUT 用 pydantic `T100ExportConfigBody` 整包驗證，儲存時**不擋**不存在的科目（只在 GET 回 `codeIssues` 警示）。 |
| 管銷／公益口徑 | GET／PUT `/api/overhead/settings`（`modules/case/api/overhead.py:17／:57`）；工具 `tools/overhead_migrate.py`、`tools/charity_migrate.py` | `system_settings`：`overhead_rule_mode`（legacy／v2）、`overhead_migration_done`（標記）、`charity_basis_mode`（direct／total）、`charity_migration_done`（標記）、`overhead_default_pct`（純量）；`profit_rules.charity_rate_pct` 在 registry（`helpers/profit_warning.py`） | 2 個字串模式＋2 個標記（由遷移工具寫入／口徑退回時刪除） | `profit_guard.rule_mode()`／`charity_mode()`／`migration_done()`（`modules/case/profit_guard.py:29–96`） | 口徑 2 欄可當 `str`＋`choices`；標記不是設定 | **已經有一半在 registry**：`overhead.default_pct`（`helpers/settings_groups_overhead.py`，money、`loosen="down"`、requires 第二人，舊入口 `defaultPct` 已走 `publish`）與 `profit_rules.charity_rate_pct`。**尚未管制的只有兩個口徑切換**（`ruleMode`、`charityMode`）：PUT 內直接 `_set_setting`＋刪標記；退回 legacy 會**連動**把公益基數強制改回 direct 並刪兩個標記；切到 v2／total 要 `confirm:true` 且遷移完成標記存在，否則 409。口徑切換不能被 registry 的單欄位寫入表達（有連動與標記），要寫成「切換申請」：申請時做前置檢查（遷移標記、連動影響），核准／期滿才一次寫入模式＋刪標記。 |

## 通知類（維持立即生效、存檔後發通知）三項的寫入點
- 獎金預設比例：GET／PUT `/cases/settings`（`bonus.py:1512／:1519`）；鍵 `bonus_case_default_rate_bp`（`bonus.py:1183`）＋三類比例鍵（兩次分開寫入）。
- 營運目標：GET／PUT `/api/settings/operating-targets`（`routers/system.py:240／:248`）；鍵 `operating_targets`（整份覆蓋、一次只存一年；寫入點 `:251`、稽核 `settings.operating_targets.update`）。
- 報價條款：`/api/settings/quote-terms-presets`（GET `system.py:2479`、PUT `:2486`）、預設付款條件 GET／PUT `/api/settings/payment-terms`（`:1970／:1977`，鍵 `default_payment_terms`，稽核 `settings.payment_terms.update`）。
- 這三項只要在各自 PUT 成功後呼叫 S1d 的 `notify_change(...)`（一行式），不需要 registry。

## 給 §15 addendum 的決定點（我不自己決定）
1. 「放寬方向」每項怎麼定義（或乾脆不分方向、一律『只等待』？一律『等待加核准』？）。
2. 傳票科目 5 欄：轉接器放哪（`bonus_vouchers` 內？或 registry 通用「多鍵舊儲存」）；`account_problem` 檢查搬到 `cross_check`。
3. 扣繳參數：版本陣列是否例外處理（不進 registry，沿用版本生效日當等待期＋確認視窗＋通知）？
4. T100：是否需要清單型欄位（registry 擴充型別）或轉接器＋整包 JSON 比對。
5. 口徑切換：做成「切換申請」（前置檢查→申請→核准／期滿→一次寫入＋刪標記），遷移仍由工程師執行（mockup 已這樣畫）。
6. 讀取端要不要改：待生效期間讀取端仍用舊值，生效時才寫入舊鍵（現有 registry 的雙寫機制行為），這四項的讀取端（見上表）可以不動。
