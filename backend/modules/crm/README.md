# M02 業務開發（crm）

報價前期的案件追蹤與開發記錄：案件、開發記錄（含附件與核准）、刪除／重新連結的申請與核准、轉建報價單、停滯與暫緩到期提醒。

## 端點

前綴 `/api/dev-cases`、`/api/dev-logs`、`/api/dev-crm`，權限 key `dev_crm`。詳細清單見 `api.py`。

## 資料（依 MODULE-GUIDE §3 分類）

| 名稱 | 類別 | 說明 |
|---|---|---|
| `dev_cases` | T1 | 業務開發案件 |
| `dev_logs` | T1 | 開發記錄（附件存在 L1 uploads） |

## 串接點

| 方向 | 串接點 | 說明 |
|---|---|---|
| 提供 | IP-11 `crm.quote_deleted` | M01 刪報價單時，在同一筆交易內解除轉建連結、退回「洽談中」；回傳被解除的案件，稽核由 M01 寫 |

## 本模組不在時

- `/api/dev-cases`、`/api/dev-logs`、`/api/dev-crm` 回 404；側欄入口隱藏（`module.json` 的 `pages`）。
- 報價單照常可以刪除，回應 `notice` 明說「轉建連結沒有自動解除」（IP-11）；伺服器記 WARNING。
- 每日 08:00 的停滯／暫緩到期提醒不跑。
- 其他模組仍會**讀** `dev_cases`／`dev_logs`（儀表板、全站搜尋、未讀標記、報價單動態、行事曆標題、封存匯出）：表由凍結 migration 建立，本模組不在時表仍在，讀取不會壞；讀取相依待另開題切斷（DEPENDENCY-MAP §3 #2／#5／#6）。

## 尚未處理

- 規格條件仍在 `docs/windows/STATE.md`，尚未拆成本模組的 `SPEC.md`。
