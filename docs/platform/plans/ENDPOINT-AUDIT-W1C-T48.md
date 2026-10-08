# 端點稽核 W1c（第 48 班後）— 核心 routers／crm／daily_tasks／filehub／lodging／netplan／tender_radar＋全站交叉檢查

作者：hichan-1d（2026-10-09）。基底 `origin/platform` 4012847ab（48a 已上線）。分支 `wip/t48-w1c-fixes`（3 個修正，各 1 commit，各附測試與 CHANGELOG `(next)`）。

## 方法（可重跑）
1. **路由表取自執行中的 app**（TestClient；FastAPI 0.141 的 `_IncludedRouter.effective_route_contexts()` 攤平）：**806 條路由**（核心 `routers/` 235、各模組 571；另 `helpers/xlsx_out.py` 匯出包裝 18、`main.py` 4）。每條記路徑、方法、實際端點函式與檔案行號、原始碼。
2. **靜態對照**：每個檔案的 `@router.<方法>` 裝飾器數 vs 執行期路由數——逐檔相符（差異只來自 `export_logged` 包裝器把函式歸到 `helpers/xlsx_out.py`），**沒有「寫了裝飾器卻沒掛上」的路由檔**。
3. **前端 → API**：掃 `frontend/**/*.html|js` 的 `/api/…` 字串與樣板（含 `${API}`、`${qs}` 尾巴、動態動作後綴），1011 處呼叫逐一對路由表。
4. **路由 → 呼叫者**：每條路由要有前端呼叫，或測試／工具／腳本的路徑字串（以含正對照的正規式比對，假路由會被標出）。
5. 重複註冊／被前面參數路由遮蔽、`module.json` `api_prefixes`／probes／頁面檔、auth 守門樣式、寫入端點稽核。

## 結論一覽
| 項目 | 結果 |
|---|---|
| 無需登入的路由 | 15 條，全部是設計上公開：`/api/ping`、`/api/system/version`、`/api/system/deployed-version`、`/api/auth/login`＋`/totp`＋`/login/qr-*`（3）、`/api/now`、`/api/system/webauthn-config-status`、`/api/system/branding/{kind}`、`/pages/*`、`/map-overlays/*`、`/static/sidebar.js`、`/`。`/api/system/branding`（公司名稱）統編只在帶有效登入時回傳。沒有發現漏守門。 |
| 重複註冊／遮蔽 | 0 |
| 前端呼叫找不到路由 | **0**（初掃的 4 筆是 `${path}`／`${action}` 動態後綴，逐個確認落在現有路由：dispatch `submit/withdraw/status/completion/*`、material-payments `submit/withdraw/void`、`payment/{idx}/…-writeoff`） |
| 沒有任何呼叫者（前端＋測試＋工具）的路由 | **0**（正對照：塞進一條假路由會被標出） |
| 寫入端點沒有稽核 | 守門只覆蓋 `routers/*.py` 與 `api.py`／`api/`：**漏掉 `modules/lodging/api_records.py`（2 條寫入端點）** → 已修（F1） |
| 布林旗標型別 | `bool(body.get(...))` 把字串 `"false"` 當 true：tender_radar 已修（F2）；其他模組見提案 P2 |
| 工作日誌 POST/PUT 型別 | 壞值 500／寫進壞資料 → 已修（F3） |

## 已修（分支 wip/t48-w1c-fixes）
- **F1 `d85d4b497` lodging 補稽核＋守門補洞**：`POST /api/lodging/records`、`POST /api/lodging/quotes`（人工詢價是「永久保存的使用者資料」）成功時沒寫稽核——「寫入端點必須稽核」守門（`test_write_endpoints_are_audited`）只掃 `routers/` 與 `api.py`／`api/`，不掃 `api_records.py`。補 `lodging_record_create`／`lodging_quote_create`（不記中心點地址〔IP-97〕、不記金額）；守門改為納入模組內任何有 `@router` 的檔，`/api/lodging/search` 列 EXEMPT（純查詢），另加「沒有端點檔逃出掃描」一題（已知例外僅 `helpers/xlsx_out.py`、`main.py`）。突變檢查：拿掉修正 ⇒ 守門紅。
- **F2 `b1e3aa6b2` tender_radar 布林嚴格解析**：`PUT /api/tender-radar/schedule` 的 `confirmHighFrequency`、`POST/PUT /watches` 的 `enabled`。字串 `"false"`／`"0"` 原本會被當 true（⇒ 悄悄通過『頻繁時段需確認』的 409 關卡）。現在只收 true/false/0/1，其餘 422 且設定不變。前端本來就送布林。
- **F3 `f35638910` 工作日誌 POST/PUT 型別與範圍檢查**（L1 `routers/system.py`）：`hours` 非數字／負／>1000、`content` 非字串或空白、`log_date` 非 YYYY-MM-DD、`user_id` 不存在、`case_no`／`contact_type` 非字串 ⇒ 4xx（原本 `float("abc")`／`.strip()` 打在非字串 = 500，PUT 更是原樣寫庫）。權限、正常值、既有 400 行為不變。core CHANGELOG `(next)`。突變檢查：還原 ⇒ 新測試紅。

