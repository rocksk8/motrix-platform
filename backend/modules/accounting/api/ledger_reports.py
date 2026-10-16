# -*- coding: utf-8 -*-
"""總帳：帳簿報表 API（試算表、總分類帳、明細分類帳、序時帳簿）與科目屬性／角色設定。設計：proposal-gl/04-reports.md、01-accounts.md。

只讀＝cashier／finance；改科目屬性與角色＝finance（superadmin 直通）。報表的日期一律 YYYY-MM-DD。
"""
import datetime as _dt

from fastapi import APIRouter, Body, Header, HTTPException, Query

from core.txn import begin_write
from db import get_db
from helpers import config_ledger as _L
from helpers import _audit, _require_user, _tok, require_any_module
from modules.accounting.ledger import fs_lines as _fs
from modules.accounting.ledger import reports as _reports
from modules.accounting.ledger import roles as _roles

router = APIRouter(prefix="/api/ledger", tags=["ledger"])


def _require_read(authorization):
    user = _require_user(authorization)
    require_any_module(user, ("cashier", "finance"), "總帳")
    return user


def _require_write(authorization):
    user = _require_user(authorization)
    require_any_module(user, ("finance",), "總帳設定")
    return user


def _require_super(authorization, what):
    user = _require_user(authorization)
    if user.get("role") != "superadmin":
        raise HTTPException(403, "只有最高管理者（會計主管）可以%s。" % what)
    return user


def _date(v, name):
    try:
        return _dt.date.fromisoformat(str(v))
    except ValueError:
        raise HTTPException(400, "%s 格式要是 YYYY-MM-DD。" % name)


def _range(start, end):
    s, e = _date(start, "起日"), _date(end, "迄日")
    if s > e:
        raise HTTPException(400, "起日不可晚於迄日。")
    return s.isoformat(), e.isoformat()


@router.get("/trial-balance")
def trial_balance(start: str, end: str, include_drafts: bool = False, include_zero: bool = False,
                  authorization: str = Header(None)):
    _require_read(authorization)
    s, e = _range(start, end)
    conn = get_db()
    try:
        try:
            return _reports.trial_balance(conn, s, e, include_drafts=include_drafts, include_zero=include_zero)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        finally:
            conn.commit()               # ensure_meta 可能補了缺的科目屬性列（冪等種子），順手落地
    finally:
        conn.close()


@router.get("/general-ledger")
def general_ledger(account: str, start: str, end: str, include_drafts: bool = False,
                   dimension: str = None, dimension_value: str = None, authorization: str = Header(None)):
    _require_read(authorization)
    s, e = _range(start, end)
    conn = get_db()
    try:
        try:
            res = _reports.general_ledger(conn, account, s, e, include_drafts=include_drafts, dimension=dimension, key=dimension_value)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if res is None:
            raise HTTPException(404, "找不到科目 %s。" % account)
        return res
    finally:
        conn.commit()
        conn.close()


@router.get("/subledger")
def subledger(account: str, dimension: str, start: str, end: str, include_drafts: bool = False,
              authorization: str = Header(None)):
    _require_read(authorization)
    s, e = _range(start, end)
    conn = get_db()
    try:
        try:
            res = _reports.subledger(conn, account, dimension, s, e, include_drafts=include_drafts)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if res is None:
            raise HTTPException(404, "找不到科目 %s。" % account)
        return res
    finally:
        conn.commit()
        conn.close()


@router.get("/journal")
def journal(start: str, end: str, include_drafts: bool = False, authorization: str = Header(None)):
    _require_read(authorization)
    s, e = _range(start, end)
    conn = get_db()
    try:
        return _reports.journal(conn, s, e, include_drafts=include_drafts)
    finally:
        conn.close()


# ── 科目屬性與角色 ────────────────────────────────────────────────────────

