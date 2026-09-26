"""共用的 tiers 依序簽核純邏輯（2026-08-22）。

報價單／出貨單／承攬商匯款申請／開票申請憑據四個 router 原本各自複製一份
幾乎逐字相同的版本——這裡只抽出「沒有副作用、判斷用」的部分集中維護，
真正的 side effect（DB 寫入、通知、PDF 產生、庫存扣減、行事曆推送等）仍留在
各自 router 裡，這個模組不碰 FastAPI（不拋 HTTPException），呼叫端自己決定
要怎麼包裝錯誤訊息。

這次抽出的直接理由：架構檢查時發現 shipping_notes.py 沒套用到稍早在
contractor_vouchers.py／invoice_vouchers.py 修好的兩個簽核漏洞（見
MOTRIX-ERP-QUICK.md 2026-08-22 changelog）——邏輯重複四份、改一個地方
其餘三個要記得改，這次就是真的漏掉一個地方，證實了共用的必要性。

⚠️ 未來開發保留：目前 tiers 完全是「逐一手動挑選簽核人員」，尚未整合
`routers/org_structure.py` 的處/部門組織架構。`divisions.manager_user_id`／
`departments.manager_user_id` 已經是刻意為此保留的欄位（2026-08-22/
2026-08-22e），未來若要支援「依部門/處自動列入主管簽核」，應該在這個模組
新增對應的純函式（例如把某部門主管展開成一個 tier 的 approver），維持
「這裡不碰 FastAPI、不做 side effect」的既有分工，不要把組織架構查詢邏輯
直接寫進四個 router 裡。
"""
import json
import logging
from datetime import date
from typing import Optional

from .settings import _get_setting

_logger = logging.getLogger(__name__)

# 文件類型可選擇「走統一流程」或「獨立設定」（2026-08-28 新增，見
# system.py 的 approval_flow_scope 設定＋前端 approval-settings.html 多選選單）。
# scope 沒有記錄某個 doc_type 時，套用這裡的預設分組——對應 2026-08-24 統一前後的
# 既有事實：報價單／出貨單／發票開立簽核單／請款單預設走統一流程，承攬商匯款申請
# 預設維持獨立（本來就有自己的 contractor_voucher_approval_flow）。
# 2026-09-11 新增 "extra_expense"（案件額外支出送審）。使用者要的是「共用分層簽核
# 並可獨立設定」——這兩件事在現有機制裡剛好就是：列進 APPROVAL_DOC_TYPES 讓簽核
# 設定頁看得到它、同時放進 DEFAULT_UNIFIED_DOC_TYPES 讓它預設走統一流程，之後在
# 設定頁把它從套用範圍取消勾選就會切成自己的 extra_expense_approval_flow。
# 2026-09-23 新增 "voucher"（會計傳票，`AS2`）。使用者原話：「**傳票的簽核需要
# 在簽核設定中出現**」。
#
# 🔴 這一項推翻了 `§161` 的「傳票不接 approval_settings」——
#    那個裁定是從「跟坊間正式傳票一樣」推出「簽核流程也要寫死」，
#    **而使用者那句是在講版面**（那張實例 PDF 上的三格）。
#    ⇒ 「兩層」是**預設值不是常數**，要改的是**它從哪裡來**。
#
# ☠️ **命名衝突**：這裡已經有 `invoice_voucher`（發票開立簽核單）與
#    `contractor_voucher`（承攬商匯款申請）⇒ 三個都叫 voucher，
#    而它們是**三種不同的單據**。標籤上必須看得出來：
#    改錯一個不會報錯 —— 它只是讓另一種單據換了簽核鏈。
#
# ⚠️ **刻意不放進 `DEFAULT_UNIFIED_DOC_TYPES`**（規格 §4 標為待使用者裁）：
#    放進去的話，傳票會與報價單／出貨單共用同一條簽核鏈，而改那一條的人
#    不會知道自己也改了會計傳票。⇒ 預設各走各的，要共用再到設定頁勾選。
#    📌 這是**可逆的預設值**：勾一下就合併，而反過來（預設合併之後拆開）
#    要先有人發現它們被合在一起了。
APPROVAL_DOC_TYPES = ["quotation", "shipping", "invoice_voucher", "payment_request",
                      "contractor_voucher", "extra_expense", "completion",
                      "voucher", "bonus"]
