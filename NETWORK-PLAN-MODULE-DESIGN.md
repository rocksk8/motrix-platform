# 網路架構規劃模組（Network Plan）— 架構報告書與施做順序

> 狀態：**開發完成，尚未部署到正式機**（§10 步驟 1～10、12 已完成＋額外新增 Excel 匯入；步驟 11 測試已覆蓋 CRUD/權限/匯出/匯入但未涵蓋前端 JS；步驟 13 部署待走 §15 流程）｜DB migration：**v64 已套用**｜每次要繼續調整這個模組前先讀本文件 + `MOTRIX-ERP-QUICK.md`

## 2026-08-26 追加調整（使用者實測回饋）

1. **🔴 重大 bug 修復：匯出的 Excel 檔案會被 Excel 判定損毀、跳出「發現部分內容有問題」修復對話框。** 根因：`network_plan_export.py::build_plan_excel()` 對空白欄位寫入空字串 `""`，openpyxl 會產生 `<c t="inlineStr"></c>`（缺少必要的 `<is>` 子元素）——這是不合法的 OOXML，只要規劃書裡**任何欄位留空**（幾乎每一份都會發生）就會觸發。修法：`_cell_text()` 空值一律回傳 `None` 而非 `""`，讓 openpyxl 產生真正空白、合法的儲存格。已用 zipfile 直接解析 XML 驗證修復前後差異，並新增迴歸測試（掃描匯出檔案的 worksheet XML，斷言不存在空白 `inlineStr` 儲存格）。**這個 bug 影響先前所有已產生的匯出檔案**，正式機套用後之前下載過的 Excel 檔都建議重新匯出。
2. **UX 改版：明細分頁改成卡片式版面，不再是需要左右滑動的寬表格。** 使用者反映「設備清單」這類 12+ 欄位的表格逐格填寫要一直左右滑動，體驗很差。改法：每筆記錄改成一張卡片，欄位用 `grid-template-columns:repeat(auto-fill,minmax(150px,1fr))` 自動換行排列，同一筆資料全部欄位在視窗寬度內就能看完、不需要水平捲動，只有記錄筆數多時才需要垂直捲動。10 個明細分頁共用同一套卡片渲染邏輯（沿用原本的 `DATA_TABS` 欄位設定），改動集中在 `network-plan-form.html`。
3. **新功能：批次套用（勾選多筆、一次設定同一欄位）。** 使用者需求：「可多項同步同一個 VLAN 或是階段，節省人員時間」。做法：每張卡片左上角加勾選框，勾選任一筆後畫面上方浮現批次工具列（選欄位＋填值＋「套用到已選取」），送出後對所有勾選列的該欄位一次性賦值。這是純前端記憶體操作，套用後仍要按「儲存」才會真的寫回後端。刪除任一列會連帶清空該分頁的勾選狀態，避免索引錯位。
4. **新功能：Excel 匯入。** 使用者需求：「現場填寫完可以直接匯入」——工程師把匯出的範本帶到現場離線填寫，回來後整份上傳，不用逐欄位重新輸入。新增 `POST /api/network-plans/{id}/import/excel`（`network_plan_export.py::parse_plan_excel()` 負責解析），比對規則：**分頁名稱＋欄位表頭文字**（不是欄位順序／位置），未辨識的分頁或欄位直接略過並回傳 warnings，不會讓整次匯入失敗；找不到任何可辨識分頁才視為錯誤（400）。有辨識到的分頁是**整批覆蓋**該分頁在 `data_json` 的陣列，不是逐列合併——所以匯入前端刻意用自訂 Modal（不是瀏覽器原生 `confirm()`，一來風格統一，二來原生 dialog 在自動化測試環境會卡死整個分頁，改自訂 Modal 後續要再測試也比較好操作）先提醒使用者「這會整批取代現有明細，未儲存的修改會遺失」。案場識別欄位（`siteName`/`quoteNo`/`status` 等）不受匯入影響，只動 10 大類明細本身。匯入成功會在修訂紀錄自動加一筆「透過 Excel 匯入更新：...」。

