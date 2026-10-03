# -*- coding: utf-8 -*-
"""35c 重新開啟已完結精算（真瀏覽器）：按「重新開啟」要在對話框填理由；沒填不送出、畫面與存檔維持完結；填了才開成草稿，理由進編輯歷程。"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._requires import requires_module  # noqa: E402
from modules.case.tests.test_e2e_settlement_assigned_list_2026_10_03 import NO, open_page, seed  # noqa: E402

pytestmark = requires_module("case", "本檔的題讀寫 M01（案件）的資料與頁面")
S = "Alpine.$data(document.body)"


def _saved():
    import db
    c = db.get_db()
    try:
        return json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
    finally:
        c.close()


@pytest.mark.e2e
def test_reopening_a_finalized_settlement_in_the_page_requires_a_reason(live_server, make_user, e2e_browser):
    sa = make_user(username="sc_sc", role="superadmin")
    seed(item_ids=("a", "b"))
    page = open_page(live_server, e2e_browser, sa)
    page.wait_for_function("() => %s.summary && %s._actualsOk && !%s.loading" % (S, S, S), timeout=20000)
    page.locator('[data-testid="stl-finalize"]').click()
    with page.expect_response(lambda r: r.request.method == "PUT" and "/settlement" in r.url, timeout=20000) as resp:
        page.get_by_role("button", name="確認完結").click()
    assert resp.value.status == 200, resp.value.text()[:200]
    page.wait_for_function("() => %s.settlement.status === 'finalized' && !%s.saving" % (S, S), timeout=20000)

    page.locator('[data-testid="stl-reopen"]').click()
    page.locator('[data-testid="stl-reopen-modal"]').wait_for(state="visible", timeout=5000)
    assert page.locator('[data-testid="stl-reopen-hint"]').inner_text().strip() == "原因僅財務人員可見"
    page.locator('[data-testid="stl-reopen-confirm"]').click()               # 沒填理由
    page.locator('[data-testid="stl-reopen-error"]').wait_for(state="visible", timeout=5000)
    assert "理由" in page.locator('[data-testid="stl-reopen-error"]').inner_text()
    assert page.evaluate("() => %s.settlement.status" % S) == "finalized"
    assert _saved()["settlement"]["status"] == "finalized", "沒填理由卻已經改到存檔"

    page.locator('[data-testid="stl-reopen-reason"]').fill("承攬商發票補開，需重算")
    with page.expect_response(lambda r: r.request.method == "PUT" and "/settlement" in r.url, timeout=20000) as resp:
        page.locator('[data-testid="stl-reopen-confirm"]').click()
    assert resp.value.status == 200, resp.value.text()[:200]
    page.wait_for_function("() => %s.settlement.status === 'draft' && !%s.saving" % (S, S), timeout=20000)
    saved = _saved()
    assert saved["settlement"]["status"] == "draft"
    assert saved["editHistory"][-1]["reason"] == "承攬商發票補開，需重算"
    page.locator('[data-testid="stl-finalize"]').wait_for(state="visible", timeout=5000)      # 草稿：又看得到「完結精算」
