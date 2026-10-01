# -*- coding: utf-8 -*-
"""客戶回簽單（報價單回簽附件）瀏覽器 e2e：已送出＋已成案 ⇒ 案件頁／報價單表單上傳 → 列出 → 預覽（下載同一支開檔）→ 上傳者可刪；
草稿 ⇒ 入口不出現、API 400；外人看不到。斷言打在畫面（DOM）與資料庫／伺服器回應。截圖預設寫暫存目錄（MOTRIX_SHOTS_DIR 可改）。
conftest 預設把檔頭檢查換成「一律符合」，本檔用真檔頭（PNG／PDF），不需要真檢查。"""
import json
import os
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._requires import requires_module  # noqa: E402

pytestmark = requires_module("case", "客戶回簽單＝M01 報價單附件")

SHOTS = Path(os.environ.get("MOTRIX_SHOTS_DIR") or os.path.join(tempfile.gettempdir(), "qsb-shots")) / "wip-w1-quote-signed-back"
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360f8cfc0f01f0005000201a5f645400000000049454e44ae426082")
Q = "MQ-SBE-001"
QD = "MQ-SBE-002"


def _db(sql, args=()):
    import db
    c = db.get_db()
    try:
        cur = c.execute(sql, args)
        c.commit()
        return [dict(r) for r in c.execute("SELECT 1 WHERE 0")] if cur.description is None else [dict(r) for r in cur.fetchall()]
    finally:
        c.close()


def _shot(page, name):
    try:
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / (name + ".png")), full_page=True)
    except Exception:                                            # noqa: BLE001
        pass


def _quote(no, status, deal, owner):
    uid = _db("SELECT id FROM users WHERE username=?", (owner,))[0]["id"]
    _db("INSERT OR REPLACE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
        " deal_tag, sales_person_id, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (no, status, "e2e客戶", "e2e工程", 1000, 952, json.dumps({"dealTag": deal}), "2026-01-01T00:00:00", "2026-01-01T00:00:00", deal, uid, owner, "[]"))


@pytest.fixture
def world(make_user):
    owner = make_user(username="sbe_owner", role="sales", modules=["quotation", "case_manage"])
    out = make_user(username="sbe_out", role="sales", modules=["quotation"])
    _quote(Q, "已送出", "已成案", "sbe_owner")
    _quote(QD, "草稿", "", "sbe_owner")
    return owner, out


def _png(tmp_path, name="customer-signed.png"):
    p = tmp_path / name
    p.write_bytes(PNG)
    return str(p)


@pytest.mark.e2e
def test_case_page_upload_list_preview_and_delete(live_server, new_context, world, tmp_path):
    owner, _out = world
    page = new_context().new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, owner[0], owner[1])
    page.goto(live_server + "/pages/case-management.html?q=" + Q)
    page.wait_for_selector('[data-testid="cm-signed-back"]', state="visible", timeout=25000)
    assert page.locator('[data-testid="cm-signed-back-upload"]').is_visible()            # 已送出 ⇒ 上傳鈕在
    page.set_input_files('[data-testid="cm-signed-back-upload"] input', _png(tmp_path))
    page.wait_for_selector('[data-testid="cm-signed-back-file"]', timeout=15000)
    assert "customer-signed.png" in page.locator('[data-testid="cm-signed-back-file"]').first.inner_text()
    stored = json.loads(_db("SELECT signed_files_json FROM quotations WHERE quote_no=?", (Q,))[0]["signed_files_json"])
    assert [f["filename"] for f in stored] == ["customer-signed.png"] and stored[0]["uploaderUsername"] == "sbe_owner"
    # 預覽／下載：同一支開檔（共用預覽元件）
    page.locator('[data-testid="cm-signed-back-file"] a').first.click()
    page.wait_for_selector('[data-testid="file-preview-img"]', state="visible", timeout=15000)
    status = page.evaluate("""async (a) => { const s = JSON.parse(localStorage.getItem('motrix_session') || '{}');
        const r = await fetch('/api/attachments/open?type=quotation_signed&doc=' + a.q + '&file=' + a.f, {headers: {Authorization: 'Bearer ' + s.token}});
        return [r.status, (await r.arrayBuffer()).byteLength]; }""", {"q": Q, "f": stored[0]["id"]})
    assert status == [200, len(PNG)]
    page.keyboard.press("Escape")
    _shot(page, "case-page-signed-back")
    # 上傳者本人可刪
    assert page.locator('[data-testid="cm-signed-back-delete"]').is_visible()
    page.click('[data-testid="cm-signed-back-delete"]')
    page.click('[data-testid="ui-dialog-ok"]')                                            # MotrixUI.confirm 的確認鈕
    page.wait_for_selector('[data-testid="cm-signed-back-file"]', state="detached", timeout=15000)
    assert json.loads(_db("SELECT signed_files_json FROM quotations WHERE quote_no=?", (Q,))[0]["signed_files_json"]) == []
    assert not errors, errors


