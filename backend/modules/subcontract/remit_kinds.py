# -*- coding: utf-8 -*-
"""匯款款別設定（31-B S0；設計 docs/platform/plans/REMIT-KINDS-31B-DESIGN.md §3b）。

[單位] m04:remit_kinds    [層] L2（M04 subcontract）    [穩定度] 實驗（31-B 逐切片補齊）
[公開介面] KIND, KEY, STAGES, current, active_kinds, default_body, kind_allowed_at, validate_body
[不變式] 款別放在定義文件庫（kind＝remit_kinds、key＝default、company scope）：有草稿、發布、版本、差異、還原（沿用 core.definitions）；
  沒有發布版＝程式出貨預設（版本 0：訂金款／進度款／完工款／驗收款）。**代碼發布後不可改、不可移除**（只能 active=false 停用；改名只改 name）；
  階段規則（stages）是「派發狀態」的子集——使用者裁示 2026-10-02：「案件狀態」＝派發的狀態；預設對應公司可在設定頁改。
  改款別只影響**之後**新開的匯款申請（申請記下 kind／kind_name／kinds_version 快照，S2 起）。

款別與派發狀態（`dispatch_flow.STATUSES`）的預設對應：訂金款＝已確認～完工；進度款＝已確認～已驗收；完工款、驗收款＝已驗收／完工。
"""
import copy
import json
import re

from core import definitions as D

KIND = "remit_kinds"
KEY = "default"
CODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
#: 規則鍵＝派發作業狀態（不含 cancelled：已取消的派發不可請款）；順序即流程順序
STAGES = ("draft", "sent", "confirmed", "pending_acceptance", "accepted", "completed")
STAGE_LABELS = {"draft": "草稿", "sent": "已送出", "confirmed": "已確認", "pending_acceptance": "待驗收", "accepted": "已驗收", "completed": "完工"}
MAX_KINDS = 30
MAX_NAME = 20
MAX_NOTE = 200

_DEFAULT = {
    "name": "匯款款別",
    "kinds": [
        {"code": "deposit", "name": "訂金款", "active": True, "sort": 10, "stages": ["confirmed", "pending_acceptance", "accepted", "completed"],
         "note": "合約簽訂後的預付款"},
        {"code": "progress", "name": "進度款", "active": True, "sort": 20, "stages": ["confirmed", "pending_acceptance", "accepted"],
         "note": "施工中依進度請款，可分多期"},
        {"code": "completion", "name": "完工款", "active": True, "sort": 30, "stages": ["accepted", "completed"], "note": "完工後的款項"},
        {"code": "acceptance", "name": "驗收款", "active": True, "sort": 40, "stages": ["accepted", "completed"], "note": "驗收通過後的尾款"},
    ],
}


def default_body(key=KEY):
    """程式出貨預設（版本 0）；只有 key＝default 有。回新物件（呼叫端可改）。"""
    return copy.deepcopy(_DEFAULT) if key == KEY else None


def _p(path, message):
    return {"path": path, "message": message}


def _known_codes(conn):
    """已經「不可移除」的代碼：任何已發布版本裡出現過的，加上（S1 之後）已被匯款申請使用的。查不到表／欄 ⇒ 略過那一項。"""
    codes = set()
    try:
        for r in conn.execute("SELECT body_json FROM ui_definitions WHERE kind=? AND key=? AND status='published'", (KIND, KEY)).fetchall():
            try:
                codes |= {k.get("code") for k in (json.loads(r[0] or "{}").get("kinds") or []) if isinstance(k, dict)}
            except (TypeError, ValueError):
                continue
    except Exception:                                              # noqa: BLE001 — 表不在（舊庫）
        pass
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(contractor_payment_vouchers)").fetchall()}
        if "kind" in cols:
            codes |= {r[0] for r in conn.execute("SELECT DISTINCT kind FROM contractor_payment_vouchers WHERE kind<>''").fetchall()}
    except Exception:                                              # noqa: BLE001
        pass
    return {c for c in codes if c}


