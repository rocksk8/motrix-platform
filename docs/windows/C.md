# 視窗 C — 驗證常駐（只有 C 寫這一份）

> 開工順序：`MULTIWIN-PROTOCOL.md` → `docs/windows/STATE.md` → 這份。
> **你的角色：寫測試、跑測試、瀏覽器實測。你不寫任何產品程式碼。**

---

## 你能動的

- `backend/tests/**`

## 你不能動的

- `backend/**`（`tests/` 以外）、`frontend/**` ← 那是 B 的。
  **發現產品碼有 bug，不要自己修** —— 寫在〈給彙整〉，由 A 派給 B。
- 根目錄 `*.md`、`docs/**` ← 那是 A 的（**除了這一份**）

---

## 你的兩個責任（順序不能顛倒）

### ① 開發單一出來，先把驗收測試寫成紅的

**「紅不起來」＝這題沒在驗東西，立刻退回 A，不要往下走。**

紅完之後在下面〈紅在哪〉填：哪一題、紅在哪一行、錯誤訊息是什麼。
B 要靠這段知道「綠」的定義。

### ② B 說綠了之後，做反向驗證

**把 bug 放回去，確認那一題精準變紅、其餘仍綠。**

這一步不可省。理由：
- 觀測點要挑「**成功後才會被寫入**」的下游欄位，不是自己設的值
- 「結束碼非 0」不等於「那一題紅了」，**也可能是你改壞了別的東西** ——
  要同時檢查紅的是不是你指名的那一支測試
- 突變本身也會寫錯，而寫錯的樣子跟「被測對象沒問題」一模一樣。
  **「突變沒抓到」的第一個假設要是「突變寫錯了」**

---

## 跑測試的固定指令

```bash
cd backend
python -m pytest tests/ --basetemp=C:/Users/hichan/AppData/Local/Temp/motrix-pytest-C -q
```

⚠️ **`--basetemp` 不可省**：不帶它，測試全過也會回非 0；而且 `%TEMP%` 每跑一次留
1～2 GB 不自動清（2026-09-14 曾清出 190 GB）。

⚠️ **`--basetemp` 的路徑要固定是 `-C` 結尾這一個，不要用時間戳或 `$(date)`** ——
共用工作目錄，會動的名字會指到別人的東西。

🔴 **兩個視窗不可以共用同一個 `--basetemp` 路徑（連單檔測試都不行）。**
pytest 會把 `--basetemp` 指到的目錄**整個刪掉重建**，時機是**第一次有測試用到
`tmp_path`／`tmp_path_factory`**（不是 session 一開始 —— 完全不碰 tmp_path 的 run
什麼都不會刪，這也是為什麼它很難重現）。本專案的 `conftest.py::_app` 幾乎一啟動
就呼叫 `tmp_path_factory.mktemp()`，所以實際上等同「一跑就刪」。

於是第二個 pytest 會把第一個正在用的 `motrix_app0/motrix_erp.db` 刪掉，
第一個 run 接著爆 `sqlite3.OperationalError: unable to open database file`。

**失敗的樣子會裝成產品 bug**：紅的是一支跟你完全無關的測試（我這次是
`test_reports_sales_owner_2026_09_14.py::test_achievement_uses_same_attribution_as_performance`），
單獨跑它 100% 綠。⚠️ **協定 §5 第 5 條只規範「全量回歸」，擋不住這個** ——
我那次是**單檔測試**撞上別人的全量回歸，跑單檔的人不會覺得第 5 條在講自己。
詳見〈給彙整〉第 9 點。

全量回歸基準：**136 檔、1,084 題**（2026-09-21 `--collect-only` 實測，不含本輪新增的 27 題）。
少於這個數字就是有東西沒被跑到。本輪加上去之後是 **137 檔、1,111 題**。

⚠️ **基準只能用 `pytest --collect-only` 算，不可以用 `grep -c "def test_"`。**
原本這裡寫的 `1,034` 就是 grep 出來的，差的 50 題是 7 個檔的 `parametrize` 展開。
（A 已於 2026-09-21 複驗、改掉 `MULTIWIN-PROTOCOL.md` §4 與 `SELLABLE-AND-MOBILE-SPEC.md` §0，
並把這條寫成協定。見〈給彙整〉第 4 點。）

---

## 本輪狀態

- **輪次**：**第 3 輪（暖身輪）** —— 供應商前置時間 ＋ 採購建議 ETA／狀態
- **狀態**：✅ **②⑤⑥全部做完，37 題全綠、全量回歸 1,129 題 0 失敗**（等 A 派下一步）
- **命名爭議**：A 已裁決**改 §3 不改實作**（`8b903eb`），`_LEAD_FIELD` 已跟著 §3 改成 camelCase
- **本輪的檔**：
  - `backend/tests/test_procurement_leadtime_2026_09_21.py`（條件 1～8、8b，共 17 題）
  - `backend/tests/test_system_audit_2026_09_14.py`（條件 **8c**，延伸既有守門，該檔 19 → 20 題）
- **契約來源**：`docs/windows/STATE.md` §3 的 **11 條**驗收條件

### 🔴 我沒有讀實作

**這一輪的測試是只讀 `STATE.md` §3 寫出來的。
我沒有開過 `backend/helpers/procurement.py`，也沒有開過 `backend/routers/inventory.py`。**