@router.get("/accounts")
def accounts(q: str = Query(default=""), only_postable: bool = False, authorization: str = Header(None)):
    _require_read(authorization)
    conn = get_db()
    try:
        _roles.ensure_meta(conn)
        _roles.ensure_default_roles(conn)
        conn.commit()
        sql = ("SELECT m.code, a.name, a.level, a.source, m.acct_type, m.normal_side, m.postable, m.is_contra, m.fs_line,"
               " m.cashflow_class, m.tax_role, m.display_name, m.is_active FROM gl_account_meta m JOIN account_items a ON a.code=m.code")
        where, args = [], []
        if q:
            where.append("(m.code LIKE ? OR a.name LIKE ?)")
            args += [q + "%", "%" + q + "%"]
        if only_postable:
            where.append("m.postable=1")
        rows = conn.execute(sql + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY m.code", args).fetchall()
        roles = conn.execute("SELECT role, scope_type, scope_key, account_code, effective_from FROM gl_account_roles"
                             " ORDER BY role, scope_type, scope_key, effective_from").fetchall()
        return {"accounts": [dict(r) for r in rows], "roles": [dict(r) for r in roles],
                "missing_fs_line": _roles.accounts_without_fs_line(conn),
                "unclassified_cashflow": _fs.unclassified_cashflow(conn), "unknown_fs_lines": _fs.unknown_fs_lines(conn)}
    finally:
        conn.close()


@router.patch("/accounts/{code}")
def patch_account(code: str, body: dict = Body(...), authorization: str = Header(None)):
    """可改：fs_line（須是 gl_fs_lines 有的列）、cashflow_class（cash／operating／investing／financing）、display_name、
    is_active（總帳層停用，法定科目也可）、note。類別與方向不開放（改了報表會整批偏）。"""
    _require_super(authorization, "修改科目的報表列與屬性")            # B：科目對應（報表列／現金流量分類…）只有最高管理者
    fields = {k: body[k] for k in ("fs_line", "cashflow_class", "display_name", "is_active", "note") if k in (body or {})}
    if not fields:
        raise HTTPException(400, "沒有可修改的欄位。")
    conn = get_db()
    try:
        _roles.ensure_meta(conn)
        row = conn.execute("SELECT acct_type FROM gl_account_meta WHERE code=?", (code,)).fetchone()
        if not row:
            raise HTTPException(404, "找不到科目 %s。" % code)
        if "fs_line" in fields and not conn.execute("SELECT 1 FROM gl_fs_lines WHERE code=?", (fields["fs_line"],)).fetchone():
            raise HTTPException(400, "報表列 %s 不存在。" % fields["fs_line"])
        if "cashflow_class" in fields:
            if fields["cashflow_class"] not in _fs.CASHFLOW_CLASSES:
                raise HTTPException(400, "現金流量分類只能是：%s。" % "、".join(_fs.CASHFLOW_CLASSES))
            if row["acct_type"] not in _fs.BS_TYPES:
                raise HTTPException(400, "損益科目不分類（淨利整體歸營業活動）。")
        sets, args = [], []
        for k, v in fields.items():
            sets.append("%s=?" % k)
            args.append(int(bool(v)) if k == "is_active" else str(v))
        conn.execute("UPDATE gl_account_meta SET %s WHERE code=?" % ", ".join(sets), args + [code])
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "ledger.account.patch", "gl_account_meta", code, "修改科目屬性：%s" % ",".join(fields))
    return {"ok": True}


# ── 角色→科目對應（金流）：變更要第二位最高管理者核准（T69 使用者裁示 a）────────────────────────────
# 走設定帳本 config_ledger：申請＝寫一筆 pending 明細（risk=money、approvals_required=1、通知其他最高管理者），
# 另一位最高管理者核准後**立即**套用到 gl_account_roles（沒有確認期間）；申請人不能核准自己的。
# 沒有第二位在職最高管理者 ⇒ 擋下（409）並說明，不自動放行（待使用者裁示，見 t69-ledger-notes.md）。
_ROLE_DOMAIN = "ledger:role"


def _role_key(p):
    return "|".join((p["role"], p["scope_type"], p["scope_key"], p["effective_from"]))


def _check_role_target(conn, code):
    m = conn.execute("SELECT postable, is_active FROM gl_account_meta WHERE code=?", (code,)).fetchone()
    if m is None:
        raise HTTPException(400, "科目 %s 不存在。" % code)
    if not m["is_active"]:
        raise HTTPException(400, "科目 %s 已停用。" % code)
    if not m["postable"]:
        raise HTTPException(400, "科目 %s 底下還有子科目，不能直接過帳；請選最底層科目。" % code)