# 🔴 `BN8`：`bonus`（獎金分潤單）**不進來** —— A `§234` 裁：猜錯的代價不對稱時
#    先做可逆的那一邊。進了統一流程 => 獎金分潤單與報價單／出貨單共用同一條簽核鏈，
#    而改那一條的人不會知道自己也改了獎金；不進 => 自己一條
#    `bonus_approval_flow`。勾一下就能合併，而反過來（預設合併之後要拆開）
#    要先有人發現它們被合在一起了 —— 所以先不合併。
DEFAULT_UNIFIED_DOC_TYPES = {"quotation", "shipping", "invoice_voucher", "payment_request",
                             "extra_expense", "completion"}
APPROVAL_DOC_TYPE_LABELS = {
    "quotation":         "報價單",
    "shipping":          "出貨單",
    "invoice_voucher":   "發票開立簽核單",
    "payment_request":   "請款單",
    "contractor_voucher": "承攬商匯款申請",
    "extra_expense":     "案件額外支出",
    "completion":        "完工單",
    # 🔑 不是「傳票」—— 三個 doc type 都叫 voucher，而設定頁上看得出來
    #    才不會改錯。只有這一個是**會計傳票**。
    "voucher":           "傳票（會計）",
    "bonus":             "獎金分潤單",
}


def approval_flow_setting_key(doc_type: str, scope: dict) -> str:
    """依 approval_flow_scope 設定解析某文件類型送審當下該讀寫哪把 system_settings
    key：scope[doc_type] 為 True（或沒設定時的預設分組）就是走 unified_approval_flow，
    否則是該類型自己的 {doc_type}_approval_flow。純判斷、不碰 DB，呼叫端自己先把
    scope 讀出來傳進來（比照本模組其餘函式的既有分工）。"""
    is_unified = scope.get(doc_type, doc_type in DEFAULT_UNIFIED_DOC_TYPES)
    return "unified_approval_flow" if is_unified else f"{doc_type}_approval_flow"


def resolve_active_flow_setting(doc_type: str) -> dict:
    """一行拿到某文件類型「當下生效」的 flow 設定字典：讀 approval_flow_scope→
    解出該類型現在該讀哪把 key→讀出那把 key 的內容。取代原本五個 router 十個
    呼叫點（送審端點＋approve 的無自訂 tiers fallback 各一次）各自重複的「讀
    scope、再呼叫 approval_flow_setting_key()」兩行（2026-08-28 code review
    抓到的重複，見 MOTRIX-ERP-QUICK.md §12 同日 changelog）。"""
    scope = _get_setting("approval_flow_scope", {}) or {}
    key = approval_flow_setting_key(doc_type, scope)
    return _get_setting(key, {"tiers": []}) or {}


def active_tiers(appr: dict) -> list:
    return appr.get("tiers") or []


def current_tier_idx(appr: dict) -> int:
    return appr.get("currentTier") or 0


class UnresolvedManagerError(Exception):
    """部門主管自動簽核層在送審當下無法解析（部門不存在／未設主管／主管已停用）。
    呼叫端（各 router 的送審端點）自己 catch 並包成 HTTPException(400, str(e))，
    這個模組維持不碰 FastAPI 的既有分工。"""


def resolve_department_manager(conn, department_id: int) -> Optional[dict]:
    """查某部門目前的主管，回傳 {userId, username, displayName} 或 None
    （部門不存在／未設主管／主管帳號已停用時皆回傳 None，呼叫端自行決定
    要不要當錯誤處理——這裡本身不拋例外）。"""
    row = conn.execute("""
        SELECT u.id, u.username, u.display_name
        FROM departments d
        JOIN users u ON u.id = d.manager_user_id
        WHERE d.id=? AND u.active=1
    """, (department_id,)).fetchone()
    if not row:
        return None
    return {"userId": row["id"], "username": row["username"], "displayName": row["display_name"] or row["username"]}


