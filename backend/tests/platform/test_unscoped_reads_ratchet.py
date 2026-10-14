# -*- coding: utf-8 -*-
"""未經範圍讀取的 AST 棘輪（§14.10 #6）：目前的未經範圍讀取集合必須是基準的子集（只減不增）。

掃描器見 `_unscoped_reads.py`。新增讀取請改走 `filter_sql`／核准 helper；確實要登記才動基準檔，且總數上限 `MAX_ENTRIES` 只准手動調小。
已知假陰性（文件化，不是漏掉）：
  ①核准 helper 以『函式』為粒度——同函式內有一句走 helper，其餘讀取都視為已處理；
  ②完全由其他函式回傳的 SQL（`conn.execute(build())`）看不到文字，只在 `execute(<變數>)` 且變數非本函式／模組組裝時記為 dynamic；
  ③字串存在 dict／list／class 屬性後再取用的 SQL，只在被當作運算式出現的地方被掃到；
  ④不含 SELECT 的寫入（UPDATE／DELETE）不屬於本棘輪（輸入側見 test_u0a_sinks）；
  ⑤migrations 目錄與 core/migrations.py 不掃。
"""
from tests.platform import _unscoped_reads as U

#: 基準總筆數上限：只准手動調小（基準縮小後把這個數字一起降下來）
MAX_ENTRIES = 838      # 凍結時實數;只准手動調小
#: 掃描器自己的下限：掃到的筆數太少 ⇒ 掃描壞了（假綠）
SCAN_FLOOR = 100


def test_current_unscoped_reads_are_subset_of_baseline():
    cur, base = U.scan_all(), U.load_baseline()
    assert len(cur) >= SCAN_FLOOR, "掃描器只掃到 %d 筆：疑似壞掉" % len(cur)
    new = {k: v for k, v in cur.items() if k not in base}
    assert new == {}, "新增未經範圍的讀取（請改走 filter_sql／核准 helper，或有理由才登記基準）：\n" + "\n".join("  %s  [%s]" % kv for kv in sorted(new.items()))
    changed = {k: (base[k], v) for k, v in cur.items() if k in base and base[k] != v}
    assert changed == {}, "類別改變：%s" % changed
    assert len(base) <= MAX_ENTRIES, "基準 %d 筆超過上限 %d" % (len(base), MAX_ENTRIES)


def test_baseline_file_is_sorted_one_entry_per_line_and_known_categories():
    raw = U.BASELINE_PATH.read_text(encoding="utf-8")
    base = U.load_baseline()
    assert raw == U.dump(base), "基準檔格式不是 dump() 的輸出（需排序、一筆一行）"
    assert set(base.values()) <= {"unscoped", "dynamic"}


def test_baseline_ids_have_no_line_numbers_and_tables_exist():
    for k, v in U.load_baseline().items():
        f, fn, tail = k.split("::")[0], "::".join(k.split("::")[1:-1]), k.split("::")[-1]
        assert f.endswith(".py") and fn, k
        if v == "unscoped":
            assert tail in U.UNIT_TABLES, k
        else:
            assert tail.startswith("<") and tail.endswith(">"), k


# ── 正對照：掃描器本身不能假綠 ───────────────────────────────────────────────────────────
def _scan(src):
    return U.scan_source("x.py", src)


def test_control_unscoped_read_is_flagged():
    got = _scan('def f(conn):\n    return conn.execute("SELECT * FROM quotations WHERE id=?", (1,)).fetchall()\n')
    assert got == {"x.py::f::quotations": "unscoped"}


def test_control_all_string_shapes_flagged():
    for body in ('conn.execute(f"SELECT * FROM quotations WHERE {w}")',
                 'conn.execute("SELECT * FROM quotations WHERE " + w)',
                 'conn.execute("SELECT * FROM quotations WHERE %s" % w)',
                 'conn.execute("SELECT * FROM quotations WHERE {}".format(w))',
                 'q = "SELECT a FROM customers c JOIN quotations q ON 1"\n    conn.execute(q)',
                 'conn.execute("SELECT a FROM suppliers, quotations")'):
        got = _scan("def f(conn, w):\n    " + body + "\n")
        assert "x.py::f::quotations" in got, body


def test_control_scoped_read_stays_green():
    for helper in ("filter_sql('case', user)", "row_access.filter_sql('case', user)", "guard_case_access(conn, q, user)"):
        src = "def f(conn, user, q):\n    frag, a = %s\n    return conn.execute('SELECT * FROM quotations WHERE 1' + frag, a)\n" % helper
        assert _scan(src) == {}, helper
    # 外層函式走 helper ⇒ 內層也算
    assert _scan("def f(conn, user):\n    filter_sql('case', user)\n    def g():\n        conn.execute('SELECT * FROM quotations')\n") == {}


def test_control_non_unit_tables_and_non_select_ignored():
    assert _scan('def f(conn):\n    conn.execute("SELECT * FROM users")\n') == {}
    assert _scan('def f(conn):\n    conn.execute("DELETE FROM quotations WHERE id=1")\n') == {}
    assert _scan('def f():\n    """SELECT * FROM quotations"""\n    return 1\n') == {}


def test_control_dynamic_sql_lands_in_dynamic_not_silent():
    assert _scan('def f(conn, t):\n    conn.execute(f"SELECT * FROM {t}")\n') == {"x.py::f::<from>": "dynamic"}
    assert _scan('def f(conn, sql):\n    conn.execute(sql)\n') == {"x.py::f::<arg:sql>": "dynamic"}
    assert _scan('def f(conn, rest):\n    conn.execute("SELECT a " + rest)\n') == {"x.py::f::<from>": "dynamic"}
    # 本函式內組好的 SQL 變數不算 dynamic
    assert _scan('def f(conn):\n    sql = "SELECT 1"\n    conn.execute(sql)\n') == {}


def test_control_ratchet_fails_when_entry_not_in_baseline():
    base = {"x.py::f::quotations": "unscoped"}
    cur = _scan('def f(conn):\n    conn.execute("SELECT * FROM quotations")\n') | _scan('def g(conn):\n    conn.execute("SELECT * FROM customers")\n')
    assert {k for k in cur if k not in base} == {"x.py::g::customers"}      # 新增一筆 ⇒ 棘輪會紅
    assert {k for k in _scan('def f(conn):\n    conn.execute("SELECT * FROM quotations")\n') if k not in base} == set()   # 縮小／不變 ⇒ 綠


def test_control_ids_do_not_depend_on_line_numbers():
    a = _scan('def f(conn):\n    conn.execute("SELECT * FROM quotations")\n')
    b = _scan('\n\n# 註解\ndef f(conn):\n\n    conn.execute("SELECT * FROM quotations")\n')
    assert a == b
