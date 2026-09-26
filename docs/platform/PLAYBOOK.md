# 後續作業手冊（PLAYBOOK）

> 用途：後續每一項工作都照這份的步驟做，不需要依賴誰記得什麼。
> 依據：規格 `CORE-SPEC.md`（使用者裁示以此為準）、準則 `MODULE-GUIDE.md`、路線圖 `ROADMAP.md`。
> 本檔只寫「怎麼做、做到哪裡算完成」；要做「什麼」，看 ROADMAP。

---

## A. 整體順序（從現在到正式換版）

| 階段 | 內容 | 進入條件 | 完成條件 |
|---|---|---|---|
| 1 | 收尾進行中的工作：模組啟停與授權（9c②③）、準則守門 G1／G2、匯出選配（9c①）、跨領域寫入改走連接器（A11） | — | 各自合回 platform，並跑過一次全量 |
| 2 | 儀表板接上 D3 選配打包、D5 模組狀態 | 階段 1 完成 | 瀏覽器實測通過 |
| 3 | 交叉稽核（CORE-SPEC §9d）→ 改善報告 → 修完必修項 | 階段 2 完成 | 必修項全部關閉，且都有測試守住 |
| 4 | 清完 L1 的逆向依賴（ROADMAP 階段 A 剩下的 A8b、A8c、A9、A10、A12） | 階段 3 完成 | `dep_scan --check-modules` 的 L1→L2 逆向 import 歸零 |
| 5 | L2 模組逐一搬進 `modules/`（ROADMAP 階段 B 的順序，每個模組照 §B 的步驟） | 階段 4 完成 | 11 個模組都在 `modules/` 底下，而且每個都通過「拿掉照常運作」的反向控制 |
| 6 | 前端跟著模組走（ROADMAP 階段 C）：頁面進模組資料夾、選單由登錄表產生 | 階段 5 完成 | 關閉模組後選單消失、頁面回 404 |
| 7 | 換版演練：用正式機資料的**複本**（由使用者提供）在開發機完整跑一次升級與兩種回滾 | 階段 6 完成 | 演練報告：每一步的耗時、雜湊比對結果、回滾結果 |
| 8 | 正式換版（**使用者執行**）：照 §D | 使用者決定日期 | 換版後觀察一週，沒有問題才刪除 V9 的備份 |

**與階段 4～6 並行：ROADMAP 階段 P（自訂與獨立升級的底層串接點，CUSTOMIZATION-SPEC §5）。** 每搬一個模組，就順手把它登記進能力目錄（P1），並在 module.json 描述可自訂點（P3）。這一步不做，之後網站內自訂就得回頭改每一個模組。
第二階段（自訂模組引擎 P8、拖曳排版器 P9）的規格已經在 CUSTOMIZATION-SPEC；等階段 6 與 P1～P7 完成之後才開工。

---

## B. 把一個業務模組搬進 `modules/`（每個模組都一樣）

**開工**
1. 回報你的工作目錄。建立 worktree：`git worktree add ..\MOTRIX-PLATFORM-<視窗> -b wip/<視窗>-<模組> platform`。
2. 讀 `DEPENDENCY-MAP.md` 裡這個模組的成員、擁有的表、跨組相依。再重跑一次掃描確認現況：`python tools/platform/dep_scan.py --check-modules`。

**先切相依，再搬檔**
3. 每一條跨組相依，擇一處理：下沉 L1，或由對方公開 provider（`core.registry`）。每一條都要登記進 `INTEGRATION-POINTS.md`，六項寫齊。
4. 「對方不在時」只能是「少一個功能，並且明白告知使用者」，不可以壞掉，也不可以悄悄略過。
5. 跨組直寫的表改走擁有者的連接器，並刪掉 `table_write_exceptions` 裡對應的那一筆 debt。

**搬檔**
6. 用 `git mv` 把 router、helper、頁面、測試搬進 `modules/<key>/`（結構照 MODULE-GUIDE §5）。
7. 寫 `module.json`（key、version、core 範圍、license_key、permissions、data 分類、provides）、`README.md`、`CHANGELOG.md`、`SPEC.md`（規格條件編號）。
8. 資料位置一律用 `core.paths`；模組資料夾裡不放資料檔。
9. 修正所有 import 與測試路徑；守門的掃描範圍一律用 `core.source_tree`。