@pytest.mark.e2e
def test_quotation_form_deal_side_entry_uploads_and_other_users_cannot_delete(live_server, new_context, world, tmp_path):
    owner, _out = world
    page = new_context().new_page()
    page.on("dialog", lambda d: d.accept())                         # 離開頁面的 beforeunload 之類：一律放行
    inject_login(page, live_server, owner[0], owner[1])
    page.goto(live_server + "/pages/quotation-form.html?id=" + Q)
    page.wait_for_selector('[data-testid="qf-signed-upload-deal"]', state="visible", timeout=25000)      # 成案處的選填入口
    page.set_input_files('[data-testid="qf-signed-upload-deal"] input', _png(tmp_path, "from-deal.png"))
    page.wait_for_function("() => document.body.innerText.includes('from-deal.png')", timeout=15000)
    assert page.locator('[data-testid="qf-signed-delete"]:visible').count() == 1          # 上傳者本人：刪除鈕看得到
    _shot(page, "quotation-form-signed-back")
    # 另一個人（管理員以外、非上傳者）看到檔但沒有刪除鈕——用 DB 把上傳者改成別人再重載
    files = json.loads(_db("SELECT signed_files_json FROM quotations WHERE quote_no=?", (Q,))[0]["signed_files_json"])
    files[0]["uploaderUsername"] = "someone_else"
    _db("UPDATE quotations SET signed_files_json=? WHERE quote_no=?", (json.dumps(files), Q))
    page2 = new_context().new_page()                                   # 全新瀏覽器環境：不帶前一個分頁留下的本機草稿快取（它會蓋掉伺服器狀態）
    page2.on("dialog", lambda d: d.accept())
    inject_login(page2, live_server, owner[0], owner[1])
    page2.goto(live_server + "/pages/quotation-form.html?id=" + Q)
    page2.wait_for_function("() => document.body.innerText.includes('from-deal.png')", timeout=20000)
    assert page2.locator('[data-testid="qf-signed-delete"]:visible').count() == 0  # 非上傳者、非 admin：看得到檔、看不到刪除鈕（x-show 只是藏起來，要驗可見）
    assert page2.locator('[data-testid="qf-signed-upload"]').is_visible()          # 仍可上傳



@pytest.mark.e2e
def test_draft_quote_hides_the_entries_and_the_api_refuses(live_server, new_context, world, tmp_path, client):
    owner, out = world
    page = new_context().new_page()
    inject_login(page, live_server, owner[0], owner[1])
    page.goto(live_server + "/pages/quotation-form.html?id=" + QD)
    page.wait_for_selector(".form-quote-no", timeout=25000)
    page.wait_for_function("() => document.querySelector('.form-quote-no').innerText.includes('MQ-')", timeout=15000)
    assert not page.locator('[data-testid="qf-signed-upload"]').is_visible()
    assert not page.locator('[data-testid="qf-signed-upload-deal"]').is_visible()
    tok = client.post("/api/auth/login", json={"username": owner[0], "password": owner[1]}).json()["token"]
    r = client.post("/api/quotations/%s/signed-files" % QD, headers={"Authorization": "Bearer " + tok}, files=[("files", ("x.png", PNG, "image/png"))])
    assert r.status_code == 400 and "已送出" in r.json()["detail"]
    assert json.loads(_db("SELECT signed_files_json FROM quotations WHERE quote_no=?", (QD,))[0]["signed_files_json"] or "[]") == []
    # 外人打開別人的案件頁：看不到這個區塊（案件讀不到）
    p2 = new_context().new_page()
    inject_login(p2, live_server, out[0], out[1])
    p2.goto(live_server + "/pages/case-management.html?q=" + Q)
    p2.wait_for_timeout(3000)
    assert not p2.locator('[data-testid="cm-signed-back"]').is_visible()
