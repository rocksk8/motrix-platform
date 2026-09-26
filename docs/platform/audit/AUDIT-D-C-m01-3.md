# 稽核：C 的 M01 ①——CA-O4：L1 不再 import M01、pdf_gen 不寫 quotations（wip/c-m01-3 b3b3b9aa；疊在 c-approval-3 上）（D，2026-09-26 19:53）

> 完整稽核（L1 與 M01 的邊界）。稽核者 D 沒有寫過任何受稽核的程式碼。
> 對象：`104cefe9`、`b3b3b9aa`。內容：
> - `helpers/__init__` 不再轉出 M01 的名稱；`summarize_payment_items` 下沉 `tax_calc`。
> - pdf_gen 的版本紀錄改經 `case.doc_version`；system 的預設條款改經 `case.default_terms`；won_month_map 改經 case.recognition。
> - KNOWN_L1 的 pdf_gen 從 rw 縮成 r；新題 `test_l1_does_not_load_m01`、`test_m01_l1_providers`；CORE 1.43。

## 0. 結論

- **必修 0**。主持的四點都成立。

| 主持的問題 | D 的驗證 | 結果 |
|---|---|---|
| L1 對 M01 的 import 是否全部切斷（不取出 M01 時 L1 能不能 import） | D2 樹**實際刪掉 M01 的 11 支 .py**（completion_pdf、helpers/{case_deadlines, case_stage_tasks, quotations, quote_terms, recognition}、routers/{case_action_items, case_extra_expenses, completion_notes, material_orders, quotations}）並清掉 pyc，逐一 import modules.json 的全部 L1 Python 單位（core／helper／router／**plat**，`main` 除外） | **80 個、失敗 0**。比新題更嚴：新題是 M01 的檔還在時看 `sys.modules`，而且沒有探 `plat:`（core/）單位 |
| pdf_gen 回寫改由 M01 提供之後，M01 不在時會怎樣 | 讀碼＋新題 `test_doc_version_without_m01_is_skipped`：沒有提供者 ⇒ return（PDF 已存、不記版本）。突變 K2「沒有提供者時丟例外」存活，但屬**等價突變**：外層 `except Exception` 本來就吞掉並寫 log，結果相同 | 成立 |
| KNOWN_L1 的 pdf_gen 從 rw 縮成 r 是否正確 | `grep`：pdf_gen 對 quotations 只剩兩處 `SELECT data_json, status, deal_tag, location_id`，沒有任何寫入 | 正確 |
| 過期守門有沒有如預期觸發 | 突變 K1：KNOWN_L1 改回 `"rw"` | 紅（`test_known_l1_baseline_is_not_stale`）⇒ 會觸發 |

- 基準：tests/platform 1219 過。
- 突變 K3「helpers 再轉出 `quotations.save_quotation_json`」⇒ 紅（`test_importing_every_l1_unit_loads_no_m01_unit`）。

**觀察 M013-O1**：`test_l1_does_not_load_m01` 的 `_unit_to_module` 不含 `plat:`（core/ 底下），core 的單位沒有被探到。D 的實刪結果顯示目前沒有問題，但之後 core/ 若 import M01，這一題抓不到。建議把 plat 納入。
