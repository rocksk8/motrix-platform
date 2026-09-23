# `DATA-EM7-39` · `EM7` 的 39 筆原始清單（A-2 產，供 D 逐條 diff）

> 產生條件：`for`／`while` ⊃ `try` ⊃ `except`，而 handler body **只有 `continue`**，
> 且 handler 內**沒有** `raise`／`+=`／任何 log-ish 呼叫。
> 掃描範圍：`backend/**/*.py`，排除 `rollback_snapshots/`／`tests/`／`deploy_packages/`。
> ⚠️ **去重**：同一個 `(檔, 行)` 只算一次（巢狀迴圈會重複命中同一個 `try`）。

> ## 🔑 D 的分類是 **42**（16 合法／20 真缺陷／5 migration／1 看不出來），
> ## 而這一份是 **39**。**差 3 是單位差異，不是誰數錯** —— 並排才看得到。
> ⚠️ 已知我這份會排除的三類：`pass`（46 處）／含 `Assign` 給預設值（37 處）／
> handler 內有任何 log-ish 呼叫的。**若 D 那 42 含其中任一類，差額就在那裡。**

| # | 檔 | 行 | 例外型別 |
|---|---|---|---|
| 1 | `archive.py` | 1182 | `ValueError` |
| 2 | `archive.py` | 1250 | `ValueError` |
| 3 | `archive.py` | 1264 | `(ValueError, IndexError)` |
| 4 | `archive.py` | 1279 | `ValueError` |
| 5 | `db.py` | 996 | `Exception` |
| 6 | `db.py` | 1651 | `Exception` |
| 7 | `db.py` | 1730 | `Exception` |
| 8 | `db.py` | 1841 | `Exception` |
| 9 | `db.py` | 3400 | `Exception` |
| 10 | `helpers/licensing.py` | 227 | `Exception` |
| 11 | `helpers/licensing.py` | 370 | `Exception` |
| 12 | `helpers/licensing.py` | 598 | `OSError` |
| 13 | `helpers/licensing.py` | 561 | `OSError` |
| 14 | `helpers/quotations.py` | 359 | `Exception` |
| 15 | `helpers/quotations.py` | 397 | `Exception` |
| 16 | `helpers/startup.py` | 193 | `Exception` |
| 17 | `helpers/startup.py` | 252 | `Exception` |
| 18 | `network_plan_topology.py` | 538 | `(TypeError, ValueError)` |
| 19 | `pdf_gen.py` | 2443 | `Exception` |
| 20 | `routers/daily_tasks.py` | 1642 | `OSError` |
| 21 | `routers/daily_tasks.py` | 1651 | `OSError` |
| 22 | `routers/daily_tasks.py` | 1185 | `Exception` |
| 23 | `routers/daily_tasks.py` | 1237 | `Exception` |
| 24 | `routers/daily_tasks.py` | 1594 | `Exception` |
| 25 | `routers/daily_tasks.py` | 1852 | `Exception` |
| 26 | `routers/daily_tasks.py` | 1859 | `Exception` |
| 27 | `routers/dashboard.py` | 963 | `Exception` |
| 28 | `routers/dashboard.py` | 454 | `Exception` |
| 29 | `routers/dashboard.py` | 880 | `(ValueError, TypeError)` |
| 30 | `routers/dashboard.py` | 1135 | `(TypeError, ValueError)` |
| 31 | `routers/dev_crm.py` | 1050 | `(ValueError, TypeError)` |
| 32 | `routers/inventory.py` | 203 | `(ValueError, TypeError)` |
| 33 | `routers/map_points.py` | 151 | `(TypeError, ValueError)` |
| 34 | `routers/quotations.py` | 955 | `Exception` |
| 35 | `routers/quotations.py` | 1746 | `Exception` |
| 36 | `routers/reports.py` | 2751 | `(UnicodeDecodeError, LookupError)` |
| 37 | `routers/reports.py` | 2771 | `ValueError` |
| 38 | `routers/system.py` | 2131 | `Exception` |
| 39 | `tools/list_payment_anomalies.py` | 52 | `Exception` |

**合計 = 39**
