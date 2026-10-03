# -*- coding: utf-8 -*-
"""材料申請「變更申請」的狀態機、驗證與原子套用（第 33 班 33-M2a；設計 docs/platform/plans/MATERIAL-CHANGE-REQUEST-DESIGN.md）。

[單位] case:material_change    [層] L2（M01）    [穩定度] 新（第 33 班）
**資料**：覆核表 `case_material_changes`（migration 0006），單號 `MC-YYYYMMDD-NNNN`。已核准的材料申請要改內容（追加採購單行、改數量）不回草稿，
改開一張變更申請走簽核；**原已核准版本在變更核准前完全不動**（成本、到貨、可出貨量照舊有效；使用者裁示 N3），核准後在同一個寫入交易內原子切換。
**狀態**：`草稿／待審核／簽核中／已核准／已退回／已撤回`；一筆材料申請同時最多一個進行中的變更（部分唯一索引擋底）。
**內容的來源**：提案內容（`before`／`after`／`problems`）由案件側 `material_coverage.change_proposal`（2e）組成，本檔只驗證、保存、簽核、套用；
套用時再呼叫一次（`PROPOSAL_FN`）重驗，過期（採購單行不再涵蓋…）⇒ 409、什麼都不改。
**簽核**：重用 `helpers/tiered_approval.py` 原語（同 `material_approval`）；沒設簽核層＝送審即核准並立即套用。
**M2a 不登記簽核單據類型**：登記（`ensure_registered`）連同佇列／詳情／通知／覆蓋守門屬 M2b，一起上才不會讓「每個單據類型都要有佇列」的守門變紅。
所有函式**不 commit**（呼叫端在自己的寫入交易內提交）；失敗一律 raise `MaterialChangeError(status, 訊息, code)`。
"""
import json
from datetime import date, datetime

from helpers.tiered_approval import (
    APPROVAL_DOC_TYPES, UnresolvedManagerError, active_tiers, check_approve_permission, check_no_tier_self_approval,
    check_reject_permission, current_tier_idx, cascade_self_tiers, register_doc_type, resolve_active_flow_setting,
    setting_to_active_tiers, sign_first_pending,
)
from modules.case import material_approval as MA
from modules.case import material_payment as MP

DOC_TYPE = "material_change"
DOC_LABEL = "材料申請變更"
DOC_PREFIX = "MC"

S_DRAFT, S_PENDING, S_IN_PROGRESS, S_APPROVED, S_RETURNED, S_WITHDRAWN = "草稿", "待審核", "簽核中", "已核准", "已退回", "已撤回"
STATUSES = (S_DRAFT, S_PENDING, S_IN_PROGRESS, S_APPROVED, S_RETURNED, S_WITHDRAWN)
LIVE = (S_DRAFT, S_PENDING, S_IN_PROGRESS)       # 占用「一次一個」的狀態
IN_FLIGHT = (S_PENDING, S_IN_PROGRESS)
EDITABLE = (S_DRAFT, S_RETURNED, S_WITHDRAWN)    # 可以改提案內容並（重新）送審

#: 變更可動的欄位（與 `material_coverage.CHANGE_KEYS` 同一組；poSnapshot 存在審核列的 approval_json.snapshot，其餘在 materialOrders[該列]）
CHANGE_KEYS = ("quantity", "unit", "unitPrice", "totalPrice", "poSnapshot", "notes")
_ORDER_KEYS = ("quantity", "unit", "unitPrice", "totalPrice", "notes")
_MONEY = ("unitPrice", "totalPrice")
_NUM = ("quantity", "unitPrice", "totalPrice")

#: 出貨下限提供者（S 線）：`callable(conn, quote_no, item_id) -> 已出貨＋占用量（float）`；沒有提供者 ⇒ 略過檢查並在回應 `warnings` 註明。測試以 monkeypatch 設。
SHIPPED_PROVIDER = None
#: 套用前重驗提案用：`callable(conn, quote_no, item_id, proposed) -> {before, after, diff, problems}`（預設延遲取 `material_coverage.change_proposal`；沒有該模組 ⇒ 略過並警告）。
PROPOSAL_FN = None


class MaterialChangeError(Exception):
    def __init__(self, status: int, message: str, code: str = ""):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


