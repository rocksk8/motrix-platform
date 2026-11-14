# -*- coding: utf-8 -*-
"""簽核流程複製（設定矩陣 S4c；`POST /api/approval/flows/copy[/preview]`）：把一份簽核流程（統一流程或某一類單據的獨立流程）複製到其他單據類型。

原則（與批次權限同一套：先預覽、再確認、才寫入）：
 1. **預覽不寫入**：回每個目標「會不會變、略過的原因、目前有幾件單據在簽核中、其中幾件會改用新流程」，以及 `planHash`。
 2. **哪些進行中的單據會受影響**：送審當下簽核層就存進單據本身（`approval.tiers`），已送審的單據照原流程簽完；只有「沒有自己的簽核層」的進行中單據
    （簽核時才讀目前流程的後備路徑，見 `tiered_approval.resolve_active_flow_setting`）會改用新流程。預覽把這兩個數字分開講，
    確認視窗先講件數、再按套用。件數來自各模組登記的「待簽核佇列提供者」；提供者讀取失敗 ⇒ `inflightComplete=False`，畫面誠實說「件數可能不完整」。
 3. **跟隨統一流程的單據類型不複製**：它實際用的是統一流程，改它自己的流程不會生效，只會留下一份沒人用的設定 ⇒ 略過並說明（不替人改套用範圍）。
 4. **整批同一個寫入交易**（`core.txn.begin_write`）；`planHash`（只含流程內容，不含進行中件數：件數隨時在變）與重算結果不同 ⇒ 409；
    稽核與通知一律在 commit 之後（呼叫端做）。只有最高管理者能呼叫（路由檢查）。
"""
import hashlib
import json
import logging

from core import registry
from helpers import tiered_approval as ta

logger = logging.getLogger(__name__)

UNIFIED = "unified"

#: 待簽核佇列項目的 `type` ⇒ 簽核單據類型（與 `tools/check_approval_queue_coverage.py` 的對照同一份來源；那份是守門用的核對表，這份是計數用）。
#: 不在表上、但本身就是已登記的單據類型代碼（模組新登記的類型）⇒ 以自己的代碼計；其餘（附屬類型、自訂模組…）不計。
_QUEUE_TYPE_TO_DOC = {
    "quotation": "quotation", "shipping_note": "shipping", "invoice_voucher": "invoice_voucher", "payment_request": "payment_request",
    "contractor_voucher": "contractor_voucher", "extra_expense": "extra_expense", "extra_expense_change": "extra_expense",
    "completion_note": "completion", "voucher": "voucher",
    "bonus_award": "bonus", "bonus_case_award": "bonus", "bonus_correction": "bonus",
}


class FlowCopyError(Exception):
    """服務層錯誤：`status` 給路由轉成 HTTPException。"""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _key(doc_type):
    return "unified_approval_flow" if doc_type == UNIFIED else "%s_approval_flow" % doc_type


def _label(doc_type):
    return "統一簽核流程" if doc_type == UNIFIED else ta.APPROVAL_DOC_TYPE_LABELS.get(doc_type, doc_type)


def _read_setting(conn, key, default):
    row = conn.execute("SELECT value_json FROM system_settings WHERE key=?", (key,)).fetchone()
    if not row:
        return default
    try:
        v = json.loads(row[0])
    except (TypeError, ValueError):
        return default
    return v if v not in (None, "") else default


def _normalize(raw) -> dict:
    """設定值 ⇒ `{tiers, includeSubmitterManagerTier}`（舊格式 `steps` 轉 `tiers`；同 `routers/system.py::_normalize_flow`）。"""
    raw = raw if isinstance(raw, dict) else {}
    tiers = raw["tiers"] if "tiers" in raw else ta.steps_to_tiers(raw.get("steps") or [])
    if not isinstance(tiers, list):
        tiers = []
    return {"tiers": json.loads(json.dumps(tiers, ensure_ascii=False)),
            "includeSubmitterManagerTier": bool(raw.get("includeSubmitterManagerTier", True))}


def _same(a, b) -> bool:
    return json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(b, sort_keys=True, ensure_ascii=False)


