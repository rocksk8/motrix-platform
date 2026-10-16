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


# ── 前端：整頁說明（靜態頁面測試；不開瀏覽器）──────────────────────────────────
_FRONT = __import__("pathlib").Path(__file__).resolve().parents[3] / "frontend"
_MSG = "需要財務或金額可見權限才能查看報表"


def test_reports_page_shows_the_explanation_instead_of_a_blank_or_raw_error():
    html = (_FRONT / "pages" / "reports.html").read_text(encoding="utf-8")
    js = (_FRONT / "js" / "reports.js").read_text(encoding="utf-8")
    assert 'data-testid="reports-no-access"' in html and 'x-show="noAccess"' in html
    assert 'x-show="!noAccess"' in html and 'data-testid="reports-body"' in html   # 其餘內容在同一個旗標下整塊隱藏
    assert html.count("<main") == 1 and html.index('data-testid="reports-body"') < html.index("</main>")
    assert "noAccessMsg: '%s'" % _MSG in js
    assert "noAccess:   false" in js
    # 兩個入口都會設旗標：init()（本機角色判斷）與 loadData()（後端 403）
    assert js.count("this.noAccess = true") >= 3
    assert "res.status === 403" in js
    # 舊的「僅管理員以上…」紅字不能再出現（它會在說明旁邊重複出現）
    assert "僅管理員以上可存取營運報表功能" not in js


def test_front_gate_and_menu_keep_their_original_or_rules_backend_403_is_the_single_source():
    """PM 裁示（audit-t68-rep-r2）：選單 perm 只能表達 OR，無法表達『營運報表 且 money_visible』，所以前端不自己重做金額判斷：
    選單入口與 isAdminPlus() 維持原本的 OR 規則，是否能看金額完全由後端 403 決定，被擋時顯示同一個說明面板。"""
    import json
    js = (_FRONT / "js" / "reports.js").read_text(encoding="utf-8")
    i = js.index("isAdminPlus()")
    assert "includes('reports')" in js[i:i + 400]
    m = json.loads((__import__("pathlib").Path(__file__).resolve().parents[2] / "modules" / "analytics" / "module.json").read_text(encoding="utf-8"))
    page = [p for p in m["pages"] if p["path"] == "reports.html"][0]
    assert page["menu"]["perm"] == ["finance", "reports"], page["menu"]


# ── 稽核必修（audit-t68-rep-r1）：新閘門永遠是舊閘門的子集 ──────────────────────────────
def _gate_passes(R, fin, reports, money, monkeypatch):
    """用三個底層判斷的所有真值組合直接驅動 `_require_reports_access`（不經 HTTP，所以連旗標 on 才可能出現的組合也能驗）。"""
    from fastapi import HTTPException
    monkeypatch.setattr(R, "has_finance_access", lambda u: fin)
    monkeypatch.setattr(R, "user_has_module", lambda u, k: reports if k == "reports" else False)
    monkeypatch.setattr(R, "money_visible", lambda u: money)
    try:
        R._require_reports_access({"role": "x", "modules": "[]"})
        return True
    except HTTPException as e:
        assert e.status_code == 403
        return False


def test_new_gate_is_never_wider_than_the_old_gate(monkeypatch):
    from modules.analytics.api import reports as R
    import itertools
    seen_allowed = set()
    for fin, reports, money in itertools.product((False, True), repeat=3):
        new = _gate_passes(R, fin, reports, money, monkeypatch)
        old = fin or reports                      # 舊閘門：財務角色／superadmin，或持有「營運報表」模組
        assert (not new) or old, ("gate widened", dict(finance=fin, reports=reports, money_visible=money))
        if new:
            seen_allowed.add((fin, reports, money))
    # 精確形狀（不只是子集，也不能把該有的拿掉）：財務一律過；reports 模組要同時 money_visible 才過
    assert seen_allowed == {(True, r, m) for r in (False, True) for m in (False, True)} | {(False, True, True)}


def test_cashier_only_without_reports_module_stays_refused(monkeypatch):
    """出納模組（money_visible 為真）但沒有營運報表模組、也不是財務角色：過去 403，現在仍 403（稽核必修）。"""
    from modules.analytics.api import reports as R
    assert _gate_passes(R, False, False, True, monkeypatch) is False


def test_cashier_plus_reports_is_allowed_and_reports_only_is_refused(monkeypatch):
    from modules.analytics.api import reports as R
    assert _gate_passes(R, False, True, True, monkeypatch) is True
    assert _gate_passes(R, False, True, False, monkeypatch) is False


def test_ledger_diff_uses_the_same_gate(client, make_user):
    """ledger-diff（analytics/api/ledger_diff.py）也呼叫同一個 `_require_reports_access`：reports-only 403、財務 200。"""
    url = "/api/reports/ledger-diff?year=2026&basis=cash"
    h = _h(client, make_user, "rm_ld_fin", "finance")
    assert client.get(url, headers=h).status_code == 200
    h = _h(client, make_user, "rm_ld_rep", "viewer", modules=["reports"])
    r = client.get(url, headers=h)
    assert r.status_code == 403 and "財務" in r.json().get("detail", "")
