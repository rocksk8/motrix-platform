# 第 29 班獨立稽核清單（audit/train29，2026-10-01）

稽核者：builder/dept 子視窗（以下簡稱 A29）。範本：`docs/platform/audit/AUDIT-D-train19-final.md`（判定／內容範圍／包的驗證／演練／安裝指示）＋PLAYBOOK §E（四件事：規格逐條驗收＋可重現證據、反向控制、找假綠燈、必修／建議／觀察三級）。
基準：正式機 **0bb4834e**（BASELINE，tag `prod/0bb4834e`）。被稽核：`wip/train-29-int1` 合併後、`ff platform` 之後建出的部署包。
**不跑全量**：全量與預演列車由列車長負責（作者測試結果採信）；A29 只做探針、突變、存疑題、獨立重算。

## 0. 獨立性聲明（先看）

A29 **是下列改動的作者**，不能稽核自己的成果，請主持另指一位稽核者（本檔 §6 把它們列成「待他人稽核」）：
`fix/login-approval-popup`（登入橫幅／標已讀）、`fix/contractor-bank-mask`（承攬商帳號遮蔽）、`fix/dept-follows-sales-owner` ＋ `wip/w3-dept-dim-c7`（部門跟業務負責人）、`fix/module-delete-ownership`（刪除模組＋modules.json 歸屬）、`ad418e88`（選單位置）、`fix/manifest-vr3`。
A29 稽核的是**別人寫的**：W1（A2-0、表單／類型）、W2（A2 額外支出）、W3（員工收款帳號、地圖縮放、類型編輯頁）、W4（總帳 G1～G3）、d7 合併。

## 1. 包與簽章（機械、先做、任何一項不符＝整包退）

| # | 檢查 | 做法（可重現） | 通過條件 |
|---|---|---|---|
| P1 | 包的 commit ＝ 預期 SHA | 讀 `deploy_manifest.json` 的 `commit`／`base`；與主持宣告的 platform SHA、`git rev-parse` 對 | 三處相同；`base`＝0bb4834e |
| P2 | `package.sha256` | 自行對包（目錄／壓縮檔）重算 SHA256，與主持、安裝指示（CLAUDE-正式機安裝指示_*.md）三處比對 | 全相同 |
| P3 | 簽章 | 用**公鑰**驗 `deploy_manifest` 簽章（工具：`backend/tools/verify_package.py`、`tools/platform/module_update.py` 的驗章段）。**不讀私鑰**（`D:\MOTRIX-KEYS` 不碰） | 驗章通過；改一個位元組（在拋棄式複本上）⇒ 驗章失敗＝反向控制 |
| P4 | 逐檔對 git blob | `git ls-tree -r <commit>` vs 包內檔；CRLF 差異另列 | 不同檔＝只有 version_manifest（投影欄位）與建包產生檔；其餘 0 |
| P5 | 包內不該有的東西 | 包內 grep：`tests/`、`.git`、`*.db`、`hmac.key`、`initial_*_credentials`、`_demo_*`、私鑰、`full_results/` | 0 命中；**同一比對器先在工作樹找已知命中（正對照）** |
| P6 | 範圍（diff scope） | `git diff --name-only 0bb4834e..<commit>` 去 docs/tests：對 §2 清單（本班 148 檔、約 +11104/-410）逐檔歸屬 | 沒有清單外的產品檔；沒有「只為過守門」的行為改動；`tools/platform/pre_train_check.py` 是工具、不應進產品包 |
| P7 | 版本紀錄 | `version_manifest.json`：已出貨條目未被改寫（`test_version_manifest_shipped_is_immutable`）；一模組一筆（VR3）；`next` 佔位已取號、無殘留 | 0 佔位、0 重複；`CORE_VERSION`／module.json 版號＝CHANGELOG 最上面 |
| P8 | 產生檔 | `dep_scan.py --check-modules`、`unit_index.py --check`、test_map 重產後無差 | 無差 |
| P9 | 演練 | 用正式機資料**複本**跑 `apply-run`（`final_drill.py`／`upgrade_drill.py`）：升級＋兩種回滾（健檢失敗回滾、手動回滾）＋冒煙 | `RESULT status=success`；回滾後回到 0bb4834e 且 `/api/ping` 200；server.log 只有已知告警 |

