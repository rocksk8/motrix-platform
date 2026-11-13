# -*- coding: utf-8 -*-
"""瀏覽器端對端：寄信帳號卡（批次 3，static/email-setup.js）。

驗：①抽出後的卡片照樣出現在通知設定頁、能載入與儲存設定、與 LINE 卡、月報卡並存。
（精靈流程的 e2e 在本檔後段。）
"""
import pytest

pytest.importorskip("playwright.sync_api")


def _open(live_server, make_user, new_page, login_as, name):
    u = make_user(username=name, role="superadmin")
    page = new_page(viewport={"width": 1440, "height": 1600})
    login_as(page, u)
    page.goto(f"{live_server}/pages/notification-settings.html")
    return page


@pytest.mark.e2e
def test_extracted_email_card_renders_loads_and_saves(live_server, make_user, new_page, login_as):
    page = _open(live_server, make_user, new_page, login_as, "e2e_es1")
    page.locator("[data-testid=ns-base-url]").wait_for(state="visible", timeout=20000)
    assert page.locator("#chk-enabled").count() == 1
    assert page.locator("#line-panel").count() == 1                      # 與 LINE 卡並存
    page.locator("[data-testid=ns-base-url]").fill("https://erp.example.com")
    page.get_by_role("button", name="儲存設定").first.click()
    page.get_by_text("設定已儲存").first.wait_for(state="visible", timeout=10000)
    page.reload()
    page.locator("[data-testid=ns-base-url]").wait_for(state="visible", timeout=20000)
    page.wait_for_function("document.querySelector('[data-testid=ns-base-url]').value === 'https://erp.example.com'", timeout=10000)


# ── 精靈流程 ─────────────────────────────────────────────────────────────────────
import smtplib


def _give_email(username, email):
    from db import get_db
    c = get_db()
    c.execute("UPDATE users SET email=? WHERE username=?", (email, username))
    c.commit()
    c.close()


@pytest.fixture()
def fake_send(monkeypatch):
    from helpers import email_notify as EN
    box = {"calls": [], "raise": None}

    def fake(to, subject, html, ignore_enabled=False, cfg=None):
        box["calls"].append(to)
        if box["raise"]:
            raise box["raise"]
    monkeypatch.setattr(EN, "_send_raising", fake)
    return box


def _fill_step2(page, user="co@gmail.com", pw="abcd efgh ijkl mnop"):
    page.locator("[data-testid=es-next1]").click()
    page.locator("[data-testid=es-step2]").wait_for(state="visible", timeout=10000)
    page.locator("[data-testid=es-user]").fill(user)
    page.locator("[data-testid=es-password]").fill(pw)


@pytest.mark.e2e
def test_wizard_three_steps_then_activate(live_server, make_user, new_page, login_as, fake_send):
    page = _open(live_server, make_user, new_page, login_as, "e2e_es2")
    _give_email("e2e_es2", "boss@example.com")
    page.reload()
    page.locator("[data-testid=es-step1]").wait_for(state="visible", timeout=20000)         # 還沒設定 ⇒ 精靈預設展開
    for key in ("gmail", "microsoft365", "yahoo", "zoho", "other"):
        assert page.locator(f"[data-testid=es-provider-{key}]").count() == 1
    assert "第 1 步" in page.locator("[data-testid=es-step-label]").inner_text()
    assert not page.locator("[data-testid=es-other-fields]").is_visible()                    # 非「其他信箱」不露出主機與埠
    _fill_step2(page)
    assert page.locator("[data-testid=es-help-link]").get_attribute("href").startswith("https://myaccount.google.com")
    page.locator("[data-testid=es-next2]").click()
    page.locator("[data-testid=es-sent]").wait_for(state="visible", timeout=10000)
    assert page.locator("[data-testid=es-sent-to]").inner_text() == "boss@example.com"
    assert fake_send["calls"] == [["boss@example.com"]]
    page.locator("[data-testid=es-got-it]").click()
    page.locator("[data-testid=es-done]").wait_for(state="visible", timeout=10000)
    page.reload()
    page.locator("[data-testid=es-summary]").wait_for(state="visible", timeout=20000)         # 設定好了 ⇒ 只顯示摘要
    assert "co@gmail.com" in page.locator("[data-testid=es-summary]").inner_text()
    assert not page.locator("[data-testid=es-steps]").is_visible()
    page.locator("[data-testid=es-reopen]").click()
    page.locator("[data-testid=es-step1]").wait_for(state="visible", timeout=10000)


