# -*- coding: utf-8 -*-
"""案件階段端點（`/api/quotations/{quote_no}/stages…`、`/api/quotations/stage-templates/preview`）——自 `api/quotations.py` 純搬移出來（逐字，零行為變更）。
路由路徑、函式名稱、驗證相依、回應形狀都與搬移前相同。階段表的讀寫 helper（`_serialize_stage`／`_get_stage_row`／`_sync_stages_to_json`／
`_sync_json_stages_to_table`）仍留在 `api/quotations.py`（案件存檔、建立報價單也在用），這裡只 import 它們。"""
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Body, HTTPException, Header

from core.txn import begin_write
from db import get_db, spawn_bg_thread
from helpers import (
    _audit, _require_user, _tok,
    push_event_delete_for_case_stage, push_event_for_case_stage_done, push_event_for_case_stage_due,
)
from helpers.case_access import guard_case_access
from helpers.validation import body_flag
from modules.case.api.quotations import (
    _deny_if_case_locked_unsupported, _get_stage_row, _guard_case, _safe_close, _serialize_stage, _sync_stages_to_json,
)
from modules.case.case_stage_tasks import daily_task_notice, delete_daily_task_for_case_stage, sync_daily_task_for_case_stage
from modules.case.recognition import normalize_ratio_bp

router = APIRouter()


def _would_create_cycle(conn, quote_no: str, stage_id: int, candidate_id: int) -> bool:
    """DFS 防環檢查，邏輯照搬 case-management.js 的 wouldCreateCycle()：若讓 stage_id
    依賴 candidate_id，順著 dependsOn 追下去會不會繞回 stage_id 自己。範圍限定在同一
    quote_no 底下的 case_stages。"""
    if stage_id == candidate_id:
        return True
    rows = conn.execute("SELECT id, depends_on FROM case_stages WHERE quote_no=?", (quote_no,)).fetchall()
    depends_map = {r["id"]: json.loads(r["depends_on"] or "[]") for r in rows}
    seen = set()

    def dfs(cur_id):
        if cur_id == stage_id:
            return True
        if cur_id in seen:
            return False
        seen.add(cur_id)
        return any(dfs(d) for d in depends_map.get(cur_id, []))

    return dfs(candidate_id)


@router.get("/api/quotations/{quote_no}/stages")
def list_case_stages_normalized(quote_no: str, authorization: str = Header(None)):
    """caseRecord.stages 正規化第一階段的驗證端點（2026-08-23）——查 case_stages/
    case_stage_visits。第二階段（CRUD 端點）新增後，這個端點仍然是唯讀查詢，尚未接
    進任何現有頁面/流程；`caseRecord.stages` JSON 欄位仍是唯一的讀寫來源，前端還沒
    有任何頁面呼叫這一系列新端點。"""
    user = _require_user(authorization)
    conn = get_db()
    _guard_case(conn, quote_no, user, allow_module="case_manage")
    stage_rows = conn.execute(
        "SELECT * FROM case_stages WHERE quote_no=? ORDER BY sort_order, id",
        (quote_no,),
    ).fetchall()
    stages = [_serialize_stage(conn, sr) for sr in stage_rows]
    conn.close()
    return {"items": stages}


@router.post("/api/quotations/{quote_no}/stages", status_code=201)
def create_case_stage(quote_no: str, body: dict = Body(...), authorization: str = Header(None)):
    """新增階段，對應 case-management.js::addStage()。第二階段 CRUD 端點，2026-08-23
    Phase 3b/4 起已由 case-management.js／quotation-form.html 實際呼叫（見 2026-09-07
    docstring 更正紀錄，本行原誤留 Phase 2 剛新增時「尚未接進」的舊字樣）。"""
    user = _require_user(authorization)
    conn = get_db()
    _guard_case(conn, quote_no, user, allow_module="case_manage")
    _deny_if_case_locked_unsupported(conn, quote_no, authorization, op="案件階段-新增")
    max_order = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) m FROM case_stages WHERE quote_no=?", (quote_no,)
    ).fetchone()["m"]
    now = datetime.now().isoformat()
    cur = conn.execute("""
        INSERT INTO case_stages
            (quote_no, label, sort_order, done, done_at, start_date, due_date,
             assigned_to, depends_on, created_at, updated_at)
        VALUES (?,?,?,0,'','','','[]','[]',?,?)
    """, (quote_no, body.get("label") or "", max_order + 1, now, now))
    new_id = cur.lastrowid
    conn.commit()
    _sync_stages_to_json(conn, quote_no)
    sr = _get_stage_row(conn, quote_no, new_id)
    result = _serialize_stage(conn, sr)
    conn.close()
    _audit(_tok(authorization), 'case_stage.create', 'case_stage', quote_no, quote_no)
    return result


