# 文件同步：平台層（node-39，第 52 班；僅文件）

分支 `wip/t52-n39-docsync`，基底 `origin/platform` `cab72495d`。派工：node-d8（使用者授權加入派工行列）；與 05 分工——05 做模組 SPEC／README／IP 段，這一份做平台層四份文件。**只改文件；沒有改程式、測試、產生檔、RUN-PLAN §6、CACHE-INDEX。**

## 一、這次改了什麼

| 文件 | 改動 | 主要來源（可自己驗） |
|---|---|---|
| `PLAYBOOK.md` | 新增 **§G7 一班列車的實際流程（第 46～51 班）**：整合分支、取號時機、`regen_all`、預檢、凍結 head 與官方閘門（`run-stage`）、獨立稽核與必修重跑、發布、基準 commit 與 `prod/*` tag；§G3 標題下加一行註記指向 §G7。**CACHE-INDEX 已過期**的說明也寫在 §G7 末段。 | RUN-PLAN §6 第 44～50 班各筆；`git log origin/platform` 第 45～50 班；`TRAIN-PREFLIGHT-T47.md`；`backend/tools/build_test_reuse.py` 檔頭；`prod-tasks/*-train4[6-9]/50-apply.md` |
| `MODULE-GUIDE.md` | 新增 **§14 端點與資料規則**：14.1 旗標只收真布林（`strict_bool`／`body_flag`）、14.2 逐案可見範圍讀寫都要守、14.3 寫入端點稽核與 `EXEMPT` 規矩、14.4 不用命令列比對結束行程、14.5 利潤口徑的 `formulaVer`／`STAMP_KEYS` 戳記規則；§1.1 補一行指向 §14.2。 | `helpers/validation.py`；`plans/VISIBILITY-TIGHTENING-T49.md`、commit `2f53a5f22`；`tests/test_write_endpoints_are_audited_2026_09_24.py`、commit `9c1b067a9`；`helpers/profit_rules.py`、`modules/case/profit_guard.py` |
| `PROD-DEV-CHANNEL.md` | 檔頭主持與正式機 Claude 代號更新；§1 回報資料夾後綴補「待使用者確認」與作業名命名；§4 第 6 步補步驟檔存檔與指向 §G7；新增 **§6 自動套用授權、§7 寫入正式資料要使用者本人確認（管銷切換先例）、§8 使用者外出規則**。 | 各班步驟檔「授權」與「停止條件」段；正式機回報 `20261010_003000_管銷切換_待使用者確認`、`…010500_管銷切換_成功`；RUN-PLAN §6 2026-09-30 11:24 與 2026-10-09 各筆 |
| `MONEY-FLOWS.md` | 新增 **§10 利潤口徑**：新舊口徑算式表、管銷＝直接毛利×比率（預設 25%、每張報價單一個、只有最高管理者能改）、五項舊間接成本在新口徑被忽略、對獎金與報表的影響、已上線狀態（2026-10-10 00:59 切 v2）、**第 52 班公益捐款改報價含稅 1%（預定，標明尚未上線）**。既有編號與表一字未動（`test_money_flows_registered` 綁編號）。 | `plans/OVERHEAD-25PCT-OPERATING-PROFIT-DESIGN-T48.md`、`CUTOVER-RUNBOOK-T48.md`；`profit_rules.py`、`profit_guard.py`、`api/overhead.py`；`origin/wip/t52-ab-charity-quote` 上的 `CHARITY-QUOTE-1PCT-DESIGN-T52.md` |

換行：這個 repo 的文件是 LF（`.gitattributes` `eol=lf`），四份都維持 LF、無 CR。

## 二、發現過期但沒有動（需要有人決定或有工具才能動）