**驗證**
10. 跑受影響的題目：`python tools/platform/modtest.py`，並跑 `tests/platform/`。
11. 反向控制：在另一個 worktree 刪掉這個模組的資料夾，伺服器要能啟動、ping 200、該模組的端點回 404；其餘測試除了「modules.json 列了但掃描不到」這一題，全部要綠。〔補充（2026-09-26 04:58 主持，D 稽核 M12）：允許紅的**產生檔一致性題**另加一題 `test_unit_index_is_current`（UNIT-INDEX 會反映實際的樹，拿掉模組之後，直接使用者數會變，這是預期的）。除此之外沒有其他例外；需要該模組才能跑的題，一律要搬進模組的 tests/。〔補充（2026-09-26，稽核 AUDIT-D-B-maps BM-M2，主持裁示 (a)）：產生檔一致性三題 `test_generated_maps.py::test_dep_graph_json_is_current`、`::test_test_map_json_is_current`、`::test_modules_json_has_no_ownership_errors` 同屬這一類（檢查產生檔與「完整的樹」一致），允許紅；它們的過期檢查由「模組全在」的那一輪負責，`::test_rc_the_three_guards_do_go_red_on_a_full_tree` 證明那一輪會紅。`tools/platform/core_only_rc.py` 的 ALLOWED 同步〕**反向控制的範圍**：tests/platform＋所有提到該模組的測試檔（grep 模組 key 與路徑），不可以只跑 tests/platform〕〔補充（2026-09-26 06:13，D 稽核 M10-S1）：反向控制的 pytest 一律帶 `--continue-on-collection-errors`，**收集錯誤也算不過**；模組拿掉之後，import 不到的測試檔會在收集階段就失敗，不帶這個參數會整輪中斷，看起來像「沒有紅」〕〔補充（2026-09-26，B M08 補 L1 連線守門時查到）：測試要判斷「某個路由有沒有註冊」一律用 `tests._routes.all_routes(app)`，**不可以直接讀 `app.routes`**——FastAPI 0.14x 的 include_router 要攤平才看得到路徑，直接讀會讓「擁有者不在 ⇒ skip」的題目在擁有者明明在的時候也假 skip；並配一題正對照（篩選看得到確定存在的路由）〕
12. 對「對方不在時」的處理做突變驗證：拿掉降級判斷，測試要紅。

**合回**
13. `git rebase platform`，重跑受影響的題目，再 `git merge --ff-only`。
14. 更新 `modules.json`、`ROADMAP.md` 的狀態，並在模組的 `CHANGELOG.md` 記下這一版。
15. 回報主持人：commit、題數、突變結果、反向控制結果，以及還沒處理的事項。

---

## C. 每一項工作的共通規則（不論大小）