@router.get("/api/quotations/{quote_no}/stages/templates")
def list_stage_templates(quote_no: str, authorization: str = Header(None)):
    """案件頁「套用階段樣板」的選單：已發布的樣板 `[{key, label, stageCount, hasRatio}]`。旗標關 ⇒ 404；權限同新增階段（case_manage）。"""
    from helpers import stage_templates as _STPL
    from core import definitions as _D
    user = _require_user(authorization)
    if not _STPL.enabled():
        raise HTTPException(404, "Not Found")
    conn = get_db()
    _guard_case(conn, quote_no, user, allow_module="case_manage")
    _STPL.ensure_kind()
    items = []
    for it in _D.list_definitions(conn, _STPL.KIND):
        if it["scope"] != "company" or not it["latestVersion"]:
            continue
        d = _D.get(conn, _STPL.KIND, it["key"], "company")
        b = (d or {}).get("body") or {}
        sts = b.get("stages") if isinstance(b.get("stages"), list) else []
        items.append({"key": it["key"], "label": b.get("label") or it["key"], "stageCount": len(sts),
                      "hasRatio": any(isinstance(x, dict) and x.get("ratioBp") is not None for x in sts)})
    conn.close()
    return {"items": items}


@router.post("/api/quotations/stage-templates/preview")
def preview_stage_template(body: dict = Body(...), authorization: str = Header(None)):
    """階段樣板編輯器的預覽（唯讀、不寫資料）：`{key, template, baseDate?}` ⇒ 以『沒有任何階段的案件』套用時會建立的階段（名稱、日期、比例）。
    僅最高管理者；旗標關 ⇒ 404；樣板不合法 ⇒ 422 `{problems}`。"""
    from helpers import stage_templates as _STPL
    from modules.case import stage_apply as _SA
    _require_user(authorization, require_superadmin=True)
    if not _STPL.enabled():
        raise HTTPException(404, "Not Found")
    tpl = body.get("template")
    probs = _STPL.definition_problems(body.get("key"), tpl)
    if probs:
        raise HTTPException(422, {"problems": probs})
    try:
        return _SA.plan(tpl, body.get("baseDate") or datetime.now().date().isoformat(), "new", [])
    except _SA.PlanError as e:
        raise HTTPException(400, str(e))


