# `SPEC-JV16` · 附件要看得到 ／ `SPEC-JV17` · 匯出鈕只留在預覽窗

> 座標：`e77fe52`（工作樹：本檔為新增）
> 作者：視窗 A-2 ／ 2026-09-23
> 使用者逐字：
> 「傳票部分，**上傳檔案在預覽中要顯示**，網頁下方的預覽右邊兩個匯出PDF跟
> 匯出PDF(含附件)這兩個**不顯示**，這兩個**只顯示於預覽窗口內**，
> 避免人員不確認就直接按匯出」

---

## §1 A 給的起點，**逐條複驗過**

```
✅ vouchers.py 共 **14 支端點**，**沒有任何一支可以取出單一附件檔案**
   （POST /{id}/attachments ／ DELETE /{id}/attachments/{file_id} ／
     GET /{id}/pdf-download ／ GET /{id}/preview，就是沒有取檔的）
✅ voucher.html:358  `<span class="vc-att__name" x-text="a.filename">`
   —— **不是連結**
```

> ☠️ **上傳得進去、列得出來、刪得掉、能併進 PDF —— 就是看不到。**

### ✅ 而 `preview_html()` docstring 那句「附件本來就有自己的檢視入口」確實是錯的

🔑 A 自報「**我差一點照它寫進派工單**」——
> **一句寫在 docstring 裡的「理由」，會讓下一個人不去查它。**

⚠️ 而**同一段 docstring 裡對的那一半仍然成立**：不帶 `file:///` 圖片，
是因為那是給伺服器上的 Edge 印 PDF 用的絕對路徑，瀏覽器連不到。
⇒ **不要改 `preview_html()`**，附件區要加在 **iframe 外面的 modal 版面上**。

---

## §2 `JV16` ① 取檔端點

### 權限閘門：**與其他 14 支一致，沒有例外**

AST 逐支對過（不是 grep，不截斷）：

```
14 支端點**全部**是 `_require_voucher_access(_require_user(authorization))`
=> 新端點照抄，**不要因為「只是一張圖」就降級**
```

```
GET /api/vouchers/{voucher_id}/attachments/{file_id}
    閘門  _require_voucher_access(_require_user(authorization))
    行為  查 attachments 找到 file_id -> abs_path(path) -> FileResponse
    擋    ① 找不到 voucher -> 404
          ② file_id 不屬於這張傳票 -> 404（**不是 403**，不要洩漏它存在）
          ③ 檔案遺失 -> 404
```

### `abs_path()` **防得住**（讀過了，不是相信它）

```python
# helpers/voucher_attachments.py:178
p = os.path.realpath(os.path.join(_uploads.UPLOADS_ROOT, str(rel or "").lstrip("/\\")))
root = os.path.realpath(_uploads.UPLOADS_ROOT)
if p != root and not p.startswith(root + os.sep):
    raise HTTPException(400, "附件路徑不合法。")
```

```
✅ realpath        => `..` 與 symlink 都先解開再比
✅ root + os.sep   => 擋得住 `uploads_evil` 這種**兄弟目錄前綴**
✅ Windows 絕對路徑（`C:\...`）=> os.path.join 會**丟掉 base**，
   但 realpath 之後不以 root 開頭 => **一樣被擋**
✅ UNC（`\\server\share`）=> lstrip("/\\") 先剝掉前導反斜線
```
📌 而它的 docstring 已經寫明**為什麼要擋來自資料庫的路徑**：
「資料庫裡的值是**很久以前某一次請求寫進去的**」。

---

## §3 `JV16` ② token 怎麼帶 —— 🔴 **不可以重用 `/api/uploads/`**

### 這個 repo 已經有一套，而**它的閘門比傳票弱**

```
GET /api/photo-token?path=...     _require_user            -> {token, ttl}
GET /api/uploads/{path}?pt=<sig>  **完全不檢查身分**
GET /api/uploads/{path}（無 pt）   _require_user
```

```python
# routers/uploads.py:105-110
if pt:
    if not _verify_photo_token(safe, pt):
        raise HTTPException(403, "照片連結已過期或無效，請重新載入")
else:
    _require_user(authorization)          # <= 有 pt 時這一行**根本不會跑**
```

☠️ **兩層都不夠**：
```
① `/api/uploads/` **沒有任何模組閘門** —— 任何登入者都讀得到
② `?pt=` 是 **HMAC(path:expires)**，**不綁使用者、不綁模組**
   => 一條 pt 連結 = 一小時內**任何人**（含未登入）都能取那個檔
```

🔴 而 `vouchers.py:60` 的註解逐字寫著這正是不可接受的：
> 「☠️ 而 `_require_user()` 單獨用是不夠的：那等於**任何登入者**都讀得到
> 全公司的會計憑證，而畫面上看不出來 —— 側欄沒有入口不代表 API 擋得住。」

⇒ **重用 `/api/uploads/` = 把整套 `_require_voucher_access` 繞過去。**

### ⚠️ 而「這不是既有外洩」**只對傳票這一側成立**

