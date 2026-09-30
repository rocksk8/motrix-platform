"""案件清單「我負責的」（CM7 `_CASE_MINE_SQL`）：顯示名稱空的使用者不可以把業務名稱空的舊案件歸成自己的
（2026-09-29f，D 稽核 RA-S1；與 helpers.row_access 同一條「空對空不算相符」）。

cashier 在 read 範圍看得到全部案件，所以這一條篩選是它唯一的限制：空對空相等時，業務名稱空的舊案件全部會出現在
「我負責的」。參數順序照 `list_quotations` 的 quick["mine"]。
"""
import sqlite3

import pytest

from modules.case.api.quotations import _CASE_MINE_SQL


def _params(user):
    # 與 modules/case/api/quotations.py quick["mine"] 相同
    return [user["id"], user["display_name"], user["id"]] + [user["username"]] * 3


# (id, sales_person_id, sales_person, assigned_user_ids, data_json)
ROWS = [
    (1, None, "", "[]", "{}"),        # 舊案件、業務名稱空  ← 本題主角
    (2, None, None, "[]", "{}"),      # 舊案件、業務名稱 NULL
    (3, None, "Amy", "[]", "{}"),     # 舊案件、業務是 Amy（正對照）
    (4, 7, "", "[]", "{}"),           # 業務 id＝7
    (5, None, "", "[7]", "{}"),       # 舊案件、業務名稱空、7 是協作者 ⇒ 仍算 7 的
    (6, 2, "", "[]", '{"caseRecord":{"roles":{"executor":{"username":"u7"}}}}'),   # 7 是執行者
]


def _ids(user):
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE quotations (id INTEGER PRIMARY KEY, sales_person_id INTEGER, sales_person TEXT, "
              "assigned_user_ids TEXT DEFAULT '[]', data_json TEXT)")
    c.executemany("INSERT INTO quotations VALUES (?,?,?,?,?)", ROWS)
    return {r[0] for r in c.execute(f"SELECT id FROM quotations WHERE {_CASE_MINE_SQL}", _params(user))}


@pytest.mark.parametrize("name", ["", None], ids=["empty", "none"])
def test_blank_display_name_does_not_claim_blank_legacy_cases(name):
    assert _ids({"id": 7, "display_name": name, "username": "u7"}) == {4, 5, 6}


def test_positive_control_legacy_name_still_claims():
    assert _ids({"id": 1, "display_name": "Amy", "username": "amy"}) == {3}
