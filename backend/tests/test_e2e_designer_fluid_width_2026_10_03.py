# -*- coding: utf-8 -*-
"""D12 驗證回饋（使用者）：新設計器區塊要置中，寬度隨視窗大小自動伸縮（不固定上限數字）。
以 1366／1600／2000／2560 與手機 400px 量：設計器寬度佔視窗寬度的比例、左右留白對稱（置中）、沒有橫向捲動、中間預覽欄隨視窗變寬（單調遞增）。
兩頁（請款類型、模組建構器 ② 表單）都量。headless。"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.e2e

from tests._builder_nav import go_step  # noqa: E402
from tests._e2e_login import inject_login  # noqa: E402

KEY = "d12_fluid"
WIDTHS = (1366, 1600, 2000, 2560)
FRESH = ("try { if (!sessionStorage.getItem('_d12_fresh')) { localStorage.removeItem('mb_designer'); localStorage.removeItem('et_designer');"
         " sessionStorage.setItem('_d12_fresh', '1'); } sessionStorage.setItem('_no_legacy_pin', '1'); } catch (e) {}")
MEASURE = """() => { const f = document.querySelector('.fd').getBoundingClientRect(), p = document.querySelector('.fd-paper').getBoundingClientRect(), W = document.documentElement.clientWidth;
  return { left: f.left, right: W - f.right, width: f.width, paper: p.width, W: W, hscroll: document.documentElement.scrollWidth > W } }"""


def _body():
    f = lambda k, label, **kw: dict({"key": k, "label": label, "type": "text", "dataClass": "T1"}, **kw)       # noqa: E731
    return {"name": "流動寬度", "icon": "", "permission": "custom." + KEY, "numbering": {"prefix": "FW", "date": "YYYYMMDD", "digits": 4},
            "fields": [f("place", "地點"), f("memo", "備註")],
            "workflow": {"initial": "draft", "states": [{"key": "draft", "label": "草稿", "final": True}], "transitions": []},
            "ui": {"form": {"groups": [{"title": "基本資料", "fields": ["place", "memo"]}]}, "list": {"columns": ["place"]}}}


@pytest.fixture()
def env(live_server, client, make_user, new_context):
    u = make_user(username="fw_sa", role="superadmin")
    tok = client.post("/api/auth/login", json={"username": u[0], "password": u[1]}).json()["token"]
    assert client.put("/api/definitions/custom_module/%s/draft" % KEY, json={"body": _body()}, headers={"Authorization": "Bearer " + tok}).status_code == 200

    def open_page(which, width):
        pg = new_context(viewport={"width": width, "height": 1000}).new_page()
        inject_login(pg, live_server, u[0], u[1])
        pg.context.add_init_script(FRESH)
        if which == "et":
            pg.goto(live_server + "/pages/expense-types.html?key=travel")
        else:
            pg.goto("%s/pages/module-builder.html?key=%s" % (live_server, KEY))
            pg.wait_for_selector("#mb-step-1", state="visible")
            go_step(pg, 2)
        pg.wait_for_selector(".fd .fd-paper", state="visible", timeout=20000)
        return pg
    return open_page


@pytest.mark.parametrize("which", ["et", "mb"])
def test_designer_is_centered_fluid_and_grows_with_the_window(env, which):
    seen = []
    for w in WIDTHS:
        m = env(which, w).evaluate(MEASURE)
        assert not m["hscroll"], (w, m)
        assert m["width"] / m["W"] >= 0.9, (w, m)                                    # 幾乎吃滿視窗（扣掉頁面內距與側欄）
        assert abs(m["left"] - m["right"]) <= 40, (w, m)                              # 置中：左右留白對稱
        seen.append(m["paper"])
    assert seen == sorted(seen) and seen[-1] > seen[0] * 1.5, seen                    # 中間預覽欄隨視窗變寬（不是固定寬度）


@pytest.mark.parametrize("which", ["et", "mb"])
def test_phone_width_has_no_horizontal_scroll(env, which):
    m = env(which, 400).evaluate(MEASURE)
    assert not m["hscroll"] and m["width"] <= m["W"], m
    assert m["left"] >= 8 and m["right"] >= 8, m                                      # 手機維持內距