@pytest.mark.e2e
def test_other_provider_shows_host_and_port_only_then(live_server, make_user, new_page, login_as, fake_send):
    page = _open(live_server, make_user, new_page, login_as, "e2e_es3")
    page.locator("[data-testid=es-step1]").wait_for(state="visible", timeout=20000)
    page.locator("[data-testid=es-provider-other]").check()
    page.locator("[data-testid=es-next1]").click()
    page.locator("[data-testid=es-other-fields]").wait_for(state="visible", timeout=10000)
    assert "向信箱或網域代管廠商詢問" in page.locator("[data-testid=es-step2]").inner_text()


@pytest.mark.e2e
def test_m365_failure_gives_plain_message_and_a_ticket_without_error_codes(live_server, make_user, new_page, login_as, fake_send):
    fake_send["raise"] = smtplib.SMTPAuthenticationError(535, b"5.7.139 Authentication unsuccessful, SmtpClientAuthentication is disabled")
    page = _open(live_server, make_user, new_page, login_as, "e2e_es4")
    _give_email("e2e_es4", "boss@example.com")
    page.reload()
    page.locator("[data-testid=es-step1]").wait_for(state="visible", timeout=20000)
    page.locator("[data-testid=es-provider-microsoft365]").check()
    _fill_step2(page, user="boss@corp.com", pw="secret-pw")
    page.locator("[data-testid=es-next2]").click()
    page.locator("[data-testid=es-fail]").wait_for(state="visible", timeout=10000)
    assert "Microsoft 365" in page.locator("[data-testid=es-fail-title]").inner_text()
    page.locator("[data-testid=es-ticket-btn]").click()
    page.locator("[data-testid=es-ticket-text]").wait_for(state="visible", timeout=5000)
    txt = page.locator("[data-testid=es-ticket-text]").inner_text()
    assert "Set-CASMailbox" in txt and "boss@corp.com" in txt and "secret-pw" not in txt
    assert "mailto:" in page.locator("[data-testid=es-ticket-mail]").get_attribute("href")
    body = page.locator("body").inner_text()
    assert "5.7.139" not in body and "535" not in body                                       # 畫面不顯示錯誤碼
    assert not page.locator("[data-testid=es-got-it]").is_visible()                         # 失敗時不能啟用
    page.locator("[data-testid=es-back]").click()
    page.locator("[data-testid=es-step2]").wait_for(state="visible", timeout=5000)


@pytest.mark.e2e
def test_user_without_email_is_asked_for_one_in_step_2(live_server, make_user, new_page, login_as, fake_send):
    page = _open(live_server, make_user, new_page, login_as, "e2e_es5")
    page.locator("[data-testid=es-step1]").wait_for(state="visible", timeout=20000)
    _fill_step2(page)
    page.locator("[data-testid=es-next2]").click()
    page.locator("[data-testid=es-need-email]").wait_for(state="visible", timeout=10000)
    assert fake_send["calls"] == []
    page.locator("[data-testid=es-recipient]").fill("me@example.com")
    page.locator("[data-testid=es-next2]").click()
    page.locator("[data-testid=es-sent]").wait_for(state="visible", timeout=10000)
    assert page.locator("[data-testid=es-sent-to]").inner_text() == "me@example.com"
