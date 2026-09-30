# -*- coding: utf-8 -*-
"""總帳 B1 · 報表列定義（gl_fs_lines）與現金流量分類（cashflow_class）（proposal-gl/04-reports.md §3、§5）。

守門的對象是「設定完整性」：任何可過帳科目沒有報表列、報表列不存在、資產負債科目沒有現金流量分類，
B2～B4 的報表都會悄悄漏算——所以每一項都要有「故意弄壞⇒偵測得到」的反向控制。
"""
import importlib

import pytest

import db
from modules.accounting.ledger import fs_lines as F
from modules.accounting.ledger import roles as ROLES


@pytest.fixture
def conn(client):
    c = db.get_db()
    ROLES.ensure_meta(c)
    c.commit()
    yield c
    c.close()


def _login(client, make_user, username, role="superadmin", modules=("finance",)):
    u, p = make_user(username=username, role=role, modules=list(modules))
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


# ── 報表列 ───────────────────────────────────────────────────────────────

def test_fs_lines_are_seeded_once_and_cover_bs_and_is(conn):
    lines = {r["code"]: r for r in F.list_fs_lines(conn)}
    assert len(lines) == len(F.seed_rows()) and {r["statement"] for r in lines.values()} == {"BS", "IS"}
    assert F.ensure_fs_lines(conn) == 0                                   # 冪等
    assert lines["IS_GP"]["kind"] == "computed" and lines["IS_REV"]["kind"] == "line"
    assert lines["BS_CL_AP"]["side"] == "C" and lines["BS_CA_INV"]["side"] == "D"
    assert len({c for c, *_ in F.seed_rows()}) == len(F.seed_rows()), "報表列代碼不可重複"


def test_every_fs_line_used_by_an_account_exists(conn):
    assert F.unknown_fs_lines(conn) == []
    assert ROLES.accounts_without_fs_line(conn) == []


def test_reverse_control_unknown_and_inactive_lines_are_detected(conn):
    conn.execute("UPDATE gl_account_meta SET fs_line='BS_NOPE' WHERE code='1112'")
    conn.commit()
    assert F.unknown_fs_lines(conn) == ["BS_NOPE"]
    conn.execute("UPDATE gl_account_meta SET fs_line='BS_CA_CASH' WHERE code='1112'")
    conn.execute("UPDATE gl_fs_lines SET is_active=0 WHERE code='BS_CA_CASH'")
    conn.commit()
    assert F.inactive_lines_in_use(conn) == ["BS_CA_CASH"]
    conn.execute("UPDATE gl_fs_lines SET is_active=1 WHERE code='BS_CA_CASH'")
    conn.commit()
    assert F.inactive_lines_in_use(conn) == []


def test_ensure_never_overwrites_accountant_edits(conn):
    conn.execute("UPDATE gl_fs_lines SET label='客製名稱', sort=999, is_active=0 WHERE code='BS_CA_INV'")
    conn.commit()
    assert F.ensure_fs_lines(conn) == 0
    r = conn.execute("SELECT label, sort, is_active FROM gl_fs_lines WHERE code='BS_CA_INV'").fetchone()
    assert tuple(r) == ("客製名稱", 999, 0)
    conn.execute("UPDATE gl_fs_lines SET is_active=1 WHERE code='BS_CA_INV'")
    conn.commit()


# ── 現金流量分類 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("code,cf", [
    ("1113", "cash"), ("1111", "cash"), ("1191", "operating"), ("1231", "operating"), ("1268", "operating"),
    ("1432", "operating"), ("1192", "operating"), ("1431", "investing"), ("1531", "investing"), ("1584", "financing"),
    ("2171", "operating"), ("2204", "operating"), ("2112", "financing"), ("2199", "investing"), ("2201", "financing"),
    ("2231", "financing"), ("3111", "financing"), ("3351", "financing"), ("3511", "financing"), ("3411", "operating"),
])
def test_default_cashflow_class(conn, code, cf):
    got = conn.execute("SELECT cashflow_class FROM gl_account_meta WHERE code=?", (code,)).fetchone()[0]
    assert got == cf, "%s 預期 %s 實際 %s" % (code, cf, got)


def test_every_postable_balance_sheet_account_is_classified_and_pl_is_not(conn):
    assert F.unclassified_cashflow(conn) == []
    pl = conn.execute("SELECT COUNT(*) FROM gl_account_meta WHERE acct_type NOT IN ('asset','liability','equity') AND cashflow_class<>''").fetchone()[0]
    assert pl == 0, "損益科目不分類（淨利整體歸營業活動）"
    assert {r[0] for r in conn.execute("SELECT DISTINCT cashflow_class FROM gl_account_meta WHERE cashflow_class<>''")} <= set(F.CASHFLOW_CLASSES)


def test_cash_class_is_exactly_the_cash_group(conn):
    cash = {r[0] for r in conn.execute("SELECT code FROM gl_account_meta WHERE cashflow_class='cash'")}
    assert cash == {"111", "1111", "1112", "1113", "1114", "1115"}, cash


def test_reverse_control_unclassified_account_is_detected(conn):
    conn.execute("UPDATE gl_account_meta SET cashflow_class='' WHERE code='1191'")
    conn.commit()
    assert F.unclassified_cashflow(conn) == ["1191"]
    ROLES.ensure_meta(conn)                                                # 只補空的，補回預設
    conn.commit()
    assert F.unclassified_cashflow(conn) == []


