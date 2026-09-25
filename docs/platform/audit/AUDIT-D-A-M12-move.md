# 稽核：A 的 M12 每日任務搬進 modules/daily_tasks（PLAYBOOK §B；上月台後稽核）（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d。稽核者 D 沒有寫過任何受稽核的程式碼。只審新版（CORE-SPEC 35014aaa）。
> 對象：`origin/wip/a-m12` `639949f4`（基底 `84c53670`；8 個 commit：前置 `98c448ad`、`67842d0a`，搬遷 `151409b7`、`acd788cf`，測試 `fa3dd907`、`639949f4`，取號 `af8449aa`、`9110327b`）。排在第三班列車。
> 稽核樹 `D:\MOTRIX-PLATFORM-D`（detached），Python `D:\MOTRIX-PLATFORM\.venv312`（只用、未改）。
> 分級：**必修**／**建議**／**觀察**。關閉規則：被稽核者回覆後，由 D 確認才關。

## 0. 結論

- **主持點名的「刪掉模組之後系統健康檢查照跑」成立**。D 在稽核樹**真的刪掉** `backend/modules/daily_tasks`（不是 monkeypatch），結果：
  - 已載入的模組只剩 `tender_radar`；`daily.check` 的提供者只剩 L1 的 `case_deadlines`。
  - `daily_checks.run_once("daily")` 照跑系統健康檢查 6 項（催辦、憑證、備份、磁碟、暫存、請求紀錄清理）。
  - `/api/daily-tasks` 回 404、`/api/ping` 回 200，已經下沉到 L1 的 `/api/settings/reminder-send-failures` 回 200。
  - D 突變 MX1（沒有提供者時就不跑系統檢查）⇒ `test_reverse_without_module_providers_system_checks_still_run` 紅。
- **必修 1 項**：
  - M-1：§B-11 的反向控制沒有通過。刪掉模組之後，`tests/platform` 加上 17 個提到每日任務的測試檔共紅 **9 題**，§B-11 只允許紅 1 題（「modules.json 列了但掃描不到」）。其中 6 題是需要 M12 存在的題目卻留在模組外面。
- 建議 4 項、觀察 3 項。

## 1. PLAYBOOK §B 逐步

| 步 | 內容 | 驗收 | 證據 |
|---|---|---|---|
| 1-2 | worktree、讀相依、重跑掃描 | ✅ | 分支 wip/a-m12 |
| 3 | 跨組相依：下沉 L1 或由對方公開 provider，登記 INTEGRATION-POINTS | ✅ | 系統健康檢查下沉 L1 `helpers/system_checks.py`、案件類檢查歸 M01 `helpers/case_deadlines.py`、新串接點 IP-10 `daily.check`；IP-5 由 M12 提供（README） |
| 4 | 對方不在時：少一個功能並明白告知 | ✅ | README「本模組不在時」；IP-5 回 notice「未建立每日任務：每日任務模組未安裝」 |
| 5 | 跨組直寫改走連接器、刪 debt | —（沒有 M12 的 debt） | |
| 6 | `git mv` 搬 router、helper、頁面、測試 | ⚠ | `routers/daily_tasks.py`（2,142 行）拆成 `modules/daily_tasks/api.py`＋L1 `system_checks`／`case_deadlines`／`daily_checks`，git 認不出是搬移（O-1）；頁面依階段 C 還在 `frontend/pages/`（允許）；**需要 M12 的測試只搬了一部分**（M-1） |
| 7 | module.json、README、CHANGELOG、**SPEC.md** | ⚠ | 前三個有；**沒有 SPEC.md**（S-1） |
| 8 | 資料位置用 core.paths | ✅ | 沒有自有資料檔 |
| 9 | import 與測試路徑、守門用 core.source_tree | ✅ | tender_radar 的 3 個測試跟著改 |
| 10 | 跑受影響的題 | ⚠ | 每日任務本身**沒有任何功能題**（搬遷前後都沒有題目打 `/api/daily-tasks`）⇒ 「受影響的題」幾乎只有系統類（S-2） |
| 11 | 反向控制：刪掉資料夾 ⇒ 伺服器能啟動、ping 200、端點 404；其餘題除了那一題全綠 | ❌ | 啟動、ping、404 ✅；**其餘題紅 9**（M-1、O-2） |
| 12 | 對「對方不在時」的降級做突變 | ✅ | D 突變 MX1 紅 |
| 13 | rebase、重跑、合回 | 列車 | |
| 14 | 更新 modules.json、**ROADMAP**、模組 CHANGELOG | ⚠ | modules.json、CHANGELOG ✅；**ROADMAP 沒有更新**（S-3） |
| 15 | 回報 | ✅ | RUN-PLAN 03:49 |

## 2. 反向控制實測（§B-11）

在稽核樹 `rm -rf backend/modules/daily_tasks`（只在稽核樹，做完用 `git checkout` 還原），跑 `tests/platform` 加上 `backend/tests` 裡提到 `daily_task` 的 17 個檔（`tests/platform` 之外）（單程序、低優先權）：**894 passed、9 failed**。

