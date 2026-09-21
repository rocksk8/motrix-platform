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
| 2026-09-21<br>第 4 輪 | **`backend/db.py`** | 標案雷達四張表。**migration `_m086_tender_radar`**（`CURRENT_VERSION` 85→86）。A 已在 §3 交付物指派並說「開工吧…四張表」 | ✅ **准**（§3 交付物）。已動，實跑確認 `DB migration 86/86` |
| 2026-09-21<br>第 4 輪 | **`backend/main.py`** | 掛 `tender_radar.router`。只動 2 行 | ✅ **准**（§3 交付物列了 router） | 
| 2026-09-21<br>第 4 輪 | **`frontend/static/sidebar.js`** | ⚠️ **等 A 回覆，尚未動。** `tender-radar.html` 沒有側欄入口就只能手打網址。需要三處：`cTender = has('dev_crm')` 一類的旗標、`'tender-radar.html': 'dev_crm'` 的頁面→模組對應、`ni(pg('tender-radar.html'), …)` 的選單項。**A 沒有把 `sidebar.js` 列進 §3 交付物**，所以我停手 | ✅ **准**（`47add8e`，A 承認漏列）。已動，並依裁決**新建 key `tender_radar`** 而不是沿用 `dev_crm` |

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
- **輪次**：**第 4 輪**（細線 6 標案雷達第 1～3 步）
- **狀態**：🛑 **第 4 輪停手。SHA = `a18adf9`**（最後一個動 `backend/`／`frontend/` 的 commit）
  在 C 回報⑤⑥之前，我不再動 `backend/` 或 `frontend/` 任何一個字。
  ⚠️ 這不是形式：⑥要跑 20 分鐘，受測對象在那 20 分鐘裡被改的話，**⑥的結果就沒有意義**
  （C 提的方案①，A 採用）。之後只會動 `docs/windows/B.md`——它不在 C 的 `fp()` 範圍、
  pytest 也不讀它。
- **C 的 46 題**：**46 passed / 0 failed**（先前 43 紅 3 綠）。
  ⚠️ **這個數字我上一輪就跑出來了，卻只講在對話裡、沒有寫進這裡，也沒有回報給 A。**
  A 是對的：**沒有回報不能當成綠燈**——那正是 §5c 那條。這一項記在這裡當教訓。
- **模組 key 三方一致性**：`test_module_keys_consistency` ＋ `test_module_permission_fixes`
  ＋ `test_dark_mode_chrome_structure` ＋ C 的 46 題 ＝ **94 題全綠**
- **全量回歸**：⚠️ **我沒有跑完。** 起跑後 A 派下模組 key 的工作，我**主動砍掉**那一支——
  它量的是 `7309864`（改模組 key 之前），留著會變成一個**看起來像數字、其實過期**的結果，
  而且會跟 C 的⑥搶 CPU。⑥是 C 的職責且是權威結果，由它跑。
- **A 已驗過停手握手**（不是相信我，是跑 `git log a18adf9..HEAD -- backend frontend` 查空）。
  ⚠️ A 順帶修掉自己寫錯的判準：原本寫「兩個 SHA 對得起來」，但**A 自己 commit 文件之後
  HEAD 就會往前跑**，那會誤報。正確判準是「`<宣告SHA>..HEAD` 對 `backend`／`frontend` 是空的」
  ——**往前跑的都不是產品碼**，不是 HEAD 沒動。
- **C 的⑤已完成：六個突變全部發火。** ⑥跑中（約 20 分鐘），由 C 回報。
- 📌 **C 查出一件關於我自己程式碼的事實，值得記著**：`_parse_row` 的形狀驗證
  **不是一道檢查，是三道**（機關含中文／機關不可像日期／截止日非空要解得出），
  C 試了四版才繞得過。**它比我自己以為的厚。**
  ⇒ 這件事的用處在未來：**下一個人看到那三行會想「這不是重複嗎」而合併掉其中兩道**，
  而合併之後反向驗證第 5 題仍然會紅（還剩一道），**看起來完全正常**。
  三道各自擋的是不同的欄序錯位組合，不是同一件事講三遍。

### 📌 第 5 輪首項（A 已排定，現在**不要動**）

`published` → `published_at`：**解析 dict 的鍵**改名，與 C 的 `test_06e` **同一輪一起改**
（我單獨改會讓那題紅）。

