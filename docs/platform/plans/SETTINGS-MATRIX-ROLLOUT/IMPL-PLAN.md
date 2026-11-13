# 實作計畫：系統設定全面改版（SETTINGS-MATRIX-ROLLOUT）

狀態：**計畫稿 v1.1**（hichan-4 寫，2026-11-13；PM 同日裁示與 h11 意見已併入：審查分流、簽核頁通知降級、S5 使用者裁示與轉接器設計、批次端點 undo；使用者已看過設計稿 `04fc33c0c` 並同意「照這個方向開始實作」；h11 對 r3.2 複驗 0 阻擋）。
寫給「T82 上線、使用者清除視窗之後的新視窗」：不靠對話紀錄也要看得懂。本檔**只是計畫**；🔴 **禁重測令仍有效**期間不動程式碼、不跑重測（單檔、序列的測試可以）。班次號碼是「最早可進」的提案，PM／整合者可前後調整，依賴關係不可違反。

## 0. 接手第一步（新視窗照做）

1. 讀本檔 → 讀 `README.md`（規則）→ `SPEC.md`（規格，§4 批次、§5 CAS、§12 權限頁、§13 草稿＋通知、§14 外框、§15 設定中心以外）→ `INVENTORY.md`（§五＝使用者裁示、§七＝後續票）。
2. 設計稿與資料都在分支 `origin/feat/settings-matrix-rollout`（本檔所在目錄 `docs/platform/plans/SETTINGS-MATRIX-ROLLOUT/`）。我的 worktree：`D:\Claude-pm\hichan4-matrix\wt`。mockup：`h3/index.html`（甲）、`h12/index.html`（乙）、`h4/index.html`（丙四個矩陣分頁）、`h4/shell.html`（外框）；每個都附 `design-notes.html` 與 `shots/`。
3. 資料驗證（不連後端，輕量）：`cd backend; PYTHONUTF8=1 python -I ../docs/platform/plans/SETTINGS-MATRIX-ROLLOUT/data/gen_seed.py --check`（兩欄可批次數：① 規則上可批次 68、② 畫面提供勾選格 65＝甲 24＋乙 41）。頁面對應＝`data/shell_groups.json`（31 頁／50 群組；產生器 `data/make_shell_groups.py`）。
4. 交接檔：`D:\Claude-pm\handoff\hichan-4.md`（我）、`hichan-3.md`、`hichan-12.md`、`hichan-6.md`、`hichan-9.md`、`hichan-10.md`、`hichan-11.md`（各切片負責人的現況）。
5. 起點狀態（寫本檔時）：設定改版只有文件與 mockup，**程式碼一行都還沒改**；T84 預定帶入的相關程式：h6 `feat/line-events-matrix`（共用核心 `settings-matrix.js` 第一版）、h9 `feat/settings-change-notify`（v1，通用化進行中）、h10 `fix/user-perm-sensitive-gate`（`9361f1033`，四條路徑中的 `PUT /api/users/{id}`、`POST /api/users`）；h9 `fix/settings-center-valueof`（`2ad78c914`）進 T83。

## 1. 共同規則（每個切片都遵守）

1. **規格是 SPEC.md**；與 mockup 衝突時以 SPEC 為準，發現規格有洞先回報 h4（不要自己決定後默默實作）。
2. **寫入一律走既有路徑**：設定中心＝`settings_registry.publish()`／`apply_profile()`；不另開寫入點（SPEC §4-4）。
3. **審查者**：每切片至少一位**非作者**審查者；設定相關找 **h11**（對抗式審查者，熟 registry／change_control），但 PM 2026-11-13 裁示 h11 只留 S1d、S2、S3a、S6；共用核心前端與信件矩陣找 **h9**；registry、安全、金額後端找 **h12／h10**。審查意見處理完才進列車。
4. **測試（禁重測令解除前後都一樣的最低要求）**：每切片自帶測試檔，單檔、序列可跑；解除禁令後，整合者跑其列車的 preflight。`data/gen_seed.py --check` 在每個動到頁面對應或盤點表的切片都要綠。測試清單見各切片。
5. **「與預設不同」「來源」「?」說明**由登錄表產生（SPEC §6）；不另建說明檔；新增文字**不得含禁用詞**（確認期間、影子、閘門、true/false、整數選項代碼；SPEC §11、UX-PRINCIPLES §6.5）。
6. **截圖關卡（使用者明講：每一班上線前都要截圖給使用者確認）**：
   - 切片作者在分支上用示範資料起本機伺服器，**逐頁截圖**（桌面＋手機寬 390px；含草稿、儲存確認、結果提示、衝突拒絕等狀態），放 `docs/platform/plans/SETTINGS-MATRIX-ROLLOUT/shots-T<班次>/`，並寫一份逐張說明（這張改了什麼、對照舊畫面）。
   - **兩道**：(a) 切片「做完、審查完」後、**進列車前**，截圖交 PM → PM 以 SendUserFile 給使用者；(b) 整合者出包後、**上線前**，用 T 班包（或開發機 head）再截一次同樣的畫面給使用者。**使用者沒回「確認」不發布**；使用者要求改的，退回切片作者，不進該班。
   - 沒有使用者可見畫面的切片（例如 S1c 後端），截圖改成「通知訊息範例、確認視窗文字」等可見輸出；仍要過這個關卡。
