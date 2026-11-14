"""瀏覽器端對端：組織架構「一次加入多人」（T86 / S4c）。

勾選多人 → 預覽（誰從哪個部門搬來）→ 確定 → 資料庫裡每個人的 department_id 都變成該部門；
「復原這一批」把每個人放回原本的部門（含原本沒有部門的）。觀測點：資料庫落地值與元件狀態，不打頁面文字。
"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

ROOT = "Alpine.$data(document.querySelector('[x-data]'))"


def _setup():
    import db
    conn = db.get_db()
    now = "2026-11-14T00:00:00"
    conn.execute("INSERT INTO divisions (name, sort_order, created_at) VALUES ('甲處', 1, ?)", (now,))
    div = conn.execute("SELECT id FROM divisions WHERE name='甲處'").fetchone()[0]
    for i, n in enumerate(("甲一部", "甲二部"), 1):
        conn.execute("INSERT INTO departments (division_id, name, sort_order, created_at) VALUES (?, ?, ?, ?)", (div, n, i, now))
    ids = {n: conn.execute("SELECT id FROM departments WHERE name=?", (n,)).fetchone()[0] for n in ("甲一部", "甲二部")}
    conn.commit()
    conn.close()
    return ids


def _dept_of(username):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT department_id FROM users WHERE username=?", (username,)).fetchone()[0]
    finally:
        conn.close()


def _set_dept(username, dept_id):
    import db
    conn = db.get_db()
    conn.execute("UPDATE users SET department_id=? WHERE username=?", (dept_id, username))
    conn.commit()
    conn.close()


@pytest.mark.e2e
def test_batch_add_members_moves_everyone_and_undo_restores_each_original_department(live_server, make_user, e2e_browser):
    sa = make_user(username="ob_sa", role="superadmin")
    for n in ("ob_a", "ob_b", "ob_c"):
        make_user(username=n, role="sales")
    ids = _setup()
    _set_dept("ob_a", ids["甲一部"])          # a 原在甲一部；b 原在甲一部；c 原本沒有部門
    _set_dept("ob_b", ids["甲一部"])
    page = e2e_browser.new_page()
    inject_login(page, live_server, *sa)
    page.goto(f"{live_server}/pages/org-structure.html")
    page.wait_for_function(f"() => {ROOT}.users && {ROOT}.users.length > 0 && {ROOT}.orgTree.length > 0", timeout=20000)
    target = ids["甲二部"]
    page.evaluate(f"() => {{ const d = {ROOT}; const dept = d.orgTree.flatMap(x => x.departments).find(x => x.id === {target}); d.openMemberBatch(dept) }}")
    page.locator('[data-testid="org-batch-modal"]').wait_for(state="visible", timeout=10000)

    uids = {n: page.evaluate(f"() => {ROOT}.users.find(u => u.username === '{n}').id") for n in ("ob_a", "ob_b", "ob_c")}
    for n in ("ob_a", "ob_c"):
        page.locator(f'[data-testid="org-batch-user-{uids[n]}"] input').click()
    assert page.evaluate(f"() => {ROOT}.mb.picked.slice().sort()") == sorted([uids["ob_a"], uids["ob_c"]])
    assert page.locator('[data-testid="org-batch-preview"]').is_visible()
    assert _dept_of("ob_a") == ids["甲一部"], "預覽階段沒有寫入任何東西"

    page.locator('[data-testid="org-batch-apply"]').click()
    page.wait_for_function(f"() => {ROOT}.mb.result && !{ROOT}.mb.busy", timeout=20000)
    assert _dept_of("ob_a") == target and _dept_of("ob_c") == target
    assert _dept_of("ob_b") == ids["甲一部"], "沒勾的人不動"

    page.locator('[data-testid="org-batch-undo"]').click()
    page.wait_for_function(f"() => !{ROOT}.mb.undo.length && !{ROOT}.mb.busy", timeout=20000)
    assert _dept_of("ob_a") == ids["甲一部"], "復原後 a 回到原部門"
    assert not _dept_of("ob_c"), "復原後 c 回到沒有部門"


@pytest.mark.e2e
def test_batch_filter_and_select_shown_only_touch_listed_users(live_server, make_user, e2e_browser):
    sa = make_user(username="ob_sa2", role="superadmin")
    for n in ("ob_x1", "ob_x2", "ob_y1"):
        make_user(username=n, role="sales")
    ids = _setup()
    page = e2e_browser.new_page()
    inject_login(page, live_server, *sa)
    page.goto(f"{live_server}/pages/org-structure.html")
    page.wait_for_function(f"() => {ROOT}.users && {ROOT}.users.length > 0 && {ROOT}.orgTree.length > 0", timeout=20000)
    page.evaluate(f"() => {{ const d = {ROOT}; d.openMemberBatch(d.orgTree.flatMap(x => x.departments).find(x => x.id === {ids['甲一部']})) }}")
    page.locator('[data-testid="org-batch-modal"]').wait_for(state="visible", timeout=10000)
    page.fill('[data-testid="org-batch-q"]', "ob_x")
    page.locator('[data-testid="org-batch-all"]').click()
    picked = page.evaluate(f"() => {ROOT}.mb.picked.map(id => {ROOT}.users.find(u => u.id === id).username).sort()")
    assert picked == ["ob_x1", "ob_x2"], "全選只選目前列出（篩選後）的人"
    page.locator('[data-testid="org-batch-none"]').click()
    assert page.evaluate(f"() => {ROOT}.mb.picked.length") == 0
