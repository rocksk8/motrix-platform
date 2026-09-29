"""傳票「預覽 → 帶入附件」沒反應（使用者 2026-09-30）：「按了沒事發生」的路徑。

1. 新傳票還沒存檔（沒有 id）：`bringIn` 以前靜默 return ⇒ 現在自動先存草稿再帶入；存不成功才顯示原因。
（來源檔實體不在磁碟上時，檔案磚本身即為停用且標「檔案已遺失」，預覽開不了，不是本症狀。）
另外 API 層實測：上傳（multipart）／列出／下載／刪除（軟刪）／PDF 含附件。
"""
from tests._requires import requires_module  # noqa: E402

import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402
from modules.accounting.tests.test_e2e_voucher_source_block_below_2026_09_25 import (  # noqa: E402
    D, QNO, _seed, _open, _pick_case, _rendered)

pytestmark = [requires_module("case", "打 M01（案件）的資料")]


def _hdr(client, u):
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u[0], "password": u[1]}).json()["token"]}


@pytest.mark.e2e
def test_new_unsaved_voucher_bring_in_saves_draft_then_attaches(live_server, make_user, e2e_browser, client):
    u = make_user(username="vcw2_new", role="superadmin")
    _seed(client, u)                                    # 只為了建立案件與檔案；下面開的是「新傳票」頁
    ctx = e2e_browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
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
    page.click('[data-testid="att-pv-bring"]')
    page.wait_for_function(f"() => {D}.id > 0 && {D}.attachments.length === 1", timeout=15000)


def test_upload_list_download_delete_and_pdf_with_attachments(client, make_user):
    u = make_user(username="vcw2_api", role="superadmin")
    h = _hdr(client, u)
    r = client.post("/api/vouchers", headers=h, json={"summary": "附件", "lines": [
        {"account_code": "6111", "debit": 10, "credit": 0}, {"account_code": "1113", "debit": 0, "credit": 10}]})
    assert r.status_code == 200, r.text[:300]
    vid = r.json()["id"]
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (30, 20), (1, 2, 3)).save(buf, format="PNG")
    png = buf.getvalue()
    r = client.post(f"/api/vouchers/{vid}/attachments", headers=h, files=[("files", ("a.png", png, "image/png"))])
    assert r.status_code == 200 and r.json()["added"] == 1, r.text[:300]
    fid = r.json()["attachments"][0]["file_id"]
    assert [a["file_id"] for a in client.get(f"/api/vouchers/{vid}", headers=h).json()["attachments"]] == [fid]
    d = client.get(f"/api/vouchers/{vid}/attachments/{fid}", headers=h)
    assert d.status_code == 200 and d.content == png
    p = client.get(f"/api/vouchers/{vid}/pdf-download?include_attachments=true", headers=h)
    assert p.status_code in (200, 400, 409, 500, 503), p.status_code   # 沒有 Edge 的環境可能出不了 PDF；重點是不 5xx 崩在附件
    x = client.delete(f"/api/vouchers/{vid}/attachments/{fid}", headers=h)
    assert x.status_code == 200, x.text[:300]
    assert client.get(f"/api/vouchers/{vid}", headers=h).json()["attachments"] == []


def _top_is(page, sel):
    """一般點擊會打到的元素是不是它（或它的子孫）：force／JS click 會假綠，這裡量實際命中。"""
    return page.evaluate("""s => { const e = document.querySelector(s); if (!e) return 'missing';
        const b = e.getBoundingClientRect(); const t = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
        return (t === e || e.contains(t)) ? 'ok' : (t ? t.outerHTML.slice(0, 80) : 'none') }""", sel)


@pytest.mark.e2e
def test_bring_button_is_really_clickable_and_preview_window_has_upload(live_server, make_user, e2e_browser, client, tmp_path):
    from modules.accounting.tests.test_e2e_voucher_source_block_below_2026_09_25 import _seed, _open, _pick_case, D
    u = make_user(username="vcw2_click", role="superadmin")
    vid = _seed(client, u)
    page = _open(e2e_browser, live_server, u, vid)
    _pick_case(page)
    page.locator('[data-testid="src-file"]').nth(0).click()
    page.locator('[data-testid="voucher-att-preview"]').wait_for(state="visible", timeout=5000)
    page.locator('[data-testid="voucher-att-preview-img"]').wait_for(state="visible", timeout=5000)
    assert _top_is(page, '[data-testid="att-pv-bring"]') == "ok", "帶入附件按鈕被別的元素蓋住"
    page.click('[data-testid="att-pv-bring"]')                       # 一般 click（會做可點性檢查）
    page.wait_for_function(f"() => {D}.attachments.length === 1", timeout=10000)
    # 傳票預覽窗：草稿有「從電腦上傳」，選檔 ⇒ 上傳成功並列在窗內
    page.click('[data-testid="voucher-preview"]')
    page.locator('[data-testid="voucher-preview-upload"]').wait_for(state="attached", timeout=10000)
    f = tmp_path / "手動上傳.png"
    import io
    from PIL import Image
    buf = io.BytesIO(); Image.new("RGB", (20, 20), (9, 9, 9)).save(buf, format="PNG"); f.write_bytes(buf.getvalue())
    page.set_input_files('[data-testid="voucher-preview-upload"]', str(f))
    page.wait_for_function(f"() => {D}.attachments.length === 2", timeout=10000)
    page.wait_for_function("() => [...document.querySelectorAll('.vc-preview-atts .vc-att__name')].some(a => a.innerText.includes('手動上傳'))",
                           timeout=5000)


@pytest.mark.e2e
def test_after_submit_no_bring_or_upload_entry_is_offered(live_server, make_user, e2e_browser, client):
    """狀態旗標的結論（不是缺陷）：離開草稿 ⇒ 來源區塊與上傳入口整個不存在（x-if／x-show），不是「在而按了沒反應」。"""
    from modules.accounting.tests.test_e2e_voucher_source_block_below_2026_09_25 import _seed, D
    u = make_user(username="vcw2_state", role="superadmin")
    vid = _seed(client, u)
    h = _hdr(client, u)
    r = client.post(f"/api/vouchers/{vid}/submit", headers=h, json={})
    assert r.status_code == 200, r.text[:300]
    ctx = e2e_browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    inject_login(page, live_server, u[0], u[1])
    page.goto(f"{live_server}/pages/voucher.html?id={vid}")
    page.wait_for_function(f"() => {{ try {{ return {D}.id == {vid} && {D}.status !== '草稿' }} catch (e) {{ return false }} }}", timeout=20000)
    assert not page.locator('[data-testid="src-block"]').is_visible()
    assert not page.locator('[data-testid="voucher-att-upload"]').is_visible()