| # | 規則 |
|---|---|
| 1 | 會跨多個檔的改動，一律在自己的 worktree＋分支做；共用工作樹只放合併後的結果 |
| 2 | commit 一律用 `git commit -- <路徑>`，不用 `git add -A`、`.` 或整個目錄 |
| 3 | pytest 一律帶自己的 `--basetemp`，跑完刪掉，只刪自己的，不用萬用字元批次刪除 |
| 4 | 改 L2 模組只跑受影響的題；~~改 L1 或 fixture 層（conftest、pytest.ini、requirements）就跑全量，並且在 detached worktree 裡跑~~〔更正（B，2026-09-26，稽核 D b-rebasecheck；主持裁示 §G3）：**各線不自己跑全量**——影響大（帶進 fixture 層／程式碼衝突、或本分支自己動 fixture 層）時，差異題擴大到那些檔＋`tests/platform`＋改到頁面的 e2e，**全量交給列車跑一次**；月台登記註明那幾個檔，帶進／動到 fixture 層的包排在列車最前面〕 |
| 5 | 每一條新規則都寫進 MODULE-GUIDE，並配一個守門；還沒有守門的，標「⚠ 未守門」，排進 ROADMAP 階段 G |
| 6 | 守門要有正對照與反向控制；正對照不可以綁在特定的 L2 模組上 |
| 7 | L0／L1 介面有新增就升次版號（`CORE_VERSION`），有修改或刪除就升主版號，並寫進 `backend/core/CHANGELOG.md`。**版號在合回時才定**（2026-09-25，一晚撞號三次：9c 修正、R、A2 都拿 1.5）：分支裡先寫「待定」或暫用號碼，rebase 到 origin 當下取「origin 的下一號」，並重產 G1 快照；規格章節編號（CUSTOMIZATION-SPEC §N、MODULE-GUIDE §N、IP-N）同樣在合回時對照 origin 再定。**工具**（B，2026-09-26）：rebase 之後跑 `python tools/platform/core_bump.py`（只列出，exit 3＝要改），確認後加 `--apply`：依 origin 的 CORE_VERSION 把我的 CHANGELOG 段落重新編號（依介面差異取次／主版號、標題註記暫用號）、改 registry、由 origin 的快照重產 G1 快照；rebase 停在 CHANGELOG 衝突時先 `git checkout origin/platform -- backend/core/CHANGELOG.md`（⚠ 不用 --ours／--theirs：rebase 時兩者的意思與 merge 相反，--theirs 是**我的** commit），再以 `--mine <rebase 前的分支尖端>` 指定我的段落。介面變了卻沒寫 CHANGELOG ⇒ 工具拒絕（不替人寫內容） |
| 8 | 長時間的動作，開跑時就回報「跑什麼、預估多久、死線」，死線＝預估×1.5 |
| 9 | 回報錯了就更正，而且要保留原本那一句錯的內容 |
| 10 | 不連線、不寫入正式機；正式機的動作一律由使用者執行 |
| 11 | **不要追著 platform 跑全量**（2026-09-25）：分支在基準 X 上跑過全綠的全量之後，rebase 到 Y 時，如果帶進來的 commit 都已經各自驗證過，而且程式碼沒有衝突，就只跑 `modtest --changed-since X` 加 `tests/platform`，然後合回；回報時寫明「全量在 X，差異題在 Y」。~~例外：差異裡有 fixture 層，或有程式碼衝突 ⇒ 重跑全量。~~〔更正（B，2026-09-26，稽核 D b-rebasecheck；主持裁示 §G3）：**各線不自己跑全量**——影響大（帶進 fixture 層／程式碼衝突、或本分支自己動 fixture 層）時，差異題擴大到那些檔＋`tests/platform`＋改到頁面的 e2e，**全量交給列車跑一次**；月台登記註明那幾個檔，帶進／動到 fixture 層的包排在列車最前面〕**補充（B 提出）**：rebase 帶進來的別人的差異，已在對方自己的全量驗過，而且和本分支的檔案不重疊 ⇒ 只跑「本分支自己的差異題」（`modtest --base platform`）加 `tests/platform`，不用照字面跑 `--changed-since`（字面上可能等於全量）。〔更正（B，2026-09-26 00:31）：`--base platform` 在本分支自己改過 fixture 層時一定被 modtest 拒絕（它看到 conftest 就要求全量），實際踩到。應跑 `modtest --changed-since X`：rebase 之後 X 與 HEAD 兩棵樹的差＝帶進來的＋全量之後才改的，本分支已驗過的部分不在其中；「字面上等於全量」只在帶進來的量很大時成立〕〔再更正（B，2026-09-26 00:40）：上一句也錯了。帶進來的是 A 改 L0 `core.source_tree` 時，`--changed-since X` 實測挑出 90.7%。正確集合是「全量之後本分支才改的檔」＝(X 與 HEAD 兩棵樹的差) − 帶進來的檔；`modtest --rebase-check X` 會算出這份清單並印出 `modtest --files …`，rebase 之前執行則拒絕給建議（exit 2）〕。**簿記檔**（B，2026-09-26，主持派工）：`backend/core/registry.py`、G1 快照、`backend/version_manifest.json`、`docs/platform/modules.json` 每次合回都會兩邊一起改，**只在同一個項目被兩邊改時才算衝突**——registry 扣掉 CORE_VERSION 那一行後兩邊都還有別的改動；快照同一個「單位::名稱」（core_version 不算）；manifest 同一筆條目（以 version 為鍵）；modules.json 同一個「群組／欄位／單位」。rebase 之後才改的（core_bump）以 onto..head 比對帶進來的。任一側讀不到或解析不了 ⇒ 保守判衝突。其餘程式檔照舊「同檔即衝突」發行前的全量照 §D，另外在發行的那個 commit 上跑。**判定工具**（B，2026-09-26）：`python tools/platform/modtest.py --rebase-check <X> [--onto origin/platform]`，會列出帶進來的 fixture 層、兩邊都改的程式檔（兩邊都改的 .md 只列出、不算），~~exit 3＝要跑全量~~〔更正：exit 3＝影響大（差異題擴大＋月台註明），不是跑全量；輸出寫明「全量交給列車（§G3）」〕；只判斷帶進來的部分，本分支自己改的 fixture 層仍照第 4 條（第 4 條同步更正） |
| 12 | **刪除共用目錄之前先查占用**（2026-09-25，B 弄壞 `.venv` 之後）：venv、主工作樹、暫存、部署包目錄都可能有別的 session 在用。刪之前先查（`Get-CimInstance Win32_Process | ? { $_.ExecutablePath -like '<路徑>*' -or $_.CommandLine -like '*<路徑>*' }`，或 `handle.exe <路徑>`）；有人在用就不刪，改用新路徑。⚠ 遞迴刪除「失敗」時，失敗點之前的檔案**已經刪掉了**：報錯後第一件事是盤點剩下什麼，並通知可能受影響的一方 |
| 13 | **全機測試負載上限**（2026-09-25 23:15〔更正：實際約 23:10，時間寫早了〕，使用者回報 CPU 100%：同時 7 組 pytest、49 個 python、70 個 headless 瀏覽器）：①整台機器同時最多 **2 組全量**〔更正（原寫 23:4x，實際 23:33；時間必須先跑 `date` 再寫，這是今晚第三次寫早。C 回報）：測試鎖一次只放 1 組全量 ⇒ 實際是「鎖內 1 組全量＋鎖外最多 1 組差異題（-n 2）」；全量排隊以 RUN-PLAN §5 的名額行為準〕〔再更正（2026-09-26 00:13，B 查證程式碼）：上面那句更正是錯的。conftest 的 `MOTRIX_PYTEST_SLOTS` 預設 2，鎖檔有 `.lock` 與 `.lock.slot2` ⇒ **確實是 2 組全量同時跑**，以程式碼為準；C 當時會被擋，是因為兩個名額都被佔了〕（全量開跑前先查 `Get-CimInstance Win32_Process -Filter "Name='python.exe'" \| ? CommandLine -match 'pytest'`，已有 2 組就排隊並回報）②差異題或單檔一律 `-n 2` 以下，全量 `-n 4` 以下（機器 12 邏輯核，要留給使用者與正式開發）③測試行程以低優先權執行（`start /BELOWNORMAL` 或啟動後設 `PriorityClass=BelowNormal`）④卡住超過 10 分鐘的題目先抓 dump 再停掉，不讓它空轉佔核 〔2026-09-26 B（主持派工）：modtest 的上限可用環境變數覆寫——`MOTRIX_FULL_MAX_WORKERS`（全量，預設 4）、`MOTRIX_PARTIAL_MAX_WORKERS`（差異題，預設 2）；值須為 1～CPU 數的整數，否則不採用、印出來、用預設。全速期間（CORE-SPEC 使用者裁示表）設定，使用者回來後拿掉即恢復，不必改程式。⚠ modtest --full 的 e2e 段也吃全量上限，而主持 13:3x 修正「e2e 一律 -n 2」——全速時全量上限設 4 以上，e2e 段要另外用 --e2e-workers 2〕 |
| 14 | **修檔腳本與 git 指令不可以用 `;` 串在同一行**（2026-09-26：一晚發生兩次，主持在第一班列車上、D 在稽核 commit 上，都是腳本失敗了，後面的 `git add`／`git commit` 照樣執行 ⇒ 衝突標記或錯的內容進了 commit）。一律用 `&&`，或是分成兩個指令：先跑腳本，確認成功（沒有衝突標記、JSON 可以解析、斷言通過），再下 git。記憶〈修檔腳本要有 assert〉的延伸：assert 擋得下腳本本身，擋不下串在後面的指令 |

