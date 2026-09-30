"""「待我簽核」佇列（L1；主持裁示 2026-09-27：自 M01 搬進共用層，不列例外）。

路徑不變、前端不改：`GET /api/approval-queue`、`/count`、`/detail`、`POST /api/approval-queue/reassign`。
這裡只做彙整、可見性過濾、分組、角標計數、每案權限、案件抬頭與金額遮蔽；單據一律由擁有模組經串接點供應：
- `approval.queue_items`（IP-10）：待簽項目。M01（報價單、已結案變更、額外支出、額外支出變更、完工單）只是其中一個提供者。
- `approval.detail`（IP-93）：一筆的詳情。
- `approval.reassign`（IP-94）：轉簽時簽核鏈的讀寫。
案件資料（抬頭、項目缺的客戶／名稱）經 `case.summary`（IP-96）取；M01 不在 ⇒ 抬頭只有單號，其他模組的單照常列出。
形狀與共用邏輯見 `helpers/approval_queue.py`。
"""
import json
import logging
from collections import defaultdict
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from core import registry
from core.txn import begin_write
from db import get_db
from helpers import _require_user, _tok, _audit, _notify, active_delegators_for, can_see_financial
from helpers.approval_queue import ApprovalUnreadable, active_tiers, current_tier_idx
from helpers.case_access import SYSTEM, case_module_present, guard_case_access, is_document_approver

logger = logging.getLogger(__name__)

router = APIRouter()


# ── 彙整 ──────────────────────────────────────────────────────────────────────

def _queue_visible_to(user: dict, item: dict, delegated_for) -> bool:
    """這一筆待簽核文件該不該讓這個人看到（2026-09-15 使用者要求）。

    「簽核佇列除了管理員以上都只能看到自己的簽核佇列卡在哪邊」。所以非 admin 的
    可見範圍是兩種，其餘一律看不到：

    1. **自己送審的**——他要知道自己的單子卡在哪一關、卡在誰身上
    2. **簽核鏈裡有自己的**（含代理他人時的被代理人）——比對的是**所有層**而不是
       只有當前層：只比當前層的話，下一關才輪到的人看不到即將輪到自己的單，
       已經簽過的人也看不到後面卡住了，兩種都會讓人誤以為「沒我的事」

    為什麼過濾放在這裡、而且只有一份：單據類型由各模組提供，每種各寫一段 WHERE 條件的話，
    下一次新增類型時漏掉的那一種就是全開的——而「漏了會外洩」的規則必須是預設安全。
    集中成一條規則、套在組裝好的 items 上，新類型自動被蓋到。

    `tiers` 為空的類型（case_change 是「任一 superadmin 皆可審核」的單層設計）對
    非 admin 只會落在第 1 條，這是對的：他不可能是它的簽核人。
    """
    if (user.get("role") or "") in ("superadmin", "admin"):
        return True
    mine = {user.get("username") or ""} | set(delegated_for or [])
    if item.get("requestedBy") in mine:
        return True
    for tier in item.get("tiers") or []:
        for ap in (tier.get("approvers") or []):
            if (ap.get("username") or "") in mine:
                return True
    return False


def _on_chain(conn, user: dict, approval_raw) -> bool:
    """詳情守門「不看案件就放行」的條件：本單簽核鏈上（任何一層，含代理）或送審人（`is_document_approver`）。
    佇列（M01 不在時要不要列）與詳情守門共用這一支——「佇列列出這一筆」⇔「詳情會放行」（主持裁示 2026-09-27，AL-O3）。"""
    return bool(approval_raw) and is_document_approver(approval_raw, user, conn)


def _item_approval_raw(item: dict) -> str:
    """佇列項目 ⇒ 詳情守門看的 approval JSON（項目的 tiers 已由 `tier_fields` 正規化，含 steps 相容）。"""
    return json.dumps({"tiers": item.get("tiers") or [], "requestedBy": item.get("requestedBy") or ""}, ensure_ascii=False)


#: `_access_step` 的三種結果
OPEN, DENY, CASE_RULE = "open", "deny", "case_rule"


