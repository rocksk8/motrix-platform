# -*- coding: utf-8 -*-
"""簽核設定儲存遇到 422（FastAPI 的 detail 是陣列）不可以顯示「[object Object]」（2026-11-13，SYSTEM-MENU-UX 提案 §T5）。
`MotrixError.detailText`（static/motrix-error.js）把 detail 的字串／陣列／物件轉成一句話。"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

_MAKE_USER_DEFAULT_ROLE = "superadmin"


@pytest.mark.e2e
def test_approval_settings_422_array_detail_is_readable(live_server, make_user, new_page, login_as):
    user = make_user(username="e2e_loaderr_422")
    page = new_page()
    login_as(page, tuple(user)[:2])
    page.goto(f"{live_server}/pages/approval-settings.html")
    page.wait_for_function("() => { const d = window.Alpine && Alpine.$data(document.body); return d && d._scopeLoaded === true }", timeout=30000)
    detail = [{"type": "missing", "loc": ["body", "tiers", 0, "departmentId"], "msg": "Field required", "input": {}},
              {"type": "value_error", "loc": ["body", "tiers", 1], "msg": "Value error, department_manager 簽核層需要指定 departmentId"}]
    page.route("**/api/settings/approval-flow-scope", lambda r: r.fulfill(status=422, content_type="application/json", body=json.dumps({"detail": detail})) if r.request.method == "PUT" else r.continue_())
    seen = []
    page.on("dialog", lambda d: (seen.append(d.message), d.accept()))
    page.evaluate("() => Alpine.$data(document.body).saveScope()")
    page.wait_for_timeout(500)
    assert seen, "沒有跳出儲存失敗的訊息"
    assert "[object Object]" not in seen[0], seen[0]
    assert "儲存失敗" in seen[0] and "簽核層需要指定" in seen[0] and "必填" in seen[0], seen[0]


@pytest.mark.e2e
def test_detail_text_never_returns_object_object(live_server, new_page):
    page = new_page()
    page.goto(f"{live_server}/pages/login.html")
    page.add_script_tag(url="/static/motrix-error.js")
    cases = [
        ("x", 400), ("", 422), (None, 500), ({"a": 1}, 422), ([{"a": 1}], 422), ([], 422), ([{"msg": "m", "loc": ["body", "f"]}], 422),
        ([["nested"]], 422), (123, 400),
    ]
    out = page.evaluate("(cs) => cs.map(c => MotrixError.detailText(c[0], c[1]))", [list(c) for c in cases])
    for r in out:
        assert isinstance(r, str) and r and "[object" not in r, out
    assert out[0] == "x"
    assert all("HTTP" not in r and "422" not in r and "500" not in r for r in out[1:3]), "使用者看到的訊息不可以有狀態碼：%r" % out
    assert out[6] == "f：m"