## 2. 本班改動的歸屬（P6 的對照表，作者各負責其測試結果）

| 線 | 主要檔 | 風險面 |
|---|---|---|
| W1 A2-0／類型定義 | `helpers/expense_types.py`、`helpers/expense_type_defs/*`、`core/definitions.py`（`D.kinds()`）、`routers/definitions.py`、`static/definition-form.js` | 定義庫變更（既有四種 kind 不得變） |
| W2 A2 額外支出 | `modules/case/api/case_extra_expenses.py`、`expense_forms.py`、`expense_notify.py`、`api/expense_form_pdf.py`、`payables.py`、`recognition.py`、`gl_events.py`、**migration `case/0003_expense_forms.py`** | **金額可見性、作廢／付款覆寫、總帳事件、報表列** |
| W3 員工收款帳號 | `modules/payroll/bank_account.py`、`api/bank_account.py`、**migration `payroll/0003_user_bank_accounts.py`**、`frontend/pages/bank-account.html` | 個資（reveal 規則、稽核不含全碼） |
| W3 地圖／類型編輯頁 | `frontend/pages/map.html`、`expense-types.html`、`js/expense-types.js` | 前端；編輯頁寫定義庫（誰能寫） |
| W4 總帳 | `modules/accounting/ledger/*`、`api/ledger_category_map.py`、`voucher_summary.py`、**migration `accounting/0003_dims_and_categories.py`**、`analytics/api/ledger_diff.py` | 分錄正確性、與營運報表對帳、migration |
| 檔案中心 | `modules/filehub/api.py`、六個模組的 `attachments.py`、`helpers/attachment_search.py`、`pages/file-center.html` | **誰搜得到／預覽到哪些附件（own_rule）** |
| 其他 | `helpers/email_notify.py`／`mail_types.py`／`notification_prefs.py`／`tiered_approval.py`／`doc_render.py`、`routers/system.py`、`archive.py`、`pdf_gen.py` | 信件不含金額與帳號；備份分流 |
| （A29 作者，待他人稽核） | 見 §0 | — |

## 3. 權限敏感路徑（逐條探針：角色矩陣 × 端點／輸出，斷言打在伺服器回應與 DB，不打畫面文字）

角色矩陣固定用：superadmin、admin（無額外模組）、admin＋cashier／finance、一般 user（申請人本人）、簽核鏈成員、無關 user、停用帳號。

### 3.1 帳號遮蔽（員工收款帳號＋承攬商）
- 員工（W3）：`GET /api/me/bank-account`（本人完整）、`/api/bank-accounts[/{id}]`（預設遮蔽；`reveal=1` 才完整＋寫稽核）、`/history`。**探針**：非資格者 reveal＝403／遮蔽；稽核 `detail`／日誌／錯誤訊息**全文不含帳號全碼**（grep 稽核表）；`payee.bank_profile` 提供者（A2 收款人）給表單／PDF／匯出時是否洩全碼；每日 JSON 匯出（archive）分流。
- 承攬商（A29 作者→他人稽核，列 §6）。
- **一致性疑點（需主持／使用者確認）**：使用者裁示「承攬商：只有最高管理者看完整」；員工帳號卻允許 superadmin／finance／cashier（reveal＋稽核）。兩套規則不同——是刻意（員工薪資付款需要出納）還是漏網？先列為「待裁示」，不當缺陷。
- **突變**：M-B1 `may_see_full` 永遠 True；M-B2 `reveal` 不寫稽核；M-B3 `mask_number` 回原值 ⇒ 對應測試必須紅。