**驗證：** 上述 4 項都已用真實瀏覽器（本機 dev server，`nptest_temp2` 臨時帳號）跑過端到端流程——修復後的匯出檔案直接用 `zipfile`+正則掃描確認沒有壞掉的 `inlineStr` 儲存格；卡片版面截圖確認同一筆資料完全不需要水平捲動；批次套用勾選兩筆設備、選「管理 VLAN」、填 45、套用後兩筆同步更新且存檔後重新載入仍正確；Excel 匯入用 `file_upload` 工具（不是點擊 input，會跳出無法互動的原生檔案選取視窗）把一份匯出檔匯入回同一份規劃書，成功訊息與修訂紀錄皆正確，且各分頁資料跟原始匯出內容一致。測試資料與臨時帳號已清除。後端新增 3 題 pytest（匯出/匯入 round-trip、上傳非法檔案 400、無權限 403），全套 168/168 全過。

## 完成狀態總結（2026-08-26 初版）

**後端：**
- `backend/db.py` — `_m064_network_plans`，`network_plans` 表（v64）
- `backend/routers/network_plans.py` — 完整 CRUD＋狀態切換＋刪除＋Excel/PDF 匯出端點，已註冊進 `main.py`
- `backend/network_plan_export.py` — Excel（openpyxl，9+1 Sheet）／PDF（Edge headless，橫向 A4）建構邏輯
- `backend/tests/test_network_plans.py` — 9 題（權限、綁案件防重複、樂觀鎖、狀態切換寫入修訂紀錄、刪除限制、匯出）
- `backend/version_manifest.json` — 已插入 `2026-08-26e` 條目（index 0）

**前端：**
- `frontend/pages/network-plans.html` — 列表頁，含「綁定既有案件」搜尋下拉選擇器（呼叫 `/api/quotations?deal_tag=已成案,已結案`，排除已建過規劃書的案件）
- `frontend/pages/network-plan-form.html` — 總覽 + 10 個明細分頁（共用同一套列表編輯 Alpine 邏輯，欄位由 `DATA_TABS` config 定義），含 IP 順序即時彙總檢視、MAC 自動格式化、庫存序號挑選 Modal（呼叫既有 `/api/inventory/stock-items`）
- `frontend/pages/users.html` — 新增 `netplan_edit` 模組（群組「網路架構規劃書」）
- `frontend/static/sidebar.js` — 「設備」分類新增選單項目
- `frontend/pages/case-management.html` ＋ `frontend/js/case-management.js::openNetworkPlan()` — 案件「執行管理→設備登錄」子分頁新增規劃書入口按鈕，自動判斷該案件是否已有規劃書（有則直接開啟，無則詢問是否建立）

**實機瀏覽器驗證（本機 dev server + 真實 Edge headless）已通過：** 建立（綁案件／獨立）、案件搜尋下拉挑選、10 個分頁填寫、IP 順序彙總即時計算、MAC 自動正規化、庫存序號挑選並連動 MAC/型號、儲存＋樂觀鎖重載、狀態切換寫入修訂紀錄、Excel 匯出（200）、PDF 匯出（200，真實 Edge headless 產出）。過程中依實際畫面回饋修正一項 UI 缺陷：`.edit-table` 的 input/select 原本背景透明，在深色主題（本專案深色模式是靠整頁 `filter:invert(1)` 反色，見 `style.css` 說明）下會跟表格背景融在一起看不清楚——已改為表格列淺灰底（`#EFEDE7`）＋欄位本身純白底＋實線邊框（`var(--border)`），反色後仍維持清楚對比。

**尚未做（刻意排除，見 §11）：** 客戶需求確認表、拓樸圖形化繪製、CAD 管理。

**下一步（使用者決定時機）：** 走 §15 既有部署流程（`build_deploy_package.ps1` → 正式機 `apply_update.ps1`）套用到正式機；套用前建議先手動在正式機用 superadmin 帳號對 1-2 位工程師帳號的 `netplan_edit` 模組打開權限。

