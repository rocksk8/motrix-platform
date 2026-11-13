# S2 設定頁範本契約（給 S4a／S4b／S4c 的作者；hichan-4 寫，2026-11-14）

結論先講：**群組設定頁由外框用登錄表資料自動產生，S4 的作者寫的是「資料」，不是每頁 HTML。** 只有獨立頁（approval-settings 等）保留自己的 HTML。

## 1. 群組頁（50 個登錄群組、31 個設定頁）＝只寫資料
作者要補的全在登錄表（`backend/helpers/settings_groups*.py` 的 `SettingDef`）：

| 欄 | 內容 | 規則 |
|---|---|---|
| `label` | 欄位白話名（粗體） | 沒有禁用詞（確認期間／影子／閘門／true／false／整數選項代碼）；`test_settings_banned_words_2026_11_14` 會擋 |
| `question` | 一句問句 | 現有的保留 |
| `help` | 「?」第一段「這是什麼」 | 現有的保留 |
| `when`（新，S1c 提供） | 「?」第二段「什麼時候用」 | 選填；**不得與 `help` 完全相同**；不寫「需第二位核准、要等 N 天」（由執行期依 `plan().kind` 產生） |
| `impact` | 第三段「改了會怎樣」 | 現有的保留 |
| `recommended`＋說明 | 第四段「建議」 | 有建議值才顯示 |
| `choices` | 選項標籤＋說明 | 標籤用白話，不給使用者看代碼 |
| `risk`／`risk_text`／`impact_scope` | 風險與影響範圍 | 影響金額／法遵／安全的欄位必填 |

來源（S1c 已提供 `h3/when_texts.json`、`h12/when-texts.csv` 的格式）：甲的 76 欄 when 在 `h3/when_texts.json`，乙的 107 欄在 `h12/when-texts.csv`。S4a／S4b 的工作＝把它們寫進登錄表，並逐群組檢查白話名、help、選項標籤。

**後端回給外框的欄位資料**（`GET /api/settings-center/groups/{g}` 的 `fields[]`，S1c 第三個 commit 加）：既有 `value／valueText／isDefault／defaultText／banner／choices…`，另加
`help: {what, when, impact, recommend}`（由上表組成，空段不出現）、`source: {kind: default|company|pending|legacy|personal, by, at, reason}`。作者**不手寫 source**。

## 2. 頁面登錄（設定頁、分類、白話名、頁內含哪些群組）
S2 新增 `backend/helpers/settings_pages.py`（我寫，內容照 `data/shell_groups.json`：31 頁、分類、`groups[]`、白話名、隱私標籤）。**守門：頁面登錄涵蓋的群組集合＝登錄表群組集合（`external=True` 的不計）**，漏登或多登都紅。
- 要新增／改頁面名稱、分類、合併頁 ⇒ 改 `settings_pages.py`（不要改 `shell_groups.json`；它在 S2 合併後停用，只留給 `gen_seed.py`）。
- 改完要讓 `gen_seed.py --check` 綠（可批次數會變）。

## 3. 獨立頁（甲 7 頁：approval-settings、approval-delegates、expense-types、remit-kinds-settings、ledger-settings、legal-params、account-items；乙的獨立頁；設定中心以外 7 項）
- 保留原網址與自己的 HTML／後端。**在 `settings_pages.py` 登記一筆 `{id, plain, category, href, standalone: true}`**，外框導覽就會出現連結，全域搜尋也找得到頁名。
- 頁面改白話、加「名稱＋小字代碼＋標籤＋『?』」（元件：`frontend/static/settings-matrix.js` 的 `help`／`source`／`diff`，S1b `c43729345`）；要批次的表格用 `SettingsMatrix.mount`（`draft:true`＝草稿＋儲存列＋離開警告；`notifyPreview`＝確認視窗的通知預覽）。**html 欄預設跳脫；`raw:true` 只給可信內容，使用者可編輯的文字（名稱、主旨、角色名）一律不得 raw。**
- 儲存通知：呼叫 h9 的 `notify_change(...)`（S1d）；寫入走原本的路徑，不另開寫入點。

## 4. 逐頁換、可還原
每個頁／每個群組一個 commit，可單獨 `git revert`；e2e 一題（可批次的格子與 `gen_seed --check` 一致）；截圖留給上線前（PM 轉使用者）。

## 5. 時程（從 11-13 夜起算）
- 現在就能做（不等外框）：把 `when`／白話名／help／選項標籤寫進登錄表（在 `feat/settings-matrix-s1c` 之上；S1c 的 `when` 欄位約 +1h）。
- 外框主體（S2）約 +9h；之後獨立頁登記與改白話可並行。外框前不要碰 `settings-center.html`（S2 整頁重做）。
