# -*- coding: utf-8 -*-
"""新版設計器開著時，建構器的草稿自動存檔改成「閒置 4 秒」（設計 §12-7）：打字不是每停 0.7 秒就存一次（每次存檔寫一筆 definitions.save_draft 稽核）。
連續打字只存一次、存之前草稿還是舊的；舊畫面（設計器關閉）維持 0.7 秒。"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_e2e_form_designer_beginner_tasks_2026_10_02 import designer, _draft, _saved, _field, _label_of  # noqa: E402,F401


def _saves():
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='definitions.save_draft'").fetchone()[0]
    finally:
        conn.close()


@pytest.mark.e2e
def test_typing_in_the_designer_saves_once_after_four_idle_seconds(designer):
    page = designer
    _field(page, "地點").click()
    before = _saves()
    box = page.locator('.fd-right [data-fd="label"]')
    box.click()
    box.press("End")
    page.keyboard.type("（新）", delay=250)                         # 連續打字，每個字間隔 0.25 秒（遠短於 4 秒）
    page.wait_for_timeout(1500)                                    # 舊的 0.7 秒去抖在這時早已存過；新的 4 秒還沒到
    assert _label_of(_draft(), "place")["label"] == "地點", "閒置不到 4 秒，草稿不該已被改"
    assert _saves() == before
    _saved(page)                                                   # 之後存檔（等到存檔完成的終點）
    assert _label_of(_draft(), "place")["label"] == "地點（新）"
    assert _saves() == before + 1, "連續打字只存一次"


@pytest.mark.e2e
def test_old_canvas_keeps_the_short_debounce(designer):
    import time
    page = designer
    page.click("#mb-fd-toggle")                                    # 關掉新版 ⇒ 舊畫布
    page.wait_for_selector("#mb-canvas", state="visible")
    t0 = time.time()
    page.fill('#mb-step-2 [data-group-title]', "改名後的區塊")      # 舊畫布的區塊標題輸入
    page.locator('#mb-step-2 [data-group-title]').first.dispatch_event("change")
    _saved(page)
    assert time.time() - t0 < 3.5, "設計器關閉時仍是約 0.7 秒就存（不被 4 秒拖慢）"
