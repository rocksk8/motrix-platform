# PDF 渲染硬化第二輪：設計筆記（H1 之後；hichan-1f；只讀原碼，未實作）

## 0. 第一輪（H1，wip/h1-pdf-hardening-r2）做了什麼、留下什麼
`helpers/startup.run_edge_pdf`（21 個呼叫端的單一出入口）渲染前：①把 CSP `<meta id="motrix-csp">` 寫進 HTML（`default-src 'none'`、`img-src data: file:`、`style-src 'unsafe-inline'`、`font-src data: file:`、frame／object／form／base／connect／media／worker 全 `'none'`、`script-src` 只有『最終 HTML 裡內嵌腳本』的 SHA-256）；②Edge 旗標 `--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE localhost`、`--disable-extensions`、`--disable-sync`。③五個輸出點補 `esc`。

**第一輪刻意接受的殘留**（都需要『有一個未逸出的輸出點』才打得到；輸出逸出是第一道防線，CSP 是第二道）：
R1 腳本白名單來自『最終 HTML』——已經注入進頁面的 `<script>` 也會被算進白名單。
R2 CSP 擋不住**頂層導航**：`<meta http-equiv="refresh" content="0;url=file:///…">`、`location=`（需要腳本）。導到 `file:///C:/…/win.ini` 會把檔案當成頁面渲染進 PDF。
R3 `--host-resolver-rules` 只管名稱解析，**直接寫 IP 的網址**（`http://10.0.0.5/`、`http://169.254.169.254/`）不受影響（目前靠 CSP 的 `connect/img/frame-src` 擋；導航仍可達）。
R4 `img-src file:` 允許載入任何本機圖片檔（只能是圖片，但仍是本機檔案洩漏）。
R5 `--no-sandbox` 仍在（全部 4 種組命令的地方都帶）。

## 1. R1：預先算好的腳本雜湊（建議做；S～M）
**事實：所有內嵌腳本都是靜態文字**，沒有一支夾帶單據資料：
| 腳本 | 位置（platform） | 用途 |
|---|---|---|
| `_FIT_A4_SCRIPT` | `helpers/doc_template.py:16`（版型引擎 `render()` 結尾） | 內容過高時 `body.style.zoom` 縮到 A4（≥ 0.70） |
| `_PAYSLIP_SCRIPT` | `helpers/doc_template.py:505` | 薪資單專用版面調整 |
| 報價單／出貨單縮放（多行版） | `pdf_gen.py:533`、`:1362`、`completion_pdf.py:255` | 同一段 fit-A4，三份文字相同 |
| 承攬匯款申請、請款單縮放（單行版） | `pdf_gen.py:1750`、`:2333` | 同一段，單行寫法（文字與多行版不同 ⇒ 雜湊不同） |
| 預覽高度回報 | `pdf_gen.py:644` | `postMessage` 給預覽 iframe；**只加在預覽 HTML，不經 Edge**，不在本題範圍 |
| 網路規劃書分頁 | `modules/netplan/export.py:522` | 依內容算 `@page` 尺寸（會動態建立 `<style>`；`style-src 'unsafe-inline'` 已涵蓋） |
實際只有 **約 5 種不同文字**（兩種 fit-A4 寫法、薪資單、netplan）。

設計：新增 `helpers/pdf_scripts.py`：把這幾段腳本文字收成具名常數（builder 改成引用常數，輸出逐位元不變），模組載入時算 `SCRIPT_HASHES = {name: 'sha256-…'}`；`_csp_for_html` 的 `script-src` **只用這個註冊表**，不再掃最終 HTML。頁面裡不在註冊表的 `<script>` ⇒ 不給雜湊 ⇒ 被 CSP 擋（R1 消除）。
守門題：①AST 掃描 builder 檔案，任何 `<script` 字面值必須是引用註冊表常數（新增腳本必須登記）；②註冊表每一支的雜湊＝CSP 裡的雜湊；③真的渲染：頁面含『註冊的腳本＋注入的另一段腳本』，只有前者執行（用 `document.title` 或 `zoom` 值當探針，PDF 文字可驗）。
成本：builder 約 8 處機械式替換；風險＝腳本文字必須與常數逐字相同（含換行），所以要有『輸出逐位元相同』的黃金題（H1 的前後渲染回歸已可沿用）。
替代方案 nonce：每次渲染產生隨機 nonce、builder 的 `<script>` 都要帶 `nonce`；需要改每個 builder 且攻擊者若能注入 `<script>` 仍拿不到 nonce（較強），但 builder 改動較多；雜湊登記法已足夠且對 builder 侵入較小。若日後出現『腳本夾帶單據資料』才改用 nonce。

