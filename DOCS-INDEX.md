# DOCS-INDEX：現行文件總目錄

> 建立 2026-11-11。一行一份：**談什麼／現在的狀態／怎麼查證的**。
> 範圍：根目錄 `*.md`、`docs/*.md`、`docs/platform/` 直屬規格文件，另附各子目錄一行。**不逐份列** `docs/platform/plans/`、`prod-tasks/`（日期快照）、`audit/`（單次稽核）。
> 與 `docs/platform/UNIT-INDEX.md` 的分工：UNIT-INDEX 是**程式單位**索引（機器產生，勿手改）；本檔是**文件**索引（人維護）。

## 欄位怎麼讀

| 狀態 | 意思 |
|---|---|
| 規劃中 | 文件講的東西還沒做（或只做一部分，括號說明） |
| 已實作 | 文件描述的功能／流程存在於程式或正在使用 |
| 已廢棄 | 被取代或不再適用（本次盤點沒有找到整份已廢棄的；個別條目廢棄的以文內刪除線＋更正註記標出） |
| 現行 | 流程／參考／範本文件，沒有「實作與否」可言，仍在使用 |
| 快照 | 某一時點的盤點或報告，不隨程式更新；讀的時候要看日期 |

| 查證 | 意思 |
|---|---|
| **程式 11-11** | 2026-11-11 對照程式碼／commit／測試核對過（核對對象寫在備註） |
| 自述 ＋ 日期 | 狀態取自文件自己的標頭或內文，加上 `git log` 最後更動日；**沒有對照程式**，可能過時 |

**維護規則（使用者裁示，2026-11-11）：每次建立或修正活文件，同一個提交裡同步更新本檔對應那一行**（狀態、查證方式與日期）；不要建完就放著讓索引自己過期。

**這份索引不保證「自述」那一欄是對的。** 發現與程式不符就改本檔那一行，並在文件開頭加上更正註記（慣例：`~~舊句~~（**日期 更正…**）`，見 `docs/quick/known-limits.md`）。

---

## 根目錄

| 文件 | 主題 | 狀態 | 查證 |
|---|---|---|---|
| `DEPLOY.md` | 2026-09-22 版上線前要做的決定（標案雷達、地圖與距離、辦公室地址；預設關閉的開關） | 快照 | 自述 09-23 |
| `DR-SOP.md` | 災難復原 SOP | 現行 | 自述 10-09 |
| `GITFLOW.md` | Git 分支規則 | 現行 | 自述 07-22（較舊；多視窗現況以 MULTIWIN-PROTOCOL 為準） |
| `HTTPS-DEPLOY-CHECKLIST.md` | HTTPS 正式機套用步驟 | 現行 | 自述 08-28 |
| `LETSENCRYPT-PUBLIC-CERT-PLAN.md` | 公開受信任憑證（Let's Encrypt＋Cloudflare）讓 Passkey 免裝 CA | 規劃中（標頭：規劃完成、尚未執行） | 自述 09-11 |
| `PASSKEY-CA-ROLLOUT.md` | Passkey 啟用的憑證與 CA 佈署步驟書（含實測紀錄） | 已實作（步驟表逐項 ✅）；`backend/routers/auth.py` 有 Passkey 路由 | 自述 09-11＋路由存在 |
| `MOTRIX-ERP-ARCHITECTURE-MAP.md` | 架構地圖與模組建議書 | 快照（模組化之前的地圖；平台化後以 `docs/platform/` 為準） | 自述 10-09 |
| `MOTRIX-ERP-QUICK.md` | 開發快速參考中樞（拆出 `docs/quick/`） | 現行 | 自述 09-23 |
| `MULTIWIN-PROTOCOL.md` | 多視窗開發協定（派工、回報、閘門） | 現行 | 自述 09-30 |
| `NETWORK-PLAN-MODULE-DESIGN.md` | 網路架構規劃模組的設計與施做順序 | 已實作（標頭：已部署、DB v64；`backend/modules/netplan/` 存在） | 自述 08-26＋模組存在 |
| `SELLABLE-AND-MOBILE-SPEC.md` | 販售化與手機版兩條端到端細線 | 自述無狀態標頭，**未核對**（細線 1「授權閘門預設關／解凍前置」那一段 11-11 已更正：預設已改開、測試已補、**未部署**） | 自述 09-21；授權閘門段**程式 11-11** |
| `MODULE-AUDIT-2026-09-13.md` | 模組權限盤點（狀態、對接、邏輯） | 快照 | 日期在檔名 |
| `WEEKLY-AUDIT-2026-09-07_2026-09-10.md` | 一週更新拆解與異常排查索引 | 快照 | 日期在檔名 |
| `AGENT-HANDOFF-TEMPLATE.md` | 視窗交接紀錄範本 | 現行（範本） | 自述 09-10 |
| `CHANGELOG.md` | 根目錄變更記錄（7 行；單一來源已搬到 `docs/quick/changelog.md`） | 現行（轉址） | 自述 09-23 |

