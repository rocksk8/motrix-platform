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
| U18 | **視窗 hichan-f9 一直顯示 waiting、兩次詢問都沒有回應**（2026-09-26 08:14） | 很可能停在權限確認畫面，要有人按。A 的 `wip/a-m03`（M03 出貨模組搬遷）從 07:07 起就沒有新 commit，而且還只在本機、沒推上去。依規則，主持不代替它做被拒絕的動作 | 請你看一下那個視窗：是權限確認就按（或拒絕），是其他狀況就告訴我。若它回不來，主持會改派子代理，從 A11 worktree 的 wip/a-m03（b9ac9ce9）接手 |
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
- **ROADMAP 待辦**（R 帶出）：R2 附件形式的依據；客戶聯絡人等其他個資表單的告知機制（MODULE-GUIDE §11 標「未守門」）；~~privacy_notice_acks 在 M04 搬遷時改用模組自己的表~~〔主持裁示 2026-09-26 07:53（D ⑮ O-1）：維持 L1 共用表——個資告知橫跨報價、網規、外包等多個模組，是共用能力，下沉資料層；不改模組表〕。
- **D1 階段 B 模組搬遷分工**（2026-09-26 03:30，使用者裁示「轉移優先」；每個模組都照 PLAYBOOK §B，搬完記選題比例（D1b），上月台）：
  - A：M12 每日任務（完成，搭第三班）→ M10（進行中）→ M03 → M01
  - 〔主持裁示 2026-09-26 09:33，M01 改派〕A（hichan-f9）自 07:07 無回應（U18），M01 由 **C** 接手，照 C 的 M01-PLAN §3 順序：**T**（稅額純函式 payment_item_amounts／quote_tax_type／tax_split／invoice_amounts／LEGACY_TAX_NOTE 下沉 L1 `helpers/tax_calc.py`，舊位置留同名別名；**核准立刻開工**，以 origin/platform 為基底，第七班）→ 小型下沉 → case_access 匯入改位置 → 讀取連接器 case.summary → M05 → case.recognition（M01 提供者，配契約題）→ approval-queue 改各單據模組提供待簽項目、M01 只彙整 → M01 本體（含 CA-O3、CA-O4，及 **pdf_gen.py:442 寫 quotations 表**要改由 M01 提供）。M01 的反向控制「提到 M01 的測試檔」≈ 全量 ⇒ 改由列車的全量兼任：M01 本體上車那一班，列車長在 sparse（不取出 M01）樹上另跑一次全量，紅必須 ⊆ §B-11 允許＋已知紅清單。A 回來後：M03（A11 的 wip/a-m03 b9ac9ce9，未推）照舊歸 A；M01 不收回。
  - B：M08（2026-09-26 04:47 從 A 移過來；C4 開工時暫停）〔2026-09-26 05:39 佇列：M08 → dep_graph／test_map 一致性守門（比照 UNIT-INDEX --check，附反向控制）→ O6 → C4（開工時主持宣布凍結）。M08 要排在 c-module-files 之後上車〕
  - C：M02 crm／dev_crm（進行中，wip/c-m02）→ M04 → M05 → M06 → M07
  - 搬遷順序依 ROADMAP 階段 B 的相依；兩邊要動同一個 L1 helper 時，先在 RUN-PLAN §6 講一聲再動
