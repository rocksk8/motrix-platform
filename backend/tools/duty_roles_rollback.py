"""職責角色化 R2 L0 邏輯回滾（R2-STEP1-EQUIV-ROLLBACK-T45.md §4）：把計畫白名單內的人還原到快照時的綁定／扣項／原始勾選／在職狀態。

用法（預設只列出，不寫）：
    python tools/duty_roles_rollback.py --snapshot S.json [--plan PLAN.json] [--db PATH] [--json-out R.json]            # dry-run：列出全部與快照不同的人
    python tools/duty_roles_rollback.py --snapshot S.json --plan PLAN.json --db PATH --apply [--batch X]                 # 真的還原（單一交易；--apply 必須明確給 --db，且檔名須與快照的 dbPath 相符）
規則：
- `--apply` **必須**給 `--plan`；只動 `PLAN.users` 白名單內的人（鍵＝使用者 id）。白名單外的人與 superadmin 一律不動。
- `users.modules`（原始勾選）與 `users.active`（在職）**預設不還原**（可能把已離職者重新啟用、或蓋掉一次合法的修改）：
  計畫檔該人明確寫 `"restoreRaw": true`／`"restoreActive": true` 才還原（第 3 步停用回收的還原就是這樣用）；沒寫而與快照不同 ⇒ 只警告。
- 解除「快照時沒有」的綁定（`granted_at` 不得早於快照時間（同一秒算快照之後；快照裡沒有的綁定本來就是快照後才出現，更早＝時鐘異常）、略過並警告）；補回「快照時有、現在沒有」的綁定
  （角色須仍存在且啟用）；扣項、`users.modules`、`users.active` 還原成快照值。**不還原 `users.role`**（只警告）、**不還原角色定義**（只警告）。
- 每筆還原**追加**一列 `permission_changes`（kind=`rollback`；原因固定「系統：R2 回滾（批次 X）」；不刪不改既有紀錄；本檔禁用 REPLACE 寫法）。
- 補回的扣項沒有原本的 `set_by`／原因（快照只存鍵）：`set_by` 為空、原因用上面那句固定文字——原始操作者與原因**無法還原**，稽核上以紀錄列為準。
- 套用後立刻重驗，**範圍限白名單內的人**（白名單外的差異只列數量、不算失敗；角色定義不在 L0 範圍；沒要求還原的勾選／在職不算差異）；
  有剩餘差異 ⇒ 結束碼 1（回滾不完整，改走 L1）。
結束碼：0 完成（或無事可做）；1 回滾後仍有差異；2 用法／讀檔／計畫檔錯誤；3 結構問題（快照 schema 不符、白名單含 superadmin）。
"""
import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.txn import begin_write  # noqa: E402


def _connect(path):
    if path:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn
    import db
    return db.get_db()


def _loads(v, default):
    try:
        out = json.loads(v) if isinstance(v, str) else v
        return out if isinstance(out, type(default)) else default
    except (TypeError, ValueError):
        return default


