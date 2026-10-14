# -*- coding: utf-8 -*-
"""流程定義的文法、驗證器、靜態分析與寬嚴比較（BP-5 P1；設計 docs/platform/plans/BP5-WORKFLOW-BUILDER-DESIGN-T62.md §3、§5、§6）。

[單位] helper:workflow_grammar    [層] L0（純函式，不碰資料庫／FastAPI）    [穩定度] 實驗（沒有任何執行期呼叫端）
[公開介面] GUARDS, ACTIONS, validate_workflow, analyze, compare
[不變式] ①定義是資料：守門只能從 GUARDS 挑、回呼只能從 ACTIONS 挑，建構器不能新增任何一項（沒有任意程式／運算式）；
    ②金額類（money）與會計入帳類（ledger）單據在第一期一律不接受任何公司版本（D-W1：唯讀）；plain 才可發布；
    ③`approved` 語意只能經簽核（who=tier）進入，或在 approval.exemption 有記錄在案的豁免時才可不經簽核；
    ④寫入類回呼（write）只能掛在對的轉換（扣庫存只在進入 approved、還庫存只在離開 approved），而且不可被拿掉（比較器視為放寬、驗證器對照內建版擋下）；
    ⑤比較器：無法判斷一律放寬；方向由內容決定，不寫死「增加＝收緊」。
[契約題] backend/tests/test_workflow_grammar_2026_10_14.py
"""
import re

SEMANTICS = ("draft", "pending", "approved", "closed", "void")
REQUIRED_SEMANTICS = ("draft", "pending", "approved")
WHO = ("owner_or_admin", "admin", "superadmin", "tier")
REASON = ("none", "optional", "required")
LOG = ("none", "basic", "full")
TONES = ("gray", "blue", "amber", "green", "red")
_ID = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

# 守門目錄：每一項對應今天某個端點裡的一個既有條件（盤點 BP5-FLOW-INVENTORY-T62.md §2.1）。建構器只能開關，不能新增。
GUARDS = {
    "has_items": "至少要有一項品項／完工項目說明（submit）",
    "completion_date_required": "完工日期必填（完工單 submit）",
    "material_link_check": "材料申請連結檢查（出貨單 submit）",
    "serials_in_stock": "出貨序號必須仍在庫（出貨單 approve）",
    "no_self_approval": "沒有簽核層時的自簽防護（approve 的最高管理者後備路徑）",
    "not_customer_signed": "客戶已回簽就不可撤銷核准（revoke）",
    "not_exported": "已匯出就不可撤銷核准（請款／開票申請 revoke）",
    "status_is_approved": "只有已核准狀態可標記回簽",
}

# 動作（回呼）目錄：kind 決定能不能被拿掉；tx 決定在交易內（失敗＝整個轉換失敗）或 commit 之後（失敗不回滾）。
ACTIONS = {
    "notify_requester": {"kind": "notify", "tx": "after", "removable": True},
    "notify_next_tier": {"kind": "notify", "tx": "after", "removable": True},
    "notify_module_activity": {"kind": "notify", "tx": "after", "removable": True},
    "fire_expense_notify": {"kind": "notify", "tx": "after", "removable": True},
    "gen_pdf": {"kind": "render", "tx": "after", "removable": True},
    "calendar_push": {"kind": "push", "tx": "after", "removable": True},
    "stock_deduct": {"kind": "write", "tx": "in", "removable": False, "only_entering": "approved"},
    "stock_return": {"kind": "write", "tx": "in", "removable": False, "only_leaving": "approved"},
}

_WHO_RANK = {"owner_or_admin": 0, "admin": 1, "superadmin": 2}          # 數字越大越嚴；tier 與它們不可比
_REASON_RANK = {"none": 0, "optional": 1, "required": 2}
_LOG_RANK = {"none": 0, "basic": 1, "full": 2}


def _p(path, msg):
    return {"path": path, "message": msg}


def _is_list(v):
    return isinstance(v, list)


def _doc_class(doc_type):
    from helpers import tiered_approval as T
    return T.doc_class(doc_type)


def validate_workflow(body, doc_type) -> list:
    """⇒ 問題清單（空＝合格）。結構驗證＋單據類別限制＋靜態分析。不丟例外。"""
    try:
        return _validate(body, doc_type)
    except Exception as e:                                           # noqa: BLE001  驗證器壞掉 ⇒ 不放行
        return [_p("", "流程定義無法驗證（%s）" % type(e).__name__)]


