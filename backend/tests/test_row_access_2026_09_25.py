"""helpers/row_access：單筆判斷（visible）與 SQL 過濾（filter_sql）必須等價。

三道比對，同一批資料：
  ①  visible() 逐筆  ==  filter_sql() 的結果集合            （兩種形式等價）
  ②  新介面  ==  舊實作（原封凍結在本檔，見 _OLD_*）          （行為不變，限舊實作有定義的資料）
  ③  壞 JSON：strict 規則兩種形式都丟例外；lenient 兩種形式都當作沒有

資料刻意涵蓋邊界：舊資料（id 為 NULL 比顯示名稱）、空顯示名稱、字串 id、浮點 id、
布林、巢狀陣列、非陣列 JSON、空字串、NULL。
"""
import itertools
import json
import sqlite3

import pytest
from fastapi import HTTPException

from helpers import row_access as ra

# 與 quotations／dev_cases 現行規則相同的宣告。用測試專用 kind 名稱，不佔用正式登錄。
CASE = ra.OwnerRule(owner_id_col="sales_person_id", legacy_name_col="sales_person",
                    id_list_cols=("assigned_user_ids",), lenient_json=False,
                    read_bypass_modules=("cashier",))
DEV = ra.OwnerRule(creator_col="created_by", id_list_cols=("sales_persons", "planners"),
                   lenient_json=True)
ra.register("_t_case", CASE)
ra.register("_t_dev", DEV)

USERS = [
    {"id": 1, "display_name": "Amy", "role": "sales", "modules": "[]"},
    {"id": 2, "display_name": "Bob", "role": "engineer", "modules": "[]"},
    {"id": 3, "display_name": "", "role": "viewer", "modules": "[]"},          # 空顯示名稱
    {"id": 4, "display_name": "Cat", "role": "sales", "modules": '["cashier"]'},
    {"id": 5, "display_name": "Dan", "role": "admin", "modules": "[]"},
    {"id": 6, "display_name": "Eve", "role": "superadmin", "modules": "[]"},
]

WELL_FORMED_LISTS = [None, "", "[]", "[1]", "[2]", "[1,2]", '["1"]', "[1.0]", "[true]", "[[1]]", "[4]"]
ODD_JSON = ['{"a":1}', "1", '"1"', "null"]          # 合法 JSON 但不是陣列
BROKEN = ["not json", "[1,"]


def _case_rows(lists):
    rows = []
    for i, (oid, name, asg) in enumerate(itertools.product(
            [None, 1, 2, 4], [None, "", "Amy", "Bob", "Cat"], lists), start=1):
        rows.append((i, oid, name, asg))
    return rows


def _dev_rows(lists):
    rows = []
    for i, (cb, sp, pl) in enumerate(itertools.product([None, 1, 2], lists, lists), start=1):
        rows.append((i, cb, sp, pl))
    return rows


def _db(case_rows=(), dev_rows=()):
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    # 型別親和性照正式 schema（db.py：quotations／dev_cases）
    c.execute("CREATE TABLE q (id INTEGER PRIMARY KEY, sales_person_id INTEGER, sales_person TEXT, "
              "assigned_user_ids TEXT DEFAULT '[]')")
    c.execute("CREATE TABLE d (id INTEGER PRIMARY KEY, created_by INTEGER, sales_persons TEXT, planners TEXT)")
    c.executemany("INSERT INTO q VALUES (?,?,?,?)", case_rows)
    c.executemany("INSERT INTO d VALUES (?,?,?,?)", dev_rows)
    return c


def _sql_ids(conn, table, kind, user, scope):
    frag, params = ra.filter_sql(kind, user, prefix="t.", scope=scope)
    return {r["id"] for r in conn.execute(f"SELECT t.id FROM {table} t WHERE 1=1{frag}", params)}


def _py_ids(conn, table, kind, user, scope):
    return {r["id"] for r in conn.execute(f"SELECT * FROM {table}") if ra.visible(kind, user, r, scope)}


# ── ① 兩種形式等價 ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("scope", ra.SCOPES)
@pytest.mark.parametrize("user", USERS, ids=lambda u: f"{u['role']}{u['id']}")
def test_case_single_equals_sql(user, scope):
    conn = _db(case_rows=_case_rows(WELL_FORMED_LISTS + ODD_JSON))
    assert _py_ids(conn, "q", "_t_case", user, scope) == _sql_ids(conn, "q", "_t_case", user, scope)


