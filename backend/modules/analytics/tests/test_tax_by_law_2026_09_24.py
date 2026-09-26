"""自 `tests/test_tax_by_law_2026_09_24.py` 拆出（M08 搬遷反向控制：這幾題需要營運分析模組，拿掉模組時一起消失）。"""
import json
from datetime import datetime
import pytest
from tests.test_tax_by_law_2026_09_24 import (  # noqa: E402,F401  含 fixture
    _invoice_rows,
    _paid,
    _quote,
)


def test_legacy_rate_keeps_its_numbers_and_is_flagged(client):
    """舊 3% 單：數字不變（照原本的算法），標「非法定稅率，請會計確認」。"""
    from modules.analytics.api.reports import _round_half_up
    _quote("MQ-L3", 10000, 10300, {"taxRate": 3}, [_paid(10300)])
    [r] = _invoice_rows("MQ-L3")
    old_tax = _round_half_up(10300 - 10300 / 1.05)
    assert (r["amountPretax"], r["taxAmount"], r["amountTotal"]) == (10300 - old_tax, old_tax, 10300)
    assert r["taxType"] == "legacy"
    assert "非法定稅率，請會計確認" in r["taxNote"]


def test_tax_export_workbook_shows_the_tax_type_and_the_legacy_note(client):
    """「稅務匯出該筆標『非法定稅率，請會計確認』」要真的印在給記帳士的檔案上，不只在資料裡。"""
    import io
    import openpyxl
    from modules.analytics.api.reports import _build_tax_export_excel
    _quote("MQ-X1", 10000, 10000, {"taxRate": 0, "taxType": "zero"}, [_paid(10000, "AB00000011")])
    _quote("MQ-X2", 10000, 10300, {"taxRate": 3}, [_paid(10300, "AB00000012")])
    rows = _invoice_rows("MQ-X1") + _invoice_rows("MQ-X2")
    wb = openpyxl.load_workbook(io.BytesIO(_build_tax_export_excel(rows, "測試", "2026-09-24 12:00")))
    text = "\n".join(str(c.value) for row in wb.active.iter_rows() for c in row if c.value is not None)
    assert "稅別" in text and "零稅率" in text
    assert "非法定稅率，請會計確認" in text
