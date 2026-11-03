# 稽核：T73 業務開發案件指派成員／回覆期限／進度回報（hichan-3，2026-11-04）

> 對象：`origin/train/t73-int` 相對 `origin/platform` 的 4 個提交
> `9a2b0994d`（squash：wip/t73-dev-case-assignment-r1，21 檔）、`8922cf416`（取號 CORE 1.148→1.149）、`b878045f8`（重產）、`1120159de`（version_manifest）。
> 方法：**純唯讀**。只讀 `git show`／`git show origin/train/t73-int:<path>`，未 checkout、未跑 pytest、未起伺服器、未改任何程式或測試、未動分支。
> 唯一「執行」：`python -c "date.fromisoformat('20261201')"`（Python 3.11.15）驗證 S2。
> 行號＝`origin/train/t73-int` 上的檔案行號（`crm/api.py` 已另存比對）。
> 分級：**必修**（不修不能關）／**建議**／**觀察**。

## 結論

- **必修：0 項。**
- **建議：10 項**（S1～S10；其中 S4 需產品裁示，若「回覆期限」預期要催辦則升為必修）。
- 觀察：6 項。
- 權限核心（`OwnerRule(owner_id_col="assigned_to")`）正確；反向控制（取消指派、換人、停用、遷移跑兩次、回退）都沒找到會漏權或誤授權的路徑。主要缺口在「周邊」：通知生命週期、API 缺欄位語意、提醒、測試覆蓋。

## 一、權限核心（符合裁示，無問題）

證據：
- `crm/api.py:126-133` `DEV_CASE_ACCESS = OwnerRule(owner_id_col="assigned_to", creator_col="created_by", id_list_cols=("sales_persons","planners"), lenient_json=True)`；`helpers/row_access.py` 本提交未動（與 `origin/platform` 逐位元相同）。
- **`assigned_to=NULL` 不影響既有權限**：`row_access.py:119-122` owner 分支要 `oid is not None and oid == uid` 才命中，其餘 creator／id_list 分支照舊 OR；`filter_sql`（`row_access.py:146-148`）為 `assigned_to=?` 與其他項 OR，`NULL=x` 不為真、不吃掉其他項。
- **取消／換人後前任立刻失權**：可見性只看目前 `assigned_to` 單值（`UPDATE` 在 `api.py:632`），無快取、無歷史表。前任若同時在 `sales_persons`／`planners`／建立者，則依既有規則仍可見（符合預期）。
- **指派當下的對象檢查**（`api.py:622-630`）：`active=1` 才能指派（400）；非 admin 角色須有 `dev_crm`（400）。與 `_require_dev`（`api.py:107-112`）同一判準。
- **事後失去模組權限／停用**：`assigned_to` 仍掛著，但 `_require_dev` 對該人所有端點 403（含 `/progress`）。不會漏權；產生孤兒見 S7。
- **`users.id` 為 `AUTOINCREMENT`**（`db.py:531`）：硬刪使用者後 id 不會被新帳號沿用，不會有「新帳號繼承舊指派」的誤授權。
- **其他出口**：非測試程式中所有讀 `dev_cases` 並丟給 `row_access.visible("dev_case")` 的位置我逐一對過——`list/get/update/status/convert/logs/新增記錄/_DevLogPathAccess`（`SELECT *`）、`search.py:62`（`SELECT *`）、`item_reads.py:193`、`crm/api.py:887`、`analytics/dashboard.py:684,915` 皆含 `assigned_to` 或 `*`，**沒有漏網**。`archive.py:2282` 為 `SELECT *`，匯出自動帶新欄。
- `/progress` 刻意不走 row_access（`api.py:660-672`）：非 admin 且 `user.id != assigned_to` ⇒ 403；案件未指派（NULL）時非 admin 一律 403。符合註解與測試。

## 二、端點對照（`PATCH /assign`、`PATCH /progress`）

