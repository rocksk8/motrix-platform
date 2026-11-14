"""CORE-SPEC §9c 模組管理頁與選單（e2e）。

① superadmin 在「模組管理」頁看到合成模組「啟用」；取消勾選→預覽→確定套用 ⇒ 該列標「待重啟」、訊息說「重新啟動服務後生效」，
   目前狀態仍是「啟用」（重啟後生效）；「復原這一批」回復；放棄草稿不寫入。頁面沒有重啟按鈕。
② 選單：這次啟動沒載入的模組（狀態表改成 disabled 模擬重啟後的結果）⇒ 側欄入口不見；
   正對照：狀態是 loaded 時入口看得到。
③ A-3：狀態帶「授權檢查未啟用」⇒ 該列與頁面頂端都標出來；正對照：沒有這個狀態時兩者都不出現。
④ core-only 反向控制：一個模組都沒有 ⇒ 管理頁顯示「沒有可選配的模組」、側欄照常建出來、頁面沒有 JS 錯誤。

🔴 不綁任何真實的 L2 模組（AUDIT-X-9c A-2；MODULE-GUIDE §7）：①③④ 用合成的狀態列；② 需要側欄裡真的有一個
   入口，所以「任取一個已載入、且側欄有入口的模組」，沒有就 skip 並說明（core-only 時側欄沒有模組入口可藏）。
   狀態表的改動一律 snapshot()／restore()（live server 與本題同一個行程）。
"""
import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import bootstrap_unavailable, inject_login  # noqa: E402

KEY = "zz_e2e"


def _open(e2e_browser, live_server, make_user, name, path):
    u = make_user(username=name, role="superadmin")
    page = e2e_browser.new_context().new_page()
    inject_login(page, live_server, u[0], u[1])
    page.goto(f"{live_server}/pages/{path}")
    return page


@pytest.fixture
def only_synthetic():
    """狀態表只留一個合成模組（loaded、沒有 note），題後還原。回傳可改狀態的函式。"""
    from core import registry
    snap = registry.snapshot()
    registry._STATES.clear()
    registry.set_state(KEY, registry.STATE_LOADED, "", {"key": KEY, "name": "合成模組", "version": "0.0.1",
                                                        "pages": [{"path": "zz-e2e.html"}]})

    def patch(**kw):
        registry._STATES[KEY] = {**registry._STATES[KEY], **kw}
    try:
        yield patch
    finally:
        registry.restore(snap)


@pytest.mark.e2e
def test_module_settings_page_toggle_is_pending_until_restart(live_server, make_user, e2e_browser, only_synthetic):
    page = _open(e2e_browser, live_server, make_user, "mse_sa1", "module-settings.html")
    state = page.locator(f"[data-testid='ms-state-{KEY}']")
    state.wait_for(timeout=15000)
    assert state.inner_text().strip() == "啟用"
    assert not page.locator(f"[data-testid='ms-pending-{KEY}']").is_visible()
    assert "重新啟動服務後才生效" in page.locator("[data-testid='ms-restart-note']").inner_text()

    toggle = page.locator(f"[data-testid='ms-toggle-{KEY}']")
    assert toggle.is_checked()
    toggle.uncheck()                                                # 只是草稿：還沒寫入
    page.locator(f"[data-testid='ms-diff-{KEY}']").wait_for(state="visible", timeout=10000)
    assert page.locator("[data-testid='ms-dirty-count']").inner_text().strip() == "1"
    assert not page.locator(f"[data-testid='ms-pending-{KEY}']").is_visible()
    page.locator("[data-testid='ms-preview-btn']").click()
    page.locator(f"[data-testid='ms-preview-{KEY}']").wait_for(state="visible", timeout=10000)
    assert "資料保留" in page.locator(f"[data-testid='ms-preview-{KEY}']").inner_text()
    page.locator("[data-testid='ms-apply']").click()
    page.locator(f"[data-testid='ms-pending-{KEY}']").wait_for(state="visible", timeout=10000)
    assert "重新啟動服務後生效" in page.locator("[data-testid='ms-msg']").inner_text()
    assert state.inner_text().strip() == "啟用", "目前狀態要到重啟後才變"
    assert not toggle.is_checked()

    page.locator("[data-testid='ms-undo']").click()                 # 復原這一批
    page.locator(f"[data-testid='ms-pending-{KEY}']").wait_for(state="hidden", timeout=10000)
    assert toggle.is_checked()
    assert page.locator("button:has-text('重啟'), button:has-text('重新啟動')").count() == 0


