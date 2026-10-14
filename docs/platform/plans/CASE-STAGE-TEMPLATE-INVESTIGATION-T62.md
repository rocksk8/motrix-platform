# 案件執行階段樣板：現況調查與設計筆記（盤點 #26；T62，hichan-1f；基底 train/t60-int 9200a0b81；只讀原碼、無執行）

## 0. 結論先講

1. **今天沒有「階段樣板」**：沒有預設階段名稱、沒有預設工期、沒有預設順序。階段完全是**每案手動新增**（前端 `case-management-exec.js:565 addStage()` 送 `POST …/stages {label:'新階段'}`；`quotation-form.html:4066` 同款）。盤點 #26 要的是「新增」一個概念，不是「把寫死的清單搬到設定」。
2. **階段沒有穩定鍵**：身分只有每案自增整數 `case_stages.id`＋自由文字 `label`。所以跨案無法依「階段種類」分組（報表、逾期統計、儀表板都只能數個數）；樣板必須先補上 `stage_key`（種類鍵），否則改名就會斷。
3. **階段牽動金流**：`case_stages.ratio_bp`（階段收入比例，基點；NULL＝未設、0＝不認列）決定權責口徑的**收入認列月份與比例**（`recognition.py:81-136`）。樣板若預帶比例，等於預帶認列規則 ⇒ 必須走治理（放寬／收緊分類），且不得改動認列公式。
4. **「進度」關卡以階段數為分母**（`_gates_from_facts`，`quotations.py:2310` 起）：樣板讓某類案件少了一個必經階段，就是讓結案關卡變容易 ⇒ 屬放寬。
5. 建議：**樣板＝套用時複製（凍結），不是即時連動**；既有案件不受樣板之後的修改影響。

## 1. 資料與程式現況（file:line 以 9200a0b81 為準）

### 1.1 儲存
| 項目 | 位置 | 備註 |
|---|---|---|
| 階段表 | `db.py:1727 _m051_case_stages_normalize`：`case_stages(id, quote_no, label, sort_order, done, done_at, start_date, due_date, assigned_to JSON, depends_on JSON, created_at, updated_at, google_calendar_event_id)`；後補欄位 `daily_task_id`、`google_calendar_done_event_id`、`ratio_bp`（`db.py:4496-4506`） | 現在表是**權威**；`quotations.data_json.caseRecord.stages` 是鏡像（`_sync_stages_to_json` `quotations.py:3532`、`_sync_json_stages_to_table` `:3597`：整包存檔時雙向收斂） |
| 到訪紀錄 | `case_stage_visits(stage_id → case_stages ON DELETE CASCADE, visit_date, visit_people, note)` | 隨階段走 |
| 沒有的 | `stage_key`／`template_key`／預設工期欄位／階段類別 | 要加（見 §3） |

### 1.2 編輯者與端點（都在 `modules/case/api/quotations.py`）
`POST /api/quotations/{no}/stages`（:3717，只收 `label`，其餘欄位空）、`PUT …/stages/{id}`（:3746，label／done／doneAt／startDate／dueDate／ratioBp，各欄獨立、不自動填日期）、`DELETE`（:3800）、`PATCH …/stages/reorder`（:3841，`orderedIds`）、負責人 `POST/DELETE …/assignees`（:3865/:3893）、前置階段 `POST …/depends-on/{id}`（:3916，DFS 防環）、到訪 `…/visits`（:3949-4006）。權限＝`_guard_case(allow_module="case_manage")`；已結案鎖定時 `_deny_if_case_locked_unsupported` 擋下。所以**誰能編**＝有案件管理權限的人，每案各自編。