- **列車月台**（PLAYBOOK §G3；各線登記：分支｜HEAD｜差異題結果｜是否動 fixture 層／main）：
  - C｜`wip/c-case-access-4`〔取代 c-case-access-3 0da9d647：rebase 到第五班 a6dc4be6；衝突只在 INTEGRATION-POINTS／ROADMAP（兩邊並存）；rebase-check 判 tests/platform：1020 過；UNIT-INDEX 重產；CORE 1.30 不變〕HEAD＝**2440fd6e**；以下為原登記：（取代 c-case-access-2：rebase 到第四班之後；**M01 在不在只留一個訊號＝A 的 `case.access`（IP-12）**，刪 `case.present`／IP-15；一致性題：拿掉 case.access ⇒ L1 guard 404、網路規劃書也 404 並說未安裝）｜0da9d647｜tests/platform＋modules＋存取類 45 檔（-n 2）：1669 過；突變（訊號改回 case.present）紅｜fixture 層／main：無；L1 新增（CORE 暫取 1.30）；A 的 M01／M03／M05／M10 與 C 的 M04 依賴它
  - C｜`wip/c-m02-s2b-2`〔取代 c-m02-s2b 6e2e15a7：rebase 到第五班 a6dc4be6；crm 版號改 1.0.5（接第五班的 1.0.4）；crm tests＋package／CHANGELOG 守門 88 過；D 已複核通過〕HEAD＝**205198e8**；以下為原登記：（主持轉 D 的 M02-S2 觀察：核准端點（刪除／重新連結）補外人題，並分開角色與列權限——建立者（有列權限）申請 403、管理員（不在名單）申請成功；外人／建立者／管理員核准 403 且資料不變、最高管理者核准成功；舊題說明加〔更正〕；**疊在 c-m02-s2 bcd4288c 之上**）｜6e2e15a7｜modules/crm/tests＋CHANGELOG／unit_cards 守門：67 過；突變 4 項（兩個核准放寬成管理員、兩個申請不擋角色）皆紅｜只加題＋模組 1.0.3；產品碼不動〔C 登記〕
  - C｜`wip/c-m07-2`〔取代 c-m07 4a731b1f：rebase 到第五班 a6dc4be6；main.py／sidebar.js 衝突同上處理；全量（eaa8e274，-n 4）4662 過 0 紅＋e2e 436 過；D 稽核必修 0（M07-S1／S2 第六班合回後另包修）〕HEAD＝**eaa8e274**；以下為原登記：（D1 階段 B：M07 薪資獎金搬進 `modules/payroll`：`api/bonus.py`、`api/payslips.py`＋6 支 helper；提供者 IP-8／IP-9／IP-16；獎金 PDF 改用 L1 版面元件（不再依賴 M06）；需要本模組的題 41 檔整檔＋10 個混合檔拆進模組 tests；規格 BN1～BN19、QS1a 的條件與範圍隨模組走（STATE／SCOPE → payroll SPEC.md）；`pii_forms.json` 新增 `notice.api_module`（模組不在時不比對端點、在時照驗，含題）＋勞報單 payroll、網路規劃書兩頁 netplan（D 在 b-g1 core-only 抓到的那題））｜4a731b1f｜M07 在：tests/platform＋modules＋提到 M07 的 31 檔＋8 道共用守門（-n 2）1956 過 0 紅；**反向控制**（sparse 工作樹不取出 modules/payroll）：有旗標與無旗標兩輪都是 1583 過、2 紅＝§B-11 允許（modules_json、UNIT-INDEX），加 1 收集錯誤 test_core.py（模組層 import，已拆，拆後 54 過）；拿掉 payroll＋netplan：test_pii_forms_notice 28 過 3 skip｜🔴 動 main.py（拿掉兩支 router）；system `/api/system/bonus-module-status` 改走提供者；共用守門改 module_installed（begin_write、page_paths、no_file_relative、final_drill 冒煙）；L1：resolve_display_names 移到 tiered_approval；CORE 暫取 1.30（core_bump，與 c-case-access-3 同號待列車配號）〔C 登記〕
  - C｜`wip/c-coreonly-depscan`（主持轉 D 的 AUDIT-D-B-G1 G-M1 交會紅：`test_dep_scan_and_source_tree_agree_on_module_files` 原本 `assert dirs`（要真實 repo 至少一個模組）⇒ core-only 必紅；改成真實 repo 有幾個比幾個，正對照移到 dep_scan 合成樹（新題 `…_on_the_synthetic_tree`，含 service/ 子目錄與 tests/ 反向控制）；基底 origin/platform 45fb1491）｜2784140e｜test_dep_scan_module_files 4 過；突變 2 項（只掃第一層、tests 也算）皆紅；core-only（sparse 不取出 daily_tasks／netplan／tender_radar）：dep_scan 題綠（同檔另跑的 pii_forms netplan 紅＝c-m07 4a731b1f 修，兩包合回後歸零）｜只改一個題檔；產品碼、fixture 層、main 都不動〔C 登記〕
  - C｜`wip/c-tax-calc`（主持核准「T」，排第七班：稅額純函式 TAX_TYPES／TAX_TYPE_LABELS／LEGAL_TAX_RATE／LEGACY_TAX_NOTE／quote_tax_type／tax_split／invoice_amounts／payment_item_amounts 自 M01 helpers/quotations 逐字下沉 L1 `helpers/tax_calc.py`；舊位置同名別名（同一物件）；pdf_gen、invoice_vouchers、reports、tools 改自 L1 import；修正 tax_split 錯誤訊息 % 未跳脫（TypeError→ValueError，呼叫端都先排除 legacy）；`__l1_public__=("_invoice_amount",)`；基底 origin/platform cc348186）｜a1d7ba4a｜全量（c60cd3fa，-n 4）：4659 過 1 紅（l2_import_baseline：M05 cashier → M01 邊已不存在 ⇒ 已 --prune）＋e2e 434 過；契約題 test_tax_calc_contract 14 題（不讀表、不 import M01、別名同一物件、掃描器正對照）；突變 4 項皆紅（別名指錯、換成複本、函式讀表、延遲 import M01）｜🔴 L1 新增（CORE 暫 1.30，待列車配號）；fixture 層／main：無〔C 登記〕〔⚠ rebase 到第六班之後必做（D 稽核 AUDIT-D-C-tax-sink2 觀察）：b-m08-2 把 routers/reports.py 搬到 modules/analytics/api/reports.py ⇒ 新位置的 `from helpers.quotations import quote_tax_type, tax_split, LEGACY_TAX_NOTE, invoice_amounts` 改成 helpers.tax_calc；另查 analytics/api/dashboard 與 l2_import_baseline 的對應邊〕
  - C｜`wip/c-m01-sink2`（M01-PLAN §3-2：`norm_at` → L1 helpers/dates、`_steps_to_tiers` → L1 helpers/tiered_approval.steps_to_tiers，舊位置同名別名；routers/system 不再為此 import helpers.quotations（CA-O4）；**疊在 c-tax-calc 之上**）｜**77b9a672**（`wip/c-m01-sink2-2`：c88aebc4 疊到 T 的 a1d7ba4a 之上）；tests/platform＋17 個相關檔 1198 過｜契約題 test_m01_sink2_contract；突變 2 項皆紅（別名換複本、system 改回）；l2_import_baseline 刪 M08 dashboard → M01｜L1 新增（CORE 暫 1.31）〔C 登記〕
  - C｜`wip/c-m04-3`〔取代 c-m04-2 dd7aecf0：rebase 到第五班 a6dc4be6，疊在 c-case-access-4 之上；main.py／sidebar.js 衝突＝兩邊各拿掉自己搬走的 router、MODULE_PAGES 聯集；ROADMAP M02 取第五班、M04 取本分支；驗證（主持裁示不自跑全量）：tests/platform＋subcontract／crm 模組題＋test_api_integration＋test_em1＋14 支開側欄的 e2e＝1252 過；⚠ 暫取 IP-12 dispatch.list_for_case／IP-13 quotation.append_items 與 origin 同號，列車定號；D 已關閉 M04-M1、S1～S3（條件：與 b-g1 同班）〕HEAD＝**740417a4**；以下為 c-m04-2 登記：〔取代 wip/c-m04（dd6f1550）：疊到 c-case-access-3 之後；稽核 D M04-M1＋S1～S3 修正；反向控制（sparse、新範圍 84 檔，有旗標／無旗標）2195 過 6 紅 → dd7aecf0 修掉自己的 3 題，剩 §B-11 允許 2＋B 的 G1 快照 1；M04 在：46 檔＋模組 tests 404 過；subcontract 1.0.3；**依賴 c-case-access-3**；pii_forms 的 api_module 機制與 c-m07 是同一份改動（文字相同）〕HEAD＝**dd7aecf0**；以下為 c-m04 原登記：（D1 階段 B：M04 外包工班搬進 `modules/subcontract`，router 放 `api/`；**疊在 c-case-access-2 之上**，含 dep_scan／module_files 同一改動（與 c-module-files 重複，列車上以先合回者為準））｜dd6f1550｜合回閘門（tests/platform＋modules＋45 檔含 e2e，-n 2）：1578 過 3 紅（origin 新守門：module.json customization、X-VAT 捨入清單路徑，已修）；修後 tests/platform＋modules 1099 過；**反向控制**（刪掉 modules/subcontract）：啟動 ping 200、四個前綴 404、出納／T100／整包明說；tests/platform＋modules 1082 過 6 紅＝§B-11 允許 2（modules_json、UNIT-INDEX）＋已分派 A 的 3（IP 登記 2、case_read_scope）＋B 的 1（G1 快照）；突變 8＋e2e 1 項皆紅｜🔴 動 main.py（拿掉三支 router）；M01 `routers/quotations.py`（IP-12 取用、IP-13 提供）、M05 `cashier.py`／M06 `accounting_export.py`（IP-14）；L1 `helpers/dates.normalize_date`；出納頁顯示 notice；CORE 暫取 1.22
  - H｜`wip/h-u14-2`（U14 前端：自訂模組草稿只有建立者與超管看得到編輯／送出，依伺服器 canEdit，缺欄位不當 false；其他人看到說明）｜1fa732e6｜會開 custom-records 的 4 檔 34 題綠（-n 2）；新 e2e 3 題；突變（還原前端 ⇒ 紅）；版本紀錄 80 題綠｜fixture 層／main：無；VR3 併入系統 26a｜等 D 稽核〔2026-09-26 07:53 H〕〔2026-09-26 08:04：D 稽核必修 0（AUDIT-D-host-U14-hist）；補 U-S1 題（存檔後不重整仍可送出），突變 U1 轉紅；可上車〕〔2026-09-26 09:40 rebase 到第五班 a6dc4be6 後改名推（取代 wip/h-u14 48dab2a3），受影響題重跑綠〕
  - H｜`wip/h-hist-4`（D 稽核 H-S1：寫入端把「讀不到」當空清單覆寫——被占用重試後仍不行就另存 pending、不碰主檔並警告；讀不懂先封存壞檔再開新檔；疊在 h-hist-2 上，第五班之後上車）｜5e736075｜儀表板＋gitignore 122 題綠；兩題＋行為突變紅（第一次突變是換回舊檔、夾具 setattr 出錯＝假陽性，改只動行為重做）｜fixture 層／main：無；.gitignore 加兩行〔2026-09-26 08:04 H〕〔2026-09-26 08:10：D 關閉 H-S1；H-S2 pending 沒有落點（只寫不收，「尚未併回」警告永遠在且蓋掉 15 分鐘失敗警告）⇒ 9e55dfa1 下一次寫入併回並刪檔、讀取端看合併後紀錄；行為突變 2 項各紅；待 D 複核〕〔2026-09-26 09:40 rebase 到第五班 a6dc4be6 後改名推（取代 wip/h-hist-3 9e55dfa1），受影響題重跑綠〕
  - A｜`wip/a-m10` 追加 `68f16342`（O-4：module_installed 改看 module.json，與載入器同一個判準；只剩 __pycache__ 的資料夾算「不在」）｜68f16342｜第四班發車後才推，沒有上車；由主持代登記（它已在 origin，不涉及權限）｜待 D 稽核〔2026-09-26 08:14 H 代登記〕
  - H｜`wip/h-corered-2`（D 稽核 AUDIT-D-B-G1 G-M1 的 A 那 2 題：case_read_scope 反向控制題、IP 登記表 present_still_red 的「模組在」正對照改用合成模組，不綁真實 L2；A 無回應由主持做）｜b682b9bf｜sparse 樹（不含 backend/modules）：舊版 2 紅、新版 11 綠；一般樹 11 綠；突變 2 項（在的模組也被豁免）各紅｜只改測試；fixture 層／main：無〔2026-09-26 09:01 H〕〔2026-09-26 09:40 rebase 到第五班 a6dc4be6 後改名推（取代 wip/h-corered 3710f462），受影響題重跑綠〕
  - H｜`wip/h-o7-2`（O7：P9 排版器切換範圍的兩個競態——載入中編輯區 inert、序號丟棄舊回應；第五班全量抓到「發布第 2 版後表頭仍是第 1 版」）｜0738f4b7｜tender_radar P9 e2e＋test_p9_layout 7＋8 題綠；tests/platform 守門子集（-n 1）277 過；突變 2 項各紅｜只動 L1 前端＋模組測試；fixture 層／main：無｜待 B 稽核〔2026-09-26 10:34 H〕〔2026-09-26 10:42 B 稽核（AUDIT-B-host-O7）必修 M-1：載入與預覽共用 busy，預覽結束解鎖 ⇒ O7 重開；改 loading 旗標＋S-1 讀不到鎖住明說＋S-2 比完整 ops＋O-1；突變 4 項各紅；待 B 複核〕
  - B｜`wip/b-m08-3`（取代 wip/b-m08-2：rebase 到第五班 a6dc4be6，衝突只在 main.py import 行／月報排程與 sidebar MODULE_PAGES（crm 與 analytics 各留），內容不變；再之前取代 wip/b-m08：含稽核 ⑰ 必修 M-1～M-4；D1 階段 B：M08 營運分析搬進 `modules/analytics`，router 放 `api/`；L1 新增 `helpers/receivables.py`（A8b 中繼，M05 搬遷時收回）、`routers/company_lookup.py`（GCIS／`/api/now`）、`/api/sales-orders` 移 M01、IP-1 改走提供者；選單四項移入 module.json；tests/platform 守門改模組感知；`tests/_db_ledger.py`（sqlite3.connect 層連線帳本，M-1）；test_no_credentials 掃 source_tree（M-2）；product_drill 改讀 `provides.probes`、沒宣告列 undeclared_probes（M-3）；首頁兩格模組不在時顯示「—」＋明說（M-4））｜7f7cda39｜**b-m08-3 閘門**（同一範圍 94 檔，-n 2、低優先權、--continue-on-collection-errors）：2057 過、2 skip、0 紅；以下為 b-m08-2 的紀錄——**閘門**（模組在；M08 相關＋tests/platform＋modules/analytics/tests＋側欄／首頁／五頁 e2e，94 檔，-n 2、低優先權、--continue-on-collection-errors）：2056 過、2 skip，2 紅已修（core CHANGELOG 殘留一行 C 的 1.21 標題、SPEC.md 未寫「本模組沒有專屬編號」；修後相關 54 題過）；**§B-11 反向控制（B 自己的樹重做）**：`git worktree` B18rc detach f7463dfa 前一版 e361bfbc → `git rm -r backend/modules/analytics` → `pytest <同一範圍 93 檔> -n 2 --continue-on-collection-errors -rfE`：1862 過、5 skip、3 紅＝§B-11 允許 2（modules.json 列了但掃描不到、UNIT-INDEX）＋core CHANGELOG 同一題（已修），收集錯誤 0；另在同一棵樹 `tests/test_spec_coverage_2026_09_21.py` 15 過（SPEC.md「本模組沒有專屬編號」的依據）；突變：M-1 三個（MX-NOW-a／b／c）、M-2 MX-CRED、M-3 probe 改前綴、M-4 還原 index.html 皆紅；**D1b**：改 reports.py 66.8%→23.3%（稽核重現 23.4%）｜fixture 層：無；**main.py：有**（拿掉兩支 router 與月報排程，改 ModuleSpec；import company_lookup）；L1 新增（CORE 暫取 1.30，列車上 core_bump 重定）〔09:10 B 更新：取代 b-m08 那一列〕〔10:00 B 更新：b-m08-3〕
  - B｜`wip/b-g1-2`（取代 wip/b-g1 6e7ba250，改名推未強推；= b-g1 ＋ 稽核 AUDIT-D-B-G1 後續：G-S2 宣告不存在的名稱改紅、G-O3 pytest exit 2／3／4 判不過、G-O4 core_only_rc 即時轉印輸出＋「排隊中：等 <持鎖者>，已等 N 分」＋60 秒無輸出心跳、G-O5 PLAYBOOK §G3 列車長核對裁示行作者（⚠ 共用 git 作者，要看訊息署名，格式待主持訂）；ALLOWED 加產生檔一致性三題（BM-M2）。G1 本體見 b-g1：L1 公開介面改由 `__l1_public__` 宣告＋core-only 工具）｜cfe4e914｜tests/platform（-n 2、低優先權）1028 過（09271a8e）；ALLOWED 那一筆後 core_only_rc 題 18 過｜fixture 層：無；main.py：無；L1 檔 11 個只新增宣告；**排第六班，與 h-corered、c-coreonly-depscan、c-m07、b-m08-3 同車**（G-M1 條件）〔10:41 B 更新：取代 b-g1〕
  - B｜`wip/b-maps-2`（取代 wip/b-maps d25f7ef3；= b-maps ＋ 稽核 AUDIT-D-B-maps 必修：BM-M1 dep_graph 不寫工作樹名（另一棵樹實跑 3 題過）、BM-M2 三題列進 §B-11 允許清單＋模組全在時會紅的反向控制（直接呼叫三題本身）、BM-S1 過期偵測走讀檔比對。本體見 b-maps：產生檔一致性＋歸屬錯誤 0 守門、OWNED_KINDS 單一定義、M12 '/api/settings' 殘留）｜c8c69c79｜本包守門＋boundaries＋unit_cards 48 過；另一棵樹（B21x）dep_graph／test_map 現況題 3 過｜fixture 層：無；main.py：無；⚠ **須與 wip/b-g1-2 同一班或在其後**（core_only_rc.ALLOWED 那三題在 b-g1-2）；產生檔每包都會衝突，列車疊完照 §G3 重產〔10:41 B 更新：取代 b-maps〕
  - B｜`wip/b-o6-2`（取代 wip/b-o6：稽核 D O6-M1——探針改放 backend/tests/.hardcap_probe_<id>（backend 根會被產品碼掃描看到，D 實測 20 次 3 次 FileNotFoundError）；刪不掉記錄並重試一次、仍不行發 warning；靜態守門：core.source_tree 的產品碼清單找不到探針（實建一個驗）、突變改回 backend 根紅）｜bd78491f｜（＋O6-S1：靜態守門說明寫明自己寫 rglob 的掃描靠各自排除 tests/）hard_cap 5 題過、探針目錄用完已刪｜fixture 層：無；main.py：無〔10:59 B 更新：取代 b-o6〕〔11:04 B 更新 HEAD；排第七班〕
  - B｜`wip/b-rebasecheck-2`（取代 wip/b-rebasecheck：＋PLAYBOOK §C-11 本文與 §C-4 的「重跑全量／就跑全量」劃掉加〔更正〕（稽核 D 必修）；主持派工：modtest 不再叫各線跑全量，§G3——--rebase-check 影響大時建議差異題擴大＋tests/platform＋改到頁面的 e2e、全量交給列車、月台註明；一般模式自己動 fixture 層也照跑差異題、閘門過了 exit 3＝要註明排車頭；need_full 改名 high_impact；MODULE-GUIDE §7、PLAYBOOK §G1〔更正〕）｜0f1d8e0a｜（＋R-O1：「全量照舊」一句與表格 ③ 補「由列車跑」）rebase-check／bookkeeping 28 過（新題：輸出不出現重跑全量／--full、建議不含 fixture 層檔）；tests/platform（-n 2、低優先權）1007 過｜fixture 層：無；main.py：無（只動 tools/platform/modtest.py 與它的題）〔10:26 B 登記〕〔10:44 B 更新：b-rebasecheck-2〕