@router.post("/api/quotations/{quote_no}/stages/apply-template")
def apply_stage_template(quote_no: str, body: dict = Body(...), authorization: str = Header(None)):
    """套用案件階段樣板（S-ST2；設計 docs/platform/plans/CASE-STAGE-TEMPLATE-INVESTIGATION-T62.md）。
    body：`{template, baseDate?(YYYY-MM-DD，預設今天), mode: 'new'|'append', dryRun?}`。
    - 旗標 `builder_stage_templates`（且建構器治理）關著 ⇒ 404，和今天完全一樣；權限與已結案鎖定同 `create_case_stage`（case_manage）。
    - 套用＝複製成這個案件自己的階段（凍結）；`dryRun` ⇒ 只回傳會建立什麼（名稱、日期、比例、說明），不寫入。
    - 建議比例只在案件原本沒有階段時帶入；附加模式一律不帶（回應 notes 會說明）。已存在的階段不改、不刪。"""
    from helpers import stage_templates as _STPL
    from modules.case import stage_apply as _SA
    user = _require_user(authorization)
    if not _STPL.enabled():
        raise HTTPException(404, "Not Found")
    conn = get_db()
    guard_case_access(conn, quote_no, user, allow_module="case_manage")      # 與 _guard_case 同一份判定；直接走範圍 helper（未經範圍讀取棘輪認得它）
    _deny_if_case_locked_unsupported(conn, quote_no, authorization, op="案件階段-套用樣板")
    key = body.get("template")
    mode = body.get("mode") or "new"
    base = body.get("baseDate") or datetime.now().date().isoformat()
    # S1：dryRun 只認布林；其他型別（'true'、1、'1'…）一律 400，不會把「看起來像預覽」的請求當成真的寫入
    dry = body.get("dryRun")
    if dry is not None and not isinstance(dry, bool):
        conn.close(); raise HTTPException(400, "dryRun 必須是 true 或 false")
    if not dry:
        # S2：會寫入 ⇒ 讀「現有階段」之前先拿寫鎖；兩個同時套用的請求不會都看到 0 個階段而各建一組（比例合計變 200%）
        begin_write(conn)
    _STPL.ensure_kind()
    from core import definitions as _D
    try:
        d = _D.get(conn, _STPL.KIND, key, "company") if isinstance(key, str) else None
    except _D.DefinitionError:
        d = None
    if not d:
        conn.close(); raise HTTPException(404, "找不到這個階段樣板，或它尚未發布")
    _rows = conn.execute("SELECT id, stage_key, label, sort_order FROM case_stages WHERE quote_no=?", (quote_no,)).fetchall()
    existing = [{"id": r["id"], "stage_key": r["stage_key"], "label": r["label"]} for r in _rows]
    max_order = max([r["sort_order"] for r in _rows if r["sort_order"] is not None] or [-1])      # 寫入端用；同一次（已持寫鎖）讀取，不再另讀
    try:
        pl = _SA.plan(d["body"], base, mode, existing)
    except _SA.PlanError as e:
        conn.close(); raise HTTPException(e.status, str(e))
    # S3：到期提醒是既有行為（case_deadlines：已成案、階段未完成、迄日是今天或 3 天後 ⇒ 通知負責人；沒有負責人 ⇒ 業務與部門主管）。
    # 新階段沒有負責人，所以套用前先講清楚會通知誰
    _soon = {datetime.now().date().isoformat(), (datetime.now().date() + timedelta(days=3)).isoformat()}
    _n_soon = sum(1 for x in pl["stages"] if x["dueDate"] in _soon)
    if _n_soon:
        pl["notes"] = list(pl["notes"]) + ["其中 %d 個階段的結束日是今天或 3 天後。這些階段尚無負責人，案件已成案時，系統會依原有的到期提醒規則通知業務與部門主管" % _n_soon]
    out = {"template": key, "templateVersion": d.get("version"), "baseDate": base, "mode": mode, **pl}
    if dry:
        conn.close()
        return out
    if not pl["stages"]:
        conn.close()
        return {**out, "created": []}
    try:
        return _apply_stage_template_write(conn, quote_no, pl, out, key, d, mode, authorization, max_order)
    except BaseException:
        try:
            conn.rollback()
        except Exception:   # noqa: BLE001
            pass
        _safe_close(conn)
        raise


def _apply_stage_template_write(conn, quote_no, pl, out, key, d, mode, authorization, max_order):
    now = datetime.now().isoformat()
    ids = {}
    for i, st in enumerate(pl["stages"]):
        cur = conn.execute("""
            INSERT INTO case_stages
                (quote_no, label, sort_order, done, done_at, start_date, due_date,
                 assigned_to, depends_on, created_at, updated_at, stage_key, ratio_bp)
            VALUES (?,?,?,0,'',?,?,'[]','[]',?,?,?,?)
        """, (quote_no, st["label"], max_order + 1 + i, st["startDate"], st["dueDate"], now, now, st["key"], st["ratioBp"]))
        ids[st["key"]] = cur.lastrowid
    for st in pl["stages"]:
        deps = list(st["existingDeps"]) + [ids[k] for k in st["dependsOn"] if k in ids]
        if deps:
            conn.execute("UPDATE case_stages SET depends_on=? WHERE id=?", (json.dumps(deps, ensure_ascii=False), ids[st["key"]]))
    conn.commit()
    _sync_stages_to_json(conn, quote_no)           # 同時把案件的 updated_at 往前推（鏡像寫回會更新它）
    created = [_serialize_stage(conn, _get_stage_row(conn, quote_no, i)) for i in ids.values()]
    conn.close()
    for i in ids.values():
        spawn_bg_thread(push_event_for_case_stage_due, args=(i,))      # 和手動填迄日一樣：推行事曆（失敗只記 log）
    _audit(_tok(authorization), 'case_stage.apply_template', 'case_stage', quote_no, quote_no,
           {'template': key, 'version': d.get("version"), 'mode': mode, 'count': len(ids)})
    return {**out, "created": created}


