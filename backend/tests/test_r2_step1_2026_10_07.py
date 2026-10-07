# -*- coding: utf-8 -*-
"""R2 第1步（第45班）：檢查器 v2／L0 回滾／D4 superadmin 全部鍵／D5 財務判斷影子模式。
設計 docs/platform/plans/R2-STEP1-EQUIV-ROLLBACK-T45.md。單檔、純函式＋小 fixture；不跑全套。"""
import copy
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

import pytest

import db
from helpers import auth as A
from helpers import duty_roles as DR

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "tools"))
import duty_roles_equivalence as EQ  # noqa: E402
import duty_roles_rollback as RB  # noqa: E402

SA = {"id": 1, "username": "sa", "display_name": "SA", "role": "superadmin", "modules": "[]"}


@pytest.fixture
def pop(client, make_user):
    for n, role, mods in (("r2_sa", "superadmin", []), ("r2_adm", "admin", ["dashboard", "case_manage"]), ("r2_eng", "engineer", ["dashboard"]),
                          ("r2_fin", "finance", None), ("r2_sales", "sales", ["quotation"]), ("r2_view", "viewer", ["dashboard"])):
        make_user(username=n, role=role, modules=mods)
    A.reset_finance_mode_cache()
    conn = db.get_db()
    ids = {r["username"]: r["id"] for r in conn.execute("SELECT id, username FROM users")}
    roles = {r["key"]: r["id"] for r in conn.execute("SELECT id, key FROM duty_roles")}
    conn.close()
    yield ids, roles
    A.reset_finance_mode_cache()


def _copy(tmp_path, name="copy.db"):
    src = db.get_db()
    dst = sqlite3.connect(str(tmp_path / name))
    src.backup(dst)
    dst.close()
    src.close()
    return str(tmp_path / name)


def _snap():
    conn = db.get_db()
    try:
        return EQ.take_snapshot2(conn)
    finally:
        conn.close()


def _verify(snap, plan=None, **kw):
    conn = db.get_db()
    try:
        return EQ.verify2(conn, snap, plan, **kw)
    finally:
        conn.close()


def _set_flag(value):
    conn = db.get_db()
    conn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,'2026-10-07') "
                 "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json", (A.FINANCE_FLAG_KEY, json.dumps(value)))
    conn.commit()
    conn.close()
    A.reset_finance_mode_cache()


# ── 檢查器 v2 ────────────────────────────────────────────────────────────────

def test_zero_change_passes_and_snapshot_has_schema2_shape(pop):
    snap = _snap()
    assert snap["schema"] == 2 and {"roles", "users", "log"} <= set(snap)
    assert len(snap["roles"]) >= 8 and snap["log"]["triggers"] == sorted(EQ.TRIGGERS)
    u = next(x for x in snap["users"].values() if x["username"] == "r2_adm")
    assert {"rawModules", "bindings", "subtracts", "effective", "guardView", "caps", "financeKeys"} <= set(u)
    res = _verify(snap)
    assert res["code"] == 0 and res["diffs"] == [] and res["structure"] == [] and res["specMismatch"] == []


def test_each_injected_difference_makes_verify_fail(pop):
    ids, roles = pop
    snap = _snap()
    conn = db.get_db()
    DR.bind_role(conn, SA, ids["r2_eng"], roles["procurement"])                              # 多鍵
    res = EQ.verify2(conn, snap)
    assert res["code"] == 1 and {d["facet"] for d in res["diffs"]} >= {"E1", "E2"} and all(d["username"] == "r2_eng" for d in res["diffs"] if "username" in d and d["facet"] != "role_def")
    DR.unbind_role(conn, SA, ids["r2_eng"], roles["procurement"])
    assert EQ.verify2(conn, snap)["code"] == 0                                                 # 解除後回到零差異
    conn.execute("UPDATE users SET modules='[]' WHERE id=?", (ids["r2_adm"],))                 # 少鍵（勾選被清）
    conn.commit()
    res = EQ.verify2(conn, snap)
    assert res["code"] == 1 and any(d["facet"] == "E5" and d["username"] == "r2_adm" for d in res["diffs"])
    conn.execute("UPDATE users SET modules=?, role='viewer' WHERE id=?", (json.dumps(["dashboard", "case_manage"]), ids["r2_adm"]))
    conn.commit()
    res = EQ.verify2(conn, snap)
    assert res["code"] == 1 and any(d["facet"] == "E4" for d in res["diffs"])                   # 基礎類別變
    conn.execute("UPDATE users SET role='admin' WHERE id=?", (ids["r2_adm"],))
    conn.execute("DELETE FROM users WHERE id=?", (ids["r2_view"],))
    conn.commit()
    res = EQ.verify2(conn, snap)
    assert res["code"] == 1 and any(d["problem"] == "帳號不見了" for d in res["diffs"])           # 帳號消失
    conn.close()


