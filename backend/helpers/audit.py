"""Audit log and in-app notification helpers."""

#: G1（MODULE-GUIDE §2）：底線開頭但屬於 L1 公開介面的名稱——改簽章或刪除照介面變更升版。
#: L1 以外只可以用這裡列出的底線名稱（守門：test_l1_interface_snapshot::test_l2_uses_only_declared_l1_underscore_names）。
__l1_public__ = (
    "_audit",
    "_filter_live_notifications",
    "_notify",
    "_purge_notifications",
)

import json
import logging
from datetime import datetime

from db import get_db

logger = logging.getLogger(__name__)


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
        conn.execute(
            "INSERT INTO audit_log "
            "(at,user_id,username,display_name,action,target_type,target_id,target_label,detail) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                datetime.now().isoformat(), user_id, username, display_name, action,
                target_type, target_id, target_label,
                json.dumps(detail or {}, ensure_ascii=False),
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass
