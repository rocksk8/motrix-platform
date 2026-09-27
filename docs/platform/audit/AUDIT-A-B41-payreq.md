# 稽核：B41 請款流程＋模組 migration（wip/b-payreq 5d30ede6）（A，2026-09-28 01:37）

> 只讀碼，沒有跑任何測試，也沒有改 B41。範圍：`git diff 6169f9cf...5d30ede6`（38 檔，+1799／−37）。行號以 5d30ede6 為準。
> 對照讀過：CORE-SPEC「請款流程（下一版）」裁示列、INTEGRATION-POINTS IP-100、`db.py::init_db`（run_all 呼叫處）、
> `helpers/module_switches.py::read_disabled_list`、`core/paths.py::modules_disabled_cache`、
> 既有的 `arap/api/cashier.py::_payable_queue`（IP-14 的前例）。

## 0. 結論

- **必修 1、建議 5、觀察 4。**
- ①②⑤⑦ 成立：
  - 載入才登記：停用、未授權的模組走不到 register
  - 未完成就不記版號，該模組後面的版號也不跑
  - 依庫分開記錄
  - module_startup 與 main.py 逐字等價
  - 挑案件：先過濾可見再取筆數，LIKE 有跳脫
  - case 0001 的未完成原因
- ④ 的 §G5 #14 兩個方向都有題，而且用一般 sales 測，放行的確實是「本人」這條規則。
- ⑥ EM1 凍結訊息的改動成立：原句保留在註解，依據是使用者裁示②。
- 缺口在 ③：**付款日仍可由填寫人自己設定或清除**（AB-M1）。IP-100 之後，「付款日空白」就是出納待付款的判準，這條舊權限因此從「報表歸月」變成「能讓一筆請款繞過出納，或讓已付的請款重新出現在待付款」。

## 1. 逐項（主持重點）

| # | 項目 | 讀碼結果 | 判定 |
|---|---|---|---|
| ① | ModuleSpec.migrations／登記時機 | `registry.py` 以串列宣告（重複鍵不會被 dict 字面值蓋掉）；`loader.load_all` 在授權檢查與停用檢查**之後**、import 模組之後才 `check_migrations`＋`register`（loader.py:146-148）⇒ 停用、未授權、不在包內的模組都不登記；版號不對 ⇒ 整個模組載入失敗 | 成立；觀察 AB-O1 |
| ① | 回傳值慣例 | `run_all`（migrations.py:49-80）：`res is not None` ⇒ 記原因、ERROR、`break`（該模組後面的版號不跑）、繼續下一個模組、不丟例外；非字串的回傳值當成寫錯，同樣不記 | 成立 |
| ① | `incomplete(db_path)` | 以 `PRAGMA database_list` 取主庫路徑，`normcase(abspath)` 當鍵；主庫、demo 庫各自一份；None＝沒對這個庫跑過。**例外路徑**：`_INCOMPLETE[key] = {}` 在執行前就設好（:56），migration 丟例外時這個庫留下的是 `{}`（「全部完成」的形狀） | 見 AB-S4 |
| ① | 不留半套 | 由各支 migration 自己負責（先檢查、後動手）。case 0001 是單一 `ALTER TABLE`，表不在就先 return、不動手 | 成立 |
| ② | module_startup 與 main.py | main.py 原段的三個名字 `license_core`／`module_registry`／`module_loader`，就是 `helpers.licensing`／`core.registry`／`core.loader`（main.py:28、30），參數逐一相同。`read_disabled_list(None)` ⇒ 讀 `db.DB_PATH`，與原本一樣；快取在主庫旁（`modules_disabled_cache`）；主庫不存在時不建空檔 | 成立 |
| ③ | IP-100 缺席 | 沒有提供者 ⇒ 200 `{available:false, notice, items:[], canPay:false}`；`POST …/pay` ⇒ 404「對應的模組未安裝」；有反向控制題 | 成立 |
| ③ | 付款日寫回 | `mark_paid` 經提供者寫回 `paid_date`；日期格式與有效性由出納端驗（cashier.py:112-117）；月支出現金口徑改用付款日 | 成立，但見 AB-M1、AB-S1 |
| ④ | 補發票／發票號碼權限 | 上傳：`_guard_case`（案件可見）→ 已核准只准 invoice 類 → `_can_modify or cashier`（:695）；發票號碼走 PATCH …/dates，同一條（:400）。題（test_payreq:93、107）：填寫人是一般 sales ⇒ 放行；看得到案件、不是填寫人的 sales ⇒ 403、內容不變、沒有稽核紀錄 | 成立；「或出納」那一條放行沒有題（AB-S5） |
| ④ | 待付款帶 customerName／projectName | 不看案件可見，對 admin／cashier／finance 全列（cashier.py:83-99；payables.py:53-58）。前例：既有的 IP-14 `payable-queue` 同樣帶 `customer_name`／`project_name`（cashier.py:134 起），也不看案件可見 | 與前例一致；要使用者裁示（AB-S2） |
| ⑤ | 挑案件 | `like_literal` 跳脫 `\` `%` `_`，三個欄位都帶 `ESCAPE '\'`（:337）；游標逐列 `case_owner_readable`，湊滿 30 就停（先過濾、後取量）；有題（:184、:201） | 成立；效能見 AB-O3 |
| ⑥ | EM1 凍結訊息被改 | `_UNTOUCHED` 的期望字串改成新訊息，原句保留在註解，依據是 CORE-SPEC 請款流程裁示②「核准後仍可補發票」。訊息內容與行為一致（其他類照舊上鎖、刪除照舊上鎖） | 成立（是使用者裁示帶來的行為變更，不是順手改字） |
| ⑦ | case 0001 未完成原因 | 表不在 ⇒ 回「case_extra_expenses 表不存在（應由 V9 v75 建立），invoice_no 這次不補、下次啟動再試」；有題（test_payreq:135）驗版號不前進、之後補上 | 成立；觀察 AB-O2 |

