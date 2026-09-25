# 稽核：C 的 M02 業務開發搬進 modules/crm（PLAYBOOK §B；合回前稽核）（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d。稽核者 D 沒有寫過任何受稽核的程式碼。**合回前稽核**，搭第四班列車。只審新版（CORE-SPEC 35014aaa）。
> 對象：`origin/wip/c-m02` `927b4599`（`23338f3f` 搬遷、`d3f68117` M01 畫面 notice、`3f01ba22`、`207bc0df` IP-11 題拆兩邊、`4db3b7a4` SPEC.md、`927b4599` ROADMAP）。
> 反向控制範圍依主持 2026-09-26 定的標準：**`tests/platform`＋所有提到該模組的測試檔**（PLAYBOOK §B-11 已更新）。
> 稽核樹 `D:\MOTRIX-PLATFORM-D`（detached），Python `D:\MOTRIX-PLATFORM\.venv312`（只用、未改）。
> 分級：**必修**／**建議**／**觀察**。關閉規則：被稽核者回覆後，由 D 確認才關。

## 0. 結論

- 主持點名的兩件事：
  - **SPEC.md**：有（`modules/crm/SPEC.md`），寫明本模組沒有專屬規格編號與查證範圍，格式與 tender_radar 相同。
  - **IP 提供方寫法**：IP-11 的提供方寫成 `modules/crm/api.py::unlink_deleted_quote`，符合 X-2 新規則（`modules/<key>/…` ⇒ 模組不在時可以豁免）。但 **IP-11 與 A 的 M10「IP-11 case.access」撞號**（O-1）。
- **必修 1 項**：
  - M02-M1：真的刪掉 `modules/crm` 之後，`tests/platform` 加上 26 個提到業務開發的測試檔（`dev_crm`、`dev-crm`、`dev_case`、`modules.crm`），共 **940 passed、35 failed**。扣掉 §B-11 允許的一題，以及會由 a-m10 的 X-2 修正（be41fd9e）解掉的一題，**還有 33 題是需要 M02 的題目，卻留在模組外**。C 在 207bc0df 的反向控制只跑了 `tests/platform`（舊範圍）。
- 建議 1 項、觀察 2 項。

## 1. 反向控制實測（§B-11，新範圍）

`rm -rf backend/modules/crm`（只在稽核樹，做完用 `git checkout` 還原）；跑 `tests/platform` 加上 26 個測試檔，單程序、低優先權，耗時 14 分鐘：**940 passed、35 failed**。

| 紅的題（依檔） | 題數 | 分類 |
|---|---|---|
| `tests/platform/test_module_boundaries.py::test_modules_json_lists_only_existing_units` | 1 | §B-11 允許 |
| `tests/platform/test_integration_points_registered.py::test_registry_matches_code` | 1 | a-m10 be41fd9e 的 X-2 豁免合回後不再紅（IP-11 的提供方寫法符合條件） |
| `tests/test_api_integration.py`（`test_dev_case_update_conflict_returns_409`、`test_mark_converted_*`、`test_request_relink_*`、`test_relink_*` 等） | 11 | **M02-M1**：端點不在，回 `405 Method Not Allowed` |
| `tests/test_dev_case_soft_delete_guard_2026_08_28.py` | 5 | **M02-M1** |
| `tests/test_e2e_unread_marks_clear_on_click_2026_09_24.py` | 6 | **M02-M1**（e2e） |
| `tests/test_item_reads_server_side_2026_09_24.py` | 4 | **M02-M1** |
| `tests/test_feed_attachments_2026_09_14.py` | 2 | **M02-M1** |
| `tests/test_dev_case_row_access_2026_09_25.py` | 1 | **M02-M1** |
| `tests/test_row_access_callers_2026_09_25.py` | 1 | **M02-M1** |
| `tests/test_e2e_dark_mode_sidebar_2026_09_13.py`、`tests/test_e2e_feed_attachment_render_2026_09_15.py` | 各 1 | **M02-M1**（e2e） |
| `tests/test_em1_screen_words_in_long_messages_2026_09_24.py` | 1 | **M02-M1**：直接讀 `modules/crm/api.py` ⇒ `FileNotFoundError`（A 在 a-m10 6492aa6c 已經讓這一題在模組不在時跳過該模組的條目；合回後應不再紅，要確認） |

## 2. 發現

### 必修

**M02-M1　33 題需要 M02 的題目留在模組外，新範圍的 §B-11 反向控制不過**
- 為什麼是必修：與 M12 的 M-1 同一類，而且量更大（業務開發的既有題目幾乎都還在 `backend/tests`）。SPEC.md 也寫著「行為的依據是既有測試（`tests/test_dev_case_*`、`tests/test_row_access_*`）」，也就是這些模組外的題目。模組被拿掉時，它們會讓每一次全量都紅；而這些紅不代表產品有問題。
- 建議修法：
  - 把 §1 表中「需要 M02 在」的題（或題的那一半）搬進 `modules/crm/tests`。
  - `test_api_integration.py` 這種混合檔，拆出業務開發那 11 題。
  - `test_item_reads_server_side`、`test_feed_attachments` 這類「L1 功能拿業務開發當對象」的題，改用合成模組或 tender_radar 當對象，或者在 M02 不在時 skip 並說明原因。
  - 修完用新範圍重跑一次反向控制，附上數字。

### 建議

- **M02-S1　SPEC.md 指向模組外的題目**：SPEC.md 說行為依據是 `tests/test_dev_case_*` 等既有測試，這些題目在模組外，模組拿掉時不會跟著消失。M02-M1 修完之後，SPEC.md 的依據要改成指向 `modules/crm/tests`。

### 觀察

- **O-1　IP-11 撞號**：C 的 `IP-11 crm.quote_deleted` 與 A 的 M10「對 M01 的相依改走 IP-11 case.access」同號。依 PLAYBOOK §C-7，由列車在合回時依 origin 重新編號；兩邊的 README、SPEC.md、測試說明與 INTEGRATION-POINTS 要一起改。
- **O-2　ROADMAP 已經更新**（§B-14 ✅），並如實列出剩下的事：他模組直讀 `dev_cases`／`dev_logs`、停滯檢查直寫 `audit_log`、頁面（階段 C）。

## 3. 回覆欄（被稽核者填；D 確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | D 確認 |
|---|---|---|---|
| M02-M1 | | | |
| M02-S1 | | | |
| O-1～O-2 | | | |
