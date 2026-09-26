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


def _seq(page, n, state, timeout=10000):
    """等第 n 輪完成（C4-S1：第二輪以後不能只等 data-menu-state——上一輪留下的 layout 會讓它立刻成立）。"""
    page.wait_for_selector("html[data-menu-seq='%d'][data-menu-state='%s']" % (n, state), state="attached", timeout=timeout)


#: 第一趟 /api/platform/menu 扣住，直到題目呼叫 window.__releaseFirst() 才回——**不靠時間差**。
#: 〔O10（第九班全量紅）：原本 setTimeout 1500ms 放行；負載下 goto 等 load 超過 1.5 秒 ⇒ 舊回應在第二趟之前就回來、
#:   沒有更新的序號可以比 ⇒ 被正常套用（產品行為正確）⇒ 題目等不到 pending 而逾時。題目的等待終點錯了，產品的序號沒有空窗〕
#: 回應物件讀到時設 window.__staleRead（ok 或 json() 被碰到＝產品已經在處理這一趟），題目再等兩個 macrotask 讓 then 鏈跑完。
_HOLD_FIRST = """
  (function () {
    var real = window.fetch, n = 0
    window.fetch = function (url, opt) {
      if (String(url).indexOf('/api/platform/menu') >= 0 && ++n === 1) {
        return new Promise(function (res) {
          window.__releaseFirst = function () {
            window.__staleDelivered = true
            res({ get ok() { window.__staleRead = true; return %(ok)s }, status: %(status)d,
                  json: function () { window.__staleRead = true; return Promise.resolve(%(body)s) } })
          }
        })
      }
      return real.apply(this, arguments)
    }
  })()
"""


def _hold_first(page, ok, status, body):
    page.add_init_script(_HOLD_FIRST % {"ok": "true" if ok else "false", "status": status, "body": body})


def _release_first_and_settle(page):
    """放行第一趟，等產品讀到它，再等兩個 macrotask（then／catch 鏈跑完）——不用 wait_for_timeout。"""
    page.evaluate("window.__releaseFirst()")
    page.wait_for_function("window.__staleRead === true", timeout=10000)
    page.evaluate("() => new Promise(r => setTimeout(() => setTimeout(r, 0), 0))")


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
    assert any("[menu]" in t and "保留宣告版" in t and "自訂模組暫不顯示" in t for t in logs), logs   # C4-S4：講清楚少了什麼


def test_stale_layout_response_is_dropped(live_server, make_user, new_page, login_as):
    """第一趟 /api/platform/menu 扣住、內容是空選單；第二趟（refresh）先回來。放行第一趟之後它要被丟掉（序號）。
    O10：第一趟由題目放行，第一趟送出後狀態一定停在 pending（不再靠 1.5 秒的時間差）。突變：成功路徑拿掉序號檢查 ⇒ 紅。"""
    _key, _href, label = _pick()
    u, p = make_user(username="c4e_seq", role="superadmin", modules=[])
    page = new_page()
    login_as(page, (u, p))
    _hold_first(page, True, 200, "{layout: {groups: [], errors: []}}")
    page.goto(f"{live_server}/index.html", wait_until="domcontentloaded")
    page.wait_for_function("typeof window.__releaseFirst === 'function'", timeout=10000)
    assert page.get_attribute("html", "data-menu-state") == "pending", "第一趟扣住時狀態要是 pending"
    assert page.evaluate("window.MotrixMenu.refresh()") == 2
    _seq(page, 2, "layout")
    _release_first_and_settle(page)
    assert label in _vocab(page), "晚到的舊回應（空選單）不可以蓋掉新的"
    assert page.get_attribute("html", "data-menu-seq") == "2"
    assert page.get_attribute("html", "data-menu-state") == "layout"


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


def test_refresh_resets_the_wait_point(live_server, make_user, new_page, login_as):
    """稽核 X C4-S1：第一輪完成後再 refresh ⇒ 狀態先回到 pending，第二輪完成時 data-menu-seq=2。
    突變：_applyLayout 不設 pending ⇒ 「refresh 後立刻是 pending」紅。"""
    u, p = make_user(username="c4e_s1", role="superadmin", modules=[])
    page = new_page()
    login_as(page, (u, p))
    page.goto(f"{live_server}/index.html")
    _seq(page, 1, "layout")
    assert page.evaluate("window.MotrixMenu.refresh()") == 2
    assert page.get_attribute("html", "data-menu-state") == "pending", "refresh 之後等待點要重設"
    _seq(page, 2, "layout")


def test_stale_failed_response_is_dropped(live_server, make_user, new_page, login_as):
    """稽核 X C4-S2：第一趟扣住、放行時是 500；第二趟先成功 ⇒ 最後狀態仍是 layout（不可以被舊的失敗改成 layout-failed）。
    O10：同上改成題目放行。突變：失敗路徑拿掉序號檢查 ⇒ 紅。"""
    _key, _href, label = _pick()
    u, p = make_user(username="c4e_s2", role="superadmin", modules=[])
    page = new_page()
    login_as(page, (u, p))
    logs = []
    page.on("console", lambda m: logs.append(m.text))
    _hold_first(page, False, 500, "{}")
    page.goto(f"{live_server}/index.html", wait_until="domcontentloaded")
    page.wait_for_function("typeof window.__releaseFirst === 'function'", timeout=10000)
    assert page.evaluate("window.MotrixMenu.refresh()") == 2
    _seq(page, 2, "layout")
    _release_first_and_settle(page)
    assert page.get_attribute("html", "data-menu-state") == "layout", "晚到的舊失敗不可以蓋掉新的成功"
    assert label in _vocab(page)
    assert not any("讀不到 /api/platform/menu" in t for t in logs), logs


def test_menu_api_is_called_once_per_page_load(live_server, make_user, new_page, login_as):
    """稽核 X C4-O2：session 沒變時，每次載入頁面只打一次 /api/platform/menu（golden 忽略它，重複或迴圈打要有人守）。"""
    u, p = make_user(username="c4e_o2", role="superadmin", modules=[])
    page = new_page()
    login_as(page, (u, p))
    calls = []
    page.on("request", lambda r: calls.append(r.url) if "/api/platform/menu" in r.url else None)
    page.goto(f"{live_server}/index.html")
    _seq(page, 1, "layout")
    page.wait_for_timeout(1500)                       # 給重複／迴圈呼叫一個出現的機會
    assert len(calls) == 1, calls

