# 稽核：個資蒐集告知擴大（wip/cloud-pii-notice；第三班列車已合回）（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d。稽核者 D 沒有寫過任何受稽核的程式碼。**合回後稽核**；只審新版（CORE-SPEC 35014aaa）。
> 對象：origin/platform `d21f14c6` 上的 `b7d8b26e`（擴大到其他表單）、`e381fdd0`（單據上手動輸入的聯絡人）、`18b82b77`（差異題修正）、`6bb082ef`（改用 `page_files()`）；列車取號 `382d9d3d`（CORE 1.23）。
> 主持點名：12 頁的決定、「covered_by 的欄位必須不可手打」守門、換聯絡人要重新告知。
> 稽核樹 `D:\MOTRIX-PLATFORM-D`（detached），Python `D:\MOTRIX-PLATFORM\.venv312`（只用、未改）。
> 分級：**必修**／**建議**／**觀察**。關閉規則：被稽核者回覆後，由 D 確認才關。

## 0. 結論

- **12 頁的決定**：守門全綠，`pii_forms.json` 共 12 頁：11 頁 notice，1 頁 `not_natural_person`（公司設定）。每一頁的偵測欄位都與決定相符。
- **「covered_by 的欄位不可手打」**：D 做了 2 項突變，兩項都轉紅。但是判斷「readonly／disabled」的正則會被屬性值裡的同名單字騙過（S-3）。目前沒有任何一頁用 covered_by，所以這是潛在問題。
- **換聯絡人要重新告知**：伺服器端成立。紀錄的鍵含聯絡人姓名，而且伺服器只接受已存檔的那一位；D 做了 5 項突變，全部轉紅。**但是畫面端沒有題目驗**：D 讓畫面在換人之後照樣顯示舊的那一筆「已告知」，e2e 10 題全部照綠（S-2）。
- **必修 1 項**：PN-M1。notice 的決定是以「頁」為單位，所以同一頁上第二種當事人的個資欄位會被放過。實例是案件頁出貨單的「收件人＋送貨地址」：可以手動輸入，而頁面的告知只記錄合約現場聯絡人。
- 建議 3 項、觀察 4 項。D 突變共 11 項：8 紅，3 存活（S-1 兩項、S-2 一項）。

## 1. 逐項驗收

| 項目 | 結果 | 證據 |
|---|---|---|
| 守門全綠 | ✅ | `tests/platform/test_pii_forms_notice.py`＋`tests/test_privacy_notice_forms_2026_09_26.py`：63 passed（PN8 那一輪，產品碼等於未改） |
| 正對照：承攬人員名冊被掃到，決定是 notice | ✅ | `test_positive_control_contractors_form_is_detected_as_notice` |
| 反向控制：全部寫成豁免 ⇒ 紅 | ✅ | `test_reverse_control_exempting_everything_turns_red`（強個資不可以豁免） |
| 11 頁拿掉告知區塊 ⇒ 各自紅；拿掉紀錄端點 ⇒ 各自紅 | ✅ | 參數化，每一頁一題 |
| 可手打的欄位用 covered_by ⇒ 紅；靜態 readonly ⇒ 綠；`:disabled` ⇒ 紅 | ✅ | `test_typed_contact_cannot_be_covered_by_a_master_form`；D 突變 PN6、PN7 皆紅 |
| 換聯絡人要重新告知（伺服器） | ✅ | 鍵為 `<kind>:<單據>:<姓名>`；姓名與已存檔的不同 ⇒ 409。D 突變 PN1～PN5、PN10 皆紅 |
| 換聯絡人要重新告知（畫面） | ⚠ 沒有題目 | S-2 |
| 報價單告知端點的案件權限 | ⚠ 沒有題目 | S-1 |
| e2e（docs＋forms 兩檔） | ✅ | 10 passed |

## 2. D 的突變

題目：PN1～PN10 跑 `tests/test_privacy_notice_forms_2026_09_26.py`＋`tests/platform/test_pii_forms_notice.py`（63 題）；PNJS 跑兩個 e2e 檔（10 題）。每一輪都確認有收到題。

| # | 突變 | 結果 |
|---|---|---|
| PN1 | 報價單 ack 不比對已存檔的聯絡人 | 紅（2） |
| PN2 | 完工單 ack 不比對驗收人 | 紅 |
| PN3 | 規劃書 ack 不比對聯絡人 | 紅 |
| PN4 | 報價單紀錄鍵不含姓名 | 紅（2） |
| PN5 | 規劃書紀錄鍵不含姓名 | 紅 |
| PN6 | `_not_typeable` 永遠成立（`and`→`or`） | 紅 |
| PN7 | `:disabled` 也算唯讀（拿掉 `:` 的 lookbehind） | 紅 |
| PN8 | 報價單 GET privacy-notice 拿掉 `row_access.require(..., scope="read")` | **存活** |
| PN9 | 報價單 POST ack 拿掉 `row_access.require` | **存活** |
| PN10 | 現場聯絡人的路徑改成報價單聯絡人 | 紅 |
| PNJS | `privacy-notice.js` 的 `pnAck()`：目前這位沒有紀錄時，改拿別人的紀錄 | **存活**（e2e 10 passed） |