def resolve_division_manager(conn, division_id: int) -> Optional[dict]:
    """查某處目前的主管，回傳 {userId, username, displayName} 或 None
    （處不存在／未設主管／主管帳號已停用時皆回傳 None）。跟
    resolve_department_manager() 對稱，2026-08-22h 新增。"""
    row = conn.execute("""
        SELECT u.id, u.username, u.display_name
        FROM divisions v
        JOIN users u ON u.id = v.manager_user_id
        WHERE v.id=? AND u.active=1
    """, (division_id,)).fetchone()
    if not row:
        return None
    return {"userId": row["id"], "username": row["username"], "displayName": row["display_name"] or row["username"]}


ORG_ROLE_LABELS = {
    "department_manager": "部門主管",
    "division_manager":   "處主管",
}


def resolve_submitter_org_chain(conn, requester_username: str) -> list:
    """申請人的**組織簽核鏈**，由下往上一層一筆（部門主管 → 處主管），
    2026-09-15 改版（使用者裁示：「簽核要按照組織流程簽核…他自己簽核兩次，
    我這邊只做知會」）。

    規則：
    1. 先解析申請人所屬部門的主管，這是第一層。
    2. **主管就是申請人本人時不再「跳過換人」，而是由本人簽自己這一層**
       （回傳的項目帶 `selfApproval=True`），並繼續往上加一層處主管。
    3. 處主管也是本人（申請人已在組織職權的頂端）→ 鏈到此為止，**不再指派
       其他超級管理員當簽核人**；改由呼叫端用 `org_chain_notice_usernames()`
       知會最高管理者（見該函式）。
    4. 只要某一層解析到的不是本人，該層就是最後一層（有人比他高就由那個人簽，
       不需要再往上疊）。

    ⚠️ 2026-08-22i~2026-09-14 的舊行為是「身兼主管就往上換人、換到頂就抓一個
    別的超級管理員」——結果是**高階主管送的單一律落到另一位最高管理者頭上**，
    而且他自己在組織上的那兩關完全沒有留下簽核紀錄。新行為讓每一關都留痕
    （本人簽的那幾關標 `selfApproval`），最高管理者退居知會。

    解析不出第一層（沒歸部門／部門被刪／部門沒主管）仍然 raise
    UnresolvedManagerError 擋下送審——那是組織設定本身缺漏。但**往上那一層
    解析不到時不擋**（沒有處、處沒設主管）：第一層已經成立，流程不會空掉，
    為了一個組織架構的缺口擋住所有送審反而更糟。"""
    req = conn.execute(
        "SELECT id, username, department_id FROM users WHERE username=? AND active=1",
        (requester_username,)
    ).fetchone()
    if not req or not req["department_id"]:
        raise UnresolvedManagerError("申請人尚未歸屬任何部門，請聯絡管理員設定部門後才能送審")

    dept = conn.execute("SELECT id, name, division_id FROM departments WHERE id=?", (req["department_id"],)).fetchone()
    if not dept:
        raise UnresolvedManagerError("申請人所屬部門已不存在，請聯絡管理員確認組織架構設定")

    mgr = resolve_department_manager(conn, dept["id"])
    if not mgr:
        raise UnresolvedManagerError(f"「{dept['name']}」尚未指定主管（或主管帳號已停用），請聯絡管理員先設定部門主管")
    chain = [{**mgr, "orgRole": "department_manager", "orgUnit": dept["name"]}]
    if mgr["username"] != requester_username:
        return chain

    # 申請人自己就是部門主管 → 他簽自己那一層，再往上加一層處主管
    div_row = conn.execute("SELECT name FROM divisions WHERE id=?", (dept["division_id"],)).fetchone() \
        if dept["division_id"] else None
    div_mgr = resolve_division_manager(conn, dept["division_id"]) if dept["division_id"] else None
    if div_mgr:
        chain.append({**div_mgr, "orgRole": "division_manager",
                      "orgUnit": div_row["name"] if div_row else ""})
    return chain


def submitter_manager_tiers(conn, requester_username: str) -> list:
    """把 resolve_submitter_org_chain() 的組織鏈轉成「一層一個人」的執行期
    tier approvers 清單（外層 list = 層，內層 list = 該層簽核人）。
    本人要簽的那幾層標 `selfApproval=True`，供 UI 顯示「您同時為本層簽核人」
    與 quotations.py::_exclude_requester() 判斷「這一筆不可以被剔除」。"""
    return [
        [{**m, "selfApproval": m["username"] == requester_username,
          "status": "pending", "approvedAt": None}]
        for m in resolve_submitter_org_chain(conn, requester_username)
    ]


