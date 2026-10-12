# A7 第二期：報價單表單 `quotation-form.html` 的下載檔名修補（待 M3 合併後套用；不在本分支）

> 原因：`quotation-form.html` 受 `FORM_VERSION` 守門（內容雜湊變 ⇒ 必須升版）；5e 的 M3 已把它升到 V3.23。本分支不碰這個檔，避免兩條分支各升一次版號。M3 合併後，把下列 4 處套進 M3 的同一個版本（或下一個版本 V3.24），並在 `quotation-form.html` 載入 `../static/download.js`。

1. 檔案頂端 script 區（`legal-round.js` 之後）加：`<script src="../static/download.js"></script>`
2. `_downloadServerPdf(mode)`：`a.download = mode === 'internal' ? \`${this.q.quoteNo}_內部.pdf\` : \`${this.q.quoteNo}.pdf\`` → `a.download = MotrixDownload.nameFrom(r, mode === 'internal' ? \`${this.q.quoteNo}_內部.pdf\` : \`${this.q.quoteNo}.pdf\`)`
3. 另一處 PDF 匯出（約 3256 行）：`a.download = \`${this.q.quoteNo}.pdf\`` → `a.download = MotrixDownload.nameFrom(r, \`${this.q.quoteNo}.pdf\`)`
4. 存檔版本下載（約 3310 行）：`a.download = \`${this.q.quoteNo}_${v.event}_${(v.at || '').slice(0, 10)}.pdf\`` → `a.download = MotrixDownload.nameFrom(r, \`${this.q.quoteNo}_${v.event}_${(v.at || '').slice(0, 10)}.pdf\`)`

三處的回應變數都叫 `r`（`const r = await fetch(...)`）。後端 `quotations.py` 四個文件端點已在本分支改好；沒套用這 4 處之前，報價單頁面下載仍用舊檔名（頁面決定名稱），其餘頁面（案件管理的結案報表、專案執行報告）已讀伺服器檔名。