def plan_rollback(conn, snap: dict, whitelist=None, options=None) -> dict:
    """⇒ {"items": [...], "warnings": [...], "skipped": [...]}。`whitelist`＝None 時列出全部差異（僅 dry-run 用）。"""
    taken = snap.get("takenAt") or ""
    roles_now = {r["key"]: {"id": r["id"], "active": bool(r["active"]), "sha": r["permissions"]}
                 for r in conn.execute("SELECT id, key, permissions, active FROM duty_roles").fetchall()}
    options = options or {}
    items, warnings, skipped = [], [], []
    for uid, x in (snap.get("users") or {}).items():
        if whitelist is not None and uid not in whitelist:
            continue
        r = conn.execute("SELECT id, username, role, active, modules FROM users WHERE id=?", (int(uid),)).fetchone()
        if r is None:
            skipped.append({"id": uid, "why": "帳號已不存在（不能還原）"})
            continue
        if r["role"] == "superadmin" or x.get("role") == "superadmin":
            skipped.append({"id": uid, "why": "superadmin 不由回滾處理"})
            continue
        cur_binds = {b["key"]: b["granted_at"] for b in conn.execute(
            "SELECT r.key, b.granted_at FROM user_duty_roles b JOIN duty_roles r ON r.id=b.role_id WHERE b.user_id=?", (r["id"],)).fetchall()}
        cur_subs = {s["perm_key"] for s in conn.execute("SELECT perm_key FROM user_perm_subtracts WHERE user_id=?", (r["id"],)).fetchall()}
        want_binds, want_subs = set(x.get("bindings") or []), set(x.get("subtracts") or [])
        raw_now = sorted(set(_loads(r["modules"], [])))
        opt = options.get(uid) or {}
        raw_snap, active_snap = sorted(x.get("rawModules") or []), bool(x.get("active"))
        it = {"id": r["id"], "username": r["username"], "unbind": [], "rebind": [], "subDrop": [], "subAdd": [],
              "rawBefore": raw_now, "rawAfter": raw_snap if opt.get("restoreRaw") is True else raw_now,
              "activeBefore": bool(r["active"]), "activeAfter": active_snap if opt.get("restoreActive") is True else bool(r["active"]),
              "rawDiffers": raw_now != raw_snap, "activeDiffers": bool(r["active"]) != active_snap}
        if it["rawDiffers"] and opt.get("restoreRaw") is not True:
            warnings.append("id %s：原始勾選與快照不同，未還原（計畫檔該人需明確寫 restoreRaw: true）" % r["id"])
        if it["activeDiffers"] and opt.get("restoreActive") is not True:
            warnings.append("id %s：在職狀態與快照不同（快照 %s／現在 %s），未還原（計畫檔該人需明確寫 restoreActive: true）" % (
                r["id"], "在職" if active_snap else "停用", "在職" if r["active"] else "停用"))
        for k, granted in sorted(cur_binds.items()):
            if k in want_binds:
                continue
            if taken and (granted or "") < taken:
                warnings.append("id %s：綁定 %s 的 granted_at（%s）早於快照（%s），不是 R2 動作，未解除" % (r["id"], k, granted, taken))
            else:
                it["unbind"].append(k)
        for k in sorted(want_binds - set(cur_binds)):
            ro = roles_now.get(k)
            if ro is None or not ro["active"]:
                warnings.append("id %s：快照有綁定 %s，但該角色已不存在或已停用，未補回" % (r["id"], k))
            else:
                it["rebind"].append(k)
        it["subDrop"] = sorted(cur_subs - want_subs)
        it["subAdd"] = sorted(want_subs - cur_subs)
        if r["role"] != x.get("role"):
            warnings.append("id %s：基礎類別 %s → %s（回滾不還原 users.role）" % (r["id"], x.get("role"), r["role"]))
        it["changed"] = bool(it["unbind"] or it["rebind"] or it["subDrop"] or it["subAdd"] or it["rawBefore"] != it["rawAfter"]
                             or it["activeBefore"] != it["activeAfter"])
        items.append(it)
    for k, y in (snap.get("roles") or {}).items():
        now = roles_now.get(k)
        if now is None or now["active"] != y.get("active"):
            warnings.append("角色 %s 的定義／啟用狀態與快照不同（L0 不還原角色定義，請另案處理）" % k)
    return {"items": items, "warnings": warnings, "skipped": skipped}


def apply_rollback(conn, plan: dict, batch: str) -> int:
    """單一交易；每筆還原追加一列 permission_changes。⇒ 還原的人數。"""
    from helpers import duty_roles as dr
    reason = "系統：R2 回滾（批次 %s）" % batch
    n = 0
    begin_write(conn)
    try:
        for it in plan["items"]:
            if not it["changed"]:
                continue
            uid = it["id"]
            before = {"bindings": [], "subtracts": [], "rawModules": it["rawBefore"], "active": it["activeBefore"]}
            for k in it["unbind"]:
                conn.execute("DELETE FROM user_duty_roles WHERE user_id=? AND role_id=(SELECT id FROM duty_roles WHERE key=?)", (uid, k))
                before["bindings"].append(k)
            for k in it["rebind"]:
                conn.execute("INSERT INTO user_duty_roles (user_id, role_id, granted_by, granted_at, reason)"
                             " SELECT ?, id, NULL, ?, ? FROM duty_roles WHERE key=?", (uid, dr._now(), reason, k))
            for k in it["subDrop"]:
                conn.execute("DELETE FROM user_perm_subtracts WHERE user_id=? AND perm_key=?", (uid, k))
                before["subtracts"].append(k)
            for k in it["subAdd"]:
                conn.execute("INSERT INTO user_perm_subtracts (user_id, perm_key, set_by, set_at, reason) VALUES (?,?,NULL,?,?)",
                             (uid, k, dr._now(), reason))
            if it["rawBefore"] != it["rawAfter"]:
                conn.execute("UPDATE users SET modules=? WHERE id=?", (json.dumps(it["rawAfter"], ensure_ascii=False), uid))
            if it["activeBefore"] != it["activeAfter"]:
                conn.execute("UPDATE users SET active=? WHERE id=?", (1 if it["activeAfter"] else 0, uid))
            after = {"unbound": it["unbind"], "rebound": it["rebind"], "subtractsDropped": it["subDrop"], "subtractsAdded": it["subAdd"],
                     "rawModules": it["rawAfter"], "active": it["activeAfter"]}
            added = sorted(set(it["rawAfter"]) - set(it["rawBefore"]))
            removed = sorted(set(it["rawBefore"]) - set(it["rawAfter"]))
            dr._record(conn, None, "rollback", "user", uid, it["username"], added, removed, before, after, False, reason, "")
            n += 1
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return n


