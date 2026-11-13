# -*- coding: utf-8 -*-
"""e2e 靜態規則：動作（click／fill…）之後「不等待就直接讀 UI 狀態」（is_visible()／text_content()…）。

[單位] test:e2e_lint    [層] 測試工具    [穩定度] 內部
[公開介面] scan_source, scan_all, load_baseline, dump, RULES, ACTIONS, READS, WAITS
[不變式]
  - 純 AST（不需要 Playwright、不開瀏覽器）；掃 backend 底下檔名含 `e2e` 的測試檔（tests/ 與 modules/*/tests/）。
  - 規則（只有一條，名字 `read-after-action`）：同一個程式區塊裡，某個動作敘述（`.click()`／`.fill()`／`.press()`／`.check()`／`.select_option()`…）
    **之後**、在碰到任何等待之前，出現「讀目前 UI 狀態」的呼叫（`.is_visible()`／`.is_hidden()`／`.text_content()`／`.inner_text()`／`.count()`…）⇒ 違規。
    為什麼：動作送出後前端（Alpine x-show、非同步 fetch 後 render）要過一個影格以上才更新；立刻讀＝賽跑。
    `assert x.is_visible()` 輸給 x-show 一個影格 ⇒ 偶發紅（2026-11-11）；`assert not x.is_visible()` 更糟——更新前就讀到「還沒出現」⇒ **假綠燈**。
  - 「等待」＝ `wait_for`／`wait_for_selector`／`wait_for_function`／`wait_for_url`／`wait_for_load_state`／`wait_for_response`／`wait_for_event`／
    `expect_*`（Playwright 的 `expect(loc).to_be_visible()` 本身就是等待＋斷言）／名字含 `wait` 的函式或方法／`to_be_*`／`to_have_*`。
    **不算等待**：`wait_for_timeout`、`time.sleep`（固定睡眠只是把賽跑拉長，不是同步點）。
  - 豁免：該行（或前一行）有註解 `# e2e-lint: ok <理由>`（理由必填）⇒ 不算違規（例：前面的輔助函式已經等過了）。
  - 基準 `e2e_lint_baseline.json`：既有違規的 id（檔::函式::讀取名#序號，不含行號）。**只准縮小**——新增違規 ⇒ 紅；
    基準裡有已經不存在的 id（修好了）⇒ 也紅，要求從基準刪掉（`python -m tests.platform._e2e_lint --shrink`），這樣修好的洞不會被拿去藏新的違規。
[契約題] tests/platform/test_e2e_lint_2026_11_13.py
"""
import ast
import json
import re
import sys
import warnings
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
BASELINE_PATH = Path(__file__).with_name("e2e_lint_baseline.json")

RULE = "read-after-action"
#: 送出動作（之後 UI 會非同步變化）
ACTIONS = frozenset({"click", "dblclick", "fill", "press", "type", "press_sequentially", "check", "uncheck", "select_option",
                     "set_input_files", "tap", "hover", "drag_to", "dispatch_event", "set_checked", "clear"})
#: 只改自己這個元素的值、不觸發非同步工作的動作（之後讀同一個元素的值是確定的，不算賽跑）
SYNC_ACTIONS = frozenset({"fill", "check", "uncheck", "set_checked", "clear", "type", "press_sequentially"})
#: 「元素自己的值」類讀取：只在動作是 SYNC_ACTIONS 時放行
SYNC_READS = frozenset({"input_value", "is_checked"})
#: 讀目前 UI 狀態（不等待、立刻回傳）
READS = frozenset({"is_visible", "is_hidden", "is_enabled", "is_disabled", "is_checked", "is_editable", "text_content", "inner_text",
                   "inner_html", "get_attribute", "input_value", "count", "all_text_contents", "all_inner_texts"})
#: 等待（碰到就清掉「剛做完動作」的狀態）；wait_for_timeout 刻意不在內
WAITS = frozenset({"wait_for", "wait_for_selector", "wait_for_function", "wait_for_url", "wait_for_load_state", "wait_for_response",
                   "wait_for_event", "wait_for_request", "expect", "expect_response", "expect_navigation", "expect_download",
                   "expect_popup", "expect_event", "expect_request", "expect_file_chooser", "expect_request_finished"})
