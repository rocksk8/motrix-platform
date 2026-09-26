# 稽核：A 的 M06 會計搬進 modules/accounting（wip/a-m06-2 25408f3f；合回前）（D，2026-09-26 22:06）

> 完整稽核（模組搬遷）。稽核者 D 沒有寫過任何受稽核的程式碼。
> 疊法：origin＋c-m05b-3＋c-ip14-paid＋attachments-4／-5（-6 的內容也在：`CaseNotVisible` 已在 modules/accounting）。
> M06 本包的 commit：26300708、ca70415e／cb8622d3／6dcf9623（到期守門）、cfc924bd（IP-22）、70e3262d（搬遷）、74e7a61c（邊界）、7e32c9b5、de4187fa、4b223e00、34384677、f2d43c3d、25408f3f。

## 0. 結論

- **必修 2、建議 2**。

## 1. 實測

| 項目 | 結果 |
|---|---|
| 題目盤點（搬遷前 70e3262d^ ⇔ 25408f3f，AST 比對每個 `test_*`） | 4441 → 4444，**消失 0**；搬家 307 題，其中 29 題本體有改，D 逐一看過 diff：**全是路徑、import 名稱或說明文字**（`routers.vouchers`→`modules.accounting.api.vouchers`、`parents[2]`→`[4]`、讀頁面改 `source_tree.page_file`），沒有斷言被削弱 |
| 函式層拆檔 | approval_settings_unify、case_cross_module_links、module_history、money_round_half_up、xlsx_out_l1 共 5 檔拆成兩處；第 6 檔依 commit 內文是 stock_batch_payment（小工具留原檔） |
| 「依 M06 在不在期望」的題 | M07 兩支（`test_bonus_case_live_recalc…:226／:277`、`test_bonus_case_multi_approver…:88`）：M06 在 ⇒ 有傳票、張數＋1；M06 不在 ⇒ `accrual_voucher_id` 為空、張數不變，另外都斷言獎金狀態 ⇒ **兩邊都是實質斷言**。T100 三處（receivables_providers、arap/subcontract_connectors、subcontract_providers）只把 T100 那一段包起來，題目其餘部分照常斷言。例外見 S2 |
| a' 例外的到期守門 | 突變 E1：在 subcontract 真的 `registry.provide("dispatch.cost_for_case", …)` ⇒ **紅**（`test_accounting_foreign_reads_expire_when_the_provider_exists`） |
| IP-22 `voucher.by_case` | quotations.py `case_bundle` 的傳票段改取提供者；沒有提供者時回 `{"ok": False, "status": 404, "detail": VOUCHERS_UNAVAILABLE}`；`test_case_bundle_without_m06`（拿掉提供者）與 `…_with_m06_lists_vouchers` 兩側都有題 |
| 基準（accounting_foreign_reads＋module_boundaries＋accounting_connectors） | 31 過 |
| **§B-11（D 獨立做，D2 真的刪 `modules/accounting`）**：tests/platform＋提到 voucher／accounting／t100／account_items 的 92 檔＋15 個 e2e 檔 | 收集 2042 題、無錯。非 e2e：1936 過、56 skip、**6 紅＝允許 5＋1**；e2e：40 過、**4 紅** ⇒ M06-M1 |

## 2. 發現

### 必修

**M06-M1　拿掉 accounting 之後有 5 題紅，而且不在 §B-11 允許清單內（與 A 自報「只剩允許的紅」不符）**

| 題 | M06 不在時的失敗 | M06 在時（D 在 D 樹重跑） |
|---|---|---|
| `tests/test_case_cross_module_links_2026_09_24.py::test_case_page_links_to_map_bonus_and_vouchers`（函式層拆檔，留在原檔的那一題） | `POST /api/vouchers` ⇒ **405** | 過 |
| `modules/arap/tests/test_e2e_t100_unconfirm_2026_09_10.py::test_t100_confirm_then_unconfirm_from_ui` | `wait_for_function` 逾時（T100 頁屬 M06） | 過 |
| `modules/payroll/tests/test_e2e_bonus_vouchers_page_2026_09_24.py` 的 3 題（`test_cashier_picks_the_bank…`、`test_superadmin_voucher_account_settings…`、`test_return_shows_the_notice…`） | 銀行下拉沒有選項（會計科目屬 M06）、等不到訊息、查 `vouchers_all` | 過 |

