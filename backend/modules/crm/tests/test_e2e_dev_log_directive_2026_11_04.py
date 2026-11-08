# -*- coding: utf-8 -*-
"""業務開發頁「開發記錄批示」（crm v4，真瀏覽器 R2：開頁、點每個新增的控制項、斷言 DOM＋DB、截圖）：
- 管理員：記錄卡有「批示」鈕；預選填寫的成員（要回覆）；內容空白不送；送出 ⇒ DB 多一筆批示與對象、卡片下方出現批示、標示「待回覆」；
- 被通知的成員：看得到批示、沒有「批示」鈕、可回覆；回覆後 DB 的 replied_at 有值、標示改「已回覆」；
- 同案件但不是作者／對象的成員：記錄卡看得到、**完全看不到批示**（沒有批示串、沒有批示鈕）；
- 已被批示的記錄，建立者按「刪除」⇒ 伺服器 409，畫面顯示失敗、DB 紀錄還在。
截圖先存 repo 內 logs/e2e-shots/（BK19 不准寫到 repo／tmp 之外）。"""
import os
from datetime import datetime

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))      # …/backend
SHOTS = os.path.join(BACKEND, "logs", "e2e-shots", "wip-hichan8-dev-log-directive")


def _shot(page, name):
    os.makedirs(SHOTS, exist_ok=True)
    with open(os.path.join(SHOTS, name), "wb") as f:
        f.write(page.screenshot())


