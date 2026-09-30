# -*- coding: utf-8 -*-
"""建構器底層支援（建構器第三輪 S2.5／S3／S5，CORE 1.72，只增）。

[單位] plat:custom-builder-support    [層] L1    [穩定度] 契約（只增）
[公開介面] ACCESS_KEYS, VISIBLE_ROLES, hidden_keys, keep_hidden_values, mask_compute, mask_record, mask_records, render_output_for, EVENT_FINANCE_POSTED, EVENT_FINANCE_REVERSED, access_problems, can_see_field, can_see_menu,
    create_revision, emit_finance_event, leaking_formulas, mark_finance_processed, mask_for, pending_finance_events
[不變式]
  - 欄位／選單可見設定存在定義 JSON（`fields[].access.visibleTo`、`menu.visibleTo`，形狀 `{roles:[…], users:[…]}`，
    兩者皆空＝不限）；最高管理者一律看得到；後端強制（mask_for 在回應前把看不到的欄位拿掉，不靠前端隱藏）
  - 公式欄若引用了「比自己更受限」的欄位＝洩漏（值算得出來就等於看得到）⇒ 發布前 leaking_formulas() 要空
  - 金流事件寫 `custom_record_finance_outbox`（與單據同一個交易內寫入，`dedupe_key` 唯一 ⇒ 重送冪等）；
    消費方（W4 總帳）自己讀 pending、處理完 mark processed；本模組不建分錄表
  - 修訂：`<原單號>-R<n>`；只能對「最新一版」修訂；新單回到起始狀態、內容複製、重新走簽核
[契約題] tests/test_builder_support_2026_09_30.py（待建）
"""
import json
from datetime import datetime

from . import formula

ACCESS_KEYS = {"visibleTo"}
#: 可見設定可選的角色（同 helpers.auth 的基本角色；建構器面板只列這些）
VISIBLE_ROLES = ("superadmin", "admin", "sales", "engineer", "viewer")
EVENT_FINANCE_POSTED = "custom_record.finance_posted"
EVENT_FINANCE_REVERSED = "custom_record.finance_reversed"


# ── 可見設定（欄位／選單） ────────────────────────────────────────────────

def _spec(v):
    """visibleTo 正規化 ⇒ (roles, users)；沒設或兩者皆空 ⇒ None（不限）。"""
    if not isinstance(v, dict):
        return None
    roles = {str(x) for x in v.get("roles") or [] if str(x).strip()}
    users = {str(x) for x in v.get("users") or [] if str(x).strip()}
    return (roles, users) if (roles or users) else None


def _allowed(spec, user) -> bool:
    if spec is None or (user or {}).get("role") == "superadmin":
        return True
    roles, users = spec
    return (user or {}).get("role") in roles or (user or {}).get("username") in users


def can_see_field(field, user) -> bool:
    access = field.get("access") if isinstance(field, dict) else None
    return _allowed(_spec((access or {}).get("visibleTo") if isinstance(access, dict) else None), user)


def can_see_menu(menu, user) -> bool:
    return _allowed(_spec((menu or {}).get("visibleTo") if isinstance(menu, dict) else None), user)


def mask_for(body, values, user) -> dict:
    """單據值 ⇒ 拿掉這位使用者看不到的欄位（新的 dict，不改傳入值）。明細表的欄位一併處理。"""
    hidden = {f["key"] for f in body.get("fields", []) if isinstance(f, dict) and not can_see_field(f, user)}
    return {k: v for k, v in (values or {}).items() if k not in hidden}


def hidden_keys(body, user) -> set:
    """這位使用者看不到的欄位 key。"""
    return {f["key"] for f in body.get("fields", []) if isinstance(f, dict) and f.get("key") and not can_see_field(f, user)}


def _mask_view(view, hidden):
    v = dict(view)
    v["fields"] = {k: x for k, x in (view.get("fields") or {}).items() if k not in hidden}
    for k in hidden:
        v.pop(k, None)
    return v


def mask_record(rec, user) -> dict:
    """單據（get_record 形狀）⇒ 拿掉使用者看不到的欄位（data、view、refLabels）。新的 dict；沒有受限欄位 ⇒ 原樣。
    定義（definition）本身不動——只有值被藏起來；後端強制，前端不需（也不能）自己再藏。"""
    body = rec.get("definition") or {}
    hidden = hidden_keys(body, user)
    if not hidden:
        return rec
    out = dict(rec)
    out["data"] = {k: v for k, v in (rec.get("data") or {}).items() if k not in hidden}
    if isinstance(rec.get("view"), dict):
        out["view"] = _mask_view(rec["view"], hidden)
    if isinstance(rec.get("refLabels"), dict):
        out["refLabels"] = {k: v for k, v in rec["refLabels"].items() if k not in hidden}
    if isinstance(rec.get("fileMeta"), dict):
        out["fileMeta"] = {k: v for k, v in rec["fileMeta"].items() if k not in hidden}
    out["hiddenFields"] = sorted(hidden)
    return out


