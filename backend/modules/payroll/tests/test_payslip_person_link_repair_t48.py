# -*- coding: utf-8 -*-
"""第 48 班 person-link 再檢查（1d re-check）的補測：
- migration 6：修復早期版本 migration 5 的汙染（contractor_match='unconfirmed' 的 contractor_id 其實是推測 ⇒ 搬回 contractor_guess_id）；冪等；全新庫不動
- 缺 quote_no 的派發：byPerson「同案」不可退化成「所有沒有案號的派發」
"""
import importlib
import json
import sqlite3

import pytest

from core import source_tree
from modules.payroll.tests.test_payslip_person_link_t48 import (  # noqa: F401  (fixtures/helpers)
    _archive_tmp, _dispatch, _link, _old_slip, _person, _q, _staff, _su, _x)

pytestmark = pytest.mark.skipif(not source_tree.module_installed("modules/subcontract/"), reason="派發在外包工班（M04）")
_MAKE_USER_DEFAULT_ROLE = "superadmin"


def _early_shaped():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE payslips (id INTEGER PRIMARY KEY, slip_no TEXT, contractor_id INTEGER, contractor_name TEXT, status TEXT,"
              " contractor_match TEXT NOT NULL DEFAULT '')")
    rows = [("PS-1", 11, "甲", "已核准", "unconfirmed"),     # 早期版本把推測寫進了 contractor_id
            ("PS-2", 12, "乙", "已付款", "unconfirmed"),
            ("PS-3", 13, "丙", "已核准", ""),                # 人工確認過 / 新單：不動
            ("PS-4", None, "丁", "已核准", "")]
    c.executemany("INSERT INTO payslips (slip_no, contractor_id, contractor_name, status, contractor_match) VALUES (?,?,?,?,?)", rows)
    return c


def test_migration6_moves_early_version_guesses_out_of_contractor_id_and_is_idempotent():
    m6 = importlib.import_module("modules.payroll.migrations.0006_payslip_person_link_repair")
    c = _early_shaped()
    assert m6.up(c) is None
    got = {r[0]: (r[1], r[2], r[3]) for r in c.execute("SELECT slip_no, contractor_id, contractor_guess_id, contractor_match FROM payslips")}
    assert got["PS-1"] == (None, 11, "") and got["PS-2"] == (None, 12, "")
    assert got["PS-3"] == (13, None, "") and got["PS-4"] == (None, None, "")
    snap = list(c.execute("SELECT * FROM payslips ORDER BY id"))
    assert m6.up(c) is None and snap == list(c.execute("SELECT * FROM payslips ORDER BY id"))        # 冪等


def test_migration6_on_a_fresh_db_only_ensures_the_column():
    m6 = importlib.import_module("modules.payroll.migrations.0006_payslip_person_link_repair")
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE payslips (id INTEGER PRIMARY KEY, slip_no TEXT, contractor_id INTEGER, contractor_name TEXT, status TEXT)")
    c.execute("INSERT INTO payslips (slip_no, contractor_id, contractor_name, status) VALUES ('PS-9', 5, '戊', '已核準')")
    assert m6.up(c) is None
    assert {r[1] for r in c.execute("PRAGMA table_info(payslips)")} >= {"contractor_guess_id"}
    assert list(c.execute("SELECT contractor_id, contractor_guess_id FROM payslips")) == [(5, None)]


def test_by_person_for_a_dispatch_without_quote_no_does_not_match_all_caseless_dispatches(client, make_user):
    sa = _su(client, make_user, "pp_sa")
    cid = _person("無案號甲")
    did = _dispatch(client, sa, [{"id": cid, "name": "無案號甲"}])
    other_caseless = _dispatch(client, sa, [{"id": cid, "name": "無案號甲"}])
    _x("UPDATE contractor_dispatches SET quote_no='' WHERE id IN (?,?)", (did, other_caseless))
    _old_slip("PS-203106-801", "無案號甲", cid)
    _link("PS-203106-801", other_caseless)                  # 只連到『另一張』也沒案號的派發 ⇒ 不可因為都沒案號就被當成同案
    body = client.get("/api/contractor-dispatches/%s/payslip-links" % did, headers=sa).json()
    assert body["byPerson"] == [], body