def _rows(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _x(sql, args=()):
    import db
    c = db.get_db()
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


@pytest.mark.e2e
def test_directive_flow_admin_target_and_bystander(live_server, new_context, make_user):
    admin = make_user(username="de_admin", role="superadmin", modules=["dev_crm"])
    a = make_user(username="de_a", role="sales", modules=["dev_crm"])
    b = make_user(username="de_b", role="sales", modules=["dev_crm"])
    uid = {n: _rows("SELECT id FROM users WHERE username=?", (n,))[0]["id"] for n in ("de_admin", "de_a", "de_b")}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _x("INSERT INTO dev_cases (case_name, customer_name, status, sales_persons, created_by, created_at, updated_at) "
       "VALUES ('批示e2e案','客戶','洽談中',?,?,?,?)", (f"[{uid['de_a']},{uid['de_b']}]", uid["de_admin"], now, now))
    cid = _rows("SELECT id FROM dev_cases WHERE case_name='批示e2e案'")[0]["id"]
    _x("INSERT INTO dev_logs (case_id, log_date, log_by, channel, content, created_by, created_at) VALUES (?,?,?,?,?,?,?)",
       (cid, now[:10], uid["de_a"], "電話", "客戶嫌報價太高", uid["de_a"], now))
    lid = _rows("SELECT id FROM dev_logs WHERE case_id=?", (cid,))[0]["id"]

    errors = []

    # ── 管理員下批示 ──
    pa = new_context().new_page()
    pa.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(pa, live_server, admin[0], admin[1])
    pa.goto(live_server + "/pages/dev-crm.html")
    pa.locator(".dc-case-card", has_text="批示e2e案").first.click()
    card = pa.locator(".dc-log-card", has_text="客戶嫌報價太高").first
    card.wait_for(state="visible", timeout=15000)
    btn = card.locator('[data-testid="directive-btn"]')
    btn.wait_for(state="visible", timeout=10000)
    assert card.locator('[data-testid="directive-form"]').is_hidden()
    btn.click()
    form = card.locator('[data-testid="directive-form"]')
    form.wait_for(state="visible", timeout=5000)
    targets = form.locator('[data-testid="directive-target"]')
    assert targets.count() == 1 and "de_a" in targets.first.inner_text()                  # 預選填寫的成員
    assert targets.first.locator('input[type=checkbox]').is_checked()                      # 預設要回覆
    form.locator('[data-testid="directive-save"]').click()                                 # 內容空白 ⇒ 不送
    pa.wait_for_timeout(500)
    assert _rows("SELECT id FROM dev_log_directive") == []
    form.locator('[data-testid="directive-text"]').fill("報價不能再讓，下週三前回我客戶底價")
    form.locator('[data-testid="directive-target-select"]').select_option(str(uid["de_b"]))      # 再加一位
    assert targets.count() == 2
    targets.nth(1).locator('input[type=checkbox]').uncheck()                                # b 只知會
    _shot(pa, "admin-directive-form.png")
    form.locator('[data-testid="directive-save"]').click()
    item = card.locator('[data-testid="directive-item"]').first
    item.wait_for(state="visible", timeout=10000)
    assert "報價不能再讓" in item.inner_text() and "de_a（待回覆）" in item.inner_text() and "de_b（知會）" in item.inner_text()
    rows = _rows("SELECT * FROM dev_log_directive WHERE parent_id IS NULL")
    assert len(rows) == 1 and rows[0]["log_id"] == lid and rows[0]["author_id"] == uid["de_admin"]
    tg = {t["user_id"]: (t["must_reply"], t["replied_at"]) for t in _rows("SELECT * FROM dev_log_directive_target")}
    assert tg == {uid["de_a"]: (1, None), uid["de_b"]: (0, None)}
    assert form.is_hidden()
    _shot(pa, "admin-directive-sent.png")

    # ── 被通知的成員 a：看得到、沒有批示鈕、回覆 ──
    ps = new_context().new_page()
    ps.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(ps, live_server, a[0], a[1])
    ps.goto(live_server + "/pages/dev-crm.html")
    ps.locator(".dc-case-card", has_text="批示e2e案").first.click()
    ca = ps.locator(".dc-log-card", has_text="客戶嫌報價太高").first
    ia = ca.locator('[data-testid="directive-item"]').first
    ia.wait_for(state="visible", timeout=15000)
    assert "報價不能再讓" in ia.inner_text()
    assert ca.locator('[data-testid="directive-btn"]').is_hidden()                          # 沒有下批示的能力
    rbtn = ia.locator('[data-testid="reply-save"]')
    ia.locator('[data-testid="reply-text"]').fill("收到，週三前回覆底價")
    rbtn.click()
    ia.locator('[data-testid="directive-reply"]').first.wait_for(state="visible", timeout=10000)
    assert "收到，週三前回覆底價" in ia.inner_text() and "de_a（已回覆）" in ia.inner_text()
    done = _rows("SELECT replied_at FROM dev_log_directive_target WHERE user_id=?", (uid["de_a"],))[0]["replied_at"]
    assert done
    assert ia.locator('[data-testid="reply-text"]').input_value() == ""                     # 送出後清空
    _shot(ps, "target-replied.png")

    # ── 同案件、不是作者／對象的成員：記錄看得到，批示一點痕跡都沒有 ──
    # （b 其實是『知會』對象，所以先把 b 從對象移掉，換成旁觀者視角）
    _x("DELETE FROM dev_log_directive_target WHERE user_id=?", (uid["de_b"],))
    pb = new_context().new_page()
    pb.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(pb, live_server, b[0], b[1])
    pb.goto(live_server + "/pages/dev-crm.html")
    pb.locator(".dc-case-card", has_text="批示e2e案").first.click()
    cb = pb.locator(".dc-log-card", has_text="客戶嫌報價太高").first
    cb.wait_for(state="visible", timeout=15000)
    pb.wait_for_timeout(800)                                                                 # 給批示請求時間回來
    assert cb.locator('[data-testid="directive-item"]').count() == 0
    assert cb.locator('[data-testid="directive-btn"]').is_hidden()
    assert "報價不能再讓" not in pb.locator("body").inner_text()
    _shot(pb, "bystander-sees-nothing.png")

    # ── 記錄建立者 a 想刪已被批示的記錄 ⇒ 409，記錄還在 ──
    resp = ps.evaluate(
        "async (id) => { const s = JSON.parse(localStorage.getItem('motrix_session')); "
        "const r = await fetch('/api/dev-logs/' + id, {method:'DELETE', headers:{Authorization:'Bearer ' + s.token}}); "
        "return [r.status, await r.text()] }", lid)
    assert resp[0] == 409 and "批示" not in resp[1]
    assert _rows("SELECT id FROM dev_logs WHERE id=?", (lid,)) != []
    assert errors == [], errors
