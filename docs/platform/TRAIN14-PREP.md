# 第十四班列車合回整備（A，2026-09-28 01:49；唯讀分析）

> 對象：origin/platform **d1f43b0b**（CORE_VERSION 1.56）。沒有改任何分支、沒有跑測試。
> 衝突以 `git merge-tree --write-tree` 計算（檔名＋`<<<<<<<` 數＝hunk 數）。
> 腳本與原始結果留在 A 的 scratchpad（`train14.py`／`train14.json`），可以重跑。
> ⚠ 量測的是 01:49 當下的 SHA。乘客換 HEAD（例如 b-payreq 修 AB-M1）後，受影響的列要重算。

## 0. 乘客與基本資料

| 乘客 | SHA | 分叉點（落後 origin 幾筆） | 改檔數 | fixture 層 | L0／main.py | 對 origin 的衝突 |
|---|---|---|---|---|---|---|
| h-branding | ec48a245 | c006a2a0（19） | 111 | **backend/conftest.py** | core/CHANGELOG、registry、**core/upgrade.py**、**main.py** | 無 |
| b-payreq | 5d30ede6 | 6169f9cf（11） | 38 | — | core/CHANGELOG、registry、**loader.py**、**migrations.py**、**main.py** | **CORE-SPEC.md 1 hunk** |
| a-prod-status-upgrade | b8858fee | 9350a3df（8） | 9 | — | core/CHANGELOG、registry、**core/upgrade.py** | 無 |
| h-apply-platform | 8eb791f7 | 9350a3df（8） | 13 | — | — | 無 |
| a-build-python-2 | b86bc4c8 | 1645b7b5（9） | 4 | — | — | 無 |
| a-builder-output | be26ee3a | e21b099a（28） | 19 | — | core/CHANGELOG、registry | 無 |
| b-builder-dnd-5 | d26a7b0c | e21b099a（28） | 26 | — | 同上 | 無 |
| a-builder-sink-guard | 6a64fd68 | e21b099a（28） | 27 | — | 同上 | 無 |
| a-cr-network-errors | db9aeb51 | fc091b5c（6） | 3 | — | — | 無 |
| b-jv36-needs-m01 | 424fe442 | 4348a3f3（1） | 4 | — | — | 無 |
| a-jv36-escape-404 | ba140a2c | 4348a3f3（1） | 4 | — | — | 無 |
| a-drill-d7extra | cd8aa5aa | 4348a3f3（1） | 2 | — | — | 無 |
| b-rc-scope | a7db2503 | d1f43b0b（0） | 3 | — | — | 無 |
| a-mustfix-scan | 2456a0cc | 4348a3f3（1） | 13 | — | — | 無 |

**包含關係**（祖先 ⇒ 只需要上較新的那一包；兩兩比對已排除）：

- `a-builder-output` ⊂ `b-builder-dnd-5` ⊂ `a-builder-sink-guard`
- `b-jv36-needs-m01` ⊂ `a-jv36-escape-404`

沒有分支動到產生檔（UNIT-INDEX／dep_graph.json／test_map.json）。

## 1. 衝突矩陣（兩兩；只列「有共同檔」的配對）

「衝突」欄是文字衝突（檔：hunk 數）。「語意重疊」欄是同檔、沒有文字衝突、但兩邊都改的地方，要人讀。三個簿記檔依 PLAYBOOK §C-11 另外判斷：
- `version_manifest.json`：同一筆條目兩邊都改才算
- `core/CHANGELOG.md`、`registry.py`：交給 `core_bump`

