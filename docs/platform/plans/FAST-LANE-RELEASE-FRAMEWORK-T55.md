# 小改動快速通道（Fast Lane）框架：最小但安全的稽核——流程表＋交叉驗證（規劃稿，僅文件）

> 2026-10-12，scope planner a3；委託：node-86（使用者要求）。**僅文件，未跑任何測試或工具**；只做針對單一檔案的 `git show`／讀檔。
> 標記：**【既有授權】**＝使用者已裁示、現行流程已在做（附來源）。**【提案·需書面同意】**＝削弱任何一道閘門或稽核，使用者書面同意前**不得實施**（常駐規則）。**UNKNOWN**＝我沒有查到證據，不推測。
> 不動：完整車道（Full Lane）的凍結樹官方閘門（not_e2e 3 workers → e2e 單獨 → 建包 → verify_package → final_drill → final_verify → 非作者稽核 → 主持 `--check` 後發布）**一字不改**。

> **r2 修訂（依 0d 審查；本稿 r1 不可原樣採用）**：下列分成「現在可採用」與「需使用者回答」。
>
> **A. 現在可採用（不削弱任何閘門或稽核）**
> 1. L0 文件層（範圍已收窄，見 §1：規則／授權／被測試讀取的文件一律不屬 L0）。
> 2. 分類器**只輸出、不決定任何事**（§4.1，`fast_lane_classify.py`）。
> 3. 硬排除表（§1.1，13 類，程式內常數）。
> 4. 影子期：只記錄分類結果與稽核升級率。
> 5. `prepush_check`／`train_preflight` 印出等級（只警告）。
> 6. §7 步驟 1–4。
>
> **B. 需使用者回答（削弱項＝問題，不是可採用事項；回答前一律不得實施）**
> - **W-1**：非作者「輕量稽核」取代完整稽核。
> - **W-2**：「底層檔僅字面值變動」視為可 L1。**它推翻 PLAYBOOK §D-1a 的「底層 ⇒ `modtest --full`」**，所以必須書面同意。
> - **W-3**：以 `scope_gate` 單獨出貨（不經凍結樹官方閘門）。
>
> - **X7 文件類是否可放寬**（問題，非提案）：被測試讀取的文件／規則文件，若對應守門（`regen_all --check`、`spec_coverage`、`cache_index`、`core_only_rc`；以實際名稱為準）通過並附證據，可否不走 L3？預設答案＝**否**，回答前一律 L3。
>
> **明講**：**L1／L2 只要隨列車出貨，一律照該列車的凍結樹官方閘門**（not_e2e → e2e → 建包 → verify_package → final_drill → final_verify → 非作者稽核 → 主持 `--check` 發布）；**凍結樹官方閘門維持強制**。本稿不提供繞過它的路徑；繞過它的項目（W-3 等）只是待回答的問題。

## 0. 結論（先講）

1. **這個框架大部分是把現有零件接起來，不是新造**。現成零件：`tools/platform/ship_tier.py`（出貨等級 1 文件／2 單模組／3 完整，判不了＝3）、`tools/platform/scope_gate.py`＋`bottom_layer.json`（範圍驗證閘門，fail-closed）、`author_gate.py`（作者推送前一支指令）、`prepush_check.py`（推送前約 1 分鐘）、`testcache_shadow.py`（影子錄製，只觀察）、`train_preflight.py --full-lint`、PLAYBOOK §G4「稽核分級」。使用者已就其中三件事書面裁示（CORE-SPEC 2026-09-28 14:08「出貨前測試依改動範圍分級」、2026-09-29 00:17「減少重複測試」、2026-09-26 15:06「省 token 而不降品質／稽核分級」）。
2. **今天的實況**：連「改一個欄位標籤」「改一個顏色門檻」都被分類成完整車道，因為 `bottom_layer.json` 把 `backend/*`（含 `backend/pdf_gen.py`）與 `frontend/static/**`、`frontend/js/**`（含 `margin-tone.js`）都列為底層（見 §6 範例）。**真正的快速通道缺口不在「少跑測試」，而在「判得出『這個底層檔只改了一個字串字面值』」與「小改動的稽核深度」**——這兩項才是新提案，都屬削弱，標【提案】。
3. **證據顯示稽核與閘門抓的是不同東西**（§3）：全域閘門抓「登記／守門／合併後才紅」；非作者稽核抓「作者自己寫的守門範圍太窄」（T49 cascade／hasFee、網路規劃書寫入守門）；兩者都**沒有**抓到「單向 golden 對新增路由失明」（GOLDEN-DRIFT，5 班官方閘門全綠）。因此**金額／權限／可見度／刪除／認證／簽章／閘門本身永遠走完整車道＋非作者完整稽核**，這是證據支持的硬排除，不是保守。
4. 快速通道**只適用沒有觸到任何硬排除、且只在 模組／頁面／測試／文件／帳務檔 層**的改動（`bottom_layer.json` 的 layer 詞彙），外加【提案·需回答 W-2】的「底層檔僅文字字面值變動（§1.2）」一條。**L1/L2 隨列車出貨時一律通過該列車的凍結樹官方閘門**。

## 1. 分級表（客觀、可由機器判定）

