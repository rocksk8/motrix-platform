"""守門：不可以在自己的寫入交易還沒 commit 時，另開連線再寫一次（2026-09-15）。

**這是這個 codebase 已經踩過兩次的坑**：

  2026-09-10  `create_quotation()` —— `_build_approval_tiers_and_notify()` 裡的
              `_notify()` 另開連線，撞上外層還沒 commit 的寫入交易，通知被
              靜默丟掉（見該函式註解）
  2026-09-15  `_apply_case_change_request()` —— `save_quotation_json()` 之後
              直接 `_audit()`，使用者回報「簽核後卡死十幾秒」，**實測 32.8 秒**，
              而且稽核紀錄同時被吞掉

形狀永遠一樣：

    conn.execute("UPDATE ...")   # 取得寫鎖，尚未 commit
    _audit(...) / _notify(...)   # get_db() 另開一條連線寫入 → 撞自己的鎖

SQLite 同時只允許一個 writer，`db.py::_connect()` 是 `connect(timeout=30)`，
所以第二條連線會等滿 30 秒；而 `_audit()`／`_notify()` 都有 `except` 會把逾時
例外吞掉——**使用者看到的是卡住然後「成功」，紀錄卻不見了**。

這支測試用 AST 靜態掃描把這個形狀變成會紅的東西，不必等下一個人踩到。
它刻意**不**執行任何程式碼——真的跑起來要等 30 秒才看得到症狀，那種測試沒人會留著。
"""
import ast
import glob
import io
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND = os.path.join(ROOT, "backend")

# 會「另開一條連線**寫入**」的呼叫。它們內部都是 get_db() 自己開、自己 commit。
#
# ⚠️ 只收真的會寫的。初稿把整個 `notify_*` 前綴都收進來，結果誤報
# `approve_quotation` 的 `notify_approved()`——實際核對過 `helpers/email_notify.py`
# 全部 43 支 `notify_*`：它們只查收件人 email（讀）然後開執行緒寄信，
# **一支都沒有寫 db**。WAL 模式下 reader 不會被 writer 擋，不構成這個問題。
# 真正會寫的只有 `helpers/audit.py` 的這三支。
#
# （附帶一提：那些 `notify_*` 在 commit 前讀到的是**尚未提交的舊狀態**。
#  目前它們只讀使用者 email，不受影響；日後若有人讓它們去讀剛剛寫入的單據
#  內容，就會讀到舊值——那是另一種 bug，不在這支守門的範圍。）
_CROSS_CONN_WRITERS = {"_audit", "_notify", "_purge_notifications"}
_CROSS_CONN_PREFIXES = ()

# 吃 conn 但會在裡面寫入、且**不 commit**的共用函式（呼叫端負責 commit）
# ⚠️ 只收「吃呼叫端的 conn、而且不自己 commit」的。`_set_setting()` 不算——
# 它自己 get_db()、自己 commit、自己 close，是完整的一次交易，不會把鎖留給
# 呼叫端（初稿把它放進來，造成 system.py 整批 18 個誤報）。
_WRITE_HELPERS = {
    "save_quotation_json", "_sync_stages_to_json", "_sync_json_stages_to_table",
    "_sync_device_stock",
}

_WRITE_SQL = ("insert", "update", "delete", "replace")

# 已知安全、刻意保留的例外。**每一筆都要寫清楚為什麼**——這份清單的意義是
# 讓下一個新增的變紅，不是讓測試變綠。
_ALLOWED = {
    # (檔名, 函式名): 理由
}


def _iter_functions():
    files = sorted(glob.glob(os.path.join(BACKEND, "routers", "*.py"))) + \
        sorted(glob.glob(os.path.join(BACKEND, "helpers", "*.py"))) + \
        [os.path.join(BACKEND, "main.py")]
    for path in files:
        if "rollback_snapshots" in path:
            continue
        try:
            src = io.open(path, encoding="utf-8").read()
            tree = ast.parse(src)
        except (SyntaxError, OSError):
            continue
        name = os.path.basename(path)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield name, node


def _call_name(node):
    """取得呼叫的函式名稱（`a.b(...)` 回 'b'，`f(...)` 回 'f'）。"""
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""


