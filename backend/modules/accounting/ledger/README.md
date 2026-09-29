# ledger/：M06 總帳（W4，P1）

設計稿：proposal-general-ledger（分冊 01–10）。本資料夾＝**快取摘要**，常重讀的規則寫在這裡，改設計時同步更新。

## 檔案職責（每檔 <1500 行，各自獨立）

| 檔 | 職責 | 不做什麼 |
|---|---|---|
| `roles.py` | 科目屬性 `gl_account_meta`（類別、正常餘額、可過帳、報表列）、科目角色 `gl_account_roles`；`ensure_meta`、`resolve_role` | 不改 `account_items`（法定列被觸發器鎖死） |
| `periods.py` | 會計年度／期間、結帳、重開、鎖定、稽核軌跡、`lock_error`、期末檢查 | 不 commit；不決定誰有權限（API 層決定） |
| `opening.py` | 期初餘額匯入（批次＋期初傳票草稿）、撤銷 | 不自動過帳 |
| `reports.py` | 試算表、總分類帳、明細分類帳、序時帳簿 | 不寫資料（除 `ensure_meta` 補種子） |
| `api/ledger_periods.py`、`api/ledger_reports.py` | HTTP 端點、權限、中文錯誤訊息 | 不含業務規則 |
| `migrations/0001_ledger_base.py` | gl_* 表、新欄位、8 個鎖定觸發器 | 不 import 會演進的程式碼 |

## 必記規則

1. **帳簿範圍**：`vouchers_all.status='已過帳' AND voided_at=''`；`kind='closing'` 預設不計。
2. **期初**：帳簿從「最近一張**已過帳**期初傳票的日期」起算（資產負債科目）；損益科目 max(會計年度起日, 期初日)；更早的傳票視為 legacy、不入餘額。沒有期初＝從頭累計（舊部署行為不變）。
3. **試算表不可跨會計年度**；上年度損益未結轉時補「以前年度損益（尚未結轉）」列使其仍平衡，**不平衡的資料照樣回 `balanced=False`**。
4. **鎖定三層**：API 訊息（`voucher.post_voucher`、`void`）、（P2 起）引擎、DB 觸發器（`gl_period_*`、`gl_posted_*`）。沒有期間資料＝全部開放。
5. **已過帳不可改**（日期、分錄）；閉期不可作廢已過帳傳票——開沖轉傳票或先重開期間。
6. **角色解析**：scope 精確命中 → 預設；日期預設今天；找不到回 None，呼叫端要說明缺哪個角色，**不猜科目**。
7. 權限：讀＝cashier／finance；結帳／重開／期初／科目設定＝finance；鎖定／解鎖＝superadmin。未新增權限鍵。
8. 金額一律整數新臺幣（`parse_amount`／`round_half_up`）。