### 附錄 C-11a：驗證範圍跟著模組化縮小（RUN-PLAN D1b；B，2026-09-26 02:24 量測與設計，實作前）

**量測**（`modtest` 的 `select()`＋collect-only 題數；全部 513 檔、4,507 題；契約題 39 檔、626 題＝13.9%，是每次必跑的下限）。「距離」＝在反向 import 圖上離改動單位幾跳（`core:main` 是彙整點，不往上傳）：

| 改動 | 目前選中 | 主要來源（題數） | 只選直接依賴（距離 ≤1）＋契約 |
|---|---|---|---|
| helpers/legal_params.py | 75.4% | 距離 2：1,661；距離 3～4：570（遞移擴散） | **19.8%** |
| helpers/email_notify.py | 82.1% | 距離 1：2,162（**26 個單位直接 import**） | 69.5% |
| helpers/auth.py | 85.0% | 距離 1：2,655（46 個直接使用者） | 80.3% |
| db.py | 89.5% | 距離 0～1：3,217；資料表一跳 112 個單位 | 88.0% |
| main.py | 87.9% | **fixture 隱含 core:main：3,049** | 19.0% |
| core/events.py | 14.3% | 契約＋dir | 13.9% |
| routers/cashier.py | 17.5% | dir＋自己 | 19.9% |

**成因**（更正主持的推測：「沿 main 的 import 閉包擴散」**不成立**——`core:main` 是彙整點，helper 被改時擴散不會經過 main；main 的 fixture 隱含只在 main 本身被改時觸發）。實際是兩種：
1. **遞移**：helper → helper → 很多 router（legal_params 那一類）。只看直接依賴即可降到 ~20%。
2. **寬扇出**：一個 helper 被幾十個單位直接 import（email_notify、auth、db）。只看直接依賴仍有 70～90%；要再細到**名稱層級**才降得下來。

