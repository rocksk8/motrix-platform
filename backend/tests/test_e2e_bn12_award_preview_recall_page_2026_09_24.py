# -*- coding: utf-8 -*-
"""`BN12` 的**頁面那一半**：詳細視窗裡看得到 PDF 版面預覽（未簽核有浮水印），申請人收得回來。

API 那一半在 `test_bn12_award_preview_and_recall_2026_09_24.py`（題名刻意不以 `test_bn12_` 開頭：
同號兩檔會被覆蓋率守門判撞名）。
⚙️ 觀測點：預覽看 **iframe 裡渲染出來的文字**；收回看**資料庫的 status**（成功後才會被寫入）。
"""
import json
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

import uvicorn
from tests._ports import free_safe_port


@pytest.fixture(autouse=True)
def _bonus_module_on(monkeypatch):
    import helpers.bonus as hb
    monkeypatch.delenv("BONUS_MODULE_ENABLED", raising=False)
    monkeypatch.setattr(hb, "BONUS_MODULE_ENABLED", True)
    assert hb.bonus_module_on(), "打開旗標之後模組還是關的 —— 前提失效，先修這裡。"


@pytest.fixture()
def live_server(client):
    import main
    config = uvicorn.Config(main.app, host="127.0.0.1",
                            port=free_safe_port(), log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    else:
        pytest.fail("uvicorn 測試伺服器在時限內沒有啟動")
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield "http://127.0.0.1:%d" % port
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def _seed(requester):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax,"
            " deal_tag, data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("MQ-BN12-E2E", "已送出", "預覽客戶", "預覽案", 0, 0, "已結案",
             json.dumps({"settlement": {"status": "finalized", "summary": {"netProfit": 50000}}}),
             "2026-09-01T00:00:00", "2026-09-01T00:00:00"))
        item = conn.execute(
            "INSERT INTO bonus_items (name, person_source, sort_order, is_active, created_by,"
            " created_at, updated_at) VALUES ('業務獎金','sales_person',0,1,'seed','2026-09-01','2026-09-01')"
        ).lastrowid
        aid = conn.execute(
            "INSERT INTO bonus_awards (quote_no, base_amount, status, created_by, created_at,"
            " updated_at, voided_at, approval_json) VALUES (?,?,?,?,?,?,'',?)",
            ("MQ-BN12-E2E", 100000, "待審核", requester, "2026-09-01", "2026-09-01",
             json.dumps({"tiers": [], "currentTier": 0, "requestedBy": requester}))).lastrowid
        conn.execute(
            "INSERT INTO bonus_award_lines (award_id, bonus_item_id, item_name_snapshot, username,"
            " person_source_snapshot, total_pct, person_pct, amount) VALUES (?,?,?,?,?,1000,10000,5000)",
            (aid, item, "業務獎金", requester, "sales_person"))
        conn.commit()
        return aid
    finally:
        conn.close()


@pytest.mark.e2e
def test_the_detail_window_previews_the_pdf_and_lets_the_requester_recall(live_server, make_user):
    u, p = make_user("bn12p_sa", role="superadmin", modules=["reports"])
    aid = _seed(u)
    errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto("%s/pages/login.html" % live_server)
        page.fill('input[x-model="username"]', u)
        page.fill('input[x-model="password"]', p)
        page.click('button:has-text("登入")')
        page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=15000)
        page.goto("%s/pages/bonus.html" % live_server)
        page.click('.bn-row:has-text("MQ-BN12-E2E")', timeout=15000)
        page.click('[data-testid="bonus-award-preview"]', timeout=15000)
        frame = page.frame_locator('[data-testid="bonus-award-preview-frame"]')
        frame.locator("body").wait_for(timeout=15000)
        preview_text = frame.locator("body").inner_text()
        page.click('[data-testid="bonus-award-recall"]', timeout=10000)
        page.wait_for_timeout(1500)
        browser.close()

    assert "尚未簽核完成" in preview_text, "預覽 iframe 裡沒有未簽核浮水印：%r" % preview_text[:300]
    assert "真實淨利" in preview_text, "預覽裡沒有精算明細表：%r" % preview_text[:300]
    import db
    conn = db.get_db()
    try:
        st = conn.execute("SELECT status FROM bonus_awards WHERE id=?", (aid,)).fetchone()["status"]
    finally:
        conn.close()
    assert st == "草稿", "按了「收回草稿」，而資料庫的狀態是 %r" % st
    assert not errors, "頁面有 JS 例外：%r" % errors