| 項目 | `/assign`（`api.py:603-655`） | `/progress`（`api.py:658-684`） |
|---|---|---|
| 權限 | `_require_dev` + `_is_admin`，否則 403 | `_require_dev`；非 admin 須為被指派人，否則 403 |
| 404 | 案件不存在／已軟刪 ✔ | 同 ✔（404 先於 403，與既有端點一致，見 O2） |
| 400 | 期限格式、對象不存在／停用、對象無模組 ✔ | 無（無長度驗證，見 S6） |
| 稽核 | `dev_case.assign`（`:638`）✔ | `dev_case.progress`（`:679`）✔（全文放 `target_label`，見 S6） |
| 通知 | 有被指派人才 `_notify` + 背景信 + `notify_module_activity`；取消只發活動通知 | 只有 `notify_module_activity` |

## 三、建議

**S1　`/assign` 缺欄位＝取消指派並清期限（API 陷阱）**
`DevCaseAssignIn`（`api.py:75-80`）兩欄皆 `Optional`，`UPDATE`（`:632`）無條件寫入 `(body.assigned_to, body.reply_deadline)`。送 `{}`、或鍵名打錯（如 `assigned_To`）⇒ 200 且案件被取消指派、期限清空，無任何提示。前端永遠兩欄都送所以 UI 不會踩到，但任何 API 呼叫端或腳本會。建議：用 `model_fields_set` 要求至少帶 `assignedTo` 鍵（缺則 422），並明定「取消指派時 `reply_deadline` 清不清」（現況：由呼叫端決定，可留下無人的期限）。

**S2　期限驗證與儲存不是同一個值**
`api.py:619` 用 `date.fromisoformat` 驗證，但 `:632` 存的是原字串。實測 Python 3.11.15：`date.fromisoformat('20261201')` 通過（3.11 起接受基本格式），於是 DB 會存 `20261201`，錯誤訊息卻寫「須為 YYYY-MM-DD」。前端是 `<input type=date>` 不會踩到，API 直打會。同時未擋過去日期（觀察，非必要）。建議：驗證後存 `d.isoformat()` 或加 `^\d{4}-\d{2}-\d{2}$` 檢查。

**S3　`dev_case_assigned` 通知沒有跟著案件生命週期**
`helpers/audit.py:218-231` `_NOTIF_SOURCE_CHECK` 只登記 `dev_case_stale`；`api.py:551` 核准刪除也只 `_purge_notifications(str(case_id), ['dev_case_stale'])`。案件軟刪除後，被指派人的「案件已指派給您」通知仍在，點進去是不存在的案件。有現成範例（stale）照抄兩行即可。

**S4　回覆期限只是顯示，沒有任何行為；被指派人不在停滯提醒收件人內（需產品裁示）**
- 全後端搜尋 `reply_deadline`：只有指派端點寫入、`_case_row` 回傳、前端顯示；沒有逾期檢查、沒有到期前提醒。
- `_check_dev_case_stale`（`api.py:1194+`）收件人 `usernames = sales_persons + planners`，兩者皆空才退回 `created_by`（`:1236-1238`），再加所有 admin。只被指派、不在名單的人永遠收不到「洽談中 30 天未更新」提醒；而 CHANGELOG 宣稱被指派人「與業務／企劃同等」。
- 若需求本意含催辦，這兩點應升為必修；若期限只是備忘，至少把被指派人加入停滯收件人。

**S5　換人／取消沒有通知前任；重存同一人會重複通知**
A→B 或取消時，A 立刻失去存取卻沒收到任何通知（`api.py:640-654` 只在 `assignee` 存在時通知新人）。反過來，對同一人只改期限再存一次，會再發一則站內通知＋一封 email（無變更偵測）。建議：比對舊值，換人通知前任、同人同期限不重發。

**S6　進度回報：單欄覆寫、無長度上限、全文塞稽核標籤**
- `progress_report` 單一欄位，管理員「補充」會蓋掉被指派人內容（測試 `test_progress_assignee_and_admin_can_write` 就是這樣寫的），舊內容只剩 `audit_log.target_label` 可追。換人時不清、也無「誰／何時」欄位，新被指派人看到的是前任文字。
- `DevCaseProgressIn.progress_report: str`（`:83-86`）無 `max_length`；全文寫進 `_audit` 的 `target_label`（`:679`）與 `notify_module_activity(detail=…)`。
- 與既有 `DevLogIn.content` 同樣無上限，所以算一致性問題而非新漏洞。建議：上限（如 4000 字）、稽核標籤放摘要、全文放 `detail`。