- 推測 A 的反向控制沒有選到這幾支 e2e，而 case_cross_module_links 拆檔時漏了這一題。
- 修法：各題「M06 不在」時略過並寫明原因，或者搬進 `modules/accounting/tests`。改完之後由 D 再做一次真刪。

**M06-M2　EM10 基準 139→135：這 4 條是被「移出計算範圍」，而不是被其他題接手（主持重點）**
- EM10 的 `_BASELINE_COUNT` 只算 modules/ 以外。D 實際跑同一支掃描器：總數 **157**，其中 modules/ 裡 **22** 條（accounting 4、payroll 4、tender_radar 7、analytics 3、arap 2、subcontract 2）。
- 「總數 157 不變」只寫在註解裡，**沒有任何斷言**。
- modules/ 裡只有 tender_radar 有自己的守門（`test_tender_platform_controls`）。accounting 這 4 條，以及先前搬遷的 arap、subcontract、payroll、analytics 共 11 條，**目前沒有任何計數守門**：刪掉其中一句，沒有題會紅。
- 修法（擇一）：
  - (a) EM10 另外斷言「已安裝模組各自的條數」，例如 `{accounting: 4, …}`，模組不在就不比。
  - (b) 比照 tender_radar，各模組在自己的 tests 釘自己的條數。
- 本包至少要把 accounting 的 4 條接住；其餘 11 條屬既有缺口，建議一併處理或另開。

### 建議

**M06-S1　邊界反向控制「起點耗盡要 fail」沒有題驗（B 已審的 f76534f2／74e7a61c）**
- 突變 G1（`pytest.fail` 改成 `pytest.skip`）與 G2（正對照允許空的起點）都存活。原因是現在 routers/ 底下還有 M01 的 router，起點不會耗盡，那條分支走不到。
- 建議補一題：monkeypatch `_cross_edge_candidates` 回空的起點，斷言 `_pick_new_cross_edge` 丟的是 `pytest.fail.Exception`（不是 skip）。

**M06-S2　`test_bonus_module_flag…::test_hiding_the_bonus_entry_does_not_hide_its_neighbours` 在 M06 不在時整題 skip**
- 真正守 bug 的後半段（`_applyBonusHidden()` 本體不可以往上爬：`closest(`／`parentNode`…）不依賴 M06，卻被一起略過。
- 建議只讓「鄰居識別字」那段依 M06；往上爬的檢查一律照跑（或者改用 M05 的 cashier.html 當鄰居）。

### 觀察
- **M06-O1**：commit 內文寫「20 支別人的 e2e 改用 `tests._e2e_login.inject_login`」，原本借用傳票檔的 `_login`。這些題的標的不是登入流程，影響應該不大；D 沒有逐支比對。

## A 回覆（2026-09-26 23:13，`wip/a-m06-4` 5afa5f3c，疊在 b-ip15-cost afbb1b8d 上；取代 a-m06-2）

**M06-M1**（5 題）：
- `test_case_page_links_to_map_bonus_and_vouchers`：改成依 M06 在不在——不在 ⇒ 不開傳票、等地圖連結、斷言沒有傳票連結（同一題原本對 M07 的寫法）。
- `test_e2e_t100_unconfirm_2026_09_10.py`、`test_e2e_bonus_vouchers_page_2026_09_24.py`（3 題）：驗的是傳票那一側 ⇒ 整檔搬進 `modules/accounting/tests/`（同檔名），頁面所屬模組（arap／payroll）不在時整檔不成立（模組層 skip，寫明原因）。M07 在 M06 不在時的行為另有 API 題（`test_voucher_connectors` 的 without 題）。
- 成因（月台已記）：上一版反向控制的 e2e 只跑手挑清單。這次非 e2e 與 e2e 用同一份 239 檔樣式清單，真刪後又抓到 3 處（`test_approval_providers` 期望 voucher、`check_approval_queue_coverage` 未登記 voucher 的擁有模組、字級 e2e 用傳票當佇列樣本），已修。
- 完整紅清單（真刪，修完後）：§B-11 允許 5（generated_maps 3、modules_json_lists_only_existing_units、unit_index）＋ origin 既有 2（cm12 案件頁色碼，第十一班修）。

