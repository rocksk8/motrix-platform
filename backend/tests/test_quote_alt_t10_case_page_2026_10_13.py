# -*- coding: utf-8 -*-
"""M3 T10（T57）：案件頁——所選方案顯示與方案比較（靜態檢查）。金額本身由回簽同交易更新 SQL 欄位與 tot，下游讀同一組欄位。"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
HTML = (ROOT / "frontend" / "pages" / "case-management.html").read_text(encoding="utf-8")
FIN = (ROOT / "frontend" / "js" / "case-management-fin.js").read_text(encoding="utf-8")
ALT_PLAN = (ROOT / "backend" / "modules" / "case" / "api" / "alt_plan.py").read_text(encoding="utf-8")


def test_case_page_shows_picked_option_and_unpicked_notice():
    assert 'data-testid="cm-alt-picked"' in HTML and "所選方案：" in HTML
    assert "客戶尚未選定擇一方案；下面的金額不含擇一品項。" in HTML
    assert "altPickedLines()" in FIN and "d.totalsByAlt !== true" in FIN         # 開關沒開 ⇒ 惰性，不顯示


def test_case_plan_comparison_is_read_only_backend_driven_and_marks_unadopted():
    assert "/case-plan-view" in FIN and "（未採用）" in HTML and "（採用）" in HTML
    seg = FIN[FIN.index("async toggleAltPlan()"): FIN.index("altPlanIsPicked")]
    assert "method" not in seg and "reduce(" not in seg                      # 只讀取、不自算


def test_two_interfaces_use_two_different_permission_functions():
    i = ALT_PLAN.index('"/api/quotations/{quote_no}/plan-view"')
    j = ALT_PLAN.index('"/api/quotations/{quote_no}/case-plan-view"')
    assert "quote_money_visible(u)" in ALT_PLAN[i:j] and "money_visible(u)" in ALT_PLAN[j:j + 600]
    assert "quote_money_visible(u)" not in ALT_PLAN[j:ALT_PLAN.index("/api/alt-quote/config")]
