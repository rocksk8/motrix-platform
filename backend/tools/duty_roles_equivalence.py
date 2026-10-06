"""職責角色化 R1 上線關卡：每個既有帳號的生效權限上線前後必須逐人相同（DUTY-ROLES-DESIGN §3.2）。

兩步（唯讀；只做 SELECT）：
  1) 上線**前**（舊程式的資料庫也能跑；本檔不 import 會演進的程式，內嵌第42班的演算法）：
       python tools/duty_roles_equivalence.py snapshot --out equiv_before.json [--db PATH]
  2) 部署並讓 migration 跑完**後**：
       python tools/duty_roles_equivalence.py verify --snapshot equiv_before.json [--db PATH]
     以現行程式（`helpers.auth.effective_modules(role, modules, user_id=…)`）重算，逐人比對。
結束碼：0 全部相同；1 有人不同（列出差異，**不可上線／要回滾**）；2 用法或讀檔錯誤。
快照後才新增的帳號只列為資訊（不算差異）；快照裡有、現在沒有的帳號算差異。
"""
import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

FINANCE_KEYS = ("cashier", "finance", "financial_view")
FINANCE_ROLES = ("superadmin", "finance")


def legacy_effective(role, modules):
    """第42班出貨的 `effective_modules`（內嵌副本；不可改成呼叫現行函式，否則證明變成自證）。"""
    if isinstance(modules, str):
        try:
            modules = json.loads(modules or "[]")
        except Exception:
            modules = []
    mods = [m for m in (modules or []) if m not in FINANCE_KEYS]
    if role in FINANCE_ROLES:
        mods += list(FINANCE_KEYS)
    return mods


def _connect(path):
    if path:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn
    import db
    return db.get_db()


def take_snapshot(conn) -> dict:
    users = {}
    for r in conn.execute("SELECT id, username, role, active, modules FROM users ORDER BY id").fetchall():
        users[str(r["id"])] = {"username": r["username"], "role": r["role"], "active": bool(r["active"]),
                               "effective": legacy_effective(r["role"], r["modules"])}
    return {"users": users}


def verify(conn, snap) -> dict:
    """⇒ {"checked": n, "diffs": [...], "new_users": [...]}。現行程式的結果與快照逐人比對（含順序）。"""
    from helpers.auth import effective_modules
    diffs, checked = [], 0
    now = {}
    for r in conn.execute("SELECT id, username, role, active, modules FROM users ORDER BY id").fetchall():
        now[str(r["id"])] = r
    for uid, before in (snap.get("users") or {}).items():
        r = now.get(uid)
        if r is None:
            diffs.append({"id": uid, "username": before.get("username"), "problem": "帳號不見了"})
            continue
        checked += 1
        after = effective_modules(r["role"], r["modules"], user_id=r["id"], conn=conn)
        if r["role"] != before.get("role"):
            diffs.append({"id": uid, "username": r["username"], "problem": "角色變了 %s → %s" % (before.get("role"), r["role"])})
        if list(after) != list(before.get("effective") or []):
            b, a = set(before.get("effective") or []), set(after)
            diffs.append({"id": uid, "username": r["username"], "role": r["role"], "problem": "生效權限不同",
                          "lost": sorted(b - a), "gained": sorted(a - b), "orderOnly": b == a})
    new_users = [now[k]["username"] for k in now if k not in (snap.get("users") or {})]
    return {"checked": checked, "diffs": diffs, "new_users": new_users}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s1 = sub.add_parser("snapshot")
    s1.add_argument("--out", required=True)
    s1.add_argument("--db")
    s2 = sub.add_parser("verify")
    s2.add_argument("--snapshot", required=True)
    s2.add_argument("--db")
    a = ap.parse_args(argv)
    try:
        conn = _connect(a.db)
    except Exception as e:                                  # noqa: BLE001
        print("讀不到資料庫：%s" % e)
        return 2
    try:
        if a.cmd == "snapshot":
            snap = take_snapshot(conn)
            with open(a.out, "w", encoding="utf-8") as f:
                json.dump(snap, f, ensure_ascii=False, indent=1)
            print("已存快照：%d 位使用者 → %s" % (len(snap["users"]), a.out))
            return 0
        try:
            snap = json.load(open(a.snapshot, encoding="utf-8"))
        except Exception as e:                              # noqa: BLE001
            print("讀不到快照：%s" % e)
            return 2
        res = verify(conn, snap)
        print("比對 %d 位使用者；差異 %d 位；快照後新增 %d 位（資訊）" % (res["checked"], len(res["diffs"]), len(res["new_users"])))
        for d in res["diffs"]:
            print("  ✗ %s（%s）：%s%s%s" % (d.get("username"), d.get("role", ""), d["problem"],
                                          "；失去 " + "、".join(d["lost"]) if d.get("lost") else "",
                                          "；多出 " + "、".join(d["gained"]) if d.get("gained") else ""))
        print("結果：%s" % ("PASS（逐人相同）" if not res["diffs"] else "FAIL（不可上線／要回滾）"))
        return 0 if not res["diffs"] else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