def mask_records(rows, body, user) -> list:
    """列表列（data 在每列裡）⇒ 拿掉看不到的欄位。"""
    hidden = hidden_keys(body, user)
    if not hidden:
        return rows
    return [dict(r, data={k: v for k, v in (r.get("data") or {}).items() if k not in hidden}) for r in rows]


def mask_compute(result, body, user) -> dict:
    """即時計算結果（computed／tables）拿掉看不到的欄位。"""
    hidden = hidden_keys(body, user)
    if not hidden:
        return result
    out = dict(result)
    for k in ("computed", "tables"):
        if isinstance(out.get(k), dict):
            out[k] = {x: v for x, v in out[k].items() if x not in hidden}
    return out


def keep_hidden_values(body, values, existing, user) -> dict:
    """寫入前：使用者看不到的欄位——不接受他送來的值（丟掉），改用單據既有的值（新單沒有既有值 ⇒ 不填）。
    否則他一存檔，看不到的欄位就被清空（或被亂填）。"""
    hidden = hidden_keys(body, user)
    if not hidden:
        return values
    out = {k: v for k, v in (values or {}).items() if k not in hidden}
    for k in hidden:
        if existing and existing.get(k) is not None:
            out[k] = existing[k]
    return out


def render_output_for(conn, module_key, record_no, user) -> str:
    """單據輸出（HTML）但看不到的欄位不進版型（版型引用到＝空白）。"""
    from . import custom_modules as CM
    rec = mask_record(CM.get_record(conn, module_key, record_no), user)
    body = CM._load_def(conn, module_key, rec["def_version"])["body"]
    return CM.render_view(body, rec["view"])


def _shape_ok(v) -> bool:
    return isinstance(v, dict) and not (set(v) - {"roles", "users"}) and all(isinstance(v.get(k, []), list) for k in ("roles", "users"))


def _role_problem(path, v):
    bad = [r for r in (v.get("roles") or []) if r not in VISIBLE_ROLES] if isinstance(v, dict) else []
    return [{"path": path, "message": "不認得的角色：%s（可用：%s）" % ("、".join(map(str, bad)), "、".join(VISIBLE_ROLES))}] if bad else []


def access_problems(body) -> list:
    """定義的可見設定有問題 ⇒ [{path,message}]（path 用 `fields[i]`，建構器才標得到卡片）：未知鍵、形狀不對、
    角色不在清單、必填欄位設成受限。"""
    out = []
    for i, f in enumerate(body.get("fields", [])):
        acc = f.get("access") if isinstance(f, dict) else None
        if acc is None:
            continue
        p = "fields[%d].access" % i
        if not isinstance(acc, dict) or set(acc) - ACCESS_KEYS:
            out.append({"path": p, "message": "欄位可見設定只認得 visibleTo"})
            continue
        v = acc.get("visibleTo")
        if v is not None and not _shape_ok(v):
            out.append({"path": p, "message": "visibleTo 要是 {roles:[…], users:[…]}"})
            continue
        out += _role_problem(p, v)
        if f.get("required") and _spec(v) is not None:
            out.append({"path": "fields[%d].required" % i, "message": "必填欄位不可以設成只有部分人看得到（其他人填不了就存不了）"})
    menu = body.get("menu")
    v = menu.get("visibleTo") if isinstance(menu, dict) else None
    if v is not None:
        out += [{"path": "menu.visibleTo", "message": "選單 visibleTo 要是 {roles:[…], users:[…]}"}] if not _shape_ok(v) else _role_problem("menu.visibleTo", v)
    return out


def leaking_formulas(body) -> list:
    """公式欄可見者 ⊄ 被引用欄位可見者 ⇒ 公式值會把受限欄位洩漏給更多人 ⇒ [{key,message}]。
    判準：被引用欄位受限（有 visibleTo）而公式欄的可見範圍不是它的子集（公式欄不限，或含了不在其中的角色／帳號）。"""
    fields = {f["key"]: f for f in body.get("fields", []) if isinstance(f, dict) and f.get("key")}
    out = []
    index = {f.get("key"): n for n, f in enumerate(body.get("fields", [])) if isinstance(f, dict)}
    for f in fields.values():
        if f.get("type") != "formula" or not f.get("formula"):
            continue
        mine = _spec(((f.get("access") or {}).get("visibleTo")) if isinstance(f.get("access"), dict) else None)
        for ref in sorted(formula.references(f["formula"])):
            src = fields.get(ref)
            if not src:
                continue
            theirs = _spec(((src.get("access") or {}).get("visibleTo")) if isinstance(src.get("access"), dict) else None)
            if theirs is None:
                continue
            if mine is None or not (mine[0] <= theirs[0] and mine[1] <= theirs[1]):
                out.append({"path": "fields[%d].formula" % index[f["key"]], "message": "公式引用了受限欄位「%s」，但這個公式欄的可見範圍比它大——會洩漏" % (src.get("label") or ref)})
    return out