def org_chain_notice_usernames(conn, tiers: list, requester_username: str) -> list:
    """整份簽核流程**每一層都只有申請人本人**（組織職權已到頂，例如處主管送的單）
    時，回傳應該「知會」的其他在職超級管理員帳號清單；否則回傳空清單。

    這是 2026-09-15 改版拿掉「抓一個別的超級管理員來簽」之後的補償機制：最高
    管理者不再被迫當簽核人，但不能因此變成完全不知情——單子送出時發一則知會
    通知，他仍可用 superadmin 的退回權限介入（check_reject_permission() 允許
    superadmin 隨時退回）。純判斷、不發通知，發送端見 helpers/audit.py::
    notify_org_chain_notice()。"""
    if not requester_username or not tiers:
        return []
    for t in tiers:
        for a in (t.get("approvers") or []):
            if (a.get("username") or "") != requester_username:
                return []
    rows = conn.execute(
        "SELECT username FROM users WHERE role='superadmin' AND active=1 AND username!=?",
        (requester_username,)
    ).fetchall()
    return [r["username"] for r in rows]


def resolve_tier_approvers(conn, tier_setting: dict, requester_username: str = None) -> list:
    """展開一個 tier 設定的 approvers。同一層可以放多筆（依陣列順序輪流簽，
    跟多層簽核同一套規則，可混合手動挑人／部門主管／處主管／申請人部門主管
    動態帶入，也可以跨部門）。手動挑人的項目（沒有 sourceType）沿用既有邏輯；
    sourceType=='department_manager'/'division_manager' 的項目在送審當下即時
    查詢該部門/處目前的主管；'submitter_manager' 則走動態鏈解析——查不到
    （單位被刪、沒設主管、主管已停用）就 raise UnresolvedManagerError，讓呼叫端
    擋下送審並提示管理員先設定主管，而不是靜默跳過整層（那樣會讓一道簽核關卡
    無聲消失）。"""
    resolved = []
    for a in (tier_setting.get("approvers") or []):
        source = a.get("sourceType")
        if source == "submitter_manager":
            # 舊設定相容：內建的「申請人部門主管」層 2026-09-15 起改由
            # setting_to_active_tiers() 直接展開成組織鏈的多層（見
            # submitter_manager_tiers()），這個分支只剩下「歷史設定值裡把
            # submitter_manager 手動塞進自訂層」的情況，取組織鏈第一層
            # （申請人的部門主管，可能就是本人）。
            mgr = resolve_submitter_org_chain(conn, requester_username)[0]
            resolved.append({**mgr, "selfApproval": mgr["username"] == requester_username,
                             "status": "pending", "approvedAt": None})
        elif source == "department_manager":
            dept_id = a.get("departmentId")
            dept_row = conn.execute("SELECT name FROM departments WHERE id=?", (dept_id,)).fetchone()
            dept_name = dept_row["name"] if dept_row else f"#{dept_id}"
            mgr = resolve_department_manager(conn, dept_id) if dept_row else None
            if not mgr:
                raise UnresolvedManagerError(
                    f"此層設定為「{dept_name}」主管自動簽核，但目前該部門未指定主管"
                    f"（或主管帳號已停用），請聯絡管理員先設定部門主管"
                )
            # 申請人剛好就是這個部門的主管時**由他本人簽這一層**（標
            # selfApproval），2026-09-15 起比照組織鏈的新規則。
            # ⚠️ 2026-08-24～2026-09-14 是「靜默剔除」——結果是這道關卡整層消失
            # （空層會被 setting_to_active_tiers() 跳過），等於管理員設的一關
            # 在特定人送審時無聲蒸發，連紀錄都沒有；改成本人具名簽核比較安全。
            resolved.append({**mgr, "selfApproval": mgr["username"] == requester_username,
                             "status": "pending", "approvedAt": None})
        elif source == "division_manager":
            div_id = a.get("divisionId")
            div_row = conn.execute("SELECT name FROM divisions WHERE id=?", (div_id,)).fetchone()
            div_name = div_row["name"] if div_row else f"#{div_id}"
            mgr = resolve_division_manager(conn, div_id) if div_row else None
            if not mgr:
                raise UnresolvedManagerError(
                    f"此層設定為「{div_name}」處主管自動簽核，但目前該處未指定主管"
                    f"（或主管帳號已停用），請聯絡管理員先設定處主管"
                )
            resolved.append({**mgr, "selfApproval": mgr["username"] == requester_username,
                             "status": "pending", "approvedAt": None})
        else:
            resolved.append({
                "userId":      a.get("userId"),
                "username":    a["username"],
                "displayName": a.get("displayName", a["username"]),
                "status":      "pending",
                "approvedAt":  None,
            })
    return resolved


