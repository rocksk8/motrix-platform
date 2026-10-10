# 模組框架化盤點 — 財務類：accounting／arap／payroll／analytics（第 54 班；盤點，不含實作）

> 規則來源：使用者 2026-10-10「每一個模組的功能都要像這樣處理」——每個模組都要盤點三類：①功能與規則 ②決策點／流程分支 ③頁面顯示模式。格式同 `QUOTE-CASE-DISPLAY-FRAMEWORK-SCOPE-T54.md`。
> 掃描基準：`wip/t54-n39-settings-s0s2` 當下；行號已讀原始碼核對，實作前須重新核對。**選項型「現況→」之後即預設（＝今天）。**
> 機制縮寫：SR＝設定中心（`helpers/settings_registry.py`）、M＝權限矩陣（F3）、S＝狀態／標籤框架（F5）、FP＝欄位政策（F7，僅設計）、D1＝個人／公司顯示偏好（新）、locked＝法令／會計完整性鎖定（寫明理由）。風險：none｜ops｜money｜legal｜security；工量 S≤0.5、M 1–2、L≥3 pd。
> 路徑：`A/`＝`backend/modules/accounting/`、`R/`＝`backend/modules/arap/`、`P/`＝`backend/modules/payroll/`、`N/`＝`backend/modules/analytics/`、`F/`＝`frontend/`。
> 已有機制（不重做）：`helpers.legal_params` 已版本化勞報單與獎金的扣繳／二代健保參數（`backend/helpers/legal_params.py:29-51`，頁 `F/pages/legal-params.html`）；四模組的簽核層級已走 `helpers.tiered_approval`／`unified_approval_flow`；`settings_groups.py` 目前只有 retention、uploads 兩組，四模組沒有任何 SR 欄位。

## 1. accounting（會計）

