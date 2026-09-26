"""瀏覽器端對端：IP-13 對方不在時，刪報價單的 notice 要顯示在畫面上（M02 搬遷，2026-09-26）。

後端回 `{"ok": true, "notice": ...}`，畫面原本只看 r.ok、固定顯示「報價單已刪除」⇒ notice 被吞掉，
使用者不會知道業務開發案件的轉建連結沒有解除（ROADMAP 階段 B「搬遷前必修」IP-5 同一類問題）。
正對照（M02 在 ⇒ 只顯示「報價單已刪除」）需要本模組 ⇒ 在 `modules/crm/tests/test_e2e_crm_quote_delete_no_notice_2026_09_26.py`（第五班列車反向控制抓到，§B-11）。
"""
import pytest

pytest.importorskip("playwright.sync_api")

from core import registry  # noqa: E402

DATA = "Alpine.$data(document.querySelector('[x-data]'))"
QNO = "MQ-202609-IP11"


def _seed():
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
                     "data_json, created_at, updated_at, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (QNO, "草稿", "刪除客戶", "刪除專案", 0, 0, "{}",
                      "2026-09-26T00:00:00", "2026-09-26T00:00:00", "2026-09-26"))
        conn.commit()
    finally:
        conn.close()


def _delete_and_read_toasts(live_server, make_user, new_page, login_as, name):
    user = make_user(username=name, role="superadmin")
    _seed()
    page = new_page()
    login_as(page, tuple(user)[:2])
    page.on("dialog", lambda d: d.accept())                      # confirm(「確定刪除…」)
    page.goto(f"{live_server}/pages/quotations.html")
    page.wait_for_function(f"() => {DATA}.quotes.some(q => q.quote_no === '{QNO}')", timeout=20000)
    page.evaluate(f"() => {{ window.__toasts = []; const t = {DATA}.toast.bind({DATA}); "
                  f"{DATA}.toast = (m, ...a) => {{ window.__toasts.push(m); return t(m, ...a) }} }}")
    page.evaluate(f"() => {DATA}.deleteQuote('{QNO}')")
    page.wait_for_function(f"() => !{DATA}.quotes.some(q => q.quote_no === '{QNO}')", timeout=15000)
    return page.evaluate("() => window.__toasts")


@pytest.mark.e2e
def test_notice_is_shown_when_crm_is_absent(live_server, make_user, new_page, login_as, monkeypatch):
    from modules.case.api import quotations
    orig = registry.providers
    monkeypatch.setattr(registry, "providers", lambda cap: {} if cap == "crm.quote_deleted" else orig(cap))
    toasts = _delete_and_read_toasts(live_server, make_user, new_page, login_as, "e2e_ip11_absent")
    assert any(quotations.QUOTE_DELETED_CRM_ABSENT in t for t in toasts), toasts

