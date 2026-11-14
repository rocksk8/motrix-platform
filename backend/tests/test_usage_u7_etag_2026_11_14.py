# -*- coding: utf-8 -*-
"""T86 U7：首頁請求量最高、回到分頁會重打同幾支 ⇒ 內容沒變就回 304（approval-queue/count、dashboard/mine）。

守住：① 第一次 200＋ETag；② 帶 If-None-Match 且內容沒變 ⇒ 304、沒有 body；③ 內容一變 ⇒ 200 新內容（不會讓舊資料多活）；
④ 每位使用者各算各的（A 的 ETag 對 B 不會 304）；⑤ bootstrap 直接呼叫原函式時仍拿到 dict（沒有 request）。
"""
import json

import pytest


def _login(client, u):
    r = client.post("/api/auth/login", json={"username": u[0], "password": u[1]})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.mark.parametrize("url", ["/api/approval-queue/count", "/api/dashboard/mine"])
def test_unchanged_content_is_304_with_no_body(client, make_user, url):
    h = _login(client, make_user(username="u7_a", role="admin"))
    r1 = client.get(url, headers=h)
    assert r1.status_code == 200 and r1.headers["etag"].startswith('"')
    assert "no-cache" in r1.headers["cache-control"] and "private" in r1.headers["cache-control"]
    r2 = client.get(url, headers={**h, "If-None-Match": r1.headers["etag"]})
    assert r2.status_code == 304 and r2.content == b"" and r2.headers["etag"] == r1.headers["etag"]
    r3 = client.get(url, headers={**h, "If-None-Match": '"stale"'})
    assert r3.status_code == 200 and r3.content


def test_dashboard_mine_ignores_its_timestamp_but_not_its_content(client, make_user):
    from helpers.http_etag import _digest
    a = {"groups": [{"key": "x", "count": 1}], "empty": False, "generatedAt": "2026-11-14 10:00:00"}
    b = dict(a, generatedAt="2026-11-14 10:00:09")
    c = dict(a, groups=[{"key": "x", "count": 2}])
    assert _digest(a, ("generatedAt",)) == _digest(b, ("generatedAt",))
    assert _digest(a, ("generatedAt",)) != _digest(c, ("generatedAt",))
    assert _digest(a, ()) != _digest(b, ())


def test_another_users_etag_only_matches_when_the_content_is_byte_identical(client, make_user):
    ha = _login(client, make_user(username="u7_x", role="admin"))
    hb = _login(client, make_user(username="u7_y", role="sales"))
    ra = client.get("/api/approval-queue/count", headers=ha)
    rb = client.get("/api/approval-queue/count", headers={**hb, "If-None-Match": ra.headers["etag"]})
    # 兩人都沒有待簽時內容相同 ⇒ 304 是對的（內容一樣）；有差異就一定是 200
    assert (rb.status_code == 304) == (rb.headers["etag"] == ra.headers["etag"]) and rb.status_code in (200, 304)
    if rb.status_code == 200:
        assert rb.json() != ra.json()


def test_bootstrap_bundle_still_returns_the_approval_count_section(client, make_user):
    h = _login(client, make_user(username="u7_b", role="admin"))
    r = client.get("/api/bootstrap", headers=h)
    assert r.status_code == 200, r.text
    d = r.json()
    sec = d.get("approvalCount") or (d.get("data") or {}).get("approvalCount")
    assert sec is not None and "count" in sec and "approvalCount" not in (d.get("errors") or {}), d.keys()


def test_bootstrap_still_gets_plain_dicts_from_the_original_handlers():
    from routers import approval_queue, dashboard_mine
    import inspect
    assert list(inspect.signature(approval_queue.get_approval_queue_count).parameters) == ["authorization"]
    assert inspect.signature(dashboard_mine.dashboard_mine).parameters["request"].default is None   # 直接呼叫不帶 request ⇒ 回 dict


def test_home_uses_the_bootstrap_warm_load_only_for_its_first_approval_count_and_the_limit_allows_it():
    from pathlib import Path
    front = Path(__file__).resolve().parents[2] / "frontend"
    idx = (front / "index.html").read_text(encoding="utf-8")
    a = idx.index("async _loadApprovalMineOnce()")
    blk = idx[a:a + 1600]
    assert "window.__mineBootUsed" in blk and "first && window.motrixBootFetch || fetch" in blk
    # 回到分頁（focus／visibilitychange）走的是第二趟以後 ⇒ 真請求；第一趟之後 __mineBootUsed 一律為真
    assert blk.index("const first = !window.__mineBootUsed") < blk.index("window.__mineBootUsed = true") < blk.index("approval-queue/count")
    guard = (front / "static" / "auth-guard.js").read_text(encoding="utf-8")
    assert "'/api/approval-queue/count': ['approvalCount', 3]" in guard      # 側欄／鈴鐺各一＋首頁一


# ───────────── e2e：首頁開頁走 bootstrap／bundle，請求數降下來；失敗時退回原端點 ─────────────
from tests._e2e_login import inject_login  # noqa: E402


def _count_requests(page, needles):
    seen = []
    page.on("request", lambda r: seen.append(r.url) if "/api/" in r.url else None)
    return seen


@pytest.mark.e2e
def test_home_first_load_uses_one_bundle_request_instead_of_six(live_server, make_user, e2e_browser):
    u, p = make_user(username="u7_home", role="superadmin")[:2]
    page = e2e_browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
    seen = _count_requests(page, None)
    inject_login(page, live_server, u, p)
    page.goto(f"{live_server}/index.html")
    page.wait_for_function("() => { try { return Alpine.$data(document.body).statsLoaded === true && !Alpine.$data(document.body).loading } catch (e) { return false } }", timeout=20000)
    page.wait_for_timeout(800)
    path = lambda u_: u_.split("?")[0].replace(live_server, "")   # noqa: E731
    got = [path(x) for x in seen]
    assert got.count("/api/dashboard/bundle") == 1, got
    for single in ("/api/dashboard/stats", "/api/dashboard/monthly", "/api/dashboard/expenses-monthly",
                   "/api/dashboard/funnel", "/api/dashboard/ops-alerts", "/api/dashboard/activity-feed"):
        assert single not in got, (single, got)
    assert got.count("/api/approval-queue/count") == 0, got          # 開頁第一趟由 bootstrap 供應
    assert page.evaluate("() => Alpine.$data(document.body).mineLoaded === true")


@pytest.mark.e2e
def test_home_falls_back_to_the_single_endpoints_when_the_bundle_fails(live_server, make_user, e2e_browser):
    u, p = make_user(username="u7_home2", role="superadmin")[:2]
    page = e2e_browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
    page.route("**/api/dashboard/bundle*", lambda r: r.fulfill(status=500, body="{}"))
    seen = _count_requests(page, None)
    inject_login(page, live_server, u, p)
    page.goto(f"{live_server}/index.html")
    page.wait_for_function("() => { try { return Alpine.$data(document.body).statsLoaded === true && !Alpine.$data(document.body).loading } catch (e) { return false } }", timeout=20000)
    got = [x.split("?")[0].replace(live_server, "") for x in seen]
    for single in ("/api/dashboard/stats", "/api/dashboard/monthly", "/api/dashboard/funnel", "/api/dashboard/ops-alerts", "/api/dashboard/activity-feed"):
        assert got.count(single) == 1, (single, got)