**設計**（依序實作，每一步都有量測與反向控制）：
1. **直接依賴選題**：改動單位 ⇒ 自己的題＋直接 import 它的單位的題＋契約題＋`dir:`。遞移擴散只在「介面變了」時才做（見 2）。
2. **介面不變規則**：以 G1 快照的描述比對改動單位在 base 與工作樹的公開介面。
   - 介面沒變（只改函式內部）⇒ 不遞移。
   - 介面有變 ⇒ 沿用現行的遞移擴散（改了簽名，間接使用者才可能壞）。
3. **名稱層級**（寬扇出的解法）：dep_scan 另記每個單位 `from X import a, b` 用到的名稱（`imported_names`）；改動單位以 AST 比對出**這次被改的頂層名稱**。
   - 只選 import 了這些名稱的直接使用者。
   - 以模組 import（`import helpers.x as m`）或 `import *` 使用的 ⇒ 當成用到全部名稱（保守）。
   - 改到模組層級的程式（非函式內）⇒ 當成全部名稱都改了。
4. **模組題只載入 L1＋該模組**：模組的 api／e2e 題改用 `load_all(modules_dir=只含該模組的暫存目錄)` 建的 app。模組之間的題互不依賴，階段 B 每搬一個模組，其他模組的題就不必跟著跑。
5. **L1 與模組之間靠契約題守**（使用者裁示）：每個被模組使用的 L1 介面（CORE-SPEC 串接點 IP-*、`core.*` 公開名稱）至少一題契約題，放 `tests/platform/`（每次必跑）。**反向控制**：在一個 helper 做「只影響間接使用者」的突變，新選題若抓不到 ⇒ 補契約題，**不擴大選題**。
6. **量測落點**：`modtest` 每次（含 dry-run）把 `{時間, 改動檔, 選中檔數／題數, 比例, 耗時, 選題規則版本}` 附加到主工作樹 `tools/platform/full_results/modtest_stats.jsonl`；D1b 的「≤30%」以這份檔驗收。

**實作後重量**（B，2026-09-26 04:05；「只改 helper 裡的一個名稱」時的選題比例，含稽核 D S-M1 的模組內引用閉包）〔更正：上表「只選直接依賴」的數字是閉包之前的估計；閉包之後 db 會上升，這是正確的代價〕：

| helper | 名稱數 | 中位數 | 75 百分位 | ≤30% 的名稱 | 說明 |
|---|---|---|---|---|---|
| legal_params | 18 | 16.4% | 16.4% | 18／18 | 達標 |
| email_notify | 63 | 20.6% | 37.9% | 40／63 | 高的是 `_cfg`／`email_send_policy` 等每封信都經過的設定（約 67.7%） |
| auth | 10 | 31.6% | 70.4% | 5／10 | `_require_user`、`_tok` 已列已知例外（主持裁示） |
| db | 139 | 81.9% | 83.5% | 8／139 | 遷移與 `_table_exists` 等都被 `init_db` 呼叫，conftest 用 `init_db` ⇒ 改 db 內部幾乎影響全部測試（判斷正確） |

反向控制：`tools/platform/scope_rc.py`（真突變 ⇒ 選到且真的紅；發版前／每批合回後跑，結果記進 modtest_stats.jsonl）。

**已知例外**（主持裁示 2026-09-26）：`main.py`、`db`（整份）、`db.get_db`／`db.init_db`、`auth._require_user`／`auth._tok`——每條請求或每一題的建庫都會經過；D1b 的 ≤30% 以其他名稱驗收。**落點**：階段 B 各模組的表與 migration 搬進模組（MODULE-GUIDE §4 模組 migration 執行器）之後，重量一次 db；屆時不再每題都經過的部分，從例外清單拿掉。

**不變的政策**：全量照舊——fixture 層改動、發版前、每批合回後。〔補充（2026-09-26，稽核 D R-O1；§G3）：這裡的全量**一律由列車跑**（每班一次）；各線動到 fixture 層只跑差異題＋tests/platform＋改到頁面的 e2e，月台註明、排車頭——不自己跑全量〕main.py 的 fixture 隱含維持（main 組裝整個 app，改它就是改所有端點的進入點）。

**目標**（實作後重量同一張表）：legal_params、email_notify、main 以外的常用 helper ≤30%。auth、db 屬於「每一條請求都經過」的核心，名稱層級後若仍高於 30%，逐一列出原因，由主持裁示是否接受。

---

## D. 發行與正式換版（使用者執行，儀表板操作）

