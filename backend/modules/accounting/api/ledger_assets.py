# -*- coding: utf-8 -*-
"""總帳：固定資產（資產卡片、折舊表、估計變動）API（C6；proposal-gl/06-fixed-assets.md）。功能旗標 `fixed_assets`（預設關）。

只讀＝cashier／finance；新增、修改、啟用、估計變動＝**只有最高管理者**（規則 B，與費用類別對應一致；主持裁示 2026-10-01；都寫稽核）。啟用後的資產卡片會由引擎產生取得（E13a）與每月折舊（E13b）分錄草稿。
"""
from fastapi import APIRouter, Body, Header, HTTPException

from db import get_db
from helpers import _audit, _require_user, _tok, require_any_module
from modules.accounting.ledger import features as _features
from modules.accounting.ledger import fixed_assets as _fa

router = APIRouter(prefix="/api/ledger", tags=["ledger"])

_READ = ("cashier", "finance")


def _require_fa_read(authorization):
    user = _require_user(authorization)
    require_any_module(user, _READ, "總帳")
    return user


def _require_fa_write(authorization):
    user = _require_user(authorization)
    if user.get("role") != "superadmin":
        raise HTTPException(403, "只有最高管理者（會計主管）可以新增或變更固定資產。")
    return user


def _flag(conn):
    if not _features.flags(conn).get("fixed_assets"):
        raise HTTPException(409, "固定資產功能尚未開啟（最高管理者在「總帳作業」開啟）。")


def _who(user):
    return (user or {}).get("username") or ""


@router.get("/assets")
def assets(authorization: str = Header(None)):
    _require_fa_read(authorization)
    conn = get_db()
    try:
        _flag(conn)
        _fa.ensure_categories(conn)
        cats = [dict(r) for r in conn.execute("SELECT * FROM fa_categories WHERE is_active=1 ORDER BY code")]
        rows = [dict(r) for r in conn.execute("SELECT * FROM fa_assets ORDER BY id DESC")]
        return {"assets": rows, "categories": cats}
    finally:
        conn.commit()
        conn.close()


@router.post("/assets")
def create_asset(body: dict = Body(...), authorization: str = Header(None)):
    user = _require_fa_write(authorization)
    conn = get_db()
    try:
        _flag(conn)
        try:
            res = _fa.create_asset(conn, body or {}, _who(user))
        except _fa.AssetError as exc:
            conn.rollback()
            raise HTTPException(400, str(exc))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "ledger.asset.create", "fa_assets", res["asset_no"], "新增資產卡片 %s（草稿）" % res["asset_no"])
    return res


@router.patch("/assets/{asset_id}")
def update_asset(asset_id: int, body: dict = Body(...), authorization: str = Header(None)):
    _require_fa_write(authorization)
    conn = get_db()
    try:
        _flag(conn)
        try:
            _fa.update_draft(conn, asset_id, body or {})
        except _fa.AssetError as exc:
            conn.rollback()
            raise HTTPException(400, str(exc))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "ledger.asset.update", "fa_assets", str(asset_id), "修改資產卡片（草稿）：%s" % ", ".join(sorted((body or {}).keys())))
    return {"ok": True}


@router.post("/assets/{asset_id}/activate")
def activate_asset(asset_id: int, authorization: str = Header(None)):
    user = _require_fa_write(authorization)
    conn = get_db()
    try:
        _flag(conn)
        try:
            no = _fa.activate(conn, asset_id, _who(user))
        except _fa.AssetError as exc:
            conn.rollback()
            raise HTTPException(400, str(exc))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "ledger.asset.activate", "fa_assets", no, "啟用資產卡片 %s" % no)
    return {"ok": True, "asset_no": no}


@router.post("/assets/{asset_id}/revision")
def revise_asset(asset_id: int, body: dict = Body(...), authorization: str = Header(None)):
    """會計估計變動（耐用年數／殘值）：自生效月起以剩餘可折舊金額重推，不追溯已提折舊。必填原因。"""
    user = _require_fa_write(authorization)
    b = body or {}
    conn = get_db()
    try:
        _flag(conn)
        try:
            _fa.add_revision(conn, asset_id, str(b.get("effective_month") or ""), b.get("life_years"), b.get("salvage"), b.get("reason"), _who(user))
        except (_fa.AssetError, TypeError, ValueError) as exc:
            conn.rollback()
            raise HTTPException(400, str(exc))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "ledger.asset.revision", "fa_assets", str(asset_id), "會計估計變動：%s" % str(b.get("reason") or "")[:60])
    return {"ok": True}


@router.get("/assets/schedule")
def asset_schedule(ym: str, authorization: str = Header(None)):
    _require_fa_read(authorization)
    if not (len(ym) == 7 and ym[4] == "-" and ym[:4].isdigit() and ym[5:].isdigit() and 1 <= int(ym[5:]) <= 12):
        raise HTTPException(400, "月份格式要是 YYYY-MM。")
    conn = get_db()
    try:
        _flag(conn)
        return _fa.schedule(conn, ym)
    finally:
        conn.commit()
        conn.close()
