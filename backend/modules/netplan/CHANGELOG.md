# 網路規劃 更新紀錄

## (next) — 2026-11-14（feat/t86-b1-h2；T86 文字：中性正式用語與覆核修正）
- 文字（行為不變）：回復 Excel 匯出表頭「被哪些規則引用」（匯出屬單據輸出，不在文字準則範圍）。
- **（併入）(next) — 2026-11-14（feat/t86-b1-h2；T86 文字：中性正式用語與覆核修正，含案件選單空狀態用語）**
- 文字（行為不變）：回復 Excel 匯出表頭「被哪些規則引用」（匯出屬單據輸出，不在文字準則範圍）。
- **（併入）(next) — 2026-11-14（fix/supplier-privacy-notice-mask-t86-h9；T86 告知紀錄遮罩；版號由列車取）**
- 行為變更（資料範圍收窄）：`GET /api/network-plans/{id}/privacy-notice` 與持有 `netplan_edit` 的非管理員呼叫 `POST …/privacy-notice/ack`（已記錄過時回傳既有紀錄）：管理員（admin／superadmin）照舊看完整紀錄；其他人只看「已告知＋日期」（`{at}`），不帶記錄人姓名／帳號（`by`／`byUsername`）與告知文字雜湊（`noticeHash`）。回應形狀不變（只是少欄位）、沒有新增權限鍵；伺服器端寫入的紀錄與稽核仍完整。
- 測試：`tests/test_privacy_notice_ack_mask_siblings_2026_11_14.py`。
- **（併入）(next) — 2026-11-14（feat/t86-short-labels-h2；T86 短標籤專業化）**
- 文字（行為、API、欄位、設定鍵、錯誤碼不變）：按鈕、卡片標題、表頭、空狀態與提示等短標籤改為正式、一致的用語（前往／查看、尚無／查無符合條件的…、僅顯示、無法…等）；前後對照見整合者的 T86 前後對照表。

## 1.0.18 — 2026-11-14（train/t85-text；T85 文字專業化；版號由列車取）
- 文字（行為、API、欄位、設定鍵、錯誤碼不變）：畫面、通知、錯誤提示與說明文字改為正式、一致的用語（您、尚未／尚無、是否、其他使用者、無法／不可等），標點與中英文間距依 `docs/platform/plans/TEXT-STYLE-GUIDE.md`；同一提交同步更新斷言字串的測試。逐項前後對照見 `docs/platform/plans/TEXT-DIFF-TABLE.md`。

## 1.0.17 — 2026-11-13（fix/xlsx-guard＋feat/ux-p0-p1-text；xlsx 守門、頁面標題後綴；T82 整合；版號由列車取）
- 變更（內部，API 路徑與回應形狀不變）：網路規劃書「匯入 Excel」（`export.py::parse_plan_excel`、`api.py` 匯入端點）改走共用 helper `helpers/xlsx_guard.read_rows`——先預掃（儲存格／欄／列號／巢狀深度等上限、禁 DTD）、再在子行程解析（硬逾時、記憶體上限）；每張表最多讀 `_PLAN_IMPORT_MAX_ROWS` 列。不合格的檔案回 400（白話訊息）、同時匯入的人太多回 429；正常檔案結果與先前相同。
- 測試：`tests/test_xlsx_guard_2026_11_13.py`（含網路規劃書匯入的炸彈 400＋正常檔正對照）。
- **（併入）(next) — 2026-11-13（feat/ux-p15-dashboard；UX P1.5）**
- 前端（文字）：頁面 `<title>` 後綴「專案管理系統」一律改為「MOTRIX PLATFORM」（系統標語改由公司設定 `brand.tagline` 決定，預設 MOTRIX PLATFORM）；不動 API／資料／權限。

## 1.0.16（next，未取號）— 2026-11-13（ui/mobile-tablet-combined 的改動；條目由 fix/mobile-cases-layout-v2 補，依各頁 git 歷史照實記錄；僅前端版面，不動 API／資料／權限判斷）
- `network-plans.html`、`network-plan-form.html`、`topology-quick.html`：手機／平板版面——彈窗在手機改為全寬（最大高度依字級縮放換算 `calc(92vh / var(--fz,1))`）、表格勾選欄間距；`network-plan-form.html`、`topology-quick.html` 的 `.page-wrap` 上方留白不再把頂欄高度加兩次（**全寬度都生效，桌機上方空白會比以前少一個頂欄高**）。