_NOT_A_WAIT = frozenset({"wait_for_timeout"})
_OK_COMMENT = re.compile(r"#\s*e2e-lint:\s*ok\s+\S")


def _call_name(node):
    f = node.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return None


def _is_wait_name(name):
    if name in _NOT_A_WAIT or name is None:
        return False
    return name in WAITS or "wait" in name.lower() or name.startswith(("to_be_", "to_have_", "to_contain_", "to_match_"))


def file_waiters(tree):
    """同一個檔案裡「函式本體（含它呼叫的同檔函式）有等待」的函式名 ⇒ 呼叫它等於等過了（例：`_saved(page)`、`_ready(page)`）。
    只認得同檔函式；跨檔的輔助函式要在呼叫處寫 `# e2e-lint: ok 理由`。"""
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    names_in = {}
    for name, fn in funcs.items():
        names_in[name] = {_call_name(c) for c in ast.walk(fn) if isinstance(c, ast.Call)}
    waiters = {n for n, calls in names_in.items() if any(_is_wait_name(c) for c in calls)}
    changed = True
    while changed:
        changed = False
        for n, calls in names_in.items():
            if n not in waiters and calls & waiters:
                waiters.add(n)
                changed = True
    return waiters


def _calls_in_order(node):
    """敘述裡所有 Call，依原始碼位置排序（同一行內也依欄位）。lambda／內層函式定義不展開（不是現在執行）。"""
    out = []

    def walk(n):
        if isinstance(n, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return
        if isinstance(n, ast.Call):
            out.append(n)
        for c in ast.iter_child_nodes(n):
            walk(c)
    walk(node)
    out.sort(key=lambda c: (c.lineno, c.col_offset))
    return out


def _simple_stmt_calls(stmt):
    """只看這個敘述自己的運算式（不進它的子區塊；子區塊另外遞迴）。"""
    if isinstance(stmt, (ast.If, ast.While)):
        return _calls_in_order(stmt.test)
    if isinstance(stmt, (ast.For, ast.AsyncFor)):
        return _calls_in_order(stmt.iter)
    if isinstance(stmt, (ast.With, ast.AsyncWith)):
        out = []
        for it in stmt.items:
            out += _calls_in_order(it.context_expr)
        return out
    if isinstance(stmt, (ast.Try, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return []
    return _calls_in_order(stmt)


def _blocks(stmt):
    """敘述底下的子區塊（list[stmt]）。"""
    out = []
    for field in ("body", "orelse", "finalbody"):
        b = getattr(stmt, field, None)
        if isinstance(b, list) and b and isinstance(b[0], ast.stmt):
            out.append(b)
    for h in getattr(stmt, "handlers", []) or []:
        out.append(h.body)
    return out


def _ok_lines(src):
    """有 `# e2e-lint: ok 理由` 註解的行號（該行與下一行都豁免）。"""
    ok = set()
    for i, line in enumerate(src.splitlines(), start=1):
        if _OK_COMMENT.search(line):
            ok.add(i)
            ok.add(i + 1)
    return ok


def _worse(a, b):
    order = {None: 0, "sync": 1, "async": 2}
    return a if order[a] >= order[b] else b


def _scan_block(stmts, pending, hits, ok_lines, waiters=frozenset()):
    """pending＝None（沒有）／"sync"（剛做完只改自己值的動作）／"async"（剛做完會觸發非同步工作的動作、還沒等過）。
    回傳區塊結束時的 pending（讓呼叫端接續；子區塊保守：視為可能 pending）。"""
    for stmt in stmts:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue                      # 函式在外層分別掃
        for c in _simple_stmt_calls(stmt):
            name = _call_name(c)
            if name in READS and isinstance(c.func, ast.Attribute):
                if pending and c.lineno not in ok_lines and not (pending == "sync" and name in SYNC_READS):
                    hits.append((c.lineno, name))
            elif _is_wait_name(name) or name in waiters:
                pending = None
            elif name in ACTIONS and isinstance(c.func, ast.Attribute):
                if name in SYNC_ACTIONS:
                    pending = pending or "sync"
                else:
                    pending = "async"
        for blk in _blocks(stmt):
            after = _scan_block(blk, pending, hits, ok_lines, waiters)
            pending = _worse(pending, after)    # 子區塊裡有動作而沒等 ⇒ 之後仍算 pending；子區塊裡等過不代表每條路都等過
    return pending


def scan_source(rel, src):
    """⇒ {id: 行號}（id＝rel::函式::讀取名#序號；行號只給人看，不進基準）。語法錯誤的檔回 {"…::<syntax>": 0}。"""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")                 # 被掃描檔裡的 '\s' 之類不是本規則的事
            tree = ast.parse(src)
    except SyntaxError:
        return {"%s::<syntax>::read#0" % rel: 0}
    ok_lines = _ok_lines(src)
    waiters = file_waiters(tree)
    out = {}

    def visit(node, qual):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                q = qual + [ch.name]
                hits = []
                _scan_block(ch.body, None, hits, ok_lines, waiters - {ch.name})
                seen = {}
                for ln, name in sorted(hits):
                    seen[name] = seen.get(name, 0) + 1
                    out["%s::%s::%s#%d" % (rel, ".".join(q), name, seen[name])] = ln
                visit(ch, q)
            elif isinstance(ch, ast.ClassDef):
                visit(ch, qual + [ch.name])
            else:
                visit(ch, qual)
    visit(tree, [])
    return out


def e2e_files():
    """backend 底下檔名含 e2e 的 .py（tests/ 與 modules/*/tests/；不含本規則自己的檔與基準工具）。"""
    out = []
    for p in sorted(BACKEND.rglob("*e2e*.py")):
        rel = p.relative_to(BACKEND)
        if "__pycache__" in rel.parts or ".venv" in "".join(rel.parts) or rel.parts[0] in ("venv", ".venv", "node_modules"):
            continue
        if rel.parts[:2] == ("tests", "platform"):
            continue                       # 規則本身與它的測試（含故意寫壞的範例字串）
        out.append(p)
    return out


def scan_all():
    out = {}
    for p in e2e_files():
        rel = p.relative_to(BACKEND).as_posix()
        out.update(scan_source(rel, p.read_text(encoding="utf-8")))
    return out


def dump(ids):
    """基準檔格式：一筆一行、依 id 排序（rebase／合併衝突只在相鄰行；resolve_baselines 的 json 驅動認得這個排版）。"""
    lines = ['  %s: 1' % json.dumps(k, ensure_ascii=False) for k in sorted(ids)]
    return '{\n "entries": {\n%s\n }\n}\n' % ",\n".join(lines)


def load_baseline():
    if not BASELINE_PATH.exists():
        return {}
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))["entries"]


def main(argv):
    cur = scan_all()
    base = load_baseline()
    new = sorted(k for k in cur if k not in base)
    stale = sorted(k for k in base if k not in cur)
    print("違規 %d 筆；基準 %d 筆；新增 %d；基準已修好（可刪）%d" % (len(cur), len(base), len(new), len(stale)))
    if "--init" in argv:
        if BASELINE_PATH.exists():
            print("拒絕：基準已存在（只准縮小，用 --shrink）")
            return 1
        BASELINE_PATH.write_text(dump(cur), encoding="utf-8", newline="\n")
        print("已建立基準", BASELINE_PATH)
        return 0
    if "--shrink" in argv:
        if new:
            print("拒絕縮小：有 %d 筆新違規（先修掉或加 `# e2e-lint: ok 理由`）：" % len(new))
            for k in new[:20]:
                print("  ", k, "第", cur[k], "行")
            return 1
        keep = {k: 1 for k in base if k in cur}
        BASELINE_PATH.write_text(dump(keep), encoding="utf-8", newline="\n")
        print("已縮小基準：%d → %d" % (len(base), len(keep)))
        return 0
    for k in new:
        print("  新違規", k, "第", cur[k], "行")
    for k in stale:
        print("  已修好（請刪）", k)
    return 1 if (new or stale) else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main(sys.argv[1:]))
