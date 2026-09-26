"""O5-S2：e2e 逾時時，失敗報告附上「已發出而未完成的請求」（conftest `_inflight_hook`＋`pytest_runtest_makereport`）。

- 記帳：卡住的請求在清單上、已完成的不在（真瀏覽器）
- 報告：逾時的失敗 ⇒ 加一段；不是逾時的失敗、通過的題 ⇒ 不加
突變：拿掉 `rep.sections.append(...)` ⇒ 報告題紅；拿掉 `E2E_CONTEXT_HOOKS.append(_inflight_hook)` ⇒ 記帳題紅（見 commit）。
"""
import types

import pytest


@pytest.mark.e2e
def test_book_lists_the_hanging_request_only(live_server, new_page, request):
    pytest.importorskip("playwright.sync_api")
    import conftest as cf
    page = new_page()
    page.context.route("**/api/o5-hang", lambda route: None)          # 不放行也不回應 ⇒ 永遠未完成
    page.goto(f"{live_server}/static/favicon.png")
    page.evaluate("fetch('/api/o5-hang').catch(() => {}); fetch('/api/build-info').catch(() => {})")
    page.wait_for_timeout(800)
    text = cf.inflight_text(request.node)
    assert "/api/o5-hang" in text, text
    assert "/api/build-info" not in text, "已完成的請求不可以列進去：" + text


def _drive(cf, typename, when="call", failed=True):
    rep = types.SimpleNamespace(when=when, failed=failed, sections=[])
    call = types.SimpleNamespace(excinfo=types.SimpleNamespace(typename=typename) if failed else None)
    item = types.SimpleNamespace(_e2e_inflight={object(): (0.0, "GET", "http://x/api/slow")})
    gen = cf.pytest_runtest_makereport.__wrapped__(item, call) if hasattr(cf.pytest_runtest_makereport, "__wrapped__") \
        else cf.pytest_runtest_makereport(item, call)
    next(gen)
    with pytest.raises(StopIteration):
        gen.send(types.SimpleNamespace(get_result=lambda: rep))
    return rep


def test_timeout_failure_gets_the_inflight_section():
    import conftest as cf
    rep = _drive(cf, "TimeoutError")
    assert rep.sections and "O5-S2" in rep.sections[0][0] and "/api/slow" in rep.sections[0][1], rep.sections


def test_other_failures_and_passes_get_nothing():
    import conftest as cf
    assert _drive(cf, "AssertionError").sections == []
    assert _drive(cf, "TimeoutError", failed=False).sections == []
    assert _drive(cf, "TimeoutError", when="teardown").sections == []
