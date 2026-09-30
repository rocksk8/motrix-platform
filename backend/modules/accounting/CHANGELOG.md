# 會計 更新紀錄

## 1.1.13 — 2026-09-30（wip/host-ledger-chrome：總帳頁面外框）
- 修正：`ledger-hub／periods／reports／settings／statements.html` 補載 `notif.js`＋`sidebar.js`（第二十五班上線後使用者回報沒有頂列／logo／模組選單）；無權限改顯示平台共用「你沒有這個頁面的權限」。守門 `tests/test_page_shell_scripts_2026_09_30.py`。

## 1.1.12 — 2026-09-30（暫用號，列車取號；wip/w2-attach-p2：附件目錄 P2）
- 新增 `attachments_catalog.py::_AccountingCatalog`（`attachments.catalog`／`accounting`，IP-105）：傳票附件開檔；權限＝cashier／finance（同傳票各端點），附件必須屬於該傳票且未刪。

## 1.1.11 — 2026-09-30（暫用號，列車取號；W4 總帳 功能旗標 ready）
- 總帳功能清單新增 `ready`：這一版尚未出貨的功能（固定資產、發票折讓／作廢、自訂模組入帳、補登多年、存貨明細、來源憑證補登）顯示『開發中』、按鈕停用、`PUT /api/ledger/features/{key}` 開啟回 409（關閉永遠允許）；已出貨的功能（分錄草稿、營業稅 401、扣繳清單）照常。新批次完成時把鍵加進 `features.READY`。

## 1.1.10 — 2026-09-30（暫用號，列車取號；W4 總帳 扣繳補齊）
- 扣繳清單補上獎金發放：native 事件帶每人代扣稅款／補充保費，作廢或變更時未繳庫的列跟著移除。

## 1.1.9 — 2026-09-30（暫用號，列車取號；W4 總帳 C5c 扣繳清單）
- 扣繳清單（功能旗標 `withholding`，預設關）：引擎為勞報單應付（E06）產生草稿時，把代扣所得稅／二代健保補充保費記入 `gl_withholding_items`（冪等；來源消失、內容變動、草稿被作廢 ⇒ 未繳庫的列跟著移除／更新，已繳庫的保留）；`GET /api/ledger/withholding`（依月份彙總、期限：所得稅次月 10 日、補充保費次月底、逾期旗標、與 2252 貸方發生額對帳）、`POST …/withholding/remit`／`unremit`（登記／取消繳庫日與傳票單號，寫稽核）。獎金代扣尚未進清單（對帳會顯示差額，不掩蓋）。

## 1.1.8 — 2026-09-30（暫用號，列車取號；W4 總帳 C5a 營業稅 401）
- 營業稅 401（功能旗標 `tax401`，預設關）：`GET /api/ledger/tax401`（依雙月期間由已過帳分錄的稅碼＋科目類別彙總銷項／進項、稅額計算 101/107/108/110/111/112、對帳：銷進項稅額 vs 稅額科目、與應收應付發票逐項對比、估計稅額與免稅銷售警示）、`GET …/tax401/export`（Excel 工作底稿，抬頭經公司資料第二道）、`POST …/tax401/settlement`（期末稅額結轉草稿 E14：借銷項／貸進項，應實繳貸應付營業稅，留抵借貸留抵稅額；對帳不平不可產生，已過帳不可重做，寫稽核）。欄位對照 `gl_tax401_map` 預設種子（二手轉載，申報前以官方格式核對）。進貨批次有發票號碼時存貨分錄帶稅碼 IN-5；補登稅額拆分的成本行一併帶稅碼。

## 1.1.7 — 2026-09-30（暫用號，列車取號；W4 總帳 C4b）
- 分錄引擎 C4b：來源憑證補登 `input_tax` 適用於『來源金額未拆稅』的事件（案件額外支出 E11、叫料 E12）：成本拆成『全額－稅額』＋進項稅額，應付不變；補登值不合理（0、不小於成本）⇒ 忽略並標記。接入 case 提供者（E11／E11b／E12／E12b）。

## 1.1.6 — 2026-09-30（暫用號，列車取號；W4 總帳 列車修補）
- 修補：`ledger_periods`／`ledger_closing` 的 `_run` 不再用非字面值 `**kw`（案件摘要用途守門）；期初餘額試算端點登記為純試算（不寫稽核）；事件庫存出庫金額欄在被擋事件重試成功後一併更新。

