# 案件管理「業務：X」與「業務負責下拉：Y」不一致——查證報告

> 2026-11-06｜唯讀查證（未改任何程式）｜基準：`76d3e2d07`（train/t76-int 工作樹）｜行號以該 commit 為準
> 限制：開發機 DB（`backend/motrix_erp.db`）是空的（quotations 0 筆），**沒有看到正式機資料**；凡涉及「那幾張案件實際值」的一律是程式碼推論，需正式機 Claude 查證（§7）。

## 1. 結論

**資料模型是設計如此（兩個獨立概念，起源於初始提交），但 UI 命名讓它看起來像同一件事——是「標籤／說明缺口」，加一個「獎金與績效可能指向不同人、沒有任何提示」的設計空洞，不是同步漏寫。**

- `quotations.sales_person`／`sales_person_id`＝**報價單上的「報價人」（開單的人）**。只有報價單存檔會寫它；案件頁編輯人員角色**完全不碰**它。
- `caseRecord.roles.sales`＝**「這個案子的業績歸誰」**。使用者 2026-09-14 親口裁示營運報表讀它、2026-10-01 部門也跟它（見 §3）。
- 兩者從 2026-07-17 初始提交就並存（初始提交的 case-management.html 已有「負責業務＝`selected.sales_person`」與「業務負責＝`roles.sales`」兩處）；**不是 CM3 引入**。CM3（2026-09-24）只把 roles 的值形狀從字串改成 `{username, display}`。
- 補充排除（產品負責人第二則）：清單卡片的「業務：」**是逐筆讀各案自己的 `sales_person` 欄**，不是登入者或固定值（§4）。多張卡片同名＝那幾張報價單的報價人真的都是黃玉龍（例如同一位負責人代開），需用正式機資料確認。

## 2. sales_person 的來源與寫入者

| 事項 | 位置 |
|---|---|
| 值來源 | 報價單表單「報價人」（`quotation-form.html:1212-1227`，欄名 `q.salesPerson`；**僅草稿或解鎖編輯時可改**，其餘唯讀；選到別人會標「代理」） |
| 寫入端點（僅兩支） | `POST` 建立（`modules/case/api/quotations.py:1718-1727`）、`PUT` 更新（同檔 `:2430-2439`）；皆寫 `sales_person=q.salesPerson` |
| `sales_person_id` | 同兩處，由 **`display_name` 反查 active 使用者**（`:1675-1680`、`:2250-2255`），不是用表單的 `salesPersonUsername`；同名或查無 ⇒ `NULL` |
| 其他寫入 | 僅 DB 遷移：`db.py:1097`（改名統一）、`:1160`（m010 由 display_name 回填 id） |
| 案件頁寫的是 | `update_case_record`（`:3479-3720`）只改 `data_json.caseRecord`；**全檔沒有任何 `SET sales_person`** 來自這支 |

## 3. 兩個欄位各自被誰使用（受影響範圍）

| 使用面 | 讀 `sales_person(_id)` | 讀 `roles.sales` | 依據 |
|---|:-:|:-:|---|
| **業務獎金**（單項獎金 `people_for_item` 來源 `sales_person`；案件分潤 `_auto_members`「業務」） | ✅ | ❌ | `payroll/bonus.py:234-255`（註明「使用者原話逐字定的：業務獎金→`sales_person`」）、`payroll/api/bonus.py:1100-1145, 1203-1230` |
| **營運報表：業務員績效／部門績效／目標達成率／首頁統計** | 退路（`roles.sales` 沒填才用） | ✅ 優先 | `analytics/api/reports.py:206-248, 278-285`；2026-09-14、2026-10-01 使用者裁示（`docs/quick/known-limits.md` §11、`changelog.md:1099,322`） |
| **列表可見度／案件可讀**（row-access） | ✅（`sales_person_id`；NULL 時比顯示名） | ❌ | `helpers/case_access.py:101-110`（`CASE_ACCESS` 只含 owner＋`assigned_user_ids`） |
| **編輯權（案件成員）** | ✅ | ✅ | `quotations.py:444-475 _is_case_member` |
| 「我負責的」篩選 | ✅ | ✅ | `quotations.py:812-818 _CASE_MINE_SQL` |
| 清單卡片「業務：」、詳情頭「負責業務」 | ✅ | ❌ | `case-management.html:377, 585` |
| 人員角色「業務負責」下拉 | ❌ | ✅ | `case-management.html:759-760`、`case-management-biz.js` |

**不連動的實際後果（兩者指向不同人時，例：報價人＝黃玉龍、業務負責＝高晟耀）：**

1. **獎金給黃玉龍、業績算高晟耀**：同一案件，營運報表把業績與部門記在高晟耀，業務獎金卻發給黃玉龍。這是金額面最大的落差；是否為使用者本意**沒有找到明文裁示**（只找到「報表讀 roles.sales」與「獎金讀 sales_person」兩條各自的裁示，兩者從未被放在一起比較）。
2. **高晟耀可能看不到這張案件**（推論，未實測）：row-access 不含 `roles.sales`；若高晟耀不是 admin、不是 `sales_person_id`、也不在 `assigned_user_ids`，列表／詳情對他是 404，卻會被記為這案的績效歸屬。反向：他若看得到（被指派），才會是成員。
3. 報表與案件頁頭顯示兩個不同的人，使用者以為是資料錯誤（本次回報）。

