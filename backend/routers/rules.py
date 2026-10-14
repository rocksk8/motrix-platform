# -*- coding: utf-8 -*-
"""標示型規則 API（BP-2 R2；設計 docs/platform/plans/BP2-RULES-MARK-DESIGN-T62.md §7、§8）。

旗標 `builder_rules.enabled` 關（預設）⇒ 本檔所有路由 404（先驗身分，與其他路由一致）。全部**唯讀**（不寫任何定義或資料；
唯一的寫入是『規則故障』的稽核，同一條規則同一版 5 分鐘最多一筆）。規則集本身的草稿／發布／還原走通用定義介面
（kind＝`rule_set`），版本帳本／預覽雜湊／放寬核准全部沿用治理層。

- `GET  /api/rules/config`   最高管理者：主題、欄位目錄（依本人可見度裁剪）、上限、是否接上資料來源
- `GET  /api/rules/summary`  最高管理者：已發布規則在最近 N 筆的命中數
- `POST /api/rules/preview`  最高管理者：草稿規則 vs 已發布規則，對最近 N 筆（掃 ≤1000、列樣本 ≤200）的新增／取消命中；**不寫資料**
- `GET  /api/rules/marks`    任何登入者：這幾筆紀錄（≤200）對『本人』的標示；紀錄的讀取權限由資料來源提供者過濾，欄位可見度由目錄裁剪

遮蔽優先：每個請求都以呼叫者本人的可見欄位評估；條件用到看不到的欄位 ⇒ 規則對他不評估（回應不含任何痕跡）。
快取：本版**不做**跨請求快取（請求量有上限且受預算約束；快取要以（規則版本，角色，可見欄位集合）為鍵，留待有量測證據後再做）。
"""
import time

from fastapi import APIRouter, Body, Header, HTTPException, Query

from db import get_db
from helpers import _require_user, _tok, _audit
from helpers import rule_catalog as C
from helpers import rule_engine as E
from helpers import rule_grammar as G
from helpers import rule_sets as RS
from core import definitions as D

router = APIRouter()

SAMPLE_SHOWN, SCAN_MAX, MARKS_MAX_IDS = 200, 1000, 200
PREVIEW_BUDGET_MS, MARKS_BUDGET_MS = 2000, 300
_DEGRADE_LOGGED = {}                                               # (主題, 規則id, 版本) ⇒ 上次寫稽核的 monotonic 時間
_DEGRADE_EVERY = 300.0


def _flag_gate(conn):
    """旗標關 ⇒ 404（不洩漏功能存在）；開 ⇒ 確保定義種類已登記。呼叫端必須已驗過身分。"""
    if not RS.enabled(conn):
        conn.close()
        raise HTTPException(404, "Not Found")
    RS.ensure_registered()


def _entity(entity):
    if entity not in C.ENTITIES:
        raise HTTPException(404, "Not Found")
    return entity


def _live(conn, entity):
    r = D.get(conn, RS.KIND, entity, "company")
    return ((r or {}).get("body") or {}), (r or {}).get("version") or 0


def _note_degraded(authorization, entity, version, degraded):
    """規則故障要大聲，但不能灌爆稽核：同一規則同一版 5 分鐘最多一筆。"""
    now = time.monotonic()
    for d in degraded:
        k = (entity, d["ruleId"], version)
        if now - _DEGRADE_LOGGED.get(k, -1e9) >= _DEGRADE_EVERY:
            _DEGRADE_LOGGED[k] = now
            try:
                _audit(_tok(authorization), "rules.degraded", "rule_set", entity,
                       "規則 %s 暫停評估（%s）" % (d["ruleId"], d["reason"]), {"ruleId": d["ruleId"], "reason": d["reason"], "version": version})
            except Exception:                                      # noqa: BLE001  稽核寫不進去不可影響畫面
                pass


def _flagged(out):
    return set(out["marks"])


@router.get("/api/rules/config")
def rules_config(authorization: str = Header(None)):
    u = _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        _flag_gate(conn)
        ents = []
        for e in C.entities():
            ents.append(dict(e, fields=C.rule_fields(e["key"], u, conn), sourceAvailable=_has_source(e["key"])))
        return {"entities": ents, "levels": list(G.LEVELS), "targets": list(G.TARGETS), "limits": dict(G.LIMITS),
                "sample": {"shown": SAMPLE_SHOWN, "scanned": SCAN_MAX}, "kind": RS.KIND,
                "modes": ["mark"], "onFailure": ["degrade_loud"]}
    finally:
        conn.close()


def _has_source(entity):
    from core import registry
    return entity in registry.providers("rules.entity")


