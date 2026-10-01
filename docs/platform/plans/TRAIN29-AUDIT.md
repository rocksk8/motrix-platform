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

## 8. 主持答覆（2026-10-01，已併入判準）

- 獨立性：A29 稽核 W1／W2／W3／W4／d7 合併；A29 作者的線由 hichan-2e 稽核。
- (b) 作廢與付款日覆寫**兩者都只有 superadmin**（使用者裁示）。int1 目前的 `paid_date` 覆寫是 admin+ ＝合併缺口（w2b `eb762b2f` 尚未進 int1，d7 合併中）⇒ **新 int1 SHA 出來後重驗**；若包內仍是 admin+ ＝必修。M-V2 的突變對象依新碼調整。
- (c) A5 `83eb814a` 已在 w4-g2-5b（`13d79ffd`）回退 ⇒ 確認包內**不存在**該檔／該行為（找守門自動探索的 `A5` 相關檔，包內 0 命中）。
- (d) `tools/platform/pre_train_check.py` 是倉庫工具 ⇒ 確認**不在產品包**；P5 的禁入物掃描加這一項，並先在工作樹命中（正對照）。
- (a) 員工帳號 reveal（superadmin／finance／cashier＋稽核）與承攬商裁示不一致：主持向使用者請示中 ⇒ 報告列「待裁示」。
- 取得：包路徑、manifest、預期 SHA、去識別的 DB 複本由主持在出包後提供。


## 9. 新增功能：報價單成案後上傳客戶簽回的報價單（a3 實作；包時程順延至約 18:00）

被稽核者：a3（不是 A29）。**包出來之後**才跑；以下是探針清單（斷言打在伺服器回應、DB 與磁碟，不打畫面文字）。實作位置待 a3 合併後補 檔案:行號（預期在 `modules/case/api/quotations.py` 或其附件模組、`helpers/uploads.py::save_document_files`、`modules/case/attachments.py`）。

### 9.1 狀態閘（只有「成案」之後才能上傳）
- 探針：報價單在 草稿／待審核／簽核中／已退回／已送出（未成案）／已作廢 各打一次上傳 ⇒ 全部被擋（4xx，不是 200 後靜默丟檔）；`dealTag` 為「已成案」放行；「已結案」是否也可補傳——**規格不明，列問題給 a3**。
- 回退：成案後上傳成功，再把成案撤回（deal_tag 改回）⇒ 既有檔的可見性與刪除行為（不消失、不可再傳）。
- 突變 M-S1：拿掉狀態檢查 ⇒ 測試必須紅。

### 9.2 權限矩陣（案件擁有者／協作者／admin／外人／viewer）
| 角色 | 上傳 | 列出／下載 | 刪除 |
|---|---|---|---|
| 案件擁有者（sales_person） | 預期 ✔ | ✔ | ✘（admin+） |
| 協作者（assigned_user_ids） | 規格待確認 | ✔ | ✘ |
| admin | ✔ | ✔ | ✔ |
| superadmin | ✔ | ✔ | ✔ |
| 外人（有報價單模組、但不是該案擁有者） | ✘（404：看不到＝不存在） | ✘ | ✘ |
| viewer（唯讀） | ✘ | 依規格 | ✘ |
- 探針：每格各打一次真端點；外人用**真的有報價單模組但不是該案擁有者**的帳號（admin 直通會遮蔽問題）；`quote_no` 可列舉 ⇒ IDOR：對別人案件的 quote_no 上傳／下載／刪除一律 404（與 `case_owner_readable` 同一結果，audit 記真正原因）。
- 假綠燈檢查：測試是否全用 admin；是否有「非擁有者被擋」的正對照。
- 突變 M-S2：上傳端點略過 `case_owner_readable`／`_guard_case`；M-S3：刪除端點降為「登入即可」。

### 9.3 路徑處理（不可目錄穿越）
- 探針：檔名 `../../x.pdf`、`..\..\x.pdf`、絕對路徑、`C:\x.pdf`、UNC、NTFS 資料流 `a.pdf:evil`、含 NUL／控制字元、超長檔名、保留名（`CON.pdf`）、Unicode 全形點。**實體檔必須落在 `uploads/` 之內**、檔名由伺服器產生（不沿用使用者檔名當路徑）；DB 記的路徑不可由使用者控制。
- 刪除與下載走 `uploads.path_access`／L1 `GET /api/attachments/open`（提供者驗權；DB 列的 `path` 即使被竄改也不可越出 UPLOADS_ROOT——對照 `tests/test_upload_path_guard_2026_10_01.py` 的測試床與反向控制寫法）。
- 突變 M-S4：換回「os.path.join 後直接寫／刪」⇒ 路徑測試必須紅。

