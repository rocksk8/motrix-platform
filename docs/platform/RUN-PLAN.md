# 使用者離開期間的總計畫（RUN-PLAN）

> 2026-09-25 約 20:25 使用者交辦（更正：原寫 21:00）：「我人會離開幾天，偶爾遠端登入。所有功能都設計好、驗證、互相稽核、修改；最後備份開發機資料，做一次轉移升級測試驗證。決策由你決定；需要我決策的，先轉去做別的。視窗上下文太長時，由你判斷重新派發。」
> 主持：hichan-8d。本檔是唯一的進度與派工來源；每次巡視都更新 §4、§5。

## 1. 最終要達成的結果（使用者原話）

1. 既有的升級模組可以直接升級。
2. 系統模組化。
3. 未來的編輯與追加功能，大部分由網頁自主增加；超出網頁能力的部分，才由底層增加模組或局部修改。

## 2. 完成的定義（全部打勾才算完成）

| # | 項目 | 驗收 |
|---|---|---|
| D1 | 11 個業務模組都在 `modules/<key>/` | 每個模組都通過「拿掉照常運作」的反向控制；L2 之間 import 為 0；L1→L2 逆向 import 為 0 |
| D1b | 驗證範圍跟著模組化縮小（使用者 2026-09-26：「共用端點驗證不需要全域」） | 常用 L1 helper 改動的選題比例 ≤30%；模組的題只載入 L1＋該模組；L1 與模組之間有契約題；選題比例每次都記錄（量測基準 2026-09-26：legal_params 74%、email_notify 81%、main.py 87%） |〔主持 2026-09-26：全域入口 db.get_db、db.init_db、auth._require_user、auth._tok 與 main.py 列為已知例外，因為每條請求都會經過；其餘名稱以 ≤30% 驗收〕〔補充（2026-09-26 04:12）：閉包之後 db 內部的中位數是 81.9%，原因是遷移函式都被 init_db 呼叫，而 conftest 用 init_db ⇒ **db 整份列為已知例外**；階段 B 把表與 migration 搬進模組之後要重量一次，不再是例外的部分要拿掉〕
| D2 | 模組選配與啟停 | 產品設定檔打包、授權、管理者啟停都有 e2e |
| D3 | 底層串接點 P1～P7 | CUSTOMIZATION-SPEC §5 每一項都有測試；能力目錄可以列出所有模組的端點、provider、輸出、事件 |
| D4 | 網頁自主增加（P8 自訂模組引擎＋建構介面、P9 拖曳排版器） | e2e：在網頁上建立一個測試用的自訂模組（欄位、流程、簽核、通知、輸出），不改任何程式就能新增、送審、核准、匯出 PDF／Excel；排版器可以調整內建模組的列表、表單、按鈕、選單、輸出版型，並依角色套用 |
| D5 | 狀態目錄 | 兩份 STATES 裡「高」全部處理；「中」處理或寫明理由延後 |
| D6 | 交叉稽核 | 每一條工作線都有別人的稽核；必修全部關閉；產出 `IMPROVEMENT-REPORT.md` |
| D7 | 最終轉移升級驗證 | 見 §3 |
| D8 | 參考設計與法規對照（使用者 21:15 追加）：參考鼎新 ERP 的功能設計、NUEiP 的區塊自訂方式，結合使用者體驗、組織流程與台灣法規 | `BENCHMARK.md`（研究代理產出，附來源）；缺口中「法規必要」的全部處理，「強烈建議」的排進 ROADMAP 並完成可以在這一輪做的部分 |
| D9 | 復盤 | `RETROSPECTIVE.md`：目標與結果、做對與做錯、每一次更正、假綠燈與稽核抓到的問題、流程上的改善、下一輪建議；在 D7 之後寫 |

## 3. 最終轉移升級驗證（D7）

