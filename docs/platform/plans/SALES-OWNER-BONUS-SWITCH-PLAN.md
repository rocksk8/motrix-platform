# 業務獎金讀源改 `roles.sales`——方案與施工紀錄（D1～D5 已裁示、新版已施工）

> 2026-11-06｜原方案階段未改程式；**D1～D5 裁示後已施工**（見文末「裁示與施工紀錄」）｜基準 `76d3e2d07`＋本分支
> 裁示（轉達）：產品負責人看過正式機實測（4 張單兩欄人不同，其中 1 張分潤草稿人工已繞過 `sales_person`、手動填 `roles.sales`）後，裁示業務獎金計算讀源改 `roles.sales`；兩個欄位仍分開存、不合併、不互相寫入；`roles.sales` 沒填退回 `sales_person`。
> 前置分析：`SALES-PERSON-VS-ROLES-SALES-ANALYSIS.md`

## 0. 先講結論（三句）

1. 影響面比想像的小：**只有「還沒有分潤單」的案件**會換人。已有分潤單（草稿／待審核／待發放／已發放，新舊兩版）的名單都已凍在 `lines` 裡，程式不會重新帶入——「不回溯」是現行結構自然的結果，不必額外寫保護。
2. 需要你們決定的有 4 件（§5）：已發放案件要不要加註記、`roles.sales` 有值但對不到帳號時**退回報價人還是不帶人**（我建議不退回）、舊版項目式獎金要不要一起改、`person_source` 鍵名保不保留。
3. 先別動畫面文字的獎金說法：目前畫面上的說明刻意**不提獎金**（見 §4），等獎金程式真的切換的同一版再補一句，避免文字比程式先走。

## 1. 現在哪裡讀 `sales_person` 算錢（要改的全部清單）

| # | 位置 | 做什麼 | 切換後 |
|---|---|---|---|
| 1 | `modules/payroll/api/bonus.py:1203-1230 _auto_members()`（§11.7「業務＝`quotations.sales_person`」） | **新版（案件為中心）**自動帶入「業務」名單 | 改讀 `roles.sales`，沒填退回 `sales_person_id`／`sales_person` |
| 2 | 同檔 `:1606 POST /cases/{no}`（建立）、`:1551 GET /cases/{no}`（無分潤單時預覽）、`:1786 POST …/preview`（無分潤單時） | 呼叫 #1 | 隨 #1 |
| 3 | `modules/payroll/api/bonus.py:1100-1145 _case_people()`→`bonus.py::people_for_item()`（`person_source='sales_person'`；`:447 GET /awards/plan`、`:853`、`:951 POST /awards/plan`） | **舊版（項目為中心）**獎金項目的人員來源 | 見決定 D3（是否一起改） |
| 4 | `modules/payroll/bonus.py:234-255 PERSON_SOURCES`（鍵名 `"sales_person"`）、註解 | 常數與裁示註解 | 見 §3、D4 |

**不改**：`db.py:4936-5020 _m103…`（凍住的歷史：回填舊單帳號，不呼叫活程式，不動）；`bonus_award_lines.person_source_snapshot='sales_person'` 的既有資料（是歷史快照）。

**為什麼已有分潤單的案件不受影響**：`GET /cases/{no}` 在 `award is None` 才呼叫 `_auto_members`；有單時名單來自 `_members_from_lines(lines)`；`PUT /cases/{no}`、`/preview` 在有單時同樣用 lines（`bonus.py` 行 1645-1830 已讀）；`approve/reject/return/mark-paid` 全都不重新解析人。舊版 `bonus_award_lines` 是建立當下凍結（`person_source_snapshot`＋`username`）。

## 2. 受影響案件清單（通用查法，不寫死單號）

唯讀腳本（SQLite `mode=ro`、不依賴專案程式碼、逐筆解析 JSON）：`docs/platform/plans/SALES-OWNER-DIFF-REPORT.py.txt`（用法：`python -I <檔> <motrix_erp.db> [--all]`，用前去掉 `.txt`）。

