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

---

## 本輪狀態

- **輪次**：第 1 輪
- **狀態**：🟢 **寫完，C 的 27 題全綠**（`pytest tests/test_licensing_core_2026_09_21.py` → `27 passed`）
- **依據**：`docs/windows/STATE.md` §5〈本輪最終契約〉（不是 §3 的舊段落）
- **全量**：`--collect-only` ＝ **1,111**（基準 1,084 ＋ 新增 27，對得上）
- **A 端驗收**：✅ 通過（範圍、私鑰、契約逐項）。程式碼已進 `2dadfb6`（四個檔）
- **下一步**：第 2 輪，開發單在 `docs/windows/STATE.md` §3

> ⚠️ **不要在 C 的測試紅之前開始寫碼。** 協定 §4 的②先於④是刻意的：
> 先有測試才寫碼，測試就不可能是照著你的實作長出來的。

---

## 改了哪些檔、為什麼

> 一行一個完整路徑 ＋ 一句為什麼。寫「小修」等於沒寫。
> 沒改任何檔案就寫「無」，**不要留白** —— 留白讀起來像忘了填。

```
backend/helpers/licensing.py   【新增】授權金鑰核心。Ed25519 簽發／驗證、機器指紋、
                               LicenseStatus 七欄位。模組叫 licensing 不是 license
                               （license 是 Python 內建名稱，會在 main.py 命名空間被蓋掉）。
backend/routers/licensing.py   【新增】GET /api/license/status。本輪只要求登入。
                               端點路徑刻意仍用 license（對外介面用一般人看得懂的字）。
backend/tools/issue_license.py 【新增】離線簽發 CLI：fingerprint／genkey／issue 三個子指令。
backend/main.py                【改 2 行】第 25 行 import 加 licensing、第 484 行掛 router。
                               middleware 一個字沒碰（那是第 3 步）。
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

> 依 STATE §5〈本輪最終契約〉施作完成。先前那幾項提問 A 都已回覆，不再重複。
> **契約沒有被我改動任何一個字**；下面是施作中發現、A 需要知道的事。

- 🔴 **`PhysicalAdapter=true` 不等於實體網卡，照字面寫會讓客戶的授權莫名其妙失效。**
  這台開發機上，WMI 把 **TAP-Windows（OpenVPN）** 與 **藍牙 PAN** 都標成
  `PhysicalAdapter=true`，而且 `Sort-Object DeviceID` 是**字串排序**（"19" < "6" < "7"），
  「第一張實體網卡」會抽到 TAP-Windows。使用者哪天移除 OpenVPN，指紋就變了，
  **已經發出去的金鑰全部失效，而且沒有任何錯誤訊息說明為什麼**。
  已用 `PNPDeviceID` 再篩一層（只留 `PCI\` 與 `USB\` 開頭），並且**排序後取最小的 MAC**
  而不是「列舉順序的第一個」——列舉順序會因裝置增減而變動，排序過的最小值不會。
  **這件事值得寫進 SPEC**：它不是實作細節，是「授權會不會自己壞掉」。
- 🟠 **`wmic` 在 Win11 26200 已經不存在了。** 改用 PowerShell CIM，冷啟約 **2 秒／行程**。
  所以 `machine_fingerprint()` **在行程內有快取**（存的是從硬體讀出來的值，
  不是啟動時的隨機值，所以 `test_07b` 跨行程那題仍然綠）。
  ⚠️ **第 3 步要特別注意**：那時 `verify_license()` 會掛進 middleware、每個 request 跑一次。
  `verify_license()` 每次重讀檔是契約要求，**但指紋的那層快取不可以一起拿掉** ——
  拿掉就變成每個 request spawn 一次 PowerShell（700ms～2s）。
  本專案有過簽核卡死 32.8 秒的前例，形狀一模一樣。
- 🟠 **`env` 的契約我照字面執行，但有一個代價，A 可能想在第 3 步改回來。**
  「簽章驗過但 `expires` 不是日期」這種情況，我其實**知道**是哪把私鑰簽的，
  但契約寫「malformed → `env` 為 None」，所以我回 None。
  留一個例外會讓「malformed 就是 None」變成「大部分時候是 None」，而日後打包關卡
  是照規則寫的 —— 我選了規則。**若 A 要的是資訊量，這一行改一個字就好**，但要一起改契約。
- 🟠 **指紋算不出來時，現在會回 `machine_mismatch`，這對現場除錯是誤導。**
  硬體來源全部讀不到 → `machine_fingerprint()` 丟 `RuntimeError` →
  `verify_license()` 接住它並**拒絕該筆**（不是放行 —— 「讀不到就當它對」等於把鎖拆掉）。
  但客戶看到的是「機器不符」，會往「金鑰發錯機器」查，而真正的原因是「這台讀不到硬體」。
  **本輪不擴充**（契約只有六個 reason）。建議第 3 步加一個 `fingerprint_unavailable`，
  已先在程式裡把這條路徑註解清楚。
- ⚠️ **目前沒有任何東西在檢查 `env != "prod"`。** `env` 查得到了，但第 7 步的打包關卡
  還不存在（契約明寫本輪不做）。在那之前，**開發金鑰被帶進出貨包仍然不會有錯誤訊息** ——
  `env` 只是讓它「查得出來」，不等於「擋得住」。這條建議直接寫進第 7 步的開發單。
- 💡 **第 7 步有一個比「打包時檢查」更強的做法，是寫碼時才看出來的。**
  驗證迴圈對**空的公鑰直接略過**（本輪是為了 `_PUBKEY_PROD` 留空而寫的），
  這個性質反過來用就是：**出貨版把 `_PUBKEY_DEV` 設成 `b""`，開發金鑰就直接驗不過。**
  差別很大——「打包時檢查 `env != "prod"`」是一道**會被繞過或忘記跑**的守門，
  而「出貨版根本沒有那把公鑰」是**結構上不可能**。兩者可以並存，但後者才是真的防線。
  ⚠️ 代價是出貨版與開發版的原始碼會有一行不同，需要在打包流程裡處理（不是本輪的事）。

---

## 收工檢查表

- [ ] 改的檔案都在我的歸屬範圍內（鎖定檔有宣告並拿到 A 回覆）
- [ ] `git status` 看過，`git add` 只加到檔案層級，沒有 `git add <目錄>`
- [ ] 上面〈改了哪些檔、為什麼〉填完了
- [ ] 有沒有動 `db.py` schema？有的話在〈給彙整〉明確寫出 migration 編號
- [ ] 有沒有新增相依套件？有的話寫進〈給彙整〉，**不要自己改 `requirements.txt` 就算了**
- [ ] 有沒有產生不該進 git 的檔案（私鑰、憑證、金鑰）？有沒有加進 `.gitignore`？
