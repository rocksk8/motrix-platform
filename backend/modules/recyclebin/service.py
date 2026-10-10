# -*- coding: utf-8 -*-
"""刪除暫存區的核心動作：進暫存區（delete）、還原（restore）、永久清除（purge）、列表／詳情／狀態、每日工作（run_daily）。

單據怎麼進出由擁有模組的 adapter 決定（helpers/recycle_bin.Adapter）；這裡只做『通用』的事：快照存檔、附件搬移、狀態機、稽核與通知。
交易約定：
- `delete()` 在**呼叫端的寫入交易內**執行，不 commit（附件先搬、再寫列、再刪資料列；任一步失敗就搬回並丟例外）。
  呼叫端之後若回滾 ⇒ 暫存區沒有那一列、附件卻在隔離區 ⇒ 每日工作 `reconcile()` 搬回原路徑。
- `restore()`／`purge()` 自己 commit（它們由 API 呼叫，連線是 API 的）。
"""
import json
import logging
import uuid
from datetime import datetime, timedelta

from core.txn import begin_write
from helpers import recycle_bin as RB
from modules.recyclebin import quarantine as Q

logger = logging.getLogger(__name__)

S_IN_BIN, S_RESTORED, S_PURGED, S_FAILED = "in_bin", "restored", "purged", "restore_failed"
LIVE = (S_IN_BIN, S_FAILED)
DISK_WARN_BYTES = 5 * 1024 ** 3          # 隔離區超過 5 GB ⇒ 告警（不自動提前清除：保存承諾優先）
DAILY_BATCH = 200                        # 每次最多清幾筆
VIA_NORMAL, VIA_APPROVED = "normal", "approved"


def _now():
    return datetime.now()


def purge_after_for(dt) -> str:
    return (dt + timedelta(days=RB.RETENTION_DAYS)).isoformat(timespec="seconds")      # 精確 30 天（含時間）；舊列只有日期，字串比較時仍以當天 00:00 視為到期


def _files_of(snap: dict) -> list:
    out, seen = [], set()
    for f in (snap or {}).get("files") or []:
        if isinstance(f, str):
            f = {"root": Q.ROOT_UPLOADS, "rel": f}
        if not isinstance(f, dict):
            continue
        key = (str(f.get("root") or Q.ROOT_UPLOADS), str(f.get("rel") or ""))
        if key[1] and key not in seen:
            seen.add(key)
            out.append({"root": key[0], "rel": key[1]})
    return out


def _codes_text(snap: dict) -> str:
    """快照 `meta.codes`（字串清單）⇒ 換行分隔的文字，存進 `recycle_bin.codes`（單號產生器查詢用；不含換行的字串才收）。"""
    codes = ((snap or {}).get("meta") or {}).get("codes")
    if not isinstance(codes, (list, tuple)):
        return ""
    return "\n".join(sorted({str(c).strip() for c in codes if c not in (None, "") and "\n" not in str(c)}))