### 1a. 規則與常數
| id | 名稱 | 現況 | file:line | 選項→預設 | 風險 | 機制 | 工 |
|---|---|---|---|---|---|---|---|
| ACC-01 | 傳票狀態集合 | 草稿、待審核、簽核中、已核准、已過帳 | `A/voucher.py:36` | 僅標籤可改 | legal | S（標籤） | S |
| ACC-02 | 可編輯狀態 | 只有「草稿」可改內容與日期 | `A/voucher.py:41` | locked：已入帳不可無痕修改（商業會計法） | legal | locked | - |
| ACC-03 | 已過帳凍結 | 已過帳不可退回，只能作廢重開 | `A/voucher.py:51,367` | locked，同 ACC-02 | legal | locked | - |
| ACC-04 | 傳票單號格式 | `YYYYMMDD-NNN`，退回升版 `-Rn` | `A/voucher.py:330,295` | 建議 locked（唯一索引） | legal | locked | - |
| ACC-05 | 傳票類別 | 收、支、轉；PDF 標題三種 | `A/api/vouchers.py:185`；`A/voucher.py:175` | 類別 locked；PDF 標題文字可選 | legal | locked＋S | S |
| ACC-06 | 現金類科目根 | 沿 `parent_code` 到 `111` 判現金類 | `A/voucher.py:178` | locked（自動判類依據） | legal | locked | - |
| ACC-07 | 簽核層名稱 | 前兩層「覆核」「主管」，第三層起「第 N 層」 | `A/voucher.py:469,460` | 文字，現況→覆核／主管 | none | S | S |
| ACC-08 | 最後一層限最高管理者 | 傳票最終關卡一律 superadmin | `A/api/vouchers.py:75-82,693,799` | 開關，現況→必須最高管理者（放寬需雙人核准） | money | M | M |
| ACC-09 | 傳票模組存取 | 需 `cashier` 或 `finance` 模組，admin 不直通 | `A/api/vouchers.py:139`；`A/attachments_catalog.py:8` | 模組清單 | security | M | S |
| ACC-10 | 作廢已過帳傳票 | 僅 superadmin；系統產生的傳票不可從傳票頁作廢 | `A/api/vouchers.py:934-938,102` | 角色，現況→superadmin | money | M | S |
| ACC-11 | 傳票附件可操作狀態 | 僅指定狀態可加／移除附件 | `A/api/vouchers.py:1251,1365` | 狀態集合，現況→僅草稿 | legal | S | S |
| ACC-12 | 附件來源白名單與排除 | `SOURCE_TYPES`、`EXCLUDED_SOURCES`、`EXPENSE_LINE_SOURCES` | `A/voucher_attachments.py:54,74,364` | 多選，預設＝現況 | ops | SR（多選） | M |
| ACC-13 | 摘要來源頁籤與上限 | 案件／已上傳檔案／支出項；每來源 50 筆 | `A/api/voucher_summary.py:53,59` | 整數 50（10–200） | none | SR | S |
| ACC-14 | 摘要範本 | `SUMMARY_PLACEHOLDERS` 與解析器 | `A/voucher_template.py:37-56` | 範本字串，預設＝現況 | none | SR（字串） | M |
| ACC-15 | 總帳申請動作與雙人 | 結帳、重開、年度決算、建期初須送申請；非 superadmin 送申請 | `A/ledger/requests.py:21`；`A/api/ledger_periods.py:126,142,208` | 每動作是否雙人，現況→要 | money | M | M |
| ACC-16 | 鎖定、解鎖、撤銷期初、年度重開 | 僅 superadmin | `A/api/ledger_periods.py:40-42,157,170,224`；`A/api/ledger_closing.py:35-37` | 角色，現況→superadmin | legal | M | S |
| ACC-17 | 總帳讀寫模組門檻 | 讀＝cashier 或 finance；寫／設定／結轉＝finance | `A/api/ledger_periods.py:20-21`；`ledger_closing.py:23-31`；`ledger_settings.py:20-30`；`ledger_tax.py:22-23`；`ledger_annotations.py:21-22` | 讀寫模組集合 | security | M | S |
| ACC-18 | 報表列設定與功能旗標 | 僅最高管理者 | `A/api/ledger_settings.py:49-52`；`A/ledger/features.py:3` | 角色 | security | M | S |
| ACC-19 | 結帳檢核 | 借貸不平衡為擋；未過帳傳票、更早期未結為警告，可「接受警告」 | `A/ledger/periods.py:131-148,155` | 警告改為擋的開關，現況→警告 | legal | SR | S |
| ACC-20 | 會計年度起始月 | 讀 `fiscal_year_start_month`，預設 1 | `A/ledger/periods.py:38-43,61-67` | 已有設定值，缺設定頁 | legal | 補設定頁 | S |
| ACC-21 | 分錄引擎自動執行 | 每 3600 秒、啟動後 300 秒首跑、回看上月 1 日 | `A/ledger/auto_run.py:19-28` | 間隔、首跑延遲、回看月數 | ops | SR | S |
| ACC-22 | 總帳功能旗標與出貨集合 | 9 個功能鍵預設全關；`READY` 僅 4 項可開 | `A/ledger/features.py:9,25` | READY 屬發版控制 locked；旗標已存在 | ops | locked／現有 | - |
| ACC-23 | 401 預設欄位對照 | 欄位代號依官方檔案格式 | `A/ledger/tax401.py:27-50` | 固定欄位 locked；可由 `gl_tax401_map` 覆寫 | legal | locked＋現有 | - |
| ACC-24 | 預設發票媒介 | `default_invoice_medium` 預設電子 | `A/ledger/tax401.py:66-72` | 電子／紙本 | legal | 補設定頁 | S |
| ACC-25 | 401 申報期別 | 雙月一期共 6 期 | `A/ledger/tax401.py:105-110` | locked（營業稅法） | legal | locked | - |
| ACC-26 | 401 媒體檔參數 | 欄寬、必填序列、尾碼編碼 | `A/ledger/tax401_media.py:72-84` | locked（官方格式） | legal | locked | - |
| ACC-27 | 扣繳繳庫期限 | 所得稅次月 10 日、二代健保次月月底 | `A/ledger/withholding.py:49` | 法定日期 locked；提醒提前天數可設 | legal | locked＋SR | S |
| ACC-28 | 扣繳批次與報表上限 | 一次登記／取消 500 筆；不指定月份列 2000 筆 | `A/ledger/withholding.py:28-29` | 整數 | none | SR | S |
| ACC-29 | 預設角色對科目 | `DEFAULT_ROLES`（現金 1111、應付 2171…） | `A/ledger/roles.py:36-48` | 科目角色設定已存在，僅預設種子 | legal | 現有 | - |
| ACC-30 | 分錄草稿狀態集 | drafted、posted、native、blocked_* | `A/ledger/engine.py:325` | 內部狀態 locked；標籤可改 | ops | S（標籤） | S |
| ACC-31 | 分錄事件查詢上限 | 預設 500、最大 2000 | `A/api/ledger_engine.py:87` | 整數 | none | SR | S |
| ACC-32 | 來源憑證補登 | 欄位白名單（input_tax、invoice_date）；清單 500；來源鍵 120 字 | `A/api/ledger_annotations.py:25-35,60` | 白名單 locked（契約）；上限 SR | money | locked＋SR | S |
| ACC-33 | T100 匯出科目與傳票別 | 預設 `voucherCategory`＝「轉」 | `A/api/accounting_export.py:93-105` | 已有設定頁 | money | 現有 | - |
| ACC-34 | 自訂科目編號 | `父代號-N`，N＝最大值加 1 | `A/api/account_items.py:280-285` | locked | ops | locked | - |
| ACC-35 | 傳票 PDF 邊界與欄寬 | 42.6pt、五欄 | `A/voucher_pdf.py:88-90` | 公司列印版面 | none | D1／output_template | M |

