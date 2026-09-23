# MOTRIX ERP — 模組：選型導覽與網路規劃書（§7.6／§7.7／§7.9／§7.10／§7.12／§7.14）

> 自 `MOTRIX-ERP-QUICK.md` 拆出（2026-09-23）。§ 編號沿用原編號，程式註解裡的「QUICK.md §N」依中樞檔的對照表找到本檔。
> 內容逐字搬移，未改寫；相對連結已改為自本目錄起算。

---

### §7.6 · 場域選型導覽（DB v30）

無人自動化載具部署場域／設備選型參考資料，原為獨立單機工具（場域選型導覽.html），2026-07-30 整合進 ERP 並資料庫化。

| Method | Path | 說明 |
|--------|------|------|
| GET | /env-guide/environments | 場域列表（需認證即可，無角色限制） |
| POST/PUT/DELETE | /env-guide/environments[/{code}] | 新增／修改／刪除場域；superadmin 或 `env_guide_edit` 模組 |
| GET | /env-guide/recommendations | 分層建議列表（需認證） |
| POST/PUT/DELETE | /env-guide/recommendations[/{id}] | 同上權限 |
| GET | /env-guide/links | 原廠／代理商連結列表（需認證） |
| POST/PUT/DELETE | /env-guide/links[/{id}] | 同上權限 |

- 前端 `frontend/pages/env-guide.html`：瀏覽模式分「簡易／進階」兩個子模式（`browseMode`，預設 simple）——**簡易**是場域方塊＋分層卡片（跟網路架構選型導覽同一套介面，Alpine 直接讀 `envRows`/`recRows`/`linkRows`）；**進階**是原單機工具的矩陣／卡片／表格／搜尋／篩選／抽屜 UI（vanilla JS，`window.EnvGuideTool.boot()` 由 Alpine `loadEnvGuideData()` 餵資料）；管理模式為新增的 CRUD 後台（Alpine + modal）
- 配色：`.envg` CSS 變數對應 MOTRIX 系統色票（`--accent`/`--text-*`/`--border-light` 等），`data-th="light"`為預設（＝系統配色），`data-th="dark"`為原工具深色調備用切換
- **Excel 匯出／匯入**：僅 `session.role==='superadmin'` 可見按鈕（UI 層限制，比其他模組的 `env_guide_edit` 更嚴格）；匯出 3 個工作表（環境/建議/連結）；匯入以場域代碼／建議與連結 ID 比對，相符則 PUT 更新、否則 POST 新增（沿用既有單筆 CRUD API，無專用批次 endpoint，做法比照 `customers.html` 匯入慣例）
- 種子資料：`backend/env_guide_seed.py`（JSON 字串常數，`_m030_env_guide` 一次性寫入，僅在表為空時執行，之後編輯一律走上述 API 不會被 migration 覆蓋）

---

### §7.7 · 網路架構選型導覽（DB v31）

選型資料庫第二個上線的類別，資料形狀是「技術族系→世代→產品」而非場域選型導覽的「情境×分層×三級」，見 `SELECTION-DB-INDEX.md`。

| Method | Path | 說明 |
|--------|------|------|
| GET | /netarch-guide/families | 技術族系列表（需認證） |
| POST/PUT/DELETE | /netarch-guide/families[/{code}] | superadmin 或 `netarch_guide_edit` |
| GET | /netarch-guide/generations | 世代/規格列表（需認證） |
| POST/PUT/DELETE | /netarch-guide/generations[/{id}] | 同上權限 |
| GET | /netarch-guide/products | 產品連結列表（需認證） |
| POST/PUT/DELETE | /netarch-guide/products[/{id}] | 同上權限 |

- 種子資料：`backend/netarch_guide_seed.py`（同樣僅在表為空時寫入一次）
- 前端 `frontend/pages/netarch-guide.html`：管理模式沿用場域選型導覽的淺色系統配色與 CRUD 慣例；瀏覽模式是新設計的「族系方塊→世代對照卡片」簡化 UI，未使用矩陣/篩選/搜尋那套

---

### §7.9 · 監控系統選型導覽（DB v39）

選型資料庫第四個上線的類別，資料形狀與交換器選型導覽相同（相機分類×場域情境矩陣），見 `SELECTION-DB-INDEX.md`／`MONITOR-GUIDE-CONTENT.md`。

| Method | Path | 說明 |
|--------|------|------|
| GET | /monitor-guide/scenarios | 場域情境列表（需認證） |
| POST/PUT/DELETE | /monitor-guide/scenarios[/{code}] | superadmin 或 `monitor_guide_edit` |
| GET | /monitor-guide/categories | 相機分類列表（需認證） |
| POST/PUT/DELETE | /monitor-guide/categories[/{code}] | 同上權限 |
| GET | /monitor-guide/fit | 適配矩陣列表（需認證） |
| POST/PUT/DELETE | /monitor-guide/fit[/{id}] | 同上權限 |
| GET | /monitor-guide/products | 產品連結列表（含 `specs_json`，需認證） |
| POST/PUT/DELETE | /monitor-guide/products[/{id}] | 同上權限 |

