# -*- coding: utf-8 -*-
"""總帳：報表設定 API（B1）——報表列（gl_fs_lines）與設定完整性檢查。設計：proposal-gl/04-reports.md §3、§5。

科目的 fs_line／cashflow_class 修改走 `PATCH /api/ledger/accounts/{code}`（ledger_reports.py）。
讀＝cashier／finance；改＝finance（superadmin 直通）。
"""
from fastapi import APIRouter, Body, Header, HTTPException

from db import get_db
from helpers import _audit, _require_user, _tok, require_any_module
from modules.accounting.ledger import fs_lines as _fs
from modules.accounting.ledger import roles as _roles

router = APIRouter(prefix="/api/ledger", tags=["ledger"])


def _require_settings_read(authorization):
    user = _require_user(authorization)
    require_any_module(user, ("cashier", "finance"), "總帳")
    return user


def _require_settings_write(authorization):
    user = _require_user(authorization)
    require_any_module(user, ("finance",), "總帳設定")
    return user


def _seed(conn):
    _roles.ensure_meta(conn)          # 內含 ensure_fs_lines 與現金流量分類預設
    conn.commit()


@router.get("/fs-lines")
def fs_lines(authorization: str = Header(None)):
    _require_settings_read(authorization)
    conn = get_db()
    try:
        _seed(conn)
        return {"lines": _fs.list_fs_lines(conn), "cashflow_classes": list(_fs.CASHFLOW_CLASSES)}
    finally:
        conn.close()


@router.patch("/fs-lines/{code}")
def patch_fs_line(code: str, body: dict = Body(...), authorization: str = Header(None)):
    """可改：label、sort、is_active、note。列代碼固定（報表程式依代碼取數）。停用仍有科目歸屬的列要先說明（回 409）。"""
    _require_settings_write(authorization)
    b = body or {}
    fields = {k: b[k] for k in ("label", "sort", "is_active", "note") if k in b}
    if not fields:
        raise HTTPException(400, "沒有可修改的欄位。")
    if "label" in fields and not str(fields["label"]).strip():
        raise HTTPException(400, "名稱不可空白。")
    if "sort" in fields:
        try:
            fields["sort"] = int(fields["sort"])
        except (TypeError, ValueError):
            raise HTTPException(400, "排序要是整數。")
    conn = get_db()
    try:
        _seed(conn)
        if not conn.execute("SELECT 1 FROM gl_fs_lines WHERE code=?", (code,)).fetchone():
            raise HTTPException(404, "找不到報表列 %s。" % code)
        if fields.get("is_active") in (0, False) and conn.execute(
                "SELECT 1 FROM gl_account_meta WHERE fs_line=? AND postable=1 AND is_active=1", (code,)).fetchone():
            raise HTTPException(409, "報表列 %s 底下還有可過帳的科目，停用會讓報表漏算它們；請先把那些科目改歸其他列。" % code)
        sets, args = [], []
        for k, v in fields.items():
            sets.append("%s=?" % k)
            args.append(int(bool(v)) if k == "is_active" else v)
        conn.execute("UPDATE gl_fs_lines SET %s WHERE code=?" % ", ".join(sets), args + [code])
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "ledger.fs_line.patch", "gl_fs_lines", code, "修改報表列：%s" % ",".join(fields))
    return {"ok": True}


@router.get("/setup-check")
def setup_check(authorization: str = Header(None)):
    """報表設定完整性：任何一項非空，對應的報表就會悄悄漏算或無法產出（B2～B4 的前置守門）。"""
    _require_settings_read(authorization)
    conn = get_db()
    try:
        _seed(conn)
        res = {"missing_fs_line": _roles.accounts_without_fs_line(conn), "unknown_fs_lines": _fs.unknown_fs_lines(conn),
               "unclassified_cashflow": _fs.unclassified_cashflow(conn), "inactive_lines_in_use": _fs.inactive_lines_in_use(conn)}
        res["ok"] = not any(res.values())
        return res
    finally:
        conn.close()
