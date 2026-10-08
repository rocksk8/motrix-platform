# 交接備忘：hichan-ab（node-ab）第 46／47 班工作（2026-10-08 寫）

> 用途：這個視窗若被 /clear 或換人接手，先讀本檔。寫於 `wip/t48-paydate-gap`（`docs/platform/plans/`）。
> 記不住的細節以 git 為準：`git -C D:\MOTRIX-PLATFORM log origin/<分支>`；下面的 head 是寫本檔時的值。

## 1. 我擁有的分支（皆已 push；除非另述，沒有未 push 的 commit）

| 分支 | head | 狀態 | 備註 |
|---|---|---|---|
| `wip/t48-r2-step2` | `92bc62853` | 完成，b5 複核過（無 must-fix） | R2 第 2 步（`users.html` 職責角色整合、舊 PUT 拒絕＋旗標 `users_put_reject_subtracted`、8a `audit_id`、唯讀報表 `--raw`、預覽 API）；差異與建議在 `plans/R2-STEP2-IMPLEMENTATION-NOTES.md`；基底 `570c54fa1`，**尚未重基到第 47 班** |
| `wip/t48-paydate-gap` | `477627648` | G1／G2／G3a 完成；提醒 e2e 為 skip 標記題 | 承攬商匯款建立視窗送 `planned_pay_date`、卡片顯示、e2e 3 題；**等第 47 班合併後重基**；提醒/站內通知 e2e 待 L1 進 platform 才寫（對照 `wip/t45-paydate-l1`） |
| `wip/t48-paydate-design` | `00e8f2453` | 設計稿（已被實作分支取代） | `plans/PAYDATE-GAP-DESIGN-T48.md` |
| `wip/t47-build-optimization` | `64377a861` | 文件＋`tools/platform/regen_all.py`（b5 的 preflight 呼叫它） | `BUILD-VERIFY-OPTIMIZATION-T47.md`、`GATE-REUSE-EQUIVALENCE-T47.md`；O5（-n 4）已核准並寫進 PLAYBOOK §C-13（在 audit-fixes 分支）；**O3／O6 尚待使用者裁示**（我的建議：不做 O6；O3 僅迭代期、需動態讀取集合追蹤＋兩週影子全量） |
| `wip/t47-audit-fixes` | `30a37e54a` | 舊分支，**不要再動**（已被 r2 取代） | |
| `wip/t47-audit-fixes-r2` | `69c62de34` | 6 commits，基底 `570c54fa1` | 稽核 S1–S5、S8、S6（有簽核層禁自核）、S9（作廢已核准需超管）、小項、政策題文件、-n 4 文件；payroll CHANGELOG 有兩個 `(next)` 在 1.2.4 之上；node-d8 已知，train 47 取號後會變成號碼 |
| `wip/t46-fix-payslip-races` | `9419a194f` | 已併入 train 46（上線） | 可刪（node-d8 決定） |
| `wip/t46-baseline-118`／`wip/t46-drill-tools` | `36aec29e1`／`6e98e237d` | 已併入 train 46 | 保留 |

## 2. 我保留的 worktree（D:\開發測試檔\）
`t48-r2s2`（wip/t48-r2-step2）、`t48-pg`（wip/t48-paydate-gap；本檔就在這）、`t48-pd`（wip/t48-paydate-design）、`t47-bo2`（wip/t47-build-optimization-wt → 推到 `wip/t47-build-optimization`）、`t47-r2`（wip/t47-audit-fixes-r2）。
用完要移除：`git -C D:\MOTRIX-PLATFORM worktree remove --force "D:\開發測試檔\<名>"`（分支保留）。**別人的 worktree（t46-int、b5-*、t47-preflight-tool）不碰。**