def setting_to_active_tiers(setting: dict, conn, requester_username: str = None) -> list:
    """system_settings 裡存的簽核流程設定（tiers: [{order, approvers:[...]}]，
    每個 approver 是手動挑選的使用者或 sourceType='department_manager'／
    'division_manager'／'submitter_manager' 的自動簽核項目）轉成送審當下要
    寫進 approval.tiers 的「執行期」格式。跳過展開後沒有簽核人的層，避免卡在
    一個永遠不會有人簽的空層——但主管解析失敗會直接 raise UnresolvedManagerError
    （不會走到「跳過」這條路），因為那代表設定本身有問題，應該擋下送審而不是
    悄悄少一層。

    「申請人部門主管自動簽核」（2026-08-22i）是系統內建、預設一律套用的第一層——
    setting.get("includeSubmitterManagerTier", True) 沒有這個 key 時視為 True，
    管理員要在簽核設定頁明確關掉才會存 False，符合「內建但可移除」的需求。

    ⚠️ 2026-08-28 修正：先前的過濾條件檢查的是「設定裡這層有沒有 approver 項目」
    （恆真——department_manager/division_manager 項目本身一定有 1 筆），而不是
    「展開後這層實際解析出幾位簽核人」。當管理員手動指定的部門/處主管層，剛好
    解析到的主管就是申請人自己時，resolve_tier_approvers() 會把該筆靜默排除
    （避免自簽），但這層仍會以「approvers: []」的空層之姿留在回傳結果裡——
    check_approve_permission() 對空層永遠回傳「無待簽核人員」，任何人（含
    superadmin）都無法通過，等同卡死。改成依「展開後」的結果過濾，讓這層照
    docstring 原意直接跳過，並重新編號 order 讓陣列保持連續。

    ⚠️ 2026-09-15 改版：內建那一層不再是「一層一個人」，而是展開成申請人的
    **組織鏈**（部門主管 →（本人身兼部門主管時再加）處主管），見
    resolve_submitter_org_chain()。一般員工的結果跟以前完全一樣（只有部門主管
    那一層）；差別只出現在「申請人自己就是主管」的情況。"""
    result = []
    if setting.get("includeSubmitterManagerTier", True):
        for approvers in submitter_manager_tiers(conn, requester_username):
            result.append({"order": len(result), "approvers": approvers})
    for t in (setting.get("tiers") or []):
        if not (t.get("approvers") or []):
            continue
        resolved = resolve_tier_approvers(conn, t, requester_username)
        if resolved:
            result.append({"order": len(result), "approvers": resolved})
    return result


def first_pending_approver(tier: dict) -> Optional[dict]:
    return next((a for a in (tier.get("approvers") or []) if a.get("status") != "approved"), None)


def active_delegators_for(conn, delegate_username: str, today: Optional[str] = None) -> set:
    """回傳目前（today，預設今天）誰把簽核代理權指派給 delegate_username——也就是
    delegate_username 現在可以代替誰簽核/退回（2026-08-28 新增，見 db.py
    _m067_approval_delegates()）。conn 為 None 時直接回傳空集合，供呼叫端在
    還沒有資料庫連線的情境下安全跳過（例如尚未確定要不要做代理判斷的呼叫點）。"""
    if conn is None:
        return set()
    today = today or date.today().isoformat()
    rows = conn.execute("""
        SELECT delegator_username FROM approval_delegates
        WHERE delegate_username=? AND active=1 AND start_date<=? AND end_date>=?
    """, (delegate_username, today, today)).fetchall()
    return {r["delegator_username"] for r in rows}


