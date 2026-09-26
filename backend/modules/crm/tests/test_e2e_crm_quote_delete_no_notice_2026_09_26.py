"""瀏覽器端對端：IP-13 正對照——M02 在 ⇒ 刪報價單只顯示「報價單已刪除」，沒有 notice（M02 搬遷，2026-09-26）。

自 `tests/test_e2e_quote_delete_crm_absent_notice_2026_09_26.py` 拆出：這一題需要本模組，拿掉模組時跟著消失（§B-11；
第五班列車反向控制抓到）。反向控制那一題（M02 不在 ⇒ notice）留在模組外。

以下為原檔說明：

後端回 `{"ok": true, "notice": ...}`，畫面原本只看 r.ok、固定顯示「報價單已刪除」⇒ notice 被吞掉，
使用者不會知道業務開發案件的轉建連結沒有解除（ROADMAP 階段 B「搬遷前必修」IP-5 同一類問題）。
正對照：M02 在 ⇒ 只顯示「報價單已刪除」，沒有 notice。
"""
import pytest

pytest.importorskip("playwright.sync_api")


DATA = "Alpine.$data(document.querySelector('[x-data]'))"
QNO = "MQ-202609-IP13P"


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
def test_no_notice_when_crm_is_present(live_server, make_user, new_page, login_as):
    from routers import quotations
    toasts = _delete_and_read_toasts(live_server, make_user, new_page, login_as, "e2e_ip11_present")
    assert toasts == ["報價單已刪除"], toasts
    assert not any(quotations.QUOTE_DELETED_CRM_ABSENT in t for t in toasts)