### 1b. 決策點
| id | 名稱 | 現況 | file:line | 選項→預設 | 風險 | 機制 | 工 |
|---|---|---|---|---|---|---|---|
| ACC-D01 | 簽核鏈無設定時 | 內建兩層（覆核→主管），主管＝superadmin | `A/api/vouchers.py:808`；`A/voucher.py:469` | 內建兩層／單層 | money | M＋簽核流程 | M |
| ACC-D02 | 同人連按多次簽核 | 允許同一人連簽三格 | `A/api/vouchers.py:736` | 開關，現況→允許 | money | M（自簽規則） | S |
| ACC-D03 | 退回流程 | 清簽核、升版 `-Rn`、同張重走 | `A/api/vouchers.py:826-900`；`A/voucher.py:273` | locked | legal | locked | - |
| ACC-D04 | 通知失敗處理 | 通知為附帶，失敗只記 log | `A/api/vouchers.py:114` | locked | ops | locked | - |
| ACC-D05 | 分錄引擎衝突分支 | 結帳期、無科目、存貨分別 blocked_* | `A/ledger/engine.py:325` | locked | legal | locked | - |

### 1c. 頁面顯示
| id | 名稱 | 現況 | file:line | 選項→預設 | 風險 | 機制 | 工 |
|---|---|---|---|---|---|---|---|
| ACC-V01 | 傳票清單排序與分頁 | `ORDER BY id DESC`，不分頁，預設不含作廢 | `A/api/vouchers.py:286-305`；`F/js/voucher.js:1294-1307` | 預設排序、含作廢、頁大小 | none | D1 | M |
| ACC-V02 | 傳票篩選條件 | 關鍵字、日期區間、狀態 | `F/js/voucher.js:1294-1307`；`F/pages/voucher.html:226-235` | 預設條件記憶 | none | D1 | S |
| ACC-V03 | 新增預設日期 | 當天 | `F/js/voucher.js:146,951` | 當天／上次輸入 | none | D1 | S |
| ACC-V04 | 金額顯示 | `Math.round().toLocaleString()` 無小數 | `F/js/voucher.js:1317` | 千分位、小數位 | none | D1（公司，D2） | S |
| ACC-V05 | 附件大小單位 | <1MB 顯示 KB | `F/js/voucher.js:760-761` | locked | none | locked | - |
| ACC-V06 | 狀態徽章色 | `.vc-status` 灰底；錯誤紅、成功綠 | `F/pages/voucher.html:27,59-60` | 色票 | none | S | S |
| ACC-V07 | 總帳作業預設頁籤 | 只顯示已開旗標的頁籤 | `F/js/ledger-hub.js:11`；`A/ledger/features.py:9` | 預設頁籤 | none | D1 | S |
| ACC-V08 | 401 預設期別與分錄預設區間 | 今年／當期；草稿區間＝今年 1/1 到當月底 | `F/js/ledger-hub.js:18,27-30` | 預設區間 | none | D1 | S |
| ACC-V09 | 財務報表預設值 | `tab=bs`；比較期＝去年；`drafts=false`、`showZero=false` | `F/js/ledger-statements.js:13-23` | 預設比較期、含草稿、顯示零 | none | D1 | S |
| ACC-V10 | 帳簿報表預設值 | `tab=tb`，區間＝當月；`dimension=party_key` | `F/js/ledger-reports.js:5-14` | 預設頁籤、區間、維度 | none | D1 | S |
| ACC-V11 | 期間作業日誌列數 | 最近 50 筆 | `F/js/ledger-periods.js:77` | 整數 | none | D1 | S |
| ACC-V12 | 科目設定列上限 | 300 列＋「只看有問題」 | `F/js/ledger-settings.js:62-71` | 整數 | none | D1 | S |
| ACC-V13 | 現金流量活動標籤 | 現金及約當、營業、投資、籌資 | `F/js/ledger-settings.js:58`；`A/ledger/cashflow.py:18` | 標籤 | none | S | S |
| ACC-V14 | 科目來源標籤 | 法定、系統預設、自訂 | `F/js/account-items.js:37-42`；`A/api/account_items.py:44-49` | locked | none | locked | - |
| ACC-V15 | 申請狀態標籤 | 待簽核、已執行（已核准）、已退回、已撤回 | `A/ledger/requests.py:20` | 標籤 | none | S | S |

> 備註：ACC-01～06 另有契約測試釘死，改動前先跑 `backend/modules/accounting/tests`。

## 2. arap（應收應付、出納）

