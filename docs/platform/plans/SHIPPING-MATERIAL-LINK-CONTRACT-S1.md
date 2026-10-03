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

---

## 8. case 側確認與實作（2e，2026-10-03；分支 `wip/t34-ship-case-2e`）
**結論：契約 §1／§2／§5 全部接受，已實作 case 提供者；以下為逐點答覆。**

1. **提供者**：`modules/case/material_shippable.py::material_shippable(conn, quote_no)`，在 `modules/case/__init__.py` 以 `("material.shippable", "case")` 登記。唯讀（測試驗證沒有寫入）；沒有該案件／空單號／沒有材料申請／舊單（沒有疊加列）⇒ `[]`。
2. **欄位語意**（與 §1 表一致）：`materialItemId`＝`materialOrders[].itemId`（＝`case_material_approvals.item_id`；注意實際欄位名是 `itemId`，不是 `id`）；`docCode`＝疊加列 `doc_code`；`name`／`unit`／`appliedQty`／`quoteItemId` 取 `caseRecord.materialOrders[]` 的**目前生效（已核准）版本**——M2 變更申請核准前，變更待審內容在 `case_material_changes`，不動這裡（N3）。回傳條件＝疊加列 `status='已核准'` 且 `received_on<>''`，順序同案件內材料申請順序。`status` 恆為 `已核准`。
3. **`arrivedQty`（E5）**：預設＝`appliedQty`（整筆到貨）；若疊加表有選填欄位 `received_qty`，用 `min(received_qty, appliedQty)`（實收不超過已核准量）。**`received_qty` 欄位與到貨 API 的 `receivedQty` 尚未做**：提供者先偵測欄位是否存在（沒有＝全數），所以 supply 現在就可以對接；欄位 migration 由我在 34 班後段補（會與 d7 的 `0006_material_changes` 錯開，取 `0007`），補上後契約不變。M2 核准後**新增的數量**需再確認到貨才計入：到貨確認屬 M2 之後的 S 線工作，S1 只讀。
4. **supply 的 `shipping.material_shipped` 形狀**（`{materialItemId: {reserved, shipped, notes[]}}`，比規格多 `shipped`／`notes`）：接受；case 的反向呼叫（S3：取消阻擋、變更申請下限、三格數量）只用 `registry.single_provider("shipping.material_shipped")`，**沒有提供者＝視為 0**，且只讀 `reserved`、`shipped`、`notes`，不依賴其他鍵。case 不會讀 `shipping_notes`。
5. **取消阻擋／變更下限**：case 取消材料申請時，若 `reserved+shipped>0` ⇒ 擋，訊息列出 `notes`（出貨單號）；變更申請（d7 的 M2b）下限＝`reserved+shipped`（代碼 `change_below_shipped`）。這兩點的呼叫端在 d7 的簽核側與 case 的取消路徑，均以上述提供者為唯一來源。
6. **E6 警示**（`GET /api/shipping-notes/{note_no}/material-link-check`）屬 supply；它要的「已到料且 `arrivedQty − reserved − shipped > 0`」資料全來自上面兩個提供者，case 不需另外提供。
7. **檔案／守門**：`modules/case` 與 `modules/supply` 互不 import（AST 守門擴充由 c7 的 S1 一併做）。case 這邊的契約題在 `modules/case/tests/test_material_shippable_2026_10_03.py`（4 題：只回已核准＋已到貨、`arrivedQty` 預設與上限、空／舊單、已登記且唯讀）。
