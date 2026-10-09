# -*- coding: utf-8 -*-
"""第 48 班 e2e：勞報單人員 ⇄ 派工連動（payslip-form 建立流程勾選派發；案件管理派發分頁以最高管理者與一般派發檢視者看）。

- payslip-form：從外包名冊選人 ⇒ 列出他的派發（只列人員名單含他的）；勾選後存檔 ⇒ 伺服器同一交易連結；沒選名冊人員 ⇒ 提示不會連到派工。
- 派發分頁「同一人員的勞報單」：已確認對應的列出（最高管理者可點進勞報單、一般人員只有文字）；名稱推測未確認的不列；任何人都看不到金額。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

NO = "MQ-PP48E-001"
ROOT = "Alpine.$data(document.querySelector('[x-data]'))"
T0 = "2026-03-01T09:00:00"


def _seed():
    import db
    conn = db.get_db()
    try:
        pid = conn.execute("INSERT INTO contractors (name, id_number, active, created_at, updated_at) VALUES (?,?,1,?,?)", ("名冊甲", "A123456789", T0, T0)).lastrowid
        other = conn.execute("INSERT INTO contractors (name, id_number, active, created_at, updated_at) VALUES (?,?,1,?,?)", ("名冊乙", "B123456789", T0, T0)).lastrowid
        vid = conn.execute("INSERT INTO vendor_contractors (name, address, active, created_at) VALUES (?,?,?,?)", ("e2e承攬", "台中市", 1, T0)).lastrowid
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
                     " deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (NO, "已送出", "客戶", "專案", 105000, 100000, json.dumps({"dealTag": "已成案"}), T0, T0, "已成案", "2026-03-01"))

        def disp(personnel):
            return conn.execute("INSERT INTO contractor_dispatches (quote_no, vendor_id, dispatch_date, scope, items_json, personnel_json, total_amount,"
                                " tax_rate, status, notes, created_by, created_at, updated_at, files_json, invoice_files_json)"
                                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                (NO, vid, "2026-03-08", "管線施工", "[]", json.dumps(personnel), 8000, 5, "進行中", "", "x", T0, T0, "[]", "[]")).lastrowid
        d_with = disp([{"id": pid, "name": "名冊甲", "amount": 7777, "note": ""}])
        d_without = disp([{"id": other, "name": "名冊乙", "amount": 1, "note": ""}])

        def slip(no, name, cid, guess):
            conn.execute("INSERT INTO payslips (slip_no, contractor_id, contractor_name, income_type, gross_amount, tax_withheld, nhi_supplement, net_amount,"
                         " payment_method, slip_date, status, tax_rules_version, data_json, created_at, updated_at, contractor_guess_id)"
                         " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (no, cid, name, "9A", 30000, 0, 0, 29876, "匯款", "2026-03-10", "已核准", "2026", json.dumps({"slipNo": no, "contractorName": name}), T0, T0, guess))
        slip("PS-202603-901", "名冊甲", pid, None)            # 已確認、連到同案的另一張派發 ⇒ 在 d_with 的派發頁列出
        slip("PS-202603-902", "名冊甲", None, pid)            # 名稱推測（contractor_id 為空）⇒ 不列
        conn.execute("INSERT INTO payslip_dispatch_links (slip_no, dispatch_id, created_by, created_at) VALUES (?,?,?,?)", ("PS-202603-901", d_without, "t", T0))
        conn.commit()
    finally:
        conn.close()
    return pid, d_with, d_without


@pytest.fixture()
def world(make_user):
    pid, d_with, d_without = _seed()
    sa = make_user(username="pp48_sa", role="superadmin")
    staff = make_user(username="pp48_staff", role="user", modules=["case_manage", "procurement", "contractor_list"], legacy_finance_flag=False)
    import db
    c = db.get_db()
    try:
        c.execute("UPDATE quotations SET sales_person=? WHERE quote_no=?", (staff[0], NO))
        c.commit()
    finally:
        c.close()
    return pid, d_with, d_without, sa, staff


def _ready(page, cond):
    page.wait_for_function(f"() => window.Alpine && document.querySelector('[x-data]') && ({cond})", timeout=25000)


@pytest.mark.e2e
def test_payslip_form_lists_the_persons_dispatches_and_links_the_ticked_one(live_server, world, new_context):
    pid, d_with, d_without, sa, _staff = world
    page = new_context(viewport={"width": 1440, "height": 1000}).new_page()
    inject_login(page, live_server, sa[0], sa[1])
    page.goto(live_server + "/pages/payslip-form.html")
    _ready(page, f"{ROOT}.rulesVersion !== '' && {ROOT}.contractors && {ROOT}.contractors.length >= 2")
    page.evaluate(f"""() => {{ const d = {ROOT}; const c = d.contractors.find(x => x.name === '名冊甲'); d.selectCon(c) }}""")
    page.wait_for_selector("[data-testid=ps-pick-dispatch-%s]" % d_with, state="visible", timeout=15000)
    assert page.locator("[data-testid=ps-pick-dispatch-%s]" % d_without).count() == 0, "人員名單沒有他的派發不可列出"
    assert "7777" not in page.locator("[data-testid=ps-person-dispatch-box]").inner_text(), "不得出現金額"
    page.locator("[data-testid=ps-pick-dispatch-%s]" % d_with).check()
    page.evaluate(f"""() => {{ const d = {ROOT}; d.q.serviceContent = '管線施工'; d.q.grossAmount = 10000; d.calc() }}""")
    page.evaluate(f"() => {ROOT}.save()")
    page.wait_for_function(f"() => {ROOT}.q.slipNo && !{ROOT}.saving", timeout=15000)
    import db
    c = db.get_db()
    try:
        rows = [dict(r) for r in c.execute("SELECT l.dispatch_id, p.contractor_id, p.contractor_guess_id FROM payslip_dispatch_links l JOIN payslips p ON p.slip_no=l.slip_no"
                                           " WHERE p.contractor_id=? AND p.slip_no NOT LIKE 'PS-202603-9%'", (pid,)).fetchall()]
    finally:
        c.close()
    assert rows == [{"dispatch_id": d_with, "contractor_id": pid, "contractor_guess_id": None}], rows


@pytest.mark.e2e
def test_payslip_form_warns_when_no_roster_person_is_picked(live_server, world, new_context):
    _pid, _a, _b, sa, _staff = world
    page = new_context(viewport={"width": 1440, "height": 1000}).new_page()
    inject_login(page, live_server, sa[0], sa[1])
    page.goto(live_server + "/pages/payslip-form.html")
    _ready(page, f"{ROOT}.rulesVersion !== ''")
    page.evaluate(f"() => {{ {ROOT}.q.contractorName = '手打姓名' }}")
    page.wait_for_selector("[data-testid=ps-no-roster-hint]", state="visible", timeout=10000)


def _open_dispatch_tab(page, live_server, user, did):
    inject_login(page, live_server, user[0], user[1])
    page.goto("%s/pages/case-management.html" % live_server)
    page.wait_for_function("() => { const d = %s; return d && d.session && d.session.token && !d.loading && d.caseCounts }" % ROOT, timeout=30000)
    page.click(".cm-card[data-quote-no='%s']" % NO, timeout=30000)
    page.wait_for_function("() => %s.selected && %s.selected.quote_no === '%s'" % (ROOT, ROOT, NO), timeout=15000)
    page.evaluate("() => { %s.activeTab = 'dispatch' }" % ROOT)
    page.wait_for_selector("[data-testid=dispatch-slips-%s]" % did, state="attached", timeout=20000)


@pytest.mark.e2e
def test_dispatch_tab_shows_confirmed_payslips_of_the_person_superadmin_gets_links(live_server, world, new_context):
    _pid, d_with, d_without, sa, _staff = world
    page = new_context(viewport={"width": 1440, "height": 1000}).new_page()
    _open_dispatch_tab(page, live_server, sa, d_with)
    page.wait_for_selector("[data-testid=dispatch-person-slip-link-PS-202603-901]", state="visible", timeout=15000)
    assert page.locator("[data-testid=dispatch-person-slip-link-PS-202603-902]").count() == 0, "名稱推測未確認的不自動顯示"
    blk = page.locator("[data-testid=dispatch-slips-person-%s]" % d_with)
    assert "1 張舊單" in blk.inner_text()
    assert page.locator("[data-testid=dispatch-slips-person-%s]:visible" % d_without).count() == 0, "沒有他的那張派發不顯示"
    t = page.locator("[data-testid=dispatch-slips-%s]" % d_with).inner_text()
    assert "29876" not in t and "29,876" not in t and "30,000" not in t and "7777" not in t


@pytest.mark.e2e
def test_dispatch_tab_plain_viewer_sees_text_only_no_money(live_server, world, new_context):
    _pid, d_with, _d, _sa, staff = world
    page = new_context(viewport={"width": 1440, "height": 1000}).new_page()
    _open_dispatch_tab(page, live_server, staff, d_with)
    page.wait_for_selector("[data-testid=dispatch-person-slip-text-PS-202603-901]", state="visible", timeout=15000)
    assert page.locator("[data-testid=dispatch-person-slip-link-PS-202603-901]").count() == 0, "一般人員：不是連結"
    blk = page.locator("[data-testid=dispatch-slips-%s]" % d_with)
    assert not [h for h in blk.locator("a").evaluate_all("els => els.map(e => e.getAttribute('href') || '')") if "payslips.html" in h]
    txt = blk.inner_text()
    assert "名冊甲" in txt and "已核准" in txt
    for secret in ("29876", "29,876", "30,000", "30000", "NT$", "7777", "A123456789"):
        assert secret not in txt, secret
    assert "待確認" not in txt, "未確認張數只給最高管理者"


@pytest.mark.e2e
def test_payslips_page_confirm_button_promotes_the_guess_and_badge_disappears(live_server, world, new_context):
    pid, _a, _b, sa, _staff = world
    page = new_context(viewport={"width": 1440, "height": 1000}).new_page()
    inject_login(page, live_server, sa[0], sa[1])
    page.goto(live_server + "/pages/payslips.html")
    _ready(page, "%s.items && %s.items.length >= 2" % (ROOT, ROOT))
    badge = page.locator("[data-testid=ps-unconfirmed-badge]:visible")
    badge.first.wait_for(state="visible", timeout=15000)
    assert badge.count() == 1, "只有 PS-202603-902 是推測對應"
    page.locator("tr", has_text="PS-202603-902").click()
    btn = page.locator("[data-testid=ps-confirm-contractor]")
    btn.wait_for(state="visible", timeout=10000)
    page.once("dialog", lambda d: d.accept())
    btn.click()
    page.wait_for_function("() => [...document.querySelectorAll('[data-testid=ps-unconfirmed-badge]')].every(e => e.offsetParent === null)", timeout=15000)
    page.wait_for_function("() => [...document.querySelectorAll('[data-testid=ps-confirm-contractor]')].every(e => e.offsetParent === null)", timeout=15000)
    import db
    c = db.get_db()
    try:
        row = dict(c.execute("SELECT contractor_id, contractor_guess_id FROM payslips WHERE slip_no='PS-202603-902'").fetchone())
    finally:
        c.close()
    assert row == {"contractor_id": pid, "contractor_guess_id": None}, row
