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


def _needed(*rule_lists):
    """這些規則實際用到的欄位代號（含標示到欄位的目標）；給資料來源省掉用不到的欄位。"""
    out = set()
    for rules in rule_lists:
        for r in rules or []:
            if isinstance(r, dict):
                out |= G.fields_used(r.get("when"))
                mk = r.get("mark") or {}
                if mk.get("target") == "field" and mk.get("field"):
                    out.add(mk["field"])
    return out


def _load(entity, user, conn, ids=None, limit=200, fields=None):
    """⇒ (紀錄清單｜None，是否失敗)。資料來源丟任何例外（壞資料、過深的 JSON…）都不可讓請求 500：呼叫端依用途降級。"""
    try:
        return C.load_records(entity, user, conn, ids=ids, limit=limit, fields=fields), False
    except Exception:                                              # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("rules: 資料來源 %s 載入失敗，降級", entity, exc_info=True)
        return None, True


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
                "modes": ["mark"], "onFailure": ["degrade_loud"], "k01Seed": RS.k01_seed_on(conn)}
    finally:
        conn.close()


def _has_source(entity):
    from core import registry
    return entity in registry.providers("rules.entity")


@router.post("/api/rules/k01/seed")
def rules_k01_seed(authorization: str = Header(None)):
    """把目前的專案毛利提醒門檻轉成種子規則，**只寫成草稿**（不發布）。發布走規則頁的正常流程（預覽、治理；調低門檻屬放寬）。
    旗標 builder_rules.k01_seed 關 ⇒ 404；規則已存在（草稿或已發布）⇒ 409；不改任何現有規則。"""
    u = _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        _flag_gate(conn)
        if not RS.k01_seed_on(conn):
            raise HTTPException(404, "Not Found")
        draft = D.get(conn, RS.KIND, RS.K01_ENTITY, "company", 0)
        base = ((draft or D.get(conn, RS.KIND, RS.K01_ENTITY, "company")) or {}).get("body") or {}
        rules = [r for r in (base.get("rules") or []) if isinstance(r, dict)]
        if any(r.get("id") == RS.K01_ID for r in rules):
            raise HTTPException(409, "這條規則已經存在（草稿或已發布），沒有重複匯入")
        from helpers import settings_registry as SR
        rules.append(RS.k01_seed_rule(SR.get("project_margin", "warn_pct", conn=conn)))
        try:
            d = D.save_draft(conn, RS.KIND, RS.K01_ENTITY, "company", {"rules": rules}, user=u["username"])
        except D.DefinitionError as e:
            raise HTTPException(422, {"problems": getattr(e, "problems", None) or [{"message": str(e)}]})
        _audit(_tok(authorization), "rules.k01_seeded", "rule_set", RS.K01_ENTITY, "把專案毛利提醒門檻匯入為規則草稿（尚未發布）", {"ruleId": RS.K01_ID})
        return {"entity": RS.K01_ENTITY, "etag": d.get("etag", ""), "ruleId": RS.K01_ID,
                "message": "已匯入為草稿：請在規則頁預覽並發布；發布之前報價單的提醒門檻不變。"}
    finally:
        conn.close()


@router.get("/api/rules/summary")
def rules_summary(entity: str = Query(...), authorization: str = Header(None)):
    u = _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        _flag_gate(conn)
        _entity(entity)
        body, ver = _live(conn, entity)
        rules = body.get("rules") if isinstance(body.get("rules"), list) else []
        rows, failed = _load(entity, u, conn, limit=SCAN_MAX, fields=_needed(rules))
        base = {"entity": entity, "version": ver, "rules": [{"id": r.get("id"), "name": r.get("name"), "enabled": r.get("enabled", True),
                                                             "level": (r.get("mark") or {}).get("level")} for r in rules if isinstance(r, dict)]}
        if rows is None:
            return dict(base, available=False, sampled=0, hits={},
                        message="資料來源暫時讀取失敗，無法計算命中數" if failed else "這個主題還沒有接上資料來源，無法計算命中數")
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
        live_body, ver = _live(conn, entity)
        rows, failed = _load(entity, u, conn, limit=limit, fields=_needed(live_body.get("rules"), body.get("rules")))
        from routers import def_pipeline as P
        direction, reasons = P.classify(RS.KIND, live_body, body)
        if rows is None:
            return {"entity": entity, "available": False, "direction": direction, "reasons": reasons,
                    "message": "資料來源暫時讀取失敗，無法預覽命中的紀錄" if failed else "這個主題還沒有接上資料來源，無法預覽命中的紀錄"}
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
def rules_marks(entity: str = Query(...), ids: str = Query(""), surface: str = Query("list"), authorization: str = Header(None)):
    u = _require_user(authorization)
    conn = get_db()
    try:
        _flag_gate(conn)
        _entity(entity)
        if surface not in G.SURFACES:
            raise HTTPException(400, "surface 只能是：%s" % "、".join(G.SURFACES))
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
        rows, _failed = _load(entity, u, conn, ids=want, limit=len(want), fields=_needed(rules))
        if not rows:
            return empty
        out = E.evaluate(rules, rows, C.visible_ids(entity, u, conn), budget_ms=MARKS_BUDGET_MS, surface=surface)
        _note_degraded(authorization, entity, ver, out["degraded"])
        res = {"entity": entity, "marks": {str(k): v for k, v in out["marks"].items()}, "degraded": bool(out["degraded"])}
        if u.get("role") == "superadmin":                          # 規則 id 與原因只給最高管理者；一般檢視者只知道『部分提醒暫時無法顯示』
            res["degradedRules"] = out["degraded"]
        return res
    finally:
        conn.close()