def check_approve_permission(tiers: list, ct_idx: int, username: str, conn=None):
    """approve 用的嚴格版：必須是當層「排序最前面的未簽核人」才能動作，或是
    該未簽核人目前有效的簽核代理人（conn 有傳入時才會檢查代理權，見
    active_delegators_for()——維持這個函式呼叫端沒有 conn 時的既有行為不變）。
    回傳 (ok, status_code, error_message)：ok=True 時後兩者為 None；ok=False 時
    呼叫端直接拿 status_code/error_message 去包 HTTPException(status_code, error_message) 即可
    （狀態碼跟訊息逐一比照四個 router 原本各自的寫法，不引入新的行為差異）。"""
    if ct_idx >= len(tiers):
        return False, 400, "所有層已完成"
    tier = tiers[ct_idx]
    approvers = tier.get("approvers") or []
    delegated_for = active_delegators_for(conn, username)

    def _matches(a):
        return a["username"] == username or a["username"] in delegated_for

    is_in_tier = any(_matches(a) for a in approvers)
    if not is_in_tier:
        pending_names = "、".join(
            a.get("displayName") or a["username"] for a in approvers if a.get("status") != "approved"
        ) or "（無待簽核人員）"
        return False, 403, f"此層需由以下人員簽核：{pending_names}"
    fp = first_pending_approver(tier)
    if not fp:
        return False, 400, "此層所有簽核人員已完成"
    if not _matches(fp):
        next_name = fp.get("displayName") or fp["username"]
        return False, 403, f"請等待 {next_name} 先完成簽核（簽核順序固定）"
    return True, None, None


def plan_self_cascade(tiers: list, ct_idx: int, username: str, conn=None) -> list:
    """同一個人連續當好幾層簽核人時，**從 ct_idx 的下一層起**算出他可以一口氣
    一起完成的層索引清單（2026-09-15 使用者要求：「某位主管同時為兩層以上簽核人，
    只要跳通知做確認，可直接簽核兩次以上，避免重複簽核兩次的狀態」）。

    純計算、不改動 tiers。條件刻意保守，只收「簽下去之後這一層一定完成」的層：
    - 預設語意（報價單／出貨單／請款單…：當層所有人都簽完才換層）：該層**剩下
      的未簽核人只有他自己**（或他目前代理的人）。若還有別人要簽，往下一層跨過去
      就等於替別人決定，一律停在這裡。
    - 2026-09-25：原本另有 `tier_completes_on_first=True`（案件額外支出「當層任一人簽即通過」：
      他是該層簽核人之一即可）。使用者裁示同層每一位都要依序簽完 ⇒ 那個語意會替同層的別人簽，已移除。

    回傳的是連續的層索引（例：ct_idx=0、回 [1] 代表第 2 層也可以一起簽掉）。"""
    delegated_for = active_delegators_for(conn, username)

    def _matches(a):
        return (a.get("username") == username) or (a.get("username") in delegated_for)

    plan = []
    idx = ct_idx + 1
    while idx < len(tiers):
        approvers = (tiers[idx] or {}).get("approvers") or []
        pending = [a for a in approvers if a.get("status") != "approved"]
        if not pending:
            break
        if not all(_matches(a) for a in pending):
            break
        plan.append(idx)
        idx += 1
    return plan


def cascade_self_tiers(tiers: list, ct_idx: int, username: str, now: str, conn=None) -> list:
    """plan_self_cascade() 的「預設語意」版本 ＋ 實際蓋章：把可以一起簽掉的層
    裡屬於自己（或被代理人）的未簽核項目標記為 approved，回傳被一併簽掉的層索引。
    呼叫端只要把 currentTier 推進 `1 + len(回傳值)` 層，其餘（通知下一層、
    all_done 判定）沿用原本的寫法即可。"""
    plan = plan_self_cascade(tiers, ct_idx, username, conn=conn)
    display = _display_name(conn, username)
    for ti in plan:
        for a in (tiers[ti].get("approvers") or []):
            if a.get("status") != "approved":
                a["status"] = "approved"
                a["approvedAt"] = now
                a["cascadedFrom"] = ct_idx
                # 2026-09-25：只加欄位、不改判斷——紀錄要看得出是誰蓋的（代理時記替誰簽）
                a["approvedBy"] = username
                a["approvedByDisplay"] = display
                if a.get("username") and a.get("username") != username:
                    a["onBehalfOf"] = a["username"]
    return plan


