# -*- coding: utf-8 -*-
"""總帳：帳簿報表 API（試算表、總分類帳、明細分類帳、序時帳簿）與科目屬性／角色設定。設計：proposal-gl/04-reports.md、01-accounts.md。

只讀＝cashier／finance；改科目屬性與角色＝finance（superadmin 直通）。報表的日期一律 YYYY-MM-DD。
"""
import datetime as _dt

from fastapi import APIRouter, Body, Header, HTTPException, Query

from db import get_db
from helpers import _audit, _require_user, _tok, require_any_module
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
                   dimension: str = None, key: str = None, authorization: str = Header(None)):
    _require_read(authorization)
    s, e = _range(start, end)
    conn = get_db()
    try:
        try:
            res = _reports.general_ledger(conn, account, s, e, include_drafts=include_drafts, dimension=dimension, key=key)
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
               " m.tax_role, m.display_name, m.is_active FROM gl_account_meta m JOIN account_items a ON a.code=m.code")
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
                "missing_fs_line": _roles.accounts_without_fs_line(conn)}
    finally:
        conn.close()


@router.patch("/accounts/{code}")
def patch_account(code: str, body: dict = Body(...), authorization: str = Header(None)):
    """可改：fs_line、display_name、is_active（總帳層停用，法定科目也可）、note。類別與方向不開放（改了報表會整批偏）。"""
    _require_write(authorization)
    fields = {k: body[k] for k in ("fs_line", "display_name", "is_active", "note") if k in (body or {})}
    if not fields:
        raise HTTPException(400, "沒有可修改的欄位。")
    conn = get_db()
    try:
        _roles.ensure_meta(conn)
        if not conn.execute("SELECT 1 FROM gl_account_meta WHERE code=?", (code,)).fetchone():
            raise HTTPException(404, "找不到科目 %s。" % code)
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


@router.put("/roles")
def put_role(body: dict = Body(...), authorization: str = Header(None)):
    """設定角色→科目（可帶 scope 與生效日）。科目必須存在；停用中的科目不可作為角色科目。"""
    _require_write(authorization)
    b = body or {}
    role, code = str(b.get("role") or "").strip(), str(b.get("account_code") or "").strip()
    if not role or not code:
        raise HTTPException(400, "需要 role 與 account_code。")
    conn = get_db()
    try:
        _roles.ensure_meta(conn)
        m = conn.execute("SELECT postable, is_active FROM gl_account_meta WHERE code=?", (code,)).fetchone()
        if m is None:
            raise HTTPException(400, "科目 %s 不存在。" % code)
        if not m["is_active"]:
            raise HTTPException(400, "科目 %s 已停用。" % code)
        if not m["postable"]:
            raise HTTPException(400, "科目 %s 底下還有子科目，不能直接過帳；請選最底層科目。" % code)
        conn.execute("INSERT INTO gl_account_roles(role,scope_type,scope_key,account_code,effective_from) VALUES(?,?,?,?,?)"
                     " ON CONFLICT(role,scope_type,scope_key,effective_from) DO UPDATE SET account_code=excluded.account_code",
                     (role, str(b.get("scope_type") or ""), str(b.get("scope_key") or ""), code, str(b.get("effective_from") or "")))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "ledger.role.put", "gl_account_roles", role, "角色 %s → %s" % (role, code))
    return {"ok": True}
