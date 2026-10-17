# -*- coding: utf-8 -*-
"""T72-A e2e：系統中心與系統子頁的『分類欄』位置固定（切換時不跳動）。

- 寬螢幕（1366／1536／1920／2560）：系統中心的分類清單（`.groups` 內第一個分類）與子頁左欄（`#sys-rail` 內第一個分類）
  的 x／y／寬度／高度相差 ≤1px（每一個分類的 y／高度都比對，確認列距相同；整欄高度也比對）；整個欄（nav）的 x／y／寬度也一致；各頁的主內容區（`.page-main`）左緣一致
- 子頁之間：主內容左緣一致
- data-no-sys-rail 頁（費用類別）仍沒有分類欄
- 窄螢幕（800px）：系統中心不套固定欄（仍在內容欄內），子頁不畫欄
截圖：環境變數 T72_SHOTS 指定的資料夾（沒設就不存）。
"""
import json
import os

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

WIDTHS = (1366, 1536, 1920, 2560)
MAIN = "main, .page-main, [class$=\"-main\"], [class*=\"-main \"]"
SHOTS = os.environ.get("T72_SHOTS", "")

_ROWS = "els => els.map(e => { const r = e.getBoundingClientRect(); return {x: r.x, y: r.y, w: r.width, h: r.height} })"
_BOX = """(sel) => { const e = document.querySelector(sel); if (!e) return null; const r = e.getBoundingClientRect();
  return {x: r.x, y: r.y, w: r.width, h: r.height} }"""


def _near(a, b, what, tol=1.0):
    assert a is not None and b is not None, "%s: 找不到元素 %s %s" % (what, a, b)
    for k in ("x", "y", "w", "h"):
        assert abs(a[k] - b[k]) <= tol, "%s：%s 不一致 %s vs %s" % (what, k, a, b)


def _shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name + ".png"))


