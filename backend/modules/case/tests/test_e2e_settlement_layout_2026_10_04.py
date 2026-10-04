"""精算頁版面（hotfix，正式機回饋 2026-10-04）：內容置中（左右邊界對稱）、頁首摘要卡在各寬度都不被裁切。
寬度 1280／1440／1920／420；用很大的金額把「金額／比例」撐到最長；截圖存 logs/e2e-shots/wip-t37b-settle-layout-fe。"""
import json
import os

import pytest

pytest.importorskip("playwright.sync_api")

from tests._requires import requires_module  # noqa: E402
from tests.test_e2e_case_concurrent_edit_2026_09_24 import _login  # noqa: F401

from modules.case.tests.test_e2e_settlement_actuals_2026_10_03 import NO, _seed  # noqa: E402

pytestmark = requires_module("case", "本檔的題讀寫 M01（案件）的資料與頁面")

SHOTS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "logs", "e2e-shots", "wip-t37b-settle-layout-fe")
S = "Alpine.$data(document.body)"


def _shot(page, name):
    os.makedirs(SHOTS, exist_ok=True)
    page.screenshot(path=os.path.join(SHOTS, "%s.png" % name), full_page=False)


@pytest.mark.e2e
def test_settlement_page_is_centered_and_kpi_cards_are_never_clipped(live_server, make_user, e2e_browser):
    import db
    sa = make_user(username="sa_sa", role="superadmin")
    _seed()
    c = db.get_db()
    try:
        d = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        d["tot"] = {"pretax": 8837550, "total": 9279428, "totalCost": 4000000}        # 大金額：「NT$ 8,825,300 ／ 99.9%」這種最長字串
        c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), NO))
        c.commit()
    finally:
        c.close()
    ctx = e2e_browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    _login(page, live_server, *sa)
    page.goto(f"{live_server}/pages/settlement.html?no={NO}")
    page.locator('[data-testid="stl-strip"]').wait_for(state="visible", timeout=20000)
    page.wait_for_function(f"() => {S}._actualsOk && {S}.summary.totalActualCost > 0", timeout=20000)

    clipped = """() => {
        const out = [];
        document.querySelectorAll('[data-testid="stl-strip"] .stl-k').forEach(card => {
            const cr = card.getBoundingClientRect();
            [card, ...card.querySelectorAll('*')].forEach(el => {
                if (el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).display !== 'inline') out.push(card.dataset.testid + ' ' + el.className + ' ' + el.scrollWidth + '>' + el.clientWidth);
                const r = el.getBoundingClientRect();
                if (r.width && r.right > cr.right + 1) out.push(card.dataset.testid + ' 超出卡片右緣 ' + el.className);
            });
        });
        return out;
    }"""
    margins = """() => {
        const m = document.querySelector('.stl-main').getBoundingClientRect(), vw = document.documentElement.clientWidth;
        return { left: m.left, right: vw - m.right, width: m.width, vw };
    }"""
    for w in (1280, 1440, 1920, 420):
        page.set_viewport_size({"width": w, "height": 900})
        page.wait_for_timeout(350)
        page.evaluate("() => window.scrollTo(0, 0)")
        assert page.evaluate(clipped) == [], (w, page.evaluate(clipped))                    # (a) 摘要卡內沒有任何東西被裁切／超出卡片
        # 毛利、淨利兩張卡：金額與比例都看得到（比例可以換到下一行，但一定在卡片裡）
        for k in ("gp", "net"):
            card = page.locator(f'[data-testid="stl-k-{k}"]')
            assert "%" in card.inner_text(), (w, k, card.inner_text())
            cb, vb = card.bounding_box(), card.locator(".stl-k__v2").bounding_box()
            assert vb["x"] + vb["width"] <= cb["x"] + cb["width"] + 1, (w, k, cb, vb)
        m = page.evaluate(margins)
        if w >= 1440:
            assert abs(m["left"] - m["right"]) <= 2, (w, m)                               # (b) 左右留白對稱
            assert m["width"] <= 1400 + 1, (w, m)
        # 5 張卡自動重排：寬螢幕一列放得下、窄螢幕換行（不被擠成裁切）
        cols = page.evaluate("() => new Set([...document.querySelectorAll('[data-testid=\"stl-strip\"] .stl-k')].map(e => Math.round(e.getBoundingClientRect().top))).size")
        if w >= 1440:
            assert cols == 1, (w, cols)
        if w == 420:
            assert cols >= 3, (w, cols)
        _shot(page, "settlement-%d" % w)

    # 列印版面不變：strip 不 sticky、工具列隱藏
    page.set_viewport_size({"width": 1440, "height": 900})
    page.emulate_media(media="print")
    assert page.locator('[data-testid="stl-strip"]').evaluate("e => getComputedStyle(e).position") == "static"
    assert page.locator(".stl-toolbar").evaluate("e => getComputedStyle(e).display") == "none"
    page.emulate_media(media="screen")