## 1.1.5 — 2026-09-30（暫用號，列車取號；W4 總帳 C4 存貨）
- 存貨帳（C4）：`ledger/inventory.py` 移動加權平均（金額守恆、出清取整筆、退回以原金額回沖、進貨成本被改另記 adjust；`gl_inv_moves` 只增不改）；事件契約加 `mode=stock`（來源只回料號／件數／案件／日期，金額由引擎算），引擎新狀態 `blocked_inventory`（在庫不足，明說原因）；同一天進貨先於出庫；出庫事件消失／數量變動／草稿被作廢 ⇒ 存貨鏈以原金額回沖。另修：先前被擋（blocked_*）的事件重試成功後，事件列的金額欄一併更新。

## 1.1.4 — 2026-09-30（暫用號，列車取號；W4 總帳 C4）
- 分錄引擎 C4：來源憑證補登（`gl_source_annotations`）新增 `invoice_date`（覆寫 E04／進貨發票 E08b 的入帳日），`input_tax` 同時適用進貨發票 E08b，進貨付款 E09 跟著 E08b 的補登調整應付與銀行金額；接入 supply 提供者（E08／E08b／E09）。

## 1.1.3 — 2026-09-30（暫用號，列車取號；W4 總帳 C3b）
- 分錄引擎 C3b：事件契約加 `mode=native`（來源模組已自行開立傳票：事件只登記 `native_voucher_id`，引擎不重複產生、不改動；狀態 `native`；作廢或改指向新傳票 ⇒ 舊列 superseded、新列 native）；提供者 `voucher.status` 回傳多帶 `date`（傳票日期，additive）；總帳作業『分錄草稿』頁籤顯示『既有傳票』、不可被整批勾選。

## 1.1.3 — 2026-09-30（暫用號，列車取號；wip/w1-file-preview 共用檔案預覽 P1）
- 傳票頁附件預覽窗抽成 L1 共用元件 `static/file-preview.js`（`MotrixFilePreview`）：規則不變（副檔名＋mime 雙重符合才內嵌 image／pdf、blob 指定 type、關閉 revoke、競態丟棄、鍵盤與焦點規則），`data-testid` 沿用舊名。

## 1.1.2 — 2026-09-30（暫用號，列車取號；W4 總帳 列車修補）
- 修補：四大表匯出經公司資料第二道；傳票提供者／佇列登記改自 voucher_providers.py；`general-ledger` 查詢參數 `key` 改 `dimension_value`；設定更新寫稽核；`_run` 不再用非字面值 `**kw`；期初餘額試算端點登記為純試算。純修補，無 migration。

## 1.1.1 — 2026-09-30（暫用號，列車取號；W4 總帳 C2）
- 分錄引擎 C2：事件收集可套用會計在 `gl_source_annotations` 補登的來源憑證資料（目前認得 field=input_tax，覆寫承攬商發票的估算進項稅額；補登值壞掉則忽略並在事件 meta 標記）；`GET /api/ledger/events/preview` 與引擎共用；接入 subcontract 提供者（E04／E05／E05b）。