def scoped_verify(conn, snap: dict, items: list) -> dict:
    """套用後重驗，範圍限白名單內的人：只算「我們有要求還原」的面向（沒要求還原勾選 ⇒ 該人的 E1／E2／gate 與 E5 不算；沒要求還原在職 ⇒ E4 不算）。
    角色定義與白名單外的人只列資訊。⇒ {"remaining": [...], "outside": n, "structure": [...]}。"""
    import duty_roles_equivalence as EQ
    now = EQ.take_snapshot2(conn)
    res = EQ.diff_snapshots(snap, now)
    by_id = {str(i["id"]): i for i in items}
    remaining, outside = [], 0
    for d in res["diffs"]:
        it = by_id.get(str(d.get("id")))
        if d.get("facet") == "role_def":
            continue
        if it is None:
            outside += 1
            continue
        f = d.get("facet")
        if f == "E4" and it["activeAfter"] == it["activeBefore"] and it["activeDiffers"]:
            continue
        if f in ("E1", "E2", "E5", "gate") and it["rawAfter"] == it["rawBefore"] and it["rawDiffers"]:
            continue
        remaining.append(d)
    return {"remaining": remaining, "outside": outside, "structure": res["structure"]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--plan")
    ap.add_argument("--db")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--batch")
    ap.add_argument("--json-out")
    a = ap.parse_args(argv)
    try:
        snap = json.load(open(a.snapshot, encoding="utf-8"))
        plan = json.load(open(a.plan, encoding="utf-8")) if a.plan else None
    except Exception as e:                                  # noqa: BLE001
        print("讀檔錯誤：%s" % e)
        return 2
    if snap.get("schema") != 2:
        print("快照 schema 不符（需要 2）")
        return 3
    if a.apply and not plan:
        print("--apply 必須給 --plan（白名單）：只還原白名單內的人")
        return 2
    if a.apply and not a.db:
        print("--apply 必須明確給 --db（不從環境推測要改哪一個資料庫）")
        return 2
    if a.apply and snap.get("dbPath") and os.path.basename(a.db) != snap["dbPath"]:
        print("目標資料庫檔名（%s）與快照的 dbPath（%s）不符：中止" % (os.path.basename(a.db), snap["dbPath"]))
        return 2
    whitelist = None
    if plan is not None:
        whitelist = {str(k) for k in (plan.get("users") or {})}
        if not whitelist:
            print("計畫檔 users 白名單是空的：無事可做")
            return 0
    try:
        conn = _connect(a.db)
    except Exception as e:                                  # noqa: BLE001
        print("讀不到資料庫：%s" % e)
        return 2
    try:
        try:
            res = plan_rollback(conn, snap, whitelist, (plan or {}).get("users"))
        except sqlite3.OperationalError as e:
            print("沒有職責角色資料表（%s）：無事可做" % e)
            return 0
        for s in res["skipped"]:
            print("  略過 id %s：%s" % (s["id"], s["why"]))
        if whitelist is not None:
            sa_in = [s for s in res["skipped"] if "superadmin" in s["why"]]
            if sa_in:
                print("白名單含 superadmin：拒絕")
                return 3
        for it in res["items"]:
            print("%s %s（id %s）：解除綁定 %s／補回綁定 %s／移除扣項 %s／補回扣項 %s／勾選 %s／在職 %s" % (
                "•" if it["changed"] else "=", it["username"], it["id"], "、".join(it["unbind"]) or "-", "、".join(it["rebind"]) or "-",
                "、".join(it["subDrop"]) or "-", "、".join(it["subAdd"]) or "-",
                "還原" if it["rawBefore"] != it["rawAfter"] else "不變", "還原" if it["activeBefore"] != it["activeAfter"] else "不變"))
        for w in res["warnings"]:
            print("  ⚠ %s" % w)
        if a.json_out:
            with open(a.json_out, "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False, indent=1)
        todo = [i for i in res["items"] if i["changed"]]
        if not a.apply:
            print("（dry-run；%d 位待還原；加 --plan 白名單與 --apply 才寫入）" % len(todo))
            return 0
        if not todo:
            print("白名單內沒有需要還原的人")
            return 0
        batch = a.batch or (plan or {}).get("batch") or snap.get("takenAt") or "?"
        n = apply_rollback(conn, res, batch)
        print("已還原 %d 位使用者（批次 %s）" % (n, batch))
        v = scoped_verify(conn, snap, res["items"])
        for d in v["remaining"]:
            print("  ✗ 白名單內仍有差異：%s（id %s）[%s] 少 %s／多 %s" % (d.get("username"), d.get("id"), d.get("facet"),
                                                                  "、".join(d.get("lost") or []) or "-", "、".join(d.get("gained") or []) or "-"))
        for st in v["structure"]:
            print("  ‼ 結構：%s" % st)
        ok = not v["remaining"] and not v["structure"]
        print("回滾後重驗（限白名單；白名單外差異 %d 筆僅供參考）：%s" % (v["outside"], "PASS" if ok else "FAIL（改走 L1）"))
        return 0 if ok else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
