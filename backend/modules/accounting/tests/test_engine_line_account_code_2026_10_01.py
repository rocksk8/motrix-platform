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


def test_collect_applies_category_map_through_the_contract(conn, monkeypatch):
    """契約收集（contract.collect）要把類別對應套到提供者事件上：類別行 meal→6134，來源模組只送類別代碼。
    （G5：突變『收集不呼叫 _apply_category_map』在沒有案件 0003 欄位的樹上只有這題抓得到）"""
    from core import registry
    from modules.accounting.ledger import category_map as CM
    from modules.accounting.ledger import contract as C
    CM.upsert_category(conn, "meal", "餐費", "taxable", 1)
    CM.upsert_map(conn, "meal", account_code="6134")
    conn.commit()
    monkeypatch.setattr(registry, "_LEGACY_PROVIDERS", {})
    monkeypatch.setattr(registry, "_LOADED", {})
    ev = {"source_type": "case_extra_expense", "source_key": "k1", "event_code": "E11", "event_date": "2196-01-10", "doc_no": "D1",
          "lines": [{"role": "EXP_OTHER", "side": "D", "amount": 600, "category": "meal"}, {"role": "AP", "side": "C", "amount": 600}]}
    registry._LEGACY_PROVIDERS[(C.CAPABILITY, "case")] = lambda s, e, changed_since="": {"events": [ev]}
    r = C.collect("2196-01-01", "2196-01-31", conn=conn)
    assert not r["invalid"] and len(r["events"]) == 1
    debit = [ln for ln in r["events"][0]["lines"] if ln["side"] == "D"]
    assert [(ln.get("account_code"), ln["amount"]) for ln in debit] == [("6134", 600)]