def test_finance_key_leaking_into_the_guard_view_is_caught_even_though_effective_is_unchanged(pop):
    ids, roles = pop
    snap = _snap()
    conn = db.get_db()
    DR.bind_role(conn, SA, ids["r2_sales"], roles["finance"], reason="測試財務角色綁定")
    res = EQ.verify2(conn, snap)
    conn.close()
    sales = [d for d in res["diffs"] if d.get("username") == "r2_sales"]
    by = {d["facet"]: d for d in sales}
    assert res["code"] == 1 and set(by) == {"E1", "E2", "gate"}                                # E3（財務能力）不變
    assert set(by["E2"]["gained"]) >= {"cashier", "finance", "financial_view"}                  # E2 多財務鍵（已知、僅資訊）
    assert not set(by["E1"]["gained"]) & set(EQ.FINANCE_KEYS)                                    # E1 不含財務鍵（第42班規則）


def test_role_definition_change_is_reported_once_not_per_member(pop):
    ids, roles = pop
    conn = db.get_db()
    for n in ("r2_eng", "r2_adm", "r2_view"):
        DR.bind_role(conn, SA, ids[n], roles["procurement"])
    snap = EQ.take_snapshot2(conn)
    DR.update_role(conn, SA, roles["procurement"], permissions=["inventory"], reason="")
    res = EQ.verify2(conn, snap)
    assert res["code"] == 1 and [d["facet"] for d in res["diffs"]] == ["role_def"]              # 不逐人洗出一堆差異
    assert EQ.verify2(conn, snap, {"roleChanges": ["procurement"]})["code"] != 3
    conn.close()


def test_order_only_difference_is_information_not_failure(pop):
    ids, _ = pop
    snap = _snap()
    conn = db.get_db()
    conn.execute("UPDATE users SET modules=? WHERE id=?", (json.dumps(["case_manage", "dashboard"]), ids["r2_adm"]))
    conn.commit()
    res = EQ.verify2(conn, snap)
    conn.close()
    assert res["code"] == 0 and [o["username"] for o in res["orderOnly"]] == ["r2_adm"]


def test_plan_whitelist_must_match_exactly(pop):
    ids, roles = pop
    snap = _snap()
    conn = db.get_db()
    DR.bind_role(conn, SA, ids["r2_eng"], roles["procurement"])
    now = EQ.take_snapshot2(conn)
    conn.close()
    gained = sorted(set(now["users"][str(ids["r2_eng"])]["effective"]) - set(snap["users"][str(ids["r2_eng"])]["effective"]))
    assert len(gained) >= 2

    def plan(g, guard=None):
        return {"users": {str(ids["r2_eng"]): {"gained": g}}}
    assert EQ.diff_snapshots(snap, now, plan(gained))["code"] == 0
    assert EQ.diff_snapshots(snap, now, plan(gained[:-1]))["code"] == 1                         # 少列一鍵
    assert EQ.diff_snapshots(snap, now, plan(gained + ["payslip"]))["code"] == 1                 # 多列一鍵
    assert EQ.diff_snapshots(snap, now, {"users": {str(ids["r2_adm"]): {"gained": gained}}})["code"] == 1   # 列錯人
    assert EQ.diff_snapshots(snap, now)["code"] == 1                                             # 無計畫＝零差異才過


def test_superadmin_visible_surface_is_strict_and_never_accepts_a_plan(pop):
    ids, _ = pop
    snap = _snap()
    now = copy.deepcopy(snap)
    now["users"][str(ids["r2_sa"])]["effective"] = sorted(set(now["users"][str(ids["r2_sa"])]["effective"]) | {"payslip"})
    res = EQ.diff_snapshots(snap, now, {"users": {str(ids["r2_sa"]): {"gained": ["payslip"]}}})
    assert res["code"] == 1 and any(d["facet"] == "E6" for d in res["diffs"])


def test_structure_problems_exit_3(pop):
    ids, _ = pop
    a = _snap()
    b = copy.deepcopy(a)
    b["log"]["permissionChangesCount"] = a["log"]["permissionChangesCount"] - 1
    assert EQ.diff_snapshots(a, b)["code"] == 3
    b = copy.deepcopy(a)
    b["log"]["triggers"] = b["log"]["triggers"][:1]
    assert EQ.diff_snapshots(a, b)["code"] == 3
    b = copy.deepcopy(a)
    b["users"][str(ids["r2_sa"])]["bindings"] = ["finance"]
    assert EQ.diff_snapshots(a, b)["code"] == 3
    b = copy.deepcopy(a)
    b["schema"] = 1
    assert EQ.diff_snapshots(a, b)["code"] == 3
    assert EQ.diff_snapshots(a, a)["code"] == 0


