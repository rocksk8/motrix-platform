# -*- coding: utf-8 -*-
"""T65 F7 S1b：真實出口證明——直接呼叫材料申請的兩支讀取端點（get_material_orders／list_case_changes），
角色 × finance_via_effective（off／shadow／on）× 授予／扣項，輸出對照**獨立的舊規則表**（test_field_policy_t65._expected，寫死在測試裡）：
表說可見 ⇒ 金額欄位都在且等於原值；表說不可見 ⇒ 金額欄位全拿掉、`moneyMasked`。不經 field_policy 的任何函式判斷期望值。"""
import json
import sqlite3

import pytest

from modules.case import material_change as MC
from modules.case.api import material_changes as CH
from modules.case.api import material_orders as MO
from tests.platform.test_field_policy_t65 import GRANTS, MODES, ROLES, _expected, _user, finance_env  # noqa: F401

ORDER = {"itemId": "I1", "itemName": "線材", "unitPrice": 10, "totalPrice": 20, "paidAmount": 5, "totalAmount": 20, "quantity": 2}


class _Conn:
    def __init__(self):
        self.c = sqlite3.connect(":memory:")
        self.c.row_factory = sqlite3.Row
        self.c.execute("CREATE TABLE quotations (quote_no TEXT, data_json TEXT, sales_person_id INT, sales_person TEXT, assigned_user_ids TEXT)")
        self.c.execute("INSERT INTO quotations VALUES ('Q1', ?, 1, 'x', '[]')", (json.dumps({"caseRecord": {"materialOrders": [dict(ORDER)]}}),))

    def execute(self, *a, **k):
        return self.c.execute(*a, **k)

    def close(self):
        pass


def _has_money(v) -> bool:
    if isinstance(v, dict):
        return any(k in ("unitPrice", "totalPrice", "amount", "paidAmount", "totalAmount") or _has_money(x) for k, x in v.items())
    if isinstance(v, list):
        return any(_has_money(x) for x in v)
    return False


def test_get_material_orders_matches_the_old_table_for_every_role_mode_and_grant(finance_env, monkeypatch):
    seen = {True: 0, False: 0}
    for mode in MODES:
        finance_env["mode"] = mode
        for role in ROLES:
            for uid in GRANTS:
                u = _user(role, "[]", uid)
                monkeypatch.setattr(MO, "_require_user", lambda a, _u=u: _u)
                monkeypatch.setattr(MO, "get_db", lambda: _Conn())
                monkeypatch.setattr(MO, "require_case_money", lambda *a, **k: None)
                out = MO.get_material_orders("Q1", "tok")
                want = _expected("material_money", role, mode, uid)
                seen[want] += 1
                if want:
                    assert out["materialOrders"][0]["unitPrice"] == 10 and out["materialOrders"][0]["totalPrice"] == 20 and not out.get("moneyMasked")
                else:
                    assert out["moneyMasked"] is True and not _has_money(out["materialOrders"]) and out["materialOrders"][0]["itemName"] == "線材"
    assert seen[True] and seen[False]                       # 兩種結果都真的測到（不是空轉）


def _change_row():
    return {"id": 1, "doc_code": "MC-1", "quote_no": "Q1", "item_id": "I1", "status": "草稿", "base_version": 1, "reason": "r",
            "approval_json": "{}", "created_by": "a", "created_at": "t", "submitted_at": "", "approved_at": "", "applied_at": "",
            "diff_json": json.dumps([{"field": "totalPrice", "old": 20, "new": 30, "money": True}, {"field": "notes", "old": "a", "new": "b"}]),
            "proposal_json": json.dumps({"after": {"unitPrice": 10, "totalPrice": 30, "notes": "b"}}),
            "base_json": json.dumps({"unitPrice": 10, "totalPrice": 20})}


def test_list_case_changes_matches_the_old_table_for_every_role_mode_and_grant(finance_env, monkeypatch):
    seen = {True: 0, False: 0}
    for mode in MODES:
        finance_env["mode"] = mode
        for role in ROLES:
            for uid in GRANTS:
                u = _user(role, "[]", uid)
                monkeypatch.setattr(CH, "_require_user", lambda a, _u=u: _u)
                monkeypatch.setattr(CH, "get_db", lambda: _Conn())
                monkeypatch.setattr(CH, "_load_case", lambda conn, no: {"data_json": json.dumps({"caseRecord": {"materialOrders": [dict(ORDER)]}})})
                monkeypatch.setattr(CH, "require_case", lambda *a, **k: None)
                monkeypatch.setattr(MC, "list_for_case", lambda conn, no: [_change_row()])
                out = CH.list_case_changes("Q1", "tok")["changes"][0]
                want = _expected("material_money", role, mode, uid)
                seen[want] += 1
                if want:
                    assert out["base"] == {"unitPrice": 10, "totalPrice": 20} and out["diff"][0]["new"] == 30
                else:
                    assert not _has_money(out["base"]) and not _has_money(out["proposal"]) and out["diff"][0].get("hidden") is True and out["diff"][0]["new"] is None
                assert out["itemName"] == "線材"
    assert seen[True] and seen[False]


def test_positive_control_a_leaking_flag_turns_the_real_exit_proof_red(finance_env, monkeypatch):
    """出口的旗標被改成永遠放行 ⇒ 對照舊規則表的證明必須變紅（證明這支測試不是空轉）。"""
    monkeypatch.setattr(MO, "tier_allowed", lambda ceiling, user: True)
    with pytest.raises((AssertionError, KeyError)):
        test_get_material_orders_matches_the_old_table_for_every_role_mode_and_grant(finance_env, monkeypatch)