### 2a. 規則與常數
| id | 名稱 | 現況 | file:line | 選項→預設 | 風險 | 機制 | 工 |
|---|---|---|---|---|---|---|---|
| ARP-01 | 款項類別 | 全額、訂金款、交貨款、驗收款、尾款 | `R/api/payment_requests.py:99-105` | 清單可增減，預設＝現況 | none | S | S |
| ARP-02 | 請款比例範圍 | 0＜比例，超過 400 | `R/api/payment_requests.py:261-262` | locked（邏輯邊界） | money | locked | - |
| ARP-03 | 請款單／開票憑證單號 | `next_entity_code(..., "PR")`；憑證另編號 | `R/api/payment_requests.py:438`；`backend/db.py:5834` | 前綴可選，位數固定（歸 F5 編號框架） | ops | F5 | M |
| ARP-04 | 請款額度鎖定 | 草稿也佔額度，超過剩餘 409 | `R/api/payment_requests.py:423`；`R/api/invoice_vouchers.py:427` | 開關，草稿是否佔額度，現況→佔 | money | SR | S |
| ARP-05 | 財務動作角色 | 建立、送審、刪除、撤銷核准僅財務與 superadmin | `R/api/payment_requests.py:141-144`；`invoice_vouchers.py:143-146` | 角色集合 | security | M | S |
| ARP-06 | 請款／開票可檢視模組 | `case_manage`、`finance`、`cashier`、`quotation` 任一；金額另需財務可視 | `R/api/payment_requests.py:74,80`；`invoice_vouchers.py:69,98-104` | 模組集合 | security | M | S |
| ARP-07 | 僅草稿可改／刪／送審 | 否則 409 | `R/api/payment_requests.py:479,565,592`；`invoice_vouchers.py:472,499` | locked（流程完整性） | money | locked | - |
| ARP-08 | 已匯出不可撤銷核准 | 匯出後撤銷 409 | `R/api/payment_requests.py:765`；`invoice_vouchers.py:673` | 開關，現況→禁止 | money | SR | S |
| ARP-09 | 無簽核鏈時核准 | 僅 superadmin 且不可自簽 | `R/api/payment_requests.py:696-711`；`invoice_vouchers.py:604-619` | 角色與自簽開關 | money | M | S |
| ARP-10 | 退回必填原因 | `require_reject_reason` | `R/api/payment_requests.py:766,814` | 開關，現況→必填 | none | SR | S |
| ARP-11 | 請款清單上限 | 最近 200 筆 | `R/api/payment_requests.py:328`；`invoice_vouchers.py:258` | 整數 | none | SR／D1 | S |
| ARP-12 | 營業稅率與捨入 | `LEGAL_TAX_RATE` 5%、`round_half_up` | `backend/helpers/tax_calc.py:52-63`；`R/receivables.py:110` | locked | legal | locked | - |
| ARP-13 | 稅別代碼 | OUT-5／OUT-0／OUT-EX／OUT-LEGACY | `R/gl_events.py:47` | locked | legal | locked | - |
| ARP-14 | 入帳案件狀態 | 僅「已成案、已結案」收款入帳 | `R/gl_events.py:19`；`R/receivables.py:229` | 狀態集合 | money | S | S |
| ARP-15 | 收款手續費類別 | 歸「收款手續費」 | `R/receivables.py:216` | 文字 | none | S | S |
| ARP-16 | 付款日必填 | 必填 `paidDate`（不預設今天） | `R/api/cashier.py:201-207` | 必填／預設今天 | money | SR | S |
| ARP-17 | 付款權限 | 登錄付款、改預定付款日、差額審核：財務或 superadmin | `R/api/cashier.py:55,88,259,357` | 角色集合 | money | M | S |
| ARP-18 | 收款人完整帳號 | 財務與 superadmin 可看；先寫稽核才回值 | `R/api/cashier.py:118,141-147` | locked | security | locked | - |
| ARP-19 | 勞報單、獎金在出納頁可見度 | 勞報單金額限財務；獎金標記已付款限 superadmin 或 cashier | `R/api/cashier.py:524,563` | 角色集合 | money | M | S |
| ARP-20 | 銀行對帳 CSV | 上限 5MB；編碼依序 utf-8-sig、utf-8、cp950、big5；欄位別名；金額完全相等才配對 | `R/api/cashier.py:845,770-773,795-802,878` | 檔案上限、別名清單 | ops | SR | M |
| ARP-21 | 逾期判定 | 預計收款日早於今天且未收即逾期，無寬限 | `R/api/cashier.py:475` | 寬限天數，預設 0 | ops | SR | S |
| ARP-22 | 執行歷史預設區間 | 當月 | `R/api/cashier.py:607-612` | 預設區間 | none | D1 | S |
| ARP-23 | 待收款狀態值 | unreceived／received／all | `R/api/cashier.py:509` | locked | none | locked | - |
| ARP-24 | 差額審核退回 | 須填原因；實付與手續費清空 | `R/api/cashier.py:380-394` | locked | money | locked | - |
| ARP-25 | 預定付款日變更通知 | 通知申請人，不含金額，本人改不通知 | `R/api/cashier.py:327` | 開關，現況→通知 | none | SR | S |

