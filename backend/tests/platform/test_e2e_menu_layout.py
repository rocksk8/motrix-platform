"""瀏覽器層級：選單宣告版 → 角色版面（C4；STAGE-C L79 更正 ②③）。

- 首屏由 MOTRIX_MENU 同步渲染（`data-menu-state=declared`），session 後打 /api/platform/menu 重排（`layout`）
- 讀版面失敗 ⇒ 保留宣告版＋`layout-failed`＋console 一筆（不靜默）
- 角色版面的 hide 只是顯示：被藏的頁面直接打網址照常開（不是「沒有權限」）
- 序號：較晚回來的舊回應丟掉
- 自訂模組只在套版面之後出現（它是資料，不在 MOTRIX_MENU）
等待終點一律是 `<html data-menu-state>`（〈e2e 等待的終點〉：等狀態，不等某一趟請求）。
不綁特定 L2：任取一個已載入、有選單項的模組；沒有 ⇒ skip 寫明。
"""
import pytest

pytest.importorskip("playwright.sync_api")

from core import registry  # noqa: E402

pytestmark = pytest.mark.e2e


def _pick():
    for m in registry.loaded():
        for p in (m.manifest or {}).get("pages") or []:
            if isinstance(p, dict) and p.get("menu"):
                return m.key, p["path"], p["menu"]["label"]
    pytest.skip("沒有已載入、宣告選單項的模組 ⇒ 無對象")


def _vocab(page):
    tops = page.locator(".mnav .mnav__top").all_text_contents()
    items = page.locator(".mnav .mnav__item").all_text_contents()
    return [t.strip() for t in (tops + items) if t and t.strip()]


def _state(page, want, timeout=10000):
    page.wait_for_selector("html[data-menu-state='%s']" % want, state="attached", timeout=timeout)


def _publish_hide(role, key, href):
    import db
    from core import definitions as D
    conn = db.get_db()
    try:
        D.save_draft(conn, "layout", "module:%s" % key, "role:%s" % role,
                     {"ops": [{"op": "hide", "target": "%s:%s/sidebar" % (key, href)}]}, user="test")
        D.publish(conn, "layout", "module:%s" % key, "role:%s" % role, note="test", user="test")
    finally:
        conn.close()


def test_declared_then_layout(live_server, make_user, new_page, login_as):
    _key, _href, label = _pick()
    u, p = make_user(username="c4e_sa", role="superadmin", modules=[])
    page = new_page()
    login_as(page, (u, p))
    page.goto(f"{live_server}/index.html")
    _state(page, "layout")
    assert label in _vocab(page)
    assert page.evaluate("Array.isArray(window.MOTRIX_MENU && window.MOTRIX_MENU.groups)")


def test_role_layout_hides_the_item_but_not_the_page(live_server, make_user, new_page, login_as):
    """hide 只是顯示：選單上不見，直接打網址照常開（不出現「沒有權限」）。正對照：別的角色照樣看得到。"""
    key, href, label = _pick()
    _publish_hide("superadmin", key, href)
    u, p = make_user(username="c4e_sa2", role="superadmin", modules=[])
    page = new_page()
    login_as(page, (u, p))
    page.goto(f"{live_server}/index.html")
    _state(page, "layout")
    assert label not in _vocab(page), "角色版面 hide 之後選單上不該出現"
    page.goto(f"{live_server}/pages/{href}")
    _state(page, "layout")
    assert page.locator("#no-module-notice").count() == 0, "hide 不是權限：頁面不可以被擋"
    assert page.locator("[data-testid='module-unavailable']").count() == 0
    # 正對照：admin 角色沒有這份版面 ⇒ 看得到（證明上面的「不見」來自版面，不是本來就沒有）
    u2, p2 = make_user(username="c4e_adm", role="admin", modules=sorted(_perm_keys(key, href)))
    page2 = new_page()
    login_as(page2, (u2, p2))
    page2.goto(f"{live_server}/index.html")
    _state(page2, "layout")
    assert label in _vocab(page2)


def _perm_keys(key, href):
    for m in registry.loaded():
        if m.key == key:
            for p in m.manifest.get("pages") or []:
                if isinstance(p, dict) and p.get("path") == href:
                    perm = p["menu"]["perm"]
                    return perm if isinstance(perm, list) else []
    return []


def test_layout_failure_keeps_declared_menu_and_says_so(live_server, make_user, new_page, login_as):
    _key, _href, label = _pick()
    u, p = make_user(username="c4e_fail", role="superadmin", modules=[])
    page = new_page()
    login_as(page, (u, p))
    logs = []
    page.on("console", lambda m: logs.append(m.text))
    page.route("**/api/platform/menu", lambda route: route.fulfill(status=500, body="boom"))
    page.goto(f"{live_server}/index.html")
    _state(page, "layout-failed")
    assert label in _vocab(page), "讀版面失敗 ⇒ 宣告版要留著"
    assert any("[menu]" in t and "保留宣告版" in t for t in logs), logs


def test_stale_layout_response_is_dropped(live_server, make_user, new_page, login_as):
    """第一趟 /api/platform/menu 故意晚回來、而且內容是空選單；第二趟（refresh）先回來。晚到的第一趟要被丟掉。"""
    _key, _href, label = _pick()
    u, p = make_user(username="c4e_seq", role="superadmin", modules=[])
    page = new_page()
    login_as(page, (u, p))
    page.add_init_script("""
      (function () {
        var real = window.fetch, n = 0
        window.fetch = function (url, opt) {
          if (String(url).indexOf('/api/platform/menu') >= 0 && ++n === 1) {
            return new Promise(function (res) {
              setTimeout(function () {
                window.__staleDelivered = true
                res(new Response(JSON.stringify({layout: {groups: [], errors: []}}), {status: 200, headers: {'Content-Type': 'application/json'}}))
              }, 1500)
            })
          }
          return real.apply(this, arguments)
        }
      })()
    """)
    page.goto(f"{live_server}/index.html")
    page.wait_for_selector("html[data-menu-state='declared']", state="attached", timeout=10000)
    page.evaluate("window.MotrixMenu.refresh()")
    _state(page, "layout")
    page.wait_for_function("window.__staleDelivered === true", timeout=10000)
    page.wait_for_timeout(100)
    assert label in _vocab(page), "晚到的舊回應（空選單）不可以蓋掉新的"


def test_custom_module_appears_after_layout(live_server, make_user, new_page, login_as, client):
    u, p = make_user(username="c4e_cm", role="superadmin", modules=[])
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}
    body = {"name": "C4瀏覽器自訂", "permission": "custom.c4e_cm",
            "numbering": {"prefix": "ZQ", "date": "YYYYMMDD", "digits": 4},
            "fields": [{"key": "item", "label": "項目", "type": "text"}],
            "workflow": {"initial": "draft", "states": [{"key": "draft", "label": "草稿", "final": True}], "transitions": []}}
    assert client.put("/api/definitions/custom_module/c4e_cm/draft", headers=h, json={"body": body}).status_code == 200
    assert client.post("/api/definitions/custom_module/c4e_cm/publish", headers=h, json={}).status_code == 200
    page = new_page()
    login_as(page, (u, p))
    page.goto(f"{live_server}/index.html")
    _state(page, "layout")
    v = _vocab(page)
    assert "C4瀏覽器自訂" in v and "模組建構器" in v, v
    assert page.locator("script[data-custom-modules-nav]").count() == 0, "custom-modules-nav.js 已退場"
