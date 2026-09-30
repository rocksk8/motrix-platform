"""W2 稽核修正（W2F2／W2F4）：傳票帶入附件。

W2F4：後端 POST attachments 只允許草稿（與刪除同一條規則；前端入口本來就只在草稿顯示）。
W2F2：新傳票自動存檔期間 `uploading` 保持鎖定 ⇒ 雙擊不再出現「傳票尚未儲存」假錯誤、也不會重複帶入。
"""
import io
import json

import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402
from tests._requires import requires_module  # noqa: E402


def _hdr(client, u):
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u[0], "password": u[1]}).json()["token"]}


def _vouchers(client, h):
    d = client.get("/api/vouchers", headers=h).json()
    return d if isinstance(d, list) else (d.get("items") or d.get("vouchers") or [])


def _png():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (6, 6), (5, 5, 5)).save(buf, format="PNG")
    return buf.getvalue()


def _voucher(client, h):
    r = client.post("/api/vouchers", headers=h, json={"summary": "W2F4", "lines": [
        {"account_code": "6111", "debit": 10, "credit": 0}, {"account_code": "1113", "debit": 0, "credit": 10}]})
    assert r.status_code == 200, r.text[:300]
    return r.json()["id"]


def test_w2f4_only_a_draft_accepts_attachments(client, make_user):
    u = make_user(username="w2fix_s4", role="superadmin")
    h = _hdr(client, u)
    vid = _voucher(client, h)
    up = client.post(f"/api/vouchers/{vid}/attachments", headers=h, files=[("files", ("a.png", _png(), "image/png"))])
    assert up.status_code == 200 and up.json()["added"] == 1, up.text[:300]                # 草稿：照常
    assert client.post(f"/api/vouchers/{vid}/submit", headers=h, json={}).status_code == 200
    st = client.get(f"/api/vouchers/{vid}", headers=h).json()["status"]
    assert st != "草稿"
    r = client.post(f"/api/vouchers/{vid}/attachments", headers=h, files=[("files", ("b.png", _png(), "image/png"))])
    assert r.status_code == 400 and "草稿" in r.json()["detail"], (r.status_code, r.text[:300])
    picks = client.post(f"/api/vouchers/{vid}/attachments", headers=h, json={"picks": [{"type": "x", "docNo": "y", "fileId": "z"}]})
    assert picks.status_code == 400 and "草稿" in picks.json()["detail"], picks.text[:300]  # 帶入形態同一道門
    n = len(client.get(f"/api/vouchers/{vid}", headers=h).json()["attachments"])
    assert n == 1, "被拒的請求不可以留下附件（%d）" % n


pytestmark_e2e = requires_module("case", "打 M01（案件）的資料")


@pytest.mark.e2e
@pytestmark_e2e
def test_w2f2_double_click_on_a_new_voucher_shows_no_false_error(live_server, make_user, e2e_browser, client):
    from modules.accounting.tests.test_e2e_voucher_source_block_below_2026_09_25 import D, _seed, _pick_case
    u = make_user(username="w2fix_s2", role="superadmin")
    _seed(client, u)
    h = _hdr(client, u)
    before = len(_vouchers(client, h))
    page = e2e_browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
    inject_login(page, live_server, u[0], u[1])
    page.goto(f"{live_server}/pages/voucher.html")
    page.click('[data-testid="voucher-new"]')
    page.wait_for_function(f"() => {{ try {{ return {D}.editing && {D}.canEdit && {D}.sourcesLoaded && {D}.id == 0 }} catch (e) {{ return false }} }}",
                           timeout=20000)
    page.evaluate(f"""() => {{ const d = {D};
        d.lines[0].account_code = '6111'; d.lines[0].debit = '100';
        d.lines[1].account_code = '1113'; d.lines[1].credit = '100'; }}""")
    _pick_case(page)
    page.locator('[data-testid="src-file"]').nth(0).click()
    page.locator('[data-testid="voucher-att-preview"]').wait_for(state="visible", timeout=5000)
    res = page.evaluate(f"""async () => {{ const d = {D};
        const a = d.bringFromPreview(), b = d.bringFromPreview(), c = d.bringFromPreview(); await Promise.all([a, b, c]);
        return {{ id: d.id, att: d.attachments.length, err: d.attErr, uploading: d.uploading }} }}""")
    assert res["id"] > 0 and res["att"] == 1 and res["err"] == "" and res["uploading"] is False, json.dumps(res, ensure_ascii=False)
    after = _vouchers(client, h)
    assert len(after) - before == 1, "連點 3 次產生了 %d 張草稿" % (len(after) - before)