@pytest.mark.e2e
def test_category_rail_is_in_the_same_place_on_hub_and_sub_pages(live_server, make_user, new_context):
    sa = make_user(username="rail_e2e_sa", role="superadmin")
    results = []
    for w in WIDTHS:
        page = new_context(viewport={"width": w, "height": 900}).new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        inject_login(page, live_server, sa[0], sa[1])
        page.goto(live_server + "/pages/system-hub.html")
        page.wait_for_selector("[data-testid=hub-groups] .grp", state="visible", timeout=25000)
        page.click("[data-testid=hub-group-data]")
        page.wait_for_selector("[data-testid=hub-item-storage-settings]", state="visible", timeout=10000)
        hrefs = page.eval_on_selector_all("[data-testid=hub-pane] a.row[data-testid^=hub-item-]", "els => els.map(e => e.getAttribute('href')).filter(h => h)")[:3]
        assert len(hrefs) == 3, hrefs
        hub_first = page.evaluate(_BOX, "[data-testid=hub-groups] .grp")
        hub_rail = page.evaluate(_BOX, "[data-testid=hub-groups]")
        hub_rows = page.eval_on_selector_all("[data-testid=hub-groups] .grp", _ROWS)
        hub_main = page.evaluate(_BOX, MAIN)
        _shot(page, "hub_%d" % w)
        subs = {}
        for i, href in enumerate(hrefs):
            page.goto(live_server + "/pages/" + href.lstrip("/").split("pages/")[-1])
            page.wait_for_selector("[data-testid=sys-rail]", state="visible", timeout=25000)
            first = page.evaluate(_BOX, "#sys-rail a.sr-i")
            rail = page.evaluate(_BOX, "#sys-rail")
            sub_rows = page.eval_on_selector_all("#sys-rail a.sr-i", _ROWS)
            main = page.evaluate(_BOX, MAIN)
            _near(hub_first, first, "%dpx 系統中心 vs %s 的第一個分類" % (w, i))
            _near(hub_rail, rail, "%dpx 系統中心 vs %s 的整欄" % (w, i))
            assert len(hub_rows) == len(sub_rows) >= 7, (hub_rows, sub_rows)
            for n, (a, b) in enumerate(zip(hub_rows, sub_rows), 1):       # 每一個分類（不只第一、二個）：列距不同會越往下越偏
                assert abs(a["y"] - b["y"]) <= 1 and abs(a["h"] - b["h"]) <= 1, "%dpx 第 %d 個分類 %s vs %s" % (w, n, a, b)
            assert abs(hub_main["x"] - main["x"]) <= 1, "%dpx 主內容區左緣 %s vs %s" % (w, hub_main, main)
            subs[href] = {"first": first, "rail": rail, "main": main}
            _shot(page, "sub%d_%d" % (i + 1, w))
        mains = [v["main"]["x"] for v in subs.values()]
        assert max(mains) - min(mains) <= 1, "%dpx 子頁主內容左緣不一致 %s" % (w, mains)
        assert not errs, errs
        results.append({"width": w, "hub_first": hub_first, "hub_rail": hub_rail, "hub_main": hub_main, "subs": subs})
        page.context.close()
    if SHOTS:
        with open(os.path.join(SHOTS, "results.json"), "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=1)


@pytest.mark.e2e
def test_no_rail_pages_stay_without_rail_and_narrow_keeps_old_behaviour(live_server, make_user, new_context):
    sa = make_user(username="rail_e2e_sa2", role="superadmin")
    page = new_context(viewport={"width": 1536, "height": 900}).new_page()
    inject_login(page, live_server, sa[0], sa[1])
    page.goto(live_server + "/pages/expense-types.html")
    page.wait_for_selector("body[data-no-sys-rail]", state="attached", timeout=25000)
    page.wait_for_timeout(1500)
    assert page.locator("#sys-rail").count() == 0
    page.context.close()
    # 800px：系統中心的分類清單在內容欄裡（不是 fixed），沒有 body 左內距
    page = new_context(viewport={"width": 800, "height": 900}).new_page()
    inject_login(page, live_server, sa[0], sa[1])
    page.goto(live_server + "/pages/system-hub.html")
    page.wait_for_selector("[data-testid=hub-groups] .grp", state="visible", timeout=25000)
    st = page.evaluate("() => ({pos: getComputedStyle(document.querySelector('[data-testid=hub-groups]')).position, pad: getComputedStyle(document.body).paddingLeft})")
    assert st["pos"] != "fixed" and st["pad"] == "0px", st
    page.goto(live_server + "/pages/users.html")
    page.wait_for_selector("[data-testid=sys-crumb]", state="attached", timeout=25000)
    page.wait_for_timeout(1500)
    assert page.locator("#sys-rail").is_visible() is False
    page.context.close()
    # 寬螢幕但清單沒畫出來（端點失敗）：不留 208px 空白欄
    page = new_context(viewport={"width": 1536, "height": 900}).new_page()
    inject_login(page, live_server, sa[0], sa[1])
    page.route("**/api/system-hub", lambda route: route.fulfill(status=500, body="{}"))
    page.goto(live_server + "/pages/system-hub.html")
    page.wait_for_timeout(2500)
    assert page.locator("[data-testid=hub-groups]").is_visible() is False
    assert page.evaluate("() => getComputedStyle(document.body).paddingLeft") == "0px"
    page.context.close()


def test_hub_rail_css_matches_sidebar_rail_geometry():
    """靜態守門：系統中心的固定欄寬度必須等於 sidebar.js 的 RAIL_W，且 >900px 才套用（和 RAIL_NARROW 一致）。"""
    import re
    here = os.path.dirname(__file__)
    from core import source_tree
    hub = source_tree.page_file("system-hub.html").read_text(encoding="utf-8")
    sb = open(os.path.join(here, "..", "..", "frontend", "static", "sidebar.js"), encoding="utf-8").read()
    rw = int(re.search(r"RAIL_W = (\d+)", sb).group(1))
    rn = int(re.search(r"RAIL_NARROW = (\d+)", sb).group(1))
    assert "@media (min-width:%dpx){" % (rn + 1) in hub
    block = hub[hub.index("@media (min-width:%dpx){" % (rn + 1)):]
    block = block[:block.index("\n    }\n")]
    assert "body.has-rail{padding-left:%dpx}" % rw in block and "width:%dpx" % rw in block
    assert "position:fixed;left:var(--sidebar-w,0px);top:var(--topbar-h,56px);bottom:0" in block
