"""MOTRIX 平台化：backend／frontend 相依掃描器（唯讀）。

用法：
    python tools/platform/dep_scan.py            # 寫出 docs/platform/dep_graph.json
    python tools/platform/dep_scan.py --check    # 只跑正對照，不寫檔

規則：
- 只用 ast.parse 讀原始碼；禁止 import main／routers（會建 DB、寫憑證、跑備份）。
- 表名以 backend 內所有 `CREATE TABLE|VIEW` 為白名單；SQL 關鍵字只認大寫（本 repo 慣例，
  用來排除英文散文裡的 from/update）。
- 正對照失敗 ⇒ exit 2，不寫檔（不可在掃描器壞掉時報「沒有其他相依」）。

單位名稱：
    router:<name>  helper:<name>  core:<module>  page:<file.html>  js:<file.js>  table:<name>
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
OUT = ROOT / "docs" / "platform" / "dep_graph.json"

# backend 頂層非 router／helper 的模組中，屬於執行期共用能力者（腳本／種子檔不列）
CORE_SKIP_PREFIX = ("sync_", "create_", "fix_", "issue_")
CORE_SKIP_SUFFIX = ("_seed.py",)

HTTP_METHODS = {"get", "post", "put", "delete", "patch", "api_route"}

RE_CREATE = re.compile(r"CREATE\s+(?:VIRTUAL\s+)?(?:TABLE|VIEW)\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"`]?(\w+)")
RE_W = [
    re.compile(r"\bINSERT\s+(?:OR\s+[A-Z]+\s+)?INTO\s+[\"`]?(\w+)"),
    re.compile(r"\bREPLACE\s+INTO\s+[\"`]?(\w+)"),
    re.compile(r"\bUPDATE\s+(?:OR\s+[A-Z]+\s+)?[\"`]?(\w+)[\"`]?\s+SET\b"),
    re.compile(r"\bDELETE\s+FROM\s+[\"`]?(\w+)"),
]
RE_DDL = re.compile(r"\b(?:ALTER|DROP)\s+TABLE\s+(?:IF\s+EXISTS\s+)?[\"`]?(\w+)")
RE_R = re.compile(r"\b(?:FROM|JOIN)\s+[\"`]?(\w+)")
RE_DYNAMIC = re.compile(r"\b(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+(?:\{|%s)|\bSET\s+(?:\{|%s)")  # f"... FROM {tbl}"／"SET %s"

RE_API = re.compile(r"""['"`](/api/[^'"`\s?#]*)""")
RE_SCRIPT = re.compile(r"""<script[^>]*\bsrc=['"]([^'"]+)['"]""")


# ───────────────────────── 共用小工具 ─────────────────────────

def rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def parse(p: Path) -> ast.Module:
    return ast.parse(p.read_text(encoding="utf-8-sig"), filename=str(p))


def docstring_ids(tree: ast.AST) -> set[int]:
    """模組／類別／函式的 docstring 與獨立字串敘述（當註解用）⇒ 不當 SQL 掃。"""
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            ids.add(id(node.value))
    return ids


def string_chunks(tree: ast.AST) -> list[str]:
    """所有字串常數；f-string 的插值換成 `{`，相鄰 `+` 串接先合併。"""
    skip = docstring_ids(tree)
    out: list[str] = []

    def flat(n) -> str | None:
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            return n.value
        if isinstance(n, ast.JoinedStr):
            return "".join(v.value if isinstance(v, ast.Constant) else "{" for v in n.values)
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
            a, b = flat(n.left), flat(n.right)
            if a is not None or b is not None:
                return (a or "{") + (b or "{")
        return None

    seen: set[int] = set()
    for node in ast.walk(tree):
        if id(node) in seen or id(node) in skip:
            continue
        if isinstance(node, (ast.BinOp, ast.JoinedStr)):
            s = flat(node)
            if s is not None:
                out.append(s)
                for sub in ast.walk(node):
                    seen.add(id(sub))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append(node.value)
    return out