def _supply_loaded() -> bool:
    """出貨模組（supply）在這個安裝包裡且已載入？（沒有提供者時，有它＝fail closed、沒有它＝警告放行。）"""
    try:
        from core import registry
        return bool(registry.is_loaded("supply"))
    except Exception:                                                                   # noqa: BLE001
        return False


def _shipped_fn():
    """出貨量提供者（c7 的出貨連動，契約 docs/platform/plans/SHIPPING-MATERIAL-LINK-CONTRACT-S1.md）：
    測試覆寫 `SHIPPED_PROVIDER` ＞ 註冊的 `shipping.material_shipped_qty`（float＝保留＋已出貨）＞ 包裝字典版 `shipping.material_shipped`
    （`{itemId: {reserved, shipped}}`）＞ None（沒有出貨連動 ⇒ 不檢查、回警告）。草稿出貨單不算保留（契約）。"""
    if SHIPPED_PROVIDER is not None:
        return SHIPPED_PROVIDER
    try:
        from core import registry
        q = registry.providers("shipping.material_shipped_qty").get("supply")
        if q is not None:
            return q
        d = registry.providers("shipping.material_shipped").get("supply")
    except Exception:                                                                    # noqa: BLE001 — 註冊表讀不到＝沒有提供者
        return None
    if d is None:
        return None

    def wrapped(conn, quote_no, item_id):
        row = (d(conn, quote_no) or {}).get(str(item_id)) or {}
        return float(row.get("reserved") or 0) + float(row.get("shipped") or 0)
    return wrapped


def ensure_registered():
    """登記簽核單據類型（M2b 在模組載入時呼叫；M2a 不自動登記）。冪等。"""
    if DOC_TYPE not in APPROVAL_DOC_TYPES:
        register_doc_type(DOC_TYPE, DOC_LABEL, unified=True)


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _display(user):
    return user.get("display_name") or user["username"]


def _j(text, default):
    try:
        v = json.loads(text or "")
    except (TypeError, ValueError):
        return default
    return v if isinstance(v, type(default)) else default


def _num(v):
    try:
        return round(float(v or 0), 4)
    except (TypeError, ValueError):
        return 0.0


# ── 讀 ───────────────────────────────────────────────────────────────

def get(conn, change_id):
    r = conn.execute("SELECT * FROM case_material_changes WHERE id=?", (int(change_id),)).fetchone()
    return dict(r) if r else None


def list_for_item(conn, quote_no, item_id) -> list:
    return [dict(r) for r in conn.execute("SELECT * FROM case_material_changes WHERE quote_no=? AND item_id=? ORDER BY id DESC", (quote_no, str(item_id)))]


def list_for_case(conn, quote_no) -> list:
    """這個案件所有材料申請的變更申請（新到舊）。"""
    return [dict(r) for r in conn.execute("SELECT * FROM case_material_changes WHERE quote_no=? ORDER BY id DESC", (quote_no,))]


def live_for(conn, quote_no, item_id):
    r = conn.execute("SELECT * FROM case_material_changes WHERE quote_no=? AND item_id=? AND status IN ('草稿','待審核','簽核中')", (quote_no, str(item_id))).fetchone()
    return dict(r) if r else None


def next_doc_code(conn, today: str = "") -> str:
    """`MC-YYYYMMDD-NNNN`（同 `material_approval.next_doc_code` 的寫法；呼叫端要已持有寫鎖，doc_code 另有唯一索引擋底）。"""
    day = (today or date.today().isoformat()).replace("-", "")
    stem = "%s-%s-" % (DOC_PREFIX, day)
    row = conn.execute("SELECT MAX(doc_code) FROM case_material_changes WHERE doc_code LIKE ? AND LENGTH(doc_code)=?", (stem + "%", len(stem) + 4)).fetchone()
    last = int(row[0][-4:]) if row and row[0] else 0
    return "%s%04d" % (stem, last + 1)


# ── 差異 ─────────────────────────────────────────────────────────────

def _norm(k, v):
    if k in _NUM:
        return _num(v)
    if k == "poSnapshot":
        return [{"poDocCode": x.get("poDocCode"), "line": x.get("line"), "qty": _num(x.get("qty")), "unit": str(x.get("unit") or ""), "amount": _num(x.get("amount"))}
                for x in (v or []) if isinstance(x, dict)]
    return str(v if v is not None else "").strip()