@router.put("/api/quotations/{quote_no}/stages/{stage_id}")
def update_case_stage(quote_no: str, stage_id: int, body: dict = Body(...), authorization: str = Header(None)):
    """局部更新階段欄位（label/done/doneAt/startDate/dueDate），對應 case-management.html
    的 x-model 直接綁定欄位＋renderGantt() 的 on_date_change。不加任何自動邏輯（例如
    done=true 不自動填 doneAt）——維持跟現有前端行為一致，各欄位互相獨立。第二階段
    CRUD 端點，已由前端實際呼叫（見 create_case_stage() docstring）。"""
    user = _require_user(authorization)
    conn = get_db()
    _guard_case(conn, quote_no, user, allow_module="case_manage")
    _deny_if_case_locked_unsupported(conn, quote_no, authorization, op="案件階段-編輯")
    sr = _get_stage_row(conn, quote_no, stage_id)
    if not sr:
        conn.close(); raise HTTPException(404, "階段不存在")
    updates = {}
    if "label" in body:     updates["label"]      = body.get("label") or ""
    if "done" in body:      updates["done"]       = 1 if body_flag(body, "done") else 0
    if "doneAt" in body:    updates["done_at"]    = body.get("doneAt") or ""
    if "startDate" in body: updates["start_date"] = body.get("startDate") or ""
    if "dueDate" in body:   updates["due_date"]   = body.get("dueDate") or ""
    if "ratioBp" in body:   updates["ratio_bp"]   = normalize_ratio_bp(body.get("ratioBp"))
    was_done = bool(sr["done"])
    had_task = bool(sr["daily_task_id"]) if "daily_task_id" in sr.keys() else False
    if updates:
        updates["updated_at"] = datetime.now().isoformat()
        sql = "UPDATE case_stages SET " + ", ".join(f"{k}=?" for k in updates) + " WHERE id=?"
        conn.execute(sql, list(updates.values()) + [stage_id])
        conn.commit()
        _sync_stages_to_json(conn, quote_no)
        if "due_date" in updates:
            spawn_bg_thread(push_event_for_case_stage_due, args=(stage_id,))
        # 勾選/取消勾選完成 → 兩張行事曆都要同步（2026-09-11 交辦第 3 項）。
        # `done_at` 單獨被改（已勾選的情況下改完成日期）也要重推，否則行事曆上
        # 留的是舊日期。兩支都是 fire-and-forget，失敗只記 log，不擋勾選本身。
        done_changed = ("done" in updates and bool(updates["done"]) != was_done)
        if done_changed or ("done_at" in updates and bool(updates.get("done", was_done))):
            actor_name = user.get("display_name") or user["username"]
            spawn_bg_thread(push_event_for_case_stage_done, args=(stage_id,))
            spawn_bg_thread(sync_daily_task_for_case_stage,
                            args=(stage_id, user["username"], actor_name))
            # IP-5：每日任務模組（M12）不在 ⇒ 勾選照常存檔，但要明說沒有建立／沒有收回每日任務
            _dt_notice = daily_task_notice(done=bool(updates.get("done", was_done)), had_task=had_task)
        else:
            _dt_notice = None
    else:
        _dt_notice = None
    sr = _get_stage_row(conn, quote_no, stage_id)
    result = _serialize_stage(conn, sr)
    if _dt_notice:
        result["notice"] = _dt_notice
    conn.close()
    _audit(_tok(authorization), 'case_stage.update', 'case_stage', quote_no, quote_no, {'stageId': stage_id})
    return result


