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
| U15 | ~~已裁示 2026-09-26 12:54：至少保留一位超管（實作歸主持）~~ **系統技術類信件（備份、磁碟、憑證告警），能不能讓所有超級管理員都退訂？**（D 稽核 a-mail 建議 M-S1） | 目前可以，全部退訂之後就沒有人收到；設定頁會標出「目前沒有人會收到」 | 建議：系統技術類「至少保留一位超級管理員」不可以退訂；最後一位退訂時要擋下並說明。這會限制個人退訂，所以要你決定 |
| U16 | ~~已裁示 2026-09-26 12:54：維持現狀~~ **子代理推送共用分支、刪除自己的 clone，被權限規則擋下**（個資告知代理，05:12） | 它把月台登記推到 platform 時，被判定為「修改共用資源」而拒絕；刪 clone 之前的占用查詢也被拒絕。依規則，主持不代替它做被拒的動作（避免繞過權限）。它的分支已經在 GitHub，主持以自己的判斷把它排進列車 | 請你決定：①要不要刪 `C:\Users\hichan\.claude\worktrees\agent-aa2f19501a0fe66d3`（clone＋測試庫）②往後子代理推 RUN-PLAN 這類文件是否要放行（需要調整權限設定，由你做） |
| U17 | ~~已裁示 2026-09-26 12:54：整份覆寫~~ **角色版面要「整份覆寫」還是「只存差異、疊加在公司版上」？**（P9 拖曳排版器） | 目前是整份覆寫：角色第一次覆寫時複製公司版；之後公司版再改，已經存在的角色版不會跟著變 | 建議改成**疊加**：角色版只存「和公司版不同的點」，公司版改了，沒有被角色覆寫的地方會自動跟著改。比較符合「公司預設＋角色覆寫」的直覺，代價是 resolve 要改成合併兩層（L0） |
| U18 | ~~2026-09-26 12:54 解除：A 回報沒有在等權限，是在等使用者回答一題；已恢復工作（M03 rebase 到最新 origin）~~ **視窗 hichan-f9 一直顯示 waiting、兩次詢問都沒有回應**（2026-09-26 08:14） | 很可能停在權限確認畫面，要有人按。A 的 `wip/a-m03`（M03 出貨模組搬遷）從 07:07 起就沒有新 commit，而且還只在本機、沒推上去。依規則，主持不代替它做被拒絕的動作 | 請你看一下那個視窗：是權限確認就按（或拒絕），是其他狀況就告訴我。若它回不來，主持會改派子代理，從 A11 worktree 的 wip/a-m03（b9ac9ce9）接手 |
| U19 | **字型授權檔不在 repo**（2026-09-26 14:19 主持查 O5 時發現） | 產品隨附 LINE Seed TW 四支 otf（frontend/fonts/，共約 21 MB），repo 裡沒有任何授權檔（OFL.txt 之類）。產品要販售，隨產品散布字型通常要附授權檔；主持推測是 SIL OFL 1.1，**尚未確認**。woff2 轉檔（O5-S3，可省約一半容量）也要等授權確認後才做 | 請你確認字型的來源與授權，並提供授權檔放進 frontend/fonts/；確認後主持轉 woff2（不做子集，避免罕用字變方框）|
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
  - 〔主持裁示 2026-09-26 14:19，M06（A 提問五點）〕a. 搬遷時暫留「L2 讀 M01 表」（quotations、case_extra_expenses）為已知例外，**比照 KNOWN_L1 附到期守門**（M01 提供 case.summary／case.extra_expenses 後自動變紅）；b. 附件另開一包 `attachments.for_document`（比照 approval.reassign，排在 M01 前置），M06 先直讀並登記例外＋到期守門；c. `parse_approval_json` 下沉 L1 tiered_approval（純解析），不登記新的 L2 邊；d. C 在 IP-14 加 `paid_between(start, end)`（M05 之後），沒趕上則 M06 先直讀＋到期守門；e. JV 系列規格比照 M07 的 BN 搬進 modules/accounting/SPEC.md。
  - 〔主持裁示 2026-09-26 13:58，M05 收回 receivables（C 提問）〕選 **(a) 薄殼**：L1 `helpers/receivables.py` 保留同名函式、改成轉呼叫 provider（`receivables.income_items`／`receivables.tax_invoices`），標記淘汰、下一個主版號刪除（依「底層同主版號只准新增」；不升 CORE 2.0）。殼不再讀 quotations ⇒ `test_known_l1_baseline_is_not_stale` 會自動提醒自 KNOWN_L1 刪除（同包刪、並以此為正對照）。另加守門：殼只准轉呼叫 provider、不准 import modules.*、不准有 SQL；M05 不在時 income 回 []、tax 回 404 並明說。淘汰記錄寫進 ROADMAP 與 L1 CHANGELOG。
  - 〔主持裁示 2026-09-26 13:24，縮短時程〕**M06 改派 A**（A 做完 M03、PN-M1 之後，依 docs/platform/plans/M06-PLAN.md 與上方 M06 裁示）；M06 依賴 M05 收回 receivables ⇒ C 的 M05 盡量提前。C 的線：probes S-1／S-2 → c-tax-calc → c-m01-sink2 → M05 → M01。M07 O-2（沒有 bonus 提供者時報表附說明）維持現狀。
  - 〔主持裁示 2026-09-26 12:54，case.summary 修訂（C 提問四點，M01-PLAN §3-4 開工前）〕① 地圖要的是地址 ⇒ **另開 `case.locations`**（M01 提供，回 `{quote_no, address}`；地址屬個資類~~，資料分級照 MODULE-GUIDE §11~~〔更正（主持，稽核 D CS-S1）：§11 是表單告知，不適用唯讀串接點；改在 IP-97 註明 address 屬個資、只給有該案讀取權限的人、呼叫端不可寫進 log 或匯出〕），不塞進 summary；map_points 改走 case.locations 後才移出 KNOWN_L1（h-cas3 的到期條件同步改寫）。② 兩者都接受「不給 quote_no ⇒ 回目前使用者看得到的全部」。③ **case.summary 是正式版**；IP-12 case.access 的 `summary(conn, quote_no)` 改成轉呼叫 case.summary 並標為淘汰，不兩個並存。④ ~~`user=None`＝系統身分、不做權限過濾，**只准 L1 背景呼叫端使用**（google_calendar 回寫、archive、company_identity），加守門：L2 呼叫帶 user=None ⇒ 紅~~〔更正（主持同意，2026-09-26）：改用哨兵 `helpers.case_access.SYSTEM`；`user=None` 一律 TypeError——None 可能在忘了傳使用者時意外出現，然後悄悄拿到系統權限；守門掃得到哨兵的每一個引用（只准 L1），掃不到一個 None〕。
  - 〔主持裁示 2026-09-26 11:16，M06 步驟表（C）〕① **轉簽直寫各單據表**（routers/quotations.py:6597 `reassign_approval`，`_REASSIGN_TABLES` 逐表直寫六種單據，含 M06 的 vouchers_all）：獨立成一包 `approval.reassign`，每種單據由擁有模組提供，並和 `approval.queue_items` 一起做，併入 M01-PLAN §3-7；不在 M06 裡只修傳票一種。② **前綴歸屬**（M06 的 /api/reports/t100-export*、/api/settings/t100-export-config 掛在 M08 與 L1 的前綴底下）：**不改網址**（改網址會破壞相容性：V9 轉移、書籤、外部呼叫）。改由 modules.json 允許「個別路由明列歸屬、優先於前綴」，B 的 check_modules 要支援這種寫法，並附反向控制（明列的路由不在該模組 ⇒ 紅）。③ 新串接點 `inventory.paid_batches`（M03 提供，accounting_export 使用）核准，號碼由列車定。④ 順序：M05 → M06（accounting_export 對 receivables 的相依要等 M05 收回）。M06 由 C 做，排在 M05 之後。
  - B：M08（2026-09-26 04:47 從 A 移過來；C4 開工時暫停）〔2026-09-26 05:39 佇列：M08 → dep_graph／test_map 一致性守門（比照 UNIT-INDEX --check，附反向控制）→ O6 → C4（開工時主持宣布凍結）。M08 要排在 c-module-files 之後上車〕
  - C：M02 crm／dev_crm（進行中，wip/c-m02）→ M04 → M05 → M06 → M07
  - 搬遷順序依 ROADMAP 階段 B 的相依；兩邊要動同一個 L1 helper 時，先在 RUN-PLAN §6 講一聲再動
