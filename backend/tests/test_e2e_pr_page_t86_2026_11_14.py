# -*- coding: utf-8 -*-
"""T86 #18～#23：請購單／採購單頁（payment-request.html）的導覽、前置提示、送審結果、必填提示（瀏覽器端對端）。

- #18 標題與說明依單據類型；選了案件就有「回到案件」與案件標籤（搜尋框收起，可「改選案件」）。
- #20 申請人沒有部門／部門沒有主管：進頁就有提示；部門欄預設帶入並鎖定（管理者只帶入不鎖定）。只提示與鎖定，簽核規則不變。
- #21 送審後：結果訊息在頁首，附「我的申請」「回到案件」「再開一張」。
- #22 帶入品項的選取表在明細上方；帶入後顯示已帶入幾筆。
- #23 送審時一次列出全部需要修正的項目、欄位標紅、捲到第一個。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._requires import requires_module  # noqa: E402

pytestmark = requires_module("case", "本檔的題打 M01（案件）的費用單據申請頁")

NO = "MQ-T86PR-001"


def _flag(on=True):
    import db
    from helpers import settings_groups, settings_registry as SR       # noqa: F401
    c = db.get_db()
    try:
        SR.publish("onepipe", {"links": 1 if on else 0}, reason="e2e", user="t86pr", conn=c)
        c.commit()
    finally:
        c.close()


def _case():
    import db
    c = db.get_db()
    try:
        c.execute("INSERT OR REPLACE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (NO, "已送出", "請購客戶", "請購工程", 1000, 952, json.dumps({"dealTag": "已成案"}), "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"))
        c.commit()
    finally:
        c.close()


def _org(username, dept_name, manager_username=None):
    """建處＋部門（可指定主管），並把 username 歸屬到該部門；dept_name 為 None ⇒ 不歸屬。回傳部門 id。"""
    import db
    c = db.get_db()
    try:
        uid = c.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
        if not dept_name:
            return None
        mid = c.execute("SELECT id FROM users WHERE username=?", (manager_username,)).fetchone()["id"] if manager_username else None
        c.execute("INSERT INTO divisions (name, sort_order, created_at) VALUES (?, 0, '2026-01-01T00:00:00')", ("處-" + dept_name,))
        div = c.execute("SELECT id FROM divisions WHERE name=?", ("處-" + dept_name,)).fetchone()["id"]
        c.execute("INSERT INTO departments (division_id, name, sort_order, manager_user_id, created_at) VALUES (?, ?, 0, ?, '2026-01-01T00:00:00')", (div, dept_name, mid))
        did = c.execute("SELECT id FROM departments WHERE name=?", (dept_name,)).fetchone()["id"]
        c.execute("UPDATE users SET department_id=? WHERE id=?", (did, uid))
        c.commit()
        return did
    finally:
        c.close()


def _open(live_server, make_user, new_page, login_as, name, role="sales", viewport=None, query="", modules=None):
    u = make_user(username=name, role=role, modules=modules)
    page = new_page(viewport=viewport or {"width": 1280, "height": 1800})
    return u, page, lambda: (login_as(page, u), page.goto(f"{live_server}/pages/payment-request.html{query}"))


@pytest.mark.e2e
def test_title_explainer_and_case_chip_with_back_link(live_server, make_user, new_page, login_as):
    _flag(True)
    _case()
    u, page, go = _open(live_server, make_user, new_page, login_as, "t86pr_a", role="superadmin", query=f"?case={NO}&type=purchase_req")
    go()
    page.wait_for_selector("#df-in-remark", timeout=20000)
    assert page.locator("[data-testid=pr-title]").inner_text() == "新增請購單"
    assert "請購單" in page.locator("[data-testid=pr-explainer]").inner_text() and "額外支出" in page.locator("[data-testid=pr-explainer]").inner_text()
    assert "支出申請就是" not in page.locator("[data-testid=pr-explainer]").inner_text(), "請購單不再顯示一般支出申請的說明"
    back = page.locator("[data-testid=pr-back-to-case]")
    assert back.is_visible() and back.get_attribute("href") == f"case-management.html?q={NO}"
    assert page.locator("[data-testid=pr-case-chip]").is_visible() and NO in page.locator("[data-testid=pr-case-chip]").inner_text()
    assert not page.locator("#pr-case-q").is_visible(), "案件已選好，搜尋框收起"
    page.locator("[data-testid=pr-case-change]").click()
    page.locator("#pr-case-q").wait_for(state="visible", timeout=5000)
    assert not page.locator("[data-testid=pr-case-chip]").is_visible() and not back.is_visible()
    page.select_option("#pr-type", "")
    page.wait_for_function("() => document.querySelector('[data-testid=pr-title]').innerText === '支出申請'", timeout=5000)


@pytest.mark.e2e
def test_prereq_hint_for_no_department_and_no_manager_and_ok(live_server, make_user, new_page, login_as):
    u, page, go = _open(live_server, make_user, new_page, login_as, "t86pr_nodept")
    go()
    page.wait_for_selector("#pr-type", timeout=20000)
    page.wait_for_timeout(800)
    assert not page.locator("[data-testid=pr-prereq]").is_visible(), "還沒選類型（一般支出申請沒有部門欄）：不顯示"
    page.select_option("#pr-type", "purchase_req")
    hint = page.locator("[data-testid=pr-prereq]")
    hint.wait_for(state="visible", timeout=20000)
    assert "尚未歸屬任何部門" in hint.inner_text() and "使用者管理" in hint.inner_text()
    page.select_option("#pr-type", "")
    hint.wait_for(state="hidden", timeout=5000)

    u2, page2, go2 = _open(live_server, make_user, new_page, login_as, "t86pr_nomgr")
    _org("t86pr_nomgr", "無主管部")
    go2()
    page2.wait_for_selector("#pr-type", timeout=20000)
    page2.select_option("#pr-type", "purchase_req")
    h2 = page2.locator("[data-testid=pr-prereq]")
    h2.wait_for(state="visible", timeout=20000)
    assert "「無主管部」尚未指定主管" in h2.inner_text() and "組織架構設定" in h2.inner_text()

    make_user(username="t86pr_boss", role="admin")
    u3, page3, go3 = _open(live_server, make_user, new_page, login_as, "t86pr_ok")
    _org("t86pr_ok", "有主管部", manager_username="t86pr_boss")
    go3()
    page3.wait_for_selector("#pr-type", timeout=20000)
    page3.select_option("#pr-type", "purchase_req")
    page3.wait_for_selector("#df-in-dept", timeout=15000)
    page3.wait_for_timeout(800)
    assert not page3.locator("[data-testid=pr-prereq]").is_visible(), "有部門、部門有主管：不顯示提示"

    # 管理者常沒有部門、也能改選別的部門：不提示
    u4, page4, go4 = _open(live_server, make_user, new_page, login_as, "t86pr_adm_nodept", role="superadmin")
    go4()
    page4.wait_for_selector("#pr-type", timeout=20000)
    page4.select_option("#pr-type", "purchase_req")
    page4.wait_for_selector("#df-in-dept", timeout=15000)
    page4.wait_for_timeout(800)
    assert not page4.locator("[data-testid=pr-prereq]").is_visible(), "管理者不顯示前置提示"


@pytest.mark.e2e
def test_department_is_prefilled_and_locked_for_staff_but_not_for_admin(live_server, make_user, new_page, login_as):
    make_user(username="t86pr_mgr", role="admin")
    u, page, go = _open(live_server, make_user, new_page, login_as, "t86pr_lock")
    did = _org("t86pr_lock", "鎖定部", manager_username="t86pr_mgr")
    go()
    page.wait_for_selector("#pr-type", timeout=20000)
    page.select_option("#pr-type", "purchase_req")
    page.wait_for_selector("#df-in-dept", timeout=15000)
    page.wait_for_function("() => document.querySelector('#df-in-dept').value !== ''", timeout=5000)
    assert page.input_value("#df-in-dept") == str(did)
    assert page.locator("#df-in-dept").is_disabled(), "一般申請人：部門鎖定為所屬部門"
    assert "依您所屬的部門帶入" in page.locator("[data-field=dept]").inner_text()
    # 管理者：只帶入預設值、可以改
    u2, page2, go2 = _open(live_server, make_user, new_page, login_as, "t86pr_lock_adm", role="admin")
    did2 = _org("t86pr_lock_adm", "管理部", manager_username="t86pr_mgr")
    go2()
    page2.wait_for_selector("#pr-type", timeout=20000)
    page2.select_option("#pr-type", "purchase_req")
    page2.wait_for_function("() => document.querySelector('#df-in-dept') && document.querySelector('#df-in-dept').value !== ''", timeout=15000)
    assert page2.input_value("#df-in-dept") == str(did2) and not page2.locator("#df-in-dept").is_disabled()


@pytest.mark.e2e
def test_validation_lists_every_problem_marks_fields_and_scrolls_to_first(live_server, make_user, new_page, login_as):
    make_user(username="t86pr_mgr2", role="admin")
    u, page, go = _open(live_server, make_user, new_page, login_as, "t86pr_val", viewport={"width": 390, "height": 800})
    _org("t86pr_val", "必填部", manager_username="t86pr_mgr2")
    go()
    page.wait_for_selector("#pr-type", timeout=20000)
    page.select_option("#pr-type", "purchase_req")
    page.wait_for_selector("#df-in-remark", timeout=15000)
    page.locator("#pr-t-submit").click()
    err = page.locator("#pr-t-error")
    err.wait_for(state="visible", timeout=10000)
    txt = err.inner_text()
    assert txt.startswith("尚有 ") and "項需要修正" in txt
    for need in ("採購備註說明必填", "需求日期必填", "第 1 列：品名／摘要必填"):
        assert need in txt, (need, txt)
    n = int(txt.split("尚有 ")[1].split(" 項")[0])
    assert n >= 4
    assert page.locator(".df-f.is-bad").count() >= 2 and page.locator("td.is-bad").count() >= 1, "欄位與明細的格子都要標紅"
    page.wait_for_timeout(900)
    top = page.evaluate("() => { const e = document.querySelector('.df-f.is-bad textarea, .df-f.is-bad input, .df-f.is-bad select, td.is-bad input'); const r = e.getBoundingClientRect(); return [r.top, r.bottom, innerHeight] }")
    assert 0 <= top[0] < top[2], "第一個有問題的欄位要在畫面內：%s" % top
    assert page.evaluate("() => document.documentElement.scrollWidth") <= 390


@pytest.mark.e2e
def test_submit_result_has_links(live_server, make_user, new_page, login_as):
    make_user(username="t86pr_mgr3", role="admin")
    u, page, go = _open(live_server, make_user, new_page, login_as, "t86pr_ok2", role="admin")
    _org("t86pr_ok2", "結果部", manager_username="t86pr_mgr3")
    go()
    page.wait_for_selector("#pr-type", timeout=20000)
    page.select_option("#pr-type", "purchase_req")
    page.wait_for_selector("#df-in-remark", timeout=15000)
    page.fill("#df-in-remark", "機房增設")
    rng = page.locator("[data-range=need_period] input")
    rng.nth(0).fill("2026-12-01")
    rng.nth(1).fill("2026-12-05")
    page.wait_for_selector("tr[data-row]", timeout=5000)           # 表單一開始就有一列空白明細
    row = page.locator('tr[data-row="0"]')
    row.locator('td[data-col="summary"] input').fill("交換器")
    row.locator('td[data-col="qty"] input').fill("2")
    row.locator('td[data-col="unitCost"] input').fill("1000")
    page.locator("#pr-t-submit").click()
    res = page.locator("#pr-result")
    page.wait_for_function("() => document.getElementById('pr-result').offsetParent !== null || document.getElementById('pr-t-error').offsetParent !== null", timeout=15000)
    assert page.locator("#pr-t-error").is_hidden(), page.locator("#pr-t-error").inner_text()
    res.wait_for(state="visible", timeout=15000)
    assert res.get_attribute("data-status") == "待審核"
    text = page.locator("[data-testid=pr-result-text]").inner_text()
    assert text.startswith("已送審（待審核）：PR-") and text.endswith("。")
    assert page.locator("[data-testid=pr-result-mine]").is_visible() and page.locator("[data-testid=pr-result-again]").is_visible()
    assert not page.locator("[data-testid=pr-result-case]").is_visible(), "沒綁案件：沒有「回到案件」"
    page.wait_for_timeout(500)
    assert page.evaluate("() => document.getElementById('pr-result').getBoundingClientRect().top") >= 0, "結果訊息要在畫面內"
    page.locator("[data-testid=pr-result-mine]").click()
    page.locator("#pr-mine").wait_for(state="visible", timeout=10000)
    page.locator("#pr-mine").get_by_text(text.split("：")[1].rstrip("。")).first.wait_for(state="visible", timeout=10000)
    page.locator("#pr-tab-new").click()
    page.locator("#pr-new").wait_for(state="visible", timeout=5000)
    assert res.is_hidden(), "看過「我的申請」再回來：舊的送審結果不再掛著"
