# -*- coding: utf-8 -*-
"""e2e 靜態規則：動作（click／fill…）之後「不等待就直接讀 UI 狀態」（is_visible()／text_content()…）。

[單位] test:e2e_lint    [層] 測試工具    [穩定度] 內部
[公開介面] scan_source, scan_all, browser_files, load_baseline, dump, ACTIONS, READS, WAITS, WAIT_HELPER_WHITELIST
[不變式]
  - 純 AST（不需要 Playwright、不開瀏覽器）。**依內容選檔**：backend 底下任何 .py 只要出現 `new_page`／`sync_playwright`／`pytest.mark.e2e`／
    `e2e_browser`，或檔名含 `e2e` ⇒ 掃（含 tests/platform；hichan-3 審查 M3：只看檔名會漏掉 53 個瀏覽器測試檔）。
  - 規則（只有一條，名字 `read-after-action`）：同一個程式區塊裡，某個動作敘述（`.click()`／`.press()`／`.select_option()`／`.fill()`…）
    **之後**、在碰到任何等待之前，出現「讀目前 UI 狀態」的呼叫（`.is_visible()`／`.is_hidden()`／`.text_content()`／`.inner_text()`／`.count()`…）⇒ 違規。
    為什麼：動作送出後前端（Alpine x-show、非同步 fetch 後 render）要過一個影格以上才更新；立刻讀＝賽跑。
    `assert x.is_visible()` 輸給 x-show 一個影格 ⇒ 偶發紅（2026-11-11）；`assert not x.is_visible()` 更糟——更新前就讀到「還沒出現」⇒ **假綠燈**。
  - 「等待」＝ `wait_for`／`wait_for_selector`／`wait_for_function`／`wait_for_url`／`wait_for_load_state`／`wait_for_response`／`wait_for_event`／
    `expect(loc).to_be_*`／`to_have_*`；`with page.expect_response(...)／expect_navigation／expect_popup…:` 區塊**結束後**也算等過（區塊裡的 click 不會讓之後的讀取違規）。
    `expect` 前綴只認 Playwright 的呼叫：裸的 `expect(...)` 與屬性呼叫 `page.expect_response／expect_navigation／expect_popup／expect_download／expect_event／expect_request／expect_file_chooser…`（名單 WAITS）；
    自己寫的 `expected_total()`、`expect_rows(page, 3)`、`helper.expect_rows()` 不是等待。
    **不算等待**：`wait_for_timeout`、`time.sleep`（固定睡眠只是把賽跑拉長，不是同步點）。
    名字含 `wait` 的輔助函式**不是**自動算等待（`_wait_db` 輪詢資料庫、不等畫面）：同檔函式看**內容**——本體有上述真正的等待、而且最後一步不是動作（先等再 click 的不算）；
    或呼叫時傳進去一個會讀 UI 的 lambda（`_wait(lambda: page.locator(..).is_visible())` 輪詢到成立；lambda 只是組出一個 Locator〔永遠為真、立刻返回〕不算）；跨檔的輔助函式只認白名單 `WAIT_HELPER_WHITELIST`。
  - 動作：`fill／check／uncheck／set_checked／type／press_sequentially` 只改自己的值（SYNC_ACTIONS）：之後讀同一個元素的 `input_value()／is_checked()` 確定、不算；
    `clear()`（Python 容器也有）不當動作；`.count(x)` 有引數的是 str／list 的 count，不是 Locator.count()。迴圈體會再掃一遍（上一圈的動作帶進下一圈的開頭）。
  - 豁免：該行（或前一行）有註解 `# e2e-lint: ok <理由>`，理由至少 10 個字 ⇒ 不算違規（例：前面的動作是同步 handler）。
  - 基準 `e2e_lint_baseline.json`：既有違規的 id（檔::函式::讀取名#序號，不含行號）。**只准縮小**——新增違規 ⇒ 紅；
    基準裡有已經不存在的 id（修好了）⇒ 也紅，要求從基準刪掉（`python -m tests.platform._e2e_lint --shrink`），這樣修好的洞不會被拿去藏新的違規。
[已知限制（寫明，不是漏掉）]
  - 輔助函式「裡面」才讀 UI（`assert _vis(page, '#ok')`，`_vis` 內部 is_visible）看不到；`page.evaluate(...)`／`page.content()` 這類讀取不算 READS（誤報太多）。
  - 輔助函式要不要算等待只看同檔；呼叫別檔的輔助函式一律當「沒等」（白名單或豁免註解）。
  - 同一行兩個同名讀取各算一筆（序號依「行、欄」排；`a.is_visible() and b.is_visible()` ⇒ `#1`、`#2`），id 本身不含行號。
  - 基準 id 用「檔::函式::讀取名#序號」：同一函式裡修掉第一個 `is_visible#1`，原本的 `#2` 會變 `#1`（舊的 `#2` 變「已修好」要刪、`#1` 仍在基準）——
    所以修一個要跑一次 `--shrink`；「用同名讀取換掉同函式裡另一個違規」不會被發現（數量不變）；把測試函式改名會讓舊 id 變「已修好」＋新 id 變「新違規」。
  - 分支／例外路徑是保守近似（子區塊裡有動作就當之後仍 pending；子區塊裡等過不代表每條路都等過）。
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
                     "set_input_files", "tap", "hover", "drag_to", "dispatch_event", "set_checked"})
#: 只改自己這個元素的值、不觸發非同步工作的動作（之後讀同一個元素的值是確定的，不算賽跑）
SYNC_ACTIONS = frozenset({"fill", "check", "uncheck", "set_checked", "type", "press_sequentially"})
#: 「元素自己的值」類讀取：只在動作是 SYNC_ACTIONS 時放行
SYNC_READS = frozenset({"input_value", "is_checked"})
#: 讀目前 UI 狀態（不等待、立刻回傳）
READS = frozenset({"is_visible", "is_hidden", "is_enabled", "is_disabled", "is_checked", "is_editable", "text_content", "inner_text",
                   "inner_html", "get_attribute", "input_value", "count", "all_text_contents", "all_inner_texts", "query_selector_all"})
#: 真正的等待（碰到就清掉「剛做完動作」的狀態）；wait_for_timeout 刻意不在內
WAITS = frozenset({"wait_for", "wait_for_selector", "wait_for_function", "wait_for_url", "wait_for_load_state", "wait_for_response",
                   "wait_for_event", "wait_for_request", "expect", "expect_response", "expect_navigation", "expect_download",
                   "expect_popup", "expect_event", "expect_request", "expect_file_chooser", "expect_request_finished"})
_WAIT_PREFIXES = ("wait_for", "to_be_", "to_have_", "to_contain_", "to_match_")
#: 跨檔、內容確認過會真的等畫面的輔助函式（tests/_e2e_login.py、tests/_ui_dialogs.py）
WAIT_HELPER_WHITELIST = frozenset({"wait_logged_in", "wait_dialog"})
_NOT_A_WAIT = frozenset({"wait_for_timeout"})
_OK_COMMENT = re.compile(r"#\s*e2e-lint:\s*ok\s+(\S[^\n]{9,})")
_BROWSER_RE = re.compile(r"\bnew_page\b|sync_playwright|pytest\.mark\.e2e|\be2e_browser\b")
_SKIP_DIRS = ("venv", ".venv", ".venv312", "node_modules", "__pycache__", "site-packages")


def _call_name(node):
    f = node.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return None


def _is_wait_name(name, node=None):
    """真正的等待（名字只要含 wait 不算）。`expect_*` 只認 Playwright 的屬性呼叫（`page.expect_response(...)`）與裸的 `expect(...)`，
    不認自己寫的 `expected_total()`／`expect_rows(...)` 這類函式。node＝該 Call（沒給就只看名字，給 file_waiters 之類用）。"""
    if name is None or name in _NOT_A_WAIT:
        return False
    if name in WAIT_HELPER_WHITELIST:
        return True
    if name.startswith("expect"):
        if name == "expect":
            return True
        return name in WAITS and (node is None or isinstance(node.func, ast.Attribute))
    return name in WAITS or name.startswith(_WAIT_PREFIXES)


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
    """有 `# e2e-lint: ok 理由（≥10 字）` 註解的行號（該行與下一行都豁免）。"""
    ok = set()
    for i, line in enumerate(src.splitlines(), start=1):
        m = _OK_COMMENT.search(line)
        if m and len(m.group(1).strip()) >= 10:
            ok.add(i)
            ok.add(i + 1)
    return ok


def _worse(a, b):
    order = {None: 0, "sync": 1, "async": 2}
    return a if order[a] >= order[b] else b


def _is_expect_with(stmt):
    """`with page.expect_response(...)／expect_navigation／expect_popup…:`——區塊結束時事件已經發生。"""
    if not isinstance(stmt, (ast.With, ast.AsyncWith)):
        return False
    for it in stmt.items:
        for c in _calls_in_order(it.context_expr):
            n = _call_name(c)
            if n and n.startswith("expect_") and isinstance(c.func, ast.Attribute):
                return True
    return False


def _lambda_reads_ui(call):
    """呼叫時傳進去的 lambda 會讀 UI（`_wait(lambda: page.locator(..).is_visible())`）⇒ 那個輔助函式在輪詢畫面。"""
    for a in list(call.args) + [k.value for k in call.keywords]:
        if isinstance(a, ast.Lambda):
            for n in ast.walk(a.body):
                if isinstance(n, ast.Call) and (_call_name(n) in READS or _call_name(n) in ("evaluate", "query_selector")):
                    return True
    return False


def _scan_block(stmts, pending, hits, ok_lines, waiters=frozenset()):
    """pending＝None（沒有）／"sync"（剛做完只改自己值的動作）／"async"（剛做完會觸發非同步工作的動作、還沒等過）。
    回傳區塊結束時的 pending（讓呼叫端接續；子區塊保守：視為可能 pending）。"""
    for stmt in stmts:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue                      # 函式在外層分別掃
        for c in _simple_stmt_calls(stmt):
            name = _call_name(c)
            if name in READS and isinstance(c.func, ast.Attribute):
                if name == "count" and (c.args or c.keywords):
                    continue              # str／list 的 count(x)，不是 Locator.count()
                if pending and c.lineno not in ok_lines and not (pending == "sync" and name in SYNC_READS):
                    hits.append((c.lineno, c.col_offset, name))
            elif _is_wait_name(name, c) or name in waiters or (name and _lambda_reads_ui(c) and "wait" in name.lower()):
                pending = None
            elif name in ACTIONS and isinstance(c.func, ast.Attribute):
                if name in SYNC_ACTIONS:
                    pending = pending or "sync"
                else:
                    pending = "async"
        loop = isinstance(stmt, (ast.For, ast.AsyncFor, ast.While))
        for blk in _blocks(stmt):
            after = _scan_block(blk, pending, hits, ok_lines, waiters)
            if loop and blk is stmt.body:                     # 迴圈體：上一圈留下的 pending 帶進下一圈的開頭
                _scan_block(blk, _worse(pending, after), hits, ok_lines, waiters)
            pending = _worse(pending, after)    # 子區塊裡有動作而沒等 ⇒ 之後仍算 pending；子區塊裡等過不代表每條路都等過
        if _is_expect_with(stmt):
            pending = None
    return pending


def file_waiters(tree):
    """同一個檔案裡「看內容真的會等畫面」的函式名 ⇒ 呼叫它等於等過了。
    條件：本體（含它呼叫的同檔等待函式）有真正的等待，而且最後一步不是動作（先等再 click 的不算）。名字含 wait 不算數。"""
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    waiters = set()
    changed = True
    while changed:
        changed = False
        for name, fn in funcs.items():
            if name in waiters:
                continue
            calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call)]
            if not any(_is_wait_name(_call_name(c), c) or _call_name(c) in waiters for c in calls):
                continue
            end = _scan_block(fn.body, None, [], set(), frozenset(waiters))
            if end is None:
                waiters.add(name)
                changed = True
    return waiters


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
                _scan_block(ch.body, None, hits, ok_lines, frozenset(waiters - {ch.name}))
                seen = {}
                for ln, _col, name in sorted(set(hits)):
                    seen[name] = seen.get(name, 0) + 1
                    out["%s::%s::%s#%d" % (rel, ".".join(q), name, seen[name])] = ln
                visit(ch, q)
            elif isinstance(ch, ast.ClassDef):
                visit(ch, qual + [ch.name])
            else:
                visit(ch, qual)
    visit(tree, [])
    return out


def browser_files():
    """backend 底下「用瀏覽器」的 .py：檔名含 e2e，或內容有 new_page／sync_playwright／pytest.mark.e2e／e2e_browser。"""
    out = []
    for p in sorted(BACKEND.rglob("*.py")):
        rel = p.relative_to(BACKEND)
        if any(part in _SKIP_DIRS or part.startswith(".venv") for part in rel.parts):
            continue
        if "e2e" in p.name.lower() or _BROWSER_RE.search(p.read_text(encoding="utf-8", errors="replace")):
            out.append(p)
    return out


e2e_files = browser_files                                  # 舊名（相容）


def scan_all():
    out = {}
    for p in browser_files():
        rel = p.relative_to(BACKEND).as_posix()
        out.update(scan_source(rel, p.read_text(encoding="utf-8", errors="replace")))
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
