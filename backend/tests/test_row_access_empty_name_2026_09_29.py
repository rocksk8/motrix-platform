"""row_access：顯示名稱為空的使用者，不可以因為「舊資料比顯示名稱」看到業務名稱為空的舊案件（2026-09-29f）。

舊規則：`sales_person_id` 為 NULL 的舊案件改比 `sales_person == user.display_name`。兩邊都是空字串時
比對成立 ⇒ 顯示名稱空的使用者看得到所有業務名稱空的舊案件（單筆 visible 與 SQL filter_sql 都是）。
修正：顯示名稱為空字串／None 一律不算相符（null 不等於 0）；其餘規則不放寬也不收緊。

用正式登錄的 `case` 規則（`helpers.case_access` 匯入即登錄），不另造測試用規則——修的是那一份宣告推導出的兩種形式。
"""
import sqlite3

import pytest
from fastapi import HTTPException

import helpers.case_access  # noqa: F401  匯入即登錄 row_access "case"
from helpers import row_access as ra

EMPTY = {"id": 7, "display_name": "", "role": "sales", "modules": "[]"}
NONE = {"id": 8, "display_name": None, "role": "sales", "modules": "[]"}
AMY = {"id": 1, "display_name": "Amy", "role": "sales", "modules": "[]"}

# (id, sales_person_id, sales_person, assigned_user_ids)
ROWS = [
    (1, None, "", "[]"),        # 舊案件、業務名稱空字串  ← 本題主角
    (2, None, None, "[]"),      # 舊案件、業務名稱 NULL
    (3, None, "Amy", "[]"),     # 舊案件、業務是 Amy（正對照：舊資料名稱比對照舊有效）
    (4, 7, "", "[]"),           # 新案件、業務 id＝7（顯示名稱空的人自己的案件，不可以被收緊）
    (5, 8, None, "[]"),         # 新案件、業務 id＝8
    (6, 2, "", "[7,8]"),        # 別人的案件、7／8 是協作者（不可以被收緊）
    (7, 2, "", "[]"),           # 別人的案件、業務名稱空字串但有 id ⇒ 本來就看不到
    (8, None, "", "[7]"),       # 舊案件、業務名稱空、7 是協作者 ⇒ 7 仍看得到（D 稽核 RA-M1：不可連協作者一起扣掉）
]


def _db():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE quotations (id INTEGER PRIMARY KEY, sales_person_id INTEGER, sales_person TEXT, "
              "assigned_user_ids TEXT DEFAULT '[]')")
    c.executemany("INSERT INTO quotations VALUES (?,?,?,?)", ROWS)
    return c


def _py(conn, user, scope):
    return {r["id"] for r in conn.execute("SELECT * FROM quotations") if ra.visible("case", user, r, scope)}


def _sql(conn, user, scope):
    frag, params = ra.filter_sql("case", user, prefix="q.", scope=scope)
    return {r["id"] for r in conn.execute(f"SELECT q.id FROM quotations q WHERE 1=1{frag}", params)}


@pytest.mark.parametrize("scope", ra.SCOPES)
@pytest.mark.parametrize("user", [EMPTY, NONE], ids=["empty", "none"])
def test_blank_display_name_does_not_see_blank_legacy_cases(user, scope):
    conn = _db()
    expected = {4, 6, 8} if user is EMPTY else {5, 6}          # 只有自己的（id 相符）與被指派的
    assert _py(conn, user, scope) == expected
    assert _sql(conn, user, scope) == expected


def test_require_blocks_blank_legacy_case():
    row = {"sales_person_id": None, "sales_person": "", "assigned_user_ids": "[]"}
    for user in (EMPTY, NONE):
        with pytest.raises(HTTPException) as e:
            ra.require("case", user, row, scope="owner")
        assert e.value.status_code == 403


@pytest.mark.parametrize("scope", ra.SCOPES)
def test_positive_control_legacy_name_match_still_works(scope):
    """不收緊：顯示名稱有值時，舊資料比名稱照舊成立（兩種形式）。"""
    conn = _db()
    assert _py(conn, AMY, scope) == {3}
    assert _sql(conn, AMY, scope) == {3}


def test_bypass_rules_unchanged():
    """不放寬也不收緊：admin 直通、cashier 在 read 直通、在 owner 只看自己的——與原本相同。"""
    conn = _db()
    admin = dict(EMPTY, role="admin")
    cashier = dict(EMPTY, modules='["cashier"]')
    everything = {r[0] for r in ROWS}
    assert _py(conn, admin, "owner") == _sql(conn, admin, "owner") == everything
    assert _py(conn, cashier, "read") == _sql(conn, cashier, "read") == everything
    assert _py(conn, cashier, "owner") == _sql(conn, cashier, "owner") == {4, 6, 8}
