"""2026-08-28 資訊安全優化：backend/tools/audit_account_permissions.py 的
稽查邏輯測試——不是 API 端點，直接匯入腳本模組呼叫 _audit()。"""
import importlib.util
import json
import os


def _load_audit_module():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "..", "tools", "audit_account_permissions.py")
    spec = importlib.util.spec_from_file_location("audit_account_permissions", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _insert_user(username, role, modules):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, display_name, role, modules, active, created_at) "
            "VALUES (?,?,?,?,?,1,?)",
            (username, "x", username, role, json.dumps(modules), "2026-01-01T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()


def test_flags_admin_with_no_modules_as_highest_priority(client):
    _insert_user("claude", "admin", [])
    mod = _load_audit_module()
    results = mod._audit()
    row = next(r for r in results if r["username"] == "claude")
    assert row["priority"] == 2  # 命名疑似自動化 + modules 稀疏
    assert row["flagAutomationName"] is True
    assert row["flagSparseModules"] is True
    assert row["moduleCount"] == 0


def test_flags_sparse_modules_without_automation_name(client):
    _insert_user("realmanager", "admin", ["quotation"])
    mod = _load_audit_module()
    results = mod._audit()
    row = next(r for r in results if r["username"] == "realmanager")
    assert row["priority"] == 1
    assert row["flagAutomationName"] is False
    assert row["flagSparseModules"] is True


def test_does_not_flag_admin_with_broad_modules(client):
    _insert_user("sundy2", "admin", ["quotation", "customer", "sales", "procurement",
                                      "inventory", "equipment", "finance", "settings"])
    mod = _load_audit_module()
    results = mod._audit()
    row = next(r for r in results if r["username"] == "sundy2")
    assert row["priority"] == 0
    assert row["flagSparseModules"] is False


def test_ignores_non_admin_roles(client):
    _insert_user("viewer1", "viewer", [])
    _insert_user("sales1", "sales", ["quotation"])
    mod = _load_audit_module()
    results = mod._audit()
    usernames = {r["username"] for r in results}
    assert "viewer1" not in usernames
    assert "sales1" not in usernames


def test_ignores_inactive_accounts(client):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, display_name, role, modules, active, created_at) "
            "VALUES (?,?,?,?,?,0,?)",
            ("disabledadmin", "x", "disabledadmin", "admin", "[]", "2026-01-01T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()
    mod = _load_audit_module()
    results = mod._audit()
    assert "disabledadmin" not in {r["username"] for r in results}


def test_results_sorted_by_priority_descending(client):
    _insert_user("automation", "superadmin", [])       # priority 2
    _insert_user("narrowadmin", "admin", ["quotation"])  # priority 1
    _insert_user("broadadmin", "admin", ["a", "b", "c", "d", "e"])  # priority 0
    mod = _load_audit_module()
    results = mod._audit()
    priorities = [r["priority"] for r in results]
    assert priorities == sorted(priorities, reverse=True)