def validate_body(body, key="", *, conn=None):
    """⇒ `[{"path","message"}]`（空＝可以發布）。conn 沒給 ⇒ 自己開唯讀連線查『不可移除的代碼』。"""
    if key and key != KEY:
        return [_p("", "匯款款別只有一份設定（key＝%s）" % KEY)]
    if not isinstance(body, dict):
        return [_p("", "定義必須是 JSON 物件")]
    out = []
    kinds = body.get("kinds")
    if not isinstance(kinds, list) or not kinds:
        return out + [_p("kinds", "至少要有一個款別")]
    if len(kinds) > MAX_KINDS:
        out.append(_p("kinds", "款別最多 %d 個" % MAX_KINDS))
    seen = set()
    for i, k in enumerate(kinds):
        p = "kinds[%d]" % i
        if not isinstance(k, dict):
            out.append(_p(p, "款別必須是物件"))
            continue
        code = k.get("code")
        if not isinstance(code, str) or not CODE_RE.match(code):
            out.append(_p(p + ".code", "代碼只能用小寫英文、數字與底線（2～40 字，英文開頭）：%r" % (code,)))
        elif code in seen:
            out.append(_p(p + ".code", "代碼重複：%s" % code))
        else:
            seen.add(code)
        name = k.get("name")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > MAX_NAME:
            out.append(_p(p + ".name", "款別名稱必填，最長 %d 字" % MAX_NAME))
        if not isinstance(k.get("active"), bool):
            out.append(_p(p + ".active", "active 要是 true／false（停用＝false，不能刪除款別）"))
        if "sort" in k and (isinstance(k["sort"], bool) or not isinstance(k["sort"], int)):
            out.append(_p(p + ".sort", "排序要是整數"))
        st = k.get("stages")
        if not isinstance(st, list) or any(s not in STAGES for s in st):
            out.append(_p(p + ".stages", "可開立的派發狀態必須是：%s" % "、".join("%s(%s)" % (STAGE_LABELS[s], s) for s in STAGES)))
        elif k.get("active") is True and not st:
            out.append(_p(p + ".stages", "啟用中的款別至少要有一個可開立的派發狀態（不想讓人用就改成停用）"))
        elif len(set(st)) != len(st):
            out.append(_p(p + ".stages", "派發狀態重複"))
        note = k.get("note", "")
        if not isinstance(note, str) or len(note) > MAX_NOTE:
            out.append(_p(p + ".note", "備註最長 %d 字" % MAX_NOTE))
    if not any(isinstance(k, dict) and k.get("active") is True for k in kinds):
        out.append(_p("kinds", "至少要有一個啟用中的款別"))
    if not out:                                                    # 結構都合法才查『不可移除』（需要資料庫）
        removed = _removed_codes(seen, conn)
        if removed:
            out.append(_p("kinds", "已發布過或已被使用的款別不能移除，只能停用（active＝false）：%s" % "、".join(sorted(removed))))
    return out


def _removed_codes(new_codes, conn):
    own = conn is None
    try:
        if own:
            import db
            conn = db.get_db()
        return _known_codes(conn) - set(new_codes)
    except Exception:                                              # noqa: BLE001 — 查不到就不擋（驗證器不可因環境問題變成新的失敗來源）
        return set()
    finally:
        if own and conn is not None:
            conn.close()


def current(conn):
    """目前生效的款別設定 ⇒ `{"version": int, "kinds": [...]}`（公司發布版；沒有發布過＝出貨預設、版本 0）。"""
    body, _src = D.resolve(conn, KIND, KEY)
    body = body if isinstance(body, dict) else default_body()
    row = D.get(conn, KIND, KEY, "company")
    return {"version": int(row["version"]) if row else 0, "kinds": list(body.get("kinds") or [])}


def active_kinds(conn):
    """啟用中的款別（依 sort、再依代碼）⇒ `[{code,name,stages,sort,note}]` 與生效版本。"""
    cur = current(conn)
    ks = [k for k in cur["kinds"] if isinstance(k, dict) and k.get("active")]
    ks.sort(key=lambda k: (k.get("sort") or 0, k.get("code") or ""))
    return {"version": cur["version"], "kinds": [{"code": k["code"], "name": k["name"], "stages": list(k.get("stages") or []),
                                                  "sort": k.get("sort") or 0, "note": k.get("note") or ""} for k in ks]}


def kind_allowed_at(kinds, code, dispatch_status):
    """⇒ (ok, 原因)。`kinds`＝`current()["kinds"]` 或 `active_kinds()["kinds"]`；找不到代碼／已停用／派發狀態不在規則內 ⇒ (False, 說明)。"""
    k = next((x for x in kinds if isinstance(x, dict) and x.get("code") == code), None)
    if k is None:
        return False, "沒有這個款別（%s）" % code
    if k.get("active") is False:
        return False, "款別「%s」已停用，不能開新的匯款申請" % k.get("name", code)
    if dispatch_status not in (k.get("stages") or []):
        ok_labels = "、".join(STAGE_LABELS.get(s, s) for s in (k.get("stages") or [])) or "（沒有）"
        return False, "派發目前是「%s」，款別「%s」只能在這些狀態開立：%s" % (STAGE_LABELS.get(dispatch_status, dispatch_status), k.get("name", code), ok_labels)
    return True, ""


if KIND not in D.kinds():
    D.register_kind(KIND, label="匯款款別", validator=validate_body, default=default_body)