### 1.3 消費者（改階段會牽動誰）
| 消費者 | 位置 | 依賴什麼 |
|---|---|---|
| 結案關卡「進度」 | `quotations.py:2258 _close_gate_facts`＋`:2310 _gates_from_facts`：`done < total` 就擋；0 階段＝N/A；通知信 `notify_case_close_blocked`（`email_notify.py:1604`） | 階段**數量** |
| 案件清單欄位 | `quotations.py:839-850`（`stage_total/stage_done/stage_overdue` 相關子查詢）、`:1249-1274`（`stageOverdue/nextDue/nextDueLabel`）、`:6628-6663`（匯出 `done/total`、逾期） | 數量、`due_date < today AND done=0`（`_CASE_STAGE_OVERDUE_SQL` `:769`）、第一個未完成階段的 label |
| 快速篩選「逾期階段」 | `quotations.py:889/:893/:946`；前端 `case-management-list.js:67-101,141,165-168` | 同上 |
| 跨案看板／甘特 | `GET /api/quotations/stage-board`（:997）；`case-management.html:39,906`（frappe-gantt）；`dependsOn`（:1094） | label、起訖日、前置階段 |
| 到期提醒 | `case_deadlines.py:41 _check_case_stage_deadline`：只看 `deal_tag='已成案' AND done=0 AND due_date ∈ {今天+3, 今天}`；去重鍵 `casestage_notif.<案>.<階段id>.<人>.<3d|deadline>`；負責人空 ⇒ 業務；另通知部門主管；信件 `notify_case_stage_deadline(_manager)`（`email_notify.py:1382/1425`） | **提醒視窗 3 天／當天寫死**；階段 id 當去重鍵 |
| 行事曆 | `google_calendar.py:237-238`（`stage_due`、`stage_done` 兩種事件，可在設定關）、`:633 push_event_for_case_stage_due`、`:709 …_done`；案件階段欄位 `google_calendar_event_id` | 階段 label、日期 |
| 每日工作事項鏡射 | `case_stage_tasks.py`（勾選完成 ⇒ 建立已完成的 `daily_tasks`，`daily_task_id` 記回階段） | label、完成日、負責人 |
| 權責認列 | `recognition.py:81-136`：`成交未稅 × ratio_bp`，認列在階段完成月；未設比例 ⇒ 全部階段完成月一次認列；合計≠100% ⇒ 照比例、標註（`stage_ratio_unset／_not_100／case_incomplete`） | **`ratio_bp`、done_at**（金流） |
| 獎金 | `payroll/bonus.py:232-291`、`payroll/api/bonus.py:865,1103-1140`：專案執行獎金的收款人來源＝`case_stages.assigned_to` | 負責人（不看 label） |
| 結案報表 PDF | `pdf_gen.py:2554-2560, 3063-3065`：階段列＋到訪起訖 | label、日期、到訪 |
| 回收桶／封存 | `recycle_adapter.py:285,352-395`（刪案件連階段快照）、`archive.py`、`core/migrations.py:580` | 整列 |
| 內建畫面自訂欄位 | `helpers/builtin_fields.py:36`（清單裡有 `stages` 這個分頁） | — |

### 1.4 現況的缺口（樣板要補的）
- 沒有「階段種類」⇒ 報表無法回答「所有案件的『驗收』階段平均逾期幾天」。
- 日期全手填；**沒有工期／相對日期**。
- 提醒視窗（3 天、當天）寫死；不是階段樣板的一部分，但常被一起問到（見 §4 Q4）。
- 比例（`ratio_bp`）每案手填，沒有預設；合計不是 100% 只做標註。

## 2. 設計：受治理的「階段樣板」定義

### 2.1 定義物（沿用定義文件庫＋治理管線；新 kind `case_stage_template`，key＝樣板鍵，scope＝company，旗標關著不登記）
```
{ "version": 1, "label": "標準施工案", "stages": [
   {"key": "survey",  "label": "現場勘查", "offsetDays": 0,  "durationDays": 3,  "ratioBp": null, "dependsOn": []},
   {"key": "install", "label": "設備安裝", "offsetDays": 3,  "durationDays": 14, "ratioBp": 7000, "dependsOn": ["survey"]},
   {"key": "accept",  "label": "驗收",     "offsetDays": 17, "durationDays": 2,  "ratioBp": 3000, "dependsOn": ["install"]} ] }
```
- `key`：階段種類鍵（小寫英數底線，樣板內唯一；**建立後不可改**，只改 label）。
- `label`：顯示名（純文字；禁標記／隱形字元／官方狀態字樣——與通知用語同一套 allowlist）。
- `offsetDays`／`durationDays`：從『套用基準日』推出 `start_date`／`due_date`（基準日＝成案日或使用者指定；週末不特殊處理，v1 只加天數）。
- `ratioBp`（選填）：**建議值**，套用時寫進 `case_stages.ratio_bp`；**認列公式與標註規則完全不動**。
- `dependsOn`：以 `key` 表示，套用時換成該案實際的階段 id，防環檢查沿用。
- 不放：負責人（每案不同；可選填『角色』留待第二期）、完成狀態、到訪。

