"""職責角色化 R1 回滾第 0 步：把每位**有綁定或扣項**的人的最終生效勾選寫回 `users.modules`（DUTY-ROLES-DESIGN §3.3）。

為什麼：舊版程式只認 `users.modules`，不認職責角色與扣項；回滾前不寫回，角色給的權限會消失、被扣掉的權限會「復活」。
寫回的是「原始勾選層」的結果（＝（原勾選 ∪ 角色權限）− 扣項，**不套**第42班的財務規則，惰性財務勾選維持原樣），
舊程式讀到後得到與現在相同的生效權限。superadmin 不會被改。**不刪**任何職責角色資料表（回滾後仍可保留）。

用法：
    python tools/duty_roles_export_effective.py [--db PATH]            # 預設只列出（dry-run）
    python tools/duty_roles_export_effective.py [--db PATH] --apply    # 真的寫回（單一交易）
結束碼：0 完成（或無事可做）；2 錯誤。有扣項的人會特別標出，請給最高管理者看過再回滾。
"""
import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def _connect(path):
    if path:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn
    import db
    return db.get_db()


def plan(conn) -> list:
    from helpers import duty_roles as dr
    out = []
    for r in conn.execute("SELECT id, username, role, modules FROM users WHERE role != 'superadmin' ORDER BY id").fetchall():
        if not dr.has_duty_data(conn, r["id"]):
            continue
        try:
            raw = json.loads(r["modules"] or "[]")
        except Exception:
            raw = []
        new = dr.resolve_raw_modules(conn, r["id"], raw)
        subs = [x[0] for x in conn.execute("SELECT perm_key FROM user_perm_subtracts WHERE user_id=? ORDER BY perm_key", (r["id"],))]
        out.append({"id": r["id"], "username": r["username"], "role": r["role"], "before": raw, "after": list(new), "subtracts": subs,
                    "changed": list(new) != raw})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    try:
        conn = _connect(a.db)
    except Exception as e:                                  # noqa: BLE001
        print("讀不到資料庫：%s" % e)
        return 2
    try:
        try:
            items = plan(conn)
        except sqlite3.OperationalError as e:
            print("沒有職責角色資料表（%s）：無事可做" % e)
            return 0
        if not items:
            print("沒有任何人有職責角色綁定或扣項：users.modules 已是完整答案，無事可做")
            return 0
        for it in items:
            gained = sorted(set(it["after"]) - set(it["before"]))
            lost = sorted(set(it["before"]) - set(it["after"]))
            print("%s %s（%s）：多 %s／少 %s%s" % ("•" if it["changed"] else "=", it["username"], it["role"],
                                               "、".join(gained) or "-", "、".join(lost) or "-",
                                               "　⚠ 有個人扣項：" + "、".join(it["subtracts"]) if it["subtracts"] else ""))
        with_subs = [i["username"] for i in items if i["subtracts"]]
        if with_subs:
            print("⚠ 有個人扣項的人（回滾後這些權限若不寫回就會復活）：" + "、".join(with_subs))
        if not a.apply:
            print("（dry-run；加 --apply 才寫回）")
            return 0
        conn.execute("BEGIN")
        for it in items:
            if it["changed"]:
                conn.execute("UPDATE users SET modules=? WHERE id=?", (json.dumps(it["after"], ensure_ascii=False), it["id"]))
        conn.commit()
        print("已寫回 %d 位使用者的 users.modules" % sum(1 for i in items if i["changed"]))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
