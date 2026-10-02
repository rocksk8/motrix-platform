"""Audit log and in-app notification helpers."""

#: G1（MODULE-GUIDE §2）：底線開頭但屬於 L1 公開介面的名稱——改簽章或刪除照介面變更升版。
#: L1 以外只可以用這裡列出的底線名稱（守門：test_l1_interface_snapshot::test_l2_uses_only_declared_l1_underscore_names）。
__l1_public__ = (
    "_audit",
    "_audit_login_failed",                # 登入失敗稽核（routers/auth.py；2026-09-30 歷史紀錄分層搜尋）
    "_FAIL_REASON_LABELS",                # 失敗原因碼 ⇒ 中文（routers/system.py）
    "_MODULE_LABELS",                     # 動作第一段 ⇒ 模組中文名（routers/system.py）
    "_filter_live_notifications",
    "_mark_notifications_read",           # 簽核處理掉 ⇒ 對應通知列標已讀（modules/case 報價單核准／退回／拒絕）
    "_notify",
    "_purge_notifications",
)

import json
import logging
import re
import threading
import time
from datetime import datetime

from db import get_db

logger = logging.getLogger(__name__)

# ── 歷史紀錄的分層搜尋欄位（使用者 2026-09-30：「人員的紀錄或是操作紀錄可以分層依模組、案件等搜尋，或是紀錄中有失敗能快速查詢」）──
#
# `audit_log` 新增 `module`／`case_no`／`ref_no`／`result`／`reason_code`／`status_code`（core migration v3）。
# 寫入端一律用 `_derive_fields()` 補 module／case_no／ref_no——所有既有 `_audit()` 呼叫端不用改。
# ⚠️ core/migrations.py 的 v3 回填有**凍結的一份**同樣的規則（migration 不准 import 會演進的程式）；
#    tests/test_audit_search_2026_09_30.py 逐列驗證兩份對同一批資料算出一樣的結果。
_CASE_NO_RE = re.compile(r"MQ-\d{6}-\d{3}")
#: 動作第一段 ⇒ 畫面上的模組名（對不到 ⇒ 顯示原字串，不猜）
_MODULE_LABELS = {
    "quotation": "報價單", "case": "案件管理", "deal_tag": "成案標記", "case_stage": "案件階段", "case_update": "案件動態",
    "case_action_item": "案件待辦", "extra_expense": "額外支出", "completion": "完工單", "shipping": "出貨單",
    "voucher": "傳票", "invoice_voucher": "開票申請", "payment_request": "請款單", "payment": "收款",
    "contractor_voucher": "承攬商匯款", "contractor": "承攬人員", "vendor": "外包廠商", "payslip": "勞報單", "bonus": "獎金分潤",
    "dev_case": "業務開發", "dev_log": "業務開發記錄", "customer": "客戶", "supplier": "供應商", "part": "料號",
    "stock_item": "庫存", "stock_batch": "進貨批次", "work_log": "工作日誌", "daily_task": "每日工作事項",
    "network_plan": "網路架構規劃", "tender_watch": "標案雷達", "tender_radar": "標案雷達", "tender": "標案雷達",
    "export": "匯出", "settings": "系統設定", "user": "使用者", "auth": "登入", "custom": "自訂模組", "custom_record": "自訂模組", "reports": "營運報表",
    "backup": "系統備份", "lodging": "附近旅宿", "lodging_search": "附近旅宿", "credential": "憑證", "division": "組織",
    "department": "組織", "approval_delegate": "簽核代理人", "ui_definition": "介面自訂", "account_items": "會計科目",
    "sales_order": "銷售訂單", "settlement": "案件精算", "device": "設備", "warranty": "保固", "fail": "操作失敗",
}
#: target_type 屬於「單據」類 ⇒ `ref_no`＝target_id（其餘 ref_no 留空）
_DOC_TARGET_TYPES = frozenset({
    "vouchers", "contractor_dispatch", "shipping_note", "payslip", "completion_note", "invoice_voucher", "payment_request",
    "bonus_awards", "bonus_case_awards", "bonus_corrections", "contractor_payment_voucher", "custom_record", "stock_batch", "network_plan",
    "case_action_item", "case_update",
})
#: 失敗列的原因碼（固定詞彙：不放自由文字，PII 安全）⇒ 中文標籤
_FAIL_REASON_LABELS = {
    "permission_denied": "沒有權限", "not_found_or_hidden": "找不到或看不到", "conflict": "狀態衝突",
    "validation": "資料不合格", "gate_blocked": "被閘門擋下", "server_error": "系統錯誤", "login_failed": "登入失敗",
}
_FAIL_STATUS_REASON = {403: "permission_denied", 404: "not_found_or_hidden", 409: "conflict", 422: "validation",
                       428: "gate_blocked", 500: "server_error", 401: "login_failed"}