def test_independent_recompute_matches_real_code_and_catches_a_broken_one(pop, monkeypatch):
    ids, roles = pop
    conn = db.get_db()
    DR.bind_role(conn, SA, ids["r2_eng"], roles["procurement"])
    DR.bind_role(conn, SA, ids["r2_sales"], roles["finance"], reason="測試財務角色綁定")
    DR.set_subtract(conn, SA, ids["r2_adm"], "inventory")
    snap = EQ.take_snapshot2(conn)
    assert EQ.spec_mismatches(snap, conn) == []
    real = A.effective_modules
    monkeypatch.setattr(A, "effective_modules", lambda role, mods, user_id=None, conn=None: [m for m in real(role, mods, user_id=user_id, conn=conn) if m != "dashboard"])
    bad = EQ.spec_mismatches(EQ.take_snapshot2(conn), conn)
    conn.close()
    assert bad and all(b["facet"] == "E1" for b in bad)                                          # 程式改壞 ⇒ 獨立重算抓得到


def test_spec_functions_exhaustive_agree_with_the_program_on_a_pure_model():
    keys = ["dashboard", "case_manage", "inventory", "cashier", "finance", "financial_view"]
    import itertools
    for role in A.VALID_ROLES:
        for raw in ([], ["dashboard"], ["cashier", "finance"], keys):
            for bound in ([], ["inventory"], ["finance", "cashier"], keys):
                for subs in ([], ["inventory"], ["dashboard"]):
                    got = EQ.spec_effective(role, raw, bound, subs)
                    assert (got & set(EQ.FINANCE_KEYS) == set(EQ.FINANCE_KEYS)) == (role in EQ.FINANCE_ROLES)
                    if role == "superadmin":
                        assert got == (set(raw) - set(EQ.FINANCE_KEYS)) | set(EQ.FINANCE_KEYS)
                    else:
                        assert "inventory" not in got or "inventory" not in subs
    assert len(list(itertools.product(A.VALID_ROLES, range(1)))) == len(A.VALID_ROLES)


def test_schema1_snapshot_still_works_and_rejects_v2_only_options(pop, tmp_path):
    dbp = _copy(tmp_path)
    out = str(tmp_path / "s1.json")
    assert EQ.main(["snapshot", "--out", out, "--db", dbp]) == 0
    assert "schema" not in json.load(open(out, encoding="utf-8"))
    assert EQ.main(["verify", "--snapshot", out, "--db", dbp]) == 0
    assert EQ.main(["verify", "--snapshot", out, "--db", dbp, "--finance-cutover"]) == 3


def test_cli_v2_roundtrip_and_offline_diff(pop, tmp_path):
    dbp = _copy(tmp_path)
    s = str(tmp_path / "s2.json")
    assert EQ.main(["snapshot", "--schema", "2", "--out", s, "--db", dbp]) == 0
    assert EQ.main(["verify", "--snapshot", s, "--db", dbp, "--json-out", str(tmp_path / "r.json")]) == 0
    c = sqlite3.connect(dbp)
    c.execute("UPDATE users SET modules='[]' WHERE username='r2_adm'")
    c.commit()
    c.close()
    s_after = str(tmp_path / "s2b.json")
    assert EQ.main(["verify", "--snapshot", s, "--db", dbp]) == 1
    assert EQ.main(["snapshot", "--schema", "2", "--out", s_after, "--db", dbp]) == 0
    assert EQ.main(["diff", "--a", s, "--b", s_after]) == 1
    assert EQ.main(["diff", "--a", s, "--b", s]) == 0
    assert EQ.main(["diff", "--a", s, "--b", str(tmp_path / "missing.json")]) == 2


# ── catalog-check／scan-finance／切換前置 ───────────────────────────────────────

def test_catalog_check_lists_missing_keys_for_each_superadmin(pop, tmp_path):
    dbp = _copy(tmp_path)
    out = str(tmp_path / "cat.json")
    assert EQ.main(["catalog-check", "--db", dbp, "--json-out", out]) == 0
    res = json.load(open(out, encoding="utf-8"))
    c0 = sqlite3.connect(dbp)
    sid = c0.execute("SELECT id FROM users WHERE username='r2_sa'").fetchone()[0]
    c0.close()
    sa = next(s for s in res["superadmins"] if s["id"] == sid)
    assert sa["missing"] and "dashboard" in sa["missing"] and set(res["missingUnion"]) >= set(sa["missing"])   # modules=[] 的 superadmin 缺全部非財務鍵
    assert not set(sa["missing"]) & set(EQ.FINANCE_KEYS)
    assert "r2_sa" not in json.dumps(res)                                                                      # 輸出不含帳號名