## 3. 發現

### 必修

**PN-M1　notice 的決定以「頁」為單位 ⇒ 同一頁上第二種當事人的個資沒有人決定過**
- 實例：`case-management.html` 出貨單的 `shippingForm.recipient`（收件人）與 `shippingForm.delivery_address`（送貨地址）都可以手動輸入。掃描有抓到 `shippingForm.delivery_address`，但因為這一頁的決定是 notice，守門就放行了。而這一頁的告知紀錄只有 `case_site_contact:<單號>:<合約現場聯絡人>`，也就是收件人從來沒有被告知。這與主持 2026-09-26 的裁示「可以手動輸入的聯絡人就是在蒐集個資 ⇒ 要 notice」不一致。
- 為什麼是必修：守門的承諾是「頁面多一個個資欄位就轉紅、要有人重新決定」，但這個承諾只對 covered_by 與 not_natural_person 成立。notice 頁面可以無限增加個資欄位，也不必新增告知對象。
- 建議修法：
  - notice 的決定也要逐欄列出 `fields`，並寫明每一欄屬於哪一個告知對象（例如 `subjects: {"site": [...], "shipping_recipient": [...]}`）；掃描結果多出一欄就轉紅。
  - 收件人要不要告知，照裁示處理：補告知，或由主持改裁示並寫進 `pii_forms.json`。
  - 補一道反向控制：在 notice 頁面多加一個 `x-model="foo.contactPhone"` ⇒ 轉紅。

### 建議

- **PN-S1　報價單告知端點的案件權限沒有題目守**：PN8、PN9 存活。拿掉 GET 的權限檢查之後，任何登入的人都能讀到別人案件的聯絡人姓名與告知紀錄；拿掉 POST 的權限檢查之後，任何人都能替別人的案件記一筆「已告知」。程式碼現在是對的，缺的是題目。建議補兩題：非擁有者 GET 回 403，非擁有者 POST 回 403。
- **PN-S2　畫面上「換了聯絡人 ⇒ 回到尚未記錄」沒有題目**：PNJS 存活。伺服器的鍵是對的，但畫面如果拿錯紀錄，使用者看到的是「已告知」，實際上這一位從來沒被告知過。這是「降級之後它還是會動」的形狀：不會有人報修。建議補一題 e2e：先記錄 A，改成 B 並存檔，重新整理之後，區塊應該顯示 `data-privacy-missing`。
- **PN-S3　`_not_typeable` 會被屬性值裡的單字騙過**：D 直接呼叫實測：
  - `:class="{ 'opacity-50': disabled }"` ⇒ True
  - `title="readonly when locked"` ⇒ True

  兩者其實都可以手打，卻被判成「不可手打」。反過來，屬性值裡有 `=>` 時，標籤會在 `>` 被截斷，判成可手打（這個方向比較安全）。目前沒有任何一頁用 covered_by，所以這是潛在問題。建議只認屬性名稱位置的 `readonly`／`disabled`，也就是前面是空白、後面是空白、`>` 或 `=`，而且不在引號內；並且把上面兩個例子加進反向控制。

### 觀察

- **O-1　第四班的 M10 要帶著告知端點走**：network-plans 的兩個告知端點目前在 `routers/network_plans.py`，而 `wip/a-m10`（ca73e25e）還沒包含個資告知。M10 rebase 時，這兩個端點要搬進 `modules/netplan/api.py`。守門有保險：`source_tree.router_files()` 含模組的 api，端點不見的話 `test_every_pii_form_has_a_decision_and_it_still_holds` 會紅。
- **O-2　告知紀錄以姓名當鍵**：同一張單據上換成另一位同名的人，會沿用舊紀錄；只修正錯字，也要重新告知。後者偏向保守，可以接受；前者在實務上很少見。記錄在這裡，不要求修改。
- **O-3　頁面搬進模組之後，決定會隨模組在不在而改變**：階段 C 把頁面搬進 `modules/<key>/pages/` 之後，模組一拿掉，`pii_forms.json` 那一頁就會變成「清單上有、頁面不存在（過期的決定）」而紅。這與主持 06:02 記的「5 道隨模組在不在而改變的守門」同一類，建議併入 B 的 core-only 反向控制工具，或者比照 X-2 用 `module_installed` 豁免。
- **O-4　完工單告知紀錄的 GET 只驗登入**：與完工單明細端點（`get_completion_note`）一致，所以不是這次新增的缺口；記錄在這裡，不要求修改（CORE-SPEC 35014aaa：不查 V9 的既有寫法）。

## 4. 回覆欄（被稽核者填；D 確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | D 確認 |
|---|---|---|---|
| PN-M1 | | | |
| PN-S1～S3 | | | |
| O-1～O-4 | | | |