它列出：所有**狀態不是草稿**、兩欄都有值且不同的案件，附
`verdict`（DIFF＝兩邊帳號都解析得出且不同；DIFF_UNRESOLVED＝至少一邊解析不出帳號（舊字串／同名），需人工看；ROLES_EMPTY／SAME 預設不列）、
新版分潤單（`status`、`paid_by`、`paid_at`、`paid`＝有任一值、業務類 lines 的帳號／來源／金額）、舊版分潤單（未作廢者的狀態與 `sales_person` 來源的 lines）、
`effect`（`SNAPSHOT`＝已有分潤單、名單已凍結不受影響；`WOULD_CHANGE`＝尚無分潤單、下次建立／預覽才換人）。

驗證：開發機 DB 是空的，我用合成資料測過（`SAME`、`ROLES_EMPTY`、草稿不列、`DIFF` 無單／新版已發放／新版草稿（人工已繞過）／舊版項目式、舊字串可唯一解析、舊字串解析不出、同名不猜、報價人無 id、壞 JSON 只標該筆）——全部分類符合預期。**正式機實跑結果需正式機 Claude 提供**（我沒有碰正式機）。

## 3. 已發放案件怎麼處理（方案，請裁示）

| 方案 | 內容 | 風險／備註 |
|---|---|---|
| **P1 不回溯（建議）** | 已有分潤單的案件一律不動；只有「尚無分潤單」者在切換後建立時改用新口徑 | 零風險（現行結構本來如此）。已發放的錢已有傳票（`accrual_voucher_id`／`payment_voucher_id`），不可也不該被改 |
| **P2 加註記（建議搭配 P1）** | 純顯示：分潤單畫面對「業務類名單帳號 ≠ 現行 `roles.sales`」的單（待審核／待發放／已發放）顯示一行中性註記：「此單名單於 YYYY-MM-DD 依報價人帶入；現行口徑為業務負責（X）」。不改 lines、不改金額、不擋任何動作 | 低；要新增一個唯讀欄位／畫面文字。若不想動分潤單畫面，改用 §2 報告留底也可 |
| P3 回溯重算 | 已發放／待發放案依新口徑重算並換人 | **不建議**：動已入帳的錢與傳票；需要退回→重提流程、會計沖轉；產品負責人未要求 |
| 草稿（含「人工已繞過」那張） | 不動：lines 已是人工填的 `roles.sales` 帳號 | 切換後這張與新口徑一致，無需處理 |
| 待審核／待發放 | 不動；若要換人走既有「退回→編輯→再提交」 | 人工流程，不自動 |

## 4. 註解與留痕怎麼處理（`bonus.py:234` 那段）

原則：**舊裁示留著當歷史、新裁示寫在旁邊、兩條都標日期與「誰推翻了誰」**；不刪原話（那是使用者逐字說的，刪了以後沒人知道當初為什麼這樣設計）。

`modules/payroll/bonus.py` 的 `PERSON_SOURCES` 說明改成（切換當天才寫，日期以實際為準）：

```
#: 每個獎金項目各自綁一個人員來源。
#:
#: ## 📜 「業務」來源的兩次裁示（新者取代舊者；兩條都留痕，不要只留最新的）
#:   ① 2026-09-23 使用者原話（逐字）：「業務獎金→`sales_person`／專案執行獎金→`case_stages.assigned_to`」
#:   ② 2026-11-06 產品負責人裁示（經 MOTRIX-ERP 模組結構圖窗口轉達；依據：正式機實測 4 張報價人≠業務負責，
#:      其中 1 張分潤草稿人工已繞過 `sales_person`）：業務獎金改讀 `caseRecord.roles.sales`（業務負責／業績歸屬），
#:      沒填才退回 `quotations.sales_person`／`sales_person_id`。**推翻 ① 的「讀哪一欄」；沒有推翻**「兩欄各自存、互不寫入」
#:      （報價單的「報價人」欄不受影響）。已有分潤單的案件不回溯（名單在建立當下已凍結）。
#:   ➜ 讀取點：`api/bonus.py::_auto_members()`（新版）＋〔D3 決定後〕`_case_people()`（舊版）。
```

