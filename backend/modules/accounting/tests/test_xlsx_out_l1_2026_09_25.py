"""T100 匯出的公司抬頭（M06 搬遷自 tests/ 同名檔）。

2026-09-26 自 `backend/tests/test_xlsx_out_l1_2026_09_25.py` 移入（PLAYBOOK §B-11：拿掉本模組時這些題跟著消失）。
"""
import io
import openpyxl
from tests.test_xlsx_out_l1_2026_09_25 import (  # noqa: F401
    _set_company,
)


def test_empty_company_prints_no_dangling_separator(client):
    from helpers.company_identity import company_heading
    from modules.accounting.api import accounting_export as ae
    _set_company("")
    assert company_heading("營運報表") == "營運報表"
    xlsx = ae._build_t100_voucher_excel([], "2026-09-01", "2026-09-30", ae._t100_config(), "2026-09-25 12:00")
    a1 = openpyxl.load_workbook(io.BytesIO(xlsx)).active["A1"].value
    assert a1 == "T100 傳票批次匯出（2026-09-01 ~ 2026-09-30）"