**S7　孤兒指派（停用／移除模組／硬刪使用者）**
- `assigned_to` 由 `ALTER TABLE … ADD COLUMN assigned_to INTEGER` 加入（`0002…py:16`），**沒有 FK**。`auth.py:1716` 的硬刪使用者保護是靠 FK 觸發 `IntegrityError` 回 409；`dev_cases.created_by` 有 FK 但 `assigned_to` 沒有，所以只被指派過的帳號現在可以被硬刪，留下懸空 id。`_case_row`（`api.py:286-288`）找不到人時顯示 **數字 id** 當姓名。
- 被指派人停用或被拿掉 `dev_crm` 後案件仍掛名，且（S4）無人提醒。
- 建議：硬刪前檢查 `dev_cases.assigned_to`（或在使用者管理的關聯檢查清單補上）；`/assign` 回應或列表對「已停用的負責人」加註。

**S8　測試缺口（假綠風險）**——兩份測試檔我逐題讀過，通過的題都是真斷言（有資料庫觀測點、有負向對照、`hichan10` 的三題都有正對照），沒有「斷言驗到自設值」的假綠。缺的是下列沒被任何測試釘住的行為：
1. **無模組的被指派對象 ⇒ 400**（`api.py:629`）：`test_assign_validates_target_user` 只測不存在與停用；`_login` 預設都帶 `dev_crm`，這條分支刪掉不會有題變紅。
2. **期限格式 400**（`api.py:619`）：無題。S2 的 `20261201` 同理。
3. **稽核與活動通知**：任務書要求檢查稽核；兩個端點的 `dev_case.assign`／`dev_case.progress` 稽核列、`notify_module_activity`、背景信 `notify_dev_case_assigned` 都沒有任何斷言。把 `_audit` 那行刪掉測試仍全綠。`notify_dev_case_assigned` 本身（`email_notify.py:1527`）也無單元測試（只有 L1 快照）。
4. **反向控制**：取消／換人後「原業務／企劃／建立者仍看得到」無直接斷言（`test_assignee_gets_full_row_access_until_unassigned` 只驗被指派人 B 的得失，沒驗 `owner` 仍可見）；A→B 換人後 A 失權、B 得權也無題。
5. **兩處 analytics 修正沒有測試**：`dashboard.py:684`（停滯提醒）與 `:915`（動態牆）補了 `assigned_to`，`hichan10` 檔案文件頭自己也寫「用 item_reads 與 activity-stats 兩個點釘住」，這兩個 SELECT 還原不會有任何題紅。
6. **`test_legacy_row_without_assignment_columns…`**：①`DROP COLUMN` 失敗會 `pytest.skip`——在較舊 SQLite 上會靜默變成「跳過」而不是失敗；②只覆蓋 `GET 單筆／列表`，不覆蓋明確 `SELECT assigned_to` 的出口（`item_reads`、`activity-stats`、dashboard）。正式環境因 migration 先於服務所以風險低，但題名「舊資料相容」說大了。
7. `test_row_access_2026_09_25.py` 的 `DEV` 是**本檔自抄的規則副本**（`:24-25`），不是 `crm.DEV_CASE_ACCESS`；該檔只比 py 與 SQL 兩邊一致，真規則被改掉它不會紅（靠 `test_dev_case_assignment` 的行為題補）。預設 `ats=(None,)` 讓其餘舊題不會走到 `assigned_to` 分支（作者在 docstring 已說明，屬刻意）。
8. 前端新控制項（`assign-user`／`assign-save`／`progress-save` 等 data-testid）沒有 UI 測試。

