# -*- coding: utf-8 -*-
"""表單「自動帶入」來源的唯一登記處（L1；表單設計器的下拉、定義驗證、伺服器端取值都讀這一份）。

欄位的預設值可以寫成 `{"$": "<token>"}`：建立單據時由**伺服器**換成當下的值，前端送什麼都不採用；**只在建立當下解析一次**，
寫進單據之後檢視、列印、再存都不重算（定義版本釘定不被破壞）。這裡的 token 清單與說明文字是唯一來源——
表單設計器不寫死 token 清單（`GET /api/platform/prefill-sources`），文字（label／why／example）也只在這裡改。

`PREFILL_SOURCES[token] = {label, why, example, applies_to, lockable, needs_context, requires_time, resolve}`
- `applies_to`：`[(欄位型別, 參照對象或 None)]`；`("ref","users")` 只給參照人員的欄位，`("date", None)` 任何日期欄。
- `lockable`：能不能搭配 `locked:true`（鎖定＝一律以伺服器值為準）。結果不固定（lastUsed）或依案件而定（caseCustomer／caseProject）的不能鎖。
- `needs_context`：需要案件脈絡（`ctx["case"]`）；掛在沒有案件的表單上沒有意義，驗證擋掉。
- `requires_time`：欄位必須是含時間的日期（`withTime`）。
- `resolve(ctx) -> 值 | None`：**永不丟例外**；`None`＝留白（沒有主管、沒有部門、沒有案件…）。
  `ctx = {user, requester, now, field, body, case, conn, module_key, last_value}`：
  `user`＝登入者（dict）；`requester`＝申請人（dict，目前沒有代填流程 ⇒ 與 user 相同）；`case`＝`{"customer","project"}` 或 None；
  `last_value`＝`fn(conn, user, 欄位key) -> 值`，讓不是自訂單據的呼叫端（例：費用單據）提供「這個人上一次填的」；沒給且有 `module_key`
  ⇒ 讀自訂單據的欄位索引表。
介面：`list_sources()`／`get(token)`／`default_token(field)`／`check_field(...)`／`make_ctx(...)`／`resolve_field(field, ctx)`／`fill_defaults(...)`。
"""
import re
from datetime import datetime

#: lastUsed 絕不帶入的欄位：個資（F2）與帶有銀行／身分證意味的 key
_SENSITIVE_KEY = re.compile(r"bank|account|passbook|id_?no|id_?card|idcard|passport|tax_?id|salary|password", re.I)
_TIME_FMT = "%Y-%m-%dT%H:%M"

PREFILL_SOURCES = {}


def _register(token, label, why, example, applies_to, resolve, *, lockable=True, needs_context=False, requires_time=False):
    PREFILL_SOURCES[token] = {
        "label": label, "why": why, "example": example,
        "applies_to": [tuple(a) for a in applies_to],
        "lockable": lockable, "needs_context": needs_context, "requires_time": requires_time,
        "resolve": resolve,
    }


def _safe(fn):
    """resolve 永不丟例外：任何錯誤 ⇒ None（留白）。"""
    def run(ctx):
        try:
            return fn(ctx)
        except Exception:                                    # noqa: BLE001 — 自動帶入失敗不可以讓建立單據失敗
            return None
    return run


def _username(person):
    return (person or {}).get("username") or None


def _now(ctx):
    return ctx.get("now") or datetime.now()


def _r_today(ctx):
    now = _now(ctx)
    return now.strftime(_TIME_FMT) if (ctx.get("field") or {}).get("withTime") else now.date().isoformat()


def _r_now(ctx):
    return _now(ctx).strftime(_TIME_FMT)


def _r_requester(ctx):
    return _username(ctx.get("requester") or ctx.get("user"))


def _r_current_user(ctx):
    return _username(ctx.get("user"))


def _requester_row(ctx):
    conn = ctx.get("conn")
    name = _username(ctx.get("requester") or ctx.get("user"))
    if conn is None or not name:
        return None
    return conn.execute("SELECT id, username, department_id FROM users WHERE username=? AND active=1", (name,)).fetchone()


def _r_dept(ctx):
    row = _requester_row(ctx)
    if not row or not row["department_id"]:
        return None
    ok = ctx["conn"].execute("SELECT id FROM departments WHERE id=?", (row["department_id"],)).fetchone()
    return ok["id"] if ok else None


