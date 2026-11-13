# 調查 B（d 權限與角色／e 選單與模組開關／f 簽核與門檻）
工作樹：D:\Claude-pm\hichan4-matrix\wt（唯讀；數字皆用 python 實際載入／計數）。
既有盤點（不重做）：docs/platform/plans/SYSTEM-MENU-UX-inventory/C-people-approval-expense-remit.md（用語、英文代碼外露等文字問題）。以下只補確切數量與點擊成本。
標記：[M]矩陣 [CB]批次勾選 [GA]群組全開全關 [S]搜尋篩選 [P]預設組合 [C]套用前確認＋6秒復原 [PC]手機卡片。痛度／頻率＝我的判斷（非量測）。

## 0. 一眼看懂
| 項目 | 真實數量（規則＋證據） | 今天怎麼操作 | 痛度 | 頻率 |
|---|---|---|---|---|
| 使用者個人權限鍵 | 30 鍵／10 群（backend/helpers/module_registry.py:50-81 `MODULES`，python 載入計：基本1、業務8、財務5、採購2、設備1、網路規劃2、專案2、工作2、勞務2、系統5） | users.html:600-632 手風琴，逐群展開、逐鍵點 chip；無全選／全清／複製他人 | 高 | 中 |
| 使用者 Email 通知偏好 | 78 事件／8 群（backend/helpers/notification_prefs.py `EVENT_GROUPS`：簽核流程34、會計傳票7、工作事項6、案件到期8、業務開發審核2、系統與報表15、標案雷達4、已結案解鎖2） | users.html:688-712 同款手風琴，每人逐鍵取消 | 高 | 低 |
| 權限矩陣 | 12 能力×5 角色＝60 格（12＝各 module.json `capabilities` 加總：payroll6、supply4、case1、crm1；角色＝`VALID_ROLES` 6 去 superadmin，auth.py:160、permmatrix/service.py:98-99）；動作詞彙 19 種（core/capabilities.py `ACTIONS`） | 每格 1 點→彈窗→「確定儲存」，一次只能一格 | 中（現在小，全面接入後會爆） | 低 |
| 職責角色 | 種子 8 個（core/migrations.py `_DUTY_SEED`：finance、sales、engineer、procurement、pm、sysadmin、viewer、admin_legacy） | 角色 chip 點一下→確認 | 低 | 中 |
| 選單 | menu_l1.json 群組9、核心項26＋模組 pages[].menu 35＝側欄 61 項；「系統」群＝核心19＋模組5＝24 | 無個人／角色隱藏開關；可見性＝權限鍵 | 中 | 低 |
| 模組管理 | 15 模組（backend/modules/* 15 目錄） | 每列一顆啟用/停用，立即 PUT、無確認、重啟生效 | 低 | 極低 |
| 簽核單據類型 | 9 類（helpers/tiered_approval.py:58-60；approval-settings.html docTypeOrder 同 9） | 每類展開→逐層→逐簽核人「選＋加入」，各區塊各自存 | 高 | 低～中 |
| 設定中心開關 | 31 群／約137欄，開關型約52、欄名 enabled 類約19（settings_groups.py 正規式**粗估**） | 設定中心逐群編輯 | 中 | 低 |

---
## (d) 權限與角色
### d1 permission-matrix.html（366 行；backend/modules/permmatrix/ api.py 142、service.py 748）
- 四分頁：角色與功能／個人／待生效／調整紀錄（:252）。
- 矩陣：依 unitLabel 分成多張表（groups()，:278）；列＝能力（現 12：勞報單6、供應商4、補登歷史報價1、開發記錄批示1），欄＝5 角色（admin／sales／engineer／viewer／finance；最高管理者不列）。每格 checkbox `@click.prevent="askRole(...)"`（:144-145）。
- 流程：點格→POST /role-cap/preview→彈窗（影響／生效時間／風險）→高風險＝security，需原因、確認期（service.py:23 預設 7 天）＋他人核准→「確定儲存」→整頁重載。一次只能改一格，沒有暫存多格再一次送出。
- 改 8 格：至少 16 次點擊（格＋確定各 8），高風險格另加原因文字，並進「待生效」分頁等核准。
- 「個人」分頁：選人→選能力→允許/禁止→下一步→確定＝每個個人例外約 5 動作；5 人×8 能力≈200 動作。
- 可沿用：預覽句、風險標、「一鍵復原上一次」（:214）、版本回溯（askRestore）。
- 痛度：中（60 格尚可；能力接入到數十物件×多動作時變成剛需）。頻率：低。
- 適用：[M]（已是矩陣，缺整列／整欄全開關）[CB]＋暫存區一次送 [GA]（依單位）[S] [C]（有確認彈窗，缺 6 秒復原，目前靠版本頁另按）[PC]（橫向捲動，手機擠）。

### d2 users.html（1495 行）
- 清單：分處／部門折疊樹，已有搜尋框（:325）；每列用 allModules（30）印 30 個唯讀 access-chip（:404-410）。人數為執行期資料，**未驗證**。
- 編輯彈窗（openEdit，:426）順序：基本資料→角色快速套用 chip（6 個系統範本＋自訂角色，:568-583）→角色層級下拉（:562-570）→存取模組手風琴（10群/30鍵，:600-632；預設只展開已有勾選的群，_initGroupOpenState）→職責角色／扣項（僅編輯既有帳號，:608）→Email 通知偏好（78鍵8群，:688-712）→「儲存」（:777）一次送出。
- 範本 ROLE_TEMPLATES（module_registry.py）：superadmin 20 鍵、admin 12、sales 8、engineer 6、finance 10、viewer 1。自訂角色（users.html:228-262、saveCr :1203）只是快速套用，套用後與範本脫鉤（applyCustomRole :1108）；其編輯器也是同款 30 鍵手風琴（:819-840）。
- 沒有任何批次：grep「批次／全選／複製」在 users.html／permission-matrix／duty-roles／module-settings 無命中（僅 approval-settings:580 說明文字）。
- 5 人給相同 8 權限的點擊成本（假設 8 鍵分散約 4 群、不吻合範本；為結構推算）：

| 路徑 | 動作 | 約略點擊（不含打字） |
|---|---|---|
| A 逐人編輯 users.html | 每人：編輯1＋展開4群＋勾8＋儲存1＝14 | 5×14＝約 70，開 5 次彈窗 |
| B 先建自訂角色再套用 | 建角色（開管理1＋新增1＋展開4＋勾8＋儲存1＝15）＋每人（編輯＋chip＋儲存＝3）×5＝15 | 約 30；套用後脫鉤，改角色不連動 |
| C duty-roles 職責角色（連動） | 新增1＋勾8 chip（扁平池免展開）＋儲存1＝10；綁5人×（chip＋確認）＝10 | 約 20；高敏感鍵（financial_view、finance、cashier、settings、audit_log、module_versions、payslip；duty_roles.py:29）每次綁定要填原因≥4字 |
| D permission-matrix 個人調整 | 每人每鍵約 5 | 約 200，不適用 |

  C 最短，但它在另一頁，且新增帳號彈窗看不到職責角色（users.html:608 `x-show="editingId && duty.visible"`）。
- 痛度：高。頻率：中（新進／調職／離職各一次）。
- 適用：[CB]＋[GA]（群頭全選／全清）[P]（把自訂角色升級成可連動預設組合）[S]（30鍵尚可，78 通知鍵必要）[C]（儲存前顯示新增X／移除Y，套用後6秒復原）[PC]（彈窗已手風琴，chip 小）[M]（人×10群總覽，再逐格切換）。

### d3 duty-roles.html（268 行；helpers/duty_roles.py）
- 三分頁：角色／使用者綁定／變更紀錄（:81-83）。
- 角色表：8 種子；編輯表單權限＝扁平 chip 池，點擊切換（:117-119，無群組、無搜尋）；原因欄（高敏感必填）；「儲存（寫入紀錄）」。權限池大小＝權限鍵（預期30，`known_keys` 未逐一驗證）。
- 使用者綁定表（:135-165）：每人一列，角色 chip 一點一綁（8 顆）＋「確認」面板（_ask :244）；個人扣項＝下拉＋「扣除」。人數未驗證。
- 批次綁定：無（一人一角色＝2 次點擊）。
- 痛度：低～中。頻率：中。
- 適用：[CB]（多人勾選→綁同角色）[S]（人名搜尋，:135 表無搜尋）[GA]（權限池依10群分組）[P]（8 種子即預設組合入口）[C]（有確認面板，缺6秒復原；變更紀錄頁不能直接還原）[PC]（已有 m-cards，:40-60）。

### d4 org-structure.html（731 行）
- 處→部門→成員折疊樹＋組織圖；新增處／部門／成員皆彈窗或下拉逐一（加成員 :298-302，移出 :289）。節點數為執行期資料，**未驗證**。
- 痛度：低。頻率：低。適用：[CB]（多人一次加入部門）[S]；其餘不適用。

### d5 VALID_ROLES 與自訂角色
- backend/helpers/auth.py:160：6 個（superadmin、admin、sales、engineer、viewer、finance）；顯示名可改（users.html:273-312，6 格＋「儲存名稱」）。
- 三套「角色」並存：固定6碼、自訂角色（快速套用）、職責角色（連動）；權限矩陣的角色＝6 去 superadmin（5）。統一時以 [M]＋[P] 落地。

---
## (e) 選單與模組開關
### e1 module-settings.html（194 行）
- 15 模組（accounting、analytics、arap、case、crm、daily_tasks、filehub、lodging、netplan、payroll、permmatrix、recyclebin、subcontract、supply、tender_radar；各 module.json）。
- 每列：名稱／版本／目前狀態／重啟後／一顆切換鈕（:92-103；toggle() 立即 PUT /api/system/modules/{key}，無確認、無影響預覽）。生效需重啟（:75-79）。授權＝每模組 `license_key`，本頁只顯示狀態，不能改。
- 改 8 模組：8 次點擊、8 次整表重載。
- 痛度：低（15 列單頁看完，極少改）。頻率：極低。
- 適用：[C]（停用案件／會計是大事，應預覽「哪些選單頁面消失」＋6秒復原）[P]（版型／方案一次定模組組合）[CB] 次要；[S][PC][M] 不需要。

### e2 menu_l1.json／sidebar.js／system-hub.html
- menu_l1.json：群組 9（主選單、客戶與業務、案件、採購與庫存、報表、財務會計、勞務管理、我的工作、系統）；核心項 26（system19、mywork3、business2、main1、supply1）；16 項限 superadmin。模組項在各 module.json pages[].menu：48 頁中 35 頁有選單（財務7、報表6、採購7、客戶與業務3、案件2、我的工作3、系統5、勞務2）。側欄共 61 項；「系統」群 24 項（>10）。
- sidebar.js（1714 行）只認權限鍵＋角色；沒有使用者自選隱藏（localStorage 僅主題／字級／session，:55-180）。
- system-hub.html（341 行）：分區＋搜尋＋最近使用；唯一設定＝是否列出無權限項目（:209）。逐項數量由 backend/core/system_hub.py 執行期組成，**未逐項驗證**。
- 逐角色／逐人選單開關：不存在；選單可見＝權限鍵（要某人看不到某選單＝取消該鍵）。
- 痛度：低。頻率：低。適用：[S]（hub 已有）；[M] 可把「選單項×角色」併入權限矩陣的 `menu` 動作（ACTIONS 含 menu）。

### e3 功能開關散在各處
- settings_registry 群組 31，欄位約137，布林／0-1 約52，enabled 類約19（例 settings_groups.py:525、562、577、681、727、748、806、847、864、880、896、912、1061、1077、1092、1158；alt_enabled :182；ext_totp_enabled :999）。粗估，未逐欄核對。操作＝設定中心逐群（A/B 組負責）。
- 執行期總開關（環境變數）：tender_radar（modules/tender_radar/__init__.py:21）、lodging（lodging/__init__.py:30）＝2；標案雷達另有每筆監看 enabled（tender_radar/api.py:88、:127）。
- 適用：[GA]（開關型欄位集中成「功能開關」總覽）[C]。

---
## (f) 簽核層級與門檻
### f1 approval-settings.html（1157 行）
- 9 類：quotation、shipping、completion、invoice_voucher、payment_request、contractor_voucher、extra_expense、voucher（會計傳票）、bonus（tiered_approval.py:58-60、:76-82）。預設併入「統一流程」的 6 類（DEFAULT_UNIFIED_DOC_TYPES :66-68）；contractor_voucher、voucher、bonus 預設獨立。`register_doc_type()`（:92-100）可執行期再登記，故不固定為 9。
- 結構：①套用範圍 9 列開關（scope[dt] :336，每列可展開 :330）＋一顆儲存（saveScope :363）；②流程區塊：1 統一＋每個獨立類各一塊，各自 saveFlow(key)（:388）；③層：新增／上移／下移／刪除（:455-461、:541），層數無上限；④簽核人：每層逐人「下拉選＋加入」（:505-523，來源含使用者／部門／處），每人一個移除鈕（:495）；另有「申請人組織主管自動簽核」（:416）。預設全收合。
- 改一條3層、每層2人的流程：新增層3＋每人（開下拉、選、加入）3×6＝18＋儲存1＝約 22；9 類都獨立＝9 塊各存一次。無「複製此流程到另一類」（僅從統一勾掉時自動複製一份，:580）。
- roleLabel() 只認 4 種角色（:1103，C 檔已提）。
- 痛度：高。頻率：低～中（組織調整時）。
- 適用：[P]（常見流程範本）[CB]（簽核人多選一次加入）[S] [C]（改流程影響進行中單據，預覽件數＋6秒復原）[M]（單據類型×層級×簽核人）[PC]（層卡片化）。

### f2 approval-delegates.html（281 行）
- 表單：委託人／代理人下拉＋起迄日＋原因＋「建立」；清單 7 欄，僅有「停用」（:136-155）。筆數未驗證。權限矩陣另有 perm_delegations（permmatrix/service.py:589 create_delegation，範圍 caps／doc_types），permission-matrix.html 目前沒有建立代理的畫面。
- 一次一筆；5 人休假≈5×約6＝30 動作。痛度：低～中。頻率：低。
- 適用：[S] [C]（建立時顯示代理期間哪些單據轉給誰）。

### f3 contractor-voucher-approval-settings.html（83 行）
- 已是「此設定已搬移」跳轉頁（title），設定併入 approval-settings 的 contractor_voucher 區塊；無操作，痛度無。

### f4 ledger-settings／bonus
- ledger-settings.html（353 行）：科目→報表列／現金流分類每列下拉，change 即存，已有搜尋＋「只看有問題的」（:82-83）；報表列（BS／IS）每列4欄即時存（:129-132）；稅別對應每列1個「儲存」（:164）；角色→科目對照＋待核准。科目數／列數為執行期資料，**未驗證**（未找到種子清單常數）。
- 痛度：中。頻率：低。適用：[S]（已有）[CB]（多科目套同分類）。
- bonus.html／bonus-corrections.html 門檻表：未深入，**未驗證**（簽核流程已併入 f1 的 bonus 類型）。

### f5 通知偏好
- 管理者代設：users.html:688-712，Email 事件 78 鍵／8 群，opt-out 清單（notification_prefs.py 檔頭，預設全收），每人逐鍵取消；不在收件範圍的鍵置灰（item.receivable）。
- 本人：my-account.html 4 分頁 profile／security／notify／prefs（:639-642）；notify 分頁只有 LINE 綁定卡（:312 起）＋「我要收的 LINE 通知」勾選（:343-358，依 prefGroups 分群，每事件一個 checkbox，即時存 setPref）。**本人看不到也改不了 Email 通知偏好**（只在管理員的 users.html）。LINE 可選事件數＝公司已開啟且角色允許（執行期），未驗證；LINE 事件表在 helpers/line_notify.py，未逐一計數。
- 痛度：高（78鍵）。頻率：低。適用：[GA]（群頭全收／全不收）[P]（「只收我要簽的」「只收系統告警」）[S] [C]。

---
## 跨頁共通缺口（判斷）
1. 權限相關頁面一次只改一項：矩陣1格／個人例外1筆／綁定1人1角色；沒有暫存區＋一次送出。
2. 沒有複製／預設組合：自訂角色與範本套用後脫鉤，自訂角色與職責角色兩套並存。
3. 群組只能展開收合，沒有群組全開／全清（users 兩組手風琴、duty-roles 扁平池）。
4. 確認機制不一：矩陣有預覽＋確認、duty-roles 有確認面板、users 儲存直接生效、module-settings／ledger 列即存、approval-settings 每區塊獨立存；全系統沒有6秒復原（矩陣有版本回溯、duty-roles 有變更紀錄，皆需跳頁）。
5. 手機：duty-roles 已卡片化（m-cards）；permission-matrix 橫向捲動；users 彈窗內 chip 尚可。

## 未能驗證
使用者人數、部門數、組織節點數、approval-delegates 筆數、科目數（執行期資料）；system_hub.py 逐項數；line_notify 事件數；duty-roles known_keys 是否正好30；settings 欄位／開關數為正規式概估；bonus 門檻表；點擊數為依 UI 結構推算、非實測。
