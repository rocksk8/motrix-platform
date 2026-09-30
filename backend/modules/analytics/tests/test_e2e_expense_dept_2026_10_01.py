"""營運報表「收支」分頁的部門維度（2026-10-01）：無案件支出依送出者部門歸屬、案件支出依案件業務部門、都沒有 ⇒ 未分類。
終點狀態＝畫面上「依部門」表與明細「部門」欄；篩選部門後，只剩該部門（含無案件但明示該部門者）。
截圖（預設暫存目錄；設 MOTRIX_SHOTS_DIR 才寫共用資料夾）。"""
import json
import os
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402
from modules.analytics.tests.test_dept_dimension_2026_10_01 import _seed_org  # noqa: E402

SHOTS = Path(os.environ.get("MOTRIX_SHOTS_DIR") or os.path.join(tempfile.gettempdir(), "aet27-shots")) / "wip-w3-dept-dim"


def _shot(page, name):
    try:
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / (name + ".png")), full_page=True)
    except Exception:                                            # noqa: BLE001 — 截圖失敗（含 BK19 護欄）不影響判定
        pass


def _seed_expenses(dept_a, dept_b):
    import db
    conn = db.get_db()
    try:
        cols = [c[1] for c in conn.execute("PRAGMA table_info(case_extra_expenses)").fetchall()]
        if "department_id" not in cols:                          # 請款模組的 migration 會加；這裡補上才有「明示部門」可驗
            conn.execute("ALTER TABLE case_extra_expenses ADD COLUMN department_id INTEGER")
        for qn, dept, amt, desc in (("MQ-D1", None, 1000, "案件A支出"),      # 案件業務部門＝工程部
                                    ("", dept_b, 700, "無案件業務部門支出"),  # 無案件、送出者＝業務部
                                    ("", None, 40, "無案件未分類")):
            conn.execute(
                "INSERT INTO case_extra_expenses (quote_no, category, description, total_cost, expense_date, status,"
                " invoice_date, created_at, updated_at, department_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (qn, "交通", desc, amt, "2026-03-10", "已核准", "2026-03-10", "2026-03-10T00:00:00", "2026-03-10T00:00:00", dept))
        conn.commit()
    finally:
        conn.close()


@pytest.mark.e2e
def test_expense_tab_groups_by_department_with_caseless_and_unclassified(live_server, make_user, e2e_browser):
    a, b = _seed_org()
    u = make_user(username="dd_admin", role="superadmin")
    _seed_expenses(a, b)
    page = e2e_browser.new_page(viewport={"width": 1280, "height": 1000})
    inject_login(page, live_server, u[0], u[1])
    page.goto(live_server + "/pages/reports.html")
    page.wait_for_selector(".period-bar", timeout=20000)
    page.evaluate("() => { const d = Alpine.$data(document.querySelector('[x-data]')); d.expensesScope='year'; d.expensesYear=2026; d.showExpensesTab(); d.loadExpenses(); }")
    page.wait_for_selector("[data-testid=expense-by-dept]", timeout=20000)
    page.wait_for_function("() => document.querySelectorAll('[data-testid=expense-by-dept] tbody tr').length === 3", timeout=20000)
    rows = page.eval_on_selector_all("[data-testid=expense-by-dept] tbody tr",
                                     "els => els.map(e => [...e.querySelectorAll('td')].map(t => t.innerText.trim()))")
    digits = lambda s: int("".join(ch for ch in s if ch.isdigit()) or 0)
    assert [(r[0], digits(r[2])) for r in rows] == [("工程部", 1000), ("業務部", 700), ("未分類", 40)], "未分類排最後"
    col = page.eval_on_selector_all("[data-testid=expense-row-dept]", "els => els.map(e => e.innerText.trim())")
    assert sorted(col) == ["工程部", "未分類", "業務部"]
    _shot(page, "1_by_department")
    # 篩選部門＝業務部：無案件但送出者為業務部的那筆仍在；其他部門與未分類不在
    page.evaluate("(id) => { const d = Alpine.$data(document.querySelector('[x-data]')); d.departmentId = id; d.loadExpenses(); }", b)
    page.wait_for_function("() => document.querySelectorAll('[data-testid=expense-by-dept] tbody tr').length === 1", timeout=20000)
    only = page.eval_on_selector_all("[data-testid=expense-by-dept] tbody tr", "els => els.map(e => e.innerText)")
    assert len(only) == 1 and "業務部" in only[0] and "700" in only[0]
    _shot(page, "2_filtered_business_dept")
