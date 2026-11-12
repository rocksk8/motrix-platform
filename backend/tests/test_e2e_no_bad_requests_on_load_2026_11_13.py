# -*- coding: utf-8 -*-
"""頁面載入時不可以有 4xx 請求（UX 巡檢 hichan-7，2026-11-13；console 紅字會掩蓋真正的錯誤）。
D1：案件管理請求 `/pages/undefined/settings/company-profile`（`this.API` 沒定義）。
D2：簽核佇列請求 `/settings/company-profile`（少了 `/api`）。
D3：案件管理載入時 `/api/system/modules/availability` 回 401（`init()` 在 session 就緒前就呼叫）。
兩個據點相關請求以前都 404，據點標籤因此從來沒有顯示過——修好之後有多據點的公司會開始看到據點名稱（預期的功能）。"""
import pytest

pytest.importorskip("playwright.sync_api")

_MAKE_USER_DEFAULT_ROLE = "superadmin"


def _load(live_server, make_user, new_page, login_as, role, page_name, settle_ms=2500):
    user = make_user(username="e2e_nobad_%s_%s" % (role, page_name.split(".")[0].replace("-", "_")), role=role)
    page = new_page()
    seen = []
    page.on("response", lambda r: seen.append((r.status, r.url.replace(live_server, ""))))
    login_as(page, tuple(user)[:2])
    page.goto(f"{live_server}/pages/{page_name}")
    page.wait_for_timeout(settle_ms)
    return page, seen


def _bad(seen):
    return [(st, u) for st, u in seen if st >= 400]


@pytest.mark.e2e
@pytest.mark.parametrize("role", ["superadmin", "sales"])
def test_d1_case_management_reads_the_company_profile_from_the_api(live_server, make_user, new_page, login_as, role):
    _page, seen = _load(live_server, make_user, new_page, login_as, role, "case-management.html")
    assert not [x for x in seen if "company-profile" in x[1] and x[0] == 404], _bad(seen)
    assert not [x for x in seen if "undefined" in x[1]], "網址裡有 undefined：%r" % [x for x in seen if "undefined" in x[1]]
    assert any(u.startswith("/api/settings/company-profile") for st, u in seen), "對照：據點清單那支請求要打到正確的網址"


@pytest.mark.e2e
@pytest.mark.parametrize("role", ["superadmin", "sales"])
def test_d2_approval_queue_reads_the_company_profile_with_the_api_prefix(live_server, make_user, new_page, login_as, role):
    _page, seen = _load(live_server, make_user, new_page, login_as, role, "approval-queue.html")
    assert not [x for x in seen if "company-profile" in x[1] and x[0] >= 400], _bad(seen)
    assert any(st == 200 and u.startswith("/api/settings/company-profile") for st, u in seen), "對照：據點清單那支請求要真的成功"
