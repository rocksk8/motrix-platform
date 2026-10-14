# 舊分頁存檔會不會刪除／蓋掉別人的階段：路徑分析與建議（S-ST4 前置；只有文件，沒有程式變更）

作者：hichan-3c；基底 wip/t62-stage-template-r4 0faec418c（套用階段樣板 S-ST2 審查 N4 的追查）。**結論先講：疑慮的「案件頁整包存檔」其實已經碰不到階段；真正剩下的只有一條路（報價單表單的整包存檔），而且它已經有樂觀鎖。建議用最小改動把這一條也關掉，不動案件頁的存檔路徑。**

## 1. 哪些路徑會依「用戶端手上的階段」寫入 `case_stages`

| # | 路徑 | 送什麼 | 對階段的影響 |
|---|---|---|---|
| 1 | 案件頁 `saveCaseRecord()` → `PATCH /api/quotations/{no}/case-record`（`case-management-core.js:763`） | `{segments, base, defaults}`：只送「改到的 caseRecord 頂層鍵」與基準；**沒有 `stages`、沒有 `_expectedUpdatedAt`** | **碰不到**。伺服端 `update_case_record` 明寫 `segments = {k: v … if k != "stages"}`（quotations.py ~3181），`defaults` 也跳過 `stages`；舊的整包格式也一律 `new_case_record["stages"] = 伺服器現有值`（~3330、~3456，2026-08-24 起「忽略 client 送來的 stages」）。 |
| 2 | 報價單表單 `apiSave()` → `PUT /api/quotations/{no}`（`update_quotation`，quotations.py ~2151） | 整張報價單 JSON，含表單載入時帶進來的 `caseRecord.stages`（表單**沒有任何階段編輯畫面**，只在 `_seedDefaultStagesIfEmpty` 時 push 新階段） | **會**：`isinstance(cr.get("stages"), list)` 就呼叫 `_sync_json_stages_to_table`：id 在表內 ⇒ 原地 UPDATE（label／done／done_at／日期／負責人）；id 不在表內 ⇒ **INSERT 成新階段（已被別人刪掉的會復活）**；表內有、陣列沒有 ⇒ **DELETE（`gone_id`，連到訪紀錄一起）**。註解說「與 update_case_record 完全比照」，但 update_case_record 早在 2026-08-24 改成忽略 client stages，這裡是**唯一漏改的殘留**。 |
| 3 | `POST /api/quotations`（`create_quotation`，~1750） | 新單 | 新單號，表內沒有舊階段，不是舊分頁問題。 |
| 4 | 階段細部端點：新增／`PUT`／`DELETE`／`reorder`／負責人／前置階段／到訪／（新）套用樣板 | 以階段 id 為單位 | 只動指名的那一列；`reorder` 只改清單裡列出的 id 的 `sort_order`（舊分頁的清單少了新階段 ⇒ 新階段排序不變，不會刪）；`DELETE` 是使用者明確動作。**舊分頁不會因這些路徑誤刪別人的階段。** |
| 5 | `_seedDefaultStagesIfEmpty()`（`case-management-core.js:498`、`quotation-form.html:4094`） | 載入時發現「0 個階段」就 `POST` 5 個預設階段 | **會重複**：分頁 B 在別人套用樣板「之前」載入（看到 0 階段）、套用之後才執行 seed ⇒ 5 個預設階段疊在樣板階段上。窗口很小（seed 在載入流程裡立刻跑），但**更大的問題是產品行為**，見 §5。 |

### 其他回答
- **分段機制（segments／base）有沒有涵蓋 `stages`？** 沒有，而且是刻意排除：階段由專屬端點維護，所以沒有 base、沒有 409。
- **`saveCaseRecord` 實際送什麼？** 見上表 #1。`_expectedUpdatedAt` 只有派工（`case-management-dispatch.js:240`）與報價單表單（`quotation-form.html:2990`）會送；案件頁存檔靠分段 base 防覆蓋。
- **套用樣板會不會讓報價單表單的舊分頁 409？** 會，而且是好事：`apply-template` 之後 `_sync_stages_to_json` → `save_quotation_json` 會推進 `quotations.updated_at`（已加測試）；表單舊分頁下次存檔帶的 `_expectedUpdatedAt` 比較舊 ⇒ 伺服端既有的 409「報價單已被其他人更新」。所以路徑 #2 在「有帶 `_expectedUpdatedAt`」時已被擋住。

### 路徑 #2 還剩的洞
1. 沒帶 `_expectedUpdatedAt` 的呼叫端（舊版前端快取、直接打 API 的程式）：整批同步照做。
2. 表單的樂觀鎖只比 `updated_at`；任何人在載入後動過案件（包含階段細部端點，因為它們都會 `_sync_stages_to_json`）都會讓它 409——所以這條路徑本來就很容易 409，真正危險的是第 1 點。
3. 「半解鎖／解鎖編輯」（`_isUnlockEdit`）一樣先過 409 檢查，不是繞過。

## 2. 三個選項（b4 提出的 a／b／c）與一個建議（d）

