# -*- coding: utf-8 -*-
"""L1 信件類型登記表（CORE-SPEC「使用者裁示」信件與通知的收件人、用語，2026-09-26）。

每一種寄出去的信都必須在這裡（或由模組經 `register()`）登記：
key、名稱、分類（業務／簽核／系統技術）、預設收件人、影響、建議處理。

收件人（`resolve_*`，由 `helpers.email_notify` 呼叫）：
```
事件收件人   notify_* 依事件決定的人（簽核人、申請人、負責人…）
群組收件人   登記的預設群組：none（只寄事件收件人）／admins／superadmins
超級管理員在「信件與通知收件設定」頁可逐類覆寫（`OVERRIDES_KEY`）：
  default          照登記
  superadmin_only  只寄超級管理員（事件收件人也不寄）
  custom           事件收件人＋指定帳號＋指定角色（取代群組收件人）
```
- 系統技術類預設**只寄超級管理員**（一般管理員不收）。
- 個人的通知設定只能退訂自己收得到的類型（`notification_muted`），不能把自己加進受限的類型。
- 沒有登記的 key：執行時記 ERROR、只寄超級管理員（fail closed）；守門在靜態掃描時就擋下。
"""
from dataclasses import dataclass, field

CATEGORIES = {"business": "業務", "approval": "簽核", "system": "系統技術"}
GROUPS = {"none": "只寄事件相關人員", "admins": "管理員與超級管理員", "superadmins": "僅超級管理員"}
MODES = ("default", "superadmin_only", "custom")
ROLES = ("superadmin", "admin", "sales", "engineer", "user", "viewer")

#: system_settings 的鍵：{key: {"mode", "users": [...], "roles": [...]}}
OVERRIDES_KEY = "mail_recipient_overrides"

#: 主旨前綴（用語規範，MODULE-GUIDE §11）
SUBJECT_PREFIX = "【MOTRIX 系統通知】"


@dataclass(frozen=True)
class MailType:
    key: str
    name: str
    category: str           # business／approval／system
    group: str              # 預設群組收件人：none／admins／superadmins
    event: str              # 事件收件人是誰（顯示用；沒有 ⇒ ""）
    impact: str             # 內文「影響」
    action: str             # 內文「建議處理」
    owner: str = "core"     # 登記者（L1＝core；模組＝模組 key）
    extra: dict = field(default_factory=dict)


_REGISTRY = {}


def register(key, name, category, group, event, impact, action, owner="core"):
    """登記一種信件類型。同 key 重複登記 ⇒ ValueError（兩份定義在搶）。"""
    if category not in CATEGORIES:
        raise ValueError("信件類型 %s：分類 %r 不存在" % (key, category))
    if group not in GROUPS:
        raise ValueError("信件類型 %s：預設群組 %r 不存在" % (key, group))
    if category == "system" and group != "superadmins":
        raise ValueError("信件類型 %s：系統技術類的預設收件人必須是僅超級管理員" % key)
    if key in _REGISTRY and _REGISTRY[key].owner != owner:
        raise ValueError("信件類型 %s 重複登記（%s／%s）" % (key, _REGISTRY[key].owner, owner))
    _REGISTRY[key] = MailType(key, name, category, group, event, impact, action, owner)
    return _REGISTRY[key]


def get(key):
    return _REGISTRY.get(key)


def all_types():
    return list(_REGISTRY.values())


def keys():
    return list(_REGISTRY)


def subject(key, reason):
    """主旨：【MOTRIX 系統通知】分類－事由。未登記 ⇒ 分類寫「未登記」（執行時另記 ERROR）。"""
    t = _REGISTRY.get(key)
    cat = CATEGORIES[t.category] if t else "未登記"
    return "%s%s－%s" % (SUBJECT_PREFIX, cat, reason)


# ── L1 登記的類型（模組自己的類型由模組 import 時 register）─────────────────────

_A, _B, _S = "approval", "business", "system"
_APPROVE_ACT = "請登入系統，於簽核佇列開啟該單據確認內容後核准或駁回。"
_RESULT_ACT = "請登入系統查看單據目前狀態；如有疑問請洽簽核人。"
_RETURN_ACT = "請登入系統依退回說明修改內容後重新送審。"

