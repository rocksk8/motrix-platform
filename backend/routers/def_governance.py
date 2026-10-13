# -*- coding: utf-8 -*-
"""定義治理 API（BP-1，t59）：版本帳本、任兩版差異、發布前影響預覽。僅超級管理員；旗標 `builder_governance.enabled` 關閉時一律 404。

邏輯與路由同檔（不新增 L0 公開介面；不改資料庫結構、不寫任何定義）。只讀（預覽會留一筆『看過預覽』稽核，不記內容）。還原沿用 `POST /api/definitions/{kind}/{key}/restore/{version}`。
"""
from fastapi import APIRouter, Header, HTTPException, Query

from db import get_db
from helpers import _require_user, _tok, _audit
from core import definitions as D

router = APIRouter()


def kinds():
    """已登錄的定義種類（唯讀檢視，所以全部可看）；寫入（發布／還原）仍走既有端點與它們各自的把關與審核。"""
    return D.kinds()

#: 影響範圍宣告（白話）：這一類定義發布後會動到哪裡。
_SCOPE_TEXT = {
    "layout": {"screens": "該模組的頁面版面（欄位顯示、順序、按鈕與選單位置）", "customerVisible": False},
    "output_template": {"screens": "該單據的列印／PDF／預覽版型", "customerVisible": True},
    "custom_fields": {"screens": "掛載該欄位集的表單與列表", "customerVisible": False},
    "custom_module": {"screens": "這個自訂模組的表單、列表、流程與簽核層", "customerVisible": False},
}
_GENERIC_SCOPE = {"screens": "使用這份定義的畫面", "customerVisible": False}


def enabled(conn=None) -> bool:
    """旗標 `builder_governance.enabled`（預設 0＝關）。讀不到一律當關。"""
    try:
        from helpers import settings_registry as R
        return int(R.get("builder_governance", "enabled", conn=conn)) == 1
    except Exception:                                                  # noqa: BLE001
        return False


def _check_kind(kind):
    if kind not in kinds():
        raise D.DefinitionError("治理檢視不支援這個定義種類：%r（可用：%s）" % (kind, "、".join(kinds())))


def ledger(conn, kind, key, scope) -> dict:
    """版本帳本：每一版的誰／何時／備註，標出目前生效版（最新已發布）與是否有草稿、是否有送審中。"""
    _check_kind(kind)
    rows = D.versions(conn, kind, key, scope)
    published = [r["version"] for r in rows if r["status"] == "published"]
    live = max(published) if published else None
    out = []
    for r in rows:
        if r["version"] == 0:
            continue                                                   # 草稿另外標示
        out.append({"version": r["version"], "status": r["status"], "note": r["note"], "by": r["published_by"] or r["created_by"],
                    "at": r["published_at"] or r["created_at"], "isLive": r["version"] == live and r["status"] == "published",
                    "restorable": r["status"] == "published" and r["version"] != live})
    return {"kind": kind, "key": key, "scope": scope, "live": live, "hasDraft": any(r["version"] == 0 for r in rows),
            "pendingReview": any(r["status"] == "submitted" for r in rows), "versions": out}


def _body(conn, kind, key, scope, which):
    if which == "draft":
        r = D.get(conn, kind, key, scope, 0)
    elif which == "live":
        r = D.get(conn, kind, key, scope)
    elif which == "default":
        return D.default_for(kind, key) or {}
    else:
        try:
            n = int(which)
        except (TypeError, ValueError):
            raise D.DefinitionError("版本必須是數字、live、draft 或 default：%r" % (which,))
        r = D.get(conn, kind, key, scope, n)
        if r is not None and r["status"] != "published":
            r = None
    if r is None:
        raise D.DefinitionError("找不到 %s" % (which,))
    return r.get("body") or {}


def version_diff(conn, kind, key, scope, a, b) -> dict:
    """任兩版（或 live／draft／default）的逐欄差異；沿用 `core.definitions.diff`。"""
    _check_kind(kind)
    return {"a": str(a), "b": str(b), "changes": D.diff(_body(conn, kind, key, scope, a), _body(conn, kind, key, scope, b))}