```
✅ 傳票附件目前**根本沒有檢視入口** => 沒有人這樣用過
   => 這一件是「**如果照最省力的方式做，就會製造一個**」，不是「已經漏了」
```

🔴 **而那句話不可以推廣到 `/api/uploads/` 整體。**

```
`/api/uploads/` 底下**現在就有東西**，而它沒有模組閘門：
   承攬商的**身分證影本／存摺影本**（`EM12` 修的正是它們的上傳）
=> 若它們走這條路，**任何登入者都讀得到**，而那是**既有狀態不是新造的**
```

> ### 📌 **本規格未檢查 `/api/uploads/` 既有內容的曝險。另案（D 正在查）。**

☠️ 我第一版寫的是「這不是既有外洩」——**我查的範圍是傳票，而那句話的寫法比範圍寬**。
🔑 〈判準的寬窄都會騙人〉：**否定句的射程要跟證據的射程一樣大。**

### ⚠️ `?token=` 那條路 **2026-09-22 已經拿掉了**（`FX21`）

`uploads.py:85-96` 逐字記著理由：**完整 session token 進 query string ⇒ 寫進
uvicorn access log（`logs/server.log`，永久追加）、瀏覽器歷史、`Referer`、中間代理**。
🔑 ⇒ **規格明著禁止任何形式的 token-in-URL**，包含「只是暫時測試」。

### ✅ 正解：`fetch` 取 blob

```js
async openAttachment(a) {
  const r = await fetch(`/api/vouchers/${this.id}/attachments/${a.file_id}`,
                        { headers: { Authorization: 'Bearer ' + this.session.token } })
  if (!r.ok) { this.attErr = '取得附件失敗（' + r.status + '）'; return }
  const url = URL.createObjectURL(await r.blob())
  window.open(url, '_blank')
  setTimeout(() => URL.revokeObjectURL(url), 60000)
}
```
⚠️ `revokeObjectURL` 的延遲**要與現有寫法一致**（`voucher.js` 那幾支用 60000）。
☠️ 立刻 revoke 會讓新分頁拿到空白 —— 而症狀是「按了沒反應」。

---

## §4 `JV16` ③ 預覽窗裡的附件區

### 顯示什麼

```
檔名 ／ 大小 ／ 來源（attFrom(a)：帶入的 還是 當場上傳的）
＋ **標出哪些會併進「含附件」的 PDF**（使用者早先裁過「要列並標出」）
```

### 🔴 「哪些併得進去」的規則**現在寫在後端，前端不可以重寫一份**

```
helpers/voucher_pdf.py:57   _IMAGE_EXTS = (".jpg", ".jpeg", ".png")
helpers/voucher_pdf.py:136  ext = splitext(filename)[1].lower()
                            (images if ext in _IMAGE_EXTS else pdfs).append(...)
=> 圖片走 <img>；其餘一律當 PDF 丟給 pypdf
```

☠️ **而副檔名只是其中一層** —— `voucher_pdf.py:363` 逐字：
> 「判『有沒有併進去』用**頁數差**，不是『有沒有丟例外』」
> 零頁 PDF 一個例外都不丟；加密 PDF 要到 `append()` 才丟。

```
前端算得出來的  副檔名分類（圖片／PDF／不支援）
**只有後端知道的**  檔案還在不在 ／ 零頁 ／ 加密
```

🔑 ⇒ 前端自己算一份的話，它必然是**比後端樂觀的版本** ——
畫面說「這 5 個都會併進去」，而實際只併進 3 個，**而使用者不會知道**。

⇒ **後端回欄位**：
```
GET /{voucher_id} 的 attachments 每一筆加 `mergeKind`
   "image" | "pdf" | "unsupported"
   由 voucher_pdf.py **同一支分類函式**算（抽成函式，不要複製條件）
⚠️ 而畫面的措辭要是「**預計併入**」不是「會併入」
   🔑 因為零頁／加密要到匯出那一刻才知道
   📌 而匯出後的實際結果**已經有回報了**（voucher.js:329
      「已匯出，而有 N 個附件沒有併進去」）=> 兩處措辭要對得起來
```

### ⚠️ 位置：**iframe 外面**

```
預覽 modal 的結構（voucher.html:520-540）
  .modal-body  -> .vc-preview-wrap -> <iframe :srcdoc="previewHtml">
  .modal-foot  -> 關閉 ／ 匯出 PDF ／ 匯出 PDF（含附件）
⇒ 附件區加在 .modal-body 裡、**iframe 旁邊或下方**
🔴 **不要塞進 previewHtml** —— 那是 preview_html() 產的，
   而它同時是給伺服器上的 Edge 印 PDF 用的（見 §1）
```

---

## §5 `JV17` 拿掉頁面那兩顆

### 兩組按鈕，**拿掉第一組的兩顆、留「預覽」**