7. **一頁一頁換**：頁面替換（S4）保持原網址；有疑慮時整個切片 `git revert` 即可還原（不做功能旗標，除非 PM 另有要求）。
8. 分支命名：`feat/settings-matrix-<切片>`（例 `feat/settings-matrix-s2-shell`）；commit 結尾 `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`；git 一律 `git -C <絕對路徑>`；worktree 放 `D:\Claude-pm\`。

## 2. 切片總表

「目標班次」是最早可進；**依賴不滿足就不進**。T84 已有的相關票（h6、h9、h10）不是本計畫的切片，但是依賴。

| 切片 | 內容 | 負責 | 審查 | 依賴 | 目標班次 |
|---|---|---|---|---|---|
| **S1a** | 共用核心補齊：eligible／lock、草稿模式（opt-in）、groupActions 防呆（SPEC §10 C-a～C-c） | h6 | h9 | h6 的 LINE 審查完成（核心不被動） | T85 |
| **S1b** | 核心元件補丁：C6「?」說明、C7 來源徽章、C8 與預設不同、C11 欄頭選取＋確認視窗的「略過原因／通知預覽」欄 | h4（對 `settings-matrix.js` 提 patch／PR，h6 合） | h6、h9 | S1a | T86 |
| **S1c** | 設定登錄表後端：`publish(..., expected_values)` 逐欄 CAS＋409；`SettingDef.when`＋`field_views` 加 `source`／`help`；禁用詞原文修正；`needs_external` | h4 | h12 | T83 已凍結的 `settings_registry.py` 基底 | T85 |
| **S1d** | 通知元件通用化（h9 的 8 項）與設定中心儲存列前端 | h9 | h11 | T83 valueOf 先進、T84 notify v1 | T84～T85（h9 目標 T84，跟不上就 T85） |
| **S2** | 設定中心外框：兩層導覽、總覽、待生效、最近變更、全域搜尋、草稿＋儲存列；後端 `overview`／`recent` | h4 | h11（後端）、h9（前端）；人機介面由 h12 覆看 | S1a、S1b、S1c、S1d | T86 |
| **S3a** | 使用者權限矩陣（`users.html` 的權限段＋批次端點＋範本逐人展開） | h4 | h12（對安全）、h11 | S1a、S1b、S1d、**h10 的 sensitive-gate 先合（T84）** | T87 |
| **S3b** | 信件收件矩陣（`mail-settings.html`＋批次端點；行事曆開關只留這頁、`google-calendar-settings.html` 改連結） | h4 | h9 | S1a、S1b、S1d | T87 |
| **S5**（後端，與 S3 平行） | §15：傳票科目、扣繳參數、T100 科目、管銷／公益口徑加變更管制；獎金預設、營運目標、報價條款存檔後發通知 | h3 | h10（金額／安全）；**SPEC §15 補強稿先給 h11 做規格審，過了 h3 才動程式** | S1c、S1d、SPEC §15 補強（見 S5） | T87 |
| **S4a** | 乙份各設定頁（11 頁；`builder_*` 13 組合一頁等） | h12 | h3 | S2（外框）、S1a～c | T88 |
| **S4b** | 甲份各設定頁（設定中心內 20 群組、7 個獨立頁、設定中心以外 7 項的白話化與連結） | h3 | h12 | S2、S1a～c、S5（設定中心以外的變更管制） | T88 |
| **S4c** | 丙份其餘頁：職責角色、組織架構、permission-matrix 暫存批次、簽核流程複製／範本（`approval-settings` 屬甲，見 S4b；流程範本批次由 h4 做） | h4 | h12（h11 建議；PM 未指定，開工前確認） | S3a、S3b | T89 |
| **S6** | 個人 Email 通知偏好的**本人入口**（my-account 通知分頁）＋管理員代設；LINE 個人偏好白話化 | h4 | h11 | S1a～b、S1d | T89 |
| **S7**（後續，不排班） | 預設組合內容（團隊提案→使用者看過→上線）；INVENTORY §七「整包寫入沒有並行控制」後續票；T83 凍結後重跑 `gen_seed.py`（monitoring 群組歸乙，預期 51 群組／186 欄） | h3＋h12＋h4 | — | S2 之後 | 待排 |

班次排法的理由：T84 已經擠了 h6、h9、h10 三張與設定相關的票，本計畫的新程式碼從 T85 才開始；每班只放「彼此獨立、能各自截圖確認」的切片；S4 依賴外框，所以在 S2 之後；S3 依賴 h10 的 gate（否則權限批次會繞過高敏感檢查）。

## 3. 各切片詳細

### S1a 共用核心補齊（h6；審查 h9；T85）
- 檔案：`frontend/static/settings-matrix.js`、`frontend/css/settings-matrix.css`（h6 的核心；**不得改既有 `data-testid`**：`mx-row-*`、`mx-batch-*`、`mx-undo`、`mx-toast-text`）。
- 內容：
  - **C-a eligible／lock**：頁面宣告列是否可批次與鎖定原因（灰色核取方塊＋tooltip；SPEC §4 的「否」字樣）；LINE 頁維持自己的覆寫（只有「重要」可放寬，守門要登記覆寫處）。
  - **C-b 草稿模式（opt-in，`draft:true`）**：點擊只改草稿、固定儲存列（放棄／儲存）、離開警告（`beforeunload`）、儲存確認視窗、結果提示；LINE 頁不啟用就維持現行立即存。
  - **C-c groupActions 防呆**：核心現有「全開／全關」群組動作要能由頁面關閉或限縮（設定中心沒有「全部開啟」，高風險列自動略過）。
- 驗收／測試：核心的 e2e（既有 6 個）全綠不改；新增 `eligible` 判定表驅動（每種 risk／pending／loosen／sensitive／文字欄位組合）、草稿模式 e2e（選→草稿→放棄；選→儲存→確認→吐司；有草稿關頁警告）；e2e 遵守 e2e lint（動作後不可立刻讀 UI 狀態，用 `expect`／`wait_for`）。
- 截圖：LINE 事件頁（確認沒變）＋核心範例頁（草稿列、儲存列、略過原因的確認視窗）。

### S1b 核心元件補丁（h4；審查 h6、h9；T86）
- 對 `settings-matrix.js` 提 patch／PR（h6 合，避免衝突）：C6 `SmHelp`（四段，內容來自 `field_views.help`）、C7 `SmSource`（預設／公司／等待生效／舊位置／個人）、C8 `SmDiff`（與預設不同＋「預設：X［還原預設］」只在不同時顯示）、C11 `SmColSelect`（欄頭勾人；權限矩陣用）、確認視窗的「略過原因」與「通知預覽」欄。
- 測試：每個元件一組純前端 node 測試（餵 rows JSON，驗輸出 DOM）＋用語守門（四段不得出現禁用詞；`when` 不得與 `help` 完全相同）。

### S1c 設定登錄表後端（h4；審查 h12；T85）
- 輸入：h3 已把甲份 76 欄的 `when` 與放寬方向推在 `h3/when_texts.json`（`329712f32`，格式 `{"fields":{"group.key":{"when":文字,"loosen":"up"|"down"|null}}}`）。**放寬那句（「需第二位最高管理者核准並等待 N 天」）刻意不放進 when**，執行期由 `plan().kind`／`otherSuperadmins` 產生（只有一位最高管理者時不得出現「第二位」）。乙份 `when` 由 h12 照同格式提供。
- 檔案：`backend/helpers/settings_registry.py`、`backend/routers/settings_center.py`、`backend/helpers/config_ledger.py`（by／at 退路）、`backend/helpers/settings_groups.py`（`when` 與禁用詞原文）。
- 內容：
  1. **逐欄 CAS**（SPEC §5-5）：`publish(group, values, ..., expected_values=None)` 在 `begin_write` 之後、寫入前逐欄比對目前**生效值**（含到期的 pending 覆蓋層）；不符丟 `SettingConflict(keys, by, at)`；路由接受 `expectedValues`，衝突回 409 `{code:'conflict', keys, by, at}`；沒有 `config_changes` 紀錄時 `by`＝「系統預設」或「舊路徑寫入，時間不明」。復原＝以 `expected_values=套用後的值` 回寫套用前的值，原因固定「復原批次」。
  1b. **S5 前置的通用能力（SPEC §15.A.1／§15.A.5，同一檔；h12 審；h11 已做規格審，MUST-FIX 1–8 修訂版 r3.4 待其複核）**：`legacy_adapter`（`read`／`write(conn…)`，只用傳入連線、冪等）、不透明 `json` 欄位型別（`summarize`、正規化標準 JSON 雜湊 CAS、15000 字元上限、`pending_exists`／`supersede`）、`loosen="both"` 擴到非數字欄位、`cross_check(values, conn)`、`external=True` 群組旗標；`materialize_due` 每群組 SAVEPOINT＋失敗取消並通知；4 個讀取咽喉點改讀登錄表生效值＋每日漂移檢查。這三項在 h11 規格審通過前不開工；S5（h3）依賴它們，所以 **S1c 的目標班次若延誤，S5 也跟著延**。
  2. `SettingDef.when`（選填）；`field_views` 加 `source:{kind,by,at,reason}` 與 `help:{what,when,impact,recommend}`；`needs_external`（SPEC §7）。
  3. **禁用詞原文修正**：h12 的掃描（`h12/scan_banned_words.py`，AST＋tokenize；清單 `h12/banned-word-sites.csv`；從 repo 根目錄 `python -I -X utf8 …/h12/scan_banned_words.py [--csv out]`）：使用者可見處 **51 處「確認期間」**（`settings_groups.py` 43、`settings_registry.py` 8，含 plan()／警告句約 588／590／730／732／742／854 行）＋**4 處「影子」**（`settings_groups.py` 433／436／437／439；選項標籤「影子（只記錄）」改成「只記錄、不生效」）；兩處 true/false 是開發者 ValueError 訊息（registry 103／163 行），不算使用者介面，守門豁免或改字；「閘門」只出現在註解。（先前說的「約 35 處」是以不同句子計，實際是 51 處。）機械式改寫成「要等 N 天才生效」（N 由參數帶入，注意 plan()／警告句用 `%d` 天）；docstring 與註解豁免。守門測試掃 `question／help／impact／risk_text／choices／when` 的字串常數＋registry `plan()`／`effect()` 句子。`when` 輸入：甲 `h3/when_texts.json`（76 欄）、乙 `h12/when-texts.csv`（107 欄／30 群組；同群組同類欄位共用一句，「when 不得等於 help」守門要逐欄比對）。
  4. 兩種等待的文字分開（SPEC §4-13）：確認視窗與待生效頁的提示文字由 `plan().kind`／`otherSuperadmins` 決定，API 回傳，前端不寫死（B 類 1）。
- 測試（單檔）：`test_settings_cas_*.py`——同群組別欄被改不誤拒、同欄被改拒、含到期 pending 的生效值、跨群組部分復原、409 body 形狀、by/at 退路；`test_settings_help_wording_*.py`（禁用詞守門，正對照用故意含禁用詞的字串）；既有 `test_settings_registry_t54.py` 要仍綠。
- 注意：動到寫入路徑；SPEC §5 已過 h11 審，實作前再讀一次 h11 的 G 系列意見（實作審查由 h12 做，規格疑義再請 h11 看）。

### S1d 通知元件通用化（h9；審查 h11；T84～T85）
h9 的 8 項（來源：h9 2026-11-13 訊息）：
1. 通用項目 `make_item(kind,label,old,new,phase,roles,recipients,risk,plain,ref,link)`＋`setting_item()` 轉接 registry 欄位。
2. **跨群組一次存檔＝單一端點** `POST /api/settings-center/batch`（body `{groups:{group:{values, expectedValues?}}, reason, preview?:true, undo?:true}`；伺服器先逐群組 `plan()` 預驗，任一不合法 400 全不寫；通過後一次 server-side `batch()` 只發**一則**通知；**不是跨群組原子**，中途失敗回 409 `{applied, failed}`）。設定頁在多於一個群組有草稿時呼叫它。**多群組復原（item 4 的多群組版）也走這支，但 S1d 不含**：
   - **現況（h9 確認）**：`undo`／`expectedValues` 在 /batch 尚未實作（需 S1c 的逐欄 CAS，不在 h9 的 base）；兩個鍵任一出現就回 400「多群組復原尚未開放」，不會被當成一般存檔。**單群組復原已只發一則「已復原到第 N 版」**。多群組復原＝**依賴 S1c**，與 S2 一起做（T86），不算 S1d 驗收。
   - 目標設計：`undo:true`＋每群組 `expectedValues`（S1c 的逐欄 CAS），否則復原會退化成 N 次單群組呼叫＝N 則通知；undo 模式的 409 body＝`{applied:[group…], failed:[{group, keys, by, at}]}`（跨群組＝逐群組、可部分復原；同群組整批拒絕）。（h11 意見，已採納；h9 實作時請確認。）
3. `plan()` 回 `recipients {superadmins, others, ignoredRoles, line}`；`preview_recipients()` 給確認視窗做 dry-run。**目前只支援最高管理者、角色片語、明列使用者；簽核人與受影響者的主管尚不支援**（列在 `ignoredRoles`，SPEC 已註明）——所以簽核流程頁的通知對象 SPEC §13-7 要降級（見 §6 開放問題）。
4. 復原（單／多群組）只發**一則**「已復原到第 N 版」。
5. 超過 8 行時最後一行放「完整明細：變更紀錄」連結，連到 `settings-center.html?tab=versions`（**頁面初始化要讀 `?tab=versions`**，S2 要接）。**現況（h9 確認）**：S1d 的頁面**已經**讀 `?tab=versions`（與 `&group=`），不必等 S2。限制：版本分頁是逐群組的，跨群組訊息的連結沒帶 group 時會開第一個群組的版本分頁；真正跨群組的「最近變更」是 S2 的內容。
6. `notify_change(kind,label,old,new,risk,roles,recipients…)` 一行式，給其他頁用；高敏感權限變更（h10 gate）呼叫它，`kind="permission", risk="security"` → 最高管理者站內＋LINE；介面先預留，h10 合併後接。
7. （PM 追加，T84 小項；**h9 回報分支尚未做**，隨 valueOf 之後 T83→T84 進）valueOf 測試 1–2 在 `MOTRIX_TRAIN=1` 且缺 node 時要**紅**不是 skip；放寬方法名守門 regex（`name: function/arrow`、`get name()`、`__define*__`／`__lookup*__`）（B 類 5）。
8. 合併順序：`fix/settings-center-valueof`（`2ad78c914`，h11 已核可）先進 T83；通知分支再 rebase（`settings-center.html` 同行衝突取 valueOf 版本）。前端剩：確認視窗顯示收件人、呼叫 batch 端點、`?tab=versions`。
- 測試：既有 `test_settings_change_notify_2026_11_13.py`（21 題）＋batch 端點／dry-run／復原合併／8 行連結（h9 回報目前 34 題：batch 端點 5、dry-run、plan recipients、單群組復原一則、>8 行連結、batch 合併、never-raises、標記）。
- 截圖：通知訊息範例（站內、LINE；批次合併一則；復原一則）＋設定中心儲存列（已在 v1）與確認視窗的收件人預覽。

### S2 設定中心外框（h4；審查 h11（後端）、h9（前端）；T86）
- 檔案：`frontend/pages/settings-center.html`（外框重做；舊的每群組卡片頁改成「設定頁」範本）、`backend/routers/settings_center.py`（新增 `GET /overview`、`GET /recent`；**待生效沿用既有 `GET /pending`**）、`data/shell_groups.json` 轉成執行期可讀的頁面登錄（建議放 `backend/helpers/settings_pages.py`，內容由 `make_shell_groups.py` 的輸出決定，守門＝與 registry 群組集合一致）。
- 內容（SPEC §14）：兩層導覽（分段＋分類＋白話設定頁名）、欄位級全域搜尋（名稱／代碼／說明／選項標籤／群組名）、「待生效 N」「最近變更」、總覽首頁、表格列（名稱＋代碼＋標籤｜目前值｜狀態徽章｜「?」）、草稿跨頁保留＋儲存列＋離開警告＋確認視窗（通知預覽、放寬 vs 只等待的文字取自 `plan().kind`）、手機抽屜與卡片、`?tab=versions`。
- **B 類 1、5**：確認視窗與待生效頁的文字由 `plan().kind`／`otherSuperadmins` 取；觸及 `settings-center.html` 時一併檢查 valueOf 守門。
- 測試：e2e（導覽、搜尋跳轉並閃框、草稿跨頁、儲存→確認→吐司、待生效頁撤銷、最近變更）＋手機 390px 無橫向捲動；後端 `overview`／`recent` 單檔測試；頁面登錄與 registry 群組集合一致的守門。
- 截圖：`h4/shot 11–26` 的同款畫面改用真實資料（總覽、群組頁、「?」展開、搜尋、草稿／儲存、含高風險儲存、單一最高管理者情境、待生效、最近變更、手機）。

### S3a 使用者權限矩陣（h4；審查 h12、h11；依賴 h10 gate；T87）
- 檔案：`frontend/pages/users.html`（權限段／彈窗）、`backend/routers/auth.py`＋新批次端點 `POST /api/users/permissions/batch`、`backend/helpers/module_registry.py`／`duty_roles.py`（`highSensitiveKeys`、`batchGrantRefused` 由 API 回）。
- 內容（SPEC §12）：職責角色（連動）為主、自訂角色併入；四條路徑（`PUT /api/users/{id}`、批次、範本套用、`POST /api/users`）都經 h10 的**單一檢查點**；財務三鍵「由角色決定」唯讀；授予高敏感與 C4 六鍵不能批次、取消可以（要原因）；範本逐人展開＋per-person revoked 清單＋略過最高管理者；通知經 S1d（高敏感另發 LINE）。
- 測試：四路徑各一測（含 create_user）；批次端點拒絕授予 C4／高敏感鍵；範本預覽展開與套用一致；superadmin 降級邊界（承 h10 的 M 級發現）。
- 截圖：`h4/index.html` 權限頁六張同款（選取、草稿、儲存確認含通知預覽、結果、範本逐人、手機）。

### S3b 信件收件矩陣（h4；審查 h9；T87）
- 檔案：`frontend/pages/mail-settings.html`、`backend/routers/settings*.py`＋`POST /api/settings/mail/batch`、`helpers/mail_types.py`；`google-calendar-settings.html` 的事件開關改成連結到 mail-settings 的行事曆欄（使用者裁示 #7）。
- 內容：67 種信件＋9 列「僅行事曆」；系統技術類可批次但確認視窗紅字；整批原子驗證；一筆稽核；通知經 S1d。
- 測試：批次端點原子性（任一不合法整批不寫）、系統技術類確認字樣、行事曆欄與 google-calendar 同一份資料。

### S5 §15 設定中心以外的變更管制（h3；審查 h10；T87，後端為主）
- **使用者 2026-11-13 選單裁示**：選「影響金額的加（建議）」——傳票科目（含憑證帳戶＝獎金傳票科目）、扣繳參數、T100 科目、管銷／公益口徑改成要等待或核准；獎金預設、營運目標、報價條款維持立即生效，但存檔後要通知。PM 在 S5 上線前截圖時會再提醒使用者這是行為改變。
- **開工前必須先決定的設計（h11 意見，採納）**：變更管制（`change_control`／pending／`plan()`）全在 `settings_registry.publish` 裡，而這四項的資料存在**登錄表之外**（例如傳票科目 `PUT /api/bonus/cases/voucher-accounts`）。「接既有機制不另造」的做法＝**把它們登記成登錄表群組＋舊儲存轉接器（legacy-store adapter）**，讓 `plan()`、待生效、放寬／第二位核准、`otherSuperadmins`、帳本全部沿用；**不做第二條 pending 路徑**。h4 先把這段寫進 SPEC §15（含每一項的「放寬方向」定義：哪種變更算放寬、哪些一律只等待），交 h11 做規格審，**過了 h3 才動程式**。h3 目前也在查這四處的寫入位置與能否不動核心，結果先回報再動。
- 順序：SPEC §15.A 補強（h4，r3.4）→ h11 複核 MUST-FIX 1–8 → S1c 的三個前置能力（h4）→ h3 實作四個群組與舊端點改造＋三項通知 → h10 審查。依據＝`h3/S5-WRITE-POINTS.md`（h3 的寫入點盤點，含 9 處讀取端、5 個傳票科目鍵、巢狀 T100 設定、口徑連動與標記）。
- 四項放寬方向：全部 `loosen="both"`（沒有有意義的大小方向；任何變更都要第二位最高管理者核准，只有一位時改為原因＋等待＋警告＋通知）。**讀取端：只改 4 個咽喉點（`load_versions`、`configured_accounts`、`_t100_config`、`profit_guard` 三個函式）改讀登錄表生效值**，不是「讀取端不改」（h11 MUST-FIX 1）。S5 範圍＝4 群組 9 欄（傳票科目 5、扣繳 1、T100 1、口徑 2），每欄要有 `risk_text`＋`impact_scope`；這 4 個群組是 `external=True`（不進設定中心一般清單、不計入 ①②）。h3 可先做不受影響的部分：三項「立即生效＋存檔後通知」。
- 範圍（SPEC §15）：傳票科目（含**憑證帳戶＝獎金傳票科目**，PM 已裁示）、扣繳參數、T100 科目、管銷／公益口徑 → 確認期或第二位最高管理者核准才生效（接既有 `change_control`／`config_ledger`，不另造機制；是否需第二人看 `otherSuperadmins`，SPEC §4-13）；獎金預設、營運目標、報價條款維持立即生效、存檔後發通知（S1d）。
- 原頁面改白話並加標示（名稱＋代碼＋標籤＋「?」），設定中心導覽「其他位置的設定」放連結。
- 同票**不處理**「整包寫入沒有並行控制」（INVENTORY §七，後續票），但實作時不得讓問題更糟（例如 operating-targets 只存一年）。
- 測試：每個新管制項一組（待生效、核准、撤銷、單一最高管理者情境）；通知範例。
- 這是**行為改變**（原本立即生效、之後要等待）：截圖要附「改前／改後」的確認視窗，並請使用者特別確認。

### S4a／S4b 乙／甲各設定頁（h12／h3；互審；T88）
- 依各自 `h12/`、`h3/` mockup 與盤點表（`data/settings-center-items.csv` 的【填】欄）逐頁換成 S2 的「設定頁」範本；`when` 逐欄寫進登錄表（盤點表備註有「建議 when」）。
- 乙 11 頁：安全 4、系統 5、業務 2（含 `builder_*` 13 組合一頁、清單與下載檔名、首頁外觀、小設定、回收筒既有卡片白話化、`external_hosts`／`internal_networks` 的清單編輯器〔只等待，不需第二人〕、retention 三欄放寬後果補寫…）。
- 甲：設定中心內 20 群組、7 個獨立頁（approval-settings、approval-delegates、expense-types、remit-kinds-settings、ledger-settings、legal-params、account-items）、設定中心以外 7 項（白話化＋連結；變更管制見 S5）。
- 每頁一個 commit，可獨立 revert；每頁 e2e 一題＋盤點表「可批次」與頁面實際勾選格一致（`gen_seed.py --check`）。
- 建議把 S4a／S4b 各再拆成兩班（先放使用者最常用的頁：報價、簽核、出納；再放其餘），由負責人與 PM 決定。

### S4c 丙份其餘頁（h4；審查 h12（暫定）；T89）
- 職責角色（批次綁定）、組織架構、permission-matrix 暫存區批次、簽核流程複製／範本（`POST /api/approval/flows/copy`；確認視窗先講進行中單據受影響件數）、LINE 個人偏好白話化。

### S6 個人 Email 偏好本人入口（h4；審查 h11；T89）
- `my-account.html` 新增「通知」分頁（本人可改；opt-out 清單；預設組合只含低風險）；管理員在 `users.html` 的代設端點不變；新增本人 GET／PUT。
- 注意 `my-account` 是 hichan-1 先前改過的頁（偏好分頁），開工前確認與 h1 的票無衝突。

## 4. h11 的 B 類 1～7 項（實作時處理；h11 已確認清單與順序）

| # | 內容 | 狀態 | 掛在哪個切片 |
|---|---|---|---|
| 1 | mock 的 wait2／loosen 文字改由 `plan().kind`（＋`otherSuperadmins`）取，確認視窗與待生效頁一律不寫死 | 待做 | S1c（後端回傳）＋S2（前端） |
| 2 | 乙 mockup DATA 殘留的 `ck`／`ckwhy` | **已由 h12 完成** | — |
| 3 | `make_shell_groups.py` 寫死路徑與無用 `style` 欄 | 路徑已改相對（`dc6b337bb`）；`style` 欄保留為預留（目前無頁面使用，gen_seed／--check 已支援）；h11 未驗證，可在 S2 時一併決定刪留 | S2 |
| 4 | h9 通用化通知＋h6 核心 C-a～C-c | 待做 | S1d（h9）、S1a（h6） |
| 5 | h9 的 valueOf 守門 regex 放寬（含 valueOf 測試在缺 node 時紅） | 待做 | S1d；任何觸及 `settings-center.html` 的切片都要檢查 |
| 6 | SPEC `login_greeting.py:112` → `:116` | **已完成** | — |
| 7 | §15 的七項：4 個影響金額要新增變更管制（傳票科目、扣繳參數、T100 科目、管銷／公益口徑）＋3 個維持立即但存檔後發通知（獎金預設、營運目標、報價條款） | 待做（新後端） | S5 |

## 5. 班次時間表（提案）

| 班次 | 內容 | 使用者要確認的截圖 |
|---|---|---|
| T83／T84（已在進行，非本計畫） | valueOf 修正；LINE 矩陣；notify v1；h10 sensitive-gate | LINE 事件頁、設定中心儲存列 |
| **T85** | S1a 核心補齊、S1c 登錄表（CAS／when／禁用詞）、S1d 通知通用化（若 T84 沒趕上） | LINE 頁不變、核心範例頁、通知訊息範例、確認視窗文字 |
| **T86** | S1b 核心元件補丁＋S2 設定中心外框 | 設定中心全新外框（總覽、導覽、搜尋、草稿／儲存、待生效、最近變更、手機） |
| **T87** | S3a 權限矩陣＋S3b 信件矩陣＋S5 §15 後端 | 權限頁、信件頁、新增變更管制後的確認視窗（改前／改後） |
| **T88** | S4a 乙＋S4b 甲（各頁逐批） | 各設定頁（先放最常用頁） |
| **T89** | S4c 丙其餘頁＋S6 本人入口 | 職責角色、簽核流程範本、我的帳號通知分頁 |
| 之後 | S7：預設組合、整包寫入並行控制、重跑 gen_seed（monitoring） | — |

## 6. 風險與開放問題（請 PM／使用者決定）

1. **班次號碼是推估**：T83／T84 的實際內容與凍結日由整合者決定；若 T84 吃不下 S1d，S1d 與 S1a、S1c 同進 T85。
2. **簽核流程頁的通知對象（PM 已裁示：降級）**：h9 的元件目前不支援「簽核人、受影響者的主管」；先做「最高管理者＋角色片語＋明列使用者」三種，不擋 S3、S4c；「簽核人／主管」排到後續（S7）。
3. **每班只一個大改**：T86（外框）與 T87（權限＋信件＋§15）是使用者可見變化最大的兩班；若使用者想慢一點確認，可把 S3a／S3b／S5 拆到兩班。
4. **預設組合內容**（S7）要團隊提案、使用者看過才上線；在那之前「套用預設組合」按鈕顯示「之後提供」。
5. **審查者分流（PM 已裁示）**：S1c 改 h12、S3b 改 h9、S5 實作審 h10（規格審仍由 h11 先看）；h11 留 S1d、S2、S3a、S6。h11 另建議 S6、S4c 交 h12，PM 未回，S4c 暫定 h12、S6 維持 h11，開工前由 PM 確認。
6. **S5 是行為改變**（原本立即生效的金額設定改成要等待或核准）：使用者已於 2026-11-13 選單明確同意（見 S5）；上線前仍由 PM 在截圖時再提醒，並在 CHANGELOG 與給正式機的步驟檔寫明。
7. **S1b 是 S2 的班內關卡**：兩者同在 T86，S1b 必須先合進該班，S2 才能收；S1b 沒趕上就 S2 一起延到 T87。
7. **`style` 欄**（`form`／`preset-only`）目前無頁面使用，S2 時決定保留或刪除。
8. **h6 的核心審查**（h9 審）若出現結構性意見，S1a 的內容可能改變；S1b 等 S1a 合併後才開始。

## 7. 每班流程（給整合者與負責人）

1. 切片作者：分支開發 → 單檔測試 → 審查者審 → 修 → **截圖（第一道，進列車前）**→ PM 轉使用者確認。
2. 整合者：收進列車，跑 preflight（禁令解除後），出包。
3. **上線前截圖（第二道）**：用包或開發機 head 再截同樣畫面，PM 轉使用者；**使用者確認後才發布**。
4. 上線後：負責人把該切片在 `INVENTORY.md`／本檔的狀態改成已上線，並更新交接檔。