## 2. 必修

**AB-M1（必修）　填寫人可以自己設定或清除付款日 ⇒ 繞過出納，或讓已付的請款重回待付款**

- 證據：
  - `PATCH /api/quotations/{no}/extra-expenses/{id}/dates` 接受 `paidDate`，`''` 代表清除（case_extra_expenses.py:387-388）
  - 權限是 `_can_modify(row, user) or cashier`（:400），而 `_can_modify` 包含填寫人本人（:172-176）；任何狀態都可以登（docstring：AC2 hichan-0a 裁示）
- 新語意：
  - IP-100 的待付款判準是 `status='已核准' AND paid_date=''`（payables.py:57）
  - 月支出現金口徑用 `paid_date`（recognition.py，IP-95）
  - 出納端登錄付款也是寫同一個欄位（payables.py:75）
- 後果（讀碼推演）：
  1. **繞過出納**：填寫人核准後自己 PATCH `paidDate` ⇒ 這筆從出納待付款消失，出納從來沒看到；現金口徑還會記在填寫人選的那個月。
  2. **重複付款**：出納已經登錄付款之後，填寫人 PATCH `paidDate: ""` ⇒ 這筆重新出現在待付款 ⇒ 可能被付第二次。稽核紀錄只有 `extra_expense.dates …（清除）`，出納畫面上看不出來它付過。
- AC2 當初放行本人的理由是「兩個日期都不影響金額，只決定報表歸哪個月」，而 IP-100 之後付款日還決定「要不要付錢」，前提已經不成立。
- 修法（建議）：
  - `paidDate` 改為只有出納或 admin 能設（本人只能設 `invoiceDate`／`invoiceNo`）
  - 已有付款日的，清除或改日期限 admin，並寫專用稽核動作；或者一律拒絕清除，要更正走變更申請
  - 補題兩個方向：填寫人（一般 sales）設 `paidDate` ⇒ 403、待付款清單不變；出納設 ⇒ 200
  - 反向控制：admin 清除已付的付款日要留專用稽核紀錄

## 3. 建議