| 選項 | 做法 | 假 409 風險 | 效果 | 評語 |
|---|---|---|---|---|
| (a) 案件頁 `saveCaseRecord` 帶 `_expectedUpdatedAt` | 前端存檔帶最近一次的 `updatedAt` | **高**：`updated_at` 被所有端點推進（階段細部、派工、材料、出貨、簽核、行事曆鏡射…）；案件頁自己的自動存檔與細部端點交錯就會把自己擋成「被別人更新」（t58 分段基準已經踩過同類問題） | **零**：案件頁存檔本來就不送階段，伺服端也忽略 | **不要做** |
| (b) 把 `stages` 當一個分段加 base | 分段 base 納入 `stages` | **很高**：階段每一次細部編輯都改變伺服端 `stages`，要每個回應都更新 base；漏一個就 409 | 重複 #1 已有的保護 | **不要做** |
| (c) `gone_id` DELETE 保守化（只刪「用戶端載入時有的」） | 需要用戶端告知載入時的 id 清單，或用 `created_at <= _expectedUpdatedAt` 近似 | 低（只減少刪除） | 只解掉「刪除」，**復活（INSERT）與 UPDATE 蓋掉 `done` 仍在** | 半套，不夠 |
| **(d) 報價單整包存檔也忽略 client 的 `stages`** | `update_quotation` 比照 `update_case_record`：不呼叫 `_sync_json_stages_to_table`，存回的 `caseRecord.stages` 用伺服器現有值（`new_cr["stages"] = 現有值`），其餘不變 | **無新增**（沒有新的比較、沒有新的 409 來源） | 一次關掉刪除、復活、蓋掉 `done`／日期三種傷害，包含沒帶 `_expectedUpdatedAt` 的呼叫端 | **建議** |

(d) 為什麼安全：報價單表單沒有任何階段編輯畫面（只有 seed，而 seed 走細部端點 `POST …/stages`，回傳的新階段只 push 進記憶體的陣列）；階段的唯一寫入者已經是細部端點，整包同步橋樑在 2026-08-24 就被案件頁路徑拿掉，這裡只是漏網。

## 3. 建議與測試計畫（排進後面的切片，要 e2e 證明）

**建議 S-ST4（小切片，只動 `update_quotation` 的 ~6 行與註解）：**
1. `update_quotation`：移除 `_sync_json_stages_to_table` 呼叫；寫入 `data_json` 前把 `q["caseRecord"]["stages"]` 換成伺服器現有的（`SELECT … case_stages` 重建，或沿用 `_sync_stages_to_json` 的結果）；沒有 `caseRecord` 的舊單不變。
2. `create_quotation` 不動（新單）。
3. 不動案件頁、不動 `saveCaseRecord`、不動分段機制。
4. `_sync_json_stages_to_table` 的 `stage_key` 保護與 INSERT 驗證保留（仍被 `create_quotation` 與測試使用）。

**測試（pytest）：**
- 舊報價單分頁：先 `GET` 取得 `caseRecord.stages`，別的帳號套用樣板／刪除一個階段／勾選完成，再用舊的 JSON `PUT`（不帶 `_expectedUpdatedAt`）⇒ 表內：新套用的階段還在、被刪的不復活、`done` 不被蓋掉；回應的 `caseRecord.stages` 是現況。
- 帶舊 `_expectedUpdatedAt` ⇒ 仍然 409（既有行為不變）。
- 舊單沒有 `caseRecord` ⇒ 行為與今天逐位元相同。
- 既有的 `test_case_stages_endpoints_2026_09_07.py` 等（若有依賴「PUT 會同步階段」的題目）改成斷言新行為，並在 PR 說明。

**e2e（要 Edge，等 gate 空檔）：** 兩個瀏覽器分頁開同一張已成案報價單：分頁 A 開著報價單表單、分頁 B 在案件頁套用階段樣板／刪階段；A 按存檔 ⇒ 看到「已被其他人更新」或（沒帶鎖時）靜默成功但 B 的階段完整保留；再開案件頁確認階段數與完成狀態不變。

**風險：** 唯一行為改變是「報價單表單的整包存檔不再改階段」——表單本來就沒有改階段的畫面；若有尚未發現的呼叫端靠這條路徑寫階段（直接打 API 的外部程式），它們會悄悄失效。上線前 `grep` 全部前端與腳本；沒有就上。

## 4. 為什麼不先做 (a)／(b)
b4 指出案件頁存檔是最常用的程式碼，t58 分段基準的經驗是基準一動就會有假 409。本分析確認：**案件頁存檔路徑不需要動**，風險最大的 (a)(b) 也買不到任何保護。

## 5. 附帶發現（產品行為，需要 PM 決定）：預設 5 階段 seed 與階段樣板互相擠壓
案件頁（與報價單表單）在**載入時發現 0 個階段就自動建立 5 個預設階段**（訂單確認、材料申請出貨、施工安裝、客戶驗收、尾款結清；沒有 `stage_key`）。因此：
- 新案件第一次被打開就有階段 ⇒ 樣板的「new」模式（空案件才可用、才帶比例）幾乎遇不到，使用者實際走的是「附加」（不帶比例）；比例的好處（建議值）等於用不上。
- 附加之後會出現預設階段與樣板階段並存（名稱相同的會重複；預覽說明已提示）。
- 選項（待 PM 裁示，各自小改動）：
  1. 旗標開啟且已發布樣板時，**seed 改成不自動建立**（空案件維持 0 階段，使用者從「套用階段樣板」或「新增階段」開始）；旗標關＝逐位元不變。
  2. 增加「預設樣板」（定義內 `default: true` 之類）：seed 時若有預設樣板就用它套用（含比例），否則維持 5 個預設階段。需要 S-ST1 定義與比較函式多一個欄位（金流相關：換預設樣板＝放寬？）。
  3. 維持現狀（使用者自己決定要不要把預設階段刪掉再套樣板）。
- 建議 1（最小、最可預期、旗標關無差異）；2 留到第二期。

## T62 列車備註（2026-10-14）

**S-ST4 未隨 T62 上線：正式機請勿開啟階段樣板旗標（`builder_stage_templates.enabled`），直到 S-ST4 上線。**（稽核 SHOULD-1；T62 只修 SHOULD-2／3／4，並在管理者手冊標註。）