- **全量名額排隊**（更新 2026-09-26 02:43）：§G3 生效後，新的全量改由列車統一跑。仍在跑、而且依規定跑完就直接合回的有：B 的 C1（合回閘門約 02:52）、C 的第二批全量。A 的 a-bonus 走合回閘門，不經過測試鎖。⚠ A 有一支孤兒 pytest（pid 53300），停不掉，已請使用者處理。**第一班列車預計約 03:15 發車**，要等月台上至少有 3 包（目前只有 x-r-fix 1 包）。
- **未結案的偶發失敗**（依〈偶發失敗先當產品競態〉，不以「單獨跑是綠的」結案；下次出現時第一件事是抓 dump，`faulthandler_timeout`／py-spy）：
  - O1：`test_archive_isolation` 在滿載的全量中紅 1 題（A2，23:0x；題名沒有留下），單檔與循序跑 670 題都是綠的。
    - ✅ **已查明（B，856e5497）**：原先歸因於「滿載」是錯的，實際是目錄狀態造成的。os.makedirs 遞迴建上層目錄時，呼叫到的是被 BK19 換掉的記錄版 makedirs；在全新的 worktree 裡 uploads 還不存在，所以多記了一筆上層目錄。開發樹裡 uploads 早就存在，因此只有全新 worktree 的全量會紅。修法：比對改成純函式，已登記寫入的上層目錄不算新缺口，並附 3 題反向控制。**這印證了「偶發失敗先當成真問題查」：它根本不是偶發。**
  - O2：`test_bonus_case_multi_approver_tier` 之後卡住十幾分鐘（A2，約 22:50，滿載時；沒有 dump），停在 multi_approver 之後、vouchers 的第一題；連跑三檔、開 faulthandler 都無法重現。
  - O5：`test_e2e_login_enter_submits::test_enter_logs_in[after_failed_attempt-webauthn]` 在 C1 全量（f3b59691）e2e 裡紅 1 次：等待導向 /index.html，8 秒逾時。單獨重跑 3 次都綠。這一輪含 core.pages（/pages 路由改由伺服器提供），要查它和登入導向是否有時序關係；下次出現時先抓頁面的網路紀錄與 dump。〔D 排除法（f6b25468）：與 /pages 無關。等待點 /index.html 由 StaticFiles 提供；這個情境要算兩次密碼雜湊。下次出現時抓兩次 login 請求的耗時〕
  - O3／O4：`test_e2e_hard_cap` 的單程序題、`test_e2e_shared_fixtures` 的 login_as（B 負責修，已知原因＝滿載時的時序）。
  - O6：`test_pytest_guards_2026_09_21::test_g2_a_corrupt_lock_file_lets_everyone_through` 在第二班列車全量（5ddd9f44）紅 1 次：子 pytest 收集 tests/ 時 `_hardcap_probe_*` 目錄被 `test_e2e_hard_cap` 同時刪掉（FileNotFoundError）。單獨重跑綠。是測試之間共用目錄的競態，不是列車造成（B）。
  - O7：`modules/tender_radar/tests/test_tender_p9_layout_e2e_2026_09_26.py::test_layout_editor_role_override_and_restore` 在第五班列車全量 e2e 段（f5e7eeee，-n 4、滿載）紅 1 次：④公司預設發布第 2 版（地點打開）後 `sales.reload()`，表頭仍是第 1 版（沒有 location）。單檔循序重跑 3 次都綠。本班沒有一包碰 tender_radar／layout（sidebar.js 只在 MODULE_PAGES 加 dev-crm 一行）。疑點：重新載入時讀到舊版面（快取或發布尚未提交就回應）⇒ 先當產品競態查，下次出現時抓 /api/layout 回應與發布請求的時序（H）
