# -*- coding: utf-8 -*-
"""T65 C1 報價單清單個人檢視偏好 ON 狀態：真瀏覽器＋真的設定 API。
場景：版面旗標＋list_view 三項開啟 ⇒ 面板出現；隱藏專案欄、日期欄上移、每頁 25 筆 ⇒ 儲存 ⇒ 重新載入仍套用（表頭與每一列順序一致）；
分頁 30 筆＝25＋5；還原預設 ⇒ 回到原本的欄位與全部筆數。關閉 list_view 後面板消失、欄位回到公司版面。
"""
import pytest

from tests._requires import requires_module
from tests.e2e_on_state._common import DATA_JS, inject_login, seed_draft_quote, set_flag, token_of

pytestmark = [pytest.mark.e2e, requires_module("case", "報價單頁")]

HEADS = "() => [...document.querySelectorAll('thead th')].filter(t => t.offsetParent !== null).map(t => t.textContent.trim())"
ROWCOLS = "() => { const tr = document.querySelector('tbody tr.ql-row'); return tr ? [...tr.children].filter(c => c.dataset.col).map(c => c.dataset.col) : [] }"


def _clone_quotes(src_qn, n):
    import db
    conn = db.get_db()
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(quotations)").fetchall() if r[1] != "id"]
        for i in range(n):
            vals = {c: None for c in cols}
            row = conn.execute("SELECT %s FROM quotations WHERE quote_no=?" % ",".join(cols), (src_qn,)).fetchone()
            vals = dict(zip(cols, row))
            vals["quote_no"] = "ON-PG-%02d" % i
            conn.execute("INSERT INTO quotations (%s) VALUES (%s)" % (",".join(cols), ",".join("?" * len(cols))), [vals[c] for c in cols])
        conn.commit()
    finally:
        conn.close()


def test_c1_personal_view_prefs_apply_persist_and_reset(live_server, make_user, new_context):
    u = make_user(username="on_lv1", role="superadmin")
    ctx = new_context()
    tk = token_of(ctx, live_server, u)
    qn = seed_draft_quote()
    _clone_quotes(qn, 29)
    set_flag(ctx, live_server, tk, "builder_layout", "quotations", 1)
    for f in ("quotes_personal_columns", "quotes_personal_default_tab", "quotes_personal_page_size"):
        set_flag(ctx, live_server, tk, "list_view", f, 1, as_int=True)
    page = ctx.new_page()
    inject_login(page, live_server, u[0], u[1])
    page.goto(live_server + "/pages/quotations.html")
    page.wait_for_function("() => %s.lvOn && %s.lvOn.columns === true && %s.lvOn.size === true" % (DATA_JS, DATA_JS, DATA_JS), timeout=20000)
    page.wait_for_function("() => document.querySelectorAll('tbody tr.ql-row').length >= 30", timeout=20000)      # 預設不分頁：全部都在
    assert "案件名稱" in page.evaluate(HEADS)
    page.get_by_test_id("lv-toggle").click()
    page.get_by_test_id("lv-panel").wait_for(state="visible", timeout=5000)
    page.evaluate("() => { const d = %s; d.lvToggle('project'); d.lvMove('date', -1); d.lvMove('date', -1); d.pv = { ...d.pv, size: 25 } }" % DATA_JS)
    # 必要欄位不可隱藏
    page.evaluate("() => %s.lvToggle('quoteNo')" % DATA_JS)
    assert page.evaluate("() => %s.pv.hidden" % DATA_JS) == ["project"]
    page.get_by_test_id("lv-save").click()
    page.wait_for_function("() => document.querySelectorAll('tbody tr.ql-row').length === 25", timeout=15000)
    page.get_by_test_id("lv-pager").wait_for(state="visible", timeout=5000)
    # 重新載入：偏好從伺服器回來
    page.reload()
    page.wait_for_function("() => document.querySelectorAll('tbody tr.ql-row').length === 25", timeout=20000)
    page.wait_for_function("(js) => !eval(js)().includes('案件名稱')", arg=HEADS, timeout=10000)
    heads = page.evaluate(HEADS)
    assert heads.index("報價日期") < heads.index("狀態"), heads
    page.wait_for_function("(js) => { const c = eval(js)(); return c.length && c[0] }", arg=ROWCOLS, timeout=10000)
    rc = page.evaluate(ROWCOLS)
    assert rc.index("date") < rc.index("status") and rc.index("quoteNo") < rc.index("customer"), rc
    ths = page.evaluate("() => [...document.querySelectorAll('thead th[data-col]')].map(t => t.dataset.col)")
    assert ths == rc, (ths, rc)                                                      # 表頭與資料列順序一致
    # 下一頁：剩下 5 筆
    page.get_by_text("下一頁").click()
    page.wait_for_function("() => document.querySelectorAll('tbody tr.ql-row').length === 5", timeout=10000)
    # 還原預設（重新載入後面板是關的）
    page.get_by_test_id("lv-toggle").click()
    page.get_by_test_id("lv-panel").wait_for(state="visible", timeout=5000)
    page.get_by_text("還原預設").click()
    page.wait_for_function("() => document.querySelectorAll('tbody tr.ql-row').length >= 30", timeout=15000)
    heads = page.evaluate(HEADS)
    assert "案件名稱" in heads and heads.index("狀態") < heads.index("案件進度") < heads.index("報價日期"), heads
    assert page.evaluate(ROWCOLS)[-1] == "date"
