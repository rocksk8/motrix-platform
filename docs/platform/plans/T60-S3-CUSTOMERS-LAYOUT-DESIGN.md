# T60 S3：客戶管理頁（customers.html）接版面引擎——設計（不實作，停在這裡）

> 日期：2026-10-14　作者：hichan-3c　基底：`train/t59-int` 588275030　狀態：**設計，待核心層裁示；沒有任何程式改動**
> 依 b4 指示：D6 預設（核心欄位＝公司名稱、統一編號、狀態）暫採；「若沒有乾淨的擁有模組就寫文件並停下，不做核心拼湊」。結論：**沒有乾淨的擁有模組**。

## 1. 為什麼卡住（已查證的事實）

版面引擎（P9）要求頁面屬於一個**已載入的模組**：
- `customization.pages[].page` 必須是**同一個 module.json** 的 `pages[].path`（`core/customization.py`）；
- `GET /api/layout/{module}` 在 `registry.is_loaded(module)` 為假時回 404（`routers/definitions.py`）；
- 版面定義的鍵是 `module:<模組>`，點由 `catalog.layout_points(模組)` 提供。

客戶管理頁不屬於任何模組：
- `customers.html` 在 `backend/core/l1_pages.json`（L1 頁面），選單在 `core/menu_l1.json`；API 在 `backend/routers/customers.py`（`main.py` 直接 `include_router`）；`docs/platform/modules.json` 把它登記為 L1（`page:pages/customers.html`、`router:customers`、`/api/customers`）。
- `docs/platform/CORE-SPEC.md` §209 明定：「**客戶（`customers`）與料號（`parts`）下沉 L1**；業務開發 CRM 仍是 M02」。所以客戶主檔是**核心共用主檔**，不是 crm 模組的資產。
- 同一頁面不能同時出現在 L1 與模組：`core.menu.check_l1_pages` 與頁面收集（`core/pages.py`）會把「L1 頁面被模組宣告」當衝突（模組被拒載）。

因此沒有「註冊客戶的模組」可掛；任何做法都要碰核心層。

## 2. 選項

| 選項 | 內容 | 核心層改動 | 風險／代價 |
|---|---|---|---|
| **A（建議）** 讓 L1 共用主檔頁面也能登記可自訂點 | 新增 core 擁有的清單（例 `core/l1_customization.json`，格式同 module.json 的 `customization`）；`catalog.layout_points("core")`／`check_layout("core", …)` 把它當一個虛擬擁有者；`GET /api/layout/core`（或 `l1`）與定義鍵 `module:core` 接受它；`customers.html`（之後 `parts`）用 `MotrixLayout.init({module:'core', page:'customers.html'})` | L0（`core.customization`／`core.catalog`）新增、`routers/definitions.py` 兩處放行 `core`、core 次版號 +1、`l1_interface_snapshot`、`CHANGELOG` | 範圍小、可逆（不登記＝沒有行為）；但碰**治理擁有的檔案**（`routers/definitions.py`）與 L0 契約，需 46/98 與 3e 同意；「虛擬擁有者」要明講不是模組（不可被停用／授權） |
| B 把客戶搬進 crm 模組（M02） | `routers/customers.py`、頁面、選單都搬到 `modules/crm` | 大：`l1_pages.json`、`menu_l1.json`、`modules.json`、`DEPENDENCY-MAP`、提供者（`customers` 被報價、案件、承攬等多處讀取）、跨模組 import 守門 | 與 CORE-SPEC §209 的決定相反；客戶是共用主檔，crm 停用時報價單就沒有客戶 API。**不建議** |
| C 建一個只放客戶版面的空殼模組 | 新模組宣告 `pages: customers.html` | 與 L1 頁面衝突（見 §1），模組會被拒載 | **不可行** |
| D 不做（維持寫死） | — | 無 | 客戶頁是使用者最常提的畫面之一；若不做，建構器的「全部可自訂」範圍缺一塊 |

## 3. 若走 A：客戶頁的登記內容（D6 預設，供核心層裁示後直接用）

列表「客戶清單」（key `customers`，entity `customer`），欄位依畫面現況：

| key | 標題（預設） | 核心？ | 備註 |
|---|---|---|---|
| name | 公司名稱 | **核心** | D6 |
| alias | 內部簡稱 | 否 | 顯示標籤（tags/alias） |
| taxId | 統一編號 | **核心** | D6 |
| contact | 主要聯絡人 | 否 | **個資**：版面只管顯示；告知流程（`privacy-notice`）不變 |
| phone | 電話 | 否 | 個資 |
| industry | 產業 | 否 | |
| owner | 負責業務 | 否 | |
| quoteCount | 累計報價 | 否 | **件數，不是金額**；登記時要在測試裡鎖「沒有金額欄」 |
| lastContact | 最後往來 | 否 | |
| status | 狀態 | **核心** | D6（含 VIP／往來中／停用的標籤） |

固定不動：第一欄頭像、最後一欄操作（編輯／報價／日誌）。

頁面接法與供應商頁（`347c5edad`）完全相同：`deferred` 初始化、旗標 `builder_layout.customers`（預設關）、旗標關閉時原表格原封不動、旗標開啟時插入版面表格並隱藏原表格、編輯位置由 JS 插入。**不需要任何新模式**；供應商頁的測試（登記＝fallback＝標題一致、核心不可隱藏、發布／還原、受限角色資料不變）可直接複製改名。

## 4. 測試與守門（走 A 時）

1. 登記驗證通過（`validate_manifest` 同一份驗證器套到 `core/l1_customization.json`）；fallback 順序＝登記順序。
2. 旗標關閉：`/api/layout/core` 不被呼叫；綁定函式回中性值（node 實跑）。
3. 核心欄位（公司名稱、統一編號、狀態）發布 `hide` 被擋（422）。
4. 受限角色：沒有客戶模組權限的人，`GET /api/customers` 本來就 403／空；發布任何版面後不變。
5. 守門：`core` 這個擁有者不得被停用／授權機制影響（寫一題證明 `registry.is_loaded("core")` 的替代判斷永遠為真，且不能被 `unload`）。
6. 反向：`layout_points("crm")` 等其他模組不受影響（快照題）。

## 5. 工量與下一步

- 走 A：L0／L1 約 0.5～1 天（含核心次版號、快照、CHANGELOG 與上述守門），頁面與測試約 0.5 天（複製供應商頁）。
- **需要的裁示**：①是否採 A；②虛擬擁有者的名稱（`core`／`l1`）；③誰動 `routers/definitions.py`（治理擁有）——建議由 3e／46 指派或同意一個最小改動（把 `registry.is_loaded(module_key)` 換成 `catalog.owner_loaded(module_key)`，行為對一般模組不變）。
- 在裁示之前，客戶頁維持現狀；本分支不含任何 customers 相關程式。