def _access_step(conn, user: dict, case_key, approval_raw, case_present: bool, existing=None, caseless: bool = False) -> str:
    """**佇列列出與詳情放行共用的唯一判斷**（§G5 #13：同一個函式、同一組輸入；稽核 D AL2-M1 的成因是兩邊各看各的欄位）。
    輸入＝（這張單掛的案件單號、簽核 JSON）：佇列取項目的 `linkedQuoteNo`＋tiers／requestedBy，詳情取提供者的 `quoteNo`＋`approvalRaw`
    ——兩者是同一件事，契約題 `test_queue_items_malformed_json` 逐一核對 `linkedQuoteNo == 詳情 quoteNo`。
    - 簽核鏈上的人與送審人（`_on_chain`）⇒ OPEN
    - M01 不在，或沒掛案件，或**掛的案件已不存在**（孤兒單；稽核 D 建議、主持採納）⇒ DENY（每案守門一定查無）
      `existing`：已知存在的案件單號集合（佇列一次查完）；None ⇒ 這裡查這一筆（詳情）——同一個 `_case_names`
    - 其餘 ⇒ CASE_RULE（交給 `guard_case_access`：admin+／業務／協作者／案件管理；佇列對非 admin 本來就只列簽核鏈上的人）
    - `caseless`（A2-0：單據本來就不掛案件，項目與詳情提供者都帶 `caseless: True`）：沒有案件可查 ⇒ 簽核鏈上的人與送審人（上面）＋超級管理員 ⇒ OPEN，其餘 DENY"""
    if _on_chain(conn, user, approval_raw):
        return OPEN
    if caseless:
        return OPEN if user.get("role") == "superadmin" else DENY
    if not (case_present and case_key):
        return DENY
    if case_key not in (existing if existing is not None else _case_names(conn, [case_key])):
        return DENY
    return CASE_RULE


def _detail_opens(conn, user: dict, item: dict, case_present: bool, detail_types, existing=None) -> bool:
    """佇列這一筆要不要列：這一類沒有詳情提供者 ⇒ 不歸這裡管（詳情回 400，佇列照列）；否則 `_access_step` 不是 DENY。"""
    if item.get("type") not in detail_types:
        return True
    return _access_step(conn, user, item.get("linkedQuoteNo"), _item_approval_raw(item), case_present, existing,
                        caseless=bool(item.get("caseless"))) != DENY


def _openable(conn, user: dict, items: list) -> list:
    """只留這個人點得開詳情的項目（主持裁示 2026-09-27：「佇列列出」⇔「詳情守門放行」）。"""
    case_present = case_module_present()
    detail_types = set(registry.providers("approval.detail"))
    existing = set(_case_names(conn, [it.get("linkedQuoteNo") for it in items
                                      if it.get("type") in detail_types and it.get("linkedQuoteNo")])) if case_present else set()
    return [it for it in items if _detail_opens(conn, user, it, case_present, detail_types, existing)]


def _case_names(conn, quote_nos) -> dict:
    """quote_no → case.summary 列（L1 以 `SYSTEM` 取；呼叫端已做完自己的權限判斷）。M01 不在 ⇒ {}。"""
    summary = registry.single_provider("case.summary")
    qs = sorted({q for q in quote_nos if q})
    if summary is None or not qs:
        return {}
    return {r["quote_no"]: r for r in summary(conn, SYSTEM, qs)}


def _queue_provider_items(conn) -> list:
    """IP-10 `approval.queue_items`：各單據模組提供自己的待簽項目。提供者壞掉只少那一類（記 exception）；
    模組不在 ⇒ 那一類不列。項目沒給 `customer`／`projectName` 而有 `linkedQuoteNo` ⇒ 這裡經 `case.summary` 補案件的
    客戶與名稱（M01 不在 ⇒ 空字串）。"""
    out = []
    for name, fn in sorted(registry.providers("approval.queue_items").items()):
        try:
            out.extend(fn(conn) or [])
        except Exception:                                    # noqa: BLE001
            logger.exception("待簽核佇列：提供者 %s 失敗（這一類不列出）", name)
    names = _case_names(conn, [it.get("linkedQuoteNo") for it in out
                               if it.get("linkedQuoteNo") and ("customer" not in it or "projectName" not in it)])
    for it in out:
        q = names.get(it.get("linkedQuoteNo"))
        it.setdefault("customer", (q["customer_name"] if q else "") or "")
        it.setdefault("projectName", (q["project_name"] if q else "") or "")
    return out


