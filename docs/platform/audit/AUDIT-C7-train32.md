# 第 32 包稽核（c7）— 包 745f3c2d（packages\20261002_185250_745f3c2d_full）

稽核員 c7；作者 d7／2e／a3（subcontract 0004 與派發完工補號為 c7 自己所寫，**當成別人寫的來測**，並另請 2e 審過）。基準 prod/a5dea50c。
方法：讀碼＋獨立探針（單檔單程序、無 `-n`、headless、暫存用完即刪）；不重跑作者測試。探針在 `docs/platform/audit/train32-probes/`，不隨產品出貨。
執行位置：worktree `wt-t32pkg`（detached 745f3c2d）；mutation 驅動 `mut.py`。

## 判定：**1 項必修（must-fix）**、2 項建議（should-fix）、數項觀察。其餘 PASS。

### 必修
**M-1　差額審核項目（`/api/cashier/remit-reviews`）丟了 `fee`、`paidAt` 兩個鍵（本包引入的退化）。**
`modules/case/material_payment_cashier.py:100`：`"diff": max(0.0, MP.r2(...)),          # 只有多付才有差額；手續費偏高的覆核是 0 "fee": float(r["fee"] or 0), "paidAt": (r["paid_at"] or "")[:10],`
——註解被接在同一行，把後面的 `"fee"`、`"paidAt"` 兩個鍵一起註解掉（`git diff a5dea50c..745f3c2d` 的 `+` 行可見；第 31 班該行是 `"diff": …, "fee": …, "paidAt": …`；來自 commit 36e8aea1）。
後果：出納頁「差額審核」表（`cashier.html:632-633`）的「手續費」「付款日」兩欄**一律空白**；本包新增的「手續費>500 進差額審核」審核人看得到原因文字（「手續費偏高（超過 500）」）卻**看不到手續費是多少**；第 31 班已有的「多付」審核也同樣少了這兩欄。核可／退回仍可運作（鍵是 `source`／`key`），所以沒有測試抓到。
實測：付 2000、手續費 600 ⇒ 項目鍵 `fee=None`、`paidAt=None`（探針 `test_fee_review_item_shows_what_the_approver_needs`、`test_overpay_review_item_also_keeps_fee_and_paidat` 紅）。
修法：把註解移到獨立一行（兩個鍵放回字典）；補一題斷言項目含 `fee`／`paidAt`（探針兩題可直接收編）。全包只有這一行有「註解吃掉後面程式碼」的形狀（掃描新增行 `#…"key":`）。

### 建議修（should-fix）
**S-1　舊單修改記號 `legacyModified.count` 有讀—改—寫競態。** 兩個同時的舊單實質編輯：稽核列 `vendor.dispatch.legacy_edit` 兩筆，`approval_json.legacyModified.count=1`（少算一次）。`update_dispatch` 在 `legacy_modified` 分支讀 `existing["approval_json"]` 後寫回，沒有持寫鎖（reset 分支才 `_begin_write`）。影響：只有計數／最後時間可能落後，稽核列完整；機率低（需同秒兩人改同一舊單）。建議：該分支先 `_begin_write` 再重讀 approval_json，或 count 以稽核列為準。探針 `test_c1_concurrent_legacy_edits_do_not_lose_count`（紅）。
**S-2　文案疊字「材料申請匯款申請」。** 機械把「叫料匯款申請」→「材料申請匯款申請」，全站約 29 處（含「材料申請單」等同型字串）（稽核、通知、簽核卡 `typeLabel`「材料申請匯款」尚可）。建議「材料匯款申請」或「材料申請的匯款申請」。純文字、不影響功能。