def _display_name(conn, username: str) -> str:
    if conn is None:
        return username
    try:
        r = conn.execute("SELECT display_name FROM users WHERE username = ?", (username,)).fetchone()
    except Exception:
        return username
    return ((r[0] if r else "") or "").strip() or username


def sign_first_pending(tier: dict, user: dict, now: str, conn=None) -> bool:
    """當層「排序最前面的未簽核人」蓋章（呼叫端已用 check_approve_permission 確認他就是那個人或其代理人），
    回傳這一層是否已全數簽完。同層多人依序輪流簽、全數 approved 才算完成（共用規則）。"""
    approvers = tier.get("approvers") or []
    fp = first_pending_approver(tier)
    fp["status"] = "approved"
    fp["approvedAt"] = now
    fp["approvedBy"] = user["username"]
    fp["approvedByDisplay"] = user.get("display_name") or _display_name(conn, user["username"])
    if fp.get("username") != user["username"]:
        fp["onBehalfOf"] = fp.get("username")
    return all(a.get("status") == "approved" for a in approvers)


def check_reject_permission(tiers: list, ct_idx: int, user: dict, conn=None):
    """reject 用的寬鬆版：當層任一簽核人（或其目前有效的簽核代理人，見
    check_approve_permission() 同一段說明）或 superadmin 皆可退回（不要求排序，
    退回不像核准需要嚴格依序，任何一個當層相關人員發現問題都該能先擋下來）。
    回傳 (ok, status_code, error_message)，同上約定。"""
    if tiers:
        tier = tiers[ct_idx] if ct_idx < len(tiers) else {}
        approvers = tier.get("approvers") or []
        delegated_for = active_delegators_for(conn, user["username"])
        is_in_tier = any(
            a["username"] == user["username"] or a["username"] in delegated_for for a in approvers
        )
        if not is_in_tier and user["role"] != "superadmin":
            return False, 403, "無退回權限（非當層簽核人員）"
        return True, None, None
    if user["role"] != "superadmin":
        return False, 403, "僅超級管理員可執行此操作"
    return True, None, None


def check_no_tier_self_approval(conn, appr: dict, user: dict) -> Optional[str]:
    """無簽核層設定（superadmin fallback）情境下，檢查申請人是否想自行審核
    自己的申請。回傳 None 表示可以放行；回傳字串表示應該擋下（訊息內容即為
    錯誤訊息）。逃生條款：申請人是目前唯一在職的最高管理者時允許自簽，
    否則會永久卡死無人可簽。"""
    if appr.get("requestedBy") != user["username"]:
        return None
    other_admin = conn.execute(
        "SELECT 1 FROM users WHERE role='superadmin' AND active=1 AND username!=? LIMIT 1",
        (user["username"],),
    ).fetchone()
    if other_admin:
        return "申請人不得自行審核，請由其他最高管理者審核"
    return None


# ── 簽核格的帳號 → 顯示名稱（2026-09-26 自 M06 helpers/voucher.py 下沉；傳票與獎金分潤單共用）──