### 9.4 檔案類型與大小
- 探針：允許清單內（jpg／png／pdf；是否含 docx／xlsx 看規格）通過；`.exe`／`.html`／`.svg`／`.js`／雙副檔名（`a.pdf.exe`）／偽裝（內容是 exe、副檔名 pdf）／0 byte／剛好上限（20MB）與 +1 byte／多檔一次上傳的總量與檔數上限。
- 魔術數檢查（`w2-upload-magic` 若已在包內）：副檔名與內容不符 ⇒ 擋。回應不洩露伺服器路徑。
- 突變 M-S5：放寬允許清單或移除大小檢查 ⇒ 測試必須紅。

### 9.5 刪除（admin+）
- 探針：擁有者／協作者／viewer 刪 ⇒ 403；admin／superadmin 刪 ⇒ 200，**實體檔與 DB 列一起消失**（或軟刪除並從列表與檔案中心消失，依規格）；刪不存在／別案的 id ⇒ 404；刪除後再下載 ⇒ 404；刪除寫稽核。

### 9.6 檔案中心可見性（own_rule）
- 探針：成案簽回件在檔案中心（`/api/filehub/search`）出現；無案件權限者（含有 `file_center` 模組者）搜不到、`/api/attachments/open` 取不到（404）；有案件權限者搜得到並可預覽；刪除後檔案中心立即消失；分類標籤正確。
- 突變 M-F3：提供者的 `search` 略過可見性 ⇒ 測試必須紅。

### 9.7 稽核紀錄
- 探針：上傳／刪除各寫一筆 `audit_log`（action 名稱、操作者、目標單號、檔名；**不含檔案內容與伺服器絕對路徑**）；權限被擋也要可查；稽核寫入失敗不可造成「上傳成功卻無痕跡」。
- 若有通知（信／站內）：不含客戶資料以外的敏感值。

### 9.8 備份與下游
- 檔案進入 uploads 鏡像備份、每日 JSON 匯出的檔案清單；demo 重置會清掉（`_demo_uploads` 前綴）；舊程式回滾後這些檔與 DB 列不會讓舊版啟動失敗（只增不改）。
- 若新增欄位／表：併入 §4 M1～M4 的冪等與回滾檢查。

### 9.9 待 a3 回覆的規格問題
(1) 已結案是否也可上傳？(2) 協作者可否上傳、viewer 可否列出／下載？(3) 允許類型與大小（預設 jpg／png／pdf、20MB）？(4) 軟刪除或實體刪除？(5) 是否新增欄位／表（是 ⇒ §4 migration 檢查）？(6) 端點檔案:行號。

### 9.10 主持預設答覆（2026-10-01，稽核依此判；程式與此不同＝偏離，逐項列出）
(1) 已結案也可上傳；成案撤回後既有檔保留（不自動刪）。(2) 協作者可上傳；能讀該報價單的人都可列出／下載；沒有該案權限的 viewer 不行。(3) pdf／jpg／png，上限＝`helpers/uploads` 預設 20MB。(4) 實體刪除（檔＋DB 列），admin+，寫稽核（同出貨單簽回附件）。(5) 重用既有附件儲存，不新增表／migration（若新增 ⇒ §4）。(6) a3 回報附 檔案:行號。


### 9.11 更正（主持 2026-10-01，**取代** 9.1／9.5／9.10 中與此衝突之處）
功能**原本就存在**：`POST／DELETE /api/quotations/{quote_no}/signed-files`（int1：`modules/case/api/quotations.py:1373／1397`，資料 `quotations.signed_files_json`，檔案中心分類 `quotation_signed`，儲存走 `helpers/uploads.save_document_files／delete_document_file`）。a3 這一班的改動只有：
(a) 上傳閘＝**已送出以上**（草稿／未送出 ⇒ 400）；(b) 刪除＝**上傳者本人或 admin+**（原本任何能讀的人都能刪）；(c) 每檔記上傳者／時間；(d) 案件頁新增「客戶回簽單」區塊＋成案確認視窗內選擇性上傳。
**基準行為（升級前，探針用來對照）**：上傳端點只有 `_require_user` ＋ `_guard_case`（`case_owner_readable`），任何能讀案件的人可補傳；刪除同樣只有 `_guard_case`；稽核 detail 只記檔案數（無檔名）。