**發行前（開發機）**
1. 在要發行的 commit 上跑全量：`python tools/platform/modtest.py --full`。全綠之後，儀表板的測試閘門才會放行。
2. 儀表板 →「1. 打包」（階段 2 完成後，可以選擇產品設定檔）。
3. 儀表板 →「這一包會改到哪些模組」：確認改動範圍，以及各模組的更新紀錄。

**換版當天（儀表板「5. 升級精靈」，逐步按下並確認）**

| 步驟 | 要看什麼 | 不過的話 |
|---|---|---|
| 0 | 「部署前健康檢查」全部通過（備份、告警、磁碟、服務、開發機標記、個資資料夾） | 先處理問題，不要疊在升級上 |
| ① 推送新版包 | 顯示推送完成 | 重推 |
| ② 停服務 | port 666 已經沒有服務在監聽 | 看輸出裡哪個行程沒停 |
| ③ 預檢 | `"ok": true` | 照 problems 逐項處理後重跑 |
| ④ 備份＋試還原 | 試還原的雜湊比對通過 | **停止**，不可以往下做 |
| ⑤ 轉換 | 轉換紀錄顯示只有新增 | 做「只回程式」回滾 |
| ⑥ 驗證 | 列數、設定、資料清單相同，6671 埠 ping 200 | 做「只回程式」回滾 |
| ⑦ 啟動服務 | 服務有回應 ping，心跳也打開了 | 看 server.log，再決定要不要回滾 |

- **回滾判斷**：優先用「只回程式」，它會保留轉換後寫入的資料。只有在資料本身出問題時，才用「完整回滾」（要輸入 FULL；轉換後寫入的資料會全部消失）。
- 備份目錄在正式機桌面的 `MOTRIX-UPGRADE-BACKUP\<時間戳>`，**換版後觀察一週沒有問題才刪**。

**換版後**
- 第一天：確認每日備份的 `.done`、「系統存檔_個資」底下有整庫備份、通知信照常寄出、心跳照常打卡。
- 第一週：每天看一次儀表板的健康檢查。

---

## E. 交叉稽核（CORE-SPEC §9d）

1. 主持人通知開始後，照分配表稽核別人的成果：A 審 C、B 審 A、C 審 B 與主持人的儀表板。
2. 每一份稽核都要涵蓋四件事：
   - 照規格逐條驗收，附可以重現的證據；
   - 針對「對方不在時」「失敗路徑」「回滾路徑」做反向控制；
   - 找假綠燈：綠燈是真的，但證明的是另一件事；
   - 提出改善建議，分成必修、建議、觀察三級。
3. 產出 `docs/platform/audit/AUDIT-<稽核者>-<對象>.md`。發現的問題要附 `檔案:行號`，還要附重現的指令。
4. 被稽核的人逐項回覆（修正、不修並說明理由，或需要使用者裁示），**不可以自己把發現關掉**：由原稽核者確認修正之後才算關閉。
5. 主持人彙整成 `IMPROVEMENT-REPORT.md` 交給使用者。必修項全部關閉之後，階段 3 才算完成。

---

## F. 什麼事要問使用者（其餘由主持人依規格裁示）

- 會改變使用者看得到的行為：權限範圍、畫面內容、通知對象。
- 個資、雲端、權限相關的決定。
- 會碰到正式機，或正式機資料的任何動作。
- 推翻使用者先前的裁示。
- 取捨時兩邊都有實際代價，而規格沒有寫到的情況。

問的時候用表單，一題一個決定，並附上推薦選項；問完當下就寫進 CORE-SPEC「使用者裁示」。

---

## G. 長期運作：安全而且有效率的驗證、降低每次閱讀的成本（使用者 2026-09-26：「這是長期運作更新的系統，思考如何安全及高效驗證，可以底層加註註解減少每次讀取時間」）

### G1. 驗證分四層（每一層都有明確的用途，下一層不代替上一層）

| 層 | 什麼時候跑 | 跑什麼 | 目標時間 |
|---|---|---|---|
| ① 開發中 | 每次存檔或 commit 前 | 名稱層級選題（改到的名稱 ⇒ 真的用到它的單位）＋該單位的契約題 | 數分鐘 |
| ② 合回閘門 | push 到 platform 前 | ①＋tests/platform（契約與守門）＋有改到的頁面的 e2e；`--rebase-check` 判定差異題要擴大到哪些檔（~~要不要升到③~~〔更正 2026-09-26：影響大也不升到③，全量交給列車，§G3〕） | ≤20 分鐘 |
| ③ 批次全量 | 每批合回之後、動到 fixture 層時〔更正（§G3）：**由列車跑**，各線不自己跑〕 | 全量（2 個名額、-n 4、低優先權） | ≤60 分鐘 |
| ④ 發版 | 出部署包前 | 全量＋D7 型的升級演練（正式機資料的複本、兩種回滾、冒煙） | 以演練報告為準 |