def impact(conn, kind, key, scope) -> dict:
    """發布前影響預覽：草稿對目前生效版的差異、驗證結果、同一定義在其他範圍（公司／角色）的版本、宣告的影響範圍。
    `previewHash`＝草稿內容戳（`etag_of`）：發布時帶回同一個戳 ⇒ 證明發布的是看過的那一版。"""
    _check_kind(kind)
    draft = D.get(conn, kind, key, scope, 0)
    live = D.get(conn, kind, key, scope)
    problems = D.validate(kind, key, draft["body"]) if draft else []
    changes = D.diff((live or {}).get("body") or {}, draft["body"]) if draft else []
    others = [{"scope": r["scope"], "latestVersion": r["latestVersion"]} for r in D.list_definitions(conn, kind)
              if r["key"] == key and r["scope"] != scope and r["latestVersion"]]
    live_v = (live or {}).get("version")
    frozen = None
    if kind == "custom_module" and scope == "company":
        # 自訂模組的單據在建立時凍結定義版本（def_version）：凍結在目前生效版的單據數＝發布新版後仍用舊版的單據數
        try:
            frozen = conn.execute("SELECT COUNT(*) FROM custom_records WHERE module_key=? AND def_version=?", (key, live_v or 0)).fetchone()[0]
        except Exception:                                              # noqa: BLE001  舊庫沒有此表 ⇒ 不適用
            frozen = None
    return {"kind": kind, "key": key, "scope": scope, "hasDraft": draft is not None,
            "liveVersion": live_v, "nextVersion": ((live_v or 0) + 1) if draft else None,
            "previewHash": (draft or {}).get("etag", ""), "changes": changes, "changeCount": len(changes),
            "validation": {"ok": not problems, "problems": problems}, "otherScopes": others,
            "declared": dict(_SCOPE_TEXT.get(kind, _GENERIC_SCOPE), roleOverridesPresent=scope == "company" and bool(others)),
            "frozenRecords": frozen,                                   # 只有自訂模組（公司範圍）會在單據上凍結版本；其他種類 ⇒ None＝不適用（不是 0）
            "note": ("已建立的單據維持它建立時的版本；新單據用新版。" if kind == "custom_module"
                     else "發布後立即套用到畫面；已存的單據資料不會被改動。")}


def _gate(authorization, kind):
    """先驗身分（未登入 ⇒ 401，與其他路由一致），再看旗標與 kind；通過回連線（呼叫端關閉）。"""
    _require_user(authorization, require_superadmin=True)
    conn = get_db()
    if not enabled(conn) or kind not in kinds():
        conn.close()
        raise HTTPException(404, "Not Found")
    return conn


@router.get("/api/def-governance/{kind}/{key}/ledger")
def def_ledger(kind: str, key: str, scope: str = Query("company"), authorization: str = Header(None)):
    conn = _gate(authorization, kind)
    try:
        return ledger(conn, kind, key, scope)
    except D.DefinitionError as e:
        raise HTTPException(400, str(e))
    finally:
        conn.close()


@router.get("/api/def-governance/{kind}/{key}/diff")
def def_diff(kind: str, key: str, scope: str = Query("company"), a: str = Query("live"), b: str = Query("draft"),
             authorization: str = Header(None)):
    conn = _gate(authorization, kind)
    try:
        return version_diff(conn, kind, key, scope, a, b)
    except D.DefinitionError as e:
        raise HTTPException(400, str(e))
    finally:
        conn.close()


@router.get("/api/def-governance/{kind}/{key}/impact")
def def_impact(kind: str, key: str, scope: str = Query("company"), authorization: str = Header(None)):
    conn = _gate(authorization, kind)
    try:
        out = impact(conn, kind, key, scope)
    except D.DefinitionError as e:
        raise HTTPException(400, str(e))
    finally:
        conn.close()
    _audit(_tok(authorization), "definitions.previewed", "ui_definition", "%s/%s/%s" % (kind, key, scope),
           "看過發布前影響預覽（%s %s，草稿戳 %s）" % (kind, key, out["previewHash"] or "無草稿"), {})
    return out