@pytest.mark.e2e
def test_module_settings_protected_module_stays_enabled(live_server, make_user, e2e_browser, only_synthetic, monkeypatch):
    """核心必須模組：勾選框鎖住並說明原因；「列出的全部設為停用」不會動它。"""
    from helpers import module_switches
    monkeypatch.setitem(module_switches.PROTECTED_MODULES, KEY, "測試用：必須保持啟用。")
    page = _open(e2e_browser, live_server, make_user, "mse_sa3", "module-settings.html")
    toggle = page.locator(f"[data-testid='ms-toggle-{KEY}']")
    toggle.wait_for(timeout=15000)
    assert toggle.is_disabled() and toggle.is_checked()
    page.locator(f"[data-testid='ms-protected-{KEY}']").wait_for(state="visible", timeout=10000)
    assert "必須保持啟用" in page.locator(f"[data-testid='ms-protected-{KEY}']").inner_text()
    page.locator("[data-testid='ms-all-off']").click()
    assert page.locator("[data-testid='ms-draft-bar']").is_hidden()  # e2e-lint: ok 全部停用略過受保護列＝沒有草稿，確認未產生變更
    assert toggle.is_checked()


@pytest.mark.e2e
def test_module_settings_page_discard_and_filter(live_server, make_user, e2e_browser, only_synthetic):
    """批次草稿：放棄這批＝回到現況、不寫入；搜尋沒有符合時顯示空狀態；全部設為停用後可預覽。"""
    page = _open(e2e_browser, live_server, make_user, "mse_sa2", "module-settings.html")
    page.locator(f"[data-testid='ms-state-{KEY}']").wait_for(timeout=15000)
    page.locator("[data-testid='ms-all-off']").click()
    page.locator("[data-testid='ms-dirty-count']").wait_for(state="visible", timeout=10000)
    assert not page.locator(f"[data-testid='ms-toggle-{KEY}']").is_checked()
    page.locator("[data-testid='ms-discard']").click()
    page.locator("[data-testid='ms-draft-bar']").wait_for(state="hidden", timeout=10000)
    assert page.locator(f"[data-testid='ms-toggle-{KEY}']").is_checked()
    assert not page.locator(f"[data-testid='ms-pending-{KEY}']").is_visible(), "放棄不得寫入"
    page.locator("[data-testid='ms-search']").fill("不存在的模組")
    page.locator(f"[data-testid='ms-row-{KEY}']").wait_for(state="detached", timeout=10000)
    page.locator("[data-testid='ms-table']").get_by_text("沒有符合的模組").wait_for(state="visible", timeout=10000)


@pytest.mark.e2e
def test_license_not_checked_is_shown(live_server, make_user, e2e_browser, only_synthetic):
    """A-3：授權檢查沒有啟用（開發模式）⇒ 該列與頂端都標「授權檢查未啟用」。"""
    from helpers import licensing as lic
    page = _open(e2e_browser, live_server, make_user, "mse_sa4", "module-settings.html")
    page.locator(f"[data-testid='ms-state-{KEY}']").wait_for(timeout=15000)
    assert not page.locator("[data-testid='ms-license-note']").is_visible(), "正對照：沒有 note 時不顯示"
    assert not page.locator(f"[data-testid='ms-mnote-{KEY}']").is_visible()

    only_synthetic(note=lic.MODULE_LICENSE_NOT_CHECKED)
    page.reload()
    banner = page.locator("[data-testid='ms-license-note']")
    banner.wait_for(state="visible", timeout=15000)
    assert lic.MODULE_LICENSE_NOT_CHECKED in banner.inner_text()
    assert page.locator(f"[data-testid='ms-mnote-{KEY}']").inner_text().strip() == lic.MODULE_LICENSE_NOT_CHECKED
    assert page.locator(f"[data-testid='ms-state-{KEY}']").inner_text().strip() == "啟用"   # 不是錯誤狀態
    assert not page.locator(f"[data-testid='ms-reason-{KEY}']").is_visible()


@pytest.mark.e2e
def test_sidebar_hides_entries_of_unloaded_modules(live_server, make_user, e2e_browser):
    from core import registry
    page = _open(e2e_browser, live_server, make_user, "mse_sa2", "module-settings.html")
    page.locator("[data-testid='ms-table']").wait_for(timeout=15000)
    page.wait_for_load_state("networkidle")
    # 任取一個已載入、且側欄裡有入口的模組（不綁特定模組）
    cands = [(st["key"], pg) for st in registry.module_states() if st["state"] == "loaded" for pg in st["pages"]]
    pick = next(((k, pg) for k, pg in cands
                 if page.evaluate("(p) => !!document.querySelector(`#app-mainnav a[href$=\"${p}\"]`)", pg)), None)
    if pick is None:
        pytest.skip("沒有任何已載入的模組在選單有入口（core-only 或模組沒有頁面）：沒有入口可藏")
    key, pg = pick
    link = f"#app-mainnav a[href$='{pg}']"
    # 觀測點＝入口元素自己的 style.display（側欄是收合的下拉分組，is_visible() 會因為父層收合而是 False，
    # 那不是這裡要驗的事）。正反兩邊用同一個觀測點。
    hidden = f"() => {{ const a = document.querySelector(\"{link}\"); return a ? a.style.display === 'none' : null }}"
    assert page.evaluate(hidden) is False, "正對照：模組已載入時入口不可被藏"

    snap = registry.snapshot()
    try:
        registry._STATES[key] = {**registry._STATES[key], "state": "disabled", "reason": "管理者已停用"}
        page.reload()
        page.locator("[data-testid='ms-table']").wait_for(timeout=15000)
        page.wait_for_function(hidden, timeout=10000)
        assert page.evaluate(hidden) is True
    finally:
        registry.restore(snap)