②（C 先寫紅測試）先於 ④（B 寫碼）的順序這一輪被打破了，紅燈順序的保證不存在，
**這句話是這一輪唯一剩下的憑據**，所以它必須是真的。我取得契約的四個來源：

| 我需要知道的 | 我從哪裡拿到 | 算不算讀實作 |
|---|---|---|
| 端點路徑、回應欄位、狀態機 | `STATE.md` §3 明文 | 否 |
| 燈號門檻 `ceil(safety×1.5)`、`items[]` 長相 | **我自己的** `test_purchase_suggestions_2026_09_07.py` | 否 |
| 狀態端點的 URL | FastAPI route table（`main.app.routes`） | 否，那是介面 |
| B 實際回的欄位名 | **打 API 看回應**（用完即刪的探針測試） | 否，那是行為 |
| ⑤突變的接縫名稱與簽名 | `dir()` 與 `inspect.signature` | 否，那是介面 |

**我沒有用過 `inspect.getsource`，也沒有 `cat`／`sed`／`grep` 過那兩個檔的內容。**

---

## 第 3 輪 · 跑出來的結果（4 紅 33 綠）

```bash
cd backend
python -m pytest tests/test_procurement_leadtime_2026_09_21.py tests/test_system_audit_2026_09_14.py   --basetemp=C:/Users/hichan/AppData/Local/Temp/motrix-pytest-C-adhoc -q
```

**4 個紅全部是同一件事**，而且**不是功能沒做**：

| | |
|---|---|
| §3 明文規定 | `lead_time_days`（snake_case） |
| B 實際回 | **`leadTimeDays`**（camelCase） |

紅的是 `test_02`、`test_03`、`test_04[7]`、`test_04[30]` —— 全都卡在讀不到那個欄位。

**我沒有改測試去遷就實作。** 我把紅燈訊息改成會自己說明是哪一種不一致，
現在跑出來直接寫著「不要把這一行改成 camelCase 來讓它變綠」。詳見〈給彙整〉第 11 點。

其餘全部正常：`eta` 回 `2026-09-28`（＝今天 ＋7，正確）、`status`／`orderedAt`／
`receivedAt` 都在，四個邊界燈號全對。

---

## 第 3 輪 · ⑤反向驗證（四個突變，每一個都精準命中）

**基準線**：套上欄位名別名（把命名那一層拿掉）之後 **17 全綠**。
⚠️ 這一步是必要的：**已經紅的題目沒辦法拿來做突變測試** —— 突變要證明的是
「這題會從綠變紅」。別名只活在那個行程裡，測試檔本身沒有被改成遷就實作。

| 突變 | 打在哪個接縫 | 結果 |
|---|---|---|
| 料號／供應商優先序對調 | `resolve_lead_time` 兩個參數互換 | **只有 `test_02` 紅**（1 紅 16 綠）|
| 前置時間未知回 `0` 不回 `None` | `resolve_lead_time` 包一層 | **只有 `test_03` 紅**（1 紅 16 綠）|
| 狀態轉移永遠放行 | `validate_transition` → `None` | **只有 `test_06` 紅**（1 紅 16 綠）|
| 開新一輪時沿用舊的 `ordered_at` | `effective_cycle` 只改一個欄位 | **只有 `test_07c` 紅**（1 紅 16 綠）|
| （8c）把一個刻意略過的欄位從清單移除 | `_BACKUP_OMITTED_ON_PURPOSE` | **只有 `test_backup_export_covers_every_column` 紅** |

§3 只要求兩個突變（條件 2、條件 3），我多做了條件 6、7c 與 8c ——
那三個是 A 在訊息裡特別點名、或我自己認為最容易假綠的。

### ⚠️ 第四個突變我第一次寫錯了，而錯的樣子是「12 題紅」

`keep_ordered` 第一版我寫成 `return stored_row`，結果 **12 題紅**。

**第一個假設要是「突變寫錯了」，不是「測試不精準」** —— 查下去果然是我錯：
`stored_row` 在全新料號上是 `None`，等於把每一筆的狀態計算整個打掉。
我用一個只印輸入輸出的探針查出 `effective_cycle` 的真實形狀
（回 `{status, ordered_at, ordered_by, received_at, received_by, new_cycle}`），
改成**只動 `ordered_at` 一個欄位**之後就精準了。

**突變的爆炸半徑太大，本身就是突變寫錯的訊號。**

### 做法：完全沒有碰 B 的檔案

四個突變都是 pytest plugin（`scratchpad/mut_proc.py`）裡的 monkeypatch，
磁碟上一個位元組都沒動。B 現在 idle 待命，但隨時可能被 A 派回去動那些檔。

⚠️ `routers/inventory.py` 是 `from helpers.procurement import ...` **by value** 綁進來的，
只換 `helpers.procurement` 上那一份沒有用 —— 跟 `conftest.py` 開頭記的是同一個坑。
plugin 裡有 `_patch()` 守門：**接縫一個都沒換到就當場 raise**，
因為「突變沒植入」跟「突變沒被抓到」長得一模一樣。

---

## 第 3 輪 · ⑥全量回歸（A 於 12:17 核准後才跑）

```
1074 passed, 55 skipped, 22 warnings in 1023.43s (0:17:03)
```

**合計 1,129 題、0 失敗。**

| | 題數 | |
|---|---|---|
| 上一輪基準 | 1,111 | 協定 §4 ⑥「不可少於上一輪」 |
| 本輪 `--collect-only` | **1,129** | ＝ 1,111 ＋ 新檔 17 ＋ 8c 那 1 |
| 本輪實跑（1074 ＋ 55） | **1,129** | 收集數 ＝ 實跑數，**沒有題目被靜默跳過** |