@router.delete("/api/quotations/{quote_no}/stages/{stage_id}")
def delete_case_stage(quote_no: str, stage_id: int, authorization: str = Header(None)):
    """刪除階段，同時清掉同案件其他階段 dependsOn 裡對它的參照，對應
    case-management.js::removeStage()。第二階段 CRUD 端點，已由前端實際呼叫
    （見 create_case_stage() docstring）。"""
    user = _require_user(authorization)
    conn = get_db()
    _guard_case(conn, quote_no, user, allow_module="case_manage")
    _deny_if_case_locked_unsupported(conn, quote_no, authorization, op="案件階段-刪除")
    sr = _get_stage_row(conn, quote_no, stage_id)
    if not sr:
        conn.close(); raise HTTPException(404, "階段不存在")
    calendar_event_id = sr["google_calendar_event_id"] or ""
    # 完成日事件與月曆鏡射也要一起收掉，否則階段刪了行事曆上還留著（DB v76）
    done_event_id = (sr["google_calendar_done_event_id"] or "") if "google_calendar_done_event_id" in sr.keys() else ""
    stage_task_id = (sr["daily_task_id"] or 0) if "daily_task_id" in sr.keys() else 0
    conn.execute("DELETE FROM case_stages WHERE id=?", (stage_id,))
    siblings = conn.execute("SELECT id, depends_on FROM case_stages WHERE quote_no=?", (quote_no,)).fetchall()
    for s in siblings:
        depends = json.loads(s["depends_on"] or "[]")
        if stage_id in depends:
            depends = [d for d in depends if d != stage_id]
            conn.execute("UPDATE case_stages SET depends_on=? WHERE id=?",
                         (json.dumps(depends, ensure_ascii=False), s["id"]))
    conn.commit()
    _sync_stages_to_json(conn, quote_no)
    conn.close()
    if calendar_event_id:
        spawn_bg_thread(push_event_delete_for_case_stage, args=(calendar_event_id,))
    if done_event_id:
        spawn_bg_thread(push_event_delete_for_case_stage, args=(done_event_id,))
    if stage_task_id:
        spawn_bg_thread(delete_daily_task_for_case_stage, args=(stage_task_id,))
    _audit(_tok(authorization), 'case_stage.delete', 'case_stage', quote_no, quote_no, {'stageId': stage_id})
    out = {"ok": True}
    _dt_notice = daily_task_notice(done=False, had_task=bool(stage_task_id))   # IP-5：M12 不在 ⇒ 明說沒有收回
    if _dt_notice:
        out["notice"] = _dt_notice
    return out


@router.patch("/api/quotations/{quote_no}/stages/reorder")
def reorder_case_stages(quote_no: str, body: dict = Body(...), authorization: str = Header(None)):
    """依 orderedIds 陣列順序重寫 sort_order，對應拖曳重排（dragOver/dragEnd）的最終
    結果。第二階段 CRUD 端點，已由前端實際呼叫（見 create_case_stage() docstring）。"""
    user = _require_user(authorization)
    ordered_ids = body.get("orderedIds") or []
    conn = get_db()
    _guard_case(conn, quote_no, user, allow_module="case_manage")
    _deny_if_case_locked_unsupported(conn, quote_no, authorization, op="案件階段-排序")
    valid_ids = {r["id"] for r in conn.execute(
        "SELECT id FROM case_stages WHERE quote_no=?", (quote_no,)
    ).fetchall()}
    now = datetime.now().isoformat()
    for idx, sid in enumerate(ordered_ids):
        if sid in valid_ids:
            conn.execute("UPDATE case_stages SET sort_order=?, updated_at=? WHERE id=? AND quote_no=?",
                         (idx, now, sid, quote_no))
    conn.commit()
    _sync_stages_to_json(conn, quote_no)
    conn.close()
    _audit(_tok(authorization), 'case_stage.reorder', 'case_stage', quote_no, quote_no)
    return {"ok": True}


@router.post("/api/quotations/{quote_no}/stages/{stage_id}/assignees")
def add_stage_assignee(quote_no: str, stage_id: int, body: dict = Body(...), authorization: str = Header(None)):
    """加入負責人，對應 case-management.js::addStageAssignee()。第二階段 CRUD 端點，
    已由前端實際呼叫（見 create_case_stage() docstring）。"""
    user = _require_user(authorization)
    username = body.get("username")
    if not username:
        raise HTTPException(400, "請提供 username")
    conn = get_db()
    _guard_case(conn, quote_no, user, allow_module="case_manage")
    _deny_if_case_locked_unsupported(conn, quote_no, authorization, op="案件階段-加入負責人")
    sr = _get_stage_row(conn, quote_no, stage_id)
    if not sr:
        conn.close(); raise HTTPException(404, "階段不存在")
    assigned = json.loads(sr["assigned_to"] or "[]")
    if username not in assigned:
        assigned.append(username)
        conn.execute("UPDATE case_stages SET assigned_to=?, updated_at=? WHERE id=?",
                     (json.dumps(assigned, ensure_ascii=False), datetime.now().isoformat(), stage_id))
        conn.commit()
        _sync_stages_to_json(conn, quote_no)
    sr = _get_stage_row(conn, quote_no, stage_id)
    result = _serialize_stage(conn, sr)
    conn.close()
    _audit(_tok(authorization), 'case_stage.assignee_add', 'case_stage', quote_no, quote_no, {'stageId': stage_id, 'username': username})
    return result


