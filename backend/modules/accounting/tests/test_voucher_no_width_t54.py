# -*- coding: utf-8 -*-
"""第 54 班：傳票每日流水第 1000 張的撞號 bug。

`next_voucher_no` 產出 `"%s-%03d" % (day, biggest + 1)`，第 1000 張會自然變成 `20261010-1000`；
舊的讀取正則 `^(\\d{8})-(\\d{3})…$` 認不得 4 位流水 ⇒ `biggest` 卡在 999 ⇒ 下一次又產出 `-1000` ⇒ 唯一索引撞號。
修正：正則 `\\d{3,}`（寬度三位起跳不變，是否改長度的問題交給使用者／T100）＋所有『依單號排序』的讀取改用流水整數。"""
import re
import sqlite3
from pathlib import Path

import pytest

from modules.accounting import voucher as V
from helpers import gl_status

DAY = "2026-10-10"


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE vouchers_all (voucher_no TEXT, voucher_date TEXT)")
    yield c
    c.close()


def _add(c, *nos):
    for n in nos:
        c.execute("INSERT INTO vouchers_all VALUES (?, ?)", (n, DAY))


def test_number_after_999_is_1000_and_then_1001_without_duplicates(conn):
    _add(conn, "20261010-%03d" % 999)
    seen = set()
    for _ in range(5):
        no = V.next_voucher_no(conn, DAY)
        assert no not in seen, "撞號：%s" % no
        seen.add(no)
        _add(conn, no)
    assert sorted(seen) == ["20261010-1000", "20261010-1001", "20261010-1002", "20261010-1003", "20261010-1004"]


def test_the_pre_fix_regex_was_blind_to_four_digits_and_the_new_one_is_not():
    old = re.compile(r"^(\d{8})-(\d{3})(?:-R\d+)?$")
    assert old.match("20261010-999") and not old.match("20261010-1000"), "舊正則的盲點（這題證明 bug 真的存在）"
    for no in ("20261010-999", "20261010-1000", "20261010-12345", "20261010-1000-R1", "20261010-007-R12"):
        assert V._DAILY_NO_RE.match(no), no
    for bad in ("20261010-99", "2026101-001", "20261010-1000-X1", "20261010-100a", "MQ-202610-001"):
        assert not V._DAILY_NO_RE.match(bad), bad


def test_mixed_widths_revisions_and_other_days_are_all_read_correctly(conn):
    _add(conn, "20261010-001", "20261010-1000", "20261010-1000-R1", "20261010-999-R2", "20261011-5000", "20261009-3000")
    assert V.next_voucher_no(conn, DAY) == "20261010-1001", "取當天最大流水（含 -R 修訂版與 4 位），別天不干擾"
    assert V.next_voucher_no(conn, "2026-10-11") == "20261011-5001"
    assert V.next_voucher_no(conn, "2026-10-12") == "20261012-001", "沒有單號的日子仍從 001 起（三位寬度不變）"
    assert V.next_voucher_no(conn, "2026-10-09") == "20261009-3001"


def test_width_stays_three_digits_below_1000(conn):
    for i in (1, 9, 10, 99, 100, 998):
        c = sqlite3.connect(":memory:")
        c.execute("CREATE TABLE vouchers_all (voucher_no TEXT, voucher_date TEXT)")
        c.execute("INSERT INTO vouchers_all VALUES (?, ?)", ("20261010-%03d" % i, DAY))
        assert V.next_voucher_no(c, DAY) == "20261010-%03d" % (i + 1)
        c.close()


def test_revision_helpers_work_on_four_digit_numbers():
    assert V.next_revision_no("20261010-1000") == "20261010-1000-R1"
    assert V.next_revision_no("20261010-1000-R1") == "20261010-1000-R2"
    assert V.revision_of("20261010-1000-R3") == 3 and V.base_no("20261010-1000-R3") == "20261010-1000"


def test_order_by_uses_the_numeric_sequence_not_the_string(conn):
    nos = ["20261010-999", "20261010-1000", "20261010-1001", "20261010-998", "20261010-1000-R1", "20261010-100", "20261010-1000-R2", "20261010-10000"]
    _add(conn, *nos)
    got = [r[0] for r in conn.execute("SELECT voucher_no FROM vouchers_all ORDER BY " + V.voucher_order_sql("voucher_no"))]
    assert got == ["20261010-100", "20261010-998", "20261010-999", "20261010-1000", "20261010-1000-R1", "20261010-1000-R2", "20261010-1001", "20261010-10000"], got
    plain = [r[0] for r in conn.execute("SELECT voucher_no FROM vouchers_all ORDER BY voucher_no")]
    assert plain != got, "字串排序確實會排錯（反向控制：不用 voucher_order_sql 就會錯）"
    seqs = [r[0] for r in conn.execute("SELECT " + V.voucher_seq_sql("voucher_no") + " FROM vouchers_all ORDER BY voucher_no")]
    assert sorted(seqs) == [100, 998, 999, 1000, 1000, 1000, 1001, 10000]


def test_readers_sort_with_the_numeric_helper_and_no_raw_order_by_voucher_no_remains():
    root = Path(__file__).resolve().parents[1]
    src = (root / "ledger" / "reports.py").read_text(encoding="utf-8")
    assert src.count("voucher_order_sql(") == 2, "序時帳簿與明細帳兩處都要用流水整數排序"
    assert "v.voucher_no, l.line_no" not in src and "voucher_date,1,10), voucher_no LIMIT" not in src, "reports.py 還有直接按單號字串排序的地方"


def test_natural_sort_key_used_by_gl_status_orders_correctly():
    key = lambda s: [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]               # noqa: E731  與 helpers/gl_status.py 同式
    assert sorted(["20261010-1000", "20261010-999", "20261010-998"], key=key) == ["20261010-998", "20261010-999", "20261010-1000"]
    src = (Path(gl_status.__file__)).read_text(encoding="utf-8")
    assert 're.split(r"(\\d+)", s)' in src, "gl_status 的排序要用自然排序"