**M06-M2**：EM10 改每組基準（B 審過 3b78b1d8、必修 0；建議 2 項 21cfdabf）。歸屬讀已安裝模組 module.json 的 pages[]；模組外 120＋各模組，總數 157；突變 3/3 紅。

**M06-S1**：`test_rc_candidate_check_and_exhausted_starts_really_fail`（模擬起點耗盡，以 BaseException 分辨 fail／skip；正對照判定對空起點要報問題）。
**M06-S2**：鄰居識別字那段依 M06，「隱藏函式不可以往上爬」一律照跑。

**a' 改走 `dispatch.cost_for_case`（主持裁示同包）——傳票摘要「支出項」承攬商派工的欄位對照：**

| 欄位 | 改寫前（`dispatch.row(row)`＋自己讀派工表） | 改寫後（IP-15 成本檢視） |
|---|---|---|
| id | `d["id"]` | `d["id"]`（同） |
| vendorName | `vendorName` | `vendorName`（同） |
| scope | `scope` | `scope`（主持裁示新增到成本檢視；同） |
| amount | `grandTotal` | `amount`（＝grandTotal，同一份算法） |
| invoiceNo | `invoiceNo` | `invoiceNo`（主持裁示新增到成本檢視；同） |
| summary 句型 | 「廠商－描述　NT$ 金額　發票：號碼」 | 同 |
| 第三層 品項 | `items[]` 有描述的逐項（description、amount；index＝原清單序號） | 同（index 改為成本檢視清單內序號：成本檢視先濾掉無描述的品項；index 未持久化、前端未用） |
| 第三層 人員 | 逐人（name、amount） | **一行「外包人員 N 人」**（count、amount＝personnelTotal）——主持裁示：不回姓名 |
| 讀不到 | 不會發生（直讀） | 403 ⇒ 支出項不列派工、`unavailable` 明說「沒有權限查看承攬商派工的成本」 |

欄位沒有少：scope、invoiceNo 仍在；只有「人員姓名」依裁示改成人數。另：案件清單改走 `case.summary` 之後只列看得到的案件（原本有傳票權限就列全部，比案件頁寬），回應 notes 與畫面都註明範圍；version_manifest 2026-09-26l 已寫這兩項使用者看得到的改變。

**A 追加（2026-09-26 23:25，`wip/a-m06-5` 37e59697，疊在 a-m06-4 上）**：上一段「案件清單改走 case.summary 之後只列看得到的」違反 AT6-O1（386cb0e1）——〔更正〕
範圍改回 JV7 現行：IP-96 加用途 `voucher_link`，有傳票權限列全部、只回摘要欄位（不含地址）；權限判斷在 L1。範圍註明與 manifest 縮窄句撤回。
題 `tests/platform/test_case_summary_purpose.py`（全部／沒有權限照可見性／不帶用途照可見性／未登錄用途拒絕／端到端）；突變 4/4 紅（拿掉權限判斷、放寬時回整列、未登錄用途默默照可見性、傳票不帶用途）。


## 4. 複核：wip/a-m06-5 37e59697（疊 a-m06-4 5afa5f3c、b-ip15-cost；D 23:36）

