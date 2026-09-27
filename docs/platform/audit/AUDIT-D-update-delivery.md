# 稽核：更新交付 wip/a-update-delivery 733794ea（含 be223e60 出貨公鑰）（D，2026-09-28）

> 範圍：`git diff origin/platform...733794ea`（delivery.py、test_delivery、UPDATE-DELIVERY.md）。主持指定 be223e60；origin 後來又多了 733794ea（交付資料夾讀儲存位置設定），一併看。
> 私鑰（D:\MOTRIX-KEYS\delivery）**沒有讀**；題目用的是自己產生的金鑰（test:30）。
> 題目與突變在拋棄式 worktree（detached 733794ea）跑，暫存已刪，`git status` 乾淨。

## 0. 結論

- **必修 0、建議 3、觀察 4。**
- 主持的三個重點：

| 重點 | 讀碼＋題目＋突變 | 判定 |
|---|---|---|
| 驗章一律用已安裝版本的公鑰 | `verify_staged` 用的是**執行中那一份** delivery.py 的 `DELIVERY_PUBKEY_PEM`（:316）；包裡的 delivery.py 要到驗章通過、`apply_staged` 複製 tools（:461）之後才進安裝目錄。CLI 沒有開放傳入公鑰 | 成立。但前提是「呼叫者是安裝目錄那一份」，目前沒有任何呼叫者（儀表板還沒接），見 US2 |
| 包不能替自己背書 | 簽章涵蓋 delivery.json＋package.sha256（:104）；payload 逐檔雜湊，多、少、不同都擋（:338-346）；包裡的公鑰不參與驗證 | 成立（突變 D2、D4、D5 皆紅） |
| 空值拒絕 | `if not pub` ⇒ problems（:326）；公鑰、簽章格式壞掉 ⇒ False（:126） | 成立（突變 D1 紅） |
| 出貨公鑰本身 | 是合法的 Ed25519 公鑰；用別的金鑰簽的包會被拒（題 :128-133） | 成立 |

- 基準 30 過；突變 8 個，紅 7、存活 1（D6，見 UO2）。

## 1. 建議

**US1　`apply_staged` 相信呼叫端交來的 `verified`，驗完到套用之間沒有再驗一次**
- 證據：`apply_staged(staged, install_root, verified)` 只看 `verified["ok"]`（:451），接著就把 `staged\payload\backend\tools` 複製進安裝目錄（:461）。驗證與按下套用之間可能隔很久；staging 在正式機本機、安裝目錄外（任何本機行程都寫得到）
- 影響：拿到本機寫入權的人，可以在驗完之後換掉 staging 裡的 tools，而這些檔案會以服務的權限執行。雲端資料夾那一側的攻擊（5-4）擋得住，本機這一側擋不住
- 建議：`apply_staged` 內部在複製 tools 之前，自己重跑 `verify_staged(staged, install_root, run_verify_package=False)`（只重算雜湊與簽章，很快），不通過就拒絕；參數 `verified` 只留作 UI 顯示用

**US2　「用已安裝版本的公鑰驗章」要變成守門，不能只靠之後接儀表板的人記得**
- 現況：`git grep verify_staged|apply_staged` 在 delivery.py 與題目以外 0 筆。(c) 接儀表板時，只要從 staging import delivery（或以 staging 的 python 執行），整條信任鏈就失效，而且不會有任何題紅
- 建議：接儀表板的那一包，同時補一題：儀表板取 delivery 模組的路徑必須在 `<ROOT>\backend\tools`，不可以在 staging 或包裡（反向控制：把路徑換成 staging ⇒ 紅）

**US3　UPDATE-DELIVERY 列了兩項防護，實作裡沒有，也沒有標成待做**
- 5-4「驗不過 ⇒ 包移到 `staging\rejected\`」：delivery.py 沒有 rejected 的處理
- 5-7「複製到 staging 前檢查可用空間 ≥ 包大小×3」：`stage` 沒有檢查空間（grep `disk_usage` 0 筆）
- §9.1 還寫著「公鑰 DELIVERY_PUBKEY_PEM 目前是空的」，be223e60 之後已經不是（文件過期）
- 建議：§9 補「未實作」清單（這兩項），並更正公鑰那一句（保留原句）

## 2. 觀察

- **UO1**：舊包重放。簽章不會過期，雲端保留最近 3 份。能寫雲端資料夾的人可以把一份舊的、合法簽章的包放回 `packages\`，正式機只給一個「退版」note（:357，U-3 確認一次）。建議畫面上把退版標成醒目的警示，不要與一般 note 同一個樣式
- **UO2**：突變 D6 存活：`stage` 的「複製前後 delivery.json 有沒有變」拿掉之後，題目照樣綠（只驗到檔數）。後面的 `verify_staged` 逐檔雜湊仍然會擋下，所以是 fail-closed，只差在訊息變成「雜湊不符」而不是「同步中」
- **UO3**：`keygen` 用 `os.open(..., 0o600)`，在 Windows 上這個權限不會生效，私鑰檔的存取權取決於所在資料夾的 ACL。建議 RUNBOOK 寫明 D:\MOTRIX-KEYS 的 ACL 只給使用者本人
- **UO4**：§9.2 寫鎖檔的 `started_at` 是 `YYYY-MM-DDTHH:MM:SS`，H12 的實作寫的是 `yyyy-MM-dd HH:mm:ss`（空白，不是 T）。目前沒有程式解析它（read_lock 只顯示），記錄備查；以其中一邊為準改齊即可

## 3. 重現

```
git worktree add --detach D:\MOTRIX-PLATFORM-D14m 733794ea
cd D:\MOTRIX-PLATFORM-D14m\backend
D:\MOTRIX-PLATFORM\.venv312\Scripts\python.exe -m pytest tests/platform/test_delivery_2026_09_28.py -q -n 2 --basetemp=%TEMP%\motrix-pytest-d-dlv
# 突變 D1～D8：delivery.py 逐項唯一錨點取代 → 跑同一個題檔 → 寫回原內容
```
