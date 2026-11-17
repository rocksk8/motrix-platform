"""正式機 11/16：精算改內容後存草稿，約 2.5 秒內再存／按完結回 409，重新整理後才能存。
用真頁面重現：改影響重算的欄位 → 存草稿 → 立刻再存／立刻完結；任何一步出現衝突橫幅或錯誤訊息就失敗。"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests._requires import requires_module  # noqa: E402
from modules.case.tests.test_e2e_settlement_actuals_2026_10_03 import _seed, _settlement  # noqa: E402
from modules.case.tests.test_e2e_settlement_t38_fe_2026_10_04 import S, _finalize_click, _open  # noqa: E402

pytestmark = requires_module("case", "本檔的題讀寫 M01（案件）的資料與頁面")


def _prod_shape():
    """MQ-202607-045 的形狀：外包人員 6,000（承攬項目空、total_amount＝0、金額只在 personnel_json）、已核准、已完工，未對應任何品項。"""
    from modules.case.tests.test_settlement_tax_basis_2026_10_03 import _dispatch
    from modules.case.tests.test_e2e_settlement_actuals_2026_10_03 import NO
    _dispatch(0, 6000, status="completed", approval="已核准", quote_no=NO)


def _assert_dispatch_counted(page, personnel_only):
    """確認造的派發真的進了頁面的成本（否則重現沒有意義）。"""
    if personnel_only:
        assert page.evaluate(f"() => {S}.summary.dispatchTotal") == 6000


def _edit_cost(page, value):
    """等同在『實際單位成本』欄輸入：改值後走 @input 的 calcItemCost＋calcSummary。"""
    page.evaluate(f"() => {{ const s = {S}; const it = s.settlement.items[0]; it.adoptSystem = false; it.actualUnitCost = {value}; s.calcItemCost(it); s.calcSummary() }}")


def _assert_no_conflict(page, what):
    page.wait_for_function(f"() => !{S}.saving", timeout=15000)
    assert not page.locator('[data-testid="stl-conflict"]').is_visible(), what + "：出現衝突橫幅"
    assert page.locator('[data-testid="stl-toast-error"]').count() == 0, what + "：" + (page.locator('[data-testid="stl-toast-error"]').first.inner_text() if page.locator('[data-testid="stl-toast-error"]').count() else "")


@pytest.mark.e2e
@pytest.mark.parametrize("personnel_only", [False, True])
def test_draft_then_immediately_draft_again_is_not_a_conflict(live_server, make_user, e2e_browser, personnel_only):
    sa = make_user(username="sa_sa", role="superadmin")
    _seed()
    if personnel_only:
        _prod_shape()
    page = _open(e2e_browser, live_server, sa)
    _assert_dispatch_counted(page, personnel_only)
    _edit_cost(page, 4000)
    page.locator('[data-testid="stl-save-draft"]').click()
    _assert_no_conflict(page, "第一次存草稿")
    _edit_cost(page, 4100)
    page.locator('[data-testid="stl-save-draft"]').click()                      # 不等，緊接著再存
    _assert_no_conflict(page, "緊接著再存草稿")
    assert _settlement()["items"][0]["actualUnitCost"] == 4100


@pytest.mark.e2e
@pytest.mark.parametrize("personnel_only", [False, True])
def test_draft_then_immediately_finalize_is_not_a_conflict(live_server, make_user, e2e_browser, personnel_only):
    sa = make_user(username="sa_sa", role="superadmin")
    _seed()
    if personnel_only:
        _prod_shape()
    page = _open(e2e_browser, live_server, sa)
    _assert_dispatch_counted(page, personnel_only)
    _edit_cost(page, 4000)
    page.locator('[data-testid="stl-save-draft"]').click()
    _assert_no_conflict(page, "存草稿")
    _edit_cost(page, 4200)                                                      # 草稿存完又改一次，緊接著完結
    _finalize_click(page)
    page.wait_for_function(f"() => !{S}.saving", timeout=15000)
    assert not page.locator('[data-testid="stl-conflict"]').is_visible(), "草稿後立刻完結：出現衝突橫幅"
    assert _settlement()["status"] == "finalized", page.locator('[data-testid="stl-toast-error"]').first.inner_text() if page.locator('[data-testid="stl-toast-error"]').count() else "未完結"