def _current_role_code(conn, p):
    r = conn.execute("SELECT account_code FROM gl_account_roles WHERE role=? AND scope_type=? AND scope_key=? AND effective_from=?",
                     (p["role"], p["scope_type"], p["scope_key"], p["effective_from"])).fetchone()
    return r[0] if r else None


_PAGE = 1000          # history() 單頁上限；用分頁走完全部，舊的待核准項不會因為列數多而被擠掉


def _role_rows(conn):
    """角色對應的全部變更明細（新→舊），分頁走完。"""
    off = 0
    while True:
        page = _L.history(conn, _ROLE_DOMAIN, None, limit=_PAGE, offset=off)
        for r in page:
            if r["domain"] == _ROLE_DOMAIN:
                yield r
        if len(page) < _PAGE:
            return
        off += _PAGE


def _role_pending_row(conn, pid):
    for r in _role_rows(conn):
        if r["id"] == pid:
            return r
    raise HTTPException(404, "找不到這筆待核准的角色對應變更。")


def _pending_view(r):
    p = r["new"] if isinstance(r["new"], dict) else {}
    return {"id": r["id"], "role": p.get("role"), "scope_type": p.get("scope_type", ""), "scope_key": p.get("scope_key", ""),
            "effective_from": p.get("effective_from", ""), "account_code": p.get("account_code"), "old_account_code": r["old"],
            "reason": r["reason"], "requested_by": r["actor"], "requested_at": r["at"], "state": r["state"],
            "approvals": list(r.get("approvals") or []), "approvals_required": int(r.get("approvals_required") or 0)}


@router.get("/roles")
def list_roles(authorization: str = Header(None)):
    """唯讀：現行角色→科目對應，與待第二位最高管理者核准的變更。"""
    _require_read(authorization)
    conn = get_db()
    try:
        _roles.ensure_meta(conn)
        _roles.ensure_default_roles(conn)
        conn.commit()
        roles = conn.execute("SELECT r.role, r.scope_type, r.scope_key, r.account_code, r.effective_from, a.name AS account_name"
                             " FROM gl_account_roles r LEFT JOIN account_items a ON a.code=r.account_code"
                             " ORDER BY r.role, r.scope_type, r.scope_key, r.effective_from").fetchall()
        pend = [_pending_view(r) for r in _role_rows(conn) if r["state"] == "pending"]
        return {"roles": [dict(r) for r in roles], "pending": pend}
    finally:
        conn.close()


@router.put("/roles", status_code=202)
def put_role(body: dict = Body(...), authorization: str = Header(None)):
    """申請設定角色→科目（可帶 scope 與生效日）；**不會立刻生效**，要另一位最高管理者核准。科目必須存在；停用中的科目不可作為角色科目。"""
    user = _require_super(authorization, "設定角色對應的科目")                # B：角色→科目對應只有最高管理者
    b = body or {}
    p = {"role": str(b.get("role") or "").strip(), "account_code": str(b.get("account_code") or "").strip(),
         "scope_type": str(b.get("scope_type") or ""), "scope_key": str(b.get("scope_key") or ""),
         "effective_from": str(b.get("effective_from") or "")}
    reason = str(b.get("reason") or "").strip()
    if not p["role"] or not p["account_code"]:
        raise HTTPException(400, "需要 role 與 account_code。")
    if len(reason) < 2:
        raise HTTPException(400, "請填寫變更原因（角色對應影響金流，另一位最高管理者要看得到原因）。")
    conn = get_db()
    try:
        begin_write(conn)
        _roles.ensure_meta(conn)
        _check_role_target(conn, p["account_code"])
        others = [r[0] for r in conn.execute("SELECT username FROM users WHERE active=1 AND role='superadmin' AND username<>?", (user["username"],))]
        if not others:
            raise HTTPException(409, "角色對應的變更需要另一位在職的最高管理者核准；目前沒有第二位最高管理者，無法申請。")
        if _current_role_code(conn, p) == p["account_code"]:
            raise HTTPException(409, "這個角色目前已經是這個科目，不需要變更。")
        key = _role_key(p)
        for r in _role_rows(conn):
            if r["key"] == key and r["state"] == "pending":
                _L.supersede(conn, r["id"], user, "被較新的申請取代")
        rec = _L.record(conn, _ROLE_DOMAIN, key, [{"field": "account_code", "old": _current_role_code(conn, p), "new": p}], reason, user,
                        risk="money", effective_at=_dt.datetime.now().isoformat(timespec="seconds"), approvals_required=1,
                        audit_action="ledger.role.request", target_label="角色 %s → %s（待核准）" % (p["role"], p["account_code"]),
                        link="ledger-settings.html")
        conn.commit()
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()
    return {"ok": True, "pending": True, "id": rec["ids"][0], "approvals_required": 1}


