"""職責角色化上線關卡：每個既有帳號的生效權限上線前後必須逐人相同（DUTY-ROLES-DESIGN §3.2；R2 第1步＝v2，設計 R2-STEP1-EQUIV-ROLLBACK-T45.md）。

只做 SELECT（本檔不寫任何資料庫）。兩代並存：
  schema 1（預設，第43班用法，行為與輸出不動）：
       python tools/duty_roles_equivalence.py snapshot --out equiv_before.json [--db PATH]
       python tools/duty_roles_equivalence.py verify --snapshot equiv_before.json [--db PATH]
     上線**前**用內嵌的第42班演算法拍快照，上線**後**以現行 `helpers.auth.effective_modules` 逐人比對（含順序）。
  schema 2（R2 全程）：六個面向（E1 生效／E2 守門視圖／E3 財務能力矩陣／E4 基礎類別＋在職／E5 原始勾選／E6 superadmin），
     角色定義、紀錄表筆數與觸發器；差異集合必須「恰好等於」計畫檔白名單；另以獨立重算 `spec_effective` 防自證：
       python tools/duty_roles_equivalence.py snapshot --schema 2 --out S.json [--db PATH]
       python tools/duty_roles_equivalence.py verify   --snapshot S.json [--db PATH] [--plan PLAN.json] [--json-out R.json] [--finance-cutover]
       python tools/duty_roles_equivalence.py diff     --a S1.json --b S2.json [--plan PLAN.json]     # 離線，不開 DB
       python tools/duty_roles_equivalence.py catalog-check [--db PATH] [--json-out R.json]            # 正式機唯讀：superadmin 生效集合 vs 全目錄鍵
       python tools/duty_roles_equivalence.py scan-finance [--root DIR] [--json-out R.json]            # 靜態：財務判斷點 A／B 類盤點
結束碼：0 PASS；1 有差異（不可放行／要回滾）；2 用法或讀檔錯誤；3 結構問題（紀錄表筆數減少、append-only 觸發器不見、
superadmin 有綁定／扣項、快照 schema 不符、切換前置條件不符）。1 與 3 都不可放行。快照後才新增的帳號只列為資訊。

計畫檔 PLAN.json（以 id 為鍵、鍵清單、不接受萬用字元；無計畫檔＝全員零差異）：
  {"batch": "...", "roleChanges": ["<roleKey>", ...],
   "users": {"<id>": {"lost": [...], "gained": [...], "guardLost": [...], "guardGained": [...],
                      "rawLost": [...], "rawGained": [...], "role": "<新基礎類別>", "active": true|false}},
   "finance": {"expectedDiff": {"<id>": {"gained": [...], "lost": [...]}}}}
"""
import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

FINANCE_KEYS = ("cashier", "finance", "financial_view")
FINANCE_ROLES = ("superadmin", "finance")
CAP_NAMES = ("finance", "cashier", "seeFinancial", "moneyVisible", "quoteMoneyVisible", "materialMoneyVisible",
             "inFinanceUsernames", "mailFinanceGroup")
TRIGGERS = ("permission_changes_no_update", "permission_changes_no_delete")
#: D5 範圍內（寫死 "finance" 字面值、已改走縫的）四個檔（使用者 2026-10-07 裁示；相對 backend/）
D5_IN_SCOPE = ("helpers/financial_mask.py", "modules/case/api/material_orders.py", "modules/case/material_guard.py",
               "modules/subcontract/api/vendor_contractors.py")


# ═════════════════════════ schema 1（第43班；不動）═════════════════════════

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


# ═════════════════════════ schema 2（R2）═════════════════════════

def _loads(v, default):
    try:
        out = json.loads(v) if isinstance(v, str) else v
        return out if isinstance(out, type(default)) else default
    except (TypeError, ValueError):
        return default