- 稽核：每一項完成、合回之後，照 CORE-SPEC §9d 的分配交叉稽核（A 審 C、B 審 A、C 審 B 與主持）；新的工作線也照這個輪替。
- 視窗上下文：各視窗會自動摘要，不會因為太長而中斷。若某個視窗出現重複、迷失或品質下降，就不再派工給它，改用新的子代理（獨立 worktree）接手；派工內容一律寫成自足的說明，並引用本檔與 PLAYBOOK，不依賴對話記憶。
- 巡視：主持每 30 分鐘（每小時 :13、:43）自動巡視一次；排程 7 天後自動失效，到期前重新建立，內容包括看各視窗狀態、看 git log、派出下一項、更新 §4／§5 與桌面交接檔。

## 6. 進度紀錄（最新在上）

- 2026-09-26 11:13 巡視：第六班組車完成、在列車上修交會紅（71ab31d0）。B、C、D 三窗閒置 ⇒ 派工：B 處理 ⑰ 的 S-1～S-8 與 O 項回覆（C4 等第六班）；C 寫 M06 步驟表（第六班合回後依序做 c-m07-s12 → tax-calc 的 import → M05 → M01）；D 做 D7 前哨第 6 次（origin 第五班之後、開發資料、-n 1）。第七班候選：c-tax-calc、c-m01-sink2-2、h-o7-3、h-o6s1、b-o6-2、b-rebasecheck-2（D 都已關閉或審過）。A（hichan-f9）仍然無回應（U18）。
- 2026-09-26 11:04 D：O6-S1 掃描那一半關閉（h-o6s1 e2c8fdbd，突變「不跳點目錄」紅）；小建議：「刻意含 tests」沒有正對照（突變連 tests 也跳過照綠）。
- 2026-09-26 11:02 D：**O6-M1 關閉（b-o6-2 31d0033d）**：新位置 edge_profile 式掃描 20 次 0 例外、突變 2/2 紅；13 道自寫 rglob 掃描逐行查 12 道排除 tests，只剩 deploy_dashboard_local_only（原本就暴露，1/20）⇒ 建議 O6-S1。R-O1 結案（0f1d8e0a）。
- 2026-09-26 11:00 D：c-tax-calc a1d7ba4a、c-m01-sink2-2 77b9a672 必修 0（突變 5/5 紅）；觀察：c-tax-calc 改 routers/reports.py import，b-m08-2 會搬走該檔，後上車者 rebase 時要把新位置的 import 一起改。
- 2026-09-26 10:57 D：b-o6 a8f60a28（`AUDIT-D-B-o6.md`）必修 O6-M1：競態從收集 tests/ 搬到產品碼掃描（實測新位置 3/20 FileNotFoundError、舊位置 0）；建議 backend/tests/.hardcap_probe_*（在 tests 內＋點開頭）。
- 2026-09-26 10:55 D：R-M1 關閉（b-rebasecheck-2 16150027）；觀察：PLAYBOOK :119、:188 的「fixture 層 ⇒ 全量」沒寫由列車跑。R-S1 仍開。
- 2026-09-26 10:55 D：**b-g1-2 19dc327c**：range-diff 前三個 commit 相同；G-S2、G-O3、G-O4、G-O5 關閉（突變 3 項紅）；G-M1 仍為條件式（同班）。**b-maps-2 c8c69c79**：BM-M1（D2 樹 9 過）、BM-M2（與 b-g1-2 cfe4e914 同班）、BM-S1 關閉。兩包可上第六班，須同車。
- 2026-09-26 10:42 主持：**第六班發車**（列車長子代理）：c-case-access-4、c-m04-3、c-m07-2、b-m08-3、c-coreonly-depscan、b-g1-2*、b-maps-2*、h-hist-4、h-u14-2、h-corered-2、h-o7-2*、c-m02-s2b-2、a-m10 68f16342（O-4）；*＝合回前須稽核關閉，否則連同相依包下車。裁示 G-O5：主持裁示 commit 訊息帶 trailer「Ruling-By: 8d」，列車長以 git log -S <錨點> --format=%B 核對（作者欄都是 rocksk8，trailer 是可稽核的約定、不是防偽）。
- 2026-09-26 10:40 D：b-rebasecheck e0137ddc（`AUDIT-D-B-rebasecheck.md`）必修 R-M1：PLAYBOOK §C-11（:70）本文仍寫「⇒ 重跑全量」，只改了表格②與 MODULE-GUIDE；建議 R-S1。
- 2026-09-26 10:34 D：b-maps d25f7ef3（`AUDIT-D-B-maps.md`）**必修 2，不宜上第六班**：BM-M1 dep_graph.json 寫入 `root`＝工作樹資料夾名（dep_scan.py:559）⇒ 模組全在時在 D 樹就紅（只在產生它的樹綠）；BM-M2 拿掉 netplan 或全部 L2 ⇒ 三題新守門全紅、不在 §B-11／core-only 允許清單。另：我那一輪 core-only 已停（taskkill /T、無孤兒、拋棄式樹已移除）。
- 2026-09-26 10:34 主持：O7 查明為產品競態（不是環境）：排版器切換範圍載入中仍可編輯，載入回來整份覆蓋 ⇒ 修改靜默消失、照樣發布出與上一版相同的一版；另有連切兩次時舊回應蓋掉新範圍。wip/h-o7 修正、交 B 稽核。主持自己踩到 G-O4：-n 2 的守門題排隊等測試鎖 40 分鐘、CPU 0.9 秒，從外面看像在跑；停掉（taskkill /T，查過無孤兒）改 -n 1。D 審完 c-m07（必修 0）、c-m04-2（全關）、depscan、b-g1（G-M1 條件式關閉）、主持三包（必修 0）⇒ 接審 B 的 b-maps、b-rebasecheck、b-o6。第六班等 C 的 c-m04-3、c-m07-2（約 10:55）。
- 2026-09-26 10:30 D：h-corered-2 b682b9bf 必修 0（拿掉全部 L2 兩檔 11 過、突變 2/2 紅）；h-hist-4 5e736075、h-u14-2 1fa732e6 range-diff 與審過版本相同（h-hist 前兩個 commit 已隨第五班合回）。
- 2026-09-26 10:28 D：**M04-M1、S1～S3、O 關閉**（c-m04-2 dd7aecf0：真刪 1459 過／3 紅＝允許 2＋G1 快照 1；條件與 b-g1 同車）。**G-M1 條件式關閉、G-S1 關閉**（b-g1 6e7ba250：突變 KR1～4 皆紅；sparse 樹實查 modules 只剩 __init__.py；條件：與 h-corered、c-coreonly-depscan、c-m07、b-m08-2 同班）；G-S2 仍開。c-coreonly-depscan 2784140e 突變 2/2 紅。觀察：judge 只擋 exit 5、排隊時無輸出。
- 2026-09-26 09:53 D：c-m07 4a731b1f（`AUDIT-D-C-M07-move.md`）必修 0，§B-11 首次提交即過（真刪 1193 過／2 允許、收集無錯；模組在 1512 過）；建議：IP 登記表 6 處結構化欄位指向搬走路徑（M04-S1 同類第二次 ⇒ 建議落實路徑存在守門）、api_module 豁免只信宣告。突變 4/4 紅。
- 2026-09-26 09:40 主持：第五班合回 a6dc4be6（列車長子代理，crm 真刪必驗通過：1190 過、只紅允許 2）；主持三包 rebase 改名上月台（h-hist-4、h-u14-2、h-corered-2）；O7（P9 排版器 e2e 發布第 2 版後表頭仍是第 1 版）由主持追查。
- 2026-09-26 09:37：**第五班列車合回**（train/0926-0746，3 包：c-m02-2（車頭，動 main.py）→ c-m02-s2 → h-hist-2，全部上車；platform a6dc4be6）。
  - 取的 commit：c-m02-2 七個（472d630a、52132397、755bdf56、6787e80d、0cd55269、81d563e9、c56ca925）、c-m02-s2 bcd4288c、h-hist f4c14dc5＋288e3a78（主持改帶 h-hist-2，全量後補上）。略過：c-m02-2 自帶 UNIT-INDEX 重產 9840974b。git cherry：皆無已合回的重複 commit。
  - 衝突（第四班 a-m10 合回後 c-m02-2 基底已舊）：main.py 匯入行、sidebar.js MODULE_PAGES、ROADMAP 階段 B 清單，列車上合併。
  - 取號：CORE 不升（core_bump：無 L1 介面變動、無段落）；IP `crm.quote_deleted` IP-11→**IP-13**（IP-11＝daily.check、IP-12＝case.access）；crm 模組 1.0.2→1.0.3（IP 定號動了模組碼）→1.0.4（下述題目拆分）；version_manifest 無新條目（三包都沒有使用者可見的新行為）。
  - 全量（f5e7eeee，-n 4、低優先權）：非 e2e 4653 過 1 紅、e2e 435 過 1 紅。①`test_module_changelog_follows_code`：IP 定號改了 crm 碼卻沒新版號 ⇒ crm 1.0.3（交互紅，已修）②P9 e2e 紅 1 ⇒ 登 **O7**（循序重跑 3 次綠）。
  - 反向控制（主持必驗，拷貝樹真刪 modules/crm，tests/platform＋提到 crm 的 18 檔，--continue-on-collection-errors、-n 2；先確認無只剩 __pycache__ 的模組資料夾）：第一次 1190 過 3 紅＝§B-11 允許兩題＋`test_no_notice_when_crm_is_present`（需要 M02 的 e2e 正對照留在模組外）⇒ 拆進 modules/crm/tests（bab09705）；重做 1190 過 **2 紅＝只剩允許兩題**、收集錯誤 0。
  - 全量之後的改動（crm 版號、288e3a78、題目拆分、test_map 重產）：tests/platform＋modules/crm/tests＋notice e2e 1042 過；deploy_dashboard／insights 119 過（-n 1）。rebase 到 origin（只有文件）後 tests/platform 1005 過；再 rebase（只有 RUN-PLAN）後直接推。全量在 f5e7eeee，差異題在 origin。
  - 待處理：疊在本班乘客上的 wip/c-m02-s2b、wip/h-hist-3 要 rebase 到 a6dc4be6；`dep_scan --check-modules` 有 1 筆既有的歸屬錯誤（daily_tasks module.json api_prefixes [] ≠ modules.json M12 `/api/settings`，第四班帶進，非本班）。