**S9　文件與註解不一致**
- `core/CHANGELOG.md` 1.149 條目仍寫「快照以 `core_bump.py --pending` 重產，**未取號**」；`crm/CHANGELOG.md` 1.0.18、`analytics/CHANGELOG.md` 1.0.45 標題仍是「暫用號，列車取號」。取號提交 `8922cf416` 只改了標題與 `registry.py`，內文沒同步。
- `crm/CHANGELOG.md` 1.0.18 說 `list/get/update/status/convert/relink/logs` 全套用 row_access；實際 `request/cancel/approve-relink-quote` 是 admin 限定，不經 row_access（`api.py:726-860`）。
- `crm/README.md`「端點」「資料」段、`SPEC.md` 未提指派端點與三個新欄位（README 的端點段只寫「見 api.py」，資料表段只列表名，尚可；但 SPEC 的行為依據清單沒加入本次兩個新測試檔）。

**S10　前端小項**
`dev-crm.html` 指派下拉列出所有 `activeUsers`，含沒有 `dev_crm` 的人，選了只會被後端 400 擋下。可依模組過濾。全部用 `x-text`，無 `x-html`，無注入問題。

## 四、觀察

- **O1**　`/assign`、`/progress` 都會 bump `updated_at`：重置 30 天停滯計時（`_check_dev_case_stale` 的 guard key 含 `updated_at`），也會讓正在編輯的人在 `PUT` 時吃樂觀鎖 409（`api.py:427`）。合理但使用者需知；進度回報會延後停滯提醒。
- **O2**　`/progress` 對任何有 `dev_crm` 的人，不存在的案件 404、存在但非被指派 403 → 可枚舉案件 id。與 `update／status` 等既有端點行為一致，不屬本次引入。
- **O3**　`/assign` 不擋「已成案」「待刪除」案件；可為已結案件指派。
- **O4**　**遷移**（`0002_dev_case_assignment.py`）：逐欄 `if not in cols`，重跑安全；表不存在回原因字串（版號不前進、下次補）；`progress_report` 為 `NOT NULL DEFAULT ''`，舊列自動補空字串；無 `commit`（符合 `test_module_migrations` 守門）。老庫升級＋重跑 OK。
- **O5**　**回退**：欄位保留、舊碼不讀（`SELECT *` + `_case_row` 的 `in row.keys()` 防護），舊 `DEV_CASE_ACCESS` 無 owner 分支 ⇒ 被指派人退回「看不到」，不會漏權。**不可回收的部分**：已寫入的 `assigned_to`／`reply_deadline`／`progress_report` 值、已寄出的站內通知與 email、`audit_log`。無破壞性副作用，但「回退」不會復原資料與通知。
- **O6**　快照與基準：`l1_interface_snapshot.json`（`core_version` 已由 `next` 取為 `1.149`，新增 `notify_dev_case_assigned`）、`response_keys_baseline.json`（5 個新鍵×2 端點）、`route_inventory.json`、`version_manifest.json` 方向一致；我沒跑對應守門，這部分交閘門驗證。

## 五、反向控制總表（任務書第 3 項）

| 問題 | 結論 | 證據 |
|---|---|---|
| `assigned_to=null` 是否動到現有業務／企劃權限 | 不動 | `row_access.py:119-132`、`:146-160` |
| 被指派人無模組權限 | 指派時 400；事後失去 ⇒ 所有端點 403，案件仍掛名（S7） | `api.py:629`、`:107-112` |
| 被指派人被停用 | 指派時 400；事後停用 ⇒ 掛名孤兒（S7）；不漏權 | `api.py:625` |
| 取消指派後前任是否真的失權 | 是（除非仍在業務／企劃／建立者名單）；前任不被通知（S5） | `api.py:632`、測試 `ra_b` 題 |
| 老庫跑兩次遷移 | 冪等 | `0002…py:12-20` |
| 回退是否不可逆 | 資料與通知不可回收；權限面可逆（O5） | O5 |

## 六、請求者對照

必修 0／建議 10／觀察 6。報告路徑：`docs/platform/audit/AUDIT-hichan3-t73.md`。
我沒有關閉或修改任何項目，也沒有動分支狀態；共用工作樹目前停在 `train/t73-int`，本檔是該樹上的未追蹤新檔，請由請求者決定如何納入提交。