def _digest(flow) -> str:
    n = len(flow["tiers"])
    return ("%d 層" % n if n else "預設（任一最高管理者簽核）") + ("，含申請人主管層" if flow["includeSubmitterManagerTier"] else "")


def parse_request(body) -> dict:
    if not isinstance(body, dict):
        raise FlowCopyError("請求必須是物件")
    source = body.get("source")
    valid = [UNIFIED] + list(ta.APPROVAL_DOC_TYPES)
    if not isinstance(source, str) or source not in valid:
        raise FlowCopyError("來源流程不存在：%s" % (source,))
    targets = body.get("targets")
    if not isinstance(targets, list) or not targets:
        raise FlowCopyError("請至少選一個要複製過去的單據類型")
    out = []
    for t in targets:
        if not isinstance(t, str) or t not in ta.APPROVAL_DOC_TYPES:
            raise FlowCopyError("不支援的單據類型：%s" % (t,))
        if t == source:
            raise FlowCopyError("來源與目標不能是同一個：%s" % _label(t))
        if t not in out:
            out.append(t)
    plan_hash = body.get("planHash") or ""
    if not isinstance(plan_hash, str):
        raise FlowCopyError("planHash 必須是字串")
    return {"source": source, "targets": out, "planHash": plan_hash}


def inflight_counts(conn) -> dict:
    """⇒ `{docType: {total, usingFlow}, "_complete": bool}`。`usingFlow`＝簽核層是空的（簽核時才讀目前流程）的進行中單據。永不丟例外。"""
    out, complete = {}, True
    try:
        providers = sorted(registry.providers("approval.queue_items").items())
    except Exception:                                          # noqa: BLE001
        providers, complete = [], False
    for name, fn in providers:
        try:
            items = fn(conn) or []
        except Exception:                                      # noqa: BLE001
            logger.exception("簽核流程複製：待簽核提供者 %s 讀取失敗（件數可能不完整）", name)
            complete = False
            continue
        for it in items:
            t = it.get("type")
            dt = _QUEUE_TYPE_TO_DOC.get(t) or (t if t in ta.APPROVAL_DOC_TYPES else None)
            if not dt:
                continue
            c = out.setdefault(dt, {"total": 0, "usingFlow": 0})
            c["total"] += 1
            if not (it.get("tiers") or []):
                c["usingFlow"] += 1
    out["_complete"] = complete
    return out


def _follows_unified(conn, doc_type) -> bool:
    scope = _read_setting(conn, "approval_flow_scope", {}) or {}
    return bool(scope.get(doc_type, doc_type in ta.DEFAULT_UNIFIED_DOC_TYPES))