1. **`CACHE-INDEX.md` 摘要過期**：**沒有產生工具**（它是手寫摘要，`regen_all.py` 只產 `dep_graph.json`／`UNIT-INDEX.md`／`test_map.json`）。依來源 commit 計算落後（`git rev-list --count <sha>..HEAD -- <檔>`，守門門檻 8）：`PLAYBOOK.md` 17（>8，守門警告）、`MODULE-GUIDE.md` 5、`FINANCE-INTEGRATION.md` 3、`CORE-SPEC.md` 2、`MULTIWIN-PROTOCOL.md` 1、`docs/quick/architecture.md` 1。這次 PLAYBOOK／MODULE-GUIDE 又各加一個 commit，PLAYBOOK 摘要要重寫並納入 §G7，MODULE-GUIDE 摘要納入 §14。守門只警告不擋合回。
2. **PLAYBOOK §G3／§G4 的細節是第九～十班的做法**（每小時一班、`train/<時間>`、`D:\MOTRIX-PLATFORM-TRAIN<N>`、列車長子代理用 sonnet）。我只在 §G3 標題下加註指向 §G7，沒有改寫或刪除原文（好幾處是被刪線的歷史、且 §G6 的規則仍有效）。後續可把 §G3／§G4 瘦身。
3. **PLAYBOOK §D「發行與正式換版（使用者執行，儀表板操作）」**仍把換版寫成使用者在儀表板逐步按；第 46 班起實際是正式機 Claude 依步驟檔自動套用（PROD-DEV-CHANNEL §6）。兩套並存，沒有明確說「何時用哪一套」。需要主持決定怎麼寫。
4. **PLAYBOOK.md 83KB、MODULE-GUIDE 51KB、PROD-DEV-CHANNEL 12KB**：前兩份超過「文件 > 40KB 要拆」的使用者規則；這次沒有拆（拆檔牽動 `test_core_only_rc` 讀 §B-11、CACHE-INDEX 守門與大量引用），只新增在尾端。
5. **PROD-DEV-CHANNEL §3**「`prod_status_snapshot.py` 隨下一個部署包進正式機，之前的快照改人工逐項查」：該工具早已在部署包內、`status\latest.json` 也在用，這句多半已過期；但我無法在不連正式機的情況下確認，沒有刪。
6. **RUN-PLAN §6 有 35 筆**（規則：只留最新 20 筆、超過 40 筆封存到 RUN-LOG）。依 node-d8 的指示 §6 由基準腳本維護，我沒有動。

## 三、寫進文件但來源不是 repo 檔（node-d8 已於 2026-10-10 確認並要求更正，已改）

- **§14.4 的事故**：來源是主持的離開日誌（不在 repo）。主持更正為 2026-10-09 約 19:50（不是 20:20）、一次結束 8 個行程、其中 2 個不明確是自己的；規則＝只依精確的自己的 PID 結束。已照改。
- **PLAYBOOK §G7 第 4～5 節**：腳本在 `C:\Users\hichan\`（不在 repo），我沒有讀到腳本本身；主持確認規則如實，並補上 fail-closed 前置條件與基準推送的 fast-forward／docs-only 守門，已寫入 §G7。
- **§G7 第 2 節** 的 worker 數與題數取自 RUN-PLAN §6 各班一筆；「官方 e2e 單獨跑、不與 not_e2e 並行、not_e2e 3 個 worker」是主持自第 47 班起的成文規則（寫在主持筆記，repo 內原本沒有），已在 §G7 寫成規則。
- **MONEY-FLOWS §10.4**（第 52 班公益捐款）依規格摘要，規格在 `origin/wip/t52-ab-charity-quote`，尚未進 `platform`；上線後要依程式更新本節（已在節內註明）。
- 沒有核對的：`prod-tasks/TEMPLATE-apply.md` 是否已反映 §6（授權段）的寫法；`MULTIWIN-PROTOCOL.md` 內是否仍寫主持為 `node-bb`。

## 四、驗證

- 已做：`git diff --check`（無空白錯誤）、四份文件無 CR、新增章節編號不撞既有編號、被守門綁定的段落（`PLAYBOOK` §B-11、`MONEY-FLOWS` 覆蓋表與編號、`MODULE-GUIDE` 規則段）未動。
- 未做（依 node-d8 指示，閘門未結束前不跑 pytest）：`test_cache_index_fresh`、`test_money_flows_registered`、CHANGELOG／文件類守門。待放行後只跑單行程輕量題。
