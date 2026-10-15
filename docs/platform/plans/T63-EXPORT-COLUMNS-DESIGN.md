# T63 匯出欄位框架化：案件批次匯出＋出納執行紀錄（設計筆記）

> 日期：2026-10-14　基底 `origin/wip/t62-int-c1`（57cbd5674）　分支 `wip/t63-export-cols-r1`　狀態：設計＋實作同批；**沒有跑任何測試**（全機閘門期間只做編輯與 py_compile／import 檢查）。
> 對應 `quote-case-finance-coupling.md` §4 切片 5。沿用 BP-3 匯出範本 kind（`helpers/export_templates.py`），**不新增 kind、不新增路由、不新增旗標**（沿用 `builder_exports.enabled`＋`builder_governance.enabled`，預設關）。

## 1. 目錄登記（模組自己登記，使用者不能新增）
| 匯出代號 | 類型 | 內容 | 所在 |
|---|---|---|---|
| `case:case-batch` | 欄位型（xlsx；PDF 姊妹跟著走） | 11 欄：單號、客戶、專案、狀態、目前階段、階段進度、逾期階段、業務、執行負責、成員、金額 | `modules/case/api/quotations.py::case_batch_export` |
| `arap:cashier-history` | 工作表型（xlsx；PDF 姊妹跟著走） | 4 張：已匯款明細（必選）、支出申請付款明細、已收款明細、獎金發放明細；全部標 money | `modules/arap/api/cashier.py::export_execution_history` |

- 案件匯出：欄位可挑、可換順序、可改標題（沒有匯入回來的流程 ⇒ `lock_labels=False`）。`金額` 欄標 `money` 並帶 `visible=quote_money_visible`：沒權限者**整欄省略**（今天是欄位在、儲存格空白；範本開啟後整欄不出現——更保守，且預覽會註明）。
- 出納匯出：只選『要哪幾張』（沿用營運報表 `sheets` 機制與放寬規則：加回含金額工作表＝放寬，需第二位最高管理者核准）。**不做欄位型**：三張表各有合計列、數字格式、欄寬都綁欄位位置，挑欄會讓合計與格式錯位；列為後續（見 §4）。
- 目錄預設範本＝今天的全部欄位／全部工作表。

## 2. 執行期掛鉤（OFF 必須逐位元相同）
- `resolve()`／`disabled_sheets()` 在旗標關、沒有已發布範本、任何錯誤 ⇒ `None`／`[]` ⇒ 端點走**原本那段程式**，沒有重構既有路徑（案件匯出保留原 `ws.append` 迴圈；範本路徑是旁支）。
- 案件匯出範本路徑：欄位清單來自 `effective_columns`（遮蔽優先再驗一次），儲存格值與原本同一份查詢與同一個 `cell()`（`xl_safe_xlsx`）；數字（金額）原樣、空值寫 None（避免 inlineStr）。
- 出納匯出：產生完整活頁簿後，把沒選到的工作表整張移除（與營運報表 `_drop_excel_sheets` 同一手法）；選項讀取失敗 ⇒ 只留必選（關起來，不整份外送）。
- 稽核不變：`@export_logged(...)` 與案件匯出內的 `_audit("case.batch_export")` 都在原位；出納的 `check_export_rate`、`_require_view_access` 在讀範本**之前**。

## 3. 耦合清單與刻意不動
| 項目 | 處理 |
|---|---|
| `export_logged` 稽核、匯出冷卻 `check_export_rate` | 不動，位置不變 |
| 金額欄伺服器端遮蔽（案件：`quote_money_visible`；出納：`_require_view_access` 先擋＋`bonusVisible` 決定獎金表） | 不動；範本只能再減不能加，欄位值仍來自同一查詢；獎金發放表在 `bonusVisible=False` 時即使被選也不會產生 |
| `row_access` 案件可見範圍（`filter_sql("case")`） | 不動 |
| `xl_safe_xlsx`／`csv_safe` | 案件範本路徑每格仍經 `cell()`；欄位標題經 `render_rows` 同一套驗證 |
| PDF 姊妹 `add_pdf_sibling` | 呼叫的是同一個函式 ⇒ 自動跟著範本；不另外改 |
| `user_buttons.BUTTON_EXPORTS` 允許清單（現為 `subcontract:roster`） | **不新增**。這兩個匯出不是按鈕候選（案件匯出是 POST＋勾選清單、出納匯出有日期參數，都不符「無參數單純路徑」）；要變按鈕須另行審查 |
| 稅務匯出（tax401／tax-export）、T100 | 不動，未登記為可自訂 |
| 路由／response keys／l1 介面快照 | 不新增路由；`route_inventory`、`response_keys_baseline` 預期不變 |
| 設定中心旗標 | 不新增 |
| 案件頁／出納頁前端 | 不動 |

## 4. 沒做（後續）
1. **報價單自訂欄位（q3）當匯出欄位**：目錄是模組登記的靜態清單，自訂欄位是管理者動態定義；需要『動態目錄＋dataClass 檢查＋治理比較』，且 q3 的值路徑（data_json）在批次匯出的 SQL 沒讀。獨立一刀，需先決定『自訂欄位出現在內部匯出是否算放寬』。本刀不做，也沒有留半成品鉤子。
2. 出納三張明細表的欄位型自訂（需先把合計列／數字格式從位置改成依欄位 id）。
3. 搜尋、批次匯出以外的報價單匯出。

## 5. 驗證（待閘門結束後）
- 單元：目錄登記（兩個 id、欄位／工作表清單與今天逐字一致）；預設範本通過 `definition_problems`；OFF 輸出與基準逐格相同（案件匯出、出納匯出各一）；無金額權限者範本路徑整欄省略；出納範本拿掉 `incoming` 後只剩其餘工作表；讀不到旗標 ⇒ 只剩必選。
- 現在只做了：py_compile／import 檢查。