def sql_tables(chunks: list[str], known: set[str]) -> tuple[set, set, set, bool]:
    r, w, ddl = set(), set(), set()
    dynamic = False
    for s in chunks:
        if not re.search(r"\b(SELECT|INSERT|UPDATE|DELETE|REPLACE|FROM|JOIN|ALTER|DROP)\b", s):
            continue
        if RE_DYNAMIC.search(s):
            dynamic = True
        body = s
        for rx in RE_W:
            for m in rx.finditer(s):
                if m.group(1) in known:
                    w.add(m.group(1))
            body = rx.sub(" ", body)  # DELETE FROM x 不算讀
        for m in RE_DDL.finditer(s):
            if m.group(1) in known:
                ddl.add(m.group(1))
        body = RE_DDL.sub(" ", body)
        for m in RE_R.finditer(body):
            if m.group(1) in known:
                r.add(m.group(1))
    return r, w, ddl, dynamic


# ───────────────────────── backend ─────────────────────────

def known_tables() -> dict[str, str]:
    """table -> 首次 CREATE 的位置 file:line。"""
    tables: dict[str, str] = {}
    for p in sorted(BACKEND.rglob("*.py")):
        if "tests" in p.parts:
            continue
        tree = parse(p)
        skip = docstring_ids(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)) or id(node) in skip:
                continue
            for m in RE_CREATE.finditer(node.value):
                t = m.group(1)
                if t.endswith(("_new", "_old", "_tmp", "_bak")) or t.startswith("_"):
                    continue  # 重建表的暫存名
                line = node.lineno + node.value.count(chr(10), 0, m.start())
                tables.setdefault(t, f"{rel(p)}:{line}")
    return tables


def helper_reexports() -> dict[str, str]:
    """helpers/__init__.py 的 `from .x import a, b` ⇒ {a: x}。"""
    tree = parse(BACKEND / "helpers" / "__init__.py")
    m: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
            for a in node.names:
                m[a.asname or a.name] = node.module.split(".")[0]
    return m


def backend_units() -> dict[str, dict]:
    units: dict[str, dict] = {}
    for p in sorted((BACKEND / "routers").glob("*.py")):
        if p.name != "__init__.py":
            units[f"router:{p.stem}"] = {"kind": "router", "path": rel(p)}
    for p in sorted((BACKEND / "helpers").glob("*.py")):
        if p.name != "__init__.py":
            units[f"helper:{p.stem}"] = {"kind": "helper", "path": rel(p)}
    for p in sorted(BACKEND.glob("*.py")):
        if p.name.startswith(CORE_SKIP_PREFIX) or p.name.endswith(CORE_SKIP_SUFFIX):
            continue
        units[f"core:{p.stem}"] = {"kind": "core", "path": rel(p)}
    return units


def resolve_imports(tree: ast.Module, self_kind: str, reexp: dict[str, str], units: dict) -> set[str]:
    deps: set[str] = set()

    def add(u: str):
        if u in units:
            deps.add(u)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                parts = a.name.split(".")
                if parts[0] == "helpers" and len(parts) > 1:
                    add(f"helper:{parts[1]}")
                elif parts[0] == "routers" and len(parts) > 1:
                    add(f"router:{parts[1]}")
                else:
                    add(f"core:{parts[0]}")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level == 1 and self_kind == "helper":
                if mod:
                    add(f"helper:{mod.split('.')[0]}")
                else:
                    for a in node.names:
                        add(f"helper:{a.name}")
                continue
            parts = mod.split(".")
            if parts[0] == "helpers":
                if len(parts) > 1:
                    add(f"helper:{parts[1]}")
                else:
                    for a in node.names:
                        if f"helper:{a.name}" in units:
                            add(f"helper:{a.name}")
                        elif a.name in reexp:
                            add(f"helper:{reexp[a.name]}")
                        else:
                            add("helper:__init__")
            elif parts[0] == "routers":
                if len(parts) > 1:
                    add(f"router:{parts[1]}")
                else:
                    for a in node.names:
                        add(f"router:{a.name}")
            elif node.level == 0:
                add(f"core:{parts[0]}")
    return deps


