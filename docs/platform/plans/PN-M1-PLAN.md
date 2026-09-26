# PN-M1 步驟表：個資告知逐欄決定＋出貨單收件人告知（A，2026-09-26）

> 來源：`docs/platform/audit/AUDIT-D-pii-notice.md`（D，cc06a04e）必修 PN-M1、建議 PN-S1～S3、觀察 O-1～O-4。
> 主持裁示（2026-09-26）：收件人要告知，比照「手動輸入的聯絡人要告知」，用途同聯絡人；`pii_forms.json` 改成**逐欄**列出每一欄與它的告知對象，守門逐欄檢查。
> 分支：`wip/a-pn-m1`（疊在 `wip/a-m03` 上：出貨單端點在 `modules/supply`）。

## 0. 現況（問題的形狀）

- 決定以「頁」為單位：`notice` 頁面只驗告知區塊標記與紀錄端點，**不驗欄位**。頁面可以無限增加個資欄位、也不必新增告知對象。
- 實例：`case-management.html` 的告知只記「合約現場聯絡人」（`case_site_contact:<單號>:<姓名>`）；出貨單的收件人（`shippingForm.recipient`）與送貨地址（`shippingForm.delivery_address`）可以手動輸入，沒有告知。
- 掃描字尾沒有 `recipient` ⇒ 收件人欄位根本掃不到（只掃到送貨地址）。

## 1. 規則（寫進 `_pii_forms.py` 檔頭與 MODULE-GUIDE §11）

1. 掃描字尾加 `recipient`（簽收人姓名＝自然人）。
2. `notice` 的決定要列 `fields`；一頁有兩種以上當事人時用 `notices`（清單），每一個對象各有 `subject`、`fields`、`ack_kind`、`ack_api`（可選 `api_module`）。
3. 逐欄：所有對象的 `fields` 聯集＝掃描結果（多一欄、少一欄都紅）；同一欄不可以同時屬於兩個對象。
4. `notices` 有兩個以上對象時，頁面上每個對象要有自己的告知區塊：`data-privacy-subject="<subject>"`。
5. `covered_by`／`not_natural_person` 維持原本的逐欄規則。

## 2. 出貨單收件人（M03）

- 端點（`modules/supply/api/shipping_notes.py`）：
  - `GET /api/shipping-notes/{note_no}/privacy-notice` ⇒ `{acks}`；權限同出貨單清單（`guard_case_access(..., allow_module="case_manage")`）
  - `POST /api/shipping-notes/{note_no}/privacy-notice/ack` `{subject}` ⇒ 只接受「已存檔的收件人」（不同 ⇒ 409）；鍵 `shipping_recipient:<出貨單號>:<收件人>`；用途 `contact`；新紀錄寫稽核
- 畫面（`case-management.html` 出貨單視窗）：`subjectState('contact', …, s => s.shippingForm.recipient, {deferred: true})` 的告知區塊；存檔成功後若勾了「已告知」⇒ 以新單號記錄（事件 `shipping-saved`）
- `pii_forms.json`：`case-management.html` 改成 `notices`：`case_site_contact`（合約聯絡人欄位）＋ `shipping_recipient`（`shippingForm.recipient`、`shippingForm.delivery_address`，`api_module: supply`）
- M03 不在：出貨單分頁本來就只有說明（IP-18），收件人欄位不出現；`api_module` 讓守門不比對端點

## 3. 建議項

- PN-S1：報價單告知端點補兩題——非擁有者 GET 403、非擁有者 POST 403（突變 PN8、PN9 要轉紅）
- PN-S2：e2e——先記錄 A，改成 B 並存檔，重新整理 ⇒ 區塊顯示 `data-privacy-missing`（突變 PNJS 要轉紅）；出貨單收件人同一題型
- PN-S3：`_not_typeable` 只認屬性名稱位置的 `readonly`／`disabled`（前空白、後接空白／`>`／`=`，不在引號內）；D 的兩個例子加進反向控制

## 4. 觀察項的回覆

- O-1：第四班列車長已把 network-plans 的兩支告知端點搬進 `modules/netplan/api.py`（主持 2026-09-26）⇒ 關閉
- O-2：姓名當鍵，同名沿用、改錯字要重告知 ⇒ 不改（D 不要求）
- O-3：頁面搬進模組後決定隨模組在不在而變 ⇒ 頁面位置已走 `page_files()`；端點走 `api_module`。頁面本身的「清單有、頁面不在」併入 B 的 core-only 反向控制工具（主持 06:02 同類）
- O-4：完工單告知 GET 只驗登入 ⇒ 與完工單明細一致，不是新缺口，不改

## 5. 驗證

- 守門：合成反向控制（多一欄、同欄兩對象、缺對象區塊、新字尾）＋真實頁面反向控制；突變每條規則一項
- 端點：403、409、鍵含姓名、稽核；畫面 e2e（出貨單收件人：記錄 → 換人 → 尚未記錄）
- 差異題＋tests/platform＋改到的頁面 e2e（-n 4）；全量交列車
