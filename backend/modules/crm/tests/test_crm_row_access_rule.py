"""業務開發的 row_access 規則：正式登錄的＝test_row_access_2026_09_25 驗過等價的那一份。

（2026-09-26 自 tests/test_row_access_callers_2026_09_25.py 拆出：需要本模組在，隨模組搬走。）
"""
import dataclasses

from tests.test_row_access_2026_09_25 import DEV


def test_registered_dev_case_rule_is_the_verified_one():
    from modules.crm.api import DEV_CASE_ACCESS
    from helpers import row_access as ra
    assert dataclasses.replace(DEV_CASE_ACCESS, deny_message="") == dataclasses.replace(DEV, deny_message="")
    assert ra._REGISTRY["dev_case"] is DEV_CASE_ACCESS