@router.get("/api/rules/summary")
def rules_summary(entity: str = Query(...), authorization: str = Header(None)):
    u = _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        _flag_gate(conn)
        _entity(entity)
        body, ver = _live(conn, entity)
        rows = C.load_records(entity, u, conn, limit=SCAN_MAX)
        rules = body.get("rules") if isinstance(body.get("rules"), list) else []
        base = {"entity": entity, "version": ver, "rules": [{"id": r.get("id"), "name": r.get("name"), "enabled": r.get("enabled", True),
                                                             "level": (r.get("mark") or {}).get("level")} for r in rules if isinstance(r, dict)]}
        if rows is None:
            return dict(base, available=False, message="這個主題還沒有接上資料來源，無法計算命中數", sampled=0, hits={})
        out = E.evaluate(rules, rows, C.visible_ids(entity, u, conn), budget_ms=PREVIEW_BUDGET_MS)
        _note_degraded(authorization, entity, ver, out["degraded"])
        return dict(base, available=True, sampled=len(rows), hits=out["hits"], degraded=out["degraded"], notApplicable=out["notApplicable"])
    finally:
        conn.close()


@router.post("/api/rules/preview")
def rules_preview(payload: dict = Body(default={}), authorization: str = Header(None)):
    """草稿（請求內的 `body`；省略 ⇒ 用已存的草稿）對已發布規則：最近 N 筆內『新增被標示』『取消被標示』幾筆與樣本。唯讀。"""
    u = _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        _flag_gate(conn)
        entity = _entity((payload or {}).get("entity"))
        body = (payload or {}).get("body")
        if body is None:
            d = D.get(conn, RS.KIND, entity, "company", 0)
            if d is None:
                raise HTTPException(400, "目前沒有草稿，也沒有帶規則內容")
            body = d["body"]
        probs = G.validate_rule_set(body, C.all_fields(entity, conn))
        if probs:
            raise HTTPException(422, {"problems": probs})
        try:
            limit = max(1, min(int((payload or {}).get("limit") or SCAN_MAX), SCAN_MAX))
        except (TypeError, ValueError):
            raise HTTPException(400, "limit 必須是整數")
        rows = C.load_records(entity, u, conn, limit=limit)
        live_body, ver = _live(conn, entity)
        from routers import def_pipeline as P
        direction, reasons = P.classify(RS.KIND, live_body, body)
        if rows is None:
            return {"entity": entity, "available": False, "message": "這個主題還沒有接上資料來源，無法預覽命中的紀錄", "direction": direction, "reasons": reasons}
        vis = C.visible_ids(entity, u, conn)
        cur = E.evaluate(live_body.get("rules") or [], rows, vis, budget_ms=PREVIEW_BUDGET_MS)
        new = E.evaluate(body.get("rules") or [], rows, vis, budget_ms=PREVIEW_BUDGET_MS)
        before, after = _flagged(cur), _flagged(new)
        by_id = {r["id"]: r for r in rows}
        samples = []
        for rid in [r["id"] for r in rows if r["id"] in after][:SAMPLE_SHOWN]:
            used = {f for m in new["marks"][rid] for f in _used_fields(body, m["ruleId"])}
            samples.append({"id": rid, "label": by_id[rid]["label"], "ruleIds": [m["ruleId"] for m in new["marks"][rid]],
                            "isNew": rid not in before, "values": {k: v for k, v in by_id[rid]["values"].items() if k in used}})
        return {"entity": entity, "available": True, "sampled": len(rows), "scanLimit": limit, "liveVersion": ver,
                "published": {"records": len(before), "hits": cur["hits"]}, "draft": {"records": len(after), "hits": new["hits"]},
                "added": len(after - before), "removed": len(before - after), "samples": samples,
                "direction": direction, "reasons": reasons,
                "degraded": new["degraded"], "notApplicable": new["notApplicable"],
                "note": "依最近 %d 筆估算（不是全部紀錄）；只列你本來就看得到的紀錄與欄位。" % len(rows)}
    finally:
        conn.close()


def _used_fields(body, rule_id):
    for r in body.get("rules") or []:
        if isinstance(r, dict) and r.get("id") == rule_id:
            return G.fields_used(r.get("when"))
    return set()


@router.get("/api/rules/marks")
def rules_marks(entity: str = Query(...), ids: str = Query(""), authorization: str = Header(None)):
    u = _require_user(authorization)
    conn = get_db()
    try:
        _flag_gate(conn)
        _entity(entity)
        want = [x for x in (s.strip() for s in ids.split(",")) if x][:MARKS_MAX_IDS]
        empty = {"entity": entity, "marks": {}, "degraded": False}
        if not want:
            return empty
        try:
            body, ver = _live(conn, entity)
        except Exception:                                          # noqa: BLE001  規則讀不到不可影響任何畫面（視為沒有規則）
            return empty
        rules = body.get("rules") if isinstance(body.get("rules"), list) else []
        if not any(isinstance(r, dict) and r.get("enabled", True) is True for r in rules):
            return empty
        rows = C.load_records(entity, u, conn, ids=want, limit=len(want))
        if not rows:
            return empty
        out = E.evaluate(rules, rows, C.visible_ids(entity, u, conn), budget_ms=MARKS_BUDGET_MS)
        _note_degraded(authorization, entity, ver, out["degraded"])
        res = {"entity": entity, "marks": {str(k): v for k, v in out["marks"].items()}, "degraded": bool(out["degraded"])}
        if u.get("role") == "superadmin":                          # 規則 id 與原因只給最高管理者；一般檢視者只知道『部分提醒暫時無法顯示』
            res["degradedRules"] = out["degraded"]
        return res
    finally:
        conn.close()