def compute_diff(before: dict, after: dict) -> list:
    """`[{field, old, new, money}]`（與 `material_coverage.change_proposal` 同形）。數字取 4 位小數、字串去空白後比較。"""
    out = []
    for k in CHANGE_KEYS:
        o, n = _norm(k, (before or {}).get(k)), _norm(k, (after or {}).get(k))
        if o != n:
            out.append({"field": k, "old": o, "new": n, "money": k in _MONEY})
    return out


# ── 驗證 ─────────────────────────────────────────────────────────────

def _order_of(conn, quote_no, item_id):
    r = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    if not r:
        return None, None
    data = _j(r["data_json"], {})
    orders = (data.get("caseRecord") or {}).get("materialOrders") if isinstance(data.get("caseRecord"), dict) else None
    for o in orders or []:
        if isinstance(o, dict) and str(o.get("itemId")) == str(item_id):
            return data, o
    return data, None


def validate(conn, quote_no, item_id, before: dict, after: dict, order: dict) -> dict:
    """提案內容檢查（建立與送審、套用前都跑）⇒ `{problems: [{code, message}], warnings: [str]}`。
    數字非負／數量>0／小計＝數量×單價（容差，單價可能是四捨五入的商）／已付鎖（D7 `paid_in_full`、`below_paid`）／不得使「已申請額度」超過新小計／
    不得低於已出貨＋占用（有出貨提供者才查）／沒有任何變更。"""
    problems, warnings = [], []
    q, u, t = _num(after.get("quantity")), _num(after.get("unitPrice")), _num(after.get("totalPrice"))
    if q <= 0:
        problems.append({"code": "bad_quantity", "message": "數量必須大於 0"})
    if u < 0 or t < 0:
        problems.append({"code": "bad_amount", "message": "單價與小計不可為負"})
    if q > 0 and abs(q * u - t) > 0.01 + 0.00005 * q:
        problems.append({"code": "bad_total", "message": "小計必須等於數量 × 單價"})
    snap = [x for x in (after.get("poSnapshot") or []) if isinstance(x, dict)]
    units = {str(x.get("unit") or "") for x in snap}
    if snap and len(units) == 1 and str(after.get("unit") or "") in units:                # 數量上限＝涵蓋的採購單行數量合計（單位一致時）：不能憑空灌大「可出貨量」（da）
        covered = sum(_num(x.get("qty")) for x in snap)
        if q > covered + 1e-9:
            problems.append({"code": "quantity_exceeds_coverage", "message": "數量 %s 超過已核准採購單行涵蓋的數量 %s" % (q, covered)})
    diff = compute_diff(before, after)
    if not diff:
        problems.append({"code": "no_change", "message": "沒有任何變更"})
    amount_changed = any(d["field"] in _NUM for d in diff)
    paid = MP.paid_so_far(conn, quote_no, item_id, order) if order is not None else 0.0
    old_total = _num((order or before).get("totalPrice"))
    if amount_changed and paid > 0 and paid >= old_total - 0.005:
        problems.append({"code": "paid_in_full", "message": "這筆材料申請已全額付款，金額不能修改；要調整請另開一筆材料申請（帶 adjustOf）。"})
    elif paid > 0 and t < paid - 0.005:
        problems.append({"code": "below_paid", "message": "新的小計低於已付金額（已付 %s），不能這樣變更。" % ("{:,.2f}".format(paid).rstrip("0").rstrip("."))})
    if order is not None and amount_changed:
        probe = dict(order)
        probe.update({"quantity": q, "unitPrice": u, "totalPrice": t})
        if MP.room_for(conn, quote_no, probe) < -0.005:
            problems.append({"code": "change_below_committed", "message": "新的小計低於已申請匯款的額度，請先處理匯款申請。"})
    ship = _shipped_fn()
    if ship is None:
        if _supply_loaded():                                                            # 出貨連動（supply）已啟用卻取不到出貨量 ⇒ fail closed：寧可擋也不讓人把已出貨的數量改小
            problems.append({"code": "shipped_unavailable", "message": "出貨連動已啟用但目前取不到已出貨量，暫時不能變更（避免把已出貨的數量改小）；請聯絡管理員"})
        else:                                                                           # 沒有出貨模組：沒有「已出貨」這件事，警告即可
            warnings.append("沒有出貨連動（出貨模組不存在），未檢查「不得低於已出貨＋占用量」")
    else:
        try:
            shipped = float(ship(conn, quote_no, item_id) or 0)
        except Exception:                                                              # noqa: BLE001 — 提供者壞了不可放行下限檢查，也不可讓變更整個爆掉
            problems.append({"code": "shipped_unavailable", "message": "暫時無法取得已出貨量，請稍後再試"})
        else:
            if q + 1e-9 < shipped:
                problems.append({"code": "change_below_shipped", "message": "新的數量低於已出貨與已占用的數量（%s）" % shipped})
    return {"problems": problems, "warnings": warnings, "diff": diff}


