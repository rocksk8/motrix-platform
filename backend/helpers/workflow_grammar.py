# -*- coding: utf-8 -*-
"""流程定義的文法、驗證器、靜態分析與寬嚴比較（BP-5 P1；設計 docs/platform/plans/BP5-WORKFLOW-BUILDER-DESIGN-T62.md §3、§5、§6）。

[單位] helper:workflow_grammar    [層] L1 （純函式，不碰資料庫／FastAPI）    [穩定度] 實驗（沒有任何執行期呼叫端）
[公開介面] GUARDS, ACTIONS, SEMANTICS, REQUIRED_SEMANTICS, WHO, REASON, LOG, TONES, TIER_ROLES, OFFICIAL_WORDS, EXEMPTION_REGISTER, DEPENDENCIES, validate_workflow, analyze, compare, removed_write_callbacks
[不變式] ⓪單據風險類（tiered_approval.DOC_CLASS）：plain 可完整調整；stock（核准會動庫存）不可關簽核、回呼只能保留；money／ledger 第一期不接受公司版本；
    ①定義是資料：守門只能從 GUARDS 挑、回呼只能從 ACTIONS 挑，建構器不能新增任何一項（沒有任意程式／運算式）；
    ②金額類（money）與會計入帳類（ledger）單據在第一期一律不接受任何公司版本（D-W1：唯讀）；plain／stock 才可發布；
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
    "notify_first_tier": {"kind": "notify", "tx": "in", "removable": True},        # submit：通知第 0 層簽核人（端點內、commit 之前呼叫）
    "notify_org_chain": {"kind": "notify", "tx": "in", "removable": True},         # submit：整條簽核鏈只有申請人時的組織職權知會
    "gen_pdf": {"kind": "render", "tx": "after", "removable": True},
    "calendar_push": {"kind": "push", "tx": "after", "removable": True},
    "stock_deduct": {"kind": "write", "tx": "in", "removable": False, "only_entering": "approved"},
    "stock_return": {"kind": "write", "tx": "in", "removable": False, "only_leaving": "approved"},
}

# 已知的相依關係：改這些單據的簽核／狀態名稱會牽動別處（宣告出來，比較器與介面據此警示；不是新的守門）。
DEPENDENCIES = {
    "completion": [
        {"id": "completion_counted_statuses", "where": "modules/case/completion_sync.py:23 COUNTED_NOTE_STATUSES",
         "note": "已完工數統計依資料庫狀態值『待審核／簽核中／已核准』計算；狀態的資料庫值必須維持內建值，只能改顯示名稱（P2 要求）"},
        {"id": "case_close_gate", "where": "modules/case/api/quotations.py:2230-2283 _CLOSE_DOC_TABLES＋_close_gate_facts（完工單與出貨單都在內）",
         "note": "案件結案閘門以資料庫狀態值『待審核／簽核中』判定還有單據在簽；待簽語意的狀態若換了資料庫值就會逃過閘門、讓案件被結案。關閉完工單簽核＝單據永遠不會進入待簽，閘門也就少一道人工確認"},
        {"id": "pending_queue", "where": "helpers/approval_queue.py:26 ACTIVE_STATUSES；modules/case/api/quotations.py 待簽佇列 SQL（約 4850、4886）",
         "note": "待簽佇列同樣寫死『待審核／簽核中』；閘門與佇列在 P2 前都必須改成讀語意（pending），待簽語意的狀態必須對應既有資料庫值"},
    ],
    "shipping": [
        {"id": "stock_flip", "where": "modules/supply/api/shipping_notes.py approve（stock_items UPDATE，同一交易）",
         "note": "核准會把庫存序號改為已出貨；撤銷核准會歸還"},
        {"id": "case_close_gate", "where": "modules/case/api/quotations.py:2230-2283 _CLOSE_DOC_TABLES＋_close_gate_facts",
         "note": "同完工單：待簽語意的狀態必須對應資料庫值『待審核／簽核中』，否則逃過結案閘門"},
        {"id": "pending_queue", "where": "helpers/approval_queue.py:26 ACTIVE_STATUSES",
         "note": "同完工單：待簽佇列讀寫死的狀態值"},
    ],
}

# 簽核層轉換的角色（明講『最後一層才進 approved』）：step＝中間層簽完、仍在待簽；final＝最後一層簽完才進 approved；return＝簽核人退回。
TIER_ROLES = ("step", "final", "return")
# 各層允許的欄位；多出來的欄位一律拒絕（否則比較器會忽略它們，卻可能被日後的執行層讀到）
_KEYS = {
    "body": {"docType", "origin", "version", "states", "transitions", "approval", "editLock", "returnLog"},
    "state": {"id", "label", "tone", "semantic"},
    "transition": {"id", "from", "to", "who", "reason", "log", "guards", "callbacks", "tierRole"},
    "approval": {"required", "exemption"},
    "exemption": {"policy"},
    "editLock": {"editableIn"},
}
# 官方狀態用語：只有 approved 語意的狀態可以用（否則一個『待審核』狀態可以掛上『已核准』的名字誤導讀者）
OFFICIAL_WORDS = ("核准", "批准", "核可", "已簽核", "簽核完成", "審核通過")
# P8 免簽核豁免登記表（policy 編號 → 帳本 id）。**第一期沒有這張表**：空集合＝任何豁免都不被接受（關簽核暫時不可發布）；
# P2 以真正的登記（帳本）取代這個集合。
EXEMPTION_REGISTER = set()

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
    if cls not in ("plain", "stock"):
        return [_p("", "金額單據的流程在第一期唯讀，不接受公司版本")]
    if not isinstance(body, dict):
        return [_p("", "流程定義必須是物件")]
    out += _unknown_keys(body, "body", "")
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
        out += _unknown_keys(s, "state", "states[%d]" % i)
        if s.get("semantic") not in SEMANTICS:
            out.append(_p("states[%d].semantic" % i, "語意標籤必須是 %s" % "／".join(SEMANTICS)))
        if not isinstance(s.get("label"), str) or not s["label"].strip() or len(s["label"]) > 20:
            out.append(_p("states[%d].label" % i, "狀態名稱必填且不超過 20 字"))
        elif s.get("semantic") != "approved" and any(w in s["label"] for w in OFFICIAL_WORDS):
            out.append(_p("states[%d].label" % i, "非『已核准』語意的狀態名稱不可使用官方用語（%s）" % "、".join(OFFICIAL_WORDS)))
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
        out += _unknown_keys(t, "transition", path)
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
        if t.get("who") == "tier":
            if t.get("tierRole") not in TIER_ROLES:
                out.append(_p(path + ".tierRole", "簽核層轉換必須宣告 tierRole：%s" % "／".join(TIER_ROLES)))
        elif "tierRole" in t:
            out.append(_p(path + ".tierRole", "只有 who=tier 的轉換可以有 tierRole"))
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
    else:
        out += _unknown_keys(ap, "approval", "approval")
        if not ap["required"] and cls == "stock":
            out.append(_p("approval", "核准會異動庫存的單據不可關閉簽核"))
        elif not ap["required"]:
            ex = ap.get("exemption")
            if not isinstance(ex, dict) or not isinstance(ex.get("policy"), int) or isinstance(ex.get("policy"), bool):
                out.append(_p("approval.exemption", "關閉簽核必須有記錄在案的豁免（policy 編號）"))
            else:
                out += _unknown_keys(ex, "exemption", "approval.exemption")
                if ex["policy"] not in EXEMPTION_REGISTER:
                    out.append(_p("approval.exemption.policy", "豁免編號 %s 不在 P8 豁免登記表內（登記表第一期尚不存在 ⇒ 暫時不能關閉簽核）" % ex["policy"]))
    el = body.get("editLock")
    if not isinstance(el, dict) or not _is_list(el.get("editableIn")) or any(x not in ids for x in el["editableIn"]):
        out.append(_p("editLock.editableIn", "editableIn 必須是已存在的狀態清單"))
    else:
        out += _unknown_keys(el, "editLock", "editLock")
        if any(ids[x] != "draft" for x in el["editableIn"]):
            out.append(_p("editLock.editableIn", "只有草稿（draft 語意）狀態可編輯：簽核後改內容會讓簽核失去意義（H3）"))
    if body.get("returnLog") not in LOG:
        out.append(_p("returnLog", "returnLog 必須是 %s" % "／".join(LOG)))
    if out:
        return out
    out = analyze(body)
    if not out and cls == "stock":
        out = _stock_rules(body)
    return out


def _unknown_keys(d, level, path):
    extra = sorted(set(map(str, d)) - _KEYS[level])
    return [_p(path, "不認得的欄位：%s（不接受未宣告的欄位）" % "、".join(extra))] if extra else []


def _stock_rules(body):
    """核准會動庫存的單據（stock 類）：庫存異動必須和『進入／離開 approved』一對一綁死。"""
    out = []
    sem = {s["id"]: s["semantic"] for s in body["states"]}
    for i, t in enumerate(body["transitions"]):
        path = "transitions[%d]" % i
        src_app = [f for f in t["from"] if sem[f] == "approved"]
        src_non = [f for f in t["from"] if sem[f] != "approved"]
        to_app = sem[t["to"]] == "approved"
        if src_app and src_non:
            out.append(_p(path + ".from", "此單據的轉換來源不可同時包含已核准與其他狀態"))
            continue
        if src_non and to_app:
            if "stock_deduct" not in t.get("callbacks", []):
                out.append(_p(path + ".callbacks", "進入已核准的轉換必須帶 stock_deduct"))
            if "serials_in_stock" not in t.get("guards", []):
                out.append(_p(path + ".guards", "進入已核准的轉換必須保留守門 serials_in_stock"))
        if src_app and not to_app and "stock_return" not in t.get("callbacks", []):
            out.append(_p(path + ".callbacks", "離開已核准的轉換必須帶 stock_return"))
    return out


def _check_callback_placement(t, ids, path):
    out = []
    to_sem = ids.get(t.get("to"))
    from_sems = {ids.get(f) for f in (t.get("from") or []) if isinstance(f, str)}
    for cb in (t.get("callbacks") or []):
        spec = ACTIONS.get(cb)
        if not spec:
            continue
        if spec.get("only_entering") and (to_sem != spec["only_entering"] or spec["only_entering"] in from_sems):
            out.append(_p(path + ".callbacks", "%s 只能掛在『從其他狀態進入 %s』的轉換" % (cb, spec["only_entering"])))
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
        if t["who"] == "tier":
            path = "transitions[%d]" % i
            if not all(sem[f] == "pending" for f in t["from"]):
                out.append(_p(path, "簽核層的轉換必須只從待簽狀態（pending 語意）出發（所有來源都要是）"))
            role, tsem = t.get("tierRole"), sem[t["to"]]
            if role == "final" and tsem != "approved":
                out.append(_p(path + ".tierRole", "final（最後一層）必須進入已核准"))
            if role == "step" and tsem != "pending":
                out.append(_p(path + ".tierRole", "step（中間層）必須留在待簽狀態"))
            if role == "return" and tsem != "draft":
                out.append(_p(path + ".tierRole", "return（退回）必須回到草稿語意的狀態"))
            if tsem == "approved" and role != "final":
                out.append(_p(path + ".tierRole", "只有 final 的簽核層轉換可以進入已核准（不可由第一層簽核就核准）"))
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
        for dep in DEPENDENCIES.get(new.get("docType"), []):
            loose("相依警示：%s" % dep["note"])
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
        elif news[sid].get("semantic") == "approved" and olds[sid].get("label") != news[sid].get("label"):
            loose("已核准狀態的顯示名稱改變（%s → %s）" % (olds[sid].get("label"), news[sid].get("label")))
    for lvl, a, b in (("body", old, new), *(("state", olds.get(k), news.get(k)) for k in set(olds) & set(news))):
        extra = (set(map(str, a or {})) | set(map(str, b or {}))) - _KEYS[lvl]
        if extra:
            loose("含不認得的欄位：%s" % "、".join(sorted(extra)))
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
    extra = (set(map(str, o)) | set(map(str, n))) - _KEYS["transition"]
    if extra:
        loose("轉換 %s 含不認得的欄位：%s" % (tid, "、".join(sorted(extra))))
    if o.get("tierRole") != n.get("tierRole"):
        loose("轉換 %s 的簽核層角色改變" % tid)
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
