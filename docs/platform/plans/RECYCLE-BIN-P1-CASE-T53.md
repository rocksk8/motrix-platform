# 刪除暫存區 P1 — 案件／供應模組 adapter（第 53 班；b5）

分支 `wip/t53-b5-rb-adapters`（基準 ab 的 `wip/t53-ab-recyclebin-p0` ee35eda71）。契約見 `helpers/recycle_bin.py`、IP-RB1／IP-RB2、`RECYCLE-BIN-P0-STATE-T53.md`。

## 範圍與做法
| entity_type | 擁有者 | 端點／寫入層 | 現行刪除規則（不放寬） | 隨它走 | 已核可入口（superadmin）拒絕條件 |
|---|---|---|---|---|---|
| `quotation` | case | `DELETE /api/quotations/{no}` | 草稿 | 階段、拜訪、進度更新（含附件）、行動事項、回簽檔／JSON 內附件 | 底下還有額外支出／完工單／出貨單／派發／請款單／收款憑據／承攬商匯款／獎金分潤／變更申請／材料申請審核；已結案 |
| `extra_expense` | case | `DELETE …/extra-expenses/{id}`（請購單／採購單／費用單據同表） | 草稿、已駁回 | 附件（files_json／change_json.addFiles） | 已登錄付款；請購單已被採購單引用 |
| `completion_note` | case | `DELETE /api/completion-notes/{no}` | 草稿 | 回簽檔 | （影響清單：回簽、保固起算；不拒絕） |
| `material_order` | case | 報價單存檔 diff 的被刪列（`material_guard._gate_orders`） | 草稿／已退回／舊單（無審核列）；有匯款申請紀錄不可刪 | 審核疊加列（`case_material_approvals`）＋ JSON 內那一列 | 有匯款申請紀錄；簽核中 |
| `shipping_note` | supply | `DELETE /api/shipping-notes/{no}` | 草稿 | 回簽檔 | 已扣庫存序號（先『撤銷核准』） |

## 決定（請 PM 複核）
1. **報價單不連帶刪其他單據**：目前硬刪只刪報價單一列、名下單據成孤兒；進暫存區後名下的「階段等附屬資料」一起進同一筆、一起還原，其他單獨存在的單據維持原樣（還原報價單時自然重新對上）；『刪除已核可』時只要還有其他單據就明確拒絕（不選「全部進同一個 group」：那會讓已付款單據被連帶刪）。
2. **材料申請的 entity_id＝`<報價單號>|<itemId>`**：沒有資料表，本體是報價單 JSON 的一列；`delete_in_tx` 同時把那一列從 JSON 拿掉（存檔流程內冪等）。舊單（沒有審核列）被刪也進暫存區（原本是靜默消失）。
3. **回應形狀不變**：進暫存區時仍回 `{ok:true}`；暫存區缺席才多 `binned:false`＋`notice`（既有測試與前端不用改）。
4. 附件搬走後，單據專屬的空資料夾由 adapter 拿掉（與原 `purge_document_files` 行為一致；`os.rmdir` 在 adapter 檔內，免守門登記）；還原由 recyclebin 重建資料夾。
5. 還原衝突：單號被占用 ⇒ `conflict`（不覆蓋；P1 不提供『以新單號還原』）；整數主鍵被占用（非 AUTOINCREMENT 表）⇒ 配新 id；父層（報價單）不在 ⇒ `parent_missing`。
6. 守門基線：移除已接入的 4 條路由與 3 個 `DELETE FROM`；`quotations.py::quotations` 次數 2→1（剩建立失敗的補償刪除，改 `exempt:`）；報價單內的階段／拜訪／進度更新單筆刪除 `p1:`→`p2:`（單筆 CRUD，整張報價單已進暫存區）。G-M1 靜態守門（只有閘寫 materialOrders）把 `recycle_adapter.py` 列為合法寫入者（有 can_delete／衝突檢查把關）。

## 未做（交接）
- 其他 p1 項目（收款憑據、請款單、勞報單、承攬商派發／匯款申請）不在本班範圍。
- `material_payment.py::case_material_payment_lines`（匯款明細隨匯款申請）仍 p2：材料申請有匯款申請紀錄時一律拒刪，所以不會被連帶刪。
- 『以新單號還原』、跨類型 group 還原（派發隨報價單）留給之後。
