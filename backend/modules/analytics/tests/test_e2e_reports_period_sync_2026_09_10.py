"""瀏覽器層級端對端測試：營運報表頂部 period-bar 切換月/季/年時，
「本期收支」KPI 區塊必須跟著切換（2026-09-10 使用者回報的 bug）。

為什麼一定要用真實瀏覽器：這個 bug 的後端完全正常（`_collect()` 一直都有依
期別正確過濾），壞的是前端 `reports.js` 的狀態同步——`init()` 有把 period-bar
的年/月同步給 `/expenses-monthly`、`/receivables-monthly` 兩支獨立資料流，但
`prevPeriod()`／`nextPeriod()`／`switchType()` 以及 period-bar 的年/月/季下拉
都沒有跟上。後端 API 測試全綠也攔不下來，只有真的在瀏覽器裡切期別才看得到
「上面期別變了、下面金額不動」。修法是把同步收斂到 `loadData()` 一個點。

需要 `playwright`（見 `test_e2e_playwright_2026_09_07.py` 檔頭說明），
沒裝的環境整個檔案 skip。
"""
import json
import re
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")

import uvicorn
from tests._e2e_login import inject_login  # noqa: E402
from tests._ports import free_safe_port

#: 2026-09-26 M05 搬遷：下列題同時需要應收應付（出納／收款資料）
_NEEDS_ARAP = pytest.mark.skipif(not __import__("core.source_tree", fromlist=["x"]).module_installed("modules/arap/"),
                                 reason="需要應收應付（M05）：模組不在這個安裝包（PLAYBOOK §B-11）")




def _login(page, base_url, username, password):
    return inject_login(page, base_url, username, password)


def _seed_income(conn, quote_no, quote_date, received_at, amount):
    """建一張已成案報價單，單一款項且已收款——同時餵得到「收入」（依 receivedAt）
    與「應收」（依成案月份）兩條資料流。"""
    data_json = json.dumps({
        "dealTag": "已成案",
        "caseRecord": {"payment": {"items": [{
            "id": 1, "type": "訂金", "pct": 100, "amount": amount,
            "received": True, "receivedAt": received_at,
        }]}},
    }, ensure_ascii=False)
    conn.execute(
        "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
        "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (quote_no, "已送出", "期別測客", "期別測專", amount, int(amount / 1.05), data_json,
         "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", quote_date),
    )


def _kpi_value(page, label_text):
    """讀「本期收支」區塊某張 KPI 卡片的數字（fmt() 產出的 'NT$ 1,234' 字串）。"""
    val = page.locator(
        f".kpi-card:has(.kpi-card__lbl:text-is('{label_text}')) .kpi-card__val"
    ).first.inner_text()
    digits = re.sub(r"[^0-9-]", "", val)
    return int(digits or 0)


def _wait_kpi(page, label_text, expected):
    """等某張 KPI 卡片的數字變成 expected。

    刻意不用固定秒數的 `wait_for_timeout()`：這頁切期別會連打三支 API
    （financial／expenses-monthly／receivables-monthly），機器忙的時候固定等待
    會不夠、閒的時候又白等，兩台 e2e 測試同時跑就會偶發逾時。改成等實際值到位，
    逾時才失敗。"""
    page.wait_for_function(
        """([label, want]) => {
             const el = [...document.querySelectorAll('.kpi-card__lbl')]
               .find(e => e.innerText.trim() === label);
             if (!el) return false;
             const v = el.parentElement.querySelector('.kpi-card__val');
             return !!v && v.innerText.replace(/[^0-9]/g, '') === String(want);
           }""",
        arg=[label_text, expected],
        timeout=20000,
    )


@_NEEDS_ARAP
@pytest.mark.e2e
def test_period_bar_drives_income_expense_block(live_server, make_user, e2e_browser):
    """核心回歸：period-bar 切到不同月份／不同季，「本期收支」的收入數字要跟著變。

    種三筆已收款：2026-07 收 110000、2026-08 收 220000、2026-10 收 990000。
      月報 2026-07 → 當月收入 110000
      月報 2026-08 → 當月收入 220000（會變，這就是原本壞掉的地方）
      季報 Q3      → 本季收入 330000（七＋八，十月的不能混進來）
    """
    username, password = make_user(username="e2e_period", role="superadmin")

    import db
    conn = db.get_db()
    try:
        _seed_income(conn, "MQ-PER-JUL", "2026-07-01", "2026-07-15T00:00:00", 110000)
        _seed_income(conn, "MQ-PER-AUG", "2026-08-01", "2026-08-15T00:00:00", 220000)
        _seed_income(conn, "MQ-PER-OCT", "2026-10-01", "2026-10-15T00:00:00", 990000)
        conn.commit()
    finally:
        conn.close()

    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, username, password)
    page.goto(f"{live_server}/pages/reports.html")
    page.wait_for_selector(".period-bar", timeout=20000)
    page.wait_for_selector(".kpi-card__lbl:text-is('當月收入')", timeout=20000)

    # ── 月報 2026-07 ──────────────────────────────────────────────
    # 2026-09-24 AC2：預設改權責口徑（收入依階段完成）；本題種的是「依收款日」的收入，
    # 驗的是期別同步不是口徑 ⇒ 明確切到現金口徑（切換本身見 test_e2e_report_recognition）
    page.evaluate("() => Alpine.$data(document.querySelector('[x-data]')).setBasis('cash')")
    page.click('.period-type-btn:has-text("月報")')
    page.select_option('.period-bar select >> nth=0', "2026")
    page.select_option('.period-bar select >> nth=1', "7")
    _wait_kpi(page, "當月收入", 110000)
    assert _kpi_value(page, "當月收入") == 110000

    # ── 月報 2026-08：這一步在修好之前完全不會變 ──────────────────
    page.select_option('.period-bar select >> nth=1', "8")
    _wait_kpi(page, "當月收入", 220000)
    assert _kpi_value(page, "當月收入") == 220000

    # ── 季報 Q3：標籤變「本季」，金額是七＋八 ─────────────────────
    page.click('.period-type-btn:has-text("季報")')
    page.select_option('.period-bar select >> nth=1', "3")
    page.wait_for_selector(".kpi-card__lbl:text-is('本季收入')", timeout=20000)
    _wait_kpi(page, "本季收入", 330000)
    assert _kpi_value(page, "本季收入") == 330000

    # ── 年報：標籤變「今年度」，金額含十月那筆 ────────────────────
    page.click('.period-type-btn:has-text("年報")')
    page.wait_for_selector(".kpi-card__lbl:text-is('今年度收入')", timeout=20000)
    _wait_kpi(page, "今年度收入", 1320000)
    assert _kpi_value(page, "今年度收入") == 1320000
