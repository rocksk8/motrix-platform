"""瀏覽器層級：動態／業務開發記錄的附件縮圖**真的載得出來**（2026-09-15）。

這一題存在的理由，就是 2026-09-14 那批附件功能漏掉的那一格：後端 API 全綠、
`test_feed_attachments_2026_09_14.py` 八題全過，使用者打開頁面看到的卻是八張
破圖——前端把 session token 當成 `?pt=` 送給 `/api/uploads/`，每一張都 403。
沒有任何一題跑過「瀏覽器去要那個 URL」這一步，所以沒有任何一題會紅。

**觀測點是 `img.naturalWidth`**，不是元素存在、也不是 `src` 長得對：
- 元素存在 → 破圖的 `<img>` 也存在
- `src` 字串比對 → 只是把當初寫錯的那串抄進測試裡，錯了也一樣綠
`naturalWidth > 0` 只有在瀏覽器**真的把回應解碼成一張圖**之後才成立，403 一定是 0。

順帶把讀取回應的狀態碼也收集起來——破圖時要能一眼看出是 403（權限/簽章）還是
404（路徑），不然下次又要從頭查一遍。

需要 `playwright`（見 `test_e2e_playwright_2026_09_07.py` 檔頭說明）。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")

import uvicorn
from tests._e2e_login import inject_login  # noqa: E402
from tests._ports import free_safe_port
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


def _png_bytes():
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def _login(page, base_url, username, password):
    inject_login(page, base_url, username, password)


@pytest.mark.e2e
def test_case_feed_attachment_thumbnail_actually_loads(live_server, client, make_user, e2e_browser):
    """案件動態那一側同一個錯、同一個修法，也要有自己的觀測點。

    兩個頁面各自實作了一份附件顯示（dev-crm.html 與 case-management.js），
    所以只驗一邊會讓另一邊繼續破圖而測試全綠——2026-09-14 就是這樣過關的。
    """
    import json

    u, p = make_user(username="e2e_att_cm", role="superadmin")
    tok = client.post("/api/auth/login",
                      json={"username": u, "password": p}).json()["token"]
    H = {"Authorization": "Bearer " + tok}

    quote_no = "MQ-ATTE2E-001"
    import db
    conn = db.get_db()
    conn.execute(
        "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, "
        "pretax, data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (quote_no, "已送出", "附件測客", "附件測專", 1000, 952,
         json.dumps({"dealTag": "已成案", "caseRecord": {}}, ensure_ascii=False),
         "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"),
    )
    conn.commit()
    conn.close()

    r = client.post(f"/api/quotations/{quote_no}/updates", headers=H,
                    data={"content": "現場照"},
                    files=[("files", ("site.png", _png_bytes(), "image/png"))])
    assert r.status_code == 201, r.text

    upload_responses = []
    browser = e2e_browser
    page = browser.new_page()
    page.on("response", lambda resp: upload_responses.append(
        (resp.status, resp.url)) if "/api/uploads/" in resp.url else None)
    _login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/case-management.html?q={quote_no}")
    page.wait_for_selector(".cm-tab:has-text('動態')", timeout=20000)
    page.click(".cm-tab:has-text('動態')")
    img = page.wait_for_selector(".feed-item img", timeout=15000)
    page.wait_for_function(
        """() => {
            const i = document.querySelector('.feed-item img')
            return i && i.src.includes('/api/uploads/')
        }""", timeout=15000)
    page.wait_for_timeout(500)
    natural_width = img.evaluate("i => i.naturalWidth")

    assert natural_width > 0, (
        "案件動態的附件縮圖沒有載出來（破圖）。/api/uploads/ 的回應："
        f"{upload_responses or '完全沒有發出請求'}"
    )
    assert all(s == 200 for s, _ in upload_responses), upload_responses