def router_prefixes_from_main() -> dict[str, str]:
    tree = parse(BACKEND / "main.py")
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "include_router" and node.args
                and isinstance(node.args[0], ast.Attribute) and isinstance(node.args[0].value, ast.Name)):
            name = node.args[0].value.id
            pre = ""
            for kw in node.keywords:
                if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                    pre = kw.value.value
            out[name] = pre
    return out


def router_routes(tree: ast.Module, main_prefix: str) -> list[dict]:
    own = ""
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and getattr(node.value.func, "id", None) == "APIRouter"):
            for kw in node.value.keywords:
                if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                    own = kw.value.value
    routes = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in node.decorator_list:
            if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                    and d.func.attr in HTTP_METHODS and isinstance(d.func.value, ast.Name)
                    and d.func.value.id == "router" and d.args and isinstance(d.args[0], ast.Constant)):
                routes.append({"method": d.func.attr.upper(), "path": main_prefix + own + d.args[0].value,
                               "func": node.name, "line": node.lineno})
    return routes


def api_prefix(path: str) -> str:
    segs = [s for s in path.split("/") if s]
    return "/" + "/".join(segs[:2]) if len(segs) >= 2 else path


# ───────────────────────── frontend ─────────────────────────

def frontend_units() -> dict[str, dict]:
    units: dict[str, dict] = {}
    for p in sorted(FRONTEND.rglob("*.html")):
        units[f"page:{p.relative_to(FRONTEND).as_posix()}"] = {"kind": "page", "path": rel(p)}
    for p in sorted(FRONTEND.rglob("*.js")):
        if "vendor" in p.parts:
            continue
        units[f"js:{p.relative_to(FRONTEND).as_posix()}"] = {"kind": "js", "path": rel(p)}
    return units


RE_BASE_CONST = re.compile(r"""(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(['"`])(/api[^'"`]*|)\2""")


def base_consts(text: str) -> dict[str, str]:
    """`const API = '/api'` 這類 URL 基底常數（30 頁用這個寫法，不代入就全部漏掉）。"""
    return {m.group(1): m.group(3) for m in RE_BASE_CONST.finditer(text)}


def substitute_bases(text: str, consts: dict[str, str]) -> str:
    for name, val in consts.items():
        n = re.escape(name)
        text = re.sub(r"\$\{\s*" + n + r"\s*\}", lambda m: val, text)             # `${API}/x`
        text = re.sub(r"(?<![\w$.])" + n + r"\s*\+\s*(['\"`])", lambda m: m.group(1) + val, text)  # API + '/x'
    return text


def fe_scan(p: Path, extra_consts: dict[str, str] | None = None) -> tuple[list[str], list[str]]:
    raw = p.read_text(encoding="utf-8-sig", errors="replace")
    consts = dict(extra_consts or {})
    consts.update(base_consts(raw))
    text = substitute_bases(raw, consts)
    # `${this.x((...)}` 巢狀插值 ⇒ 截在殘留的第一個 `$`，後段交給前綴比對
    calls = sorted({re.sub(r"\$\{[^}]*\}", "{}", m.group(1)).split("$", 1)[0] for m in RE_API.finditer(text)})
    scripts = []
    if p.suffix == ".html":
        for m in RE_SCRIPT.finditer(text):
            src = (p.parent / m.group(1)).resolve()
            try:
                key = "js:" + src.relative_to(FRONTEND.resolve()).as_posix()
            except ValueError:
                continue
            if "vendor" not in key:
                scripts.append(key)
    return calls, scripts