| 配對 | 衝突 | 語意重疊（非簿記檔） |
|---|---|---|
| a-cr-network-errors × 建構器鏈（output／dnd-5／sink-guard） | **custom-records.html：3**、manifest：1 | — |
| a-prod-status-upgrade × h-apply-platform | **tools/platform/upgrade.py：1**、manifest：1 | UPGRADE-RUNBOOK.md |
| b-payreq × h-branding | CHANGELOG（core／analytics／arap／case）、**case/module.json：1**、registry：1、l1_interface_snapshot：1、manifest：1 | **main.py**、analytics／arap module.json、MODULE-GUIDE.md、modules.json、**cashier.html** |
| b-payreq × 建構器鏈 | core/CHANGELOG：1、registry：1、l1_interface_snapshot：1、manifest：1 | modules.json |
| b-payreq × a-prod-status-upgrade | core/CHANGELOG：1、registry：1、l1_interface_snapshot：1、manifest：1 | — |
| h-branding × 建構器鏈 | core/CHANGELOG：1、manifest：1 | l1_interface_snapshot、modules.json、**custom-records.html**、**module-builder.html**、**sidebar.js** |
| h-branding × a-prod-status-upgrade | core/CHANGELOG：1、manifest：1 | **core/upgrade.py**、l1_interface_snapshot |
| a-prod-status-upgrade × 建構器鏈 | core/CHANGELOG：1、manifest：1 | l1_interface_snapshot |
| b-payreq × h-apply-platform | manifest：1 | CORE-SPEC.md |
| a-cr-network-errors × h-branding | manifest：1 | **custom-records.html** |
| a-mustfix-scan × b-rc-scope | — | PLAYBOOK.md（兩邊各加一段） |
| 其餘有 manifest 的配對（a-build-python-2 × 7 包、h-apply-platform × 4 包 等） | manifest：1（同日同一個插入點） | — |

**要人讀的五處（文字衝突之外的實質重疊）**

1. **custom-records.html**：有三方。
   - a-cr-network-errors 與建構器鏈的 3 個 hunk，解法見 AUDIT-A 第 1 項回報：保留 `_send`，api／post／put 開頭照字面保留 `this._noApiInPreview();`，否則 `test_builder_preview_static` 與 `test_e2e_builder_preview` 會紅。
   - h-branding 在同頁把 favicon 改成打 API（見第 6 點）。
   - a-builder-sink-guard 的守門會掃合回後的頁面，a-cr-network-errors 沒有新增 HTML 寫入點（讀碼確認：只有 `_send`／`fail`／`runRetry`）。
2. **tools/platform/upgrade.py**：兩邊都改 `convert` 的收尾，要兩個都保留。
   - a-prod-status-upgrade 寫部署紀錄（prod-status）
   - h-apply-platform 寫 apply baseline（`write_apply_baseline`）
3. **main.py**：b-payreq 把模組載入搬進 `helpers/module_startup`，h-branding 另改 main.py。合回後要確認兩者之間沒有塞進新的程式（「逐字相同」的守門是 `test_module_startup`）。
4. **core/upgrade.py**：h-branding（安裝基準過濾）與 a-prod-status-upgrade 都改，沒有文字衝突，但兩者都影響轉換流程 ⇒ 兩邊的題都要跑。
5. **cashier.html**：b-payreq 加「請款待付款」頁籤，h-branding 改 favicon 連結（見第 6 點）⇒ e2e 要跑出納頁。
6. 🔴 **h-branding × 建構器預覽的「不打 API」**（兩包各自都綠，合回後才會碰到）：
   - h-branding 把頁面的 favicon 從 `../static/favicon.png` 改成 `/api/system/branding/favicon`；custom-records.html、cashier.html 讀碼確認，其他頁應同樣改了。
   - 建構器的 `test_e2e_builder_preview_2026_09_27.py:165-166`（題②：直接開 `custom-records.html?preview=1`）收集頁面上**所有** URL 含 `/api/` 的請求，要求為 0。
   - 頂層頁面的 favicon 由瀏覽器自己請求，不經 `window.fetch`，預覽模式的三道防線擋不到。headless Chromium 若請求 favicon，這一題合回後就會紅，或時紅時綠。
   - iframe 裡那一題（:141）只收 iframe 的請求，而瀏覽器不替 iframe 抓 favicon ⇒ 不受影響。
   - 處置：列車上一定要跑 `test_e2e_builder_preview`。紅了的話，由主持裁示二選一：
     - (a) 題目排除 `/api/system/branding/favicon`（它是公開、唯讀的資源，不是資料 API）
     - (b) 預覽模式把 favicon 換回靜態檔
   - 不可以把收集範圍放寬成「只看 fetch」：那樣會把預覽頁上其他真正的 API 請求一起放過。