同一次要同步更新的文字（grep 確認過的清單）：`api/bonus.py:1204` docstring「§11.7：業務＝quotations.sales_person」、`SPEC.md:34-36`、`SPEC-BONUS §11.7`、`docs/quick/known-limits.md` §11 對應列（把「報表讀 roles.sales／獎金讀 sales_person」兩條並列的落差標成「2026-11-06 已統一」並記日期）、payroll `CHANGELOG`、`docs/quick/changelog.md`。`db.py` 裡 `_m103`／`_m113` 的 docstring 是凍住的歷史，**不改**（改了反而讓歷史說謊）。

另加一支測試鎖住留痕：`PERSON_SOURCES` 註解必須同時含 `2026-09-23` 與 `2026-11-06` 兩個日期（避免日後有人「整理」註解時把舊裁示或新裁示刪掉）。

畫面文字（已在做，與獎金分開）：角色下拉說明、頭部／卡片現在只講「營運報表的業績與部門依此欄位」，**不提獎金**（測試 `test_hint_does_not_promise_bonus_behaviour` 鎖著）。獎金程式切換的同一版再補「業務獎金亦依此欄位」並改那支測試。

## 5. 需要裁示的決定

| # | 問題 | 我的建議 |
|---|---|---|
| D1 | 已發放／待發放案件：P1（不回溯）＋P2（註記）？還是只 P1？ | P1＋P2；不做 P3 |
| D2 | `roles.sales` **有值但對不到唯一帳號**（舊字串未對應、同名、帳號已停用）時：退回 `sales_person`？還是不帶人並提示「請手動指定」？ | **不退回**（照現有 `_auto_members` 對報價人解不出時的做法：不帶、`notes` 提示手動指定）。理由：悄悄退回等於把錢發給可能是錯的人，正是營運報表當初「不要悄悄退回開單者」的同一原則；只有「完全沒填」才退回，與你轉達的規則一致 |
| D3 | 舊版項目式獎金（`person_source='sales_person'`、`/awards/plan`）是否一起改讀 `roles.sales`？ | 先確認舊版是否還在用（`m113` 註記「舊單直接作廢、新頁面不理會」）。若已停用就**不改**，只在註解標「舊版不隨此裁示」；若仍在用，必須與新版同口徑（否則同一案兩套獎金對不同人）。請正式機確認 `bonus_awards` 近期是否仍有未作廢新單 |
| D4 | `person_source` 鍵名 `"sales_person"` 保不保留？ | **保留鍵名**（它存在 `bonus_items.person_source`、`person_source_snapshot` 歷史列與 UI 選單；改名要 migration 與回填），只改解析邏輯並在註解與 UI 選項說明寫清楚「業務（業務負責，沒填取報價人）」 |
| D5 | 切換後「尚無分潤單且兩欄不同」的案件（§2 的 `WOULD_CHANGE`）是否通知原報價人／新業務負責？ | 不自動通知；把清單給產品負責人，人工告知 |

## 6. 施工與驗證計畫（點頭後才做）

1. 改 `_auto_members()`：優先 `roles.sales`（物件取 `username`；舊字串走現有 `_unique_username_by_display`；帳號須 `active=1`），完全沒填才退回現有報價人解析；有值但解不出 ⇒ 依 D2。
2. 新測試：兩欄相同／不同／`roles.sales` 空／舊字串可解析／舊字串解不出／同名／已停用帳號；**已有分潤單時名單不變**（正向控制）；已發放單 lines 位元組不變；建立→預覽→PUT 三條路徑一致。
3. 差異探針：切換前後對同一批合成案件逐位元組比對 `_auto_members` 輸出——兩欄相同或 `roles.sales` 空的案件必須與切換前**完全相同**。
4. 同版補畫面「業務獎金亦依此欄位」與更新留痕註解、SPEC、known-limits、CHANGELOG。
5. 不動：報價單表單、`sales_person` 的任何寫入、報表、row-access、`db.py` 凍住的歷史。