def _bin_one(conn, ad, entity_type, entity_id, user, reason, via, group_token, parent, impact):
    snap = ad.snapshot(conn, entity_id)
    if not isinstance(snap, dict) or not isinstance(snap.get("rows"), dict):
        raise RB.BinError("adapter %s 的快照格式不對（需要 {'rows': {...}}）" % entity_type)
    payload = json.dumps(snap, ensure_ascii=False, default=str)
    cap = RB.MAX_SNAPSHOT_BYTES_ADMIN if (user or {}).get("role") in ("admin", "superadmin") else RB.MAX_SNAPSHOT_BYTES
    if len(payload.encode("utf-8")) > cap:
        more = "" if cap == RB.MAX_SNAPSHOT_BYTES_ADMIN else "（管理員可刪除到 %d MB）" % (RB.MAX_SNAPSHOT_BYTES_ADMIN // (1024 * 1024))
        raise RB.BinError("too_large: 這張單據的資料太大，無法進暫存區（上限 %d MB）%s" % (cap // (1024 * 1024), more))
    token = uuid.uuid4().hex
    try:
        manifest = Q.move_in(token, _files_of(snap))
    except OSError as e:
        raise RB.BinError("附件搬進暫存區失敗，單據未刪除：%s" % e)
    now = _now()
    try:
        cur = conn.execute(
            "INSERT INTO recycle_bin (token, group_token, entity_type, entity_id, entity_label, parent_type, parent_id, deleted_by, deleted_by_display,"
            " deleted_at, purge_after, reason, via, impact_json, snapshot_json, files_manifest_json, bytes, file_count, restore_status, codes)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (token, group_token, entity_type, str(entity_id), str(snap.get("label") or entity_id), parent[0] if parent else "", str(parent[1]) if parent else "",
             (user or {}).get("username", ""), (user or {}).get("display_name", ""), now.isoformat(), purge_after_for(now), (reason or "")[:500], via,
             json.dumps(impact or [], ensure_ascii=False), payload, json.dumps(manifest, ensure_ascii=False),
             sum(int(m.get("size") or 0) for m in manifest), sum(1 for m in manifest if m.get("state") == "moved"), S_IN_BIN, _codes_text(snap)))
        ad.delete_in_tx(conn, entity_id)
    except Exception:
        _mapping, back_fails = Q.move_back(token, manifest)
        if back_fails:                      # 搬不回原路徑（防毒鎖檔…）⇒ 資料夾與檔案原封不動留在隔離區，每日工作會再搬；回報給呼叫端，**不可刪掉**
            logger.error("recyclebin: 單據 %s 刪除失敗後附件搬不回去，保留在隔離區 %s：%s", entity_id, token, back_fails)
            raise RB.BinError("單據未刪除，但有 %d 個附件暫時搬不回原路徑（已保留在隔離區 %s，系統會自動再搬回）" % (len(back_fails), token))
        try:
            Q.remove(token)
        except OSError as e:                # 單據沒刪成、附件已全部搬回；只是空的隔離資料夾暫時清不掉 ⇒ 仍以 BinError 回報（不丟裸 OSError），每日工作會清
            logger.warning("recyclebin: 單據 %s 刪除失敗後空的隔離資料夾 %s 清不掉：%s", entity_id, token, e)
            raise RB.BinError("單據未刪除（資料與附件都在原處）；暫存區的暫存資料夾稍後會自動清理")
        raise
    return {"bin_id": cur.lastrowid, "token": token, "entity_type": entity_type, "entity_id": str(entity_id),
            "purge_after": purge_after_for(now), "files": sum(1 for m in manifest if m.get("state") == "moved"),
            "_hook": (ad, entity_id, snap), "_undo": (token, manifest)}


def delete(conn, entity_type, entity_id, user, reason="", approved=False) -> dict:
    """provider `recyclebin.delete`：送進暫存區（含連帶單據與附件）。不 commit。"""
    ad = RB.get_adapter(entity_type)
    if ad is None:
        raise RB.BinError("沒有『%s』的暫存區 adapter（擁有模組未載入？）" % entity_type)
    begin_write(conn)                       # 快照前先拿寫鎖（呼叫端已在交易內 ⇒ 不動作）：快照與刪除之間不會有別的寫入插進來
    if approved:
        if (user or {}).get("role") != "superadmin":
            raise RB.BinError("只有最高管理者可以刪除已核可的單據")
        ok, why = ad.can_delete_approved(conn, entity_id, user)
    else:
        ok, why = ad.can_delete(conn, entity_id, user)
    if not ok:
        raise RB.BinError(why or "此單據目前不可刪除")
    via = VIA_APPROVED if approved else VIA_NORMAL
    impact = ad.impact(conn, entity_id) if approved else []
    group = uuid.uuid4().hex
    children = []
    try:
        for ct, cid in ad.cascade_children(conn, entity_id) or []:   # 子單據先進（外鍵順序）；還原時父層先
            cad = RB.get_adapter(ct)
            if cad is None:
                raise RB.BinError("連帶刪除的『%s』沒有暫存區 adapter，單據未刪除" % ct)
            children.append(_bin_one(conn, cad, ct, cid, user, reason, via, group, (entity_type, entity_id), []))
        info = _bin_one(conn, ad, entity_type, entity_id, user, reason, via, group, None, impact)
    except Exception:
        _undo_moves(children)               # 前面已搬進隔離區的子單據附件要搬回（呼叫端會 rollback，資料列不會留）；失敗的那一筆 _bin_one 已自己處理
        raise
    info["children"] = children
    hooks = [c.pop("_hook") for c in children] + [info.pop("_hook")]
    undo_all = children + [info]
    undos = [x.pop("_undo") for x in undo_all]

    def after_commit():
        """呼叫端在**自己 commit 之後**呼叫：逐個 adapter 的 after_commit('delete', …)；錯誤只記 log。"""
        for h_ad, h_id, h_snap in hooks:
            _run_hook(h_ad, "delete", h_id, h_snap, info)

    def rollback_files():
        """呼叫端在 delete() 回來**之後**、commit 之前失敗要 rollback 時呼叫：把已搬進隔離區的附件全部搬回（資料列由呼叫端 rollback 一併撤銷）。"""
        _undo_moves_raw(undos)
    info["after_commit"] = after_commit
    info["rollback_files"] = rollback_files
    return info


def _undo_moves(infos):
    _undo_moves_raw([i["_undo"] for i in infos if i.get("_undo")])


def _undo_moves_raw(undos):
    """把一組 (token, manifest) 的附件搬回原路徑並清掉空的隔離資料夾；搬不回的留在隔離區（每日 reconcile 會再搬），只記 log。"""
    for token, manifest in reversed(undos):
        try:
            _mapping, back_fails = Q.move_back(token, manifest)
            if back_fails:
                logger.error("recyclebin: 回復時附件搬不回去，保留在隔離區 %s：%s", token, back_fails)
                continue
            Q.remove(token)
        except Exception:                                          # noqa: BLE001 — 回復路徑不可再丟例外蓋掉原本的錯誤
            logger.exception("recyclebin: 回復隔離區 %s 失敗（每日 reconcile 會處理）", token)


def audit_tx(conn, user, action, target_type="", target_id="", label="", detail=None):
    """稽核寫進**同一個交易**（不 commit）：寫不進去就丟例外，讓呼叫端整筆 rollback（不可『做完了才發現沒稽核』）。"""
    from helpers.audit import _derive_fields, _DETAIL_MAX
    d = _derive_fields(action, target_type, target_id, label, detail)
    payload = json.dumps(detail or {}, ensure_ascii=False)
    if len(payload) > _DETAIL_MAX:
        payload = json.dumps({"_truncated": True, "originalLength": len(payload), "preview": payload[:_DETAIL_MAX - 200]}, ensure_ascii=False)
    conn.execute(
        "INSERT INTO audit_log (at,user_id,username,display_name,action,target_type,target_id,target_label,detail,module,case_no,ref_no,result,reason_code,status_code)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'ok','',0)",
        (_now().isoformat(), (user or {}).get("id"), (user or {}).get("username", ""), (user or {}).get("display_name", ""),
         action, target_type, target_id, label, payload, d["module"], d["case_no"], d["ref_no"]))


def _run_hook(ad, event, entity_id, snap, result):
    """commit 之後的後續動作：錯誤只記 log、不往外丟（資料已經 commit）。"""
    try:
        ad.after_commit(event, entity_id, snap, result)
    except Exception:                                          # noqa: BLE001
        logger.exception("recyclebin after_commit(%s) %s %s failed", event, getattr(ad, "entity_type", "?"), entity_id)


def reserved_ids(conn, entity_type="") -> set:
    """provider `recyclebin.reserved`：暫存區保留中的單號（entity_id ＋ 快照 meta.codes）；見 helpers/recycle_bin.reserved_ids。"""
    sql = "SELECT entity_id, codes FROM recycle_bin WHERE restore_status IN (?,?)"            # codes 欄＝進暫存區當下從快照抄出（不讀快照 JSON）
    args = list(LIVE)
    if entity_type:
        sql += " AND entity_type=?"
        args.append(entity_type)
    out = set()
    try:
        rows = conn.execute(sql, args).fetchall()
    except Exception:                                          # noqa: BLE001 — 表還沒建（模組剛啟用、migration 未跑）⇒ 沒有保留號碼
        return out
    for r in rows:
        out.add(str(r[0]))
        out.update(c for c in str(r[1] or "").split("\n") if c)
    return out


def _row(conn, bin_id):
    r = conn.execute("SELECT * FROM recycle_bin WHERE id=?", (bin_id,)).fetchone()
    if r is None:
        raise RB.BinError("not_found: 暫存區沒有這一筆")
    return r


def _summary(r) -> dict:
    today = _now().date()
    try:
        left = (datetime.fromisoformat(r["purge_after"]).date() - today).days
    except ValueError:
        left = None
    return {"id": r["id"], "entityType": r["entity_type"], "entityId": r["entity_id"], "label": r["entity_label"],
            "parentType": r["parent_type"], "parentId": r["parent_id"], "deletedBy": r["deleted_by_display"] or r["deleted_by"],
            "deletedAt": r["deleted_at"], "purgeAfter": r["purge_after"], "daysLeft": left, "reason": r["reason"], "via": r["via"],
            "status": r["restore_status"], "bytes": r["bytes"], "fileCount": r["file_count"], "restoredBy": r["restored_by"],
            "restoredAt": r["restored_at"], "restoreNote": r["restore_note"], "purgedAt": r["purged_at"], "purgedBy": r["purged_by"]}


def list_items(conn, status="in_bin", entity_type="", q="", page=1, size=50) -> dict:
    where, args = [], []
    if status and status != "all":
        where.append("restore_status=?")
        args.append(status)
    if entity_type:
        where.append("entity_type=?")
        args.append(entity_type)
    if q:
        like = "%" + q.replace("%", "").replace("_", "") + "%"
        where.append("(entity_id LIKE ? OR entity_label LIKE ? OR deleted_by LIKE ? OR deleted_by_display LIKE ?)")
        args += [like] * 4
    w = (" WHERE " + " AND ".join(where)) if where else ""
    page, size = max(1, int(page)), max(1, min(200, int(size)))
    total = conn.execute("SELECT COUNT(*) FROM recycle_bin" + w, args).fetchone()[0]
    rows = conn.execute("SELECT id, entity_type, entity_id, entity_label, parent_type, parent_id, deleted_by, deleted_by_display, deleted_at, purge_after,"
                        " reason, via, restore_status, bytes, file_count, restored_by, restored_at, restore_note, purged_at, purged_by"
                        " FROM recycle_bin" + w + " ORDER BY id DESC LIMIT ? OFFSET ?", args + [size, (page - 1) * size]).fetchall()
    types = {}
    for k, ad in RB.adapters().items():
        types[k] = ad.label or k
    return {"items": [_summary(r) for r in rows], "total": total, "page": page, "size": size, "types": types}


def detail(conn, bin_id) -> dict:
    r = _row(conn, bin_id)
    out = _summary(r)
    try:
        snap = json.loads(r["snapshot_json"] or "{}")
    except ValueError:
        snap = {}
    ad = RB.get_adapter(r["entity_type"])
    masked = (ad.mask(snap) if ad is not None else RB.mask_obj(snap)) if snap else {}
    try:
        manifest = json.loads(r["files_manifest_json"] or "[]")
    except ValueError:
        manifest = []
    out.update(snapshot=masked, files=[{"rel": m.get("rel"), "size": m.get("size"), "state": m.get("state")} for m in manifest],
               adapterAvailable=ad is not None, impact=json.loads(r["impact_json"] or "[]"))
    return out


def restore(conn, bin_id, user, audit=None) -> dict:
    """還原一筆。自己 commit。`audit(conn, result)`（可選）在 commit 前、同一交易內呼叫：稽核寫不進去 ⇒ 整筆還原失敗並回到暫存區。失敗 ⇒ 檔案搬回隔離區、資料列留在暫存區、狀態 restore_failed 並記原因；丟 BinError。"""
    begin_write(conn)                       # 寫鎖＋鎖內重讀：連點兩次還原，第二個等第一個做完、重讀到 restored 就被擋下
    r = _row(conn, bin_id)
    if r["restore_status"] not in LIVE:
        conn.rollback()
        raise RB.BinError("這一筆不在暫存區（狀態：%s）" % r["restore_status"])
    ad = RB.get_adapter(r["entity_type"])
    if ad is None:
        conn.rollback()
        raise RB.BinError("adapter_missing: 『%s』的擁有模組未載入，無法還原" % r["entity_type"])
    if r["group_token"] and r["parent_type"]:                      # 子單據：父層還在暫存區 ⇒ 先還原父層
        p = conn.execute("SELECT id, entity_label FROM recycle_bin WHERE group_token=? AND entity_type=? AND entity_id=? AND restore_status IN (?,?)",
                         (r["group_token"], r["parent_type"], r["parent_id"], S_IN_BIN, S_FAILED)).fetchone()
        if p is not None:
            conn.rollback()
            raise RB.BinError("parent_in_bin: 請先還原上層單據『%s』（暫存區 #%d）" % (p["entity_label"], p["id"]))
    snap = json.loads(r["snapshot_json"] or "{}")
    manifest = json.loads(r["files_manifest_json"] or "[]")
    mapping, fails = Q.move_back(r["token"], manifest)
    if fails:
        Q.stash_again(r["token"], mapping)
        conn.rollback()
        _fail(conn, bin_id, "附件搬回失敗：" + "；".join("%s（%s）" % (f["rel"], f["why"]) for f in fails[:5]))
        raise RB.BinError("附件搬回失敗，已保留在暫存區：" + "；".join(f["rel"] for f in fails[:5]))
    ctx = RB.RestoreContext(files=mapping, user=user)
    now = _now().isoformat()
    try:
        res = ad.restore_in_tx(conn, snap, ctx) or {}
        cur = conn.execute("UPDATE recycle_bin SET restore_status=?, restored_by=?, restored_at=?, restore_note=? WHERE id=? AND restore_status IN (?,?)",
                           (S_RESTORED, (user or {}).get("username", ""), now, "；".join(res.get("notes") or [])[:500], bin_id, S_IN_BIN, S_FAILED))
        if cur.rowcount != 1:
            raise RB.BinError("這一筆的狀態剛被改變，請重新整理後再試")
        if audit is not None:
            audit(conn, {"entityType": r["entity_type"], "entityId": r["entity_id"], "label": r["entity_label"], "renumbered": bool(res.get("renumbered")),
                         "notes": res.get("notes") or []})
        conn.commit()
    except Exception as e:                                         # noqa: BLE001 — 任何失敗都要還原到『還在暫存區』
        conn.rollback()
        Q.stash_again(r["token"], mapping)
        msg = str(e) if isinstance(e, RB.BinError) else "還原時發生錯誤：%s" % e.__class__.__name__
        if not isinstance(e, RB.BinError):
            logger.exception("recyclebin restore #%s failed", bin_id)
        _fail(conn, bin_id, msg)
        raise RB.BinError(msg)
    out = _summary(_row(conn, bin_id))
    out.update(restoredEntityId=res.get("entity_id"), renumbered=bool(res.get("renumbered")), notes=res.get("notes") or [])
    _run_hook(ad, "restore", res.get("entity_id") or r["entity_id"], snap, out)      # commit 之後
    return out


def _fail(conn, bin_id, note):
    """記『還原失敗』——只改還在暫存區的列（條件式）：不會把已還原／已清除的列翻成失敗（連點兩次還原的第二次）。"""
    conn.execute("UPDATE recycle_bin SET restore_status=?, restore_note=? WHERE id=? AND restore_status IN (?,?)", (S_FAILED, note[:500], bin_id, S_IN_BIN, S_FAILED))
    conn.commit()


def purge(conn, bin_id, by="system", audit=None) -> dict:
    """永久刪除：隔離檔整個刪掉、快照清空，保留一列墓碑（狀態 purged）。自己 commit。"""
    begin_write(conn)
    r = _row(conn, bin_id)
    if r["restore_status"] not in LIVE:
        conn.rollback()
        raise RB.BinError("這一筆不在暫存區（狀態：%s）" % r["restore_status"])
    if audit is not None:                   # 稽核先寫進同一個交易（寫不進去 ⇒ 還沒刪任何東西就整筆失敗）；之後才刪隔離檔
        try:
            audit(conn, {"entityType": r["entity_type"], "entityId": r["entity_id"], "label": r["entity_label"], "deletedAt": r["deleted_at"],
                         "purgeAfter": r["purge_after"]})
        except Exception as e:              # noqa: BLE001
            conn.rollback()
            logger.exception("recyclebin purge #%s audit failed", bin_id)
            raise RB.BinError("audit_failed: 稽核紀錄寫不進去，未清除：%s" % e.__class__.__name__)
    try:
        Q.remove(r["token"])                # 驗證資料夾真的刪乾淨；刪不掉就丟 OSError，這一筆維持在暫存區（不標已清除、不清快照）
    except OSError as e:
        conn.rollback()
        raise RB.BinError("purge_blocked: 隔離檔刪不乾淨，這一筆仍留在暫存區：%s" % e)
    cur = conn.execute("UPDATE recycle_bin SET restore_status=?, snapshot_json='{}', files_manifest_json='[]', bytes=0, file_count=0, purged_at=?, purged_by=?"
                       " WHERE id=? AND restore_status IN (?,?)", (S_PURGED, _now().isoformat(), by, bin_id, S_IN_BIN, S_FAILED))
    if cur.rowcount != 1:
        conn.rollback()
        raise RB.BinError("這一筆的狀態剛被改變，請重新整理後再試")
    conn.commit()
    return _summary(_row(conn, bin_id))


def status(conn) -> dict:
    counts = {s: 0 for s in (S_IN_BIN, S_RESTORED, S_PURGED, S_FAILED)}
    for r in conn.execute("SELECT restore_status, COUNT(*) n FROM recycle_bin GROUP BY restore_status").fetchall():
        counts[r["restore_status"]] = r["n"]
    oldest = conn.execute("SELECT MIN(deleted_at) FROM recycle_bin WHERE restore_status IN (?,?)", LIVE).fetchone()[0]
    used, nfiles = Q.used_bytes()
    return {"counts": counts, "oldest": oldest or "", "retentionDays": RB.RETENTION_DAYS, "dir": Q.root_dir(), "defaultDir": Q.default_dir(),
            "usedBytes": used, "fileCount": nfiles, "freeBytes": Q.free_bytes(), "warnBytes": DISK_WARN_BYTES, "overWarn": used > DISK_WARN_BYTES,
            "adapters": {k: a.label or k for k, a in RB.adapters().items()}}


def reconcile(conn) -> int:
    """孤兒隔離資料夾（呼叫端交易回滾／當機）⇒ 檔案搬回原路徑。回處理幾個資料夾。"""
    known = {r[0] for r in conn.execute("SELECT token FROM recycle_bin").fetchall()}
    n = 0
    for tok in Q.orphan_tokens(known):
        try:
            Q.restore_orphan(tok)
            n += 1
        except Exception:                                          # noqa: BLE001
            logger.exception("recyclebin reconcile %s failed", tok)
    return n


def due_ids(conn, today=None) -> list:
    now = today or _now().isoformat(timespec="seconds")                 # 完整時間；傳日期字串（舊用法）＝當天 24:00 前到期的都算
    if len(now) == 10:
        now += "T23:59:59"
    return [r[0] for r in conn.execute("SELECT id FROM recycle_bin WHERE restore_status IN (?,?) AND purge_after<=? ORDER BY id LIMIT ?",
                                       (S_IN_BIN, S_FAILED, now, DAILY_BATCH)).fetchall()]


def superadmins(conn) -> list:
    return [r[0] for r in conn.execute("SELECT username FROM users WHERE role='superadmin' AND active=1 ORDER BY id").fetchall()]
