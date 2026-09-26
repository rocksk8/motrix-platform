"""O5-S1：e2e 的 /fonts/* 換成替身（conftest `_font_stub_hook`），量得到下載量。

- 預設：頁面有要字型（正對照：至少一支 /fonts/ 請求），而收到的字型總量 < 4 KB（替身 648 bytes）；console 沒有字型解碼錯誤
- `@pytest.mark.real_fonts`：照舊拿真字型 ⇒ 總量 > 1 MB（量法的正對照：替身拿掉時，上一題會量到這個量級而紅）
突變：拿掉 `E2E_CONTEXT_HOOKS.append(_font_stub_hook)` ⇒ 第一題紅（見 commit）。
"""
import pytest

pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.e2e


def _font_bytes(page, live_server, make_user, login_as, name):
    u, p = make_user(username=name, role="superadmin", modules=[])
    login_as(page, (u, p))
    got, errors = [], []
    page.on("response", lambda r: got.append(r) if "/fonts/" in r.url else None)
    page.on("console", lambda m: errors.append(m.text) if m.type in ("error", "warning") else None)
    page.goto(f"{live_server}/index.html")
    page.wait_for_load_state("load", timeout=60000)      # 這裡要等 load：量的正是 load 之前的字型下載
    page.evaluate("document.fonts.ready.then(() => true)")
    total = sum(len(r.body()) for r in got)
    return got, total, errors


def test_fonts_are_served_as_a_tiny_stub(live_server, make_user, new_page, login_as):
    page = new_page()
    got, total, errors = _font_bytes(page, live_server, make_user, login_as, "o5_stub")
    assert got, "正對照：頁面沒有要任何 /fonts/ ⇒ 這一題量不到東西"
    assert total < 4096, "收到的字型 %d bytes（%d 支）——替身沒有生效" % (total, len(got))
    assert not [e for e in errors if "font" in e.lower()], errors


@pytest.mark.real_fonts
def test_real_fonts_marker_gets_the_real_files(live_server, make_user, new_page, login_as):
    page = new_page()
    got, total, _ = _font_bytes(page, live_server, make_user, login_as, "o5_real")
    assert got and total > 1_000_000, "標 real_fonts 卻只收到 %d bytes（%d 支）" % (total, len(got))


def test_login_wait_does_not_depend_on_fonts(live_server, make_user, new_page, login_as):
    """O5-S1 後半：`wait_logged_in` 等應用就緒、不等 load——字型請求永遠不回來，它照樣在逾時內完成。
    突變：wait_logged_in 改回預設（等 load）⇒ 逾時紅。"""
    from tests._e2e_login import wait_logged_in
    u, p = make_user(username="o5_wait", role="superadmin", modules=[])
    page = new_page()
    login_as(page, (u, p))
    page.context.route("**/fonts/*", lambda route: None)     # 不放行也不回應 ⇒ load 永遠不會觸發（後註冊的先比對）
    page.goto(f"{live_server}/index.html", wait_until="commit")
    wait_logged_in(page, timeout=8000)
    assert page.evaluate("document.readyState") != "complete", "正對照：字型卡住時 load 真的沒有觸發"