### 觀察（不要求本班修）
- O-1　離頁提示 `sidebar.js` 的 `window.motrixDirtyProbe()` 呼叫沒有 try/catch：掛鉤若丟例外，會讓**每一個**成功的寫入請求在 JS 端變成被拒（`fetch` 的 `.then` 丟錯）。目前掛鉤是 `() => !!this.moDirty`，實務上不會丟；加一層 try/catch 即可根治。另 `case-management-core.js:593`（重載伺服器值）無條件 `window.motrixIsDirty=false`，不看 `moDirty`——該路徑下材料申請未存列的離頁警告會消失（罕見）。
- O-2　`poLine=0` 被 `_dump_order`（`api/material_orders.py`）當「沒填」丟掉 ⇒ 連整張採購單（不報錯）；負數、字串、小數、1e30 皆被擋（422／`bad_link`）。無安全後果。
- O-3　簽核佇列 `tags` 沒有伺服器端正規化：提供者回 `None`／字串／含 `None` 的陣列時 API 仍回 200 並原樣送出；前端 `x-for="tg in (item.tags||[])"`＋`tg.text`，含 `null` 元素會讓卡片列表渲染丟錯。現行唯一提供者（`queue_tags`）永遠回合法形狀，屬防禦性缺口。輸出為 `x-text`（注入字串 `<img onerror>` 不執行）。
- O-4　整包存檔（`PATCH /case-record`，body 為 `caseRecord`）會把 `data_json.materialOrders` 整個丟掉（連同送來的也不存）；**在 prod/a5dea50c 同樣**（非本包引入），前端走分段存。偽造連結／狀態不會落地、不建審核列（探針 A2e、A2g 綠）。
- O-5　出納實付 1e15 仍可登錄（進「待審核」差額審核，非靜默入報表）；與第 31 班 O-5 相同，未變。
- O-6　未裁示項目（續）：31-C O-1（已付清舊單實質編輯回草稿）本包對**派發**舊單已裁示維持舊單；材料申請舊單仍回草稿（未動）。
- O-7　`version_manifest.json` 在 a5dea50c..745f3c2d 之間**沒有任何變更**（`git log` 無提交）；各模組 CHANGELOG 版號已遞增、無殘留 `(next)`。若政策是「每班在 manifest 有使用者可見條目」，請確認建包時由列車寫入（我沒看到包內容物，未驗）。

## PASS 項（獨立探針／讀碼）
**升級（真基準庫，`t32_mig_probe.py`）**：prod/a5dea50c 程式建庫（含 31-C 資料、舊派發單、卡住列、已發布 travel v1＋草稿）→ 第 32 包升級兩次。除 `module_schema_versions` 與卡住列的 `doc_code` 外，**每表逐列相同**；欄位集合不變、無新表；`contractor_dispatches` 只有 2 筆卡住列（待審核／簽核中、`doc_code=''`）的 **`doc_code` 一個欄位**變動（單號日期取送審日 `DP-20260920-0001`、無日期者取 `updated_at` 並接在同日最大號後 `DP-20261002-0002`）；未卡住的舊單（已完成／已驗收）`doc_code` 維持空；已發布 travel v1 位元不變；integrity ok、FK 0；第二次升級零變更。
（註：探針第一次跑的是舊樹 `wt-t32int`，migration 沒執行而「全相同」——已改預設路徑並以 `<backend 路徑>` 參數驗證；這是探針設定錯誤，不是包的結果。）
**A 連結**：A1 兩筆同列並發送審 ⇒ 恰一個 200、一個 400（`po_line_taken`），活連結 1 筆；撤回後該列可再用。A2 儲存路徑：不存在／草稿／已駁回／已作廢／他案／請購單 的採購單、`quoteItemId` 不在報價單、有列序無採購單、列序負數／越界／字串／小數／1e30 ⇒ 一律 `bad_link`（或 422），**不留列、不留草稿審核列**；整包／分段存檔夾帶偽造連結不落地。A4 連到有效採購單者權責與現金口徑都不重複計、總帳 E12／E12b 不入帳，採購單作廢後金額回來並帶 `noPo`；對照組（未連結者）仍入帳。A5 剩餘量手算（採購 3＋材料申請 已核准 2＋待審核 1＋舊單 4＝10；草稿／退回／取消不計）與 `purchase-items`、送審上限三處同數。A6 無財務檢視者看不到 `unitCost`／`amount`、外人 404、未登入 401／403。
**B 尚未送審**：草稿不進簽核佇列與紅點、報表、總帳、不可開匯款申請（409）；佇列 tags 只有「未申請採購單」一個 warn（已連結／$0 無標註，文字不含金額或品名）。（B3 離頁提示以讀碼為主，見 O-1。）
**C 派發**：舊單改欄位仍是舊單、不重設、marker 與稽核列在；PUT body 夾帶 `approval_json`／`approval_status`／`doc_code`／`legacyModified` 全被忽略；有匯款申請的舊單仍 409；已核准實質編輯仍回草稿、無 marker；舊單編輯後申請完工仍補號且 marker 保留；審核中取消 ⇒ 審核關閉（已退回）、紅點歸零、事後 `/approve` ⇒ 409。第 30 班探針 `test_probe_t30_dispatch_c7.py` 21 題**全綠**（F1／F2 原本的紅已修）。
**D 改字**：全站字串字面值（Python AST 排除 docstring＋前端 html／js／json 非註解行）「叫料」殘留 **0**（僅 `version_manifest` 歷史條目）；匯款申請端點回應／稽核／通知／佇列標題皆為「材料申請」。
**E d7 修正項**：E1 告知紀錄寫入失敗 ⇒ 建立回 503、無申請列（rollback 稽核 `material_payment.create_rolled_back`）；送審對無告知紀錄 409。E2 手續費：1e12／-1／>實付 ⇒ 400；**500 不進審核、500.01 起進差額審核**（邊界已測）；手續費覆核項目 `diff=0`＋原因（但見 M-1）。E3 `payee-bank`：superadmin／持 `cashier` 模組者看完整帳號；admin、admin2、**明確勾了 cashier 的 admin** 皆只見 `****7890`；一般成員／外人 403；稽核標「遮罩」與否正確、稽核不含帳號。31-C 探針 36 題：35 綠、1 紅＝實付 1e15 仍可登錄（O-5，未變）。
**F tags**：契約形狀（`base_item` 預設 `[]`、既有鍵不變）、`tone` 僅 `warn`、文字不含金額／人名、輸出 `x-text`。
**G1** 四份出貨請款類型預設與 a5dea50c 逐鍵比對：**僅 `fields[0].help` 一個字串各改一次**（4 處）。G4 模組版號遞增、無殘留 `(next)`（O-7 另述）。
**預審探針複驗**：我預審 S4c／S4d 的 5 個紅探針（切案重設、晚到回應、已付歷史不視為連結、N+1、現金口徑）在本包**全綠**（`test_probe_t32_mlink_leak_c7.py` 4 題、`test_probe_t32_s4c_cash_c7.py` 1 題；包內另有 2e 轉成綠的版本）。

