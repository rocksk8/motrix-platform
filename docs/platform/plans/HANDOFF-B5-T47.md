# 交接：b5 視窗（第 46～47 班）— 2026-10-08

> 作者 b5（對 node-d8 回報的獨立審查／整合視窗）。這份在被 /clear 前寫。標「relayed by node-d8」的使用者裁示，是 node-d8 轉述的，我沒有直接聽到使用者說。

## 1. 我擁有的分支（遠端 heads）
| 分支 | head | 狀態 |
|---|---|---|
| `wip/t47-users-list-privacy` | **a070834c3**（本檔所在） | 內容：①`GET /api/users` 對一般人員不給別人的 email／phone／modules／notificationMuted（自己那列與 admin 照舊）②`GET /api/users/sales-contact?username=`（報價人代理帶入電話／Email，僅四欄，需 quotation 模組）＋quotation-form 改用 ③PO 收款帳號遮罩（清單／我的申請／變更提議只給末四碼，財務與超管完整）＋草稿 PATCH／變更申請「沒帶收款人欄位＝保留」＋銀行＋分行上限 110 ④T48 小項票。**待 05 合進 `train/t47-int`**（base 是 b7695b4e8，合時可能要 rebase；CHANGELOG 的 case `(next)` 標題我每次改程式都會動標題尾巴以通過 changelog_follows_code） |
| `wip/t47-po-vendor-bank` | c5c1ca5ef | 已在 `train/t47-int`（PO 表單收款帳戶；後端 `_check_payee_bank`；測試 API 13＋e2e 3）。其後續修補在 users-list-privacy 分支（上列③） |
| `wip/t47-full-account-strict` | 5775c7f6d | 已 squash 進 `train/t47-int`（b7695b4e8）。`case` 提供者 `FULL_ACCOUNT_STRICT=True`：先稽核才給帳號、no-store；**可見的人沒變**（端點本來就 `_can_pay`＝財務角色＋超管） |
| `wip/t47-train-preflight` | **284e4ba04**（含 dd53b0aae 的 measure 資料） | 列車預檢工具＋文件＋測試（見 §4）。已隨 `train/t47-int` 的 squash 合入（train 上多一個修補 commit 83e15057a，內容已回灌本分支） |
| `wip/t47-template-fix` | 41763b345 | `TEMPLATE-apply.md` 步驟 3 #9 只准檢查會部署的程式檔，不檢查 `docs\platform`（已在 `train/t47-int`） |
| `wip/t47-payslip-dispatch-e2e` | acc26fa87 | audit-log 篩選補勞報單動作、派發頁勞報單區塊 403 UX（無相關模組者不送請求）、viewer e2e（已在 `train/t47-int`） |
| `wip/t46-r2-design` | 2d9fdb69a | R2 第 2–4 步設計稿（`docs/platform/R2-STEPS-2-4-DESIGN.md`，第 7 節標了使用者裁示）。第 2 步實作是 ab 的 `wip/t48-r2-step2`（我審過，無 must-fix） |
| `wip/t46-payslip-impl-r1` | 769476fa2 | 第 46 班勞報單簽核（已上線，不再動） |
| `wip/t46-fix-pr-remark` | 444003275 | 第 46 班第二輪（S1 費用歸屬單位／S2 PO 不退回申請人帳戶／S6 resync 不建空庫）（已上線） |
| `train/t47-int` | 由 05 持續推進（我建的部分：570c54fa1 上的 6 個 squash＋修補 83e15057a＋full-account-strict b7695b4e8） | **我不再是整合者**；paydate-l1 與之後的合併由 05 做 |

## 2. 我倚賴的使用者裁示（**relayed by node-d8**）
- PO 廠商銀行資料＝選項 A（逐張採購單填）；Q2「擋付款」**不在第 47 班**（A 上線後另案，只對新單）；Q3 不強制「已告知」勾選，只放提醒文字。
- 完整帳號只給財務角色＋最高管理者，與叫料匯款同規則（我查實：端點本來就如此，沒有可見度變動）。
- `GET /api/users`：**只收緊敏感欄位**（email／phone／modules／notificationMuted），不做 `/selectable` 遷移；自己那列照舊；admin／superadmin 完整。報價人代理的電話／Email 不可退化成空白 ⇒ 加 `sales-contact`。
- R2 步驟 2–4 設計題 Q1–Q7 全採我的建議（拒絕＋旗標、保留 duty-roles 頁、既有使用者不預填模板、重新啟用＝全空、先列現有停用帳號清單再決定、月提醒延到第 5 步、一般角色固定文字/財務三鍵角色人工填原因）。
- 勞報單：送審限真正的最高管理者；Q0＝匯出不需付款日；代理人規則不變。
- 報價日期：維持現狀（不改）。
- paydate-l1 延到第 47 班（05 負責），最後合。

