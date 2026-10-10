# 框架化債務清單（第 54 班起；稽核者維護）

> 規則（核心記憶「框架優先、不鎖死內容」，`MODULE-GUIDE.md` §15；使用者 2026-10-10）：**碰到就框架化**——修正或變更觸及寫死的業務規則／數值／名單／角色字串時，同一個 PR 內改成登錄／設定／選項（預設＝今天的行為，附等值證明），或在本清單列一筆有負責人的後續項目。審查者與稽核者拒絕沒有書面理由的新寫死業務值；棘輪守門把現存位置列為債務（只准減不准增）。
> 來源：`CONFIGURABILITY-INVENTORY-T54.md`／`configurability_items_t54.csv`（141 項，盤點日 2026-10-10）。欄位：狀態 `open`／`in-progress`（分支）／`done`（SHA）／`locked-pending`（暫列鎖定、待使用者確認，見設計稿附錄 B）／`wontfix`（附理由）。負責人由派工填。

| id | 群組 | 位置（檔:行） | 寫死的內容（今天的值） | 目標框架 | 優先 | 風險 | 狀態 | 負責人 |
|---|---|---|---|---|---|---|---|---|
| CFG-001 | K01 | backend/helpers/profit_rules.py:34 | 營業利益率目標警示門檻 12%（紅）：後端與前端各一份；operating_targets 設定並未餵進這條警示（TARGET_MARGIN_PCT = 12） | 新群組 profit_warning（設定中心；operating_targets 是財務年度營收／毛利目標，不是警示門檻，不可混用） | P1 | money | open | |
| CFG-002 | K01 | frontend/pages/quotation-form.html:1911 | 報價單營業利益率燈號 12% 紅／20% 黃／綠，及「低於目標 12%」文字，寫在樣板，與 profit-rules.js 的 12 重複（tot.netMarginPct < 12 … < 20；'⚠ 低於目標 12%'） | 新群組 profit_warning（設定中心；operating_targets 是財務年度營收／毛利目標，不是警示門檻，不可混用） | P1 | money | open | |
| CFG-003 | K01 | frontend/pages/settlement.html:1019 | 精算頁、營運報表的利潤率 20% 綠／10% 橘門檻（與報價單 12/20 不一致，三處各寫各的）（summary.netMarginPct >= 20（reports.html:1563 為 >=20 / >=10）） | 新群組 profit_warning（設定中心；operating_targets 是財務年度營收／毛利目標，不是警示門檻，不可混用） | P1 | money | open | |
| CFG-004 | K01 | frontend/static/profit-rules.js:10 | 前端複製一份：舊口徑管銷 10%、預設管銷 25、公益 1%、目標 12 全寫死（與後端重複，靠黃金向量測試對齊）；DEFAULT_OVERHEAD_PCT 繞過 overhead_default_pct（LEGACY_ADMIN_RATE = 0.10, DEFAULT_OVERHEAD_PCT = 25, CHARITY_RATE = 0.01, TARGET_MARGIN_PCT = 12） | overhead_rule_mode + overhead_default_pct（/api/overhead/settings）已存在，前端應只讀它 | P1 | money | open | |
| CFG-005 | K01 | backend/helpers/profit_rules.py:32 | 全域預設管銷 25 的程式後備值（設定缺／壞時退回 25；profit_guard.py:65 與 pdf_gen.py:43 各自再寫一次）（DEFAULT_OVERHEAD_PCT = 25） | overhead_default_pct 已存在；只需收斂後備來源 | P2 | money | open | |
| CFG-006 | K01 | backend/helpers/profit_rules.py:33 | 公益捐款比率 1%（後端；前端 profit-rules.js 亦同，PDF 標籤『公益捐款（1%）』）（CHARITY_RATE = 0.01） | 類比 overhead_default_pct 新增 charity_rate 鍵；charity_basis_mode 已是設定（第 52 班） | P2 | money | open | |
| CFG-007 | K01 | backend/helpers/profit_rules.py:31 | 舊口徑管銷＝報價稅前 10% 固定值（已結案舊單用，歷史口徑）（LEGACY_ADMIN_RATE = 0.10） | none（刻意凍結） | P4 | legal | open | |
| CFG-008 | K02 | backend/helpers/tax_calc.py:27 | 營業稅法定稅率 5%，後端多處重複：tax_calc、supply gl_events、arap 應收拆稅 /1.05、case recognition /1.05、settlement_actuals（LEGAL_TAX_RATE = 0.05） | tax_rules / tax_rules_versions 目前只含所得稅與健保，可加入 vat_rate 並讓各處讀同一來源 | P2 | legal | open | |
| CFG-009 | K02 | backend/modules/arap/receivables.py:110 | 應收含稅金額拆稅直接 /1.05（amt_incl - amt_incl / 1.05） | 同上 vat_rate | P2 | legal | open | |
| CFG-010 | K02 | backend/modules/case/settlement_actuals.py:20 | 精算預設實際成本＝報價成本×1.05（5% 非扣抵進項稅假設）；settlement.html、quotation-form.html、reports 另有重複（ESTIMATE_RATE = 1.05） | vat_rate（再加『進項稅是否可扣抵』開關） | P2 | money | open | |
| CFG-011 | K02 | backend/modules/subcontract/dispatch_flow.py:101 | 承攬商派發稅率預設 0.05 散落至少 7 處（dispatch_flow、remit_create、vendor_contractors、contractor_vouchers、gl_events、DB 欄位預設、前端）（tax_rate if tax_rate is not None else 0.05（另見 remit_create.py:92、vendor_contractors.py:85/175/599/673、contractor_vouchers.py:400、gl_events.py:60、db.py:1341/3047、frontend/js/case-management-dispatch.js:212/237）） | vat_rate 設定鍵 | P2 | legal | open | |
| CFG-012 | K02 | backend/modules/supply/gl_events.py:19 | 進項稅推估 5%（有發票號才計）自帶一份 _RATE，沒走 tax_calc（_RATE = 0.05） | 同上 vat_rate | P2 | legal | open | |
| CFG-013 | K02 | frontend/pages/quotation-form.html:2370 | 報價單稅率預設 5、含稅／免稅切換寫 5 或 0；進項稅 0.05 另寫；售價回推進位到 5 元（… ? 5 : Number(this.q.taxRate)；:2378 t==='taxable'?5:0；:2457 halfUp(totalCost, 0.05)；:2437 /5)*5） | vat_rate 設定；進位單位可併入報價設定 | P2 | legal／money | open | |
| CFG-014 | K02 | backend/helpers/legal_params.py:34 | 法定參數預設值（所得稅 5%/10%/20% 與起扣點、二代健保 2.11%、單次上限、門檻）在 legal_params.py 與 db.py 種子各寫一份（"50": {tax_rate 0.05, tax_threshold 90501} … rate 0.0211（db.py:820-832 另有同一份）） | tax_rules / tax_rules_versions 已可編；只需合併兩份種子、避免版本分叉 | P3 | legal | open | |
| CFG-015 | K02 | backend/helpers/legal_params.py:23 | 所得類別代碼（INCOME_TYPES = ("50","9A","9B")） | legal_params 本身 | P4 | legal | open | |
| CFG-016 | K02 | backend/modules/accounting/ledger/tax401_media.py:72 | 401 媒體申報手動欄位代碼（MANUAL_CODES = (113, 114, 115)） | none（法定格式） | P4 | legal | open | |
| CFG-017 | K03 | backend/modules/payroll/bonus_case.py:19 | 獎金分類固定三類（CATEGORIES = ("sales","project","admin")） | bonus_payable_account_code 為同模組設定先例 | P2 | money | open | |
| CFG-018 | K03 | backend/modules/payroll/api/payslips.py:695 | 勞報單簽核人只能是最高管理者；核准後作廢需 superadmin；已匯出可由模組持有者作廢；核准／駁回僅 superadmin（if status=="已核准" and role!="superadmin" → 403；可作廢狀態 ("已匯出","已核准")（:690）） | approval-flow settings（payslip_approval_flow 已讀 payslip_approval.py:72）+ permission matrix (1d)；簽核人限制仍寫死 | P3 | money／legal | open | |
| CFG-019 | K03 | backend/modules/payroll/bonus.py:366 | 獎金應付預設科目 2191（DEFAULT_PAYABLE_ACCOUNT = "2191"） | 總帳『角色→科目對應』設定（最高管理者）；bonus_payable_account_code 已存在 | P3 | money | open | |
| CFG-020 | K03 | backend/modules/payroll/bonus_case.py:21 | 案件獎金預設比率 10%（1000bp）與業務/專案/後勤 50/30/20 的程式後備值（設定缺時退回）（DEFAULT_RATE_BP = 1000; DEFAULT_SPLIT_BP = {sales 5000, project 3000, admin 2000}） | bonus_case_default_rate_bp / bonus_case_default_split_bp 已存在（api/bonus.py:1178、1188-1190） | P3 | money | open | |
| CFG-021 | K03 | backend/modules/payroll/api/payslip_approval.py:35 | 勞報單狀態常數寫死（草稿/待審核/已核准，另 已匯出/已簽回/已付款/已作廢）（S_DRAFT, S_REVIEW, S_APPROVED = 草稿, 待審核, 已核准） | none | P4 | ops | open | |
| CFG-022 | K04 | backend/helpers/auth.py:54 | 密碼最少長度（8 處呼叫共用）（MIN_PASSWORD_LEN = 8） | none（單一常數，易改成讀 system_settings） | P1 | security | open | |
| CFG-023 | K04 | backend/main.py:211 | 一般角色閒置登出門檻 8 小時（_IDLE_TIMEOUT_SECONDS = 8*3600） | none（system_settings） | P1 | security | open | |
| CFG-024 | K04 | backend/main.py:216 | superadmin/admin 閒置登出門檻 2 小時（_ADMIN_IDLE_TIMEOUT_SECONDS = 2*3600） | none | P1 | security | open | |
| CFG-025 | K04 | backend/routers/auth.py:42 | 登入失敗鎖定：連續失敗次數與鎖定時間（依來源 IP）（_LOGIN_MAX_FAILS=5；_LOGIN_LOCKOUT_S=900） | none（system_settings + 範圍檢查） | P1 | security | open | |
| CFG-026 | K04 | backend/helpers/auth.py:83 | Passkey/WebAuthn 總開關寫死為關閉（要開要改碼）（PASSKEY_ENABLED = False） | webauthn_rp_id/webauthn_origin 已可設，總開關未接 system_settings | P2 | security | open | |
| CFG-027 | K04 | backend/main.py:558 | 哪些角色算高權限而套用較短閒置門檻（寫死 superadmin/admin，提示文字『2 小時／8 小時』也寫死）（role in ('superadmin','admin')） | none（可併入閒置設定，每角色一個秒數） | P2 | security | open | |
| CFG-028 | K04 | backend/routers/auth.py:539 | Session 有效期（登入後 expires_at）（timedelta(days=30)） | none | P2 | security | open | |
| CFG-029 | K04 | backend/helpers/auth.py:42 | 弱密碼黑名單（舊預設密碼＋額外 4 個）（_LEGACY_WEAK_PASSWORDS 舊預設密碼清單＋額外 4 個常見弱密碼（:115）；內容不在此重述） | security.* scan 設定鍵（已有）可擴充追加項；內建清單應保留 | P3 | security | open | |
| CFG-030 | K04 | backend/main.py:127 | CORS 預設白名單內含寫死內網 IP 172.16.10.177（6 筆 localhost/127.0.0.1/172.16.10.177 的 :666 http/https） | 環境變數 MOTRIX_CORS_ORIGINS（main.py:139）；未接 system_settings，換 IP 仍需改環境變數並重啟 | P3 | security | open | |
| CFG-031 | K04 | backend/modules/payroll/api/payslip_approval.py:309 | 薪資單明細揭露頻率限制（每人每分鐘 30 次（_REVEAL_LIMIT, _REVEAL_WINDOW = 30, 60.0）） | none | P3 | security | open | |
| CFG-032 | K04 | backend/routers/auth.py:148 | TOTP 挑戰有效時間與錯誤次數上限；驗證容許視窗（300 秒；5 次（:149）；valid_window=1（:588、:855）） | none | P3 | security | open | |
| CFG-033 | K04 | backend/routers/auth.py:149 | TOTP 錯誤次數上限（_TOTP_MAX_FAILS = 5） | none | P3 | security | open | |
| CFG-034 | K04 | backend/helpers/company_setup.py:64 | 首次未設定本公司資料的暫時放行時數上限（GRACE_MAX_HOURS = 72） | none（寧可保留寫死） | P4 | legal | open | |
| CFG-035 | K04 | backend/routers/auth.py:439 | Demo 登入 token 有效期（timedelta(days=1)） | none | P4 | none | open | |
| CFG-036 | K05 | backend/archive.py:52 | 備份／稽核保留預設值：已有 GET/PATCH 與設定頁（company-profile-settings.html:1176/1270），驗證範圍 1～3650 天；audit_log_keep_days 沒有法遵下限（可設成 1 天）（local_db 30; cloud_daily 60; weekly 90; monthly 0(永久); pre_update 5; audit_log 1825） | system_settings.backup_retention + GET/PATCH /api/settings/backup-retention（routers/system.py:2270/2277）+ 公司資料設定頁；缺：稽核下限、通知／request 日誌保留併入 | P1 | legal | in-progress（wip/t54-n39-settings-s0s2） | |
| CFG-037 | K05 | backend/helpers/audit.py:165 | 站內通知保留天數（已讀未讀都清）（NOTIFICATION_RETENTION_DAYS = 90） | 可併入 system_settings.backup_retention（archive.py:52）+ PATCH /api/settings/backup-retention | P1 | none | in-progress（wip/t54-n39-settings-s0s2） | |
| CFG-038 | K05 | backend/helpers/system_checks.py:731 | request 日誌保留天數（keep_days = 90） | 可併入 backup_retention | P2 | ops | in-progress（wip/t54-n39-settings-s0s2） | |
| CFG-039 | K05 | backend/helpers/system_checks.py:182 | 每日備份過期告警門檻（_BACKUP_STALE_HOURS = 36） | none | P3 | ops | in-progress（wip/t54-n39-settings-s0s2） | |
| CFG-040 | K05 | backend/archive.py:1679 | Server log 輪替大小與保留份數（50 MB × 5 份（:1680）） | 仿 backup_retention 設定 | P4 | ops | in-progress（wip/t54-n39-settings-s0s2） | |
| CFG-041 | K05 | backend/archive.py:940 | 備份後快照緩衝秒數（_SNAPSHOT_AFTER_CUSHION_SECONDS = 300） | none | P4 | ops | in-progress（wip/t54-n39-settings-s0s2） | |
| CFG-042 | K05 | backend/helpers/system_checks.py:543 | 簽核提醒失敗紀錄保留筆數（REMINDER_FAILURE_KEEP = 200） | none | P4 | none | in-progress（wip/t54-n39-settings-s0s2） | |
| CFG-043 | K05 | backend/routers/system.py:385 | 稽核日誌分層樹預設／最大查詢天數（預設 90 天；最大 366 天（:386）；module-counts 90 天（:387）） | none | P4 | ops | in-progress（wip/t54-n39-settings-s0s2） | |
| CFG-044 | K06 | backend/helpers/uploads.py:38 | 單檔大小上限（20 * 1024 * 1024） | none（system_settings 可承載） | P1 | ops | in-progress（wip/t54-n39-settings-s0s2） | |
| CFG-045 | K06 | backend/helpers/uploads.py:43 | 支出申請每單附件數與單次總量上限（case_extra_expense: max_files 10, max_request_bytes 50MB） | 表結構現成，改讀 system_settings 並擴及其他資料夾 | P1 | ops | in-progress（wip/t54-n39-settings-s0s2） | |
| CFG-046 | K06 | backend/modules/case/api/case_extra_expenses.py:86 | 附件種類（發票／其他）固定二種（FILE_KINDS = ("invoice","other")） | FORM-DESIGNER 必填規則 | P2 | legal | in-progress（wip/t54-n39-settings-s0s2） | |
| CFG-047 | K06 | backend/helpers/custom_files.py:28 | 自訂欄位檔案允許副檔名與最大檔數（ALLOWED_EXTS=(jpg,jpeg,png,pdf)；_MAX_FILES=50（:30）） | 自訂欄位定義已可每欄設 max（:125），預設值寫死 | P3 | security | in-progress（wip/t54-n39-settings-s0s2） | |
| CFG-048 | K06 | backend/helpers/uploads.py:32 | 附件允許副檔名白名單（全系統）（{'.jpg','.jpeg','.png','.pdf'}） | none（只能在已有 magic 規則的類型中勾選） | P3 | security | in-progress（wip/t54-n39-settings-s0s2） | |
| CFG-049 | K06 | backend/helpers/uploads.py:36 | 各資料夾額外放行副檔名（傳票附件 Word/Excel、支出 HEIC）（voucher_attachments:{.docx,.xlsx,.doc,.xls}; case_extra_expense:{.heic,.heif}） | none | P3 | security | in-progress（wip/t54-n39-settings-s0s2） | |
| CFG-050 | K06 | backend/modules/case/api/case_extra_expenses.py:851 | 作廢權限＋條件：僅 superadmin、僅已核准且未付款、理由必填（docstring「僅最高管理員 superadmin；僅已核准且尚未付款；理由必填」；VOIDED_STATUS="已作廢"（:83）） | permission matrix (1d) | P3 | money／legal | in-progress（wip/t54-n39-settings-s0s2） | |
| CFG-051 | K06 | backend/helpers/branding.py:32 | 品牌圖檔大小上限 2MB、最大邊長 4096、允許格式（MAX_UPLOAD_BYTES = 2 * 1024 * 1024） | branding_assets（已有 limits 回傳） | P4 | none | in-progress（wip/t54-n39-settings-s0s2） | |
| CFG-052 | K06 | backend/helpers/xlsx_out.py:18 | Excel／PDF 匯出冷卻秒數（EXCEL_COOLDOWN=5; PDF_COOLDOWN=30） | none | P4 | ops | in-progress（wip/t54-n39-settings-s0s2） | |
| CFG-053 | K06 | backend/modules/case/api/case_extra_expenses.py:85 | 發票號碼長度上限（INVOICE_NO_MAX = 40） | none | P4 | none | in-progress（wip/t54-n39-settings-s0s2） | |
| CFG-054 | K06 | backend/modules/case/expense_forms.py:26 | 費用單明細上限 200 行、資料大小 20000 位元組（MAX_LINES = 200; MAX_DATA_BYTES = 20000） | none | P4 | ops | in-progress（wip/t54-n39-settings-s0s2） | |
| CFG-055 | K07 | backend/archive.py:3003 | 每日／每週備份排程間隔（_DAILY_INTERVAL_SECONDS = 2*3600; _WEEKLY_INTERVAL_SECONDS = 6*3600） | none（backup_retention 只管保留天數，未管頻率） | P2 | ops | open | |
| CFG-056 | K07 | backend/helpers/daily_checks.py:48 | 每日檢查（逾期、提醒、證書、備份新鮮度）執行時刻（hour=8, minute=0） | none | P2 | ops | open | |
| CFG-057 | K07 | backend/modules/analytics/api/reports.py:3083 | 月報寄送日與時刻（每月 1 日 08:00）（每月 1 日 hour=8 minute=0） | monthly_report_recipients（收件人已可調，日／時未可調） | P2 | ops | open | |
| CFG-058 | K07 | backend/modules/accounting/ledger/auto_run.py:19 | 總帳引擎自動執行間隔與啟動延遲（INTERVAL_SECONDS=3600; FIRST_DELAY_SECONDS=300） | none | P3 | money | open | |
| CFG-059 | K07 | backend/modules/crm/api.py:1230 | CRM 每日提醒執行時刻（hour=8） | none（可與 daily_checks 一併設定） | P3 | none | open | |
| CFG-060 | K07 | backend/modules/tender_radar/source.py:161 | 標案詳細頁每日抓取上限 20、靜默期 7 天、假日表預警 60 天、高頻時段門檻 12（DETAIL_DAILY_LIMIT = 20（:132 QUIET_PERIOD_DAYS = 7；:153 HIGH_FREQUENCY_SLOT_THRESHOLD = 12；:1107 HOLIDAY_WARN_DAYS = 60）） | none | P3 | ops | open | |
| CFG-061 | K07 | backend/helpers/geo.py:486 | 地理編碼快取 TTL 與預熱間隔、請求間隔（GEOCODE_CACHE_TTL_DAYS=180; GOOGLE_CACHE_TTL_DAYS=30; GEOCODE_INTERVAL_SECONDS=1.1; GEOCODE_WARM_INTERVAL_SECONDS=6h） | system_settings google_quota 已有；TTL／間隔未有 | P4 | ops | open | |
| CFG-062 | K07 | backend/modules/lodging/source.py:48 | 住宿資料每日更新時刻與頻率／失敗上限（MIN_SUCCESS_INTERVAL=24h; FAILURE_COOLDOWN=1h; SCHEDULED_MIN_INTERVAL=20h; DAILY_REFRESH_HOUR=3; DAILY_MAX_FAILURES=3） | none | P4 | ops | open | |
| CFG-063 | K07 | backend/modules/tender_radar/source.py:1107 | 休假警示天數、靜默期天數（HOLIDAY_WARN_DAYS=60；QUIET_PERIOD_DAYS=7（source.py:132）） | 同上 tender 設定 | P4 | none | open | |
| CFG-064 | K07 | backend/routers/company_lookup.py:70 | GCIS 每日查詢上限預設值（已可由 gcis_daily_limit 調整）（GCIS_DAILY_LIMIT_DEFAULT = 300） | system_settings gcis_daily_limit（已可調，僅預設寫死） | P4 | ops | open | |
| CFG-065 | K08 | backend/helpers/payable_due_core.py:33 | 應付款到期提醒：提前幾天通知（SOON_DAYS = 3（逾期＝預定日後第 1 個工作日）） | none；寄信開關已走 mail_types/email_notify | P1 | money | open | |
| CFG-066 | K08 | backend/helpers/system_checks.py:503 | 簽核逾時催辦階段（第 1、3、5 天，之後每 5 天）（REMINDER_FIRST_STAGES = (1, 3, 5); REMINDER_STEP_AFTER = 5） | approval-flow settings | P1 | ops | open | |
| CFG-067 | K08 | backend/modules/analytics/api/dashboard.py:584 | 報價追蹤門檻：報價滿 14 天未回覆列入跟進（days_since >= 14） | none | P1 | none | open | |
| CFG-068 | K08 | backend/modules/analytics/api/dashboard.py:654 | 開發案停滯門檻：30 天無動靜列入停滯（days_since >= 30） | none | P1 | none | open | |
| CFG-069 | K08 | backend/modules/crm/api.py:1083 | 業務開發停滯天數 30、重複通知間隔 14 天、暫擱置自動轉未成案 180 天（dashboard.py:626 與 email_notify 註解寫同一個 30，重複）（_STALE_DAYS = 30; _STALE_RENOTIFY_INTERVAL = 14（:1084）; _HOLD_AUTO_CONVERT_DAYS = 180（:1085）） | none | P1 | ops | open | |
| CFG-070 | K08 | backend/modules/crm/api.py:1084 | 久未更新提醒再次通知間隔（_STALE_RENOTIFY_INTERVAL = 14） | none | P1 | none | open | |
| CFG-071 | K08 | frontend/pages/quotation-form.html:2599 | 報價有效天數預設與「超過 30 天需主管審核」門檻（前端寫死，後端預設 30）（if (this.q.validDays > 30)；預設 validDays: 30（:2253）；後端 quotations.py:1557） | tiered_approval 簽核設定／system_settings | P1 | money | open | |
| CFG-072 | K08 | backend/helpers/payable_due_core.py:39 | 應付到期提醒天數固定 3 天前／當天／逾期（_LABEL = {soon:預定付款日將到（3 天後）, today, overdue}） | notification_prefs / notify_matrix（提醒對象可設，天數未見設定） | P2 | ops | open | |
| CFG-073 | K08 | backend/modules/analytics/api/reports.py:1862 | 應收帳齡色階門檻（>60 橘、>90 紅）（d > 90 / d > 60） | none | P2 | money | open | |
| CFG-074 | K08 | backend/modules/case/case_deadlines.py:218 | 保固到期預警天數 7 日（紅）／30 日（橙）（_WARR_THRESHOLDS = (7, 30)） | none | P2 | ops | open | |
| CFG-075 | K08 | backend/modules/crm/api.py:1085 | 暫擱置案件自動轉未成案天數（_HOLD_AUTO_CONVERT_DAYS = 180） | none | P2 | ops | open | |
| CFG-076 | K08 | backend/modules/supply/api/inventory.py:42 | 庫存黃燈倍數 1.5（紅＝低於安全庫存，黃＝低於安全庫存×1.5）及採購建議補貨目標 ceil(safety×1.5)（_YELLOW_MULTIPLIER = 1.5） | none（每料號 safety_stock 已可設，倍數無設定） | P2 | ops | open | |
| CFG-077 | K08 | frontend/pages/cashier.html:370 | 出納待付款『預定付款日 3 天內到期』提示寫死 3 天（兩處）；後端 plannedState 判定亦同門檻（3 天內到期（另 :503）） | none（payable_calendar／payable_reminders 只有事件開關，無天數設定） | P2 | ops | open | |
| CFG-078 | K08 | backend/routers/map_points.py:1025 | 地圖『即將截止』天數（CLOSING_SOON_DAYS = 7） | none | P3 | none | open | |
| CFG-079 | K08 | backend/helpers/company_setup.py:470 | 憑證／簽章到期警示天數與寬限小時（SIGNED_EXPIRY_WARN_DAYS=30; GRACE_EXPIRY_WARN_HOURS=6; GRACE_MAX_HOURS=72（:64）） | none | P4 | legal | open | |
| CFG-080 | K08 | backend/helpers/system_checks.py:50 | 憑證長效判定天數（_CERT_LONG_LIVED_DAYS = 180） | none | P4 | security | open | |
| CFG-081 | K09 | backend/db.py:5834 | 共用編號產生器：固定 前綴-YYYYMM-NNN（月重置、3 位數）；呼叫前綴 C S V CN DN IV PR PV NP PO(批號)（month=%Y%m；pattern f"{prefix}-{month}-???"；LENGTH=prefix+11（超過 999 張／月會破格）） | none（custom_modules 已有 PREFIX_RE 自訂前綴，helpers/custom_modules.py:28） | P2 | ops | open | |
| CFG-082 | K09 | backend/modules/case/expense_forms.py:19 | 請購／採購／差旅／零用金單號前綴與格式（日重置、4 位數），與其它模組格式不同；PR 與請款單 PR、PO 與庫存批號 PO 前綴重複（KIND_PREFIX = {purchase_req:PR, purchase_order:PO, travel:TE, petty_cash:PC}；{前綴}-{YYYYMMDD}-{NNNN}（:265-272）） | expense-types designer（helpers/expense_types.py PREFIX_RE 已允許自訂前綴） | P2 | none | open | |
| CFG-083 | K09 | backend/modules/case/material_approval.py:27 | 叫料單／變更／匯款單號前綴與日重置 4 位格式（DOC_PREFIX="MO"（material_change.py:27="MC"、material_payment.py:32="MP"）；MO-YYYYMMDD-NNNN（:153-161）） | none | P3 | none | open | |
| CFG-084 | K09 | backend/modules/case/api/quotations.py:732 | 報價單單號格式 MQ-YYYYMM-NNN（月重置、3 位數、前綴固定）；audit.py:34、migrations.py:360 以 regex 反推（f"MQ-{month}-{next_seq:03d}"（quote_seq 表以月為鍵）） | none | P4 | legal | open | |
| CFG-085 | K10 | backend/modules/crm/api.py:26 | 商機狀態選項寫死（_STATUS_OPTIONS = [洽談中, 成案, 未成案, 暫擱置]） | none | P1 | ops | open | |
| CFG-086 | K10 | backend/modules/netplan/api.py:58 | 網路規劃狀態列表寫死（_STATUSES = (規劃中, 已確認, 已交付)） | none | P1 | none | open | |
| CFG-087 | K10 | frontend/js/case-management-dispatch.js:845 | 狀態→badge 顏色對照表重複貼在多個頁面（同一行複製 5 次）（{草稿:badge--draft, 待審核:badge--pending, 簽核中:badge--signing, 已核准:badge--approved, 已駁回:badge--rejected, 已作廢:badge--lost}；同樣一行重複於 case-management-fin.js:699、:802、case-management-shipping.js:471、pages/payment-request-form.html:394） | none（CSS badge--* class 已集中，僅 status→class 映射重複） | P1 | none | open | |
| CFG-088 | K10 | frontend/pages/completion-note-form.html:455 | 完工單狀態顏色以硬編碼十六進位色（已核准 #DCFCE7/#15803D；待審核/簽核中 #FEF3C7/#92400E（js/case-management-completion.js:146-147 用 badge-green/badge-amber；exec.js:141-143、206-208 用 var(--success)）） | none | P2 | none | open | |
| CFG-089 | K10 | frontend/pages/quotations.html:653 | 報價單狀態顯示文字與顏色（待審核顯示『審核中』）寫死（待審核→{text:'審核中',cls:'badge--pending'}；quotation-form.html:806/:821 另一份 map） | none | P2 | none | open | |
| CFG-090 | K10 | backend/helpers/procurement.py:30 | 採購建議狀態序列寫死（建議→已下單→已到貨）（STATUS_SEQUENCE = (STATUS_SUGGESTED, STATUS_ORDERED, STATUS_RECEIVED)） | none | P4 | ops | open | |
| CFG-091 | K10 | backend/modules/lodging/search.py:20 | 住宿報價單位（{per_night:每晚, per_person:每人}） | none | P4 | none | open | |
| CFG-092 | K10 | backend/trail.py:502 | 稽核軌跡的狀態標籤、動作標籤、模組標籤集中寫死表（STATUS_LABELS = {…}（ACTION_LABELS :222、MODULE_LABELS :62、KIND_LABELS :294）；helpers/audit.py:36 _MODULE_LABELS 重複） | none | P4 | none | open | |
| CFG-093 | K11 | backend/modules/case/api/case_extra_expenses.py:81 | 額外支出可編輯／可刪除狀態寫死為 草稿＋已駁回（編輯、刪除、變更申請共用）（EDITABLE_STATUSES = ("草稿", "已駁回")（用於 :574 :833 :924；:1522 另有一份寫死）） | none（可掛 per-doc-type 規則表，沿用 system_settings） | P2 | money | locked-pending | |
| CFG-094 | K11 | backend/modules/arap/api/invoice_vouchers.py:470 | 發票開立簽核單刪除／送審僅草稿（status != "草稿" → 409（送審 :497）） | none | P3 | legal | locked-pending | |
| CFG-095 | K11 | backend/modules/arap/api/payment_requests.py:477 | 請款單修改／刪除／送審僅草稿（status != "草稿" → 409（刪除 :563、送審 :590）） | none | P3 | money | locked-pending | |
| CFG-096 | K11 | backend/modules/case/api/completion_notes.py:326 | 完工單編輯／刪除／送審皆僅草稿（if row["status"] != "草稿" → 409（刪除 :370、送審 :400）） | none | P3 | legal | locked-pending | |
| CFG-097 | K11 | backend/modules/case/api/quotations.py:1951 | 報價單可手動 PATCH 的狀態白名單（_STATUS_PATCH_WHITELIST = {草稿,待審核,已送出,已取消,已拒絕}） | none | P3 | ops | locked-pending | |
| CFG-098 | K11 | backend/modules/case/api/quotations.py:2502 | 報價單僅草稿可刪除（其餘 403）（if row["status"] != "草稿" → 403） | none | P3 | legal | locked-pending | |
| CFG-099 | K11 | backend/modules/case/recognition.py:416 | 認列／結算計入哪些額外支出狀態寫死（COUNTED_EXTRA_STATUSES = (待審核, 簽核中, 已核准)；accounting/ledger/periods.py:17 UNPOSTED_STATUSES） | none | P3 | money | locked-pending | |
| CFG-100 | K11 | backend/modules/subcontract/api/contractor_vouchers.py:524 | 匯款申請刪除／送審僅草稿，已送審分期申請只能作廢（status != "草稿" → 409（送審 :626）） | none | P3 | money | locked-pending | |
| CFG-101 | K11 | backend/modules/supply/api/shipping_notes.py:337 | 出貨單編輯／刪除／送審僅草稿（if row["status"] != "草稿" → 409（刪除 :363、送審 :391）） | none | P3 | money | locked-pending | |
| CFG-102 | K11 | backend/modules/accounting/voucher.py:36 | 傳票狀態集合、可編輯狀態、凍結狀態、終態寫死；有測試鎖死 EDITABLE=草稿（VOUCHER_STATUSES=(草稿,待審核,簽核中,已核准,已過帳)；EDITABLE_STATUSES=("草稿",)（:41）；_FROZEN_STATUS="已過帳"（:367）） | none（刻意鎖死，§103e 測試） | P4 | legal／money | locked-pending | |
| CFG-103 | K11 | backend/modules/case/material_approval.py:29 | 叫料單狀態集合寫死（草稿/待審核/簽核中/已核准/已退回/已取消）；取消為已核准後 admin 以上＋理由（S_DRAFT..S_CANCELLED（material_change.py:30 另有 已撤回）） | none | P4 | ops | locked-pending | |
| CFG-104 | K11 | backend/modules/case/material_coverage.py:13 | 『保留額度／計入』狀態集合寫死（影響額度與庫存預留）（LIVE_STATUSES = (草稿,待審核,簽核中,已核准)；material_payment.py:40 QUOTA_STATUSES；supply/material_link.py:18-19 RESERVED_STATUSES / SHIPPED_STATUSES） | none | P4 | money | locked-pending | |
| CFG-105 | K12 | backend/helpers/tiered_approval.py:58 | 可簽核單據類型為程式內固定清單與預設『走統一流程』分組（新類型需 register_doc_type 於程式碼登記）（APPROVAL_DOC_TYPES 9 類；DEFAULT_UNIFIED_DOC_TYPES（:66）；標籤 :68） | approval-flow-scope（已可由設定頁覆寫，僅『預設』與清單寫死） | P3 | ops | open | |
| CFG-106 | K12 | backend/modules/payroll/bonus.py:372 | 簽核層級名稱 ('覆核','主管') 寫死，超過兩層才顯示『第 N 層』（兩處重複）（_TIER_LABELS = ("覆核", "主管")（accounting/voucher.py:469 同）） | approval-flow settings（/api/settings/approval-flow*） | P3 | ops | open | |
| CFG-107 | K12 | backend/helpers/approval_queue.py:26 | 簽核佇列『進行中』狀態與單據類型標籤寫死（ACTIVE_STATUSES = (待審核, 簽核中)；routers/approval_queue.py:228 _ITEM_TYPE_LABELS） | none | P4 | ops | open | |
| CFG-108 | K12 | backend/helpers/tiered_approval.py:182 | 組織簽核鏈固定為 部門主管→處主管（兩層，本人即主管則往上、頂端止於知會）（resolve_submitter_org_chain：dept manager → division manager；ORG_ROLE_LABELS（:176）） | approval-flow settings（tiers 可選『部門主管自動』層，層數可設，org 展開邏輯寫死） | P4 | money／legal | open | |
| CFG-109 | K13 | backend/helpers/email_notify.py:1830 | 通知矩陣：module_activity 一律寄全體 admin/superadmin、audience=finance 寄財務+superadmin（收件角色寫死於程式）（audience='admins'／'finance'；_admin_emails / _finance_audience_emails（:271/:297）） | system_settings email_notify（每類型開關）、mail_recipient_overrides（收件人覆寫）、個人 mail 偏好；角色分流仍寫死 | P2 | ops | open | |
| CFG-110 | K13 | backend/modules/case/expense_notify.py:71 | 費用單據出納通知對象＝財務角色+superadmin（寫死）（helpers.auth.finance_usernames(conn)） | mail_recipient_overrides（若涵蓋此類型）；站內通知 helpers/audit._notify 無開關 | P2 | money | open | |
| CFG-111 | K13 | backend/helpers/audit.py:126 | 站內通知（_notify）無逐類型開關，收件人由各模組呼叫端決定（_notify(username, type_, ref_id, ref_label, message, link)） | mail_types registry 只管信件；站內通知偏好可延用 | P3 | ops | open | |
| CFG-112 | K14 | backend/pdf_gen.py:334 | 報價單條款區塊標題與順序（付款／交貨／保固／售後／驗收）（term_block('付款條件')…'交貨條件'…'保固條件'…'售後服務'…'驗收標準'） | quote_terms_presets（只管內容）；標題／順序可併入 module.json customization.outputs | P2 | legal | open | |
| CFG-113 | K14 | backend/modules/accounting/voucher.py:469 | 傳票簽章欄位標籤固定『覆核／主管』，第三層起『第N層』（_TIER_LABELS = ("覆核", "主管")；簽名格 製票/覆核/主管（:460-464）） | module.json customization(outputs)／FORM-DESIGNER 可承接 | P3 | none | open | |
| CFG-114 | K14 | backend/pdf_gen.py:1322 | 出貨單簽收欄「客戶簽收 · 簽章」（客戶簽收 · 簽章） | customization.outputs／doc_template | P3 | legal | open | |
| CFG-115 | K14 | backend/pdf_gen.py:2097 | 請款範圍業務語意分類（訂金款／交貨款／驗收款…）（"acceptance": "驗收款"（同表其他階段）） | default_payment_terms／quote_terms_presets | P3 | money | open | |
| CFG-116 | K14 | backend/pdf_gen.py:444 | 有效期限措辭「N 日內」（有效期限：{validDays} 日內） | customization.outputs | P3 | legal | open | |
| CFG-117 | K14 | backend/pdf_gen.py:500 | 簽章欄位標籤「買方確認 · 簽章」（買方確認 · 簽章） | customization.outputs／doc_template | P3 | legal | open | |
| CFG-118 | K14 | backend/pdf_gen.py:2572 | PDF 內狀態中文對照（待驗收／已驗收…）（"pending_acceptance": "待驗收", "accepted": "已驗收"） | none | P4 | none | open | |
| CFG-119 | K14 | backend/pdf_gen.py:94 | 報價 PDF「報價預留間接成本」列名（報價預留間接成本（運費／安裝／差旅／保固／其他）） | customization.outputs | P4 | money | open | |
| CFG-120 | K14 | frontend/pages/quotation-form.html:2184 | 報價表單版本號（單據留存、守門測試綁定）（const FORM_VERSION = 'V3.20'） | none（刻意由雜湊守門測試管控） | P4 | legal | open | |
| CFG-121 | K15 | backend/modules/case/api/case_extra_expenses.py:91 | 額外支出類別清單（工時/材料/差旅/運費/安裝/外包/其他） | expense-types designer／gl_category_map（類別需對應科目） | P1 | money | open | |
| CFG-122 | K15 | backend/helpers/part_catalog.py:10 | 料件類別與編號前綴（網通設備 NET／監控設備 CCTV／交換器 SW／伺服器·工控 SVR／線材配件 CAB／其他 OTH） | t100_export_config（部分） | P2 | ops | open | |
| CFG-123 | K15 | backend/modules/accounting/ledger/roles.py:48 | 稅務科目角色對照（進項／銷項／應付營業稅／留抵）（{1268:input_tax, 2204:output_tax, 2194:tax_payable, 1269:tax_carry}） | gl_category_map／科目表 role 欄位（bonus_payable_account_code 先例） | P2 | money | open | |
| CFG-124 | K15 | backend/modules/analytics/api/reports.py:3194 | 設備類料件類別集合（報表判斷設備）（{網通設備,監控設備,交換器,伺服器/工控}） | part_catalog 類別設定（若可編輯） | P2 | money | open | |
| CFG-125 | K15 | backend/modules/accounting/ledger/custom_events.py:31 | 自訂事件的「發票」類型字面值（{invoice,統一發票,發票,電子發票}） | none | P3 | money | open | |
| CFG-126 | K15 | backend/modules/accounting/ledger/fs_lines.py:78 | 現金流量表科目對照（_CF_BY_CODE = {…}） | 科目表 cf_line 設定 | P3 | money | open | |
| CFG-127 | K15 | backend/modules/accounting/ledger/roles.py:14 | 成本抵減科目集合（{5123,5124,5133,5134}） | 科目表屬性 | P3 | money | open | |
| CFG-128 | K15 | backend/modules/accounting/ledger/roles.py:18 | 銷貨折讓類科目對應財報行（{4113,4114,4232: IS_REV_ALLOW}） | 科目表 fs_line 設定 | P3 | money | open | |
| CFG-129 | K15 | backend/modules/accounting/api/vouchers.py:185 | 傳票類別固定「收／支／轉」（_CATEGORIES = ("收","支","轉")） | none | P4 | legal | open | |
| CFG-130 | K15 | backend/modules/accounting/ledger/roles.py:10 | 損益類科目型別集合（(revenue,cost,expense,other_income,other_expense,tax,oci)） | none（結構性，不建議開放） | P4 | legal | open | |
| CFG-131 | K15 | backend/modules/accounting/ledger/withholding.py:29 | 扣繳報表單次最多列數 2000（REPORT_LIMIT = 2000） | none | P4 | none | open | |
| CFG-132 | K16 | backend/helpers/business_days.py:20 | 國定假日／補班日表是打包的靜態 JSON（需發版更新）；年份不涵蓋時只辨識週末（靜默退化）（holidays_tw.json（行政院人事行政總處）） | none（可加 system_settings 覆寫層：公司自訂休息日／補班日） | P2 | ops | open | |
| CFG-133 | K16 | backend/modules/analytics/api/dashboard.py:32 | 儀表板依角色字面值決定能否看報價卡（superadmin/admin/sales）（role in ('superadmin','admin','sales') or 'quotation' in mods） | modules 權限（已有 'quotation' 模組鍵） | P2 | none | open | |
| CFG-134 | K16 | backend/helpers/auth.py:155 | 財務能力綁定角色 finance + superadmin，財務三鍵由角色推導（FINANCE_ROLES=('superadmin','finance'); keys cashier/finance/financial_view） | system_settings finance_via_effective（off/shadow/on，helpers/auth.py:163） | P3 | money | open | |
| CFG-135 | K16 | backend/helpers/auth.py:156 | 內建角色清單（驗證建立／修改使用者的 role）（FINANCE_ROLES=(superadmin, FINANCE_ROLE)；VALID_ROLES=(superadmin,admin,sales,engineer,viewer,FINANCE_ROLE)（:158）；routers/system.py:2680 _VALID_BASE_ROLES；helpers/mail_types.py:26 ROLES） | permission matrix (1d) / custom_roles | P3 | security | open | |
| CFG-136 | K16 | backend/helpers/case_roles.py:9 | 案件角色固定三種：填表人／業務負責／執行負責（ROLE_LABELS = {filler:填表人, sales:業務負責, executor:執行負責}） | role_labels / custom_roles（僅標籤，案件角色集合不同） | P3 | security | open | |
| CFG-137 | K16 | backend/modules/analytics/api/dashboard.py:631 | 儀表板『是否 admin 視角』判斷（role in ('superadmin','admin')（:811 同）） | none | P3 | none | open | |
| CFG-138 | K16 | backend/modules/arap/api/cashier.py:356 | 出納差額審核決定者＝財務存取（admin 直通已拿掉）（has_finance_access(user)） | duty roles / 權限矩陣專案 | P3 | money | open | |
| CFG-139 | K16 | backend/core/menu.py:26 | 選單群組固定在 core/menu_l1.json，模組不可自開群組；項目 group/order/perm 來自各 module.json（管理員已可用 apply_layout 調整排版）（群組鍵固定；perm ∈ any/superadmin/[模組鍵]） | core/menu.py:139 apply_layout + routers/platform_menu.py:51（已可編輯排版）；modules_disabled 控制顯示 | P4 | none | open | |
| CFG-140 | K16 | backend/modules/analytics/api/dashboard.py:842 | 儀表板活動動態每區塊最多列 40 筆（LIMIT 40（:858/882/900/926/949/978 同）） | none | P4 | none | open | |
| CFG-141 | K16 | backend/routers/search.py:14 | 全域搜尋每類結果數（_LIMIT = 6） | none | P4 | none | open | |