## 4. 排除「清單卡片誤繫同一個值」

- 後端清單 `list_cases`（`quotations.py:~870-1047`）：`SELECT … sales_person …` 逐列取欄，`items.append(dict(row))`，沒有以登入者覆寫。
- 前端：`case-management*.js` 內**沒有任何對 `sales_person` 的指派**（唯一出現是 `case-management-list.js:126` 的 `r.salesPerson` 篩選，與顯示無關）；卡片 `x-text` 直接綁每個 `c.sales_person`；`lLabel('sales','業務')` 只換標籤文字。
- 詳情頭：`selected` 來自 `/case-bundle` → `get_quotation` → `SELECT *`，同一欄位（`case-management-core.js:377`、`quotations.py:1342-1351`）。
- 結論：**程式沒有誤繫**。若截圖中多筆都是「黃玉龍」，是資料（那幾張報價單的報價人欄）如此。要確認需在正式機跑 §7 的唯讀查詢。

## 5. 這個落差何時產生

- 兩欄並存＝初始提交 `2c5f02f75`（2026-07-17）。**無單一 T 編號引入**；是最初設計的兩個概念，後續各面向各自裁示：
  - 2026-09-14（第十四輪）：報表業務員績效改讀 `roles.sales`；
  - 2026-09-23（QS1-a／BN）：獎金明定讀 `sales_person`，並解析成帳號；
  - 2026-09-24（CM3／CM14）：roles 改存帳號物件；編輯權加入 roles；
  - 2026-10-01：部門歸屬跟 `roles.sales`。
- 因此「報表／獎金／可見度三邊各讀不同欄」是逐步形成，沒有哪一班疏漏，但也**從未有一份文件把三者並列比對並由使用者拍板**。

## 6. 修法選項與風險

| 選項 | 做法 | 風險 |
|---|---|---|
| **A. 只改 UI 命名（建議先做，零資料風險）** | 清單／頭部標籤改「報價人」；下拉改「業績歸屬（業務負責）」並加一句說明「獎金依報價人計算」；若兩者不同，案件頁顯示一個提示條 | 不改任何計算；低風險。解決「看起來不一致」，不解決 §3 的 1、2 |
| **B. 清單／頭部改顯示 `roles.sales`（沒填退回報價人）** | 比照 `_case_sales_owner()` 的優先序，前端與清單 API 共用同一解析 | 卡片與獎金／可見度仍分歧，只是把不一致移到別處；清單依「業務」搜尋／篩選語意要一併決定 |
| **C. 兩者併成單一欄位** | 下拉寫回時同步 `sales_person`／`sales_person_id`（或反向） | **獎金方向風險最高**：改寫 `sales_person` 會直接改變 `_auto_members` 與單項獎金的發放對象；已精算／已發放的案件被回溯改人。必須：①使用者先明確裁示以哪個為準；②只對未精算案件生效；③已有獎金分潤列（`bonus_award_lines`）不得被改；④舊資料（roles.sales 未填者）不回填；⑤同名帳號不猜。另需處理「報價人是代理開單」這個合法情境（開單者≠業績歸屬）——併成單一欄位會讓它消失 |
| **D. 維持兩者、補可見度規則** | 把 `roles.sales` 納入 `CASE_ACCESS`（`id_list_cols`／新增來源） | 擴大可見範圍＝安全面改動（M01-O1、CM14 系列守門測試會紅，需重驗）；只解決 §3-2 |
| **E. 獎金改讀 `roles.sales`** | 與報表同口徑 | **方向風險**：違反使用者原話「業務獎金→sales_person」；金額面影響；未經使用者裁示不得做 |

建議順序：先 A（立刻消除誤會）；§3-1 的「獎金 vs 業績是否該同人」交使用者裁示後，再決定 C／E 是否需要；任何涉及獎金的改動都要先出「受影響案件清單」（`sales_person` 與 `roles.sales` 帳號不同者）給使用者過目。

## 7. 待正式機 Claude 唯讀查證（只讀，不寫）

```sql
-- 1) 清單那幾張的實際欄位
SELECT quote_no, customer_name, sales_person, sales_person_id,
       json_extract(data_json,'$.caseRecord.roles.sales') AS roles_sales
FROM quotations WHERE customer_name LIKE '%小林%' OR customer_name LIKE '%凱悅%'
   OR customer_name LIKE '%比漾%' OR customer_name LIKE '%大綜%';
-- 2) 全量落差規模（兩者帳號不同的案件數）
-- 以 Python 逐筆解析 data_json（新程式不寫 json_extract，見 test_json_extract_ratchet）：
--   roles.sales.username（或舊字串反查）≠ users.username(sales_person_id)
-- 3) 其中已有獎金分潤列的案件數（bonus_award_lines）
```