def route_regex(path: str) -> re.Pattern:
    parts = []
    for seg in path.strip("/").split("/"):
        parts.append(r"[^/]+" if seg.startswith("{") else re.escape(seg))
    return re.compile("^/" + "/".join(parts) + "$")


def match_call(call: str, routes: list[tuple[str, str, re.Pattern]]) -> set[str]:
    """前端路徑字串 ⇒ 服務它的 router。`{}` 視為任意段；字串以 / 結尾或被截斷時比前綴。"""
    c = call.rstrip("/")
    hits = set()
    csegs = c.strip("/").split("/")
    for unit, rpath, rx in routes:
        rsegs = rpath.strip("/").split("/")
        # 完整比對
        probe = "/" + "/".join("X" if s in ("{}", "") else s for s in csegs)
        if rx.match(probe):
            hits.add(unit)
            continue
        # 前綴比對（`'/api/x/' + id` 這類被截斷的字串）
        if call.endswith("/") or "{}" in csegs[-1]:
            n = len(csegs)
            if len(rsegs) > n - (0 if call.endswith("/") else 1):
                ok = all(cs in ("{}",) or cs == rs or rs.startswith("{") or "{}" in cs
                         for cs, rs in zip(csegs, rsegs))
                if ok:
                    hits.add(unit)
    return hits


# ───────────────────────── 主流程 ─────────────────────────

def build() -> dict:
    tables = known_tables()
    known = set(tables)
    reexp = helper_reexports()
    units = backend_units()
    units.update(frontend_units())
    main_pre = router_prefixes_from_main()

    all_routes: list[tuple[str, str, re.Pattern]] = []
    for name, u in list(units.items()):
        if u["kind"] not in ("router", "helper", "core"):
            continue
        tree = parse(ROOT / u["path"])
        u["imports"] = sorted(resolve_imports(tree, u["kind"], reexp, units) - {name})
        r, w, ddl, dyn = sql_tables(string_chunks(tree), known)
        u["tables_r"], u["tables_w"], u["tables_ddl"] = sorted(r - w), sorted(w), sorted(ddl)
        u["dynamic_sql"] = dyn
        # 表名以獨立字串出現（`table="x"` 交給共用 helper 寫）⇒ 讀寫方向不明，另列
        named = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and n.value in known}
        u["tables_named"] = sorted(named - w - ddl)
        if u["kind"] == "router":
            stem = name.split(":", 1)[1]
            routes = router_routes(tree, main_pre.get(stem, ""))
            u["routes"] = routes
            u["registered"] = stem in main_pre
            u["api_prefixes"] = sorted({api_prefix(x["path"]) for x in routes})
            for x in routes:
                all_routes.append((name, x["path"], route_regex(x["path"])))
        else:
            u["api_prefixes"] = []

    # js 檔的基底常數可能定義在引用它的頁面裡 ⇒ 先收頁面常數
    page_consts: dict[str, dict[str, str]] = defaultdict(dict)
    for name, u in units.items():
        if u["kind"] == "page":
            raw = (ROOT / u["path"]).read_text(encoding="utf-8-sig", errors="replace")
            c = base_consts(raw)
            for s in fe_scan(ROOT / u["path"])[1]:
                page_consts[s].update(c)

    for name, u in units.items():
        if u["kind"] not in ("page", "js"):
            continue
        calls, scripts = fe_scan(ROOT / u["path"], page_consts.get(name))
        u["imports"] = sorted(s for s in scripts if s in units)
        u["tables_r"], u["tables_w"] = [], []
        u["api_calls"] = calls
        u["api_prefixes"] = sorted({api_prefix(c) for c in calls})
        hit = set()
        unmatched = []
        for c in calls:
            h = match_call(c, all_routes)
            hit |= h
            if not h:
                unmatched.append(c)
        u["routers_called"] = sorted(hit)
        u["api_unmatched"] = unmatched

    # 頁面的有效呼叫＝自身＋其 ../js/ 腳本（../static/ 共用殼另列，不併入）
    for name, u in units.items():
        if u["kind"] == "page":
            eff = set(u["routers_called"])
            for s in u["imports"]:
                if s.startswith("js:js/"):
                    eff |= set(units[s]["routers_called"])
            u["routers_called_effective"] = sorted(eff)

    # 表單位
    writers, readers, named_by = defaultdict(set), defaultdict(set), defaultdict(set)
    for name, u in units.items():
        for t in u.get("tables_w", []):
            writers[t].add(name)
        for t in u.get("tables_r", []):
            readers[t].add(name)
        for t in u.get("tables_named", []):
            named_by[t].add(name)
    for t, loc in sorted(tables.items()):
        units[f"table:{t}"] = {
            "kind": "table", "path": loc, "imports": [], "tables_r": [], "tables_w": [], "api_prefixes": [],
            "writers": sorted(writers[t]), "readers": sorted(readers[t]), "named_by": sorted(named_by[t]),
        }

    # router 的遞移表（router → helper 閉包，不跨 router）
    def closure(start: str) -> set[str]:
        seen, stack = set(), [start]
        while stack:
            n = stack.pop()
            for d in units[n].get("imports", []):
                if d.startswith("helper:") and d not in seen:
                    seen.add(d)
                    stack.append(d)
        return seen

    for name, u in units.items():
        if u["kind"] == "router":
            hs = closure(name)
            u["helpers_transitive"] = sorted(hs)
            u["tables_w_transitive"] = sorted(set(u["tables_w"]).union(*[units[h]["tables_w"] for h in hs]))
            u["tables_r_transitive"] = sorted(set(u["tables_r"]).union(*[units[h]["tables_r"] for h in hs]))

    return {"generated_by": "tools/platform/dep_scan.py", "root": ROOT.name, "units": units}


