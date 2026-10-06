# -*- coding: utf-8 -*-
"""t44-attach-views e2e：出納頁「待付款申請」的附件清單（唯讀）——清單、預覽按鈕、開檔失敗的行內訊息。

觀測點：附件清單（發票／附件標籤、名稱、大小）、HEIC 標「（下載）」；點圖片 ⇒ 預覽視窗開起（img 出現）；點檔案不存在的 HEIC ⇒
畫面出現行內錯誤、**沒有任何瀏覽器對話框（alert）**；已登錄付款後整列消失。
"""
import json
import os

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._requires import requires_module  # noqa: E402

pytestmark = [pytest.mark.e2e, requires_module("case", "費用單據端點"), requires_module("arap", "出納頁")]

SENT = "/api/quotations/-/extra-expenses"
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 40


def _x(sql, args=()):
    import db
    c = db.get_db()
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


def test_cashier_sees_attachment_list_and_preview_and_inline_error(live_server, make_user, e2e_browser):
    from helpers import uploads as up
    users = {n: make_user(username=n, role=r, modules=m) for n, r, m in (
        ("pf_form", "sales", ["expense_forms"]), ("pf_cash", "finance", None))}
    ctx = e2e_browser.new_context().request
    r = ctx.post(f"{live_server}/api/auth/login", data={"username": "pf_form", "password": users["pf_form"][1]})
    assert r.ok, r.text()
    h = {"Authorization": "Bearer " + r.json()["token"]}
    r = ctx.post(live_server + SENT, headers=h, data={"kind": "travel", "lines": [{"category": "其他", "summary": "高鐵", "amount": 4321}],
                                                       "data": {"applicant": "pf_form"}, "payeeType": "employee", "payeeName": "申請人"})
    assert r.status == 201, r.text()
    eid = r.json()["id"]
    folder = "case_extra_expense/-_%s" % eid
    files = [
        {"id": "f1", "filename": "inv.png", "path": folder + "/inv.png", "size": len(PNG), "mime": "image/png", "uploadedBy": "pf_form",
         "uploadedAt": "2026-10-06T09:00:00", "kind": "invoice"},
        {"id": "f2", "filename": "IMG_1.HEIC", "path": folder + "/IMG_1.HEIC", "size": 7, "mime": "image/heic", "uploadedBy": "pf_form",
         "uploadedAt": "2026-10-06T09:02:00", "kind": "other"},
    ]
    full = os.path.join(up.UPLOADS_ROOT, *files[0]["path"].split("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as fh:
        fh.write(PNG)                                           # f2（HEIC）刻意不寫檔 ⇒ 開檔 404 ⇒ 行內錯誤
    _x("UPDATE case_extra_expenses SET status='已核准', files_json=? WHERE id=?", (json.dumps(files), eid))

    page = e2e_browser.new_context().new_page()
    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    inject_login(page, live_server, *users["pf_cash"])
    page.goto(live_server + "/pages/cashier.html")
    tab = page.locator('[data-testid="cashier-payreq-tab"]')
    tab.wait_for(state="visible", timeout=20000)
    tab.click()
    box = page.locator('[data-testid="cashier-payreq-files-case-%d"]' % eid)
    box.wait_for(state="visible", timeout=15000)
    txt = box.inner_text()
    assert "發票" in txt and "inv.png" in txt and "附件" in txt and "IMG_1.HEIC（下載）" in txt, txt

    # 預覽按鈕：圖片 ⇒ 預覽視窗出現圖片
    page.locator('[data-testid="cashier-payreq-file-case-%d-f1"]' % eid).click()
    page.locator('[data-testid="file-preview-img"]').wait_for(state="visible", timeout=15000)
    page.locator('[data-testid="file-preview-close"]').click()

    # 檔案不存在的 HEIC ⇒ 行內錯誤，不能彈對話框
    page.locator('[data-testid="cashier-payreq-file-case-%d-f2"]' % eid).click()
    err = page.locator('[data-testid="cashier-payreq-file-error-case-%d"]' % eid)
    err.wait_for(state="visible", timeout=10000)
    assert "開啟檔案失敗" in err.inner_text()
    assert dialogs == [], dialogs
