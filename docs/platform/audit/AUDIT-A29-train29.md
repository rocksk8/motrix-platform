# 稽核：第二十九班（包 20261001_212935_47db5613_full，platform 47db5613）（A29＝hichan-c7，2026-10-01）

稽核者獨立性：我不是這一班被審線的作者（W1／W2／W3／W4、a3、d7 的成果）；我寫的線（登入橫幅、承攬商帳號遮蔽、部門跟業務負責人、刪除模組、選單位置、manifest VR3、外包名冊遮蔽更正、e2e 種子修正）**未審**，由 hichan-2e 審。
方法：只做探針、突變、獨立重算、合成資料的升級演練；**沒有**跑全量或 `-n`；作者與建包閘門（not_e2e 7848、e2e 741 全綠）的測試結果採信。探針與腳本存於 `docs/platform/audit/train29-probes/`（非 `test_*` 命名，不被收集）。

## 0. 判定

**PASS（可上正式機），無必修；3 項建議（測試缺口）、2 項觀察、1 項待裁示。**

## 1. 包的驗證（P1–P9）

| # | 結果 | 證據 |
|---|---|---|
| P1 commit／SHA | ✅ | `delivery.json`／`deploy_manifest.json` 的 commit＝`47db561356c6…`＝origin/platform HEAD；kind=full；772 檔；`package.sha256` 檔 SHA256＝`71245f7d7c92bc3778e756826f39b467a32cb40b3f9004b3e1c1fa8b9688c133`（與主持一致） |
| P2 逐檔雜湊 | ✅ | 獨立重算：清單 772、缺 0、雜湊不符 0、磁碟多出未列 0 |
| P3 簽章 | ✅ | Ed25519 以**已安裝版本的公鑰**驗過（`DELIVERY_PUBKEY_PEM` 與正式機 0bb4834e 相同＝新包不能替自己背書）；反向控制：改 `package.sha256` 一個位元組⇒驗章 False、改 `delivery.json` 一個位元組⇒False |
| P4 對 git blob | ✅ | 772 檔 vs `git ls-tree 47db5613`：742 相同、25 僅 CRLF、1 不同＝`backend/version_manifest.json`（`time` 欄投影，歷班皆然）、4 建包產生（deploy_manifest.json、backend/.build_commit、backend/export_ignore.json、backend/modules.lock.json） |
| P5 禁入物 | ✅＋觀察 O1 | tests／.git／*.db／hmac.key／initial_*credentials／_demo_／full_results／金鑰／.env／pyc／backend/uploads／venv＝0 命中。**O1：`tools/platform/pre_train_check.py` 在包內**（主持要求確認不在）。正式機基準包 0bb4834e 本來就整包出貨 `tools/platform/*`，屬同一類既有現象、無祕密；是否改排除由主持定，我評為觀察 |
| P6 範圍 | ✅ | 對正式機基準包：新增 42、移除 0、變更 103；新增檔皆在預期十個區域（支出類型／case 費用單據＋migration／accounting migration＋category_map／payroll 銀行帳號＋migration／subcontract bank_mask／filehub／attachment_search／doc_render／custom_module_delete／前端頁與 js／docs 計畫）；A5 `83eb814a` 在歷史中但已由 `13d79ffd` 回退，`tools/platform/dep_scan.py`、`scope_gate.py` 在 83eb814a^…47db5613 之間淨差為空＝**未生效** |
| P7 版本紀錄 | ✅ | 正式機包 462 筆全部原樣在新包（缺 0、內容改 0）；新增 6 筆（會計、承攬商管理、營運報表、簽核、模組建構器、報價單）每模組恰 1（VR3）；`next` 佔位 0 |
| P8 產生檔 | ✅（採信） | 建包閘門 tests/platform 全綠（含 dep_scan／UNIT-INDEX／test_map／generated_maps 守門）；未另行重產 |
| P9 升級演練 | ✅（合成資料） | 見 §3 |

