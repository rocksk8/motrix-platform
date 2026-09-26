"""O5-S2：e2e 逾時時，失敗報告附上「已發出而未完成的請求」（conftest `_inflight_hook`＋`pytest_runtest_makereport`）。

- 記帳：卡住的請求在清單上、已完成的不在（真瀏覽器）
- 報告：逾時的失敗 ⇒ 加一段；不是逾時的失敗、通過的題 ⇒ 不加
突變：拿掉 `rep.sections.append(...)` ⇒ 報告題紅；拿掉 `E2E_CONTEXT_HOOKS.append(_inflight_hook)` ⇒ 記帳題紅（見 commit）。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import types

import pytest
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


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

def test_teardown_watchdog_says_why_and_closes_the_browser():
    """超過上限 ⇒ fired、寫出原因（含未完成的請求），並在瀏覽器的事件迴圈上排程關閉；**不結束行程**。"""
    import asyncio
    import io
    import threading
    import time
    import conftest as cf
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    closed = []

    class _Impl:
        _loop = loop

        async def close(self):
            closed.append(1)
    br = types.SimpleNamespace(_impl_obj=_Impl())
    item = types.SimpleNamespace(nodeid="t::x", _e2e_inflight={object(): (time.monotonic(), "GET", "http://x/api/o9-hang?pt=S")})
    out = io.StringIO()
    wd = cf._TeardownWatchdog(item, 0.2, lambda: [br], out=out)
    with wd:
        time.sleep(0.8)
    loop.call_soon_threadsafe(loop.stop)
    t.join(2)
    assert wd.fired and closed == [1], (wd.fired, closed)
    text = out.getvalue()
    assert "t::x" in text and "/api/o9-hang" in text and "route" in text and "pt=S" not in text, text


def test_teardown_watchdog_is_silent_when_close_is_quick():
    import io
    import conftest as cf
    out = io.StringIO()
    wd = cf._TeardownWatchdog(types.SimpleNamespace(nodeid="t::y"), 5, lambda: [], out=out)
    with wd:
        pass
    assert not wd.fired and out.getvalue() == ""


# ── 反向控制（主持：-n 0 與 -n 2 各一）：teardown 真的卡住時，只有那一題 error，其他題照跑、行程不被結束 ─────

_HANG_IN_TEARDOWN = """
import pytest


@pytest.mark.e2e
@pytest.mark.e2e_teardown_limit(3)
def test_hangs_in_teardown(live_server, new_page):
    page = new_page()
    page.context.route("**/api/td-hang", lambda route: None)
    page.goto(live_server + "/static/favicon.png")
    # 模擬「close() 永遠不回來」：teardown 呼叫到的 close 其實在等一個 route 不回應的 fetch
    page.context.close = lambda: page.evaluate("fetch('/api/td-hang').catch(() => {})")


@pytest.mark.e2e
def test_next_e2e_still_gets_a_browser(live_server, new_page):
    page = new_page()
    page.goto(live_server + "/static/favicon.png")


def test_plain_one_after():
    assert True