```
第一組  voucher.html:461-473   `.vc-acts`（頁面下方）
        voucher-preview               ✅ **留**
        voucher-pdf                   ❌ 拿掉
        voucher-pdf-attachments       ❌ 拿掉
第二組  voucher.html:533-537   `.modal-foot`（預覽窗內）
        匯出 PDF ／ 匯出 PDF（含附件）  ✅ **留**
```

⚠️ `voucher.html:474-477` 那段 `vc-att__hint`（「『含附件』會把圖片與 PDF
憑證接在傳票後面…」）是**在解釋被拿掉的那兩顆** ⇒ **一起搬進 modal**，
不要留在原地變成一句沒有主詞的說明。

### 🔴 「拿掉的是入口，不是檢查」

實查所有會觸發匯出的路徑：

```
✅ voucher.js:293  exportPdf(withAttachments)   —— **唯一一支**
✅ voucher.js:300  fetch('/api/vouchers/' + id + '/pdf-download' + q)
                   —— 前端唯一打這支端點的地方
✅ 鍵盤快捷        voucher.html／voucher.js 的 keydown/keyup/addEventListener = **0**
✅ 清單頁入口      其他頁打 pdf-download 的都是 contractor-vouchers ／
                   invoice-vouchers（**不同端點、不同單據**）
🔴 而 `GET /api/vouchers/{id}/pdf-download` **仍然直接打得到**
```

> ### ⇒ 使用者要的是「**避免人員不確認就直接按匯出**」，
> ### 而那是一個**介面上的減速帶**，不是一道閘門。

```
✅ 它擋得住：手滑、不看就按
❌ 它擋不住：直接打端點、改前端、書籤
⚠️ **不要為此在端點加「必須先預覽過」的檢查** ——
   那需要伺服器記住「誰預覽過哪一張」，而那是一個新的狀態
   ☠️ 而它的失敗模式是「預覽過了卻說沒有」，比現在更糟
📌 現有的真閘門仍然在：`pdf-download` 會擋未簽核完成（`§228`：閘門綁端點）
```

---

## §6 驗收（`AC1`）

```
① 後端  GET /{id}/attachments/{file_id} 存在且走 _require_voucher_access
        GET /{id} 的 attachments 每筆帶 mergeKind
② 前端  附件列可點開（fetch->blob），**網址列不出現任何 token**
        預覽 modal 有附件區並標出預計併入
③ 頁面  ⓐ 頁面下方**只剩「預覽」一顆**
        ⓑ 開預覽 -> modal 內有附件清單 ＋ 兩顆匯出
        ⓒ 點一個附件 -> 開得起來
        ⓓ **沒有 cashier／finance 模組的帳號**打 GET /{id}/attachments/{fid} -> 403
           🔑 ⓓ 是 §3 的驗收 —— 沒有它就分不出「有做閘門」與「剛好沒人試」
```

---

## §7 守門

```
✅ 釘：`/api/vouchers/**` 的**每一支**端點都有 `_require_voucher_access`
   ⚙️ 正對照 新的取檔端點要在名單裡
   🎣 誘餌   自己加一支合成的無閘門端點，確認守門會亮
✅ 釘：前端**不出現 token-in-URL**
   ⚙️ 掃 frontend/ 的 `?token=`／`&token=`／`?pt=` 用在 vouchers 路徑上 = **0**
   ⚠️ 而 `?pt=` 在**案件附件**那邊是既有且合法的 ⇒ 判準要**綁 vouchers 路徑**，
      不是全站禁用 `?pt=`
      ☠️ 全站禁的話會紅在 case-management.js 寫對的碼上
✅ 釘：`mergeKind` 由**後端**算
   ⚙️ 掃 frontend/ 不出現 `.jpg`/`.png` 的副檔名判斷用在傳票附件上
   ⚠️ 反向控制：後端那支分類函式要**只有一份**
      （`voucher_pdf.py` 與新端點共用，不是各寫一次）
✅ 釘：頁面 `.vc-acts` 裡**沒有** `voucher-pdf` / `voucher-pdf-attachments`
   ⚙️ 負對照 `.modal-foot` 裡的那兩顆**必須還在**
      🔑 少了負對照，「兩顆都刪掉」也會全綠
```

---

## §8 我沒查什麼

```
① `mergeKind` 加進 GET /{id} 之後的**成本**：分類要 os.path.isfile()
   ⚠️ 我**沒有量**一張傳票有幾個附件、清單頁會不會連帶變慢
   ⇒ 若要省，副檔名分類是純函式（不碰磁碟），檔案存在與否留給預覽那一刻
② 附件的 **MIME/Content-Type** 怎麼回：FileResponse 會自己猜，
   而**猜錯的後果是瀏覽器下載而不是開啟** —— 沒查既有 uploads 那支怎麼處理
③ 預覽 modal 的**版面**（附件區放左還是放下）—— 那是設計不是規格
④ 附件很多（>20）時 modal 要不要捲動／分頁 —— 沒查現有附件數的分布
⑤ ⓓ 那一題要用哪個沒有模組的角色帳號 —— 沒查測試 fixture 有沒有現成的
```