## 突變（突變前工作樹乾淨、每輪還原後 `git status` 無追蹤檔變動）
| # | 突變 | 結果 |
|---|---|---|
| M1 | `po_line_taken` 檢查拿掉 | 紅（A1 並發題） |
| M2 | `MG.LINK_VALIDATOR` 不掛 | 紅（A2 儲存路徑題） |
| M3 | 草稿也算成本（`cost_state`） | 紅（作者 reports_gate 題） |
| M4 | `legacyModified` 不寫 | 紅（作者 legacy_edit 題） |
| M5 | 舊單編輯又回草稿 | 紅（作者 legacy_edit 題） |
| M6 | `queue_tags` 帶金額 | 紅（F2 題） |
| M7 | `base_item` 不補 `tags` | 紅（作者 link_keys 題） |
| M8 | 簽核佇列列入草稿 | 紅（B1 題） |
8／8 守門會紅，無「守門有洞」。（M-1 的所在行沒有守門——見必修；補題後可再加一個突變。）

## 未涵蓋
B3 離頁提示的 e2e（只讀碼）；A3 的 `has_payments` 兩路（作者測試已含真 HTTP，未重打）；A7 簽核詳情欄位的注入（`tags` 以 `x-text` 證實，詳情欄位僅讀碼）；G2 請購單明細（procurement／quotation-form）的角色矩陣、G3 帳務檔案的異動範圍；設計器 +13 行（作者自審項）；包內容物（SHA256、檔案清單）未驗；form 預設 help 文案「管理者可在設計器解除鎖定」與設計器實際權限是否一致（未驗）。

## 執行紀錄
`test_probe_t32_pkg_link_c7.py` 28 題全綠；`test_probe_t32_pkg_pay_c7.py` 11 題：9 綠、2 紅（M-1）；`test_probe_t32_pkg_dispatch_c7.py` 6 題：5 綠、1 紅（S-1）；`test_probe_t30_dispatch_c7.py` 21／21；`test_probe_t31c_material_c7.py` 35／36；預審探針 5／5；`t32_mig_probe.py` 通過；突變 8／8。