def positive_controls(g: dict) -> list[str]:
    """已知存在的相依必須被抓到；抓不到＝掃描器壞了。"""
    U = g["units"]
    fails = []
    checks = [
        # routers/quotations.py:15 `from helpers.quotations import begin_write, write_txn`
        ("router:quotations imports helper:quotations", "helper:quotations" in U["router:quotations"]["imports"]),
        # `from helpers import (...)` 經 __init__ 再匯出解析：quotations 用 _audit ⇒ helper:audit
        ("router:quotations imports helper:audit (via __init__ re-export)", "helper:audit" in U["router:quotations"]["imports"]),
        ("router:quotations imports core:db", "core:db" in U["router:quotations"]["imports"]),
        ("router:quotations writes table quotations", "quotations" in U["router:quotations"]["tables_w"]),
        ("table users exists", "table:users" in U),
        ("page:pages/quotations.html calls router:quotations",
         "router:quotations" in U["page:pages/quotations.html"]["routers_called_effective"]),
        ("router:auth serves /api/auth", "/api/auth" in U["router:auth"]["api_prefixes"]),
        # routers/vouchers.py `table="voucher_edit_log"` 交給 helpers/edit_log 寫
        ("router:vouchers names table voucher_edit_log", "voucher_edit_log" in U["router:vouchers"]["tables_named"]),
        # 反向控制：db.py:425 註解「CREATE TABLE IF NOT EXISTS is a no-op」不可變成表
        ("comment text is not a table (table:IF absent)", "table:IF" not in U),
    ]
    for label, ok in checks:
        if not ok:
            fails.append(label)
    return fails


MODULES = ROOT / "docs" / "platform" / "modules.json"
ASSIGNED_KINDS = ("router", "helper", "core", "page", "js")  # 皆須剛好歸屬一組（派工最低要求為 router/helper/page）


