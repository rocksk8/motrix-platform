# -*- coding: utf-8 -*-
"""傳票連接器提供者（IP-2 voucher.draft、IP-4 void_draft／status／by_no、待簽項目與轉簽）。

2026-09-30（W4 總帳 P1）自 vouchers.py **純搬移**（行為不變）。
"""
import datetime as _dt
import json
import os
from datetime import datetime

from fastapi import APIRouter, Body, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from urllib.parse import quote

from db import get_db
# 🔑 科目代號的規則**只有一份** —— 借用既有那一支，不在這裡再寫。
#    （router 互相 import 在這個 repo 是既有做法，實查 7 處。）
from modules.accounting.api.accounting_export import validate_account_code
# `JV21`：承攬商派工的 grandTotal（含稅費用＋外包人員）算法**只有一份**——在 M04，
# 經 IP-15 成本檢視 `dispatch.cost_for_case` 取用（2026-09-26 起；原本經 IP-1 `dispatch.row`＋自己讀派工表），
# 不 import M04 的私有函式、不讀 M04 的表。
# ⚠️ **不要自己重算**：`total_amount` 少了稅、也少了外包人員費用，`ACC-BN6 §3` 已經踩過這個坑。
from core import registry as _registry
from helpers import _require_user, _tok, _audit, require_any_module
from helpers.edit_log import append_edit_log, MissingOldValue
from helpers.tiered_approval import (
    approval_flow_setting_key, setting_to_active_tiers,
    UnresolvedManagerError, active_delegators_for,
)
from helpers import _get_setting
from helpers.uploads import save_document_files
from modules.accounting.voucher_pdf import (
    export_voucher_pdf, preview_html, classify_attachment_kind,
)
from modules.accounting.voucher_attachments import (
    resolve_picks, copy_into, abs_path, case_attachments,
    line_source_files, LINE_SOURCES, EXPENSE_LINE_SOURCES, expense_line_uses, unavailable_sources, hidden_sources, CaseNotVisible, CASE_NOT_FOUND,
)
from modules.accounting.ledger import periods as _ledger_periods
from modules.accounting.voucher import (
    EDITABLE_STATUSES, can_edit, describe_balance, get_voucher,
    next_voucher_no, post_voucher, can_send_back, next_revision_no,
    diff_lines, approval_done, parse_approval_json, VoucherChainUnreadable,
    normalize_amount_lines, classify_category,
)

from modules.accounting.api.voucher_common import _amount_lines, _line_sources, insert_draft_voucher  # noqa: E402


# ── 連接器 IP-2 voucher.draft（docs/platform/INTEGRATION-POINTS.md，契約版本 1）───────────
# 別組（例：M07 獎金）要開傳票草稿時走這裡，不 import 本檔的私有函式。
# 在呼叫端的交易裡寫入，**不 commit**；科目有效性由呼叫端先用 voucher.account_check 檢查。
def _provide_voucher_draft(conn, *, voucher_date, summary, lines, created_by, now, origin=""):
    """lines：[{account_code, summary, debit, credit}]。回 {"id", "voucher_no"}。
    `origin`（選填，總帳 P1 加，契約仍是版本 1）：產生來源標記（例 bonus_accrual），總帳引擎據此辨識既有自動傳票、不重複產生。"""
    norm = _line_sources(_amount_lines(lines))
    vid, no = insert_draft_voucher(conn, voucher_date, summary, norm, created_by, now,
                                   classify_category(conn, norm))
    if origin:
        conn.execute("UPDATE vouchers_all SET origin=? WHERE id=?", (str(origin)[:40], vid))
    return {"id": vid, "voucher_no": no}


# （提供者改由 modules/accounting/__init__.py 的 ModuleSpec.providers 宣告：voucher.draft）


# ── 連接器 IP-4 voucher.void_draft／voucher.status（INTEGRATION-POINTS.md，契約版本 1）────
# 別組不直接讀寫 vouchers_all。都在呼叫端的交易裡做，不 commit。
def _provide_voucher_void_draft(conn, voucher_id, *, voided_by, now, reason):
    """只作廢「草稿」。回 {"result": "voided"|"not_draft"|"gone", "voucher_no", "status"}：
    voided＝已作廢；not_draft＝已送審，不動；gone＝不存在或早已作廢（呼叫端解除連結即可）。"""
    v = conn.execute("SELECT voucher_no, status, voided_at FROM vouchers_all WHERE id = ?",
                     (voucher_id,)).fetchone()
    if v is None or v["voided_at"]:
        return {"result": "gone", "voucher_no": v["voucher_no"] if v else "", "status": v["status"] if v else ""}
    if v["status"] != "草稿":
        return {"result": "not_draft", "voucher_no": v["voucher_no"], "status": v["status"]}
    conn.execute("UPDATE vouchers_all SET voided_at=?, voided_by=?, void_reason=?, updated_at=? WHERE id=?",
                 (now, voided_by, reason, now, voucher_id))
    return {"result": "voided", "voucher_no": v["voucher_no"], "status": v["status"]}


