"""靜態守門：`BEGIN …` 只准出現在 helpers.quotations.begin_write 裡（2026-09-25 lost update／寫鎖稽核後）。

理由：直接 `conn.execute("BEGIN IMMEDIATE")` 的路徑，拿了寫鎖之後若沒被保護，丟例外 ⇒ 寫鎖留到連線被回收
（他人寫入卡 30 秒後 500，W-6）；也繞過 save_quotation_json 守門需要的登記。新程式一律用 begin_write／write_txn。
既有、已確認受保護（拿鎖點在「finally 會 close／rollback」的 try 裡）的列在白名單，**只准變少**；
白名單的每一項也要仍然受保護，否則紅。
"""
import ast
import io
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

#: (相對路徑, 函式名) -> 理由。新增一筆＝有人決定了「這裡不用 begin_write 也安全」，要寫出為什麼。
ALLOWED = {
    ("core/txn.py", "begin_write"): "唯一合法的 BEGIN IMMEDIATE 出處（2026-09-25 自 helpers/quotations.py 下沉 L1）",
    ("pdf_gen.py", "_record_doc_version"): "單據版本號；try/finally 關連線，不讀 quotations.data_json",
    ("modules/payroll/api/bonus.py", "create_case_bonus"): "獎金分潤表；try/finally 關連線，不經 save_quotation_json",
    ("modules/payroll/api/bonus.py", "update_case_bonus"): "同上",
    ("modules/payroll/api/bonus.py", "submit_case_bonus"): "同上",
    ("modules/payroll/api/bonus.py", "approve_case_bonus"): "同上",
    ("modules/payroll/api/bonus.py", "reject_case_bonus"): "同上",
    ("modules/payroll/api/bonus.py", "return_case_bonus"): "同上",
    ("modules/payroll/api/bonus.py", "mark_case_bonus_paid"): "同上",
    ("routers/quotations.py", "case_batch_assign"): "批次指派；讀前已拿鎖、try/finally 關連線（lost update C 組判讀）",
}


def scan(source, rel):
    """回傳 [(rel, 函式名, 行號, 是否受保護)]：每一個以 BEGIN 開頭的 SQL 字串常數。"""
    t = ast.parse(source)
    parents = {}
    for n in ast.walk(t):
        for c in ast.iter_child_nodes(n):
            parents[c] = n
    out = []
    for call in ast.walk(t):
        # 只看 SQL：execute／executescript 的第一個參數（避免 trail.py 的事件名 "begin" 這類誤判）
        if not (isinstance(call, ast.Call) and getattr(call.func, "attr", "") in ("execute", "executescript")
                and call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str)):
            continue
        c = call.args[0]
        v = c.value.strip().upper()
        if not (v == "BEGIN" or v.startswith("BEGIN IMMEDIATE") or v.startswith("BEGIN EXCLUSIVE")
                or v.startswith("BEGIN DEFERRED") or v.startswith("BEGIN TRANSACTION")):
            continue
        p, fn, protected = c, "<module>", False
        while p in parents:
            p = parents[p]
            if (not protected and isinstance(p, ast.Try)
                    and any(("close" in ast.unparse(x) or "rollback" in ast.unparse(x)) for x in p.finalbody)):
                protected = True
            if isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn = p.name
                break
        out.append((rel, fn, c.lineno, protected))
    return out


def _all_sites():
    sites = []
    for f in sorted(BACKEND.rglob("*.py")):
        rel = f.relative_to(BACKEND).as_posix()
        if rel.startswith(("tests/", "venv", ".venv")) or "/site-packages/" in rel:
            continue
        try:
            src = io.open(f, encoding="utf-8").read()
            sites += scan(src, rel)
        except (SyntaxError, UnicodeDecodeError):
            continue
    return sites


def test_begin_appears_only_in_begin_write_or_the_allowlist():
    bad = [s for s in _all_sites() if (s[0], s[1]) not in ALLOWED]
    assert not bad, ("新的 BEGIN 出處（請改用 core.txn.begin_write／write_txn）：%s" % bad)


def test_every_allowlisted_site_still_exists_and_is_protected():
    sites = {(s[0], s[1]): s for s in _all_sites()}
    from core import source_tree
    # 模組被拿掉（選配／反向控制，PLAYBOOK §B-11）⇒ 它的出處本來就不在，不算過期
    stale = [k for k in ALLOWED if k not in sites and source_tree.module_installed(k[0])]
    assert not stale, "白名單裡已不存在的出處（只准變少：請刪掉這一筆）：%s" % stale
    unprotected = [sites[k] for k in ALLOWED if k in sites and k[1] != "begin_write" and not sites[k][3]]
    assert not unprotected, "白名單的出處拿鎖後不再受 try/finally 保護：%s" % unprotected


def test_the_scanner_sees_what_it_should():
    """正對照：掃描器真的抓得到裸 BEGIN、也分得出有沒有保護。"""
    raw = 'def f(conn):\n    conn.execute("BEGIN IMMEDIATE")\n    conn.execute("x")\n'
    guarded = ('def g(conn):\n    try:\n        conn.execute("begin immediate")\n'
               '    finally:\n        conn.close()\n')
    assert scan(raw, "x.py") == [("x.py", "f", 2, False)]
    assert scan(guarded, "x.py") == [("x.py", "g", 3, True)]
    assert scan('s = "BEGINNER"\n', "x.py") == []