def _proposal_fn():
    """案件側提案函式（2e：`material_coverage.change_proposal`）；測試以 `PROPOSAL_FN` 注入。沒有 ⇒ None。"""
    if PROPOSAL_FN is not None:
        return PROPOSAL_FN
    try:
        from modules.case import material_coverage as _mc
    except ImportError:
        return None
    return _mc.change_proposal


def proposal(conn, quote_no, item_id, proposed=None) -> dict:
    """取得變更提案（`{itemId, before, after, diff, uncoveredLines, problems}`）：端點建立／預覽用。案件側提案函式還沒上線 ⇒ 501。"""
    fn = _proposal_fn()
    if fn is None:
        raise MaterialChangeError(501, "變更申請的提案功能尚未啟用", "proposal_unavailable")
    return fn(conn, quote_no, item_id, proposed or {})


def _reproposal(conn, quote_no, item_id, stored_after):
    """套用前重驗：用「儲存的數量／備註」重跑案件側提案；回 (cp 或 None, 警告)。"""
    fn = _proposal_fn()
    if fn is None:
        return None, "沒有案件側提案函式，套用前未重驗涵蓋範圍"
    proposed = {k: stored_after.get(k) for k in ("quantity", "notes") if k in stored_after}
    return fn(conn, quote_no, item_id, proposed), ""


# ── 建立／修改 ───────────────────────────────────────────────────────

def _live_check(conn, quote_no, item_id):
    if live_for(conn, quote_no, item_id):
        raise MaterialChangeError(409, "這筆材料申請已有進行中的變更申請，請先處理（核准／撤回／退回）", "change_in_progress")


def _precheck_base(conn, quote_no, item_id):
    row = MA.get(conn, quote_no, item_id)
    if row is None:
        raise MaterialChangeError(404, "這筆材料申請沒有審核單（舊單不走變更申請，直接修改即可）", "use_direct_edit")
    if row["status"] != MA.S_APPROVED:
        raise MaterialChangeError(409, "只有「已核准」的材料申請可以提變更申請（目前「%s」）" % row["status"], "not_approved")
    if not MA.po_required_for(row):
        raise MaterialChangeError(409, "這筆是規則上線前建立的單，直接修改即可（修改後需重新送審）", "use_direct_edit")
    data, order = _order_of(conn, quote_no, item_id)
    if order is None:
        raise MaterialChangeError(404, "找不到這筆材料申請", "not_found")
    return row, order


def _check_cp(cp):
    if not isinstance(cp, dict) or "before" not in cp or "after" not in cp:
        raise MaterialChangeError(400, "缺少變更提案內容", "bad_proposal")
    if cp.get("problems"):
        p = cp["problems"][0]
        raise MaterialChangeError(400, p.get("message") or "提案不成立", p.get("code") or "bad_proposal")