分級輸入＝`git diff <正式機基準 P>..<候選 X>`（與 `ship_tier`／`scope_gate` 相同基準；基準必須等於最新 `prod/<sha>` tag）。判不了、任何一步出錯、規則檔缺失 ⇒ **往上升一級**（fail closed，沿用 `ship_tier` 與 `scope_gate` 原則）。

| 等級 | 名稱 | 機器判定條件（全部成立） | 對應現有工具 | 出貨 |
|---|---|---|---|---|
| **L0** | 只改一般說明文件 | 改動檔全屬 `layer=doc`，**且不屬 §1.1 X7（規則／授權文件）、也不在下列「被測試讀取的文件」清單**，且不是 `export-ignore` 例外。**`layer=doc` 只是起點，不等於 L0**：`docs/**` 與 `*.md` 一律先過 X7 與下方清單。**`docs/platform/**` 會隨正式機交付給客戶**（`apply_update.ps1` 不部署，但交付包內含），其內容須視為對外文字 | `ship_tier` 等級 1 | 無東西要出貨 |
| **L1** | 單模組文字／版面 | ① 改動檔全屬 `module`／`page`／`test`／`bookkeeping`／`doc` 層，且恰好 **1 個**模組；② 沒觸到 §1.1 任一硬排除；③ 非測試檔的 diff 只含：**§1.2 定義的「僅文字字面值」**（HTML 只限使用者看得見的文字節點與 `title`／`placeholder`／`alt`／`aria-label`／label 文字屬性；CSS 僅限 §1.2 第 6 條）、CHANGELOG／manifest 條目；**不含**新 `def`／路由裝飾器／SQL 字串／`import`／判斷式（比較或布林運算）的變動；④ 改動行數 ≤ N、檔數 ≤ M（N、M 放設定表，初值 UNKNOWN，須由使用者/PM 定）；⑤ 若動到 `quotation-form.html`，同 commit 必須有 `FORM_VERSION` 升版與 `test_form_version_bumped_2026_09_24.py` 登記 | `scope_gate plan`（`module/page/test/bookkeeping/doc`）＋新增的「diff 內容檢查」（**新，屬提案**） | 隨列車（單模組包＝W-3，需回答） |
| **L2** | 單模組一般邏輯 | 同 L1 的①②，但③不成立（有邏輯變動）；且不含 §1.1 硬排除 | `ship_tier` 等級 2＋`scope_gate`（範圍驗證） | 隨列車（單模組包＝W-3，需回答） |
| **L3** | 完整車道 | 其他一切：任一硬排除命中、底層（`bottom`）層檔案、2 個以上模組、提供者（capability）被改而消費端判不了、`FORM_VERSION` 以外的公開 API 形狀變動（`l1_interface_snapshot`／路由 golden／`module.json` provides）、判不了 | `ship_tier` 等級 3 | 完整包＋凍結樹官方閘門 |

### 1.1 硬排除（**永遠 L3**；分類器內建常數，不在可調設定表）