def _validate(body, doc_type) -> list:
    out = []
    cls = _doc_class(doc_type)
    if cls == "ledger":
        return [_p("", "會計入帳／法定類型的單據不在可編輯範圍")]
    if cls == "money":
        return [_p("", "金額單據的流程在第一期唯讀，不接受公司版本")]
    if not isinstance(body, dict):
        return [_p("", "流程定義必須是物件")]
    if body.get("docType") != doc_type:
        out.append(_p("docType", "docType 必須等於 %s" % doc_type))
    states, trans = body.get("states"), body.get("transitions")
    if not _is_list(states) or not states or not all(isinstance(s, dict) for s in states):
        return out + [_p("states", "states 必須是非空的物件清單")]
    if not _is_list(trans) or not all(isinstance(t, dict) for t in trans):
        return out + [_p("transitions", "transitions 必須是物件清單")]
    ids = {}
    for i, s in enumerate(states):
        sid = s.get("id")
        if not isinstance(sid, str) or not _ID.match(sid):
            out.append(_p("states[%d].id" % i, "狀態代號不合法"))
            continue
        if sid in ids:
            out.append(_p("states[%d].id" % i, "狀態代號重複：%s" % sid))
        ids[sid] = s.get("semantic")
        if s.get("semantic") not in SEMANTICS:
            out.append(_p("states[%d].semantic" % i, "語意標籤必須是 %s" % "／".join(SEMANTICS)))
        if not isinstance(s.get("label"), str) or not s["label"].strip() or len(s["label"]) > 20:
            out.append(_p("states[%d].label" % i, "狀態名稱必填且不超過 20 字"))
        if s.get("tone") is not None and s["tone"] not in TONES:
            out.append(_p("states[%d].tone" % i, "顏色不合法"))
    sems = list(ids.values())
    for need in REQUIRED_SEMANTICS:
        if sems.count(need) < 1:
            out.append(_p("states", "至少要有一個語意為 %s 的狀態" % need))
    if sems.count("draft") > 1:
        out.append(_p("states", "起始（draft 語意）狀態必須唯一"))
    tids = set()
    for i, t in enumerate(trans):
        path = "transitions[%d]" % i
        tid = t.get("id")
        if not isinstance(tid, str) or not _ID.match(tid):
            out.append(_p(path + ".id", "轉換代號不合法"))
        elif tid in tids:
            out.append(_p(path + ".id", "轉換代號重複：%s" % tid))
        else:
            tids.add(tid)
        frm = t.get("from")
        if not _is_list(frm) or not frm or any(f not in ids for f in frm) or len(set(frm)) != len(frm):
            out.append(_p(path + ".from", "from 必須是已存在且不重複的狀態清單"))
        if t.get("to") not in ids:
            out.append(_p(path + ".to", "to 必須是已存在的狀態"))
        if t.get("who") not in WHO:
            out.append(_p(path + ".who", "who 必須是 %s" % "／".join(WHO)))
        if t.get("reason") not in REASON:
            out.append(_p(path + ".reason", "reason 必須是 %s" % "／".join(REASON)))
        if t.get("log") not in LOG:
            out.append(_p(path + ".log", "log 必須是 %s" % "／".join(LOG)))
        for key, catalog in (("guards", GUARDS), ("callbacks", ACTIONS)):
            v = t.get(key, [])
            if not _is_list(v) or len(set(map(str, v))) != len(v):
                out.append(_p(path + "." + key, key + " 必須是不重複的清單"))
                continue
            for x in v:
                if x not in catalog:
                    out.append(_p(path + "." + key, "不在目錄內：%s（建構器不能新增）" % x))
        out += _check_callback_placement(t, ids, path)
    ap = body.get("approval")
    if not isinstance(ap, dict) or not isinstance(ap.get("required"), bool):
        out.append(_p("approval", "approval.required 必須是布林"))
    elif not ap["required"]:
        ex = ap.get("exemption")
        if not isinstance(ex, dict) or not isinstance(ex.get("policy"), int) or isinstance(ex.get("policy"), bool):
            out.append(_p("approval.exemption", "關閉簽核必須有記錄在案的豁免（policy 編號）"))
    el = body.get("editLock")
    if not isinstance(el, dict) or not _is_list(el.get("editableIn")) or any(x not in ids for x in el["editableIn"]):
        out.append(_p("editLock.editableIn", "editableIn 必須是已存在的狀態清單"))
    if body.get("returnLog") not in LOG:
        out.append(_p("returnLog", "returnLog 必須是 %s" % "／".join(LOG)))
    if out:
        return out
    return analyze(body)