def _provide_voucher_status(conn, voucher_id):
    """回 {"id", "voucher_no", "status", "voided"}；不存在 ⇒ None。"""
    v = conn.execute("SELECT id, voucher_no, status, voided_at, voucher_date FROM vouchers_all WHERE id = ?",
                     (voucher_id,)).fetchone()
    if v is None:
        return None
    return {"id": v["id"], "voucher_no": v["voucher_no"], "status": v["status"], "voided": bool(v["voided_at"]),
            "date": (v["voucher_date"] or "")[:10]}


def _provide_voucher_by_no(conn, voucher_no):
    """IP-4 追加 `voucher.by_no`（2026-09-29，勞報單付款回填傳票單號用）：以傳票單號查。
    回 {"id", "voucher_no", "status", "voided"}；不存在 ⇒ None。唯讀。"""
    v = conn.execute("SELECT id, voucher_no, status, voided_at FROM vouchers_all WHERE voucher_no = ?",
                     (str(voucher_no or "").strip(),)).fetchone()
    if v is None:
        return None
    return {"id": v["id"], "voucher_no": v["voucher_no"], "status": v["status"], "voided": bool(v["voided_at"])}


# （提供者改由 modules/accounting/__init__.py 的 ModuleSpec.providers 宣告：voucher.void_draft）
# IP-22（暫定號）：M01 案件整包的傳票段；同一份授權、權限判斷與單獨打 /api/vouchers/by-case/{no} 逐字相同
# （提供者改由 modules/accounting/__init__.py 的 ModuleSpec.providers 宣告：voucher.by_case）
# （提供者改由 modules/accounting/__init__.py 的 ModuleSpec.providers 宣告：voucher.status）


# ── 待我簽核與轉簽（M01-PLAN §3-7，2026-09-26）：本模組提供自己的待簽項目與簽核鏈讀寫，M01 佇列只彙整 ──
# ⚠️ 跟 data_json 類單據不同：approval_json 是 vouchers_all 自己的**欄位**（傳票沒有 data_json）。
from helpers import approval_queue as _aq  # noqa: E402


def _queue_items(conn) -> list:
    """`approval.queue_items`：待審核／簽核中的會計傳票（`AS3`；`type`＝`voucher`）。
    傳票不掛在任何案件底下（一般分類帳憑證），`customer` 留空、`projectName` 放摘要。"""
    rows = conn.execute("""
        SELECT id, voucher_no, voucher_date, summary, submitted_by, submitted_at,
               approval_json,
               COALESCE((SELECT SUM(debit) FROM voucher_lines
                         WHERE voucher_id = vouchers_all.id), 0) as total_debit
        FROM vouchers_all
        WHERE status IN ('待審核','簽核中')
        ORDER BY id DESC
    """).fetchall()
    out = []
    for r in rows:
        raw = _aq.approval_raw_of(r["approval_json"], "voucher", r["voucher_no"])   # 壞一筆只跳過那一筆（QJ-M1）
        if raw is None:
            continue
        f = _aq.tier_fields(raw)
        # 🔑 舊資料（AS3 之前送審的）approval_json 沒嵌 requestedBy ⇒ 退回 submitted_by／submitted_at 兩欄
        requested_by = f["requestedBy"] or r["submitted_by"] or ""
        out.append(_aq.base_item(
            "voucher", r["voucher_no"], f,
            customer="",
            projectName=r["summary"] or "",
            total=r["total_debit"] or 0,
            quoteDate=r["voucher_date"] or "",
            requestedBy=requested_by,
            requestedByDisplay=f["requestedByDisplay"] or requested_by,
            requestedAt=f["requestedAt"] or r["submitted_at"] or "",
            # 🔴 `/api/vouchers/{voucher_id}/...` 吃數字 id，不是人看的單號 ⇒ 兩個都給（approval-queue.html `itemPathId()`）
            voucherId=r["id"],
        ))
    return out


class _VoucherReassign:
    """`approval.reassign`（`JV35`）：簽核鏈在 `vouchers_all.approval_json`；作廢的傳票不算（狀態欄可能還停在簽核中）。"""

    @staticmethod
    def load(conn, doc_no):
        row = conn.execute(
            "SELECT voucher_no, status, approval_json FROM vouchers_all"
            " WHERE voucher_no=? AND COALESCE(voided_at, '')=''", (doc_no,)).fetchone()
        if not row:
            return None
        # 🔴 讀不出來要擋（fail-closed，同 `_appr_of`），不可以吞成空鏈——那與「沒有設定流程」一模一樣
        from helpers.tiered_approval import parse_approval_json, ApprovalChainUnreadable
        try:
            appr = parse_approval_json(dict(row))
        except ApprovalChainUnreadable:
            raise _aq.ApprovalUnreadable(doc_no)
        # 📌 傳票沒有 quote_no ⇒ 以單號代入（通知的 ref_label 用它）
        return {"docNo": row["voucher_no"], "quoteNo": row["voucher_no"], "status": row["status"], "approval": appr}

    @staticmethod
    def save(conn, doc, approval, now):
        conn.execute("UPDATE vouchers_all SET approval_json=?, updated_at=? WHERE voucher_no=?",
                     (json.dumps(approval, ensure_ascii=False), now, doc["docNo"]))


# （提供者改由 modules/accounting/__init__.py 的 ModuleSpec.providers 宣告：approval.queue_items）
# （提供者改由 modules/accounting/__init__.py 的 ModuleSpec.providers 宣告：approval.reassign）