#: 這些狀態碼的寫入請求才記失敗列（不記 GET、不記 401 過期——登入失敗另走 `_audit_login_failed`）
_FAIL_STATUSES = frozenset({403, 404, 409, 422, 428, 500})
_FAIL_WINDOW_SECONDS = 60
#: `detail` 的字元上限（超過 ⇒ 改存 `{_truncated, originalLength, preview}`）。簽章不變；所有既有呼叫端的 detail 都遠小於此
_DETAIL_MAX = 2000
_FAIL_HOURLY_CAP = 200
_FAIL_LOCK = threading.Lock()
_FAIL_LAST = {}      # (user, method, route, status) -> (monotonic 秒, audit_log id)
_FAIL_HOUR = {}      # user -> (小時桶, 筆數)
#: 路由第一段 ⇒ 模組 key（與動作第一段同一套詞彙；對不到 ⇒ 第一段把 - 換成 _）
_ROUTE_MODULE_ALIASES = {
    "quotations": "quotation", "vouchers": "voucher", "completion-notes": "completion", "shipping-notes": "shipping",
    "payslips": "payslip", "invoice-vouchers": "invoice_voucher", "payment-requests": "payment_request",
    "contractor-vouchers": "contractor_voucher", "contractor-dispatches": "vendor", "vendor-contractors": "vendor",
    "contractors": "contractor", "customers": "customer", "suppliers": "supplier", "parts": "part", "bonus": "bonus",
    "dev-cases": "dev_case", "work-logs": "work_log", "daily-tasks": "daily_task", "network-plans": "network_plan",
    "users": "user", "auth": "auth", "settings": "settings", "reports": "reports", "approval-queue": "quotation",
}


def _derive_fields(action: str, target_type: str = "", target_id: str = "", target_label: str = "",
                   detail=None) -> dict:
    """由一筆稽核的內容算出 `module`／`case_no`／`ref_no`（純函式）。
    module＝動作第一段（`quotation.approve` ⇒ `quotation`）；case_no＝在 target_id／target_label／detail 的字串值裡找
    `MQ-YYYYMM-NNN`（第一個）；ref_no＝target_type 屬單據類時的 target_id。對不到一律空字串（畫面顯示「其他」，不猜）。"""
    module = (action or "").split(".", 1)[0]
    hay = [str(target_id or ""), str(target_label or "")]
    if isinstance(detail, dict):
        hay += [v for v in detail.values() if isinstance(v, str)]
    elif isinstance(detail, str):
        hay.append(detail)
    case_no = ""
    for h in hay:
        m = _CASE_NO_RE.search(h)
        if m:
            case_no = m.group(0)
            break
    ref_no = str(target_id or "") if (target_type or "") in _DOC_TARGET_TYPES else ""
    return {"module": module, "case_no": case_no, "ref_no": ref_no}


def _notify(username: str, type_: str, ref_id: str, ref_label: str, message: str) -> None:
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO notifications "
            "(username, type, ref_id, ref_label, message, is_read, created_at) "
            "VALUES (?,?,?,?,?,0,?)",
            (username, type_, ref_id, ref_label, message, datetime.now().isoformat()),
        )
        conn.commit()
    except Exception as e:
        logger.warning("_notify failed: %s", e)
    finally:
        conn.close()


def notify_org_chain_notice(conn, tiers: list, requester_username: str,
                            ref_id: str, ref_label: str, message: str,
                            type_: str = "approval_notice") -> list:
    """「知會」通知（2026-09-15）：某張單的簽核鏈**每一層都只有申請人本人**
    （他已經在組織職權的頂端，例如處主管送自己的單）時，通知其他在職的最高
    管理者一聲，回傳實際被通知的帳號。

    背景：2026-09-15 之前，這種情況會硬抓一位別的超級管理員當簽核人——使用者
    的裁示是「他自己簽核兩次，我這邊只做知會」。最高管理者退出簽核鏈之後，
    這則通知就是他唯一的知情管道（他仍隨時可用 superadmin 權限退回）。

    判斷邏輯放在 tiered_approval.py::org_chain_notice_usernames()（純函式、
    不碰通知），這裡只負責送——維持該模組「不做 side effect」的既有分工。"""
    from .tiered_approval import org_chain_notice_usernames
    names = org_chain_notice_usernames(conn, tiers, requester_username)
    for u in names:
        _notify(u, type_, ref_id, ref_label, message)
    return names


_NOTIF_SOURCE_CHECK = {
    'approval_request':          "SELECT 1 FROM quotations WHERE quote_no=?",
    'approval_notice':           "SELECT 1 FROM quotations WHERE quote_no=?",
    'approval_returned':         "SELECT 1 FROM quotations WHERE quote_no=?",
    'approval_rejected':         "SELECT 1 FROM quotations WHERE quote_no=?",
    'case_stage_deadline':       "SELECT 1 FROM quotations WHERE quote_no=?",
    'shipping_approval_request': "SELECT 1 FROM shipping_notes WHERE note_no=?",
    'shipping_approval_notice':  "SELECT 1 FROM shipping_notes WHERE note_no=?",
    'shipping_approved':         "SELECT 1 FROM shipping_notes WHERE note_no=?",
    'shipping_returned':         "SELECT 1 FROM shipping_notes WHERE note_no=?",
    'daily_task':                "SELECT 1 FROM daily_tasks WHERE id=? AND is_deleted=0",
    'project_deadline':          "SELECT 1 FROM projects WHERE code=?",
    'dev_case_stale':            "SELECT 1 FROM dev_cases WHERE id=? AND is_deleted=0",
}


def _filter_live_notifications(conn, rows: list) -> list:
    """濾掉來源記錄已刪除/軟刪除的通知列（未知 type 一律放行，不受影響）。"""
    out = []
    for r in rows:
        sql = _NOTIF_SOURCE_CHECK.get(r["type"])
        if sql and r["ref_id"] and not conn.execute(sql, (r["ref_id"],)).fetchone():
            continue
        out.append(r)
    return out


def _purge_notifications(ref_id: str, types: list) -> None:
    """來源記錄刪除/軟刪除時，主動清掉對應通知列。"""
    if not ref_id or not types:
        return
    conn = get_db()
    try:
        ph = ",".join("?" * len(types))
        conn.execute(
            f"DELETE FROM notifications WHERE ref_id=? AND type IN ({ph})",
            [ref_id, *types],
        )
        conn.commit()
    except Exception as e:
        logger.warning("_purge_notifications failed: %s", e)
    finally:
        conn.close()


