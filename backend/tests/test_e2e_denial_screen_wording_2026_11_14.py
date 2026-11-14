# -*- coding: utf-8 -*-
"""T86 h5 複測小意見：沒有權限畫面的用語與符號。

(a) 僅限最高管理者的頁面（設定中心、職責角色）：說明要講真正原因「這一頁僅限最高管理者使用」，
    不能叫人去「使用者管理」開通模組（開了也進不去）；需要模組權限的頁面照舊說明。
(b) 三張沒有權限畫面（共用守門、使用狀況、公司資料）都不用 emoji（TEXT-STYLE-GUIDE）。
"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

LOCK = "\U0001F512"


def _open(live_server, make_user, new_context, username, role, path, modules=None):
    kw = {"modules": modules} if modules is not None else {}
    u = make_user(username=username, role=role, **kw)
    page = new_context(viewport={"width": 1440, "height": 900}).new_page()
    inject_login(page, live_server, u[0], u[1])
    page.goto(live_server + path)
    return page


@pytest.mark.e2e
@pytest.mark.parametrize("path", ["/pages/settings-center.html", "/pages/duty-roles.html"])
def test_superadmin_only_pages_say_so(live_server, make_user, new_context, path):
    page = _open(live_server, make_user, new_context, "dn_sa_" + path.split("/")[-1][:5], "sales", path)
    box = page.locator("#no-module-notice")
    box.wait_for(state="visible", timeout=15000)
    text = box.inner_text()
    assert "您沒有這個頁面的權限" in text
    assert "這一頁僅限最高管理者使用" in text
    assert "使用者管理" not in text and LOCK not in text


@pytest.mark.e2e
def test_module_pages_keep_the_module_wording(live_server, make_user, new_context):
    page = _open(live_server, make_user, new_context, "dn_mod", "user", "/pages/case-management.html", modules=["quotation"])
    box = page.locator("#no-module-notice")
    box.wait_for(state="visible", timeout=15000)
    text = box.inner_text()
    assert "這一頁需要對應的模組權限" in text and "使用者管理" in text
    assert "僅限最高管理者" not in text and LOCK not in text


@pytest.mark.e2e
def test_online_stats_and_company_wizard_denials_have_no_emoji(live_server, make_user, new_context):
    # 使用狀況頁自己的說明通常被共用守門畫面先蓋掉：直接檢查頁面來源沒有 emoji
    p1 = _open(live_server, make_user, new_context, "dn_os", "admin", "/pages/online-stats.html")
    html = p1.request.get(live_server + "/pages/online-stats.html").text()
    assert "使用狀況僅限最高管理者檢視" in html and LOCK not in html
    p2 = _open(live_server, make_user, new_context, "dn_cw", "admin", "/pages/company-setup-wizard.html")
    p2.locator("[data-testid=cw-denied]").wait_for(state="visible", timeout=15000)
    assert LOCK not in p2.locator("[data-testid=cw-denied]").inner_text()