## 1.0.15 — 2026-11-11（feat/ux-navigation-hierarchy；UX 提案批次 1+2「導覽與資訊架構＋視覺層級」；不動 API／資料／權限判斷；L1 介面不變）
- 選單宣告：`network-plans.html` 從「設備管理」（已併除）移到「採購與庫存」群組（order 90），入口與權限不變；頁頭改用麵包屑規格（B6）。
- 前端視覺（D3）：本模組頁面內文字最小 12px（原有 9～11px 一律拉到 12px）；文字色改用語意 token（`--text-secondary` #595959／`--text-dim` #666666／深底 `--text-on-dark-dim` #A3A3A3，在頁底 #F5F4F0 上對比 ≥4.5:1）。只改 CSS 值，不改版面結構、不改 API、資料、權限。規格見 `docs/UI-HEADER-COLOR-SPEC.md`。
- 測試：`tests/test_e2e_nav_hierarchy_2026_11_11.py`（7 項真瀏覽器：每個舊入口仍可達、群組與報表中心頁籤、權限過濾、頁頭麵包屑）。

## 1.0.14 — 2026-10-16（wip/t68-c7-r1；C7 狀態顯示名稱）
- `pages/network-plans.html`、`pages/network-plan-form.html` 的狀態名稱改讀設定中心『網路規劃：狀態名稱』（預設＝規劃中／已確認／已交付，逐字相同）；`api.py` 刪除限制訊息與 `export.py` 規劃書匯出的「狀態」欄也跟著顯示名稱。狀態值與流程不變。

## 1.0.13 — 2026-10-14（wip/h2-pdf-hardening-r1；PDF 渲染硬化第二輪）
- 拓樸圖 PDF 匯出頁（`export.py`）的內嵌腳本字面值改成引用 `helpers/pdf_scripts` 註冊表常數；輸出逐位元相同（H2：CSP `script-src` 只認註冊表雜湊）。

## 1.0.12 — 2026-10-14（wip/t61-xl-safe-r1；匯出公式注入中和；網路規劃書匯出）；修正：xlsx 轉義可逆
- 匯出公式注入中和（資安小切片，無旗標）：網路規劃書匯出（封面、各分頁欄位、修訂紀錄）文字儲存格若以 `=` 開頭，前面補一個單引號，Excel 開啟時當文字、不再當公式（CWE-1236；openpyxl 只有 `=` 會被綁成公式，所以 `+886…`、`-VLAN10` 這類文字不加單引號、與今天相同）；真正的數字（含負數）不受影響，其餘儲存格逐格相同。無 migration、無新路由、無權限變更。匯入（`parse_plan_excel`）會還原匯出時補的那一個單引號（`xlsx_unescape`；補單引號的規則可逆，本來就以 '= 開頭的文字也不會被吃掉），匯出再匯入的文字逐字相同。

## 1.0.11 — 2026-10-13（wip/t57-download-name-p2-r1；A7 下載檔名第二期）
- 網路架構規劃表／規劃書／拓樸圖下載的 `Content-Disposition` 改用 `content_disposition()`（檔名不變，只統一編碼）。

## 1.0.10 — 2026-10-10（wip/t50-int；第 50 班）
- **（併入）(next) — 2026-10-09（wip/t49-strict-bool；W1c-P4）**
- `module.json` `provides.routes` 明列 `/api/quotations/{quote_no}/network-plan`（`modules.json` M10 本來就有）：它落在案件模組的 `/api/quotations` 前綴底下，demo 缺席訊息原本會把它算成案件的。行為只影響 demo 缺席提示；沒有端點／權限變更。

## 1.0.9 — 2026-10-09（wip/t49b-b5-netplan-writes）：規劃書寫入端點同套逐案權限
- ab 稽核補強：`PUT /api/network-plans/{id}`、`PATCH …/status`、`POST …/import/excel`、`POST …/privacy-notice/ack` 原本用裸 `SELECT … WHERE id=?`，沒有讀取端點的逐案權限——有 netplan_edit 但沒有該案權限的人讀得到 404、卻能改（200）；ack 回 409 還洩漏『存在』。現在四支都先過 `_load_visible_plan`（看不到＝404、什麼都不寫）。
- admin／最高管理者視為直通：案件列被刪掉時 `case.access.allowed` 回 False，不能讓規劃書從 admin 眼前消失（一般人員案件不在就不給看）。
- 測試：`test_netplan_visibility_t49.py` 新增三題（無案件權限的寫入 404 且資料列不變、擁有者與獨立規劃書照常可寫、案件被刪後 admin 仍看得到）。