### 2.2 套用方式與對既有案件的影響（**凍結，不即時連動**）
- 套用＝複製：案件頁新按鈕「套用階段樣板」（只在該案**沒有任何階段**或使用者明確選『附加』時可按）⇒ 伺服端 `POST /api/quotations/{no}/stages/apply-template {template, baseDate, mode}` 逐筆走既有的 `create_case_stage` 規則（權限、鎖定、稽核、行事曆／到期提醒掛鉤照舊），不開新寫入路徑。
- 每個階段多記 `stage_key`（可空）與案件上的 `stage_template`／`stage_template_version`（可空）。**舊案件這些欄位都是 NULL，行為完全不變**。
- 樣板之後被修改／停用：**已套用的案件不動**；案件頁可顯示『樣板已有新版』與差異，由使用者**明確**按「補上缺少的階段」（只加不改、不刪、不碰已完成階段）。
- 為什麼不即時連動：階段已是每案的權威資料（完成日、負責人、行事曆事件、每日任務、認列月份、獎金）；即時連動會讓『改一個樣板』改動幾十個案件的財務與提醒。

### 2.3 治理分類（`def_pipeline` 比較函式）
| 變更 | 分類 | 理由 |
|---|---|---|
| 新增階段（無比例） | 收緊 | 新案件結案要多完成一項 |
| 移除階段 | **放寬** | 新案件結案關卡變容易；權責比例分母變 |
| 改 `label`／`durationDays`／`offsetDays`／順序 | 中性 | 純顯示與日期建議 |
| 新增或更改 `ratioBp` | **放寬** | 影響收入認列月份與比例（金流）；需第二位核准 |
| 改 `key` | 不允許（驗證擋） | 種類鍵永久 |
| `dependsOn` 變動 | 中性（驗證防環） | |
驗證：`ratioBp` 若有任何階段設定，**合計必須 = 10000**（否則存不了；今天每案手填時才是標註，樣板層級就不讓它不完整）；階段數 1–30；`key`／`label` 規則同上；工期 0–730。

### 2.4 對消費者的影響（全部**不改**，只靠新欄位增能）
關卡、清單、看板、提醒、行事曆、每日任務、認列、獎金、PDF、回收桶——都讀 `case_stages` 原欄位，樣板只是『新增階段時預填』，所以沒有消費者要改。新欄位 `stage_key` 的唯一用途：未來報表可依種類分組（第二期）；回收桶快照整列帶走（`recycle_adapter` 用 SELECT *，需確認欄位白名單）。
**提醒視窗（3 天／當天）**不放進樣板；若要開放，另開設定群組（`case_stage_deadlines`：提醒提前天數 0–14、可多值），並保留去重鍵格式。

### 2.5 實作切片（建議）
1. **S-ST1**（M，低風險）：加 `stage_key`／`stage_template`（migration，NULL 預設）＋ kind `case_stage_template`＋驗證＋比較函式＋預覽（顯示『套用後會建立的階段與日期』，樣本基準日）＋旗標 `builder_stage_templates`（預設關）。
2. **S-ST2**（M）：`apply-template` 端點＋案件頁按鈕（兩段確認，不用原生對話框）＋『補上缺少的階段』。
3. **S-ST3**（L，之後）：編輯器（階段列表編輯、拖曳排序、依賴選單、比例合計即時檢查）、報表依 `stage_key` 分組。