## 2. 建議上車順序

依 PLAYBOOK §G3：動到 fixture 層的排最前面，L0／main.py 次之，再來是依賴關係，最後是只加題或文件的。

| # | 乘客 | 理由 |
|---|---|---|
| 1 | h-branding | 唯一動 **conftest.py**（fixture 層）；也動 main.py、core/upgrade.py；改 11 個模組版號 |
| 2 | b-payreq（**AB-M1 修好的新 HEAD**） | L0：loader／migrations／registry、main.py（module_startup）；CORE-SPEC 對 origin 有 1 hunk。**必修 AB-M1 未修好之前不上車**；沒上的話第 4 包的模組化乾跑路徑維持休眠（行為等於舊版，RUNBOOK 已寫明） |
| 3 | a-prod-status-upgrade | core/upgrade.py＋L0 registry；和第 4 包在 upgrade.py 有 1 hunk ⇒ 先上，第 4 包 rebase 時解 |
| 4 | h-apply-platform | 依賴第 2 包的 `helpers/module_startup`（乾跑照啟動規則載入模組）；與第 3 包的 upgrade.py、RUNBOOK 要合併 |
| 5 | a-build-python-2 | 同屬部署工具；版本紀錄與第 3、4 包併成一筆（見 §3） |
| 6 | a-builder-sink-guard（含 a-builder-output、b-builder-dnd-5） | 只上最頂的那一包；和第 1 包在 custom-records／module-builder／sidebar.js 有語意重疊 |
| 7 | a-cr-network-errors | 必須在第 6 包**之後**：照 §1 第 1 點的解法 rebase 到建構器上 |
| 8 | a-jv36-escape-404（含 b-jv36-needs-m01） | 只加題；上最頂的那一包 |
| 9 | a-drill-d7extra | 只改工具與題 |
| 10 | b-rc-scope | 只加工具與題；PLAYBOOK 與第 11 包各加一段 |
| 11 | a-mustfix-scan | **排最後**：它的守門掃列車上**所有**稽核檔。前面各包若帶進新的必修或關閉紀錄，登記表（`mustfix_open.json`）要在同一班更新（見 §4） |

## 3. 版號撞號清單

**CORE_VERSION**（origin 1.56）：

| 乘客 | 分支上的暫用號 |
|---|---|
| h-branding | 1.57 |
| a-prod-status-upgrade | 1.57 |
| 建構器鏈（output／dnd-5／sink-guard） | 1.57 |
| b-payreq | 1.58 |

⇒ 照 PLAYBOOK §C-7 在列車上逐包 `core_bump --apply`，依 §2 的順序取號。預期是 branding 1.57 → payreq 1.58 → prod-status 1.59 → 建構器 1.60；實際的次版號或主版號，以 core_bump 依介面差異判定為準。

**version_manifest（2026-09-28 的同日字母；VR3 一個模組一筆、版號唯一）**：

| 版號 | 模組 | 乘客 |
|---|---|---|
| 2026-09-28a | 部署工具 | a-build-python-2 |
| 2026-09-28a | 部署工具 | h-apply-platform |
| 2026-09-28b | 部署工具 | a-prod-status-upgrade |
| 2026-09-28a | 自訂模組/單據 | a-cr-network-errors |
| 2026-09-28a | 系統設定/模組建構器 | b-builder-dnd-5／a-builder-sink-guard |
| 2026-09-28a | 我的工作/請款 | b-payreq |
| 2026-09-27b | 系統設定 | h-branding |

- `2026-09-28a` 被 5 包使用 ⇒ 列車依上車順序重排字母（a、b、c…）。
- **「部署工具」有 3 筆未出貨條目** ⇒ VR3 要求併成一筆，內容合併三包的說明。
- `2026-09-27b` 只剩 h-branding 使用（建構器那筆已由 dnd-5 改成 28a）。只上 a-builder-output 的話，才會與 branding 撞號。
- ⚠ `backend/tests/_prod_baseline.py` 的 `BASELINE` 仍是 2220aedb，而正式機已升到 c006a2a0（2026-09-27）。VR3 判定「未出貨」的範圍因此偏寬（把已出貨的 9/25～9/27 條目也當成未出貨）。**建議本班一併把 BASELINE 更新為 c006a2a0**，並核對那些條目的內容沒有被改（已出貨不可改的守門）。

