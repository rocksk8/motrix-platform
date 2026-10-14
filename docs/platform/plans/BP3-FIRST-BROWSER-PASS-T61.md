# BP-3 第一次真瀏覽器驗證清單（機器空閒後；靜態寫成，尚未執行）

> 分支 `wip/t61-bp3-templates-r1`（疊在 `wip/t61-xl-safe-r1` 上，一起合併）。前提：用拋棄式伺服器＋拋棄式資料庫（`e2e` 在路徑裡），不碰正式機；一次只開一個 uvicorn。
> 設定值用設定中心改（`builder_exports.enabled`：0／1）。每項記「預期」與「實際」，不一致就停手回報。

## A. 開票申請憑據 PDF 的頁尾／浮水印（唯一無法靠 HTML 字串測試證明的部分：Edge headless 的實際排版）
準備：一張已核准、一張未核准的開票申請憑據（任何金額；未核准那張用來確認橫幅）。
1. **旗標關（0）**：下載兩張憑據 PDF（`/api/invoice-vouchers/{no}/pdf-download`），存成基準 A0-approved.pdf、A0-draft.pdf。
2. 把旗標設 1。到「簽核佇列」頁（`approval-queue.html`，頁面有 `motrix-export-id`），以最高管理者登入：畫面左下角應出現「匯出格式」按鈕（非最高管理者、旗標關時**不**出現）。
3. 開啟面板 → 頁尾填「內部資料，請勿外流」、浮水印填「內部使用」→ 按「預覽」：iframe 樣本頁底部有頁尾文字、頁面中央斜向淺灰浮水印；**預期**：浮水印在文字下層、不蓋住樣本內容。
4. 試各種不合法輸入，面板與伺服端都要擋：浮水印「已核准」「正本」「已 付 款」「作廢」；頁尾含 `<script>`、`&`、`{x}`；浮水印 41 字。**預期**：紅字說明、不能發布。
5. 發布（治理旗標關）→ 重新下載兩張憑據 PDF：
   - 已核准那張：頁尾文字出現在每頁底部、不壓到原有頁尾（身分頁尾 identity_foot）與簽核欄；浮水印淺灰、斜向、在內容下層（文字清楚可讀）。
   - **未核准那張：紅色「此為開票申請預覽稿，尚未正式核准」橫幅必須仍在最上層、完全可讀**（範本文字不得蓋掉它）。
   - 多頁憑據（明細很多）：頁尾與浮水印每頁都有；A4 縮放腳本（fit_a4）沒有因為多了固定區塊而改變分頁。
   - 憑據的金額、公司抬頭、統編、簽核欄與 A0 基準逐字相同（用 PDF 文字抽取比對；多出來的只能是頁尾與浮水印那兩段字）。
6. 旗標設回 0 → 再下載：**預期**與 A0 基準 PDF 的抽取文字與版面完全相同。已發布的範本此時不應再套用。
7. 治理旗標開（`builder_governance.enabled`=1）：新增頁尾文字應回「已送出，待第二位最高管理者核准…」，面板如實顯示、不說已發布；第二位最高管理者核准且確認期間過後才生效。

若第 5 項的版面有疊字：先回報截圖與頁數；調整方向是 `helpers/export_templates._PDF_CSS` 的 `bottom`／`top`，不要改憑據版型。

## B. 外包名冊 Excel（xlsx 頁尾／頁首＝列印頁首頁尾）
1. 旗標 1，到外包名冊頁（`vendor-contractors.html`——**注意：目前只有每日任務頁與簽核佇列頁宣告了 `motrix-export-id`，名冊頁尚未宣告；用 API 或在該頁加 meta 後驗**）。
2. 發布範本：只選「姓名、電話、證件號碼」三欄、頁首「外包名冊」、頁尾「請勿外流」。下載 xlsx：只有三欄、順序依範本；Excel 的「列印預覽」看到頁首頁尾；證件號碼是 `******1234`；電話 `+886…` **沒有**可見的單引號；姓名若以 `=` 開頭則前面有 `'`。
3. 用匯出的檔案做「匯入」：欄位標題是原標題，匯入成功、不產生錯誤（標題鎖定的理由）。
4. 同一份檔案的 PDF 姊妹（`/api/contractors/export/pdf`）：表格上方有頁首文字、下方有頁尾文字。
5. 旗標 0：下載的名冊與基準（旗標從未開過時的下載）逐格相同。

## C. 每日任務歷程 CSV
1. 旗標 0、頁面載入時用瀏覽器 Network 面板：**只應有頁面原本就有的請求**——特別檢查沒有 `/api/export-templates/…/status`、沒有 `/static/export-editor.js`、沒有 `/api/exports/client-log`。（本檢查已以 `/api/platform/menu` 的 `builderExports`／`exportAudit` 鍵取代額外請求；daily-tasks 沒有 e2e／network golden，所以靠這一步人工確認。）
2. 旗標 1（最高管理者）：Network 出現 `/static/export-editor.js`、`/api/export-templates/daily_tasks%3Atask-history/status`；非最高管理者：只有 `exportAudit` 鍵（沒有編輯器、沒有 status）。
3. 發布範本（調順序、改標題、拿掉「回報內容」）→ 歷程匯出 CSV：標題與順序依範本；BOM 仍在；`=` 開頭的任務標題前有 `'`。旗標 0 → 回到原本七欄。

## D. SheetJS 三頁（客戶／料號／供應商）
1. 旗標 0：按「匯出 Excel」，Network 面板**沒有** `/api/exports/client-log`；檔案與以前相同。
2. 旗標 1：按匯出 → 有一個 `POST /api/exports/client-log`（`keepalive`），即使它回 4xx／5xx 或被擋，檔案照樣下載（只記錄、不擋）；稽核紀錄頁看到 `export.xlsx`、`client:true`、列數。連按三次：三筆都記、都不回 429。
3. 伺服端 Excel 匯出的 5 秒冷卻不受影響（先按任一伺服端匯出，再按 SheetJS 匯出，兩者互不影響）。

## E. 選單回應的新鍵（不洩漏）
旗標 0：`/api/platform/menu` 對所有人**沒有** `builderExports`、`exportAudit`。旗標 1：最高管理者兩個鍵都有；其他角色只有 `exportAudit`。