| 項目 | D 的驗證 | 結果 |
|---|---|---|
| **M06-M1** | D2 **再真刪一次** `modules/accounting`（同樣的 92 檔＋13 個 e2e 檔）：收集 2081、無錯；非 e2e 1980 過、56 skip、**只剩允許的 5 紅**；e2e **40 過、0 紅** | **關閉** |
| **M06-M2** | EM10 改為每組一個基準 `_BASELINE_BY_GROUP`（accounting 4、analytics 8、arap 3…）；突變 N1「accounting 的一句『請至少選擇一個檔案。』改掉」⇒ **紅**（`test_em10_the_navigation_tone_message_count_does_not_drop`） | **關閉** |
| **M06-S1** | 突變 G1b（起點耗盡的 `pytest.fail` 改成 skip）⇒ **紅**（`test_rc_candidate_check_and_exhausted_starts_really_fail`） | **關閉** |
| **M06-S2** | 那一題已沒有 skip；「往上爬」的檢查一律執行，只有鄰居迴圈依 M06 | **關閉** |
| a' 改走 `dispatch.cost_for_case` | 改動前後 `_dispatch_expense_entry` 用到的欄位：前＝`grandTotal, invoiceNo, items, personnel(name, amount), scope, vendorName, id`；後＝`amount, invoiceNo, items, personnelCount, personnelTotal, scope, vendorName, id`。scope 與 invoiceNo 本來就有用到，**沒有新增其他欄位**；外包人員從逐人姓名改成一行「外包人員 N 人」 | 成立 |
| -5 用途範圍 | 突變 P1「未登錄用途照可見性（不拒絕）」、P2「不看模組一律 all」、P3「放寬時回完整列（含地址等）」⇒ 3/3 紅 | 成立 |

**M06-M3（必修，新）　`purpose="voucher_link"` 沒有守門限制呼叫端（主持重點：這條路不能被非傳票端點借用）**
- 放寬與否只看**使用者**有沒有 cashier／finance，不看**是誰在呼叫**。任何模組、任何端點都可以 `case_summary(conn, user, purpose="voucher_link")`；只要登入者有傳票權限，就拿到全部案件的單號、客戶名、案名。
- `git grep`：目前只有 `modules/accounting/api/vouchers.py:688` 在用，所以現況沒有被借用；但也**沒有任何題**擋下一個借用者。
- 影響有上限：能看到全部的人，本來就能在傳票頁看到（AT6-O1 界線）。但借用端點的輸出可能流到別處（匯出、通知、其他使用者看得到的畫面），這正是主持要求擋的。
- 修法：比照 CS-M1 的 SYSTEM 掃描，靜態守門「只有 `modules/accounting/` 可以傳 `purpose="voucher_link"`」（含變數傳遞、`**kwargs` 等寫法的反向控制）。或者在 `case_summary_scope` 加執行期檢查呼叫端所在的模組（比照 CS-M1 的 frame 檢查）。

- 觀察 **M06-O2**：`vouchers_by_case` 用 `_dispatch_costs(no, authorization)[0]`，丟掉了 403 的說明。能打這支的只有 cashier／finance，兩者都在成本檢視的放行名單內，所以現況不會發生。

**A 回覆 M06-M3（2026-09-26 23:40，`wip/a-m06-6` 00f5f0a6）**：`tests/platform/test_case_summary_purpose.py` 新增三題——
- `test_only_the_voucher_module_passes_the_voucher_link_purpose`：全樹（`source_tree.product_files()`，backend＋modules）字面值 `voucher_link`（dep_scan.string_chunks：不含 docstring、串接先合併）只准 `helpers/case_access.py`（登錄處）與 `modules/accounting/api/vouchers.py`（呼叫者）；允許清單寫死在守門裡，新增要主持裁示。任何呼叫的 `purpose=` 必須是字串字面值（明文禁止非字面值）。
- 正對照：M06 在時 accounting 的實際呼叫點被掃到（把它從允許清單拿掉就報它）。
- 反向控制（沙盒原始碼）：別的模組帶用途、用變數傳、`"voucher_" + "link"` 串接 ⇒ 紅；docstring 提到不算。
- 突變 3/3 紅：在 modules/supply 加一個 `purpose="voucher_link"`、會計改成用變數傳、守門允許清單放寬。M06 不在時本檔照跑（端到端題略過）。

