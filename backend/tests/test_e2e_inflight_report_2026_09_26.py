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


def _drive(cf, typename, when="call", failed=True, longrepr=None, url="http://x/api/slow"):
    rep = types.SimpleNamespace(when=when, failed=failed, sections=[], longrepr=longrepr)
    call = types.SimpleNamespace(excinfo=types.SimpleNamespace(typename=typename) if failed else None)
    item = types.SimpleNamespace(_e2e_inflight={object(): (0.0, "GET", url)})
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
    assert _drive(cf, "AssertionError", longrepr="x").sections == []
    assert _drive(cf, "TimeoutError", failed=False).sections == []
    assert _drive(cf, "TimeoutError", when="teardown").sections == []


# ── D 稽核 S2-S1／O5S2-O1：失敗訊息的遮蔽 ─────────────────────────────────────────────

def test_inflight_section_prints_query_names_not_values():
    import conftest as cf
    rep = _drive(cf, "TimeoutError", url="http://x/api/uploads/a.jpg?pt=SECRET1&q=客戶甲")
    body = rep.sections[0][1]
    assert "/api/uploads/a.jpg?pt=***&q=***" in body, body
    assert "SECRET1" not in body and "客戶甲" not in body


@pytest.mark.parametrize("raw", [
    "authorization: Bearer SECRET2",
    '{"Authorization": "Bearer SECRET2"}',
    "GET http://127.0.0.1:1/api/uploads/x.jpg?pt=SECRET2",
    '"token": "SECRET2"',
    "cookie: motrix=SECRET2",
])
def test_redact_every_known_shape(raw):
    import conftest as cf
    assert "SECRET2" not in cf.redact(raw), cf.redact(raw)


def test_redact_keeps_the_useful_part():
    import conftest as cf
    got = cf.redact("TimeoutError: waiting for selector #x | GET /api/cases/12?tab=log")
    assert "waiting for selector #x" in got and "/api/cases/12" in got and "tab=log" in got


@pytest.mark.e2e
def test_rc_a_real_playwright_failure_leaks_nothing(live_server, new_page, request):
    """反向控制（主持指定）：真的 Playwright 失敗——網址帶 ?pt=SECRET3、標頭帶 Bearer SECRET3——
    它自己的錯誤訊息就含 SECRET3（正對照），經過報告 hook 之後整段不可以再出現。"""
    import conftest as cf
    page = new_page()
    page.goto(f"{live_server}/static/favicon.png")
    try:
        page.request.get(f"{live_server}/api/o5-no-such?pt=SECRET3&q=SECRET3",
                         headers={"Authorization": "Bearer SECRET3"}, fail_on_status_code=True, timeout=5000)
    except Exception as e:                                   # noqa: BLE001 要的正是它的錯誤文字
        raw = str(e)
    else:
        pytest.fail("正對照：這個請求應該失敗（404）")
    assert "SECRET3" in raw, "正對照：Playwright 的錯誤文字本來就帶出 SECRET3（否則下一步是空轉）：\n" + raw[:500]
    rep = _drive(cf, "Error", longrepr=raw, url=f"{live_server}/api/o5-no-such?pt=SECRET3")
    assert "SECRET3" not in str(rep.longrepr), str(rep.longrepr)[:500]
    assert all("SECRET3" not in body for _t, body in rep.sections)



def test_inflight_text_itself_hides_query_values():
    """第一層（inflight_text／safe_url）自己就不可以印出值——不靠報告 hook 的第二層（突變 safe_url 原樣回傳時，上一題被第二層接住而存活）。"""
    import time
    import conftest as cf
    item = types.SimpleNamespace(_e2e_inflight={object(): (time.monotonic(), "GET", "http://x/api/uploads/a.jpg?pt=SECRET4&q=客戶乙")})
    text = cf.inflight_text(item)
    assert "?pt=***&q=***" in text and "SECRET4" not in text and "客戶乙" not in text, text


# ── O9 附註：關 context 的死線（conftest `_TeardownWatchdog`）────────────────────────────────

def test_teardown_watchdog_says_why_and_exits():
    """超過上限 ⇒ 寫出原因（含未完成的請求）並 exit_fn(3)。突變：不啟動計時器 ⇒ 紅。"""
    import io
    import time
    import conftest as cf
    item = types.SimpleNamespace(nodeid="t::x", _e2e_inflight={object(): (time.monotonic(), "GET", "http://x/api/o9-hang")})
    out, fired = io.StringIO(), []
    with cf._TeardownWatchdog(item, 0.2, exit_fn=fired.append, out=out):
        time.sleep(0.8)
    text = out.getvalue()
    assert fired == [3], (fired, text)
    assert "t::x" in text and "/api/o9-hang" in text and "route" in text, text


def test_teardown_watchdog_is_silent_when_close_is_quick():
    import io
    import conftest as cf
    out, fired = io.StringIO(), []
    with cf._TeardownWatchdog(types.SimpleNamespace(nodeid="t::y"), 5, exit_fn=fired.append, out=out):
        pass
    assert fired == [] and out.getvalue() == ""