def _check_callback_placement(t, ids, path):
    out = []
    to_sem = ids.get(t.get("to"))
    from_sems = {ids.get(f) for f in (t.get("from") or []) if isinstance(f, str)}
    for cb in (t.get("callbacks") or []):
        spec = ACTIONS.get(cb)
        if not spec:
            continue
        if spec.get("only_entering") and to_sem != spec["only_entering"]:
            out.append(_p(path + ".callbacks", "%s 只能掛在進入 %s 的轉換" % (cb, spec["only_entering"])))
        if spec.get("only_leaving") and not (from_sems == {spec["only_leaving"]} and to_sem != spec["only_leaving"]):
            out.append(_p(path + ".callbacks", "%s 只能掛在離開 %s 的轉換" % (cb, spec["only_leaving"])))
    return out


def analyze(body) -> list:
    """靜態分析（假設結構已通過）：可達性、無卡死狀態、通往 approved 的每條路徑必經簽核或有豁免。"""
    out = []
    sem = {s["id"]: s["semantic"] for s in body["states"]}
    trans = body["transitions"]
    start = next(i for i, v in sem.items() if v == "draft")

    def reach(allowed):
        seen, todo = {start}, [start]
        while todo:
            cur = todo.pop()
            for t in trans:
                if cur in t["from"] and allowed(t) and t["to"] not in seen:
                    seen.add(t["to"])
                    todo.append(t["to"])
        return seen
    seen = reach(lambda t: True)
    for sid in sem:
        if sid not in seen:
            out.append(_p("states", "狀態 %s 從起始狀態無法到達" % sid))
    if not any(sem[x] == "approved" for x in seen):
        out.append(_p("states", "沒有任何路徑可以到達已核准（approved）"))
    for sid, v in sem.items():
        if sid in seen and v not in ("closed", "void") and not any(sid in t["from"] and t["to"] != sid for t in trans):
            out.append(_p("states", "狀態 %s 只進不出（卡死）" % sid))
    ap = body["approval"]
    non_tier_seen = reach(lambda t: t["who"] != "tier")
    if ap["required"] and any(sem[x] == "approved" for x in non_tier_seen):
        out.append(_p("approval", "要求簽核，但有不經簽核（who=tier）就能到達已核准的路徑"))
    for i, t in enumerate(trans):
        if sem[t["to"]] == "approved" and t["who"] != "tier" and ap["required"] and any(sem[f] != "approved" for f in t["from"]):
            out.append(_p("transitions[%d]" % i, "進入已核准的轉換必須由簽核層執行（who=tier）"))
        if t["who"] == "tier" and not any(sem[f] == "pending" for f in t["from"]):
            out.append(_p("transitions[%d]" % i, "簽核層的轉換必須從待簽狀態（pending 語意）出發"))
    return out


# ── 寬嚴比較 ────────────────────────────────────────────────────────────────────────────────────────
def compare(old, new):
    """⇒ (class, reasons)；class ∈ loosen／tighten／neutral。任何看不懂／不可比的差異 ⇒ loosen（整體取最寬鬆者）。不丟例外。"""
    try:
        return _compare(old, new)
    except Exception:                                                # noqa: BLE001  格式怪到比不下去 ⇒ 放寬
        return "loosen", ["流程定義格式無法比較"]


def _compare(old, new):
    reasons_l, reasons_t = [], []

    def loose(msg):
        reasons_l.append(msg)

    def tight(msg):
        reasons_t.append(msg)
    if not isinstance(old, dict) or not isinstance(new, dict) or not isinstance(old.get("transitions"), list) or not isinstance(new.get("transitions"), list):
        return "loosen", ["流程定義格式無法比較"]
    if old.get("docType") != new.get("docType"):
        loose("單據類型改變")
    oa, na = old.get("approval") or {}, new.get("approval") or {}
    if oa.get("required") is True and na.get("required") is False:
        loose("關閉簽核（豁免）")
    elif oa.get("required") is False and na.get("required") is True:
        tight("開啟簽核")
    elif oa.get("required") is False and na.get("required") is False and oa.get("exemption") != na.get("exemption"):
        loose("豁免內容改變")
    elif oa.get("required") not in (True, False) or na.get("required") not in (True, False):
        loose("簽核設定無法比較")
    olds = {s.get("id"): s for s in old.get("states") or [] if isinstance(s, dict)}
    news = {s.get("id"): s for s in new.get("states") or [] if isinstance(s, dict)}
    for sid in set(olds) & set(news):
        if olds[sid].get("semantic") != news[sid].get("semantic"):
            loose("狀態 %s 的語意標籤改變" % sid)
    ot = {t.get("id"): t for t in old["transitions"] if isinstance(t, dict)}
    nt = {t.get("id"): t for t in new["transitions"] if isinstance(t, dict)}
    for tid in sorted(set(nt) - set(ot), key=str):
        loose("新增轉換 %s" % tid)
    for tid in sorted(set(ot) - set(nt), key=str):
        loose("移除轉換 %s" % tid)
    for tid in sorted(set(ot) & set(nt), key=str):
        _cmp_transition(tid, ot[tid], nt[tid], loose, tight)
    oe, ne = (old.get("editLock") or {}).get("editableIn"), (new.get("editLock") or {}).get("editableIn")
    if isinstance(oe, list) and isinstance(ne, list):
        if set(ne) - set(oe):
            loose("可編輯的狀態變多")
        elif set(oe) - set(ne):
            tight("可編輯的狀態變少")
    elif oe != ne:
        loose("編輯鎖無法比較")
    ol, nl = old.get("returnLog"), new.get("returnLog")
    if ol != nl:
        if ol in _LOG_RANK and nl in _LOG_RANK:
            (tight if _LOG_RANK[nl] > _LOG_RANK[ol] else loose)("退回紀錄等級改變：%s → %s" % (ol, nl))
        else:
            loose("退回紀錄等級無法比較")
    if reasons_l:
        return "loosen", reasons_l
    if reasons_t:
        return "tighten", reasons_t
    return "neutral", []