## 1.1.0 — 2026-09-30（暫用號，列車取號；W4 總帳「底層一次到位」＋A／B1／B2 ，wip/w4-gl）
- 新增總帳基礎（設計：docs/platform/plans 之 proposal-general-ledger）：會計年度／期間（可建到任意過去年度，補登用）、結帳／重開／鎖定、期間稽核軌跡（只增不改不刪）、期初餘額匯入（批次＋期初傳票草稿，過帳前可撤銷）、科目屬性（類別、正常餘額、可過帳、報表列、現金流量分類）與科目角色、帳簿報表（試算表、總分類帳、明細分類帳、序時帳簿）、財務報表（資產負債表、綜合損益表；權益變動表、現金流量表隨後）、報表設定頁、總帳作業頁（功能旗標，預設全關）。
- **行為變化（請寫進使用者說明）**：①已結帳／鎖定期間**不可過帳**、**不可作廢已過帳傳票**（要更正請開沖轉傳票，或由具權限者先「重開期間」並填理由）；之前已過帳傳票可隨時作廢重開。②已過帳傳票的日期與分錄在資料庫層也不可修改。未建立任何期間資料的部署，行為與舊版相同（沒有期間＝全部開放）。
- 自有 migration v1（modules/accounting/migrations/0001_ledger_base.py，**上線後凍結**）：一次涵蓋後續各批會用到的 31 張表（gl_*、fa_*）、`voucher_lines`（case_no／party_key／tax_code／doc_no）與 `vouchers_all`（kind／reverses_no／is_backfill／origin／gl_event_id）新欄位、15 個觸發器；全部只新增、冪等。之後若欄位不夠一律新增下一支 migration，不改 0001。
- 提供者 `voucher.draft`（IP-2）加**可選**參數 `origin`（契約仍是版本 1，舊呼叫端不受影響）；新增 `gl.events` 契約 v1 的收集與驗證（`ledger/contract.py`、`GET /api/ledger/events/preview`，目前無來源提供者，回應明說「未安裝／尚未接入」，不產生傳票）。
- 年度結轉與決算（B5）：產生兩張結轉傳票草稿（損益結轉入 3353、3353 轉 3351；kind=closing，日期＝年度末日，走一般簽核過帳）；決算要「1～11 期已結帳＋結轉傳票已過帳＋損益科目歸零＋四大表對帳全過」才成立，並寫入凍結快照；年度重開（最高管理者＋理由）把期間、結轉傳票復原並留稽核軌跡；四大表 Excel 匯出（決算後匯出凍結版）。財務報表新增權益變動表、現金流量表（間接法）。
- `api/vouchers.py` 純搬移拆檔（voucher_common／voucher_summary／voucher_providers；行為不變，名稱重新匯入）。
- 權限：讀＝cashier／finance；結帳、重開、期初、科目設定＝finance；鎖定／解鎖、功能旗標＝superadmin（未新增權限鍵）。
## 1.0.11 — 2026-09-30（暫用號，列車取號；wip/w2-voucher-office）
- 傳票附件開放 Word／Excel（使用者裁示）：docx／xlsx／doc／xls 也可上傳（jpg／png／pdf 保留；exe 等其他格式仍拒）；放行只限傳票附件（L1 `helpers/uploads.py::_EXTRA_EXTS_BY_SUBFOLDER`，函式簽章不動），單檔 20MB 上限沿用；三個上傳入口（主頁面、預覽窗、來源清單為空）的檔案選擇器與提示同步。
- 匯出「含附件」PDF：Word／Excel 不併入，只在最後一頁列檔名（既有「未能併入」規則）；附件標籤改「不會併入 PDF（只列檔名）」。下載一律 `attachment` 且檔名正確（含中文）。

## 1.0.10 — 2026-09-30（暫用號，列車取號；wip/w2-report-cash）
- T100 收款傳票：客戶內扣手續費時「借 銀行(入帳＝含稅−手續費)＋借 收款手續費支出／貸 銷貨收入＋銷項稅額」，借貸相等；沒有手續費時與舊版完全相同。設定新增選填 `receiptFeeAccount`（收款手續費支出科目，出納頁 T100 設定可填；沒填時匯出檔頭提示）。
## 1.0.9 — 2026-09-30（暫用號，列車取號；W1 wip/w1-remit-fee）
- 稽核補修：T100 承攬商付款傳票排除「差額待審核」（核可後才進、退回則整筆消失），對齊 accounting_export 註解
- W1 出納匯款手續費（暫用號，列車取號）：T100 承攬商付款傳票：承攬商費用＝實付金額（舊資料＝應付）、手續費另借「匯款手續費支出」（設定 `remitFeeAccount`，選填；沒填 ⇒ 匯出檔頁尾列出缺科目）、銀行存款貸方＝實付＋手續費（借貸相等）
## 1.0.8 — 2026-09-30（暫用號，列車取號；wip/w2-voucher-dash-2，W2 交叉稽核 S2／S4）
- S4：`POST /api/vouchers/{id}/attachments`（上傳與帶入兩種形態）只允許草稿（`can_edit`），與刪除同一條規則；離開草稿的傳票回 400（原本除作廢外不看狀態，加了也刪不掉）。作廢重開（JV24）走內部複製，不受影響。
- S2：`bringIn` 新傳票自動存檔期間 `uploading` 保持鎖定；存檔中（busy）不插入。連點不再出現「傳票尚未儲存」假錯誤、也不會重複帶入。

## 1.0.7 — 2026-09-30（暫用號，列車取號；W2 wip/w2-voucher-dash）
- 傳票「帶入附件」：新傳票尚未存檔（沒有 id）時，`bringIn` 以前靜默 return ⇒ 按了沒反應；改為自動先存成草稿（存檔失敗才在附件區顯示原因），再帶入。後端契約不動（附件掛傳票 id）
- 傳票預覽窗（草稿）新增「從電腦上傳檔案」入口；分錄下方來源清單為空時，同處提示可直接上傳。離開草稿後來源區塊與上傳入口本來就不出現（設計，非缺陷）