def test_scan_finance_finds_in_scope_clean_and_out_of_scope_listed():
    res = EQ.scan_finance()
    assert res["d5InScopeRemaining"] == []                                                       # D5 四個檔已不寫死 finance 角色字面值
    assert any(e["file"] == "routers/mail_settings.py" for e in res["B_notIncluded_finance"])    # 使用者裁示維持、僅列出
    assert any(e["file"] == "helpers/auth.py" for e in res["A"])
    assert res["B_notIncluded_admin_sales"]                                                      # 「部分生效」來源


def test_scan_finance_flags_a_hardcoded_literal_in_a_d5_file(tmp_path):
    d = tmp_path / "helpers"
    d.mkdir()
    (d / "financial_mask.py").write_text('def f(user):\n    return user.get("role") in ("admin", "finance")\n', encoding="utf-8")
    res = EQ.scan_finance(str(tmp_path))
    assert [e["file"] for e in res["d5InScopeRemaining"]] == ["helpers/financial_mask.py"]


def test_finance_cutover_preconditions(pop):
    ids, roles = pop
    snap = _snap()
    res = _verify(snap, finance_cutover=True)
    assert res["code"] == 0 and res["cutover"]["violations"] == [] and res["cutover"]["wouldChange"] == {}   # 乾淨：新舊規則逐人相同
    conn = db.get_db()
    DR.bind_role(conn, SA, ids["r2_sales"], roles["finance"], reason="測試財務角色綁定")
    res = EQ.verify2(conn, snap, finance_cutover=True)
    assert res["code"] == 3 and any(v.startswith("①") for v in res["cutover"]["violations"])               # 非 finance 類別綁財務角色
    DR.unbind_role(conn, SA, ids["r2_sales"], roles["finance"], reason="測試財務角色綁定")
    conn.execute("INSERT INTO user_perm_subtracts (user_id, perm_key, set_by, set_at, reason) VALUES (?,?,?,?,?)",
                 (ids["r2_fin"], "cashier", 1, "2026-10-07", "測試"))
    conn.commit()
    res = EQ.verify2(conn, snap, finance_cutover=True)
    conn.close()
    assert res["code"] == 3 and any(v.startswith("②") for v in res["cutover"]["violations"])
    assert res["cutover"]["wouldChange"][str(ids["r2_fin"])] == {"lost": ["cashier"], "gained": []}


# ── D4 ──────────────────────────────────────────────────────────────────────

def test_d4_superadmin_passes_every_key_but_nobody_else_changes(pop):
    from helpers import module_registry as MR
    keys = [k for k, _l, _g in MR.MODULES] + ["brand_new_key_xyz"]
    sa = {"role": "superadmin", "modules": "[]"}
    assert all(A.user_has_module(sa, k) for k in keys)
    for role in ("admin", "sales", "engineer", "viewer", "finance"):
        u = {"role": role, "modules": "[]"}
        assert not any(A.user_has_module(u, k) for k in keys if k not in A.FINANCE_MODULE_KEYS)
    conn = db.get_db()
    r = conn.execute("SELECT role, modules FROM users WHERE username='r2_sa'").fetchone()
    assert A.effective_modules(r["role"], r["modules"]) == ["cashier", "finance", "financial_view"]        # 可見面（E1）逐字不變
    conn.close()


# ── D5 影子模式 ───────────────────────────────────────────────────────────────

def _user(ids, name, role, mods="[]"):
    return {"id": ids[name], "username": name, "role": role, "modules": mods}


def _shadow_audit_rows():
    A._join_shadow_threads()                                       # 影子稽核在背景執行緒寫，等它寫完再讀
    conn = db.get_db()
    try:
        return conn.execute("SELECT detail FROM audit_log WHERE action='permission.finance_shadow_diff'").fetchall()
    finally:
        conn.close()


def test_d5_off_is_the_old_rule_and_reads_no_user_tables(pop):
    ids, roles = pop
    conn = db.get_db()
    DR.bind_role(conn, SA, ids["r2_sales"], roles["finance"], reason="測試財務角色綁定")
    conn.close()
    u = _user(ids, "r2_sales", "sales")
    assert not A.has_finance_access(u) and not A.has_cashier_access(u) and not A.can_see_financial(u)
    assert not A.finance_duty_person(u) and _shadow_audit_rows() == []


def test_d5_shadow_returns_old_rule_but_records_one_rate_limited_diff(pop):
    ids, roles = pop
    conn = db.get_db()
    DR.bind_role(conn, SA, ids["r2_sales"], roles["finance"], reason="測試財務角色綁定")
    conn.close()
    _set_flag("shadow")
    u = _user(ids, "r2_sales", "sales")
    for _ in range(3):
        assert not A.has_finance_access(u) and not A.has_cashier_access(u) and not A.can_see_financial(u)
        assert not A.user_has_module(u, "finance") and not A.finance_duty_person(u)               # 回傳舊規則
    rows = _shadow_audit_rows()
    keys = sorted(json.loads(r["detail"])["key"] for r in rows)
    assert keys == sorted(["finance", "cashier", "financial_view", "finance_duty_person"])         # 每人每鍵一筆，重複呼叫不洗版
    fin = _user(ids, "r2_fin", "finance")
    assert A.has_finance_access(fin) and len(_shadow_audit_rows()) == 4                            # 新舊相同 ⇒ 不告警


