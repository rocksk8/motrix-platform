"""瀏覽器端對端：自選條件報表（參數化範本，T79 候選）。

流程：選範本 → 選條件 → 產出 → 改條件 → 結果跟著變 → 下載 Excel。
每一步等的是「這一次產出完成」的條件（stale 提示消失＋列數），不是立刻讀畫面。
"""
import io
import json

import openpyxl
import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from modules.analytics.tests.test_report_templates_2026_11_11 import _seed  # noqa: E402

ROWS = "[data-testid=rt-row]"


def _open(live_server, make_user, e2e_browser, name, role="superadmin", modules=None, path="report-templates.html"):
    username, password = make_user(username=name, role=role, **({"modules": modules, "legacy_finance_flag": False} if modules else {}))
    page = e2e_browser.new_page(viewport={"width": 1440, "height": 900})
    inject_login(page, live_server, username, password)
    page.goto(f"{live_server}/pages/{path}")
    return page


def _ready(page):
    page.wait_for_selector("[data-testid=rt-form]", timeout=20000)


def _run(page, expect_rows):
    """按『產出報表』，等這一次產出完成（條件已套用＝不再 stale、列數對）。"""
    page.click("[data-testid=rt-run]")
    page.wait_for_function(
        """(n) => { const st = document.querySelector('[data-testid=rt-stale]');
                    const b = document.querySelector('[data-testid=rt-run]');
                    return st && st.offsetParent === null && b && !b.disabled
                      && document.querySelectorAll('[data-testid=rt-row]').length === n }""",
        arg=expect_rows, timeout=20000)


def _quote_nos(page):
    return page.evaluate("""() => [...document.querySelectorAll('[data-testid=rt-row] td:nth-of-type(1)')].map(e => e.innerText.trim())""")


def _sum(page, label):
    return page.locator(f"[data-testid='rt-sum-{label}'] .rt-sum__v").inner_text()


@pytest.mark.e2e
def test_pick_parameters_run_change_parameters_rerun(live_server, make_user, e2e_browser):
    a, b = _seed()
    page = _open(live_server, make_user, e2e_browser, "e2e_rt1")
    _ready(page)
    assert [t.inner_text() for t in page.locator(".rt-tab").all()] == ["案件清單", "收款明細", "業務員績效"]
    # 還沒按產出：沒有結果表
    assert page.locator("[data-testid=rt-result]").count() == 0

    _run(page, 4)
    assert sorted(_quote_nos(page)) == ["MQ-T1", "MQ-T2", "MQ-T3", "MQ-T4"]
    assert _sum(page, "案件數") == "4"

    # 選日期區間 → 只剩 5 月的兩張
    page.fill("[data-testid=rt-param-date_from]", "2026-05-01")
    page.fill("[data-testid=rt-param-date_to]", "2026-05-31")
    # 條件已變更、尚未重新產出：畫面明說，且不能下載（免得下載到與條件不符的檔）
    page.wait_for_selector("[data-testid=rt-stale]", state="visible")
    assert page.locator("[data-testid=rt-excel]").is_disabled()
    _run(page, 2)
    assert sorted(_quote_nos(page)) == ["MQ-T2", "MQ-T3"]
    assert _sum(page, "案件數") == "2"
    assert page.locator("[data-testid=rt-excel]").is_enabled()

    # 再加部門 → 一張
    page.select_option("[data-testid=rt-param-department_id]", str(b))
    _run(page, 1)
    assert _quote_nos(page) == ["MQ-T3"]

    # 案件狀態、業務關鍵字也生效
    page.select_option("[data-testid=rt-param-department_id]", "")
    page.fill("[data-testid=rt-param-date_from]", "")
    page.fill("[data-testid=rt-param-date_to]", "")
    page.select_option("[data-testid=rt-param-deal_tag]", "已結案")
    _run(page, 1)
    assert _quote_nos(page) == ["MQ-T2"]
    page.select_option("[data-testid=rt-param-deal_tag]", "")
    page.fill("[data-testid=rt-param-sales_person]", "乙")
    _run(page, 2)
    assert sorted(_quote_nos(page)) == ["MQ-T3", "MQ-T4"]

    # 清除條件 → 回到全部
    page.click("[data-testid=rt-reset]")
    _run(page, 4)


@pytest.mark.e2e
def test_quick_range_and_empty_result(live_server, make_user, e2e_browser):
    _seed()
    page = _open(live_server, make_user, e2e_browser, "e2e_rt2")
    _ready(page)
    page.click("[data-testid=rt-quick-lastyear]")
    y = page.evaluate("() => new Date().getFullYear() - 1")
    assert page.input_value("[data-testid=rt-param-date_from]") == f"{y}-01-01"
    assert page.input_value("[data-testid=rt-param-date_to]") == f"{y}-12-31"
    _run(page, 0)                       # 種子資料都在 2026，去年沒有
    page.wait_for_selector("[data-testid=rt-empty]", state="visible")
    assert _sum(page, "案件數") == "0"
    page.click("[data-testid=rt-quick-year]")
    yy = page.evaluate("() => new Date().getFullYear()")
    assert page.input_value("[data-testid=rt-param-date_from]") == f"{yy}-01-01"