for _k, _n, _doc in (
        ("approval_request", "報價單待審核", "報價單"),
        ("shipping_submitted", "出貨單待審核", "出貨單"),
        ("contractor_voucher_submitted", "承攬商匯款申請待審核", "承攬商匯款申請"),
        ("invoice_voucher_submitted", "開票申請憑據待審核", "開票申請憑據"),
        ("payment_request_submitted", "請款單待審核", "請款單"),
):
    register(_k, _n, _A, "none", "當層簽核人",
             "%s在您簽核之前不會進入下一個流程。" % _doc, _APPROVE_ACT)
for _k, _n, _doc in (
        ("next_tier", "報價單進入下一層審核", "報價單"),
        ("shipping_next_tier", "出貨單進入下一層審核", "出貨單"),
        ("contractor_voucher_next_tier", "承攬商匯款申請進入下一層審核", "承攬商匯款申請"),
        ("invoice_voucher_next_tier", "開票申請憑據進入下一層審核", "開票申請憑據"),
        ("payment_request_next_tier", "請款單進入下一層審核", "請款單"),
):
    register(_k, _n, _A, "none", "該層簽核人",
             "前一層已完成，%s在本層簽核之前不會繼續。" % _doc, _APPROVE_ACT)
register("approved", "報價單審核完成", _A, "admins", "申請人",
         "報價單已核准，可以對外提供。", _RESULT_ACT)
for _k, _n in (("shipping_approved", "出貨單審核完成"),
               ("contractor_voucher_approved", "承攬商匯款申請審核完成"),
               ("invoice_voucher_approved", "開票申請憑據審核完成"),
               ("payment_request_approved", "請款單審核完成")):
    register(_k, _n, _A, "none", "申請人", "單據已核准，進入後續作業。", _RESULT_ACT)
for _k, _n in (("returned", "報價單退回修改"), ("shipping_returned", "出貨單退回修改"),
               ("contractor_voucher_returned", "承攬商匯款申請退回修改"),
               ("invoice_voucher_returned", "開票申請憑據退回修改"),
               ("payment_request_returned", "請款單退回修改")):
    register(_k, _n, _A, "none", "申請人", "單據已退回，修改並重新送審之前流程暫停。", _RETURN_ACT)
register("resubmit_requester", "修改版報價單重新送審確認", _A, "none", "申請人",
         "修改版已重新進入簽核流程，原版本不再流轉。", _RESULT_ACT)
register("bonus_submitted", "獎金分潤待審核", _A, "none", "輪到的簽核人（含代理人）",
         "獎金分潤在您簽核之前不會進入待發放。", _APPROVE_ACT + "（信中不含金額，請登入查看）")
register("bonus_payout_ready", "獎金分潤核准待發放", _A, "none", "出納",
         "獎金分潤已核准，等待出納發放。", "請登入系統，於出納頁「獎金待發放」確認後標記已發放。（信中不含金額）")
register("approval_reminder", "簽核逾期催辦", _A, "superadmins", "當層簽核人",
         "單據停留在同一層超過規定工作日，後續作業延遲。", _APPROVE_ACT)
register("dev_case_delete_request", "業務開發案件刪除申請", _A, "superadmins", "",
         "案件在核准或駁回之前維持待刪除狀態。", "請登入系統，於業務開發頁確認申請理由後核准或駁回。")
register("dev_case_relink_request", "業務開發案件連結異動申請", _A, "superadmins", "",
         "案件與報價單的連結在核准之前維持原狀。", "請登入系統，於業務開發頁確認後核准或駁回。")
register("case_close_blocked", "結案被防呆機制擋下", _A, "superadmins", "待處理的承辦人",
         "案件在前置條件完成之前無法結案。", "請依信中列出的未完成項目逐項處理後再結案。")
register("case_change_requested", "已結案案件變更待審核", _A, "superadmins", "",
         "變更在審核通過之前不會套用到已結案案件。", "請登入系統，於案件頁審核變更內容後套用或退回。")