- 2026-09-26 09:33 主持：裁示 M01 改派 C（A 無回應）；核准 T 先做（稅額純函式下沉 L1，解掉 pdf_gen、M05、M08、receivables 對 M01 的相依，也是 CA-O4 的一半）；M01 反向控制由列車全量在 sparse 樹兼任。C 的更正：helpers/quotations 歸 M01 不是 L1（原句保留劃掉）。新發現：L1 pdf_gen 會寫 M01 的 quotations 表。
- 2026-09-26 09:31 主持：D 關閉 ⑰ M08 必修 M-1～M-4（b-m08-2 f7463dfa，LD1＋§B-11 獨立重做：刪 analytics 後 1264 過、只紅允許 2）。D 指出：worktree 啟用 sparse checkout 會在共用 .git/config 寫入 `extensions.worktreeconfig=true`（主持的 Hcore、C 的 C29／C31／C33、B 的暫存樹都用過）。查證：各樹的 sparse 設定在自己的 config.worktree，主樹與其他樹不受影響。**裁示保留這一行**：拿掉的話，那幾棵樹的 sparse 設定會被忽略，下次 checkout 會把模組取回來，反向控制變成沒人察覺的假綠。兩種做法都接受（自己樹裡刪資料夾／sparse）。X-O10（演練只看 probes，未宣告的模組不再被打）：tender_radar 由主持在 b-m08-2 合回後補，daily_tasks／netplan 交給擁有者。C：M05 等第六班合回後以 origin 開工（先試合 b-m08-2＋c-m04-2 撞 13 檔，已 abort）；等待期間寫 M05 與 M01 步驟表（M01 可能從 A 轉給 C，待裁示）。
- 2026-09-26 09:29 D：⑰ M08 必修 M-1～M-4 **全部關閉**（b-m08-2 f7463dfa；突變 14 項全紅）。§B-11 D 獨立重做：真刪 analytics 1264 過／2 紅皆允許、收集無錯誤；模組在 1459 過。觀察 X-O10：tender_radar 等未宣告 probes ⇒ 演練不再打它們的端點。
- 2026-09-26 09:27 B（記錄主持裁示，AUDIT-D-B-G1 G-M1）：**core-only 已知紅清單**首批（`tools/platform/core_only_known_red.json`；列車判定＝紅燈 ⊆ §B-11 允許＋本清單；清單只准縮短，新增一筆要在本檔寫一行帶錨點的主持裁示）：
  - `CORE-ONLY-KR-1` test_reverse_controls_absent_module_routes_are_exempt_present_ones_still_compared（case_read_scope）：擁有者 A（暫記主持），修復分支 wip/h-corered 3710f462
  - `CORE-ONLY-KR-2` test_absent_module_green_present_module_still_red（IP 登記表）：擁有者 A（暫記主持），修復分支 wip/h-corered 3710f462
  - `CORE-ONLY-KR-3` test_dep_scan_and_source_tree_agree_on_module_files（dep_scan 一致性）：擁有者 C，修復分支待 C 指定
  - `CORE-ONLY-KR-4` test_every_pii_form_has_a_decision_and_it_still_holds（pii_forms 的 netplan 告知端點）：擁有者 C，修復分支 c-m07 816101b2（api_module）
  - 另 menu_parity 兩題（test_every_legacy_item_is_declared_identically、test_rendered_menu_matches_for_every_single_permission）由 wip/b-m08-2 修，不進清單（同一班列車帶上即綠）。
