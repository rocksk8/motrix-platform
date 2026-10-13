# -*- coding: utf-8 -*-
"""材料卡片『認列已核准採購單』（T57；MATERIAL-LINK-BUG-T57）。

使用者情境：採購單已經核准（有的供應商不在供應商主檔，沒辦法填供應商），要直接把它**認列**到材料卡片，卡片就能勾『已申購／已到料』。
做法：材料卡片（`caseRecord.materials[]`）持有一個經伺服器驗證的 `poLink`，**不**建立材料申請、**不**進審核流程、**不**產生金額、**不**產生付款路徑——
採購單本身已核准，這裡只『連結＋讓旗標可勾』。

`poLink`（伺服器存的形狀；**全部非金額欄位**）：`{key, poDocCode, docCodes, name, vendor, quoteItemId, claimedBy, claimedAt, arrivedOn, arrivedBy, arrivedAt, stale}`。
用戶端只有兩個主張會被採用：`key`（要認列哪一組）與『到貨日』`arrivedOn`（勾已到料時）；其餘一律由伺服器填，用戶端帶的一律忽略。

規則（`process()`，由 `material_guard._gate_materials` 呼叫＝所有寫入路徑的共同閘）：
- 認列／取消認列／換組：只有**最高管理者**可以（設定 `material_recognition.who_may`，預設只有最高管理者）。其他人嘗試 ⇒ **整件取消**（卡片的 poLink 與旗標維持原值，
  同一份資料裡其他卡片欄位照存），回 `rejected` code `recognize_denied`，並在同一交易寫稽核 `material.recognize_denied`；依 `on_denied` 寄信通知管理員（有去重與上限）。
- `actor=None`（系統／已結案變更核准）：**不接受**新的或變更的 poLink，只保留原本有效的；旗標不可由系統翻成真（沒有人可記錄為到貨確認人）。
- 認列成立：該分組目前存在（＝已核准採購單涵蓋）、沒有活的材料申請（含草稿）、沒有被別張卡片認列（含同一份資料內兩張卡片搶同一組）。
- 勾『已申購』：認列有效即可；勾『已到料』：另需到貨日（有效日期，必填），伺服器記下確認人與時間；被拒時連同序號（devices）一起維持原值。
- 過期（`stale`）：採購單之後被撤銷／取消／改回草稿／行被移除 ⇒ 每次存檔重新驗證；過期的認列旗標維持歷史，但不能再勾、涵蓋檢視不再把它算作占用。
- 取消認列 ⇒ 已申購／已到料旗標一併取消（除非卡片另有已核准材料申請可支撐）；序號不自動移除（與其他取消旗標的路徑一致），稽核記錄當時序號數與到貨日。
- 反向：認列中的分組不能再建立／連結材料申請（`claimed_conflict`，由 `material_guard._link_problem` 呼叫）。
稽核：`material.recognize`／`material.recognize_undo`／`material.recognize_arrived`／`material.recognize_unarrived`／`material.recognize_denied`，與狀態變更同一交易。
"""
import json
import logging
from datetime import datetime, timedelta

from helpers import settings_registry as sr
from helpers.dates import normalize_date
from modules.case import material_coverage_view as MCV

logger = logging.getLogger(__name__)

GROUP = "material_recognition"
FLAGS = ("ordered", "arrived")
_SYSTEM = {"username": "system", "role": "system", "display_name": "系統"}
_MSG_DENIED = "這個帳號不能認列採購單，已取消這次認列%s。"


def _setting(key, default, conn=None):
    try:
        v = sr.get(GROUP, key, conn=conn)
        return default if v is None else v
    except Exception:                                                                 # noqa: BLE001 — 設定讀不到 ⇒ 最嚴的預設
        return default


def _key_of(link) -> str:
    return str(link.get("key") or "").strip() if isinstance(link, dict) else ""


def link_key(card) -> str:
    return _key_of((card or {}).get("poLink")) if isinstance(card, dict) else ""


def claimed_keys(cards) -> dict:
    """{分組鍵: 卡片 id}（已認列的卡片，**過期的也算**：唯一性要撐到有人取消認列；採購單重新核准後不會出現兩張卡片同時持有）。"""
    out = {}
    for c in cards or []:
        k = link_key(c)
        if k and isinstance(c, dict):
            out.setdefault(k, str(c.get("id") or ""))
    return out


