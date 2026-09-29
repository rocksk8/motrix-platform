"""W2 稽核修正（S1／S5／S6）：首頁「等我簽核」。

S1  focus＋visibilitychange 連發只送一趟 /approval-queue/count；隔一段時間再觸發會再送（不是永久封鎖）。
S5  /count 讀不到 ⇒ hero／band 顯示「—」，不沿用 dashboard/stats 的報價單版本數字。
S6  /count 在 dashboard/stats 的 json 解析期間完成 ⇒ 數字不被舊值蓋回。
"""
import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402

B = "document.body"
DATA = "Alpine.$data(document.body)"


def _home(e2e_browser, live_server, make_user, name, route=None):
    u, p = make_user(username=name, role="superadmin")[:2]
    page = e2e_browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
    if route:
        page.route("**/api/approval-queue/count", route)
    inject_login(page, live_server, u, p)
    page.goto(f"{live_server}/index.html")
    return page


@pytest.mark.e2e
def test_s1_focus_and_visibility_share_one_request(live_server, make_user, e2e_browser):
    page = _home(e2e_browser, live_server, make_user, "w2fix_s1")
    page.wait_for_function(f"() => {{ try {{ return {DATA}.mineLoaded === true }} catch (e) {{ return false }} }}", timeout=20000)
    page.wait_for_timeout(600)                                   # 讓初次載入的 300 ms 節流窗過去
    n = []
    page.on("request", lambda r: n.append(r.url) if "/api/approval-queue/count" in r.url else None)
    page.evaluate("() => { window.dispatchEvent(new Event('focus')); document.dispatchEvent(new Event('visibilitychange')) }")
    page.wait_for_timeout(1200)
    assert len(n) == 1, "一次回到分頁送了 %d 個 /count" % len(n)
    page.wait_for_timeout(400)
    page.evaluate("() => window.dispatchEvent(new Event('focus'))")
    page.wait_for_timeout(1200)
    assert len(n) == 2, "隔開之後的再次回到分頁應該再讀一次（%d）" % len(n)


@pytest.mark.e2e
def test_s5_when_count_fails_hero_and_band_show_dash(live_server, make_user, e2e_browser):
    page = _home(e2e_browser, live_server, make_user, "w2fix_s5", route=lambda r: r.fulfill(status=500, body="{}"))
    page.wait_for_function(f"() => {{ try {{ return {DATA}.statsLoaded === true && !{DATA}.loading }} catch (e) {{ return false }} }}", timeout=20000)
    assert page.locator(".h-band__c .h-band__n").first.inner_text().strip() == "—"
    assert page.locator(".h-state div:has-text('我的待簽核') b").first.inner_text().strip() == "—"
    hero = page.locator(".h-hero__t").inner_text()
    assert "今天有" not in hero and "目前沒有待您簽核" not in hero, hero
    assert "讀不到待簽核清單" in page.locator(".h-band__c .h-band__p").first.inner_text()
    assert page.locator('[data-testid="home-mine-unknown"]').count() == 1


@pytest.mark.e2e
def test_s6_count_finishing_during_stats_json_is_not_overwritten(live_server, make_user, e2e_browser):
    page = _home(e2e_browser, live_server, make_user, "w2fix_s6")
    page.wait_for_function(f"() => {{ try {{ return {DATA}.mineLoaded === true && {DATA}.statsLoaded === true }} catch (e) {{ return false }} }}", timeout=20000)
    res = page.evaluate(f"""async () => {{
      const d = {DATA};
      d.mineLoaded = false; d.stats.waitingForMe = 0;
      const orig = window.fetch;
      window.fetch = async (url, o) => {{
        if (String(url).includes('dashboard/stats')) {{
          const r = await orig(url, o);
          // /count 恰好在這一趟的 json 解析期間完成
          return {{ ok: true, status: 200, json: async () => {{
            d.mineCount = 7; d.stats.waitingForMe = 7; d.mineLoaded = true;
            return {{ ...(await r.json()), waitingForMe: 99 }} }} }}
        }}
        return orig(url, o)
      }}
      await d.loadStats()
      window.fetch = orig
      return d.stats.waitingForMe }}""")
    assert res == 7, "被舊值蓋回：%r" % res