---

## 實作與草稿設計的差異（供之後維護參考）

- `PUT`/`POST` body 採原始 `dict`（`Body(...)`）而非 Pydantic model，理由是 `data` 欄位本質是 9+1 大類自由結構，比照 `netarch_guide.py` 既有做法。
- `data_json` 內部鍵名用 camelCase（`wanLines`/`ipAllocations`/`portProfiles`/`switchPorts`/`firewallRules`/`ipPortGroups`/`wifiSsids`/`revisionLog`），跟本文件 §3.2 草稿裡用的 snake_case 命名不同——欄位定義以 `network-plan-form.html::DATA_TABS` 與 `network_plan_export.py::SECTIONS` 這兩份互相對應的清單為準（改一邊要同步改另一邊）。
- 新建時若 `data_json` 未提供 `data`，`POST` 會塞入 10 個空陣列 + 1 筆初版 `revisionLog`；`PUT` 若沒有帶 `data` 鍵則保留原值不覆蓋（前端要整包送 `data` 才會生效）。
- WAN 分頁沒有另外設計單號/合約防重複校驗，純自由表格，跟其餘 9 類一致。

---

## 0. 決策摘要（已與使用者確認）

| 決策點 | 結論 |
|---|---|
| 與案件的關係 | **兩者皆可**：可綁定案件（`quote_no`），也可獨立建立（無案件的售前評估/巡檢） |
| 版本管理 | **單一文件 + 修訂紀錄**（不做報價單式 R1/R2 改版鎖定） |
| 編輯權限 | **工程師可編輯**：superadmin/admin 預設可編輯；engineer 需被賦予 `netplan_edit` 模組權限；其餘角色唯讀 |
| MAC／序號來源 | **整合現有庫存**：設備清單可從 `stock_items`（序號級庫存）挑選帶入 MAC/型號，亦可自由輸入未登記項目 |

---

## 1. 目標與範圍

在 MOTRIX-ERP 內新增一個「網路架構規劃書」模組，讓工程師可以在系統內直接填寫一份客戶網路建置案的完整技術規劃文件，涵蓋：

- WAN／對外線路（ISP、頻寬、固定 IP、合約）
- 設備清單（路由器／防火牆／交換器／AP／NVR／伺服器…）與管理 IP
- VLAN 規劃（VLAN ID、網段、DHCP、用途）
- IP 位址配置（含「IP 順序」檢視、衝突偵測）
- Port Profile 定義與交換器 Port 對應
- 防火牆／ACL 規則、IP／Port 群組
- 無線 SSID 規劃
- 實體線路／幹線配置
- 修訂紀錄

並能一鍵匯出 **Excel**（給工程師自己維運、比對用）與 **PDF**（給客戶的正式規劃書）。

**不在本次範圍（列為未來可選項目，見 §9）：** 客戶需求確認表（802.1X／NPS／AD／Captive Portal 等前期訪談內容）、拓樸圖形化繪製、實體圖面（CAD）管理。

---

## 2. 現況調查

### 2.1 這不是重做 `netarch_guide`
系統既有的 `netarch_guide.py` / `netarch-guide.html`（連同 `switch_guide`／`monitor_guide`／`access_guide`／`gateway_guide`／`env_guide`，六大類「選型資料庫」）是**技術族系／世代規格／產品選型導覽**，用途是「選什麼設備」，跟本次要做的「**這個案子實際怎麼規劃、給客戶的文件**」是完全不同的東西，不會互相取代，但設備清單填寫時可以參考選型資料庫做下拉建議（非必要）。

