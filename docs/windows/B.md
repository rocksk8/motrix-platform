# 視窗 B — 寫手（只有 B 寫這一份）

> 開工順序：`MULTIWIN-PROTOCOL.md` → `docs/windows/STATE.md` → 這份。
> **你的角色：寫產品程式碼。你不寫任何測試。**

---

## 你能動的

- `backend/**`（**不含** `backend/tests/`）
- `frontend/**`

## 你不能動的

- `backend/tests/**` ← 那是 C 的
- 根目錄 `*.md`、`docs/**` ← 那是 A 的（**除了這一份**）

## 動之前要先在下面〈宣告〉段寫一行、等 A 回覆的鎖定檔

`backend/db.py` · `backend/main.py` · `frontend/static/sidebar.js` · `backend/helpers/__init__.py`

---

## 宣告（要動鎖定檔就寫在這）

| 時間 | 要動哪個鎖定檔 | 為什麼 | A 回覆 |
|------|--------------|--------|--------|
| 2026-09-21 | `backend/main.py` | 掛 `licensing.router` | ✅ **准**（STATE §5 回覆 B 第 1 項）。已動，只有兩行：第 25 行 import 末端加 `, licensing`、第 484 行 `app.include_router(licensing.router)`。**middleware 一個字沒碰。** |
| 2026-09-21 | `backend/helpers/__init__.py` | 條件性 re-export | ✅ **准但預設不動**（STATE §5 第 2 項）。**最後沒有動** —— C 的測試用 `from helpers import licensing as lic`，`helpers/__init__.py` 不需要改。 |
| 2026-09-21<br>第 2 輪 | `backend/main.py` | 掛授權守門 middleware。位置在 `auth_middleware` **之後**（先確認是誰，再確認這台機器有沒有買）。⚠️ **總開關做完並驗過之後才動這個檔** | ✅ **准**（STATE §5 第三次回覆）。已動，**只新增 53 行、無刪除** |
| 2026-09-21<br>第 3 輪 | **`backend/db.py`** | 加前置時間欄位與採購建議狀態。**migration 編號 `_m085_procurement_lead_time`**（目前 `CURRENT_VERSION = 84`，最後一支是 `_m084_backfill_role_bypass_modules`）。一支 migration 做三件事：①`suppliers` 加 `lead_time_days INTEGER`（預設 NULL）②`parts` 加同名欄位 ③新建 `purchase_suggestion_status` 表。⚠️ 協定 §3 明寫兩人同時加 migration 會產生兩個 `_m085_`、merge 不衝突、只在執行時撞版本號——**我在這裡把編號講死，A 若已派給別人請立刻回我** | ⬜ 等回覆 |

---

## 本輪狀態

- **輪次**：**第 2 輪**（細線 1 第 3 步：擋住）
- **第 1 輪**：✅ A 端驗收通過，程式碼 `2dadfb6`、視窗紀錄 `649f07f`
- **第 1 輪全量回歸**（我跑的，非 C 的⑥）：**1,055 過／55 skip／1 紅**，合計 1,111，數字對得上
  - 紅的是 `test_pdf_concurrency_2026_09_07.py::test_semaphore_caps_concurrent_holders`
  - **單獨重跑是綠的**；該測試只碰 `EDGE_PDF_SEMAPHORE` 與執行緒，與授權零交集
  - 當下**機器上有三個 pytest 同時在跑**（另兩個不是我的），該測試的第二個斷言
    `peak == max_concurrency`（「應該至少有一批真的頂到上限」）在 CPU 被搶時會頂不到
  - ⚠️ **我無法百分之百證明是哪一行紅的**：我把輸出接了 `tail -25`，traceback 被截掉了。
    這是我的失誤，下次全量回歸不接 `tail`。C 的⑥要在機器安靜時重跑一次才算數
- **狀態**：✅ **第 2 輪收尾完成**（細線 1 已凍結在第 3 步）／🟡 第 3 輪等 A 回覆 `db.py`
- **條件 12 · 全量回歸**（開關 `LICENSE_GATE_ENABLED = False`，＝正式機真正會跑到的狀態）：

  ```
  1056 passed, 55 skipped, 22 warnings in 1185.52s (0:19:45)
  ```

  **1056 ＋ 55 ＝ 1,111，零失敗**，與上一輪基準相同（協定 §4 ⑥「不可少於現況」✅）。

  ⚠️ **上一次那 1 題紅（`test_semaphore_caps_concurrent_holders`）這次自己好了。**
  兩次之間我沒有改過那支測試、也沒有改過它碰的任何東西（`EDGE_PDF_SEMAPHORE`／
  `startup.py`），唯一的差別是 A 停掉了他那支背景回歸。
  **這是「CPU 搶奪造成」這個說法唯一一次真的被驗證**——先前我只能說「單獨跑是綠的」，
  那不足以下結論（單獨跑就過，正是 flaky 測試的樣子）。現在有了對照組。
  ⚠️ 但這仍**不能取代 C 的⑥**：我跑的是 B 自己的工作樹，⑥是 C 的職責且是權威結果。
