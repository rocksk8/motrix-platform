# -*- coding: utf-8 -*-
"""引擎 `_account_for`：事件行指定的 `account_code` 優先於角色設定（IP-109 付款科目、出納指定科目）；不存在／不可過帳 ⇒ NoAccount（不靜默改用角色）。
不依賴案件 migration（G2 驗收檔在沒有 case 0003 的樹上會 skip，這一條在任何樹上都跑）；也是 G5 突變守門的偵測題之一。"""
import pytest

import db
from modules.accounting.ledger import engine as E
from modules.accounting.ledger import roles as ROLES


@pytest.fixture
def conn(client):
    c = db.get_db()
    ROLES.ensure_meta(c)
    ROLES.ensure_default_roles(c)
    c.commit()
    yield c
    c.close()


def test_line_account_code_wins_over_role(conn):
    role_code = ROLES.resolve_role(conn, "AP", on_date="2196-01-10")
    assert role_code == "2171"
    assert E._account_for(conn, {"role": "AP", "side": "D", "amount": 1, "account_code": "1111"}, "2196-01-10") == "1111"
    assert E._account_for(conn, {"role": "AP", "side": "D", "amount": 1}, "2196-01-10") == "2171"


def test_line_account_code_unknown_is_refused_not_replaced_by_role(conn):
    with pytest.raises(E.NoAccount):
        E._account_for(conn, {"role": "AP", "side": "D", "amount": 1, "account_code": "9999"}, "2196-01-10")
