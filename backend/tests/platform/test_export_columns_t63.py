# -*- coding: utf-8 -*-
"""T63：案件批次匯出（欄位型）與出納執行紀錄（工作表型）登記為 BP-3 匯出範本。（已寫、閘門期間未跑）

①目錄與原始碼同步 ②驗證與遮蔽優先 ③OFF 路徑（旗標關 ⇒ resolve/disabled_sheets 不動）④不擴大允許清單（BUTTON_EXPORTS）
"""
import re
from pathlib import Path

from helpers import export_templates as ET
from helpers import user_buttons as UB
import modules.arap.api.cashier as C
import modules.case.api.quotations as Q

ROOT = Path(__file__).resolve().parents[3]
CASE_SRC = (ROOT / "backend" / "modules" / "case" / "api" / "quotations.py").read_text(encoding="utf-8")
CASH_SRC = (ROOT / "backend" / "modules" / "arap" / "api" / "cashier.py").read_text(encoding="utf-8")


def test_case_catalog_matches_the_original_header():
    reg = ET.registered()[Q.CASE_BATCH_EXPORT_ID]
    assert [c["label"] for c in reg["columns"]] == ["單號", "客戶", "專案", "狀態", "目前階段", "階段進度", "逾期階段", "業務", "執行負責", "成員", "金額"]
    assert [c["id"] for c in reg["columns"] if c["money"]] == ["amount"]
    assert 'ws.append(["單號", "客戶", "專案", "狀態", "目前階段", "階段進度", "逾期階段", "業務", "執行負責", "成員", "金額"])' in CASE_SRC, "OFF 路徑的原標題列必須還在"
    assert [i for i, _h in Q._CASE_BATCH_COLS] == [c["id"] for c in reg["columns"]]


def test_case_default_template_is_valid_and_masks_money_for_unprivileged():
    d = ET.default_template(Q.CASE_BATCH_EXPORT_ID)
    assert ET.definition_problems(Q.CASE_BATCH_EXPORT_ID, d) == []
    viewer = {"id": 0, "username": "nobody", "role": "viewer", "modules": ""}
    cols, omitted = ET.effective_columns(Q.CASE_BATCH_EXPORT_ID, d, viewer)
    assert "amount" not in [c["id"] for c in cols] and [o["id"] for o in omitted] == ["amount"]


def test_case_template_rejects_unknown_column_and_formula_label():
    bad = {"version": 1, "format": "xlsx", "columns": [{"id": "cost", "label": "成本"}]}
    assert ET.definition_problems(Q.CASE_BATCH_EXPORT_ID, bad)
    bad2 = {"version": 1, "format": "xlsx", "columns": [{"id": "quote_no", "label": "=SUM(A1)"}]}
    assert ET.definition_problems(Q.CASE_BATCH_EXPORT_ID, bad2)


def test_cashier_catalog_matches_the_workbook_sources():
    reg = ET.registered()[C.CASHIER_EXPORT_ID]
    assert [x["id"] for x in reg["sheets"]] == [s for s, _t in C._CASHIER_SHEETS] and reg["columns"] == []
    assert [x["id"] for x in reg["sheets"] if x["required"]] == ["outgoing"] and all(x["money"] for x in reg["sheets"])
    titles = re.findall(r'create_sheet\("([^"]+)"\)', CASH_SRC)
    assert titles == [t for _s, t in C._CASHIER_SHEETS], "活頁簿建立順序必須等於目錄順序"


def test_cashier_sheet_validation():
    eid = C.CASHIER_EXPORT_ID
    ok = {"version": 1, "format": "xlsx", "sheets": ["outgoing", "incoming"]}
    assert ET.definition_problems(eid, ok) == []
    assert ET.definition_problems(eid, {"version": 1, "format": "xlsx", "sheets": ["incoming"]}), "必選不能拿掉"
    assert ET.definition_problems(eid, {"version": 1, "format": "xlsx", "sheets": ["incoming", "outgoing"]}), "順序固定"
    assert ET.definition_problems(eid, {"version": 1, "format": "xlsx", "sheets": ["outgoing"], "footer": {"text": "內部資料"}}), "工作表型不收頁尾"


def test_off_path_is_untouched_when_flag_is_off(monkeypatch):
    monkeypatch.setattr(ET, "enabled", lambda conn=None: False)
    monkeypatch.setattr(ET, "enabled_strict", lambda conn=None: False)      # disabled_sheets 走嚴格讀取
    assert ET.resolve(Q.CASE_BATCH_EXPORT_ID) is None
    assert ET.disabled_sheets(C.CASHIER_EXPORT_ID) == []


def test_cashier_fail_closed_when_settings_unreadable(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("settings unreadable")
    monkeypatch.setattr(ET, "disabled_sheets", boom)
    assert C._cashier_off_sheets() == ["payreq", "incoming", "bonus"]


def test_audit_and_rate_limit_stay_before_the_template_hook():
    assert '@export_logged("xlsx", "arap", "cashier-history")' in CASH_SRC and '@export_logged("xlsx", "case", "case-batch")' in CASE_SRC
    i = CASH_SRC.index("def export_execution_history")
    assert CASH_SRC.index("_require_view_access(user)", i) < CASH_SRC.index("_cashier_off_sheets()", i)
    assert CASH_SRC.index("check_export_rate(user", i) < CASH_SRC.index("_cashier_off_sheets()", i)


def test_button_exports_allowlist_not_widened():
    assert set(UB.BUTTON_EXPORTS) == {"subcontract:roster"}