def _reassign_types() -> list:
    """可以轉簽的單據類型＝有 `approval.reassign` 提供者的（模組不在 ⇒ 不給轉簽，前端不顯示按鈕）。"""
    return sorted(registry.providers("approval.reassign"))


def _counts_for_me(item: dict, my_usernames: set, my_username: str, is_sa: bool) -> bool:
    """角標：這一筆是否「輪到我」。與佇列頁 `canApprove()` 一致：有簽核層 ⇒ 當層未簽的人裡有我（含代理）；
    沒有簽核層 ⇒ 任一 superadmin、自己送的不算（2026-09-15 修正：原本整批跳過，佇列列得出來而角標是 0；
    自己送的若算進來會變成按不下去的紅點）。"""
    tiers = item.get("tiers") or []
    if tiers:
        ct = item.get("currentTier") or 0
        if ct < len(tiers):
            return any(a.get("username") in my_usernames and a.get("status") != "approved"
                       for a in (tiers[ct].get("approvers") or []))
        return False
    return is_sa and (item.get("requestedBy") or "") != my_username


@router.get("/api/approval-queue")
def get_approval_queue(authorization: str = Header(None)):
    """待我簽核佇列：各模組提供的項目（IP-10）→ 可見性過濾 → 依送審人分組。

    欄位沿用報價單的名稱（quoteNo/customer/projectName/total/quoteDate/salesPerson）承載各類型資料，
    `type` 供前端分流動作按鈕與連結（見 approval-queue.html）。

    `myDelegatedFor`（2026-08-28）：目前使用者正在代理誰的簽核權限——前端 canApprove()/myPendingCount
    要一併比對，否則代理人看不到任何「輪到我」。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        my_delegated_for = sorted(active_delegators_for(conn, user["username"]))
        items = _openable(conn, user, _queue_provider_items(conn))
    finally:
        conn.close()

    # 權限過濾（2026-09-15）：過濾在分組**之前**——分組之後才過濾會留下「某某人 0 件」的空群組。
    items = [it for it in items if _queue_visible_to(user, it, my_delegated_for)]

    groups: dict = defaultdict(list)
    for item in items:
        groups[item["requestedBy"]].append(item)

    queue = []
    for username, group_items in groups.items():
        group_items.sort(key=lambda x: x["requestedAt"])
        queue.append({
            "requestedBy":        username,
            "requestedByDisplay": group_items[0]["requestedByDisplay"] if group_items else username,
            "count":              len(group_items),
            "items":              group_items,
        })
    queue.sort(key=lambda g: g["items"][0]["requestedAt"] if g["items"] else "")

    return {"queue": queue, "total": len(items), "myDelegatedFor": my_delegated_for,
            "reassignTypes": _reassign_types()}


#: 與 approval-queue.html 的 `docTypeLabel()` 同一份對照（兩處標籤要一致）。
_ITEM_TYPE_LABELS = {
    "contractor_voucher": "匯款申請", "invoice_voucher": "開票申請憑據", "shipping_note": "出貨單",
    "completion_note": "完工單", "payment_request": "請款單", "case_change": "已結案案件變更",
    "extra_expense": "案件額外支出", "extra_expense_change": "額外支出變更", "voucher": "傳票（會計）",
    "bonus_award": "獎金", "bonus_case_award": "獎金分潤", "bonus_correction": "獎金更正單", "dispatch_file_delete": "報價單附件刪除",
    "custom_module_def": "自訂模組定義", "ledger_action": "總帳申請",
}


def _item_type_label(it: dict) -> str:
    t = it.get("type")
    if t == "custom_record":
        return it.get("moduleName") or it.get("moduleKey") or "自訂模組"
    if t in _ITEM_TYPE_LABELS:
        return _ITEM_TYPE_LABELS[t]
    return it.get("typeLabel") or "報價單"      # 模組登記的新單據類型（A2-0 #2）自帶標籤；都沒有才退回舊預設


@router.get("/api/approval-queue/count")
def get_approval_queue_count(authorization: str = Header(None)):
    """topbar 角標：輪到我簽核的項目數（含「我目前代理誰」，2026-08-28）。與佇列列表同一份來源
    （`_queue_provider_items`），兩邊才對得起來。"""
    u = _require_user(authorization)
    conn = get_db()
    try:
        my_usernames = {u["username"]} | set(active_delegators_for(conn, u["username"]))
        items = _openable(conn, u, _queue_provider_items(conn))
    finally:
        conn.close()
    is_sa = u["role"] == "superadmin"
    mine = [it for it in items if _counts_for_me(it, my_usernames, u["username"], is_sa)]
    # 首頁「等我簽核」的數字與清單同一份（2026-09-30 使用者：儀表板與簽核佇列沒有連動）：
    # 清單＝角標的那些項目（最早送審的在前，最多 10 筆），不含金額（首頁不做財務遮蔽判斷）。
    mine.sort(key=lambda x: x.get("requestedAt") or "")
    return {"count": len(mine),
            "items": [{"type": it.get("type") or "", "typeLabel": _item_type_label(it),
                       "quoteNo": it.get("quoteNo") or "", "customer": it.get("customer") or "",
                       "projectName": it.get("projectName") or "",
                       "requestedByDisplay": it.get("requestedByDisplay") or it.get("requestedBy") or ""}
                      for it in mine[:10]]}


# ── 詳情（依 type 分流到擁有模組的 `approval.detail`）─────────────────────────
#
# 使用者要求（2026-09-14）：「簽核佇列內的送審資料要詳細，例如夾帶檔案，要顯示哪個案件什麼內容，
# 如果是檔案可顯示預覽，編修後的結果」。清單一次可能上百筆，每筆都去讀明細會讓開啟佇列變慢，
# 而使用者一次只看一筆 ⇒ 詳情另開這支端點。

def _case_header(conn, quote_no: str) -> dict:
    """詳情上方的案件抬頭（`case.summary`，L1 以 `SYSTEM` 取——呼叫前已經過每案守門）。M01 不在或查無 ⇒ 只有單號。"""
    q = _case_names(conn, [quote_no]).get(quote_no)
    if not q:
        return {"quoteNo": quote_no, "customerName": "", "projectName": "", "dealTag": ""}
    return {"quoteNo": q["quote_no"], "customerName": q["customer_name"] or "",
            "projectName": q["project_name"] or "", "dealTag": q.get("deal_tag") or ""}


def _guard_queue_detail(conn, user: dict, quote_no: str, approval_raw=None, caseless: bool = False) -> None:
    """簽核佇列詳情的存取守門（2026-09-14 自動安全掃描後補上）。

    詳情回傳完整內容（明細、附件路徑、變更 payload、匯款帳戶），而 `id` 是可預測的單號或小整數 ⇒
    只要求登入就是 IDOR。放行順序（先寬後嚴，因為簽核人往往不是案件的人）：
    1. **這張單據自己的簽核人**（含代理人）——他本來就該看得到要簽的東西
    2. 其餘走一般的每案規則 `guard_case_access()`（admin+／該案業務／協作者／案件管理模組、案件本身的簽核人）；
       看不到與查無同一個 404（c-case404，M01-O1）；M01 不在 ⇒ 404（`case_access` 的 fail-closed）
    """
    step = _access_step(conn, user, quote_no, approval_raw, case_module_present(), caseless=caseless)
    if step == OPEN:
        return
    if step == DENY:
        raise HTTPException(404, "denied")          # 呼叫端換成同一句「單據 {id} 不存在」並記 audit
    guard_case_access(conn, quote_no, user, allow_module="case_manage", allow_approver=True)


def _can_see_queue_money(conn, user: dict, approval_raw=None) -> bool:
    """能不能看到這筆的金額：`can_see_financial()` 或**本單簽核人**（看不到金額就沒辦法判斷該不該簽）。"""
    if can_see_financial(user):
        return True
    return bool(approval_raw and is_document_approver(approval_raw, user, conn))


_MONEY_LABELS = {"金額", "單價", "小計", "總金額", "存簿封面"}


def _mask_money(out: dict) -> None:
    """沒有財務檢視權時，把金額欄位換成說明字串而不是直接拿掉（直接拿掉像「這張單沒有金額」，更容易誤判）。"""
    out["fields"] = [
        f if f["label"] not in _MONEY_LABELS
        else {"label": f["label"], "value": "（無財務檢視權限）"}
        for f in out.get("fields") or []
    ]
    masked_items = []
    for it in out.get("items") or []:
        if isinstance(it, dict):
            it = {k: v for k, v in it.items()
                  if k not in ("amount", "subtotal", "unitPrice", "unit_cost", "price", "total")}
        masked_items.append(it)
    out["items"] = masked_items
    out["moneyMasked"] = True


#: 詳情「查無」與「看不到」同一句（AL-S1，比照 c-case404：訊息逐字相同、不帶關聯的案件單號；audit 記真正原因）
DETAIL_DENIAL_AUDIT = "approval.detail_denied"


def detail_not_found_message(doc_id) -> str:
    return "單據 %s 不存在" % doc_id


def _deny_detail(user: dict, type_: str, doc_id, reason: str):
    """記真正原因（not_found／denied）後丟同一個 404。背景寫 audit（同 case_access 的做法：呼叫端之後會關連線）。"""
    from db import spawn_bg_thread

    def _write(uid, uname, dname):
        try:
            c = get_db()
            try:
                c.execute("INSERT INTO audit_log (at,user_id,username,display_name,action,target_type,target_id,target_label,detail) "
                          "VALUES (?,?,?,?,?,?,?,?,?)",
                          (datetime.now().isoformat(), uid, uname, dname, DETAIL_DENIAL_AUDIT, type_, str(doc_id), "",
                           json.dumps({"reason": reason}, ensure_ascii=False)))
                c.commit()
            finally:
                c.close()
        except Exception:                                    # noqa: BLE001  記錄失敗不影響回應
            pass
    u = user or {}
    spawn_bg_thread(_write, args=(u.get("id"), u.get("username") or "", u.get("display_name") or ""))
    raise HTTPException(404, detail_not_found_message(doc_id))


def _open_detail(conn, user: dict, type_: str, doc_id: str) -> dict:
    """詳情的內容＋存取守門（詳情端點與 `/api/photo-token` 的簽核佇列情境共用同一支）。
    類型沒有提供者 ⇒ 400；查無或看不到 ⇒ 同一個 404（`_deny_detail`）。回提供者的原始內容（未遮蔽）。"""
    prov = registry.providers("approval.detail").get(type_)
    if prov is None:
        raise HTTPException(400, "不支援的類型（或該單據的模組未安裝）：" + str(type_))
    try:
        d = prov(conn, doc_id)
    except HTTPException as e:                           # 提供者自己的查無訊息（例：「完工單不存在」）也統一
        if e.status_code != 404:
            raise
        d = None
    if not d:
        _deny_detail(user, type_, doc_id, "not_found")
    approval_raw = d.get("approvalRaw")
    # `selfViewBy`：申請人本人不經每案守門。**只有 M01 的已結案變更（case_change）宣告**——單層「任一 superadmin」、
    # 沒有簽核鏈可比對，而申請人要看得到自己送出的內容；其他提供者不可以宣告（它會繞過每案守門）。
    if not (d.get("selfViewBy") and d["selfViewBy"] == user["username"]):
        try:
            _guard_queue_detail(conn, user, d["quoteNo"], approval_raw, caseless=bool(d.get("caseless")))
        except HTTPException as e:                       # 守門的 404 帶關聯的案件單號（會洩漏掛在哪一案）⇒ 換成同一句
            if e.status_code != 404:
                raise
            _deny_detail(user, type_, doc_id, "denied")  # 案件層的真正原因 case_access 已另記
    return d


def detail_file_paths(conn, user: dict, type_: str, doc_id: str) -> set:
    """這個人**點得開的**簽核佇列詳情 (type, id) 列出的檔案路徑（`/api/photo-token` 的簽核佇列情境，2026-09-30 P0）。
    簽核人常常不是案件的人（`_guard_queue_detail` 放行順序 1）⇒ 單看路徑的擁有單據規則會擋掉他要簽的附件；
    這裡只放行「詳情守門放行 ∧ 詳情真的列出這個路徑」。看不到 ⇒ 丟與詳情相同的 404。"""
    d = _open_detail(conn, user, type_, doc_id)
    return {f.get("path") for f in (d.get("files") or []) if isinstance(f, dict) and f.get("path")}


@router.get("/api/approval-queue/detail")
def approval_queue_detail(type: str, id: str, authorization: str = Header(None)):
    """一筆待簽核項目的完整內容：屬於哪個案件、送審了什麼、夾帶哪些檔案、改了什麼。

    內容由擁有模組提供（`approval.detail`，名稱＝type）；這裡做每案權限、案件抬頭與金額遮蔽。
    真正的動作權限（核准／退回）仍由各自的端點把關。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        d = _open_detail(conn, user, type, id)
        approval_raw = d.get("approvalRaw")
        out = {"type": type, "id": id, "title": d.get("title") or id,
               "fields": list(d.get("fields") or []), "items": list(d.get("items") or []),
               "files": list(d.get("files") or []), "changes": d.get("changes"),
               "case": _case_header(conn, d["quoteNo"])}
        # 金額遮蔽：規則與憑證流一致（見 _can_see_queue_money）
        if not _can_see_queue_money(conn, user, approval_raw):
            _mask_money(out)
            # 內嵌影像（dataUrl：存簿封面）一律拿掉——看的是「有沒有內嵌內容」，不只看 id 字串（稽核 D AP-M2）
            out["files"] = [f for f in out["files"] if not f.get("dataUrl") and f.get("id") != "passbook"]
        return out
    finally:
        conn.close()