⚠️ 「收集數 ＝ 實跑數」要分開對一次。只看「passed 比上一輪多」的話，
**一批題目被 skip 掉也會長得像通過**——skip 不是 fail，它不會讓任何東西變紅。

### 受測對象在這 17 分鐘裡沒有變（跑前 12:17:10 → 跑後 12:34:29）

七個檔的 sha256 **逐字元相符**：`helpers/procurement.py`／`routers/inventory.py`／
`main.py`／`db.py`／`helpers/licensing.py` ＋ **我自己的兩個測試檔**。

視窗 B 另外給了一份**獨立**的跑前雜湊，四個產品碼跟我的逐字元相符 ——
「量的是這一棵」有兩份互不依賴的來源。

⚠️ **那兩個測試檔是 B 提醒我才加進去的，這是本輪最好的一次互相檢查。**
我做這道指紋，是因為上一輪 A 在我跑回歸跑到一半時改了 `main.py`；
於是我防的是「**別人**動**產品碼**」——而這一輪 `git status` 整棵樹只有一個檔是髒的，
就是**我自己的測試檔**。最可能動的東西，正好不在我的清單裡。

> **防護是照著上一次的傷口長出來的，所以它的盲側，就是上一次沒有受傷的那一側。**

而且漏掉的後果特別惡劣：結果會照常印出漂亮的數字，指紋也會回報「全部相符」，
因為變動的那個檔**根本不在清單裡**。
**一道回報「全部相符」的守門，比沒有守門更容易讓人停止懷疑。**

### 量測期間有人碰過樹，查證後不重跑

視窗 B 自首：在量測視窗內於 repo 根目錄建了又刪了 `.fp_probe_tmp`（存在約兩秒）。
**我自己查過才決定不重跑**，不是因為 B 說沒事：
`grep` 過 `backend/tests/*.py` 全部的 `glob`／`listdir`／`iterdir`／`rglob`／`scandir`／`walk(`，
**沒有任何一題枚舉 repo 根**，全部指定子目錄；該檔是根目錄 dotfile 且已不存在。

### 下一輪起改用不靠手列清單的指紋

```sh
fp() { { git ls-files -z -- backend frontend | xargs -0 -r sha256sum
         git ls-files --others --exclude-standard -z -- backend frontend | xargs -0 -r sha256sum
       } | sha256sum; }
```

**本輪基準值：`7dec671a735d3d84`**（`backend/` ＋ `frontend/` 的工作樹內容）。

⚠️ **這個值是給下一輪當基準用的，不是本輪的前後比對依據** ——
`fp()` 是我在本輪跑到一半才想出來的，跑前沒有取過。本輪的前後比對用的是上面那七個手列檔。

為什麼要換掉手列清單（視窗 B 的論點，我同意）：
**只要是人列的，就有沒列到的那一格，而沒列到的那一格永遠不會讓指紋變動。**
那不是「更小心就會好」的機率問題，是**不可觀測性**。

為什麼不直接用 B 原版的 `git rev-parse HEAD` ＋ 全樹 `git status`：
**A 在任何一次 20 分鐘的回歸裡幾乎一定會 commit `docs/`**，而 pytest 不讀那裡。
誤報的代價不是零——**一道會在無害情況下亮紅燈的守門，很快會被當成雜訊，
然後它真的該叫的那一次也沒人理。** 所以範圍照「**pytest 實際會從磁碟讀到什麼**」劃，
不是照「git 知道什麼」劃。

六條路徑我在**丟棄式 repo** 裡逐條實測過（改 `docs/` 不變、commit `docs/` 不變、
改 `backend/` 追蹤檔變、新增未追蹤檔變、改未追蹤檔**內容**再變、刪掉精準回到前值）。
用丟棄式 repo 而不是正在被量的那一棵——那是 B 那個錯誤的正確版本。

---

## 【第 1 輪 · 已結案】紅在哪（①之後填，B 靠這段知道「綠」的定義）

**指令**（就是上面〈跑測試的固定指令〉那一條，只是指定單檔）：

```bash
cd backend
python -m pytest tests/test_licensing_core_2026_09_21.py --basetemp=C:/Users/hichan/AppData/Local/Temp/motrix-pytest-C -q
```

**現況：`8 failed, 19 errors` —— 27 題全紅，沒有任何一題是綠的。**

紅的原因只有一個，正是預期的那個：

```
AssertionError: backend/helpers/licensing.py 還不存在（或 import 失敗）：
ImportError("cannot import name 'licensing' from 'helpers'")。需要的名字見本檔開頭的契約表。
                                        tests/test_licensing_core_2026_09_21.py:69
```

`failed` 跟 `error` 的差別只是那一題撞在 test 本體還是撞在 fixture 裡，原因同一個。
**唯一例外是 `test_08a`** —— 它不碰 `helpers.licensing`，紅在
`/api/license/status` 這條 route 根本沒註冊（見〈給彙整〉第 3 點）。

### 27 題對應 STATE §3 的 11 條驗收條件