### 3.2 類型化額外支出可見性（`case_extra_expenses.py:_amount_viewer／_mask_row／_caseless_visible`）
- 規則（使用者 2026-10-01）：申請人、本單簽核鏈、出納／財務、admin 以上看金額；其他人只看狀態。
- **探針**：每個**輸出面**各打一次（不只列表）：列表／詳情／摘要與合計（`fee_total` 是否只算 visible）／匯出／PDF（`expense_form_pdf.py`）／通知信（信內不含金額）／簽核佇列／營運報表列（W2 報表列）／總帳事件 payload／全文搜尋與檔案中心。無關 user 與無案件單據（`quote_no=""`）特別測。
- **假綠燈檢查**：遮蔽測試是否用 admin 帳號（admin 直通）而沒測「非 admin 且非簽核人」；`_MASKED_KEEP` 白名單是否夾帶說明／類別（註解寫了不留）。
- **突變**：M-E1 `_amount_viewer` 回 True；M-E2 `_mask_row` 不清 `lines`；M-E3 `_caseless_visible` 對 None 回 True（fail-open）。

### 3.3 作廢／付款日覆寫（`case_extra_expenses.py:664 void`、`:580–640 paid_date`）
- 規則：作廢只有 superadmin、且僅「已核准且尚未付款」；`paidDate` 只有出納或 admin+ 能設；已有付款日的清除／改期只限 admin+，並寫 `extra_expense.paid_date_override` 稽核。
- **注意措詞落差**：使用者清單寫「void/paid override superadmin-only」，程式是 void＝superadmin、paid override＝**admin+**。A29 先照程式與使用者裁示原文核對，不一致列「待裁示」。
- **探針**：申請人本人設／清付款日（403）；出納清已付日（403）；admin 清（200＋稽核列存在且 target 正確）；superadmin 以外作廢（403）；作廢已付款（拒）；作廢後總帳事件與營運報表是否反向／消失（W2 自述「作廢路徑未做」——確認包裡到底有沒有，沒有就明說未覆蓋）。
- **突變**：M-V1 去掉 `role != superadmin` 檢查；M-V2 去掉 `old_paid and changed` 的 admin+ 限制；M-V3 override 不寫稽核。

### 3.4 檔案中心 own_rule（`filehub/api.py`、六個 `attachments.py`、`attachment_search.py`）
- 規則：無案件條件的全域搜尋只有 superadmin 或 `file_center` 模組；逐檔可見性走各來源模組自己的 `case_owner_readable`／own_rule（`case_read_scope.json` 分類 row_access／module／own_rule）。
- **探針**：A 的案件附件，B（無該案權限、有 file_center）搜得到嗎？預覽／下載（`uploads.path_access` 直連路徑）？搜尋結果摘要是否含不該看的檔名／金額；停用／缺席模組（反向控制：模組不在時 filehub 要明說不可用，不是回空當作沒有）。
- **假綠燈**：搜尋測試只用 superadmin；`test_case_read_scope.py` 只驗分類登記、不驗行為。
- **突變**：M-F1 某來源 `attachments.py` 的可見性回 True；M-F2 搜尋略過 `case_owner_readable`。

### 3.5 其他權限面（抽查）
- 登入橫幅／通知（A29 作者，待他人稽核）；`routers/system.py` 變更；`archive.py` 個資分流 `_F2_FIELDS`（員工帳號是否進分流）；信件類型不含金額與帳號。

## 4. migration 與資料安全

| # | 檢查 | 做法 | 條件 |
|---|---|---|---|
| M1 | 冪等 | 在 0bb4834e 的 DB 複本上連跑 migration 兩次（`case/0003`、`payroll/0003`、`accounting/0003`），比對 schema 與列數 | 第二次零變更、零例外；`ADD COLUMN` 皆有存在檢查 |
| M2 | 不動舊資料 | 升級前後比對 `case_extra_expenses`／`gl_*` 既有列（hash）；舊列 `kind=''`、行為不變 | 舊列逐欄相同 |
| M3 | 回滾 | 升級後回滾到 0bb4834e 的程式：新增欄位／表是否讓舊程式啟動失敗？（只增不改應可共存） | 舊程式啟動＋`/api/ping` 200＋舊功能不壞 |
| M4 | 外鍵／索引 | `PRAGMA foreign_key_check`、`integrity_check` 升級後 | 無輸出／ok |
| M5 | 備份相容 | 每日 JSON 匯出能含新表／新欄（`test_system_audit_2026_09_14` 的表分類）；不夾帶祕密欄位 | 0 缺、0 洩漏 |
| M6 | 版本號 | `db.CURRENT_VERSION`／各模組 migration 序號與 CHANGELOG 一致、無撞號（列車取號後） | 一致 |

