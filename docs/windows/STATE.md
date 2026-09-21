# STATE — 權威交接檔（只有視窗 A 寫）

> 更新：2026-09-21 · 由視窗 A 維護。B／C 要交接的事寫在自己的視窗檔「給彙整」段，A 收進來。
> **每個視窗開工順序：`MULTIWIN-PROTOCOL.md` → 這份 → 自己的視窗檔。**

---

## §1 · 現在在哪裡

| | |
|---|---|
| 機器 | **開發機**（`hichan`，`C:\Users\hichan\Desktop\MOTRIX-ERP`） |
| 基準 commit | `b6e29ea`（與 `origin/master` 同步，工作樹乾淨） |
| 本期目標 | 兩條端到端細線，見 [`SELLABLE-AND-MOBILE-SPEC.md`](../../SELLABLE-AND-MOBILE-SPEC.md) |
| 目前這條線 | **細線 1 · 授權底座**（細線 2 手機版要等它七步走完） |
| 本輪 | **第 1 輪** |

## §2 · 兩條細線的進度

**細線 1 — 授權底座**（七步定義見 SPEC）

| 步 | 內容 | 狀態 |
|---|------|------|
| 1 | 產一把金鑰 | ⬜ 未開始 ← **本輪** |
| 2 | 裝進一台機器、status 端點 | ⬜ 未開始 ← **本輪** |
| 3 | 無效／過期要擋住（402） | ⬜ 未開始 |
| 4 | 金鑰決定開哪些模組 | ⬜ 未開始 |
| 5 | 抬頭不再寫死（124 處） | ⬜ 未開始 |
| 6 | 到期前提醒 | ⬜ 未開始 |
| 7 | 換機裝得上去 | ⬜ 未開始 |

**細線 2 — 手機專用頁面**：七步全部 ⬜，等細線 1 完成。

---

## §3 · 本輪開發單（第 1 輪）

### 目標
**細線 1 第 1、2 步**：能產一把金鑰、放進機器、問得到它的狀態。

### 交付物

| 檔案 | 歸屬 | 內容 |
|------|------|------|
| `backend/helpers/licensing.py` | **B** | 金鑰的簽發驗證核心 |
| `backend/routers/licensing.py` | **B** | `GET /api/license/status` |
| `backend/tools/issue_license.py` | **B** | 離線簽發 CLI |
| `backend/main.py` | **B** | 掛 router（**鎖定檔，B 動之前在 `B.md` 宣告**） |
| `backend/tests/test_licensing_core_2026_09_21.py` | **C** | 驗收測試 |

### 規格（照這個寫，不要自己擴充）

**金鑰內容**（JSON，再連同簽章一起 base64）：
```
{
  "customer":    "某某公司",
  "tax_id":      "12345678",
  "machine":     "<指紋 sha256 前 16 碼>",
  "modules":     ["quotation", "case_manage", "..."]  或 ["*"] 代表全開,
  "issued":      "2026-09-21",
  "expires":     "2027-09-21",
  "sig":         "<Ed25519 簽章>"
}
```

**核心函式**（`helpers/licensing.py`）：
- `machine_fingerprint() -> str` — 主機板 UUID ＋ 第一張實體網卡 MAC 的 sha256 前 16 碼
- `sign_license(payload: dict, private_key_pem: bytes) -> str`
- `verify_license(blob: str) -> LicenseStatus` — 回
  `{valid, reason, env, customer, modules, expires, days_left}`；
  `reason` 是 `ok` / `missing` / `bad_signature` / `machine_mismatch` / `expired` / `malformed`

**端點**：`GET /api/license/status` — **本輪先只要求登入即可讀**，第 3 步再收權限。

### ⚠️ 雙金鑰對：開發用臨時金鑰必須「結構上」分得出來

> 使用者 2026-09-21 裁示：**私鑰先用開發用臨時金鑰，正式的之後再決定。**
>
> 這件事的風險不在「臨時金鑰不能用」，在**它能用**。開發金鑰跟正式金鑰簽出來的
> 授權長得一模一樣、行為一模一樣，所以它被帶進出貨包的那一天，不會有任何錯誤訊息。
> 壞掉會被報修，**降級不會**。因此不靠命名慣例、不靠記得，**做成結構上可偵測**：

- `helpers/licensing.py` 內嵌**兩把公鑰**：`_PUBKEY_DEV` 與 `_PUBKEY_PROD`。
- `verify_license()` **兩把都試**，並在回傳值裡帶 **`env`**：
  用開發公鑰驗過的 → `env="dev"`；用正式公鑰驗過的 → `env="prod"`；都驗不過 → `bad_signature`。
