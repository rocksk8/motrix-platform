# U0a 單位鍵洩漏防線 — 設計與覆蓋（T57）

> 作者 hichan-1d（2b）；依 `FRAMEWORK-ORG-UNITS-T57.md` §14.10 #4。分支 `wip/t57-u0a-leak-defence-r1`。內部欄位名固定：`owner_unit_id`（業務表）、`unit_id`（`audit_log`、`notifications`）、`legal_entity_id`。

## 1 防線（誰擋什麼）
| 出口 | 做法 | 位置 |
|---|---|---|
| JSON 回應（約 815 條路由） | 最外層純 ASGI 中介層：僅 `application/json`、無壓縮、有 `content-length` ≤16 MB 才緩衝；本文含 `unit_id`／`legal_entity_id` 位元組才解析→遞迴剝鍵→更新長度；其餘（檔案、串流、壓縮、非 JSON）原樣轉送；超限／無長度的 JSON 記 ERROR。**沒有任何輸出內部欄位的開關**（日後要顯示單位用別的欄位名） | `core/internal_cols.py`、`main.py` |
| xlsx／csv 匯出 | 九個匯出模組的表頭都是手寫中文，不由資料列欄位推出；記錄器仍覆蓋表頭 | 記錄器 |
| `archive.py` 約 85–89 處 `SELECT *` | **全部保留完整欄位**：每日 JSON 備份／還原工具要讀（1c 裁示 q1）；使用者看得見的下載不經這些處 | 見 §3 |
| `table_digests` | 預設忽略內部欄位（加欄不改雜湊）；明列 `columns` 時照明列，真缺欄仍抓得到。`logical_digest` 含 `sqlite_master` SQL，加欄必然改變（schema 比對，預期） | `core/upgrade.py` |
| 即時通道 | 目前無；出現即紅（需先補剝除） | `test_u0a_sinks.py` |
| 輸入側（mass-assignment） | 動態 `UPDATE…SET` 組字串基線（7 檔，只准縮小）；內部欄位名不得出現在產品碼字串（寫入白名單） | `test_u0a_sinks.py` |
| 整列直接 `json.dumps(dict(row))` | 基線 2 處，只准縮小（通知／稽核／快照／信件的整列序列化是已知缺口，見 §4） | `u0a_row_dump_baseline.json` |
| 啟用判斷 | `core/features_l1.json` 宣告 `org_units`＝`planned`（`MS4` 為占位）；`spine.declared_and_open("org_units")`＝已宣告且 open 且已驗證；刪宣告⇒保持關閉 | `core/spine.py` |

## 2 回應鍵集基準（凍結條件）
- 記錄器 `tests/platform/_response_keys.py`：每張表先塞一列（NOT NULL 無預設的欄位按型別填：整數 1、文字 `x`），讓清單路由有鍵；記 JSON 鍵路徑（list 取聯集）與 csv／xlsx 表頭；路徑參數用種子值（整數 1、字串 `x`），必填查詢參數用合理預設（year／month／日期／fmt…）。拒絕清單：登出、關機、備份還原、套用升級、自檢、探針、`/map`／geo／tile（會對外連線）。
- 基準 `response_keys_baseline.json` 必須錄在 **U0 之前的父提交**（`0ea1d7197`＝MS1c payload）。比對：缺路由／多路由／鍵集或狀態類別不同 ⇒ 紅；任何內部欄位名 ⇒ 紅；下限防空洞（路由數、有鍵路由數、匯出數）。
- 正對照：中介層剝除換成恆等＋表加欄 ⇒ 必須回報洩漏；未剝除的 csv／xlsx 表頭 ⇒ 必須回報。
- **r2 擴充（已在父提交 `0ea1d7197` 重錄，連錄兩次逐項相同＝決定性）**：納入路徑參數 GET 與必填查詢參數的路由。實測：**370 條路由、336 條有鍵集、5 個匯出（200 且有表頭）、10 條狀態 0（種子垃圾資料下伺服器端例外，同樣記錄；日後它們若不再丟例外也會被比對抓到）、0 洩漏**；狀態分佈 200:269、422:37、404:27、400:15、409:6、429:4（匯出冷卻）、428:1。下限設為 路由≥340、有鍵≥300、匯出≥4。

## 3 路由覆蓋：約 815 條，第一版記 238
依裝飾器靜態計數（產品碼）：

