# -*- coding: utf-8 -*-
"""業務開發頁「指派／進度回報」重設計（crm v3，真瀏覽器 R2：開頁、點每個新增／變更的控制項、斷言 DOM＋DB、截圖）：
- 管理員看到逾期標示（清單卡片＋詳情），進度區沒有輸入框（唯讀），提示只有被指派人能新增；
- 被指派人看得到輸入框，空白時按鈕不能按；新增 ⇒ DB 多一列、目前進度顯示（作者·時間）、逾期標示消失、輸入框清空；再新增一筆 ⇒ 歷史新到舊；
- 管理員換人 ⇒ DB 換成新對象、畫面「新負責人尚未回報」、歷史仍在且前任的標「（原負責人）」；
- 有改動的期限早於今天 ⇒ 伺服器 400，訊息顯示在畫面、DB 不變。
截圖先存 repo 內 logs/e2e-shots/（BK19 不准寫到 repo／tmp 之外）。"""
import os
from datetime import date, datetime, timedelta

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))      # …/backend
SHOTS = os.path.join(BACKEND, "logs", "e2e-shots", "wip-hichan3-dev-case-progress")


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
def test_progress_history_readonly_admin_overdue_and_reassign(live_server, new_context, make_user):
    admin = make_user(username="pe_admin", role="superadmin", modules=["dev_crm"])
    asg = make_user(username="pe_asg", role="sales", modules=["dev_crm"])
    other = make_user(username="pe_other", role="sales", modules=["dev_crm"])
    uid = {n: _rows("SELECT id FROM users WHERE username=?", (n,))[0]["id"] for n in ("pe_admin", "pe_asg", "pe_other")}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    past = (date.today() - timedelta(days=3)).isoformat()
    _x("INSERT INTO dev_cases (case_name, customer_name, status, created_by, created_at, updated_at, assigned_to, assigned_by, assigned_at, reply_deadline) "
       "VALUES ('進度e2e案','客戶','洽談中',?,?,?,?,?,?,?)", (uid["pe_admin"], now, now, uid["pe_asg"], uid["pe_admin"], "2026-11-01 09:00:00", past))
    cid = _rows("SELECT id FROM dev_cases WHERE case_name='進度e2e案'")[0]["id"]

    # ── 管理員：看得到逾期標示、進度區唯讀 ──
    errors = []
    pa = new_context().new_page()
    pa.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(pa, live_server, admin[0], admin[1])
    pa.goto(live_server + "/pages/dev-crm.html")
    card = pa.locator(".dc-case-card", has_text="進度e2e案").first
    card.wait_for(state="visible", timeout=15000)
    assert "逾期 3 天未回報" in card.locator('[data-testid="card-overdue"]').inner_text()
    card.click()
    pa.locator('[data-testid="progress-box"]').wait_for(state="visible", timeout=10000)
    assert "逾期 3 天未回報" in pa.locator('[data-testid="overdue-badge"]').inner_text()
    assert pa.locator('[data-testid="progress-text"]').count() == 0 and pa.locator('[data-testid="progress-save"]').count() == 0     # 管理員沒有輸入框
    assert "只有被指派人能新增進度回報" in pa.locator('[data-testid="progress-readonly-hint"]').inner_text()
    assert "尚無進度回報" in pa.locator('[data-testid="progress-empty"]').inner_text()
    assert pa.locator('[data-testid="assign-deadline"]').get_attribute("min") == date.today().isoformat()
    _shot(pa, "admin-readonly-overdue.png")

    # ── 被指派人：新增兩筆 ──
    ps = new_context().new_page()
    ps.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(ps, live_server, asg[0], asg[1])
    ps.goto(live_server + "/pages/dev-crm.html")
    ps.locator(".dc-case-card", has_text="進度e2e案").first.click()
    ta, btn = ps.locator('[data-testid="progress-text"]'), ps.locator('[data-testid="progress-save"]')
    ta.wait_for(state="visible", timeout=10000)
    assert ta.get_attribute("maxlength") == "4000" and btn.is_disabled()                           # 空白不能送
    ta.fill("   ")
    assert btn.is_disabled()
    ta.fill("第一次：已約客戶週三拜訪")
    assert not btn.is_disabled()
    btn.click()
    ps.wait_for_function("() => document.querySelector('[data-testid=progress-current-text]') && document.querySelector('[data-testid=progress-current-text]').innerText.includes('第一次')", timeout=10000)
    assert ta.input_value() == "" and btn.is_disabled()                                              # 送出後清空
    prog = _rows("SELECT * FROM dev_case_progress WHERE case_id=?", (cid,))
    assert [(p["author_id"], p["content"]) for p in prog] == [(uid["pe_asg"], "第一次：已約客戶週三拜訪")]
    meta = ps.locator('[data-testid="progress-current"] .dc-progress-meta').inner_text()
    assert " · " in meta and prog[0]["created_at"][:16] in meta                                     # 作者 · 時間
    assert not ps.locator('[data-testid="overdue-badge"]').is_visible()                              # 一回報逾期標示消失
    assert not ps.locator('[data-testid="card-overdue"]').first.is_visible()
    ta.fill("第二次：客戶要求報價")
    btn.click()
    ps.wait_for_function("() => document.querySelector('[data-testid=progress-current-text]').innerText.includes('第二次')", timeout=10000)
    ps.locator('[data-testid="progress-history-toggle"]').click()
    items = ps.locator('[data-testid="progress-item"]')
    items.first.wait_for(state="visible", timeout=10000)
    texts = [items.nth(i).inner_text() for i in range(items.count())]
    assert len(texts) == 2 and "第二次" in texts[0] and "第一次" in texts[1]                          # 新到舊
    assert "（原負責人）" not in "".join(texts)                                                       # 都是現任寫的
    _shot(ps, "assignee-two-entries-history.png")

    # ── 管理員換人：舊進度留著、新負責人尚未回報 ──
    pa.reload()
    pa.locator(".dc-case-card", has_text="進度e2e案").first.click()
    sel = pa.locator('[data-testid="assign-user"]')
    sel.wait_for(state="visible", timeout=10000)
    sel.select_option(str(uid["pe_other"]))
    pa.locator('[data-testid="assign-deadline"]').fill((date.today() + timedelta(days=10)).isoformat())
    pa.locator('[data-testid="assign-save"]').click()
    pa.wait_for_function("() => document.querySelector('[data-testid=progress-empty]') && document.querySelector('[data-testid=progress-empty]').innerText.includes('新負責人尚未回報')", timeout=10000)
    case = _rows("SELECT assigned_to, assigned_by, assigned_at, reply_deadline FROM dev_cases WHERE id=?", (cid,))[0]
    assert case["assigned_to"] == uid["pe_other"] and case["assigned_by"] == uid["pe_admin"] and case["assigned_at"] > "2026-11-01 09:00:00"
    assert len(_rows("SELECT id FROM dev_case_progress WHERE case_id=?", (cid,))) == 2                # 前任的兩筆都還在
    pa.locator('[data-testid="progress-history-toggle"]').click()
    pa.locator('[data-testid="progress-item"]').first.wait_for(state="visible", timeout=10000)
    hist = pa.locator('[data-testid="progress-history"]').inner_text()
    assert "（原負責人）" in hist and "第二次" in hist and "第一次" in hist
    assert pa.locator('[data-testid="overdue-badge"]').is_hidden()                                    # 新期限在未來
    _shot(pa, "admin-after-reassign.png")

    # ── 有改動的期限早於今天：伺服器擋下，訊息顯示、DB 不變 ──
    pa.locator('[data-testid="assign-deadline"]').fill("2020-01-01")
    pa.locator('[data-testid="assign-save"]').click()
    pa.get_by_text("回覆期限不可早於今天").first.wait_for(state="visible", timeout=10000)
    assert _rows("SELECT reply_deadline FROM dev_cases WHERE id=?", (cid,))[0]["reply_deadline"] == (date.today() + timedelta(days=10)).isoformat()
    _shot(pa, "admin-past-deadline-rejected.png")

    # ── 前任（pe_asg）失去存取：重新整理後清單裡沒有這個案件；新被指派人（pe_other）看得到輸入框 ──
    ps.reload()
    ps.wait_for_function("() => !document.body.innerText.includes('載入中')", timeout=10000)
    ps.wait_for_timeout(500)
    assert ps.locator(".dc-case-card", has_text="進度e2e案").count() == 0
    po = new_context().new_page()
    po.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(po, live_server, other[0], other[1])
    po.goto(live_server + "/pages/dev-crm.html")
    po.locator(".dc-case-card", has_text="進度e2e案").first.click()
    po.locator('[data-testid="progress-text"]').wait_for(state="visible", timeout=10000)
    assert "新負責人尚未回報" in po.locator('[data-testid="progress-empty"]').inner_text()
    _shot(po, "new-assignee-sees-input.png")
    assert errors == [], errors
