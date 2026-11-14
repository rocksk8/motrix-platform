"""瀏覽器端對端：權限矩陣頁「暫存區批次」（T86 / S4c）。

點格子只是暫存（畫面上勾框真的跟著變、出現「待套用」、暫存列顯示格數、資料庫不動）→ 「預覽並套用」彈窗逐格列出 → 確定儲存才寫入；
「全部放棄」清空暫存。⚠️ 勾框要真的顯示暫存值（曾因 @click.prevent 被瀏覽器還原而永遠顯示舊值）。
用真實模組宣告的能力，挑第一個「已接入且非高風險」的格子，不假設特定能力鍵。
"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

DATA = "Alpine.$data(document.querySelector('[x-data]'))"


def _pick(page):
    return page.evaluate(f"""() => {{
      const d = {DATA}
      for (const c of d.m.caps) {{
        if (!c.wired || c.risk === 'high') continue
        for (const r of d.m.roles) if (c.cells[r.role]) return {{ cap: c.key, role: r.role, granted: c.cells[r.role].granted }}
      }}
      return null }}""")


def _open(page, live_server):
    page.goto(f"{live_server}/pages/permission-matrix.html")
    page.wait_for_function(f"() => {DATA}.m && {DATA}.m.caps && {DATA}.m.caps.length > 0", timeout=20000)
    cell = _pick(page)
    assert cell, "真實模組宣告裡找不到已接入的非高風險格子"
    return cell


def _db_rows(cap, role):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute("SELECT granted FROM perm_role_caps WHERE role=? AND cap=?", (role, cap))]
    finally:
        conn.close()


@pytest.mark.e2e
def test_staging_a_cell_flips_the_checkbox_shows_the_tag_and_writes_nothing(live_server, make_user, e2e_browser):
    sa = make_user(username="pms_sa", role="superadmin")
    page = e2e_browser.new_page()
    inject_login(page, live_server, *sa)
    c = _open(page, live_server)
    box = page.locator(f'[data-testid="pm-cell-{c["cap"]}-{c["role"]}"]')
    assert box.is_checked() is c["granted"]
    box.click()
    page.locator(f'[data-testid="pm-staged-{c["cap"]}-{c["role"]}"]').wait_for(state="visible", timeout=5000)
    assert box.is_checked() is (not c["granted"]), "暫存後勾框要顯示暫存的值（不是被瀏覽器還原成舊值）"
    page.locator('[data-testid="pm-stagebar"]').wait_for(state="visible", timeout=5000)
    assert page.evaluate(f"() => {DATA}.stageCount()") == 1
    before = _db_rows(c["cap"], c["role"])
    box.click()                                                   # 再點一次＝回到原值 ⇒ 不再算暫存
    page.locator(f'[data-testid="pm-staged-{c["cap"]}-{c["role"]}"]').wait_for(state="hidden", timeout=5000)
    assert box.is_checked() is c["granted"] and page.evaluate(f"() => {DATA}.stageCount()") == 0
    assert _db_rows(c["cap"], c["role"]) == before, "暫存階段沒有寫入任何東西"


@pytest.mark.e2e
def test_preview_lists_the_cell_apply_saves_and_discard_clears(live_server, make_user, e2e_browser):
    sa = make_user(username="pms_sa2", role="superadmin")
    page = e2e_browser.new_page()
    inject_login(page, live_server, *sa)
    c = _open(page, live_server)
    box = page.locator(f'[data-testid="pm-cell-{c["cap"]}-{c["role"]}"]')

    # 全部放棄
    box.click()
    page.locator('[data-testid="pm-stagebar"]').wait_for(state="visible", timeout=5000)
    page.locator('[data-testid="pm-stage-clear"]').click()
    page.locator('[data-testid="pm-stagebar"]').wait_for(state="hidden", timeout=5000)
    assert box.is_checked() is c["granted"]

    # 預覽 → 彈窗逐格列出 → 確定儲存
    box.click()
    page.locator('[data-testid="pm-stage-preview"]').click()
    page.locator('[data-testid="pm-batch-dialog"]').wait_for(state="visible", timeout=10000)
    page.locator(f'[data-testid="pm-batch-line-{c["cap"]}-{c["role"]}"]').wait_for(state="visible", timeout=5000)
    page.locator('[data-testid="pm-batch-apply"]').click()
    page.wait_for_function(f"() => {DATA}.stageCount() === 0 && !{DATA}.bdlg && !{DATA}.busy", timeout=20000)
    page.wait_for_function(f"() => {DATA}.m.caps.some(x => x.key === '{c['cap']}' && x.cells['{c['role']}'].granted === {str(not c['granted']).lower()})", timeout=10000)
    assert box.is_checked() is (not c["granted"])
    rows = _db_rows(c["cap"], c["role"])
    assert not rows or bool(rows[0]["granted"]) is (not c["granted"])