| 紅的題 | 分類 |
|---|---|
| `test_module_boundaries::test_modules_json_lists_only_existing_units` | §B-11 允許 |
| `test_integration_points_registered::test_registry_matches_code` | 框架：登記表不認得「模組不在包內」。C 搬 M02 時也遇到，已報主持（O-2） |
| `test_unit_cards::test_unit_index_is_current` | 框架：UNIT-INDEX 依現有單位產生，模組不在就不相符（O-2） |
| `test_case_stage_done_calendar_2026_09_11.py` 的 5 題（`test_daily_task_created_with_case_name_and_stage`、`…_always_has_an_assignee`、`…_prefers_stage_assignees`、`…_is_marked_complete_so_no_overdue_mail`、`test_uncheck_withdraws_the_daily_task`） | **M-1**：這幾題要驗「M01 經 IP-5 建立每日任務」，需要 M12 存在；模組不在時 `tasks == []` |
| `test_em1_screen_words_in_long_messages_2026_09_24::test_em1_the_other_long_messages_did_not_change_a_single_character` | **M-1**：直接讀 `modules/daily_tasks/api.py` 的原始碼 ⇒ `FileNotFoundError` |

## 3. 發現

### 必修

**M-1　6 題需要 M12 的題目留在模組外，§B-11 反向控制不過**
- `fa3dd907` 已經把「需要 M12 在的正對照」搬進 `modules/daily_tasks/tests`，但漏了 §2 表中的 6 題。模組拿掉（停用、未授權、不在安裝包）時，這些題就會紅；而它們測的是 M12 的行為，不是 L1 的行為。
- 為什麼是必修：§B-11 是每一個模組搬遷的完成條件。階段 B 還有 9 個模組要搬，這個反向控制要是只跑 `tests/platform` 就算數，同樣的漏網會一直重複出現。
- 建議修法：
  - 把這 6 題的「M12 在」那一半搬進 `modules/daily_tasks/tests`。「M12 不在時 M01 回 notice」的反向控制留在外面（IP-5 已有）。
  - `test_em1` 讀原始碼的那一段，改成依 `core.source_tree` 找檔，檔案不在就略過並說明原因，或整段搬進模組。
  - 反向控制的指令寫進 PLAYBOOK §B-11：刪掉資料夾後，跑 `tests/platform` **加上** `modtest` 選到的、提到該模組的題目，不能只跑 tests/platform。

### 建議

- **S-1　沒有 SPEC.md**：§B-7 要求模組附規格條件編號。其他搬遷可以照同一個格式補。
- **S-2　每日任務本身沒有功能題**：`modules/daily_tasks/api.py` 1,105 行（建立、指派、完成回報、編輯紀錄、逾期、區間到期），整個 repo 沒有一題打 `/api/daily-tasks`，搬遷前也沒有。搬進模組之後，模組的選題只剩契約題與 2 題提供者題。建議至少補建立、完成回報、權限三題，放在模組的 tests。
- **S-3　ROADMAP 沒有更新**：§B-14。
- **S-4　`system_checks.run_all` 沒有逐項隔離**：六項檢查依序呼叫、外面只包一個 try（`daily_checks.run_once`）⇒ 第一項 `_check_approval_reminders` 一丟例外，憑證、備份、磁碟檢查當天都不會跑。搬遷前（`routers/daily_tasks.py:2002-2006` 等）就是這個寫法，**不是這次造成的**；但既然這次把它抽成 L1 的「一律執行」，建議每一項各自 try，並補一題「第一項丟例外，其餘照跑」。

### 觀察

- **O-1　git 認不出搬移**：`routers/daily_tasks.py` 被刪、內容拆到四個新檔，`git log --follow`／`git blame` 在新檔上看不到原本的歷史。拆分是為了把健康檢查下沉 L1，這是合理的代價；建議在模組 CHANGELOG 寫明「搬自 routers/daily_tasks.py（基底 84c53670）」，方便追查。
- **O-2　兩個框架題在模組不在時會紅**：`test_registry_matches_code`、`test_unit_index_is_current`。它們與「modules.json 那一題」同一類，應該由 B 或主持決定：這兩題認得「模組不在包內」，或者列入 §B-11 的允許清單。〔補註（寫完後查到）：`test_registry_matches_code` 已由 A 在 `wip/a-m10` be41fd9e 修正（提供方模組不在時視為合規，主持裁定），與本包同搭第三班列車 ⇒ 合回後這一題不再紅；`test_unit_index_is_current` 仍待裁定〕
- **O-3　與列車上其他包的交會**：第二班列車上的 x-p1p3-fix 會讓 G2 要求每個模組都寫 `customization`，C3 會要求 `pages[].menu` 的格式；本包的 module.json 兩者都沒有。IP-10 與 C 的 `approval.queue_items` 撞號（RUN-PLAN 已記）。第三班列車 rebase 時要一併處理。

## 4. 回覆欄（被稽核者填；D 確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | D 確認 |
|---|---|---|---|
| M-1 | | | |
| S-1～S-4 | | | |
| O-1～O-3 | | | |