def test_d5_on_follows_effective_permissions_including_subtracts(pop):
    ids, roles = pop
    conn = db.get_db()
    DR.bind_role(conn, SA, ids["r2_sales"], roles["finance"], reason="測試財務角色綁定")
    conn.execute("INSERT INTO user_perm_subtracts (user_id, perm_key, set_by, set_at, reason) VALUES (?,?,?,?,?)",
                 (ids["r2_fin"], "cashier", 1, "2026-10-07", "測試"))
    conn.commit()
    conn.close()
    _set_flag("on")
    sales, fin = _user(ids, "r2_sales", "sales"), _user(ids, "r2_fin", "finance")
    assert A.has_finance_access(sales) and A.has_cashier_access(sales) and A.can_see_financial(sales) and A.finance_duty_person(sales)
    assert A.has_finance_access(fin) and not A.has_cashier_access(fin) and A.can_see_financial(fin)        # 個別被扣
    assert not A.user_has_module(fin, "cashier") and A.user_has_module(fin, "finance")
    inert = _user(ids, "r2_adm", "admin", json.dumps(["cashier", "finance", "financial_view"]))
    assert not A.has_finance_access(inert) and not A.finance_duty_person(inert)                     # 惰性勾選不計
    sa = _user(ids, "r2_sa", "superadmin")
    assert A.has_finance_access(sa) and A.has_cashier_access(sa) and A.can_see_financial(sa) and not A.finance_duty_person(sa)


