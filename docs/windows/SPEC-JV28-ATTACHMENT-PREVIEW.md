# `SPEC-JV28` · 傳票附件要能預覽，不能只有檔名

> 座標：master `3370d74`（正式機 `46dc6ae`）／作者：hichan-0a ／ 2026-09-24
> 使用者逐字：「**在傳票上，已上傳檔案要能夠預覽，只有名稱無法辨別**」
> 前一輪：`SPEC-JV16-JV17.md`（取檔端點＋預覽窗內可點清單）——本檔是它沒解決的那一半。

---

## §1 現況（讀碼，HEAD `3370d74`）

| 位置 | 現況 | 問題 |
|---|---|---|
| `voucher.html:461-475` 編輯頁附件清單 | `<span class="vc-att__name" x-text="a.filename">` | **只有檔名，不能點** |
| `voucher.html:630-640` 預覽窗附件清單 | `<a @click.prevent="openAttachment(a)">` | 可點 |
| `voucher.js:395-409` `openAttachment()` | `fetch`（帶 Authorization）→ blob → **`window.open(url)`** | `window.open` 在 `await` 之後 ⇒ 已不是使用者手勢 ⇒ **可能被彈出視窗封鎖**；且開新分頁，離開傳票畫面 |
| `vouchers.py:1310` `GET /{id}/attachments/{file_id}` | `FileResponse(mime, filename)` | 端點本身可用；前端走 blob 所以 Content-Disposition 不影響 |

> ⚠️ 未實測「被封鎖」——這是依程式形狀推斷。實作前先在 e2e 裡重現（⑤ 的第一支題）。

## §2 要做的

1. **頁內預覽窗**（取代 `window.open`）：點附件 ⇒ 同一頁開一個預覽 modal。
   - 圖片（`image/png`、`image/jpeg`、`image/gif`、`image/webp`）⇒ `<img>` 顯示原圖，可縮放到視窗大小。
   - PDF（`application/pdf`）⇒ `<iframe>` 內嵌顯示。
   - 其他類型 ⇒ 顯示檔名、大小、類型，與「下載」鈕（**不內嵌**）。
   - modal 內有「下載」鈕（所有類型），以及上一個／下一個（同一張傳票的附件間切換）。
2. **編輯頁清單**：檔名改成可點（開同一個預覽窗）；**圖片附件顯示縮圖**（約 48px，延遲載入）。
3. **預覽窗內的附件清單**（JV16 那份）改用同一個預覽窗，不再 `window.open`。
4. blob URL 用完要 `revokeObjectURL`（關閉 modal 或切換附件時），不可累積。

## §3 🔴 安全界線（不可以省略）

- **只有 §2-1 列出的 MIME 可以內嵌**。`image/svg+xml`、`text/html`、`application/xhtml+xml` 及任何未列出的類型 **一律只給下載**——SVG／HTML 內嵌等於在我們的網域執行上傳者的腳本。
- MIME 判斷以**伺服器存的 `mime`＋副檔名兩者都符合**為準；只看其中一個就不內嵌。
- blob 建立時明確指定 `type`，不讓瀏覽器猜。
- 取檔權限不變：沿用 `_require_voucher_access`，不新增公開路徑、不加 `?token=`（FX21 已拿掉）。

## §4 不做

- 不改 `preview_html()`（理由見 `SPEC-JV16-JV17.md` §1）。
- 不做 Office 檔（doc/xls）線上預覽——下載即可。
- 不改附件上傳、刪除、併入 PDF 的邏輯。

## §5 驗收（題先紅，觀測點打在畫面上真的看得到的東西）

| # | 題 | HEAD 上應該 |
|---|---|---|
| ① | 點編輯頁的圖片附件 ⇒ 頁內出現預覽 modal，`<img>` 的 `naturalWidth > 0` | 紅（檔名不能點） |
| ② | 點 PDF 附件 ⇒ modal 內 iframe 的 src 是 blob、type 是 pdf | 紅 |
| ③ | 圖片附件在清單上有縮圖（`naturalWidth > 0`） | 紅 |
| ④ | 上傳一個 `.svg`（與一個偽裝成 `.png` 但 mime 是 `image/svg+xml`）⇒ **不內嵌**，只出現下載鈕 | 突變「放行 svg」⇒ 紅 |
| ⑤ | 預覽窗（JV16 那份）點附件 ⇒ 同一個頁內 modal，**沒有開新分頁**（page 事件 `popup` 0 次） | 紅 |
| ⑥ | 關閉 modal 後 blob URL 已 revoke（對照：不 revoke 的突變 ⇒ 紅） | — |
| ⑦ | 非本人／無權限帳號取檔 ⇒ 403（既有權限不退） | 綠（凍結組） |

使用者可見的改動 ⇒ **要附頁面實測截圖或 e2e 輸出**，不能只有後端綠。