def _sha(perms) -> str:
    return hashlib.sha256(json.dumps(sorted(perms), ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


# ── 獨立重算（逐字照 DUTY-ROLES-DESIGN §2.2 與 R1 §6.1；**不呼叫 helpers.auth**）─────────────

def spec_guard_view(role, raw, bound_perms, subtracts) -> set:
    """E2：`_require_user` 給後端守門用的原始勾選（superadmin 不經角色／扣項；其餘＝（勾選∪角色權限）−扣項）。"""
    raw = set(raw or [])
    if role == "superadmin":
        return raw
    return (raw | set(bound_perms or [])) - set(subtracts or [])


def spec_effective(role, raw, bound_perms, subtracts) -> set:
    """E1：先套角色／扣項（superadmin 例外），再套財務規則（財務三鍵由基礎類別決定：只有 superadmin／finance 有）。"""
    base = spec_guard_view(role, raw, bound_perms, subtracts)
    out = {m for m in base if m not in FINANCE_KEYS}
    if role in FINANCE_ROLES:
        out |= set(FINANCE_KEYS)
    return out


def spec_finance(role, bound_perms, subtracts) -> set:
    """D5 新規則：財務生效鍵＝（基礎類別 finance 隱含三鍵 ∪ 已啟用角色的財務鍵）− 個人扣項；superadmin 全有；原始勾選不計。"""
    if role == "superadmin":
        return set(FINANCE_KEYS)
    keys = set(FINANCE_KEYS) if role == "finance" else set()
    keys |= {k for k in (bound_perms or []) if k in FINANCE_KEYS}
    return keys - set(subtracts or [])


def _table_rows(conn, sql, args=()):
    try:
        return conn.execute(sql, args).fetchall()
    except sqlite3.OperationalError:
        return []


def take_snapshot2(conn) -> dict:
    from datetime import datetime
    from helpers import auth as A
    from helpers import duty_roles as dr
    from helpers import financial_mask as FM
    roles, role_perms, role_active = {}, {}, {}
    for r in _table_rows(conn, "SELECT id, key, permissions, active, version, is_system FROM duty_roles ORDER BY id"):
        perms = sorted(k for k in _loads(r["permissions"], []) if isinstance(k, str))
        roles[r["key"]] = {"id": r["id"], "permsSha": _sha(perms), "perms": perms, "active": bool(r["active"]),
                           "version": r["version"], "isSystem": bool(r["is_system"])}
        role_perms[r["id"]], role_active[r["id"]] = perms, bool(r["active"])
    key_of = {r["id"]: r["key"] for r in _table_rows(conn, "SELECT id, key FROM duty_roles")}
    binds, subs = {}, {}
    for r in _table_rows(conn, "SELECT user_id, role_id FROM user_duty_roles ORDER BY user_id, role_id"):
        binds.setdefault(r["user_id"], []).append(r["role_id"])
    for r in _table_rows(conn, "SELECT user_id, perm_key FROM user_perm_subtracts ORDER BY user_id, perm_key"):
        subs.setdefault(r["user_id"], []).append(r["perm_key"])
    fin_names = set(A.finance_usernames(conn))
    users = {}
    for r in conn.execute("SELECT id, username, role, active, modules FROM users ORDER BY id").fetchall():
        uid, role = r["id"], r["role"]
        raw = _loads(r["modules"], [])
        eff_ordered = list(A.effective_modules(role, r["modules"], user_id=uid, conn=conn))
        if role == "superadmin":
            guard = list(raw)
        else:
            guard = list(dr.resolve_raw_modules(conn, uid, raw))
        ud = {"id": uid, "username": r["username"], "role": role, "modules": r["modules"]}
        caps = {"finance": bool(A.has_finance_access(ud)), "cashier": bool(A.has_cashier_access(ud)),
                "seeFinancial": bool(A.can_see_financial(ud)), "moneyVisible": bool(FM.money_visible(ud)),
                "quoteMoneyVisible": bool(FM.quote_money_visible(ud)), "materialMoneyVisible": bool(FM.material_money_visible(ud)),
                "inFinanceUsernames": r["username"] in fin_names, "mailFinanceGroup": role in ("finance", "superadmin")}
        users[str(uid)] = {"username": r["username"], "role": role, "active": bool(r["active"]),
                           "rawModules": sorted(set(raw)),
                           "bindings": sorted(key_of.get(i, "?%s" % i) for i in binds.get(uid, [])),
                           "subtracts": sorted(subs.get(uid, [])),
                           "effective": sorted(set(eff_ordered)), "effectiveOrdered": eff_ordered,
                           "guardView": sorted(set(guard)), "caps": caps,
                           "financeKeys": sorted(A.finance_effective_keys(ud))}
    trig = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'permission_changes_no%' ORDER BY name")]
    pc = _table_rows(conn, "SELECT COUNT(*) AS n, COALESCE(MAX(id),0) AS m FROM permission_changes")
    return {"schema": 2, "takenAt": datetime.now().isoformat(timespec="seconds"), "dbPath": "", "codeVersion": {},
            "roles": roles, "users": users,
            "log": {"permissionChangesCount": pc[0]["n"] if pc else 0, "permissionChangesMaxId": pc[0]["m"] if pc else 0, "triggers": trig}}


def _plan_user(plan, uid) -> dict:
    return ((plan or {}).get("users") or {}).get(str(uid)) or {}


def _setdiff(a, b):
    a, b = set(a or []), set(b or [])
    return sorted(a - b), sorted(b - a)           # (lost, gained)


def _check_facet(diffs, uid, name, facet, before, after, want_lost, want_gained, extra=None):
    lost, gained = _setdiff(before, after)
    wl, wg = sorted(set(want_lost or [])), sorted(set(want_gained or []))
    if lost != wl or gained != wg:
        d = {"id": uid, "username": name, "facet": facet, "problem": "差異與計畫不符" if (wl or wg) else "非預期差異",
             "lost": lost, "gained": gained}
        if wl or wg:
            d["expectLost"], d["expectGained"] = wl, wg
        diffs.append(d)


def diff_snapshots(a: dict, b: dict, plan=None) -> dict:
    """離線比對兩份 schema 2 快照。⇒ {"code", "diffs", "structure", "info", "orderOnly"}（code：0／1／3）。"""
    diffs, structure, info, order_only = [], [], [], []
    if a.get("schema") != 2 or b.get("schema") != 2:
        return {"code": 3, "diffs": [], "structure": ["快照 schema 不符（需要 2）：a=%s b=%s" % (a.get("schema"), b.get("schema"))],
                "info": [], "orderOnly": []}
    plan = plan or {}
    role_changes_ok = set(plan.get("roleChanges") or [])
    # 結構
    la, lb = a.get("log") or {}, b.get("log") or {}
    if (lb.get("permissionChangesCount", 0) < la.get("permissionChangesCount", 0)
            or lb.get("permissionChangesMaxId", 0) < la.get("permissionChangesMaxId", 0)):
        structure.append("permission_changes 筆數／最大編號減少（%s→%s／%s→%s）：紀錄被刪" % (
            la.get("permissionChangesCount"), lb.get("permissionChangesCount"), la.get("permissionChangesMaxId"), lb.get("permissionChangesMaxId")))
    for t in TRIGGERS:
        if t not in (lb.get("triggers") or []):
            structure.append("append-only 觸發器不見：%s" % t)
    for uid, u in (b.get("users") or {}).items():
        if u.get("role") == "superadmin" and (u.get("bindings") or u.get("subtracts")):
            structure.append("superadmin（id %s）出現綁定／扣項列" % uid)
    # 角色定義先比
    role_diff = False
    ra, rb = a.get("roles") or {}, b.get("roles") or {}
    for k in sorted(set(ra) | set(rb)):
        x, y = ra.get(k), rb.get(k)
        if x is None or y is None or (x.get("permsSha"), x.get("active")) != (y.get("permsSha"), y.get("active")):
            if k in role_changes_ok:
                continue
            role_diff = True
            lost, gained = _setdiff((x or {}).get("perms"), (y or {}).get("perms"))
            diffs.append({"facet": "role_def", "role": k, "problem": "角色定義變動（計畫檔 roleChanges 未列）",
                          "lost": lost, "gained": gained,
                          "activeBefore": (x or {}).get("active"), "activeAfter": (y or {}).get("active")})
    fin_exp = ((plan.get("finance") or {}).get("expectedDiff") or {})
    ua, ub = a.get("users") or {}, b.get("users") or {}
    for uid, x in ua.items():
        y = ub.get(uid)
        if y is None:
            diffs.append({"id": uid, "username": x.get("username"), "facet": "user", "problem": "帳號不見了"})
            continue
        name, pu = x.get("username"), _plan_user(plan, uid)
        # E4
        want_role, want_active = pu.get("role", x.get("role")), pu.get("active", x.get("active"))
        if (y.get("role"), y.get("active")) != (want_role, want_active):
            diffs.append({"id": uid, "username": name, "facet": "E4", "problem": "基礎類別／在職變動",
                          "before": {"role": x.get("role"), "active": x.get("active")}, "after": {"role": y.get("role"), "active": y.get("active")}})
        # E5
        _check_facet(diffs, uid, name, "E5", x.get("rawModules"), y.get("rawModules"), pu.get("rawLost"), pu.get("rawGained"))
        # E6：superadmin 的可見面（E1）嚴格相等，不接受計畫白名單
        if x.get("role") == "superadmin":
            _check_facet(diffs, uid, name, "E6", x.get("effective"), y.get("effective"), [], [])
        if not role_diff:
            if x.get("role") != "superadmin":
                _check_facet(diffs, uid, name, "E1", x.get("effective"), y.get("effective"), pu.get("lost"), pu.get("gained"))
            _check_facet(diffs, uid, name, "E2", x.get("guardView"), y.get("guardView"),
                         pu.get("guardLost", pu.get("lost")), pu.get("guardGained", pu.get("gained")))
            ca = sorted(k for k, v in (x.get("caps") or {}).items() if v)
            cb = sorted(k for k, v in (y.get("caps") or {}).items() if v)
            fe = fin_exp.get(uid) or {}
            _check_facet(diffs, uid, name, "E3", ca, cb, fe.get("lost"), fe.get("gained"))
        if (x.get("effectiveOrdered") != y.get("effectiveOrdered") and x.get("effective") == y.get("effective")):
            order_only.append({"id": uid, "username": name})
    info += ["快照後新增帳號：%s" % ub[k].get("username") for k in ub if k not in ua]
    code = 3 if structure else (1 if diffs else 0)
    return {"code": code, "diffs": diffs, "structure": structure, "info": info, "orderOnly": order_only}


def spec_mismatches(snap2: dict, conn) -> list:
    """獨立重算：快照內每人的 E1／E2／財務鍵，用 `spec_*` 對照 helpers.auth 的實際結果；不同＝程式與規格不一致。"""
    out = []
    key_perms = {}
    for r in _table_rows(conn, "SELECT id, key, permissions, active FROM duty_roles"):
        key_perms[r["key"]] = (_loads(r["permissions"], []), bool(r["active"]))
    for uid, u in (snap2.get("users") or {}).items():
        bound = [p for k in u.get("bindings", []) for p in (key_perms.get(k, ([], False))[0] if key_perms.get(k, ([], False))[1] else [])]
        subs = u.get("subtracts") or []
        for facet, want, got in (
                ("E1", spec_effective(u["role"], u["rawModules"], bound, subs), set(u["effective"])),
                ("E2", spec_guard_view(u["role"], u["rawModules"], bound, subs), set(u["guardView"])),
                ("財務生效鍵", spec_finance(u["role"], bound, subs), set(u["financeKeys"]))):
            if want != got:
                out.append({"id": uid, "username": u.get("username"), "facet": facet, "problem": "程式與規格不一致",
                            "spec": sorted(want), "actual": sorted(got)})
    return out


def finance_cutover_check(snap2: dict) -> dict:
    """D5 切換前置條件（§10.2.3）。⇒ {"violations": [...], "wouldChange": {uid: {gained, lost}}}。
    違反＝結束碼 3；`wouldChange`＝「新規則 vs 舊規則（只看基礎類別）」逐人財務三鍵差異，必須等於 PLAN.finance.expectedDiff（預設空）。"""
    vio, would = [], {}
    roles = snap2.get("roles") or {}
    for uid, u in (snap2.get("users") or {}).items():
        role = u.get("role")
        bound_fin = sorted({p for k in u.get("bindings", []) for p in (roles.get(k, {}).get("perms") or []) if p in FINANCE_KEYS})
        if role not in ("finance", "superadmin") and bound_fin:
            vio.append("①非 finance／superadmin 的使用者（id %s）綁定含財務鍵的角色：%s" % (uid, "、".join(bound_fin)))
        fin_subs = [k for k in (u.get("subtracts") or []) if k in FINANCE_KEYS]
        if fin_subs:
            vio.append("②財務鍵扣項（id %s）：%s" % (uid, "、".join(fin_subs)))
        if role in ("finance", "superadmin") and not set(FINANCE_KEYS) <= set(u.get("effective") or []):
            vio.append("③%s（id %s）的生效權限缺財務三鍵" % (role, uid))
        old = set(FINANCE_KEYS) if role in FINANCE_ROLES else set()
        new = set(u.get("financeKeys") or [])
        lost, gained = sorted(old - new), sorted(new - old)
        if lost or gained:
            would[uid] = {"lost": lost, "gained": gained}
    return {"violations": vio, "wouldChange": would}


def verify2(conn, snap, plan=None, finance_cutover=False, root=None) -> dict:
    """現況拍新快照 → 與 `snap` 比對 → 獨立重算 →（可選）切換前置條件。"""
    now = take_snapshot2(conn)
    res = diff_snapshots(snap, now, plan)
    sm = spec_mismatches(now, conn)
    res["specMismatch"] = sm
    if sm and res["code"] == 0:
        res["code"] = 1
    res["checked"] = len(snap.get("users") or {})
    if finance_cutover:
        cut = finance_cutover_check(now)
        exp = ((plan or {}).get("finance") or {}).get("expectedDiff") or {}
        scan = scan_finance(root)
        cut["inScopeLiteralsRemaining"] = scan["d5InScopeRemaining"]
        for v in cut["inScopeLiteralsRemaining"]:
            cut["violations"].append("④D5 範圍內仍有寫死 finance 字面值：%s:%s" % (v["file"], v["line"]))
        mism = {u: {"expected": exp.get(u), "actual": cut["wouldChange"].get(u)}
                for u in set(exp) | set(cut["wouldChange"])
                if {k: sorted(v) for k, v in (exp.get(u) or {}).items()} != {k: sorted(v) for k, v in (cut["wouldChange"].get(u) or {}).items()}}
        cut["expectedDiffMismatch"] = mism
        res["cutover"] = cut
        if cut["violations"]:
            res["code"] = 3
        elif mism and res["code"] == 0:
            res["code"] = 1
    res["now"] = now
    return res


# ── catalog-check ──────────────────────────────────────────────────────────────

def catalog_check(conn) -> dict:
    from helpers import duty_roles as dr
    from helpers import auth as A
    catalog = sorted(dr.known_keys())
    sa = []
    for r in conn.execute("SELECT id, role, modules FROM users WHERE role='superadmin' ORDER BY id").fetchall():
        eff = set(A.effective_modules(r["role"], r["modules"], user_id=r["id"], conn=conn))
        sa.append({"id": r["id"], "role": "superadmin", "effective": sorted(eff), "missing": sorted(set(catalog) - eff)})
    union = sorted({k for s in sa for k in s["missing"]})
    return {"catalog": catalog, "superadmins": sa, "missingUnion": union}


# ── scan-finance（靜態、離線）──────────────────────────────────────────────────

_A_RE = re.compile(r"\b(has_finance_access|has_cashier_access|can_see_financial|finance_usernames|finance_duty_person)\b|"
                   r"user_has_module\([^)]*[\"'](finance|cashier|financial_view)[\"']")
_ROLE_LIT_RE = re.compile(r"[\"'](finance|admin|sales|superadmin)[\"']")
_FIN_LIT_RE = re.compile(r"[\"']finance[\"']")


def _code_part(line: str) -> str:
    return line.split("#", 1)[0]


def scan_finance(root=None) -> dict:
    """A＝經 `has_*`／`user_has_module(財務鍵)` 的點（跟著新縫走）；B＝寫死角色字面值的點（不跟著走）：
    B-納入（含 finance 字面值、屬 D5 四個檔）／B-未納入-finance（含 finance 字面值但不在 D5 範圍，使用者裁示維持）／
    B-未納入-admin/sales（「部分生效」標示的來源）。`d5InScopeRemaining`＝D5 四個檔裡仍寫死 finance 角色字面值的行（應為空）。"""
    root = root or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    root = os.path.abspath(root)
    a, b_in, b_out_fin, b_out_as = [], [], [], []
    skip_dirs = {"tests", "tools", "__pycache__", ".venv", "venv", "node_modules", "migrations"}
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in skip_dirs]
        for fn in fns:
            if not fn.endswith(".py"):
                continue
            full = os.path.join(dp, fn)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if rel in ("db.py", "conftest.py"):
                continue
            try:
                lines = open(full, encoding="utf-8").read().splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for i, ln in enumerate(lines, 1):
                code = _code_part(ln)
                if not code.strip():
                    continue
                if _A_RE.search(code) and not re.match(r"\s*(def|from|import)\b", code):
                    a.append({"file": rel, "line": i, "text": code.strip()[:140]})
                if "role" in code and _ROLE_LIT_RE.search(code) and not re.match(r"\s*(def|from|import)\b", code):
                    ent = {"file": rel, "line": i, "text": code.strip()[:140]}
                    if _FIN_LIT_RE.search(code):
                        (b_in if rel in D5_IN_SCOPE else b_out_fin).append(ent)
                    else:
                        b_out_as.append(ent)
    return {"A": a, "B_included": b_in, "B_notIncluded_finance": b_out_fin, "B_notIncluded_admin_sales": b_out_as,
            "d5InScopeRemaining": [x for x in b_in if x["file"] in D5_IN_SCOPE]}


# ═════════════════════════ CLI ═════════════════════════

def _print_v2(res):
    print("比對 %d 位使用者；差異 %d 筆；結構問題 %d 筆；獨立重算不一致 %d 筆；快照後新增／其他資訊 %d 筆%s" % (
        res.get("checked", 0), len(res["diffs"]), len(res["structure"]), len(res.get("specMismatch") or []), len(res["info"]),
        "；順序不同 %d 位（資訊）" % len(res["orderOnly"]) if res["orderOnly"] else ""))
    for s in res["structure"]:
        print("  ‼ 結構：%s" % s)
    for d in res["diffs"] + (res.get("specMismatch") or []):
        extra = ""
        if d.get("lost"):
            extra += "；少 " + "、".join(d["lost"])
        if d.get("gained"):
            extra += "；多 " + "、".join(d["gained"])
        if d.get("expectLost") or d.get("expectGained"):
            extra += "；計畫預期 少[%s] 多[%s]" % ("、".join(d.get("expectLost") or []), "、".join(d.get("expectGained") or []))
        print("  ✗ %s（id %s）[%s]：%s%s" % (d.get("username") or d.get("role") or "", d.get("id", ""), d.get("facet", ""), d["problem"], extra))
    cut = res.get("cutover")
    if cut:
        for v in cut["violations"]:
            print("  ‼ 切換前置：%s" % v)
        for u, m in cut["expectedDiffMismatch"].items():
            print("  ✗ 切換差異與計畫不符（id %s）：預期 %s／實際 %s" % (u, m["expected"], m["actual"]))
    for i in res["info"]:
        print("  ℹ %s" % i)
    print("結果：%s" % {0: "PASS", 1: "FAIL（有差異；不可放行／要回滾）", 3: "FAIL（結構問題；不可放行）"}[res["code"]])


def _read_json(path, what):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:                              # noqa: BLE001
        return None, "讀不到%s：%s" % (what, e)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s1 = sub.add_parser("snapshot")
    s1.add_argument("--out", required=True)
    s1.add_argument("--db")
    s1.add_argument("--schema", type=int, choices=(1, 2), default=1)
    s2 = sub.add_parser("verify")
    s2.add_argument("--snapshot", required=True)
    s2.add_argument("--db")
    s2.add_argument("--plan")
    s2.add_argument("--json-out")
    s2.add_argument("--finance-cutover", action="store_true")
    s3 = sub.add_parser("diff")
    s3.add_argument("--a", required=True)
    s3.add_argument("--b", required=True)
    s3.add_argument("--plan")
    s3.add_argument("--json-out")
    s4 = sub.add_parser("catalog-check")
    s4.add_argument("--db")
    s4.add_argument("--json-out")
    s5 = sub.add_parser("scan-finance")
    s5.add_argument("--root")
    s5.add_argument("--json-out")
    a = ap.parse_args(argv)

    def _dump(path, obj):
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False, indent=1)

    if a.cmd == "scan-finance":
        res = scan_finance(a.root)
        print("A（跟著新縫走）%d 處；B-納入 %d 處（D5 範圍內仍寫死 %d 處）；B-未納入 finance %d 處；B-未納入 admin／sales %d 處（「部分生效」來源）" % (
            len(res["A"]), len(res["B_included"]), len(res["d5InScopeRemaining"]), len(res["B_notIncluded_finance"]), len(res["B_notIncluded_admin_sales"])))
        for k in ("d5InScopeRemaining", "B_notIncluded_finance"):
            for e in res[k]:
                print("  %s %s:%s  %s" % ("‼" if k == "d5InScopeRemaining" else "·", e["file"], e["line"], e["text"]))
        _dump(a.json_out, res)
        return 0
    if a.cmd == "diff":
        sa, e1 = _read_json(a.a, "快照 a")
        sb, e2 = _read_json(a.b, "快照 b")
        plan, e3 = _read_json(a.plan, "計畫檔") if a.plan else (None, None)
        if e1 or e2 or e3:
            print(e1 or e2 or e3)
            return 2
        res = diff_snapshots(sa, sb, plan)
        res["checked"] = len(sa.get("users") or {})
        _print_v2(res)
        _dump(a.json_out, res)
        return res["code"]
    try:
        conn = _connect(a.db)
    except Exception as e:                              # noqa: BLE001
        print("讀不到資料庫：%s" % e)
        return 2
    try:
        if a.cmd == "catalog-check":
            try:
                res = catalog_check(conn)
            except Exception as e:                      # noqa: BLE001
                print("讀不到資料庫內容：%s" % e)
                return 2
            print("目錄鍵 %d 個；superadmin %d 位" % (len(res["catalog"]), len(res["superadmins"])))
            for s in res["superadmins"]:
                print("  superadmin id %s：缺 %s" % (s["id"], "、".join(s["missing"]) or "（無）"))
            print("缺哪些鍵（聯集）：%s" % ("、".join(res["missingUnion"]) or "（無）"))
            _dump(a.json_out, res)
            return 0
        if a.cmd == "snapshot":
            if a.schema == 2:
                snap = take_snapshot2(conn)
                snap["dbPath"] = os.path.basename(a.db or "")
            else:
                snap = take_snapshot(conn)
            with open(a.out, "w", encoding="utf-8") as f:
                json.dump(snap, f, ensure_ascii=False, indent=1)
            print("已存快照（schema %d）：%d 位使用者 → %s" % (a.schema, len(snap["users"]), a.out))
            return 0
        snap, err = _read_json(a.snapshot, "快照")
        plan, perr = _read_json(a.plan, "計畫檔") if a.plan else (None, None)
        if err or perr:
            print(err or perr)
            return 2
        if (snap or {}).get("schema") != 2:
            if a.plan or a.finance_cutover:
                print("schema 1 快照不支援 --plan／--finance-cutover（請用 --schema 2 重拍）")
                return 3
            res = verify(conn, snap)
            print("比對 %d 位使用者；差異 %d 位；快照後新增 %d 位（資訊）" % (res["checked"], len(res["diffs"]), len(res["new_users"])))
            for d in res["diffs"]:
                print("  ✗ %s（%s）：%s%s%s" % (d.get("username"), d.get("role", ""), d["problem"],
                                              "；失去 " + "、".join(d["lost"]) if d.get("lost") else "",
                                              "；多出 " + "、".join(d["gained"]) if d.get("gained") else ""))
            print("結果：%s" % ("PASS（逐人相同）" if not res["diffs"] else "FAIL（不可上線／要回滾）"))
            return 0 if not res["diffs"] else 1
        res = verify2(conn, snap, plan, finance_cutover=a.finance_cutover)
        now = res.pop("now")
        _print_v2(res)
        if a.json_out:
            res["now"] = {"takenAt": now["takenAt"], "users": len(now["users"])}
            _dump(a.json_out, res)
        return res["code"]
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