### 2b. 決策點
| id | 名稱 | 現況 | file:line | 選項→預設 | 風險 | 機制 | 工 |
|---|---|---|---|---|---|---|---|
| ARP-D01 | 缺模組降級 | 缺席模組以明文訊息顯示，不回空清單 | `R/api/cashier.py:61-83,353,520` | locked | ops | locked | - |
| ARP-D02 | 發票金額優先序 | 有發票未稅與稅額以發票為準，否則按報價拆稅 | `R/receivables.py:105-117` | locked | money | locked | - |
| ARP-D03 | 開票不要求先收款 | 使用者明確要求放寬 | `R/api/invoice_vouchers.py:5` | 開關，現況→不要求 | money | SR | S |

### 2c. 頁面顯示
| id | 名稱 | 現況 | file:line | 選項→預設 | 風險 | 機制 | 工 |
|---|---|---|---|---|---|---|---|
| ARP-V01 | 出納子頁籤與順序 | 待付款、待收款、獎金、勞報單、待付款申請、差額審核、執行歷史、銀行對帳、T100 | `F/pages/cashier.html:313-340` | 預設頁籤、隱藏頁籤 | none | D1 | S |
| ARP-V02 | 待收款篩選頁籤 | 全部、未收款、已收款、未開發票；預設 all | `F/pages/cashier.html:585-588`；`F/js/cashier.js:53,178-182` | 預設篩選 | none | D1 | S |
| ARP-V03 | 預定付款日提示 | 已過＝overdue、3 天內＝soon | `F/js/cashier.js:355-361` | 提前天數 3（1–14） | ops | SR | S |
| ARP-V04 | 前端到期判定 | `dateStr < 今天` | `F/js/cashier.js:196-198` | 同 ARP-21（共用單一來源） | none | SR | S |
| ARP-V05 | 未開發票列底色、合計列色 | `#FFFBEB`、`#111827` | `F/pages/cashier.html:101,64` | 色票 | none | S | S |
| ARP-V06 | 金額格式 | `NT$ ` 前綴＋toLocaleString | `F/js/cashier.js:136` | 公司顯示格式（D2） | none | D1 | S |
| ARP-V07 | 應收帳款頁 | `receivables.html` 僅轉址 | `F/pages/receivables.html:9` | 退場候選 | none | — | - |

## 3. payroll（勞報單、獎金分潤）