## 第 53 班回收桶列車新增的寫死值（b7 提供；預設皆＝今天的行為）

| id | 群組 | 位置 | 寫死的內容 | 目標框架 | 優先 | 風險 | 狀態 | 負責人 |
|---|---|---|---|---|---|---|---|---|
| T53-01 | 回收桶 R | helpers/recycle_bin.py:39（訊息：recyclebin/api.py:157、jobs.py:63、service.py:33,303、recycle-bin.html:14,55,259） | 保存天數 RETENTION_DAYS=30（使用者裁示 D4「固定 30 天」早於框架優先規則） | 設定 `recyclebin.retention_days`，預設 30，上下限在登錄；訊息改讀設定 | P2 | ops | open | |
| T53-02 | 回收桶 R | helpers/recycle_bin.py:40-41 | 快照大小上限 MAX_SNAPSHOT_BYTES 5 MB／管理者 50 MB | 設定 `recyclebin.max_snapshot_mb`（一般／管理者） | P3 | ops | open | |
| T53-03 | 回收桶 R | recyclebin/service.py:63（依角色上限）、:106（`role != superadmin` 閘）、:328（通知名單 role='superadmin' AND active）；recyclebin/api.py:70（can_delete_approved 角色字串）；recyclebin/module.json:29（選單權限） | 角色字串決定誰能看／還原／清除／刪已核准、通知誰 | 權限矩陣能力 `recyclebin.view／restore／purge／delete_approved` ＋通知規則 | P2 | security | open（待 1d 權限矩陣） | |
| T53-04 | 回收桶 R | case/recycle_adapter.py:136 EDITABLE、:418 DELETABLE、:250、:462 狀態元組；subcontract/recycle_adapter.py:111；payroll/recycle_adapter.py:21 _NOTICE_TYPES、:71 ('已付款',) | 各單據可編輯／可刪除的狀態名單、通知類型 | 單據型別狀態／規則定義（churn T1／T3） | P3 | ops | open | |
| T53-05 | 薪資 | payroll/api/payslip_approval.py:310 | 通知名單 role='superadmin' | approval_policy 通知對象（audiences） | P3 | ops | open | |
