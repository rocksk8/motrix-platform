# 授權閘門：緊急放行通行證與 402 說明頁（操作手冊）

> T80（使用者 2026-11-11 裁示）。程式：`backend/helpers/licensing.py`（「緊急放行通行證」一節）、`backend/helpers/license_alerts.py`、`backend/main.py::license_gate_middleware`、`frontend/pages/license-required.html`、`frontend/static/notif.js`。
> 前提：`LICENSE_GATE_ENABLED=True`（預設開）。**正式機尚未切換**：正式機沒有 `license.key`、`_PUBKEY_PROD` 仍是空的，切換前的順序見 `helpers/licensing.py` 的 `LICENSE_GATE_ENABLED` 註解。

## 1. 什麼時候用

授權金鑰（`backend/license.key`）本身沒問題，但**這一刻**驗不過，而且等重新簽發會停工：

| 狀態代碼 | 常見原因 | 通行證能救嗎 |
|---|---|---|
| `machine_mismatch` | 換主機板／網卡，機器指紋變了 | 能 |
| `expired` | 年費到期，續約文件還沒辦完 | 能 |
| `missing`／`malformed`／`bad_signature` | 沒裝金鑰、檔案壞了、被改過 | **不能**（這些不是「橋接」的情境，放行等於沒有守門） |

通行證是**橋接**，不是續約：最多 14 天（驗證端強制，簽發端簽再長也只認 14 天）。到期前要把正式的授權金鑰重新簽發裝好。

## 2. 為什麼這不是後門

- 簽發要用**授權私鑰**（跟簽 `license.key` 同一把），沒有私鑰簽不出來；驗章走同一條路徑。
- `purpose` 必須是 `emergency_pass`；**授權金鑰不能當通行證用，通行證也不能當授權金鑰用**。
- 綁**客戶統編**，且必須等於「驗章通過的那把授權金鑰」的統編（別的客戶的通行證沒用）。
- 只涵蓋 `machine_mismatch`、`expired`。
- 期間上限 14 天、檔案上限 8 KB、必須是檔案（不是目錄）；日期不合理、已過期、尚未生效都不放行。
- 放行時**不安靜**：每天寫一次 ERROR log＋稽核（`license.emergency_pass`）、每頁頂端橫幅、`/api/license/status` 的 `emergency` 欄位。

## 3. 簽發（供應商端，持有私鑰的人）

```
python backend/tools/issue_license.py emergency --tax-id <客戶統編> --customer "<客戶名稱>" ^
    --days 7 --reason "換主機板，新授權金鑰簽發中" --key <私鑰路徑> --out license_emergency.key
```

`--reason` 必填（寫進稽核）；`--days` 1～14（預設 7）。工具簽完會自我複驗，並印出有效期與放置位置。

## 4. 安裝（客戶端）

把 `license_emergency.key` 放到**與 `license.key` 同一個資料夾**（安裝目錄的 `backend\`）。**不必重啟、不必改程式**；下一個請求就生效。

- 位置由 `core/paths.py::LICENSE_PATH` 決定（`emergency_path()` 跟著走）。
- 檔案在 `.gitignore`（per-installation，同 `license.key`）；`git archive` 打包不會帶、`apply_update` 只加不刪，所以更新不會洗掉它。

## 5. 確認有沒有生效

- 任何頁面頂端出現橫幅「緊急放行通行證生效中（至 YYYY-MM-DD）」。
- `GET /api/license/status`：`emergency.active=true`、`emergency.until`；沒生效時 `emergency.why` 講原因（`token_expired`、`tax_id_mismatch`、`license_not_covered`、`token_span_too_long`…）。
- 系統稽核有 `license.emergency_pass`（每個通行證每天一筆）；伺服器 log 有 ERROR 一行。
- 被擋的人會看到 `pages/license-required.html`：狀態代碼、機器代碼（給簽發方）、授權客戶與到期日；若偵測到通行證但不能用，會講原因。

## 6. 結束

裝好新的正式授權金鑰後**刪掉 `license_emergency.key`**（不刪也無妨：授權有效時通行證不會被用到，`why=not_needed`；但留著會讓人誤以為還在橋接）。

## 7. 其他兩個相關行為

- **開發金鑰（env=dev）：只警告、不拒絕啟動。** 驗章通過但簽發方是開發公鑰 ⇒ log WARNING＋稽核 `license.dev_key`（每天一次）＋每頁橫幅「開發用授權金鑰」。目前 `_PUBKEY_PROD` 是空的，所有實際簽出的金鑰都是 env=dev，拒絕＝全部起不來。要不要升級成擋住，等有「這台是正式機」的可靠判斷之後另外決定。
- **啟動檢查**：`main.py` 啟動時多一步 `license_check`（`license_alerts.startup_check()`）：授權不通過／靠通行證／開發金鑰都留 log＋稽核。**不丟例外、不擋啟動**（擋的是業務 API 的 402）。閘門關著時什麼都不做。

## 8. 風險（交給使用者知道的）

- 機器指紋靠主機板 UUID＋網卡 MAC；硬體不穩定、換件、虛擬機搬家都會讓授權失效。通行證是這條路上唯一的行程外出口，**簽發私鑰的保管就是整個機制的安全邊界**。
- 通行證不撤銷（離線驗證沒有撤銷清單）；最壞情況就是它的 14 天上限。
- 授權閘門一開，沒有 `license.key` 的機器業務 API 全部 402；通行證**不能**救「沒金鑰」。正式機切換前必須先裝好有效的金鑰。