1. **備份開發機資料**：完整備份 V9 開發目錄 `C:\Users\hichan\Desktop\MOTRIX-ERP` 的資料庫與資料目錄，放到 `D:\MOTRIX-FINAL-DRILL\source-backup\`（用 Online Backup API，附雜湊清單）。V9 原目錄本身完全不動。
2. 把 V9 目錄**複製**成演練用的安裝目錄 `D:\MOTRIX-FINAL-DRILL\v9-install\`；路徑不可以含 `V9.0`，並放好開發機標記。
3. 用最新 `platform` 打包的部署包，照 UPGRADE-RUNBOOK 逐步執行：預檢、備份與試還原、轉換、驗證。
4. 在轉換後的目錄啟動新版，跑全量測試與一輪 e2e 冒煙測試（登入、報價、案件、傳票、獎金、出納、報表、模組管理、自訂模組）。
5. 分別演練「只回程式」與「完整回滾」：回滾後 V9 可以啟動，雜湊逐一相等。
6. 產出 `docs/platform/FINAL-DRILL-REPORT.md`：每一步的耗時、結果、雜湊、發現的問題與處置。
7. 刪除演練用的暫存（備份保留到使用者回來）。

## 4. 待使用者決策（先記下，先做別的）

| # | 題目 | 背景 | 我的建議 |
|---|---|---|---|
| U1 | V9 部署儀表板的 `success` 未賦值（S-P01）要不要在 V9 修 | 部署、回滾的歷史不會寫入；新版已修 | 修（開發工具，不影響正式機執行） |
| U2 | V9 正式機的四個備份缺陷（S-CD02 損毀庫照常備份、S-CC07 時鐘跳動清光快照、S-CC06 月底月備份缺漏、S-CN03 告警寄不出去時沒有任何管道）要不要在 V9 修 | 新版已修（C，2f528951） | 修 S-CC07 與 S-CD02（會造成資料損失）；另外兩項等換版 |
| U3 | 用**正式機資料的複本**再做一次換版演練（PLAYBOOK 階段 7） | 最終驗證先用開發機資料 | 使用者回來後提供複本 |
| U4 | 獎金分潤的**扣繳（5%，起扣 90,501）與二代健保補充保費（超過投保金額 4 倍）**由誰算？ | BENCHMARK §6.2／6.3：目前系統只留一行金額 0 的「代扣稅款」由出納手填；要算補充保費需要員工的投保金額與全年累計（系統沒有這些資料） | 若公司另有薪資系統負責，就在 MOTRIX 標示「由薪資系統處理」並匯出資料；若要 MOTRIX 算，需補員工投保金額欄位。**需要你告訴我目前實務怎麼做** |
| U5 | 個資的**保存期限與到期刪除**（各類資料留多久、到期刪除或去識別化；與「月備份永久保存」衝突） | 個資法 §11 III | 需要公司政策，建議請會計或法務顧問訂年限；機制可以先做，年限由你填 |
| U6 | 電子發票是否串接加值中心 | BENCHMARK §6.1；需要選定廠商並申請帳號 | 先做匯入或對帳；串接等你選定廠商 |
| U7 | 行動簽核的通知管道（LINE 官方帳號或推播） | 需要外部帳號 | 先做行動版頁面；管道做成 provider，等你決定 |
| U8 | 標案雷達若要販售，先向工程會確認資料使用授權 | 政府電子採購網的使用要點 | 販售前確認；自用不受影響 |
| U9 | 稽核紀錄保存年限（目前 730 天）是否要依商業會計法拉長到 5 年或 10 年 | 需要判斷稽核紀錄算不算會計憑證 | 請會計顧問判斷 |
| U10 | 正式機的 Python 版本與套件 | 開發機專案 venv 要對齊正式機，「在正式機環境驗證過」才成立；主持不在使用者離開時連正式機 | 回來後在儀表板按一次「部署前健康檢查」即自動存成 backend/tools/prod_env.json，B 的 venv 工具會比對並提示 |

### 新的待決（2026-09-26 01:40 起，使用者離線中記下）

| # | 題目 | 背景 | 我的建議 |
|---|---|---|---|
| U11 | **V9 正式機的勞報單二代健保補充保費少算 1 元**（D 稽核 D-1） | V9 `backend/routers/payslips.py:99` 用 Python `round()`，是銀行家捨入：.5 時取偶數；健保署規定四捨五入。實測 35,000、55,000、75,000…（每 20,000 一個）都少 1 元，畫面用 Math.round 顯示正確值，存檔卻少 1 元。新版會修 | 在 V9 修一行（改成四捨五入）並附測試，和 N-1 一起在你回來後決定要不要出包；已經開過的單要不要回補，需要會計判斷 |
| U12 | **V9 正式機的 Google 地圖額度警戒信從來沒寄出去**（A 做信件收件設定時發現） | V9 `helpers/geo.py:764` 呼叫 `_send_raising(subject, body)` 少了收件人參數，一執行就 TypeError。例外被背景工作接住，所以每 6 小時記一筆 exception log，服務不受影響；額度硬上限另外每次都會檢查，仍然有效。新版已修 | 風險低（只是少一封預警信）。可以併進 U11／N-1 的 V9 修補包，由你決定要不要出 |
| U13 | **勞報單的法規年度，依「開單日」還是「給付日」？**（R 修正代理 O-2），以及**扣繳「元以下捨去」的法源**（O-5） | 目前依開單日套用規則：12 月開單、1 月才給付的單，會套到前一年度的門檻與費率。扣繳目前是元以下捨去，但沒有核對到法源 | 建議改依**給付日**（扣繳義務在給付時發生），請會計確認；O-5 也請會計確認捨去規則，要改只需改 `floor_amount` 一處 |〔補充（D 稽核 A-bonus O）：獎金補充保費的 1000 萬上限，目前套在計費基數而不是給付額，要請會計一併確認條文〕
| U14 | **自訂模組的草稿，同權限的人可不可以修改、送出別人的草稿？**（D 稽核 C-O3；屬於權限範圍，依 PLAYBOOK §F 要問使用者） | 目前有同一個模組權限的人，就能改、送別人建立的草稿 | 建議：草稿只有建立者與超級管理員可以修改、送出，其他人只能看；送出之後的簽核照流程走。決定之前維持現行行為 |
| U15 | **系統技術類信件（備份、磁碟、憑證告警），能不能讓所有超級管理員都退訂？**（D 稽核 a-mail 建議 M-S1） | 目前可以，全部退訂之後就沒有人收到；設定頁會標出「目前沒有人會收到」 | 建議：系統技術類「至少保留一位超級管理員」不可以退訂；最後一位退訂時要擋下並說明。這會限制個人退訂，所以要你決定 |
| U16 | **子代理推送共用分支、刪除自己的 clone，被權限規則擋下**（個資告知代理，05:12） | 它把月台登記推到 platform 時，被判定為「修改共用資源」而拒絕；刪 clone 之前的占用查詢也被拒絕。依規則，主持不代替它做被拒的動作（避免繞過權限）。它的分支已經在 GitHub，主持以自己的判斷把它排進列車 | 請你決定：①要不要刪 `C:\Users\hichan\.claude\worktrees\agent-aa2f19501a0fe66d3`（clone＋測試庫）②往後子代理推 RUN-PLAN 這類文件是否要放行（需要調整權限設定，由你做） |
| U17 | **角色版面要「整份覆寫」還是「只存差異、疊加在公司版上」？**（P9 拖曳排版器） | 目前是整份覆寫：角色第一次覆寫時複製公司版；之後公司版再改，已經存在的角色版不會跟著變 | 建議改成**疊加**：角色版只存「和公司版不同的點」，公司版改了，沒有被角色覆寫的地方會自動跟著改。比較符合「公司預設＋角色覆寫」的直覺，代價是 resolve 要改成合併兩層（L0） |
| U11 補充 | V9 的開票申請（`routers/invoice_vouchers.py:325、358、385、386`）也用內建 `round()` 計算未稅額與稅額，遇到 .5 時會取偶數，少 1 元 | 營業稅的計算應該四捨五入；新版另派修正 | 和 U11 一起決定 V9 要不要修 |

### 裁示結果（2026-09-25 21:51 使用者表單；已寫進 CORE-SPEC「使用者裁示」）

| # | 裁示 | 落地 |
|---|---|---|
| U1 | 不修 V9 | 無 |
| U2 | V9 只修 S-CC07、S-CD02 | 子代理在 V9 repo 的獨立 worktree 修，commit＋push；打包部署由使用者 |
| U3 | 只用開發機資料 | D7 不變；PLAYBOOK 階段 7 的正式機複本演練取消 |
| U4 | MOTRIX 自動計算扣繳與補充保費 | 併入 A 線 ③ 獎金三項（需 R1 法規參數版本） |
| U5 | 到期去識別化，預設離職／結案後 7 年，可調 | 新增 R7（接在 R1～R3 之後） |
| U6 | 電子發票不做 | 從 ROADMAP R 移除 |
| U7 | 行動版頁面＋Email，管道做成 provider | 排入階段 S |
| U8 | 自用，販售前再確認 | README 標示；對外產品設定檔預設不含 |
| U9 | 稽核紀錄 5 年 | 併入 R7 |
| U10 | ✅ 23:07 取得：正式機 **Python 3.12.10**、fastapi 0.141.1、starlette 1.3.1、uvicorn 0.52.0、pydantic 2.13.4（共 46 個套件，存在 backend/tools/prod_env.json）。依使用者裁示不綁版本，只作提示 | ⚠ 開發機過去的測試環境（hermes：fastapi 0.133）比正式機舊；A2 在 0.141 上抓到平台路由衝突漏擋（修正中）。V9 產品碼沒有走訪 app.routes（已 grep） |

### 使用者回來時要知道的事（R1～R3 合回帶出，不需要現在決定）

- **2027 年（民國 116 年）法規參數**：最低工資 30,900 元還沒核定，起扣標準也還沒公告，所以系統沒有預設值。公告之後，由管理者在「法規參數設定」按「新增下一年度」填入；進入 12 月還沒設定時，系統會顯示提示。
- **營業稅法 §7、§8 條文**：沒有取得逐字條文，只查到摘要。§8 做成「第一項＋說明欄必填（填款次與內容）」。建議請會計確認下拉選單的款名。〔更正（X-R，2026-09-26，稽核 S-4）：§8 已取得逐字條文（全國法規資料庫，整編截止 115-09-18），改成第 1～32 款逐字下拉（第 7 款已刪除），說明欄選填；§7 仍是摘要〕

## 5. 派工佇列（依序；做完一項就把同一條線的下一項派出去）

| 線 | 負責 | 佇列 |
|---|---|---|
| 平台與模組 | A | ① 9c 全量合回 → ② STATES-PLATFORM 4 項 → ③ 獎金三項（IP-7、IP-8）→ ④ 階段 A 剩餘（A8b、A9、A10、A12）→ ⑤ P1 能力目錄＋P3 模組描述＋P6 事件匯流排 → ⑥ 階段 B 搬遷（M12、M10、M02、M04、M05、M06、M07、M03、M08、M01，每個照 PLAYBOOK §B，同時登記進能力目錄） |
| 測試、守門、打包 | B | ① G1／G2 合回 → ② 9c① 演練與合回 → ③ G3／G4 → ④ P7 模組更新包（含儀表板的操作介面由主持接）→ ⑤ 階段 C：頁面搬進模組、選單由登錄表產生 → ⑥ 每個模組搬遷後的測試搬移與 modtest 調整 |
| 資料、輸出、升級 | C | ① A11＋states-fix 全量合回 → ② A8c 公司聯絡資料 → ③ P2 輸出引擎版型化 → ④ P4 自訂欄位命名空間＋P5 版面定義儲存 → ⑤ P8 自訂模組引擎（文件式儲存、通用 API、流程、輸出）→ ⑥ D7 最終轉移升級驗證 |
| 稽核 | D（hichan-08，2026-09-26 使用者新增） | 交叉稽核：① 法規 R1～R3 → ② B 的專案環境／requirements 守門／§C-13／全量依 commit 分檔 → ③ 主持的 P6、傳票修正、完整回滾預覽 → ④ C 的 P4／P5／P8（C 推上 origin 之後）→ ⑤ P8 前端、P1／P3（合回後）|
| 主持 | 8d | P6 事件匯流排（從 A 的佇列移過來，主持現在有空檔）；儀表板 D3（選配打包）、D5（模組狀態）、P7 的操作介面；P9 拖曳排版器（與 C 的 P5 串接）；P8 建構介面的前端；D8 缺口分派；彙整稽核、IMPROVEMENT-REPORT、RETROSPECTIVE |

- **待排的交叉稽核**（CORE-SPEC §9d）：R1～R3 法規（609cd5b8）；B 的 .venv／requirements 守門／§C-13；C 的 P4／P5／P8；主持的 P6 事件匯流排、傳票修正、完整回滾預覽。負載允許時，每次派 1 個獨立代理。
- **這一輪要做（使用者 2026-09-26 裁示）**：其他蒐集個資的表單（客戶聯絡人等）加個資告知，沿用 R3，在 D7 前完成；負載允許時派子代理。P1＋P3 也等負載降下來再派（使用者裁示）。
- **信件收件設定＋用語正式化**（使用者 2026-09-26，見 CORE-SPEC 裁示表）：派給 A（email_notify、notification_prefs 的作者），排在 wip/a-bonus 合回之後、D7 之前。
- **ROADMAP 待辦**（R 帶出）：R2 附件形式的依據；客戶聯絡人等其他個資表單的告知機制（MODULE-GUIDE §11 標「未守門」）；privacy_notice_acks 在 M04 搬遷時改用模組自己的表。
- **D1 階段 B 模組搬遷分工**（2026-09-26 03:30，使用者裁示「轉移優先」；每個模組都照 PLAYBOOK §B，搬完記選題比例（D1b），上月台）：
  - A：M12 每日任務（完成，搭第三班）→ M10（進行中）→ M03 → M01
  - B：M08（2026-09-26 04:47 從 A 移過來；C4 開工時暫停）〔2026-09-26 05:39 佇列：M08 → dep_graph／test_map 一致性守門（比照 UNIT-INDEX --check，附反向控制）→ O6 → C4（開工時主持宣布凍結）。M08 要排在 c-module-files 之後上車〕
  - C：M02 crm／dev_crm（進行中，wip/c-m02）→ M04 → M05 → M06 → M07
  - 搬遷順序依 ROADMAP 階段 B 的相依；兩邊要動同一個 L1 helper 時，先在 RUN-PLAN §6 講一聲再動
- **列車月台**（PLAYBOOK §G3；各線登記：分支｜HEAD｜差異題結果｜是否動 fixture 層／main）：
  - C｜`wip/c-module-files`（主持裁示：dep_scan 列舉模組檔改用 `core.source_tree.module_files`；**A 的 M03 現在就需要，請排在車頭附近**；C 的 M04、B 的 M08 也依賴）｜b36b3719｜tests/platform＋modules＋test_spec_coverage（-n 2、低優先權）：1087 過；正對照（合成樹子目錄檔與它的跨組 import、tests/ 不算）、一致性題（dep_scan＝source_tree、test_map.unit_name＝dep_scan 單位）、突變 2 項皆紅｜fixture 層／main：無；L0 新增 `module_files`（CORE 暫取 1.21）；只加覆蓋，現有單位名稱不變
  - C｜`wip/c-refopt`（P8 前端代理回報：參照欄選項也檢查被參照那一方的讀取權限——custom:<模組>、customers；沒有 ⇒ 403）｜825b17f5｜tests/platform＋modules＋自訂模組／定義庫＋新題＋spec_coverage（-n 2、低優先權）：1151 過；突變 3 項皆紅｜fixture 層／main：無；L1 新增參數（CORE 暫取 1.21）
  - C｜`wip/c-case-access-2`（取代 wip/c-case-access 7c056468：已 rebase 到 origin、含稽核 D CA-M1／S1／S2／O1 修正；主持裁示：案件存取守門下沉 L1；**A 的 M01／M03／M05／M10 與 C 的 M04 依賴它**）｜a82da8ec｜合回閘門（tests/platform＋modules＋存取／授權／簽核佇列／出貨／網路規劃／開票／請款／承攬憑據等，-n 2、低優先權）：1471 過；CA 突變 7 項皆紅（前一版 3 項）｜fixture 層／main：無；L1 新增（CORE 暫取 1.21）；新串接點 IP-15 `case.present`（M01 → L1）；l2_import_baseline 刪 4 條邊；與 A wip/a-m10 的 IP-11 `case.access` 會交會（後上車的一方 rebase）
  - C｜`wip/c-audit-d-2`（〔第三班列車長 2026-09-26 06:3x：C-M3／C-M5／C-S1～S5／C-O1／U14 已隨第三班以 wip/c-audit-d 合回（CORE 1.22）；本分支只剩 C-M4 bc2cf522 未合回 ⇒ 請 C rebase 到 platform、只留 C-M4 再上車〕取代 wip/c-audit-d：第二批已合回，rebase 到 origin；AUDIT-D-C-P4P5P8 修正 C-M3／C-M5＋第二道防線、C-S1～S5、C-O1、U14，**加上 C-M4 公式 round 四捨五入**（接 R 的 legal_params.round_half_up））｜bf80789f｜合回閘門（tests/platform＋modules＋自訂模組／定義庫／版型／勞報單／待我簽核佇列／法規參數＋spec_coverage，-n 2、低優先權）：1238 過 1 紅（UNIT-INDEX 過期，已重產）；突變 15 項皆紅｜fixture 層／main：無；L1 新增與收緊驗證（CORE 暫取 1.21）
  - C｜`wip/c-m02`（D1 階段 B：M02 業務開發搬進 `modules/crm`）｜927b4599（207bc0df 之後只加 SPEC.md 與文件）｜全量未跑；合回閘門：tests/platform 661 過＋業務開發／報價刪除相關 30 檔（含 e2e）1009 過、開報價清單的 e2e 14 過；**反向控制**（刪掉 modules/crm）：啟動 ping 200、三個前綴 404、報價單照刪回 notice；tests/platform＋modules 891 過 2 紅＝`modules_json_lists_only_existing_units`（§B11 允許）與 `test_registry_matches_code`（登記表不認得「模組不在包內」；A 已在 wip/a-m10 修，IP-11 提供方已寫成 `modules/crm/…` 合新規則）；突變 5 項皆紅｜🔴 動 main.py（拿掉 dev_crm 的 import／掛載／排程，與 A 的 M12 改同一行）；M01 `routers/quotations.py` 刪報價單改走 IP-11（暫定號）；`quotations.html` 顯示 notice；刪 dev_cases 的 debt
  - A｜`wip/a-m10`（D1 階段 B：M12 每日任務＋M10 網路規劃搬進 modules/；**取代 wip/a-m12**，已含 D 稽核 M12 的 M-1／S-1～S-3、X-C-batch1 B-1、X-2 模組不在裁定、G2 要求 SPEC.md、正對照不綁 L2（X-2、Z-5）、case_read_scope 豁免反向控制）｜ca73e25e｜閘門（16865fa3，73 檔，-n 1、低優先權）：1692 過；之後兩個 commit 只動測試：受影響 82＋5 題綠。**§B-11 反向控制**（d2a95371，範圍＝tests/platform＋所有提到該模組的測試檔＋另一個模組的題）：拿掉 M12 ⇒ 1047 過 2 紅、拿掉 M10 ⇒ 913 過 2 紅，紅的都是允許清單（modules.json、UNIT-INDEX）｜突變：X-2 5/5、G2 SPEC 5/5、M12 主流程 4/4、B-1 6/6、§B-11 歸位 2/2、Z-5 3/3 皆紅；選題比例 M12 85.6%→16.4%、M10 74.8%→15.8%｜🔴 動 main.py（拿掉 daily_tasks／network_plans 掛載與排程）、L1 新增 helpers/daily_checks／system_checks、core.source_tree.module_installed（CORE 暫取，列車上 core_bump）；M01 `helpers/quotations`（IP-11 _CaseAccess，與 c-case-access 同檔，後上車者由 A 收斂成只剩 summary）、`routers/quotations.py`（階段 notice）、`helpers/case_stage_tasks.py`；fixture 層：無｜登記 2026-09-26 05:2x A，更新 06:1x
  - H｜`wip/h-p8-gaps`（P8 前端接上 C 的缺口 #3～#7：待我簽核列自訂模組單據＋通知點 custom: 開單、參照欄 ref-options 下拉＋搜尋（403 才手動）、建構器 ⑤ 參數表單依 outputBlockSpecs／主題與格式與簽核人來源只取目錄／when fail-safe 說明、首頁全部模組＋刪草稿二次確認、PDF 預覽；疊在 44b39103 之上）｜27fd6df1｜差異題 `modtest --base 3d457fdf`（236 檔、單程序、低優先權）：2016 過 3 skip 0 紅；新 e2e 11 題（test_e2e_p8_gaps）＋既有 P8 6 題綠；突變 16 項皆紅（拿掉點卡片轉頁那一項，只有「點卡片」那題紅，按鈕題本來就不經過它）｜fixture 層：無；main.py：無；後端：無；sidebar.js：不動（通知點擊改在 notif.js）；VR3 併進「系統」26a｜登記 2026-09-26 06:21 H
  - H｜`wip/h-p9`（P9 拖曳排版器＝D4 後半：layout 驗證器接 check_layout、`GET /api/layout/{模組}`、custom-layout.js 排版模型＋layout-runtime.js＋layout-editor.js 同頁編輯模式；標案雷達 1.3.0 列表／表單／按鈕依版面渲染、搜尋條件表單分兩區塊；CUSTOMIZATION-SPEC §3.10）｜46685cce｜差異題 `modtest --base origin/platform`（118 檔、1531 題、單程序、低優先權）：1529 過 2 紅（CHANGELOG 頂端≠CORE_VERSION、UNIT-INDEX）⇒ core_bump 暫取 1.21＋重產後 82 題複跑綠；新 e2e 4 題（編輯→角色覆寫→另一角色看公司預設→還原、個人層、問題標回＋未登記的點被拒、手機）＋tests/platform/test_p9_layout.py（合成模組）；突變 14 項皆紅（M14 補強斷言後轉紅）｜fixture 層：無；main.py：無；sidebar.js：不動；L1 新增（CORE 暫取 1.21，列車上再定號）；tests/test_definitions_store 三題改為拿掉 layout 驗證器（只驗儲存語意）｜登記 2026-09-26 06:33 H
- **全量名額排隊**（更新 2026-09-26 02:43）：§G3 生效後，新的全量改由列車統一跑。仍在跑、而且依規定跑完就直接合回的有：B 的 C1（合回閘門約 02:52）、C 的第二批全量。A 的 a-bonus 走合回閘門，不經過測試鎖。⚠ A 有一支孤兒 pytest（pid 53300），停不掉，已請使用者處理。**第一班列車預計約 03:15 發車**，要等月台上至少有 3 包（目前只有 x-r-fix 1 包）。
- **未結案的偶發失敗**（依〈偶發失敗先當產品競態〉，不以「單獨跑是綠的」結案；下次出現時第一件事是抓 dump，`faulthandler_timeout`／py-spy）：
  - O1：`test_archive_isolation` 在滿載的全量中紅 1 題（A2，23:0x；題名沒有留下），單檔與循序跑 670 題都是綠的。
    - ✅ **已查明（B，856e5497）**：原先歸因於「滿載」是錯的，實際是目錄狀態造成的。os.makedirs 遞迴建上層目錄時，呼叫到的是被 BK19 換掉的記錄版 makedirs；在全新的 worktree 裡 uploads 還不存在，所以多記了一筆上層目錄。開發樹裡 uploads 早就存在，因此只有全新 worktree 的全量會紅。修法：比對改成純函式，已登記寫入的上層目錄不算新缺口，並附 3 題反向控制。**這印證了「偶發失敗先當成真問題查」：它根本不是偶發。**
  - O2：`test_bonus_case_multi_approver_tier` 之後卡住十幾分鐘（A2，約 22:50，滿載時；沒有 dump），停在 multi_approver 之後、vouchers 的第一題；連跑三檔、開 faulthandler 都無法重現。
  - O5：`test_e2e_login_enter_submits::test_enter_logs_in[after_failed_attempt-webauthn]` 在 C1 全量（f3b59691）e2e 裡紅 1 次：等待導向 /index.html，8 秒逾時。單獨重跑 3 次都綠。這一輪含 core.pages（/pages 路由改由伺服器提供），要查它和登入導向是否有時序關係；下次出現時先抓頁面的網路紀錄與 dump。〔D 排除法（f6b25468）：與 /pages 無關。等待點 /index.html 由 StaticFiles 提供；這個情境要算兩次密碼雜湊。下次出現時抓兩次 login 請求的耗時〕
  - O3／O4：`test_e2e_hard_cap` 的單程序題、`test_e2e_shared_fixtures` 的 login_as（B 負責修，已知原因＝滿載時的時序）。
  - O6：`test_pytest_guards_2026_09_21::test_g2_a_corrupt_lock_file_lets_everyone_through` 在第二班列車全量（5ddd9f44）紅 1 次：子 pytest 收集 tests/ 時 `_hardcap_probe_*` 目錄被 `test_e2e_hard_cap` 同時刪掉（FileNotFoundError）。單獨重跑綠。是測試之間共用目錄的競態，不是列車造成（B）。
- 稽核：每一項完成、合回之後，照 CORE-SPEC §9d 的分配交叉稽核（A 審 C、B 審 A、C 審 B 與主持）；新的工作線也照這個輪替。
- 視窗上下文：各視窗會自動摘要，不會因為太長而中斷。若某個視窗出現重複、迷失或品質下降，就不再派工給它，改用新的子代理（獨立 worktree）接手；派工內容一律寫成自足的說明，並引用本檔與 PLAYBOOK，不依賴對話記憶。
- 巡視：主持每 30 分鐘（每小時 :13、:43）自動巡視一次；排程 7 天後自動失效，到期前重新建立，內容包括看各視窗狀態、看 git log、派出下一項、更新 §4／§5 與桌面交接檔。

## 6. 進度紀錄（最新在上）

- 2026-09-26 06:36：**第三班列車合回**（train/0926-0517，4 包：b-scope（車頭，fixture 層）→ c-ko2 → c-audit-d → cloud-pii-notice，全部上車；platform 2934bbc9）。
  - 取號：CORE 1.21 c-ko2（K-O2 句原被 cherry-pick 併進已合回的 1.17 段，移出另立一段）／1.22 c-audit-d／1.23 個資告知（core_bump）；b-scope 不升版。版本紀錄：個資蒐集告知 2026-09-26k（26e 已用）。報價表單 FORM_VERSION：個資告知改 V3.10（V3.9 已被 X-VAT 用），帳本 LEDGER 登記 V3.10。各包自帶的簿記 commit（c-audit-d d132336f、個資告知 71f68b2e／6cef4e32／f7fcc81a／2ae1d86d、manifest 19346d6b）在列車上略過、改由列車 commit 取號。git cherry：4 包皆無已合回的重複 commit。
  - 重產 UNIT-INDEX、dep_graph.json、test_map.json（後兩份自 01:02 未重產，主持追加）。
  - 全量（4f35abba，-n 4、低優先權）：非 e2e 4592 過 0 紅、e2e 418 過 0 紅；O6 未出現。重產 dep_graph／test_map 後 tests/platform 968 過；rebase 到 origin（帶進 modules.json 三行＋文件）後 tests/platform＋版本紀錄＋報價表單版號 992 過，再兩次 rebase（只有 .md）後版本紀錄、單位卡、G1、CHANGELOG 段落 62 過。
  - wip/c-audit-d-2 的 C-M3～U14 已隨本班合回，月台列保留並註記只剩 C-M4。

- 2026-09-26 06:34：**P9 拖曳排版器完成**，已上月台（wip/h-p9 46685cce；套用在 tender_radar：列表、表單、按鈕、頁內選單，公司／角色／個人三層；e2e 涵蓋角色隔離、還原、反向控制；突變 14 全紅）。新增 GET /api/layout/{module}（一般使用者讀自己角色的版面）。缺口：add_section 被 check_layout 擋、只守了列表欄。U17（角色覆寫是整份還是疊加）等使用者裁示。側欄套用要等 C4（B）。
- 2026-09-26 06:22：P8 前端缺口 #3～#7 完成並上月台（wip/h-p8-gaps 27fd6df1；e2e 11 題、突變 16 全紅；差異題 2016 過）。後端缺口「custom: 參照沒有檢查被參照模組的權限」交給 C。U14 的 canEdit 等 c-audit-d 合回之後再接（主持佇列）。另外 modtest 的 `--list` 會直接開跑，而不是只列清單，排進 ROADMAP 給 B。
- 2026-09-26 06:1x A：a-m10 更新到 ca73e25e（§B-11 兩個模組都只剩允許清單的紅；X-2／Z-5 正對照不綁 L2；case_read_scope 豁免補反向控制）；D 稽核 M12 的回覆欄已填（dfebd89d）。M03（wip/a-m03，本地）：前置 IP-16／IP-17、cherry-pick C 的 module_files、搬進 modules/supply/api/、案件頁 e2e 完成，§B-11 反向控制跑中。範圍外：origin 的 modules.json 裡 js:static/legal-round.js 未歸屬（dep_scan --check-modules）。
- 2026-09-26 06:13：D 審完 ⑫、⑬：a-m10（M10＋M12）必修 0，M12 M-1 已關閉 ⇒ 可以上第四班；c-m02 必修 M02-M1（真刪後有 33 題需要 M02 卻在模組外）⇒ 交給 C。PLAYBOOK §B-11 補充：收集錯誤也算不過。
- 2026-09-26 06:13 巡視：第三班列車的全量應該快跑完了（死線約 06:25）。C 的 CA-M1 修正上月台（c-case-access-2）；A 的 a-m10 修正已推；B 在做 M08；D 在審；P8 缺口與 P9 子代理在等背景測試。不派工。
- 2026-09-26 06:13 D：⑫ M02（`AUDIT-D-C-M02-move.md`）：必修 M02-M1——真刪 modules/crm、新範圍 940 passed／35 failed，33 題需要 M02 留在模組外（test_api_integration 11、dev_case_soft_delete 5、e2e unread 6…）。⑬（`AUDIT-D-A-M10-M12.md`，a-m10 d2a95371）：必修 0；**M12 M-1 關閉**（真刪 953 passed、2 failed 皆允許）；M10 真刪 885 passed、2 failed 皆允許、無收集錯誤；X-2 突變 7/7 紅。仍開：M02-M1、CA-M1。
- 2026-09-26 06:02：**系統性問題**：M12（D）、M04（C）的反向控制都抓到「守門的結果會隨 L2 模組在不在而改變」，共 5 道：IP 登記、正對照綁 dispatch.row、G1 的 L1 介面依使用者計算、UNIT-INDEX、case_read_scope。處置：與其每搬一個模組才抓一題，改由 B 做「core-only 反向控制」工具（modules/ 全拿掉跑 tests/platform），每一班列車都跑；G1 的介面定義不應該隨安裝的模組而變（交給 B）；其餘分給作者 A。已補 3 支 js 的歸屬（6945583e）。
- 2026-09-26 05:43 巡視：D 審 c-case-access，必修 CA-M1：「M01 不在就 404」用的是「表不存在」當判準，但這張表在每個安裝都存在，反向控制用空庫，驗到的是另一件事 ⇒ 交給 C，c-case-access 與疊在上面的 c-m04 暫緩上車。第三班列車進行中；P8 缺口子代理進行中；P9 在等背景測試。
- 2026-09-26 05:40 C：**`wip/c-module-files` 已上月台（b36b3719），A 可以在上面做 M03**。`core.source_tree.module_files(d)` 是「模組裡有哪些檔」唯一的定義（遞迴、排除 tests／migrations）；dep_scan 用它，單位名稱 `mod:<key>/<相對路徑>`（例 `mod:<key>/api/orders`）；`test_map.unit_name` 本來就產生同樣的名稱。另：`docs/platform/dep_graph.json`／`test_map.json` 自 01:02 起沒重產（origin 上 `test_map.py --check` 已不一致），modtest 讀的是這兩份 ⇒ 建議列車統一重產。
- 2026-09-26 05:19 D：⑭ case_access（`AUDIT-D-C-case-access.md`）：必修 CA-M1——「M01 不在⇒404」只在案件表不存在時成立，而 db.py 在每個安裝都建這張表 ⇒ M01 停用／不在包裡時照 owner 規則放行；判準要改成 M01 是否載入。守門正則漏 5 種寫法（建議改用 dep_scan.sql_tables）。M02 反向控制進行中。
- 2026-09-26 05:15：個資告知擴大完成（wip/cloud-pii-notice 2ae1d86d；11 頁有告知區塊；報價單、案件、完工單的聯絡人可以手動輸入，所以也補了告知）。它推月台登記與刪 clone 被權限擋下 ⇒ 記 U16，主持不代做；分支由主持排進第三班列車。
- 2026-09-26 05:2x A：a-m10 推上 origin（16865fa3，含 M12，取代 a-m12），D 的 ⑬ 可以開始。內容：D 稽核 M12 的 M-1（5 題移入模組）、S-1（SPEC.md＋G2 守門）、S-2（主流程三題）、S-3（ROADMAP）；補做 X-C-batch1 B-1（M12 搬遷前必修，當初漏了）：勾選／取消勾選／刪除各自提示，畫面顯示，任務 id 保留（主持裁示）。閘門與 §B-11 反向控制跑中。M03 開工（wip/a-m03，疊在 a-m10 上）。
- 2026-09-26 05:13 巡視：月台上有 a-m10（含 M12）、b-scope、c-audit-d、c-case-access、c-ko2、c-m02；個資告知約 05:10 會登記。D 派做 ⑫ M02、⑬ M10／M12、⑭ case_access 的合回前稽核。第三班列車約 05:30 發車（等 D 至少審完搬遷類）。
- 2026-09-26 05:07：第二班列車合回之後，主持派出兩個子代理：P8 前端接上缺口 #3～#7 與 custom: 通知點擊（wip/h-p8-gaps）；P9 拖曳排版器（wip/h-p9）。B 先完成 M08，再做 C4。§G3 補一條規則：全量跑的期間不可以改列車的樹。
- 2026-09-26 05:05：**第二班列車合回**（train/0926-0415，7 包：C3、c-d7-km1、c-p2-legal、a-mail-fix、x-vat-round、x-p1p3-fix、h-p8-frontend，全部上車；platform 10b30038）。
  - 取號：CORE 1.16 C3／1.17 c-d7-km1／1.18 c-p2-legal／1.19 a-mail-fix（`mail_types.MANAGED_ELSEWHERE` 另立一段，1.14 已合回不改寫）／1.20 P1P3；版本紀錄：案件管理/財務憑證 26e、外包名冊 26f、案件管理 26g、營運報表 26h、庫存管理 26i、財務憑證/T100匯出 26j；獎金分潤 X-VAT 句併入 26c、P8 前端併入系統 26a、報價單 25r 句尾補一句（皆未出貨）；IP-10 `approval.queue_items` 維持（origin 未使用；A 的 daily.check 上車時改取 IP-11）；tender_radar 1.1.0（a-mail＋C3 合併）→1.2.0（P1P3）。
  - 全量（5ddd9f44，-n 4、低優先權）：非 e2e 4402 過 8 紅、e2e 407 過 1 紅。7＋1 題**交會問題**，列車上修（d1afb50c 等兩筆）：C3 選單 L1 登錄缺 a-mail 的 mail-settings（對等守門）；core/l1_pages.json 缺 mail-settings／module-builder／custom-records；X-VAT 與 a-mail-fix 新題頁面路徑未經 source_tree（C1 守門）；單位卡缺 plat:menu／catalog／customization、definitions／pages／upgrade 公開介面缺新名稱；P8 驗收 e2e 通知查詢用單號、c-p2-legal 已改 ref_id＝`custom:<模組>:<單號>`；Alpine 頁母體 49（合併時處理）。修後相關題 1146 過（-n 2）；rebase 到 origin（只有文件）後版本紀錄、單位卡、G1 共 56 過。
  - 另 1 題非列車造成：`test_pytest_guards::test_g2_a_corrupt_lock_file_lets_everyone_through` 子 pytest 收集時 `backend/tests/_hardcap_probe_*` 被 hard_cap 題同時刪掉（FileNotFoundError），單獨重跑綠 ⇒ 登 **O6**（B：探針目錄不要放在會被收集的 tests/ 下）。
  - 待補（C／H）：前端通知點擊還不認 `custom:` ref_id（c-p2-legal 說「供前端開頁」，目前沒有頁面處理）。
- 2026-09-26 05:15 C（主持裁示，通知 B）：**`tools/platform/dep_scan.py` 列舉模組檔案改用 `core.source_tree`**。起因：M04 有三支 router、依 CORE-SPEC §3 放在 `modules/subcontract/api/`，而 dep_scan 只掃模組第一層（`d.glob("*.py")`）、source_tree 只認 `api.py`／`api/` ⇒ 兩份清單各走各的，任何一種放法都有一道守門看不到。改法：遞迴與排除（tests、migrations）只在 source_tree 定義一次（新增 `module_files(d)`），dep_scan 只使用；單位名稱 `mod:<key>/<相對路徑>`（例 `mod:subcontract/api/contractors`），現有單位名稱不變。附正對照、一致性題、突變。B 的 M08 若用到 dep_scan 的單位名稱，搬 `api/` 結構時會看到新名稱。
- 2026-09-26 05:00 C：**`wip/c-case-access` 已上月台（7c056468），A 可以依賴**。L1 `helpers/case_access.py` 提供 `CASE_ACCESS`、`is_document_approver`、`case_access_allowed`、`guard_case_access`；`helpers.quotations`／`helpers` 的同名匯入保留（同一物件，呼叫端不必改）。L1 其他檔新增讀 `quotations` 會被 `test_case_access_l1` 擋；案件表不存在 ⇒ 404。M01／M03／M05／M10 搬遷時：直接 `from helpers.case_access import …` 即不算對 M01 的相依（dep_scan 以定義所在歸屬）。
- 2026-09-26 04:56 D：⑩ M12 稽核（`AUDIT-D-A-M12-move.md`）：真的刪掉 modules/daily_tasks ⇒ 系統健康檢查 6 項照跑、端點 404、ping 200 ✅；**必修 M-1**：反向控制紅 9 題（§B-11 只允許 1），其中 test_case_stage_done_calendar 5 題與 test_em1 1 題需要 M12 卻留在模組外；另 2 題框架題（登記表、UNIT-INDEX）請主持裁定是否列入允許清單。
- 2026-09-26 04:54 B：M08 開工（D:\MOTRIX-PLATFORM-B17，wip/b-m08）。**動 L1 預告**：`/api/now` 與 `/api/company/tax|search`（GCIS 查統編，L1、M03、M04 都在用）從 `routers/dashboard.py` 拆出，成為 L1 router `routers/company_lookup.py`（端點路徑、權限、GCIS 額度設定鍵都不變）；地圖（map_points、map.html、/api/map）在 modules.json 歸 L1（主持確認）。其他線若在改 dashboard.py 的這兩段請告知。
- 2026-09-26 04:54：M08 裁示更正：主持先前指示 `_collect_income_items`／`_collect_tax_invoices` 由「M08 公開 provider」——**這是錯的**，那兩個函式收的是應收收入與進項發票，照主持自己的規則屬於「純資料、多個模組在用」⇒ 改為下沉 L1 中立位置（B 發現與 ROADMAP A8b 牴觸），M05 搬遷時收回 M05。拿掉 M08 時，出納與會計匯出不受影響。
- 2026-09-26 04:47：A 修好共用守門 X-2（模組不在包裡時豁免），M12、M10 搭第三班；B 的 scope 上月台，scope_rc 三項都選到而且真的紅。M08 從 A 移給 B，C4 之前先做。
- 2026-09-26 04:43 巡視：D 確認關閉 c-d7（K-M1、K-S3）、P1＋P3（P-M1、P-M2、P-S2）、A 的信件與獎金（M-M1、M-S2、A-S）。第二班列車進行中（04:14 發車）；第三班約 05:30 發車，車上有 b-scope、c-ko2、c-audit-d、c-m02、a-m12、個資告知。各線都在工作，不派工。
- 2026-09-26 04:39 D：c-d7 K-M1 關閉（c-d7-km1 2d9fcf1f：用錯備份、不相等也啟動、失敗也刪 3 項突變紅；相等條件的突變與 C 所說一致為等價）⇒ D7 稽核結案。
- 2026-09-26 04:37 D：P1＋P3 修正（x-p1p3-fix 5ddb0265）確認：P-M1、P-M2、P-S2 關閉（D 突變 5 項全紅）⇒ 結案，列車合回後生效。
- 2026-09-26 04:35 D：A 的信件（M-M1、M-S2）與獎金（A-S1、A-S2）回覆確認：在 wip/a-mail-fix 6c5a2ac7 重做原本存活的 E03、E09、A04 與 A-S2 突變，全紅 ⇒ 兩份結案（修正合回後生效）。
- 2026-09-26 04:32：裁示案件存取規則下沉到 L1 helpers/case_access.py（C 做；A 的 M01／M03／M05／M10 搬遷以此為前提）。共用守門 test_registry_matches_code 在「模組不在包裡」時會誤報，交給作者 A 修。C 的 K-O2 守門改推新分支 wip/c-ko2，因為 c-d7-km1 已經在第二班車上。
- 2026-09-26 04:35 C：D1 階段 B 開工 M04 外包工班（key `subcontract`，worktree C24、wip/c-m04）。會動到的共用處：①**L1 `helpers/dates.py` 新增 `normalize_date`**（自 M01 `helpers/recognition.py` 下沉；recognition 改為從 dates 匯入同名，M01 呼叫端不變）；②M01 `routers/quotations.py`：案件整包的承攬派工段改走 M04 提供者（不在 ⇒ 那一段回 404 說明）；M01 新增提供者讓 M04 把派工品項匯入報價單（不再 import `save_quotation_json`）；③M05 `routers/cashier.py`、M06 `routers/accounting_export.py`：`_voucher_public` 改走 M04 提供者；④`main.py` 拿掉三支 router；`sidebar.js` MODULE_PAGES；`modules.json`。串接點編號暫用 IP-12～（列車定號）。
- 2026-09-26 04:30 D：R1～R3 回覆確認 ⇒ 結案（D-1 35,000→739、D-2 並行紀錄保留、S-3 損毀 409；重做突變 4 項全紅）。O-2（開單日＝給付日）需使用者裁示、O-5 需會計確認。
- 2026-09-26 04:24 D：⑪ P8 前端回覆確認（6f9a4902）⇒ 結案：S1（F05 重做紅）、S2（逾時放行突變紅）、O1（驗收題改走網頁授權）。
- 2026-09-26 04:19：D 關閉確認 D1b（b-scope 可以上第三班；D 用 email_notify 另一個真突變驗證閉包在第二個模組也成立）與 C 的 P4／P5／P8 必修（C-M4 等 round_half_up）。PLAYBOOK 新增 §C-14：腳本與 git 不可以用 `;` 串接（一晚兩次）。
- 2026-09-26 04:18 D：D1b S-M1 關閉（閉包突變 2 項紅；B 沒見過的 email_notify._users_emails 真突變「選到且紅」；scope_rc 實跑兩項皆過）。C 的 P4／P5／P8：C-M1、M2、M3、M5 關閉（在 c-audit-d d132336f 驗證，探針重跑＋突變 5 紅），C-M4 仍開（等 round_half_up）。〔更正：上一個 commit 3729e8b3 的訊息寫了 D1b，實際只含 C 的確認；D1b 在這一筆〕
- 2026-09-26 04:14 巡視：**第二班列車發車**，由列車長子代理操作。車上 7 包：C3 → c-d7-km1 → c-p2-legal → a-mail-fix → x-vat-round → x-p1p3-fix → h-p8-frontend。b-scope 等 D 確認後搭第三班，c-m02、a-m12 也搭第三班，約 05:30 發車。各線都在工作。
- 2026-09-26 04:12：B 修完 D1b 的 S-M1（模組內引用閉包、scope_rc 反向控制工具），閘門綠了就上月台，D 做關閉確認。閉包後重新量測：legal_params ≤17.8%、email_notify 中位數 20.6%、auth 31.6%、db 81.9%（整份列為例外）。C3 已上月台。
- 2026-09-26 04:10：營業稅與金額捨入統一完成，已上月台（wip/x-vat-round e786cb54）：後端 37 處、前端的金額計算全部改走 L1 legal_params.round_half_up／MotrixLegalRound，擴大守門範圍，突變 60 紅、5 處等價。實例：10,015×30% 原本存 3,004、畫面顯示 3,005；外包稅額 10,010×5% 原本存 500、應為 501。剩下兩項：公式引擎的 round 已交給 C（C-M4）；`:,.0f` 格式化 23 處只影響帶角分的顯示，排進 ROADMAP，不擋。
- 2026-09-26 04:09：**第一班列車合回**（a-mail、x-r-fix、x-unitcard；CORE 1.14／1.15）。
  - 全量：e2e 394 全綠；非 e2e 4211 過、7 紅。7 題**全部是交會問題**，每一包自己都綠，疊在一起才紅：x-r-fix 的捨入守門 × a-bonus 的扣繳與補充保費；C1 的頁面路徑守門 × a-mail 的題；單位卡 × C1 的新名稱與 core.pages；Alpine 頁母體 × a-mail 新頁；存檔欄位標記 × a-mail 新頁。
  - 主持在列車上修好（01f9f293），受影響的 309 題全綠，rebase 到 origin（只有文件改動）後重跑版本紀錄、單位卡、G1，共 52 題全綠，推上 platform。
  - 教訓：這正是「列車一次驗整批」的價值，各自的閘門都抓不到交會問題。
- 2026-09-26 03:58 D：確認 B 對 AUDIT-D-B-env-guards 的回覆（b-scope 3a62d617）：必修 B-M1～M3 全部關閉（D 重做突變 5 項全紅，含原本存活的 B02／B07 類）。⚠ 與 D1b 同分支，b-scope 要等 S-M1 關閉才能合回。
- 2026-09-26 03:49 D：預先查核 c-d7 的 K-M1 修正（本機 e16de793）：方向正確（第一份備份＋與原始庫比邏輯內容）；**但流程順序沒有題目**（突變 K01 存活），補題後才能關。回覆欄未填。
- 2026-09-26 03:49：**D1b 第一個真實的模組數據**：M12 搬進 modules/daily_tasks 之後，只改 M12 自己的檔，選題從 85.6% 降到 16.4%（3941 → 757 題，其中 659 題是每次必跑的契約題）。反向控制：刪掉整個模組之後，系統健康檢查照跑。A 的 a-mail-fix（D 的必修與建議）與 M12 都在跑閘門（改 -n 1，不搶測試鎖）。U15 記入。
- 2026-09-26 03:48：D 審 D1b 選題縮小，必修 S-M1：名稱層級選題看不到模組內的呼叫關係。真突變 `_as_date` ⇒ 新選題的 678 題全綠，但被拿掉的 r1 題有 6 題紅，**會漏抓**。scope 包在關閉之前不可以上車；B 修的方向是在模組內做引用閉包。這正是「選題變小＝少跑題，漏了會出事」所以要先稽核的原因。C3 可以先單獨上車。
- 2026-09-26 03:47 D：⑨ D1b 選題（`AUDIT-D-B-D1b-scope.md`）：**必修 S-M1**——名稱層級只看被改的頂層名稱，私有函式被改時呼叫它的公開函式的使用者全被拿掉；真突變 legal_params._as_date：新選題 48 檔 678 題全綠，被拿掉的 test_legal_params_r1 6 紅（舊規則有選到）。建議在模組內做呼叫閉包並把 §C-11a ⑤ 落實成題。⑩ M12 還沒上月台；⑪ origin 的 h-p8-frontend 仍是 ece37cf1，沒有新狀態。
- 2026-09-26 03:43 巡視：第一班列車的全量非 e2e 段跑到 80%，還沒有紅。〔更正：這句是錯的，是只看記錄檔最後幾行就下的結論。記錄檔在 10%、13%、20% 各有 F，至少 4 題紅，題名要等整段跑完才會列出〕月台上等下一班的有：c-p2-legal、c-d7-km1，另有 C3、scope、P1P3、VAT 將陸續上來。各線都在工作，不派工。
- 2026-09-26 03:50 C：D1 階段 B 開工 M02 業務開發（key `crm`，worktree C20、wip/c-m02）。會動到的共用處：`main.py`（拿掉 dev_crm 的 import／掛載／排程——A 的 M12 也改同一行 import，合回時由後到的一方解）；`routers/quotations.py` 刪報價單那一段（直寫 `dev_cases` 的 debt 改成 M01 宣告事件 `quotation.deleted`、M02 訂閱解除轉建連結，刪掉 table_write_exceptions 那一筆）；`frontend/static/sidebar.js` MODULE_PAGES；`docs/platform/modules.json`。不動 L1 helper。
- 2026-09-26 03:30：C 的 p2-legal（第二批）上月台；c-d7 修好 K-M1，預演第 5 次 11 步全過，第一份備份完整回滾後邏輯內容等於原始庫，排在閘門後上月台。撞號提醒：IP-10（C 的 approval.queue_items 與 A 的 daily.check）、版本紀錄 26d（第一班列車已經給勞報單用了）⇒ 下一班車統一重排。§5 補上階段 B 分工。
- 2026-09-26 03:29：D 完成 ⑥～⑧：a-bonus 必修 0（建議 2）；a-mail 必修 1（M-M1 只缺題目、行為正確 ⇒ 不下車，A 另開小包補）；C1 必修 1（P-M1：模組可以把 L1 頁面宣告成自己的，停用後登入頁會 404 ⇒ 交給 B）。D 的新佇列：⑨ D1b 選題、⑩ M12、⑪ P8 前端。
- 2026-09-26 03:28 D：⑥ A 的獎金＋U4（`AUDIT-D-A-bonus-U4.md`，已合回，改為合回後稽核）：必修 0；主持點名三點都成立；建議 A-S1（全年累計只算已發放沒有題目）、A-S2（投保金額設定整份覆寫，壞 JSON 時會清光）。⑥～⑧ 與 d7 全部完成。
- 2026-09-26 03:21 D：⑧ B 的 C1 稽核（`AUDIT-D-B-C1-pages.md`）：必修 P-M1——模組 manifest 可把 L1 頁面（login.html）宣告成自己的，模組停用後登入頁回 404 提示頁（探針實證），建議 L1 頁面明確清單＋衝突拒絕。O5：等待點 /index.html 不經 core.pages、登入鎖定每題重設 ⇒ 無關聯證據；下次抓 /api/auth/login 兩次耗時。
- 2026-09-26 03:17：**第一班列車發車**（train/0926-0313，worktree D:\MOTRIX-PLATFORM-TRAIN）。
  - 上車：a-mail（車頭，動到 L1 與 main）、x-r-fix、x-unitcard。
  - 列車上取號：a-mail 1.14、x-r-fix 1.15（core_bump）。版本紀錄方面，勞報單改用 26d（26c 已被獎金分潤用掉）、系統 26a 採用 origin 版。INTEGRATION-POINTS 與 MODULE-GUIDE 兩邊的內容都保留。UNIT-INDEX 已重產；CHANGELOG 沒有重複段落。
  - 全量開跑（-n 4），預估 55 分鐘，死線約 04:40。
  - ⚠ 主持的錯誤：解 x-r-fix 的衝突時，腳本的斷言擋下了，但同一個指令照樣把帶衝突標記的 version_manifest 加進 commit，列車上的 3ade2ad2 因此含有衝突標記。下一個 commit 已修正，列車最終的內容是乾淨的；中間那個 commit 不改寫。教訓：解衝突的腳本和 git add 不可以寫在同一個指令裡。
- 2026-09-26 03:15 D：⑦ wip/a-mail 合回前稽核（`AUDIT-D-A-mail-settings.md`）：必修 M-M1（找不到超級管理員時不退回一般管理員——行為正確但無題目，突變存活）；grep＋AST 查過所有寄信呼叫點，沒有未登記的寄送路徑。
- 2026-09-26 03:10：
  - B 的 C1（core.pages）已合回（8235c8ed＋97192db6，CORE 1.13；閘門 650 綠）。守門補上第三種寫死頁面路徑的寫法（基線 79 檔 138 處），順手修了 a-bonus 自己拼頁面路徑的 3 處。
  - A 的 a-bonus 已合回（55acc94e，CORE 1.12，26c）；a-mail 上月台；M12 搬遷中，順帶把系統健康檢查從每日任務模組拆到 L1，停用 M12 不再連帶停掉系統告警。
  - **D1b 量測**（「只改一個名稱」時的選題比例）：legal_params 全部 ≤18.4%；email_notify 中位數 22.4%（50／61 ≤30%）；db 一般函式 15～24%。仍高的是每條請求都會經過的入口：db.get_db 84.9%、db.init_db 73.3%、auth._require_user 75.1%、auth._tok 71.7%。主持裁示：這 4 個入口與 main.py 一樣列為**已知例外**（本質上就是全域入口），D1b 的 ≤30% 以其他名稱驗收；⑤ 的反向控制正在驗證沒被選中的 181 檔在突變下全綠。
- 2026-09-26 03:05：D 審 wip/c-d7：必修 K-M1（演練的完整回滾驗錯了對象，用的是已經轉換過的第二份備份）⇒ 從月台退回給 C，優先處理。A 的 a-bonus 已合回（0c009565）；D 改成合回後稽核。單位卡的強制範圍先限 backend/core/（7baf4d94，轉移優先）。
- 2026-09-26 03:05 D：換版優先——wip/c-d7 合回前稽核（`AUDIT-D-C-D7-drill.md`）：必修 K-M1（演練的完整回滾基準是已轉換的第二份備份，沒驗到還原原始 V9 庫；建議對調順序）；冒煙清單 `/api/definitions/custom_module` 在 origin 不存在（K-S2）。RUNTIME_STATE_SETTINGS 修正與守門成立，突變 6 全紅。接著 ⑥ A 的獎金（已合回，改為合回後稽核）、⑦ 信件、⑧ C1。
- 2026-09-26 02:56 X-UC：§G2 單位卡＋總索引＋守門完成，上月台（wip/x-unitcard 14ee6bc9）。L0 core/ 9 檔補卡；UNIT-INDEX 48 單位（有卡 9）。⚠ 合回之後：各線改到沒卡的 L0／L1 檔（helpers、db、main、新的 core/pages、core/menu）會被要求補卡；改了任何 L1 的 import 關係也要重產 UNIT-INDEX（直接使用者數會變）。
- 2026-09-26 02:52：使用者常設裁示：V9 的錯誤一律等換版，不再檢查 V9 有沒有同類問題，所有驗證以新版為準，**轉移流程優先**（D1 模組搬遷、D7）。已寫進 CORE-SPEC，並通知全部視窗。
- 2026-09-26 02:51：使用者表單裁示：U14 草稿只有建立者與超管可以改、送（交給 C）；U13 依給付日（x-r-fix 合回後派子代理做）；V9 的 N-1、U11、U11 補充、U12 全部等換版（N-1 分支保留不推）。已寫進 CORE-SPEC 裁示表。
- 2026-09-26 02:50 A：wip/a-bonus 合回（A 線 ③ 獎金三項＋U4）。通知（送審→輪到的簽核人＋代理人、核准→出納；信中不含金額；可個別關閉）、IP-8 `bonus.payouts`（出納頁獎金待發放、執行歷史、Excel；財務看不到）、IP-9 `expense.entries`（發放日列營運報表與月支出）、獎金傳票帶案件來源（案件頁相關傳票）、U4 經 IP-7 legal_params 撥付日選版自動算扣繳與補充保費（投保金額與全年累計；讀不到或缺投保金額⇒拒絕撥付；存版本與整份 rules 快照）。**全量在 fae19134**（4028＋e2e 388，0 紅）；**合回閘門在本 HEAD**（tests/platform＋獎金／出納／法規／報表題＋獎金與出納 e2e，899 passed；modtest --base 選到全量的 89%，依主持裁示改跑閘門）。突變：U4 14＋5＋1、通知與出納／報表 6、e2e 1，全紅。CORE 1.12（core_bump）、版本紀錄 2026-09-26c。待辦：R 的 round_half_up／floor_amount 隨列車合回後取代 U4 本地捨入；投保金額存 system_settings、會進一般每日 JSON——資料分類（F2？）請 C 判定；M07 停用而資料仍在時報表少列已發放獎金（觀察）。
- 2026-09-26 02:47：D 審 C 的 P4／P5／P8 後端完成（38a51a11，必修 5 項）。C-M1、C-M2 C 已經修了；C-M3～M5 與 5 項建議交給 C，C-M4 改用 R 的共用捨入函式。C-O3 記成 U14。D 的新佇列：⑥ a-bonus、⑦ a-mail、⑧ C1，都是合回前稽核。C 的 wip/c-d7 已上月台。
- 2026-09-26 02:46 D：④ C 的 P4／P5／P8 後端稽核完成（`AUDIT-D-C-P4P5P8.md`）：必修 5（簽核條件空值跳層、條件執行期 500、自動通過互指遞迴、round 銀行家捨入、NaN 寫入後模組列表 500），突變 14 全紅；C-O3「同模組權限可改送別人的草稿」需使用者裁示。佇列清空，等回覆或新派工。
- 2026-09-26 02:43 巡視：沒有新的合回。月台上 1 包（x-r-fix）；6 個子代理與 4 個視窗都在工作。第一班列車約 03:15 發車。
- 2026-09-26 02:43：B 的 C1 全量跑完，非 e2e 紅 1（VR3，已修）、e2e 紅 1（登錄為 O5），照 §G3「跑完直接合回」處理，合回閘門預估 02:52。main.py 兩邊都改了，是真的程式碼重疊，列車的全量要特別留意。D1b 進度：legal_params 從 75.4% 降到 18.9%；email_notify 單一名稱中位數 22.4%；auth 中位數 33.4%（_require_user 76.5%）；db 約 88%，原因是動態 SQL 被保守地擴大到資料表一跳，下一步把資料表一跳細到被改的函式。
- 2026-09-26 02:40：R1～R3 稽核修正完成，已登記月台（wip/x-r-fix 8cc2dd29，突變 14 全紅；共用捨入函式是 legal_params.round_half_up／floor_amount，寫進 IP-7 契約 1.2）。範圍外的發現：開票申請的營業稅也用了銀行家捨入 ⇒ 新版另派修正，V9 記成 U11 補充。O-2、O-5 記成 U13。
- 2026-09-26 02:22：使用者問「模組化之後驗證範圍應該會縮小」。主持用 modtest --dry-run --files 量了一次（總數 510 檔）：
  - core/events 13%、routers/cashier 16%、voucher.js 20%、tender_radar/match 20%；
  - **helpers/legal_params 74%、helpers/email_notify 81%、main.py 87%**。
  - 結論：模組與頁面的改動已經縮小；常用的 L1 helper 仍然幾乎等於全量，推測是選題沿著 main 的 import 閉包擴散。
    - 〔更正（2026-09-26 02:25，B 量測 cf8c2871，PLAYBOOK §C-11 附錄 a）：上面的推測是錯的。main 是彙整點，helper 被改時擴散不會經過 main。實際成因有兩個：一是遞移（legal_params 距離 ≥2 的有 2,231 題，只選直接依賴就會降到 19.8%）；二是寬扇出（email_notify 被 26 個單位直接 import、auth 被 46 個、db 更多）。設計改為：直接依賴 → 介面不變就不遞移 → 名稱層級選題 → 模組題只載入 L1＋該模組 → 靠契約題守 → 每次記錄選題比例〕
  - 已派給 B：選題改成「直接依賴＋介面不變規則＋模組題只載入 L1＋該模組」，並記錄選題比例，目標是常用 helper 在 30% 以下。
  - C 的 D7 預演抓到正式機升級一定會碰到的阻擋點：啟動時會寫入兩個節流日期，被判成「改寫設定」。已在 wip/c-d7 修好。
- 2026-09-26 02:18：A 完成 X06 題（cdf41cc0 已合回），信件收件設定做完（wip/a-mail，52 種信件類型登記、mail-settings.html、主旨與內文正式化、禁用詞守門，突變 11 全紅），要等 a-bonus 合回後 rebase，再跑全量。順帶發現 V9 的地圖額度警戒信從來沒寄出去 ⇒ U12。B 的 rebase-check 簿記檔規則完成（ccc474f7），排在 C1 之後跑全量。
- 2026-09-26 02:13 巡視：4 個視窗與 4 個子代理都在工作（A 的 a-bonus 跑差異題後合回；B 的 C1 全量＋b-audit-d；C 的 gaps2＋p2-legal 全量，含 when 條件改成 fail-safe；D 審 C 的後端；子代理：P8 前端、P1＋P3 修正、R 修正、個資告知合回）。**D1 階段 B（10 個模組搬遷）目前沒有人做，是最長的一段**：A 做完 a-bonus 與信件收件設定之後接 M12、M10…；C 做完 gaps2 之後分擔一半。不派工。
- 2026-09-26 02:10 D：合回前稽核 ⑤-a P1＋P3（`AUDIT-D-P1P3-catalog.md`：必修 P-M1、P-M2，**關閉前不可合回**；突變 16 全紅；試 rebase 只在 §C-7 三檔衝突）、⑤-b P8 前端 ece37cf1（`AUDIT-D-P8-frontend.md`：必修 0，可合回；建議 checkbox 補題）。接著做 ④ C 的 P4／P5／P8 後端（23b04b74）。
- 2026-09-26 02:09：個資告知擴大完成（wip/cloud-pii-notice，受影響題 1504 綠，突變 14／15 紅，第 15 項是突變本身太弱，改用更強的版本後轉紅）。12 張頁面都有決定並加守門；告知文字依用途分成承攬、聯絡人、使用者三份。主持裁示：network-plan 兩頁的聯絡人是手動輸入，要補告知；其餘 covered_by 確認。由同一個代理接手合回（要跑全量）。（這項同樣不是在雲端跑的。）
- 2026-09-26 02:06：C 的 P4／P5＋P8 後端＋A8d＋缺口 #1、#2＋N-1 已合回（23b04b74，CORE 1.11）⇒ D3 的 P4／P5 完成，D4 的 P8 後端完成。已派子代理 rebase 前端並接上 #1、#2（e2e 改由網頁授權，拿掉寫 DB 的繞道）。D 的佇列 ④ 開始審 C 的後端。主持的 D 稽核修正與 N-1／N-2／N-4 已合回（add39465，CORE 1.10）。
- 2026-09-26 02:06 X-R：R1～R3 稽核（AUDIT-D-R1-R3）修正完成 `2c8ff4d3`（CORE 1.12；version 2026-09-26c）。D-1 補充保費改四捨五入，共用函式 `legal_params.round_half_up`／`floor_amount` 已寫進 IP-7（**A 的 U4 獎金補充保費請改用它，守門會擋直接 round()**）；D-2 勞報單修改改在 write_txn 內；S-1～S-6 修正；O-2（開單日期＝給付日？）、O-5（扣繳捨去）待裁示。突變 14 項全紅。另發現 invoice_vouchers 營業稅用內建 round()（未改，待派）
- 2026-09-26 01:43 C：推上 origin——P4／P5 定義文件庫＋自訂欄位、P8 自訂模組引擎後端、A8d 前端公司名（`/api/system/branding`）、P8 前端缺口 #1（custom.<key> 權限可在網站授權）／#2（舊單帶回該版定義）、S-CC07 N-1（最新一份距今 >2 天 ⇒ 暫停清理＋告警；週／月層 2 個週期）；CORE 1.11。經過：原本只合進共用樹的本機 platform、沒有推上 origin（本機從 609cd5b8 分岔），rebase 到 origin 時 1.8～1.10 已被 O-9、A2、D 使用，以 core_bump 取 1.11。抓到的產品問題：通知在寫入交易內另開連線（database is locked 且靜默消失）、核准後簽核紀錄被清空。突變共 41 項皆紅。全量（8db7312f，-n 4、低優先權）：主段 4062 過、1 紅（VR1 跨日，主持已在 origin 補 09-26a），e2e 385 過；rebase 到 origin 後 `--rebase-check` 判定只跑 tests/platform。版本紀錄併入「系統」未發版的 09-26a（VR3）。待推：wip/c-p8-gaps2（缺口 #3～#7）、wip/c-p2-legal（P2 開票憑據稅別依據＋勞報單版型化與個資告知）。
- 2026-09-26 01:57 D：確認主持對 AUDIT-D-host 的回覆 ⇒ **結案**（突變 7 項 6 紅）。新發現：N-1 L1 行為改變（events／txn）沒有寫 core/CHANGELOG；N-4「換成案件時手改保留」沒有題目；N-2 JSON 來回改寫鍵型別、N-3 交易內檢查只認 begin_write。R 與 B 兩份等回覆。
- 2026-09-26 01:54 D：AUDIT-X-9c 的 A-1、C-1、C-2 代為確認 ⇒ 關閉，**9c 結案**（基準 41865c87，82 passed；突變 6 項 5 紅，WAL 與檔頭損毀兩種觸發方式都轉紅）。新觀察 X06：損毀的快取檔沒有題目（交 A）。接著確認主持的回覆（03331c69）。
- 2026-09-26 01:53 巡視：
  - 合回：B 的 core_bump（8ccde02a，合回時依 origin 自動取 CORE 版號，改善報告的建議落地）；主持的 D 稽核修正（03331c69）。
  - 查到並修好：共用 repo 的 .git/config 在 09-25 23:00～23:09 被加了 user.email=t@t，那段期間所有 commit 的作者都受影響；已移除，推上去的歷史不改寫。
  - 進行中：B 的 C1 全量（預估 02:35）、C 的 gaps 包、A 的 a-bonus 全量、D 的 9c 代為確認、R 修正子代理；已詢問個資告知代理的進度。
- 2026-09-26 01:38 D：稽核佇列 ①～③ 完成。R1～R3 `AUDIT-D-R1-R3-legal.md`（必修 D-1 補充保費捨入、D-2 並行清掉已告知；兼職薪資＋職業工會免扣經查證為正確）；B `AUDIT-D-B-env-guards.md`（必修 B-M1～M3）；主持 `AUDIT-D-host-P6-voucher-rollback.md`（必修 H-M1）。突變合計 32 項：25 紅、7 存活（都列成發現）。接著做 9c A-1／C-1／C-2 代為確認。
- 2026-09-26 01:26：C4（前端切換到登錄表選單）裁示：改由伺服器在 sidebar.js 前面接上 window.MOTRIX_MENU，同步過濾（避免先渲染後非同步載入的競態）。時機排在 C1、C3、P8 前端都合回之後；自訂模組也併進 MOTRIX_MENU，custom-modules-nav.js 退場。開工時通知全部視窗凍結 sidebar.js 相關的 15 個測試檔，凍結到 C4 合回為止。
- 2026-09-26 01:25：C 補齊前端缺口 #3～#7 的後端（wip/c-p8-gaps2 6197693b，突變 11 項紅），排在 8db7312f 之後推。8db7312f 推上去後，主持另派前端接手：rebase wip/h-p8-frontend，接上 #1～#7，並把 e2e 裡「寫 DB 繞過授權」的那一步改成走網頁操作。IP-8 編號 C 與 A 撞號，照 §C-7 合回時才定。
- 2026-09-26 01:23：合回順序（這幾條會互相衝突）：C 的 c-p8-gaps（約 02:00）→ B 的 C1（約 02:15）→ B 的 C3（選單由登錄表產生，要自己再跑一輪全量）→ 主持把 P1＋P3（wip/cloud-p1p3）rebase 合回，tender_radar 改用 1.2.0 → 主持的 P8 前端（rebase 到 C 之後）→ A 的 a-bonus（時序依它的全量結果而定）。P9 在 P3 與 P5 都合回之後開工。
- 2026-09-26 01:13 巡視：各視窗都在工作。C 的 wip/c-p8-gaps 全量預估 02:00；A 的 wip/a-bonus 全量進行中；B 做 C1 第二步與 404 提示頁；D 做 R1～R3 稽核；個資告知子代理仍在跑。P9 要等 P3（wip/cloud-p1p3）與 P5（C 的 gaps 包）合回才開工。不派工。
- 2026-09-26 01:05：V9 的 N-1 補強完成，在 V9 本機分支 fix/v9-clock-gap 的 17c65780（新題 13 題，突變 8／6 紅，備份相關 354 綠）。**push 到 V9 origin/master 被權限分類器擋下，等使用者決定**（指令已提供給使用者）。只改碼，不打包、不部署。
- 2026-09-26 01:04：A2（STATES-PLATFORM ②）合回 98d43855（CORE 1.9）：路由衝突、讀不到停用清單時沿用快取或全部停用、側欄 availability、直接打網址的提示頁、地圖／連結、授權在執行中變更，6 項，突變全紅。9c 的 A-1／C-1／C-2 改交給 D 代為確認。已通知 C（改用 1.10）、A（取下一號）、B（C1 第二步可以接上）。
- 2026-09-26 01:02：P1＋P3 完成，推在 origin/wip/cloud-p1p3（6ac64b45；突變 15 項全紅；暫用 CORE 1.8，合回時依 origin 重定）。
  - 合回排在 A2、C、A 之後；要跑全量（動到 loader 與 main），之後交給 D 稽核。
  - ⚠ **更正**：「雲端試跑」實際沒有在雲端跑。Agent 的 remote 隔離在這個帳號不可用，系統默默改成在本機 worktree（使用者家目錄的 .claude/worktrees/）執行。先前說的「雲端不佔本機 CPU」不成立。已告知使用者。
  - 真的要試雲端，要由使用者在 claude.ai/code 對 GitHub repo 開工作階段。前提是規格與程式碼都已推上 GitHub（C 的 P8 就曾經只存在本機）。
- 2026-09-26 00:59：使用者新增視窗 D（hichan-08），派做交叉稽核線，佇列見 §5。C 發現自己 13 筆只合進了本機 platform、從沒推上 origin，已 rebase 到 bd197ad7，改用 CORE 1.9，全量 00:58 開跑，預估 01:40。
- 2026-09-26 00:55：使用者要求信件用語正式化，並新增獨立的「信件與通知收件設定」，一般管理員不收系統技術類信件。已寫進 CORE-SPEC 裁示表，排給 A。
- 2026-09-26 00:46：關閉確認完成（9a2ae823，突變 15 項全紅）：X-9b 結案；X-batch1 必修全部關閉，B-1 補進 ROADMAP（M12 搬遷前必修）後可以關閉；X-9c 還有 A-1、C-1、C-2 等 A2 合回。新發現 N-1：時鐘往前跳，但小於保留天數時，會靜默刪掉真實快照。已裁示並寫進 CORE-SPEC：新版由 C 修，V9 master 由子代理修。
- 2026-09-26 00:43 巡視：A 合回 Z-5 範圍守門（af3d5ef7）。其餘都在工作中：A2 死線 01:20、B 的 e2e 死線 01:30、C 合回 P8；關閉確認與兩項雲端試跑還在進行，雲端分支還沒出現。不派工。
- 2026-09-26 00:42：P8 前端完成（wip/h-p8-frontend，5 個 commit）：建構器 6 步＋執行頁＋選單疊加；e2e 從零建立設備借用單、兩層簽核、PDF、舊單凍結都綠，突變 4 項全紅。等 C 的 wip/c-p8 合回後再 rebase 合入。後端缺口 7 項交給 C，🔴 第 1 項（網站上給不了自訂模組權限；e2e 目前寫 DB 繞過）擋 D4。O-9 與 .build_commit 已合回（b32956fd，CORE 1.8）。
- 2026-09-26 00:39 X-O9 子代理：合回稽核 X-9b O-9（協力廠商帳戶列為 F2，一般每日／週／月備份不帶出，只進個資資料夾；守門哨兵走真實 API＋突變 4 個皆紅）與 S-CU12（`.build_commit` 歸類成程式，轉換後版本端點回新版、回滾回 V9；突變 3 紅）（b32956fd，CORE 1.8：1.7 已被 R 使用）。差異題＋tests/platform＋備份／升級相關題在 rebase 後 592 passed（含演練 2 題）；未跑全量。
- 2026-09-26 00:37：A 已合回 IP-1～4 稽核修正（66982bbf；突變 22 種全紅；Y-5 修出一個實際缺陷：不是案件成員的簽核人會被 403）。Z-5 經使用者表單裁示為「維持現狀並寫進規格」，範圍寫進 MODULE-GUIDE 的工作交給 A。A 的 wip/a-bonus 已接上 legal_params，正在跑差異題。
- 2026-09-26 00:40 A：AUDIT-X-IP1-4-row-access 修正合回（wip/a-ip-fix，10 commits）。必修 X-1（IP-1 缺席明說：報表／待補登／傳票來源回 `unavailable` 並顯示）、X-2（登記表與程式碼一致守門，CORE-SPEC §5）、X-3（dev_crm 四條讀取路徑的 row_access 行為題）；建議 Y-1（收款帳戶端點限出納／管理員）、Y-2（M06 不在時 M07 照常載入，PDF 端點 503）、Y-3（core.source_tree 涵蓋 api/、service/）、Y-4（mp1／mp6 importorskip 移入 e2e 題）、Y-5（簽核人與案件守門規則合為一份；修出實際缺陷：額外支出簽核人在簽核佇列被 403）。每項突變皆紅（合計 22 種）。差異題：tests/platform＋變動檔 541 passed；1 紅為本機 venv 缺 cv2／numpy（同步 requirements 後 6/6 綠）。另：licensing test_08a 在稽核基準 6c3bfd8b 也紅（本機環境），非本次造成。延後：Y-3 的 test_no_credentials_in_query 掃描來源改寫、Z 項排入各模組搬遷。回覆欄已填，待 X 確認。
- 2026-09-26 00:35：雲端試跑第二項：P1 能力目錄＋P3 模組描述（分支 wip/cloud-p1p3，只 push 分支）。雲端不佔本機 CPU，所以不受「等負載降下來」的限制。要求與 STAGE-C 的 module.json 欄位一起設計。
- 2026-09-26 00:15：使用者裁示「雲端先試一項小工作」：把「個資告知擴大範圍」派到雲端（分支 wip/cloud-pii-notice，只 push 分支，不合回）。回報要附雲端環境的障礙清單；主持在 Windows 開發機驗證後才合回，再決定要不要全面搬。
- 2026-09-26 00:14 巡視：沒有新的合回，每個視窗都有工作，沒有人超過死線（A2 00:40／01:00、B 01:30）。不派工。
- 2026-09-26 00:08：用量恢復（使用者告知），照恢復清單處理：P8 前端代理中止時沒有產出，已重新派工，並要求每完成一步就 commit；O-9 與關閉確認兩個代理仍在跑；各 worktree 沒有遺失的半成品。
- 2026-09-26 00:07：⚠ **每週用量上限已到，要到 2026-09-30 03:00（台北）才重置**。子代理會陸續以 429 中止，第一個是 P8 前端代理。恢復時照下面的清單做，不要靠記憶：
  1. `git worktree list`，並檢查以下 worktree 裡有沒有沒 commit 的半成品，有的話先 commit 到它自己的 wip 分支，不要丟掉：
     - D:\MOTRIX-PLATFORM-P8F（P8 前端）
     - D:\MOTRIX-PLATFORM-XO9（O-9、.build_commit）
     - D:\MOTRIX-PLATFORM-CONF（關閉確認）
     - A2（wip/a-platform-states）
  2. 查有沒有孤兒 pytest 行程與鎖檔（PLAYBOOK §C-12、§C-13；記憶〈TaskStop 不會殺掉 pytest 子行程〉）。
  3. 依 §5 的佇列重新派工：中止的子代理改派新的代理，派工說明引用本檔。
  4. 巡視排程（cron）是 session 內的，7 天後失效；恢復時先用 CronList 確認還在。
- 2026-09-26 00:05：使用者表單裁示：V9 收款帳戶端點不修、V9 備份修補包先不出、個資告知擴大範圍這一輪做、P1＋P3 等負載降下來再派。主持裁示階段 C 設計 D1～D4（照 B 的推薦）。
- 2026-09-25 23:59：派出 P8 建構器前端＋自訂單據執行頁的子代理（基於 wip/c-p8；C 合回前不合回）。P9 排版器的前置條件是 P3「模組登記可自訂點」（A 線佇列 ⑤），目前沒有人做。等負載降下來（目前 3 個視窗＋3 個子代理），再派子代理做 P1＋P3。
- 2026-09-25 23:58：R1～R3 合回（609cd5b8，CORE 1.7；差異題 817 綠，突變全紅，抓到並修正 1 個假綠燈）。兩項 PDF 輸出交給 C，併進 P2 輸出引擎；A 可以接上真正的參數表。
- 2026-09-25 23:55 R（法規代理，時間由 date 產生）：合回 R1～R3（wip/r-legal）。R1 法規參數依生效日版本化（L1 `helpers.legal_params`、設定頁「法規參數設定」、勞報單凍結版本＋快照、12 月提示、門檻＝最低工資守門、`nhi.bonus_insured_multiple`；U4 介面見 INTEGRATION-POINTS IP-7）；R2 零稅率／免稅必填依據（報價、開票申請）；R3 個資蒐集告知（公司設定頁範本、列印告知書、「已告知」紀錄）。規格 CUSTOMIZATION-SPEC §9、MODULE-GUIDE §11；CORE_VERSION 1.7。驗證：全量（3.11）在 d435987f——非 e2e 3777 過／2 紅（test_e2e_hard_cap，單獨重跑綠）、e2e 375 全綠；差異題在 4fb1c7be 之後（.venv312，-n 2）817 題全綠。
- 2026-09-25 23:50 巡視（時間由 datetime 產生）：
  - 已合回：B 的 .venv312、§C-13、Python 不綁定（ba14bf36 等）；C 的 batch1 修正（972fbb5b）；9b 修正（a11de47e，CORE 1.6）；9c 修正（13f37f0a，1.5）；主持的完整回滾預覽（4fb1c7be）。
  - 派出關閉確認代理（X-9c／X-batch1／X-9b）；O-9（承攬商帳戶列為個資，使用者裁示）與 .build_commit 由子代理處理中。
  - 等候中：R（縮小驗證後合回）、A2（死線 01:00）、A（IP 稽核修正）、C（P4／P5／P8 合回）、B（修 K5／K6）。
- 2026-09-25 23:42 C：合回 AUDIT-X-C-batch1 修正（wip/c-fix-x1）。必修 A-1 時鐘異常 ⇒ `.prune_hold` 暫停清理、每輪告警，與 V9 a1cc2871 同一作法，六層都套用；A-2 啟動 quick_check 守門改用 AST；A-3 IP-6 五種回寫都實際執行（不同 id、lost-update）。建議 B-3、B-4 已修，B-2 移交 X9B。C-4 使用者頁不再顯示舊解鎖密碼；C-5；RUNBOOK §1b 控制字元。更正：ROADMAP A8d 第一項原寫「預設解鎖密碼含統編」是錯的，那是弱密碼黑名單；原文保留。每項修正都做突變驗證（14 項，全部由斷言轉紅）。全量（3.12，舊基底 eac0323d）：主段 3760 過、3 紅，是 FastAPI 0.141 環境問題，77b0e460 已修；e2e 365 過。rebase 到 92bd85ad（含 X9B 的 upgrade／archive 修正）後，帶進的 conftest 改動（BK19 放行 __pycache__、tender_radar 夾具移位）不碰本批用到的夾具 ⇒ 依 §C-11 的判斷只跑受影響題＋tests/platform＋那 3 題＋X9B 的升級／個資題：682 過（未照字面重跑全量，已報主持）。另：V9 唯讀掃描「DML 之後、commit 之前呼叫會另開連線寫入的函式」（P8 抓到的那一類）⇒ 嚴格與寬鬆兩種模式皆 0 筆（正對照成立）；掃不到的情況：呼叫端把尚未 commit 的連線傳給一個本身不做 DML、只呼叫 `_notify`／`_audit` 的函式。注意 V9 的 `_audit` 以 `except: pass` 吞掉所有錯誤，連線 timeout 30 秒。
- 2026-09-25 23:27 X-9b 修正代理：AUDIT-X-9b 必修 M-1～M-4、建議 S-1～S-7、B-2（X-C-batch1）、觀察 O-1／O-2／O-3／O-5／O-6／O-7 修正合回（eda4d3cb、837c0be8、ffd0be0c），CORE 1.6（rebase 時 1.5 已被 X9 使用）。主持裁示寫進 CORE-SPEC §9b（保留原句並註明更正）：不自動回滾、驗證不過提示回滾＋指令、回滾後自動 ping V9 只印結果。突變 24 個全紅；演練修正前紅（M-1 verify、M-2 code／full）、修正後 2 passed。驗證：受影響題 -n 2 低優先權 764 題：762 綠、2 紅＝BK5 兩題的失敗注入點（月整庫改走 `_pii_copy_file`），改注入點後 19／19 綠；rebase 後重跑受影響題（§C-13，未跑全量）。不修：O-8（理由見回覆欄）；需裁示：O-9（協力廠商帳戶是否屬個資，M-3 守門允許清單連動）。⚠ 未守門：新增的個資寫入路徑是否走 helper（ROADMAP G6b）。
- 2026-09-25 23:25 X9（9c 修正代理）合回 AUDIT-X-9c 的修正（5f372370、35189b82，CORE 1.5）。A-2：§9c 的守門、子行程與 e2e 改用合成模組；拿掉 tender_radar 後 37 passed、2 skipped（修正前 7 紅）。A-3：狀態加 `note`，管理頁會標「授權檢查未啟用」。另修 B-1～B-4、C-4。A-1、C-1、C-2、C-3 留給 `wip/a-platform-states`。全量在 8ac0b042：除了 1 題已修，其餘 6 紅是既有問題（fn4 兩題、licensing 08a、缺 cv2／numpy 三題）。⚠ `wip/a-platform-states` 合回時會跟這次的修正衝突，也要改用合成模組；說明見稽核檔的「合併注意」。
- 2026-09-25 23:25：B 的 3.12 全量完成：非 e2e 3,746 過 1 紅、e2e 364 過 1 紅，兩題都是負載造成的測試時序問題，已裁示合回 wip/b-venv（寫進已知問題，.last_full 維持 ok=false），之後由 B 修這兩題。B 已自行處理共用樹分岔（a33ef2b5）。全量名額交給 C。
- 2026-09-25 23:13 巡視：沒有新的合回。CPU 滿載已處置（PLAYBOOK §C-13）：headless 瀏覽器從 70 降到 15，pytest 相關行程剩 10。死線：A2 23:50、IP-1～4 稽核 23:50、R 23:45。其餘都在工作中，不派工。
- 2026-09-25 23:12：健康檢查通過，U10 已取得（正式機 3.12.10、fastapi 0.141.1）。第一次失敗的原因是遠端沒有主控台，[Console]::OutputEncoding 丟例外（9c8895ff 修正）。使用者裁示 Python 不綁版本（4e96fc09）。A2 在 0.141 上抓到路由衝突漏擋，修正中（死線 23:50）。R 合回前會補 nhi.bonus_insured_multiple。
- 2026-09-25 22:43 巡視：沒有新的合回。B 在 .venv312 上跑全量（死線 22:55）；A2 只跑差異題後合回（死線 23:05，不跑全量）；已詢問法規代理的進度；prod_env.json 仍未取得。
- 2026-09-25 22:25 巡視：A、B、C 與 5 個子代理都在工作中，沒有新的合回，也沒有逾時；不派工。U10 等使用者再按一次健康檢查。
- 2026-09-25 22:40（更正：實際約 22:20，時間寫早了；同類錯誤第二次 ⇒ 之後進度時間一律先跑 `date` 取得）巡視：
  - V9 修補（U2）：S-CC07、S-CD02 已合回 V9 master（a1cc2871）。清理暫停改用 `.prune_hold`，每輪都告警；建議出修補包，由使用者決定。啟動時的 quick_check 沒有做，因為 main.py 是 V9 鎖定檔。
  - 稽核：9b 升級（b2469f61）有必修 4 項，已派子代理修（擋 D7）；9c 修正派子代理；C 修 batch1 必修，時鐘跳動的作法對齊 V9。
  - 主持：D3／D5 必修已合回（549f56dd）。U10 首跑時版本讀不到而且沒有任何提示，原因是 WinRM 工作階段的 PATH 沒有 python；已改由 autostart.bat 推得（正式機是 Python312）。
  - A 視窗：使用者 /clear 之後重新派工 ③ 獎金三項＋U4。
  - B：誤刪了一半的 .venv（已報，並寫進 PLAYBOOK §C-12）；.venv312 建置中。
  - **待處理**：舊的 .venv（3.13，已損壞）等子代理全部結束後，通知 B 刪除。
- 2026-09-25 21:58 C：D6 稽核完成（反向控制實跑 14 項＋正對照 4 項）。`audit/AUDIT-C-host-D3D5.md`：必修 D-1（D3 列表讀根目錄的 lock，打包寫在 backend/ ⇒ 新包全顯示「沒有清單」，測試自擺同一錯位置）、D-2（D5 非預期型別 ⇒ prod-health 500、前次通過仍有效）；建議 4、觀察 3。`audit/AUDIT-C-B-guards.md`：必修 G-1（G1 不看底線開頭的跨模組 API，刪 `_require_user` 的 module 參數仍綠）、P-1（9c① 驗包放過無 module.json 的模組資料夾與 helpers/__init__.py）；建議 5、觀察 4。C 回 P4／P5。
- 2026-09-25 21:51 使用者表單裁示 U1～U9（見 §4 裁示結果）；U10 待回來。
- 2026-09-25 21:50 巡視：沒有新的合回。B 在 .venv 上跑全量（死線 22:01），C 做 P2。D6 覆蓋缺口：§9d 原本分給 A 的（9b／paths／個資）與分給 B 的（IP-1～4／row_access）還沒有稽核 ⇒ 各派一個獨立代理。IMPROVEMENT-REPORT 骨架已建（覆蓋表）。
- 2026-09-25 21:40 B：專案 .venv 做好（Python 3.13.3，wip/b-venv 210ef6b3）。乾淨環境抓到三個缺口：httpx2、cv2／numpy 沒列在 requirements，以及 BK19 誤擋 .venv 的 __pycache__；都已補齊。新守門 test_requirements_cover_imports；project_env check 會比對 prod_env.json（正式機環境還沒取得，見 U10）。發現：hermes 是 starlette 1.0.1，.venv 是 1.7 ⇒ 過去一直在舊版上測。全量 21:35 開跑，死線 22:01，全綠就合回，接著做 ④ P7。
- 2026-09-25 21:28 合回：C 批次（fceaadde，CORE_VERSION 1.3）、主持 D3 選配打包（0d55250f）、U10 正式機 Python 版本（507a76ea）。D6 稽核：A 已退役 ⇒ 新代理（獨立 worktree）審 A 的 9c 與 C 批次 1；C 在 P2 之後審 B 的 G1～G4／9c①與主持 D3／D5。
- 2026-09-25 21:19 合回：A 的 9c 模組啟停與授權（c45d6227）、B 的 G1～G4 準則守門（66f7dd60）、主持的 D5 正式機模組狀態（a64cdcd3）、BENCHMARK（50af9d35）⇒ 階段 R＋U4～U9。A 視窗交接（上下文長），② 改派新代理；法規 R1～R3 由另一個代理進行。C 整串全量進行中（死線 21:45）；B 9c① 演練完成、待合回。
- 2026-09-25 20:40（更正：原寫 21:40，實際時間 20:40）主持：P6 事件匯流排合回（8d19378c）；傳票支出第二筆金額連動修正（c2913a80，只修新版）；儀表板稽核全部結案。B：G3／G4 完成（待 A 合回後一併合回），9c① 演練進行中。A：9c 全量重跑中（死線 21:53）。C：A11＋states-fix 等 A 合回後全量。研究代理：BENCHMARK 進行中。
- 2026-09-25 20:30（更正：原寫 21:10）建立本計畫。
- 2026-09-25 20:43 巡視：A 9c 全量中、B 9c① 打包演練中、C 待 A 合回、研究代理進行中；無逾時、無新派工。
