# 稽核：C 的 M01-PLAN §3-4——case.summary／case.locations、SYSTEM 哨兵（wip/c-m01-s3-2 d93a792a；合回前）（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d：改到 L1 產品碼與權限，完整稽核。稽核者 D 沒有寫過任何受稽核的程式碼。
> 對象：`c-m05b-2..d93a792a`（3 commits；取代 c-m01-s3 6d091294）。內容：
> - M01 提供 `case.summary`（IP-96 暫編號）與 `case.locations`（IP-97 暫編號）。
> - `helpers.case_access.SYSTEM` 哨兵：`user=None` 一律 TypeError。
> - L1 地圖改走 `case.locations`，不再讀 quotations。
> - IP-12 `_CaseAccess.summary` 改為轉呼叫並登記淘汰；`test_deprecations` 支援 `Class.member`；CORE 1.37。
>
> 稽核樹 `D:\MOTRIX-PLATFORM-D`（detached），`-n 4`；地圖題用 `-n 2`。

## 0. 結論

- **必修 1、建議 1**。
- 可見性、None 拒絕、M01 不在時的說明、快取指紋都有題守住，突變 5/5 紅。
- 必修的原因：守「SYSTEM 只准 L1」的掃描器，只認得兩種寫法。

## 1. 實測

| 項目 | 結果 |
|---|---|
| 基準：tests/platform＋netplan 題 | 1137 過、1 紅（`test_every_module_page_is_declared_in_sidebar`，已知，等 C4） |
| 基準：引用地圖或案件摘要的 27 檔（`-n 2`） | 274 過 |
| 邏輯搬移 | `case_delivery_address` 與原本的 `_case_address` 逐行相同；地圖可見性原本是本地 `_case_rows_visible_to`，現在由 M01 判，判準同樣是 row_access `case`／read；IP-12 summary 用 SYSTEM，與原本不驗權限一致 |

## 2. 突變

| # | 突變 | 結果 |
|---|---|---|
| C1 | `user=None` 當成 SYSTEM | 紅（2） |
| C2 | 不逐筆過濾可見性 | 紅（4） |
| C3 | 地圖取使用者的點時改用 SYSTEM（外洩別的業務的工地地址） | 紅（mp6 的 2 題） |
| C4 | M01 不在時不寫 `module_absent` 說明 | 紅 |
| C5 | 指紋不含可見性欄位（改派不失效） | 紅（2） |

## 3. 發現

### 必修

**CS-M1　`system_users` 掃描器只認得 `from helpers.case_access import SYSTEM` 和 `case_access.SYSTEM` 兩種寫法**
- D 把掃描函式原樣抽出來，對合成的 L2 原始碼逐一測試：

| 寫法 | 結果 |
|---|---|
| `from helpers.case_access import SYSTEM`（對照） | 抓到 |
| `import helpers.case_access as ca; ca.SYSTEM` | **漏** |
| `from helpers import case_access as ca; ca.SYSTEM` | **漏** |
| `import helpers.case_access; helpers.case_access.SYSTEM` | **漏** |
| `from helpers.case_access import *` | **漏** |
| `getattr(case_access, "SYSTEM")` | **漏** |
| `from helpers.case_access import _SystemCaller` | **漏** |

- `from helpers import X as Y` 在 modules／routers 已經有 30 處，是 repo 的慣用寫法，不算刻意繞過。
- 另外，`helpers/__init__.py` 已經從 `.case_access` 轉出名稱；日後如果有人把 SYSTEM 加進去，`from helpers import SYSTEM` 也會漏。
- SYSTEM 等於「不做逐案權限過濾」。主持裁示它只准 L1 使用，而這道掃描是唯一的控制。
- 建議修法（擇一或併用）：
  - 改成「凡是從 helpers.case_access 取得名稱的檔都要檢查」：任何形式的 import 或 alias，再看檔內出現的任何 `SYSTEM` 或 `_SystemCaller`，`import *` 也算一律記一筆。
  - 或者加執行期的防線：`_caller_is_system` 收到 SYSTEM 時檢查呼叫端的模組是否在 L1 名單裡。
- 修完後，上表 6 種寫法都要納入反向控制。

### 建議

**CS-S1　IP-97 沒有寫明 `address` 的資料性質**
- 交貨地址在客戶是自然人時屬於個資。這次沒有新的曝露面：可見性與搬移前相同；SYSTEM 路徑只用來預熱地理編碼，這是原本就有的行為，快取屬 F4。
- 但 IP-97 是新的對外契約，建議在「回傳」欄註明：address 可能是自然人個資，取用方不得寫進 log 或信件，也不得外傳；只能顯示給 row_access 判定可見的人。
- MODULE-GUIDE §11 的告知規則管的是蒐集個資的表單，不適用這個唯讀串接點；如果主持指的是另一種分級，請指明。

## 4. 回覆欄（被稽核者填；D 確認後才關）

| # | 回覆 | commit | D 確認 |
|---|---|---|---|
| CS-M1 | **修正**：`system_users` 改成「從 case_access 取得任何名稱（所有 import 寫法，含 `import *`、`from helpers import case_access as x`、`import helpers.case_access as x`、`from helpers import SYSTEM`）且提到哨兵名字（名稱、屬性、字串常數、`_SystemCaller`）的檔都算」；你列的 6 種全部納入反向控制，另加兩個不該抓的反向。另加**執行期第二道**：把 SYSTEM 傳進提供者的那一方（frame 2）在 `backend/modules/` ⇒ PermissionError；M01 自己（IP-12 轉呼叫替 M10 取摘要）照常。突變 2 項皆紅（拿掉執行期檢查、掃描器退回舊判準） | dbd07633 |  ⏸ 16:30 D：**靜態那一半通過**——突變 R2「不認 from helpers import case_access」、R3「不看字串常數」⇒ 反向控制紅。**執行期那一半未關**：新題 `test_runtime_refuses_system_from_an_l2_module` 不帶建庫夾具（`client`），單獨跑 ⇒ `sqlite3.OperationalError: no such table: quotations`（D 實測 `-n 0` 單跑紅；`-n 4` 基準也紅；整檔依序跑才綠＝靠前面的題建庫）。請加 `client` 夾具後 D 重跑 R1（執行期不擋）。另：判斷用子字串 `/backend/modules/`——部署路徑固定是 `<ProdRoot>ackend`（apply_update.ps1:58），目前成立；較穩的寫法是由本檔位置推 modules 目錄，列觀察 CS-O1 |
| CS-S1 | **修正**（主持更正裁示）：IP-97 回傳欄註明 address 屬個資、只給有該案讀取權限的人、取用方不可寫進 log 或匯出；RUN-PLAN §5 D1 ① 的「照 MODULE-GUIDE §11」劃掉加〔更正〕 | dbd07633 |  ✅ 16:30 D：IP-97 回傳欄已註明 address 屬個資與取用限制 ⇒ **關閉（dbd07633）** |
