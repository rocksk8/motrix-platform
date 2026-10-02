# -*- coding: utf-8 -*-
"""外包名冊頁（contractors.html）的收款帳號遮蔽（使用者裁示 2026-10-01）：持 contractor_list 模組的管理員看到 ****末四碼，
最高管理者看到全碼；管理員開編輯、不改帳號就存檔 ⇒ DB 裡的真帳號不變（斷言打在 DB）。"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

FULL = "00012345678901"


def _stored():
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT bank_account_number FROM contractors WHERE name='名冊遮蔽測試'").fetchone()[0]
    finally:
        conn.close()


@pytest.mark.e2e
def test_roster_page_masks_for_module_holder_and_edit_keeps_the_number(live_server, client, make_user, new_context):
    sa = make_user(username="rbp_sa", role="superadmin")
    ad = make_user(username="rbp_admin", role="admin", modules=["contractor_list"])
    tok = client.post("/api/auth/login", json={"username": sa[0], "password": sa[1]}).json()["token"]
    r = client.post("/api/contractors", headers={"Authorization": "Bearer " + tok}, json={
        "name": "名冊遮蔽測試", "id_number": "B123456789", "bank_code": "700", "bank_name": "中華郵政",
        "bank_account_name": "名冊遮蔽測試", "bank_account_number": FULL})
    assert r.status_code == 201, r.text
    errors = []

    def open_detail(user):
        page = new_context().new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        inject_login(page, live_server, user[0], user[1])
        page.goto(live_server + "/pages/contractors.html")
        page.locator("tr", has_text="名冊遮蔽測試").first.click()
        page.wait_for_selector('[data-testid="contractor-bank-number"]')
        return page

    p_sa = open_detail(sa)                                                       # 正向控制
    assert p_sa.inner_text('[data-testid="contractor-bank-number"]') == FULL
    p_ad = open_detail(ad)
    assert p_ad.inner_text('[data-testid="contractor-bank-number"]') == "****8901"
    assert FULL not in p_ad.content()
    p_ad.get_by_text("編輯資料").first.click()
    p_ad.wait_for_selector('[data-testid="bank-masked-hint"]', state="visible")
    with p_ad.expect_response(lambda r: r.request.method == "PUT" and r.url.rstrip("/").split("/")[-2] == "contractors"):
        p_ad.locator(".modal-foot button.btn-primary").first.click()
    assert _stored() == FULL, "管理員存檔把真帳號覆蓋成遮蔽值"
    assert not errors, errors