def _plan(conn, req) -> dict:
    if req["source"] != UNIFIED and _follows_unified(conn, req["source"]):
        raise FlowCopyError("「%s」目前跟隨統一流程，它自己的流程不會生效，不能當來源。請改選「統一簽核流程」當來源，或先到簽核設定頁取消它的「跟隨統一流程」。" % _label(req["source"]), 409)
    src = _normalize(_read_setting(conn, _key(req["source"]), {"tiers": []}))
    people = []
    for dt in req["targets"]:
        cur = _normalize(_read_setting(conn, _key(dt), {"tiers": []}))
        row = {"docType": dt, "label": _label(dt), "before": _digest(cur), "after": _digest(src), "status": "copy", "note": "", "_beforeValue": cur}
        if _follows_unified(conn, dt):
            row.update(status="skipped", note="目前跟隨統一流程：改它自己的流程不會生效。請先到簽核設定頁取消「跟隨統一流程」再複製。")
        elif _same(cur, src):
            row.update(status="nochange", note="流程已經一樣")
        people.append(row)
    if not src["tiers"] and any(p["status"] == "copy" for p in people):
        # 來源沒有任何簽核層 ⇒ 複製過去等於把對方改成「任一最高管理者簽核」＝放寬簽核：後端直接拒絕（不提供略過選項）
        raise FlowCopyError("來源「%s」尚未設定任何簽核層，複製過去會讓目標單據變成「任一最高管理者簽核」（放寬簽核）。請先在簽核設定頁設好來源流程再複製。" % _label(req["source"]), 409)
    digest = hashlib.sha256(json.dumps({"source": [req["source"], src], "targets": [[p["docType"], p["status"], _normalize(_read_setting(conn, _key(p["docType"]), {"tiers": []}))] for p in people]},
                                       sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
    return {"source": req["source"], "sourceLabel": _label(req["source"]), "sourceDigest": _digest(src), "sourceEmpty": not src["tiers"],
            "targets": people, "planHash": digest, "_value": src}


def _with_counts(plan, counts) -> dict:
    total = using = 0
    for p in plan["targets"]:
        c = counts.get(p["docType"]) or {"total": 0, "usingFlow": 0}
        p["inflight"] = {"total": c["total"], "usingFlow": c["usingFlow"]}
        if p["status"] == "copy":
            total += c["total"]
            using += c["usingFlow"]
    plan["inflightComplete"] = bool(counts.get("_complete", True))
    plan["summary"] = {"changed": sum(1 for p in plan["targets"] if p["status"] == "copy"),
                       "unchanged": sum(1 for p in plan["targets"] if p["status"] == "nochange"),
                       "skipped": sum(1 for p in plan["targets"] if p["status"] == "skipped"),
                       "inflightTotal": total, "inflightUsingFlow": using}
    return plan


def _public(plan) -> dict:
    out = {k: v for k, v in plan.items() if not k.startswith("_")}
    out["targets"] = [{k: v for k, v in t.items() if not k.startswith("_")} for t in plan["targets"]]
    return out


def preview(conn, actor, body) -> dict:
    """唯讀：每個目標會不會變、進行中件數、`planHash`。"""
    req = parse_request(body)
    plan = _plan(conn, req)
    return _public(_with_counts(plan, inflight_counts(conn)))


def apply(conn, actor, body) -> dict:
    """套用：同一個寫入交易重算計畫；`planHash` 與預覽不同 ⇒ 409（不照過期預覽寫入）。
    ⇒ `{..plan.., ok, applied:[docType…]}`；稽核與通知由呼叫端在 commit 之後做。"""
    from core.txn import begin_write
    from datetime import datetime
    req = parse_request(body)
    if not req["planHash"]:
        raise FlowCopyError("套用要帶預覽的 planHash（請先預覽再套用）")
    counts = inflight_counts(conn)                             # 慢的事（跑各模組提供者）在拿寫鎖之前做完
    begin_write(conn)
    try:
        plan = _plan(conn, req)
        if req["planHash"] != plan["planHash"]:
            raise FlowCopyError("流程在預覽之後有變動，請重新預覽再套用", 409)
        applied = []
        value = json.dumps(plan["_value"], ensure_ascii=False)
        now = datetime.now().isoformat()
        for p in plan["targets"]:
            if p["status"] != "copy":
                continue
            conn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?, ?, ?) "
                         "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                         (_key(p["docType"]), value, now))
            applied.append(p["docType"])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    out = _public(_with_counts(plan, counts))
    out["ok"] = True
    out["applied"] = applied
    out["_before"] = {p["docType"]: p["_beforeValue"] for p in plan["targets"] if p["docType"] in applied}   # 稽核存舊值（路由取走後不回給前端）
    return out


def notify(actor, plan, applied) -> None:
    """commit **之後**：一次複製＝**一則**合併通知（`settings_notify.batch`）。永不丟例外。"""
    try:
        from helpers import settings_notify as sn
        who = (actor or {}).get("username") or ""
        with sn.batch(verb="", header="複製簽核流程"):
            for p in plan["targets"]:
                if p["docType"] in set(applied or ()):
                    sn.emit([sn.make_item("approval_flow", "%s的簽核流程" % p["label"], p["before"], p["after"], "updated",
                                          actor=who, link="approval-settings.html")])
    except Exception:                                          # noqa: BLE001
        logger.warning("approval_flow_copy.notify 失敗（不影響已 commit 的寫入）", exc_info=True)
