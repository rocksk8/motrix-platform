# 稽核：第十九班最終審（origin/platform 0af16ad1，部署包 20260928_231025_0af16ad1）（D，2026-09-28）

## 0. 判定

**可上正式機。**

## 1. 內容範圍

- f04a245a（正式機將是的基底）..0af16ad1 的產品碼（排除 docs、tests）：`main.py`（API 文件預設關閉）、`conftest.py`、`registry.py`（CORE 1.67）、`core/CHANGELOG`、`final_drill.py`、`version_manifest.json`
- 與 D 審過的 A46（309e28ed，含 A46-S1）相比，只差 version_manifest 一筆「附近旅宿 2026-09-28k」（第十八班 T18F-O1 的補記；內文只描述功能與官方資料來源，無識別值）

## 2. 包的驗證（D 獨立重做）

| 項目 | 結果 |
|---|---|
| 包內檔數 | 573（pyc 0） |
| 逐檔對 git blob（0af16ad1） | 546 相同、23 只差 CRLF、3 為建包產生、1 不同＝version_manifest |
| version_manifest | 427 筆、順序相同；只有 51 筆舊條目多 `time` 欄（投影，同前幾班） |
| 與第十八班包比較 | 多 3 檔，全是 `docs/platform/audit/` 的 D 稽核文件（docs 整包出貨，是 H2 販售包去識別化已知、另開一線的那一類）；無檔案移除 |
| 包外（程式目錄、非 tests） | 31，同第十八班的排除規則 |
| 雲端 payload（packages\20260928_231952_0af16ad1_full） | 573 檔，只在本機 0、只在雲端 0、內容不同 0 |
| `package.sha256` 的 SHA256 | F406A2D3…FE08，與主持提供的一致 |

## 3. 演練（apply-run-t16，run_T19.log）

- f04a245a → 0af16ad1：`::RESULT:: v=2 status=success rolled_back=applied service=up exit=0`；刪 0、新增 0；健檢第 1 次連不上（服務剛起），第 2 次（7 秒）成功
- 本次啟動段 server.log：「模組 lodging 1.1.1 已載入」、「MOTRIX_GEO=1 …」都在；ERROR 只有既有的「雲端備份路徑不可用（這台設定成不寄信）」演練告警
- log 中段「開關沒有生效：MOTRIX_GEO」＝第十八班 T18F-O2 的時序誤報（server.log 有那一行）；A 已在 wip/a-switch-warn 修正（D 審過放行），尚未上車

## 4. 安裝指示（CLAUDE-正式機安裝指示_0af16ad1.md）

- 版本檢查 f04a245a、雜湊 F406A2D3…、`bad=0 files=573`、`ApplyScriptVersion 28g` 都與包一致
- 第十八班的 T18F-F1 已改正：`unhealthy_rolled_back` 的回滾目標寫 **f04a245a**
- 已預告 GEO／雷達開關的時序誤報，並明寫「不要因此改 autostart 或排程」✔
- 旅宿下載開關：寫明「使用者已同意寫進 autostart.bat（上次）、本次重啟後生效、不要再改 autostart、只看狀態不要按下載」✔
- 建議（非必修）：成功後的確認加一項「`/openapi.json`、`/docs` 回 404」，就能驗到本包的主要改動是否在正式機生效（演練已驗）