| 驗收條件 | 測試 | 題數 |
|---|---|---|
| 1 有效金鑰 → `ok` | `test_01_valid_license_verifies` | 1 |
| **2 竄改 → `bad_signature`** | `test_02_...[customer/tax_id/modules/expires]`、`test_02b_tampered_signature`、`test_02c_signed_by_another_key` | **6** |
| 3 換機器 → `machine_mismatch` | `test_03_other_machine_is_machine_mismatch` | 1 |
| 4 過期 → `expired` ＋ `days_left` 為負 | `test_04_expired_license_reports_expired` | 1 |
| 5 檔案不存在 → `missing`，不丟例外 | `test_05_missing_license_file`、`test_05b_missing_blob` | 2 |
| 6 亂碼／截斷 → `malformed`，不丟例外 | `test_06_...`（6 種壞法）、`test_06b_truncated_valid_blob` | 7 |
| 7 指紋穩定 | `test_07_..._in_process`、`test_07b_..._across_processes` | 2 |
| 8 未登入 401／登入後拿得到欄位 | `test_08a_requires_login`、`test_08_returns_customer_and_days_left` | 2 |
| **8b 沒金鑰 → 200 ＋ `customer:null`** | `test_08b_status_without_license_is_200_and_null_customer` | 1 |
| **9 dev 私鑰簽 → `env == "dev"`** | `test_09_dev_signed_license_reports_env_dev` | 1 |
| **10 `_PUBKEY_PROD` 是空的不丟例外** | `test_10_empty_prod_pubkey_does_not_raise` | 1 |
| **11 status 回傳有 `env` 鍵** | `test_11_status_response_includes_env_key` | 1 |
| （補強）裝了金鑰的那一路 | `test_08c_status_endpoint_reports_installed_license` | 1 |

另外 **9 處 `env` 斷言直接加在既有測試裡**（不另開題，所以總數仍是 27）：
`bad_signature`／`missing`／`malformed` → `env is None`；
`machine_mismatch`／`expired` → **`env` 仍是 `"dev"`**（簽章驗過了，擋下來的是別的檢查）。

### 「綠」的定義（B 要做到的契約）

以 `STATE.md` §5〈本輪最終契約〉為準，測試檔開頭有同一張表：

| 名字 | 形態 | 備註 |
|------|------|------|
| `_PUBKEY_DEV` | `bytes` | 開發公鑰。**驗證時才載入**，不可以在 import 時就解析成 key 物件 |
| `_PUBKEY_PROD` | `bytes` | **本輪＝`b""`**。空的要略過，`load_pem_public_key(b"")` 會丟 `ValueError` |
| `LICENSE_PATH` | `str` | 預設 `backend/license.key`，**每次呼叫才讀** |
| `machine_fingerprint()` | `-> str` | 16 碼小寫 hex，**跨行程要一樣** |
| `sign_license(payload, private_key_pem)` | `-> str` | blob ＝ base64(JSON)，`sig` 放在 JSON 裡面 |
| `verify_license(blob=None)` | `-> LicenseStatus` | `blob` 省略或 `None` → 改讀 `LICENSE_PATH` |

`LicenseStatus` 用 dict 或 dataclass 都可以（測試兩種都讀得到），**七個**欄位：
`valid` / `reason` / `env` / `customer` / `modules` / `expires` / `days_left`。

`backend/routers/licensing.py`：`GET /api/license/status`
（**端點路徑與 `backend/license.key` 檔名不跟著改名**，A 已裁決）。

**檢查順序**：`malformed → missing → bad_signature → machine_mismatch → expired`。
簽章一定要排在 `machine`／`expires` 之前 —— **簽章驗過之前 payload 沒有任何一個欄位可信**。

## 【第 1 輪 · 已結案】反向驗證結果

> 格式：把什麼放回去 → 哪一題紅了 → 其餘幾題仍綠
> **只寫「通過」等於沒驗。**

**基準**：突變前 `27 passed`（2026-09-21 09:59，對 B 當下的 `helpers/licensing.py`）。

### ⚠️ 做法：突變**不改 B 的檔案**，用 `-p` 注入到記憶體

視窗 B 正在同一個工作目錄上做第 2 輪 —— 實測 `helpers/licensing.py` 在我做反向驗證
的這 20 分鐘內就被 B 改過一次（09:36 → **09:59:13**，20,074 → 23,493 bytes）。
**改他的檔再改回來，中間他只要存一次檔，我的「還原」就會蓋掉他的東西** ——
失敗的樣子會是〈共用空間裡不要用會動的名字〉那條：「成功了，只是動到別人的」。

所以三個突變都是 pytest plugin：
- 突變 1 用 monkeypatch（`scratchpad/mut_sig.py`）
- 突變 2／3 讀原始碼、改字串、`compile` 進新的 module 物件再塞回 `sys.modules`
  （`scratchpad/mut_src.py`）—— **磁碟上的檔案一個位元組都沒動**

⚠️ `mut_src.py` 裡有 `hits != 1` 就 `raise` 的守門。`str.replace` 對不上是**靜默無效**的，
而「突變沒被抓到」跟「突變根本沒植入」長得一模一樣 —— 那是最難分辨的假陰性。

---

### 突變 1 · 簽章驗證無條件通過 → **7 題紅、20 題綠** ✅

```
FAILED test_02_tampered_payload_is_bad_signature[customer-冒名的公司]
FAILED test_02_tampered_payload_is_bad_signature[tax_id-00000000]
FAILED test_02_tampered_payload_is_bad_signature[modules-value2]
FAILED test_02_tampered_payload_is_bad_signature[expires-2099-12-31]
FAILED test_02b_tampered_signature_is_bad_signature
FAILED test_02c_license_signed_by_another_key_is_bad_signature
FAILED test_10_empty_prod_pubkey_does_not_raise
7 failed, 20 passed
```

