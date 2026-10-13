# -*- coding: utf-8 -*-
"""U0a 決定：回收桶快照與備份**保留**單位鍵欄位（還原不丟單位歸屬）；只有 HTTP 輸出剝除。

還原要雙向相容（0d M-3）：
 ① 舊快照（沒有 owner_unit_id）→ 新結構（有該欄、DEFAULT 1）：還原後該欄＝預設 1，不報錯。
 ② 新快照（帶 owner_unit_id）→ 沒有該欄的結構（回滾後的舊庫／較舊的庫）：忽略未知欄位，不報錯。
 ③ 新快照 → 新結構：值原樣放回（U1 之後才不會丟單位歸屬）。
四個模組的回收桶轉接器各有自己的『依現有欄位插入』函式，全部要過。
"""
import sqlite3

import pytest

from modules.arap import recycle_adapter as A_ARAP
from modules.case import recycle_adapter as A_CASE
from modules.payroll import recycle_adapter as A_PAY
from modules.subcontract import recycle_adapter as A_SUB

HELPERS = [
    ("arap", A_ARAP.insert_row),
    ("case", A_CASE._insert),
    ("payroll", A_PAY._insert),
    ("subcontract", A_SUB._insert),
]


def _db(with_unit_col: bool):
    c = sqlite3.connect(":memory:")
    c.execute("create table t (id integer primary key autoincrement, no text not null, name text%s)"
              % (", owner_unit_id integer not null default 1" if with_unit_col else ""))
    return c


@pytest.mark.parametrize("name,insert", HELPERS)
def test_old_snapshot_into_new_schema_gets_the_default(name, insert):
    c = _db(True)
    insert(c, "t", {"id": 7, "no": "A", "name": "舊快照"})
    assert c.execute("select owner_unit_id from t where no='A'").fetchone()[0] == 1


@pytest.mark.parametrize("name,insert", HELPERS)
def test_new_snapshot_into_schema_without_the_column_ignores_it(name, insert):
    c = _db(False)
    insert(c, "t", {"id": 7, "no": "A", "name": "新快照", "owner_unit_id": 3, "unit_id": 3, "legal_entity_id": 2})
    row = c.execute("select no, name from t").fetchone()
    assert row == ("A", "新快照")
    assert [r[1] for r in c.execute("pragma table_info(t)")] == ["id", "no", "name"]


@pytest.mark.parametrize("name,insert", HELPERS)
def test_new_snapshot_into_new_schema_keeps_the_unit_assignment(name, insert):
    c = _db(True)
    insert(c, "t", {"id": 7, "no": "A", "name": "新快照", "owner_unit_id": 3})
    assert c.execute("select owner_unit_id from t where no='A'").fetchone()[0] == 3


def test_decision_is_written_down():
    """決定要寫在文件裡（改動這個決定必須先改文件）。"""
    from pathlib import Path
    doc = (Path(__file__).resolve().parents[3] / "docs" / "platform" / "plans" / "U0A-LEAK-DEFENCE-T57.md").read_text(encoding="utf-8")
    assert "回收桶" in doc and "保留" in doc and "還原雙向" in doc
