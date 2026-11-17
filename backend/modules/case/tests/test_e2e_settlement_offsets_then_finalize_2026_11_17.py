"""正式機 11/16：頁面上才剛改過「對應」→ 存草稿 → 立刻按完結 ⇒ 409；重新載入後同樣的資料完結成功。
正式機的請求順序：preview（改對應）→ PUT 200 → 2.5 秒 → PUT 409 → 重新載入 → PUT 200（完結）。
這裡用真頁面走同一個順序：改對應（派發單／材料）→ 存草稿 → 立刻完結；有衝突橫幅或沒完結就失敗。"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests._requires import requires_module  # noqa: E402
from modules.case.tests.test_e2e_settlement_actuals_2026_10_03 import _seed, _settlement  # noqa: E402
from modules.case.tests.test_e2e_settlement_t38_fe_2026_10_04 import S, _finalize_click, _open  # noqa: E402

pytestmark = requires_module("case", "本檔的題讀寫 M01（案件）的資料與頁面")


def _dispatches(kind):
    from modules.case.tests.test_settlement_tax_basis_2026_10_03 import _dispatch
    from modules.case.tests.test_e2e_settlement_actuals_2026_10_03 import NO
    if kind == "personnel_only":
        return [_dispatch(0, 6000, status="completed", approval="已核准", quote_no=NO)]
    if kind == "normal":
        return [_dispatch(10000, 2000, status="completed", approval="已核准", quote_no=NO)]
    return [_dispatch(0, 6000, status="completed", approval="已核准", quote_no=NO), _dispatch(10000, 2000, status="accepted", approval="已核准", quote_no=NO)]


def _conflict_or_error(page):
    page.wait_for_function(f"() => !{S}.saving", timeout=15000)
    if page.locator('[data-testid="stl-conflict"]').is_visible():
        return "衝突橫幅：" + (page.locator('[data-testid="stl-toast-error"]').first.inner_text() if page.locator('[data-testid="stl-toast-error"]').count() else "")
    return ""


@pytest.mark.e2e
@pytest.mark.parametrize("kind", ["personnel_only", "normal", "both"])
@pytest.mark.parametrize("map_what", ["dispatch", "material", "both", "none"])
def test_offsets_changed_then_draft_then_finalize(live_server, make_user, e2e_browser, kind, map_what):
    sa = make_user(username="sa_sa", role="superadmin")
    _seed()
    dids = _dispatches(kind)
    page = _open(e2e_browser, live_server, sa)
    if map_what in ("dispatch", "both"):
        for did in dids:
            page.evaluate(f"async () => {{ await {S}.setOffset('dispatch', '{did}', 'a') }}")
    if map_what in ("material", "both"):
        page.evaluate(f"async () => {{ await {S}.setOffset('material', 'X', 'b') }}")
    page.locator('[data-testid="stl-save-draft"]').click()
    err = _conflict_or_error(page)
    assert not err, "存草稿：" + err
    _finalize_click(page)
    page.wait_for_function(f"() => !{S}.saving", timeout=15000)
    assert not page.locator('[data-testid="stl-conflict"]').is_visible(), "改對應→存草稿→完結：" + (page.locator('[data-testid="stl-toast-error"]').first.inner_text() if page.locator('[data-testid="stl-toast-error"]').count() else "出現衝突橫幅")
    assert _settlement()["status"] == "finalized"
