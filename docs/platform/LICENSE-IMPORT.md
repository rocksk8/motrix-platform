# 授權匯入：授權頁、匯入端點、到期提醒（T83）

> 來源：系統選單提案 v2「授權匯入」批次（`docs/platform/plans/SYSTEM-MENU-UX-PROPOSAL.md` §批次「授權匯入」）。
> 程式：`backend/helpers/license_manager.py`（邏輯）、`backend/routers/licensing.py`（`/api/license/overview`、`/api/license/import`）、
> `backend/helpers/licensing.py`（`expiry_reminder`／`expiry_banner`、豁免清單）、`backend/helpers/system_checks.py::_check_license_expiry`、
> `frontend/pages/license-settings.html`、`frontend/pages/license-required.html`（連結）、`frontend/static/notif.js`（橫幅）。
> 測試：`backend/tests/test_license_import_2026_11_13.py`、`backend/tests/test_e2e_license_import_2026_11_13.py`。
> **T80 的安全性一律沒有動**：驗章流程、公鑰、`LICENSE_GATE_ENABLED`、緊急放行通行證判定、402 行為、`/api/license/status` 都與 T80 相同。

## 1. 買家能做什麼（白話）

最高管理者在 **系統 → 授權**（系統中心「公司與參數設定」也有一張卡）看到：客戶名稱、到期日與剩餘天數、授權種類（年費／永久）、可用功能、
綁定的電腦（「已綁定這台電腦」）、提醒、最近的匯入紀錄、備份份數。拿到供應商的新授權檔後：**選擇授權檔 → 系統檢查 → 看到預覽 → 按「確認更換」**。
失敗時用白話說原因（「這份授權是給另一台電腦的」「已經過期」「沒有通過驗證」…），系統什麼都沒有動。

授權失效（沒有授權／已到期／換了機器）時，所有業務 API 回 402，使用者被導到「授權無法使用」說明頁；**最高管理者在那一頁看得到「前往授權頁匯入」**
（其他人看不到），所以買家不需要工程師去放檔案。授權頁本身是獨立頁（不載入側欄、只呼叫兩條授權豁免端點），授權失效時也開得起來。

## 2. 端點

| 端點 | 說明 |
|---|---|
| `GET /api/license/overview` | 授權頁資料（白話欄位）。最高管理者＋非示範帳號。 |
| `POST /api/license/import` | 本文 JSON `{"content": "<授權檔內容>", "apply": false, "confirm": false}`。`apply` 省略＝**預覽**（只驗證、不寫任何東西）；`apply: true`＝驗證通過才換；有差異（`warnings`）時要 `confirm: true`，否則 409。 |

兩條都在 `licensing.LICENSE_EXEMPT_PATHS`（也在 `main.py::_COMPANY_SETUP_ALLOWED`）。**豁免只跳過授權閘門，不跳過任何其他檢查**：端點自己要求已登入＋最高管理者＋非示範帳號。
回應：成功 200（`applied`、`warnings`、`license`、`backup`、`restart_needed`、`message`）；失敗一律有白話 `message`（同 `detail`）與給程式判斷的 `reason`：
`empty`／`malformed`／`bad_signature`／`machine_mismatch`／`machine_unreadable`／`expired`／`same_as_current`（400）、`too_big`（413）、`needs_confirm`／`busy`（409）、`rate_limited`（429＋`Retry-After`）、`backup_failed`／`write_failed`／`verify_after_write_failed`（500）、非最高管理者／示範帳號（403）。

## 3. 安全設計（審查請逐條對）