A 清點的實況是**三種拼法橫跨三層**：
解析 dict `published`（`tender_source.py:244,381`）／DB 欄 `published_at`／API 與前端 `publishedAt`。
**API 那一層的不同是有意義的**（跨邊界，`leadTimeDays` 那次定案過）；
**解析 dict 那一層沒有**——它跟 DB insert 在相鄰兩行，中間沒有轉換層。

⚠️ **A 不現在改的理由值得抄下來**：不是它不重要，是**可出貨**。
它使用者看不到、API 看不到、DB 看不到，影響是 0；而現在改要解除停手、重新宣告、
讓 C 再等一輪——**把一個為了讓⑥有意義而設的握手，花在一件對⑥沒有影響的事上**。
🔑 **握手是用來保護驗證的，不是用來保護整潔的。**
- **第 3 輪 commit**：`4edf210` 實作 → `6613224` A 的兩項裁決 → `9c2e70c` 備份登記修補
- **自我驗證**：29/29（scratchpad 腳本，不進 repo、沒碰 `backend/tests/`）
- **全量回歸（`-full`，驗 `9c2e70c`）**：

  ```
  1056 passed, 55 skipped, 22 warnings in 1040.66s (0:17:20)
  ```

  **零 FAILED**，1056 ＋ 55 ＝ **1,111**，與基準相同。
  題數沒有增加是**對的**：這一輪我沒有寫任何測試（C 還沒寫第 3 輪的），
  新增的是一張表與兩個欄位，不是新的題目。

  ⚠️ **前一支（驗 `4edf210`）是 1 failed**，紅的就是我漏登記備份那一題，
  修掉之後這一支才是零。**兩支都記在這裡，不要只留好看的那一支** ——
  那一紅是這一輪唯一一個「自我驗證永遠抓不到」的缺口被抓到的證據。

  ⚠️ 這**仍不能取代 C 的⑥**：我跑的是 B 自己的工作樹，⑥是 C 的職責且是權威結果。
  而且這一輪 ②先於④ 破了（A 已認錯並補進協定 §4），
  所以 C 的⑤要比平常更嚴 —— **只讀開發單、不讀我的實作**。
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

