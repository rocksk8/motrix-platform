# -*- coding: utf-8 -*-
"""LINE 事件目錄：哪些事件可以發 LINE、怎麼分組、哪些永遠不發（2026-11-13；使用者裁示「寄信有的 LINE 都要」）。

[單位] helper:line_catalog    [層] L1    [穩定度] 實作
[公開介面] BUSINESS_PERM_GROUPS, EVENT_MODULES, EXCLUDED_KEYS, EXCLUDED_OWNERS, EXCLUDED_PREFIXES, GROUP_MODULES, GROUP_ORDER, LINE_ONLY_EVENTS, WHO_OF, exclusion_reason, follows_text, group_of, is_known, kind_of, line_only_names, mail_key_of, modules_needed, name_of, needs_business_perm
[契約題] tests/test_line_events_all_2026_11_13.py
[不變式]
  ① **接線單位是「信件登記表」**（`mail_types`）：登記過的信件類型，除非被明確排除，一律可以發 LINE（預設關，由最高管理者逐項勾選）。
     不手寫 100 種清單：新模組登記新類型就自動出現；忘了處理的守門在測試（每個類型都要有分組、每個寄信入口都要有 LINE 呼叫）。
  ② **永遠排除**（使用者裁示：獎金、薪資、勞報單維持不開）：`bonus_*`、`payslip_*`、以及登記者是 `payroll` 的任何類型（日後新增的 payroll 類型預設也被擋）。
     另有兩個技術性排除（PM 2026-11-13 同意）：`system_test_mail`（信件設定測試信）、`line_quota_warning`（LINE 額度告警用 LINE 發＝耗額度，且額度滿時發不出去）。
     被排除的 key：`line_notify.event_enabled` 恆為 False、`set_event` 等一律 ValueError、設定頁與個人頁都不列。
  ③ **LINE-only 事件**（`LINE_ONLY_EVENTS`）：站內通知有、信件沒有的點（PM 同意新增，不新增 Email），設定頁標示「僅 LINE」。
     它們不是信件類型，所以「收件人設定來源」借用一個相近的信件類型（`mail_key`，例如 `dev_case_unassigned` 借 `dev_case_assigned`）：
     超級管理員在「信件與通知收件設定」對那個信件類型的覆寫，也會套用在這個 LINE 事件（收件人只有一個來源）。
  ④ **LINE 細項事件**（`kind="sub"`）：信件端只有一個泛用類型（`module_activity`，CRM 的所有更新都走它），LINE 端依操作拆成可分開勾選的事件
     （例如 `crm_case_status`＝階段變更、`crm_visit_logged`＝拜訪記錄）。信件內容與收件人完全不變。
  ⑤ 分組（`group_of`）依 key 規則對到「模組」，順序＝`GROUP_ORDER`（使用者優先順序：簽核 → 指定人員／業務開發 → 其餘）。沒對到的歸「其他」，
     測試要求**不得有任何已接線事件落在「其他」**（新增事件忘了分組會失敗）。
  ⑥ 本檔只放對照與規則，不讀寫設定、不碰資料庫；`mail_types` 在函式內才 import（email_notify → line_notify → 本檔，避免循環）。
"""

#: 永遠排除的 key 前綴（獎金／勞報單；使用者裁示）
EXCLUDED_PREFIXES = ("bonus_", "payslip_")
#: 永遠排除的登記者（薪資類模組；日後新增的 payroll 類型預設也被擋）
EXCLUDED_OWNERS = ("payroll",)
#: 技術性排除 ⇒ {key: 原因}
EXCLUDED_KEYS = {
    "system_test_mail": "信件設定測試信；LINE 有自己的「驗證 token」",
    "line_quota_warning": "LINE 額度告警用 LINE 發會耗額度，額度滿時也發不出去；維持 Email",
}

