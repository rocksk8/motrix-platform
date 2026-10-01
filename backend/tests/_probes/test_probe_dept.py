import json
from modules.analytics.tests.test_dept_follows_sales_owner_2026_10_01 import _setup, _case

def test_dept(client, make_user):
    h, a, b, alice, bob = _setup(client, make_user)
    _case("DSO-1", bob, {"username": "dso_alice", "display": "愛麗絲"}, 100000)
    _case("DSO-2", bob, "沒有帳號的人", 20000)
    _case("DSO-3", bob, None, 3000)
    def tot(dep):
        q = "/api/reports/receivables-monthly?year=2026&month=2026-03" + ("&department_id=%d" % dep if dep else "")
        r = client.get(q, headers=h); assert r.status_code == 200, r.text
        d = r.json()
        return d, sum(float(i.get("amount") or 0) for i in d.get("yearOutstandingItems") or [])
    d_all, t_all = tot(None)
    print("DEPT keys", [k for k in d_all if "utstanding" in k][:6])
    _, t_a = tot(a); _, t_b = tot(b)
    print("DEPT totals all=%s A=%s B=%s  (expected 123000 / 100000 / 3000; unclassified 20000 = all-A-B=%s)" % (t_all, t_a, t_b, t_all - t_a - t_b))
    assert (t_all, t_a, t_b) == (123000, 100000, 3000)