（第 3 輪後續，`6613224` ＋ `9c2e70c`）
```
backend/routers/inventory.py   收掉第三份黃燈門檻字面值（_stock_level 改用模組常數，
                               連 docstring 裡那句「安全庫存 * 1.5」也改成引用常數名）
frontend/pages/suppliers.html  舊「標準交期」改為遷移提示＋legacyLeadTimeCount
backend/archive.py             把 purchase_suggestion_status 登記進每日 JSON 備份
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
- 🔴 **全量回歸抓到一個我的漏洞，而且是「產品碼全綠也抓不到」的那種。**
  `test_system_audit_2026_09_14::test_every_table_is_either_backed_up_or_explicitly_excluded`
  ——我加了 `purchase_suggestion_status` 卻**沒有決定它要不要進每日 JSON 匯出**。
  那題的 docstring 問得很準：「這張表的資料如果要靠 JSON 重建，重建得出來嗎？」
  **處置是「加進備份」不是「加進排除清單」**：「這個料號是哪天下單的、哪天到貨的」
  在系統裡**沒有第二個來源**——採購建議本身是即時從庫存算出來的，
  **重算得出清單、重算不出這段歷史**。已加進 `archive.py::_daily_backup()`（`9c2e70c`）。
  也查了還原路徑：整庫 `.db` 是主路徑，JSON 是 §8.3 還原優先序的「最後手段」人可讀層
  （`archive.py:1039`），沒有第二張對應表要同步維護。
  ⚠️ **這一條我的自我驗證腳本永遠抓不到**——它驗的是 API 行為，
  而這是一道跨檔案的登記守門。全量回歸不是形式。
- 🟢 **從那個漏洞看出的一件更值錢的事（A 已採納，`8e971f1`）：這道守門只擋「新表」，
  擋不到「新欄位」。** 我這輪也加了兩個欄位，但那兩張表本來就在備份清單裡、
  備份語句又是 `SELECT *`，所以新欄位自動跟著進去——**這次是運氣好**。
  哪天有人在一張備份語句是**列舉欄位**的表上加欄位，守門不會紅，
  而那個欄位從加進去那天起就沒被備份過，直到真的需要還原才會知道。
  A 查證後指出既有的 `test_every_backup_query_actually_runs` 已經在做同一件事的一半
  （拿 `cursor.description` 對 `PRAGMA table_info`，只是範圍限在 BLOB 欄位），
  所以是**延伸既有機制而不是新建一套**。
  ⚠️ 我說「它現在會是綠的」不是缺點：**綠著的守門不是沒用的守門，是還沒被觸發的那一種。**
- ⚪ 差點犯的一個小錯，記著提醒自己：我在 `inventory.html` 寫了 `class="btn-mini"`，
  **那個 CSS 類別整個專案不存在**，是我自己發明的——按鈕會變成沒有樣式的裸按鈕。
  commit 前 grep 了一次才發現。前端沒有型別檢查，寫錯的類別名不會有任何錯誤訊息。

- 🟠 **提報給 A：這個 repo 缺 `.gitattributes`，而缺它會讓「用 git 還原檔案」悄悄改掉位元組。**
  （C 在跑⑥時發現的，我在這棵樹上查證了條件成立。**不動手，等 A 決定。**）

  **查證過的事實**（我剛實際讀的，非推論）：
  ```
  core.autocrlf = true
  .gitattributes = 不存在
  磁碟上的 .py / .html = 全部 LF（含我從沒碰過的 archive.py、routers/auth.py、helpers/auth.py）
  磁碟上的 .bat / .ps1 = 全部 CRLF，需要 BOM 的都有 ← 這部分專案處理得對，不需要動
  ```

  **後果**（機制由 C 在丟棄式 repo 裡實測證明，條件在這裡成立；
  ⚠️ 我**沒有**在這棵樹上重現，因為當時 C 正在量它）：
  `git checkout -- <某支 .py>` 會把它拉回 **git 認為的樣子**＝ CRLF。
  `git diff` 看不出來（它會正規化），但磁碟上的位元組變了、內容雜湊會變。

  **真正的形狀比「git 會改行尾」深一層**（C 的講法，比我的準）：
  > 工作樹長期由「不經過 git 的工具」維護，於是它偏離了 git 認為 checkout 該產出的樣子。
  > 平常沒事，直到有人用 git 去「還原」一個檔——那一刻 git 把它拉回 git 的版本，
  > 而那跟原本磁碟上的不是同一串位元組。
  > **「還原」這個詞在這裡會騙人：它還原成 git 認為的原樣，不是你動手之前的原樣。**

  **最容易中的是突變測試**（改檔 → 跑 → `git checkout` 還原）。
  C 第 1、3 輪全走 monkeypatch 所以沒中，**但那是運氣不是設計**。

  **✅ 已由 A 加上（`e9929d1`），而且是零改寫的。**

  ⚠️ **上面那段警語我原本寫的是錯的，留在這裡當紀錄**：我抄了「它會重寫整棵樹的
  位元組 ⇒ 不可以在任何人跑回歸時做、做完要重跑一次當新基準」。
  **那是一個沒查證的假設**（A 提出、我原封不動轉述）。A 後來去查物件庫才發現
  **ODB 裡存的本來就全是 LF**，加規則只是把「checkout 該產出什麼」講清楚：
  實測 0 個追蹤檔被視為修改、`.bat`／`.ps1` 與備份逐位元組相同。

  **教訓（A 的話，我認同）：「延後的理由」也要被查證。**
  延後看起來像謹慎，而**謹慎地做錯事比急著做對事更難被質疑**。
  而那個被延後的風險在決定延後的 30 分鐘內就真的發生了（C 把 `C.md` 轉成了 CRLF）。
  ⇒ 對我的具體修正：**轉述別人的風險評估時，要嘛自己查證，要嘛標明「這是轉述、我沒查」。**
  我當時兩件都沒做。

---

## 收工檢查表

- [ ] 改的檔案都在我的歸屬範圍內（鎖定檔有宣告並拿到 A 回覆）
- [ ] `git status` 看過，`git add` 只加到檔案層級，沒有 `git add <目錄>`
- [ ] 上面〈改了哪些檔、為什麼〉填完了
- [ ] 有沒有動 `db.py` schema？有的話在〈給彙整〉明確寫出 migration 編號
- [ ] 有沒有新增相依套件？有的話寫進〈給彙整〉，**不要自己改 `requirements.txt` 就算了**
- [ ] 有沒有產生不該進 git 的檔案（私鑰、憑證、金鑰）？有沒有加進 `.gitignore`？
