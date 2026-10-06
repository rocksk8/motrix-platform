# -*- coding: utf-8 -*-
"""職責角色化 R1 的上線關卡工具與回滾工具（tools/duty_roles_equivalence.py、tools/duty_roles_export_effective.py）。"""
import json
import os
import sqlite3
import sys

import pytest

import db
from helpers import auth as A
from helpers import duty_roles as DR

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import duty_roles_equivalence as EQ  # noqa: E402
import duty_roles_export_effective as EX  # noqa: E402

SA = {"id": 1, "username": "sa", "display_name": "SA", "role": "superadmin", "modules": "[]"}


@pytest.fixture
def pop(client, make_user):
    for n, role, mods in (("tl_sa", "superadmin", None), ("tl_adm", "admin", ["dashboard", "case_manage"]), ("tl_eng", "engineer", ["dashboard"]),
                          ("tl_fin", "finance", None), ("tl_sales", "sales", ["quotation"])):
        make_user(username=n, role=role, modules=mods)
    conn = db.get_db()
    ids = {r["username"]: r["id"] for r in conn.execute("SELECT id, username FROM users")}
    roles = {r["key"]: r["id"] for r in conn.execute("SELECT id, key FROM duty_roles")}
    conn.close()
    return ids, roles


def _db_copy(tmp_path):
    src = db.get_db()
    dst = sqlite3.connect(str(tmp_path / "copy.db"))
    src.backup(dst)
    dst.close()
    src.close()
    return str(tmp_path / "copy.db")


def test_snapshot_then_verify_passes_when_nothing_changed(pop, tmp_path):
    conn = db.get_db()
    snap = EQ.take_snapshot(conn)
    res = EQ.verify(conn, snap)
    conn.close()
    assert res["checked"] >= 5 and res["diffs"] == [] and res["new_users"] == []


def test_verify_catches_a_binding_a_subtract_and_a_role_change_after_the_snapshot(pop):
    ids, roles = pop
    conn = db.get_db()
    snap = EQ.take_snapshot(conn)
    DR.bind_role(conn, SA, ids["tl_eng"], roles["procurement"])
    DR.bind_role(conn, SA, ids["tl_adm"], roles["procurement"])
    DR.set_subtract(conn, SA, ids["tl_adm"], "inventory")
    res = EQ.verify(conn, snap)
    bad = {d["username"]: d for d in res["diffs"]}
    assert set(bad) == {"tl_eng", "tl_adm"}
    assert "procurement" in bad["tl_eng"]["gained"] and "inventory" in bad["tl_eng"]["gained"]
    assert "procurement" in bad["tl_adm"]["gained"] and "inventory" not in bad["tl_adm"]["gained"] and bad["tl_adm"]["lost"] == []
    conn.execute("UPDATE users SET role='viewer' WHERE id=?", (ids["tl_sales"],))
    conn.commit()
    res = EQ.verify(conn, snap)
    assert any("角色變了" in d["problem"] for d in res["diffs"])
    conn.execute("DELETE FROM users WHERE id=?", (ids["tl_sales"],))
    conn.commit()
    assert any(d["problem"] == "帳號不見了" for d in EQ.verify(conn, snap)["diffs"])
    conn.close()


def test_verify_reports_new_users_as_information_only(pop, make_user):
    conn = db.get_db()
    snap = EQ.take_snapshot(conn)
    conn.close()
    make_user(username="tl_new", role="viewer")
    conn = db.get_db()
    res = EQ.verify(conn, snap)
    conn.close()
    assert res["diffs"] == [] and "tl_new" in res["new_users"]


def test_cli_exit_codes_and_files(pop, tmp_path):
    dbp = _db_copy(tmp_path)
    out = str(tmp_path / "snap.json")
    assert EQ.main(["snapshot", "--out", out, "--db", dbp]) == 0
    assert EQ.main(["verify", "--snapshot", out, "--db", dbp]) == 0
    c = sqlite3.connect(dbp)
    c.execute("UPDATE users SET modules='[]' WHERE username='tl_adm'")
    c.commit()
    c.close()
    assert EQ.main(["verify", "--snapshot", out, "--db", dbp]) == 1
    assert EQ.main(["verify", "--snapshot", str(tmp_path / "nope.json"), "--db", dbp]) == 2


