# -*- coding: utf-8 -*-
"""寫鎖區塊內不得「另開連線寫入」或「啟動背景工作」的靜態掃描（W3 approval-freeze）。

## 成因（2026-09-30 使用者回報正式機：簽核時整個系統卡住約 3 秒）
`with write_txn(conn):`（= BEGIN IMMEDIATE）區塊內呼叫 `_notify()`（helpers/audit.py，**另開一條連線** INSERT notifications）：
新連線要等同一個請求握著的寫鎖，等滿 busy timeout 才失敗 ⇒ 通知遺失，而且這段時間全體寫入都被卡住。
同型的還有：區塊內 `spawn_bg_thread(...)`（背景執行緒在 commit 之前就開始讀資料，讀到簽核前的狀態）。

## 規則
`with write_txn(...)` 區塊（含區塊內巢狀 with／if／for／try，但不含區塊內定義的函式；頂層 `conn.commit()`／`close()`／`rollback()` 之後的陳述式不算，因為寫鎖已放掉）**不得呼叫**：
  _notify / _audit / spawn_bg_thread / notify_* / push_event_* / threading.Thread / 寄信（send_*mail*）
  ⇒ 正確寫法：區塊內只收集（例如 `after_commit.append(lambda: _notify(...))`），**commit 之後**再做。
例外（白名單 `ALLOWED`）要寫理由，而且同一個 (檔案, 函式, 呼叫) 的次數要一致（多了少了都紅）。

用法：python tools/platform/write_txn_scan.py [--json]    # 列出所有命中
"""
import argparse
import ast
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOTS = ("backend",)
SKIP_PARTS = {"tests", "__pycache__", "node_modules", "migrations_frozen"}

#: 名稱（呼叫的最後一段）符合任何一條 ⇒ 命中
DENY = [re.compile(p) for p in (
    r"^_notify$", r"^_audit$", r"^spawn_bg_thread$", r"^notify_.+", r"^push_event_.+", r"^Thread$", r"^send_.*mail.*$", r"^audit$",
)]

#: 已知而且必須留著的例外：{(相對路徑, 函式, 呼叫名): (次數, 理由)}
ALLOWED = {
    ("backend/helpers/custom_modules.py", "decide", "notify_ref"): (
        1, "只組出通知參照字串（不寫入）；實際通知由 _Effects.flush() 在 commit 之後才做"),
    ("backend/modules/recyclebin/service.py", "restore", "audit"): (
        1, "audit 是呼叫端傳入的 callback，三個呼叫端（api／jobs）都只傳 lambda 呼叫 service.audit_tx：同一條 conn、同一交易 INSERT audit_log，不 commit、不另開連線、不通知、不啟動背景工作；稽核與還原必須原子（寫不進去 ⇒ 整筆 rollback，test_recyclebin_fixes_r5_t53）"),
    ("backend/modules/recyclebin/service.py", "purge", "audit"): (
        1, "同 restore：callback 只走 service.audit_tx（同 conn 同交易），先稽核、再 commit、最後才刪隔離檔；稽核寫不進去 ⇒ 什麼都沒刪"),
}


def _call_name(node):
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def _is_write_txn(item):
    e = item.context_expr
    return isinstance(e, ast.Call) and _call_name(e) == "write_txn"


def _releases_lock(stmt):
    """頂層陳述式本身就是 `<conn>.commit()`／`.rollback()`／`.close()` ⇒ 寫鎖在這之後放掉。
    （巢狀在 if／for 裡的 commit 不算——不是每條路徑都會走到；保守起見繼續往後檢查。）"""
    return (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call) and _call_name(stmt.value) in ("commit", "rollback", "close"))


def _is_begin(stmt):
    """手動開寫鎖：`begin_write(conn)`（含 `began = begin_write(conn)`）或 `conn.execute("BEGIN IMMEDIATE")`。"""
    v = stmt.value if isinstance(stmt, (ast.Expr, ast.Assign)) else None
    if not isinstance(v, ast.Call):
        return False
    if _call_name(v) == "begin_write":
        return True
    return (_call_name(v) == "execute" and bool(v.args) and isinstance(v.args[0], ast.Constant)
            and isinstance(v.args[0].value, str) and "BEGIN IMMEDIATE" in v.args[0].value.upper())


def _sub_bodies(st):
    if isinstance(st, (ast.If, ast.For, ast.AsyncFor, ast.While)):
        return [st.body, st.orelse]
    if isinstance(st, ast.Try):
        return [st.body, *[h.body for h in st.handlers], st.orelse, st.finalbody]
    if isinstance(st, (ast.With, ast.AsyncWith)):
        return [st.body]
    return []