@pytest.mark.parametrize("scope", ra.SCOPES)
@pytest.mark.parametrize("user", USERS, ids=lambda u: f"{u['role']}{u['id']}")
def test_dev_case_single_equals_sql(user, scope):
    conn = _db(dev_rows=_dev_rows(WELL_FORMED_LISTS + ODD_JSON + BROKEN))
    assert _py_ids(conn, "d", "_t_dev", user, scope) == _sql_ids(conn, "d", "_t_dev", user, scope)


def test_positive_control_sets_are_not_trivial():
    """等價若來自「兩邊都空」或「兩邊都全部」就沒有意義：一般使用者必須看到一部分、不是全部。"""
    conn = _db(case_rows=_case_rows(WELL_FORMED_LISTS), dev_rows=_dev_rows(WELL_FORMED_LISTS))
    for table, kind in (("q", "_t_case"), ("d", "_t_dev")):
        total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        got = _sql_ids(conn, table, kind, USERS[0], "owner")
        assert 0 < len(got) < total, (kind, len(got), total)
    # 反向控制：把 SQL 片段換成恆真，比對必須失敗（證明比對真的在比）
    frag_py = _py_ids(conn, "q", "_t_case", USERS[0], "owner")
    assert frag_py != {r["id"] for r in conn.execute("SELECT id FROM q")}


# ── ② 新介面 == 舊實作（原封凍結，2026-09-25 自 HEAD 複製，只改函式名）────────────

def _OLD_visible_case_filter_sql(user, prefix=""):     # routers/quotations.py:251
    if json.loads(user.get("modules") or "[]").count("cashier"):
        return ("", [])
    return (
        f" AND ({prefix}sales_person_id=? OR ({prefix}sales_person_id IS NULL AND {prefix}sales_person=?)"
        f" OR EXISTS (SELECT 1 FROM json_each({prefix}assigned_user_ids) WHERE value=?))",
        [user["id"], user["display_name"], user["id"]],
    )


def _OLD_check_quotation_owner(row, user):               # helpers/quotations.py:20
    if user["role"] in ("superadmin", "admin"):
        return
    sp_id = row["sales_person_id"] if "sales_person_id" in row.keys() else None
    sp_name = row["sales_person"] if "sales_person" in row.keys() else None
    owns = (sp_id == user["id"]) or (sp_id is None and sp_name == user["display_name"])
    if not owns and "assigned_user_ids" in row.keys():
        assigned = json.loads(row["assigned_user_ids"] or "[]")
        owns = user["id"] in assigned
    if not owns:
        raise HTTPException(403, "x")


def _OLD_can_access_case(user, row):                     # routers/dev_crm.py:100
    if user["role"] in ("superadmin", "admin"):
        return True
    uid = user["id"]
    try:
        sp = json.loads(row["sales_persons"] or "[]")
    except Exception:
        sp = []
    try:
        pl = json.loads(row["planners"] or "[]")
    except Exception:
        pl = []
    return row["created_by"] == uid or uid in sp or uid in pl


# 舊實作有定義的資料：陣列（含 NULL）。空字串與非陣列 JSON 在舊 SQL／舊單筆之間本來就不一致，另題列出。
OLD_DEFINED = [None, "[]", "[1]", "[2]", "[1,2]", '["1"]', "[1.0]", "[true]", "[[1]]", "[4]"]


@pytest.mark.parametrize("user", USERS, ids=lambda u: f"{u['role']}{u['id']}")
def test_case_matches_old_sql_read_scope(user):
    conn = _db(case_rows=_case_rows(OLD_DEFINED))
    if user["role"] in ("superadmin", "admin"):
        old = {r["id"] for r in conn.execute("SELECT id FROM q")}      # 舊版由呼叫端直通
    else:
        frag, params = _OLD_visible_case_filter_sql(user)
        old = {r["id"] for r in conn.execute(f"SELECT id FROM q WHERE 1=1{frag}", params)}
    assert _sql_ids(conn, "q", "_t_case", user, "read") == old