#: LINE-only／細項事件 ⇒ {key: {"name", "group", "mail_key", "line_group", "kind"}}
#:   kind "line_only"＝站內通知有、信件沒有（設定頁標「僅 LINE」）；"sub"＝信件端是泛用類型、LINE 端拆細。
#:   mail_key＝收件人設定（覆寫）借用的信件類型；line_group＝LINE 的群組收件人（None＝只發給事件收件人；"inherit"＝同 mail_key 的登記群組）。
LINE_ONLY_EVENTS = {
    "dev_case_unassigned": {"name": "業務開發案件被取消指派（前任負責人）", "group": "業務開發", "mail_key": "dev_case_assigned",
                            "line_group": None, "kind": "line_only"},
    "dev_case_deadline_changed": {"name": "業務開發案件回覆期限被調整（被指派人）", "group": "業務開發", "mail_key": "dev_case_assigned",
                                  "line_group": None, "kind": "line_only"},
    "dev_log_directive_reply": {"name": "業務開發記錄批示被回覆", "group": "業務開發", "mail_key": "dev_log_directive",
                                "line_group": None, "kind": "line_only"},
    "dispatch_file_delete_request": {"name": "承攬商報價單附件刪除申請待簽核（當層簽核人）", "group": "承攬商", "mail_key": "dispatch_submitted",
                                     "line_group": None, "kind": "line_only"},
    "settings_changed": {"name": "設定中心：高風險設定被變更／核准／生效／撤銷（只發最高管理者）", "group": "系統告警", "mail_key": "company_setup_alert",
                         "line_group": None, "kind": "line_only"},
    "crm_case_created": {"name": "業務開發：新增案件", "group": "業務開發", "mail_key": "module_activity", "line_group": None, "kind": "sub"},
    "crm_case_status": {"name": "業務開發：案件狀態（階段）變更", "group": "業務開發", "mail_key": "module_activity", "line_group": None, "kind": "sub"},
    "crm_case_progress": {"name": "業務開發：案件進度回報（量大）", "group": "業務開發", "mail_key": "module_activity", "line_group": None, "kind": "sub"},
    "crm_visit_logged": {"name": "業務開發：新增拜訪記錄（量大）", "group": "業務開發", "mail_key": "module_activity", "line_group": None, "kind": "sub"},
    "crm_log_approved": {"name": "業務開發：開發記錄審核通過", "group": "業務開發", "mail_key": "module_activity", "line_group": None, "kind": "sub"},
    "crm_case_converted": {"name": "業務開發：案件轉建報價單／估價單", "group": "業務開發", "mail_key": "module_activity", "line_group": None, "kind": "sub"},
}

#: 分組顯示順序（使用者優先順序：簽核 → 指定人員／業務開發 → 其餘）
GROUP_ORDER = ("報價單與簽核", "出貨單", "請款與開票", "承攬商", "費用與完工", "材料申請", "會計", "自訂模組",
               "業務開發", "工作事項", "案件管理", "財務提醒", "標案雷達", "系統告警", "通知與報表", "其他")

#: (分組, 完全相同的 key, key 前綴)；由上往下第一個符合的為準
_GROUP_RULES = (
    ("報價單與簽核", ("approval_request", "next_tier", "approved", "returned", "resubmit_requester", "approval_review_edit", "approval_reminder"), ()),
    ("出貨單", (), ("shipping_",)),
    ("請款與開票", (), ("payment_request_", "invoice_voucher_")),
    ("承攬商", (), ("contractor_voucher_", "dispatch_")),
    ("費用與完工", (), ("expense_", "completion_note_")),
    ("材料申請", (), ("material_",)),
    ("會計", (), ("voucher_", "ledger_action_")),
    ("自訂模組", (), ("custom_",)),
    ("業務開發", (), ("dev_case_", "dev_log_", "crm_")),
    ("工作事項", (), ("daily_task_", "range_task_")),
    ("案件管理", ("case_stage_deadline", "case_stage_deadline_manager", "case_project_overdue", "warranty_expiry", "settlement_finalized",
               "case_close_blocked", "case_change_requested", "case_closing_report"), ()),
    ("財務提醒", ("case_invoice_uploaded",), ("payable_due_",)),
    ("標案雷達", (), ("tender_",)),
    ("系統告警", ("cert_expiry", "backup_stale", "backup_error", "disk_space_low", "heartbeat_stale", "company_setup_alert",
              "auth_lockout", "geo_quota_warning", "license_expiry", "settings_changed"), ()),
    ("通知與報表", ("monthly_report", "module_activity", "user_notice"), ()),
)


#: ── 「指定的人要有該事件所屬模組的權限」（使用者裁示 2026-11-13，審查 h8 M1）──────────────────────────
#: 分組 ⇒ 需要的模組（**任一個**即可，與各模組 API 的 `require_any_module` 同一組鍵）。`()`＝不檢查模組；`"@admin"`＝角色要是管理員以上。
#: superadmin 一律通過。管理員在「誰要發」指定的人（含角色成員），**沒有這組權限就不發**（設定時擋下、發送時再查一次：權限被拿掉的人自動不發）。
#: 對照來源：各 API 的 require_any_module 字面值；「自訂模組」的權限是動態的（建構器），目前不檢查模組、只要在職。
GROUP_MODULES = {
    "報價單與簽核": ("quotation", "case_manage"),
    "出貨單": ("quotation", "case_manage"),
    "請款與開票": ("case_manage", "finance", "cashier", "quotation"),
    "承攬商": ("procurement", "case_manage", "contractor_list"),
    "費用與完工": ("case_manage", "quotation", "expense_forms"),
    "材料申請": ("case_manage", "quotation", "project_manage"),
    "會計": ("finance", "cashier"),
    "自訂模組": (),
    "業務開發": ("dev_crm",),
    "工作事項": ("daily_task", "case_manage"),
    "案件管理": ("case_manage", "quotation"),
    "財務提醒": ("finance", "cashier", "case_manage"),
    "標案雷達": ("tender_radar",),
    "系統告警": ("settings",),
    "通知與報表": ("@admin",),
    "其他": ("@admin",),
}
#: 這些分組的「業務收件人」（例如案件的業務負責人與主管）本身也要有該分組的模組權限才發 LINE（2026-11-13，PM 裁示；比照「指定的人」的規則）。
#: 沒有權限的人 LINE 不發（Email 照舊，行為不變）；原因：LINE 內容是業務開發案件摘要，沒有「業務開發」權限的人在系統裡本來就看不到這些案件。
BUSINESS_PERM_GROUPS = ("業務開發",)
#: 個別事件覆寫（優先於分組）
EVENT_MODULES = {
    "monthly_report": ("reports",),
    "user_notice": (),
}


