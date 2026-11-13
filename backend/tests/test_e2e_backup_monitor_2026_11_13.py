# -*- coding: utf-8 -*-
"""瀏覽器端對端：系統 → 備份與監控（批次 4a，2026-11-13）。

驗畫面真的能用：載入出狀態、立即備份先跳確認（取消不送、確定才送且按鈕鎖定）、監控網址存了之後畫面只顯示主機名、
壞網址在欄位下方用白話報錯、整頁看不到網址本體與伺服器路徑。觀測點：DOM 文字、設定檔、被攔下的請求；外部打卡一律 fake。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect  # noqa: E402

_MAKE_USER_DEFAULT_ROLE = "superadmin"
SECRET = "https://hc-ping.example.com/E2E-SECRET-UUID"


@pytest.fixture()
def isolated(monkeypatch, tmp_path):
    from core import paths
    from helpers import backup_monitor as bm
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(paths, "LOGS_DIR", str(logs))
    monkeypatch.setattr(paths, "HEARTBEAT_CONFIG", str(tmp_path / "heartbeat_config.json"))
    monkeypatch.setitem(bm._hb_last, "at", 0.0)
    monkeypatch.setitem(bm._running, "on", False)
    calls = {"backup": 0, "ping": 0}
    import archive
    monkeypatch.setattr(archive, "_daily_backup", lambda *a, **k: calls.__setitem__("backup", calls["backup"] + 1))
    monkeypatch.setattr(archive, "_weekly_backup", lambda *a, **k: None)
    monkeypatch.setattr(bm, "_ping", lambda u: (calls.__setitem__("ping", calls["ping"] + 1), (True, "監控服務有收到這次回報。"))[1])
    # 解析網域與寄信都換成假的：測試不碰網路與 SMTP
    from core import safe_ping
    import helpers.email_notify as en
    monkeypatch.setattr(safe_ping, "resolve_host", lambda host, port: ["93.184.216.34"])
    calls["mails"] = []
    monkeypatch.setattr(en, "send_registered", lambda key, **kw: (calls["mails"].append(key), True)[1])
    bm._set_setting(bm._LAST_KEY, "")
    return tmp_path / "heartbeat_config.json", calls


def _open(live_server, make_user, new_page, login_as, name, width=1440):
    u = make_user(username=name, role="superadmin")
    page = new_page(viewport={"width": width, "height": 1400})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    login_as(page, u)
    page.goto(f"{live_server}/pages/backup-monitor.html")
    page.locator('[data-testid="bm-overall"]').wait_for(state="visible", timeout=20000)
    return page, errors


@pytest.mark.e2e
def test_page_loads_with_every_section_and_hides_secrets(live_server, make_user, new_page, login_as, isolated):
    cfg, _ = isolated
    cfg.write_text(json.dumps({"ping_url": SECRET}), encoding="utf-8")
    page, errors = _open(live_server, make_user, new_page, login_as, "bm_e2e1")
    for tid in ("bm-backups", "bm-cloud", "bm-disks", "bm-heartbeat", "bm-alerts", "bm-settings"):
        assert page.locator(f'[data-testid="{tid}"]').is_visible(), tid
    assert "hc-ping.example.com" in page.locator('[data-testid="bm-hb-host"]').inner_text()
    html = page.content()
    assert "E2E-SECRET-UUID" not in html and "SECRET" not in page.inner_text("body")
    assert page.locator('[data-testid="bm-link-retention"]').get_attribute("href").endswith("#retention")
    assert not errors, errors


@pytest.mark.e2e
def test_backup_now_asks_first_then_runs_once_and_disables(live_server, make_user, new_page, login_as, isolated):
    _, calls = isolated
    page, _ = _open(live_server, make_user, new_page, login_as, "bm_e2e2")
    page.locator('[data-testid="bm-backup-now"]').click()
    dlg = page.locator('[data-testid="bm-dialog"]')
    dlg.wait_for(state="visible", timeout=5000)
    page.locator('[data-testid="bm-dialog-cancel"]').click()
    dlg.wait_for(state="hidden", timeout=5000)
    assert calls["backup"] == 0                          # 取消＝什麼都沒發生
    page.locator('[data-testid="bm-backup-now"]').click()
    page.locator('[data-testid="bm-dialog-ok"]').click()
    page.locator('[data-testid="bm-backup-now-why"]').wait_for(state="visible", timeout=15000)
    assert page.locator('[data-testid="bm-backup-now"]').is_disabled()
    page.wait_for_function("() => true")
    import time
    end = time.time() + 10
    while calls["backup"] < 1 and time.time() < end:
        time.sleep(0.05)
    assert calls["backup"] == 1


@pytest.mark.e2e
def test_heartbeat_url_save_test_and_bad_url(live_server, make_user, new_page, login_as, isolated):
    cfg, calls = isolated
    page, _ = _open(live_server, make_user, new_page, login_as, "bm_e2e3")
    assert page.locator('[data-testid="bm-ping-save"]').is_disabled()       # 沒貼網址不能按
    assert page.locator('[data-testid="bm-ping-test"]').is_disabled()       # 沒存網址不能測
    # 壞網址：欄位下方白話報錯，設定檔不動
    page.fill('[data-testid="bm-ping-input"]', "http://192.168.1.5/x")
    page.locator('[data-testid="bm-ping-save"]').click()
    page.locator('[data-testid="bm-dialog-ok"]').click()
    err = page.locator('[data-testid="bm-ping-err"]')
    err.wait_for(state="visible", timeout=10000)
    assert "內網" in err.inner_text() and not cfg.exists()
    # 好網址：存下來、畫面只顯示主機名、輸入框清空
    page.fill('[data-testid="bm-ping-input"]', SECRET)
    page.locator('[data-testid="bm-ping-save"]').click()
    page.locator('[data-testid="bm-dialog-ok"]').click()
    page.locator('[data-testid="bm-hb-host"]').filter(has_text="hc-ping.example.com").wait_for(state="visible", timeout=10000)
    assert json.loads(cfg.read_text(encoding="utf-8"))["ping_url"] == SECRET
    assert page.input_value('[data-testid="bm-ping-input"]') == ""
    assert "E2E-SECRET-UUID" not in page.content()
    # 測試心跳：先確認，再顯示結果
    page.locator('[data-testid="bm-ping-test"]').click()
    page.locator('[data-testid="bm-dialog-ok"]').click()
    msg = page.locator('[data-testid="bm-ping-msg"]')
    msg.wait_for(state="visible", timeout=10000)
    assert "有收到" in msg.inner_text() and calls["ping"] == 1


@pytest.mark.e2e
def test_disable_asks_for_a_reason_then_waits_for_a_second_superadmin(live_server, make_user, new_page, login_as, isolated):
    cfg, calls = isolated
    cfg.write_text(json.dumps({"ping_url": SECRET}), encoding="utf-8")
    make_user(username="bm_e2e_other", role="superadmin")                # 第二位最高管理者＝停用需要核准
    page, _ = _open(live_server, make_user, new_page, login_as, "bm_e2e6")
    page.locator('[data-testid="bm-ping-clear"]').click()
    ok = page.locator('[data-testid="bm-dialog-ok"]')
    reason = page.locator('[data-testid="bm-dialog-reason"]')
    reason.wait_for(state="visible", timeout=5000)
    assert ok.is_disabled()                                              # 沒寫原因不能送
    reason.fill("改用別家監控")
    expect(ok).to_be_enabled()                                           # 按鈕解鎖由前端事件更新：用自動重試的斷言，不立刻讀 is_disabled
    ok.click()
    banner = page.locator('[data-testid="bm-disable-request"]')
    banner.wait_for(state="visible", timeout=10000)
    txt = banner.inner_text()
    assert "bm_e2e_other" in txt and "核准（已送出 不到 1 小時）" in txt and txt.startswith("等待 ") and "改用別家監控" in txt and "停用對外回報" in txt
    assert "若對方長期不在，可請對方登入核准，或撤回這次變更" in txt
    assert json.loads(cfg.read_text(encoding="utf-8"))["ping_url"] == SECRET        # 核准前沒有真的停用
    assert page.locator('[data-testid="bm-disable-approve"]').count() == 0 or not page.locator('[data-testid="bm-disable-approve"]').is_visible()   # 申請人看不到「核准」
    assert not page.locator('[data-testid="bm-ping-clear"]').is_visible()
    # 撤回
    page.locator('[data-testid="bm-disable-cancel"]').click()
    page.locator('[data-testid="bm-dialog-ok"]').click()
    banner.wait_for(state="hidden", timeout=10000)
    assert json.loads(cfg.read_text(encoding="utf-8"))["ping_url"] == SECRET
    assert page.locator('[data-testid="bm-ping-clear"]').is_visible()


@pytest.mark.e2e
def test_mobile_width_has_no_horizontal_scroll(live_server, make_user, new_page, login_as, isolated):
    page, _ = _open(live_server, make_user, new_page, login_as, "bm_e2e4", width=390)
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1")


@pytest.mark.e2e
def test_non_superadmin_sees_a_plain_refusal(live_server, make_user, new_page, login_as, isolated):
    u = make_user(username="bm_e2e5", role="sales")
    page = new_page(viewport={"width": 1440, "height": 900})
    login_as(page, u)
    page.goto(f"{live_server}/pages/backup-monitor.html")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)
    # 平台的頁面守門先擋：非最高管理者看到「沒有這個頁面的權限」，不是空白或錯誤堆疊；頁面本身的資料一個字都沒載
    assert "沒有這個頁面的權限" in page.inner_text("body")
    assert page.locator('[data-testid="bm-overall"]').count() == 0