斷言差異是 `- bad_signature` / `+ ok` —— **觀測到的是 `verify_license()` 的回傳值變了**，
不是測試自己算出來的東西。條件 2 的 6 題全紅，確認它們真的在驗簽章。

**`test_10` 是第 7 題，這是預期內的**：它自己內含一格「別人私鑰簽的 → `bad_signature`」。
不是多紅了一題，是它本來就同時在驗那件事。

**為什麼不用「把驗證整段註解掉」**（原開發單的寫法）：`env` 的值是從「**哪一把公鑰驗過**」
推出來的，整段拿掉會連帶弄壞 `env`，於是 `test_03`／`test_04`（機器不符／過期，
兩題都斷言 `env == "dev"`）會**跟著紅**，「只有條件 2 精準變紅」就不成立了 ——
那是突變選錯，不是測試寫錯。
改成「讓 `.verify()` 什麼都不做」之後，`env` 照樣被指派成 `"dev"`，
**`test_03`／`test_04` 實測維持綠**，突變就落在簽章這一件事上。

### 突變 2 · 機器指紋檢查永遠通過 → **只有 `test_03` 紅**（1 紅 26 綠）✅

```
[突變已植入] machine：if (not isinstance(licensed_to, str) or this_machine is None → if False
FAILED test_03_other_machine_is_machine_mismatch
1 failed, 26 passed
```

### 突變 3 · 過期檢查永遠通過 → **只有 `test_04` 紅**（1 紅 26 綠）✅

```
[突變已植入] expiry：if days_left < 0: → if False
FAILED test_04_expired_license_reports_expired
1 failed, 26 passed
```

### 結論

三個突變各自打在不同的檢查上，**每一個都精準點亮對應的那幾題、其餘全綠**。
突變移除後複驗 `27 passed`。條件 2、3、4 確認不是假綠燈。

---

## 全量回歸結果（⑥）

**`1056 passed, 55 skipped` ＝ 1,111 題，0 失敗**（2026-09-21 09:35→09:55，20 分 46 秒）。
＝ 既有 **1,084** ＋ 本輪 **27**，數字對得上，沒有少跑。

### ⚠️ 兩件必須跟著這個數字一起讀的事

**① 第一次跑出來的 `1 failed` 是我自己造成的，不是既存紅燈。**
紅的是 `test_reports_sales_owner_2026_09_14.py::test_achievement_uses_same_attribution_as_performance`，
錯誤 `sqlite3.OperationalError: unable to open database file`。
原因是我在那個回歸跑到 86% 時，用**同一個固定 `--basetemp`** 跑了單檔測試，
而 pytest 每次 session 開始會把 `--basetemp` 整個刪掉重建 —— 等於把它正在用的
`motrix_app0/motrix_erp.db` 刪掉了。乾淨重跑後該題全綠。詳見〈給彙整〉第 9 點。

**② 這個數字是「B 的第 1 輪」的，不是「現在這一刻」的。**
B 已經在做第 2 輪（`helpers/licensing.py` 09:59:13 又長了 3,419 bytes，
已加入 `LICENSE_GATE_ENABLED = False`，middleware 還沒掛）。
我另外跑了一次涵蓋 B 當下狀態的全量回歸並**在前後各取一次 sha256**，見下。

### 第二次（10:01:10 → 10:21:50）：同樣 1,111 全綠，但指紋抓到受測對象跑一半變了

```
1056 passed, 55 skipped in 1225.91s (0:20:25)
```

**sha256 前後比對的結果**——這就是我在〈給彙整〉第 10 點建議的做法，它當場就抓到了：

| 檔案 | 跑之前 | 跑之後 | |
|------|--------|--------|---|
| `helpers/licensing.py` | `2de54e7f…` | `2de54e7f…` | ✅ 沒變 |
| `routers/licensing.py` | `4a01a2fa…` | `4a01a2fa…` | ✅ 沒變 |
| `main.py` | `b6a10437…` | **`00d75c59…`** | ❌ **10:11:25 變了** |
| `tools/issue_license.py` | `bf83d8dc…` | **`939a980d…`** | ❌ 10:01:54 變了 |

B 在 10:11:25 把 `license_gate_middleware` 掛進 `main.py`（第 2 輪的活）。
pytest 在 session 一開始就 `import main`，所以**這次跑的是掛 middleware 之前的 `main.py`**。

**所以這個數字能證明什麼、不能證明什麼，要講清楚：**

- ✅ **第 1 輪的兩個交付物（`helpers/licensing.py`、`routers/licensing.py`）
  在整整 20 分鐘裡一個位元組都沒動** ⇒ **第 1 輪的⑥成立**，1,111 全綠是真的。
  （`helpers/licensing.py` 這一版已經含第 2 輪的 `LICENSE_GATE_ENABLED = False`，
  也就是說「總開關關著時既有功能全綠」這件事已經被驗到了 —— 那正是開發單第 12 題的前半。）
- ❌ **B 的授權守門 middleware 完全沒被這次回歸跑到。** 它 10:11 才進 `main.py`。
  第 2 輪的⑥要重跑，不能拿這個數字充數。