## docs/

| 文件 | 主題 | 狀態 | 查證 |
|---|---|---|---|
| `docs/MOTRIX_ERP_System_Plan.md` | 內部專案管理系統最初規劃（2026-07-09，「可開始第一階段」） | 快照（早期需求文件，已實作超出其範圍） | 自述 09-06 |
| `docs/UI-HEADER-COLOR-SPEC.md` | 選單、頁頭、語意色票、對比與字級規格 | 現行 | 自述 11-11（本日剛更動） |
| `docs/UI-REDESIGN-PLAN.md` | 介面轉換計畫書（套用官網 v4 設計語彙） | 自述無狀態標頭，**未核對** | 自述 10-09 |
| `docs/module-viz-mockup.html` | 模組視覺化示意稿（HTML，非文件） | 快照 | 未核對 |

## docs/platform/ 規格與準則

| 文件 | 主題 | 狀態 | 查證 |
|---|---|---|---|
| `CORE-SPEC.md` | 共用核心規格；**使用者裁示的唯一落點**（標頭 11-11 已更正：不再是草案；§3 以後是 09-25 條文原文，與現況不一致時以程式與「使用者裁示」為準） | 現行 | **程式 11-11**（模組分組已裁示、`modules.json` 為機器來源、91 次提交、多支測試引用） |
| `MODULE-GUIDE.md` | 模組開發準則（每條規則要有守門測試） | 現行 | 自述 11-08 |
| `PLAYBOOK.md` | 後續作業手冊（步驟式） | 現行 | 自述 10-13 |
| `ROADMAP.md` | 模組化路線圖與待辦；S-PLD12 已於 11-11 更正為已實作 | 現行（個別條目狀態以條目為準） | **程式 11-11**（S-PLD12：`core/migrations.py` `run_all()` SAVEPOINT，d9b90719b） |
| `DEPENDENCY-MAP.md` | 相依盤點與模組分組提案 | 快照（初版 09-26；機器版在 `dep_graph.json`／`modules.json`） | 自述 09-26 |
| `INTEGRATION-POINTS.md` | 模組串接點（IP-xx）登記 | 現行 | 自述 10-16 |
| `UNIT-INDEX.md` | L0／L1 程式單位索引（機器產生） | 現行 | `unit_index.py --check` 有守門測試 |
| `CACHE-INDEX.md` | 大文件快取索引 | 現行 | 自述 09-30 |
| `DATA-COMPAT.md` | 既有資料相容性盤點 | 快照（初版 09-25，10-08 更新） | 自述 10-08 |
| `CUSTOMIZATION-SPEC.md` | 網站內自訂：模組建構、拖曳排版、獨立升級 | **主體已實作**（標頭 11-11 已更正）。P6 `core/events.py`、P7 `module_update.py`、P8 `module-builder.html`＋`core/customization.py`（總開關預設關）、P9 `/api/layout`＋BP1 選單建構 | **程式 11-11**（只核對存在，未逐節核對與規格一致） |
| `BUILDER-UX.md` | 模組建構器拖曳式／縮圖化 UX | 已實作（頁面存在） | **程式 11-11**（只核對存在） |
| `STAGE-C-DESIGN.md` | 階段 C：頁面進模組資料夾、選單由登錄表產生 | **部分實作（標頭 11-11 已更正）**：C1～C4 已做（`core/pages.py`、`source_tree.page_file`、`/api/platform/menu`、sidebar 吃宣告）；C5 實體搬家**沒做**（46 個宣告頁 0 頁搬進 `modules/<key>/pages/`）；§7 決策點是否全有裁示未逐題核對 | **程式 11-11** |
| `COMPANY-SETUP-GATE.md` | 販售版本公司資料設定閘門 | **已實作**（E4，609fc0257；標頭 11-11 已更正）。`helpers/company_setup.py`、`main.py` 閘門、6 組 `test_company_setup_*`＋e2e；「停擺風險」列的 `LICENSE_GATE_ENABLED=False` 11-11 已更正（授權閘門預設已改開，未部署） | **程式 11-11** |
| `LICENSE-EMERGENCY-PASS.md` | 授權閘門：緊急放行通行證（簽發／安裝／確認／結束）、402 說明頁、env=dev 警告、風險 | **已實作**（T80，2026-11-11；`LICENSE_GATE_ENABLED` 預設開，**正式機未切換**） | 程式 11-11 |
| `LICENSE-IMPORT.md` | 授權匯入（T83）：授權頁／匯入端點／備份與還原／到期提醒（30、14、7 天）、安全設計與審查對照 | **已實作**（T83，2026-11-13；分支 `feat/license-import-ui`） | 程式 11-13 |
| `LODGING-NEARBY.md` | 地圖附近旅宿：來源調查與設計 | **已實作**（L2 模組 `lodging` v1.2.10；標頭 11-11 已更正） | **程式 11-11**（模組、migration、頁面、測試存在；§5 未查證各項未重核） |
| `GOOGLE-BASEMAP.md` | Google 底圖：計費、條款、做法比較 | 已實作（文內已更正，採 Maps JavaScript API；`helpers/geo.py`、`routers/map_points.py`） | 自述更正 09-28＋程式存在 |
| `MONEY-FLOWS.md`／`FINANCE-INTEGRATION.md`／`LEDGER-ACCEPTANCE.md` | 金流串接覆蓋表／財務串接總覽（快取）／總帳端到端驗收 | 現行（`money_flows.json` 有守門） | 自述 10-01～10-10 |
| `TAX401-OFFICIAL-FIELDS.md` | 營業稅 401 欄位代號官方核對表 | 現行 | 自述 10-01 |
| `THIRD-PARTY-LICENSES.md` | 隨產品散布的第三方元件授權清單 | 現行（有守門） | 自述 09-30 |
| `BENCHMARK.md` | 競品與法規對標 | 快照 | 自述 09-25 |