def load_groups(path: Path = MODULES) -> tuple[dict[str, list[str]], dict[str, list[str]], set[str]]:
    """modules.json ⇒ (unit→[群組…], table→[群組…], L2 群組集合)。群組名：L1／M01…／retired:M09。"""
    m = json.loads(path.read_text(encoding="utf-8"))
    groups = {"L1": m["L1"]}
    groups.update(m["modules"])
    groups.update({f"retired:{k}": v for k, v in m.get("retired", {}).items()})
    u2g, t2g = defaultdict(list), defaultdict(list)
    for gname, g in groups.items():
        for u in g.get("units", []):
            u2g[u].append(gname)
        for t in g.get("tables", []):
            t2g[t].append(gname)
    return u2g, t2g, set(m["modules"])


def check_modules(g: dict, path: Path = MODULES) -> tuple[list[str], dict[str, list[str]]]:
    """①歸屬檢查（錯誤）②跨群組邊清單（只列，不失敗）。"""
    U = g["units"]
    u2g, t2g, l2 = load_groups(path)
    errors: list[str] = []
    for n, u in sorted(U.items()):
        if u["kind"] in ASSIGNED_KINDS and len(u2g.get(n, [])) != 1:
            label = "未歸屬" if not u2g.get(n) else f"重複歸屬 {u2g[n]}"
            errors.append(f"{n}: {label}")
    for n in sorted(u2g):
        if n not in U:
            errors.append(f"{n}: modules.json 列了，但掃描不到（過期）")

    edges: dict[str, list[str]] = defaultdict(list)
    grp = lambda n: (u2g.get(n) or ["?"])[0]
    for n, u in sorted(U.items()):
        src = grp(n)
        if src == "?":
            continue
        deps = [(d, "import") for d in u.get("imports", [])]
        deps += [(d, "api") for d in u.get("routers_called", [])]
        for d, how in deps:
            dst = grp(d)
            if dst == src or dst == "?":
                continue
            if n == "core:main" and d.startswith("router:"):
                edges["載入器 main→router（預期；待模組載入器取代）"].append(f"{dst} {d}")
            elif src in l2 and dst in l2:
                edges[f"L2→L2 {how}"].append(f"{src} {n} → {dst} {d}")
            elif src == "L1" and dst in l2:
                edges[f"L1→L2 {how}（逆向）"].append(f"{n} → {dst} {d}")
            elif dst.startswith("retired:"):
                edges[f"→退役 {how}"].append(f"{src} {n} → {dst} {d}")
    warnings = []
    for n, u in sorted(U.items()):
        if u["kind"] == "table" and len(t2g.get(n[6:], [])) != 1:
            warnings.append(f"{n}: 表歸屬 {t2g.get(n[6:]) or '無'}")
    for t in sorted(t2g):
        if f"table:{t}" not in U:
            warnings.append(f"table:{t}: modules.json 列了，但掃描不到")
    edges["表歸屬警告（不失敗）"] = warnings
    return errors, edges


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只跑正對照")
    ap.add_argument("--check-modules", action="store_true",
                    help="驗 modules.json：router/helper/page 各歸屬一組（失敗 exit 1）；列出跨組邊（不失敗）")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    g = build()
    fails = positive_controls(g)
    if fails:
        print("正對照失敗（掃描器不可信，不寫檔）：", *fails, sep="\n  ", file=sys.stderr)
        return 2
    print(f"正對照 OK；units={len(g['units'])}")
    if a.check_modules:
        errors, edges = check_modules(g)
        # 正對照：routers/accounting_export.py:76 `from routers.reports import …`（M06→M08）必須出現在清單裡
        known = "M06 router:accounting_export → M08 router:reports"
        if not any(e == known for e in edges.get("L2→L2 import", [])):
            print(f"正對照失敗：跨組邊清單缺已知邊「{known}」", file=sys.stderr)
            return 2
        for k, v in edges.items():
            print(f"\n== {k}：{len(v)}")
            for e in v:
                print("  " + e)
        print(f"\n== 歸屬錯誤：{len(errors)}")
        for e in errors:
            print("  " + e)
        return 1 if errors else 0
    if not a.check:
        out = Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(g, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"寫出 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