def create(conn, quote_no: str, item_id: str, user: dict, cp: dict, reason: str) -> dict:
    """建立變更申請（草稿）。`cp`＝案件側 `change_proposal` 的結果（before／after／diff／problems）；`reason` 必填。回變更列（dict）＋`warnings`。"""
    text = (reason or "").strip()
    if not text:
        raise MaterialChangeError(400, "變更原因必填", "reason_required")
    _check_cp(cp)
    row, order = _precheck_base(conn, quote_no, item_id)
    _live_check(conn, quote_no, item_id)
    res = validate(conn, quote_no, item_id, cp["before"], cp["after"], order)
    if res["problems"]:
        p = res["problems"][0]
        raise MaterialChangeError(400 if p["code"] not in ("change_below_shipped", "change_below_committed") else 409, p["message"], p["code"])
    now = _now()
    code = next_doc_code(conn)
    appr = {"history": [{"at": now, "by": user["username"], "byDisplay": _display(user), "action": "create", "tier": 0, "comment": text}]}
    conn.execute("INSERT INTO case_material_changes (quote_no, item_id, doc_code, status, base_version, proposal_json, base_json, diff_json, approval_json, reason,"
                 " created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (quote_no, str(item_id), code, S_DRAFT, int(row["version"] or 1), json.dumps(cp["after"], ensure_ascii=False), json.dumps(cp["before"], ensure_ascii=False),
                  json.dumps(res["diff"], ensure_ascii=False), json.dumps(appr, ensure_ascii=False), text, user["username"], now, now))
    out = live_for(conn, quote_no, item_id)
    out["warnings"] = res["warnings"]
    _audit(conn, user, "material_changes.create", quote_no, out, "建立材料申請變更 %s" % code)
    return out


def revise(conn, change_id, user: dict, cp: dict, reason: str = "") -> dict:
    """改提案內容（草稿／已退回／已撤回）；已退回／已撤回改完回「草稿」（仍受『一次一個』限制）。base_version 以目前審核列為準。"""
    ch = _must(conn, change_id)
    if ch["status"] not in EDITABLE:
        raise MaterialChangeError(409, "「%s」狀態不可修改" % ch["status"], "bad_status")
    _check_cp(cp)
    row, order = _precheck_base(conn, ch["quote_no"], ch["item_id"])
    if ch["status"] != S_DRAFT:
        _live_check(conn, ch["quote_no"], ch["item_id"])
    res = validate(conn, ch["quote_no"], ch["item_id"], cp["before"], cp["after"], order)
    if res["problems"]:
        p = res["problems"][0]
        raise MaterialChangeError(400, p["message"], p["code"])
    now = _now()
    text = (reason or "").strip() or ch["reason"]
    appr = _j(ch["approval_json"], {})
    appr.setdefault("history", []).append({"at": now, "by": user["username"], "byDisplay": _display(user), "action": "revise", "tier": 0, "comment": text})
    for k in ("tiers", "currentTier"):
        appr.pop(k, None)
    conn.execute("UPDATE case_material_changes SET status=?, base_version=?, proposal_json=?, base_json=?, diff_json=?, approval_json=?, reason=?, updated_at=? WHERE id=?",
                 (S_DRAFT, int(row["version"] or 1), json.dumps(cp["after"], ensure_ascii=False), json.dumps(cp["before"], ensure_ascii=False),
                  json.dumps(res["diff"], ensure_ascii=False), json.dumps(appr, ensure_ascii=False), text, now, int(change_id)))
    out = get(conn, change_id)
    out["warnings"] = res["warnings"]
    _audit(conn, user, "material_changes.revise", ch["quote_no"], out, "修改材料申請變更 %s" % ch["doc_code"])
    return out


def _must(conn, change_id):
    ch = get(conn, change_id)
    if ch is None:
        raise MaterialChangeError(404, "找不到這張變更申請", "not_found")
    return ch


def _save(conn, change_id, status, appr, now, **extra):
    sets, args = ["status=?", "approval_json=?", "updated_at=?"], [status, json.dumps(appr, ensure_ascii=False), now]
    for k, v in extra.items():
        sets.append("%s=?" % k)
        args.append(v)
    args.append(int(change_id))
    conn.execute("UPDATE case_material_changes SET %s WHERE id=?" % ", ".join(sets), args)


# ── 送審／核准／退回／撤回 ────────────────────────────────────────────

