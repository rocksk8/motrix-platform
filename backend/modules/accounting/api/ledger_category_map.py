# -*- coding: utf-8 -*-
"""費用類別清單與「費用類別 → 會計科目」對應的 API（G1，2026-10-01；規則見 `ledger/category_map.py`）。

- 讀取＝cashier／finance；**寫入（類別清單、對應表）＝只有最高管理者**（會計規定 B 類：科目對應變更只有最高管理者直接做），每筆寫稽核（含舊值）。
- 費用類別代碼發布後不可改（改名只改 `name`）；停用用 `active=false`。
- 提供者 `expense.categories`（單一提供者，供費用單據的定義下拉取用）由 `provide_categories` 回傳啟用中的類別。
"""
from fastapi import APIRouter, Body, Header, HTTPException

from db import get_db
from helpers import _audit, _require_user, _tok, require_any_module
from modules.accounting.ledger import category_map as _cm

router = APIRouter(prefix="/api/ledger", tags=["ledger"])
list_router = APIRouter(prefix="/api", tags=["ledger"])        # 費用單據下拉選單用：任何登入者可讀（只讀啟用中的類別）


def _require_read(authorization):
    user = _require_user(authorization)
    require_any_module(user, ("cashier", "finance"), "總帳")
    return user


def _require_super(authorization, what):
    user = _require_user(authorization)
    if user.get("role") != "superadmin":
        raise HTTPException(403, "只有最高管理者（會計主管）可以%s。" % what)
    return user


def provide_categories(conn):
    """IP `expense.categories`：啟用中的費用類別 `[{code, name, default_tax}]`（代碼發布後不可改）。唯讀。"""
    return [{"code": c["code"], "name": c["name"], "default_tax": c["default_tax"]} for c in _cm.list_categories(conn, only_active=True)]


@router.get("/category-map")
def get_category_map(authorization: str = Header(None)):
    _require_read(authorization)
    conn = get_db()
    try:
        accounts = [dict(r) for r in conn.execute("SELECT code, COALESCE(NULLIF(display_name,''), code) AS name FROM gl_account_meta WHERE postable=1 AND is_active=1 ORDER BY code")]
        return {"coverage": _cm.coverage(conn), "map": _cm.list_map(conn), "categories": _cm.list_categories(conn), "accounts": accounts[:1500]}
    finally:
        conn.close()


@router.put("/category-map")
def put_category_map(body: dict = Body(...), authorization: str = Header(None)):
    _require_super(authorization, "設定費用類別對應的科目")
    b = body or {}
    conn = get_db()
    try:
        try:
            res = _cm.upsert_map(conn, b.get("category"), b.get("account_code"), b.get("role"), bool(b.get("nondeductible")), b.get("note"))
        except _cm.CategoryError as exc:
            conn.rollback()
            raise HTTPException(400, str(exc))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "ledger.category_map.put", "gl_category_map", str(b.get("category")),
           "費用類別 %s → 科目 %s%s（原：%s）" % (b.get("category"), b.get("account_code") or b.get("role"), "（不得扣抵進項稅額）" if b.get("nondeductible") else "", res["previous"] or "無"))
    return {"ok": True, **res}


@router.delete("/category-map/{category}")
def delete_category_map(category: str, authorization: str = Header(None)):
    _require_super(authorization, "刪除費用類別對應")
    conn = get_db()
    try:
        try:
            old = _cm.delete_map(conn, category)
        except _cm.CategoryError as exc:
            conn.rollback()
            raise HTTPException(404, str(exc))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "ledger.category_map.delete", "gl_category_map", category, "刪除費用類別 %s 的科目對應（原：%s）" % (category, old))
    return {"ok": True}


@router.put("/expense-categories")
def put_expense_category(body: dict = Body(...), authorization: str = Header(None)):
    _require_super(authorization, "新增或修改費用類別")
    b = body or {}
    conn = get_db()
    try:
        try:
            res = _cm.upsert_category(conn, b.get("code"), b.get("name"), b.get("default_tax") or "", b.get("sort") or 0, b.get("note") or "", b.get("active") is not False)
        except _cm.CategoryError as exc:
            conn.rollback()
            raise HTTPException(400, str(exc))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "ledger.expense_category.put", "expense_categories", str(b.get("code")),
           "費用類別 %s＝%s（原名稱：%s）" % (b.get("code"), b.get("name"), res["previous_name"] or "無"))
    return {"ok": True, **res}


def provide_category_account(conn, key):
    """IP `gl.category_account`：`fn(conn, category_code_or_name) -> account_code | None`（唯讀；None＝沒對應，入帳時走預設科目）。"""
    return _cm.category_account(conn, key)


@list_router.get("/expense-categories")
def list_active_expense_categories(authorization: str = Header(None)):
    """費用單據的類別下拉選單（任何登入者；只回啟用中的 `[{code, name, default_tax}]`，不含科目）。"""
    _require_user(authorization)
    conn = get_db()
    try:
        return {"categories": provide_categories(conn)}
    finally:
        conn.close()