def _r_manager(ctx):
    """申請人的直屬主管＝組織簽核鏈（部門主管 → 處主管）裡第一個不是本人的人；沒有 ⇒ None。"""
    from helpers import tiered_approval as _ta
    name = _username(ctx.get("requester") or ctx.get("user"))
    if ctx.get("conn") is None or not name:
        return None
    try:
        chain = _ta.resolve_submitter_org_chain(ctx["conn"], name)
    except _ta.UnresolvedManagerError:
        return None
    return next((m["username"] for m in chain if m.get("username") and m["username"] != name), None)


def _r_company(ctx):
    from helpers import company_identity as _ci
    return (_ci.location_identity().get("company_name") or "").strip() or None


def _r_case_customer(ctx):
    return ((ctx.get("case") or {}).get("customer") or "").strip() or None


def _r_case_project(ctx):
    return ((ctx.get("case") or {}).get("project") or "").strip() or None


def _custom_last_value(conn, user, module_key, key, ftype, target):
    """自訂單據：這個人在同一個表單、同一個欄位最近一次填的值（走欄位索引表，不用 json_extract）。"""
    row = conn.execute(
        "SELECT v.value_text FROM custom_record_values v JOIN custom_records r ON r.id = v.record_id "
        "WHERE r.module_key=? AND r.created_by=? AND v.field=? AND v.value_text<>'' ORDER BY r.id DESC LIMIT 1",
        (module_key, user.get("username") or "", key)).fetchone()
    if not row:
        return None
    v = row["value_text"]
    if ftype == "ref" and target == "departments":
        try:
            return int(v)
        except (TypeError, ValueError):
            return None
    return v


def _r_last_used(ctx):
    f = ctx.get("field") or {}
    key = f.get("key") or ""
    if not key or f.get("dataClass") == "F2" or _SENSITIVE_KEY.search(key):
        return None
    conn, user = ctx.get("conn"), ctx.get("user") or {}
    if conn is None or not user.get("username"):
        return None
    fn = ctx.get("last_value")
    if fn is not None:
        v = fn(conn, user, key)
    elif ctx.get("module_key"):
        v = _custom_last_value(conn, user, ctx["module_key"], key, f.get("type"), f.get("target"))
    else:
        return None
    if v in (None, ""):
        return None
    if f.get("type") in ("select", "radio") and v not in (f.get("options") or []):
        return None                                           # 選項後來被改掉了 ⇒ 不帶舊值
    return v


# ── 登記（順序＝設計器下拉順序；文字給非工程人員看，用詞與 form-designer-prototype 的 FILLS 一致）──────────
_register("requester", "申請人本人", "填表的人是誰就帶誰。", "王小明",
          [("ref", "users")], _safe(_r_requester))
_register("currentUser", "目前登入的人", "現在正在操作的人（目前與申請人相同；日後有代填流程時才會不同）。", "李助理",
          [("ref", "users")], _safe(_r_current_user))
_register("requesterDept", "申請人所屬部門", "申請人在人事資料裡的部門。", "業務部",
          [("ref", "departments")], _safe(_r_dept))
_register("requesterManager", "申請人的主管", "申請人在人事資料裡的直屬主管。", "陳經理",
          [("ref", "users")], _safe(_r_manager))
_register("today", "今天日期", "打開表單的那一天。", "2026/10/01",
          [("date", None)], _safe(_r_today))
_register("now", "現在的日期與時間", "打開表單的那一刻（欄位要設成含時間）。", "2026/10/01 14:30",
          [("date", None)], _safe(_r_now), requires_time=True)
_register("company", "公司名稱", "系統設定裡的公司名稱。", "○○機械股份有限公司",
          [("text", None)], _safe(_r_company))
_register("caseCustomer", "這個案件的客戶", "從案件帶入客戶名稱（只有掛在案件底下的表單才有）。", "台灣精密",
          [("text", None)], _safe(_r_case_customer), lockable=False, needs_context=True)
_register("caseProject", "這個案件的專案", "從案件帶入專案名稱（只有掛在案件底下的表單才有）。", "新廠自動化",
          [("text", None)], _safe(_r_case_project), lockable=False, needs_context=True)
_register("lastUsed", "我上一次填過的內容", "這個人上次填同一格的內容，省得重打。", "台北出差",
          [("ref", "users"), ("ref", "departments"), ("date", None), ("text", None), ("select", None), ("radio", None)],
          _safe(_r_last_used), lockable=False)


# ── 對外介面 ──────────────────────────────────────────────────────────────

def get(token):
    """登記的來源（含 resolve）；沒有 ⇒ None。"""
    return PREFILL_SOURCES.get(token) if isinstance(token, str) else None