def _applicable(conn, ch):
    """核准前（與套用當下）能不能套：原審核列仍是「已核准」且版本沒變；案件側提案重驗無 problems 且 after 不變；提案內容仍通過驗證。回 (order, warnings)。"""
    quote_no, item_id = ch["quote_no"], ch["item_id"]
    row = MA.get(conn, quote_no, item_id)
    if row is None or row["status"] != MA.S_APPROVED or int(row["version"] or 1) != int(ch["base_version"]):
        raise MaterialChangeError(409, "原材料申請已被修改或取消（版本不符），這張變更申請作廢，請重新提案", "base_changed")
    _data, order = _order_of(conn, quote_no, item_id)
    if order is None:
        raise MaterialChangeError(404, "找不到這筆材料申請", "not_found")
    stored = _j(ch["proposal_json"], {})
    warnings = []
    cp, warn = _reproposal(conn, quote_no, item_id, stored)
    if warn:
        warnings.append(warn)
    if cp is not None:
        if cp.get("problems"):
            raise MaterialChangeError(409, "提案已過期：%s" % cp["problems"][0].get("message", ""), "proposal_stale")
        if compute_diff(cp.get("after") or {}, stored):
            raise MaterialChangeError(409, "採購單涵蓋範圍已有變動，提案內容已過期，請重新提案", "proposal_stale")
    res = validate(conn, quote_no, item_id, _j(ch["base_json"], {}), stored, order)
    if res["problems"]:
        p = res["problems"][0]
        raise MaterialChangeError(409, p["message"], p["code"])
    return order, warnings + res["warnings"]


def submit(conn, change_id, user: dict) -> dict:
    """送審（草稿／已退回／已撤回 → 待審核；沒設簽核層 ⇒ 直接核准並套用）。回 `{status, tierCount, firstApprovers, autoApproved, applied}`。"""
    ch = _must(conn, change_id)
    if ch["status"] not in EDITABLE:
        raise MaterialChangeError(409, "「%s」狀態不可送審" % ch["status"], "bad_status")
    if ch["status"] != S_DRAFT:
        _live_check(conn, ch["quote_no"], ch["item_id"])
    _applicable(conn, ch)
    flow = resolve_active_flow_setting(DOC_TYPE)
    try:
        tiers = setting_to_active_tiers(flow, conn, user["username"])
    except UnresolvedManagerError as e:
        raise MaterialChangeError(400, str(e), "unresolved_manager")
    now = _now()
    appr = _j(ch["approval_json"], {})
    hist = appr.get("history") or []
    diff = compute_diff(_j(ch["base_json"], {}), _j(ch["proposal_json"], {}))
    if ch["status"] != S_DRAFT:                                                         # 已退回／已撤回重送：回到草稿佔位（唯一索引在這裡擋同時兩張）
        conn.execute("UPDATE case_material_changes SET status=? WHERE id=?", (S_DRAFT, int(change_id)))
    if not tiers:
        appr.update({"autoApproved": True, "note": "未設定任何簽核層，送審即視為核准", "requestedBy": user["username"], "requestedByDisplay": _display(user), "requestedAt": now})
        hist.append({"at": now, "by": user["username"], "byDisplay": _display(user), "action": "submit", "tier": 0, "comment": "自動核准"})
        appr["history"] = hist
        _save(conn, change_id, S_IN_PROGRESS, appr, now, submitted_by=user["username"], submitted_at=now, diff_json=json.dumps(diff, ensure_ascii=False))
        applied = _apply(conn, change_id, user, now)
        _audit(conn, user, "material_changes.submit", ch["quote_no"], get(conn, change_id), "送審並自動核准材料申請變更 %s" % ch["doc_code"])
        return {"status": S_APPROVED, "tierCount": 0, "firstApprovers": [], "autoApproved": True, "applied": applied}
    appr = {"requestedBy": user["username"], "requestedByDisplay": _display(user), "requestedAt": now, "tiers": tiers, "currentTier": 0,
            "history": hist + [{"at": now, "by": user["username"], "byDisplay": _display(user), "action": "submit", "tier": 0, "comment": ""}]}
    _save(conn, change_id, S_PENDING, appr, now, submitted_by=user["username"], submitted_at=now, diff_json=json.dumps(diff, ensure_ascii=False))
    _audit(conn, user, "material_changes.submit", ch["quote_no"], get(conn, change_id), "送審材料申請變更 %s" % ch["doc_code"])
    return {"status": S_PENDING, "tierCount": len(tiers), "firstApprovers": [a["username"] for a in (tiers[0].get("approvers") or [])], "autoApproved": False, "applied": False}