### 2.2 可直接複用的既有機制
| 需求 | 複用來源 |
|---|---|
| 單號生成（如 `NP-YYYYMM-NNN`） | `db.next_entity_code()`（`quote_seq`／`payslip_seq` 同款模式） |
| 案件綁定 | 比照 `case_action_items.py`／`payment_requests.py`：用 `quote_no TEXT` 對應 `quotations.quote_no`（案件本體其實就是 `quotations` 表 `deal_tag` 已成案的資料列，案件內容存於 `data_json.caseRecord`） |
| 明細資料儲存 | 比照 `quotations.data_json`／`dev_cases` 的模式：**熱欄位 + `data_json` JSON blob**，不用為 9 個分類各開一張表 |
| 樂觀鎖 | 比照 `PATCH .../payment/{idx}` 的 `_expectedUpdatedAt` → 409 模式 |
| 權限 | `helpers.auth._require_user(authorization, require_superadmin=True, module='netplan_edit')`（superadmin 或具該模組者可編輯，任何登入者可讀取）— 與 `netarch_guide_edit` 同款式 |
| MAC／序號挑選 | `GET /api/inventory/stock-items`（序號級庫存，已含 `serial_no`/`mac` 欄位） |
| Excel 匯出 | `reports.py::_build_excel()` 的 openpyxl 多 Sheet 建法（樣式：`Alignment`/`Border`/`Font`/`PatternFill`） |
| PDF 匯出 | `pdf_gen.py`：Edge headless `--print-to-pdf`，走 HTML 模板 → PDF，含公司抬頭/Logo 慣例 |
| Demo 帳號隔離 | 若牽涉檔案（PDF 存檔），需比照 `photos.py`/`helpers/uploads.py` 的 `is_demo_mode()` 導向 `_demo` 隔離目錄 |

### 2.3 參考範本分析（小林機械案，已調閱三份實際文件）
使用者提供的 `小林機械_網路架構規劃表_08.24.xlsx` 是**目前業務上實際在用、成熟度最高**的範本，共 9 個分頁，逐一列出如下（下方即為本模組資料模型設計的直接依據）：

| 分頁 | 核心欄位 |
|---|---|
| 01 設備清單 | 項次／設備名稱／類別／型號／位置／管理IP／管理VLAN／角色用途／**MAC**／階段／狀態／備註 |
| 02 VLAN規劃 | VLAN ID／名稱／中文名稱／Purpose／網段CIDR／Gateway／DHCP模式／DHCP起訖／DNS／用途／使用單位樓層／階段／狀態／備註 |
| 03 IP位址配置 | 項次／主機設備／**IP**／標籤名稱／開放埠／設備回應名稱／VLAN／遮罩／Gateway／配發方式／**MAC**／OS韌體／用途／狀態／備註 |
| 04 PortProfile定義 | Profile名稱／Native VLAN／Tagged VLAN／PoE模式／用途說明／套用對象／狀態／備註 |
| 05 交換器Port對應 | 設備／位置／管理IP／埠號／埠類型／連接對象／Port Profile／Native VLAN（自動）／Tagged VLAN（自動）／PoE／配線標籤／端點位置／狀態／備註 |
| 06 防火牆規則 | 優先權／規則名稱／類型（ACL交換器層／防火牆層）／動作／協定／來源／目的／目的Port／啟用／備註 |
| 07 IP與Port群組 | 類別／群組名稱／成員（IP網段Port）／用途／被哪些規則引用／狀態／備註 |
| 08 無線SSID | SSID／Profile名稱／VLAN／加密方式／密碼認證／頻段／AP群組／上下行限速／用戶端隔離／漫遊／狀態／備註 |
| 10 線路與幹線 | 路段／起點設備埠／終點設備埠／介質／規格／概估長度／標籤編號／路由路徑／狀態／備註 |

另兩份文件僅作對照，**不直接複製其結構**：
- `小林既有IP位置一覽表`：純歷史遺留的「IP+MAC+使用者」清單，比 03 分頁陽春，屬於改造前現況記錄，可視為 03 分頁在「尚未規劃、只是抄現況」階段的簡化用法，不需要另開資料表。
- `小林機械網路建置需求確認表`：這是**前期客戶訪談**用的表單（基本資訊／設計規劃說明／終端設備清查／VLAN規劃確認／認證與資安需求），屬於規劃書「之前」的階段性文件，列入 §9 未來可選項目，本次不做。

