# AUDIT-D：wip/cloud-rowaccess-empty-name（fef26fa5，基底 70ec2523）

2026-09-29｜依 8c34f08a：以作者結果為準，只跑探針與突變。**必修 1 項（測試缺口）；建議 1 項。**

## 已驗
- 行為修正正確：`_legacy_name` 空／None ⇒ None；`visible` 與 `filter_sql` 同一條件（SQL 不再產生該項）；admin／cashier 直通、id／協作者／建立者規則不動；案件端點都經 `row_access`（`case_access` 登錄）⇒ 修正對清單、單筆、404 遮罩都生效 ✔
- 新題與舊題共 58 過（自跑）；突變：`filter_sql` 還原成舊寫法 ⇒ 6 題紅 ✔（已還原）
- CORE 1.69 暫號、interface snapshot 只動版號 ✔

## 必修
### RA-M1 凍結舊實作的比對，「扣格」寫得比「那一格」寬，且測資沒有能證明它不遮東西
`_minus_intended_change_2026_09_29f` 對顯示名稱空且非 admin 的使用者，從舊結果扣掉**所有** `sales_person_id IS NULL AND sales_person=''` 的列，沒有排除「該使用者本來就靠別條規則看得到」的列（協作者 `assigned_user_ids` 含自己、cashier 讀取直通）。此刻不出事，只因測資裡空名稱使用者（id 3）不在任何 `assigned_user_ids`，且 cashier 使用者名稱非空。
**自做突變**：把扣格 SQL 放寬成扣掉**所有** `sales_person_id IS NULL` 的列 ⇒ `test_row_access_2026_09_25.py` 50 題**全過**。即：舊比對測試沒有能力偵測「新實作把別的可見列也收掉了」（這正是凍結比對存在的目的：只准差那一格）。新增的 `test_row_access_empty_name_2026_09_29.py` 也沒有「舊案件（id NULL、名稱空）＋自己是協作者」這列（其協作者列的 sales_person_id 非 NULL）。
**修法**：①扣格改成只扣「舊結果中、且該使用者不因協作者／建立者／bypass 而可見」的那些列（或在測資加入 `[3]` 的協作者列，使過寬的扣格會使比對失敗）；②新題加一列 `(NULL, '', '[7]')`，斷言空顯示名稱的協作者 7 仍看得到（visible 與 SQL 兩式）。

## 建議
### RA-S1 `_CASE_MINE_SQL`（quotations.py:730，「我負責的」快篩）同型未改
`(sales_person_id IS NULL AND sales_person=?)` 仍空對空相符。經核對它以 AND 疊在可見性之後（quotations.py:851 起「皆為 AND」），故對一般使用者不外洩；唯 cashier（讀取直通、可見性為空）且顯示名稱空時，「我負責的」會納入所有名稱空的舊案件。建議一併套同一規則（空 ⇒ 不產生該項），並讓凍結比對／新題守它。
