# -*- coding: utf-8 -*-
"""D12 輔助證據：用 Playwright 的**真滑鼠事件**（page.mouse.down／move／up；Chromium 會合成原生拖放，不是 dispatch_event）驗新設計器的拖放：
① 左邊「長文字」拖到兩個欄位之間 ⇒ 新欄位插在那裡；③ 欄位拖到另一個區塊 ⇒ 搬過去（不是複製）；⑤ 欄位拖進空區塊。
⚠️ 這**不取代**使用者親手驗證（不同瀏覽器／觸控板／手感；指引 docs/platform/plans/D12-VERIFY-GUIDE.md）；只證明「真滑鼠事件序列」在 Chromium 下行得通。
每題等終點（欄位數／順序），不用 sleep。headless。"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.e2e

from tests._builder_nav import go_step  # noqa: E402
from tests._e2e_login import inject_login  # noqa: E402

KEY = "d12_mouse"
FRESH = ("try { if (!sessionStorage.getItem('_d12_fresh')) { localStorage.removeItem('mb_designer'); localStorage.removeItem('et_designer');"
         " sessionStorage.setItem('_d12_fresh', '1'); } sessionStorage.setItem('_no_legacy_pin', '1'); } catch (e) {}")
LAYOUT_JS = """() => [...document.querySelectorAll('.fd .fd-sec')].map(s => ({
  title: ((s.querySelector('.fd-sechead') || {}).innerText || '').split('\\n')[0].trim(),
  fields: [...s.querySelectorAll('.fd-fld')].map(f => (f.querySelector('label') || f).innerText.split('\\n')[0].replace('*', '').trim())}))"""


def _body():
    lines = {"key": "lines", "label": "費用明細", "type": "table", "dataClass": "T1", "minRows": 0, "maxRows": 200, "addLabel": "新增一列",
             "columns": [{"key": "item", "label": "項目", "type": "text"}, {"key": "qty", "label": "數量", "type": "number"},
                         {"key": "unit_cost", "label": "單價", "type": "number"},
                         {"key": "amount", "label": "小計", "type": "formula", "formula": "round_half_up(qty * unit_cost)"}]}
    f = lambda k, label, **kw: dict({"key": k, "label": label, "type": "text", "dataClass": "T1"}, **kw)       # noqa: E731
    return {"name": "真滑鼠", "icon": "", "permission": "custom." + KEY, "numbering": {"prefix": "RM", "date": "YYYYMMDD", "digits": 4},
            "fields": [f("place", "地點", required=True), f("amount", "金額", type="number", min=0), f("memo", "備註"), f("reason", "事由"), lines],
            "workflow": {"initial": "draft", "states": [{"key": "draft", "label": "草稿", "final": True}], "transitions": []},
            "ui": {"form": {"groups": [{"title": "基本資料", "fields": ["place", "amount"]}, {"title": "其他", "fields": ["memo", "reason"]},
                                       {"title": "費用", "fields": ["lines"]}, {"title": "空區塊", "fields": []}]}, "list": {"columns": ["place"]}}}


@pytest.fixture()
def page(live_server, client, make_user, new_context):
    u = make_user(username="rm_sa", role="superadmin")
    tok = client.post("/api/auth/login", json={"username": u[0], "password": u[1]}).json()["token"]
    r = client.put("/api/definitions/custom_module/%s/draft" % KEY, json={"body": _body()}, headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 200, r.text
    pg = new_context(viewport={"width": 1500, "height": 1700}).new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(pg, live_server, u[0], u[1])
    pg.context.add_init_script(FRESH)                                                                   # 清掉 e2e 預設釘的舊畫面偏好 ⇒ 全新使用者
    pg.goto("%s/pages/module-builder.html?key=%s" % (live_server, KEY))               # 沒有 designer 參數：驗「預設開」
    pg.wait_for_selector("#mb-step-1", state="visible")
    go_step(pg, 2)
    pg.wait_for_selector(".fd .fd-paper", state="visible", timeout=20000)
    yield pg
    assert not errors, errors


def _drag(pg, src, dst_x, dst_y):
    b = src.bounding_box()
    pg.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
    pg.mouse.down()
    pg.mouse.move(dst_x, dst_y, steps=18)
    pg.mouse.up()


def _bottom_of(loc):
    b = loc.bounding_box()
    return b["x"] + 40, b["y"] + b["height"] - 3


def _top_of(loc):
    b = loc.bounding_box()
    return b["x"] + 40, b["y"] + 3


def test_designer_is_on_by_default(page):
    assert page.locator(".fd .fd-paper").is_visible()
    assert [len(s["fields"]) for s in page.evaluate(LAYOUT_JS)] == [2, 2, 1, 0]                             # 四個區塊（含空區塊）與各自的欄位數


def test_real_mouse_palette_tile_dropped_between_two_fields_is_inserted_there(page):
    before = page.evaluate(LAYOUT_JS)
    place = page.locator(".fd-fld", has=page.locator("label", has_text="地點")).first
    x, y = _bottom_of(place)
    _drag(page, page.locator('.fd-tile[data-add="textarea"]'), x, y)
    page.wait_for_function("(n) => document.querySelectorAll('.fd .fd-fld').length === n", arg=sum(len(s["fields"]) for s in before) + 1, timeout=10000)
    sec = page.evaluate(LAYOUT_JS)[0]["fields"]
    assert len(sec) == 3 and sec[0] == "地點" and sec[2] == "金額", sec                                   # 新欄位夾在地點與金額之間


def test_real_mouse_moving_a_field_to_another_section_moves_not_copies(page):
    before = page.evaluate(LAYOUT_JS)
    memo = page.locator(".fd-fld", has=page.locator("label", has_text="備註")).first
    place = page.locator(".fd-fld", has=page.locator("label", has_text="地點")).first
    x, y = _top_of(place)                                                                                  # 放在地點的上半 ⇒ 排在地點前面
    _drag(page, memo, x, y)
    page.wait_for_function("() => { const s = [...document.querySelectorAll('.fd .fd-sec')][0]; return s && s.querySelectorAll('.fd-fld').length === 3 }", timeout=10000)
    after = page.evaluate(LAYOUT_JS)
    assert after[0]["fields"][0] == "備註" and "備註" not in after[1]["fields"], after
    assert sum(len(s["fields"]) for s in after) == sum(len(s["fields"]) for s in before)                  # 總數不變＝搬移不是複製


def test_real_mouse_dropping_a_field_into_the_empty_section(page):
    reason = page.locator(".fd-fld", has=page.locator("label", has_text="事由")).first
    slot = page.locator(".fd-slot.fd-empty").first.bounding_box()
    _drag(page, reason, slot["x"] + slot["width"] / 2, slot["y"] + slot["height"] / 2)
    page.wait_for_function("() => { const s = [...document.querySelectorAll('.fd .fd-sec')][3]; return s && s.querySelectorAll('.fd-fld').length === 1 }", timeout=10000)
    after = page.evaluate(LAYOUT_JS)
    assert after[3]["fields"] == ["事由"] and after[1]["fields"] == ["備註"], after