**若沒有前後取指紋，我會把這個 1,111 當成「含 middleware 的全綠」回報出去** ——
而那是假的。這是第 10 點那個建議的實證：它不依賴任何人記得停手，機器自己判得出來。

## 給彙整（A 會收進 STATE.md）

> 發現的產品碼 bug（**不要自己修**）、驗收條件寫不出測試、規格有歧義，寫在這裡。

### ✅ 上一批四項已由 A 於 2026-09-21 全數裁決（STATE §5），這裡只留結論

| # | 我提的 | A 的裁決 | 我做了什麼 |
|---|--------|---------|-----------|
| 1 | `verify_license(blob=None)` 省略時讀 `LICENSE_PATH` | ✅ 採納，照我釘的 | 不用改 |
| 2 | 要求 B「不快取」 | ✅ 准，已寫進本輪契約 | 不用改；⚠️ A 提醒第 3 步掛進 middleware 後會變成**每個 request 讀一次檔**，屆時若加快取要用 mtime 判定，**不可以改成 import 時一次性載入**，否則測試又會變成只有某台機器跑得動 |
| 3 | middleware 對未註冊路徑也回 401 | ✅ A 已複驗屬實，升級成通則寫進 STATE §3 | 不用改 |
| 4 | 基準 `1,034` 應為 `1,084` | ✅ A 算錯（用 `grep -c "def test_"`），差的 50 題是 7 個檔的 `parametrize` 展開 | 已改本檔；A 已改協定與 SPEC |
| 5 | 我自己下的五個判斷 | ✅ 全部同意，一個都不要改 | 不用改 |

**本輪已照 A 的最終契約改完**：改名 3 處（`license` → `licensing`）、補 4 題（23 → **27**）。

---

### 6 · 🟡 `test_10` 裡有一條**刻意會紅**的絆線，A 要知道它的存在

`test_10_empty_prod_pubkey_does_not_raise` 最後一行：

```python
assert _PUBKEY_PROD_AT_IMPORT == b""
```

**正式公鑰一旦產生，這一題就會紅。那是刻意的。**
紅了不是測試壞了，是在擋 STATE §4 第 1 項 —— 私鑰保管、備援副本、外洩處置流程
還沒定案之前，不應該有人默默塞一把公鑰進去就當作可以出貨。
錯誤訊息裡已經寫明「請回 STATE §4 第 1 項定案，再改這一行」。

這正是 A 說的「做成結構可偵測，不靠人記得」。**若 A 覺得這條太硬，跟我說，我拿掉。**

⚠️ 它讀的是 **import 當下拍下來的值**（`_PUBKEY_PROD_AT_IMPORT`），
不是 monkeypatch 之後的值 —— 讀 patch 後的值等於驗自己設的值，就是假綠燈。

### 7 · 🟠 `env` 與簽章驗證是**綁在一起**的，第⑤步反向驗證要用對的突變

`env` 的值是「**哪一把公鑰驗過的**」推出來的，所以它天生依賴簽章驗證。
如果第⑤步的突變是「**把簽章驗證整段註解掉**」，那 `env` 會跟著壞，
`test_03`／`test_04`（機器不符／過期，兩題都斷言 `env == "dev"`）會**跟著紅**，
於是「只有條件 2 精準變紅」就不成立了 —— 但那是突變選錯了，不是測試寫錯。

**我會用的突變是：讓簽章驗證「無條件回 True」**（不是拿掉整段）。
這樣 `env` 仍然被指派成 `"dev"`，`test_03`／`test_04` 維持綠，
只有條件 2 的 6 題變紅 —— 那才是真的在問「條件 2 有沒有觀測到簽章檢查」。

寫在這裡是因為這條會影響 A 怎麼讀第⑤步的回報數字。

### 8 · 🟢 `test_11` 順便驗到了「每次呼叫才讀 `LICENSE_PATH`」

`test_11` 在**同一個行程、不重啟服務**的情況下換掉金鑰檔，第二次請求要看得到新結果。
所以第 3 步若真的加了快取而沒保留 mtime 重讀，**`test_11` 會先紅**，
不用等到第 6 步的到期提醒才發現。這是 A 在裁決 2 裡點出的風險，現在有守門了。

### 9 · 🔴 共用 `--basetemp` 會**刪掉**別人正在用的 DB —— 與 A 查到的 CPU 那件事是兩回事

**A 在 `64fa66f` 裡查的是另一個紅**（`test_semaphore_caps_concurrent_holders`，
CPU 被搶 → `peak` 頂不到 `max_concurrency`），那個診斷是對的。
**但我這邊踩到的是不同的一個紅、不同的機制**，兩件事同一天發生，容易被併成一件：

| | A 查的那件 | 我踩的這件 |
|---|---|---|
| 紅的測試 | `test_semaphore_caps_concurrent_holders` | `test_reports_sales_owner_2026_09_14.py::test_achievement_uses_same_attribution_as_performance` |
| 錯誤 | 斷言 `peak == max_concurrency` 不成立 | `sqlite3.OperationalError: unable to open database file` |
| 機制 | **CPU 競爭**（吵，但沒破壞任何東西） | **檔案被刪掉**（破壞性） |
| 觸發者 | 兩個**全量回歸**同時跑 | **單檔測試**撞上一個正在跑的全量回歸 |

**機制（已實測，不是推論）**：pytest 把 `--basetemp` 指到的目錄**整個刪掉重建**，
時機是**第一次有測試用到 `tmp_path`／`tmp_path_factory`**。