def list_sources() -> list:
    """給前端／文件的公開清單（依登記順序；沒有 resolve）：`[{token,label,why,example,applies_to,lockable,needs_context,requires_time}]`。"""
    return [{"token": t, "label": s["label"], "why": s["why"], "example": s["example"],
             "applies_to": [list(a) for a in s["applies_to"]], "lockable": s["lockable"],
             "needs_context": s["needs_context"], "requires_time": s["requires_time"]}
            for t, s in PREFILL_SOURCES.items()]


def default_token(field):
    """欄位的 `default` 是 `{"$": token}` ⇒ token（可能不合法；不是字串 ⇒ ""）；不是這個形狀 ⇒ None。"""
    d = field.get("default") if isinstance(field, dict) else None
    if not isinstance(d, dict):
        return None
    t = d.get("$", "")
    return t if isinstance(t, str) else ""


def _applies(src, field) -> bool:
    ftype = field.get("type")
    target = field.get("target") if ftype == "ref" else None
    return any(t == ftype and (tg is None or tg == target) for t, tg in src["applies_to"])


def check_field(field, *, mount_has_case=True, locked=None, path="") -> list:
    """欄位自動帶入的定義檢查 ⇒ `[{"path","message"}]`（空＝通過；路徑 `<path>.default`）。
    擋：不認得的 token、欄位型別不在 `applies_to`、`now` 欄位沒設含時間、`lockable=False` 卻 `locked:true`、
    需要案件脈絡的 token 掛在沒有案件的表單（`mount_has_case=False`）、lastUsed 用在個資（F2）欄位。
    `locked=None` ⇒ 讀 `field["locked"]`。欄位沒有 token 預設值 ⇒ 空。"""
    tok = default_token(field)
    if tok is None:
        return []
    where = path + ".default"
    src = get(tok)
    if src is None:
        return [{"path": where, "message": "預設值只認得 %s：%r" % ("、".join(PREFILL_SOURCES), tok)}]
    name = "「%s」" % src["label"]
    if not _applies(src, field):
        return [{"path": where, "message": "預設值%s不能用在這個型別的欄位" % name}]
    if src["requires_time"] and not field.get("withTime"):
        return [{"path": where, "message": "預設值%s只能用在含時間的日期欄" % name}]
    if (field.get("locked") if locked is None else locked) and not src["lockable"]:
        return [{"path": where, "message": "預設值%s每次結果不固定或依案件而定，不能搭配「鎖定」" % name}]
    if src["needs_context"] and not mount_has_case:
        return [{"path": where, "message": "這個表單沒有掛在案件底下，不能用預設值%s" % name}]
    if tok == "lastUsed" and field.get("dataClass") == "F2":
        return [{"path": where, "message": "個資（F2）欄位不能帶入上一次填的內容"}]
    return []


def make_ctx(conn, viewer, *, requester=None, case=None, module_key="", last_value=None, now=None) -> dict:
    """取值用的脈絡（呼叫端建一次、整張單據共用）；`field`／`body` 由 `fill_defaults` 逐欄補上。"""
    viewer = viewer or {}
    return {"conn": conn, "user": viewer, "requester": requester or viewer, "now": now or datetime.now(),
            "case": case, "module_key": module_key, "last_value": last_value, "field": None, "body": None}


def resolve_field(field, ctx):
    """單一欄位的 token 預設值 ⇒ 值；沒有 token／不認得／解析不到 ⇒ None。永不丟例外。"""
    src = get(default_token(field))
    if src is None:
        return None
    return src["resolve"](dict(ctx or {}, field=field))


def fill_defaults(body, values, ctx, *, prior=None) -> dict:
    """依定義把 token 預設值換成伺服器值 ⇒ 新的 values（不改傳入的）。
    - 建立（`prior is None`）：沒填的欄位換成當下的值；`locked` 的欄位一律以伺服器值為準（前端送什麼都不採用）。
    - 更新（`prior` 是既有單據的資料）：**不重算任何 token**；`locked` 的欄位保留 `prior` 的值，其餘照送來的。
    不認得的 token 靜默略過（驗證在定義存檔時就擋了）。"""
    values = dict(values) if isinstance(values, dict) else {}
    ctx = dict(ctx or {}, body=body)
    for f in (body or {}).get("fields", []):
        if not isinstance(f, dict) or not f.get("key"):
            continue
        tok = default_token(f)
        if tok is None or get(tok) is None:
            continue
        key, locked = f["key"], bool(f.get("locked"))
        if prior is not None:
            if locked:
                values[key] = prior.get(key)
            continue
        if not locked and values.get(key) not in (None, ""):
            continue
        v = resolve_field(f, ctx)
        if locked:
            values[key] = v
        elif v is not None:
            values[key] = v
    return values