"""


def _run_probe(tmp_name, xdist, basetemp):
    import os
    import subprocess
    import sys
    from pathlib import Path as _P
    here = _P(__file__).resolve().parent
    f = here / tmp_name
    f.write_text(_HANG_IN_TEARDOWN, encoding="utf-8")
    try:
        cmd = [sys.executable, "-X", "utf8", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--basetemp", str(basetemp),
               str(f.relative_to(here.parent)).replace(os.sep, "/")]
        if xdist:
            cmd[6:6] = ["-n", "2"]
        env = dict(os.environ, MOTRIX_E2E_TEST_LIMIT="60")
        r = subprocess.run(cmd, cwd=str(here.parent), capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=240, env=env)
        return r.returncode, r.stdout + r.stderr
    finally:
        f.unlink()


@pytest.mark.e2e
@pytest.mark.parametrize("xdist", [False, True], ids=["n0", "n2"])
def test_rc_teardown_hang_fails_only_that_test(xdist, tmp_path):
    """子行程跑三題：第一題 teardown 卡住 ⇒ 那一題另記一個 error（訊息含原因），三題本體都 passed（第二題是 e2e，要新瀏覽器），
    行程正常結束（有摘要行）。突變：看門狗不關瀏覽器 ⇒ 子行程卡到 240 秒逾時（TimeoutExpired）⇒ 紅。"""
    import uuid
    code, out = _run_probe("test_zz_td_probe_%s.py" % uuid.uuid4().hex[:8], xdist, tmp_path / "bt")
    # teardown error 的那一題本體算 passed ⇒ 三題都 passed＋一個 error（實測 -n 0：3 passed, 1 error in 13s）
    assert "3 passed" in out and "1 error" in out, out[-1500:]
    assert "[e2e teardown]" in out and "td-hang" in out, out[-1500:]



# ── e2e 每題死線（conftest pytest_runtest_call＋_close_contexts_threadsafe）─────────────────────

@pytest.mark.e2e
@pytest.mark.e2e_limit(4)
def test_deadline_breaks_a_never_settling_evaluate(live_server, new_page, request):
    """evaluate 等 route 不回應的 fetch promise（原本要等 renderer crash，50～400 秒以上）⇒ 死線（這題 4 秒）一到就丟例外。
    突變：不啟動計時器 ⇒ 這一題卡死（由外層 timeout 判紅）。"""
    import time
    import conftest as cf
    page = new_page()
    page.context.route("**/api/deadline-hang", lambda route: None)
    page.goto(f"{live_server}/static/favicon.png")
    t0 = time.monotonic()
    with pytest.raises(Exception):
        page.evaluate("fetch('/api/deadline-hang').catch(() => {})")
    took = time.monotonic() - t0
    assert took < 20, "死線 4 秒，卻等了 %.1f 秒" % took
    assert getattr(request.node, "_e2e_deadline_hit", False), "死線沒有觸發（例外是別的原因丟的）"
    assert "/api/deadline-hang" in cf.inflight_text(request.node)


def test_deadline_report_section_names_the_limit_and_the_requests():
    import conftest as cf
    rep = types.SimpleNamespace(when="call", failed=True, sections=[], longrepr="TargetClosedError")
    call = types.SimpleNamespace(excinfo=types.SimpleNamespace(typename="TargetClosedError"))
    item = types.SimpleNamespace(_e2e_inflight={object(): (0.0, "GET", "http://x/api/slow?q=SECRET5")}, _e2e_deadline_hit=True,
                                 get_closest_marker=lambda name: types.SimpleNamespace(args=(7,)) if name == "e2e_limit" else None)
    gen = cf.pytest_runtest_makereport(item, call)
    next(gen)
    with pytest.raises(StopIteration):
        gen.send(types.SimpleNamespace(get_result=lambda: rep))
    title, body = rep.sections[0]
    assert "死線 7 秒" in title and "/api/slow?q=***" in body and "SECRET5" not in body, rep.sections


# ── D 稽核 E2D-M1：軟上限一律在硬上限－30 以下 ──────────────────────────────────────────────

def _marker_item(name=None, value=None):
    def gcm(n):
        return types.SimpleNamespace(args=(value,)) if n == name else None
    return types.SimpleNamespace(nodeid="t::lim", get_closest_marker=gcm)


def test_soft_limits_stay_below_the_hard_cap(monkeypatch, capsys):
    """預設、標記、環境變數、teardown 上限：全部 ≤ 硬上限－30；超過的被夾住並說出來。突變 DL1（預設改成＋30）⇒ 紅。"""
    import conftest as cf
    monkeypatch.setenv("MOTRIX_E2E_HARD_CAP", "120")
    monkeypatch.delenv("MOTRIX_E2E_TEST_LIMIT", raising=False)
    ceiling = 120 - cf.SOFT_MARGIN
    assert cf._e2e_limit_of(_marker_item()) == ceiling, "預設要等於硬上限－30"
    assert cf._e2e_limit_of(_marker_item("e2e_limit", 500)) == ceiling
    assert cf._e2e_limit_of(_marker_item("e2e_limit", 5)) == 5, "比上限小的標記照用"
    monkeypatch.setenv("MOTRIX_E2E_TEST_LIMIT", "999")
    assert cf._e2e_limit_of(_marker_item()) == ceiling
    assert cf._teardown_limit_of(_marker_item("e2e_teardown_limit", 400)) == ceiling
    monkeypatch.setattr(cf, "E2E_TEARDOWN_LIMIT", 400.0)
    assert cf._teardown_limit_of(_marker_item()) == ceiling, "teardown 上限（環境變數）也要夾"
    err = capsys.readouterr().err
    assert err.count("[e2e 上限]") >= 4 and "MOTRIX_E2E_TEST_LIMIT" in err, err


def test_soft_ceiling_follows_the_hard_cap(monkeypatch):
    import conftest as cf
    monkeypatch.setenv("MOTRIX_E2E_HARD_CAP", "60")
    monkeypatch.delenv("MOTRIX_E2E_TEST_LIMIT", raising=False)
    assert cf._e2e_limit_of(_marker_item()) == 30
    monkeypatch.setenv("MOTRIX_E2E_HARD_CAP", "20")
    assert cf._e2e_limit_of(_marker_item()) == 10, "下限 10 秒"