def _cmp_transition(tid, o, n, loose, tight):
    of, nf = set(o.get("from") or []), set(n.get("from") or [])
    if nf - of:
        loose("轉換 %s 可從更多狀態觸發" % tid)
    elif of - nf:
        tight("轉換 %s 可觸發的狀態變少" % tid)
    if o.get("to") != n.get("to"):
        loose("轉換 %s 的目的地改變" % tid)
    ow, nw = o.get("who"), n.get("who")
    if ow != nw:
        if ow in _WHO_RANK and nw in _WHO_RANK:
            (tight if _WHO_RANK[nw] > _WHO_RANK[ow] else loose)("轉換 %s 的執行者改變：%s → %s" % (tid, ow, nw))
        else:
            loose("轉換 %s 的執行者改變（簽核層與角色不可比）" % tid)
    orr, nr = o.get("reason"), n.get("reason")
    if orr != nr:
        if orr in _REASON_RANK and nr in _REASON_RANK:
            (tight if _REASON_RANK[nr] > _REASON_RANK[orr] else loose)("轉換 %s 的原因要求改變" % tid)
        else:
            loose("轉換 %s 的原因要求無法比較" % tid)
    og, ng = o.get("log"), n.get("log")
    if og != ng:
        if og in _LOG_RANK and ng in _LOG_RANK:
            (tight if _LOG_RANK[ng] > _LOG_RANK[og] else loose)("轉換 %s 的紀錄等級改變" % tid)
        else:
            loose("轉換 %s 的紀錄等級無法比較" % tid)
    og_, ng_ = o.get("guards") or [], n.get("guards") or []
    if not isinstance(og_, list) or not isinstance(ng_, list) or any(x not in GUARDS for x in set(map(str, og_)) | set(map(str, ng_))):
        loose("轉換 %s 的守門無法比較" % tid)
    elif set(og_) - set(ng_):
        loose("轉換 %s 拿掉守門：%s" % (tid, "、".join(sorted(set(og_) - set(ng_)))))
    elif set(ng_) - set(og_):
        tight("轉換 %s 加了守門：%s" % (tid, "、".join(sorted(set(ng_) - set(og_)))))
    oc, nc = o.get("callbacks") or [], n.get("callbacks") or []
    if not isinstance(oc, list) or not isinstance(nc, list) or any(x not in ACTIONS for x in set(map(str, oc)) | set(map(str, nc))):
        loose("轉換 %s 的回呼無法比較" % tid)
        return
    for x in set(oc) ^ set(nc):
        if ACTIONS[x]["kind"] == "write":
            loose("轉換 %s 的寫入類回呼改變：%s" % (tid, x))


def removed_write_callbacks(baseline, candidate) -> list:
    """候選版相對內建基準拿掉了哪些『不可移除』的寫入類回呼（驗證器的第二道：對照內建版）。⇒ [(transition, action)]"""
    out = []
    cand = {t.get("id"): set(t.get("callbacks") or []) for t in candidate.get("transitions") or [] if isinstance(t, dict)}
    for t in baseline.get("transitions") or []:
        for cb in t.get("callbacks") or []:
            spec = ACTIONS.get(cb)
            if spec and not spec["removable"] and cb not in cand.get(t.get("id"), set()):
                out.append((t.get("id"), cb))
    return out