### 3a. 規則與常數
| id | 名稱 | 現況 | file:line | 選項→預設 | 風險 | 機制 | 工 |
|---|---|---|---|---|---|---|---|
| PAY-01 | 勞報單單號 | `PS-YYYYMM-NNN` 按月序號 | `P/api/payslips.py:52,205-215` | 格式固定（路徑檢查依此） | ops | locked | - |
| PAY-02 | 鎖定狀態 | 待審核…已作廢皆不可改 | `P/api/payslips.py:179` | locked | money | locked | - |
| PAY-03 | 所得類別 | 50、9A（21 子類）、9B | `F/pages/payslip-form.html:273-304` | 申報代碼 locked | legal | locked | - |
| PAY-04 | 居住者判定 | 國籍字串「外國籍（未滿183天）」視為非居住者 | `P/api/payslips.py:112`；`payslip-form.html:210-212` | locked | legal | locked | - |
| PAY-05 | 扣繳稅率與起扣點 | 本國 50：5%/90501、9A 9B：10%/20010；外國 18%／6%／20% | `backend/helpers/legal_params.py:34-42`；`P/api/payslips.py:114-129` | 已版本化（依單據日期選版） | legal | 現有 legal-params | - |
| PAY-06 | 二代健保 | 費率 2.11%、單次上限 10,000,000、門檻 29500／20000、獎金投保倍數 4 | `legal_params.py:47-51`；`P/api/payslips.py:131-142` | 已版本化 | legal | 現有 | - |
| PAY-07 | 捨入 | 扣繳 floor；補充保費四捨五入 | `legal_params.py:99-106`；`payslips.py:138` | locked | legal | locked | - |
| PAY-08 | 勞報單端點權限 | 建立、改、匯出、作廢、送審：superadmin 或有「勞報單」模組 | `P/api/payslips.py:190,290,419` | 模組與角色 | security | M | S |
| PAY-09 | 付款角色 | `mark-paid`、`unpay`：財務或最高管理者 | `P/api/payslips.py:662-667,867,895` | 角色集合 | money | M | S |
| PAY-10 | 作廢規則 | 已簽回與已付款不可直接作廢；已核准僅 superadmin | `P/api/payslips.py:689-697` | 角色與狀態 | money | M＋S | S |
| PAY-11 | 匯出前置 | 須先送審並核准；作廢單不可匯出 | `P/api/payslips.py:537-540` | locked | money | locked | - |
| PAY-12 | 簽回檔限制 | pdf／jpg／jpeg／png，單檔 20MB；僅已匯出可上傳；僅已簽回未付款可刪 | `P/api/payslips.py:181-182,738,816` | 副檔名與大小（大小併 uploads 群組） | ops | SR | S |
| PAY-13 | 勞報單簽核人 | 簽核人與代理人必須是 superadmin | `P/api/payslip_approval.py:51-82,171-172` | 角色，現況→superadmin | money | M | S |
| PAY-14 | 無簽核層時 | superadmin 送審直接核准；否則待審並通知其他 superadmin | `P/api/payslip_approval.py:141-157` | 直接核准／強制待審 | money | SR | S |
| PAY-15 | 敏感欄位揭露頻率 | 身分證、銀行、帳號：每人每分鐘最多 30 次，先寫稽核 | `P/api/payslip_approval.py:308-310` | 整數 30、視窗 60 秒 | security | SR | S |
| PAY-16 | 銀行帳號遮蔽 | `****`＋末四碼；非最高管理者看遮蔽值且不可存入 | `P/payslip_bank.py:12-13`；`payslip-form.html:781` | locked | security | locked | - |
| PAY-17 | 可付款狀態 | 已核准、已匯出、已簽回可進出納待付款 | `P/payslip_payables.py:23`；`P/remit_link.py:35` | 狀態集合 | money | S | S |
| PAY-18 | 勞報單通知 | 6 種信，不含金額與受領人 | `P/payslip_notify.py:19-36` | 收件人與開關 | none | SR＋個人通知偏好 | S |
| PAY-19 | 列表上限 | 後端 100；前端寫死 500 | `P/api/payslips.py:218-220`；`F/pages/payslips.html:513` | 整數（前後端收斂單一來源） | none | D1 | S |
| PAY-20 | 獎金模組開關 | 預設開，環境變數 `BONUS_MODULE_ENABLED=0` 關 | `P/bonus.py:52,55-64` | 開關，預設開 | ops | SR（環境變數保留為逃生口） | S |
| PAY-21 | 獎金池比率 | 預設營業利益 10%（1000 基點），floor | `P/bonus_case.py:21,56` | 已有 `bonus_case_default_rate_bp` | money | 現有，補說明 | S |
| PAY-22 | 三類分配 | 業務／專案／後勤＝50/30/20%，合計須 100% | `P/bonus_case.py:19-22`；`P/api/bonus.py:1178-1179` | 已有 `bonus_case_default_split_bp` | money | 現有 | S |
| PAY-23 | 類別名稱 | 業務、專案、後勤 | `P/bonus_case.py:20` | 文字 | none | S | S |
| PAY-24 | 零頭歸屬 | 每人 floor，零頭留公司 | `P/bonus_case.py:6-12` | 留公司／給最後一位，現況→留公司 | money | SR | S |
| PAY-25 | 獎金基數 | `netProfit`，不退回毛利 | `P/bonus.py:69` | locked | money | locked | - |
| PAY-26 | 可發放案件狀態 | 「已成案、已結案」才可產生 | `P/api/bonus.py:1177,547` | 狀態集合 | money | S | S |
| PAY-27 | 獎金人員來源 | sales_person、case_stages.assigned_to、group、manual | `P/bonus.py:251-256`；`P/api/bonus.py:1181` | locked | money | locked | - |
| PAY-28 | 獎金寫入、可見權限 | admin＋可產生；看別人金額僅 superadmin；財務可查基數與預覽 | `P/api/bonus.py:55-86,419-420,965-966` | 角色集合 | money | M | S |
| PAY-29 | 獎金簽核人 | 簽核人與代理人必須是 superadmin；無鏈時 superadmin 且不可自簽 | `P/api/bonus.py:1287-1300` | 角色 | money | M | S |
| PAY-30 | 獎金狀態 | 未精算…已發放；核准後不可改；連傳票不可改 | `P/api/bonus.py:1662-1666`；`F/js/bonus.js:175-177` | 標籤可改，轉移 locked | money | S（標籤）＋locked | S |
| PAY-31 | 獎金入帳科目 | 應付 2191（可設）；追回暫記 1213（可設） | `P/bonus.py:362-366`；`P/bonus_correction.py:146-147`；`P/api/bonus.py:1460-1475` | 已有設定頁 | legal | 現有 | - |
| PAY-32 | 撥付扣繳與補充保費 | 取法規版本；缺投保金額則拒絕撥付 | `P/bonus_deductions.py:1-30,54-68` | 已版本化 | legal | 現有 | - |
| PAY-33 | 更正單 | 狀態五種；原因 200 字；更正後金額 0–99,999,999 | `P/bonus_correction.py:30-34,92,122` | 原因字數、金額上限 | money | SR＋S | S |
| PAY-34 | 更正單權限 | 建立、改、送審、核准、駁回＝superadmin；標記補發＝superadmin 或 cashier；同張獎金僅一張未結案更正單 | `P/api/bonus_correction.py:116,150,164,375-377` | 角色 | money | M | S |
| PAY-35 | 更正前提 | 只有「已發放」可開更正單 | `P/api/bonus_correction.py:44` | locked | money | locked | - |
| PAY-36 | 獎金通知流程 | 送審通知簽核人；待發放通知出納並回報送審人 | `P/api/bonus.py:1736-1760` | 通知偏好 | none | SR | S |
| PAY-37 | 簽名列文字 | 製表、覆核、主管 | `P/bonus.py:372,378` | 文字 | none | S | S |
| PAY-38 | 獎金 PDF 邊界 | `_MARGIN=42.6` | `P/bonus_pdf.py:56` | 公司列印版面 | none | D1 | S |