def _is_conn_write(node) -> bool:
    """`conn.execute("UPDATE ...")` / `conn.executemany(...)` 之類。"""
    f = node.func
    if not isinstance(f, ast.Attribute) or f.attr not in ("execute", "executemany"):
        return False
    if not isinstance(f.value, ast.Name) or "conn" not in f.value.id.lower():
        return False
    if not node.args:
        return False
    sql = node.args[0]
    text = ""
    if isinstance(sql, ast.Constant) and isinstance(sql.value, str):
        text = sql.value
    elif isinstance(sql, ast.JoinedStr):
        text = "".join(v.value for v in sql.values
                       if isinstance(v, ast.Constant) and isinstance(v.value, str))
    elif isinstance(sql, ast.BinOp):          # "..." + table + "..."
        text = " ".join(n.value for n in ast.walk(sql)
                        if isinstance(n, ast.Constant) and isinstance(n.value, str))
    return any(text.lstrip().lower().startswith(k) for k in _WRITE_SQL)


def _is_conn_commit(node) -> bool:
    f = node.func
    return (isinstance(f, ast.Attribute) and f.attr in ("commit", "rollback", "close")
            and isinstance(f.value, ast.Name) and "conn" in f.value.id.lower())


def _is_cross_conn_write(name: str) -> bool:
    return name in _CROSS_CONN_WRITERS or name.startswith(_CROSS_CONN_PREFIXES)


def _scan(func) -> list:
    """回傳這個函式裡「寫了還沒 commit 就跨連線再寫」的呼叫名稱清單。

    以原始碼出現順序線性掃描（不做控制流分析）。這對這個形狀夠用——兩者幾乎
    都寫在同一段直線程式碼裡；而且**寧可誤報也不要漏報**，誤報可以放進
    `_ALLOWED` 並寫下理由，漏報則是等下一個人卡 30 秒。
    """
    holding, hits = False, []
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        yield_order = getattr(node, "lineno", 0)
        node._line = yield_order
    calls = sorted((n for n in ast.walk(func) if isinstance(n, ast.Call)),
                   key=lambda n: (getattr(n, "lineno", 0), getattr(n, "col_offset", 0)))
    for call in calls:
        name = _call_name(call)
        if _is_conn_write(call) or name in _WRITE_HELPERS:
            holding = True
            continue
        if _is_conn_commit(call):
            holding = False
            continue
        if holding and _is_cross_conn_write(name):
            hits.append((name, getattr(call, "lineno", 0)))
    return hits


def test_no_cross_connection_write_while_holding_write_lock():
    """全域掃描。新增的違規會在這裡變紅。"""
    offenders = []
    for filename, func in _iter_functions():
        if (filename, func.name) in _ALLOWED:
            continue
        hits = _scan(func)
        if hits:
            offenders.append(
                f"{filename}::{func.name} — "
                + "、".join(f"{n}() @L{ln}" for n, ln in hits))

    assert not offenders, (
        "以下函式在自己的寫入交易還沒 commit 時，又呼叫了會另開連線寫入的函式。\n"
        "SQLite 同時只允許一個 writer，第二條連線會等滿 30 秒 busy_timeout，"
        "而且例外被吞掉——症狀是「卡住十幾秒然後顯示成功，但紀錄不見了」。\n"
        "修法：把那些呼叫延後到 conn.commit() 之後"
        "（見 routers/quotations.py::approve_case_change 的 deferred_audits）。\n"
        "確定安全的請加進本檔 _ALLOWED 並寫明理由。\n\n  "
        + "\n  ".join(offenders))


def test_the_guard_actually_detects_the_known_bug():
    """**證明這支掃描抓得到東西**，不是永遠綠的裝飾品。

    用 2026-09-15 那個真實 bug 的形狀當樣本：先寫、不 commit、再 _audit()。
    """
    src = (
        "def broken(conn, authorization):\n"
        "    save_quotation_json(conn, 'X', {})\n"
        "    _audit(authorization, 'a.b', 'quotation', 'X', 'label')\n"
        "    conn.commit()\n"
    )
    func = ast.parse(src).body[0]
    hits = _scan(func)
    assert [n for n, _ in hits] == ["_audit"], hits


def test_the_guard_accepts_the_fixed_shape():
    """反向控制：commit 之後才寫稽核 → 不該被判成違規。"""
    src = (
        "def fixed(conn, authorization):\n"
        "    save_quotation_json(conn, 'X', {})\n"
        "    conn.commit()\n"
        "    conn.close()\n"
        "    _audit(authorization, 'a.b', 'quotation', 'X', 'label')\n"
    )
    func = ast.parse(src).body[0]
    assert _scan(func) == []