**本次設計比範本多一項：** 範本沒有獨立的 WAN 分頁（WAN 資訊是混在 03 分頁裡的幾筆 IP 列），但使用者明確要求 WAN 要能填寫，而 ISP／頻寬／合約編號等欄位跟一般 IP 列的欄位形狀不同，所以本設計**新增一個獨立的 WAN／對外線路小節**，其餘 9 個分類則完整比照範本欄位設計，不做增減。

---

## 3. 資料模型設計

### 3.1 新表：`network_plans`（db.py migration v64）

```sql
CREATE TABLE network_plans (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_no       TEXT UNIQUE NOT NULL,   -- NP-YYYYMM-NNN，比照 quote_seq 模式
    quote_no      TEXT,                   -- 選填，綁定案件 → quotations.quote_no；UNIQUE（一案一份規劃書）
    site_name     TEXT DEFAULT '',        -- 案場/客戶名稱（未綁案件時手動填；綁定時建立當下帶入唯讀提示用途）
    contact_name  TEXT DEFAULT '',
    contact_phone TEXT DEFAULT '',
    status        TEXT DEFAULT '規劃中',  -- 規劃中 / 已確認 / 已交付
    created_by    TEXT NOT NULL,
    updated_by    TEXT DEFAULT '',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    data_json     TEXT NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX idx_network_plans_quote_no ON network_plans(quote_no) WHERE quote_no IS NOT NULL;
```

> 選擇「一案最多一份規劃書」而非允許多份：符合「單一文件＋修訂紀錄」的決策——同一案子的規劃異動記錄在 `revision_log` 裡，不靠開新文件表達版本。若之後真的出現同案需要兩份平行規劃書的情境（目前沒有實例），再放寬 UNIQUE 限制。

### 3.2 `data_json` 內部結構

```json
{
  "wan_lines": [
    {"isp": "中華電信", "line_type": "光纖專線", "bandwidth_up": "100M", "bandwidth_down": "1G",
     "public_ip": "220.130.211.56", "subnet": "/29", "gateway": "220.130.211.57",
     "dns1": "", "dns2": "", "contract_no": "", "status": "已完成", "note": ""}
  ],
  "devices": [
    {"seq": 1, "name": "M2F-EFG Controller-01", "category": "閘道器／控制器", "model": "...",
     "location": "本棟2F核心機房", "mgmt_ip": "172.16.0.1", "mgmt_vlan": "1",
     "role": "Inter-VLAN 路由 + 控制器", "mac": "58:d6:1f:67:08:9a",
     "stock_item_id": null, "phase": "第一期", "status": "已完成", "note": ""}
  ],
  "vlans": [
    {"vlan_id": 1, "name": "Default", "name_zh": "預設", "purpose_tag": "Corporate",
     "cidr": "172.16.0.0/24", "gateway": "172.16.0.1", "dhcp_mode": "關閉",
     "dhcp_start": "", "dhcp_end": "", "dns": "", "usage": "", "location": "",
     "phase": "第一期", "status": "已完成", "note": ""}
  ],
  "ip_allocations": [
    {"seq": 1, "device": "EFG（LAN／控制器）", "ip": "172.16.0.1", "tag": "", "open_ports": "",
     "hostname": "", "vlan": "Default", "mask": "/24", "gateway": "—", "assign_type": "靜態",
     "mac": "58:d6:1f:67:08:9a", "os_fw": "5.1.19", "usage": "控制器管理介面", "status": "已完成", "note": ""}
  ],
  "port_profiles": [
    {"seq": 1, "name": "TRUNK-ALL", "native_vlan": 20, "native_vlan_name": "MGMT-INFRA",
     "tagged_vlans": "全部 VLAN", "poe_mode": "PoE 關閉", "usage": "交換器上行幹線",
     "apply_to": "", "status": "", "note": ""}
  ],
  "switch_ports": [
    {"device": "M2F-USW Enterprise-01", "location": "2F核心機房", "mgmt_ip": "172.16.20.10",
     "port_no": "1", "port_type": "RJ45 1G", "endpoint": "", "port_profile": "TRUNK-ALL",
     "native_vlan_auto": "", "tagged_vlan_auto": "", "poe": "", "cable_label": "",
     "endpoint_location": "", "status": "", "note": ""}
  ],
  "firewall_rules": [
    {"priority": 1, "name": "ALLOW-ADMIN-TO-ALL", "rule_type": "ACL(交換器層)", "action": "Accept",
     "protocol": "All", "source": "ADMIN(99)", "destination": "ANY", "dest_port": "Any",
     "enabled": true, "note": ""}
  ],
  "ip_port_groups": [
    {"category": "IP 群組", "group_name": "GRP-DEPT-VLANS", "members": "172.16.40.0/24, ...",
     "usage": "所有部門 VLAN", "referenced_by": "ALLOW-DEPT-TO-SHARED", "status": "", "note": ""}
  ],
  "wifi_ssids": [
    {"seq": 1, "ssid": "DYNASTY-STAFF", "profile": "CORP-STAFF", "vlan": 45,
     "security": "WPA2/WPA3-Personal", "auth": "", "band": "2.4+5+6GHz", "ap_group": "APG-1F/2F/6F",
     "down_limit": "不限", "up_limit": "不限", "client_isolation": "關閉", "roaming_11r": "開啟",
     "status": "已完成", "note": ""}
  ],
  "cabling": [
    {"seq": 1, "segment": "", "from": "", "to": "", "media": "", "spec": "", "length_est": "",
     "label": "", "route_path": "", "status": "", "note": ""}
  ],
  "revision_log": [
    {"version": 1, "date": "2026-08-26T10:00:00", "editor": "jeff", "note": "初版建立"}
  ]
}
```