我第一次想驗證時寫了一支不碰 `tmp_path` 的測試，目錄**沒有**被刪 —— 差點據此
認定自己的假設是錯的。換成會用 `tmp_path` 的測試就刪了：

```
之前： bt_demo/motrix_app0/motrix_erp.db
跑一支 test_uses_tmp(tmp_path) --basetemp=./bt_demo
之後： bt_demo/test_uses_tmp0/x     ← motrix_app0/ 整個不見了
```

本專案的 `conftest.py::_app` 幾乎一啟動就 `tmp_path_factory.mktemp("motrix_app")`，
所以實際上等同「一跑就刪」。

**為什麼要寫給 A**：
- **協定 §5 第 5 條擋不住這個。** 它寫的是「**全量回歸**一次只能有一個人跑」，
  而我是跑**單檔測試**撞上別人的全量回歸 —— 跑單檔的人不會覺得那條在講自己。
- 第 5 條的理由寫的是「CPU 也是共用資源」。照這個理由推，會得到
  「機器閒著就可以一起跑」的結論 —— **但刪檔跟 CPU 忙不忙沒有關係**。
- 這一條的失敗模式比 CPU 那條更糟：CPU 競爭讓斷言不成立（吵），
  刪檔是**把另一個 run 的資料庫刪掉**（破壞），而且紅在一支毫不相干的測試上。

**建議 A 把 §5 第 3 條從「一律帶 `--basetemp`」改成「一律帶，而且每個視窗一個專屬路徑」**
（`...-A` / `...-B` / `...-C`，仍是固定名字，不是會動的名字）。
這樣就**不依賴任何人記得先宣告**，也不受「這次只是跑一支測試」的例外心理影響。
第 5 條（宣告 ＋ 一次一個人跑全量回歸）仍然需要，因為它解的是 CPU，那是另一個問題。

### 10 · 🔴 第 2 輪在 C 做完⑤⑥之前就開跑了，於是⑥量的是一個會動的東西

STATE §3 自己寫著「**⛔ C 沒做完⑤⑥之前，第 1、2 步不得標記完成**」——這是對的。
但同一份文件也已經把第 2 輪的單發給 B 了，而 B 立刻就動工了。實測：

| 時間 | `helpers/licensing.py` |
|------|------------------------|
| 09:36:01 | 20,074 bytes（第 1 輪完成） |
| **09:59:13** | **23,493 bytes**（第 2 輪的 `LICENSE_GATE_ENABLED` 已進去） |

**後果是⑥的結果沒有意義可言**：全量回歸要 **20 分鐘**，而受測對象在這 20 分鐘裡會被改。
我第一次跑的那一次，起跑時間（09:35:02）比 `licensing.py` 的最後寫入（09:36:01）還早
**59 秒** —— 我沒辦法證明它載入的是哪一個版本。

**這不是誰做錯了**，是七步的迴圈假設「B 在④之後會停下來等」，而 A 為了不讓 B 閒著
先發了下一輪。兩件事都合理，湊在一起就讓⑥失去意義。

**建議 A 擇一**（我不改協定，那是 A 的檔）：
1. **⑥ 改成「B 宣告本輪停手」之後才跑**，B 在 `B.md` 寫一行「第 N 輪停手，SHA 是 X」，
   C 跑完⑥才解鎖下一輪 —— 最乾淨，代價是 B 要等 20 分鐘。
2. **⑥ 接受「測的是那一刻的樹」，但強制在前後各取一次 sha256**，對不上就重跑。
   我這一次已經這樣做了（`scratchpad/subject_before.txt` / `subject_after.txt`）。
   代價是可能要重跑，好處是 B 不用停。

我傾向 **2**：它不需要任何人記得停手，而且「對不上就重跑」是機器判得出來的條件。
⚠️ 但 2 有個前提：**`--basetemp` 要每個視窗一個**（〈給彙整〉第 9 點），
否則 B 一跑測試就會把 C 的回歸打掉，那比版本漂移更難診斷。

### 11 · 🔴 欄位命名：§3 寫 `lead_time_days`，B 回 `leadTimeDays`（4 題紅，等裁決）

這是本輪唯一的紅，**不是功能沒做**。

**我的判斷是 B 比較對，§3 寫錯了。** 那支端點的既有欄位全是 camelCase
（`safetyStock`／`inStockCount`／`stockLevel`／`suggestedQty`／`estimatedCost`／
`orderedAt`／`receivedAt`），B 跟了既有慣例；§3 看起來是直接把**資料庫欄位名**
抄進了**API 回應規格**。唯一的例外 `part_no` 是既有的歷史遺留。

**但我沒有自己改成 camelCase**，因為 A 的指示是「紅代表理解不一致 ⇒ 回報，
不要改測試去遷就實作」。**請 A 裁決要改 §3 還是改實作**，我這邊是改一個常數的事
（`_LEAD_FIELD`）。

⚠️ 若裁定改 §3，記得**同時改 DB 欄位名以外的地方**：`suppliers.lead_time_days` 與
`parts.lead_time_days` 是資料庫欄位，那兩個**不該**跟著改成 camelCase。

### 12 · 🟠 §3 條件 8c 的前提寫錯了：**備份查詢不是全部 `SELECT *`**

§3 寫「📌 它現在會是綠的（`_daily_backup()` 目前全部 `SELECT *`）」。**實測不是。**
有兩條查詢本來就是列舉欄位、刻意略過憑證素材：