## docs/platform/ 更新、升級、交付

| 文件 | 主題 | 狀態 | 查證 |
|---|---|---|---|
| `UPDATE-DELIVERY.md` | 雲端交付＋正式機一鍵套用（簽章、staging、驗證、回滾） | **已實作**（09-28 上車；標題與狀態區塊 11-11 更正） | **程式 11-11**（commit 對照在文件開頭） |
| `MODULE-UPDATE-DELIVERY.md` | 單一模組更新包：簽章交付＋正式機同等保護 | **已實作**（09-28～29 上車；標題與狀態區塊 11-11 更正） | **程式 11-11**＋實跑演練 [`plans/MODULE-UPDATE-MIGRATION-DRILL-20261111.md`](docs/platform/plans/MODULE-UPDATE-MIGRATION-DRILL-20261111.md) |
| `MODULE-UPDATE-PROD-INSTRUCTIONS.md` | 給正式機 Claude 的單模組套用指示範本（回滾參數未定稿前不可交出） | 現行（範本，附使用條件） | 自述 09-28 |
| `UPGRADE-RUNBOOK.md` | V9→新版升級轉換與回滾手冊（對正式機執行是使用者的動作） | 已實作（`tools/platform/upgrade.py`、`core/upgrade.py`、`upgrade_drill.py` 存在） | 自述 10-08＋工具存在 |
| `D7-CHECKLIST.md`／`FINAL-DRILL-REPORT.md` | D7 正式轉移升級演練檢核清單／演練報告（c006a2a0，13 份包） | 現行（清單）／快照（報告 09-27） | 自述 |
| `PROD-DEV-CHANNEL.md` | 開發機↔正式機 Claude 溝通協定 | 現行 | 自述 10-10 |
| `TRAIN-PREFLIGHT-T47.md` | 列車預檢（一個指令列出便宜的紅燈） | 已實作（`tools/platform/train_preflight.py` 存在） | 自述 10-08＋工具存在 |
| `BUILD-VERIFY-OPTIMIZATION-T47.md` | 建包與驗證時間優化（≤30 分鐘） | 規劃中（標頭：待主持／使用者裁示；後續另有 `build_log_report.py`、`preflight_seconds.json`，是否採納未核對） | 自述 10-08 |
| `PO-VENDOR-BANK-GAP-T47.md` | 採購單廠商銀行資料缺口：選項與建議 | 已實作（使用者已裁示；`FULL_ACCOUNT_STRICT` 相關 commit 已合） | 自述 10-08＋commit |
| `WRITE-ENDPOINT-LOCK-AUDIT-T79.md` | 案件模組 99 條寫入路由的樂觀鎖覆蓋稽核＋「token 選填要不要強制」建議 | 稽核結果（2026-11-11；已修自動存檔無聲 409，其餘缺口待另開票） | 本票分支 `feat/draft-optimistic-lock` |