register("daily_task_assigned", "工作事項指派", _B, "none", "負責人",
         "您有新的工作事項需要處理。", "請登入系統查看工作事項內容與期限。")
register("daily_task_completed", "工作事項完成回報", _B, "admins", "主管",
         "指派的工作事項已完成。", "請登入系統確認完成內容。")
register("daily_task_overdue", "工作事項逾期未完成", _B, "admins", "負責人與主管",
         "工作事項已超過期限，相關作業延遲。", "請負責人完成或更新進度；主管請確認是否需要協助。")
register("daily_task_overdue_manager", "部門成員工作事項逾期", _B, "none", "部門主管",
         "部門成員的工作事項已超過期限。", "請確認進度並視需要調整分工。")
register("daily_task_edited", "工作事項內容已編輯", _B, "admins", "主管",
         "工作事項內容有異動。", "請登入系統確認異動內容。")
register("range_task_deadline", "區間工作事項即將到期", _B, "admins", "負責人與主管",
         "區間工作事項即將到期。", "請在期限前完成或更新進度。")
register("case_stage_deadline", "案件執行進度即將到期", _B, "admins", "負責人與主管",
         "案件階段即將到期，逾期會影響整體時程。", "請在期限前完成該階段或更新預計日期。")
register("case_stage_deadline_manager", "部門成員案件進度即將到期", _B, "none", "部門主管",
         "部門成員負責的案件階段即將到期。", "請確認進度並視需要調整人力。")
register("case_project_overdue", "案件專案期間已超期", _B, "admins", "",
         "案件已超過預定的專案期間。", "請確認案件狀態，完成結案或更新專案期間。")
register("warranty_expiry", "設備保固即將到期", _B, "admins", "業務負責人",
         "設備保固即將到期，到期後維修需另行報價。", "請聯繫客戶確認是否續約或延長保固。")
register("dev_case_stale", "業務開發案件逾期未跟進", _B, "none", "業務與規劃人員",
         "業務開發案件已超過規定天數沒有新的開發紀錄。", "請聯繫客戶並登錄開發紀錄。")
register("settlement_finalized", "成本精算完結", _B, "admins", "",
         "案件成本已精算完結，可進行獎金分潤與結案。", "請登入系統查看精算結果。")
register("case_closing_report", "案件結案報表", _B, "superadmins", "",
         "案件已結案，結案報表如附件。", "請檢閱附件；如需修正請於案件頁處理。")
register("monthly_report", "每月營運報表", _B, "superadmins", "報表收件人設定",
         "上月營運報表已產生。", "請檢閱附件或登入系統查看報表。")
register("module_activity", "模組新增與異動", _B, "admins", "",
         "系統有新增或異動的資料。", "如非預期的異動，請登入系統查看稽核紀錄。")

register("cert_expiry", "HTTPS 憑證即將到期", _S, "superadmins", "",
         "憑證到期後，使用者開啟系統時瀏覽器會出現安全性警告。", "請依系統說明更新憑證，並於更新後重新啟動服務。")
register("backup_stale", "備份已停止運作", _S, "superadmins", "",
         "超過規定時間沒有成功的備份，發生故障時可能遺失資料。", "請檢查備份排程、雲端硬碟掛載與磁碟空間，處理後確認下一次備份成功。")
register("disk_space_low", "磁碟空間不足", _S, "superadmins", "",
         "磁碟空間不足時，備份與上傳可能失敗。", "請清理暫存檔案或擴充磁碟空間。")
register("backup_error", "備份嚴重錯誤", _S, "superadmins", "",
         "本次備份沒有完成，發生故障時可能遺失資料。",
         "請確認雲端硬碟是否已掛載、本機快照（backend/db_backups/）是否存在，以及伺服器磁碟空間。")
register("geo_quota_warning", "地圖定位額度達警戒線", _S, "superadmins", "",
         "達到額度上限後，系統改用精度較低的免費定位來源；功能不會關閉。", "如需維持定位精度，請調整額度設定；下一個計費週期開始時自動恢復。")
register("system_test_mail", "測試信", _S, "superadmins", "",
         "本信僅用於確認寄信設定。", "收到本信表示寄信設定正確，無需處理。")