### 3b. 頁面顯示
| id | 名稱 | 現況 | file:line | 選項→預設 | 風險 | 機制 | 工 |
|---|---|---|---|---|---|---|---|
| PAY-V01 | 勞報單列表欄位 | 單號、受領人、所得類別、應付總額、實發金額、日期、狀態 | `F/pages/payslips.html:112-120` | 欄位顯示 | none | D1 | M |
| PAY-V02 | 勞報單篩選 | 月份＋搜尋框，無預設值 | `F/pages/payslips.html:100-106` | 預設月份 | none | D1 | S |
| PAY-V03 | 狀態顏色 | draft 灰、exported 綠、signed 藍、paid 深綠、void 紅刪除線 | `F/pages/payslips.html:29-35` | 色票 | none | S | S |
| PAY-V04 | 付款方式選項 | 匯款、現金 | `F/pages/payslip-form.html:328-330` | 清單 | money | S | S |
| PAY-V05 | 獎金列表狀態頁籤與顏色 | 全部＋狀態 | `F/pages/bonus.html:141-144`；`F/js/bonus.js:175-177` | 色票 | none | S | S |
| PAY-V06 | 比率顯示 | 基點÷100，最多兩位小數 | `F/js/bonus.js:17-18` | locked | none | locked | - |

## 4. analytics（儀表板與營運報表）

### 4a. 規則與常數
| id | 名稱 | 現況 | file:line | 選項→預設 | 風險 | 機制 | 工 |
|---|---|---|---|---|---|---|---|
| ANA-01 | 保固預警天數 | 90 天內到期；30 天內「即將到期」 | `N/api/dashboard.py:152,240`；`N/api/reports.py:593,1696` | 整數 90、30（儀表板與報表共用） | ops | SR | S |
| ANA-02 | 保固排序分桶 | 已過期→30 天→90 天→其他 | `N/api/dashboard.py:515-521` | 跟 ANA-01 | none | SR（共用） | S |
| ANA-03 | 保固清單上限 | 儀表板 5；報表 30 | `N/api/dashboard.py:293`；`reports.py:710` | 整數 | none | D1／SR | S |
| ANA-04 | 報價追蹤門檻 | 已送出逾 14 天未回應；有效期 ≤3 天提醒；有效期預設 30 天 | `N/api/dashboard.py:579,584,594` | 整數 14、3、30（有效天數與報價 Q1 同源） | ops | SR | S |
| ANA-05 | 開發案停滯 | 洽談中 30 天無新開發紀錄 | `N/api/dashboard.py:654` | 整數 30（與 crm CRM-02 同源） | ops | SR（共用） | S |
| ANA-06 | 出貨單卡簽核 | 待審核或簽核中逾 5 天未動；僅管理員可見 | `N/api/dashboard.py:693,707` | 整數 5 | ops | SR | S |
| ANA-07 | 成案判定 | 「已成案、已結案」計勝；「未成案」計敗；勝率一位小數 | `N/api/dashboard.py:563-570,606` | 狀態集合 | money | S | S |
| ANA-08 | 應收帳齡分桶 | 0–30／31–60／61–90／90+ 天，以成案日為基準 | `N/api/reports.py:2610,2638,2653` | 邊界天數預設 30/60/90 | ops | SR | S |
| ANA-09 | 帳齡顏色 | 逾 90 紅、逾 60 橘 | `N/api/reports.py:1795,1810,1861` | 同 ANA-08 | none | S | S |
| ANA-10 | 預設認列口徑 | 現金（含稅）；權責在切換裡 | `backend/helpers/recognition_basis.py:10`；`F/js/reports.js:81` | 現金／權責，預設現金 | legal | SR＋D1 | S |
| ANA-11 | 年度目標達成 | 年度比例＝年內第幾天÷365；目標存 `operating_targets` | `N/api/reports.py:748-757,2499` | 算法 locked；目標已有設定 | none | 現有 | - |
| ANA-12 | 平均毛利計算 | 以未稅營收加權 | `N/api/reports.py:765-770` | locked | money | locked | - |
| ANA-13 | 預留間接成本抵用 | 實際直接成本先抵用報價預留 | `N/api/reports.py:318-335` | locked | money | locked | - |
| ANA-14 | 設備料件分類 | 網通設備、監控設備、交換器、伺服器／工控 | `N/api/reports.py:3194` | 多選 | ops | SR／S | S |
| ANA-15 | 報表存取角色 | 財務角色，或持有「營運報表」模組 | `N/api/reports.py:87-104` | 模組集合 | security | M | S |
| ANA-16 | 儀表板財務卡 | 需財務角色且 `can_see_financial` 才給應收、毛利、結算 | `N/api/dashboard.py:31-32,64,292-309` | 角色集合 | security | M | S |
| ANA-17 | 月度、支出趨勢 | 財務限定；固定近 12 個月，口徑＝權責 | `N/api/dashboard.py:319,405,416-418,450` | 月數 12（6–24） | none | SR | S |
| ANA-18 | 儀表板清單長度 | 應收 10、毛利前 5、比較 8、追蹤報價 10、到期報價 5、停滯 10 | `N/api/dashboard.py:177,292-295,619-620,705-707` | 整數 | none | D1 | S |
| ANA-19 | 動態牆 | 預設 30、最大 100；各來源 40 筆 | `N/api/dashboard.py:801,842` | 整數 | none | D1 | S |
| ANA-20 | 與總帳差異分類 | 承攬商、設備、料件、其他；對應 gl:E04、E05、E10、E12 | `N/api/ledger_diff.py:26-31,139` | locked | none | locked | - |
| ANA-21 | 收款異常偵測 | 「錢從報表上無聲消失」的異常規則寫在函式內 | `N/api/reports.py:3247` | 規則集需另行盤點 | money | 待細查 | M |
| ANA-22 | 未收款當月口徑 | 依 `expectedReceiptDate` 落區間；缺日期者跳過 | `N/api/reports.py:3197-3204` | locked | none | locked | - |