1. **驗章不重寫**：`license_manager` 只呼叫 `licensing.verify_license(blob)`（＝`_verify_blob`＝`_open_blob`＋機器指紋＋到期）；沒有自己的 Ed25519／base64 解碼（測試用 AST 釘住：不 import `base64`／`binascii`／`cryptography`）。
2. **只換驗過 `reason == "ok"` 的授權**；永久授權「已過維護期」也不收（匯入的目的是讓系統能用）。簽章沒驗過之前不回任何 payload 欄位（`_unverified`）。
3. **驗的與存的是同一個字串**：上傳先正規化（去 BOM、去所有空白，只准 base64／base64url 字元，其餘 `malformed`）。`base64.b64decode` 預設會悄悄丟掉非字母表字元，不先擋的話「驗過的」與「存下去的」可能不是同一份。
4. **先備份、原子寫入、換後複驗、失敗還原**：備份失敗 ⇒ 不換；寫同資料夾暫存檔再 `os.replace`；換完走**讀檔路徑**（`verify_license()`）再驗一次，客戶與到期日必須與剛驗過的一致，否則用備份檔原樣還原（原本沒有檔就刪掉剛寫的）。備份在授權檔旁的 `license_backups/license_<時間>.key`，留最近 30 份。
5. **大小上限 32 KB**：路由層串流讀、讀到上限就停（不先整包讀進記憶體；有無 `Content-Length` 都擋）。**頻率限制**：全域滑動視窗 10 次／10 分鐘（預覽與匯入都算；不依 IP——X-Forwarded-For 可偽造）；被擋時稽核只寫該視窗第一筆。
6. **稽核**：成功 `license.import`、失敗（含預覽被拒）`license.import_rejected`；只記檔案編號（前 12 碼）、驗證後的客戶／到期日、原因碼，**不記授權內容**；要求確認（`needs_confirm`）與預覽成功不寫。
7. **示範帳號一律擋**：示範帳號 role 也是 superadmin，但授權檔是整台機器共用的——不擋就能換掉正式機的授權。
8. **沒有私鑰、沒有繞過**：不提供下載、不簽發、不改 `LICENSE_GATE_ENABLED`、不碰公鑰（測試掃原始碼釘住）。**LG-O1（開發私鑰／`_PUBKEY_DEV` 不進出貨包）與本功能獨立**：LG-O1 落地後（包內 `_PUBKEY_DEV` 清空），開發金鑰簽的授權在正式機上自然驗不過（`bad_signature`）；在那之前，開發金鑰簽的授權匯入時會被標成「測試用」並要求確認（閘門本身照舊收，行為與 T80 一致）。
9. **有差異要確認**：客戶名稱不同、新授權沒包含目前正在用的功能（用載入器同一個 `module_licensed` 判斷）、到期日變早、永久改年費、測試用授權。
10. **模組載入只在開機決定一次**（`core/loader.py`）：匯入後業務 API 立刻依新授權放行／擋，但功能的增減要**重啟服務**才生效——預覽與成功訊息都如實講（`modules_after_restart.gain／lose`、`restart_needed`）。

## 4. 到期提醒

- 橫幅：已登入的 `/api` 回應多帶 `X-Motrix-License-Expiry`（`days=12;level=warning;kind=subscription`，或 `none`；未登入／公開端點沒有此標頭）。`notif.js` 據此在每頁頂端顯示橫幅；剩 ≤30 天 `notice`、≤14 天 `warning`、≤7 天（含當天）`critical`；永久授權已過維護期顯示 `ended`（仍可使用，只是不再提供更新）。最高管理者的橫幅帶「前往授權頁」，其他人看到「請通知最高管理者向供應商續約」。**只在授權仍可用時提醒**（年費過期＝402，由說明頁處理）。獨立於 T80 的 `X-Motrix-License`，兩者互不影響。
- 通知：每日 08:00 的 `system_checks.run_all` 多一步 `_check_license_expiry`，跨過 30／14／7 天（與永久授權已過維護期）各寄一次 `license_expiry` 信給最高管理者；旗標 `system_settings.license_expiry_notified`＝「到期日|檔位」，**寄成功才寫**（沒寄成明天重試），續約換了到期日或回復正常就重新計。信件類型 `license_expiry`（`mail_types`：系統類、`superadmins`、信件格鎖住不可關）。
- **LINE**：信件走 `email_notify.send_registered`，它附帶的 LINE 通道只對 `line_notify.WIRED_EVENTS` 內的事件生效。hichan-6 的事件登記表（`feat/line-events-all`）併入後，**在 `LINE_EVENTS` 加一筆 `license_expiry`（`priority: critical`、`digest: False`）即可**——本分支沒有動 `line_notify`（避免與該分支衝突）。

## 5. 營運備忘

- 備份還原：把 `license_backups/` 內要還原的檔複製成 `backend/license.key`（授權檔每次讀取都會重新驗證，不需重啟）。
- 授權頁的「機器代碼」是申請／換發授權時要給供應商的值（與 402 說明頁同一個說法），不是祕密。
- 正式機上線前提不變：先有有效的 `license.key`（見 `helpers/licensing.py` 的 `LICENSE_GATE_ENABLED` 註解）；本功能讓之後的換約不需要工程師。
