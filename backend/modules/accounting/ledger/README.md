# ledger/：M06 總帳（W4，P1）

設計稿：proposal-general-ledger（分冊 01–10）。本資料夾＝**快取摘要**，常重讀的規則寫在這裡，改設計時同步更新。

## 檔案職責（每檔 <1500 行，各自獨立）

| 檔 | 職責 | 不做什麼 |
|---|---|---|
| `roles.py` | 科目屬性 `gl_account_meta`（類別、正常餘額、可過帳、報表列）、科目角色 `gl_account_roles`；`ensure_meta`、`resolve_role` | 不改 `account_items`（法定列被觸發器鎖死） |
| `periods.py` | 會計年度／期間、結帳、重開、鎖定、稽核軌跡、`lock_error`、期末檢查 | 不 commit；不決定誰有權限（API 層決定） |
| `opening.py` | 期初餘額匯入（批次＋期初傳票草稿）、撤銷 | 不自動過帳 |
| `reports.py` | 試算表、總分類帳、明細分類帳、序時帳簿 | 不寫資料（除 `ensure_meta` 補種子） |
| `contract.py` | `gl.events` 契約 v1：事件驗證、內容雜湊、向多提供者收集並明說缺席 | 不產生傳票（C1 才做引擎草稿） |
| `closing.py`、`export.py` | 年度結轉（兩張 kind=closing 傳票）、決算（四表對帳＋凍結快照）、年度重開；四大表 Excel | 不自動過帳結轉傳票 |
| `statements.py`、`equity.py`、`cashflow.py` | 資產負債表＋綜合損益表／權益變動表／現金流量表（間接法） | 不寫資料 |
| `fs_lines.py` | 報表列定義 `gl_fs_lines`（BS／IS 種子）、現金流量分類推導、設定完整性查詢 | 不算報表數字（B2～B4） |
| `api/ledger_periods.py`、`api/ledger_reports.py`、`api/ledger_engine.py`、`api/ledger_settings.py` | HTTP 端點、權限、中文錯誤訊息 | 不含業務規則 |
| `migrations/0001_ledger_base.py`、`0002_fs_lines_cashflow.py` | gl_* 表、新欄位、8 個鎖定觸發器；gl_fs_lines＋cashflow_class | 不 import 會演進的程式碼 |

## 必記規則

1. **帳簿範圍**：`vouchers_all.status='已過帳' AND voided_at=''`；`kind='closing'` 預設不計。
2. **期初**：帳簿從「最近一張**已過帳**期初傳票的日期」起算（資產負債科目）；損益科目 max(會計年度起日, 期初日)；更早的傳票視為 legacy、不入餘額。沒有期初＝從頭累計（舊部署行為不變）。
3. **試算表不可跨會計年度**；上年度損益未結轉時補「以前年度損益（尚未結轉）」列使其仍平衡，**不平衡的資料照樣回 `balanced=False`**。
4. **鎖定三層**：API 訊息（`voucher.post_voucher`、`void`）、（P2 起）引擎、DB 觸發器（`gl_period_*`、`gl_posted_*`）。沒有期間資料＝全部開放。
5. **已過帳不可改**（日期、分錄）；閉期不可作廢已過帳傳票——開沖轉傳票或先重開期間。
6. **角色解析**：scope 精確命中 → 預設；日期預設今天；找不到回 None，呼叫端要說明缺哪個角色，**不猜科目**。
7. 權限：讀＝cashier／finance；結帳／重開／期初／科目設定＝finance；鎖定／解鎖＝superadmin。未新增權限鍵。
8. 金額一律整數新臺幣（`parse_amount`／`round_half_up`）。
9. **新增單元／頁／端點前先過三個全域釘子**：`docs/platform/modules.json`（M06 的 units／tables／api_prefixes）、守門函式命名（端點主體要直接呼叫 `_require…`）、頁面母體 `PAGE_POPULATION`（`tests/test_alpine_double_init_2026_09_23.py`）；產生檔（UNIT-INDEX、dep_graph、test_map）**不在分支裡重產**（列車產）。
10. **設定完整性**：`fs_lines.unclassified_cashflow`／`unknown_fs_lines`／`inactive_lines_in_use` ＋ `roles.accounts_without_fs_line` 必須全空（`/api/ledger/setup-check`）；`ensure_meta` 只補空、不覆蓋會計師改過的值。
11. **報表守門的反向科目要全類型覆蓋**：累計折舊／備抵（資產類貸方）、銷貨折讓（收入類借方）、庫藏股票（權益類借方，權益區段一律貸方為正）；B3 測試曾逼出資產負債表把庫藏股票加進權益的缺陷。
12. **結轉傳票的日期＝年度末日**，所以第 12 期必須還開著才過得了帳；決算才關第 12 期。損益表／現金流量表／權益變動表的『其他變動』一律排除 `kind='closing'`，資產負債表含結轉。