- **列車月台**（PLAYBOOK §G3；各線登記：分支｜HEAD｜差異題結果｜是否動 fixture 層／main）：
  - C｜`wip/c-approval-2`（主持裁示：/detail 接著做、排在 M01 本體之前——`approval.detail`（IP-93 暫定）：簽核佇列詳情裡其他模組單據（承攬商匯款申請、開票申請、請款單、出貨單）的內容由擁有模組提供，M01 只做每案權限、案件抬頭、金額遮蔽；**c-approval 299aed61 之上 fast-forward 兩個 commit**，D 稽核 c-approval 可直接接著看 299aed61..49dcb781）｜49dcb781｜tests/platform＋佇列／詳情／轉簽相關＋M04／M05 非 e2e＋出貨單相關：1781 過（紅 1＝sidebar，等 C4）後修 3 紅（契約題缺案件種子、IP-93 路徑寫成萬用字元、UNIT-INDEX），修後受影響題過；開簽核佇列頁的 e2e 24 過；契約題 +3；突變 6/6 紅（首輪兩項綠 ⇒ 補「鏈上一般使用者看得到內容與金額、外人 403」一題）｜CORE 1.39 同段補兩個名稱；subcontract 1.0.6、arap 1.0.2（列車取號）〔C 登記〕
  - C｜`wip/c-approval`（M01-PLAN §3-7，主持裁示 M06 ①：`approval.reassign`（IP-94 暫定）＋`approval.queue_items`（IP-10）——轉簽與待我簽核／角標改由各單據模組提供，M01 只彙整；L1 新增 `helpers/approval_queue`；**疊在 c-m01-rec-2 之上**）｜299aed61｜tests/platform＋佇列／轉簽相關＋M04／M05／M07 非 e2e 與傳票／出貨單相關題：2153 過（紅 1＝sidebar，等 C4）；開簽核佇列頁的 e2e 6 檔 24 過；契約題 6＋覆蓋率 2；突變 8/8 紅｜CORE 暫 1.39；動 subcontract 1.0.5、arap 1.0.1、payroll 1.0.3（與 c-ip14-paid／b-c4 版號交會，列車取號）、A 的 M03 `routers/shipping_notes.py`（origin 已搬 modules/supply，rebase 時跟著搬）、M06 `routers/vouchers.py`（與 a-approval-parse 同檔不同段）；§6 已宣告〔C 登記〕
  - C｜~~`wip/c-m01-rec`~~ → **`wip/c-m01-rec-2`**〔更正（C）：c-m01-s3-2 加一行夾具修 CS-M1（88192c07）後 rebase，內容不變；D 通過 a56f33e4〕（M01-PLAN §3-6：`case.recognition`（IP-95 暫定）——M08 報表的收入認列／支出歸月／待補登改經 M01 提供者；口徑標籤下沉 L1 `helpers/recognition_basis.py`；M01 不在 ⇒ 權責收入 incomeNotice、支出 unavailable 列案件類、待補登 {}；**疊在 c-m01-s3-2 之上**）｜~~aac6b836~~ **a56f33e4**｜tests/platform＋analytics tests 1260 過（紅 1＝sidebar，等 C4）；契約題 9；突變 5 項皆紅｜L1 新增（CORE 暫 1.38）；動 B 的 analytics（1.0.5，§6 已宣告）〔C 登記〕
  - C｜`wip/c-m01-s3-2`〔取代 c-m01-s3 6d091294：疊到 c-m05b-2 之上（主持裁示）；IP-12 `_CaseAccess.summary` 登記進 deprecations.json（兩包同班不紅）；test_deprecations 支援 Class.member；CORE 1.37〕HEAD＝**dbd07633**（d93a792a 之後修稽核 D CS-M1：SYSTEM 守門涵蓋所有取用寫法＋執行期第二道；CS-S1：IP-97 個資註記）；以下為原登記：（M01-PLAN §3-3＋§3-4：§3-3 在 origin 上已成立、不需改碼；§3-4 `case.summary`／`case.locations`（主持四點裁示；IP-96／97 暫定）；系統身分哨兵 `helpers.case_access.SYSTEM`（user=None 拒絕，只准 L1＋守門）；地圖改走 case.locations、KNOWN_L1 刪 map_points（到期題紅→綠）；IP-12 summary 轉呼叫並標淘汰；基底 origin/platform）｜6d091294｜tests/platform＋地圖／案件存取相關檔 1425 過；突變 5 項皆紅｜L1 新增（CORE 暫 1.35）；⚠ 與 c-m05b-2 交會：deprecations 反掃會要求登記 IP-12 summary（兩包都上車後補）；ATT 那一列待第八班合回後補〔C 登記〕
  - C｜`wip/c-ip14-paid`（主持派工，A 的 M06 前置：IP-14 加 `contractor_voucher.paid_between(start, end)`；M06 accounting_export 的 T100 付款傳票改走它、不再讀 M04 的表；基底 origin/platform）｜**9623f1be**（6c8406c5 之後修稽核 D IP-M1）｜tests/platform＋subcontract tests 1151 過；突變 4 項皆紅；IP-M1 修後 88 過｜只動 subcontract（1.0.5，與 c-probes／C4 版號交會，列車取號）、accounting_export 一個函式、INTEGRATION-POINTS IP-14〔C 登記〕
  - C｜`wip/c-m05b-2`〔c-m05b 之後快轉：稽核 D M5-M1（淘汰登記＋到期守門）、M5-M2（e2e 關 context）、M5-S1〕HEAD＝**c5484962**；以下為 c-m05b 登記：（D1 階段 B：M05 應收應付搬進 `modules/arap`（api/ 三支 router）；receivables 收回＋L1 薄殼（主持裁示 (a)）；bank-reconcile 收回；新 provider IP-98／99 暫定；M01 案件頁、M08 報表頁在 M05 不在時說出原因；細節：分支 README／CHANGELOG、AUDIT 待 D）｜b17e5296｜M05 在：tests/platform＋123 檔 1993 過、e2e 87 過；紅 1＝sidebar 題（等 C4）。反向控制（sparse、有／無旗標）：1914 過 6 紅＝§B-11 允許 2＋產生檔一致性 3（test_generated_maps，交 B 判定是否同類允許）＋CHANGELOG 1（已修）；突變 8 項皆紅｜**依賴 c-tax-calc-2（疊在其上）＋B 的 C4（sidebar 題；上車前 rebase 到 C4，並把 cashier.html 選單項移進 module.json）**；🔴 動 main.py、modules.json、INTEGRATION-POINTS、analytics（1.0.3）、accounting_export；CORE 暫 1.36〔C 登記〕
  - A｜`wip/a-pn-m1`（稽核 D AUDIT-D-pii-notice PN-M1＋PN-S1～S3：個資告知逐欄決定、出貨單收件人告知；**疊在 wip/a-m03 上，排在它後面**）｜7c11091b｜非 e2e：tests/platform＋modules/supply＋告知題（-n 4）1165 過；e2e：改到的頁面 75 檔（-n 2）265 過 2 紅 ⇒ 修後 52 過（golden 不變：出貨單區塊改成打開視窗才載入）｜突變 14/14 紅（守門 6、端點 3、畫面 3、PN8／PN9），含 D 原本存活的 PN8、PN9、PNJS｜動 M01 頁面 case-management.html／case-management-shipping.js、M03 出貨單端點（supply 1.0.2）、守門 _pii_forms.py、pii_forms.json（客戶／供應商主檔 not_natural_person＝使用者表單 (a)）；fixture 層／main／L1：無｜登記 2026-09-26 14:4x A，排第九班
  - A｜`wip/a-approval-parse`（主持裁示 M06-c：簽核鏈 approval_json 解析下沉 L1 `helpers.tiered_approval`；M01 簽核佇列不再 import M06；獨立 L1 小包，基底 origin/platform）｜708dbe0d｜tests/platform＋傳票／簽核相關 169 檔：非 e2e（-n 4）2380 過、e2e（-n 2）131 過｜突變 5/5 紅（別名指錯、例外類別不一致、L1 反過來 import L2、M01 退回 import M06、別名不帶「傳票」）；契約題：tiered_approval 不 import L2｜L1 新增兩個公開名稱（CORE 暫取 1.35，列車上 core_bump）；`routers/quotations.py` **只改一行 import（與 C 的 M01 包同檔一行）**；l2_import_baseline 刪 M01→M06 一條邊；fixture 層／main：無｜登記 2026-09-26 15:0x A，排第九班
  - B｜`wip/b-c4-3`（取代 b-c4-2 dd20cc5d：稽核 X AUDIT-X-B-C4 必修 M1＋建議 S1～S5＋O3 主持裁示＋O1／O2 已修，rebase 到 origin；版號改 crm 1.0.7、payroll 1.0.4、subcontract 1.0.6（c-probes 先上第八班）；其餘同 b-c4-2 列）｜7f52389e｜rebase 後非 e2e（tests/platform＋凍結靜態題＋6 模組 tests，-n 4）1857 過；e2e（凍結清單＋修過三檔＋選單 e2e 8 題，-n 2）97 過；突變 X8／X2／S1 皆紅｜**動 main.py**、**前端全頁**；待 X 複核〔15:29 B〕
  - 〔已由 b-c4-3 取代，不上車〕B｜`wip/b-c4-2`（**第八班**；階段 C／C4 選單切換，主持裁示 A 與三點：`/static/sidebar.js` 前置 `window.MOTRIX_MENU`（與使用者無關的宣告：L1＋已載入模組、pageModules；不含任何資料庫字串，附題＋反向控制）；session 後打 `/api/platform/menu` 套角色版面＋自訂模組（`data-menu-state`、序號、讀失敗明說）；hide 不是權限；`custom-modules-nav.js` 與寫死的選單清單／MODULE_PAGES 移除；**7 項模組頁選單搬回模組 module.json**（主持核准改他人模組：crm 1.0.6、subcontract 1.0.5、payroll 1.0.3、daily_tasks 1.0.3、netplan 1.0.4——**版號與 c-probes、h-probes 交會，列車取號**；已通知 C）；`check_l1_pages` 守門；C3 對等題退場→`test_menu`；凍結 36 檔改讀宣告；取代本機 wip/b-c4（推過備份、未登記）：rebase 到 origin 896e7761）｜dd20cc5d｜非 e2e（tests/platform＋凍結靜態題＋6 模組 tests，-n 4）rebase 後 2 紅已修、受影響題 91 過；e2e：rebase 前全部 e2e（-n 2 -rf）454 過／3 紅（皆 C4 造成、已修），rebase 後凍結清單＋修過的三檔＋選單 e2e 94 過；core-only 反向控制（727b32cb）非預期紅 1 已修，並在 core-only 樹驗「dev-crm 放回 menu_l1 ⇒ 兩題紅」｜**動 main.py**（StaticFiles 前加 /static/sidebar.js 路由；與 h-fonts 同檔、不同段）、**前端全頁**（sidebar.js 每頁載入）；CORE 1.35 暫用（c-tax-calc-2／c-m01-sink2-3 也暫用 1.35／1.36，列車 core_bump 取號）；C 的 arap（cashier 選單）排在本包之後〔14:35 B〕
  - B｜`wip/b-m08-attr`（主持轉派：A 在 M03 反向控制查到的 analytics 既有問題——業績歸屬題不帶 client、`_compute_achievement` 無條件查 users ⇒ 單獨跑紅；改為名字⇒帳號對照可由呼叫端給（沒給才查，產品呼叫端不變），題改給空對照＋新增 id 比對一題；analytics 1.0.2）｜52178979｜單獨跑正對照：修後兩題 2 過、修前 origin 3e017154 同題 1 紅；modules/analytics/tests＋tests/platform（-n 4，非 e2e）1257 過＋CHANGELOG 守門提交後過｜不動 fixture／main｜analytics 版號若與他包交會 ⇒ 列車取號〔14:47 B〕
  - B｜`wip/b-modtest-env`（主持派工：modtest worker 上限可用環境變數覆寫 `MOTRIX_FULL_MAX_WORKERS`／`MOTRIX_PARTIAL_MAX_WORKERS`，預設 4／2 不變；不合法不採用並印出；PLAYBOOK §C-13 補述，含「--full 的 e2e 段也吃全量上限 ⇒ 全速時另給 --e2e-workers 2」）｜fb3c687f｜test_env_and_load_guards 新 9 題、突變 2 紅；tests/platform（-n 4）1085 過｜不動 fixture／main；快轉追加 MOTRIX_E2E_MAX_WORKERS（預設 2，--full 的 e2e 段讀它，主持裁示），tests/platform 1086 過〔14:56 B〕〔15:08 B 更新 HEAD〕〔15:58 B：快轉 MT-O1（差異題選到 e2e 也套 E2E 上限），1087 過〕
  - B｜`wip/b-o5-s1`（O5-S1，INVESTIGATION-D-O5：e2e /fonts/* 換成 648 bytes 替身（E2E_CONTEXT_HOOKS）；`real_fonts` 標記給量版面的 8 檔；登入後 `wait_logged_in` 等應用就緒不等 load；golden 案件頁不記 Referer 是 index 的請求（替身讓既有時序浮現））｜4e6d97d3｜全部 e2e（-n 2 -rf）457 過／1 紅已修（golden）、14:36（前次 16:07）；rebase 後相關 e2e 33 過；tests/platform 1074＋2 已修；突變 2 紅｜**動 fixture 層（conftest、pytest.ini 標記）⇒ 排車頭**〔16:01 B〕
  - 〔已由 b-o5-s2-2 取代，不上車〕B｜`wip/b-o5-s2`（O5-S2：e2e 逾時時失敗報告附「未完成的請求」（conftest 記帳 hook＋makereport）；**疊在 b-o5-s1 上、排在它後面**）｜c7940387｜tests/platform 1078 過；全部 e2e（-n 2）458 過／1 紅（jv7 見下）；突變 2 紅｜**動 fixture 層 ⇒ 排車頭**〔16:31 B〕
  - A｜`wip/a-attachments`（IP-21 `attachments.for_document`，主持裁示 M06-b；步驟表 plans/ATTACHMENTS-PLAN.md）｜afcfb513｜tests/platform＋所有模組題＋傳票／附件／上傳相關 151 檔：非 e2e 3247 過、e2e 189 過（test_map 過期已重產）；§B-11 拿掉 subcontract：3057＋222 過，紅＝允許 5 題＋附件範圍 4 題（已改依 M04 在不在）＋`modules/analytics/tests/test_reports_dispatch_connector` 2 題（**既有**，驗 M04 在時，與本包無關，交 M08 擁有者）｜突變 8/8 紅（缺席靜默、不說缺席、壞 JSON 吞掉、殘留直讀、M04 沒宣告、端點不回、畫面不顯示、提供者重疊）｜L1 新增 2 名稱（CORE 暫取 1.37）；**動 C 的 subcontract**（attachments.py、ModuleSpec 一列、1.0.6）；M05 `routers/invoice_vouchers.py` 加提供者；M01 新 helper case_attachments；M06 voucher_attachments／vouchers.py／傳票頁；fixture 層／main：無｜登記 2026-09-26 17:16 A
  - A｜`wip/a-analytics-dispatch`（主持派工：analytics 派工連接器「提供者在」2 題依 M04 在不在）｜ef3b9f60｜M04 在：4 過；拿掉 subcontract：2 過 2 略過；反向確認（拿掉略過標記）⇒ 2 紅｜只動 B 的 analytics 測試檔；產品碼／fixture／main：無｜登記 2026-09-26 17:18 A
  - B｜`wip/b-o5-s2-2`（取代 b-o5-s2 c7940387：D 稽核 S2-S1＋O5S2-O1——失敗訊息遮蔽 query 值、Bearer、token、pt；O5S2-O2 查明；**疊在 b-o5-s1 上**）｜fd5af159｜全部 e2e（-n 2）460 過；tests/platform 1086 過；突變 2 紅＋反向控制（真 Playwright 失敗不外洩）｜**動 fixture 層 ⇒ 排車頭**〔17:26 B〕
  - B｜`wip/b-o9`（O9：jv7 `_opened` 改等畫面終點，並注入延後 .json() 讓偶發變必然；e2e 關 context 加死線 `MOTRIX_E2E_TEARDOWN_LIMIT`（預設 60s）超時說明原因＋未完成請求＋堆疊後結束 worker；**疊在 b-o5-s2-2 上**）｜79b89eef｜全部 e2e（-n 2）459 過、tests/platform 1080 過（rebase 前）；rebase 後相關 46 過；突變 2 紅｜**動 fixture 層 ⇒ 排車頭**〔17:31 B〕
  - B｜`wip/b-modtest-durations`（IMPROVEMENT-REPORT §4-1：modtest --full 記最慢 30 題（題名、秒數、階段、段別）進 full_results；預設開、--no-durations 關；**疊在 b-modtest-env 上**）｜5cbcd9b9｜新 3 題、突變 2 紅、對真 xdist 輸出驗過；tests/platform 1090 過｜不動 fixture／main〔17:38 B〕
- **全量名額排隊**（更新 2026-09-26 02:43）：§G3 生效後，新的全量改由列車統一跑。仍在跑、而且依規定跑完就直接合回的有：B 的 C1（合回閘門約 02:52）、C 的第二批全量。A 的 a-bonus 走合回閘門，不經過測試鎖。⚠ A 有一支孤兒 pytest（pid 53300），停不掉，已請使用者處理。**第一班列車預計約 03:15 發車**，要等月台上至少有 3 包（目前只有 x-r-fix 1 包）。
- **未結案的偶發失敗**（依〈偶發失敗先當產品競態〉，不以「單獨跑是綠的」結案；下次出現時第一件事是抓 dump，`faulthandler_timeout`／py-spy）：
  - O9（B，16:31，b-o5-s2 全部 e2e）：`test_e2e_voucher_summary::test_jv7_an_edited_summary_survives_a_reload` 紅 1 次「摘要欄在 DOM 裡而看不見」（L332），單跑 3 次、全檔 -n 2 皆過。**成因（讀碼）**：`_opened` 等的是 `GET /api/vouchers/{id}` 的 response（標頭到就成立）＋一次 nextTick，而頁面還要 `r.json()` 之後才設 editing ⇒ 可見性檢查可能早於 x-show 生效（〈e2e 等待的終點〉：等終點狀態不等某一趟請求）。字型替身（O5-S1）讓頁面變快，可能讓它更常出現。建議：`_opened` 後改等摘要欄可見（同 `_open_editor` 的條件）。擁有者：傳票（M06 線），B 未修。另：route 攔下不回應＋該題失敗 ⇒ teardown 永遠卡住（origin 同樣重現），寫 e2e 用 route 擋請求時注意〔17:31 B：已修 wip/b-o9（主持派 B），見月台列；本體（test 內 evaluate 等永不回應的 promise）另無上限，未處理〕
  - O1：`test_archive_isolation` 在滿載的全量中紅 1 題（A2，23:0x；題名沒有留下），單檔與循序跑 670 題都是綠的。
    - ✅ **已查明（B，856e5497）**：原先歸因於「滿載」是錯的，實際是目錄狀態造成的。os.makedirs 遞迴建上層目錄時，呼叫到的是被 BK19 換掉的記錄版 makedirs；在全新的 worktree 裡 uploads 還不存在，所以多記了一筆上層目錄。開發樹裡 uploads 早就存在，因此只有全新 worktree 的全量會紅。修法：比對改成純函式，已登記寫入的上層目錄不算新缺口，並附 3 題反向控制。**這印證了「偶發失敗先當成真問題查」：它根本不是偶發。**
  - O2：`test_bonus_case_multi_approver_tier` 之後卡住十幾分鐘（A2，約 22:50，滿載時；沒有 dump），停在 multi_approver 之後、vouchers 的第一題；連跑三檔、開 faulthandler 都無法重現。
  - O5：`test_e2e_login_enter_submits::test_enter_logs_in[after_failed_attempt-webauthn]` 在 C1 全量（f3b59691）e2e 裡紅 1 次：等待導向 /index.html，8 秒逾時。單獨重跑 3 次都綠。這一輪含 core.pages（/pages 路由改由伺服器提供），要查它和登入導向是否有時序關係；下次出現時先抓頁面的網路紀錄與 dump。〔D 排除法（f6b25468）：與 /pages 無關。等待點 /index.html 由 StaticFiles 提供；這個情境要算兩次密碼雜湊。下次出現時抓兩次 login 請求的耗時〕
  - O3／O4：`test_e2e_hard_cap` 的單程序題、`test_e2e_shared_fixtures` 的 login_as（B 負責修，已知原因＝滿載時的時序）。
  - O6：`test_pytest_guards_2026_09_21::test_g2_a_corrupt_lock_file_lets_everyone_through` 在第二班列車全量（5ddd9f44）紅 1 次：子 pytest 收集 tests/ 時 `_hardcap_probe_*` 目錄被 `test_e2e_hard_cap` 同時刪掉（FileNotFoundError）。單獨重跑綠。是測試之間共用目錄的競態，不是列車造成（B）。
  - O7：`modules/tender_radar/tests/test_tender_p9_layout_e2e_2026_09_26.py::test_layout_editor_role_override_and_restore` 在第五班列車全量 e2e 段（f5e7eeee，-n 4、滿載）紅 1 次：④公司預設發布第 2 版（地點打開）後 `sales.reload()`，表頭仍是第 1 版（沒有 location）。單檔循序重跑 3 次都綠。本班沒有一包碰 tender_radar／layout（sidebar.js 只在 MODULE_PAGES 加 dev-crm 一行）。疑點：重新載入時讀到舊版面（快取或發布尚未提交就回應）⇒ 先當產品競態查，下次出現時抓 /api/layout 回應與發布請求的時序（H）
  - O8：`modules/tender_radar/tests/test_tender_p9_layout_e2e_2026_09_26.py::test_publish_problems_are_marked_on_the_item_and_unregistered_points_are_refused` 在 A 的 M03 反向控制 e2e 段（b2e5f7e4，拿掉 modules/supply，-n 2）紅 1 次，單獨重跑綠；沒有 dump（記錄時間 2026-09-26 13:3x，A）。
- 稽核：每一項完成、合回之後，照 CORE-SPEC §9d 的分配交叉稽核（A 審 C、B 審 A、C 審 B 與主持）；新的工作線也照這個輪替。
- 視窗上下文：各視窗會自動摘要，不會因為太長而中斷。若某個視窗出現重複、迷失或品質下降，就不再派工給它，改用新的子代理（獨立 worktree）接手；派工內容一律寫成自足的說明，並引用本檔與 PLAYBOOK，不依賴對話記憶。
- 巡視：主持每 30 分鐘（每小時 :13、:43）自動巡視一次；排程 7 天後自動失效，到期前重新建立，內容包括看各視窗狀態、看 git log、派出下一項、更新 §4／§5 與桌面交接檔。

## 6. 進度紀錄（最新在上）

- 2026-09-26 17:46 C：wip/c-approval-2 49dcb781 上月台（/detail 改 `approval.detail`）；ROADMAP P8 記「自訂模組單據轉簽本輪不加」（7e739035）。M01 詳情端點剩下的直讀只有 M01 自己的表（quotations、completion_notes、case_extra_expenses、case_change_requests）。
- 2026-09-26 17:34 D：a-attachments afcfb513 **AT-M1 待主持裁示**（列出／預覽／帶入只看傳票模組權限、不看原單據可見性；IP-21 契約無 user 參數，建議現在加）；M04 不在的 notice／400 突變紅、已帶入附件 D 探針不受影響、§B-11 5 紅皆允許；建議 AT-S1（M06-PLAN §5 b 列已達成、守門檔尚未存在）、AT-S2（case_update 壞 JSON 吞成空無題）。a-analytics-dispatch ef3b9f60 抽查通過（skip 是真的需要 M04、原因寫明、M04 在時照跑）。
- 2026-09-26 17:33 主持：使用者表單「全量開發完成才跑」⇒ 第十班起列車不跑全量（PLAYBOOK §G4 第 4 步更正、CORE-SPEC 裁示表）；第九班已在跑的全量照跑完。裁示 B：①產生檔提案採 §7 合一方案（分支不動產生檔、modtest 現場產生、「是否最新」三題只在列車跑）交 B 實作；②e2e 每題加死線（永不回應的 promise 會等到 renderer crash 50～400 秒）交 B。交互紅紀錄：第四班 4、第五班 2、第六班 5、第七班 2、第八班 1（全量抓到、分支沒抓到）。
- 2026-09-26 17:23 C：wip/c-approval 299aed61 上月台（§3-7；疊在 c-m01-rec-2）。出貨單（M03）一併改成提供者（原派工未列 M03；origin 已搬 modules/supply，列車 rebase 時跟著搬）。自訂模組單據維持只有佇列、不支援轉簽（原本就不支援）。簽核佇列詳情端點 `/api/approval-queue/detail` 仍直讀各單據表，未在本包範圍。
- 2026-09-26 17:17 A：開工 wip/a-analytics-dispatch（主持派工）：**會改 B 的 `modules/analytics/tests/test_reports_dispatch_connector_2026_09_26.py`**，兩題「提供者在」改成依 M04 在不在（§B-11）；只動測試，analytics 版號由列車取號。
- 2026-09-26 17:16 A：wip/a-attachments 上月台（afcfb513）。範圍外：analytics 派工連接器 2 題在 M04 不在時紅（既有）。
- 2026-09-26 16:58 D：**CS-M1 關閉（88192c07，R1 重跑紅）**；c-m01-rec-2 a56f33e4 通過（必修 0，突變 5/5 紅）；b-o5-s2 c7940387 通過（必修 0）：標頭不印，但 URL 含 query（?pt= 短效簽章、?q= 搜尋字）照印 ⇒ 建議 S2-S1 遮值；觀察 Playwright call log 自己印 Authorization。
- 2026-09-26 16:33 C：**M01-PLAN §3-7 approval 開工宣告**（wip/c-approval，疊在 c-m01-rec-2 a56f33e4）。轉簽改成 `approval.reassign`（單據擁有者各自提供讀寫）、待我簽核與角標改成各模組提供 `approval.queue_items`，M01 只彙整。會動：M04 `modules/subcontract/api/contractor_vouchers.py`＋module.json；M05 `modules/arap/api/invoice_vouchers.py`、`payment_requests.py`＋module.json；**A 的 M03** `routers/shipping_notes.py`（origin 已搬到 `modules/supply/api/shipping_notes.py`，列車 rebase 時跟著搬）；**M06** `routers/vouchers.py`（A 的 M06 搬遷會同檔）；M07 `modules/payroll`（bonus_awards／bonus_case_awards 兩類待簽）；M01 `routers/quotations.py`、`routers/completion_notes.py`、`frontend/pages/approval-queue.html`；L1 新增 `helpers/approval_queue.py`；INTEGRATION-POINTS（新 IP，列車定號）。custom 模組引擎已是 `approval.queue_items` 提供者，不改。不動 sidebar、tiered_approval。
- 2026-09-26 16:32 主持：第九班組車中（Sonnet 列車長）；D 關閉 CS-S1、T8-O1、b-o5-s1、MT-O1；C 做 approval（c-approval），A 做 attachments，B 做 O9＋產生檔提案。優化紀錄開在 IMPROVEMENT-REPORT §4-1（產生檔衝突、全量每題耗時）。
- 2026-09-26 16:30 D：c-m01-s3-2 dbd07633 複核：**CS-S1 關閉**；CS-M1 靜態掃描通過（R2／R3 紅），但執行期新題 `test_runtime_refuses_system_from_an_l2_module` 不帶 client 夾具⇒單跑紅（no such table），**CS-M1 未關**，待加夾具後重跑 R1。
- 2026-09-26 16:27 D：h-roleguard d10fc8e9 抽查通過，**T8-O1 關閉**：24 過、突變 RG1 紅；新 AST 64 筆 ⊇ 舊正則的真實比對；觀察 RG-O1（SQL 內角色字面值 9 檔無人驗）。
- 2026-09-26 16:23 D：b-o5-s1 4e6d97d3 通過（必修 0）：golden Referer 過濾**未變寬**（G1 案件頁多一支 GET⇒紅；首頁 load 後的 GET 在 origin 真字型下也抓不到＝本來就不在範圍；G4 拿掉過濾⇒API 清單紅 2/3）；替身兩突變紅。MT-O1 關閉（fb3c687f）。列車 07547758／cf7c3bb3 事後抽查通過，觀察 T8-O1。
- 2026-09-26 16:16 A：開工 wip/a-attachments（`attachments.for_document`，裁示 M06-b；步驟表 docs/platform/plans/ATTACHMENTS-PLAN.md）。**會改到 C 的模組**：`modules/subcontract/`（新增 attachments.py、ModuleSpec.providers 加一列）；M05 未合回 ⇒ `routers/invoice_vouchers.py` 旁以 registry.provide 登記（arap 搬遷時改宣告）；M01 新增 `helpers/case_attachments.py`。M06-PLAN 補 §4 JV 清單、§5 到期守門。
- 2026-09-26 16:14 第八班列車長：**第八班合回 93fac177**（train/0926-1441，基底 841fcae1 → rebase 到 f63e2f6b，帶進的只有文件）。上車 8 包全數合回：h-fonts（1，略過重產 7728934b）、a-m03（7；sidebar.js MODULE_PAGES 與 ROADMAP 第 9 項手解衝突）、c-tax-calc-2（4，bf133a9e 內的產生檔以列車版為準）、c-m01-sink2-3（1）、c-m07-s12b（2）、c-probes（4＋主持後加的 c6f8ed0e 文件一列）、h-smoke-probes（2，略過重產 ca02ce66、ba29aa44）、h-u15-2（4，略過重產 db56f2ff、134328be）；git cherry 無已合回的重複；無下車。取號：core_bump（onto 1.34）⇒ c-tax-calc-2＝**CORE 1.35**、c-m01-sink2-3＝**1.36**（與暫用號相同）；IP：origin 最大 IP-17 ⇒ a-m03 **IP-18 shipping.list_for_case、IP-19 stock.serial、IP-20 inventory.paid_batches**（與暫定號相同）；模組版號：**analytics 1.0.2**（c-tax-calc-2 暫用 1.0.1 與 origin 撞號，列車往後排）、crm 1.0.6、subcontract 1.0.5、payroll 1.0.3、supply 新模組。重產三份產生檔單獨一個 commit（e541d1bb），--check 一致；D 的 O-1（a-m03 test_map 過期）重產後 test_test_map_json_is_current 綠。交會／列車修正 3 個：①l1_to_l2 基線刪掉已消失的 3 條 L1 → M01 邊（T 與 sink2 各自切斷、S-7 基線題）；②h-smoke-probes 的 test_smoke_core_has_no_paths_of_migrated_modules 正對照綁在 L2 模組（core-only 非預期紅）⇒ 前綴改由 modules.json 已搬遷群組＋樹上 module.json 取得（sparse 無模組樹 20 過、反向控制報 payroll 前綴）；③h-u15-2 的 mail_settings `role in (ov.get("roles")…)` 被 test_no_unknown_role_strings 當成角色字串（全量唯一紅）⇒ 拆出變數、行為不變；②③屬包內問題、非交會，列車上修掉未下車，請 D 抽查。全量（97d767c0，-n 4／e2e -n 2、低優先權）：非 e2e 4849 過 **1 紅**（③，修後該題與相關 32 題過）；e2e 457 過 0 紅（O5 未出現）。core-only：97d767c0 非預期紅 1（②）；修後 32c6f9ee ok：1081 過、紅 5＝§B-11 允許、已知紅清單空、無新增（不需核對 Ruling-By）。supply 真刪（32c6f9ee sparse，MSYS_NO_PATHCONV、ls 確認 supply 不在；tests/platform＋提到 supply／其前綴／stock_items 的 34 檔、--continue-on-collection-errors）：非 e2e -n 4 1390 過 5 紅＝允許題、收集無錯；e2e -n 2 15 過 1 skip。冒煙：test_final_drill_tool＋test_product_drill_probes 23 過；完整產品 smoke_plan 57 項、UNDECLARED／UNREGISTERED 0（8 個模組都有 probes，supply 5 支）。
- 2026-09-26 16:07 D：c-m01-s3-2 d93a792a（`AUDIT-D-C-m01-s3.md`）**必修 CS-M1**：SYSTEM 只准 L1 的掃描器漏 alias／dotted／star／getattr／_SystemCaller 6 種寫法；可見性、None 拒絕、M01 不在、指紋突變 5/5 紅；基準 1137＋274 過（紅 1＝sidebar 已知）。
- 2026-09-26 16:00 C：**M01-PLAN §3-6 case.recognition 開工宣告**（wip/c-m01-rec，疊在 c-m01-s3-2）。會動：**B 的 M08** `modules/analytics/api/reports.py`（recognition.* 改取 M01 provider、M01 不在時明說）、`helpers/recognition.py`（M01）、INTEGRATION-POINTS（新 IP，列車定號）。不動 sidebar。
- 2026-09-26 15:58 D：**M5-M1／M5-M2／M5-S1 關閉（c5484962）、IP-M1 關閉（9623f1be）**：MB8、S1、P5 重跑皆紅；e2e 連跑 5 次全綠。交會：a-approval-parse 的 voucher.py／tiered_approval.py 含「淘汰」未登記 ⇒ 兩包都合回時反掃必紅，後進的補登記。
- 2026-09-26 15:58 主持：使用者表單定本輪範圍——授權機制不做、M01 已知例外可接受（D7 報告列出＋到期守門）、不安排人工驗收（CORE-SPEC 裁示表）。預估完工 9/29（±1 天）。
- 2026-09-26 15:51 D：b-m08-attr 52178979、b-modtest-env bf4abacb 抽查（`AUDIT-D-B-attr-modtestenv.md`）皆通過、必修 0；突變 4/4 紅；觀察 MT-O1（差異題的 e2e 無獨立上限）。
- 2026-09-26 15:47 D：c-ip14-paid 6c8406c5（`AUDIT-D-C-ip14-paid.md`）**必修 IP-M1**：test_cashier_and_t100_without_m04 只拿掉 contractor_voucher.public，T100 資料已改走 paid_between ⇒ 拿掉 None 防護（真 M04 不在會 500）照綠；其餘突變 4/4 紅、基準 97 過。
- 2026-09-26 15:38 D：c-m05b b17e5296（`AUDIT-D-C-M05-move.md`）**必修 2**：M5-M1 薄殼「下一個主版號刪除」無觸發（CORE 升 2.0 守門照綠）；M5-M2 `test_e2e_arap_absent_notices` 不關 context＋route.fetch ⇒ 同 worker 下一題偶發紅（未突變 1/3，基準 golden 紅同因）。§B-11 通過（5 紅皆允許、1486 收集無錯、端點 404）；突變 7/7 紅。