## 2. R2：頂層導航（meta refresh）——CSP 擋不住，要在 HTML 層或瀏覽器層處理
選項（可疊加）：
A. **出入口 HTML 中和**：在 `run_edge_pdf` 寫 CSP 的同一步，把不該出現的標籤／屬性中和掉：`<meta http-equiv=refresh>`、`<base>`、`<iframe|frame|object|embed|applet|portal>`、`<link>`（除了我們自己）、所有 `on*=` 屬性、`javascript:`／`data:text/html` 網址、`<script>`（不在註冊表）。實作用 `html.parser.HTMLParser` 取標籤位置、只改寫命中的標籤（不重排整份文件）。前提：builder 本來就沒有這些——用一個掃描測試鎖住（已掃描 pdf_gen、doc_template、completion_pdf、voucher_pdf、netplan（export／topology）、reports、bonus_pdf：**沒有任何 `on*=` 屬性、`<base>`、`<link>`、`http-equiv`**；`<iframe|object|embed>` 只在 voucher_pdf 的一段**註解文字**裡出現（沒有實際標記）——掃描測試把這個清單鎖住）。風險：誤傷合法標記；用前後渲染回歸（H1 測試）＋『builder 原始輸出不含被中和的標籤』斷言防住。
B. **瀏覽器層**：Edge 沒有『禁止導航』旗標；`--disable-features=…` 無對應項。可行的是**把渲染改成 CDP 控制**（`--remote-debugging-pipe` ＋ `Page.setDocumentContent` 載入 HTML、`Fetch.enable` 攔截所有請求只放行 `data:`、`Page.printToPDF`、頂層導航事件 `Page.frameRequestedNavigation` ⇒ 中止）。這是**較大的改動**（要寫小型 CDP 客戶端、處理逾時與 profile），建議列第三輪，不在本輪。
C. 補強：把 `file:` 導航的風險降到只剩圖片（見 R4）——若所有圖片都內嵌成 `data:`，導航到 `file:///…win.ini` 仍會顯示文字，所以 C 不是替代品。
建議：先做 A（出入口中和）＋R1（雜湊註冊），B 留待之後。

## 3. R3：直接寫 IP 的 SSRF
`--host-resolver-rules` 不攔 IP 字面值。對策：強制所有 http(s) 走一個**必定連不上**的代理：`--proxy-server=http://127.0.0.1:9`（discard 埠；本機沒人聽）＋ `--proxy-bypass-list=<-loopback>`（連 loopback 也不繞過代理）；`file:`／`data:` 不經代理。驗證要**實測**：測試開一個 127.0.0.1 監聽埠＋一個 LAN 位址（或第二個 loopback 位址 127.0.0.2）當目標，用 `<meta refresh>`／`<img>`／`fetch` 三種方式觸發，控制組（無旗標）有連線、硬化後 0。注意 Edge 在受管機器上可能被群組原則覆蓋代理設定——要在正式機同一環境驗一次。
附帶：`--host-resolver-rules` 保留（對應 DNS 外洩），兩者疊加。

## 4. R4：`img-src file:`
現況需要 `file:` 的只有**傳票附件圖**（`voucher_pdf.build_html` 的 `<img src='file:///ABS'>`）。做法：該 builder 改成讀檔並內嵌 `data:` URI（受大小上限，沿用既有附件大小檢查）⇒ CSP 的 `img-src` 與 `font-src` 去掉 `file:`，只留 `data:`。其餘 builder 的圖片本來就是 `data:`（資料庫內的 base64）。成本小（1 個 builder）；回歸＝傳票附件 PDF 前後頁數與圖片數相同（H1 沒涵蓋傳票，這裡一併補）。

## 5. R5：移除 `--no-sandbox` 的可行性（要實測，現在不能下結論）
事實：`--no-sandbox` 出現在所有組命令處（pdf_gen 15、voucher_pdf、reports、netplan、completion 等）；程式碼與文件沒有寫明為什麼加（歷史原因推測：服務以高權限或受限 session 執行時 Chromium 沙箱無法建立）。**要回答的問題**：正式機 uvicorn 服務跑在哪個帳號／完整性層級（SYSTEM？一般管理員？受限服務帳號？）？
步驟（全在**測試機複製正式機設定**上做，不動正式機）：①`Get-CimInstance Win32_Process`＋`tasklist /v` 查服務帳號與 session；②用同一帳號、同一 session 寫一支 canary 腳本：以『不帶 `--no-sandbox`』渲染 H1 測試的幾份 HTML，記錄結束碼與錯誤輸出（Chromium 沙箱失敗的典型訊息：`Sandbox cannot access executable`／`Check failed: ... LowIntegrity`）；③若成功：以環境變數 `MOTRIX_EDGE_SANDBOX=1` 開關（預設仍帶 `--no-sandbox`），`run_edge_pdf` 依旗標移除；先在測試機跑整個 PDF 測試集，再上正式機灰度（一種文件類型一天）；④若失敗：評估把服務改跑在非提權的服務帳號（Windows 沙箱需要『不是 SYSTEM／不是高完整性』的 token）——這是**運維決策**（要使用者同意），不是程式問題。
沙箱是深度防禦：它擋的是『渲染器被攻破』之後的逃逸；第一、二輪已大幅降低被攻破的機會。優先序低於 R1／R2／R3。

## 6. 建議順序與切片
1. **H2-a**（M）：R1 腳本註冊表＋`script-src` 只用註冊表＋守門題；同一刀加 R3 代理旗標（含實測）。
2. **H2-b**（M）：R2-A 出入口標籤中和（含掃描測試與前後渲染回歸）。
3. **H2-c**（S）：R4 傳票附件圖內嵌 data URI，CSP 去掉 `file:`。
4. **H2-d**（調查）：R5 沙箱實測與運維決策。
5. 第三輪（大）：CDP 控制渲染（頂層導航與所有請求在瀏覽器層封死）。
每一刀都沿用 H1 的測試骨架（真的 Edge、控制組必須會洩漏、前後渲染回歸）；每刀單獨可回滾（出入口單一）。

## 7. 要使用者（PM）裁示的
①是否同意 R5 調查（可能涉及改服務帳號）；②H2-a/b/c 是否排在 t62 之後的熱修列車；③傳票附件圖改內嵌 `data:` 的大小上限沿用現有附件上限，OK？
