# -*- coding: utf-8 -*-
"""承攬商管理頁的收款帳號遮蔽（使用者裁示 2026-10-01）：一般管理員看到 ****末四碼，最高管理者看到全碼；
管理員開編輯、不改帳號就存檔 ⇒ DB 裡的真帳號不變（斷言打在 DB，不打在畫面文字）。"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

FULL = "00012345678901"


def _stored_number():
    import db
    conn = db.get_db()
    try:
        return json.loads(conn.execute("SELECT data_json FROM vendor_contractors WHERE name='遮蔽測試承攬商'").fetchone()[0])["bankAccountNumber"]
    finally:
        conn.close()


@pytest.mark.e2e
def test_vendor_page_masks_for_admin_and_full_for_superadmin_and_edit_keeps_the_number(live_server, client, make_user, new_context):
    sa = make_user(username="bmv_sa", role="superadmin")
    ad = make_user(username="bmv_admin", role="admin", modules=["contractor_list", "procurement", "case_manage"])
    tok = client.post("/api/auth/login", json={"username": sa[0], "password": sa[1]}).json()["token"]
    r = client.post("/api/vendor-contractors", headers={"Authorization": "Bearer " + tok}, json={
        "name": "遮蔽測試承攬商", "tax_id": "12345678",
        "data": {"bankCode": "700", "bankName": "中華郵政", "bankBranch": "台中", "bankAccountName": "遮蔽測試承攬商", "bankAccountNumber": FULL}})
    assert r.status_code == 201, r.text
    errors = []

    def open_detail(user):
        ctx = new_context()
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        inject_login(page, live_server, user[0], user[1])
        page.goto(live_server + "/pages/vendor-contractors.html")
        page.locator("tr", has_text="遮蔽測試承攬商").first.click()
        page.wait_for_selector('[data-testid="vendor-bank-number"]')
        return page

    p_sa = open_detail(sa)                                                   # 正向控制：最高管理者看全碼
    assert p_sa.inner_text('[data-testid="vendor-bank-number"]') == FULL
    p_ad = open_detail(ad)
    assert p_ad.inner_text('[data-testid="vendor-bank-number"]') == "****8901"
    assert FULL not in p_ad.content()
    # 管理員開編輯：看到遮蔽值與提示；不改帳號就存檔 ⇒ 真帳號不變
    p_ad.get_by_text("編輯資料").click()
    p_ad.wait_for_selector('[data-testid="bank-masked-hint"]', state="visible")
    with p_ad.expect_response(lambda r: r.request.method == "PUT" and "/api/vendor-contractors/" in r.url and "passbook" not in r.url):
        p_ad.locator('.modal-foot button.btn-primary').first.click()
    assert _stored_number() == FULL, "管理員存檔把真帳號覆蓋成遮蔽值"
    assert not errors, errors