- 安全靠的是**邊界上的契約題**加上**守門的突變抽查**，不是每次都跑全部。每新增一道守門，都要附一個會讓它轉紅的突變。
- 偶發失敗一律當成真問題查（O1 的教訓：它其實不是偶發），不准標成 flaky 或加重試。
- 每一次選題都記錄比例與耗時（`full_results/modtest_stats.jsonl`）；比例變大就要找原因（D1b）。

### G2. 單位卡：讓人和 AI 不必讀完整個檔案（底層加註）

- **每個 L0／L1 檔案的開頭寫一張「單位卡」**（模組 docstring 的固定格式），要在 30 行以內讀懂：

```
"""<一行用途>

[單位] core:events            [層] L0／L1        [穩定度] 契約（改介面照 §C-7 升版）
[公開介面] declare, publish, subscribe, …   ← 要和 G1 快照一致，守門比對
[不變式] 發佈在 commit 之後；payload 必須 JSON 來回不變；訂閱者失敗不外拋
[契約題] tests/platform/test_core_events.py
[注意] 訂閱者同步執行，慢工作要自己丟背景
"""
```

- **不手寫會過期的東西**：「誰使用我」「被哪些題涵蓋」由工具產生，不寫在卡上；卡上只寫人才知道的事（用途、不變式、注意事項）。
- **產生一份總索引** `docs/platform/UNIT-INDEX.md`，由 dep_scan＋單位卡產生。每個單位一行：用途、公開介面、直接使用者數、契約題。新的 session 先讀這份，再決定要開哪個檔，不要 grep 全庫。
- **守門**：卡片欄位齊全、「公開介面」與 G1 快照一致、「契約題」檔案存在；UNIT-INDEX 必須與重新產生的結果相同。
- **強制範圍（主持 2026-09-26）**：使用者裁示「轉移流程優先」，所以規則 1「改到就要補卡」**目前只強制 `backend/core/`**（`ENFORCED_PREFIXES`）；D1 模組搬遷完成後，擴大到 `backend/helpers/` 等 L1。已經有卡的檔，照樣要保持合格（規則 2）。
- **漸進導入，避免和各條線衝突**：守門只要求「這次有改到的 L0／L1 檔案」必須有合格的卡片，之後改到誰就補誰；總索引一次產生。L2 模組已經有 README／SPEC，不重複做。
- 目的是兩個：減少每次閱讀的時間；讓選題工具（D1b ③ 名稱層級）與人看的是同一份資料。
- **用法**（X，2026-09-26）：產生 `python tools/platform/unit_index.py`；檢查 `--check`（過期 exit 1）；選題工具讀卡片用 `unit_index.cards()`。守門 `tests/platform/test_unit_cards.py`：①本分支（對 origin/platform 合流點，含未提交與新檔）改到的 L0／L1 檔必須有卡；②已有的卡一律要合格（〔公開介面〕只列頂層名稱，類別成員由類別代表）；③UNIT-INDEX 與重產相同——改了 import 關係、卡片或 G1 快照都要重產並一起 commit。卡片寫在模組 docstring 第一行（用途）之後、連續不空行；`←` 之後是旁註、不解析。

（2026-09-26 02:28 主持）

### G3. 合回列車：多條線一起驗證（使用者 2026-09-26：「如果有可多視窗共同驗證的開發項目，可一次同時驗證 CPU」）

- **為什麼**：每條線各自跑全量（45～60 分鐘，全機只有 2 個名額），6～8 包要排 3～4 小時，大半是重複跑同一批題。
- **做法**：
  1. 各線做完，只跑 §G1 ②合回閘門（差異題＋tests/platform＋改到的頁面 e2e），綠了就在 RUN-PLAN §5 的「列車月台」登記：分支名、HEAD、差異題結果、有沒有動到 fixture 層。**不要自己跑全量。**
  2. 主持大約每 60 分鐘發一班：從 origin/platform 開 `train/<時間>`，依登記順序一包一包 rebase 上去。rebase 有衝突的那一包退回月台，下一班再上；CORE 版號與版本紀錄由主持在列車上用 core_bump 與 VR3 統一處理。
  3. 列車只跑**一次**全量（-n 4、低優先權，佔 1 個名額）。
  4. 全綠：列車 fast-forward 推上 platform，每一包的作者在 §6 補記一筆。
  5. 有紅：依失敗題的歸屬（test_map 的單位 ⇒ 哪一包改到那個單位）找出可疑的包，只在可疑的包之間二分排查。找到的那一包退回給作者，其他包重跑差異題後推上去。