def claimed_conflict(conn, quote_no, order, cards) -> str:
    """反向占用：這筆材料申請要連到的分組若已被卡片認列 ⇒ 訊息；否則 ""。`cards`＝已存的 `caseRecord.materials`。"""
    qid, po = str((order or {}).get("quoteItemId") or "").strip(), str((order or {}).get("poDocCode") or "").strip()
    for c in cards or []:
        pl = c.get("poLink") if isinstance(c, dict) else None
        if not isinstance(pl, dict) or not _key_of(pl):                              # 過期的認列也算占用：直到最高管理者取消認列為止
            continue
        if (qid and _key_of(pl) == "item:" + qid) or (not qid and po and (_key_of(pl) == "po:" + po)):
            return "這個品項已認列到材料卡片「%s」，不能再建立材料申請（請先由最高管理者取消認列）" % (c.get("name") or "")
    return ""


class Ctx:
    def __init__(self, conn, quote_no, old_list, orders, actor, rows):
        self.conn, self.quote_no, self.actor, self.orders, self.rows = conn, quote_no, actor, orders or [], rows
        self.user = actor or _SYSTEM
        self.taken = claimed_keys(old_list)
        self.groups = None
        self.events = []                                                              # [(action, mid, detail)]
        self.now = datetime.now().isoformat(timespec="seconds")
        self.who_may = int(_setting("who_may", 1, conn))
        self.on_denied = int(_setting("on_denied", 1, conn))

    def group_map(self):
        if self.groups is None:
            self.groups = {g.get("key"): g for g in MCV.groups(self.conn, self.quote_no, show_cost=False)}
        return self.groups

    @property
    def may_change(self) -> bool:
        a = self.actor
        if a is None:
            return False
        if a.get("role") == "superadmin":
            return True
        if self.who_may == 2:                                                         # 『有權限編輯材料的人』＝與材料申請列相同的條件（管理員以上或專案經理且有財務檢視權），不是任何能存案件的帳號
            from modules.case import material_guard as MG
            return MG.can_edit_orders(a)
        return False


def _order_conflict(ctx, g) -> bool:
    """同一份資料裡剛建立的材料申請已占用這一組（資料庫尚看不到）。"""
    docs = set(g.get("docCodes") or [])
    for o in ctx.orders:
        if not isinstance(o, dict):
            continue
        if (g.get("quoteItemId") and str(o.get("quoteItemId") or "") == g["quoteItemId"]) or \
           (not g.get("quoteItemId") and str(o.get("poDocCode") or "") in docs):
            return True
    return False


def _build(ctx, key, mid):
    g = ctx.group_map().get(key)
    if g is None:
        return None, "找不到這張已核准的採購單（可能還沒核准、已被取消，或不屬於這個案件）"
    owner = ctx.taken.get(key)
    if owner and owner != mid:
        return None, "這張採購單已經認列到另一張材料卡片"
    if (g.get("existing") and not g.get("recognized")) or _order_conflict(ctx, g):
        return None, "這個品項已有材料申請，請改用該材料申請"
    return {"key": g["key"], "poDocCode": g.get("poDocCode") or "", "docCodes": list(g.get("docCodes") or []), "name": g.get("name") or "",
            "vendor": g.get("vendor") or "", "quoteItemId": g.get("quoteItemId") or "",
            "claimedBy": ctx.user.get("username", ""), "claimedAt": ctx.now}, None


def _rej(rejected, mid, field, code, message):
    rejected.append({"itemId": mid, "field": field, "code": code, "message": message})


def _approved_support(ctx, m, om) -> bool:
    link = str(m.get("orderItemId") or (om or {}).get("orderItemId") or "")
    row = ctx.rows.get(link) if link else None
    return bool(row is not None and row["status"] == "已核准")


def process(ctx, m, om, mid, rejected) -> dict:
    """處理一張卡片的 poLink 與（有認列時的）旗標。就地修改 `m`。回 `{"has": 是否持有有效認列, "reverted_arrival": 到料被拒}`；`has` 為真時呼叫端略過一般旗標檢查。"""
    out = {"has": False, "reverted_arrival": False}
    om = om or {}
    old = om.get("poLink") if isinstance(om.get("poLink"), dict) and _key_of(om.get("poLink")) else None
    inc_present = "poLink" in m
    inc = m.get("poLink") if isinstance(m.get("poLink"), dict) else {}
    inc_key = _key_of(inc)
    link, denied_key = None, None
    if old is None and not inc_key:
        m.pop("poLink", None)
        return out
    if old is not None and (not inc_present or inc_key == _key_of(old)):
        link = dict(old)                                                              # 保留伺服器現值（不信用戶端重送的其他欄位）
    elif old is not None and not inc_key:                                             # 明確取消認列
        if not ctx.may_change:
            denied_key, link = _key_of(old), dict(old)
        else:
            _unlink(ctx, m, om, old, mid)
            m["poLink"] = None                                                        # 明確標記『已取消』：寫入漏斗會再過一次閘（資料庫此時仍是舊值），沒有這個標記會被當成『舊頁面沒帶』而還原
            return out
    elif old is not None:                                                              # 換組：先取消目前的再認列另一張
        if ctx.may_change:
            _rej(rejected, mid, "poLink", "bad_recognize", "要換成另一張採購單，請先取消目前的認列")
        else:
            denied_key = inc_key
        link = dict(old)
    else:                                                                              # 新認列
        if not ctx.may_change:
            denied_key = inc_key
            m.pop("poLink", None)
        else:
            built, msg = _build(ctx, inc_key, mid)
            if built is None:
                _rej(rejected, mid, "poLink", "bad_recognize", msg)
                m.pop("poLink", None)
            else:
                link = built
                ctx.taken[inc_key] = mid
                ctx.events.append(("material.recognize", mid, {"key": inc_key, "poDocCode": built["poDocCode"], "docCodes": built["docCodes"]}))
    if denied_key is not None:
        ctx.events.append(("material.recognize_denied", mid, {"key": denied_key, "attempt": "remove" if not inc_key else "claim", "mailed": False}))
        _rej(rejected, mid, "poLink", "recognize_denied", _MSG_DENIED % ("，並已通知管理員" if ctx.on_denied == 1 else ""))
    if link is None:
        return out
    link["stale"] = link["key"] not in ctx.group_map() if old is not None else False
    if not link["stale"]:
        link.pop("stale", None)
    out["has"] = True
    _flags(ctx, m, om, link, inc, mid, rejected, out)
    m["poLink"] = link
    return out


