"""順序探針（不會被自動收集：檔名不是 test_*）。由 test_shared_playwright_event_loop_2026_09_25 以子 pytest、
固定順序、單一行程跑：① 一題用共用瀏覽器但**沒有標 e2e** ② 一題用 asyncio.run（合法寫法）。"""
import asyncio

import pytest

pytest.importorskip("playwright.sync_api")


def test_1_uses_the_shared_browser_without_e2e_mark(e2e_browser):
    page = e2e_browser.new_page()
    page.goto("data:text/html,<p>x</p>")


def test_2_asyncio_run_still_works():
    async def _f():
        return 1
    assert asyncio.run(_f()) == 1


def test_3_the_shared_browser_starts_again_after_being_stopped(e2e_browser):
    page = e2e_browser.new_page()
    page.goto("data:text/html,<p>y</p>")
    assert page.inner_text("p") == "y"
