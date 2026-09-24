"""案件管理顏色語意＋不只靠顏色（2026-09-24 使用者表單）。

- 紅色只給逾期：「目前階段」的階段條與卡片進度不用紅（accent #C8102E／danger）
- 逾期要有文字：卡片寫出「逾期 N」（清單與看板），不是只把數字變紅
- 看板卡片也標「有新動態」（原本只有清單有）
- 階段條可鍵盤操作：每一段可 Tab 到、Enter／空白鍵展開，並有可讀的標籤
觀測點：計算後的顏色、畫面文字、展開狀態。
"""
import json
import threading
import time
from datetime import datetime

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"
NO = "MQ-CLR-001"
LATE = "MQ-CLR-LATE"
REDS = {"rgb(200, 16, 46)", "rgb(185, 28, 28)", "rgb(233, 85, 85)", "rgb(200, 73, 73)"}


def _case(no, stages):
    """stages：[(label, done, due_date)]"""
    import db
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        st = []
        for i, (label, done, due) in enumerate(stages):
            cur = conn.execute("INSERT INTO case_stages (quote_no, label, sort_order, done, due_date, created_at, updated_at)"
                               " VALUES (?,?,?,?,?,?,?)", (no, label, i, 1 if done else 0, due, now, now))
            st.append({"id": cur.lastrowid, "label": label, "done": done, "dueDate": due})
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (no, "已送出", "客戶", "專案", 1000, 952,
             json.dumps({"dealTag": "已成案", "caseRecord": {"payment": {"items": []}, "stages": st}},
                        ensure_ascii=False), now, now, "已成案", "2026-08-01"))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def live_server(client):
    import uvicorn
    import main
    from tests._ports import free_safe_port
    config = uvicorn.Config(main.app, host="127.0.0.1", port=free_safe_port(), log_level="warning")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    else:
        pytest.fail("uvicorn 測試伺服器在時限內沒有啟動")
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        t.join(timeout=5)


def _open(browser, base, user, query=""):
    page = browser.new_context().new_page()
    page.on("dialog", lambda d: d.accept())
    page.goto(f"{base}/pages/login.html")
    page.fill('input[x-model="username"]', user[0])
    page.fill('input[x-model="password"]', user[1])
    page.click('button:has-text("登入")')
    page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=15000)
    page.goto(f"{base}/pages/case-management.html{query}")
    page.wait_for_function(f"() => {DATA_JS} && {DATA_JS}.session && {DATA_JS}.session.token && !{DATA_JS}.loading",
                           timeout=20000)
    return page


@pytest.mark.e2e
def test_current_stage_is_not_red_and_segments_work_by_keyboard(live_server, make_user):
    u = make_user(username="clr_e1", role="admin")
    _case(NO, [("完成", True, ""), ("進行中", False, "2099-12-31"), ("之後", False, "2099-12-31")])
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = _open(browser, live_server, u, f"?q={NO}&tab=exec")
            page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}'",
                                   timeout=15000)
            cur = page.locator(".stage-segbar__seg--current")
            cur.wait_for(state="visible", timeout=10000)
            bg = cur.evaluate("e => getComputedStyle(e).backgroundColor")
            assert bg not in REDS, f"目前階段不可以用紅色：{bg}"
            card_prog = page.locator(f".cm-card[data-quote-no='{NO}'] .cm-card__stageprog")
            assert card_prog.evaluate("e => getComputedStyle(e).color") not in REDS
            # 鍵盤：Tab 到得了、有標籤、Enter 展開
            assert cur.get_attribute("tabindex") == "0"
            assert "進行中" in (cur.get_attribute("aria-label") or "")
            sid = page.evaluate(f"() => {DATA_JS}.cr.caseRecord.stages[1].id")
            cur.focus()
            page.keyboard.press("Enter")
            page.wait_for_function(f"() => {DATA_JS}._openStageDetail[{sid}] === true", timeout=5000)
        finally:
            browser.close()


@pytest.mark.e2e
def test_overdue_is_written_out_and_board_shows_new_activity(live_server, client, make_user):
    u = make_user(username="clr_e2", role="admin")
    _case(LATE, [("逾期一", False, "2020-01-01"), ("逾期二", False, "2020-02-01"), ("未到", False, "2099-12-31")])
    r = client.post("/api/auth/login", json={"username": u[0], "password": u[1]})
    h = {"Authorization": "Bearer " + r.json()["token"]}
    client.post("/api/reads/unread", headers=h, json={"kind": "case", "keys": []})
    time.sleep(1.1)
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO case_updates (quote_no, author, content, created_at) VALUES (?,?,?,?)",
                     (LATE, "別人", "新動態", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
    finally:
        conn.close()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = _open(browser, live_server, u)
            prog = page.locator(f".cm-card[data-quote-no='{LATE}'] .cm-card__stageprog")
            prog.wait_for(state="visible", timeout=10000)
            assert "逾期 2" in prog.inner_text(), prog.inner_text()
            page.evaluate(f"() => {{ {DATA_JS}.caseViewMode = 'board'; {DATA_JS}.loadCases() }}")
            board_card = page.locator(f".cm-board-group .cm-card[data-board-quote-no='{LATE}']")
            board_card.wait_for(state="visible", timeout=10000)
            page.wait_for_function(f"() => {DATA_JS}.caseActivity['{LATE}']", timeout=10000)
            assert "有新動態" in board_card.inner_text(), board_card.inner_text()
            assert "逾期 2" in board_card.inner_text(), board_card.inner_text()
        finally:
            browser.close()
