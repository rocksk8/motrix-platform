# -*- coding: utf-8 -*-
"""ROADMAP A8：Excel 樣式／匯出速率下沉 helpers/xlsx_out.py；_COMPANY → company_identity；
PART_CATEGORIES → helpers/part_catalog.py（DEPENDENCY-MAP §3 #10 #12 #13 #17）。

搬移前後同資料的 xlsx 值與樣式逐格相同，是在搬移當下以一次性比對驗證的（commit 訊息記錄），
這裡釘的是搬移後要一直成立的性質。
"""
import ast
import io
from pathlib import Path

import openpyxl
import pytest
from fastapi import HTTPException

from helpers import xlsx_out

BACKEND = Path(__file__).resolve().parent.parent


def _imports_from(rel, module):
    tree = ast.parse((BACKEND / rel).read_text(encoding="utf-8"))
    return {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == module
            for a in n.names}


@pytest.mark.parametrize("rel", ["routers/accounting_export.py", "routers/cashier.py"])
def test_accounting_and_cashier_no_longer_import_output_helpers_from_reports(rel):
    got = _imports_from(rel, "routers.reports")
    moved = {"_xl_style", "_set_row", "_check_export_rate", "_COMPANY",
             "xl_style", "set_row", "check_export_rate"}
    assert not (got & moved), got & moved


def test_accounting_export_takes_part_categories_from_l1():
    assert "PART_CATEGORIES" not in _imports_from("routers/accounting_export.py", "routers.parts")
    assert "PART_CATEGORIES" in _imports_from("routers/accounting_export.py", "helpers.part_catalog")


def test_no_hardcoded_company_name_left():
    for rel in ("routers/reports.py", "routers/accounting_export.py", "modules/netplan/export.py"):
        from core import source_tree
        if not source_tree.module_installed(rel):
            continue                                  # 模組未安裝（選配／反向控制）
        tree = ast.parse((BACKEND / rel).read_text(encoding="utf-8"))
        names = {t.id for n in ast.walk(tree) if isinstance(n, ast.Assign)
                 for t in n.targets if isinstance(t, ast.Name)}
        assert "_COMPANY" not in names, rel


def test_cooldown_is_one_shared_state():
    """報表、出納、T100 共用同一個冷卻（搬移前就是同一個 dict）。"""
    uid = 987_001
    xlsx_out.check_export_rate(uid, "excel")
    with pytest.raises(HTTPException) as ei:
        xlsx_out.check_export_rate(uid, "excel")
    assert ei.value.status_code == 429
    xlsx_out.check_export_rate(uid, "pdf")          # 格式分開計


# 這兩題**在同一個行程依序跑**時，靠 conftest 每題重置 `helpers.xlsx_out._export_times`
# 才會都綠（拿掉 conftest 那一行 ⇒ 第二題 429）。
def test_cooldown_reset_between_tests_first(client):
    xlsx_out.check_export_rate(987_002, "excel")


def test_cooldown_reset_between_tests_second(client):
    xlsx_out.check_export_rate(987_002, "excel")


def _set_company(name):
    from helpers.settings import _set_setting, _get_setting
    prof = _get_setting("company_profile", {}) or {}
    _set_setting("company_profile", {**prof, "companyName": name, "company_name": name, "locations": []})


def test_heading_uses_company_profile(client):
    from helpers.company_identity import company_heading
    _set_company("某某股份有限公司")
    assert company_heading("營運報表") == "某某股份有限公司 — 營運報表"
    assert company_heading("營運報表", sep=" ") == "某某股份有限公司 營運報表"


def test_empty_company_prints_no_dangling_separator(client):
    from helpers.company_identity import company_heading
    from routers import accounting_export as ae
    _set_company("")
    assert company_heading("營運報表") == "營運報表"
    xlsx = ae._build_t100_voucher_excel([], "2026-09-01", "2026-09-30", ae._t100_config(), "2026-09-25 12:00")
    a1 = openpyxl.load_workbook(io.BytesIO(xlsx)).active["A1"].value
    assert a1 == "T100 傳票批次匯出（2026-09-01 ~ 2026-09-30）"