- 種子資料：`backend/monitor_guide_seed.py`（僅在表為空時寫入一次）
- 前端 `frontend/pages/monitor-guide.html`：以交換器選型導覽為範本（依情境查看／對照矩陣總覽／規格比較／管理後台 CRUD 全數沿用）

---

### §7.10 · 門禁系統選型導覽（DB v40）

選型資料庫第五個上線的類別，資料形狀同上（元件分類×場域情境矩陣），見 `SELECTION-DB-INDEX.md`／`ACCESS-GUIDE-CONTENT.md`。

| Method | Path | 說明 |
|--------|------|------|
| GET | /access-guide/scenarios | 場域情境列表（需認證） |
| POST/PUT/DELETE | /access-guide/scenarios[/{code}] | superadmin 或 `access_guide_edit` |
| GET | /access-guide/categories | 元件分類列表（需認證） |
| POST/PUT/DELETE | /access-guide/categories[/{code}] | 同上權限 |
| GET | /access-guide/fit | 適配矩陣列表（需認證） |
| POST/PUT/DELETE | /access-guide/fit[/{id}] | 同上權限 |
| GET | /access-guide/products | 產品連結列表（含 `specs_json`，需認證） |
| POST/PUT/DELETE | /access-guide/products[/{id}] | 同上權限 |

- 種子資料：`backend/access_guide_seed.py`（僅在表為空時寫入一次）
- 前端 `frontend/pages/access-guide.html`：以交換器選型導覽為範本（依情境查看／對照矩陣總覽／規格比較／管理後台 CRUD 全數沿用）
- 所有分類都需要一台執行 UniFi Access App 的 UniFi OS Console 才能運作，`READER` 分類的產品不能單獨運作，需搭配 `MULTI_DOOR_HUB` 才能控制門鎖，詳見 `ACCESS-GUIDE-CONTENT.md` §1

---

### §7.12 · 網路架構規劃書（DB v64，2026-08-26，見 §5 補充／`NETWORK-PLAN-MODULE-DESIGN.md`）

| Method | Path | 說明 |
|--------|------|------|
| GET | /network-plans | 列表（需登入） |
| GET | /network-plans/{plan_id} | 完整明細（10 分頁資料） |
| GET | /quotations/{quote_no}/network-plan | 依案件查詢對應規劃書 |
| POST | /network-plans | 建立（`netplan_edit` 模組或 superadmin） |
| PUT | /network-plans/{plan_id} | 更新 |
| PATCH | /network-plans/{plan_id}/status | 狀態切換 |
| DELETE | /network-plans/{plan_id} | 刪除 |
| GET | /network-plans/{plan_id}/export/excel \| /export/pdf | 匯出（10 分頁 Excel／Edge PDF，PDF 自動內嵌拓樸圖，見下） |
| POST | /network-plans/{plan_id}/import/excel | 匯入（分頁名稱＋欄位表頭比對，無法辨識分頁於 warnings 明確提示） |
| POST | /network-plans/{plan_id}/topology-preview | 拓樸圖即時預覽（不落地存檔），2026-09-04 新增，見 §12 同日條目 |

可綁 `quote_no` 也可獨立建立；**與 §7.6/§7.7 的「網路架構選型導覽」`netarch_guide` 是完全不同的兩個模組**，勿混淆。

**拓樸圖（2026-09-04）**：`backend/network_plan_topology.py::build_topology_svg()` 依「設備清單」＋「交換器 Port 對應」自動繪圖，PDF 匯出自動內嵌。獨立無狀態的「快速拓樸圖產生器」（不填規劃書、單純產圖）走另一組路由 `routers/network_plans_quick.py`（`POST /api/network-plans-quick/preview` \| `/pdf`，刻意用 `-quick` 前綴避免跟本節 `{plan_id}` 參數化路由衝突），對應頁面 `frontend/pages/topology-quick.html`，資料只存瀏覽器 localStorage、不寫入 `network_plans` 表。

---

### §7.14 · 自動化系統選型導覽（DB v65，2026-08-26 起，選型資料庫第七類）

情境×分類矩陣結構，與 switch/monitor/access/gateway 四類完全同款樣板（CRUD 端點命名/權限模式一致，`automation_guide_edit` 模組或 superadmin 可編輯）：

| Method | Path |
|--------|------|
| GET / POST / PUT / DELETE | /automation-guide/scenarios[/{code}] |
| GET / POST / PUT / DELETE | /automation-guide/categories[/{code}] |
| GET / POST / PUT / DELETE | /automation-guide/fit[/{id}] |
| GET / POST / PUT / DELETE | /automation-guide/products[/{id}] |

§6 Sidebar「選型資料庫」區塊現為**七大類**（原六類＋本類），`selection-db-overview.html` 涵蓋度總覽頁是否已納入本類需之後確認。