## docs/platform/ 作業與紀錄（日期快照）

| 文件 | 主題 | 狀態 | 查證 |
|---|---|---|---|
| `RUN-PLAN.md` | 使用者離開期間的總計畫與當班進度（§6 持續更新） | 現行（最新至第 75 班） | 自述 11-04 |
| `RUN-LOG.md` | RUN-PLAN §6 進度封存（最新在上） | 快照（最後封存 09-27） | 自述 09-27 |
| `IMPROVEMENT-REPORT.md` | 交叉稽核彙整改善報告 | 快照（09-27 最終狀態，11-04 補記） | 自述 11-04 |

## 子目錄

| 位置 | 內容 | 狀態 |
|---|---|---|
| `docs/quick/` | `MOTRIX-ERP-QUICK.md` 拆出的各主題快速參考（`changelog.md` 為變更摘要唯一來源；`known-limits.md` 為已知限制，更正慣例的範本） | 現行 |
| `docs/reference/` | 官方參考檔（商業會計項目表、傳票實例；`.sha256`） | 現行 |
| `docs/windows/` | 多視窗時期各視窗的待辦佇列、交接與稽核（87 檔） | 快照（日期在內文） |
| `docs/platform/plans/`、`prod-tasks/`、`audit/`、`runplan/`、`archive/` | 各班計畫、正式機任務單、單次稽核、RUN-PLAN 分檔、封存 | 快照 |
| `docs/platform/states/` | `STATES-PLATFORM.md`（2026-09-25 快照）、`STATES-DATA-OPS.md` | 快照 |
| `docs/platform/*.json` | 機器可讀登記表（modules、dep_graph、money_flows、mustfix_*、pii_forms…），由工具或守門測試維護，不手改 | 現行 |

---

## 待更正事項

1. ~~`CUSTOMIZATION-SPEC`、`COMPANY-SETUP-GATE`、`LODGING-NEARBY` 標頭說「尚未實作」~~、~~`CORE-SPEC`「草案 v0.1」~~、~~`STAGE-C-DESIGN`「草案，待裁示」~~：**2026-11-11 已更正**（MOTRIX-ERP 同意；STAGE-C 寫明「C1～C4 已做、C5 沒做」，沒有改成「已實作」）。
2. `STAGE-C-DESIGN`：§7 決策點 D1～D4 是否全有書面裁示、`sidebar.js` 的 `_FILE_MODULE` 殘留是否已被宣告取代，未逐項核對。
3. `GITFLOW.md`（07-22）：多視窗時期以 `MULTIWIN-PROTOCOL.md` 為準，內文未註明。
4. 「自述」欄全數**沒有**對照程式逐項核對；`SELLABLE-AND-MOBILE-SPEC.md`、`UI-REDESIGN-PLAN.md` 連狀態標頭都沒有。