## 3. 未結事項／小項（不在第 47 班修）
- `docs/platform/plans/T48-SMALL-ITEMS.md`：supplier-log.html 一般角色 JS 例外（未改動的基底就有）；`duty_roles._write_audit` 沒用 `_derive_fields`；users 清單 `hasAccess()` 對空 modules 的樣板回退（R2 第 3 步前要改）；R2 第 2 步 PUT 失敗後解除扣項已生效的提示。
- `GET /api/users` 以外：無。PO bank 風險已在 `PO-VENDOR-BANK-GAP-T47.md` 更正。
- 5 個審查問題我回報過、已由對應分支處理：第 46 班 S1/S2/S6、PO 帳號外洩（本分支上列③）。

## 4. 預檢工具（`tools/platform/train_preflight.py`，設計 `docs/platform/TRAIN-PREFLIGHT-T47.md`）
- 用法：`python tools/platform/train_preflight.py [--base origin/platform] [--static-only] [--no-impacted] [--full-cheap] [--budget-min N] [--dry-run]`；`measure --workers 2` 只在機器閒置時跑（約 60 分，更新 `tools/platform/preflight_seconds.json`）。
- 結束碼：0 綠／1 有紅／2 工具出錯／3 超過預算未完成。
- A 層（靜態，約 1 分）：A0 產生檔過期（呼叫 `regen_all.run`）、A1 CHANGELOG `(next)` 位置／遞減、A2 IP 登記表、A3 bottom_layer global_tests、A4 新單據類型 vs approval_flow_scope 表、A5 新 BEGIN、A6 golden（樣式 golden 只在動 CSS／被選 class 時旗標）、A7 寫死 `--expect-db-version`、A8 變動測試裡裸 `get_db()`。
- B 層預設窄版（固定清單＋全域訊號＋tests/platform 掃描型；量測 ≥30 秒的排除）≈136 檔／620 worker-秒；`--full-cheap` ≈800 檔。實測資料（2026-10-08，-n 2）：921 個非 e2e 測試檔共約 6920 worker-秒，<10 秒的 741 個檔（約 2117 worker-秒）。
- 教訓：預檢自己也要過 `test_no_window_guard`（子行程要 `creationflags`）與 `test_page_paths_centralized`（不可寫死 `frontend/pages`）——寫工具後先跑真的守門，不要只跑自己的測試。

## 5. 保留的工作樹（只刪我自己的、用完整路徑）
- `D:\開發測試檔\b5-t47int`（`train/t47-int` 的本機整合樹；05 已接手，可刪）
- `D:\開發測試檔\b5-ulp`（本分支 `wip/t47-users-list-privacy`）
- 沒有殘留的 `%TEMP%\pt_b5_*`（每次用完以完整路徑刪）。

## 6. 踩過的坑（下個人省時間）
- **CHANGELOG 守門**：`test_module_changelog_follows_code` 看的是「程式改動之後有沒有新的版號條目」，**只在既有 `(next)` 區塊加條列不算**——要動 `(next)` **標題行**（尾巴加一段）才會被認作更新。一班一個模組只有一個 `(next)` 區塊。
- **pydantic v2**：對 body 賦值（`body.x = ...`）會把欄位加進 `model_fields_set`，之後用它判斷「有沒有帶」會被騙；賦值前先判斷是否本來就有帶。
- **Python `\d`** 會放行全形數字，驗帳號用 `[0-9]`。
- **heredoc 寫含 `\n` 的 Python 字串**會被 bash 層吃掉反斜線；改用 Write 工具寫腳本檔再執行。
- **列表長命令列**：1000+ 個檔名會爆 Windows 命令列（WinError 206），傳目錄。
- **出納端點**：`payee-bank` 由 `_can_pay`（＝`has_cashier_access`：財務角色＋超管）把關；沒有出納權限的 admin 是 403——不要憑印象說「admin 看得到完整帳號」。
- **e2e**：非超管看不到案件列表以外的案件（把案件 `sales_person` 設成測試帳號才點得到）；無案件費用單需要 `expense_forms` 模組或 admin。
- 工作樹／分支／暫存：測試用 `--basetemp %LOCALAPPDATA%\Temp\pt_b5_<用途>`，用完刪完整路徑；不要用萬用字元刪（hook 會擋）。
- 共用樹 `D:\MOTRIX-PLATFORM` 只讀（`git -C` 取資訊、建 worktree）；絕不在裡面寫檔。
