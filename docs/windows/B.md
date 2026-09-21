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
| 2026-09-21<br>第 3 輪 | **`backend/db.py`** | 加前置時間欄位與採購建議狀態。**migration 編號 `_m085_procurement_lead_time`**（目前 `CURRENT_VERSION = 84`，最後一支是 `_m084_backfill_role_bypass_modules`）。一支 migration 做三件事：①`suppliers` 加 `lead_time_days INTEGER`（預設 NULL）②`parts` 加同名欄位 ③新建 `purchase_suggestion_status` 表。⚠️ 協定 §3 明寫兩人同時加 migration 會產生兩個 `_m085_`、merge 不衝突、只在執行時撞版本號——**編號在宣告裡講死** | ✅ **准**（A 另查證 `_m085` 零命中、無人在改 `db.py`）。已動 |

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
- **狀態**：🟢 **第 3 輪產品碼寫完**（`4edf210`），自我驗證 29/29；全量回歸跑中（`-full`）
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

（第 3 輪，`4edf210`）
```
backend/db.py                  migration _m085_procurement_lead_time（84→85）：
                               suppliers/parts 各加 lead_time_days INTEGER（預設 NULL）、
                               新建 purchase_suggestion_status
backend/helpers/procurement.py 【新增】全是純函式：clean_lead_time／resolve_lead_time／
                               compute_eta／effective_status／effective_cycle／
                               validate_transition。三個 router 走同一套判定
backend/routers/suppliers.py   lead_time_days 進出；驗證移到 broad except 之外
backend/routers/parts.py       lead_time_days 進出；照既有 safety_stock 的慣用法
backend/routers/inventory.py   採購建議加 leadTimeDays／eta／status；
                               新增狀態轉移端點；_YELLOW_MULTIPLIER 提為模組常數
frontend/pages/inventory.html  三個新欄位＋狀態按鈕；更正過期的說明文字
frontend/pages/suppliers.html  前置時間（天）數值欄位
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

> 第 1、2 輪已結案。以下是**第 3 輪**的提報。

- 🔴 **供應商表單裡「本來就有」一個前置時間欄位，現在變成兩個，請 A 裁決怎麼收。**
  `frontend/pages/suppliers.html:636` 有 `form.leadTime`，標籤「標準交期」，
  自由文字（placeholder 寫「例：30 天、4~6 週」），存在 `data_json` 裡。
  我 grep 過整個 `backend/`：**沒有任何一行後端程式碼讀它** ——
  這就是 SPEC §5.1 說的「`lead_time` 實測 0 處」的真身：**欄位一直都在，只是沒人用**。
  這一輪加的 `lead_time_days` 是真欄位、數值、進得了計算，兩者現在並存。
  我把舊的改標成「標準交期（說明）」並註明「系統不拿它算日期」，新的標「前置時間（天）」，
  **但這只是把混淆寫清楚，沒有消除混淆**。
  ⚠️ **不做資料遷移是刻意的**：`"4~6 週"` 要怎麼變成一個整數，不是我該替使用者決定的。
  請 A 裁決：① 維持並存 ② 退休舊欄位（要先確認沒有客戶在用它記別的東西）
  ③ 做一次人工協助的遷移。
- 🟠 **我動了一行既有程式碼，單子說「不要順手重構」，所以明講。**
  `inventory.py` 原本 `yellow_multiplier = 1.5` 是函式內的字面值。我把它提成模組常數
  `_YELLOW_MULTIPLIER` 並讓那一行引用它。**只有這一行，演算法一個字沒動。**
  理由：新的狀態轉移端點要判斷「這個料號現在還缺不缺貨」，必須跟清單用同一個門檻。
  兩邊各留一份字面值的話，某天有人只改一邊，就會出現「清單上看得到、
  轉移時卻說它不缺貨」——兩邊各自都對、合起來錯。
  ⚠️ **`parts_summary()::_stock_level()` 裡還有第三份 `1.5`**，是既有的，這一輪照單子不動它。
  它跟我的兩處目前一致，但它是**下一個會漂的地方**，建議排進某一輪處理。
- 🟢 **自我驗證第一次跑就抓到兩個真的 bug，值得記下形狀。**
  1. 清單算出 `status="suggested"`（新的一輪），卻把**上一輪的** `orderedAt` 原樣回傳。
     狀態欄對、時間欄對，合起來是「這一輪還沒下單，但下單時間是 3 天前」。
     **這正是我在同一輪裡警告過 A 的形狀，然後我自己寫了出來。**
     修法不是在清單那邊補一段 if，是把判定收進 `effective_cycle()`，
     讓清單與轉移端點**走同一支** —— 補 if 只會製造第三個判斷點。
  2. `create_supplier` 的 `except Exception` 把 `clean_lead_time()` 丟的 422 吞成 409，
     負數前置時間會回「建立失敗：...」而不是說明原因。驗證移到 `try` 之外。
  ⚠️ 兩個都不會被「程式跑得起來」這件事抓到。**第一個連 12 條驗收條件都可能全綠**
  （C 若只驗 `status` 欄位就驗不到）。建議 C 的測試對第 7 題加驗 `orderedAt`。
- ⚪ 差點犯的一個小錯，記著提醒自己：我在 `inventory.html` 寫了 `class="btn-mini"`，
  **那個 CSS 類別整個專案不存在**，是我自己發明的——按鈕會變成沒有樣式的裸按鈕。
  commit 前 grep 了一次才發現。前端沒有型別檢查，寫錯的類別名不會有任何錯誤訊息。

---

## 收工檢查表

- [ ] 改的檔案都在我的歸屬範圍內（鎖定檔有宣告並拿到 A 回覆）
- [ ] `git status` 看過，`git add` 只加到檔案層級，沒有 `git add <目錄>`
- [ ] 上面〈改了哪些檔、為什麼〉填完了
- [ ] 有沒有動 `db.py` schema？有的話在〈給彙整〉明確寫出 migration 編號
- [ ] 有沒有新增相依套件？有的話寫進〈給彙整〉，**不要自己改 `requirements.txt` 就算了**
- [ ] 有沒有產生不該進 git 的檔案（私鑰、憑證、金鑰）？有沒有加進 `.gitignore`？