- 本輪 `_PUBKEY_PROD` **先放空字串**（正式金鑰尚未產生），驗證時自動略過，**不可以丟例外**。
- `GET /api/license/status` 回傳中要有 `env`。

這樣「這台機器裝的是開發金鑰」就變成一個**查得到的事實**，而不是一個要記得的事。
日後打包關卡只要檢查 `env != "prod"` 就能擋，不必翻檔名或問人。

**公私鑰**：
- 兩把公鑰**硬編在 `helpers/licensing.py`**，進 git（公鑰本來就是公開的）。
- 開發私鑰產出後存 `backend/tools/_license_private_key_dev.pem`。
- **`.gitignore` 已由 A 於 `0ea90d6` 之後預先補好**（`backend/license.key`／
  `backend/tools/_license_private_key*.pem`／`**/*_private_key*.pem`）——
  **B 產金鑰之前先確認 `git status` 看不到那個 .pem**，看得到就先停下來問 A。
  私鑰一旦進了 git 歷史就拔不乾淨，而離線驗證**沒有撤銷清單**，已發出的授權撤不回來。

### 驗收條件（C 先寫成測試，寫完應該是紅的）

1. 簽一把有效金鑰 → `verify_license` 回 `valid=True, reason="ok"`
2. **改動 payload 任何一個位元組 → `reason == "bad_signature"`**
   （⚠️ 這題最容易寫成假綠燈：不要驗「簽章字串不一樣」，要驗 `verify_license` 的回傳值）
3. `machine` 換成別的指紋 → `reason == "machine_mismatch"`
4. `expires` 設成昨天 → `reason == "expired"`，且 `days_left` 是負數
5. 檔案不存在 → `reason == "missing"`，**不可以丟例外**（服務要起得來）
6. 亂碼／截斷的 blob → `reason == "malformed"`，**不可以丟例外**
7. `machine_fingerprint()` 同一台機器連呼叫兩次結果相同
8. `GET /api/license/status` 未登入回 401、登入後回得到 `customer` 與 `days_left`
8b. **沒有金鑰檔時，status 端點回 `200` ＋ `{valid:false, reason:"missing", customer:null}`**
    —— **不是 402 也不是 404**。402 是第 3 步用來擋業務 API 的；
    status 端點本身必須永遠讀得到，否則現場沒授權時連「為什麼沒授權」都查不出來
    （這正是 B 在 `B.md` 問的第 3 題，A 確認採用 B 的判斷）
9. **開發私鑰簽的金鑰 → `valid=True` 且 `env == "dev"`**
10. **`_PUBKEY_PROD` 是空字串時，驗證要正常跑完不丟例外**
    （正式公鑰還沒產生，這是本輪的真實狀態，不是邊界情況）
11. **`GET /api/license/status` 的回傳裡有 `env` 這個鍵**
    ——沒有它，日後打包關卡就沒有東西可以檢查

### 反向驗證（C 在第⑤步做，不可省）

兩題，都要做：

1. 把「簽章驗證」那一行註解掉 → **第 2 題必須精準變紅，其餘仍綠**。
   若第 2 題沒紅，代表它驗到的是自己設的值，退回重寫。
2. 把 `env` 的判定改成永遠回 `"prod"` → **第 9 題必須精準變紅**。
   這題是在驗「開發金鑰認得出自己」，不是在驗字串比對。

⚠️ 「結束碼非 0」不等於「那一題紅了」——要同時確認**紅的是你指名的那一支**。
⚠️ 突變沒抓到時，第一個假設要是「突變寫錯了」，不是「被測對象沒問題」。

### 不做
- 不要碰 `main.py` 的 middleware（那是第 3 步）
- 不要碰任何既有 router、不要碰 `db.py`
- 不要建資料表（金鑰是檔案，不進 DB）
- **不要產正式金鑰對**（`_PUBKEY_PROD` 留空，等使用者決定私鑰保管方式）
- 不要在打包腳本加檢查（那是第 7 步；本輪只要讓 `env` 查得到）

---

## §4 · 等使用者決定