def resolve_display_names(conn, slots):
    """`JV13`：`signatures_of()` 的 `by` 存的是 **username**（穩定識別、
    `_user_name()` 寫入的就是它），而印在紙上／畫面上的要是**顯示名稱**。

    ## 🔴 修的是輸出這一層，不改存的值

    ```
    signatures_of()          仍然回 username —— 那是它的職責（讀簽核紀錄）
    get_voucher() 的回傳值    包一層，把 by 換成顯示名稱
    ```
    ⚠️ 兩者混在一起會兩頭不討好：`signatures_of()` 若直接回顯示名稱，
       它就不再是「簽核紀錄的原始值」，而變成一個**跟查詢時機綁定**的東西
       （使用者改名之後，舊的 `approval_json` 裡沒有任何欄位需要跟著動，
       這裡永遠查的是**現在**的顯示名稱）。

    ⚠️ **查不到顯示名稱時落回 username，不要印空白**（`STATE.md §257`
       JV13 逐字）—— 空白比印一個帳號更難查（帳號至少查得到是誰）。

    📌 這裡才用得到 `conn`，`signatures_of()` 本身仍然不碰資料庫
       （模組開頭的原則：純邏輯，可以直接餵值問它，不必先造一個 DB）。

    🔴 `BN7` 沿用：這支對 `slots` 的形狀（`{格名: {by, at}}`）沒有任何
    傳票專屬的假設，`modules/payroll/bonus_pdf.py` 直接 import 這一支處理
    `bonus_signatures_of()` 的輸出，不重寫一份——原本的底線 `_` 已拿掉
    （原本只有一個呼叫端，現在是共用工具，保留底線會誤導成「模組內部
    專用，不可外部 import」）。
    """
    usernames = {(v or {}).get("by") for v in slots.values()} - {"", None}
    if not usernames:
        return slots
    placeholders = ",".join("?" for _ in usernames)
    rows = conn.execute(
        "SELECT username, display_name FROM users WHERE username IN (%s)"
        % placeholders, tuple(usernames)).fetchall()
    names = {r["username"]: (r["display_name"] or r["username"]) for r in rows}
    out = {}
    for label, cell in slots.items():
        cell = dict(cell or {})
        by = cell.get("by") or ""
        if by:
            cell["by"] = names.get(by, by)
        out[label] = cell
    return out


def steps_to_tiers(steps: list) -> list:
    """Convert old single-approver steps list to modern tiers list (no status fields).

    2026-09-26 自 M01 helpers/quotations._steps_to_tiers 下沉（M01-PLAN §3-2）；舊名在 quotations 保留為別名。"""
    return [
        {
            "order": i,
            "approvers": [{
                "userId":      s.get("userId", 0),
                "username":    s.get("username", ""),
                "displayName": s.get("displayName", s.get("username", "")),
            }],
        }
        for i, s in enumerate(steps)
    ]


# ── 簽核鏈 approval_json 的解析（2026-09-26 自 M06 helpers/voucher 下沉，主持裁示 M06-c）─────────────
# M01 的簽核佇列也要讀傳票的簽核鏈；解析放在 M06 就是 M01 → M06 的 import（M06 搬進模組後成為 L2 邊）。
# 這是純解析、沒有資料相依 ⇒ 放在 L1。helpers.voucher 保留同名別名（淘汰中）。

class ApprovalChainUnreadable(Exception):
    """簽核鏈存在而**讀不出來**。與「沒有簽核鏈」是兩件事。

    ☠️ 這兩者折疊在一起的後果不是版面錯，是**閘門靜默放行**：
    讀取失敗 -> 回 [] -> 讀起來就是「這張單不需要簽核」-> 閘門判「沒有需要簽核的關卡」-> **判定已完成** -> 放行。
    ⇒ 所以這裡**丟**，不回 `[]`、也不回 `None`（回 None 只是把同一個問題往下移一層：呼叫端一個 `or []` 就又折回去了）。
    """


def parse_approval_json(record, *, doc_label="單據"):
    """`approval_json` 的原始解析（整包 dict，含 `tiers`／`currentTier`）；單據的唯一解析入口（`JV27`）。

    ```
    沒有 approval_json   => **回 {}**（明確的「沒有設定簽核流程」）
    有而解析失敗          => **raise ApprovalChainUnreadable**（fail-closed：一律視為未簽核完成）
    ```
    `doc_label` 只用在訊息（例：「傳票」）。"""
    raw = record.get("approval_json")
    if not raw:
        return {}
    try:
        return json.loads(raw) or {}
    except (TypeError, ValueError) as exc:
        # 訊息寫出**哪一個動作**失敗，以及 **fail-closed 這個選擇本身**
        _logger.warning("%s %s 的簽核鏈解析失敗（fail-closed：一律視為**未簽核完成**）：%s",
                        doc_label, record.get("id"), exc)
        raise ApprovalChainUnreadable(
            "這張%s的簽核資料讀不出來，無法判斷是否已完成簽核。" % doc_label) from exc