| # | 範疇 | 機器可驗的訊號（任一即命中） | 證據為何要排除（§3） |
|---|---|---|---|
| X1 金流 | ① 改動檔屬 `accounting`／`arap`／`payroll` 三模組；② **明列的 case／報價金額檔（整檔命中，不看 diff 內容）**：`backend/modules/case/profit_guard.py`、`backend/modules/case/settlement_actuals.py`、`backend/modules/case/api/settlement_actuals.py`、`backend/modules/case/recognition.py`、`backend/modules/case/quote_terms.py`、`backend/helpers/tax_calc.py`、`backend/pdf_gen.py` 的金額／合計區塊、`frontend/pages/quotation-form.html` 的合計／毛利區塊（total／pretax／tot／profit 的計算與顯示）；**以及任何讀取 `total`／`pretax`／`tot` 或渲染金額的檔**（分類器以這些識別字 grep 全檔）；③ 非字面值 diff 含 `round_half_up`、`tax`、`amount`、`total`、`fee`、`paid`、`profit`、`overhead`、`charity`。**注意：`docs/platform/money_flows.json` 是「模組＋capability」登錄（欄位 `module`／`capability`／`name`），不是檔案路徑清單，不能拿來判斷檔案是否屬金流**。**X1 無法判定（不確定是否碰金額）⇒ L3，不是「保守 L2」** | T49 `hasFee`（匯款手續費旗標）漏網；T52 公益口徑；M1-a 傳票編號撞號 |
| X2 權限／可見度 | `module.json` 的 perms／menu 欄、`perm.`、`require_*`、`superadmin`、`role ==`、`guard_case_access`、`view_filter`；`case_read_scope.json`、`pii_forms.json`；頁面載入/隱藏條件 | T49 `cascade`、網路規劃書寫入守門；M1-a 轉簽規則 |
| X3 遷移／schema | `backend/modules/*/migrations/**`、`db.py`、`migrations_frozen/**`；diff 含 `CREATE`／`ALTER`／`DROP`／`module_schema_versions` | 已是 `bottom_layer.json` 的 bottom |
| X4 刪除／回收桶 | `DELETE FROM`、`recycle`、`purge`、`helpers/recycle_bin.py`、`modules/recyclebin/**`、刪除端點 | T53 回收桶 adapter 多輪修補（分支 wip/t53-1d-rb-adapters r2–r7、wip/t53-b5-rb-adapters r1–r4 的存在；各輪缺陷內容：UNKNOWN） |
| X5 認證／工作階段 | `auth_middleware`、登入／密碼／token／cookie／CSP、`main.py`、公開路徑白名單 | final_verify V3.2（公開 API 白名單）；`main.py` 已是 bottom |
| X6 簽章／交付 | `delivery.py`、`build_deploy_package*`、`verify_package`、`publish_*.sh`、`product/**`、`backend/tools/**`、`tools/**` | 已是 bottom；使用者規則：簽章金鑰只傳路徑 |
| X7 閘門本身 | `tools/platform/**`、`**/conftest.py`、`pytest.ini`、`bottom_layer.json`、`known_flakes.json`、`final_verify_allow.json`、`.githooks/**`、**本框架的規則檔**；**規則／授權文件**：`docs/platform/CORE-SPEC.md`（含「使用者裁示」節）、`PLAYBOOK.md`、`MULTIWIN-PROTOCOL.md`；**被測試讀取的文件**：`docs/windows/STATE.md`、`SCOPE.md`、`docs/platform/RUN-PLAN.md`、`CACHE-INDEX` 的來源文件、`docs/platform/audit/**`——這些改動⇒ **一律 L3**（本表是「永遠 L3」，不含任何放寬）。清單由分類器維護，**只能增加** | 閘門改動不可由被它放行的流程自己放行（`bottom_layer.json` 檔頭：「改這份檔＝改 tools/**＝底層 ⇒ 那一包必須全量」） |
| X8 公開形狀 | 路由新增/刪除/簽名改變（OpenAPI 路由表）、`l1_interface_snapshot.json`、`module.json` `provides`、IP 登錄（`INTEGRATION-POINTS.md`） | GOLDEN-DRIFT：路由 golden 對新增失明；雙向檢查落地前不得靠它判定 |

| X9 簽核流程 | 簽核／審批流程：`approval`、`approval_queue`、`tiers`、`currentTier`、`reassign`、`approve`／`reject` 端點、簽核層設定、`is_document_approver` | 轉簽規則、代簽（E1 `cascade`）；簽核是權限＋金流的交會 |
| X10 個資 | PII／個資：`pii_forms.json`、`pii` 相關欄位與遮罩、身分證／電話／地址／銀行帳號欄位的讀寫與顯示、匯出（Excel／PDF）含個資欄 | 外洩不可逆；`case_read_scope.json` 已在 X2，本項補欄位層 |
| X11 備份／保留／稽核紀錄 | 備份、保留天數、稽核紀錄（`audit_log`）、`backup_retention`、`db_backups`、任何刪除或縮短保存的程式 | 不可逆（縮短保留＝更早刪除）；M2 設定中心「縮短需待生效」即為此類 |
| X12 對外通知 | 對外送出的通知／email／簡訊／Webhook、站內通知的收件人決定邏輯 | 送出後無法撤回；洪水與誤發風險 |
| X13 授權／公司資料閘 | 授權與公司資料閘：`.install_identity`、`company_setup`、`company_confirmation.sig`、授權驗證、公司資料設定 | 動到會鎖死或放行整台系統 |

> 設定表可以**再加**排除，**不可以**移除或縮小（§4.2）。X1／X2 的字詞清單是**起點**，需用 §4.3 的正對照/反向控制驗證召回率，**不是**完備定義。

### 1.2 「僅文字字面值」的唯一定義（L1 ③／W-2 共用）

**只有同時成立才算「僅文字字面值」變動**，否則一律 ≥ L2（需非作者**完整**稽核）：
1. 變動的節點是**使用者看得見的文字節點，或位於白名單內的標籤常數**（白名單＝規則檔列出的「檔案＋常數名」，**只能增加**；不在白名單的字串＝非字面值）。
2. **舊字面值不得有任何其他引用**：對舊字串 grep `*.py`、`*.js`、`*.html`、`*.json`、`tests/**`（含測試斷言、golden、manifest），除本次要改的位置外**不得再出現**。
3. 舊字面值**不得等於任何已知的**：狀態值、角色名、權限鍵、欄位鍵（如 `afterSales`）、模組名、action 名、HTML `id`、`data-*` 屬性、`href`、`onclick`／事件處理字串、列舉（enum）值。
4. 不在 f-string 運算式、SQL、路徑、格式字串、正規式內；父節點型別不變。
5. HTML 屬性**只允許** `title`、`placeholder`、`alt`、`aria-label` 與 label 文字；**絕不可**變動 `id`、`class`、`name`、`value`、`href`、`src`、`onclick`（及任何 `on*`）、`data-*`、`for`。
6. CSS 變動僅限不涉及 `display`、`visibility`、`pointer-events`、`content`（含 `::before`／`::after` 的 `content`）的屬性，且所作用的元素**不被 JS 引用、也不屬 X2 可見度控制**；否則 ≥ L2。
7. 任一條判不了或解析失敗 ⇒ 非字面值。

## 2. 每級必經閘門、稽核者、證據、時間、回滾

「已授權」＝現行已實施且使用者曾裁示。「提案」＝削弱，需書面同意。

| 項目 | L0 | L1 | L2 | L3 |
|---|---|---|---|---|
| **作者端必跑** | `prepush_check --static-only`（約 1 分鐘，硬上限 90 秒）；動索引則 `regen_all --check`【已授權：PREPUSH-USAGE-T51】 | `prepush_check`；`author_gate`（設計估 9～11 分：A1 `tests/platform` 整目錄＋A2 檔名樣式守門檔＋A3 受影響題＋A4 新增測試；AUTHOR-GATE-DESIGN §2）；改頁面 ⇒ 該頁 e2e | 同 L1 | 同 L1；`pre_train_check`／`train_preflight --full-lint`（凍結前） |
| **閘門** | 無（不出貨） | **隨列車：該列車的凍結樹官方閘門（強制）**。`scope_gate`-only 單獨出貨路徑＝W-3，**需使用者回答，非本稿可採用**（PLAYBOOK §D-1a 不在此當作現行同意重述） | **隨列車：該列車的凍結樹官方閘門（強制）**（單獨出貨同 W-3） | 凍結樹官方閘門，**不變** |
| **稽核者** | 作者以外抽查（看 diff＋1 突變）【已授權：PLAYBOOK §G4 稽核分級 ③】 | **【提案·需書面同意】W-1 非作者「輕量稽核」**：看 diff＋確認分類器輸出＋作者回報（指令／題數／通過數）＋1 個突變；不重跑作者已跑的題。現行 §G4 ④ 規定「產品碼…照舊完整稽核」，L1 含產品碼（頁面/字串），故這是削弱。**輕量稽核者必須獨立重跑分類器**（不採信作者貼的輸出），結果**只能維持或升級、不得降級**；任何 §1.2 條件判不了 ⇒ 升 L2 完整稽核 | 非作者完整稽核（附突變）【已授權：§G4 ④】 | 非作者完整稽核＋必修修完重跑閘門【已授權：§G7 第 3 節】 |
| **證據** | diff＋prepush 輸出 | 分類器 JSON（等級＋命中規則＋diff 內容檢查結果）、author_gate 結果檔（綁 tree sha）、scope_gate 紀錄（commit／基準／規則雜湊）、稽核報告 | 同 L1＋完整稽核報告 | 閘門紀錄（題數、worker、head SHA）＋步驟檔＋稽核報告 |
| **預期牆鐘** | **UNKNOWN**（影子期資料前不填數字） | **UNKNOWN**（影子期資料前不填；作者端各工具的設計估計不當成節省量）；`scope_gate run` 實測：**UNKNOWN**（來源無實測紀錄）；稽核：**UNKNOWN** | 同 L1，稽核更長：UNKNOWN | 現況：not_e2e 約 2400 s（M1-a／M2 r1）～8766 s（M2 r2 重跑；hichan-21 報告，記憶 away_log 10-12 04:10）；e2e 另計；M2 整班超過 8 小時（記憶 `update_time_target_2h`）；使用者目標一次更新約 2 小時 |
| **回滾** | 不需要（無出貨） | 隨列車出貨⇒同 L3。單模組包（W-3 路徑）：`module_update.py rollback`；是否已進正式交付流程：**UNKNOWN**（2026-09-28 時 ROADMAP P7 標 ⏳「不在交付流程」，之後狀態未核） | 同 L1 | 失敗＝步驟檔「只記錄、停下，不自行回滾」；**回滾一律由使用者決定**（PLAYBOOK §G7） |

**不變式（所有等級）**：①分類器輸出與規則雜湊進證據；②等級只升不降（作者不能自行降級，稽核者可以升級要求）；③任一閘門紅 ⇒ 不放行，**不以「小改動」為由蓋章或放行偶發紅**（沿用 `known_flakes`：未登記未蓋章的偶發題不得放行，PLAYBOOK §G7）；④作者端結果不得寫成整段綠（AUTHOR-GATE-DESIGN §4）。

### 2.1 本框架裡**所有**削弱項（逐項列出，使用者書面同意前不得實施）

| ID | 內容 | 削弱了什麼 | 風險與緩解 |
|---|---|---|---|
| W-1 | L1 非作者「輕量稽核」（取代完整稽核） | 稽核深度 | T49 證據：作者自寫守門範圍太窄是非作者稽核抓到的（§3 E1）；緩解＝L1 限制在純文字/版面、硬排除全擋、分類器 diff 內容檢查、輕量稽核保留「找守門盲點」與「讀發布文字」兩項 |
| W-2 | 「底層檔僅文字字面值變動（§1.2 定義）」視為可 L1。**這推翻 PLAYBOOK §D-1a「底層 ⇒ `modtest --full`」**；X1 金額檔（含 `pdf_gen.py`、`quote_terms.py`）不適用 | 範圍驗證的底層全量規則（`bottom_layer.json`：底層 ⇒ 全量） | 需 AST／token 級證明並滿足 §1.2 全部條件（白名單常數、舊字面值無其他引用、不等於任何已知鍵名／狀態／id／enum）；客戶可見輸出須非作者看實際輸出 |
| W-3 | 單獨以 `scope_gate` 範圍驗證出貨（不隨列車、不經凍結樹官方閘門） | 官方閘門 | **需使用者回答**：PLAYBOOK §D-1a 的授權範圍是否涵蓋本框架的 L1/L2、是否仍有效，不由本稿假設；回答前，L1/L2 一律隨列車並通過該列車的凍結樹官方閘門 |
| W-4 | 多個 L1/L2 合成一班一起過 `scope_gate` | 每個 commit 各自驗證 | 【提案】是否需要：UNKNOWN；不需要就不提 |
| W-5 | （未來）影子錄製器命中結果「沿用」綠燈 | 實際執行 | **已有條件同意但尚未實作**（SPEEDUP-PIPELINE-T51-USAGE：「沒有任何快取結果可以取代凍結樹的正式閘門；步驟 3–5 需使用者書面同意」）；本框架**不依賴**它 |

## 3. 交叉驗證：哪些檢查真的抓到過缺陷、哪些從沒觸發

> 方法限制（誠實）：我只讀了指定來源與少量 `git show`；`docs/platform/audit/` 有 113 份稽核報告，**沒有逐份統計「必修率」**，下表只列有明確 commit／文件證據的案例。「從沒觸發」多為「**無證據**」＝UNKNOWN，不能當成「沒用」。

| # | 案例（來源） | 抓到它的檢查 | 沒抓到它的檢查 | 對分級的意義 |
|---|---|---|---|---|
| E1 | **T49 `cascade`／`hasFee` 真值漏網**：W1C 端點稽核提出 P2「同型 `bool(body.get(flag))`，字串 `"false"` 被當 true」（`docs/platform/plans/ENDPOINT-AUDIT-W1C-T48.md` P2，含 `cascade`、`remit_require_payslip` 緊急關閉開關）；作者修補 `bd88cfaa5`（`helpers/validation` ＋守門）範圍太窄：八個 approver 端點的 `cascade` 與 `remit.parse_remit` 的 `hasFee`（在 `api/` 以外）掃不到；`fbfb57209`（t49b）說明並把守門放寬到全部非測試產品檔。PLAYBOOK §G7 第 3 節：「第 49 班第一版（`c0d01cd57`）因兩項必修（cascade／hasFee 嚴格解析漏網、網路規劃書寫入端點漏逐案守門）整個作廢」 | **非作者獨立稽核**（PLAYBOOK §G7 記載為必修）；具體哪位稽核者/哪份報告：**UNKNOWN**（我沒找到該報告檔） | 作者自己寫的守門（`test_no_truthy_request_flags` 初版）；第一版已走完的官方閘門並未攔下 | 金流（hasFee）＋權限（cascade 代簽）類，作者守門範圍是盲點 ⇒ **X1／X2 必須非作者完整稽核**；輕量稽核不能用 |
| E2 | **網路規劃書寫入端點漏逐案權限**（`738688ce0` t49b：PUT/PATCH status／import excel／privacy ack 同套逐案權限；該 commit 並「更正 W1b 稽核報告一句」） | 第二輪非作者稽核（同 E1 的必修）；之後新增 `netplan/tests/test_netplan_visibility_t49.py`、`test_netplan_moved_guards.py` | W1b 端點稽核（第一輪）報告有一句錯 | 可見度/寫入權限 ⇒ X2；第一輪靜態稽核也會漏 |
| E3 | **路由 golden 單向比對**（`docs/platform/plans/GOLDEN-DRIFT-T52.md`）：`test_openapi_route_table_matches_the_golden` 只檢查「golden 有、現況沒有」；第 46–50 班新增的 30 條路由沒人補，**5 班官方閘門全綠**；另 `test_endpoint_auth_w1b_t48.py` 只掃 `case`／`subcontract`／`supply` 三模組 | 人工（b7 發現），非閘門；修法已提（嚴格相等；`wip/t52-n39-golden-r1`） | **官方閘門（5 班）** | 「閘門綠＝無缺陷」不成立：**有方向盲點的守門不得當 L1 唯一依據**；X8 在雙向檢查落地前一律 L3 |
| E4 | **M2 官方 not_e2e 第 1 輪紅 7 題**（settings 3／perm 2／hub 2；記憶 away_log 10-11 22:25）：wording 守門、`router_registration` 別名正規式漏判、`L1_OWNER` 未列入單位卡公開介面（r2 full-lint 紅 1，10-11 23:2x） | 官方 not_e2e／`full-lint`（全域守門） | 作者自選清單：缺 `ac1/demo_reset/module_keys/router_registration/wording_guards` 與 `modules/*/tests`（away_log 10-11 23:xx 根因） | 全域守門檔（`bottom_layer.json` 的 `global_tests`，約 47 檔）會被**任何**模組改動觸發；`author_gate` A1／A2 的設計正是對此。L1/L2 作者端必須跑 A1∪A2，不可只跑自選題 |
| E5 | **M2 r2 重跑紅 4**（away_log 10-12 05:29、06:06、06:14）：`company_setup_cli`×3＝負載逾時（單獨過）；`fail_stream_aborted`＝既有計時競態（platform c14f0a1df 與 M2 皆 0/3 過）；r1 另有 `MOTRIX_TRAIN=1` 漏設紅 1（02:34）；`known_flakes` 為空 | 官方 not_e2e | — | **環境/計時紅佔相當比例**；快速通道不能依賴計時題，否則 L1 會被機器負載拖住 |
| E6 | **第 26–27 班建包失敗 10 次**，約 6 次「分支單獨綠、合併後才紅」（登記／歸屬／`**` 棘輪／單元卡…），其餘為時間相依（記憶 `feedback_build_gates_time_and_integration`、`feedback_presubmit_gate_before_review`）；**第 31 班整合 5 輪紅**：e2e marker、31-C 登記×9、changelog、字級 vh、金額往返、spec owner map、子模組 pii 鏡像（AUTHOR-GATE-DESIGN §0、§6） | `pre_train_check`／整合樹閘門；回放驗證表列為 `author_gate` 驗收（**回放是否已執行：UNKNOWN**） | 作者端（當時無 `author_gate`） | 便宜的全域守門（`tests/platform`）抓「登記/版本」類缺陷頻繁 ⇒ L1/L2 作者端必跑；它們是**便宜且有證據會觸發**的檢查 |
| E7 | **`4eb521384`（M1-a）**：「05 文字稽核」發現版本紀錄/CHANGELOG 用語過度宣稱（毛利率顏色只在報價單列表與表單；徽章改用獨立計數；已精算或已結案），改文字（3 檔：case CHANGELOG、`version_manifest.json`、`test_form_version_bumped`） | **非作者的文字稽核**（05） | 作者自述/官方閘門（文字內容不在測試範圍） | **面向使用者的文字也會錯**；L0/L1 的輕量稽核不能省掉「讀發布文字是否與 diff 一致」 |
| E8 | **`c36946e84`（M1-a）**：「報價單表單 V3.21（登記表單版本帳）＋版本紀錄 2026-10-11a～c（日期跨日）」——改標籤/版本時漏登表單版本帳與版本紀錄日期 | 哪一道抓到：**UNKNOWN**（commit 訊息未說；`test_form_version_bumped` 與 changelog 守門都在候選） | — | L1 規則⑤（FORM_VERSION 同 commit 升版）合理，但「由誰抓到」缺證據 |
| E9 | **T52-NOTES（b5）**：S6 獎金代核與工作日誌兩項「**尚未執行任何測試**（依主持指示切換期間機器安靜）」 | 無（這是證據缺口） | — | 寫入留痕/通知類（X1/X2）當時只靠語法檢查；之後結果 **UNKNOWN**。不用於證明快速通道安全 |
| E10 | **從沒觸發/無證據**：`final_verify`（V1–V5）抓過什麼缺陷：**UNKNOWN**（只讀到檢查項目表，`FINAL-VERIFY-T49.md` 不在 platform 樹，只有 T48 範本）；`testcache_shadow` 命中率：UNKNOWN；`fail_stream`／`failfast` 抓缺陷：UNKNOWN | — | — | 這些不能當 L1 放行依據，只能當附加檢查 |

### 3.1 把證據翻成「每級該有什麼」

- **有證據會觸發、便宜、應列入 L1/L2 作者端**：`tests/platform` 整目錄（E4、E6）、`*changelog*`、`*form_version*`、`*approval*/*queue*/*pii*/*migration*/*spec_coverage*/*money_round*/*font_zoom*` 檔名樣式（E6）。
- **只有非作者人眼能抓到**：作者守門範圍盲點（E1、E2）、發布文字與 diff 一致性（E7）。⇒ L1 輕量稽核**必須**保留「讀 diff 找守門盲點」與「讀發布文字」兩項；這是 W-1 能成立的底線。
- **有方向盲點，不能當依據**：路由 golden（E3）。
- **不穩定，不能當依據**：計時題（E5）。

## 4. 自動化掛點與「框架優先」規則

### 4.1 可自動檢查的位置

| 掛點 | 既有 | 可加的檢查（皆為**新增檢查**，不削弱任何閘門） |
|---|---|---|
| `prepush_check`（推送前，約 1 分鐘，硬上限 90 秒） | 靜態 A1–A8、wip 帶產生檔、changelog_follows_code、FORM_VERSION、便宜守門檔；推 train/platform 只警告不擋 | 印出分類器等級與命中規則（只警告）；偵測「改動了規則檔/閘門檔」（X7） |
| `train_preflight` | `--full-lint` | `--tier` 輸出；L3 候選混入 L1 的 commit 時列出，供整合者分車 |
| `ship_tier`／`scope_gate` | 等級 1/2/3、底層清單 | 以同一份 `bottom_layer.json` 為基礎（**不另建第二套規則**，避免兩份清單分歧） |
| 影子錄製器 | 只觀察 | 可記錄「分類器判定等級」與實際結果，累積 §3 缺的證據（例：L1 被非作者升級的比率）；**仍不決定任何事** |
| 分類器（新，`tools/platform/fast_lane_classify.py`，**提案，尚未存在**） | — | 讀 diff＋規則表，輸出 JSON：`tier`、`reasons[]`、`hard_exclusions[]`、`literal_only`（W-2 的證明）、`rules_sha`；任何錯誤 ⇒ L3 |

### 4.2 框架優先：規則放設定表，硬排除上鎖

- **可調（設定表 `tools/platform/fast_lane_rules.json`，提案）**：各級的層別白名單、行數/檔數上限（L1 的 N、M）、字詞/模式清單（**只能增加**）、各級必經檢查清單、稽核者人數。格式沿用 `bottom_layer.json`（`format`、`_doc`、`rules[]`、每條 `why`）。
- **上鎖（程式內常數＋守門題，不在設定表）**：§1.1 的 13 類硬排除（X1–X13）與「等級只升不降」「判不了＝L3」。設定表只能**加**排除。
- **放寬規則**：設定表中任何會讓更多改動進快速通道的變更（放大 N、M、移除模式、放寬層別）＝削弱 ⇒ 須使用者書面同意，記錄於規則檔的 `consent` 欄（日期、來源）；由守門題檢查「規則雜湊變動 ⇒ 必須有對應 consent 條目」。收緊（增加排除）即時生效。這與設定中心「放寬需核准、收緊立即生效」的既有原則（記憶 `settings_center_plan`）一致。
- **改規則檔本身＝X7＝L3**（與 `bottom_layer.json` 現行規則相同）。

### 4.3 分類器自己的守門（必備，否則不得啟用）

沿用記憶 `feedback_scanner_positive_control`、`feedback_mutating_destructive_code`：
1. 每個硬排除一組**正對照**（會命中的假 diff）與**反對照**（不會命中的）；
2. 突變：把任一硬排除拿掉 ⇒ 守門題紅；
3. 召回率回放：以 §3 的真實案例（E1 `bd88cfaa5`→`fbfb57209`、E2 `738688ce0`、`d4c3ecf68`、`c6379c50a`、`4eb521384`）當輸入，斷言分類結果；E1/E2 必須 L3；
4. 與 `ship_tier`／`scope_gate` 一致性題：分類器 L1/L2 ⇒ `scope_gate plan` 必須也判可範圍驗證；反之不成立（分類器更嚴）；
5. 字面值證明（W-2；條件見 §1.2）：Python 用 `ast` 比對前後語法樹、HTML 用文字節點比對、舊字面值全庫 grep（py/js/html/json/tests）；任何解析失敗或條件判不了 ⇒ 非字面值。
6. 輕量稽核的獨立性：稽核端重跑分類器，結果與作者不同時**取較高級**；守門題須含「稽核重跑結果較低時仍維持作者較高級」的反向案例。
7. 新增硬排除 X9–X13 各一組正／反對照（簽核流程、個資、備份／保留／稽核紀錄、對外通知、授權／公司資料閘）。

## 5. 一頁檢查表

### 5.1 作者（送快速通道前）

- [ ] 跑分類器；等級≠我預期（或 L3）⇒ 照 L3 辦，不爭論。
- [ ] 改動只在一個模組＋其頁面＋測試＋CHANGELOG/manifest；`git diff --stat` 沒有 `bottom` 層檔（除非 W-2 獲同意且分類器證明僅字面值）。
- [ ] 沒碰 §1.1 的 13 類（金流、權限/可見度、遷移、刪除、認證、簽章/交付、閘門、公開形狀、簽核流程、個資、備份/保留/稽核紀錄、對外通知、授權/公司資料閘）。
- [ ] 改了面向使用者的標籤/文字：同 commit 更新 CHANGELOG、`version_manifest.json`；動 `quotation-form.html` ⇒ `FORM_VERSION` 升版＋`test_form_version_bumped` 登記。
- [ ] 改了顏色/門檻/排序/預設值＝**不是**純文字（`d4c3ecf68` 的「40 較嚴」改變哪些列變色）⇒ 升 L2 並寫「前後行為差異」。
- [ ] `prepush_check` 綠；`author_gate`（A1∪A2∪A3∪A4）綠，附**指令、題數、通過數、tree sha**。
- [ ] 改頁面 ⇒ 該頁 e2e 綠；客戶可見輸出（頁面/PDF）實際看過。
- [ ] 發布文字（步驟檔/版本紀錄）與 diff 逐項一致，**不誇大**（E7）。
- [ ] 沒有「未登記的偶發紅」；機器安靜（無其他視窗的 pytest；可用記憶體 ≥ 4 GB）。
- [ ] 回滾方式寫明（單模組包 or 隨列車）。

### 5.2 稽核者（非作者）

- [ ] 自己重跑分類器，結果與作者一致；有疑慮 ⇒ 升級（只升不降）。
- [ ] 看 diff：有沒有「作者守門範圍之外」的同型位置（E1：同型寫法在 `api/` 以外？）；grep 同型字串/旗標。
- [ ] 對每個標籤/文字變更：搜尋舊字串是否仍殘留（PDF、Excel、列印預覽、`quote_terms.py`、測試斷言）。
- [ ] 對發布文字：逐句對照 diff（E7）。
- [ ] 作者回報：指令/題數/通過數齊全；**不重跑作者已跑的題**（記憶 `feedback_audit_trust_author_tests`），只跑自己的探針、1 個突變、有疑慮的題。
- [ ] 突變：把改動還原一部分，確認至少一題轉紅（記憶 `flaky_test_is_a_clue`：新測試必須證明會紅）。
- [ ] 確認沒有觸及硬排除；觸及 ⇒ 退回 L3。
- [ ] 結論只有 PASS／必修；必修修完要**重跑閘門**後複驗（PLAYBOOK §G7）。
- [ ] 報告放 `docs/platform/plans/`，RUN-PLAN 只寫結論一行。

## 6. 三個過去小改動的示範（以現有規則逐檔判定；不代表當時實際走的流程）

| 範例 | 改動檔（`git show --stat`） | 現行 `bottom_layer.json` 判定 | 本框架判定 | 實際歷史 |
|---|---|---|---|---|
| **A. 標籤更名**「售後服務」→「售後服務及備註說明」（`c6379c50a`，表單 V3.22，鍵名 `afterSales` 不動） | `case/CHANGELOG.md`、`case/quote_terms.py`、**`backend/pdf_gen.py`**、`test_form_version_bumped`、`test_quote_submit_reasons_server`、`version_manifest.json`、`quotation-form.html` | `pdf_gen.py` 命中 `backend/*` ⇒ **底層 ⇒ 全量**（現行即 L3） | 現行規則 ⇒ **L3**。`quote_terms.py`、`pdf_gen.py` 是 §1.1 X1 明列的金額檔（`money_flows.json` 是模組登錄，不能用來判斷），**X1 命中 ⇒ L3，且不因 W-2 獲同意而改變**；X1 無法判定也是 L3，**不是**「保守 L2」。本例若要走 L1，須先把這兩檔從 X1 拆出（縮小排除屬削弱，須使用者書面同意；本稿不提議） | ab 稽核 PASS（away_log 10-11 11:24）；隨 M2 出貨（尚未上線）；省多少時間：**UNKNOWN**（無對照） |
| **B. 狀態/顏色**：毛利率門檻單一來源、列表空列 colspan、已成案徽章（`d4c3ecf68`，M1-a） | `margin-tone.js`（`frontend/static/**` ⇒ bottom）、3 個 HTML 頁、`case-management-list.js`（`frontend/js/**` ⇒ bottom）、新測試 | 底層 ⇒ 全量 | **L3**；即使不是底層也不是 L1：門檻改成「40 較嚴」會改變哪些列變色＝行為變更（§5.1 第 5 項）；`margin-tone.js` 新增 `function` ⇒ 非字面值 | 隨 M1-a 全班出貨；M1-a 步驟檔「框架化債務」記下 30／40 仍寫死 |
| **C. 文字修正**（版本紀錄/CHANGELOG 用語更正，`4eb521384`） | `case/CHANGELOG.md`、`version_manifest.json`（bookkeeping）、`test_form_version_bumped_2026_09_24.py`（test） | `module`＋`bookkeeping`＋`test` 層 ⇒ 可範圍驗證（ship_tier 等級 2）。已核對 `bottom_layer.json`：`backend/version_manifest.json` 為 `bookkeeping`（規則排在 `backend/*` 之前），`backend/modules/*/**` 為 `module`，`backend/tests/**/test_*.py` 為 `test` | **L1**（只含文字/帳務檔，單模組，無硬排除）。必經：`prepush`、`author_gate`、`scope_gate`（含 VR 守門題）；稽核：W-1 輕量稽核（E7 的文字稽核項必保留） | 該修正本身即來自 05 的非作者文字稽核（E7）；隨 M1-a 出貨 |

> 範例 A、B 說明：**今天「小」改動在實務上因 `backend/*`、`frontend/static|js|css/**` 為底層而幾乎全進完整車道**。要不要鬆這一條（W-2）是使用者決定；證據（§3）支持「底層檔僅字面值＋非金流」可考慮、不支持其他放寬。

## 7. 實作順序與工量（建議；UNKNOWN 者未估）

| 步 | 內容 | 工量 | 依賴 | 削弱？ |
|---|---|---|---|---|
| 1 | 規則檔格式＋硬排除常數＋分類器（不接任何流程，只輸出） | UNKNOWN | `bottom_layer.json`、`ship_tier` | 否 |
| 2 | 分類器守門題（§4.3）與真實案例回放 | UNKNOWN | 1 | 否 |
| 3 | `prepush`／`preflight` 印出等級（只警告） | UNKNOWN | 1 | 否 |
| 4 | 影子期：僅記錄分類結果＋稽核升級率，累積 §3 缺的證據 | 觀察期 | 3 | 否 |
| 5 | 取得使用者書面同意 W-1／W-2／W-3（／W-4）；同意後才啟用 L1 輕量稽核與字面值證明 | — | 4 的數據 | **是** |
| 6 | 稽核報告統計（113 份：必修率、發現類型 × 等級） | UNKNOWN | — | 否；補 §3 的缺口 |

## 8. 待確認（UNKNOWN／決定）

1. L1 的行數/檔數上限 N、M；是否限制「頁面 e2e 必跑」。
2. X1 字詞清單的召回率（§4.3 回放驗證）。`money_flows.json` **已確認為模組登錄（module／capability），不用於判定檔案是否屬金流**。
3. 單模組包（`module_update`）目前是否已在正式交付流程（2026-09-28 為 ⏳）；回滾實際路徑。
4. `scope_gate run` 的實測牆鐘時間；L1 若不另出包而隨列車，是否仍省時間。
5. W-1、W-2、W-3 是否同意；W-4 是否需要；X7 文件類是否可放寬（見標頭 B）。
6. E1 的原始稽核報告（誰、哪份）；E8 的偵測者。
7. 路由 golden 嚴格化（`wip/t52-n39-golden-r1`）是否已併入 platform（本稿 base c14f0a1df 上是否已修：UNKNOWN）；X8 在其落地前保持 L3。
8. 依據文件版本：`bottom_layer.json`、`PLAYBOOK.md`、`AUTHOR-GATE-DESIGN.md`、`PREPUSH-USAGE-T51.md`、`SPEEDUP-PIPELINE-T51-USAGE.md`、`GOLDEN-DRIFT-T52.md`、`T52-NOTES.md`、`ENDPOINT-AUDIT-W1C-T48.md`、`FINAL-VERIFY-T48.md` 取自 來源樹 `origin/platform@c14f0a1df`（文件版本；正式機基準為 `4eb521384`，見 prod tag）；T49 commit 取自 `origin/train/t49-int`／`origin/wip/t49*`。