@pytest.mark.parametrize("user", USERS, ids=lambda u: f"{u['role']}{u['id']}")
def test_case_matches_old_single_owner_scope(user):
    conn = _db(case_rows=_case_rows(OLD_DEFINED))
    old = set()
    for r in conn.execute("SELECT * FROM q"):
        try:
            _OLD_check_quotation_owner(r, user)
            old.add(r["id"])
        except HTTPException:
            pass
    assert _py_ids(conn, "q", "_t_case", user, "owner") == old


@pytest.mark.parametrize("user", USERS, ids=lambda u: f"{u['role']}{u['id']}")
def test_dev_case_matches_old(user):
    lists = OLD_DEFINED + ["", "not json"]
    conn = _db(dev_rows=_dev_rows(lists))
    old = {r["id"] for r in conn.execute("SELECT * FROM d") if _OLD_can_access_case(user, r)}
    assert _py_ids(conn, "d", "_t_dev", user, "owner") == old


def test_known_old_inconsistency_empty_string_assigned():
    """舊 SQL 對 assigned_user_ids='' 丟 malformed JSON，舊單筆當成 []。新版兩者都當成 []。"""
    conn = _db(case_rows=[(1, 2, "Bob", "")])
    frag, params = _OLD_visible_case_filter_sql(USERS[0])
    with pytest.raises(sqlite3.OperationalError):
        conn.execute(f"SELECT id FROM q WHERE 1=1{frag}", params).fetchall()
    assert _sql_ids(conn, "q", "_t_case", USERS[0], "read") == set()
    assert _py_ids(conn, "q", "_t_case", USERS[0], "read") == set()


# ── ③ 壞 JSON ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", BROKEN)
def test_strict_broken_json_raises_in_both_forms(bad):
    conn = _db(case_rows=[(1, 2, "Bob", bad)])        # 不是 Amy 的 ⇒ 會走到成員欄位
    with pytest.raises(ValueError):
        _py_ids(conn, "q", "_t_case", USERS[0], "owner")
    with pytest.raises(sqlite3.OperationalError):
        _sql_ids(conn, "q", "_t_case", USERS[0], "owner")


def test_admin_and_bypass_return_empty_fragment():
    assert ra.filter_sql("_t_case", USERS[4]) == ("", [])
    assert ra.filter_sql("_t_case", USERS[3], scope="read") == ("", [])
    assert ra.filter_sql("_t_case", USERS[3], scope="owner") != ("", [])


def test_unregistered_kind_fails_closed(caplog):
    """擁有該表的模組不在 ⇒ 只能少看到，不可以多看到：連 admin 都不放行，SQL 恆假，並記 WARNING。"""
    conn = _db(case_rows=_case_rows(WELL_FORMED_LISTS))
    assert "_t_unregistered" not in ra._REGISTRY
    with caplog.at_level("WARNING", logger="helpers.row_access"):
        for u in USERS:                                   # 含 admin／superadmin／cashier
            for scope in ra.SCOPES:
                assert _py_ids(conn, "q", "_t_unregistered", u, scope) == set()
                assert _sql_ids(conn, "q", "_t_unregistered", u, scope) == set()
                with pytest.raises(HTTPException) as e:
                    ra.require("_t_unregistered", u, {"sales_person_id": u["id"]}, scope)
                assert e.value.status_code == 403
    assert any("_t_unregistered" in r.getMessage() for r in caplog.records)
    # 正對照：同一批資料、登錄後就看得到
    ra.register("_t_unregistered_ctrl", CASE)
    assert _sql_ids(conn, "q", "_t_unregistered_ctrl", USERS[0], "owner")


def test_require_uses_registered_message():
    ra.register("_t_msg", ra.OwnerRule(owner_id_col="sales_person_id", deny_message="不是你的"))
    ra.require("_t_msg", USERS[0], {"sales_person_id": 1})
    with pytest.raises(HTTPException) as e:
        ra.require("_t_msg", USERS[0], {"sales_person_id": 2})
    assert (e.value.status_code, e.value.detail) == (403, "不是你的")


def test_unknown_scope_is_refused():
    with pytest.raises(ValueError):
        ra.filter_sql("_t_case", USERS[0], scope="all")
