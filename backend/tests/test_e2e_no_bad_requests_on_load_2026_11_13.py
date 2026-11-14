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


def _served(seen, prefix):
    """對照用：這份資料有被成功取得——直接打原端點（200），或由啟動資料合併請求 `/api/bootstrap?page=case`（T86 #10；案件管理頁首屏的小請求都併在這一支）供應。
    原端點與合併請求二選一都算；只要兩者都沒有（也沒有任何 4xx）就是頁面根本沒載入資料。"""
    return any(st == 200 and (u.startswith(prefix) or u.startswith("/api/bootstrap?page=case")) for st, u in seen)


@pytest.mark.e2e
@pytest.mark.parametrize("role", ["superadmin", "sales"])
def test_case_management_reads_the_company_profile_from_the_api(live_server, make_user, new_page, login_as, role):
    _page, seen = _load(live_server, make_user, new_page, login_as, role, "case-management.html")
    assert not [x for x in seen if "company-profile" in x[1] and x[0] == 404], _bad(seen)
    assert not [x for x in seen if "undefined" in x[1]], "網址裡有 undefined：%r" % [x for x in seen if "undefined" in x[1]]
    assert any(u.startswith("/api/settings/company-profile") or u.startswith("/api/bootstrap?page=case") for st, u in seen), "對照：據點清單那支請求要打到正確的網址"


@pytest.mark.e2e
@pytest.mark.parametrize("role", ["superadmin", "sales"])
def test_approval_queue_reads_the_company_profile_with_the_api_prefix(live_server, make_user, new_page, login_as, role):
    _page, seen = _load(live_server, make_user, new_page, login_as, role, "approval-queue.html")
    assert not [x for x in seen if "company-profile" in x[1] and x[0] >= 400], _bad(seen)
    assert any(st == 200 and u.startswith("/api/settings/company-profile") for st, u in seen), "對照：據點清單那支請求要真的成功"


@pytest.mark.e2e
@pytest.mark.parametrize("role", ["superadmin", "sales"])
def test_case_management_has_no_401_on_load(live_server, make_user, new_page, login_as, role):
    """401 的原因是 init() 在 session 就緒前就帶著 `Bearer undefined` 打 API，不是權限設計：已登入的人載入頁面不該有任何 401。"""
    _page, seen = _load(live_server, make_user, new_page, login_as, role, "case-management.html")
    assert not [x for x in seen if x[0] == 401], _bad(seen)
    assert _served(seen, "/api/system/modules/availability"), "對照：模組狀態請求要成功"
    assert _served(seen, "/api/settings/company-profile"), "對照：據點清單請求要成功"
    assert not _bad(seen), _bad(seen)