**探針（對 a3 的實作逐條）**
| # | 檢查 | 做法 | 通過條件 |
|---|---|---|---|
| S1 | 狀態閘 | 報價單在 草稿／未送出 各上傳 ⇒ 400（不是 200 後靜默丟、也不是 500）；已送出／待審核／簽核中／已成案／已結案各上傳 ⇒ 201 | 草稿被擋；**已送出階段既有的上傳照常可用**（迴歸，使用者明確要求不可壞） |
| S2 | 閘的邊界 | 已退回？已作廢？（`status` 與 `dealTag` 兩個欄位的組合）各一次；退回成草稿後再傳 | 行為與 a3 宣告的「已送出+」定義一致，並列出實際判準（status／deal_tag）供使用者確認 |
| S3 | 刪除規則 | 上傳者本人刪自己的 ⇒ 200；**同案另一位協作者／擁有者刪別人上傳的 ⇒ 403**；admin／superadmin 刪任何人的 ⇒ 200；viewer ⇒ 403／404 | 規則＝上傳者或 admin+；舊資料（沒有上傳者欄位的歷史檔）誰能刪？＝預期僅 admin+（若 a3 讓「無上傳者＝任何人可刪」＝偏離，必修） |
| S4 | 上傳者欄位可信度 | 用 body／檔名偽造 `uploadedBy` ⇒ 伺服器必須用 session 身分，不吃用戶端值 | 刪除權限判斷用伺服器記的上傳者；改名帳號（display_name 變動）後本人仍可刪（比對 username 不是顯示名） |
| S5 | IDOR | 外人（有報價單模組、非擁有者／協作者）對他人案件 quote_no 上傳／刪除／列出 ⇒ 一律 404；`file_id` 屬於別案的檔 ⇒ 404；刪除端點帶別案 quote_no＋本案 file_id ⇒ 404 | 與 `case_owner_readable` 同一結果；不洩漏檔案是否存在 |
| S6 | 刪除的路徑處理 | 把 `signed_files_json` 某檔的 `path` 竄改成 `../../x`、絕對路徑、`C:\x`、UNC、NTFS 流後呼叫刪除 ⇒ 不可刪到 `uploads/` 之外（對照 `test_upload_path_guard_2026_10_01` 測試床）；刪除只用資料庫列內的 path、不吃請求參數當路徑 | 外面的檔毫髮無傷；DB 列照常移除或明確報錯，但不 500 洩路徑 |
| S7 | 上傳的路徑／類型／大小 | 沿用 §9.3／§9.4（檔名穿越、雙副檔名、偽裝、0B、20MB／+1B、多檔） | 全擋；實體檔在 `uploads/quotations/<單號>/…` 之內、檔名伺服器產生 |
| S8 | 成案確認視窗內上傳 | 成案確認流程中同時上傳：成案失敗（驗證不過／競態）時，檔案是否已寫入（孤兒檔）？上傳失敗時成案是否仍成立或整體回滾？ | 兩者一致：不留孤兒檔、不出現「成案了但使用者以為檔案已存」 |
| S9 | 檔案中心可見性 | `quotation_signed` 分類：有案件權限者搜得到；無案件權限但有 `file_center` 者搜不到、`/api/attachments/open` 取不到（404）；刪除後立即消失；新增的每檔上傳者／時間欄位不洩給無權者 | own_rule 行為不變且不放寬 |
| S10 | 稽核 | 上傳／刪除各一筆 `audit_log`；**被 403／400 擋下的也要有可查紀錄**（至少 403）；detail 含上傳者與檔名、不含伺服器絕對路徑／內容 | 可追到「誰刪了誰上傳的檔」 |
| S11 | 案件頁區塊權限 | 「客戶回簽單」區塊：無權者看不到刪除鈕只是顯示、後端仍須擋（前端隱藏≠權限）；窄螢幕、舊案件（沒有任何回簽檔）顯示正常 | 後端判斷為準；e2e 驗終點狀態（DB／磁碟）＋截圖 |
| S12 | 備份／回滾 | `signed_files_json` 新增欄位（uploader/time）向下相容：舊程式讀新資料不炸、新程式讀舊資料（欄位缺）不炸；每日 JSON 匯出含新欄位 | 兩個方向都不炸 |

**突變**：M-S1 拿掉 400 閘；M-S3 刪除改回只有 `_guard_case`；M-S4 上傳者改吃用戶端值；M-S5 刪除端點用請求參數當路徑；M-S6 狀態閘把「草稿」放行。每個都必須有測試轉紅，否則＝假綠燈（必修）。
**舊測試對照**：`test_*signed*` 既有題的正對照（已送出階段上傳）是否仍在、是否被這班改弱。
