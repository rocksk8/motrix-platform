# 稽核：主持的 O7 修正（P9 排版器切換範圍的兩個競態）（B 稽核，2026-09-26）

> 依 PLAYBOOK §E、§9d 輪替（B 原本審 A，A 無回應改審主持）。稽核者 B 沒有寫過受稽核的程式碼。
> 對象：`origin/wip/h-o7` `a234771d`（基底 `bf64e82b`）；改動 `frontend/static/layout-editor.js`（+35／−12）、`modules/tender_radar/tests/test_tender_p9_layout_e2e_2026_09_26.py`（+70）。
> 稽核樹 `D:\MOTRIX-PLATFORM-B20`（detached a234771d）；探針檔 `modules/tender_radar/tests/test_zz_o7_audit_probe.py` 只在稽核樹、未提交，稽核完刪除。
> 分級：**必修 M**／**建議 S**／**觀察 O**。

## 0. 結論

- 序號丟棄舊回應（`_scopeSeq`）成立：兩處 await 之後都有檢查；被取代的那一趟直接 return，由最新那一趟收尾。
- `loadsDone` 在例外路徑有加到（`loadScope` 的 `finally`）。✅（主持指定要看的第 3 點）
- inert 範圍：只套在 `.ml-ed__body`；表頭（關閉、套用範圍、以角色預覽）不受影響，頁尾按鈕原本就 `:disabled="busy"`。✅（第 1 點：沒有擋到不該擋的）
- **必修 1 項**：`busy` 是兩個非同步動作共用的一個布林——範圍載入中去點表頭的「以角色預覽」，`previewAs()` 結束時把 `busy` 設回 false ⇒ inert 解除、頁尾可按，**O7 原本的競態重新打開**（實測，見 M-1）。
- 建議 2 項、觀察 1 項。

## 1. 發現

### 必修

**M-1　範圍載入中切「以角色預覽」⇒ `busy=false` ⇒ 編輯區在載入完成前恢復可編輯**
- 位置：`layout-editor.js` `previewAs()`（`this.busy = true … this.busy = false`）與 `_loadScope()`（`this.busy = true … this.busy = false`）共用 `busy`；inert 綁 `busy`（`x-effect="$el.inert = busy"`），頁尾 `:disabled="busy"`。
- 「以角色預覽」下拉在 `.ml-ed__head`，刻意不在 inert 範圍內 ⇒ 載入期間可以操作。
- 實測（稽核樹探針，`_hold` 攔住 `scope=role:admin` 的回應）：切範圍 ⇒ `busy=1`；選預覽角色 sales 後 1.5 秒：`{busy: '0', loaded: '', inert: False}`；回到編輯（預覽選空）⇒ 仍 `{busy: '0', loaded: '', inert: False}`，「地點」勾選框**點得到**（`clickable_while_scope_loading=True`）。之後攔住的回應回來 ⇒ `_loadScope` 以舊範圍整份覆蓋 ⇒ 剛才的修改靜默消失，而頁尾的「發布」在這段期間也可以按。
- 同樣會騙到 e2e：只等 `data-busy === '0'` 的題會在載入完成前就往下走（新題改等 `data-loaded-scope` 是對的，但舊的 `IDLE` 仍被其他題使用）。
- 建議修法：載入與預覽各用自己的旗標（例：`loadingScope` 與 `previewing`），`inert`／頁尾 disabled／`data-busy` 看兩者的「或」；或載入期間把「以角色預覽」也 disabled。補一題 e2e：攔住範圍回應 ⇒ 切預覽角色 ⇒ 回到編輯 ⇒ 勾選框仍點不到；釋放後可以（正對照）。

### 建議

**S-1　`_loadScope` 丟例外時 `busy` 卡在 true、畫面沒有說明**
- `_j()` 用 `fetch`：斷線／伺服器沒回應時 `fetch` 會 reject ⇒ `_loadScope` 在 `busy = true` 之後直接丟出 ⇒ `busy` 永遠是 true（編輯區 inert、頁尾全部 disabled），`state`、`msg` 都沒有變，看起來像當掉。`loadsDone` 有 +1（finally），但只有 e2e 看得到。
- 在 inert 之前也是這個樣子，但 inert 讓它從「可以操作但資料舊」變成「整塊不能動、也沒有理由」。
- 建議：`_loadScope` 以 try／finally 收尾——這一趟仍是最新的（`seq === this._scopeSeq`）才清 `busy`；例外時 `state = 'error'`、`msg` 說明「載入範圍失敗，請重新選擇範圍或重新開啟」（〈降級之後它還是會動〉：讀不到要明說）。補一題：`page.route` 讓範圍請求 abort ⇒ 畫面有錯誤訊息、可以再切一次範圍恢復。

**S-2　原題「第 2 版內容」的斷言只驗「沒有那一筆 hide」**
- 新增的 `assert {"op": "hide", "target": COL + "location"} not in <第 2 版 ops>`：與第 1 版相同的空發布會被抓到（第 1 版有那筆 hide）✅；但「第 2 版的 ops 整個是空的」（例如其他 op 也一併遺失）同樣會過。
- 建議改成比對完整內容：第 2 版 ops ＝ 第 1 版 ops 扣掉那一筆 hide（或直接列出預期的 ops）。

### 觀察

**O-1　新 e2e 第一題以 `pytest.raises(Exception)` 驗「點不到」**
- `box.click(timeout=1500)` 丟任何例外都算過——元素找不到、被 detach、不可見也會丟逾時。建議在點之前先斷言那個元素確實存在且可見、`.ml-ed__body` 的 `inert === true`，讓「點不到」只可能是 inert 造成的。

## 2. 核對過的事

| 項目 | 結果 |
|---|---|
| 序號：兩個 await 之後都檢查 `seq !== this._scopeSeq` | ✅ |
| 被取代的那一趟不改 `defs`／`startNote`／`work`／`loadedScope` | ✅（全部延到檢查之後才寫） |
| `loadsDone` 例外路徑 | ✅ `finally` |
| inert 範圍不含表頭 | ✅ `.ml-ed__head` 在 `.ml-ed__body` 之外 |
| 頁尾按鈕載入中不可按 | ✅（`:disabled="busy"`）——但見 M-1：`busy` 會被預覽提早清掉 |
| `_scope()` 改等 `data-loaded-scope` | ✅ 比只等 `busy=0` 正確 |

## 3. 回覆欄（被稽核者填；原稽核者確認後才關）

| # | 回覆 | commit | 稽核確認 |
|---|---|---|---|
| M-1 | | | |
| S-1 | | | |
| S-2 | | | |
| O-1 | | | |
