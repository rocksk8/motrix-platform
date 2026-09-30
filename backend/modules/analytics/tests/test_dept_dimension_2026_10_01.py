"""支出報表的「部門」維度（2026-10-01，A2 無案件支出）。

解析順序：提供者明示的 departmentId（送出當下凍結）＞案件業務的部門＞未分類。
篩選與明細共用同一個解析；`byDepartment` 的總和＝所有明細的總和（守恆）。
`departmentId` 是選填鍵：沒有（舊提供者、欄位尚未加）⇒ 行為與舊版相同。"""
import json

import pytest

NOW = "2026-01-01T00:00:00"


def _seed_org():
    """兩個部門、兩位業務、兩張案件：MQ-D1（業務 sa→部門 A）、MQ-D2（業務 sb→部門 B）。回傳 (deptA, deptB)。"""
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO divisions (name, sort_order, created_at) VALUES ('事業處', 0, ?)", (NOW,))
        div = conn.execute("SELECT id FROM divisions WHERE name='事業處'").fetchone()["id"]
        ids = []
        for nm in ("工程部", "業務部"):
            conn.execute("INSERT INTO departments (division_id, name, sort_order, created_at) VALUES (?,?,0,?)", (div, nm, NOW))
            ids.append(conn.execute("SELECT id FROM departments WHERE name=?", (nm,)).fetchone()["id"])
        uids = []
        for uname, dept in (("dd_sa", ids[0]), ("dd_sb", ids[1])):
            conn.execute("INSERT INTO users (username, password_hash, display_name, role, modules, active, created_at,"
                         " must_change_password, department_id) VALUES (?,?,?,?,?,1,?,0,?)",
                         (uname, "x", uname, "viewer", "[]", NOW, dept))
            uids.append(conn.execute("SELECT id FROM users WHERE username=?", (uname,)).fetchone()["id"])
        for qn, uid in (("MQ-D1", uids[0]), ("MQ-D2", uids[1])):
            conn.execute(
                "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, "
                "created_at, updated_at, deal_tag, quote_date, sales_person_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (qn, "已送出", "客戶", "專案", 1, 1, json.dumps({}), NOW, NOW, "已成案", "2026-03-01", uid))
        conn.commit()
        return ids[0], ids[1]
    finally:
        conn.close()


def _patch(monkeypatch, contractor=(), other=(), provider=()):
    from modules.case import recognition as rp
    from core import registry

    def _mk(rows, **extra):
        return lambda *a, **k: [dict({"date": d, "quoteNo": q, "desc": "x", "amount": amt, "taxNote": "",
                                      "provisional": False}, **extra, **({"departmentId": dep} if dep != "-" else {}))
                                for d, q, amt, dep in rows]
    monkeypatch.setattr(rp, "dispatch_entries", _mk(contractor))
    monkeypatch.setattr(rp, "material_entries", _mk(()))
    monkeypatch.setattr(rp, "extra_entries", _mk(other, files=[], pending=False, category="其他"))
    orig = registry.providers
    prov = _mk(provider, category="獎金分潤")
    monkeypatch.setattr(registry, "providers",
                        lambda cap: {"t": (lambda conn, a, b: prov())} if cap == "expense.entries" else orig(cap))


def _ex(dept=None):
    from modules.analytics.api.reports import _collect_expenses
    return _collect_expenses(2026, dept)


def _sum_dept(ex):
    return sum(b["total"] for b in ex["byDepartment"])


def test_case_derived_department_and_unclassified(client, monkeypatch):
    a, b = _seed_org()
    _patch(monkeypatch, contractor=[("2026-03-05", "MQ-D1", 1000, "-"), ("2026-03-06", "MQ-D2", 500, "-")],
           other=[("2026-03-07", "", 300, "-")])                      # 無案件、無明示部門 ⇒ 未分類
    ex = _ex()
    by = {x["deptId"]: x for x in ex["byDepartment"]}
    assert by[a]["total"] == 1000 and by[a]["deptName"] == "工程部" and by[a]["contractor"] == 1000
    assert by[b]["total"] == 500
    assert by[None]["total"] == 300 and by[None]["deptName"] == "未分類" and by[None]["other"] == 300
    assert ex["byDepartment"][-1]["deptId"] is None, "未分類排最後"
    assert _sum_dept(ex) == ex["totals"]["total"] == 1800, "守恆：Σ 部門＝總額"
    row = next(d for d in ex["details"]["contractor"] if d["quoteNo"] == "MQ-D1")
    assert (row["deptId"], row["deptName"]) == (a, "工程部")


def test_explicit_department_wins_over_case_and_covers_caseless(client, monkeypatch):
    a, b = _seed_org()
    _patch(monkeypatch, other=[("2026-04-01", "", 700, b),            # 無案件但送出者部門 B
                               ("2026-04-02", "MQ-D1", 200, b)],       # 有案件（A）但明示 B ⇒ 明示優先
           provider=[("2026-04-03", "", 50, a)])
    ex = _ex()
    by = {x["deptId"]: x["total"] for x in ex["byDepartment"]}
    assert by == {b: 900, a: 50}
    assert _sum_dept(ex) == ex["totals"]["total"] == 950
    assert {(d["deptId"], d["amount"]) for d in ex["details"]["other"]} == {(b, 700), (b, 200), (a, 50)}


def test_filter_keeps_caseless_with_explicit_dept_and_drops_unclassified(client, monkeypatch):
    a, b = _seed_org()
    _patch(monkeypatch, other=[("2026-05-01", "", 700, b), ("2026-05-02", "", 40, "-"),
                               ("2026-05-03", "MQ-D2", 10, "-")])
    exb = _ex(b)
    assert exb["totals"]["total"] == 710, "篩選 B：明示 B 的無案件支出＋案件屬 B 的；未分類不計"
    assert [x["deptId"] for x in exb["byDepartment"]] == [b]
    assert _ex(a)["totals"]["total"] == 0
    assert _ex()["totals"]["total"] == 750
    assert _sum_dept(exb) == exb["totals"]["total"]


def test_zero_is_a_real_department_id_not_absent(client, monkeypatch):
    """`is None` 才是「沒有」：明示 0 不退回案件推導（不同於缺欄位）。"""
    a, b = _seed_org()
    _patch(monkeypatch, other=[("2026-06-01", "MQ-D1", 100, 0)])
    ex = _ex()
    assert [x["deptId"] for x in ex["byDepartment"]] == [0]


def test_stock_items_attributed_by_case(client, monkeypatch):
    from tests.test_money_round_half_up_2026_09_26 import _stock
    import db
    a, b = _seed_org()
    _patch(monkeypatch)
    _stock("DD-P1", 120, "2026-07-08T00:00:00")
    conn = db.get_db()
    try:
        conn.execute("UPDATE stock_items SET quote_no='MQ-D1' WHERE part_no='DD-P1'")
        conn.commit()
    finally:
        conn.close()
    _stock("DD-P2", 30, "2026-07-09T00:00:00")                         # 常備庫存、沒掛案件
    ex = _ex()
    by = {x["deptId"]: x["total"] for x in ex["byDepartment"]}
    assert by == {a: 120, None: 30}
    assert _sum_dept(ex) == ex["totals"]["total"]
    assert _ex(a)["totals"]["total"] == 120


def test_backward_compat_entries_without_key(client, monkeypatch):
    """舊提供者不給 departmentId、舊資料庫沒有欄位 ⇒ 與舊版相同的總額與篩選語意。"""
    a, b = _seed_org()
    _patch(monkeypatch, contractor=[("2026-03-05", "MQ-D1", 1000, "-")], other=[("2026-03-07", "", 300, "-")])
    ex = _ex(a)
    assert ex["totals"]["total"] == 1000, "無案件 ⇒ 篩選開啟時仍排除（與舊版一致）"
    assert _ex()["totals"]["total"] == 1300


def test_extra_entries_carries_department_id_when_column_exists(client, seed_extra_expense):
    import db
    from modules.case import recognition as rp
    _seed_org()
    seed_extra_expense("MQ-D1", total_cost=500, category="交通", expense_date="2026-08-01", description="a")
    conn = db.get_db()
    try:
        before = rp.extra_entries(conn, "accrual")
        assert before and all(e["departmentId"] is None for e in before), "沒有欄位 ⇒ 鍵在、值 None"
        conn.execute("ALTER TABLE case_extra_expenses ADD COLUMN department_id INTEGER")
        conn.execute("UPDATE case_extra_expenses SET department_id=7")
        after = rp.extra_entries(conn, "accrual")
        assert [e["departmentId"] for e in after] == [7]
        conn.execute("UPDATE case_extra_expenses SET department_id=NULL")
        assert [e["departmentId"] for e in rp.extra_entries(conn, "accrual")] == [None]
    finally:
        conn.rollback()
        conn.close()
