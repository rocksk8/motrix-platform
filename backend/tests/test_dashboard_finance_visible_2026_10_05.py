"""首頁（儀表板）：stats 回 financeVisible===false ⇒ 應收款項面板與收款百分比一併隱藏（資料被保留，不能被讀成「目前無待收款項」）；
鍵不存在（舊 API）⇒ 維持原本行為。node 載入頁面元件直接呼叫 getter。"""
import json
import re

from tests.test_money_round_half_up_2026_09_26 import FRONTEND, _js, needs_node


def _dash(stats, role="admin", modules=None):
    body = ("o.session = { role: %s, modules: %s }; o.stats = Object.assign({}, o.stats, %s);"
            " return { show: o.showReceivables, fin: o.financeVisible, pct: o.receivedPct, canFinance: o.canFinance }"
            % (json.dumps(role), json.dumps(modules or []), json.dumps(stats)))
    return _js("page", str(FRONTEND / "index.html"), "dashboard", body)


@needs_node
def test_receivables_panel_hides_when_the_api_withholds_finance_data():
    r = _dash({"financeVisible": False, "paymentItems": [], "receivableSummary": {"total": 0, "received": 0}})
    assert r["canFinance"] is True and r["fin"] is False and r["show"] is False and r["pct"] is None


@needs_node
def test_receivables_panel_is_unchanged_when_the_key_is_absent_or_true():
    for stats in ({}, {"financeVisible": True}):
        r = _dash(dict(stats, receivableSummary={"total": 200, "received": 50}))
        assert r["fin"] is True and r["show"] is True and r["pct"] == 25, (stats, r)
    r = _dash({"receivableSummary": {"total": 0, "received": 0}})
    assert r["show"] is True and r["pct"] == 0


@needs_node
def test_accounts_without_finance_never_see_the_panel():
    r = _dash({"financeVisible": True}, role="staff", modules=["quotation"])
    assert r["canFinance"] is False and r["show"] is False


def test_the_panel_is_bound_to_the_finance_visible_getter_and_keeps_the_nav_link_rule():
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    assert re.search(r'<div class="panel" x-show="showReceivables"', html)
    assert 'x-show="canFinance">營運報表' in html          # 其他 canFinance 規則不動