---

## 7. 裁示與施工紀錄（2026-11-06，產品負責人裁示，經 MOTRIX-ERP 模組結構圖窗口轉達）

| # | 裁示 | 施工 |
|---|---|---|
| D1 | 已發放（及其他已建立分潤單）**不回溯**，只加中性註記（採 P1＋P2，不做 P3） | 不回溯＝現行結構自然結果（有單時名單來自 lines）；測試鎖住。註記：`GET /api/bonus/cases/{no}` 對最高管理者、非草稿單、現行「業務負責」不在名單內時多回 `salesOwnerNote`（`api/bonus.py::_sales_owner_note`），`pages/bonus.html`「發放明細」上方以中性色顯示；出納／名單本人看不到 |
| D2 | `roles.sales` 有值但對不到唯一帳號 ⇒ 不退回報價人、提示手動指定；**只有完全沒填**才退回 | `api/bonus.py::_roles_sales_of()`＋`_auto_members()`：舊字串查無／同名、帳號停用或不存在 ⇒ `members.sales=[]`、`memberNotes.sales` 說明；反向控制測試：同一案件清空業務負責就會退回報價人 |
| D3 | 舊版項目式獎金路徑：**凍結不處理** | **正式機回覆（2026-11-06，經窗口轉達）**：舊路徑相關表（`bonus_awards`、`bonus_award_lines`、`bonus_items` 等）全部 0 筆，從未有 `person_source='sales_person'` 的紀錄，`/awards/plan` 在正式機等於從未啟用；正式機唯一有資料的分潤是新版 `bonus_case_awards` 1 筆（MQ-202607-023）。⇒ 不為它設計相容方案；`_case_people()` 與 `PERSON_SOURCES` 註解標「凍結、仍讀報價人、日後啟用要先回頭決定」，程式未動 |
| D4 | 鍵名保留 `'sales_person'`，只改解析邏輯 | 鍵名與 `bonus_items.person_source`／`person_source_snapshot` 歷史列未動；測試鎖鍵名仍在 |
| D5 | 尚無分潤單、兩欄不同：**不主動通知**（**未採我原本「人工告知」的建議**；理由：建單時自然會看到） | 無通知程式 |

**留痕**：`modules/payroll/bonus.py::PERSON_SOURCES` 註解並列 ①2026-09-23 使用者原話（逐字，未刪）②2026-11-06 產品負責人裁示（含依據、推翻的是「讀哪一欄」而非「兩欄各自存」）與 D1～D5、D3 正式機回覆；`test_person_sources_comment_keeps_both_rulings_and_legacy_path_is_marked_frozen` 鎖「兩個日期、舊原話、凍結、鍵名」都在。同步更新：`api/bonus.py` `_auto_members`／`_case_people` docstring、`docs/windows/SPEC-BONUS.md` §11.7（原文留著、加更新段）、`docs/quick/known-limits.md` §11 新列、payroll `CHANGELOG.md`。`db.py` 的 `_m103`／`_m113`（凍住的歷史）未改。

**畫面文字**：案件管理頁角色下拉說明與不同人提示條，在同一版補上「業務獎金依此欄位」（測試 `test_hint_and_note_state_bonus_follows_sales_owner_now_that_bonus_code_switched` 鎖：畫面這樣說，程式就必須真的這樣做）。

**驗證**：`modules/payroll/tests/test_bonus_sales_owner_2026_11_06.py` 29 題；還原 `_auto_members` 後 24 題轉紅（反向控制）。不被寫入：預覽與建立分潤單前後 `quotations.sales_person`／`sales_person_id` 位元組相同。

**提醒（來源）**：新裁示來自產品負責人，經窗口轉達，不是使用者本人逐字；程式註解與文件都照實寫「產品負責人裁示（經窗口轉達）」。