## 1.0.8 — 2026-10-09（wip/t49-b5-visibility）：規劃書讀取加逐案權限（可見範圍收緊）
- `GET /api/network-plans`、`GET /api/network-plans/{id}`：綁定案件的規劃書改依「依案件查詢」同一道逐案權限——看不到該案的人（不是該案業務／協作者、不是 admin 以上、沒有 case_manage）清單看不到、單筆 404；沒綁案件的獨立規劃書與 admin／最高管理者不受影響。案件模組不在時，綁案件的規劃書只給 admin 以上。
- 補洞：Excel／PDF 匯出、拓樸預覽原本只驗登入（任何登入者可匯出任一份），現在要規劃書讀取模組（netplan／netplan_edit／case_manage）並套同一道逐案權限；個資告知查詢同樣套逐案權限。

## 1.0.7 — 2026-09-30（暫用號，列車取號；wip/w3-export-pdf）
- 匯出規則（使用者 2026-09-30）：網路規劃 Excel／PDF 匯出每次寫稽核（`export.xlsx`／`export.pdf`）。

## 1.0.6 — 2026-09-27 23:02（暫用號；H10 品牌設定，主持派工）
- 頁面的分頁圖示（favicon）改讀 `/api/system/branding/favicon`（L1 品牌設定，可在公司資料設定更換；沒上傳回預設圖）：`network-plans.html`、`network-plan-form.html`、`topology-quick.html`

## 1.0.5 — 2026-09-27（C，M01-PLAN §5 ④；列車取號）
- 頁面（稽核 D M4-M2，M01-PLAN §5 ④）：案件模組（M01）不在 ⇒ 新增規劃書的「綁定案件」停用並明說「案件模組未安裝：無法綁定案件（規劃書本身照常可建立）」，不再是空清單；e2e `tests/test_e2e_pages_without_case_module_2026_09_27.py`（含正對照）

## 1.0.4 — 2026-09-26
- 選單宣告搬進本模組：`network-plans.html` 的 `pages[].menu`（原寫在 L1 的 `core/menu_l1.json`；group／order／perm／badge 原值照搬）。階段 C／C4（主持裁示 A）：本模組不在時它的入口隨宣告一起消失，不再靠前端寫死的頁面⇒模組對照表；〔rebase 到 origin：h-probes 已取 1.0.3 ⇒ 本段 1.0.4〕

## 1.0.3 — 2026-09-26
- 宣告 `provides.probes`（D7 演練與產品演練打這幾支確認模組在；純讀、無副作用，D7-CHECKLIST §4）

## 1.0.2 — 2026-09-26
- 第四班列車：IP 定號（`daily.check` IP-10→IP-11、`case.access` IP-11→IP-12，cb4667b1）
- `module.json` 補 `customization`（本模組目前沒有可自訂點：寫出空類別＝有人決定過）

## 1.0.1 — 2026-09-26
- 快速拓樸的說明文字不寫死頁面路徑（頁面位置一律經 `core.source_tree`）

## 1.0.0 — 2026-09-26
- 模組化：`routers/network_plans.py` → `modules/netplan/api.py`、`routers/network_plans_quick.py` 併入同一檔、同一支 router、`network_plan_export.py` → `export.py`、`network_plan_topology.py` → `topology.py`；三份測試移入 `tests/`（PLAYBOOK §B）
- 對 M01 的兩個相依（案件逐案權限、讀案件客戶／專案名稱）改走 IP-12 `case.access`；M01 不在時規劃書照常，只是不能綁定案件，並明說
- 第四班列車：搬遷期間 origin 在舊檔新增的個資蒐集告知兩支端點（`GET /api/network-plans/{id}/privacy-notice`、`POST …/privacy-notice/ack`，e381fdd0）原樣移入 `api.py`
