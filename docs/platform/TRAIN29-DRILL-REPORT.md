# 第 29 班套用演練報告（TRAIN29-DRILL-REPORT）

- 日期：2026-10-01（演練時間 21:31～21:36）；負責：W1；工具：`tools/platform/drill_train_apply.py`；計畫：`docs/platform/plans/TRAIN29-DRILL.md`
- 基線：`0bb4834e`（第 28 班）全新安裝＋合成資料（40 張報價單、109 開發案、64 傳票／151 分錄、12 筆舊額外支出含 4 個附件、稽核 3350 列、4 個總帳開關）；新版：包 `20261001_212935_47db5613_full`（commit `47db5613`，prod 金鑰簽章，驗章用 `0bb4834e` 內建公鑰；`package.sha256` 71245f7d…c133 相符；`verification.mode=full`）。
- 環境：`D:\開發測試檔\drill-t29\`、埠 6760、只用合成資料、未碰正式機資料庫與金鑰；演練完已停服務並刪除安裝與暫存。

## 結果：PASS（A、C、E、B 全過；第 29 班專屬判準全過）

| 場 | `::RESULT::` | 耗時 | 重點 |
|---|---|---|---|
| 交付 | stage／verify_staged／`verify_package --expect-db-version 116` | — | 全過，無 problems |
| A 套用 | `success／applied／up` | 26.1 s | 見下表 |
| C 資料庫回滾（僅演練） | `rollback_ok／restored／up` | 14.6 s | 回到 `0bb4834e`；schema 版本回 2/2/2（case／accounting／payroll）；三個新表消失；舊資料列逐列相同 |
| E 回滾後重套 | `success／applied／up` | 22.8 s | migration 重跑無錯；A 的 6、9、10 項重驗全過 |
| B 只回程式 | `rollback_ok／restored／up` | 16.2 s | 舊程式對已 migrate 的庫：ping 200、無 Traceback、舊式額外支出建立＋送審照常（200）；新表／欄位留在庫裡（預期） |

## A 套用後檢查（計畫 §5）
版本＝`47db5613`；ping 200；`/openapi.json`、`/docs` 404；模組全 loaded、版本變化＝包內與基線差集（accounting 1.1.45→1.1.49、analytics 1.0.20→1.0.22、arap 1.0.31→1.0.33、case 1.0.45→1.0.61、crm 1.0.15→1.0.16 等）、新增 filehub；log Traceback 0；單一監聽 PID；**schema：case=3、accounting=3、payroll=3、core=6、DB 版本 116**；新表 `expense_categories／gl_dimensions／user_bank_accounts` 存在、`voucher_lines.dim_json` 預設 `{}`；`case_extra_expenses` 新欄位齊全與兩個新索引（`idx_case_extra_exp_doc_code`、`idx_case_extra_exp_kind_status`）；六個筆數不變、12 筆舊額外支出 `id／狀態／金額／附件清單` 雜湊不變且新欄位皆為預設（`kind=''` 等）；總帳開關 4 列不變；新頁與 `definition-form.js` 存在；未登入打 `/api/expense-types`、`/api/expense-categories`、`/api/filehub/search`、`/api/definition-kinds`、`/api/settings/approval-doc-types` 皆 401；重啟冪等（4.6 s 起來、schema 不變、無錯）；**舊附件逐檔開啟 200 且大小一致（含舊資料夾 `quotation_settlement_extra`）**；舊流程建立＋送審 200。

## A′ 首次登入：費用類別清單為空（使用者裁示選項 A）
`GET /api/expense-categories` → 200 `{"categories": []}`；無類別時費用單據**草稿可存（201）、送審成功（200）**，金額照算（321），明細類別為空不編造；新增類別 `DRILL_TRAVEL` 後清單出現、送審成功且明細寫入 `categoryCode／categoryName`；有類別後送一個不存在的類別 ⇒ 400「不是啟用中的類別」（嚴格驗證恢復）；超級管理員全域檔案中心 200。表單層（類別欄不必填＋說明字＋抓不到清單維持必填）由 `test_e2e_expense_form_a24`（含反向控制）驗，修正 `4fd54996` 已在包內。

## 未涵蓋
- D（模組載入失敗自動回滾）、F（migration 乾跑擋下）需要變體包，工具未支援，本輪未演練（前一輪模組更新演練已證明該機制；本班新增的是 3 個 migration，C／E 已驗其冪等與回滾）。
- 不驗：HTTPS 憑證路徑、Remote Control 回報、Google Drive 路徑、正式機資料量下的 ALTER／建索引耗時（演練量級小，不外推）。
- 非 admin 角色的選單／403 行為（A′ 第 4、5 項）由各自的單元／e2e 測試覆蓋，演練未重做。

## 缺陷
無擋上線缺陷。工具本身的排練期間修過 5 個環境問題（記於 `drill_train_apply.py` 註解）。
