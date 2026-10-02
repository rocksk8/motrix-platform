# 出貨單連動材料申請 — S1 提供者契約（一頁）

2026-10-03，c7 草擬、**待 2e（case 側）確認**。依 `MATERIAL-FORCE-PO-AND-SHIPPING-SPEC.md` rev.2 §C 與裁示 E5／E6。兩個模組不互相 import，只經 `core.registry` 提供者互通。

## 1. case 提供（2e 擁有）：`("material.shippable", "case")`
`fn(conn, quote_no) -> list[dict]`；沒有該案件／沒有材料申請 ⇒ `[]`。每個元素：

| 欄位 | 型別 | 定義 |
|---|---|---|
| `materialItemId` | str | `materialOrders[].id`（＝`case_material_approvals.item_id`；案件內唯一） |
| `docCode` | str | 叫料單號（`MO…`，全域唯一） |
| `name`／`unit` | str | 品名／單位（取**已核准版本**） |
| `quoteItemId` | str | 對應報價品項（沒有＝`""`） |
| `appliedQty` | number | 已核准版本的 `quantity` |
| `arrivedQty` | number | **E5**：已做到貨確認（`received_on` 非空）才有值；有 `received_qty`（新欄，選填）用它，沒填＝`appliedQty`；未到貨＝`0`。變更申請核准後新增的部分需再確認才計入（M2 的事，S1 只讀） |
| `status` | str | 恆為 `已核准`（其餘狀態不回傳） |

回傳條件：疊加列 `status='已核准'` 且 `received_on<>''`；`已取消`、草稿、待審核、簽核中、已退回一律不回。變更申請待審期間仍以已核准版本計（N3 預設）。**唯讀、不寫入、不 commit**。

**請 2e 確認／補做**：(a) `case_material_approvals` 加 `received_qty REAL`（migration，選填）與到貨確認 API 的選填 `receivedQty`（S1 前沒有也行——先全數；有了再接）；(b) 上表欄位語意；(c) 提供者放哪個檔（建議 `modules/case/material_shippable.py`，`__init__.py` 的 providers 登記）。

## 2. supply 提供（c7 擁有）：`("shipping.material_shipped", "supply")`
`fn(conn, quote_no, exclude_note_no=None) -> dict`：`{materialItemId: {"reserved": qty, "shipped": qty, "notes": [note_no, …]}}`。
- 來源＝該案件出貨單 `items_json` 內的 `materialLink: {materialItemId, docCode, qty}`。
- `reserved`＝狀態 `待審核`／`簽核中`；`shipped`＝`已核准`；`草稿`、`已退回`（退回＝回草稿）不計。`exclude_note_no`＝檢查自己時排除自己。
- （規格寫成 `{id: 占用量}`；本契約加 `shipped` 與 `notes` 供畫面三格與取消阻擋用，**向下相容於只讀 `reserved+shipped` 的呼叫端**——請 2e 確認。）

## 3. 出貨單明細（加性）
`items_json[i].materialLink = {"materialItemId": str, "docCode": str, "qty": number>0}`；舊單無此鍵＝行為不變。一列對一筆材料申請；同一張出貨單內同一 `materialItemId` 的列數量合計計算。**與 `part_no`／`serials` 同列互斥**（400 `ship_link_serial_exclusive`）。

## 4. supply 驗證（送審與核准各一次；核准時防競態）
對每個 `materialLink`（以 `case` 提供者取 `shippable`，找不到該 `materialItemId`／`docCode` 不符 ⇒ 400 `ship_link_invalid`「材料申請未核准、未到貨、已取消或不存在」）：
`其他單據 reserved+shipped（exclude 自己） + 本單合計 qty ≤ arrivedQty`，超出 ⇒ 400 `ship_exceeds_arrived`（訊息列出品名、已到料、已占用、本單）。`case` 提供者不存在（M01 未啟用）而單內有 `materialLink` ⇒ 400 `ship_link_module_off`。
**E6 警示（不擋）**：`GET /api/shipping-notes/{note_no}/material-link-check` ⇒ `{"unlinked": [{materialItemId, docCode, name, remaining}]}`＝該案件已到料且 `arrivedQty − reserved − shipped > 0`、而本單沒有連結的品項；畫面送審前顯示。

## 5. 反向（S3，case 呼叫 supply）
case 取消材料申請／變更申請下限／三格數量：呼叫 `registry.single_provider`／`providers("shipping.material_shipped")`（沒有提供者＝視為 0）。**不直接讀 `shipping_notes`**。

## 6. 守門與測試
- AST 守門：`modules/supply` 不得 import `modules.case`、反之亦然（既有 `test_supply_moved_guards` 風格擴充）。
- 契約題：兩個提供者各自回傳形狀；`reserved`／`shipped` 狀態對照（草稿、退回不計）；`exclude_note_no`；超量 400；核准時重檢（送審後另一單先核准 ⇒ 本單核准 400）；序號互斥；舊單不變（無 `materialLink` 的出貨單送審／核准／PDF 逐位相同）。
- L1：新能力名登記於 core 介面快照（`--update --pending`），CHANGELOG (next)。

## 7. 切分
S1（本頁＋supply 提供者與驗證＋case 提供者〔2e〕）→ S2（出貨單頁「從材料申請帶入」、簽核詳情欄）→ S3（材料申請頁三格、取消阻擋、報表欄）。S1 的 case 側若 2e 尚未完成，supply 驗證以 `material.shippable` 的假提供者（測試註冊）先行，兩邊以本頁欄位對接。
