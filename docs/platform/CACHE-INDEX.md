# 大文件快取索引（CACHE-INDEX）

> 用途（PLAYBOOK §G-瓶頸，使用者 2026-09-30）：常被重讀的大文件，先讀這裡的 10 行摘要＋章節索引，需要細節再開原檔的那一節，
> 降低每個 session 的重讀成本。**摘要是快取，不是真相**：每一段都標「來源 commit」；原檔之後改動的 commit 數超過門檻時，
> 守門題 `tests/platform/test_cache_index_fresh.py` 會**警告**（不擋合回）——看到警告就重讀原檔對應章節、更新摘要、換來源 commit。
> 機器可讀行格式（守門解析）：`- 來源檔：<路徑>｜來源 commit：<sha>`。門檻 N＝**8**（同一檔改了 8 次以上就該更新）。

---

## CORE-SPEC（75KB）

- 來源檔：docs/platform/CORE-SPEC.md｜來源 commit：4fe94185
- 摘要：MOTRIX-PLATFORM 共用核心規格。分三層：L0 平台（`backend/core/`，載入器、登錄表、migration）、L1 共用核心（`helpers/`、`routers/`）、L2 業務模組（`modules/<key>/`，宣告在 `module.json`）。
  模組之間**只經 provider（IP-*）串接、不互相 import**；底層穩定契約＝同一主版號內只准新增。資料庫由凍結的 V9 migration 建基礎表，模組自己的 migration 從 1 起連續。
  §9b 升級轉換與回滾（V9→新版）、§9c 模組選配（匯出前選擇、裝好後啟停）、§9e 部署儀表板、§9d 交叉稽核。「使用者裁示」節是**規則的最高權威**（衝突時以它為準）。
- 章節索引：§1 目標與驗收｜§2 分層｜§3 模組目錄結構｜§4 module.json｜§5 模組間串接｜§6 資料庫｜§7 端點登錄表｜§8 測試分層｜§9 遷移步驟｜§9b 升級轉換與回滾｜§9c 模組選配｜§9e 部署儀表板｜§9d 交叉稽核｜§10 環境｜使用者裁示（2026-09-25 起）｜已知問題

## MULTIWIN-PROTOCOL（77KB）

- 來源檔：MULTIWIN-PROTOCOL.md｜來源 commit：85237966
- 摘要：多視窗（多個 Claude session 並行）開發協定。每個視窗開工先讀它再讀自己的視窗檔。角色：A 彙整／排程、B／C 執行、D 稽核副手、A-2 共同校驗。
  一輪七步（§4）；硬規則（§5）與一長串「通則」§5a～§5t（訊息只是規則的副本、狀態旗標不可蓋過真實狀態、證據存在≠證明你以為的事、不要用 `git checkout --` 還原檔案、
  長跑用 detached worktree、回報綠燈附工作樹是否乾淨、沒收到回覆三分鐘後重送…）。檔案佔用（§3）是撞車防線；停機條件（§6）；四段式回報格式在最後。
- 章節索引：§1 為什麼｜§2 角色（§2b 視窗 D、§2c A-2）｜§3 檔案佔用｜§4 一輪七步｜§5 硬規則（§5a～§5t 通則）｜§6 停機條件｜§7 兩條端到端細線｜四段式

## MODULE-GUIDE（41KB）

- 來源檔：docs/platform/MODULE-GUIDE.md｜來源 commit：eebad525
- 摘要：模組開發準則，每條規則要有守門測試（沒有的標「⚠ 未守門」）。底層不動、模組各自長；資料分類與存放（§3：T1／T3、F2 等）；migration（§4）；
  標準資料夾結構（§5）；每個模組獨立的 CHANGELOG＋`module.json` 版號（§6，改程式沒升版守門會紅）；測試分層（§7）；新增模組步驟（§8）；匯出選配（§9）；
  模組更新包（§10）；法規參數（§11）；信件通知收件人（§12）；**金流串接（§13，2026-09-30：新模組有金額就必須登記 `money_flows.json`＋MONEY-FLOWS.md）**。
- 章節索引：§0 核心概念｜§1 分層與相依｜§2 底層穩定契約｜§3 資料分類｜§4 資料庫與 migration｜§5 資料夾結構｜§6 更新紀錄與版本｜§7 測試｜§8 新增模組｜§9 產品選配｜§10 模組更新包｜§11 法規參數｜§12 信件與通知｜§13 金流串接

## PLAYBOOK（50KB）

- 來源檔：docs/platform/PLAYBOOK.md｜來源 commit：ffffc071
- 摘要：後續每項工作的步驟手冊（「怎麼做、做到哪算完成」；做什麼看 ROADMAP）。A 整體順序（八階段）、B 把模組搬進 `modules/`、C 每項工作共通規則（選題 `modtest --changed-since`、rebase 後的重跑判定、版號／CHANGELOG／manifest、
  不追著 platform 跑全量、簿記檔衝突規則…）、D 發行與正式換版（使用者執行）、E 交叉稽核、F 什麼事要問使用者、G 長期運作（驗證四層⓪～④、送測前自查 §G5、瓶頸與快取 §G-瓶頸）。
  全量由**列車**跑，各線只跑差異題＋`tests/platform`＋改到頁面的 e2e。
- 章節索引：A 整體順序｜B 搬模組｜C 共通規則（C-11 選題／rebase）｜D 發行與換版｜E 交叉稽核｜F 什麼要問使用者｜G 長期運作（G1 四層、G3 列車、G5 自查、G-瓶頸）

## docs/quick/（各檔 3～10KB，原 QUICK 系列）

- 來源檔：docs/quick/architecture.md｜來源 commit：7128f6a5
- 摘要：給人快速上手的分主題短文（架構、資料模型、API 核心、各業務模組 mod-*、備份與部署 ops-*、安全、已知限制、變更紀錄）。與 `docs/platform/` 的規格互補：quick 是「現況導覽」，platform 是「規則與裁示」。
  兩者衝突時以 platform 的規格與 CORE-SPEC「使用者裁示」為準。
- 章節索引：architecture｜data-model｜api-core｜mod-case／mod-quotation／mod-contractor／mod-crm／mod-inventory／mod-shipping／mod-selection-guides｜ops-backup／ops-deploy｜security｜known-limits｜changelog*

---

## 維護

- 新增大文件（>40KB 且常被重讀）＝在這裡加一段（摘要 10 行內、章節索引、來源檔＋來源 commit）。
- 更新摘要時：重讀原檔改動的章節 → 改摘要 → 把「來源 commit」換成該檔目前最新的 commit（`git log -1 --format=%h -- <檔>`）。
- 文件 >40KB、程式 >1500 行要拆（PLAYBOOK §G-瓶頸）：RUN-PLAN §6 舊紀錄已搬到 `docs/platform/runplan/`。
