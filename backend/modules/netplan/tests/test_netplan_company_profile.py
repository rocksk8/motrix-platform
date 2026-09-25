"""網路規劃書使用公司資料（2026-09-26 自 tests/test_company_contact_a8c／test_xlsx_out_l1 移入本模組：拿掉 M10 時一起消失）。"""
import io

import openpyxl

from tests.test_xlsx_out_l1_2026_09_25 import _set_company  # noqa: F401


def test_empty_profile_writes_none_not_empty_string(client):
    """openpyxl 的空字串會產生非法 inlineStr（Excel 開檔要修復）⇒ 空白一律寫 None。"""
    from helpers.settings import _set_setting, _get_setting
    import modules.netplan.export as npe
    prof = _get_setting("company_profile", {}) or {}
    _set_setting("company_profile", {**prof, "companyName": "", "companyNameEn": "", "taxId": "",
                                      "phone": "", "email": "", "locations": []})
    wb = openpyxl.load_workbook(io.BytesIO(npe.build_plan_excel({"name": "x", "data": {}})))
    assert wb["封面"]["A1"].value is None and wb["封面"]["A2"].value is None


def test_network_plan_cover_uses_company_profile(client):
    import modules.netplan.export as npe
    _set_company("網規測試公司")
    wb = openpyxl.load_workbook(io.BytesIO(npe.build_plan_excel({"name": "x", "data": {}})))
    assert wb["封面"]["A1"].value == "網規測試公司"
