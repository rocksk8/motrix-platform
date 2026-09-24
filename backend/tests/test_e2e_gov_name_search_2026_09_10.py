"""瀏覽器端對端：依公司名稱查政府登記資料的畫面入口（2026-09-10 稽核補上）。

背景：後端 `GET /api/company/search?q=` 從一開始就存在，但客戶／供應商／承攬商
三個頁面都只接了 `/api/company/tax/{id}`（統編查詢）——使用者得先知道確切統編
才查得到，想用公司名稱找只能自己去經濟部網站查完再回來貼。

三頁的「帶入表單」欄位名不同（customers 用 `taxId`、vendor-contractors 用
`tax_id`），所以查詢邏輯抽到 `static/gov-lookup.js` 共用、帶入各頁自理。
這支測試就是釘住三頁都真的接對了——尤其是那個 `taxId` / `tax_id` 的差異，
純後端測試絕對攔不下來。

GCIS 是外部政府 API，測試不能真的打（會慢、會不穩、離線就掛），
這裡 monkeypatch `dashboard._gcis_get` 回固定資料。
"""
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")

import uvicorn
from tests._e2e_login import inject_login  # noqa: E402
from tests._ports import free_safe_port

FAKE_GCIS = [
    {"Company_Name": "允碩整合集創股份有限公司", "Business_Accounting_NO": "60575481",
     "Company_Status": "核准設立"},
    {"Company_Name": "允碩測試工程有限公司", "Business_Accounting_NO": "12345678",
     "Company_Status": "核准設立"},
]


@pytest.fixture()
def live_server(live_server, monkeypatch):
    """把 GCIS 外部查詢換成固定資料（PERF #5：覆寫延伸 conftest 的共用伺服器；
    伺服器與題目在同一個行程，dashboard._gcis_get 在呼叫時才查，換掉就生效）。"""
    from routers import dashboard

    def _fake_gcis_get(url):
        return (FAKE_GCIS, "ok") if "Company_Name%20like" in url or "Company_Name+like" in url \
            or "Company_Name" in url else ([], "ok")

    monkeypatch.setattr(dashboard, "_gcis_get", _fake_gcis_get)
    return live_server


def _login(page, base_url, username, password):
    return inject_login(page, base_url, username, password)


# (頁面, 開啟新增表單的按鈕文字, 帶入後統編會出現在哪個 x-model)
PAGES = [
    ("customers.html", "新增客戶", "form.taxId"),
    ("suppliers.html", "新增供應商", "form.taxId"),
    ("vendor-contractors.html", "新增承攬商", "form.tax_id"),
]


@pytest.mark.e2e
def test_gov_name_search_fills_form(live_server, make_user, e2e_browser):
    """三頁都要：輸入名稱 → 查詢 → 點結果 → 統編與名稱帶進表單。

    三頁刻意在**同一個 browser／同一個 live_server** 裡跑完，不用 parametrize：
    每個 param 都會各自起一台 uvicorn 加一個 chromium，e2e 檔案變多之後這種
    負載會把同批其他測試的等待擠爆（2026-09-10 實測，既有的
    test_login_create_submit_approve_smoke 偶發失敗率從 1/18 升到 2/4）。
    失敗訊息會標明是哪一頁，診斷性不受影響。
    """
    username, password = make_user(username="e2e_gov", role="superadmin")

    browser = e2e_browser
    for page_file, new_btn, tax_model in PAGES:
        ctx = browser.new_context()
        page = ctx.new_page()
        try:
            _login(page, live_server, username, password)
            page.goto(f"{live_server}/pages/{page_file}")
            page.wait_for_load_state("networkidle")

            page.click(f'button:has-text("{new_btn}")')
            search_box = page.locator('input[x-model="govNameQ"]')
            search_box.wait_for(state="visible", timeout=20000)

            search_box.fill("允碩")
            page.locator('button:has-text("查詢")').last.click()

            page.wait_for_function(
                "() => document.body.innerText.includes('允碩整合集創股份有限公司')",
                timeout=20000)

            page.locator("text=允碩整合集創股份有限公司").last.click()

            # 統編帶進表單——三頁最容易接錯的地方（taxId vs tax_id）
            page.wait_for_function(
                """(sel) => {
                     const el = document.querySelector(`input[x-model="${sel}"]`);
                     return el && el.value === '60575481';
                   }""",
                arg=tax_model, timeout=20000)
        except Exception as e:
            raise AssertionError(
                f"{page_file} 的公司名稱查詢沒有把統編帶進 {tax_model}：{e}") from e
        finally:
            ctx.close()