def test_custom_child_inherits_cashflow_class_and_hand_edits_survive(conn):
    conn.execute("INSERT INTO account_items(code, level, name, parent_code, source) VALUES ('1113-77', 5, '測試銀行', '1113', 'custom')")
    ROLES.ensure_meta(conn)
    conn.commit()
    assert conn.execute("SELECT cashflow_class FROM gl_account_meta WHERE code='1113-77'").fetchone()[0] == "cash"
    conn.execute("UPDATE gl_account_meta SET cashflow_class='investing' WHERE code='1191'")
    conn.commit()
    ROLES.ensure_meta(conn)
    assert conn.execute("SELECT cashflow_class FROM gl_account_meta WHERE code='1191'").fetchone()[0] == "investing"
    conn.execute("UPDATE gl_account_meta SET cashflow_class='operating' WHERE code='1191'")
    conn.commit()


def test_migration_is_idempotent_and_has_cashflow_column(conn):
    m = importlib.import_module("modules.accounting.migrations.0001_ledger_base")
    assert m.up(conn) is None and m.up(conn) is None
    assert "cashflow_class" in {r[1] for r in conn.execute("PRAGMA table_info(gl_account_meta)")}


# ── API ─────────────────────────────────────────────────────────────────

def test_api_setup_check_and_accounts_payload(client, make_user, conn):
    hdr = _login(client, make_user, "gl_b1_a")
    r = client.get("/api/ledger/setup-check", headers=hdr)
    assert r.status_code == 200 and r.json()["ok"] is True, r.text
    # 一個推不出預設的新科目（不在任何已知群組下）：報表歸屬與現金流量分類都缺 ⇒ setup-check 必須紅
    conn.execute("INSERT INTO account_items(code, level, name, parent_code, source) VALUES ('1999', 4, '測試無群組科目', NULL, 'statutory')")
    conn.commit()
    r = client.get("/api/ledger/setup-check", headers=hdr).json()
    assert r["ok"] is False and r["unclassified_cashflow"] == ["1999"] and r["missing_fs_line"] == ["1999"], r
    accs = client.get("/api/ledger/accounts?q=1999", headers=hdr).json()
    assert accs["unclassified_cashflow"] == ["1999"] and "cashflow_class" in accs["accounts"][0]
    # 補上歸屬與分類後恢復綠燈
    assert client.patch("/api/ledger/accounts/1999", headers=hdr, json={"fs_line": "BS_CA_OTHER", "cashflow_class": "operating"}).status_code == 200
    assert client.get("/api/ledger/setup-check", headers=hdr).json()["ok"] is True


def test_api_patch_account_fs_line_and_cashflow_validation(client, make_user, conn):
    hdr = _login(client, make_user, "gl_b1_b")
    p = lambda code, body: client.patch("/api/ledger/accounts/" + code, headers=hdr, json=body)
    assert p("1113", {"fs_line": "BS_NOPE"}).status_code == 400
    assert p("1113", {"cashflow_class": "weird"}).status_code == 400
    assert p("4111", {"cashflow_class": "operating"}).status_code == 400          # 損益科目不分類
    assert p("1113", {"fs_line": "BS_CA_CASH", "cashflow_class": "cash"}).status_code == 200
    assert p("1191", {"cashflow_class": "operating"}).status_code == 200


def test_api_fs_lines_edit_rules_and_permissions(client, make_user, conn):
    hdr = _login(client, make_user, "gl_b1_c")
    cash = _login(client, make_user, "gl_b1_cash", role="staff", modules=("cashier",))
    none = _login(client, make_user, "gl_b1_none", role="staff", modules=())
    assert client.get("/api/ledger/fs-lines", headers=none).status_code == 403
    r = client.get("/api/ledger/fs-lines", headers=cash)
    assert r.status_code == 200 and {x["code"] for x in r.json()["lines"]} >= {"BS_CA_CASH", "IS_NI"}
    assert client.patch("/api/ledger/fs-lines/BS_CA_INV", headers=cash, json={"label": "x"}).status_code == 403   # 只有 finance 可改
    assert client.patch("/api/ledger/fs-lines/BS_CA_INV", headers=hdr, json={"label": "存貨（管理用）", "sort": "155"}).status_code == 200
    assert conn.execute("SELECT label, sort FROM gl_fs_lines WHERE code='BS_CA_INV'").fetchone()[1] == 155
    assert client.patch("/api/ledger/fs-lines/BS_CA_INV", headers=hdr, json={"label": "  "}).status_code == 400
    assert client.patch("/api/ledger/fs-lines/BS_CA_INV", headers=hdr, json={"sort": "abc"}).status_code == 400
    assert client.patch("/api/ledger/fs-lines/NOPE", headers=hdr, json={"label": "x"}).status_code == 404
    assert client.patch("/api/ledger/fs-lines/BS_CA_INV", headers=hdr, json={}).status_code == 400
    # 停用仍有科目歸屬的列 ⇒ 409 並說明；停用沒有科目的列（例如計算列）可以
    r = client.patch("/api/ledger/fs-lines/BS_CA_INV", headers=hdr, json={"is_active": False})
    assert r.status_code == 409 and "漏算" in r.json()["detail"]
    assert client.patch("/api/ledger/fs-lines/IS_TCI", headers=hdr, json={"is_active": False}).status_code == 200