def approve(conn, change_id, user: dict, comment: str = "", cascade: bool = False) -> dict:
    """核准當層；最後一層過了 ⇒ 同一個交易內原子套用（套不了就整個 raise、什麼都不改）。"""
    ch = _must(conn, change_id)
    if ch["status"] not in IN_FLIGHT:
        raise MaterialChangeError(409, "「%s」狀態不在簽核中" % ch["status"], "bad_status")
    appr = _j(ch["approval_json"], {})
    tiers = active_tiers(appr)
    ct = current_tier_idx(appr)
    if tiers:
        ok, code, msg = check_approve_permission(tiers, ct, user["username"], conn)
        if not ok:
            raise MaterialChangeError(code, msg, "forbidden")
    else:
        err = check_no_tier_self_approval(conn, appr, user)
        if err:
            raise MaterialChangeError(403, err, "forbidden")
    now = _now()
    tier_done = sign_first_pending(tiers[ct], user, now, conn=conn) if tiers else True
    cascaded = cascade_self_tiers(tiers, ct, user["username"], now, conn=conn) if (tiers and tier_done and cascade) else []
    appr["tiers"] = tiers
    appr["currentTier"] = (ct + 1 + len(cascaded)) if tier_done else ct
    done = appr["currentTier"] >= len(tiers)
    appr.setdefault("history", []).append({"at": now, "by": user["username"], "byDisplay": _display(user), "action": "approve", "tier": ct, "comment": comment or ""})
    if done:
        _applicable(conn, ch)                                                            # 先確認套得了：不行就 raise，這一層的簽名也不留下
        _save(conn, change_id, S_IN_PROGRESS, appr, now)
        applied = _apply(conn, change_id, user, now)
    else:
        _save(conn, change_id, S_IN_PROGRESS, appr, now)
        applied = False
    nxt = [] if done else [a["username"] for a in (tiers[appr["currentTier"]].get("approvers") or [])]
    _audit(conn, user, "material_changes.approve", ch["quote_no"], get(conn, change_id), "核准材料申請變更 %s%s" % (ch["doc_code"], "（已套用）" if done else ""))
    return {"status": S_APPROVED if done else S_IN_PROGRESS, "currentTier": appr["currentTier"], "nextApprovers": nxt, "requester": appr.get("requestedBy", ""),
            "done": done, "applied": applied, "tierNo": appr["currentTier"] + 1, "totalTiers": len(tiers)}


def reject(conn, change_id, user: dict, reason: str) -> dict:
    """退回（當層簽核人或 superadmin；原因必填）→ 已退回。原材料申請完全不動。"""
    ch = _must(conn, change_id)
    if ch["status"] not in IN_FLIGHT:
        raise MaterialChangeError(409, "「%s」狀態不在簽核中" % ch["status"], "bad_status")
    appr = _j(ch["approval_json"], {})
    tiers, ct = active_tiers(appr), current_tier_idx(appr)
    ok, code, msg = check_reject_permission(tiers, ct, user, conn)
    if not ok:
        raise MaterialChangeError(code, msg, "forbidden")
    text = (reason or "").strip()
    if not text:
        raise MaterialChangeError(400, "退回要填原因", "reason_required")
    now = _now()
    appr.setdefault("history", []).append({"at": now, "by": user["username"], "byDisplay": _display(user), "action": "reject", "tier": ct, "comment": text})
    appr.update({"rejectedAt": now, "rejectedByDisplay": _display(user), "rejectReason": text})
    _save(conn, change_id, S_RETURNED, appr, now)
    _audit(conn, user, "material_changes.reject", ch["quote_no"], get(conn, change_id), "退回材料申請變更 %s：%s" % (ch["doc_code"], text))
    return {"status": S_RETURNED, "requester": appr.get("requestedBy", ""), "reason": text}


def withdraw(conn, change_id, user: dict) -> dict:
    """撤回：草稿／待審核／簽核中 → 已撤回（建單人、送審人或 admin 以上）。原材料申請完全不動。"""
    ch = _must(conn, change_id)
    if ch["status"] not in LIVE:
        raise MaterialChangeError(409, "「%s」狀態不可撤回" % ch["status"], "bad_status")
    appr = _j(ch["approval_json"], {})
    owner = {appr.get("requestedBy"), ch["created_by"]}
    if user["username"] not in owner and user["role"] not in ("admin", "superadmin"):
        raise MaterialChangeError(403, "只有建單人、送審人或管理員可以撤回", "forbidden")
    now = _now()
    appr.setdefault("history", []).append({"at": now, "by": user["username"], "byDisplay": _display(user), "action": "withdraw", "tier": current_tier_idx(appr), "comment": ""})
    for k in ("tiers", "currentTier"):
        appr.pop(k, None)
    _save(conn, change_id, S_WITHDRAWN, appr, now)
    _audit(conn, user, "material_changes.withdraw", ch["quote_no"], get(conn, change_id), "撤回材料申請變更 %s" % ch["doc_code"])
    return {"status": S_WITHDRAWN}