def _header_exprs(st):
    if isinstance(st, (ast.If, ast.While)):
        return [st.test]
    if isinstance(st, (ast.For, ast.AsyncFor)):
        return [st.iter]
    if isinstance(st, (ast.With, ast.AsyncWith)):
        return [i.context_expr for i in st.items]
    return []


class _Walker:
    """依序走每個函式的陳述式：寫鎖「持有中」的期間（`with write_txn` 區塊、或手動 begin 之後到頂層 commit／rollback／close 之前）
    內所有呼叫都要檢查；持有中不進區塊內新定義的函式／lambda（那只是稍後才執行的收集，不算在鎖內執行）。"""

    def __init__(self):
        self.hits = []          # (函式, 行, 呼叫名)

    def run(self, tree):
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._seq(fn.body, False, fn.name)
        self._seq(tree.body, False, "(module)")

    def _seq(self, stmts, held, fn):
        for st in stmts:
            if held:
                bodies = _sub_bodies(st)
                if bodies:
                    # 複合陳述式：標頭表達式照檢查；每個分支各自依序走（分支內頂層的 commit／close 之後，該分支後面的呼叫寫鎖已放掉）。
                    # 保守：分支走完後仍視為持有中（不是每條路徑都會放掉）。
                    for e in _header_exprs(st):
                        self._calls(e, fn)
                    for body in bodies:
                        self._seq(body, True, fn)
                    if isinstance(st, (ast.With, ast.AsyncWith)) and any(_releases_lock(x) for x in st.body):
                        held = False        # with 區塊一定會走完（例外則整個離開）：區塊頂層的 commit／close 已放掉寫鎖，區塊之後不算持鎖
                    continue
                self._calls(st, fn)
                if _releases_lock(st):
                    held = False
                continue
            if isinstance(st, (ast.With, ast.AsyncWith)) and any(_is_write_txn(i) for i in st.items):
                self._seq(st.body, True, fn)
                continue
            if _is_begin(st):
                held = True
                continue
            for body in _sub_bodies(st):
                self._seq(body, False, fn)

    def _calls(self, stmt, fn):
        stack = [stmt]
        while stack:
            n = stack.pop()
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            if isinstance(n, ast.Call):
                name = _call_name(n)
                if name and any(rx.match(name) for rx in DENY):
                    self.hits.append((fn, n.lineno, name))
            stack.extend(ast.iter_child_nodes(n))


def scan_file(path, rel):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return []
    w = _Walker()
    w.run(tree)
    return [(rel, fn, line, name) for fn, line, name in sorted(set(w.hits), key=lambda h: h[1])]


def scan(root=REPO):
    out = []
    for top in ROOTS:
        base = Path(root) / top
        for p in sorted(base.rglob("*.py")):
            rel = p.relative_to(root)
            if any(part in SKIP_PARTS for part in rel.parts):
                continue
            out += scan_file(p, rel.as_posix())
    return out


def problems(hits, allowed=None):
    """⇒ 問題清單（空＝通過）。白名單的次數必須一致。"""
    allowed = ALLOWED if allowed is None else allowed
    counts = {}
    for rel, fn, _line, name in hits:
        counts[(rel, fn, name)] = counts.get((rel, fn, name), 0) + 1
    out = []
    for k, n in sorted(counts.items()):
        ok = allowed.get(k)
        if ok is None:
            out.append("%s::%s 的 write_txn 區塊內呼叫 %s ×%d" % (k[0], k[1], k[2], n))
        elif ok[0] != n:
            out.append("%s::%s 的 %s 白名單登記 %d 次，實際 %d 次（理由：%s）" % (k[0], k[1], k[2], ok[0], n, ok[1]))
    for k, (n, why) in sorted(allowed.items()):
        if k not in counts:
            out.append("白名單過期：%s::%s 已不再呼叫 %s（%s）" % (k[0], k[1], k[2], why))
    return out


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    hits = scan()
    if a.json:
        print(json.dumps([list(h) for h in hits], ensure_ascii=False, indent=1))
    else:
        for rel, fn, line, name in hits:
            print("%s:%d  %s  呼叫 %s" % (rel, line, fn, name))
        print("共 %d 處" % len(hits))
    return 1 if problems(hits) else 0


if __name__ == "__main__":
    sys.exit(main())
