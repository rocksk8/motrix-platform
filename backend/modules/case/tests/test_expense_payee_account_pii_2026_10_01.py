# -*- coding: utf-8 -*-
"""A2 S2：收款人銀行帳號（case_extra_expenses.payee_account）是 F2 個資：一般每日備份拿掉、完整列只進個資份、合回等於原表。
（收款人姓名／銀行名稱不列入：同承攬人員界線。）"""
import json

import archive

ACCOUNT = "9876543210123"
NAME, BANK = "王小明", "玉山銀行"


def _seed(conn):
    cur = conn.execute(
        "INSERT INTO case_extra_expenses(quote_no, category, description, total_cost, status, kind, doc_code, payee_type, payee_name, payee_bank, payee_account, created_at) "
        "VALUES ('', '其他', '差旅', 1200, '已核准', 'travel', 'TE-20261001-0001', 'employee', ?, ?, ?, '2026-10-01T00:00:00')", (NAME, BANK, ACCOUNT))
    conn.commit()
    return cur.lastrowid


def test_payee_account_is_declared_f2_and_label_points_at_the_table():
    spec = archive._F2_FIELDS["案件額外支出"]
    assert spec["table"] == "case_extra_expenses" and spec["columns"] == ("payee_account",)
    assert "FROM case_extra_expenses" in archive._daily_backup_tables()["案件額外支出"]


def test_general_row_drops_the_account_but_keeps_name_and_bank_and_merge_restores(client):
    from db import get_db
    conn = get_db()
    try:
        eid = _seed(conn)
        original = [dict(r) for r in conn.execute(archive._daily_backup_tables()["案件額外支出"]).fetchall()]
    finally:
        conn.close()
    general = [archive._general_row("案件額外支出", dict(r)) for r in original]
    blob = json.dumps(general, ensure_ascii=False)
    assert ACCOUNT not in blob and "payee_account" not in blob                      # 一般份沒有帳號（連欄名都沒有）
    assert NAME in blob and BANK in blob                                             # 姓名／銀行名稱不是 F2（界線同承攬人員）
    merged, missing = archive.merge_general_and_pii("案件額外支出", general, original)
    assert missing == [] and merged == original                                      # 一般＋個資 合回＝原表
    assert [m["payee_account"] for m in merged if m["id"] == eid] == [ACCOUNT]


def test_without_pii_copy_the_general_row_stays_without_the_account(client):
    from db import get_db
    conn = get_db()
    try:
        _seed(conn)
        original = [dict(r) for r in conn.execute(archive._daily_backup_tables()["案件額外支出"]).fetchall()]
    finally:
        conn.close()
    general = [archive._general_row("案件額外支出", dict(r)) for r in original]
    merged, missing = archive.merge_general_and_pii("案件額外支出", general, [])
    assert merged == general and missing and all("payee_account" not in m for m in merged)            # 不猜、不補空值
