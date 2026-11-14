# -*- coding: utf-8 -*-
"""T86 U9：模組建構器的編號預覽、輸出預覽「送出前先檢核＋白話原因」。

正式機 90 天內 custom-modules preview 回 422 ×6：建構器每次編輯草稿都會重算編號預覽與輸出預覽，
規則還沒填好（前綴空白、位數打到一半、還沒有任何欄位）就一直被伺服器退回。
這裡驗：這些狀態下畫面直接說明「哪裡不對、怎麼改」，**不送** preview 請求；改成合法後照常送出並出現預覽。
"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._builder_nav import go_step, start_blank  # noqa: E402

KEY = "pv_precheck"


def _open(live_server, make_user, new_context):
    user = make_user(username="pvpc_root", role="superadmin")
    page = new_context().new_page()
    inject_login(page, live_server, user[0], user[1])
    posts = []
    page.on("request", lambda r: posts.append(r.url.split("/api/", 1)[-1].split("?")[0]) if r.method == "POST" and "/preview" in r.url else None)
    page.goto(live_server + "/pages/module-builder.html")
    start_blank(page, KEY)
    return page, posts


def _count(posts, what):
    return sum(1 for x in posts if x.endswith(what))


@pytest.mark.e2e
def test_numbering_preview_explains_bad_rules_without_calling_the_server(live_server, make_user, new_context):
    page, posts = _open(live_server, make_user, new_context)
    page.fill("#mb-prefix", "EL")
    page.select_option("#mb-date", "YYYYMMDD")
    page.wait_for_function("() => /^EL-\d{8}-\d+$/.test(document.getElementById('mb-num-example').dataset.example || '')", timeout=15000)
    base = _count(posts, "numbering/preview")
    assert base >= 1
    bad_cases = [("#mb-prefix", "", "請填寫編號前綴"), ("#mb-prefix", "1A", "英文字母開頭"), ("#mb-prefix", "ABCDEFGH", "最多 6 個字"),
                 ("#mb-prefix", "A-B", "只能用大寫英文字母與數字"), ("#mb-digits", "2", "必須在 3～8"), ("#mb-digits", "", "請填整數")]
    for sel, val, expect in bad_cases:
        # 每一輪先回到合法值，再打入壞值
        page.fill("#mb-prefix", "EL")
        page.fill("#mb-digits", "4")
        page.wait_for_function("() => document.getElementById('mb-num-example').dataset.example !== ''", timeout=15000)
        n0 = _count(posts, "numbering/preview")
        page.fill(sel, val)
        page.locator("#mb-num-example").locator("xpath=..").locator(".mb-bad").filter(has_text=expect).wait_for(state="visible", timeout=10000)
        assert page.locator("#mb-num-example").get_attribute("data-example") == ""
        page.wait_for_timeout(600)           # 超過 250ms 防抖：若會送請求，這時一定已送出
        assert _count(posts, "numbering/preview") == n0, "壞值 %r 不該送出請求" % val
    # 合法值照常送出並出現範例
    page.fill("#mb-prefix", "OK")
    page.fill("#mb-digits", "5")
    page.wait_for_function("() => /^OK-\d{8}-00001$/.test(document.getElementById('mb-num-example').dataset.example || '')", timeout=15000)


@pytest.mark.e2e
def test_output_preview_without_fields_is_explained_and_not_requested(live_server, make_user, new_context):
    page, posts = _open(live_server, make_user, new_context)
    go_step(page, 5)
    page.locator("#mb-step-5 .mb-bad").filter(has_text="尚無可以預覽的欄位").first.wait_for(state="visible", timeout=15000)
    assert page.locator("#mb-preview-state").get_attribute("data-state") == "bad"
    page.click("#mb-preview-btn")
    page.locator("#mb-step-5 .mb-bad").filter(has_text="新增至少一個欄位").first.wait_for(state="visible", timeout=10000)
    assert _count(posts, "output/preview") == 0, "沒有欄位：不該送出 output/preview"
    # 加一個欄位並填 key ⇒ 開始送出並出現預覽
    go_step(page, 2)
    page.click('[data-palette-type="text"]')
    page.fill("#mb-f-key", "item")
    page.press("#mb-f-key", "Tab")
    page.fill("#mb-f-label", "設備")
    go_step(page, 5)
    page.click("#mb-preview-btn")
    page.wait_for_function("() => document.getElementById('mb-preview-state').dataset.state === 'ok'", timeout=20000)
    assert _count(posts, "output/preview") >= 1
