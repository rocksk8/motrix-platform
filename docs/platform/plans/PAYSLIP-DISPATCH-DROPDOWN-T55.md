# 勞報單「選派發」下拉選單——範圍盤點（第 55 班，唯讀盤點，未改程式）

作者：05。基底 `origin/platform` c14f0a1df。需求（使用者經 node-d8 轉述）：勞報單表單要能用下拉選單選擇所屬的承攬商派發。

## 0. 結論先行
- **已有一半**：新增勞報單時，選了外包名冊人員就會列出「這位人員的派工」勾選清單（第 48／51 班，`payslip-form.html` + `GET /api/payslip-person-dispatches`）。**缺口有三**：①已建立的勞報單，連派發只能在 `payslips.html` 詳情**手打派發編號**（數字）；②沒選名冊人員（手打姓名）就沒有清單；③沒有搜尋，派發多了無法找。
- 建議做法：新增一支 M04 提供者 `dispatch.search`（加法）＋ M07 一支搜尋端點，兩個畫面都改成「可搜尋的下拉」。**連結資料模型、簽核流程、匯款流程都不動**。
- 工作量 **約 4 人日**（含測試與稽核補件）；風險低（見 §4）。

## 1. 今天怎麼建立連結（已查實）
| 入口 | 端點 | 誰能用 | 限制 |
|---|---|---|---|
| 勞報單新增表單（勾選清單） | `POST /api/payslips`（`dispatchIds`，相容舊 `dispatchId`）；清單來自 `GET /api/payslip-person-dispatches?contractor_id=` | 最高管理者＋勞報單模組 | 必須有 `contractor_id`；派發須存在且人員名單含此人，否則 400 整張不建；與勞報單**同一交易**；清單不含草稿／已取消，**無金額** |
| 勞報單詳情（手打編號） | `POST /api/payslips/{slip_no}/dispatch-links` `{dispatchId}` | 最高管理者＋勞報單模組 | 只驗派發存在、勞報單未作廢；**不驗人員名單**（可連到與受領人無關的派發）；已存在 ⇒ 409 |
| 派發頁（案件管理） | `POST /api/contractor-dispatches/{did}/payslip-links` `{slipNo}` | 最高管理者 | 同上，單號手打 |
| 從派發頁「新增勞報單」 | `payslip-form.html?dispatchId=` | 最高管理者 | 名單只有一位名冊人員時預選，建立時帶 `dispatchId` |
- 解除：`DELETE …/dispatch-links/{id}`，勞報單**已付款（含經匯款單付款）不可解除**。
- 稽核：`payslip.dispatch_link`／`payslip.dispatch_unlink`（勞報單側）、`dispatch.payslip_link`／`dispatch.payslip_unlink`（派發側），已有。
- 資料：`payslip_dispatch_links`，唯一鍵 (slip_no, dispatch_id)；**多對多**（一派發對多勞報單、一勞報單對多派發，P3 設計）。

## 2. 下拉選單需要什麼
1. **清單來源（新）**：M04 提供者 `dispatch.search(conn, q, contractor_id=None, limit=30, user=None)`（registry 單一提供者，加法；M04 不在 ⇒ 下拉顯示「外包工班模組未安裝」，沿用 `DISPATCH_MISSING`）。M07 端點 `GET /api/payslip-dispatch-options?q=&contractor_id=&include_all=`（最高管理者＋勞報單模組，同勞報單其他端點）。**M07 不 import M04**。
2. **權限／範圍過濾**：勞報單端點本來就只有最高管理者，所以「誰能看」不是問題；仍沿用 `dispatches_for_person` 的做法——案件名稱只給通過 `guard_case_access` 的人，其他只顯示單號；**不回金額、身分、銀行**（Q9 原則不變）。
3. **大量派發的搜尋**：伺服器端搜尋＋分頁（預設 30 筆，新到舊）；搜尋欄位＝派發編號 `doc_code`、案件單號 `quote_no`、廠商名、案件名稱／客戶（僅有權限者）。`LIKE` 在上述欄位上，派發量級（千筆內）不需新索引；若超過再評估 `quote_no` 索引。前端用輸入即搜（延遲 300 ms）的「可搜尋下拉」，不是一次載入全部。
4. **只列可連的**：預設 ＝ 人員名單含該受領人、狀態不是草稿／已取消、**且尚未連到這張勞報單**。已連到「別張未作廢勞報單」的標「已有勞報單」但仍可選（一派發對多勞報單是設計，例如分期付款）。需要時「顯示全部派發」開關才跳出名單限制（給沒選名冊人員的勞報單用）。
5. **一對一還是一對多**：維持**多對多**，不改資料模型（改了要動 migration、回收桶快照、匯款單相容，且與 P3 設計衝突）。
6. **回收桶／已取消**：
   - 派發進回收桶 ⇒ 連結列已被 `delete_for_dispatch` 移除，下拉自然看不到（查詢本來就查 `contractor_dispatches`）。還原時 `restore_rows` 補回連結（既有行為）。
   - 派發 `cancelled`：預設不列；若已有連結，詳情仍顯示（含「已取消」徽章），可解除。
   - 勞報單作廢：連結保留並標已作廢；下拉在作廢單上隱藏（現況：作廢單不能新增連結）。
