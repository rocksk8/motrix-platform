# 部署腳本的安裝目錄（`$ProdRoot`）與「只能在正式機執行」守門——設計備忘（去識別化線，第 26 班之後）

> 狀態：設計，**尚未實作**。範圍：`apply_update.ps1`、`rollback_update.ps1`、`apply_module_update.ps1`、`setup_autostart_task.ps1`、`setup_heartbeat_task.ps1`、`autostart.bat`、`verify_package.py` 的一則訊息。
> 主持裁示（2026-09-30）：不可以直接改成 `$PSScriptRoot`——這個路徑比對是**安全守門**（防止在開發樹上套用更新），要換成等強度的守門。需要自己的三路徑演練與反向控制。

## 1 · 現況

- 每支腳本開頭寫死 `$ProdRoot = "C:\Users\Motrix\Desktop\V9.0"`、`$Port = 666`；`apply_update.ps1:537-539`／`rollback_update.ps1:345-347` 比對
  `(Get-Item $PSScriptRoot).Parent.Parent.FullName -ne $ProdRoot` ⇒ 不一致就中止（`not_prod_machine`／`rollback_not_prod_machine`）。
- 兩個用途混在同一個常數：① 「腳本現在在哪一棵樹裡」的**身分守門**；② 之後所有 `robocopy`／`plan`／`company_setup_cli` 的**目標路徑**。
- 演練工具（`drill_module_apply.py`、`stepfile_drill.py`、本班的 `drill_t24.py`）都靠「只改寫這兩行」把腳本指到演練目錄——演練副本與正式機腳本的差異必須只有這兩行。
- sale 包的問題：客戶的安裝目錄不是 `C:\Users\Motrix\Desktop\V9.0`，這串路徑（含帳號名）也是本公司環境資訊（掃描器 `dev_path` 命中 19 筆）。

## 2 · 目標與不變式

1. **守門強度不降**：在開發樹（有 `.git`、開發機標記）或任何「不是安裝目錄」的地方執行，一律中止。
2. 目標路徑**由腳本所在位置推得**（`$PSScriptRoot` 往上兩層），不寫死；自用（own）安裝可用設定檔釘死明確路徑（保留現行的「路徑必須等於設定值」比對）。
3. 演練副本與正式腳本的差異不得變多：仍只允許「改寫一處設定」。
4. 不改變任何現有安裝的行為：既有正式機沒有設定檔 ⇒ 沿用現行寫死值（過渡期），逐步換。

## 3 · 建議設計

**根目錄來源（優先序）**
1. `<root>\backend\.install_root`（一行文字，安裝時寫；own 安裝由部署人建立、值＝明確路徑）⇒ 腳本比對「推得的根＝檔內值」，不等 ⇒ 中止（保留 own 現行的強比對）。
2. 沒有該檔：`$PSScriptRoot` 往上兩層推得根，並要求**全部**成立才放行（客戶安裝的預設）：
   - 根下有 `backend\.install_identity`（E4 安裝識別檔；沒有 ⇒ 這不是一個被確認過的安裝，中止並說明）
   - 根下**沒有** `.git`（任何層）
   - 根下**沒有**開發標記：`.no_email_send`、`.no_cloud_archive`、`backend\_demo_*`（演練與開發樹才有）
   - 不做路徑字串判斷（帳號名、資料夾名都不看；不可以用安裝路徑猜正式機）
3. 兩者皆不成立 ⇒ 中止。

**Port**：不再寫死，讀 `backend\.install_port`（沒有 ⇒ 666）；演練改寫的是這個檔而不是腳本。

**演練**：腳本本身**不再需要被改寫**（更強：演練跑的就是正式腳本原樣）——演練目錄放 `.install_root`／`.install_port` 即可。這同時解掉「apply 之後 rollback 腳本被包內原檔蓋回、要重新改寫」的演練專屬麻煩（第二十四班演練發現）。

## 4 · 需要的驗證（自己的三路徑演練＋反向控制）

| 路徑 | 內容 |
|---|---|
| p1 own 既有正式機形狀 | 有 `.install_root`（明確路徑）：正常套用／回滾；把腳本搬到別的樹 ⇒ 中止 |
| p2 客戶安裝形狀 | 無 `.install_root`、有 `.install_identity`、無 `.git`、無開發標記：正常套用／回滾 |
| p3 過渡 | 舊安裝沒有任何新檔、腳本仍是寫死值：行為與現在逐字相同（過渡期相容） |

反向控制（每一條都要紅）：在 `.git` 樹裡執行、在有 `.no_email_send` 的演練樹裡執行（p2 條件下）、缺 `.install_identity`、`.install_root` 與推得的根不一致、`.install_port` 內容非數字。
掃描面：sale 包的 `dev_path` 命中因此歸零（腳本內不再有 `C:\Users\Motrix\…`）。

## 5 · 不做的事

- 不用路徑字串（帳號名、資料夾名）判斷「是不是正式機」。
- 不放寬 own 現行比對（`.install_root` 存在時仍是嚴格相等）。
- 這份設計**不含**IP 預設值（172.16.10.177）的另案，那是功能預設值，見獨立項目。

## 6 · 排程與相依

排在第 26 班的去識別化線之後；依賴 E4（`.install_identity`）已合回（已合）。實作前先做 p1/p2/p3 的演練腳本再改腳本（先有紅燈）。