# ── 原子套用 ─────────────────────────────────────────────────────────

def _apply(conn, change_id, user: dict, now: str) -> bool:
    """把已核准的變更寫回材料申請（呼叫端交易內；任一步 raise ⇒ 呼叫端回滾，整件都不生效）。
    ① 檢查（`_applicable`：版本、案件側重驗、驗證）② 寫 materialOrders[該列] 的 quantity／unit／unitPrice／totalPrice／notes ③ 審核列：version+1、
    content_hash 重算、歷程 `changed`、`snapshot.poSnapshot` 換成新涵蓋快照、**`received_*` 保留** ④ 重投影付款狀態 ⑤ 變更列＝已核准。"""
    ch = _must(conn, change_id)
    quote_no, item_id = ch["quote_no"], ch["item_id"]
    order_before, _w = _applicable(conn, ch)
    stored = _j(ch["proposal_json"], {})
    diff = compute_diff(_j(ch["base_json"], {}), stored)
    data, order = _order_of(conn, quote_no, item_id)
    for k in _ORDER_KEYS:
        if k in stored:
            order[k] = stored[k]
    # 系統自己的投影（同 sync_order_paid），不經 material_guard；直接寫 data_json、不經 save_quotation_json ⇒ 不更新 updated_at／熱欄位
    # （材料申請欄位目前不影響報價單的熱欄位；若之後有欄位進熱欄位，這裡要改走 save_quotation_json）。
    conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(data, ensure_ascii=False), quote_no))
    row = MA.get(conn, quote_no, item_id)
    appr = _j(row["approval_json"], {})
    snap = appr.get("snapshot") if isinstance(appr.get("snapshot"), dict) else {}
    if "poSnapshot" in stored:
        snap["poSnapshot"] = stored["poSnapshot"]
        appr["snapshot"] = snap
    summary = "、".join("%s %s→%s" % (d["field"], d["old"] if d["field"] != "poSnapshot" else "%d 行" % len(d["old"]),
                                     d["new"] if d["field"] != "poSnapshot" else "%d 行" % len(d["new"])) for d in diff)
    appr.setdefault("history", []).append({"at": now, "by": user["username"], "byDisplay": _display(user), "action": "changed", "tier": 0,
                                           "comment": "變更申請 %s 核准套用：%s" % (ch["doc_code"], summary), "changeId": int(change_id)})
    conn.execute("UPDATE case_material_approvals SET version=?, content_hash=?, approval_json=?, updated_at=? WHERE quote_no=? AND item_id=?",
                 (int(row["version"] or 1) + 1, MA.content_hash(order), json.dumps(appr, ensure_ascii=False), now, quote_no, str(item_id)))
    MP.sync_order_paid(conn, quote_no, item_id)
    conn.execute("UPDATE case_material_changes SET status=?, approved_at=?, applied_at=?, updated_at=? WHERE id=?", (S_APPROVED, now, now, now, int(change_id)))
    _audit(conn, user, "material_changes.apply", quote_no, get(conn, change_id), "材料申請變更 %s 已套用：%s" % (ch["doc_code"], summary))
    return True


# ── 稽核（與請求同一交易；稽核表缺欄的舊庫不因此擋）────────────────────

def _audit(conn, user, action, quote_no, ch, label):
    try:
        conn.execute("INSERT INTO audit_log (at,user_id,username,display_name,action,target_type,target_id,target_label,detail) VALUES (?,?,?,?,?,?,?,?,?)",
                     (_now(), user.get("id"), user.get("username") or "", user.get("display_name") or "", action, "quotation", quote_no, label,
                      json.dumps({"docCode": (ch or {}).get("doc_code"), "itemId": (ch or {}).get("item_id"), "status": (ch or {}).get("status")}, ensure_ascii=False)))
    except Exception:                                                                    # noqa: BLE001
        pass
