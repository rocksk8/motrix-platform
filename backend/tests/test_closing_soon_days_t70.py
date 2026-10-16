# -*- coding: utf-8 -*-
"""T70-3b：地圖標案『即將截止』的天數是設定 `tender_closing.closing_soon_days`（預設 7、1～60）。
改設定一律走真實帳號＋HTTP（設定中心路由）；地圖點位用 `/api/map/points` 取；不 monkeypatch 權限。"""
import datetime

import pytest

import db
from helpers import settings_groups  # noqa: F401
from helpers import settings_registry as SR
from routers import map_points
from tests.test_mp1_map_points_link_to_records_2026_09_24 import _geo  # noqa: F401
from tests._requires import requires_module

needs_tender_radar = requires_module("tender_radar", "本題驗地圖上的標案點，標案資料由標案雷達（tender_radar）提供；它不在時沒有對象")

URL = "/api/settings-center/groups/tender_closing"
TODAY = datetime.date(2026, 9, 24)


def _login(client, make_user, name, role, modules=None):
    u, p = make_user(username=name, role=role, modules=modules)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def su(client, make_user):
    return _login(client, make_user, "tc_su", "superadmin")


def _set(client, su, n):
    r = client.post(URL, json={"values": {"closing_soon_days": n}, "reason": "測試"}, headers=su)
    assert r.status_code == 200, r.text
    assert not r.json().get("pending"), "risk=none 的設定必須立即生效"


def test_default_is_7_and_the_boundary_equals_the_old_constant(su):
    f = {x["key"]: x for x in SR.groups()["tender_closing"]["fields"]}["closing_soon_days"]
    assert (f["default"], f["min"], f["max"]) == (7, 1, 60)
    assert map_points.CLOSING_SOON_DAYS == 7 == map_points.closing_soon_days()
    st = lambda d: map_points._deadline_status((TODAY + datetime.timedelta(days=d)).isoformat(), TODAY)
    assert [st(-1), st(0), st(7), st(8)] == ["closed", "closing", "closing", "open"]


def test_changing_the_setting_moves_the_boundary(client, su):
    st = lambda d: map_points._deadline_status((TODAY + datetime.timedelta(days=d)).isoformat(), TODAY)
    _set(client, su, 3)
    assert [st(3), st(4)] == ["closing", "open"]
    _set(client, su, 30)
    assert [st(30), st(31)] == ["closing", "open"]
    assert map_points._deadline_status("2026-09-23", TODAY) == "closed", "已截止不受影響"
    assert map_points._deadline_status("", TODAY) == "unknown", "讀不懂的日期仍是 unknown"


@needs_tender_radar
def test_map_points_endpoint_follows_the_setting_and_reports_the_number(client, su, _geo, monkeypatch):
    monkeypatch.setattr(map_points, "_today", lambda: TODAY)
    conn = db.get_db()
    try:
        for case_no, deadline in (("TC-A", "2026-09-27"), ("TC-B", "2026-10-04"), ("TC-C", "2026-11-30")):
            conn.execute("INSERT INTO tenders (case_no, name, org, location, deadline, fetched_at) VALUES (?,?,?,?,?,?)",
                         (case_no, "標案" + case_no, "台中市西屯區", "台中市西屯區", deadline, "2026-09-24"))
        conn.commit()
    finally:
        conn.close()

    def get():
        r = client.get("/api/map/points?sources=tenders", headers=su)
        assert r.status_code == 200, r.text
        d = r.json()
        return d["closingSoonDays"], {p["caseNo"]: p["deadlineStatus"] for p in d["points"]}

    assert get() == (7, {"TC-A": "closing", "TC-B": "open", "TC-C": "open"})        # 預設 7：與以前相同
    _set(client, su, 14)                                                              # 設定一改，快取不可回舊結果
    assert get() == (14, {"TC-A": "closing", "TC-B": "closing", "TC-C": "open"})
    _set(client, su, 1)
    assert get() == (1, {"TC-A": "open", "TC-B": "open", "TC-C": "open"})


def test_bounds_and_permissions_with_real_users(client, make_user, su):
    keep = map_points.closing_soon_days()
    for bad in (0, 61, -1, "abc"):
        r = client.post(URL, json={"values": {"closing_soon_days": bad}, "reason": "x"}, headers=su)
        assert r.status_code == 400, (bad, r.text)
    ad = _login(client, make_user, "tc_admin", "admin", modules=["tender_radar", "reports"])
    assert client.post(URL, json={"values": {"closing_soon_days": 14}, "reason": "x"}, headers=ad).status_code in (401, 403)
    assert client.post(URL, json={"values": {"closing_soon_days": 14}, "reason": "x"}).status_code in (401, 403)
    assert map_points.closing_soon_days() == keep


def test_unreadable_or_invalid_setting_falls_back_to_7(monkeypatch):
    monkeypatch.setattr(SR, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert map_points.closing_soon_days() == 7
    monkeypatch.setattr(SR, "get", lambda *a, **k: 0)
    assert map_points.closing_soon_days() == 7
    monkeypatch.setattr(SR, "get", lambda *a, **k: 61)
    assert map_points.closing_soon_days() == 7


# ── 頁面（e2e）：標籤用後端回的天數，沒回就是 7 ───────────────────────────────
@pytest.mark.e2e
def test_map_page_labels_use_closing_soon_days(live_server, make_user, _geo, e2e_browser):
    import json
    pytest.importorskip("playwright.sync_api")
    from tests._e2e_login import inject_login
    from tests.test_mp3_map_tenders_by_deadline_2026_09_24 import _POINTS, _D, _rendered, _table
    u, p = make_user(username="tc_page", role="superadmin")
    page = e2e_browser.new_page(viewport={"width": 1280, "height": 900})
    page.route("**/api/map/points*", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"points": _POINTS, "locations": [], "sources": [], "closingSoonDays": 14})))
    page.route("**/tile.openstreetmap.org/**", lambda route: route.abort())
    inject_login(page, live_server, u, p)
    page.goto(live_server + "/pages/map.html")
    page.wait_for_function("() => { const d = " + _D + "; return d.info && d.info.points && d.info.points.length === 5 }", timeout=15000)
    _rendered(page)
    opt = page.locator("select.mp-tender-filter option[value=closing]").inner_text()
    label = {r[0]: r[1] for r in _table(page)}
    assert opt == "14 天內截止" and label["T-SOON"] == "14 天內截止", (opt, label)
    page.close()
