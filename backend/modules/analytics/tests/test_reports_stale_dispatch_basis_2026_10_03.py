# -*- coding: utf-8 -*-
"""35c 稅基 B：營運報表的「精算快照過期」比對要口徑對口徑（三處之一；另兩處在 settlement.html／case-management 的 e2e）。

精算的承攬商成本改成未稅＋外包人員（summary 帶 dispatchBasis='pretax'）；舊完結案沒有這個鍵＝含稅口徑，值不改寫。
比對：沒有標記 ⇒ 跟含稅現算值比；pretax ⇒ 跟未稅現算值比——舊完結案不會因為口徑切換而全部誤報過期。
"""
import pytest

from core import source_tree
from modules.analytics.tests.test_reports_logic_fixes_2026_08_28 import _insert_case, _insert_dispatch

pytestmark = pytest.mark.skipif(not source_tree.module_installed("modules/subcontract/"), reason="外包工班（M04）不在這個安裝包：dispatch.row 提供者本來就不在")


def _stale(summary):
    from modules.analytics.api.reports import _collect
    _insert_case("MQ-TB-001", deal_tag="已結案", settlement={"status": "finalized", "summary": summary})
    _insert_dispatch("MQ-TB-001", total_amount=45000)           # 未稅 45000；含稅 47250（預設稅率 5%）
    return _collect("2026-01-01", "2026-12-31")["summary"]["staleSettlementCount"]


def test_an_old_finalized_case_without_the_marker_compares_against_the_tax_inclusive_live_total(client):
    assert _stale({"dispatchTotal": 47250, "netProfit": 1}) == 0, "舊完結案（含稅口徑）不可以因為口徑切換被誤報過期"


def test_a_new_finalized_case_with_the_marker_compares_against_the_pretax_live_total(client):
    assert _stale({"dispatchTotal": 45000, "dispatchBasis": "pretax", "netProfit": 1}) == 0


def test_mixed_up_bases_are_still_caught_in_both_directions(client):
    assert _stale({"dispatchTotal": 47250, "dispatchBasis": "pretax", "netProfit": 1}) == 1      # 標未稅卻存了含稅值 ⇒ 過期（口徑錯配被抓到）


def test_an_unmarked_summary_holding_the_pretax_value_is_flagged_not_silently_accepted(client):
    assert _stale({"dispatchTotal": 45000, "netProfit": 1}) == 1


def test_a_real_change_after_finalize_is_still_detected_on_the_new_basis(client):
    assert _stale({"dispatchTotal": 40000, "dispatchBasis": "pretax", "netProfit": 1}) == 1