- **第 2 輪 commit**：`fb329be`（開關＋kind＋快取）→ `a63cc49`（middleware）
  兩個 commit 是刻意分開的：開關沒驗過之前不掛 middleware

> ⚠️ **不要在 C 的測試紅之前開始寫碼。** 協定 §4 的②先於④是刻意的：
> 先有測試才寫碼，測試就不可能是照著你的實作長出來的。

---

## 改了哪些檔、為什麼

> 一行一個完整路徑 ＋ 一句為什麼。寫「小修」等於沒寫。
> 沒改任何檔案就寫「無」，**不要留白** —— 留白讀起來像忘了填。

（第 1 輪，`2dadfb6`）
```
backend/helpers/licensing.py   【新增】授權金鑰核心
backend/routers/licensing.py   【新增】GET /api/license/status
backend/tools/issue_license.py 【新增】離線簽發 CLI
backend/main.py                【改 2 行】掛 router
```

（第 2 輪，`fb329be` ＋ `a63cc49`）
```
backend/helpers/licensing.py   LICENSE_GATE_ENABLED（預設 False）、kind 年費/永久、
                               LICENSE_EXEMPT_PATHS 具名常數、金鑰檔快取、
                               license_blocks_request()／license_block_message() 純函式
backend/tools/issue_license.py 加 --kind 參數（預設 subscription）
backend/main.py                【新增 53 行、無刪除】license_gate_middleware
```

**私鑰放在哪、有沒有進 .gitignore**（收工檢查表要求明確回報）：

- 路徑：`backend/tools/_license_private_key_dev.pem`（Ed25519，PKCS8，未加密，chmod 600）
- 公鑰已內嵌 `helpers/licensing.py` 的 `_PUBKEY_DEV`，會進 git（公鑰本來就是公開的）
- `_PUBKEY_PROD` ＝ `b""`，**照契約留空**，驗證時略過不丟例外
- **產檔前**先跑 `git check-ignore -v`：四條金鑰路徑全部命中 `.gitignore:11`／`:13`
- **產檔後**複驗 `git status --porcelain | grep -i "pem\|license.key"` → **空輸出**
- 沒有在 repo 內留下任何 `license.key`：手測用的金鑰寫在 scratchpad，`verify_license(None)`
  現在回 `missing`（＝ `backend/license.key` 確實不存在）

**沒有新增任何相依套件**：`cryptography>=42.0.0` 本來就在 `requirements.txt:14`。
**沒有動 `db.py`、沒有 migration、沒有建資料表**（金鑰是檔案）。

---

## 給彙整（A 會收進 STATE.md）

> 發現的問題、要動別人的檔、規格對不上、需要裁決的事，寫在這裡。
> **不要自己擴充規格範圍**；覺得該多做什麼，寫在這裡讓 A 決定。

> 第 1、2 輪的提報 A 都已收進 STATE §5 並結案。以下是**第 3 輪**開工前的事。

- ✅ **條件 7 已裁決：採用②（一次採購循環），A 已改寫開發單（`309d330`）。**
  新條件 7：(a) `received` 後庫存回到水位之上 → 不出現（**是庫存算出來的，不是狀態抑制的**）
  (b) 庫存仍低 → 要再次出現，而且是新的一輪（回到 `suggested`）。
  **這改變了實作形狀**：狀態表**完全不參與清單的過濾**，清單純粹由庫存算出來，
  狀態只是附註。`ordered` 留在清單裡（東西在路上，採購要看得到）。
  **「新的一輪」不在 GET 裡寫 DB**（GET 有副作用是另一種難查的 bug）：
  改成一支 `_effective_status(stored, 目前是否低於水位)` 純函式，
  **GET 與狀態轉移端點都走同一支** —— 兩邊各自判斷就會各自對、合起來錯，
  這正是我跟 A 講 §8 時說的「讓兩邊被迫走同一支函式」。
  轉移端點看到 stored=`received` 而 effective=`suggested` 時，
  接受 `suggested → ordered` 並清掉上一輪的 `received_at`，開始新的一輪。

- 🟠 **三個我自己決定的實作細節**（都是例行判斷，不需要 A 回覆，寫出來是為了可稽核）：
  - 狀態表 `purchase_suggestion_status`，以 `part_no` 為主鍵，一個料號一列（＝目前那一輪）
  - 狀態轉移端點 `POST /api/inventory/purchase-suggestions/{part_no}/status`
    （條件 6 要求「跳過中間狀態要被拒絕」，所以轉移必須有一支端點來拒絕它）
  - `ordered` 仍然留在清單裡（條件 7 只講 `received`）——東西還在路上，採購要看得到
- ⚠️ **協定改了：`--basetemp` 要分用途（全量 `-full`／臨時單檔 `-adhoc`），我照改。**
  C 實測 pytest 每次 session 開始會把 `--basetemp` **整個刪掉重建**。
  我先前**全量與單檔都用同一個 `motrix-pytest-B`** —— 跟 C 踩到的是同一個形狀。
  回頭查了自己的時序：兩次全量回歸期間我都沒有再跑 pytest（只跑了不用 pytest 的
  驗證腳本），所以**沒有真的撞到，但只差一步**。已改用 `-full`／`-adhoc`。

