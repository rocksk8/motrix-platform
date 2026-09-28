# 稽核：第十八班最終審（origin/platform f04a245a，部署包 20260928_204954_f04a245a）（D，2026-09-28）

## 0. 判定

**可上正式機。** 交付前把安裝指示的一個錯字改掉（§4 T18F-F1）；包本身不需要重建。

## 1. 內容範圍

- 3e061d6f（正式機現況）..f04a245a 的產品碼 ＝ E 旅宿線（E1 設計、E2 全段 7760dcf3、E3 487b26f0、第十八班競態＋demo 分類 b4528e8d，全部 D 審過）＋列車簿記
- 以 `git diff b4528e8d f04a245a`（排除 docs 與 tests）核對：**只差 `backend/core/CHANGELOG.md`**（B54 段去重，9 行刪除）⇒ 出貨的產品碼就是 D 審過的 b4528e8d
- 其他 commit 是稽核文件、CORE-SPEC 裁示、mustfix 登記、一個 test-only 修正（ab581ecb，SST 範圍題改用自己的空表）

## 2. 包的驗證（D 獨立重做）

| 項目 | 結果 |
|---|---|
| 包內檔數 | 570（pyc 0） |
| 逐檔對 git blob（f04a245a） | 543 相同、23 只差 CRLF（.gitattributes 規則內的 bat／ps1／txt 等）、3 為建包產生（deploy_manifest.json、.build_commit、modules.lock.json）、1 不同＝`version_manifest.json` |
| version_manifest 差異 | 425 筆、模組與版本順序完全相同；51 筆舊條目多了 `time` 欄（建包投影，前幾班相同）；內容無其他改動 |
| 包外（程式目錄、非 tests） | 31：12 份模組 SPEC.md（含新的 lodging，建包刻意排除）、16 支開發機工具、conftest／migration 計畫／requirements-dev ⇒ 與第十七班相同的排除規則，多的一個就是 lodging/SPEC.md |
| 雲端 payload（MOTRIX-交付 packages\20260928_205112_f04a245a_full） | 570 檔，只在本機 0、只在雲端 0、內容不同 0 |
| `package.sha256` 的 SHA256 | FC688E37…DC83，與主持提供的一致 |

## 3. 演練（apply-run-t16，run_T18.log）

- 3e061d6f → f04a245a：`::RESULT:: v=2 status=success rolled_back=applied service=up exit=0`
- 刪除計畫：刪 0、新增 15；migration 乾跑通過；健檢第 1 次（4 秒）成功
- server.log：20:50:54「模組 lodging 1.1.1 已載入」；ERROR 只有既有的「雲端備份路徑不可用（這台設定成不寄信）」演練告警，套用前後同樣出現

## 4. 主持問的兩點與其他發現

**版本端點仍是 2026-09-28i：與內容一致。** version_manifest **沒有任何旅宿的條目**（最上面一筆是「地圖 2026-09-28i」），所以端點不會變。PLAYBOOK §G5 #11 只要求「當天第一個 commit 補當天條目」，9/28 已有 a～i，字面上沒有違反；但一個使用者看得到的新功能沒有版本紀錄，「版本紀錄」頁不會告訴使用者多了附近旅宿。**不擋出貨**；要不要補由主持決定（補的話要重建包，建議下一班）。→ T18F-O1

**`MOTRIX_LODGING_FETCH` 沒設時：功能可用、不能下載，而且畫面有說明。**
- `source.fetch_on()` 判準是 `== "1"`，出貨常數 `LODGING_FETCH_ENABLED = False` ⇒ 預設關；關著時 `refresh()` 回 `switch_off`，連 `fetch_raw` 都不呼叫
- 紀錄頁：「更新旅宿資料」按鈕在 `!fetchEnabled` 時停用，最高管理員會看到「旅宿資料下載未開啟（伺服器需設定 MOTRIX_LODGING_FETCH=1 並重啟）」
- 地圖覆蓋層與查詢：沒有資料 ⇒ 「尚未下載旅宿資料，請到『附近旅宿紀錄』頁按『更新旅宿資料』」（`available=False, reason=no_catalog`，不是 0 筆，有題）
- 要不要在正式機開這個開關（對外連線到觀光署資料）是使用者的決定；安裝指示沒有提到，建議在回報或指示裡提一句 → T18F-S1

**T18F-F1（交付前改；不是產品必修）　安裝指示第 5 步的回滾目標寫錯**
- `CLAUDE-正式機安裝指示_f04a245a.md` 第 74 行：「`unhealthy_rolled_back`｜健檢沒過，已自動回到 **822286ed**」。正式機現在是 **3e061d6f**（同一份指示第 8、23 行也這樣寫）⇒ 改成 3e061d6f；否則正式機 Claude 回報時會寫錯版本，或以為回滾到了別的版本

**T18F-O2（觀察，既有誤報）　「開關沒有生效：MOTRIX_GEO」**
- run_T18.log 中段有這個警告區塊（叫人到工作排程器重新執行），而 server.log 在 20:50:55 **確實**寫了「MOTRIX_GEO=1 —— 地址定位已開」，只比健檢成功晚一點
- run_T14／T16／T17 也都出現同一個警告 ⇒ 是 ps1 開關檢查的時序誤報，不是這一班造成的
- 指示第 15 行已禁止改排程與結束行程，所以正式機 Claude 不會照警告去做；建議在指示裡預先說明「若出現這個警告，確認 server.log 有 MOTRIX_GEO=1 那一行即可」，並把 ps1 的檢查改成等待幾秒或讀到該行為止（下一輪）

**建議**
- **T18F-S1**：安裝指示或正式機回報提醒一句「旅宿資料下載預設關閉；要開需在 autostart.bat 設 `MOTRIX_LODGING_FETCH=1` 並重啟（對外連線，使用者決定）」