| 類別 | 條數 | 狀態 | 為什麼 |
|---|---|---|---|
| GET 無路徑參數 | 239 | 已記（扣 map／geo 等拒絕項） | — |
| GET 含路徑參數 | 133 | 已納入（盡力：種子值對不上的會是 404/422，同樣記狀態＋鍵集，仍有比對意義） | 需要種子 id／單號 |
| POST | 266 | **未覆蓋（U0b）** | 回應多為確認訊息或剛寫入的整列；需要每條的合法請求本文與前置資料；不安全地批次呼叫會改資料／寄信／寫稽核 |
| PUT／PATCH | 74／43 | **未覆蓋（U0b）** | 同上，且需先建立目標資料 |
| DELETE | 60 | **未覆蓋（U0b）** | 會刪資料、需前置；回應通常很小 |
→ 未覆蓋合計約 443 條（全為會改資料的方法）。它們的回應仍受**中介層**保護（剝除與路由無關），缺的只是『基準 diff』這道獨立證明；U0b 以授權矩陣金標的路由清單加合法請求夾具補齊。

## 4 已知缺口（非 HTTP JSON 出口，0d 2）
`audit_log.detail` 與設定帳本快照、回收桶 `snapshot_json`／`files_manifest`（RBN12 已遮罩，需同步）、`notifications` payload、信件本文／`rows=`（`send_registered`）。U0a 目前以『整列 json.dumps 基線只准縮小』擋新增；既有 2 處與通知／稽核的明列欄位化列入下一個提交的逐處清單（strip｜keep）。
**決定（0d M-3）**：回收桶快照（`snapshot_json`）與每日 JSON 備份**保留**單位鍵欄位——還原不可丟單位歸屬；**只有 HTTP 輸出剝除**。`archive.py` 的 JSON 備份目前沒有自動還原程式（§8.3 最後手段，人工）；真正會執行還原的是四個模組的回收桶轉接器（arap／case／payroll／subcontract），它們的『依現有欄位插入』都只放現在表裡還有的欄位，所以還原雙向相容：舊快照→新結構取 DEFAULT 1、新快照→缺欄位的庫忽略未知欄位、新快照→新結構值原樣放回。`tests/platform/test_u0a_restore.py` 逐一驗證四個轉接器。
**demo 模式**：demo 請求走同一個 `main.app`，中介層在最外層、早於驗證與 demo 路由切換，所以不另有路徑；`test_internal_cols_middleware_is_the_last_registered_middleware` 守住這個位置。

## 5 流程
1. 在父提交錄基準（單獨一次、約 3 分鐘）→ 2. 本分支重生 L1 快照與 CHANGELOG `(next)` → 3. 單檔測試：`test_internal_cols`、`test_u0a_sinks`、`test_response_keys_baseline`（差異必須為空）、`test_unit_cards`、L1 快照、`test_core_loader`、升級相關 → 4. U0 core 遷移（c7）後重跑基準比對，差異必須為空。

## 6 驗證直譯器：作者送審前的自查必須跑在閘門用的直譯器（2026-10-13 教訓）
- **事實**：閘門（列車機）用 `D:\MOTRIX-PLATFORM\.venv312\Scripts\python.exe`＝Python 3.12.8、FastAPI 0.141.1、starlette 1.7.0、pydantic 2.13.5；作者視窗預設的 `python`＝3.11.15、FastAPI 0.133.1、starlette 1.0.1、pydantic 2.13.4。
- **差異**：FastAPI ≥0.14x 的 `include_router` 不再把子路由攤進 `app.routes`，而是放 `_IncludedRouter`（沒有 `.path`，只有 `effective_route_contexts()`）；0.133 仍攤平。凡是『遍歷 app.routes』的程式在新版上會**安靜地少看**（U0a 回應鍵集記錄器就是這樣在列車機只看到 4 條 GET、記到 0 條路由而紅，作者機卻綠）。
- **規則**：①遍歷路由一律用共用的 `tests/_routes.py::all_routes(app)`（核心程式用 starlette 公開的 `route.matches(scope)`，見 `core/loader.py::_match_owner`）；不直接讀 `app.routes[i].path`。②作者送審前的自查（單檔測試）**必須在 `.venv312` 直譯器上跑**（或兩個都跑）；只在 3.11 綠不算。③守門測試應有『路由數下限＋診斷訊息』，避免空洞（本記錄器已加）。
- **已核對可相容**（FastAPI 0.141 閘門通過或程式自己處理）：`core/catalog.py`（處理 `_IncludedRouter`）、`core/loader.py::mount_modules/_match_owner`（用 `matches()`）、`tests/_routes.py`、`tests/platform/test_module_routes_declared.py`、`tests/test_company_setup_gate_2026_09_28.py`／`test_non_api_routes_whitelist_2026_09_28.py`（自行走 `_IncludedRouter`）、`modules/case/tests/test_route_table_golden_2026_10_05.py`（路由表金標，閘門通過）。