## 3. 還開著的 nit／待辦
- R2 step 2：`hasAccess()`（使用者清單矩陣）對空 `modules` 仍顯示樣板權限（後端無此回退）——建議第 3 步一併改；`users.html` 區塊抽離（設計 §5.2）沒做。
- L1 複核（`wip/t45-paydate-l1` @12ca427ff）的 SHOULD-FIX：`run_scan` 在 SMTP unknown／等待上限時，後面的項目連站內通知也丟了；承攬商匯款 approve/revoke/reject 的 `_PD.fire` 在 `_notify` 之後；cashier hook 沒包 try/except；兩個背景 sync 競態可能留孤兒事件（皆低風險，已回報 node-d8）。
- PO 廠商銀行複核（b5 `c5c1ca5ef`＋`5775c7f6d`）：`extra-expenses` 清單／`mine` 對非財務的需看金額者（申請人、簽核人）仍回完整帳號（我實測確認），建議改末四碼；核准後的變更申請若不帶 payee 欄位會清掉廠商銀行資料；銀行＋分行字串可能超過 60 字上限。已回報 node-d8，等決定。
- 付款日缺口：C1／C2／C3 已由 node-d8 答覆（舊清單頁＝承攬商卡片＋出納舊頁籤；不做申請人端改期；不做申請人提醒）；G4（L1 落地後驗證與提醒 e2e）未做。
- 第 47 班合併後：把 `wip/t48-paydate-gap`、`wip/t48-r2-step2` 重基到新 `origin/platform`（`wip/t47-audit-fixes-r2` 已是 r2，train 47 取號後可能要再重基）。
- 產生檔（dep_graph／test_map／UNIT-INDEX）不在分支上提交，由列車重產；分支上 `test_generated_maps` 在 MOTRIX_TRAIN=1 下會紅是預期。

## 4. 我依賴的使用者裁示（經 node-d8 轉述；我沒有直接聽到使用者）
- R2：Q1＝舊 PUT 勾到被扣的鍵→400＋旗標退場；Q2＝保留 `duty-roles.html`；Q3＝既有使用者空 modules 不預填樣板（只有新增使用者預填）。順序：R2 step 2 → 付款日缺口 → 廠商銀行付款阻擋。
- 稽核政策：Q-S6＝A（有簽核層禁送審人自核，唯一在職超管例外）、Q-S7＝B（維持現狀並記錄）、Q-S9＝A（作廢已核准需真正超管，已匯出不變）。
- 採購單廠商銀行資料：收集、A 案（每張採購單填）、只擋新單且在 A 上線後、自然人「已告知收款人」不強制（只提示）。
- 建包：非 e2e 段 `-n 4`；e2e 維持 `-n 2`、同時最多 2 組 e2e、可用記憶體 <4 GB 不開跑；整機最多 2 組全量不變（已寫入 PLAYBOOK §C-13／CORE-SPEC，但寫的是「經 node-d8 轉述」）。
- 閘門：任何新紅 ＝ 停下來回報，不繞過；不得自行把偶發題登進 `known_flakes.json`。

## 5. 學到的規則（請照做）
- **只刪自己建立的確切路徑，絕不對共用暫存用萬用字元**（我曾用 `rm -rf $TEMP/motrix-runstage-not_e2e-2026100*`，誤刪 05 正在跑的 basetemp，已揭露並由 node-d8 處理）。
- pytest basetemp 一律 `%TEMP%\pt_ab_<用途>`，用完刪那一個確切路徑；超過 5 分鐘的指令用背景 shell＋完成通知（`run_in_background`），不要前景 sleep 輪詢。
- 不在別人的 worktree／共用 `D:\MOTRIX-PLATFORM` 寫檔；改程式一律在自己的 worktree；`git -C <絕對路徑>` 取代 `cd && git`。
- 回報要誠實：沒跑的測試寫「沒跑」；聽來的使用者裁示標「經 node-d8 轉述」；推翻自己先前的說法要立刻更正（例：`require_superadmin=True, module=` 其實放行模組持有者）。
- 守門紅 → 先分辨是我造成、既有偶發、還是時序（取號前）；mutation 檢查：改測試保護的程式一行，確認測試轉紅。
- 工具：`tools/platform/regen_all.py --check`（stdout 只印過期檔路徑）、b5 的 `train_preflight.py --static-only`（推前跑；它的 A8 不追夾具鏈，測試要明列 `client`）。Windows 主控台編碼：腳本輸出中文要 `PYTHONIOENCODING=utf-8`；用 heredoc 改含反斜線的程式碼會被吃掉跳脫字元，改用「Write 工具寫腳本檔再執行」。

## 6. 待決／等待
- 等 node-d8：`/clear` 與否的決定；O3／O6 使用者裁示；PO 銀行複核處置；train 47 合併時點（之後重基我的兩個 t48 分支）。