@pytest.mark.e2e
def test_each_template_has_its_own_parameters_and_remembers_them(live_server, make_user, e2e_browser):
    _seed()
    page = _open(live_server, make_user, e2e_browser, "e2e_rt3")
    _ready(page)
    assert page.locator("[data-testid=rt-param-paid]").count() == 0
    page.fill("[data-testid=rt-param-customer]", "大海")
    _run(page, 2)

    page.click("[data-testid=rt-tab-payments]")
    page.wait_for_selector("[data-testid=rt-param-paid]", state="attached")
    assert page.locator("[data-testid=rt-param-sales_person]").count() == 0
    assert page.input_value("[data-testid=rt-param-customer]") == "", "別的範本的條件不帶過來"
    page.select_option("[data-testid=rt-param-paid]", "unreceived")
    _run(page, 2)
    assert sorted(_quote_nos(page)) == ["MQ-T3", "MQ-T4"]
    # 有日期條件時，沒填日期的款項被排除——畫面要明說
    page.fill("[data-testid=rt-param-date_from]", "2026-01-01")
    page.fill("[data-testid=rt-param-date_to]", "2026-12-31")
    _run(page, 1)
    assert "沒填" in page.locator("[data-testid=rt-notes]").inner_text()

    page.click("[data-testid=rt-tab-case-list]")
    page.wait_for_selector("[data-testid=rt-param-sales_person]", state="attached")
    assert page.input_value("[data-testid=rt-param-customer]") == "大海", "回到原範本，之前填的條件還在"

    page.click("[data-testid=rt-tab-sales-perf]")
    _run(page, 2)
    assert sorted(_quote_nos(page)) == ["乙業務", "甲業務"]


@pytest.mark.e2e
def test_server_validation_message_is_shown(live_server, make_user, e2e_browser):
    _seed()
    page = _open(live_server, make_user, e2e_browser, "e2e_rt4")
    _ready(page)
    page.fill("[data-testid=rt-param-date_from]", "2026-06-01")
    page.fill("[data-testid=rt-param-date_to]", "2026-05-01")
    page.click("[data-testid=rt-run]")
    err = page.locator("[data-testid=rt-error]")
    err.wait_for(state="visible", timeout=10000)
    assert "起日不可晚於迄日" in err.inner_text()
    assert page.locator("[data-testid=rt-result]").count() == 0
    # 改對再產出 ⇒ 錯誤消失
    page.fill("[data-testid=rt-param-date_to]", "2026-06-30")
    page.click("[data-testid=rt-run]")
    page.wait_for_selector("[data-testid=rt-error]", state="detached", timeout=10000)
    page.wait_for_selector("[data-testid=rt-result]", state="attached", timeout=10000)


@pytest.mark.e2e
def test_download_excel_matches_the_conditions_on_screen(live_server, make_user, e2e_browser):
    a, b = _seed()
    page = _open(live_server, make_user, e2e_browser, "e2e_rt5")
    _ready(page)
    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    page.fill("[data-testid=rt-param-date_from]", "2026-05-01")
    page.fill("[data-testid=rt-param-date_to]", "2026-05-31")
    page.select_option("[data-testid=rt-param-department_id]", str(b))
    page.click("[data-testid=rt-param-customer]")
    page.keyboard.type("大海")                      # 真的打字：篩選條件不可觸發全站「未儲存變更」守門
    _run(page, 1)
    assert page.evaluate("() => !window.motrixIsDirty"), "篩選條件不是待存內容"
    with page.expect_download(timeout=20000) as dl:
        page.click("[data-testid=rt-excel]")
    with open(dl.value.path(), "rb") as f:               # 下載暫存檔沒有副檔名，openpyxl 依副檔名拒讀
        wb = openpyxl.load_workbook(io.BytesIO(f.read()))
    ws = wb["報表"]
    assert dialogs == [], dialogs
    assert {ws.cell(row=i, column=1).value for i in range(2, ws.max_row + 1)} == {"MQ-T3"}
    cond = {r[0].value: r[1].value for r in wb["條件"].iter_rows(min_row=1) if r[0].value}
    assert cond["報價日 起"] == "2026-05-01" and cond["部門"] == "事業處 / 業務部"


@pytest.mark.e2e
def test_cell_text_is_rendered_as_text_not_markup(live_server, make_user, e2e_browser):
    """客戶名稱帶 HTML／腳本：畫面只當文字顯示，不執行、不產生元素。"""
    _seed()
    import db
    conn = db.get_db()
    try:
        evil = "<img src=x onerror=window.__rt_pwned=1>"
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at,"
            " updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("MQ-T9", "已送出", evil, "x", 1000, 1000, json.dumps({"dealTag": "已成案"}), "2026-01-01T00:00:00",
             "2026-01-01T00:00:00", "已成案", "2026-09-01"))
        conn.commit()
    finally:
        conn.close()
    page = _open(live_server, make_user, e2e_browser, "e2e_rt6")
    _ready(page)
    _run(page, 5)
    assert page.locator("[data-testid=rt-table] img").count() == 0
    assert evil in page.locator("[data-testid=rt-table]").inner_text()
    assert page.evaluate("() => window.__rt_pwned === undefined")


@pytest.mark.e2e
def test_account_without_finance_view_sees_explanation(live_server, make_user, e2e_browser):
    _seed()
    page = _open(live_server, make_user, e2e_browser, "e2e_rt7", role="viewer", modules=["reports"])
    err = page.locator("[data-testid=rt-load-error]")
    err.wait_for(state="visible", timeout=20000)
    assert "財務" in err.inner_text()
    assert page.locator("[data-testid=rt-form]").count() == 0


@pytest.mark.e2e
def test_hub_lists_the_page_and_it_opens(live_server, make_user, e2e_browser):
    page = _open(live_server, make_user, e2e_browser, "e2e_rt8", path="reports-hub.html")
    card = page.locator("[data-testid='rh-card-report-templates.html']")
    card.wait_for(state="visible", timeout=20000)
    assert "自選條件報表" in card.inner_text()
    card.locator("a").click()
    page.wait_for_url("**/report-templates.html**", timeout=20000)
    _ready(page)