```
使用者 (users):              少了 password_hash / daily_task_pw_hash /
                             unlock_password_hash / totp_secret / totp_recovery_codes
通行金鑰 (webauthn_credentials): 少了 credential_id / public_key
```

**照 §3 字面寫成「選到的 ＝ 宣告的」，這題今天就會紅在一個正確的行為上**
（那些欄位本來就不該進 JSON 備份，`test_business_critical_tables_are_in_json_backup`
的說明也寫著是刻意的）。

我改成驗 **「宣告的 － 選到的 ＝ 刻意略過的那幾個」，一個不多一個不少**，
清單寫成 `_BACKUP_OMITTED_ON_PURPOSE` 常數。這樣才真的達到 §3 想要的效果：
**把「哪些欄位可以不備份」從散在 SQL 裡的沉默決定，變成一個要改就會被看見的清單。**

另外加了一道：清單裡列了、但表上已經不存在的欄位要報錯 ——
**過期的豁免清單會讓守門對同名的新欄位自動放行**。

### 13 · 🟠 條件 4「用固定日期測」我只做到一半

§3 要求「用固定日期測，**不要用 `date.today()` 當預期值**」。我做不到完整版：

- 這台機器**沒有 `freezegun`**
- 要 monkeypatch 實作取「今天」的來源，就得先知道它從哪裡取 —— **那要讀實作，本輪禁止**

折衷：用**兩個差很遠的前置時間**（7 與 30）跑同一條路徑，再加「`eta` 不可以等於今天」。
這擋得住「寫死成常數」與「直接把 eta 填成今天」，**但擋不住「實作與測試用同一個錯的今天」**
（例如兩邊都用 UTC，而正確答案是本地時間 —— 跨日那幾小時會一起錯）。

**要真的關掉這個缺口，二選一**：① 裝 `freezegun`；
② 請 B 把「今天」從一個可 monkeypatch 的接縫取（例如 `procurement.today()`）——
我查過 `compute_eta(lead_time_days, today)` 已經把 `today` 當參數收了，
所以**呼叫端**傳的是什麼才是關鍵，那一段我沒看也不該看。

### 14 · 🟠 `core.autocrlf=true` ＋ 無 `.gitattributes`：`git checkout` 還原出來的不是原本那串位元組

**已驗（視窗 B 讀這棵樹 ＋ 我在丟棄式 repo 重現）**：
`core.autocrlf = true`、`.gitattributes` 不存在、磁碟上的 `.py`／`.html` **全是 LF**
（`.bat`／`.ps1` 是 CRLF ＋ 該有 BOM 的都有，那部分專案處理得對）。

我在丟棄式 repo 用同一組條件實測：`git checkout -- a.py` 之後 `od -c` 讀到 `code
`，
用 `printf 'code
'` 寫回 LF，指紋才精準復原。

**真正的形狀不是「git checkout 會改行尾」，而是**：

> 工作樹長期由「**不經過 git 的工具**」維護（編輯器、腳本），於是它偏離了
> 「git 認為 checkout 應該產出的樣子」。平常沒事，直到有人用 git 去「還原」一個檔 ——
> 那一刻 git 把它拉回 **git 的版本**，而那跟原本磁碟上的不是同一串位元組。

**「還原」這個詞會騙人**：它還原成 *git 認為的原樣*，不是 *你動手之前的原樣*。
兩者平常重合，所以沒有人會去分辨。

**對做⑤的人的實害**：若突變流程是「改檔 → 跑 → `git checkout` 還原」，
還原後那支檔會從 LF 變 CRLF，**`git diff` 看不出來（它會正規化），但 `fp()` 會變**。
到時候會看到「指紋對不上，但 git 說沒改東西」——**那個組合最容易讓人以為指紋壞了**
（我在丟棄式 repo 裡就一度這樣以為）。

**我的做法**：突變一律 monkeypatch（零磁碟寫入）；非寫磁碟不可時用 `printf`／Python
寫回原位元組，**不用 `git checkout` 還原**。第 1、3 輪都是 monkeypatch，沒中過，
⚠️ **但那是運氣不是設計** —— 我當時沒想到這件事。

**根治要 `.gitattributes`（`*.py text eol=lf`），那是 repo 層級、歸 A。**
⚠️ 提醒 A：**改它會重寫整棵樹的位元組**，所以
① 不能在任何人跑回歸的時候做，② 做完當天第一次全量回歸要重跑一次當新基準。

## 收工檢查表

**第 3 輪（2026-09-21）**

- [x] 只動了 `backend/tests/**`（突變全用 pytest plugin 注入記憶體，沒碰 B 的檔）
- [x] **我沒有讀實作**——`helpers/procurement.py`／`routers/inventory.py` 一次都沒開過
- [x] ⑤反向驗證：五個突變，每一個都只點亮它指名的那一題
- [x] ⑥全量回歸：**1,129 題 0 失敗**，收集數 ＝ 實跑數，且 ≥ 上一輪 1,111
- [x] 跑前跑後七個檔的 sha256 逐字元相符（含 B 提醒我補的兩個測試檔）
- [x] 跑之前通知了 `hichan-70`；basetemp 用 `-C-full`，臨時跑用 `-C-adhoc`
- [x] `git add`／`git commit` 都帶 pathspec，只到檔案層級
- [x] 發現的問題都寫進〈給彙整〉（第 11～14 點），沒有自己動產品碼