# ── 轉簽（2026-09-14 使用者要求）────────────────────────────────────────────
#
# 「簽核代理人，增加最高權限人可以轉簽簽核佇列的內容，要註明原因跟註記這筆簽核」。
#
# 與既有「簽核代理人」（`approval_delegates`）的分工：
#   - 代理人是**事前、長期**的授權（某人請假期間由某人代簽，範圍是那個人的全部簽核）
#   - 轉簽是**事後、單筆**的處置（這一張卡住了，改由另一個人簽）
#
# **原因是必填**：轉簽等於把一筆待辦從 A 身上拿走塞給 B，沒有理由就是無從追究的
# 權限變更。原因會寫進單據的 approval.reassignLog、audit_log，並顯示在簽核佇列詳情
# 與簽核歷史裡。單據的讀寫交給擁有模組（`approval.reassign`，IP-94）。

class ReassignIn(BaseModel):
    type: str
    id: str
    to_username: str
    reason: str
    from_username: Optional[str] = None


@router.post("/api/approval-queue/reassign")
def reassign_approval(body: ReassignIn, authorization: str = Header(None)):
    """把某一筆待簽核轉給別人（限最高管理者）。

    只動**當層尚未簽核**的那個人：已經簽過的不能被換掉（那會讓簽核紀錄失真），
    後面幾層也不動（那是簽核流程設定的事，不是單筆處置）。沒有 `approval.reassign` 提供者的類型不支援
    （`extra_expense`：簽核名單在自己的欄位；`case_change`：單層「任一 superadmin」不會卡在特定人身上）。
    """
    user = _require_user(authorization, require_superadmin=True)
    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(400, "請填寫轉簽原因")
    store = registry.providers("approval.reassign").get(body.type)
    if store is None:
        # 不支援的類型，或擁有該單據的模組沒有安裝（它的單也不會出現在佇列上）
        raise HTTPException(400, "此類型不支援轉簽（或該單據的模組未安裝）：" + str(body.type))
    to_username = (body.to_username or "").strip()
    if not to_username:
        raise HTTPException(400, "請選擇要轉給誰")

    conn = get_db()
    try:
        begin_write(conn)   # lost update：各單據的 data_json／approval_json 在寫鎖內讀、整包寫回
        target = conn.execute(
            "SELECT username, display_name FROM users WHERE username=? AND active=1",
            (to_username,)).fetchone()
        if not target:
            raise HTTPException(404, "找不到該使用者或帳號已停用")

        # 🔴 讀不出來要擋（fail-closed），不可以吞成空鏈——那與「沒有設定流程」一模一樣。
        try:
            row = store.load(conn, body.id)
        except ApprovalUnreadable:
            raise HTTPException(400, "這張單的簽核資料格式不正確，無法轉簽。")
        if not row:
            raise HTTPException(404, "單據不存在")
        if (row["status"] or "") not in ("待審核", "簽核中"):
            raise HTTPException(409, "只有待審核／簽核中的單據可以轉簽（目前：" + (row["status"] or "") + "）")
        appr = row["approval"]
        tiers = active_tiers(appr)
        if not tiers:
            raise HTTPException(400, "這張單沒有分層簽核資料，無法轉簽")
        ct = current_tier_idx(appr)
        if ct >= len(tiers):
            raise HTTPException(400, "所有層級都已完成簽核")

        approvers = tiers[ct].get("approvers") or []
        # 指定 from 就換那個人，否則換「當層第一個還沒簽的人」——後者是實務上的
        # 「這張卡在誰身上」，也是佇列畫面顯示的那個人。
        idx = None
        for i, a in enumerate(approvers):
            if a.get("status") == "approved":
                continue
            if body.from_username and a.get("username") != body.from_username:
                continue
            idx = i
            break
        if idx is None:
            raise HTTPException(400, "當層沒有可轉簽的待簽核人員")

        old = approvers[idx]
        if old.get("username") == to_username:
            raise HTTPException(400, "轉簽對象與原簽核人相同")

        now = datetime.now().isoformat()
        actor = user.get("display_name") or user["username"]
        approvers[idx] = {
            **old,
            "username": target["username"],
            "displayName": target["display_name"] or target["username"],
            "status": old.get("status") or "pending",
            # 註記留在這一筆簽核上：簽核佇列詳情與 PDF 都讀得到，不必回頭翻 audit
            "reassignedFrom": old.get("username"),
            "reassignedFromDisplay": old.get("displayName") or old.get("username"),
            "reassignedBy": actor,
            "reassignedAt": now,
            "reassignReason": reason,
        }
        tiers[ct]["approvers"] = approvers
        log = appr.get("reassignLog")
        if not isinstance(log, list):
            log = []
        log.append({"at": now, "by": actor, "tier": ct + 1,
                    "from": old.get("username"), "fromDisplay": old.get("displayName") or old.get("username"),
                    "to": target["username"], "toDisplay": target["display_name"] or target["username"],
                    "reason": reason})
        appr["reassignLog"] = log
        appr["tiers"] = tiers

        store.save(conn, row, appr, now)
        conn.commit()
    finally:
        conn.close()

    _audit(_tok(authorization), "approval.reassign", body.type, body.id,
           body.id + "：" + (old.get("displayName") or old.get("username") or "") + " → "
           + (target["display_name"] or target["username"]),
           {"from": old.get("username"), "to": to_username, "reason": reason,
            "tier": ct + 1, "docType": body.type})
    # 被轉到的人要知道自己多了一張要簽的單，否則這張會靜靜卡在他的佇列裡
    _notify(to_username, "approval_request", body.id, row["quoteNo"] or body.id,
            actor + " 將「" + body.id + "」的簽核轉給你（原因：" + reason + "）")

    return {"ok": True, "to": to_username,
            "toDisplay": target["display_name"] or target["username"],
            "reason": reason, "tier": ct + 1}