@pytest.mark.e2e
@pytest.mark.parametrize("via_bootstrap", [True, False], ids=["bootstrap", "direct"])
def test_core_only_page_and_sidebar_still_work(live_server, make_user, e2e_browser, via_bootstrap):
    """A-2 反向控制：狀態表是空的（core-only 產品）⇒ 管理頁說「沒有可選配的模組」、側欄照常、沒有 JS 錯誤。
    2026-11-13（bootstrap）：側欄的 availability 第一次由 /api/bootstrap 的 moduleAvailability 供應；bootstrap 不可用時退回原端點。兩條路都驗。"""
    from core import registry
    snap = registry.snapshot()
    try:
        registry._STATES.clear()
        u = make_user(username="mse_sa3%s" % ("b" if via_bootstrap else "d"), role="superadmin")
        page = e2e_browser.new_context().new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        inject_login(page, live_server, u[0], u[1])
        if not via_bootstrap:
            bootstrap_unavailable(page)
        want = (lambda r: r.url.endswith("/api/bootstrap")) if via_bootstrap else (lambda r: "/api/system/modules/availability" in r.url)
        with page.expect_response(want) as resp:
            page.goto(f"{live_server}/pages/module-settings.html")
        body = resp.value.json()
        avail = body["moduleAvailability"] if via_bootstrap else body
        assert resp.value.status == 200 and avail == {}                   # 側欄改用 availability（bootstrap 時是它的區段）
        page.locator("text=這個安裝包裡沒有可選配的模組").wait_for(state="visible", timeout=15000)
        page.wait_for_load_state("networkidle")
        # 第 54 班（系統中心）：『系統』群組在導覽列收成單一連結（指向系統中心），模組管理不再是獨立導覽項；
        # 「選單照常建出來」改驗：系統中心入口在、本頁被認成系統頁（頂端有『← 系統』連結可回系統中心）。
        assert page.locator("#app-mainnav a[href$='system-hub.html']").count() >= 1, "選單要照常建出來（系統中心入口）"
        assert page.locator("[data-testid=sys-crumb]").count() == 1, "模組管理頁要掛『← 系統』連結"
        assert not errors, errors
    finally:
        registry.restore(snap)


@pytest.mark.e2e
def test_page_shows_unreadable_disabled_list_and_license_change(live_server, make_user, e2e_browser, monkeypatch):
    """STATES-PLATFORM P-SW-05／P-SW-03：頂端標「停用清單讀取失敗」、該列標「授權變更於重啟後生效」。
    正對照：正常啟動、授權沒變 ⇒ 兩者都不出現。"""
    from core import registry
    from helpers import licensing as lic
    # 合成模組列（不綁真實 L2 模組；AUDIT-X-9c A-2）
    monkeypatch.setitem(registry._STATES, "zz_e2e", {"key": "zz_e2e", "name": "合成模組", "version": "0.0.1",
                                                     "license_key": "zz_e2e", "pages": [], "state": "loaded",
                                                     "reason": ""})
    page = _open(e2e_browser, live_server, make_user, "mse_sa4", "module-settings.html")
    page.locator("[data-testid='ms-state-zz_e2e']").wait_for(timeout=15000)
    assert not page.locator("[data-testid='ms-disabled-list']").is_visible()
    assert not page.locator("[data-testid='ms-license-zz_e2e']").is_visible()

    snap = registry.snapshot()
    try:
        registry.set_disabled_list("unreadable", "停用清單讀取失敗（database is locked），也沒有上次的紀錄")
        monkeypatch.setattr(lic, "module_license_check", lambda man: (False, "未授權：授權金鑰未包含此模組"))
        page.reload()
        banner = page.locator("[data-testid='ms-disabled-list']")
        banner.wait_for(state="visible", timeout=15000)
        assert banner.get_attribute("data-source") == "unreadable"
        assert "模組暫不載入" in banner.inner_text() and "database is locked" in banner.inner_text()
        note = page.locator("[data-testid='ms-license-zz_e2e']")
        note.wait_for(state="visible", timeout=10000)
        assert "授權變更於重啟後生效" in note.inner_text()
        assert page.locator("[data-testid='ms-pending-zz_e2e']").is_visible()
    finally:
        registry.restore(snap)