**設計原則：**
- 每個分類都是**陣列＋自由物件**，不強制固定 schema（各案子可能欠缺某些欄位），前端表單即為欄位入口。
- `devices[].stock_item_id`：選填，若工程師從庫存挑選序號設備，寫入 `stock_items.id`，MAC/型號自動帶入且**唯讀**（避免規劃書上的 MAC 跟庫存實際序號脫鉤）；未選庫存則所有欄位自由輸入。
- IP 順序不是存出來的欄位，是**畫面上的計算檢視**（見 §4.3）。

---

## 4. 後端 API 設計（`backend/routers/network_plans.py`，新檔）

| Method | Path | 說明 |
|---|---|---|
| GET | `/api/network-plans` | 列表（可用 `?quote_no=`／`?status=`／`?q=` 篩選），任何登入者 |
| POST | `/api/network-plans` | 新建（可帶 `quote_no` 綁案件或留空），`netplan_edit` |
| GET | `/api/network-plans/{id}` | 明細，任何登入者 |
| PUT | `/api/network-plans/{id}` | 整份更新 `data_json` + 樂觀鎖 `_expectedUpdatedAt` → 409，`netplan_edit` |
| PATCH | `/api/network-plans/{id}/status` | 狀態切換（規劃中/已確認/已交付），寫入 `revision_log`，`netplan_edit` |
| DELETE | `/api/network-plans/{id}` | 僅 `規劃中` 可刪，superadmin |
| GET | `/api/quotations/{quote_no}/network-plan` | 依案件查規劃書（比照 `case_action_items.py` 巢狀路由慣例），供案件詳情頁直接連結 |
| GET | `/api/network-plans/{id}/export/excel` | 匯出 9+1 個 Sheet 的 xlsx，`StreamingResponse` |
| GET | `/api/network-plans/{id}/export/pdf` | 走 Edge headless 產出客戶版 PDF |

沿用 `_audit()` + `notify_module_activity()` 記錄稽核與活動通知（比照 `netarch_guide.py` 寫法）。

