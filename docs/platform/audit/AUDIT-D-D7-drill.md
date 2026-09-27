# 稽核：D7 正式轉移升級演練（c006a2a0，13 份包）（D，2026-09-27 22:57）

> 標準等級、讀碼優先。對象：`D:\MOTRIX-DRILLS\FINAL-DRILL-REPORT.md`、`d7-results\`、`d7-tools\`、`d7-packages\`。
> 主持要 D 嚴格審的是「第一輪 3 份沒過，子代理改了自己的兩條判準後重跑全過」。

## 0. 結論

- **full 包可以上正式機**：必修 0。兩條判準的更正都有規格原文支持，不是「改判準變綠」；13 份包與 c006a2a0 的內容一致、沒有被探針污染。
- 建議 2（S-1、S-2 的意見見 §4）、觀察 1。

## 1. 兩條被改的判準（逐條對照規格原文）

| # | 第一輪的判準 | 規格原文 | 判定 |
|---|---|---|---|
| 1 | `/api/system/modules/availability` 要提到缺席的模組（core-only、accounting-only、analytics-only 因此紅） | `routers/system.py::module_availability` docstring：「不在這份清單裡的 key ＝不在這個安裝包（STATES-PLATFORM P-FE-02）」。STATES-PLATFORM §9 P-FE-02：`sidebar.js` 入口只在 `state==='loaded'` 時顯示，「**未知＝不在包內＝不顯示**」；缺席的「明說」由 P-FE-03（直接打網址 ⇒ 未安裝提示頁）與缺席 404 負責，不是這支端點 | **第一輪判準寫反，更正成立**。新判準「清單 key＝lock 模組、皆 loaded」與規格一致 |
| 2 | IP-98 `expenses-monthly` 不帶 basis（預設權責口徑）時，arap 缺席要有「應收應付模組未安裝」 | INTEGRATION-POINTS IP-98「使用方：…（現金口徑：當月／今年度／季收入；**權責口徑不用它**）」。程式：`_build_income_expense_scopes` 權責口徑收入走 M01 `case.recognition`（缺席 ⇒ `CASE_RECOGNITION_MISSING`），現金口徑才走 `receivables.income_items`（缺席 ⇒ `RECEIVABLES_MISSING`）；同一回應裡不分口徑的「當月未收」「收款異常」讀的是 `quotations` 的付款項目，也不用 arap | **更正成立**：預設口徑完全不用 arap 的資料，沒有靜默降級。現金口徑的提示在更正後的題裡驗到 |

- 兩條都符合〈推翻的證據不會自動支持替代方案〉的檢查：D 沒有採信子代理的說法，是逐條讀規格與程式後獨立得出的。

## 2. 包的完整性（主持：確認 sha256 與建包時一致）

- 報告的「13 份包逐檔 sha256 與 V5 清單相同」只證明演練前後沒變，V5 本身是演練時算的。D 另做三項不依賴演練工具的檢查：
  1. 13 份包裡 `.pyc`＝0、`__pycache__`＝0。
  2. 沒有任何檔案的 mtime 晚於該包的建包時間（資料夾名的時間戳＋300 秒）。
  3. 逐檔 git blob 比對（c006a2a0）：除了建包產生的 3 檔（`.build_commit`、`modules.lock.json`、`deploy_manifest.json`），每份包都只有 24 檔不同——其中 23 檔是 `.gitattributes` 指定的 CRLF（.bat／.ps1／.vbs／.ini／.txt 等），還原 LF 後相同；剩下 `backend/version_manifest.json` 是建包 Step 的「投影成使用者可見欄位」（`ConvertTo-Json | Set-Content -Encoding UTF8` ⇒ BOM＋CRLF＋重新格式化），**逐鍵內容相同**；讀它的 `helpers/startup.py`、`routers/auth.py`（以及工具 `check_version_sync.py`，不在包裡）都用 `utf-8-sig`，演練冒煙的版本端點 200。
- ⇒ **13 份包＝c006a2a0 的內容，沒有被演練污染**（比對來源 commit，比「與演練時的清單相同」更強）。

## 3. 其他

- E1～E4（來源唯讀）：報告的證據成立（來源 db mtime、wal／shm 無新增、source-backup 雜湊、6327 檔前後一致）。
- **觀察 D7-O1**：報告的 O-1①～③ 是探針自己的錯，都已更正留列；「最終採用的結果全部來自更正後的重跑」與原始結果檔（22:42 起的 full、core-only、accounting-only 整份重跑）一致。

## 4. 對 S-1、S-2 的意見

- **S-1（同意，建議排入）**：「L1 在模組缺席時明說」目前只在 `d7_extra.py` 這支臨時腳本裡驗，應收進 `final_drill`。收進時要帶上本次學到的兩點：availability 的判準是「清單＝lock 模組」；IP-98 要依口徑分開驗。否則下一次會重演這次的假紅。
- **S-2（同意列觀察，不擋 full）**：未以 HTTP 驗的缺席行為（寫入類與連外）只影響**單一模組包與 core-only**。full 包所有模組都在，這些路徑在 full 走不到。這些行為各有單元題守門；要在演練層驗，需要可丟棄的資料庫與攔截連外，建議下一輪再做。
- **完整版走不到的**：S-2 全部、以及 §1 兩條判準本身（都只在有模組缺席時才有意義）。上 full 包不受影響。