7. **稽核**：沿用既有 4 個動作碼，**不新增**；補一筆建議——選擇下拉時寫入的 `note`（來源：`下拉選取`）不需要。唯一要補的是：從「顯示全部」跳出名單限制選到**人員名單不含受領人**的派發時，稽核細節註記「名單外」，讓事後查得到（見 Q3）。
8. **伺服器端守門**：`POST dispatch-links`（詳情入口）目前不驗人員名單；下拉只是前端提示，**不能當守門**。若使用者要「名單外不可連」，需在 `add_link` 加與 `create_payslip` 同一條檢查（見 Q3）。

## 3. 會動到的檔案
| 檔案 | 改動 |
|---|---|
| `backend/modules/subcontract/api/dispatch_payslip_links.py` | 新 `dispatch_search()` 提供者函式（同檔已有 `dispatch_brief`、`dispatches_for_person`）；`__init__.py` 註冊 `dispatch.search`（IP 號待列車取號，暫記 IP-116） |
| `backend/modules/payroll/api/payslip_links.py` | 新 `GET /api/payslip-dispatch-options`；（若 Q3 選「名單外不可連」）`add_link` 加名單檢查 |
| `backend/modules/payroll/payslip_links.py` | 小：回傳「已連到哪些勞報單」的旗標（`linkedForThisPerson` 同一做法） |
| `frontend/pages/payslips.html` | 詳情「來源派發」：手打編號欄改成可搜尋下拉（`linkInput` → 選取物件） |
| `frontend/pages/payslip-form.html` | 新增：沒選名冊人員時也能搜尋（原勾選清單保留）；編輯模式（今天沒有連結區）加入同一個下拉（可選，Q4） |
| 版本說明、兩模組 CHANGELOG（`## (next)`）、`docs/platform/INTEGRATION-POINTS.md`（新 IP）、`module.json` 提供者宣告、`route_table_golden.json`（新端點） | 規定動作 |
| 測試 | M04 提供者（搜尋／狀態過濾／名單／回收桶不出現／不含金額）、M07 端點（權限 403／M04 不在／分頁）、e2e（輸入搜尋→選取→出現在詳情與派發頁） |
- 還要確認：`FORM_VERSION` 規則只管 `quotation-form.html`，勞報單頁不需要。
- 文字走使用者語言：「選擇所屬派發」「搜尋派發編號、案件或廠商」；不顯示 `dispatchId`／狀態碼，狀態用既有人話徽章。

## 4. 對勞報單簽核流程的風險
- 連結**不在** `approval_json`、也不參與金額與扣繳計算、匯款單 `personnel[].payslipNo` 與連結互不依賴（`payslip_links.py` 檔頭已明載）。下拉只是換掉輸入方式，**不改簽核、付款、核准規則**，也不碰剛上的「簽核人死鎖例外」（`_deadlock_bypass`）。
- 已確認的邊界：連結可在「待審核／已核准」時新增（今天就是如此，`link()` 只擋作廢）；只有**已付款**才擋解除。維持現狀，不在本案放寬或收緊。若使用者希望「送審後不可再改派發」，那是**政策變更**，另案（走欄位政策設計 DOC-FIELD-POLICY 的格子，不在這裡寫死）。
- 風險點只有兩個：①搜尋 `LIKE` 組字串——一律參數化；②「顯示全部」讓人連到無關派發——靠 Q3 的決定與稽核註記。
- 回收桶守門：不新增任何 `DELETE FROM payslip_dispatch_links`（連結列唯一刪除點仍是 `_delete_links`），守門基線不需更新。

## 5. 工作量（人日）
| 項目 | pd |
|---|---|
| M04 提供者 `dispatch.search`＋測試 | 0.75 |
| M07 端點＋（選配）名單守門＋測試 | 0.75 |
| `payslips.html` 可搜尋下拉（含 e2e） | 0.75 |
| `payslip-form.html` 搜尋＋編輯模式連結區 | 0.75 |
| IP 登錄、dep_graph／module.json／route golden、CHANGELOG、版本說明 | 0.5 |
| 非作者稽核補件、回歸（派發頁雙向顯示、回收桶還原） | 0.5 |
| **合計** | **約 4**（只做 `payslips.html` 下拉＝約 2.25） |

## 6. 要問使用者的問題（一題一決定）
1. **選項範圍**：下拉預設只列「這位受領人在名單內、已派出（非草稿／取消）」的派發，另有「顯示全部」開關可搜尋所有派發嗎？〔建議：是；沒選名冊人員時自動等於顯示全部〕
2. **已有勞報單的派發**：已連到別張勞報單的派發，是照常可選（標「已有勞報單」，一派發可對多張，例如分期付款），還是隱藏？〔建議：照常可選＋標示；資料模型維持多對多〕
3. **名單外的派發**：用「顯示全部」選到人員名單不含這位受領人的派發，是允許（稽核註記「名單外」），還是禁止（與新增勞報單時同一規則）？〔建議：禁止，與新增時一致；真有例外再由管理者在設定中開放〕
4. **放在哪裡**：只改「新增勞報單」表單，還是同時把已建立勞報單詳情裡的「手打派發編號」也換成下拉？〔建議：兩處都換——手打編號正是最容易連錯的地方〕
