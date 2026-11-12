# -*- coding: utf-8 -*-
"""簽核佇列壓力帶「待我簽核」的數字要跟清單一致（UX 巡檢 hichan-7，2026-11-13：數字寫 0、清單有 1 件）。
原因：壓力帶用 currentApprovers 另算一套；沒有簽核層、由最高管理者簽的項目 currentApprovers 是空的，
清單用的 canApprove() 卻認得它。現在兩邊共用 myItems。"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

_MAKE_USER_DEFAULT_ROLE = "superadmin"


def _item(no, **kw):
    base = {"type": "quotation", "quoteNo": no, "requestedBy": "someone_else", "requestedAt": "2026-11-12 09:00:00",
            "customerName": "測試客戶", "projectName": "測試專案", "total": 1000, "tiers": [], "currentApprovers": [], "currentTier": 0}
    base.update(kw)
    return base


def _numbers(page):
    page.locator(".vm-andon").wait_for(state="visible", timeout=20000)
    andon = page.locator(".vm-andon__seg--mine .vm-andon__val").inner_text().strip()
    col = page.locator(".aq-col__count").first.inner_text().strip()
    cards = page.evaluate("() => Alpine.$data(document.body).myItems.length")
    return andon, col, cards


@pytest.mark.e2e
@pytest.mark.parametrize("items,mine", [
    ([_item("MQ-NOTIER-1")], 1),                                                    # 沒有簽核層：最高管理者可簽（舊版壓力帶算 0）
    ([_item("MQ-NOTIER-1"), _item("MQ-NOTIER-2")], 2),
    ([_item("MQ-OTHER", tiers=[{"approvers": [{"username": "nobody_else", "status": "pending"}]}],
            currentApprovers=[{"username": "nobody_else", "status": "pending"}])], 0),   # 輪到別人：兩邊都是 0
], ids=["no-tier-one", "no-tier-two", "someone-elses-turn"])
def test_the_mine_number_matches_the_list(live_server, make_user, new_page, login_as, items, mine):
    user = make_user(username="e2e_aq_count_%d" % len(items) + str(mine))
    page = new_page()
    login_as(page, tuple(user)[:2])
    page.route("**/api/approval-queue", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"queue": [{"requestedBy": "someone_else", "items": items}], "total": len(items), "myDelegatedFor": [], "reassignTypes": []}))
        if r.request.method == "GET" else r.continue_())
    page.goto(f"{live_server}/pages/approval-queue.html")
    andon, col, cards = _numbers(page)
    assert cards == mine, "前提：這組資料下輪到我的是 %d 件（實際 %d）" % (mine, cards)
    assert andon == str(mine), "壓力帶寫 %r，清單有 %d 件" % (andon, mine)
    assert col == "%d 件" % mine, col