- **AB-S1　`mark_paid` 先查再改，不是原子操作**
  - 證據：payables.py:68-77 先 SELECT 檢查 `paid_date` 為空，再 `UPDATE … WHERE id=?`
  - 情境：兩位出納幾乎同時按「登錄付款」，兩個請求都通過檢查 ⇒ 後者蓋掉前者的付款日，稽核留下兩筆「已付款」
  - 建議：`UPDATE … WHERE id=? AND status='已核准' AND COALESCE(paid_date,'')=''`，`rowcount==0` ⇒ 重新讀一次，決定回 404 還是 409
- **AB-S2　待付款清單的案件資訊（B 自己提的 d）**
  - 事實：admin、cashier 與 **finance** 看得到每一筆已核准請款的單號、客戶、專案、事由、金額、請款人，不管他看不看得到那個案件
  - 前例：IP-14 的 payable-queue 同樣帶客戶與專案名稱，所以這不是新的洩漏類型；但 finance 原本對案件額外支出的內容（事由、請款人）沒有這個入口
  - 建議：由使用者裁示。選項：
    - (a) 維持
    - (b) 看不到案件的人只看單號＋金額＋請款人
    - (c) finance 不看事由
- **AB-S3　migration 未完成時模組照常載入**
  - 事實：`run_all` 未完成只記 ERROR，模組狀態仍是 loaded，路由也照常掛上
  - 後果：程式讀不存在的欄位（例如 `invoice_no`）⇒ 500，使用者看到的是「壞掉」而不是明說
  - 建議：`init_db` 之後依 `incomplete(DB_PATH)` 把該模組狀態改成 failed，原因用 migration 回傳的那句 ⇒ 模組管理頁與缺席明說（P-FE-03）接手
- **AB-S4　`incomplete` 在例外路徑回「全部完成」的形狀**
  - 證據：migrations.py:56 在執行前就設 `_INCOMPLETE[key] = {}`；migration 丟例外時，這個庫的紀錄停在 `{}`
  - 現況：`init_db` 不吞例外（db.py:761），H12 的 migrate_like_startup 會因例外 exit ≠ 0，所以目前沒有假綠
  - 風險：介面契約寫「空 dict＝全部完成」，將來有呼叫端 catch 例外再查 `incomplete`，就會得到假的通過
  - 建議：丟例外時在 `todo` 記 `(v, "例外：…")` 再 re-raise；補一題
- **AB-S5　「或出納」那一條放行沒有題**：已核准後，看得到案件、不是填寫人的出納補發票或發票號碼 ⇒ 應該 201／200。目前只有本人放行、非本人非出納 403 兩題（§G5 #14：分支的每個放行條件各自要有題）。

## 4. 觀察

- **AB-O1**：`core.migrations._REGISTRY` 是行程層級的全域變數、沒有清除。同一個行程呼叫 `load_all` 兩次、停用清單又不同時（工具、測試），第一次登記的 migration 會留著 ⇒ 被停用的模組在第二次的 `run_all` 照跑。正式啟動每個行程只載一次，不受影響；工具若在同一個行程先後處理兩個庫，要注意。
- **AB-O2**：case 0001「表不在」這一支實務上走不到（V9 v75 一定建）；題用 monkeypatch 驗過行為，可接受。
- **AB-O3**：挑案件對 `quotations` 做全表掃描，並逐列呼叫 `case_owner_readable`，看得到的案件少時要掃到最後。前端若每按一個鍵就查一次，案件數大時會慢。建議前端 debounce（目前的頁面有沒有做，未查）。
- **AB-O4**：`COUNTED_EXTRA_STATUSES` 改變了月支出的口徑（草稿與已駁回不再計入）。這是使用者裁示，兩種口徑同一處決定、有題（test_payreq:249）。上線後，同一個月的報表數字會與舊版不同，版本紀錄應寫明（版本紀錄內容未查）。

## 5. 給 D 的建議驗證點（這一輪沒跑）

1. AB-M1：一般 sales 填寫人，核准後 PATCH `paidDate` ⇒ 目前 200，並從 `/api/cashier/pending-payables` 消失；出納付款後 PATCH `paidDate:""` ⇒ 重新出現。
2. AB-S1：兩個執行緒同時 `POST …/pay` 同一筆 ⇒ 看 `paid_date` 與稽核筆數。
3. AB-S3：把 case 0001 暫時改成回原因，啟動後開額外支出頁 ⇒ 看是 500 還是明說。