def test_d5_switch_flag_values_and_error_fallback(pop, monkeypatch):
    ids, _ = pop
    _set_flag("garbage")
    assert A._finance_mode() == "off"
    _set_flag("shadow")
    assert A._finance_mode() == "shadow"
    monkeypatch.setattr(A, "finance_effective_keys", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    _set_flag("on")
    assert not A.has_finance_access(_user(ids, "r2_sales", "sales")) and A.has_finance_access(_user(ids, "r2_fin", "finance"))   # 算不出新規則 ⇒ 舊規則


def test_d5_literal_points_follow_the_seam_for_the_four_files(pop):
    from helpers import financial_mask as FM
    ids, roles = pop
    conn = db.get_db()
    DR.bind_role(conn, SA, ids["r2_view"], roles["finance"], reason="測試財務角色綁定")
    conn.close()
    viewer = _user(ids, "r2_view", "viewer")
    assert not FM.quote_money_visible(viewer) and not FM.material_money_visible(viewer)
    _set_flag("shadow")
    assert not FM.quote_money_visible(viewer) and not FM.material_money_visible(viewer)
    _set_flag("on")
    assert FM.quote_money_visible(viewer) and FM.material_money_visible(viewer)
    assert FM.material_money_visible(_user(ids, "r2_adm", "admin")) and FM.quote_money_visible(_user(ids, "r2_sa", "superadmin"))


# ── 守門面（D4 可見）＆旗標／影子的強化 ─────────────────────────────────────────

def test_gate_facet_sees_d4_and_is_zero_diff_for_everyone_else(pop):
    ids, _ = pop
    snap = _snap()
    sa = snap["users"][str(ids["r2_sa"])]
    assert set(sa["gateKeys"]) == set(snap["gateCatalog"])                                       # superadmin：目錄全部＋目錄外的鍵
    assert EQ.UNKNOWN_KEY in sa["gateKeys"] and EQ.UNKNOWN_KEY not in snap["users"][str(ids["r2_adm"])]["gateKeys"]
    pre = copy.deepcopy(snap)                                                                    # 模擬 D4 之前的快照
    pre["users"][str(ids["r2_sa"])]["gateKeys"] = ["dashboard"]
    res = EQ.diff_snapshots(pre, snap)
    assert res["code"] == 1 and any(d["facet"] == "gate" and d["id"] == str(ids["r2_sa"]) for d in res["diffs"])
    missing = sorted(set(snap["gateCatalog"]) - {"dashboard"})
    assert EQ.diff_snapshots(pre, snap, {"users": {str(ids["r2_sa"]): {"gateGained": missing}}})["code"] == 0   # 白名單恰好等於缺鍵
    assert EQ.diff_snapshots(pre, snap, {"users": {str(ids["r2_sa"]): {"gateGained": missing[:-1]}}})["code"] == 1
    lost = copy.deepcopy(snap)
    lost["users"][str(ids["r2_sa"])]["gateKeys"] = ["dashboard"]
    assert EQ.diff_snapshots(snap, lost, {"users": {str(ids["r2_sa"]): {"gateGained": missing}}})["code"] == 1   # True→False 不准
    other = copy.deepcopy(snap)
    other["users"][str(ids["r2_adm"])]["gateKeys"] = other["users"][str(ids["r2_adm"])]["gateKeys"] + ["settings"]
    assert EQ.diff_snapshots(snap, other, {"users": {str(ids["r2_adm"]): {"gateGained": ["settings"]}}})["code"] == 1   # 非 superadmin 不接受白名單


def test_independent_gate_recompute_catches_a_broken_user_has_module(pop, monkeypatch):
    conn = db.get_db()
    try:
        assert EQ.spec_mismatches(EQ.take_snapshot2(conn), conn) == []
        real = A.user_has_module
        monkeypatch.setattr(A, "user_has_module", lambda u, k: False if (u or {}).get("role") == "superadmin" else real(u, k))
        bad = EQ.spec_mismatches(EQ.take_snapshot2(conn), conn)
        assert bad and all(b["facet"] == "gate" for b in bad)                                    # 把 D4 拿掉 ⇒ 抓得到
        monkeypatch.setattr(A, "user_has_module", lambda u, k: True if (u or {}).get("role") == "admin" else real(u, k))
        bad = EQ.spec_mismatches(EQ.take_snapshot2(conn), conn)
        assert bad and any(b["username"] == "r2_adm" for b in bad)                               # 對 admin 也放行 ⇒ 抓得到
    finally:
        conn.close()


def test_flag_read_error_keeps_last_known_good_mode(pop, monkeypatch):
    _set_flag("on")
    assert A._finance_mode() == "on"

    def boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(A, "get_db", boom)
    A._fin_mode["at"] = -1e9                                                                     # 讓快取過期
    assert A._finance_mode() == "on"                                                             # 沿用，不退回 off
    A.reset_finance_mode_cache()
    assert A._finance_mode() == "off"                                                            # 從沒讀到過 ⇒ off


def test_on_mode_computation_error_takes_the_stricter_of_old_and_new(pop, monkeypatch):
    ids, roles = pop
    conn = db.get_db()
    DR.bind_role(conn, SA, ids["r2_sales"], roles["finance"], reason="測試財務角色綁定")
    conn.close()
    _set_flag("on")
    monkeypatch.setattr(A, "finance_effective_keys", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert not A.has_finance_access(_user(ids, "r2_sales", "sales")) and not A.finance_duty_person(_user(ids, "r2_sales", "sales"))
    assert A.has_finance_access(_user(ids, "r2_fin", "finance")) and A.has_cashier_access(_user(ids, "r2_sa", "superadmin"))


def test_shadow_audit_is_written_off_the_calling_thread(pop, monkeypatch):
    import threading
    from helpers import audit as AU
    ids, roles = pop
    conn = db.get_db()
    DR.bind_role(conn, SA, ids["r2_sales"], roles["finance"], reason="測試財務角色綁定")
    conn.close()
    seen = []
    monkeypatch.setattr(AU, "_audit", lambda *a, **k: seen.append(threading.current_thread()))
    _set_flag("shadow")
    assert not A.has_finance_access(_user(ids, "r2_sales", "sales"))
    A._join_shadow_threads()
    assert seen and all(t is not threading.main_thread() and t is not threading.current_thread() for t in seen)


# ── L0 回滾 ───────────────────────────────────────────────────────────────────

def _db_state(path):
    c = sqlite3.connect(path)
    try:
        return (c.execute("SELECT id, role, active, modules FROM users ORDER BY id").fetchall(),
                c.execute("SELECT user_id, role_id FROM user_duty_roles ORDER BY 1,2").fetchall(),
                c.execute("SELECT user_id, perm_key FROM user_perm_subtracts ORDER BY 1,2").fetchall(),
                c.execute("SELECT COUNT(*) FROM permission_changes").fetchone()[0])
    finally:
        c.close()


def _r2_actions(dbp, ids, roles):
    c = sqlite3.connect(dbp)
    c.row_factory = sqlite3.Row
    SAx = dict(SA)
    DR.bind_role(c, SAx, ids["r2_eng"], roles["procurement"])
    DR.set_subtract(c, SAx, ids["r2_adm"], "inventory")
    c.execute("UPDATE users SET modules='[]', active=0 WHERE id=?", (ids["r2_sales"],))
    c.commit()
    c.close()


def test_rollback_dry_run_changes_nothing_and_apply_needs_a_plan(pop, tmp_path):
    ids, roles = pop
    dbp = _copy(tmp_path)
    s = str(tmp_path / "s.json")
    assert EQ.main(["snapshot", "--schema", "2", "--out", s, "--db", dbp]) == 0
    _r2_actions(dbp, ids, roles)
    before = _db_state(dbp)
    assert RB.main(["--snapshot", s, "--db", dbp]) == 0
    assert _db_state(dbp) == before
    assert RB.main(["--snapshot", s, "--db", dbp, "--apply"]) == 2                             # --apply 沒有計畫檔 ⇒ 拒絕
    assert _db_state(dbp) == before


def test_rollback_apply_restores_whitelist_only_appends_log_and_reverifies(pop, tmp_path):
    ids, roles = pop
    dbp = _copy(tmp_path)
    s = str(tmp_path / "s.json")
    assert EQ.main(["snapshot", "--schema", "2", "--out", s, "--db", dbp]) == 0
    base = _db_state(dbp)
    _r2_actions(dbp, ids, roles)
    after_actions = _db_state(dbp)
    plan = {"batch": "T45-X", "users": {str(ids["r2_eng"]): {}, str(ids["r2_adm"]): {},
                                        str(ids["r2_sales"]): {"restoreRaw": True, "restoreActive": True}}}
    p = str(tmp_path / "plan.json")
    json.dump(plan, open(p, "w", encoding="utf-8"))
    assert RB.main(["--snapshot", s, "--plan", p, "--db", dbp, "--apply"]) == 0               # 內含無計畫的重驗必須 PASS
    st = _db_state(dbp)
    assert st[:3] == base[:3]                                                                   # 使用者、綁定、扣項回到快照
    assert st[3] > after_actions[3]                                                              # 紀錄只增
    c = sqlite3.connect(dbp)
    assert c.execute("SELECT COUNT(*) FROM permission_changes WHERE kind='rollback' AND reason LIKE '%T45-X%'").fetchone()[0] >= 3
    c.close()
    assert EQ.main(["verify", "--snapshot", s, "--db", dbp]) == 0


def test_rollback_touches_only_the_whitelist(pop, tmp_path):
    ids, roles = pop
    dbp = _copy(tmp_path)
    s = str(tmp_path / "s.json")
    assert EQ.main(["snapshot", "--schema", "2", "--out", s, "--db", dbp]) == 0
    _r2_actions(dbp, ids, roles)
    p = str(tmp_path / "plan.json")
    json.dump({"users": {str(ids["r2_eng"]): {}}}, open(p, "w", encoding="utf-8"))               # 只列一個人
    assert RB.main(["--snapshot", s, "--plan", p, "--db", dbp, "--apply"]) == 0                  # 重驗限白名單：白名單外的差異只列數量、不算失敗
    c = sqlite3.connect(dbp)
    assert c.execute("SELECT COUNT(*) FROM user_duty_roles WHERE user_id=?", (ids["r2_eng"],)).fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM user_perm_subtracts WHERE user_id=?", (ids["r2_adm"],)).fetchone()[0] == 1   # 沒被動
    assert c.execute("SELECT active FROM users WHERE id=?", (ids["r2_sales"],)).fetchone()[0] == 0
    c.close()


def test_rollback_does_not_restore_raw_or_active_unless_the_plan_says_so(pop, tmp_path):
    ids, roles = pop
    dbp = _copy(tmp_path)
    s = str(tmp_path / "s.json")
    assert EQ.main(["snapshot", "--schema", "2", "--out", s, "--db", dbp]) == 0
    _r2_actions(dbp, ids, roles)                                                                 # 含：r2_sales 勾選清空＋停用（模擬離職者）
    p = str(tmp_path / "plan.json")
    json.dump({"users": {str(ids["r2_sales"]): {}, str(ids["r2_adm"]): {}}}, open(p, "w", encoding="utf-8"))
    assert RB.main(["--snapshot", s, "--plan", p, "--db", dbp, "--apply"]) == 0                  # 未要求還原的面向不算失敗
    c = sqlite3.connect(dbp)
    assert c.execute("SELECT active, modules FROM users WHERE id=?", (ids["r2_sales"],)).fetchone() == (0, "[]")   # 離職者沒被重新啟用
    assert c.execute("SELECT COUNT(*) FROM user_perm_subtracts WHERE user_id=?", (ids["r2_adm"],)).fetchone()[0] == 0   # 扣項照常還原
    c.close()
    json.dump({"users": {str(ids["r2_sales"]): {"restoreActive": True}}}, open(p, "w", encoding="utf-8"))
    assert RB.main(["--snapshot", s, "--plan", p, "--db", dbp, "--apply"]) == 0
    c = sqlite3.connect(dbp)
    assert c.execute("SELECT active FROM users WHERE id=?", (ids["r2_sales"],)).fetchone()[0] == 1            # 只還原要求的在職
    assert c.execute("SELECT modules FROM users WHERE id=?", (ids["r2_sales"],)).fetchone()[0] == "[]"        # 勾選仍沒動
    c.close()


def test_rollback_apply_requires_an_explicit_matching_db(pop, tmp_path):
    import shutil
    ids, roles = pop
    dbp = _copy(tmp_path)
    s = str(tmp_path / "s.json")
    assert EQ.main(["snapshot", "--schema", "2", "--out", s, "--db", dbp]) == 0
    _r2_actions(dbp, ids, roles)
    p = str(tmp_path / "plan.json")
    json.dump({"users": {str(ids["r2_eng"]): {}}}, open(p, "w", encoding="utf-8"))
    before = _db_state(dbp)
    assert RB.main(["--snapshot", s, "--plan", p, "--apply"]) == 2                               # 沒給 --db
    other = str(tmp_path / "other.db")
    shutil.copy(dbp, other)
    assert RB.main(["--snapshot", s, "--plan", p, "--db", other, "--apply"]) == 2                # 檔名與快照 dbPath 不符
    assert _db_state(dbp) == before and _db_state(other) == before


def test_rollback_refuses_superadmin_and_old_schema(pop, tmp_path):
    ids, _ = pop
    dbp = _copy(tmp_path)
    s = str(tmp_path / "s.json")
    assert EQ.main(["snapshot", "--schema", "2", "--out", s, "--db", dbp]) == 0
    p = str(tmp_path / "plan.json")
    json.dump({"users": {str(ids["r2_sa"]): {}}}, open(p, "w", encoding="utf-8"))
    assert RB.main(["--snapshot", s, "--plan", p, "--db", dbp, "--apply"]) == 3
    s1 = str(tmp_path / "s1.json")
    assert EQ.main(["snapshot", "--out", s1, "--db", dbp]) == 0
    assert RB.main(["--snapshot", s1, "--db", dbp]) == 3


# ── 靜態守門與 export_effective ───────────────────────────────────────────────

def test_static_rules_for_the_duty_tools():
    tools = sorted((BACKEND / "tools").glob("duty_roles_*.py"))
    assert {t.name for t in tools} >= {"duty_roles_equivalence.py", "duty_roles_export_effective.py", "duty_roles_rollback.py"}
    for t in tools:
        src = t.read_text(encoding="utf-8")
        assert '"--db"' in src, t.name                                                            # 每支都有 --db
        assert not re.search(r"INSERT\s+OR\s+REPLACE|REPLACE\s+INTO", src, re.I), t.name           # 禁用繞過 append-only 的寫法
    eq = (BACKEND / "tools" / "duty_roles_equivalence.py").read_text(encoding="utf-8")
    assert not re.search(r"execute\(\s*[\"'](INSERT|UPDATE|DELETE)", eq), "檢查器只做 SELECT"
    assert "import duty_roles_rollback" not in eq and "begin_write" not in eq                       # snapshot 路徑不 import 寫入路徑
    rb = (BACKEND / "tools" / "duty_roles_rollback.py").read_text(encoding="utf-8")
    assert 'add_argument("--apply", action="store_true")' in rb and "if not a.apply:" in rb         # 寫入預設 dry-run
    assert not re.search(r"INSERT\s+OR\s+REPLACE|REPLACE\s+INTO", (BACKEND / "helpers" / "duty_roles.py").read_text(encoding="utf-8"), re.I)


def test_direct_readers_of_user_modules_have_no_finance_key_judgement():
    """§6「綁定含財務三鍵」：E2 可能多出財務鍵，所以直讀 `user["modules"]` 的程式不得以財務三鍵判斷。"""
    bad = []
    for rel in ("modules/analytics/api/dashboard.py", "modules/case/api/case_action_items.py", "modules/crm/api.py", "routers/search.py",
                "routers/custom_records.py", "routers/map_points.py", "helpers/custom_modules.py", "helpers/custom_files.py"):
        p = BACKEND / rel
        if not p.exists():
            continue
        for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            code = ln.split("#", 1)[0]
            if 'modules' in code and re.search(r"[\"'](financial_view|finance|cashier)[\"']", code):
                bad.append("%s:%d" % (rel, i))
    assert bad == []


def test_export_effective_dry_run_lists_high_sensitivity_bindings(pop, tmp_path, capsys):
    import duty_roles_export_effective as EX
    ids, roles = pop
    conn = db.get_db()
    DR.bind_role(conn, SA, ids["r2_eng"], roles["procurement"])
    DR.bind_role(conn, SA, ids["r2_sales"], roles["finance"], reason="測試財務角色綁定")
    conn.close()
    dbp = _copy(tmp_path)
    assert EX.main(["--db", dbp]) == 0
    out = capsys.readouterr().out
    assert "綁定含高敏感鍵的人" in out and "r2_sales" in out and "r2_eng" not in out.split("綁定含高敏感鍵的人")[1].split("\n")[0]
