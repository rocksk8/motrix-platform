# -*- coding: utf-8 -*-
"""表單設計器的深色主題守門。

深色主題＝整頁 invert 濾鏡（style.css）：頁面用「淺色版」token，濾鏡才把它反轉成深色；設計器若吃到 style.css 的深色 token 就會被反轉回淺灰
（2026-10-02 截圖：窗格淺灰、頁面深色）。這題用**真的像素**驗：深色主題下三個窗格、白紙表單的底色都要是深的；淺色主題下都要是亮的；
`<dialog>`（最上層，濾鏡不作用）在深色下也要是深的。另驗「濾鏡確實存在於設計器的祖先」——前提沒了，這題的意義就變了，要紅燈提醒。
反向控制：把 .fd 的固定 token 拿掉（讓它吃 style.css 深色 token）⇒ 像素檢查要抓到窗格變亮。
"""
import io

import pytest

pytest.importorskip("playwright.sync_api")
PIL = pytest.importorskip("PIL.Image")

from tests.test_e2e_form_designer_beginner_tasks_2026_10_02 import designer, _field  # noqa: E402,F401


def _lum(page, selector, dx=4, dy=4):
    """該元素左上角內側一小塊的平均亮度（0～1；避開文字）。"""
    box = page.locator(selector).first.bounding_box()
    png = page.screenshot(clip={"x": box["x"] + dx, "y": box["y"] + dy, "width": 6, "height": 6})
    im = PIL.open(io.BytesIO(png)).convert("L")
    px = list(im.getdata())
    return sum(px) / len(px) / 255.0


def _theme(page, name):
    page.evaluate("(n) => document.documentElement.setAttribute('data-theme', n)", name)
    page.wait_for_timeout(250)


@pytest.mark.e2e
def test_panes_and_paper_are_dark_in_dark_theme_and_light_in_light_theme(designer):
    page = designer
    _theme(page, "light")
    light = {s: _lum(page, s) for s in (".fd-left", ".fd-right", ".fd-center", ".fd-paper")}
    assert all(v > 0.80 for v in light.values()), light
    _theme(page, "dark")
    assert page.evaluate("""() => { for (let n = document.querySelector('.fd'); n; n = n.parentElement) {
        if (/invert/.test(getComputedStyle(n).filter)) return true } return false }"""), "設計器的祖先沒有 invert 濾鏡：前提變了，這題與 CSS 的固定淺色 token 都要重新檢討"
    dark = {s: _lum(page, s) for s in (".fd-left", ".fd-right", ".fd-center", ".fd-paper")}
    assert all(v < 0.30 for v in dark.values()), dark


@pytest.mark.e2e
def test_dialog_is_dark_in_dark_theme(designer):
    page = designer
    _theme(page, "dark")
    page.click('.fd-bar [data-fd-act="check"]')
    page.wait_for_selector("dialog[data-fd-checklist][open]")
    assert _lum(page, "dialog[data-fd-checklist]", 6, 6) < 0.30, "最上層的確認／檢查表視窗在深色主題下應是深底"
    page.click("dialog[data-fd-checklist] [data-r]")
    _theme(page, "light")
    page.click('.fd-bar [data-fd-act="check"]')
    page.wait_for_selector("dialog[data-fd-checklist][open]")
    assert _lum(page, "dialog[data-fd-checklist]", 6, 6) > 0.80
    page.click("dialog[data-fd-checklist] [data-r]")


@pytest.mark.e2e
def test_reverse_control_without_the_pinned_tokens_the_panes_turn_light_in_dark(designer):
    page = designer
    _theme(page, "dark")
    page.add_style_tag(content=".fd { --surface: #1C1C1E !important; --surface-muted: #232326 !important; --surface-sunken: #2A2A2D !important; }")
    page.wait_for_timeout(250)
    assert _lum(page, ".fd-left") > 0.60, "吃到 style.css 的深色 token ⇒ 被濾鏡反轉成淺灰：這個檢查要抓得到"