### 4.1 IP 衝突檢查（後端輕量驗證）
`PUT` 時額外掃描 `devices[].mgmt_ip` + `ip_allocations[].ip`，同一 VLAN 內若出現重複 IP，**不擋存檔**（規劃過程本來就可能暫時衝突），但回傳 `warnings: [...]` 讓前端提示，不當硬性 400——理由：規劃書是草稿性質文件，過度阻擋會妨礙工程師邊想邊填。

---

## 5. 前端頁面設計

### 5.1 `network-plans.html`（列表頁，比照 `quotations.html`）
- 表格：規劃書編號／案場名稱／綁定案件（連結至 case-management）／狀態／最後更新／更新人
- 篩選：狀態 Tab、搜尋框（案場/案件編號）
- 「新增規劃書」按鈕 → 彈窗選擇「綁定既有案件」或「獨立建立」

### 5.2 `network-plan-form.html`（表單頁，比照 `quotation-form.html` 分頁 Tab 模式）

Tab 順序即施工/規劃邏輯順序：

1. **總覽** — 規劃書編號、案場資訊、綁定案件（唯讀顯示，來自 `quotations`）、狀態、修訂紀錄表
2. **WAN／對外線路** — 新增小節，非範本既有分頁
3. **設備清單** — 類別下拉（路由器/防火牆/交換器/AP/NVR/伺服器/其他），「從庫存挑選」按鈕開 Modal 呼叫 `GET /api/inventory/stock-items?q=` 挑序號
4. **VLAN 規劃**
5. **IP 位址配置** — 見 §5.3 IP 順序檢視
6. **Port Profile 定義**
7. **交換器 Port 對應**
8. **防火牆規則 ＋ IP／Port 群組**（兩個範本分頁高度相關，合併同一 Tab 上下區塊呈現）
9. **無線 SSID**
10. **線路與幹線**

每個表格 Tab 皆為「新增列／複製列／刪除列／上移下移排序」的通用列表編輯 UI（可抽一個共用 Alpine component，9 個分類共用同一套列表操作邏輯，只有欄位定義不同——避免寫 9 份幾乎一樣的 CRUD 表格程式碼）。

工具列固定顯示：**儲存**／**匯出 Excel**／**匯出 PDF**／狀態切換。

### 5.3 「IP 順序」檢視（使用者明確提出的需求）
在「IP 位址配置」Tab 頂部提供一個**唯讀彙總視圖**：把 `devices[].mgmt_ip` 與 `ip_allocations[].ip` 兩個來源合併，依 VLAN 分組、IP 由小到大排序顯示（用四段 octet 補零排序，不是字串排序），同一 IP 出現兩次時整列標紅並顯示「⚠ IP 重複」。這個視圖純前端計算（Alpine computed getter），不另外存資料庫欄位。

### 5.4 MAC 格式輔助
共用 `formatMac(input)` 工具：輸入時自動正規化為 `xx:xx:xx:xx:xx:xx` 小寫格式（範本裡出現過 `:` 和 `-` 兩種分隔符混用，統一輸出格式，但顯示時保留原始輸入亦可還原比對），並做基本正則驗證，格式錯誤時欄位標紅但不阻擋儲存（同樣是草稿優先原則）。

---

## 6. Excel 匯出設計

沿用 `reports.py::_build_excel()` 的 openpyxl 建法（`Alignment`/`Border`/`Font`/`PatternFill`），輸出結構**完全比照小林機械範本的 9 個分頁命名與欄位順序**，額外加：

- 封面 Sheet（沿用 §7 PDF 的公司抬頭/案場資訊，方便單獨轉寄 Excel 時也有識別資訊）
- WAN 分頁（新增於 01 之前）
- 最後一頁：修訂紀錄

檔名慣例：`{plan_no}_{site_name}_網路架構規劃表.xlsx`。

---

## 7. PDF 匯出設計