def _flags(ctx, m, om, link, inc, mid, rejected, out):
    for flag in FLAGS:
        want, had = bool(m.get(flag)), bool(om.get(flag))
        if want == had:
            continue
        if want:
            if link.get("stale") or ctx.actor is None:
                _rej(rejected, mid, flag, "recognize_stale" if link.get("stale") else "no_permission",
                     "採購單已變更，不能再勾選；請管理員確認這張採購單目前的狀態" if link.get("stale") else "系統路徑不能代為勾選")
                m[flag] = had
                out["reverted_arrival"] |= flag == "arrived"
                continue
            if flag == "arrived":
                try:
                    day = normalize_date((inc or {}).get("arrivedOn") or "", "到貨日期")
                except Exception as e:                                               # noqa: BLE001 — HTTPException
                    day, why = "", getattr(e, "detail", None) or str(e)
                else:
                    why = "請先填到貨日期（才能標記已到料）"
                if not day:
                    _rej(rejected, mid, flag, "receipt_missing", why)
                    m[flag] = had
                    out["reverted_arrival"] = True
                    continue
                link.update(arrivedOn=day, arrivedBy=ctx.user.get("username", ""), arrivedAt=ctx.now)
                ctx.events.append(("material.recognize_arrived", mid, {"key": link["key"], "arrivedOn": day, "devices": len(m.get("devices") or [])}))
        elif flag == "arrived":                                                       # 取消已到料：清掉到貨記錄；序號不自動移除（與其他取消旗標一致），稽核留痕
            ctx.events.append(("material.recognize_unarrived", mid, {"key": link["key"], "was": link.get("arrivedOn", ""), "devices": len(m.get("devices") or [])}))
            for k in ("arrivedOn", "arrivedBy", "arrivedAt"):
                link.pop(k, None)


def handle_removed(ctx, om, mid, rejected) -> bool:
    """舊卡片持有認列、但新資料裡沒有它（＝刪除卡片）。回 True＝保留舊卡片（不准刪）。
    刪卡片等於取消認列：只有可變更認列者可以（記 `recognize_undo`）；其他人或系統路徑 ⇒ 保留並記 `recognize_denied`。"""
    old = om.get("poLink") if isinstance(om.get("poLink"), dict) else None
    key = _key_of(old)
    if not key:
        return False
    if ctx.may_change:
        ctx.taken.pop(key, None)
        ctx.events.append(("material.recognize_undo", mid, {"key": key, "flagsBefore": {f: bool(om.get(f)) for f in FLAGS}, "arrivedOn": old.get("arrivedOn", ""),
                                                               "devices": len(om.get("devices") or []), "removedWithCard": True}))
        return False
    ctx.events.append(("material.recognize_denied", mid, {"key": key, "attempt": "remove_card", "mailed": False}))
    _rej(rejected, mid, "poLink", "recognize_denied", _MSG_DENIED % ("，並已通知管理員" if ctx.on_denied == 1 else "") + "（已認列的材料卡片不能刪除）")
    return True


def changes_recognition(old_cards, new_cards) -> bool:
    """這份新卡片清單是否新增／變更／移除了認列（舊頁面沒帶 poLink 欄位＝不變）。已結案變更申請在核准時以系統身分套用、不接受新認列，所以送出前就要擋。"""
    olds = {str(c.get("id")): c for c in (old_cards or []) if isinstance(c, dict)}
    news = {str(c.get("id")): c for c in (new_cards or []) if isinstance(c, dict)}
    for mid, c in news.items():
        if "poLink" in c and _key_of(c.get("poLink")) != link_key(olds.get(mid)):
            return True
    return any(link_key(c) and mid not in news for mid, c in olds.items())


