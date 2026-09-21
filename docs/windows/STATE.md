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
| `backend/helpers/license.py` | **B** | 金鑰的簽發驗證核心 |
| `backend/routers/license.py` | **B** | `GET /api/license/status` |
| `backend/tools/issue_license.py` | **B** | 離線簽發 CLI |
| `backend/main.py` | **B** | 掛 router（**鎖定檔，B 動之前在 `B.md` 宣告**） |
| `backend/tests/test_license_core_2026_09_21.py` | **C** | 驗收測試 |

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

**核心函式**（`helpers/license.py`）：
- `machine_fingerprint() -> str` — 主機板 UUID ＋ 第一張實體網卡 MAC 的 sha256 前 16 碼
- `sign_license(payload: dict, private_key_pem: bytes) -> str`
- `verify_license(blob: str) -> LicenseStatus` — 回
  `{valid, reason, customer, modules, expires, days_left}`；
  `reason` 是 `ok` / `missing` / `bad_signature` / `machine_mismatch` / `expired` / `malformed`

**端點**：`GET /api/license/status` — **本輪先只要求登入即可讀**，第 3 步再收權限。

**公私鑰**：
- 公鑰**硬編在 `helpers/license.py`**，進 git。
- 私鑰產出後存 `backend/tools/_license_private_key.pem`，**加進 `.gitignore`，絕對不進 git**。
  B 要在 `B.md` 明確回報「私鑰放在哪、有沒有進 .gitignore」。

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

### 反向驗證（C 在第⑤步做，不可省）
把「簽章驗證」那一行註解掉 → **第 2 題必須精準變紅，其餘 7 題仍綠**。
若第 2 題沒紅，代表它驗到的是自己設的值，退回重寫。

### 不做
- 不要碰 `main.py` 的 middleware（那是第 3 步）
- 不要碰任何既有 router、不要碰 `db.py`
- 不要建資料表（金鑰是檔案，不進 DB）

---

## §4 · 等使用者決定

| # | 事項 | 為什麼卡著 | 狀態 |
|---|------|-----------|------|
| 1 | **金鑰私鑰要放哪裡、誰保管** | 不可逆＋密碼學＋會出貨，三條全中。私鑰外洩＝所有授權形同虛設；私鑰遺失＝所有客戶都不能續約。**第 1 輪可以先用開發用臨時金鑰做完，但正式簽發前必須有答案** | 🔴 未決 |
| 2 | **金鑰裡的模組清單用哪一套 key** | 現有 35 個使用者模組旗標是「人能看什麼」，授權模組是「機器買了什麼」，兩套粒度不一定該一樣（例如選型資料庫七類可能該整包賣、不分開） | 🟠 第 4 步前要決 |
| 3 | **賣的是永久授權還是年費** | 決定第 6 步「到期」的語意：年費到期要擋住，永久授權到期只是不再更新 | 🟠 第 6 步前要決 |

## §5 · 紀律提醒（給所有視窗）

- 不准用 `HEAD~1`／`$(git rev-parse HEAD)`／`ls -t | head -1` —— 共用目錄，會指到別人的東西
- `git add` 只到檔案層級，不要 `git add <目錄>`
- pytest 一律帶 `--basetemp`
- 收工一定更新自己的視窗檔；沒寫下來的結論等於沒發生
