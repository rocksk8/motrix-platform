"""迴歸測試：vendor 目錄下的自架第三方函式庫應可長效快取，其餘 .js/.html/.css 頁面
程式碼仍維持 no-store（2026-09-08，見 MOTRIX-ERP-QUICK.md §12 2026-09-08 條目）。

背景：`main.py::no_cache_static()` 原本對所有 .html/.css/.js 一律下
`Cache-Control: no-store`，CDN 自架（2026-09-07）之後這條規則誤傷了版本號釘死在
檔名裡、內容保證不變的 vendor 函式庫（如 alpine-3.17.1.min.js）——每次換頁都要
重新向本機同一個 uvicorn process 要一次，徒增同源請求量與延遲，也是造成
test_login_create_submit_approve_smoke 在整套跑時偶發逾時的放大因子之一。
"""


def test_vendor_js_is_long_cached(client):
    r = client.get("/static/vendor/alpine-3.17.1.min.js")
    assert r.status_code == 200
    cc = r.headers.get("cache-control", "")
    assert "no-store" not in cc
    assert "immutable" in cc
    assert "max-age=31536000" in cc


def test_app_js_still_no_store(client):
    r = client.get("/static/sidebar.js")
    assert r.status_code == 200
    cc = r.headers.get("cache-control", "")
    assert "no-store" in cc


def test_page_html_still_no_store(client):
    r = client.get("/pages/login.html")
    assert r.status_code == 200
    cc = r.headers.get("cache-control", "")
    assert "no-store" in cc