# ── 金流事件 outbox ─────────────────────────────────────────────────────

def emit_finance_event(conn, event, module_key, record_id, record_no, kind, payload, dedupe_key=None) -> bool:
    """寫一筆金流事件（呼叫端負責交易與 commit，與單據狀態變更同一個交易）。
    回 True＝新寫入；False＝同 dedupe_key 已存在（冪等略過）。預設 dedupe_key＝事件＋模組＋單＋狀態序，
    呼叫端要在「撤回後又入帳」時傳不同的 key（例：帶 rev 或時間戳）。"""
    key = dedupe_key or "%s:%s:%s" % (event, module_key, record_id)
    cur = conn.execute("INSERT OR IGNORE INTO custom_record_finance_outbox "
                       "(dedupe_key, event, module_key, record_id, record_no, kind, payload_json, created_at) "
                       "VALUES (?,?,?,?,?,?,?,?)",
                       (key, event, module_key, int(record_id), record_no or "", kind or "",
                        json.dumps(payload or {}, ensure_ascii=False, allow_nan=False),
                        datetime.now().isoformat(timespec="seconds")))
    return cur.rowcount == 1


def pending_finance_events(conn, limit=100) -> list:
    rows = conn.execute("SELECT * FROM custom_record_finance_outbox WHERE processed_at='' ORDER BY id LIMIT ?",
                        (int(limit),)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["payload"] = json.loads(d.pop("payload_json") or "{}")
        out.append(d)
    return out


def mark_finance_processed(conn, ids) -> int:
    ids = [int(i) for i in ids]
    if not ids:
        return 0
    cur = conn.execute("UPDATE custom_record_finance_outbox SET processed_at=? WHERE processed_at='' AND id IN (%s)"
                       % ",".join("?" * len(ids)), [datetime.now().isoformat(timespec="seconds")] + ids)
    return cur.rowcount


# ── 單據修訂 -R ─────────────────────────────────────────────────────────

def create_revision(conn, module_key, record_no, reason, user) -> dict:
    """對已送出的單據開修訂版 ⇒ 新單（`<原單號>-R<n>`，起始狀態、內容複製）。
    只能對最新一版修訂；原單留存不動（金流撤回由呼叫端依單據狀態處理）。回新單（get_record 形狀）。"""
    from core.txn import write_txn
    from . import custom_modules as CM
    reason = (reason or "").strip()
    if not reason:
        raise CM.CustomModuleError("修訂要填原因", [{"path": "reason", "message": "必填"}])
    with write_txn(conn):
        src = CM._row(conn, module_key, record_no)
        body = CM._load_def(conn, module_key, src["def_version"])["body"]
        if src["status"] == body["workflow"]["initial"]:
            raise CM.CustomModuleError("草稿直接修改即可，不需要修訂", status=409)
        base = src["base_no"] or src["record_no"]
        last = conn.execute("SELECT MAX(rev) FROM custom_records WHERE module_key=? AND (base_no=? OR record_no=?)",
                            (module_key, base, base)).fetchone()[0] or 0
        if src["rev"] != last:
            raise CM.CustomModuleError("只能對最新一版修訂（目前最新是 R%d）" % last if last else "只能對最新一版修訂", status=409)
        rev = last + 1
        no = "%s-R%d" % (base, rev)
        now = datetime.now().isoformat(timespec="seconds")
        vals = src["data"]
        cur = conn.execute("INSERT INTO custom_records (module_key, record_no, def_version, status, data_json, approval_json, "
                           "created_by, created_at, updated_by, updated_at, base_no, rev, supersedes_id) "
                           "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (module_key, no, src["def_version"], body["workflow"]["initial"], CM._dump_values(vals), "{}",
                            user["username"], now, user["username"], now, base, rev, src["id"]))
        if src["rev"] == 0 and not src["base_no"]:
            conn.execute("UPDATE custom_records SET base_no=? WHERE id=?", (base, src["id"]))
        CM._write_index(conn, cur.lastrowid, module_key, vals)
        CM._log(conn, cur.lastrowid, "revise", "", body["workflow"]["initial"], user["username"], "由 %s 修訂：%s" % (record_no, reason))
        CM._log(conn, src["id"], "revised", src["status"], src["status"], user["username"], "已開修訂版 %s：%s" % (no, reason))
        conn.execute("INSERT INTO custom_record_revisions (module_key, base_no, rev, record_id, prev_id, reason, by_user, at) "
                     "VALUES (?,?,?,?,?,?,?,?)", (module_key, base, rev, cur.lastrowid, src["id"], reason, user["username"], now))
        conn.commit()
    return CM.get_record(conn, module_key, no)