- ⚪ 解析順序照單子寫：`parts.lead_time_days` → 該料號最近一筆進貨的供應商 → NULL。
  第二層我會沿用既有的 `last_batch_by_part`（`inventory.py:148`，已經算好 `supplierId`），
  **不另外寫一套查詢** —— 單子明寫「不要順手重構既有邏輯」。

- 🔴🔴 **「用 mtime 判定重讀」不夠，快取鍵還必須包含「今天的日期」。**
  這是本輪最重要的一項，而且它會**完全符合全部 12 條驗收條件**之後才在客戶那裡發作。
  `days_left` 是拿 `date.today()` 算出來的。快取鍵只有 mtime 的話，一台**不重啟的
  正式機**會永遠沿用第一次算出來的值——今天算「還有 1 天」，明天、明年都還是
  「還有 1 天」，**年費授權就這樣變成永久授權，而且不會有任何錯誤訊息**。
  諷刺的是這正是第 1 輪決定「不快取」的原因（A 的原話：「第 6 步到期提醒本來就要
  每天重新判定 days_left，啟動時快取的話服務不重啟就永遠不會提醒」）——
  **加了快取就等於把那個問題原封不動地放回來了**，只是換成一天以上的粒度。
  已把 `date.today().toordinal()` 放進快取鍵，成本 0.76 微秒。
  **建議 §3〈第 3 步預先註記〉那句「用 mtime 判定重讀」補上這一項**，
  不然下一個人照那句話寫會再中一次。
- 🔴 **Starlette 是「後宣告的先跑」，所以「位置在 `auth_middleware` 之後」要寫在它前面。**
  開發單寫的是執行順序（先確認是誰，再確認有沒有買），但照字面當成**原始碼順序**
  寫在 `auth_middleware` 後面的話，守門會變成最外層、**先跑**。
  後果沒有任何錯誤訊息：未登入的請求會收到 402 而不是 401，而且對還沒通過身分
  驗證的人洩漏「這台機器沒有授權」。
  本檔第 350 行附近既有註解 `Registered last = outermost` 講的就是這件事，
  我另外用一支最小 app 實測確認過，並在自我驗證裡放了一題專門釘它
  （「沒金鑰 + 未登入 → 必須是 401 不是 402」）。
  **建議 C 的驗收測試也要有這一題** —— 它是這一輪唯一一個「寫反了全部條件還是綠」的地方。
- 🟠 **`kind` 刻意不列入 `_REQUIRED_FIELDS`。** 第 1 輪簽出來的金鑰沒有這個欄位，
  列為必要會讓它們從 `ok` 變成 `malformed`——那不是「保守」，那是把已發出的授權弄壞。
  缺漏／拼錯／型別不對／沒見過的值一律正規化成 `subscription`（會被擋那一邊）。
  只有明確寫著 `perpetual` 才算永久。⚠️ 我做成**不分大小寫**：`kind` 在簽章範圍內，
  客戶改不動它，所以這裡寬鬆不是攻擊面，只是避免自己簽錯字。若 A 要嚴格比對，
  改一行就好。
- 🟠 **middleware 裡刻意不包 try/except，這是一個我替 A 做了的決定，請覆核。**
  `verify_license()` 契約上任何情況都不丟例外，C 也有測試釘住。萬一它真的丟了：
  包起來放行＝授權形同虛設、包起來擋住＝付費客戶整套系統癱瘓、不包＝那一支 API 回 500。
  我選不包，理由是本專案自己的原則——**500 會被報修，「出錯就放行」是降級，
  而降級不會有人報修**。但這是可用性與正確性的取捨，A 可能有不同看法。
- 🟢 **實測數字**（供第 3 步之後參考）：`verify_license()` 含讀檔 0.90 ms／次；
  加快取後 0.143 ms／次（6.3 倍）；`os.stat()` 0.12 ms；指紋已快取時 0.0001 ms。
  以內部 ERP 的請求量來說，就算完全不加快取也撐得住（約 1,110 次／秒），
  加快取是為了**第 3 步之後每個 request 都會走到這裡**，不是因為現在慢。
- ⚪ 小事：豁免清單裡的 `/api/auth/logout` 實際是 **POST**，我用 GET 打它會 404
  （不是 402，所以豁免本身是對的）。C 寫第 8 題時記得用對的 method，
  否則會驗成「404 也算通過」——那題就變成在驗 route 不存在。

---

## 收工檢查表

- [ ] 改的檔案都在我的歸屬範圍內（鎖定檔有宣告並拿到 A 回覆）
- [ ] `git status` 看過，`git add` 只加到檔案層級，沒有 `git add <目錄>`
- [ ] 上面〈改了哪些檔、為什麼〉填完了
- [ ] 有沒有動 `db.py` schema？有的話在〈給彙整〉明確寫出 migration 編號
- [ ] 有沒有新增相依套件？有的話寫進〈給彙整〉，**不要自己改 `requirements.txt` 就算了**
- [ ] 有沒有產生不該進 git 的檔案（私鑰、憑證、金鑰）？有沒有加進 `.gitignore`？