沿用 `pdf_gen.py` 的 Edge headless `--print-to-pdf` 模式：後端組一份 HTML 模板（複用公司抬頭/Logo 慣例，如報價單 PDF），章節順序與 Excel 分頁一致，適合直接給客戶看的排版（表格化，非 Excel 網格外觀）。存檔路徑走 `_get_pdf_base()` 同款可設定路徑機制，**若為 demo 帳號需自建 `DEMO_NETWORK_PLAN_PDF_ARCHIVE_DIR` 隔離目錄**，比照既有 6 種單據 PDF 的 demo 隔離慣例，不能漏掉（§2.2 已知踩坑）。

---

## 8. 權限與模組串接

- `users.html allModules` 新增 `netplan_edit`（供 admin 賦予特定 engineer 帳號編輯權）
- `sidebar.js` 新增選單項目（區塊建議放在「案件管理」或「設備」分類旁）
- 案件詳情頁（`case-management.html`）內加一顆「網路架構規劃書」按鈕，若已綁定則直接開啟、未綁定則帶 `quote_no` 建新

---

## 9. 測試計畫（pytest，比照現有慣例）

- CRUD：建立（綁案件/不綁案件）、更新樂觀鎖 409、狀態切換寫入 revision_log
- 權限：viewer 唯讀 403、engineer 未授權 403、engineer 授權後可編輯 200
- `quote_no` UNIQUE：同案重複建立規劃書應 409
- 庫存串接：選庫存序號帶入 MAC 後，`stock_item_id` 存在時 MAC 欄位應以庫存資料為準
- Excel/PDF 匯出：至少驗證 HTTP 200 + content-type 正確（PDF 依現有慣例，若本機無 Edge headless 環境，比照 `reports.py` 只驗證 HTML 字串組裝本身）
- Demo 隔離：demo 帳號建立的規劃書/PDF 不得污染正式庫與正式目錄

---

## 10. 施做順序（建議依序進行，每步驟可獨立驗收）

1. **DB migration v64**：新增 `network_plans` 表 + `_m064_network_plans()`，`CURRENT_VERSION` 遞增，先跑 `check_guide_sync.py`（若有動到六大類選型資料庫則跑，本次純新表可略過）
2. **後端 CRUD API**：`network_plans.py` 基本 GET/POST/PUT/DELETE + 樂觀鎖 + 權限（不含匯出）
3. **`users.html` 補 `netplan_edit` module key** + `sidebar.js` 選單項目
4. **前端列表頁 `network-plans.html`**
5. **前端表單頁 `network-plan-form.html`**：先做 Tab 1～3（總覽/WAN/設備清單），驗證「從庫存挑選設備」串接無誤
6. **表單頁其餘 Tab 4～10**（VLAN/IP/PortProfile/交換器Port/防火牆/SSID/線路），共用列表編輯 component 這時候可以定型並重複套用，加快後面幾個 Tab 的開發
7. **IP 順序彙總檢視 + IP/MAC 衝突提示**（§5.3、§5.4）
8. **Excel 匯出**（`_build_excel` 風格，9+1 Sheet）
9. **PDF 匯出**（Edge headless 模板 + demo 隔離目錄）
10. **案件詳情頁串接**：`case-management.html` 加入規劃書入口按鈕
11. **pytest 測試補齊**（§9 全項）
12. **`version_manifest.json` 插入新條目**（index 0，既有專案文件慣例）
13. 開發機驗證完成後，走 §15 既有部署流程（`build_deploy_package.ps1` → 正式機 `apply_update.ps1`）套用至正式機

---

## 11. 未來可選項目（本次不做）

- 客戶需求確認表模組（802.1X／NPS／AD／RADIUS／Captive Portal／終端設備數量清查）— 可視為規劃書「前置階段」的獨立小模組，之後有需要再評估是否併入同一個 `network_plans` 或另開表
- 拓樸圖形化繪製（目前僅能填表＋文字說明，圖檔仍建議另外存在案件資料夾如現行做法，如 `六樓拓樸圖_VLAN_V2.png`）
- CAD 圖面管理