@router.delete("/api/quotations/{quote_no}/stages/{stage_id}/assignees/{username}")
def remove_stage_assignee(quote_no: str, stage_id: int, username: str, authorization: str = Header(None)):
    """移除負責人，對應 case-management.js::removeStageAssignee()。第二階段 CRUD 端
    點，已由前端實際呼叫（見 create_case_stage() docstring）。"""
    user = _require_user(authorization)
    conn = get_db()
    _guard_case(conn, quote_no, user, allow_module="case_manage")
    _deny_if_case_locked_unsupported(conn, quote_no, authorization, op="案件階段-移除負責人")
    sr = _get_stage_row(conn, quote_no, stage_id)
    if not sr:
        conn.close(); raise HTTPException(404, "階段不存在")
    assigned = [u for u in json.loads(sr["assigned_to"] or "[]") if u != username]
    conn.execute("UPDATE case_stages SET assigned_to=?, updated_at=? WHERE id=?",
                 (json.dumps(assigned, ensure_ascii=False), datetime.now().isoformat(), stage_id))
    conn.commit()
    _sync_stages_to_json(conn, quote_no)
    sr = _get_stage_row(conn, quote_no, stage_id)
    result = _serialize_stage(conn, sr)
    conn.close()
    _audit(_tok(authorization), 'case_stage.assignee_remove', 'case_stage', quote_no, quote_no, {'stageId': stage_id, 'username': username})
    return result


@router.post("/api/quotations/{quote_no}/stages/{stage_id}/depends-on/{candidate_id}")
def toggle_stage_dependency(quote_no: str, stage_id: int, candidate_id: int, authorization: str = Header(None)):
    """切換依賴關係：已存在就移除，不存在就先做防環檢查（DFS，邏輯照搬
    wouldCreateCycle()）再加入。對應 case-management.js::toggleStageDependency()。
    第二階段 CRUD 端點，已由前端實際呼叫（見 create_case_stage() docstring）。"""
    user = _require_user(authorization)
    conn = get_db()
    _guard_case(conn, quote_no, user, allow_module="case_manage")
    _deny_if_case_locked_unsupported(conn, quote_no, authorization, op="案件階段-前置階段")
    sr = _get_stage_row(conn, quote_no, stage_id)
    if not sr:
        conn.close(); raise HTTPException(404, "階段不存在")
    if not _get_stage_row(conn, quote_no, candidate_id):
        conn.close(); raise HTTPException(404, "前置階段不存在")
    depends = json.loads(sr["depends_on"] or "[]")
    if candidate_id in depends:
        depends = [d for d in depends if d != candidate_id]
    else:
        if _would_create_cycle(conn, quote_no, stage_id, candidate_id):
            conn.close()
            raise HTTPException(400, "這樣設定會讓階段之間互相循環依賴，請重新選擇前置階段")
        depends.append(candidate_id)
    conn.execute("UPDATE case_stages SET depends_on=?, updated_at=? WHERE id=?",
                 (json.dumps(depends, ensure_ascii=False), datetime.now().isoformat(), stage_id))
    conn.commit()
    _sync_stages_to_json(conn, quote_no)
    sr = _get_stage_row(conn, quote_no, stage_id)
    result = _serialize_stage(conn, sr)
    conn.close()
    _audit(_tok(authorization), 'case_stage.dependency_toggle', 'case_stage', quote_no, quote_no, {'stageId': stage_id, 'candidateId': candidate_id})
    return result


@router.post("/api/quotations/{quote_no}/stages/{stage_id}/visits", status_code=201)
def add_stage_visit(quote_no: str, stage_id: int, body: dict = Body(...), authorization: str = Header(None)):
    """新增拜訪紀錄，對應 case-management.js::addVisit()。第二階段 CRUD 端點，
    已由前端實際呼叫（見 create_case_stage() docstring）。"""
    user = _require_user(authorization)
    conn = get_db()
    _guard_case(conn, quote_no, user, allow_module="case_manage")
    _deny_if_case_locked_unsupported(conn, quote_no, authorization, op="拜訪紀錄-新增")
    sr = _get_stage_row(conn, quote_no, stage_id)
    if not sr:
        conn.close(); raise HTTPException(404, "階段不存在")
    now = datetime.now().isoformat()
    conn.execute("""
        INSERT INTO case_stage_visits (stage_id, visit_date, visit_people, note, created_at)
        VALUES (?,?,?,?,?)
    """, (stage_id, body.get("visitDate") or "", int(body.get("visitPeople") or 0), body.get("note") or "", now))
    conn.execute("UPDATE case_stages SET updated_at=? WHERE id=?", (now, stage_id))
    conn.commit()
    _sync_stages_to_json(conn, quote_no)
    sr = _get_stage_row(conn, quote_no, stage_id)
    result = _serialize_stage(conn, sr)
    conn.close()
    _audit(_tok(authorization), 'case_stage.visit_create', 'case_stage', quote_no, quote_no, {'stageId': stage_id})
    return result