## 5. 最危險的五項：探針＋突變（對應 §3、§4）

| # | 變更 | 為什麼最危險 | 探針 | 突變（測試必須紅，否則＝假綠燈，必修） |
|---|---|---|---|---|
| R1 | 員工收款帳號（W3 payroll 0003＋reveal） | 個資＋新 migration＋三種角色例外 | §3.1 | M-B1／B2／B3 |
| R2 | 類型化支出金額可見性（W2） | 多輸出面、遮蔽漏一面＝洩漏；fail-open 風險 | §3.2 | M-E1／E2／E3 |
| R3 | 作廢＋付款日覆寫（W2） | 動錢的狀態；權限與稽核 | §3.3 | M-V1／V2／V3 |
| R4 | 檔案中心 own_rule（W1/W2 附件提供者） | 跨模組可見性，單一提供者錯＝全站洩漏 | §3.4 | M-F1／F2 |
| R5 | 三個 migration＋總帳維度（W4 accounting 0003） | 不可逆資料結構；分錄正確性 | §4 M1～M4＋抽 3 筆分錄對營運報表重算（`ledger_diff`） | M-L1 `category_map` 回錯科目；M-L2 migration 去掉存在檢查 |

突變做法（PLAYBOOK §G：突變前先 commit、在自己的 worktree；還原用 `git checkout -- <檔>` 只還原**單一檔**，不碰未 commit 的其他修改——吃過一次虧：還原整檔會連同正式修改一起吃掉）。編譯紅≠測試紅：突變後先確認模組仍可 import，再看測試是否因斷言而紅。

## 6. 待他人稽核（A29 為作者）與不覆蓋範圍

- 待他人：登入橫幅、承攬商帳號遮蔽（含 PDF／簽核佇列）、部門跟業務負責人（reports／dashboard 全部彙總）、刪除模組（含 L1 歸屬）、選單位置、manifest VR3。各線自述與測試：見各分支 commit 與 `docs/quick/changelog.md` 2026-10-01 條目。
- A29 **不覆蓋**：W1 表單畫面（A2-2/A2-4/A2-7，若未進包）、去識別化 prodroot、時鐘守門、檔案中心 P3（未排入）。進包與否以 `deploy_manifest` 的檔案清單為準，**列出但不審**要明寫在報告。
- 已知未做（作者自述）：W2 作廢路徑／稽核匯出 PDF／四型 e2e；W3 通知信、隱私說明；W4 G4 文件／G5／recon 分桶；`A5 守門自動探索 83eb814a`（**未驗證、有疑慮，單獨 revert**）——確認它**不在**包內，若在＝必修。

## 7. 報告格式與關閉

- 產出 `docs/platform/audit/AUDIT-A29-train29.md`：§0 判定（可上／有條件／不可）、§1 範圍、§2 包的驗證表（P1～P9 逐項結果）、§3 探針結果（附指令與回應節錄）、§4 突變表（突變→紅的測試名／沒紅＝假綠燈）、§5 發現（必修／建議／觀察，附 `檔案:行號`＋重現指令）、§6 不覆蓋與待裁示。
- 必修的關閉寫單行 `✅ <編號> 關閉（<commit>）`，未關登記 `docs/platform/mustfix_open.json`（上限 10 筆）；被稽核者不可自己關。
- 判定前提：P1～P5、P9 全過；R1～R5 突變全紅；無未關必修。
- 資源：不跑全量；一次最多跑 1 個 pytest 行程（`-n 2` 以下）；暫存放 `D:\開發測試檔\`、用完即刪；先向列車長要測試鎖時段。