def modules_needed(key: str) -> tuple:
    """這個事件要求「指定的人」具備的模組（任一個）；`()`＝不檢查；含 `"@admin"`＝角色要是管理員以上。"""
    if key in EVENT_MODULES:
        return EVENT_MODULES[key]
    return GROUP_MODULES.get(group_of(key), ("@admin",))


def needs_business_perm(key: str) -> bool:
    """這個事件的「業務收件人」要不要也檢查模組權限（見 `BUSINESS_PERM_GROUPS`）。"""
    return group_of(key) in BUSINESS_PERM_GROUPS


def _mt():
    from . import mail_types as mt          # 惰性 import（見檔頭 ⑥）
    return mt


def exclusion_reason(key: str, mail_type=None) -> str:
    """這個 key 為什麼不能發 LINE；空字串＝可以。`mail_type` 沒給就去登記表查（沒登記＝看 key 本身）。"""
    if not isinstance(key, str) or not key:
        return "沒有事件代碼"
    if key.startswith(EXCLUDED_PREFIXES):
        return "獎金、薪資、勞報單類通知不提供 LINE（使用者裁示）"
    if key in EXCLUDED_KEYS:
        return EXCLUDED_KEYS[key]
    t = mail_type if mail_type is not None else _mt().get(key)
    if t is not None and getattr(t, "owner", "") in EXCLUDED_OWNERS:
        return "獎金、薪資、勞報單類通知不提供 LINE（使用者裁示）"
    return ""


def is_known(key: str) -> bool:
    """可以發 LINE 的事件：LINE-only／細項事件，或「已登記的信件類型且沒被排除」。"""
    if not isinstance(key, str) or not key:
        return False
    if key in LINE_ONLY_EVENTS:
        return not exclusion_reason(key)
    t = _mt().get(key)
    return t is not None and not exclusion_reason(key, t)


def kind_of(key: str) -> str:
    """"mail"＝信件類型的 LINE 通道；"line_only"＝僅 LINE；"sub"＝LINE 細項（信件是泛用類型）。"""
    return LINE_ONLY_EVENTS.get(key, {}).get("kind", "mail")


def mail_key_of(key: str) -> str:
    """收件人設定（覆寫）的來源信件類型；一般事件就是自己。"""
    return LINE_ONLY_EVENTS.get(key, {}).get("mail_key") or key


#: LINE-only／細項事件「原本收件人」的說明（依事件本身語意決定，**不借用任何 Email 收件設定**；審查 h8 M3）。設定頁顯示用。
WHO_OF = {
    "dev_case_unassigned": "被取消指派的前任負責人",
    "settings_changed": "全部在職最高管理者（只發高風險設定：資安／金額／法規）",
    "dev_case_deadline_changed": "被指派人",
    "dev_log_directive_reply": "下批示的人",
    "dispatch_file_delete_request": "當層簽核人（沒有簽核層級時為最高管理者）",
    "crm_case_created": "案件相關人員（業務負責人與主管，不含操作者本人）",
    "crm_case_status": "案件相關人員（業務負責人與主管，不含操作者本人）",
    "crm_case_progress": "案件相關人員（業務負責人與主管，不含操作者本人）",
    "crm_visit_logged": "案件相關人員（業務負責人與主管，不含操作者本人）",
    "crm_log_approved": "案件相關人員（業務負責人與主管，不含操作者本人）",
    "crm_case_converted": "案件相關人員（業務負責人與主管，不含操作者本人）",
}


def follows_text(key: str) -> str:
    """設定頁每個事件的「收件人依循哪個設定」說明。Email 類型＝同名 Email 通知的收件設定；LINE-only／細項＝事件本身（不跟任何 Email 設定）。"""
    if kind_of(key) == "mail":
        return "原本收件人：與這則 Email 通知的收件設定相同（在「Email 通知」頁調整）；LINE 只是多一個管道。"
    return "原本收件人：" + WHO_OF.get(key, "由事件本身決定") + "。這則通知不跟任何 Email 收件設定，要調整請用「指定誰要發」。"


def name_of(key: str) -> str:
    if key in LINE_ONLY_EVENTS:
        return LINE_ONLY_EVENTS[key]["name"]
    t = _mt().get(key)
    return t.name if t is not None else key


def group_of(key: str) -> str:
    """事件所屬的設定頁分組（模組）。沒對到＝「其他」。"""
    if key in LINE_ONLY_EVENTS:
        return LINE_ONLY_EVENTS[key]["group"]
    for label, exact, prefixes in _GROUP_RULES:
        if key in exact or (prefixes and key.startswith(prefixes)):
            return label
    return "其他"


def line_only_names() -> tuple:
    return tuple(LINE_ONLY_EVENTS)