### 4b. 頁面顯示
| id | 名稱 | 現況 | file:line | 選項→預設 | 風險 | 機制 | 工 |
|---|---|---|---|---|---|---|---|
| ANA-V01 | 報表頁籤與順序 | 目標、圖表、業務、應收、未收、支出、案件、毛利、保固、客戶、帳齡、與總帳差異、資金水位 | `F/pages/reports.html:487-535` | 預設頁籤、隱藏頁籤 | none | D1 | M |
| ANA-V02 | 預設期別 | `periodType='month'` | `F/js/reports.js:17-20` | 月／季／年 | none | D1 | S |
| ANA-V03 | 支出、應收預設範圍 | 預設 month，跟隨頂部期別列 | `F/js/reports.js:72,87,451-470` | 預設範圍 | none | D1 | S |
| ANA-V04 | 客戶排序 | 預設 revenue；可選 cases、winrate、activity | `F/js/reports.js:38,353-357` | 預設排序 | none | D1 | S |
| ANA-V05 | 金額縮寫 | ≥1 億「億」兩位小數、≥1 萬「萬」一位 | `F/js/reports.js:9-10` | 縮寫規則（D2） | none | D1（公司） | S |
| ANA-V06 | 收款率顏色門檻 | ≥95 綠、≥80 橘、其他紅 | `F/js/reports.js:381-389` | 兩個門檻 95、80；色票走 S | none | SR＋S | S |
| ANA-V07 | 儀表板首頁文案 | 「我的待簽核」等；模組缺席顯示「—」 | `F/index.html:486-504` | locked | none | locked | - |
| ANA-V08 | Excel／PDF 欄寬與樣式 | 各分頁欄寬、色碼、標題色 | `N/api/reports.py:1112,1178,1567` | 公司匯出版面 | none | D1（公司）／output_template | L |

## 5. 風險提醒與限制

1. 四模組的「誰能做什麼」幾乎都散在每個端點的 `user.get("role") == "superadmin"` 或 `require_any_module(...)`；放進 M 之前，須先抽共用判斷函式，否則逐端點改容易漏。
2. 標為 locked 的項目（傳票不可變、單號格式、401 欄位、稅率、捨入、簽核人限 superadmin 的核心規則）碰到法規或帳務完整性；若客戶要求鬆綁，走 `loosen` 雙人核准＋待生效（`confirm_period_days`），不開成一般設定。
3. 閾值類（ANA-01、ANA-04、ANA-08、ARP-V03）同一數字在前端、後端、PDF、Excel 各寫一份；改成 SR 時須同時收斂為單一來源，否則畫面與匯出對不上。
4. 未細查：`A/ledger/{inventory,equity,statements,cashflow}.py` 的報表演算規則、`N/api/reports.py` 約 4000 行的其餘細部規則、`payment-request.html`、`settlement.html`；估算請預留 10–20 項餘量。
5. 行號為讀檔當下；未跑測試，也未確認哪些常數被 docs 或契約測試逐字釘死（accounting 有，見 `A/attachments_catalog.py:8` 註解）。