def _mark_notifications_read(ref_id: str, types: list, username: str = None) -> None:
    """簽核已經處理掉（簽過、退回、拒絕）⇒ 對應的「待簽核」通知列標已讀（不刪：留作紀錄）。
    username＝只標這個人的（核准：只有自己的那一筆失效，同層／下層的人還在等）；None＝這張單所有人的（退回／拒絕：整條簽核作廢）。
    不標已讀的後果：橫幅／未讀計數永遠留著已簽過的項目，每次登入再跳一次（2026-10-01 使用者回報）。"""
    if not ref_id or not types:
        return
    conn = get_db()
    try:
        ph = ",".join("?" * len(types))
        sql = f"UPDATE notifications SET is_read=1 WHERE ref_id=? AND type IN ({ph}) AND is_read=0"
        args = [ref_id, *types]
        if username:
            sql += " AND username=?"
            args.append(username)
        conn.execute(sql, args)
        conn.commit()
    except Exception as e:
        logger.warning("_mark_notifications_read failed: %s", e)
    finally:
        conn.close()


def _audit(
    token: str,
    action: str,
    target_type: str = "",
    target_id: str = "",
    target_label: str = "",
    detail: dict = None,
) -> None:
    try:
        conn = get_db()
        user_id, username, display_name = None, "", ""
        if token:
            row = conn.execute(
                "SELECT u.id, u.username, u.display_name "
                "FROM sessions s JOIN users u ON s.user_id=u.id WHERE s.token=?",
                (token,),
            ).fetchone()
            if row:
                user_id, username, display_name = row["id"], row["username"], row["display_name"]
        d = _derive_fields(action, target_type, target_id, target_label, detail)
        now = datetime.now().isoformat()
        payload = json.dumps(detail or {}, ensure_ascii=False)
        if len(payload) > _DETAIL_MAX:                     # 安全審查 W3 #5：detail 沒有上限 ⇒ 單列可以塞到很大（放大資料庫與搜尋成本）
            payload = json.dumps({"_truncated": True, "originalLength": len(payload), "preview": payload[:_DETAIL_MAX - 200]},
                                 ensure_ascii=False)
        try:
            conn.execute(
                "INSERT INTO audit_log "
                "(at,user_id,username,display_name,action,target_type,target_id,target_label,detail,"
                "module,case_no,ref_no,result,reason_code,status_code) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'ok','',0)",
                (now, user_id, username, display_name, action, target_type, target_id, target_label, payload,
                 d["module"], d["case_no"], d["ref_no"]),
            )
        except Exception:
            # 新欄位還沒建（core migration v3 尚未跑完的庫）⇒ 退回舊寫法，稽核不可以因此寫不進去
            conn.execute(
                "INSERT INTO audit_log "
                "(at,user_id,username,display_name,action,target_type,target_id,target_label,detail) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (now, user_id, username, display_name, action, target_type, target_id, target_label, payload),
            )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _audit_failure(user_id, username: str, display_name: str, method: str, route: str, status: int,
                   reason: str = "", case_no: str = "", ref_no: str = "", now: float = None) -> str:
    """記一筆「被擋下／失敗的寫入」（`result='fail'`）。回傳 `new`／`repeat`／`capped`／`skip`／`error`。

    **不記請求內容**：只有方法、路由樣板、單號、狀態碼、原因碼（固定詞彙）。
    **限流**：同 (人, 方法, 路由樣板, 狀態) 60 秒內只寫第一筆，後續只在那一列的 detail 累加 `repeat`；
    另有每人每小時 200 筆上限（超過只記 log）。鉤子本身絕不丟例外、不擋回應。"""
    try:
        if method not in ("POST", "PUT", "PATCH", "DELETE") or int(status) not in _FAIL_STATUSES:
            return "skip"
        reason = reason if reason in _FAIL_REASON_LABELS else _FAIL_STATUS_REASON.get(int(status), "server_error")
        mono = time.monotonic() if now is None else now
        key = (user_id, method, route, int(status))
        seg = (route or "").split("/")
        first = seg[2] if len(seg) > 2 else ""
        module = _ROUTE_MODULE_ALIASES.get(first, first.replace("-", "_"))
        with _FAIL_LOCK:
            last = _FAIL_LAST.get(key)
            if last and mono - last[0] < _FAIL_WINDOW_SECONDS:
                row_id = last[1]
            else:
                row_id = None
                bucket = int(mono // 3600)
                hb, cnt = _FAIL_HOUR.get(user_id, (bucket, 0))
                if hb != bucket:
                    hb, cnt = bucket, 0
                if cnt >= _FAIL_HOURLY_CAP:
                    _FAIL_HOUR[user_id] = (hb, cnt)
                    logger.warning("audit failure cap reached for user %s (%d/hour): further failure rows dropped", user_id, _FAIL_HOURLY_CAP)
                    return "capped"
                _FAIL_HOUR[user_id] = (hb, cnt + 1)
        conn = get_db()
        try:
            if row_id is not None:
                r = conn.execute("SELECT detail FROM audit_log WHERE id=?", (row_id,)).fetchone()
                if r is not None:
                    try:
                        det = json.loads(r["detail"] or "{}")
                    except ValueError:
                        det = {}
                    det["repeat"] = int(det.get("repeat", 0)) + 1
                    det["last_at"] = datetime.now().isoformat(timespec="seconds")
                    conn.execute("UPDATE audit_log SET detail=? WHERE id=?", (json.dumps(det, ensure_ascii=False), row_id))
                    conn.commit()
                    return "repeat"
            cur = conn.execute(
                "INSERT INTO audit_log (at,user_id,username,display_name,action,target_type,target_id,target_label,detail,"
                "module,case_no,ref_no,result,reason_code,status_code) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'fail',?,?)",
                (datetime.now().isoformat(), user_id, username or "", display_name or "", "fail." + method, "request", "",
                 route, json.dumps({"method": method, "route": route, "repeat": 0}, ensure_ascii=False),
                 module, case_no or "", ref_no or "", reason, int(status)),
            )
            conn.commit()
            with _FAIL_LOCK:
                _FAIL_LAST[key] = (mono, cur.lastrowid)
            return "new"
        finally:
            conn.close()
    except Exception:                                         # noqa: BLE001
        logger.exception("_audit_failure failed")
        return "error"


def _audit_login_failed(username: str, ip: str = "", now: float = None) -> str:
    """登入失敗（401）：記嘗試的帳號名與來源 IP，**不記密碼**。同帳號＋同 IP 60 秒限流（累加 repeat）。"""
    try:
        mono = time.monotonic() if now is None else now
        key = ("login", (username or "")[:64], ip or "")
        with _FAIL_LOCK:
            last = _FAIL_LAST.get(key)
            row_id = last[1] if last and mono - last[0] < _FAIL_WINDOW_SECONDS else None
        conn = get_db()
        try:
            if row_id is not None:
                r = conn.execute("SELECT detail FROM audit_log WHERE id=?", (row_id,)).fetchone()
                if r is not None:
                    try:
                        det = json.loads(r["detail"] or "{}")
                    except ValueError:
                        det = {}
                    det["repeat"] = int(det.get("repeat", 0)) + 1
                    conn.execute("UPDATE audit_log SET detail=? WHERE id=?", (json.dumps(det, ensure_ascii=False), row_id))
                    conn.commit()
                    return "repeat"
            cur = conn.execute(
                "INSERT INTO audit_log (at,user_id,username,display_name,action,target_type,target_id,target_label,detail,"
                "module,case_no,ref_no,result,reason_code,status_code) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'fail','login_failed',401)",
                (datetime.now().isoformat(), None, (username or "")[:64], "", "auth.login_failed", "user", (username or "")[:64],
                 (username or "")[:64], json.dumps({"ip": ip or "", "repeat": 0}, ensure_ascii=False), "auth", "", ""),
            )
            conn.commit()
            with _FAIL_LOCK:
                _FAIL_LAST[key] = (mono, cur.lastrowid)
            return "new"
        finally:
            conn.close()
    except Exception:                                         # noqa: BLE001
        logger.exception("_audit_login_failed failed")
        return "error"
