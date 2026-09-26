"""自 `tests/test_case_roles_username_2026_09_24.py` 拆出（M08 搬遷反向控制：這幾題需要營運分析模組，拿掉模組時一起消失）。"""
import json
import pytest


def test_reports_sales_owner_uses_username():
    from modules.analytics.api import reports as rp
    users = {1: {"displayName": "同名", "username": "a"}, 2: {"displayName": "同名", "username": "b"}}
    name_index = rp._build_name_index(users)
    row = {"sales_person_id": None, "sales_person": ""}

    class R(dict):
        def keys(self):
            return super().keys()
    key, label = rp._case_sales_owner({"roles": {"sales": {"username": "b", "display": "同名"}}}, R(row),
                                      name_index, users)
    assert key == ("id", 2) and label == "同名"
