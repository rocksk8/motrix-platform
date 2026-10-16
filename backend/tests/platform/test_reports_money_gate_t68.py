"""T68 營運報表金額閘（使用者裁示 2026-10-17，audit-t68-reports-money）。

只持有「營運報表」模組的帳號（沒有財務角色、也不是 superadmin）**不得**看到全公司金額：
`/api/reports/*` 11 支端點共用 `_require_reports_access`，過去 `user_has_module(u, "reports")` 就放行，
而 `_collect` 等後續組裝完全不看使用者。現在改成：要有 `has_finance_access` 或 `money_visible`
（兩者就是 `/api/quotations`、儀表板財務卡片用的同一條規則）才能打這 11 支。

① 正對照（先紅）：閘門的老規則下，viewer＋reports 對 11 支都回 200，且 `/api/reports/financial` 的 casesAll 帶金額。
   斷言本身不吃自設值：先用財務帳號確認這 11 支「通常是 200」（題目問得對），再驗 reports-only 現在是 403。
② 財務角色與 superadmin 不變（11 支仍 200；financial 仍帶 casesAll 金額鍵）。
③ 其他模組權限不受影響：reports-only 的 403 訊息明說原因；沒登入仍 401。
"""
import pytest

#: (名稱, 網址)——11 支端點；匯出類帶最小參數。
ENDPOINTS = [
    ("financial", "/api/reports/financial?period=2026-09"),
    ("financial-excel", "/api/reports/financial/excel?period=2026-09"),
    ("financial-pdf", "/api/reports/financial/pdf?period=2026-09"),
    ("ar-aging", "/api/reports/ar-aging"),
    ("cash-position", "/api/reports/cash-position"),
    ("tax-export", "/api/reports/tax-export?year=2026"),
    ("customer-history", "/api/reports/customer-history"),
    ("monthly-trend", "/api/reports/monthly-trend?months=6"),
    ("payment-anomalies", "/api/reports/payment-anomalies"),
    ("expenses-monthly", "/api/reports/expenses-monthly?year=2026&month=2026-09"),
    ("receivables-monthly", "/api/reports/receivables-monthly?year=2026&month=2026-09"),
]


def _h(client, make_user, name, role, modules=None):
    u, p = make_user(name, "Conn-Pass-123", role=role, modules=modules)[:2]
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def test_there_are_exactly_the_eleven_report_endpoints():
    """題目的範圍＝路由表裡 /api/reports/* 的 GET 全集（有人新增第 12 支而沒進這張表 ⇒ 轉紅）。"""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "modules" / "analytics" / "api" / "reports.py").read_text(encoding="utf-8")
    import re
    routes = set(re.findall(r'@router\.get\("(/api/reports/[^"]+)"\)', src))
    mine = {u.split("?")[0] for _, u in ENDPOINTS}
    assert routes == mine, (routes ^ mine)
    assert src.count("_require_reports_access(u)") == 11


@pytest.mark.parametrize("name,url", ENDPOINTS, ids=[n for n, _ in ENDPOINTS])
def test_positive_control_finance_role_gets_200(client, make_user, name, url):
    """正對照：題目問對了——財務角色打這 11 支是 200（不是路徑打錯 404／參數錯 422 才得到「非 200」）。"""
    h = _h(client, make_user, "rm_fin_" + name.replace("-", "_"), "finance")
    r = client.get(url, headers=h)
    assert r.status_code == 200, (name, r.status_code, r.text[:200])


@pytest.mark.parametrize("name,url", ENDPOINTS, ids=[n for n, _ in ENDPOINTS])
def test_reports_module_only_accounts_are_refused_on_every_endpoint(client, make_user, name, url):
    for role in ("viewer", "engineer", "sales", "admin"):
        h = _h(client, make_user, "rm_only_%s_%s" % (role, name.replace("-", "_")), role, modules=["reports"])
        r = client.get(url, headers=h)
        assert r.status_code == 403, (name, role, r.status_code)
        assert "財務" in r.json().get("detail", ""), r.text[:200]


def test_reports_module_only_account_never_sees_case_amounts(client, make_user):
    """金額不外洩的直接斷言：回應本文不含 casesAll／settleSummary 等金額欄（403 的 detail 也不夾金額）。"""
    h = _h(client, make_user, "rm_only_body", "viewer", modules=["reports"])
    r = client.get("/api/reports/financial?period=2026-09", headers=h)
    assert r.status_code == 403
    for k in ("casesAll", "settleSummary", "grossProfit", "netMarginPct", "receivedAmount"):
        assert k not in r.text


def test_finance_and_superadmin_still_get_amount_keys(client, make_user):
    for role, name in (("finance", "rm_keep_fin"), ("superadmin", "rm_keep_sa")):
        h = _h(client, make_user, name, role)
        j = client.get("/api/reports/financial?period=2026-09", headers=h).json()
        assert "casesAll" in j and "targets" in j, (role, sorted(j)[:8])


def test_unauthenticated_is_still_401(client):
    for _, url in ENDPOINTS:
        assert client.get(url).status_code == 401, url
