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
- 綁**被救的那把授權金鑰**：統編與 `machine` 值都必須等於「驗章通過的那把授權金鑰」的值（別的客戶、同客戶另一個安裝的通行證沒用；兩個檔一起複製到別台仍然擋不住，由 14 天上限兜底）。
- **簽發環境（開發／正式）必須與那把授權金鑰相同**：開發金鑰簽的通行證救不了正式金鑰的授權。
- 只涵蓋 `machine_mismatch`、`expired`。
- 期間上限 14 天、檔案上限 8 KB、必須是檔案（不是目錄）；日期不合理、已過期、尚未生效都不放行。
- 放行時**不安靜**：每天寫一次 ERROR log＋稽核（`license.emergency_pass`）、每頁頂端橫幅、`/api/license/status` 的 `emergency` 欄位。

## 3. 簽發（供應商端，持有私鑰的人）

```
python backend/tools/issue_license.py emergency --license <被救的 license.key> --customer "<客戶名稱>" ^
    --days 7 --reason "換主機板，新授權金鑰簽發中" --key <私鑰路徑> --out license_emergency.key
```

`--reason` 必填（寫進稽核）；`--days` 1～14（預設 7）。工具簽完會自我複驗，並印出有效期與放置位置。

## 4. 安裝（客戶端）

把 `license_emergency.key` 放到**與 `license.key` 同一個資料夾**（安裝目錄的 `backend\`）。不必改程式；**業務 API 下一個請求就恢復**。

⚠️ **但模組是否載入只在開機時決定一次**（`core/loader.py`）。最常見的情境——換主機板後重開機——服務是在「授權失效、還沒有通行證」的狀態下啟動的，被擋的模組當時就沒有載入（沒有路由、沒有頁面）。這時放好通行證只會讓 402 消失，**那些模組要再重啟一次服務才會出現**。`GET /api/license/status` 的 `modules_unlicensed` 列出還在等重啟的模組，說明頁也會講。**最順的做法：先放通行證、再重啟服務。**

- 位置由 `core/paths.py::LICENSE_PATH` 決定（`emergency_path()` 跟著走）。
- 檔案在 `.gitignore`（per-installation，同 `license.key`）；`git archive` 打包不會帶、`apply_update` 只加不刪，所以更新不會洗掉它。

## 5. 確認有沒有生效

- 任何頁面頂端出現橫幅「緊急放行通行證生效中（至 YYYY-MM-DD）」。
- `GET /api/license/status`：`emergency.active=true`、`emergency.until`；沒生效時 `emergency.why` 講原因（`token_expired`、`tax_id_mismatch`、`license_not_covered`、`token_span_too_long`…）。
- `modules_unlicensed` 是空的（不是空的 ⇒ 還要重啟服務，見 §4）。
- 系統稽核有 `license.emergency_pass`（每個通行證每天一筆）；伺服器 log 有 ERROR 一行。
- 被擋的人會看到 `pages/license-required.html`：狀態代碼、機器代碼（給簽發方）、授權客戶與到期日；若偵測到通行證但不能用，會講原因。

## 6. 結束

裝好新的正式授權金鑰後**刪掉 `license_emergency.key`**（不刪也無妨：授權有效時通行證不會被用到，`why=not_needed`；但留著會讓人誤以為還在橋接）。

## 7. 其他兩個相關行為

- **開發金鑰（env=dev）：只警告、不拒絕啟動。** 驗章通過但簽發方是開發公鑰 ⇒ log WARNING＋稽核 `license.dev_key`（每天一次）＋每頁橫幅「開發用授權金鑰」。目前 `_PUBKEY_PROD` 是空的，所有實際簽出的金鑰都是 env=dev，拒絕＝全部起不來。要不要升級成擋住，等有「這台是正式機」的可靠判斷之後另外決定。
- **啟動檢查**：`main.py` 啟動時多一步 `license_check`（`license_alerts.startup_check()`）：授權不通過／靠通行證／開發金鑰都留 log＋稽核。**不丟例外、不擋啟動**（擋的是業務 API 的 402）。閘門關著時什麼都不做。

- 橫幅標頭 `X-Motrix-License` 只給**已登入**的請求（公開／未登入的呼叫者看不到這台靠通行證或開發金鑰在跑）；已登入的回應一定帶（沒有提示時值是 `none`）。
- 告警的稽核寫入在背景執行緒，且一律寫正式庫（不看目前請求是不是示範帳號）。
- **上正式金鑰時要另外開的票**：`_PUBKEY_PROD` 填入之後，部署包不要再帶 `_PUBKEY_DEV`（build／git archive 那一步）。靠「這台是不是正式機」的判斷擋 env=dev 不可靠，不帶開發公鑰才是唯一可靠的訊號。

## 8. 風險（交給使用者知道的）

- 機器指紋靠主機板 UUID＋網卡 MAC；硬體不穩定、換件、虛擬機搬家都會讓授權失效。通行證是這條路上唯一的行程外出口，**簽發私鑰的保管就是整個機制的安全邊界**。
- 通行證不撤銷（離線驗證沒有撤銷清單）；最壞情況就是它的 14 天上限。
- 授權閘門一開，沒有 `license.key` 的機器業務 API 全部 402；通行證**不能**救「沒金鑰」。正式機切換前必須先裝好有效的金鑰。
- 通行證綁「被救的那把授權金鑰」的統編＋machine 值與簽發環境，限制了「拿客戶的通行證去救別的安裝」，但**擋不住把授權金鑰與通行證兩個檔一起複製到別台**（那台指紋也對不上，所以實際擋它的只有 14 天上限）。

## 9. 開發機：閘門預設開之後怎麼跑

- **測試**不受影響：`backend/conftest.py` 提供自簽測試金鑰＋固定指紋（驗章走真路徑）；子行程腳本用 `tests/_license_boot.py`。測試不呼叫硬體查詢。
- **在開發機上跑整套伺服器／打開畫面**：沒有 `backend/license.key` 時業務 API 一律 402（說明頁會講原因）。要有授權：在**允許硬體查詢的機器**上用開發私鑰簽一把（`python backend/tools/issue_license.py issue --tax-id 00000000 --customer dev --days 365 --modules "*" --out backend/license.key`；機器代碼預設取本機指紋）；金鑰檔在 `.gitignore`。這會讀主機板 UUID／網卡（PowerShell CIM 查詢）。
- ⚠️ **這台開發機（有 BSOD 與硬體／儲存 WMI 查詢導致長時間無回應的紀錄）不要在閘門開著、沒有 stub 的情況下啟動伺服器或打 `/api/license/status`**——指紋計算會跑 CIM 查詢。狀態端點在指紋讀不到時 5 分鐘內不重試（`routers/licensing.py::_machine_or_none`），但第一次仍會查。需要在這台跑整套畫面的人，請在別台機器跑，或先由管理者決定怎麼處理。
- 沒有執行期的關閘開關（刻意的：只有程式裡的常數）。