def _unlink(ctx, m, om, old, mid):
    keep = _approved_support(ctx, m, om)
    before = {f: bool(om.get(f)) for f in FLAGS}
    if not keep:
        for f in FLAGS:
            m[f] = False
    ctx.taken.pop(_key_of(old), None)
    ctx.events.append(("material.recognize_undo", mid, {"key": _key_of(old), "flagsBefore": before, "arrivedOn": old.get("arrivedOn", ""),
                                                           "devices": len(om.get("devices") or [])}))


# ── 稽核＋通知 ──
def _audit(conn, user, action, quote_no, mid, detail, now):
    from helpers.audit import _derive_fields
    detail = dict(detail, card=mid)
    d = _derive_fields(action, "quotation", quote_no, "%s 材料卡片認列" % quote_no, detail)
    conn.execute(
        "INSERT INTO audit_log (at,user_id,username,display_name,action,target_type,target_id,target_label,detail,module,case_no,ref_no,result,reason_code,status_code) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'ok','',0)",
        (now, user.get("id"), user.get("username", ""), user.get("display_name") or user.get("username", ""), action, "quotation", quote_no,
         "%s 材料卡片認列" % quote_no, json.dumps(detail, ensure_ascii=False), d["module"], d["case_no"], d["ref_no"]))


def _may_mail(ctx, username, key) -> bool:
    """去重＋上限，查稽核表（資料庫狀態，在寫入交易內，不靠行程記憶體）：同 (帳號, 案件, 分組) 視窗內已寄過 ⇒ 不再寄；視窗內總寄信數達上限 ⇒ 不寄。"""
    win = int(_setting("mail_window_minutes", 60, ctx.conn))
    cap = int(_setting("mail_cap", 10, ctx.conn))
    since = (datetime.now() - timedelta(minutes=win)).isoformat(timespec="seconds")
    c = ctx.conn
    base = "FROM audit_log WHERE action='material.recognize_denied' AND at>=? AND instr(detail, '\"mailed\": true')>0"
    if c.execute("SELECT COUNT(*) " + base + " AND username=? AND target_id=? AND instr(detail, ?)>0",
                 (since, username, ctx.quote_no, json.dumps({"key": key}, ensure_ascii=False)[1:-1])).fetchone()[0]:
        return False
    return c.execute("SELECT COUNT(*) " + base, (since,)).fetchone()[0] < cap


def _first_time(ctx, action, mid, detail) -> bool:
    """同一條連線（＝同一個寫入交易）內，同一件事只記一次：端點先過閘、寫入漏斗 `save_quotation_json` 會對同一份資料再過一次（此時資料庫仍是舊值）。
    用連線專屬的 TEMP 表記，隨連線消失、隨交易回滾。"""
    sig = json.dumps([action, mid, {k: v for k, v in detail.items() if k != "mailed"}], sort_keys=True, ensure_ascii=False)
    ctx.conn.execute("CREATE TEMP TABLE IF NOT EXISTS _rg_seen (sig TEXT PRIMARY KEY)")
    return ctx.conn.execute("INSERT OR IGNORE INTO _rg_seen (sig) VALUES (?)", (sig,)).rowcount == 1


def finish(ctx):
    """寫稽核（同交易）；被拒的認列依設定寄信（附帶動作：失敗只記 log，不影響拒絕本身）。"""
    for action, mid, detail in ctx.events:
        if not _first_time(ctx, action, mid, detail):
            continue
        if action == "material.recognize_denied":
            mail = ctx.actor is not None and ctx.on_denied == 1 and _may_mail(ctx, ctx.user.get("username", ""), detail.get("key", ""))
            detail["mailed"] = bool(mail)
            _audit(ctx.conn, ctx.user, action, ctx.quote_no, mid, detail, ctx.now)
            if mail:
                sent = False
                try:
                    from modules.case import material_notify
                    sent = bool(material_notify.fire_recognize_denied({"quoteNo": ctx.quote_no, "cardId": mid, "who": ctx.user.get("username", ""), "at": ctx.now}))
                except Exception:                                                     # noqa: BLE001
                    logger.exception("認列被拒通知失敗")
                if not sent:                                                          # `mailed` 是寄之前寫的（用來去重）；寄失敗另記一筆，事後查得到
                    _audit(ctx.conn, ctx.user, "material.recognize_denied_mail_failed", ctx.quote_no, mid, {"key": detail.get("key", "")}, ctx.now)
        else:
            _audit(ctx.conn, ctx.user, action, ctx.quote_no, mid, detail, ctx.now)