- 2026-09-26 09:14 巡視：第五班列車長在跑 crm 真刪反向控制；B 的 M08 必修已修（b-m08-2 f7463dfa）⇒ D 複核中；C 的 c-m07 約 09:20、c-m04-2 約 09:50；A（hichan-f9）仍無回應（U18）。主持：IMPROVEMENT-REPORT 補 M08 稽核列與 5 條系統性問題（觀測點綁名字、掃描範圍寫死舊目錄、修並發只驗一個方向、刪資料夾被擋改用 sparse checkout、主持自己違反 rebase／push 分開）。
- 2026-09-26 09:01 主持：D 稽核 b-g1（AUDIT-D-B-G1）必修 G-M1：core-only 反向控制跑出 4 題非預期紅，§G3 規定全綠，第一班就會擋車。裁示：工具加「已知紅」清單（題名、擁有者、修復分支；只准縮短、已轉綠還留著也紅、新增要附主持裁示），交 B 在 M08 必修之後做。4 題中歸 A 的 2 題由主持在 wip/h-corered 修掉（正對照改用合成模組）；C 的 2 題（dep_scan 一致性、pii_forms netplan）交 C。G-S1（0 題判 ok）交 B。做法說明：要「只剩底層」的樹時用 sparse checkout 不取出 modules，不刪資料夾（刪資料夾會被權限擋，也不應該繞過）。
- 2026-09-26 08:58 D：b-g1（`AUDIT-D-B-G1.md`，6b0c8fdd）：必修 G-M1——D 實跑 core_only_rc 在 B 自己的 commit 上 8 failed／989 passed，扣允許 2、b-m08 已修 2（menu_parity），**另 4 題沒處理也沒分派**（case_read_scope 反向控制、IP 登記表 present-still-red、dep_scan 一致性、pii_forms——正對照需要一個在的模組／netplan 告知端點）⇒ 照 §G3 第一班就擋車。建議：exit 5／0 題也判 ok（實測）、宣告不存在名稱靜默忽略。宣告機制突變 4/4 紅。
- 2026-09-26 08:43 巡視：第五班全量跑完（f5e7eeee），列車長在修交互紅（07f81ed3 crm 版號、fa713fac h-hist-2）；D 關閉 O-4、M02-S2（含 s2b）⇒ 派審 B 的 wip/b-g1；B 在修 M08 必修（死線 10:20）；C 的 c-m04-2 晚於預估的 08:30（在等反向控制結果）、M07 預計 10:00 回報；A（hichan-f9）仍然無回應（U18）。主持自己更正：這幾輪推文件時，rebase 與 push 寫在同一個指令（違反 PLAYBOOK／〈rebase 之後先重跑再推〉），帶進來的都只有文件、沒有造成影響；之後分成兩個指令。
- 2026-09-26 08:41 D：c-m02-s2b 6e2e15a7 複核：核准端點外人題與角色／列權限分辨成立，D 突變 S2c 紅 ⇒ M02-S2 觀察結案。
- 2026-09-26 08:21 D：O-4 關閉（a-m10 68f16342：突變 2/2 紅；實境殘留 __pycache__ 探測新判準只紅允許 1、舊判準紅 4）。M02-S2 關閉（c-m02-s2 bcd4288c：先前存活的 MC2 轉紅＋新增記錄突變紅）。
- 2026-09-26 08:20 主持：稽核 ⑰ M08 完成（子代理，wip/audit-m08 611b6c6f 併進 platform）：必修 4、建議 6。系統性：守門以名字包 db.get_db 觀測連線，綁名 import 全部漏看（B 的 O8 同源）⇒ 要求改觀測最底層。稽核員 rm 模組資料夾做 §B-11 被權限擋，照規則沒有繞過、主持不代做；改由 B 在自己的樹重做。附帶發現：主工作樹 `.venv` 缺 pyvenv.cfg（`.venv312` 可用）。
- 2026-09-26 08:14 巡視：第五班（TRAIN5，train/0926-0746）與 M08 稽核 ⑰ 進行中；D 已審完 h-u14、h-hist 系列，全部結案，閒置中 ⇒ 派它審 A 的 O-4 68f16342 與 C 的 c-m02-s2；C 預計 08:30 推 c-m04-2；A（推定 hichan-f9）從 07:07 起沒有動作，兩次詢問都沒有回應 ⇒ 記 U18。
- 2026-09-26 08:12 D：H-S2 關閉（h-hist-3 9e55dfa1：併回、順序、刪檔失敗後不重複、警告回正常，實測＋13 passed）。AUDIT-D-host-U14-hist 必修／建議全數關閉。
- 2026-09-26 08:07 D：U-S1 關閉（h-u14 48dab2a3，突變 U1 紅）；H-S1 關閉（h-hist-3 1ef54b72，實測主檔不動、另存 pending）。新建議 H-S2：pending 從不併回、警告永久存在且排在「15 分鐘剛失敗」之前（警告疲勞）。
- 2026-09-26 08:04 主持：D 審完 h-u14（必修 0）、h-hist-2（H-M1 關閉，可上車）、c-case-access-3（CA-M1 維持關閉）。處理：U-S1 補題（h-u14 48dab2a3）、H-S1 修正（wip/h-hist-3 1ef54b72）、CA-O4 寫進 ROADMAP M01 條目（M01 搬遷時切斷 L1 對 helpers.quotations 的匯入，交 A）。
- 2026-09-26 08:00 D：**H-M1 關閉**（h-hist-2 288e3a78：同一探針 0 例外、200／200、讀到空 0 次；10 passed）。新建議 H-S1（H-O1 升級）：寫入端把讀檔失敗當空再覆寫，一次暫時占用就把 200 筆蓋成 1 筆（修正前既有，不擋車）。
- 2026-09-26 07:59 主持：D 抓到 h-hist 第一版讓掉筆變多（讀取端沒拿鎖）；wip/h-hist-2 288e3a78 修正，已通知第五班列車長改帶。教訓：修並發只測了「寫對寫」，沒測「讀對寫」，而讀取端就是儀表板本身。
- 2026-09-26 07:58 D：h-hist 必修 H-M1——讀取端（/api/history、15 分鐘失敗警告）沒拿 _history_lock ⇒ Windows 上 os.replace 丟 PermissionError，真實程式實測 300 寫 145 例外掉筆（修正前 0）；07:54～07:57 之間已建議下第五班（原寫 07:52 為手打，已更正）。h-u14 必修 0、建議 U-S1（存檔後 canEdit 缺欄位路徑無題）。c-case-access-3 0da9d647 複核：CA-M1 維持關閉（突變 2/2 紅）；CA-O4：case.access 在 helpers/quotations 匯入時登記、L1 也匯入它 ⇒ M01 搬遷時須改 ModuleSpec 登記並切斷 L1 匯入。
- 2026-09-26 07:53 主持：第五班列車長（c-m02-2、c-m02-s2、h-hist）與 M08 稽核 ⑰ 子代理出發；U14 前端完成（wip/h-u14 6639ea8d，交 D 稽核）。裁示 D ⑮ O-1：privacy_notice_acks 維持 L1 共用表。M04-M1＋S1～S3 交 C 在 c-m04-2 修。PLAYBOOK §G3 補兩條（列車長要等到結果行、反向控制前清 __pycache__ 殘留模組夾）。C：c-case-access-3（0da9d647）與 c-m04-2（26ff8a50）差異題中，約 08:30 推；M07 搬遷完成、剩 6 道共用守門改 module_installed。hichan-f9 07:2x 詢問未回。
- 2026-09-26 07:46 D：⑮ M04（`AUDIT-D-C-M04-move.md`，c-m04 dd6f1550）：必修 M04-M1——真刪 subcontract，tests/platform＋49 檔 1273 過／77 紅／2 檔收集失敗（模組在時 1411 全過）；扣允許 2、已知已分派 4、第四班已修 1 ⇒ 70 題＋2 檔需要 M04 留在模組外（c-m04-2 重上車時一併修）。建議：IP-1／12／14 提供方路徑少了 `api/`（登記表守門不驗路徑存在）。O-1 privacy_notice_acks 改模組表延後需主持確認。
- 2026-09-26 07:44 主持：**第四班列車合回 427c8be9**（c-module-files、a-m10〔M12＋M10〕、h-p9、h-p8-gaps、c-audit-d-2〔C-M4〕、c-refopt；CORE 1.24～1.29；IP daily.check＝IP-11、case.access＝IP-12）。全量（892ea49a）非 e2e 4642 過 4 紅、e2e 434 過 0 紅；4 紅皆交會：daily_tasks／netplan 缺 customization＋列車 IP 定號動了模組碼沒有版號條目（補空類別、升 1.0.1／1.0.2）；兩題用 layout 驗儲存語意，同 worker 先 import routers.definitions（P9 驗證器）就擋（補 delitem）。修後相關 272 題＋rebase 後讀文件的 52 檔 806 題綠。D 的 O-1（netplan 告知端點）列車上已搬。列車長在等待中結束回合，主持接手；之後它復活並核對同一修正（1396 題綠），推送由主持做。另：history.json 殘字＝產品競態，wip/h-hist 修。
- 2026-09-26 07:11 D：**M02-M1、M02-S1 關閉**（c-m02-2 9840974b）：真刪 crm 1251 passed／4 failed＝允許 2＋待 a-m10 合回 2；模組內 34 passed；條件：第四班 a-m10＋c-m02-2 同車時列車上真刪 crm 只剩允許 2 題。新建議 M02-S2（修改業務開發案件的列權限無題，突變存活；搬遷前既有）。
- 2026-09-26 07:05 C：D1 階段 B 開工 M07 薪資獎金（key `payroll`，worktree C28、wip/c-m07；M05 等 B 的 M08、M06 等 M04／M08 合回，先做 M07）。會動到的共用處：①L1 `routers/system.py` 的 `/api/system/bonus-module-status` 改走 M07 提供者（不再 import `helpers.bonus`，DEPENDENCY-MAP #27）；②`helpers/bonus_pdf.py` 不再借 M06 的 `voucher`／`voucher_pdf`：公司抬頭改用 L1 `company_identity.company_name`、HTML→PDF 改用 L1 `pdf_gen.html_to_pdf_bytes`（Edge 參數相同）、`resolve_display_names`（簽核格的帳號→顯示名稱）與 `_fmt_money` 下沉 L1（M06 保留同名匯入）；③`main.py` 拿掉兩支 router；`sidebar.js`、`modules.json`。
- 2026-09-26 06:50：D 做完個資告知的合回後稽核：必修 PN-M1（決定以頁為單位，同一頁的第二種當事人，例如出貨單收件人，沒有人決定過）⇒ 裁示改為逐欄決定、收件人要告知，交給 A（出貨模組擁有者），排在 M03 之後；O-1（network_plans 的告知端點要跟著搬進 netplan）已提醒第四班列車長；O-4 module_installed 改看 module.json，交給 A。
- 2026-09-26 06:49 D：⑯ 個資告知（`AUDIT-D-pii-notice.md`，合回後）：必修 PN-M1——notice 決定以頁為單位，案件頁出貨單收件人＋送貨地址可手打、沒有告知對象而守門放行（違反「手動輸入的聯絡人要 notice」）；建議 3（報價單告知端點權限、畫面換人重新告知、唯讀判斷）；12 頁決定與伺服器端換人重新告知成立。O-1：第四班 M10 rebase 要把 network-plans 告知端點搬進 modules/netplan（守門會抓）。另補 M10 稽核 O-4（空模組資料夾被 module_installed 當成在）。⑮ c-m04 尚未推上 origin，等 C。
- 2026-09-26 06:43 巡視：各線都在工作（A M03、B M08、C M02-M1／M04、D ⑮～⑰），第四班列車進行中。D1 剩下 M05、M06、M07（C）與 M01（A）尚未開工；這幾個模組彼此牽連，同時開太多條線會衝突，所以不另外派子代理。不派工。
- 2026-09-26 06:39：第三班列車合回（2934bbc9／2794b93e，4 包，0 紅）。第四班列車進行中。D 關閉 case_access 的 CA-M1 ⇒ c-case-access-2 搭第五班；D 下一個審 c-m04（⑮）、個資告知（⑯）、M08（⑰）。CA-O3 寫進 ROADMAP，M01 搬遷時必做。
- 2026-09-26 06:38 D：⑭ case_access **CA-M1 關閉**（c-case-access-2 a82da8ec）：判準改看 `case.present`，loader 對停用／未授權不 import ⇒ 成立；D 突變 6/6 紅、基準 106 passed；CA-S1／S2／O1 關閉；新增觀察 CA-O2（表名變數、大寫 Quotations 抓不到）、CA-O3（M01 搬遷時 case.present 要進 ModuleSpec.providers）。仍開：M02-M1。
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