@router.put("/api/quotations/{quote_no}/stages/{stage_id}/visits/{visit_id}")
def update_stage_visit(quote_no: str, stage_id: int, visit_id: int, body: dict = Body(...), authorization: str = Header(None)):
    """局部更新拜訪紀錄欄位，對應 v.visitDate/v.visitPeople/v.note 的 x-model 綁定。
    第二階段 CRUD 端點，已由前端實際呼叫（見 create_case_stage() docstring）。"""
    user = _require_user(authorization)
    conn = get_db()
    _guard_case(conn, quote_no, user, allow_module="case_manage")
    _deny_if_case_locked_unsupported(conn, quote_no, authorization, op="拜訪紀錄-編輯")
    sr = _get_stage_row(conn, quote_no, stage_id)
    if not sr:
        conn.close(); raise HTTPException(404, "階段不存在")
    vr = conn.execute("SELECT id FROM case_stage_visits WHERE id=? AND stage_id=?", (visit_id, stage_id)).fetchone()
    if not vr:
        conn.close(); raise HTTPException(404, "拜訪紀錄不存在")
    fields = {}
    if "visitDate" in body:   fields["visit_date"]   = body.get("visitDate") or ""
    if "visitPeople" in body: fields["visit_people"] = int(body.get("visitPeople") or 0)
    if "note" in body:        fields["note"]         = body.get("note") or ""
    if fields:
        sql = "UPDATE case_stage_visits SET " + ", ".join(f"{k}=?" for k in fields) + " WHERE id=?"
        conn.execute(sql, list(fields.values()) + [visit_id])
        conn.execute("UPDATE case_stages SET updated_at=? WHERE id=?", (datetime.now().isoformat(), stage_id))
        conn.commit()
        _sync_stages_to_json(conn, quote_no)
    sr = _get_stage_row(conn, quote_no, stage_id)
    result = _serialize_stage(conn, sr)
    conn.close()
    _audit(_tok(authorization), 'case_stage.visit_update', 'case_stage', quote_no, quote_no, {'stageId': stage_id, 'visitId': visit_id})
    return result


@router.delete("/api/quotations/{quote_no}/stages/{stage_id}/visits/{visit_id}")
def delete_stage_visit(quote_no: str, stage_id: int, visit_id: int, authorization: str = Header(None)):
    """刪除拜訪紀錄，對應 case-management.js::removeVisit()。第二階段 CRUD 端點，
    已由前端實際呼叫（見 create_case_stage() docstring）。"""
    user = _require_user(authorization)
    conn = get_db()
    _guard_case(conn, quote_no, user, allow_module="case_manage")
    _deny_if_case_locked_unsupported(conn, quote_no, authorization, op="拜訪紀錄-刪除")
    sr = _get_stage_row(conn, quote_no, stage_id)
    if not sr:
        conn.close(); raise HTTPException(404, "階段不存在")
    vr = conn.execute("SELECT id FROM case_stage_visits WHERE id=? AND stage_id=?", (visit_id, stage_id)).fetchone()
    if not vr:
        conn.close(); raise HTTPException(404, "拜訪紀錄不存在")
    conn.execute("DELETE FROM case_stage_visits WHERE id=?", (visit_id,))
    conn.execute("UPDATE case_stages SET updated_at=? WHERE id=?", (datetime.now().isoformat(), stage_id))
    conn.commit()
    _sync_stages_to_json(conn, quote_no)
    conn.close()
    _audit(_tok(authorization), 'case_stage.visit_delete', 'case_stage', quote_no, quote_no, {'stageId': stage_id, 'visitId': visit_id})
    return {"ok": True}