## 2. 權限探針與突變（R1–R4＋客戶回簽單）

探針全部在包 commit（47db5613 的拋棄式 worktree）上跑，斷言打在 HTTP 回應、DB、磁碟與稽核表。突變＝套一個替換→跑指定測試→`git checkout -- <單檔>` 還原（`a29_mut.py`）。

| 線 | 探針（過） | 突變 | 結果 |
|---|---|---|---|
| R1 員工收款帳號（W3） | 本人完整；無資格者（含沒有財務模組的 admin）一律 404；財務／出納／最高管理者預設遮蔽、`reveal=1` 才完整且**每次寫稽核**；改別人只有最高管理者／財務（出納 404）；歷史與整張稽核表**全文無帳號全碼**；輸入驗證 | M-B1 `may_see_full` 恆 True／M-B2 reveal 不寫稽核／M-B3 `mask_number` 回原值 | 3/3 被 `modules/payroll/tests/test_bank_account_2026_10_01.py` 抓到 |
| R2 類型化支出金額可見性（W2） | 單據 PDF 對非金額可見者 404（回應不含金額）；案件列表對「案件擁有者但非申請人」遮蔽（含明細）；檔案中心搜尋對非金額可見者不列費用單據附件（正對照：申請人／最高管理者搜得到） | M-E1 `_amount_viewer` 恆 True／M-E2 `_mask_row` 保留明細／M-E3 `_caseless_visible` 對 None 改 fail-open／M-F1 附件遮蔽判斷改 False | M-E1、M-E2、M-F1 被抓到；**M-E3 沒被抓到→建議 R-1** |
| R3 作廢＋付款日覆寫（W2；使用者裁示兩者皆僅最高管理者） | 作廢：申請人／出納／admin 皆 403、理由必填 400、草稿 409、重複 409、已付款 409、只寫 1 筆稽核；付款日：申請人不能自登 403、未核准 409、admin 有權看時首次可登、已付款後 admin／申請人改或清皆 403、最高管理者可覆寫且寫 `extra_expense.paid_date_override`；已付款不可作廢。**包內程式為 superadmin-only（`case_extra_expenses.py:617`）＝合併缺口 w2b 已補** | M-V1 作廢角色檢查移除／M-V2 付款日覆寫檢查移除／M-V3 覆寫稽核移除 | 3/3 被抓到（`test_expense_void_2026_10_01`、`test_payreq_2026_09_27`） |
| R4 檔案中心 own_rule | 費用單據附件對非金額可見者隱藏；**舊版**（kind=''）額外支出附件：案件擁有者搜得到、無案件權限者（即使有 file_center）看不到 | M-F1（見上）／M-F2 `extra_expense` 讀取規則改成人人可讀 | M-F1 被抓到；**M-F2 repo 測試全綠＝沒抓到→建議 R-2**（探針能抓到：product 行為正確，缺的是 repo 測試） |
| 客戶回簽單（a3） | 狀態閘：草稿／待審核／簽核中各 400（清單不變、寫 `upload_signed_files_denied` 稽核），**已送出階段上傳照常 201**，實體檔落在 `quotations/<單號>/` 之內、記 `uploaderUsername`；矩陣：協作者／admin 可傳，外人與 viewer 對任何狀態都 404（不洩漏狀態）；刪除：非上傳者（含擁有者）403 並寫 `delete_signed_file_denied`、外人 404、上傳者本人 200 且**實體檔一併刪**、admin 可刪他人、舊檔（無 uploaderUsername）只有 admin+ 刪得掉、不存在 id 404；別案 file_id 404 且不動他案清單；DB 路徑竄改（`../`、`..\`、絕對、`C:`、他案資料夾、NTFS 流）一律 409、uploads 之外的檔毫髮無傷；類型／大小：`.exe`／`.html`／`.svg`／`a.pdf.exe`／>20MB 全擋，檔名穿越被改名留在 uploads 內 | M-S1 狀態閘移除／M-S7 閘放寬含草稿／M-S3 刪除規則還原為任何讀者／M-S5 路徑守門移除／M-S4 上傳者改取顯示名 | M-S1、M-S7、M-S3、M-S5 被抓到；**M-S4 沒被抓到→建議 R-3**（顯示名＝帳號時看不出差別） |

## 3. migration 與升級／回滾演練（合成資料，用應用程式啟動路徑，`a29_drill2.py`）

0bb4834e 啟動建庫（`MOTRIX_CREATE_NEW_DB=1` 僅此段）→塞舊報價單與舊額外支出→47db5613 啟動升級→再啟動一次→0bb4834e 在升級後的庫上啟動：

| 步驟 | 結果 |
|---|---|
| 升級 | accounting 2→3、case 2→3、payroll 2→3；新增物件只有 `expense_categories`、`gl_dimensions`、`user_bank_accounts` 與其索引（`idx_case_extra_exp_doc_code`、`idx_case_extra_exp_kind_status`、`idx_uba_*`）；舊報價單／舊額外支出逐列雜湊相同 |
| 冪等 | 再啟動：schema 雜湊、模組版號、資料雜湊全相同 |
| 完整性 | `integrity_check`＝ok、`foreign_key_check`＝0 列 |
| 回滾相容 | 0bb4834e 在升級後的庫上啟動 `/api/ping` 200、舊資料逐列相同（只增不改、新欄位皆 `NOT NULL DEFAULT`） |
靜態檢視三支 migration：只有 `CREATE … IF NOT EXISTS`／帶存在檢查的 `ADD COLUMN`，無 DROP／DELETE／UPDATE／RENAME，不自行 commit。

## 4. 發現

必修：**無**。

建議（皆為測試缺口，產品行為已由探針證實正確；探針可直接納入 repo 測試）：
- **R-1（M-E3）** `case_extra_expenses._caseless_visible` 對 `user=None` 的 fail-closed 路徑沒有測試；現行呼叫端永遠傳 dict，不可達，屬防禦程式碼。
- **R-2（M-F2）** `modules/case/attachments._READ_RULE["extra_expense"]` 被改成人人可讀時 repo 測試全綠：缺「無案件權限者看不到**舊版**額外支出附件」的測試。探針 `a29_probe_r2.py::test_legacy_extra_expense_attachment_not_visible_to_outsider` 補得上。
- **R-3（M-S4）** 回簽附件的上傳者必須用帳號（`uploaderUsername`）而非顯示名；現行測試的顯示名恰等於帳號，改用顯示名看不出來。補一題「顯示名與帳號不同、且與另一人的顯示名相同」。

觀察：
- **O1** `tools/platform/pre_train_check.py` 隨包出貨（見 P5）。
- **O2** 出納（只有 cashier 模組、非案件相關人）對 `PATCH …/extra-expenses/{id}/dates` 得 404（看不到案件）；端點文件寫「或出納」。出納實際登付款走出納頁／提供者而非此端點，不影響使用者裁示；若出納要用此端點需先有案件讀權。僅提醒文件與實作措詞不一致。

待裁示：
- **D1** 員工收款帳號允許 superadmin／finance／cashier 經稽核 reveal，與承攬商裁示（只有最高管理者完整）不一致；主持已向使用者請示。

## 5. 未覆蓋

- 我作者的線（見檔頭）；W1 表單畫面若未進包（`wip/w1-a2-2` 類型畫面）不審；去識別化 prodroot、時鐘守門、檔案中心 P3 未排入。
- 未跑：全量／`-n`、e2e（採信建包閘門 741 全綠）、M-L1／M-L2（總帳 category_map 突變、migration 去存在檢查突變：靜態檢視已見存在檢查）、真實正式機資料複本演練（改用合成資料）。
- 殘餘風險：W2 自述未做的「稽核／匯出／PDF 的作廢路徑 e2e」我只覆蓋 API 層；PDF 單據對非金額可見者已驗，作廢後的 PDF／匯出內容未驗。