## 3. 風險
- `ratio_bp` 預填是本案唯一的金流點：務必保持『建議值、可逐案覆寫、公式不變』，且樣板層級合計=100% 才可發布。
- `_sync_json_stages_to_table`（整包存檔收斂）要確認新欄位 `stage_key` 不會被舊前端整包存檔洗掉（舊前端不帶該欄 ⇒ 原地 UPDATE 時**不可覆寫為空**；實作時加守門題）。
- 去重鍵用階段 id：套用樣板新建階段不會與舊鍵衝突。
- 已結案鎖定、案件回收桶、封存：套用端點必須沿用 `_deny_if_case_locked_unsupported`。

## 4. 請 PM 裁示
1. 是否接受『凍結複製、舊案不動、需要時手動補階段』（建議：是）？
2. `ratioBp` 要不要放進樣板 v1（建議：放，但發布時合計=100%＋視為放寬）？
3. `offsetDays` 是否需要排除週末（建議：v1 不排除）？
4. 到期提醒視窗（3 天／當天）要不要一起做成設定（建議：另案）？
5. 階段『負責人角色』要不要列入第二期（建議：是）？

## 5. 給使用者的五個問題（白話版；每題附建議答案）

1. **樣板改了之後，已經建好的案件要不要跟著變？**
   建議：**不要**。樣板只在「套用」的那一刻把階段複製進案件；之後樣板怎麼改，舊案件都不動。需要時，案件頁有一顆「補上缺少的階段」按鈕，由您自己決定要不要補。
2. **樣板裡要不要可以預先填「每個階段占多少收入」？**
   建議：**要，但當成建議值**。這個比例會影響營運報表把收入算在哪個月，所以：只要有一個階段填了，每個階段都要填，合計一定要剛好 100%；而且新增或更改比例要第二位最高管理者核准。案件仍可逐案改，計算規則完全不動。
3. **階段的日期，要不要排除週末？**
   建議：**先不要**。樣板只寫「第幾天開始、做幾天」，直接用日曆天推算；之後真的需要，再加上排除週末的選項。
4. **「到期前 3 天、當天」的提醒要不要一起開放調整？**
   建議：**另外做**，不放進樣板。這是整個系統共用的提醒時間，和「哪些階段」是兩件事，混在一起會讓樣板的核准意義不清。
5. **階段的負責人要不要也能寫在樣板裡（例如「施工主管」）？**
   建議：**第二期再做**。第一期樣板只管階段本身，負責人仍照現在方式在案件上指派。

## 6. 實作狀態（S-ST1，2026-10-14）
已完成純函式部分（程式碼，未接任何執行路徑）：`helpers/stage_templates.py`（定義、驗證、旗標、功能狀態閘門）、`helpers/safe_text.py`（共用文字檢查）、`def_pipeline._cmp_stage_template`（依階段種類鍵配對的放寬／收緊分類）、`def_governance` 影響範圍白話、`definitions` 惰性登記、設定群組 `builder_stage_templates`（預設關）。**沒有**套用端點、migration、案件頁按鈕（S-ST2）。3c 的審閱意見到達後再修訂本文件。

## 7. 審閱後的修正（04，S-ST1 r3）
- 鍵（樣板鍵、階段種類鍵）一律 `fullmatch`：Python 的 `$` 會在結尾換行前比對成功，「a
」會被當成合法的鍵並與「a」並存。`core/definitions.py` 的通用 `_KEY_RE` 有同樣的寫法（既有，不在本刀處理；之後可一併改成 `fullmatch`）。
- 階段名稱重複以 NFKC＋casefold 比較（「ＡＢ」與「AB」算同一個）。`version` 必須是整數 1（1.0、true 一律拒絕）。
- 惰性登記的 kind 登記後到重啟前都會留在 `D.kinds()`；`GET /api/definition-kinds` 在旗標關時把「案件階段樣板」濾掉（只有最高管理者看得到這個端點，這是避免旗標關了還列出一個用不了的種類）。
- 階段名稱的字元規則會擋「像網址」的寫法（含斜線，或英數字夾小數點，例如 `Phase 1.20`）；已寫進設定說明。