@router.post("/roles/pending/{pid}/approve")
def approve_role(pid: int, body: dict = Body(default={}), authorization: str = Header(None)):
    """另一位最高管理者核准 ⇒ 立刻套用到 gl_account_roles。申請人不能核准自己的；核准時再驗一次科目（可能已被停用）。"""
    user = _require_super(authorization, "核准角色對應的變更")
    why = str((body or {}).get("reason") or "")
    conn = get_db()
    try:
        begin_write(conn)
        row = _role_pending_row(conn, int(pid))
        if row["state"] != "pending":
            raise HTTPException(409, "這筆已不是待核准狀態（%s）。" % row["state"])
        p = row["new"] if isinstance(row["new"], dict) else {}
        try:
            _check_role_target(conn, str(p.get("account_code") or ""))
        except HTTPException as e:                       # 申請後科目被停用／改成非葉節點：不核准，維持待核准（可撤銷）
            raise HTTPException(409, "申請後科目狀態已改變，無法核准：" + str(e.detail))
        res = _L.approve(conn, int(pid), user, why)
        if not res["ok"]:
            raise HTTPException(409, res["why"])
        _L.audit_event(conn, user, "ledger.role.approve", pid, {"id": int(pid), "role": p.get("role"), "account_code": p.get("account_code"),
                                                                  "reason": why}, target_label="核准角色對應 #%s" % pid)
        conn.execute("INSERT INTO gl_account_roles(role,scope_type,scope_key,account_code,effective_from) VALUES(?,?,?,?,?)"
                     " ON CONFLICT(role,scope_type,scope_key,effective_from) DO UPDATE SET account_code=excluded.account_code",
                     (p["role"], p.get("scope_type", ""), p.get("scope_key", ""), p["account_code"], p.get("effective_from", "")))
        _L.audit_event(conn, user, "ledger.role.put", p["role"], {"role": p["role"], "account_code": p["account_code"], "old": row["old"],
                                                                    "requested_by": row["actor"], "approved_by": user["username"], "id": int(pid)},
                       target_label="角色 %s → %s" % (p["role"], p["account_code"]))
        _L._append(conn, int(pid), "activated", user, "核准後套用")
        conn.commit()
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()
    return {"ok": True, "applied": True}


@router.post("/roles/pending/{pid}/cancel")
def cancel_role(pid: int, body: dict = Body(default={}), authorization: str = Header(None)):
    """撤銷待核准的角色對應變更：任一最高管理者（含申請人）皆可，需原因。"""
    user = _require_super(authorization, "撤銷角色對應的待核准變更")
    reason = str((body or {}).get("reason") or "").strip()
    if len(reason) < 2:
        raise HTTPException(400, "撤銷請填寫原因。")
    conn = get_db()
    try:
        begin_write(conn)
        row = _role_pending_row(conn, int(pid))
        if not _L.cancel(conn, int(pid), user, reason):
            raise HTTPException(409, "這筆已不是待核准狀態（%s）。" % row["state"])
        _L.audit_event(conn, user, "ledger.role.cancel", pid, {"id": int(pid), "reason": reason}, target_label="撤銷角色對應 #%s" % pid)
        conn.commit()
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()
    return {"ok": True}
