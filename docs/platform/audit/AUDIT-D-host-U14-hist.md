# 稽核：主持的 U14 前端（wip/h-u14）與部署儀表板歷史寫入（wip/h-hist）（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d。稽核者 D 沒有寫過任何受稽核的程式碼。只審新版（CORE-SPEC 35014aaa）。
> 對象：`origin/wip/h-u14` `6639ea8d`（合回前）；`origin/wip/h-hist` `f4c14dc5`（已排上第五班，順手看）。
> 稽核樹 `D:\MOTRIX-PLATFORM-D`（detached），Python `D:\MOTRIX-PLATFORM\.venv312`（只用、未改）。
> 分級：**必修**／**建議**／**觀察**。關閉規則：被稽核者回覆後，由 D 確認才關。

## 0. 結論

- **h-hist：必修 1 項（H-M1）**。這個修正在 Windows 上造成新的失敗：
  - 兩個讀取端沒有拿鎖，只要有人開著歷史檔，寫入端的 `os.replace` 就會丟 PermissionError。
  - D 用真實程式碼實測：300 次寫入有 145 次丟例外、那一筆遺失；修正前同一個實驗是 0 次。
  - D 已在 07:52 通知主持，建議 h-hist 先下第五班。
- **h-u14：必修 0**。「其他人看不到編輯與送出」有題目守，D 突變 2/2 轉紅。但 commit 寫的「缺欄位不當 false」沒有題目守（U-S1，突變存活），而且這條路徑確實會走到。

## 1. h-u14（U14 前端：草稿只有建立者與超管能編輯、送出）

| 項目 | 結果 | 證據 |
|---|---|---|
| 同權限的其他人看不到「編輯」「送出」、看到說明、仍可輸出 | ✅ | `test_peer_with_same_permission_sees_no_edit_or_submit`（先等說明出現，才檢查按鈕不在；狀態驗 DB） |
| 建立者、超管看得到而且送得出去（正對照，斷言驗 DB） | ✅ | `test_owner_and_superadmin_can_edit_and_submit[owner／superadmin]` |
| 後端另外擋 403 | —（c-audit-d，已合回） | `routers/custom_records.py:144` GET 回 `canEdit`＝`CM.can_edit_draft` |

D 的突變（`tests/test_e2e_u14_draft_owner_2026_09_26.py`，3 題）：

| # | 突變 | 結果 |
|---|---|---|
| U1 | `draftLocked()` 把沒帶 `canEdit` 的回應當成不能改（`=== false` → `!== true`） | **存活**（3 passed） |
| U2 | `canEdit()` 不看 `draftLocked()` | 紅 |
| U3 | `availableTransitions()` 不看 `draftLocked()` | 紅 |

### 建議

- **U-S1　「null 不等於 false」沒有題目守，而那條路一定會走到**：`save()` 存檔成功後執行 `showRecord(r.data)`，而 POST／PUT 的回應不帶 `canEdit`。所以建立者新增或存檔之後，畫面上的 `record.canEdit` 就是 undefined。把 U1 突變放進產品，建立者一存檔就會看不到「送出」，要重新整理才恢復；現有的 3 題照綠，因為它們都是打開既有的單據。建議補一題 e2e：建立者編輯、存檔之後，不重新整理，「送出」仍然在，按下去 DB 變成已送出。

### 觀察

- **U-O1　版本紀錄併入既有的「系統 2026-09-26a」**：新版還沒出貨，照 VR3 由主持統一處理，可以接受。記錄在這裡，是因為 `version_manifest.json` 已出貨的條目不可以追加（MEMORY：共用 JSON 用文字插入）；新版出貨之後，這個作法就不能再用。

## 2. h-hist（部署儀表板歷史寫入：加鎖＋原子取代）

### 必修

**H-M1　寫入改成 `os.replace` 之後，讀取端沒有拿同一把鎖 ⇒ Windows 上寫入會丟 PermissionError、歷史掉筆**
- 讀取端有兩個：`get_history()`（`/api/history`）與 `_recent_failure_warning()`（部署前「15 分鐘內剛失敗」的警告），兩者都直接 `read_text`，沒有拿 `_history_lock`。在 Windows 上，目標檔被別的 handle 開著時，`os.replace` 會失敗。
- 實測一：純 Python，一個執行緒不停讀檔，主執行緒 `os.replace` 2000 次 ⇒ 1206 次 PermissionError。
- 實測二：`f4c14dc5` 的真實 `deploy_dashboard`，`HISTORY_PATH` 指到暫存目錄，一個執行緒輪詢 `get_history()`，主執行緒 `_append_history()` 300 次：

| 版本 | `_append_history` 例外 | 歷史留存 | 輪詢讀到空清單 |
|---|---|---|---|
| 修正前 `a474e5d4`（`write_text` 原地寫） | 0 | 200／200（上限 200） | 48 |
| **修正後 `f4c14dc5`** | **145 次 PermissionError** | **155**（掉了 145 筆） | 638 |

- 後果：部署或回滾收尾（`:624`）時，只要剛好有人開著儀表板，歷史那一筆就會掉，例外往上拋進 job 執行緒（鎖由 finally 釋放）。這一筆正是「15 分鐘內剛失敗」警告的依據（S-P01），而警告的讀取端在讀檔失敗時回 `""`，所以**警告會靜默消失，不會有人報修**。
- 為什麼題目沒抓到：新增的 `test_history_concurrent_appends_keep_valid_json_and_every_entry` 只讓寫入端彼此競爭，沒有同時讀取。
- 建議修法：
  - 兩個讀取端也在 `_history_lock` 內讀。三者都在同一個行程，這樣就能完全解決。
  - 或者 `os.replace` 碰到 PermissionError 時短暫重試，但這只是降低機率。
  - 補一題「寫入同時有讀取」：寫入不可以丟例外、不可以掉筆，讀取不可以回空。在 Windows 上跑。

### 觀察

- **H-O1　歷史檔讀不懂時會被當成空的，然後覆寫**：`except Exception: history = []` 之後照樣寫回，所以壞掉的檔案（包括舊版殘字造成的）會被靜默換成只有一筆的新檔，舊的 200 筆就沒了。這個寫法在修正前就存在；既然這次已經碰到這幾行，建議壞檔先改名封存（比照升級紀錄的「封存讀不懂的紀錄」），再開新檔。

## 3. 回覆欄（被稽核者填；D 確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | D 確認 |
|---|---|---|---|
| H-M1 | | | |
| U-S1 | | | |
| U-O1、H-O1 | | | |
