"""營運報表的精算快照過期檢查改走 IP-1 `dispatch.row`（M08 搬遷 ⑤；INTEGRATION-POINTS IP-1 的待辦）。

原本 `_live_dispatch_totals_by_quote` 自己又算了一次 grandTotal（同一算法的第二份實作）、直讀 M04 的表。
改用 M04 的提供者之後：
  - 提供者在 ⇒ 數字與原本一致（既有 test_reports_logic_fixes 的兩題是正對照；這裡再驗一次等價）
  - 提供者不在（外包工班模組未安裝）⇒ `staleSettlementCount` 是 None ＋ 說明，不是 0（不可以把「無法檢查」說成「沒有過期」）
"""
import pytest

from core import source_tree
from modules.analytics.tests.test_reports_logic_fixes_2026_08_28 import _insert_case, _insert_dispatch

#: 「提供者在」的兩題需要外包工班（M04，IP-1 的提供者）：模組不在時提供者本來就不在，
#: 那一側由 test_without_the_dispatch_provider_the_check_says_it_could_not_run 驗（PLAYBOOK §B-11）
_NEEDS_M04 = pytest.mark.skipif(not source_tree.module_installed("modules/subcontract/"),
                                reason="外包工班（M04）不在這個安裝包：dispatch.row 提供者本來就不在")

def _stale_case():
    _insert_case("MQ-IP1-001", deal_tag="已結案", settlement={"status": "finalized", "summary": {
        "dispatchTotal": 40000, "netProfit": 100000, "netMarginPct": 50.0}})
    _insert_dispatch("MQ-IP1-001", total_amount=45000)          # 含稅後 47250，跟快照 40000 對不上


@_NEEDS_M04
def test_totals_through_the_provider_match_the_old_algorithm(client, make_user):
    import db
    from modules.analytics.api.reports import _live_dispatch_totals_by_quote
    _stale_case()
    conn = db.get_db()
    try:
        totals = _live_dispatch_totals_by_quote(conn)
    finally:
        conn.close()
    assert totals["MQ-IP1-001"] == 45000 + round(45000 * 0.05)   # 原本的算法：未稅＋round(未稅×稅率)＋外包人員


def test_without_the_dispatch_provider_the_check_says_it_could_not_run(client, make_user, monkeypatch):
    from core import registry
    from modules.analytics.api.reports import _collect
    _stale_case()
    real = registry.single_provider
    monkeypatch.setattr(registry, "single_provider", lambda cap: None if cap == "dispatch.row" else real(cap))
    s = _collect("2026-01-01", "2026-12-31")["summary"]
    assert s["staleSettlementCount"] is None, "無法檢查不可以說成 0 件或 1 件"
    assert "外包工班模組未安裝" in (s["staleSettlementNote"] or "")


@_NEEDS_M04
def test_with_the_provider_there_is_no_note(client, make_user):
    """正對照：提供者在 ⇒ 照常計數、沒有說明。"""
    from modules.analytics.api.reports import _collect
    _stale_case()
    s = _collect("2026-01-01", "2026-12-31")["summary"]
    assert s["staleSettlementCount"] == 1 and s["staleSettlementNote"] is None


def test_report_page_shows_the_note():
    from core import source_tree
    html = source_tree.page_file("reports.html").read_text(encoding="utf-8")
    assert 'data-testid="stale-settlement-unavailable"' in html and "summary.staleSettlementNote" in html