def test_snapshot_uses_the_embedded_train42_algorithm_not_the_current_one(pop, monkeypatch):
    """快照必須獨立於現行程式（否則上線前用舊程式跑不起來，證明也變成自證）。"""
    def boom(*a, **k):
        raise AssertionError("snapshot 不可呼叫現行 effective_modules")
    monkeypatch.setattr(A, "effective_modules", boom)
    conn = db.get_db()
    snap = EQ.take_snapshot(conn)
    conn.close()
    assert snap["users"]


def test_export_effective_dry_run_changes_nothing_and_apply_round_trips_for_the_old_code(pop, tmp_path):
    ids, roles = pop
    conn = db.get_db()
    DR.bind_role(conn, SA, ids["tl_eng"], roles["procurement"])
    DR.bind_role(conn, SA, ids["tl_adm"], roles["procurement"])
    DR.set_subtract(conn, SA, ids["tl_adm"], "inventory")
    DR.bind_role(conn, SA, ids["tl_sales"], roles["finance"], reason="測試財務角色綁定")
    want = {n: A.effective_modules(r, m, user_id=ids[n], conn=conn) for n, r, m in
            [(r["username"], r["role"], r["modules"]) for r in conn.execute("SELECT username, role, modules FROM users WHERE username LIKE 'tl_%'")]}
    before_raw = {r["username"]: r["modules"] for r in conn.execute("SELECT username, modules FROM users")}
    conn.close()
    dbp = _db_copy(tmp_path)
    assert EX.main(["--db", dbp]) == 0
    c = sqlite3.connect(dbp)
    assert {n: m for n, m in c.execute("SELECT username, modules FROM users")} == before_raw, "dry-run 不改資料"
    c.close()
    assert EX.main(["--db", dbp, "--apply"]) == 0
    c = sqlite3.connect(dbp)
    c.row_factory = sqlite3.Row
    rows = {r["username"]: (r["role"], r["modules"]) for r in c.execute("SELECT username, role, modules FROM users WHERE username LIKE 'tl_%'")}
    c.close()
    for name, (role, raw) in rows.items():
        # 「舊程式」只認 users.modules ＋財務規則（無角色／扣項）：結果必須等於新程式現在的生效清單
        assert EQ.legacy_effective(role, raw) == want[name], name
    assert "inventory" not in json.loads(rows["tl_adm"][1]) and "procurement" in json.loads(rows["tl_adm"][1]), "被扣的權限不會復活"
    assert "procurement" in json.loads(rows["tl_eng"][1])
    assert rows["tl_sa"] == ("superadmin", rows["tl_sa"][1])


def test_export_effective_leaves_superadmin_and_unbound_users_untouched(pop, tmp_path):
    ids, roles = pop
    conn = db.get_db()
    DR.bind_role(conn, SA, ids["tl_eng"], roles["viewer"])
    conn.execute("INSERT INTO user_perm_subtracts (user_id, perm_key, set_at) VALUES (?,?,?)", (ids["tl_sa"], "dashboard", "x"))   # 硬塞
    conn.commit()
    raw = {r["username"]: r["modules"] for r in conn.execute("SELECT username, modules FROM users")}
    conn.close()
    dbp = _db_copy(tmp_path)
    assert EX.main(["--db", dbp, "--apply"]) == 0
    c = sqlite3.connect(dbp)
    after = {n: m for n, m in c.execute("SELECT username, modules FROM users")}
    c.close()
    for n in ("tl_sa", "tl_adm", "tl_fin", "tl_sales"):
        assert after[n] == raw[n], n


def test_export_effective_without_any_duty_data_is_a_noop(pop, tmp_path, capsys):
    dbp = _db_copy(tmp_path)
    assert EX.main(["--db", dbp, "--apply"]) == 0
    assert "無事可做" in capsys.readouterr().out


def test_verify_flags_an_order_only_difference(pop):
    """集合相同、順序不同也要紅（上線關卡逐字比對含順序）。"""
    ids, roles = pop
    conn = db.get_db()
    snap = EQ.take_snapshot(conn)
    row = conn.execute("SELECT modules FROM users WHERE id=?", (ids["tl_adm"],)).fetchone()
    mods = json.loads(row[0])
    assert len(mods) >= 2
    conn.execute("UPDATE users SET modules=? WHERE id=?", (json.dumps(list(reversed(mods))), ids["tl_adm"]))
    conn.commit()
    res = EQ.verify(conn, snap)
    conn.close()
    assert [d["username"] for d in res["diffs"]] == ["tl_adm"] and res["diffs"][0]["orderOnly"] is True