| # | 事項 | 為什麼卡著 | 狀態 |
|---|------|-----------|------|
| 1 | **正式簽發私鑰要放哪裡、誰保管** | 不可逆＋密碼學＋會出貨，三條全中。私鑰外洩＝所有已發出的授權形同虛設**且撤不回來**（離線驗證沒有撤銷清單）；私鑰遺失＝所有客戶都不能續約。**✅ 2026-09-21 使用者裁示：第 1 輪先用開發用臨時金鑰，正式的之後再決定。**<br>⇒ 已做成結構可偵測（雙公鑰＋`env` 欄位，見 §3），不靠人記得。<br>**仍然待決，且是出貨前的硬關卡**：`_PUBKEY_PROD` 一天是空的，這套系統就一天不能真的賣出去。回來決定時要一起定：私鑰存在哪個實體媒介、誰有權限、備援副本放哪、萬一外洩的處置流程（現在沒有撤銷機制 ⇒ 處置流程只能是「換公鑰＋重發全部客戶金鑰＋強迫每一台更新」，要先知道這個代價再決定保管方式） | 🟡 本輪已解鎖，**出貨前必須回來** |
| 2 | **金鑰裡的模組清單用哪一套 key** | 現有 35 個使用者模組旗標是「人能看什麼」，授權模組是「機器買了什麼」，兩套粒度不一定該一樣（例如選型資料庫七類可能該整包賣、不分開） | 🟠 第 4 步前要決 |
| 3 | **賣的是永久授權還是年費** | 決定第 6 步「到期」的語意：年費到期要擋住，永久授權到期只是不再更新 | 🟠 第 6 步前要決 |

## §5 · A 對視窗提問的回覆

> **A 不寫 `B.md`／`C.md`。** 回覆一律寫在這裡，視窗自己來讀。
> （兩個人編輯同一個表格儲存格，正是協定 §3 要防的撞車。B.md 的「A 回覆」欄由 B
> 自己把這裡的結論抄過去，或直接留白寫「見 STATE §5」。）

### 2026-09-21 · 回覆 B 的五項（`B.md`〈宣告〉＋〈給彙整〉）

| # | B 問什麼 | A 的裁決 |
|---|---------|---------|
| 1 | 動 `backend/main.py` 掛 router | ✅ **准**。就是你說的那兩行，`include_router` 接在 `accounting_export` 之後。**不要碰 middleware**。 |
| 2 | 動 `backend/helpers/__init__.py` re-export | ✅ **准，但預設不動**，照你的判斷。`from helpers.licensing import verify_license` 是對的寫法；只有 C 的測試真的需要才加。 |
| 3 | `.gitignore` 歸誰 | **歸 A**，已由 A 做完，**B 不用動**。它是 repo 層級的守門而不是程式碼，而且私鑰進了 git 歷史就拔不乾淨——這種不可逆的東西要在 B 產金鑰**之前**就位，不能等宣告往返。<br>已補三條並**實測**（不是只看有沒有寫進去，你這點提得對，工作樹≠repo）：<br>`git check-ignore -v backend/tools/_license_private_key_dev.pem` → `.gitignore:13:**/*_private_key*.pem`<br>`git check-ignore -v backend/license.key` → `.gitignore:11:backend/license.key`<br>兩個假檔建起來 `git status` 都看不到，已刪除。**你照常產私鑰即可。** |
| 4 | `license` 會遮蔽 Python 內建名稱 | ✅ **你是對的，照你的建議改**：模組一律叫 **`licensing`**——`helpers/licensing.py`、`routers/licensing.py`、測試 `test_licensing_core_2026_09_21.py`。開發單已同步改好（5 處）。<br>**檔名 `backend/license.key` 不改**（那是資料不是模組），**端點路徑 `/api/license/status` 也不改**（對外介面用一般人看得懂的字）。 |
| 5 | 沒金鑰時 status 回什麼 | ✅ **採用你的判斷**：`200` ＋ `{valid:false, reason:"missing", customer:null}`。已寫進驗收條件 **8b**，C 的測試會照這個驗。理由：402 是第 3 步擋業務 API 用的，status 端點本身必須永遠讀得到，否則現場沒授權時連原因都查不出來。 |

**給 B 的一句話**：五題都問在點上，尤其第 3 題「寫了不等於生效」。繼續等 C 的紅燈再動產品碼。

---

## §6 · 紀律提醒（給所有視窗）

- 不准用 `HEAD~1`／`$(git rev-parse HEAD)`／`ls -t | head -1` —— 共用目錄，會指到別人的東西
- `git add` 只到檔案層級，不要 `git add <目錄>`
- pytest 一律帶 `--basetemp`
- 收工一定更新自己的視窗檔；沒寫下來的結論等於沒發生
