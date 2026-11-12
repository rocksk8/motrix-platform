# -*- coding: utf-8 -*-
"""瀏覽器端對端：通知設定頁的「心跳監控狀態」卡片（2026-11-12）。

驗：壞狀態（本機服務被判 local_down 很久）⇒ 卡片顯示「異常」並指出協定可疑；改成正常後按「重新整理」⇒ 變「正常」；
沒有心跳的機器 ⇒「未設定」；頁面任何地方都不出現 ping 網址。狀態檔／設定檔換成暫存路徑，不碰真的。
"""
import json
from datetime import datetime, timedelta

import pytest

pytest.importorskip("playwright.sync_api")

SECRET = "https://hc-ping.example/UI-LEAK-ME"


@pytest.fixture()
def hb_dir(monkeypatch, tmp_path):
    from core import paths
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(paths, "LOGS_DIR", str(logs))
    monkeypatch.setattr(paths, "HEARTBEAT_CONFIG", str(tmp_path / "heartbeat_config.json"))

    def write(status, since_ago, seen_ago=timedelta(minutes=10)):
        n = datetime.now()
        (logs / "heartbeat_state.json").write_text(json.dumps({
            "status": status, "since": (n - since_ago).isoformat(timespec="seconds"),
            "seen_at": (n - seen_ago).isoformat(timespec="seconds"), "scheme": "https" if status != "local_down" else "",
            "local_ok_at": "", "ext_ok_at": (n - timedelta(hours=1)).isoformat(timespec="seconds")}), encoding="utf-8")
        (tmp_path / "heartbeat_config.json").write_text(json.dumps({"ping_url": SECRET}), encoding="utf-8")
    return write


def _open(live_server, make_user, new_page, login_as, name):
    u = make_user(username=name, role="superadmin")
    page = new_page(viewport={"width": 1440, "height": 1400})
    login_as(page, u)
    page.goto(f"{live_server}/pages/notification-settings.html")
    page.locator("#hb-panel").wait_for(state="visible", timeout=20000)
    return page


@pytest.mark.e2e
def test_heartbeat_card_shows_bad_then_ok_after_refresh_and_never_the_ping_url(live_server, make_user, new_page, login_as, hb_dir):
    hb_dir("local_down", timedelta(hours=5))
    page = _open(live_server, make_user, new_page, login_as, "e2e_hb1")
    page.locator("[data-testid=hb-level]").filter(has_text="異常").wait_for(state="visible", timeout=10000)
    assert "協定" in page.locator("[data-testid=hb-summary]").inner_text()
    hb_dir("ok", timedelta(hours=1))
    page.locator("#hb-panel").get_by_role("button", name="重新整理").click()
    page.locator("[data-testid=hb-level]").filter(has_text="正常").wait_for(state="visible", timeout=10000)
    assert "已設定" in page.locator("#hb-panel").inner_text()
    assert "UI-LEAK-ME" not in page.content()


@pytest.mark.e2e
def test_heartbeat_card_na_on_a_machine_without_heartbeat(live_server, make_user, new_page, login_as, hb_dir):
    page = _open(live_server, make_user, new_page, login_as, "e2e_hb2")
    page.locator("[data-testid=hb-level]").filter(has_text="未設定").wait_for(state="visible", timeout=10000)