## 1.0.6 — 2026-09-29（暫用號，列車取號；wip/payslip-void-signed）
- 新增提供者 `voucher.by_no`（IP-4 追加）：以傳票單號查 `{id, voucher_no, status, voided}`，不存在 ⇒ None；唯讀。勞報單出納付款回填傳票單號時驗證用（M07 不直接讀 `vouchers_all`）。

## 1.0.5 — 2026-09-28（暫用號，列車取號；E4 wip/e-company-gate-impl 第三段）
- 本公司資料設定閘門第二道（COMPANY-SETUP-GATE §5；D CG5-M1）：傳票 PDF 的公司抬頭改走 L1 `company_identity.company_name()`（主要據點與別名都認，且先過第二道：未設定／判定失敗 ⇒ 428，不產生）；原本只讀 `company_profile["name"]`

## 1.0.4 — 2026-09-27 23:02（暫用號；H10 品牌設定，主持派工）
- 頁面的分頁圖示（favicon）改讀 `/api/system/branding/favicon`（L1 品牌設定，可在公司資料設定更換；沒上傳回預設圖）：`voucher.html`、`account-items.html`

## 1.0.3 — 2026-09-27（第十三班列車取號；c-approval-l1-4，稽核 D QJ-M1）
- 待簽佇列提供者 `_queue_items`：傳票的簽核 JSON 改經 L1 `approval_raw_of` 逐筆解析（原本 `tier_fields` 直接吞 `approval_json`，壞的一筆解不出來就當成空字典 {}⇒ 列給每個 superadmin、角標多計 1，核准時才丟例外）；解析不了 ⇒ 跳過那一筆＋ERROR（寫單號不寫內容）

## 1.0.2 — 2026-09-26（A，wip/a-m06-5：主持裁示對齊 AT6-O1；列車取號）
- 傳票摘要的「案件」清單改帶 IP-96 用途 `purpose="voucher_link"`：有傳票權限（cashier／finance）列全部案件、只拿摘要欄位（權限判斷在 L1）；範圍與現行相同（JV7）
- 撤回 1.0.1 的範圍註明（回應 notes 與畫面）；M01 不在時的「案件模組未安裝」說明保留

## 1.0.1 — 2026-09-26（A，wip/a-m06-4：稽核 D M06-M1／M2／S1／S2＋a' 到期；列車取號）
- 傳票摘要的承攬商派工改走 IP-15 成本檢視 `dispatch.cost_for_case`（B 的 b-ip15-cost）：不再讀 M04 的派工表；外包人員改列「外包人員 N 人」（主持裁示）；讀不到成本（403）⇒ 明說
- 案件的傳票（by-case）派工那一段的 id 也來自成本檢視
- ~~傳票摘要的「案件」清單改走 M01 的 IP-96 `case.summary`（到期守門觸發）：只列看得到的案件，回應 notes 與畫面都註明範圍~~ 〔更正（1.0.2）：縮小範圍違反 AT6-O1 裁示（JV7 照現行：有傳票權限列全部案件）⇒ 改帶用途 voucher_link，範圍註明撤回〕
- 到期守門：a' 與 a 的 quotations 到期刪除，剩 case_extra_expenses（等 case.extra_expenses）
- 題：拿掉本模組時多紅的 5 題逐題處理（搬進本模組或改驗 M06 不在時的行為）

## 1.0.0 — 2026-09-26（A，M06 搬遷；未發版，搬遷各步驟併在這一段；列車取號）
- 模組化：自 `routers/{vouchers,accounting_export,account_items}.py` 搬入 `api/`、`helpers/{voucher,voucher_pdf,voucher_template,voucher_attachments}.py` 搬入模組根（PLAYBOOK §B；M06-PLAN）
- 提供者改由 `ModuleSpec.providers` 宣告：IP-2 `voucher.draft`／`voucher.account_check`、IP-3 `accounting.settings`、IP-4 `voucher.void_draft`／`voucher.status`、IP-22（暫定號）`voucher.by_case`
- 選單（傳票、會計科目）自 L1 `core/menu_l1.json` 移進 `module.json` 的 pages[].menu（模組不在 ⇒ 側欄不出現）
- 規格：JV1～JV36 在本模組 `SPEC.md`（主持裁示 M06-e）
- 附件來源（IP-21，a-attachments-4～6 帶入）：依原單據自己的讀取規則；因權限沒列出只說類別＋個數；整個案件看不到照「不存在」回
- `vouchers` 是 VIEW：module.json 另列 `views`（不備份、不分類）