- **例外**：動到 conftest 或 fixture 層、改 main.py 的包，照樣可以上車，但要在月台註明，並排在列車的最前面，出事時比較好定位。
- **正在跑的全量**：讓它跑完，不要中途停掉，跑完的那一包直接合回。
- **每一班列車疊完之後，都要重產三份產生檔**（2026-09-26 05:39，C 發現 dep_graph.json、test_map.json 從 01:02 之後就沒有重產，modtest 選題會漏掉新搬的模組檔）：UNIT-INDEX.md、dep_graph.json、test_map.json，單獨一個 commit，再跑全量。B 會補守門，讓它們過期時轉紅。
- **列車長要等到全量兩段都有結果行才結束回合**（2026-09-26 07:53，第四班列車長在「正在等」時結束回合，主持接手）：用背景 until 迴圈盯 pid，不用命令列字串比對。
- **做反向控制之前，先清掉只剩 `__pycache__`、沒有 `module.json` 的模組資料夾**（2026-09-26 07:53，D 的 O-4：切換分支後常留下這種資料夾，`module_installed` 會把它當成模組存在 ⇒ 假綠；A 的 O-4 改看 module.json 合回之後這一條可刪）。
- **自己建 sparse 樹的 MSYS 陷阱**（2026-09-26 13:58 主持；B、C 各踩過一次）：在 Git Bash 下 `git sparse-checkout set '/*' '!/backend/modules/<key>/'`，參數會被轉成 Windows 路徑（例 `!C:/Program Files/Git/…`），**排除失效、模組照樣取出** ⇒ 反向控制變成沒人察覺的假綠。對策：加 `MSYS_NO_PATHCONV=1`，或直接寫 `info/sparse-checkout`，或用 PowerShell／Python 呼叫 git（core_only_rc 用 Python subprocess，不受影響）。**建樹之後一律先 `ls backend/modules` 確認模組真的不在，再跑。**
- **每一班列車都跑一次 core-only 反向控制**（2026-09-26，主持派工 B）：`python tools/platform/core_only_rc.py --commit <列車 HEAD>`——拋棄式工作樹（`git worktree add --no-checkout` ＋ sparse-checkout 排除每個 `backend/modules/<key>/`，**不刪檔**）跑 tests/platform（-n 2、低優先權、`--continue-on-collection-errors`）；紅燈必須 ⊆ §B-11 允許的兩題（modules.json 列了但掃描不到、UNIT-INDEX）∪ 已知紅清單 `tools/platform/core_only_known_red.json`（新增一筆要在 RUN-PLAN 寫帶錨點的主持裁示；清單上的題轉綠未刪、或一題都沒跑 ⇒ 不過；AUDIT-D-B-G1 G-M1）。紅了 ⇒ 那是「守門的結果隨裝了哪些模組而改變」，照失敗題找改到它的那一包退回。可以和全量同時跑（不同 basetemp，不搶 -full 鎖）。起因：G1 快照原本依「L2 有沒有在用」決定 L1 公開介面，拿掉 M04 就報刪除——每搬一個模組才抓到一題太慢。
- **已知紅清單新增的每一筆，列車長合回時核對裁示行的作者**（2026-09-26，稽核 AUDIT-D-B-G1 G-O5）：`tools/platform/core_only_known_red.json` 比上一班多出的每一筆，用 `git log -S <錨點> --format="%h %an %s" -- docs/platform/RUN-PLAN.md` 找出寫入那一行裁示的 commit，**必須是主持（8d）的 commit**；不是 ⇒ 那一包退回月台。〔格式（主持裁示 2026-09-26）：主持的裁示 commit，**訊息最後一行加 trailer `Ruling-By: 8d`**；列車長用 `git log -S <錨點> --format=%B -- docs/platform/RUN-PLAN.md` 核對寫入那一行的 commit 有沒有這一行 trailer。⚠ 各視窗共用 git 作者（rocksk8），作者欄分不出是誰 ⇒ trailer **只是可稽核的約定，不是防偽**；列車長看到可疑的（trailer 在、但訊息內容不像主持的裁示），回報主持。B 代記的 25b81a70（「記錄主持裁示」）不算。〕守門只驗「有沒有裁示行」（被稽核者自己也寫得出來），誰寫的要靠這一步。
- **全量跑的期間不可以改列車的樹**（2026-09-26 05:06，第二班列車長的自我回報）：交會問題的修正要等全量跑完才能 commit；想提早動手，就另開一棵 worktree 準備，全量跑完再搬過來。否則全量驗到的不是同一個樹的狀態。

（2026-09-26 02:31 主持）
