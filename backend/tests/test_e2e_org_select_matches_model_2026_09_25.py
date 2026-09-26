"""下拉「顯示的」值必須等於模型值——營運報表季下拉（7ad9392）的同型候選。

hichan-bf 修季下拉時列出三個同型寫法：`<option :value="0">` ＋ `x-for` 產生的選項。
- users.html 編輯帳號的「處」「部門」：openEdit 把既有值寫進 form，若 option 還沒長出來，
  畫面會顯示「未分類」而模型是實際部門；使用者一存檔（或一動下拉）就把帳號改成未分類
  ⇒ 依部門判定的可見範圍跟著變。
- org-structure.html「加入部門」選人：模型只由使用者選或程式重設為 0。

量法同 7ad9392：每個看得到的 `select[x-model]`，DOM 選中的值 ＝ Alpine 模型值。
既有資料刻意放在**第二個**處（值非預設、也不是第一個選項），否則顯示錯位時剛好選到它也會綠。
"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login as _login  # noqa: E402,F401
from tests._e2e_select_model import MISMATCHES_JS as _MISMATCHES_JS  # noqa: E402

ROOT = "Alpine.$data(document.querySelector('[x-data]'))"



def _rendered(page):
    """PERF #6：等 Alpine 把這次狀態變化畫完（nextTick）＋瀏覽器實際畫出兩個影格。
    ⚠️ 只適用於沒有 CSS transition 的元素（有 transition 的要等轉場落定）。"""
    page.evaluate("() => new Promise(r => (window.Alpine ? Alpine.nextTick : (f => f()))(() => requestAnimationFrame(() => requestAnimationFrame(r))))")

def _org_with_member(username):
    import db
    conn = db.get_db()
    now = "2026-09-25T00:00:00"
    conn.execute("INSERT INTO divisions (name, sort_order, created_at) VALUES ('甲處', 1, ?)", (now,))
    conn.execute("INSERT INTO divisions (name, sort_order, created_at) VALUES ('乙處', 2, ?)", (now,))
    div_b = conn.execute("SELECT id FROM divisions WHERE name='乙處'").fetchone()[0]
    conn.execute("INSERT INTO departments (division_id, name, sort_order, created_at) VALUES (?, '乙一部', 1, ?)",
                 (div_b, now))
    conn.execute("INSERT INTO departments (division_id, name, sort_order, created_at) VALUES (?, '乙二部', 2, ?)",
                 (div_b, now))
    dept = conn.execute("SELECT id FROM departments WHERE name='乙二部'").fetchone()[0]
    conn.execute("UPDATE users SET department_id=? WHERE username=?", (dept, username))
    conn.commit()
    conn.close()
    return div_b, dept


@pytest.mark.e2e
@pytest.mark.parametrize("tree_late", [False, True], ids=["tree-first", "tree-late"])
def test_editing_a_user_shows_their_real_division_and_department(live_server, make_user, tree_late, e2e_browser):
    """tree-late：init 以 Promise.all 同時載帳號與組織樹 ⇒ 帳號列可能先出現；在組織樹回來前按編輯，
    選項是之後才長出來的——正是季下拉錯位的時序。"""
    admin = make_user(username="osm_sa", role="superadmin")
    make_user(username="osm_member", role="sales")
    div_b, dept = _org_with_member("osm_member")
    browser = e2e_browser
    page = browser.new_context().new_page()
    _login(page, live_server, *admin)
    held = []
    if tree_late:
        page.route("**/api/org/tree*", lambda r: held.append(r))
    page.goto(f"{live_server}/pages/users.html")
    page.wait_for_function(f"() => window.Alpine && {ROOT} && ({ROOT}.users || []).some(u => u.username === 'osm_member')",
                           timeout=20000)
    if tree_late:
        assert held and not page.evaluate(f"() => ({ROOT}.orgTree || []).length"), "組織樹應該還沒回來"
    page.evaluate(f"() => {{ const d = {ROOT}; d.openEdit(d.users.find(u => u.username === 'osm_member')) }}")
    if tree_late:
        page.wait_for_timeout(300)
        for r in held:
            r.continue_()
    page.wait_for_function(f"() => ({ROOT}.orgTree || []).length >= 2", timeout=10000)
    page.wait_for_function(f"() => {ROOT}.form.departmentId === {dept}", timeout=5000)
    _rendered(page)   # PERF #6：原本固定等 300ms
    got = page.evaluate("""() => { const d = Alpine.$data(document.querySelector('[x-data]'))
      const pick = e => [...document.querySelectorAll('select')].find(s => s.getAttribute('x-model.number') === e)
      return { div: pick('form.divisionId').value, dept: pick('form.departmentId').value,
               modelDiv: String(d.form.divisionId), modelDept: String(d.form.departmentId) } }""")
    assert got["modelDiv"] == str(div_b) and got["modelDept"] == str(dept), got
    assert got["div"] == got["modelDiv"], "處下拉顯示的不是帳號實際的處：%s" % got
    assert got["dept"] == got["modelDept"], "部門下拉顯示的不是帳號實際的部門：%s" % got
    assert page.evaluate(_MISMATCHES_JS) == []


@pytest.mark.e2e
def test_org_structure_add_member_picker_matches_model(live_server, make_user, e2e_browser):
    """選人下拉在 x-if="isDeptMembersOpen(dept.id)" 裡（與季下拉同型）。
    ☠️ 情境：選了一個人 → 收合部門 → 再展開：模型仍是那個人，若下拉顯示「選擇要加入的使用者…」，
       按「加入部門」會加進一個畫面上沒選的人。"""
    admin = make_user(username="osm_sa2", role="superadmin")
    make_user(username="osm_new", role="sales")
    _div, dept = _org_with_member("osm_sa2")
    browser = e2e_browser
    page = browser.new_context().new_page()
    _login(page, live_server, *admin)
    page.goto(f"{live_server}/pages/org-structure.html")
    page.wait_for_function(f"() => window.Alpine && {ROOT} && ({ROOT}.orgTree || []).length >= 2", timeout=20000)
    sel_css = r"select[x-model\.number='addMemberSelection[dept.id]']"
    page.evaluate(f"() => {ROOT}.toggleDeptMembers({dept})")
    sel = page.locator(sel_css)
    sel.wait_for(state="visible", timeout=5000)
    # 初始：模型 undefined、DOM 為 "0"——兩者都是「未選」（addMember 以 !uid 擋），不算錯位
    init = page.evaluate(f"() => [[...document.querySelectorAll('select')].find(e => e.getAttribute('x-model.number') === 'addMemberSelection[dept.id]').value, {ROOT}.addMemberSelection[{dept}]]")
    assert init[0] == "0" and not init[1], init
    opt = sel.locator("option").nth(1).get_attribute("value")
    sel.select_option(opt)
    _rendered(page)   # PERF #6：原本固定等 200ms
    assert page.evaluate(_MISMATCHES_JS) == []          # 使用者選了一個人
    page.evaluate(f"() => {ROOT}.toggleDeptMembers({dept})")   # 收合（x-if 拆掉下拉）
    _rendered(page)   # PERF #6：原本固定等 200ms
    page.evaluate(f"() => {ROOT}.toggleDeptMembers({dept})")   # 再展開（重建）
    sel.wait_for(state="visible", timeout=5000)
    _rendered(page)   # PERF #6：原本固定等 300ms
    got = page.evaluate(f"() => [[...document.querySelectorAll('select')].find(e => e.getAttribute('x-model.number') === 'addMemberSelection[dept.id]').value, String({ROOT}.addMemberSelection[{dept}])]")
    assert got[0] == got[1] == opt, "重新展開後下拉顯示 %s、模型是 %s（選的是 %s）" % (got[0], got[1], opt)
