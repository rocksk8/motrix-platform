# MOTRIX 正式機升級結果（V9 → MOTRIX-PLATFORM，2026-09-27）

給開發機主持（hichan-8d）：正式機依 PROD-UPGRADE-HANDOFF.md 升級完成，結果如下。

## 摘要

- 安裝包：`20260927_220134_c006a2a0`（full，commit c006a2a0），SHA256 清單 503 檔全符、0 缺檔
- 預檢：exit 0（第一次 exit 1，原因見「偏差」第 2 點）
- 備份：exit 0，已試還原比對雜湊
- **manifest SHA256：`647360dede4824076dc471123fdab6cea1a1e5fe82b28ff2f56e3f2f3f0dd6b9`**
  （使用者已抄在備份目錄以外；與 `$BK\upgrade_manifest.json` 實際雜湊相符）
- 轉換：exit 0；`migrate.ok` 為 true，`stderr_tail` 為空；移除 1629 檔、新增 502 檔、無替換而移除 1450 檔
- 驗證（port 6671）：exit 0；`problems` 為空，`warnings` 為空
- 恢復服務：`https://127.0.0.1:666/api/ping` 約 14 秒回 200；Heartbeat 的 LastTaskResult 為 0；三個排程都是 Ready
- 升級後確認（使用者用瀏覽器看）：首頁、案件、傳票、報表、字型、地圖都正常；雲端備份目標（個資存檔）顯示「已就緒」
- `company_profile.filled`：空的（沒補任何欄位）
- `settings_added`：`payslip_archive_path`（值是空的）

## 路徑（與交接單不同）

```
$ROOT = C:\Users\Motrix\Desktop\V9.0
$NEW  = C:\Users\Motrix\Desktop\20260927_220134_c006a2a0      （交接單原寫 MOTRIX-NEW-20260927\...）
$SHA  = C:\Users\Motrix\Desktop\full-package-sha256.txt        （交接單原寫 MOTRIX-NEW-20260927\...）
$BK   = C:\Users\Motrix\Desktop\MOTRIX-UPGRADE-BACKUP\20260927  （保留，至少到下個月的月備份產生之後）
```

## 偏差 / 請主持留意

1. **轉換沒印出「⚠ 以下設定檔保留了這台機器的版本」**（交接單預期會出現 autostart.bat），`package_default_config.kept_differs_from_package` 是空的。`backend\autostart.bat` 仍然存在，服務也正常起來了。
2. **第 5 節停服務的步驟不夠完整**：`backend\autostart.bat` 是一個 `:loop` 迴圈，uvicorn 結束後 5 秒會自動重開。這台機器從 9/22 起就有一個 `cmd.exe /c autostart.bat`（PID 20884）一直在跑，停用排程並不會結束它，所以停服務之後 V9 又被拉起來，導致第一次預檢失敗（「V9 服務仍在執行」）。經使用者同意，先確認命令列，再結束 cmd.exe 20884 和 uvicorn.exe 14396，之後預檢才通過。
   **建議**：RUNBOOK §1 / 交接單第 5 節加上「結束命令列含 autostart.bat 的 cmd.exe」。
3. 被移走的檔案裡有 `frontend/fonts/LINESeedTW-*.otf` 字型和 `frontend/static/vendor/leaflet/*` 地圖套件。使用者確認升級後字型和地圖都正常。
4. 轉換結束時最後一行中文訊息印成亂碼，但 JSON 內容和結束碼都正常。

## 備份目錄檔案 SHA256（`$BK`）

```
430a04b1467e64b987c60f11ae7b5595575d101b2e0def161266e1ec9750072b  backup_verify.json
e720e780d9973e4c1e5d0cd63d3e7e490aab4ef836f51abe9e1b87c477fb4d73  conversion_log.json
b8b4884a62d2bfd6afcdff7f26e0db76c233e9abf5fd743358f3410e36bcf8b6  post_convert.json
647360dede4824076dc471123fdab6cea1a1e5fe82b28ff2f56e3f2f3f0dd6b9  upgrade_manifest.json
909b4e5bb15f161cbf66aacabb60102b6916776c05b76b756921578737cfecbc  verify_log.json
```

## verify_log.json 原文

```json
{
 "problems": [],
 "warnings": []
}
```
