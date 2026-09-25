"""自 `tests/test_company_contact_a8c_2026_09_25.py` 拆出的營運報表那一個參數（M08 搬遷反向控制）。"""
from tests.test_company_contact_a8c_2026_09_25 import test_no_hardcoded_company_contacts_left as _check


def test_no_hardcoded_company_contacts_left_in_reports():
    _check("modules/analytics/api/reports.py")