**模組版號（module.json；兩包都從同一個起點升號）**：

| 模組 | origin | b-payreq | h-branding |
|---|---|---|---|
| analytics | 1.0.8 | 1.0.9 | 1.0.9 |
| arap | 1.0.7 | 1.0.8 | 1.0.8 |
| case | 1.0.10 | 1.0.12 | 1.0.11 |

⇒ 第二個上車的（依 §2 是 b-payreq）要改成下一號，並同步該模組的 CHANGELOG（§G5 #4）。h-branding 另外升 accounting、crm、daily_tasks、netplan、payroll、subcontract、supply、tender_radar，這幾個沒有撞號。

## 4. 每包的待辦（上車前）

| 乘客 | 待 D 稽核／複核 | 待使用者裁示 | 其他 |
|---|---|---|---|
| h-branding | D 必修 0（fc5c47f4、4aa2c29c），已完成 | — | 建議項：掃描加 .vbs／.pyw（D 23:59） |
| b-payreq | **AB-M1 修正的複核**（A 或 D）；D 本身尚未稽核 | **AB-S2**（待付款清單的案件資訊給 finance 看不看） | S1／S3／S5 修正中（主持 01:40 派 B） |
| a-prod-status-upgrade | 待 D | — | — |
| h-apply-platform | **D 單獨完整稽核**（正式機使用的前提，CORE-SPEC §9b） | **AH-S7**（停服後失敗時要不要改走自動回滾） | 四條路演練已通過；A 稽核 AH-M1～M3 已關閉（A37 7fcbea8a，**未合回**） |
| a-build-python-2 | **BP-M1 複核**（D） | — | BP-M1 在 `mustfix_open.json` 登記為未關；D 關閉時要在同一班移除那一筆 |
| 建構器鏈 | be26ee3a／f84fb2df：D 必修 0；dnd-5：A 必修 0（AUDIT-A-B42-B43）；sink-guard：待 D | — | AB42-C1 撞號由列車處理（§3） |
| a-cr-network-errors | 待 D | — | 突變 N1～N3（db9aeb51）重跑結果：主持 |
| a-jv36-escape-404 | 可免（只收緊斷言、補題；突變 2/2 紅） | — | — |
| a-drill-d7extra | 待 D 複核（單元 51／突變 5/5／實跑兩份包通過） | — | 合回時寫 IMPROVEMENT-REPORT §6 #1 關閉 |
| b-rc-scope | **無稽核紀錄**（RUN-PLAN 查無）⇒ 待 D 或 A | — | — |
| a-mustfix-scan | 13 行標準關閉紀錄，**請 D 覆核**（是 A 寫進 D 的稽核檔） | — | 見下方 |

**a-mustfix-scan 與其他稽核檔的連動（上車前一定要處理）**：

- 目前 origin 只有 BP-M1 未關，與登記表一致。
- 下列尚未合回的稽核檔一旦與它同班，守門就會算進去：
  - `wip/a-audit-h12`（A37）：AH-M1～M3 已有標準關閉 ⇒ 不影響
  - `wip/a-audit-b41`（A39）：**AB-M1 未關** ⇒ 同班時要登記 `AB-M1 {audit: AUDIT-A-B41-payreq.md, owner: B, fix: wip/b-payreq…, state}`；或者等 AB-M1 修好並寫完關閉之後再上
  - D 若在這一班關閉 BP-M1 ⇒ 同一個 commit 要移除登記表裡的 BP-M1，否則「登記過期」會紅
- 稽核分支（A37、A39、B 系列）不在本班候選名單內。建議本班一併帶上，或明確排到下一班。帶上的話，順序要排在 a-mustfix-scan 之前。