驗證（單 worker，.venv312）：寫入端點稽核守門 11 過；lodging 紀錄 45 過；tender_radar schedule 27 過；work-log 驗證＋case_project_merge 10 過；上傳／附件相關 121 過；`test_changelog_sections`／`test_module_changelog_follows_code`／`test_version_slots`／`test_generated_maps` 綠。**未跑全量閘門**（列車做）。

## 提案（不改，等裁示或交給對應模組負責人）
- **P1（netplan，權限語意）** `GET /api/network-plans`、`GET /api/network-plans/{id}` 只要 `netplan`／`netplan_edit`／`case_manage` 任一模組即可讀**所有**規劃書（含綁定案件者的聯絡人電話／現場資料），沒有套 `case.access` 逐案守門；同模組的 `GET /api/quotations/{quote_no}/network-plan` 卻有 `ca.guard`。同一份資料兩條讀法規則不同。建議：有 `quote_no` 的規劃書改走逐案守門（列表過濾）。需使用者裁示（涉及誰看得到）。
- **P2（跨模組，bool 解析）** 同型 `bool(body.get(flag))`：`ledger_closing.py:69,84`（`accept_warnings`：字串 `"false"` = 接受警告！）、`ledger_periods.py:129`、`ledger_settings.py:119`（開關總帳功能）、`vouchers.py:920`（reopen）、`ledger_category_map.py:54`、`contractor_vouchers.py:991`（`remit_require_payslip` **緊急關閉開關**）、`quotations.py:5397`、`material_approvals/changes/payments` 的 `cascade`。前端送真布林所以平時無事；API 直打或舊用戶端會繞過關卡。建議在 L1 加一個共用嚴格解析（新增型介面，向下相容）後各模組改用；accounting／subcontract／case 屬 05／b5 範圍，我沒碰。
- **P3（型別驗證）** 寫入端點用裸 `body: dict` 共 **203 條**（routers 44、case 43、payroll 31、accounting 30、subcontract 19、supply 11、arap 10、netplan 7、lodging 3、tender_radar 3、xlsx_out 2）；手寫 `(body.get("x") or "").strip()` 遇到非字串 = 500。F3 示範了一種作法；系統性解法是 pydantic 模型（會改 OpenAPI／route golden，建議逐模組做）。
- **P4（api_prefixes 覆蓋）** 影響只有「demo 庫該模組升級未完成時回清楚的 404」：`/api/expense-categories`（`accounting/api/ledger_category_map.py:107`）不在 accounting 任何前綴下；`/api/quotations/{quote_no}/network-plan`（netplan）落在 case 的 `/api/quotations` 前綴；accounting 的 `/api/reports/t100-export/*` 落在 analytics／arap 的 `/api/reports` 前綴。無資料風險；加前綴要同改 `docs/platform/modules.json`。
- **P5（work-log 權限）** `GET /api/work-logs` 要 `work_log`／`case_manage` 模組，但 `POST／PUT／DELETE` 只要登入（PUT／DELETE 另限本人或 admin+）；`POST` 可替任何 `user_id` 建立（畫面上是「出勤人員」下拉，看似設計），PUT 非 admin 的本人可把 `user_id` 改成別人。是否要補模組檢查／限制改 `user_id` 需裁示。
- **P6** `module.json` 的 `provides`（api_prefixes／probes）與 `docs/platform/modules.json` 登記、頁面檔皆一致（14 個模組逐一比對；唯一差異即 P4）。crm／daily_tasks／filehub／lodging／netplan／tender_radar 的 `permissions` 與程式內使用的模組鍵一致（crm `dev_crm` 走 `_require_user` 已解析的生效權限清單，職責角色／扣項有效）。

## 沒動、也不建議動
`/api/auth/login/qr-approve` 等公開登入流程（另有防暴力與挑戰逾時）；`/api/definitions`、`custom_records` 的預覽／驗證 POST（EXEMPT 原因屬實）；filehub 搜尋（各提供者套原單據讀取規則，看不到的不列也不計數）。
