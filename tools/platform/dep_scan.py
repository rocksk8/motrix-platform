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
import contextlib
import json
import re
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
OUT = ROOT / "docs" / "platform" / "dep_graph.json"

# backend 頂層非 router／helper 的模組中，屬於執行期共用能力者（腳本／種子檔不列）
CORE_SKIP_PREFIX = ("sync_", "create_", "fix_", "issue_")
CORE_SKIP_SUFFIX = ("_seed.py", "conftest.py")  # conftest.py：2026-09-25 自 tests/ 上移到 backend/，是測試設定不是產品碼

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
    # L0 平台：backend/core/<file>.py ⇒ plat:<file>（歸 L1）
    for p in sorted((BACKEND / "core").glob("*.py")) if (BACKEND / "core").is_dir() else []:
        if not _docstring_only(p):
            units[f"plat:{p.stem}"] = {"kind": "plat", "path": rel(p)}
    # L2 模組：backend/modules/<key>/<file>.py ⇒ mod:<key>/<file>（整個資料夾歸同一組）
    for d in sorted((BACKEND / "modules").iterdir()) if (BACKEND / "modules").is_dir() else []:
        if not d.is_dir() or d.name.startswith(("_", ".")):
            continue
        for p in sorted(d.glob("*.py")):
            if p.name == "__init__.py" and _docstring_only(p):
                continue
            units[f"mod:{d.name}/{p.stem}"] = {"kind": "mod", "path": rel(p), "module_key": d.name,
                                              "role": _mod_role(p)}
    return units


def _docstring_only(p: Path) -> bool:
    body = parse(p).body
    return all(isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) for n in body)


def _is_router_file(tree: ast.Module) -> bool:
    return any(isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
               and getattr(n.value.func, "id", None) == "APIRouter"
               and any(getattr(t, "id", None) == "router" for t in n.targets)
               for n in tree.body)


def _mod_role(p: Path) -> str:
    if p.name == "__init__.py":
        return "init"
    return "router" if _is_router_file(parse(p)) else "helper"


def _self_pkg(self_name: str) -> tuple[str, str] | None:
    """mod:<key>/<file> ⇒ ("mod", key)；plat:<file> ⇒ ("plat", "")。相對 import 用。"""
    if self_name.startswith("mod:"):
        return "mod", self_name[4:].split("/", 1)[0]
    if self_name.startswith("plat:"):
        return "plat", ""
    return None


def resolve_imports(tree: ast.Module, self_kind: str, reexp: dict[str, str], units: dict,
                    self_name: str = "") -> set[str]:
    deps: set[str] = set()

    def add(u: str):
        if u in units:
            deps.add(u)

    def add_mod(key: str, sub: str | None):
        """modules.<key>[.<sub>]：sub 是檔案就指向它，否則指向套件 __init__。"""
        if sub and f"mod:{key}/{sub}" in units:
            add(f"mod:{key}/{sub}")
        else:
            add(f"mod:{key}/__init__")

    def add_plat(sub: str | None):
        add(f"plat:{sub}" if sub and f"plat:{sub}" in units else "plat:__init__")

    pkg = _self_pkg(self_name)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                parts = a.name.split(".")
                if parts[0] == "modules" and len(parts) > 1:
                    add_mod(parts[1], parts[2] if len(parts) > 2 else None)
                elif parts[0] == "core":
                    add_plat(parts[1] if len(parts) > 1 else None)
                elif parts[0] == "helpers" and len(parts) > 1:
                    add(f"helper:{parts[1]}")
                elif parts[0] == "routers" and len(parts) > 1:
                    add(f"router:{parts[1]}")
                else:
                    add(f"core:{parts[0]}")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level >= 1 and pkg:
                kind, key = pkg
                targets = [mod.split(".")[0]] if mod else [a.name for a in node.names]
                for t in targets:
                    add_mod(key, t) if kind == "mod" else add_plat(t)
                continue
            parts0 = mod.split(".")
            if node.level == 0 and parts0[0] == "modules":
                if len(parts0) >= 3:
                    add_mod(parts0[1], parts0[2])
                elif len(parts0) == 2:
                    for a in node.names:
                        add_mod(parts0[1], a.name)
                else:
                    for a in node.names:
                        add_mod(a.name, None)
                continue
            if node.level == 0 and parts0[0] == "core":
                if len(parts0) >= 2:
                    add_plat(parts0[1])
                else:
                    for a in node.names:
                        add_plat(a.name)
                continue
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

def is_router(u: dict) -> bool:
    return u["kind"] == "router" or (u["kind"] == "mod" and u.get("role") == "router")


def build() -> dict:
    tables = known_tables()
    known = set(tables)
    reexp = helper_reexports()
    units = backend_units()
    units.update(frontend_units())
    main_pre = router_prefixes_from_main()

    all_routes: list[tuple[str, str, re.Pattern]] = []
    for name, u in list(units.items()):
        if u["kind"] not in ("router", "helper", "core", "mod", "plat"):
            continue
        tree = parse(ROOT / u["path"])
        u["imports"] = sorted(resolve_imports(tree, u["kind"], reexp, units, name) - {name})
        r, w, ddl, dyn = sql_tables(string_chunks(tree), known)
        u["tables_r"], u["tables_w"], u["tables_ddl"] = sorted(r - w), sorted(w), sorted(ddl)
        u["dynamic_sql"] = dyn
        # 表名以獨立字串出現（`table="x"` 交給共用 helper 寫）⇒ 讀寫方向不明，另列
        named = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and n.value in known}
        u["tables_named"] = sorted(named - w - ddl)
        if is_router(u):
            stem = name.split(":", 1)[1]
            routes = router_routes(tree, main_pre.get(stem, "") if u["kind"] == "router" else "")
            u["routes"] = routes
            # mod:* 由 L0 模組載入器掛載（core/loader.py），不經 main.py include_router
            u["registered"] = (stem in main_pre) if u["kind"] == "router" else "loader"
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
                same_mod = (d.startswith("mod:") and units[d].get("role") != "router" and start.startswith("mod:")
                            and units[d]["module_key"] == units[start]["module_key"])
                if (d.startswith("helper:") or same_mod) and d not in seen:
                    seen.add(d)
                    stack.append(d)
        return seen

    for name, u in units.items():
        if is_router(u):
            hs = closure(name)
            u["helpers_transitive"] = sorted(hs)
            u["tables_w_transitive"] = sorted(set(u["tables_w"]).union(*[units[h]["tables_w"] for h in hs]))
            u["tables_r_transitive"] = sorted(set(u["tables_r"]).union(*[units[h]["tables_r"] for h in hs]))

    return {"generated_by": "tools/platform/dep_scan.py", "root": ROOT.name, "units": units}


@contextlib.contextmanager
def use_root(root: Path):
    """暫時把掃描根目錄換成 `root`（合成樹的正對照用）；各函式都在呼叫當下才讀這三個全域值。"""
    global ROOT, BACKEND, FRONTEND
    saved = (ROOT, BACKEND, FRONTEND)
    ROOT, BACKEND, FRONTEND = Path(root), Path(root) / "backend", Path(root) / "frontend"
    try:
        yield
    finally:
        ROOT, BACKEND, FRONTEND = saved


# ── 合成樹：正對照不綁任何真實 L2 模組（MODULE-GUIDE：拿掉那個模組，守門不可以跟著失效）──
# 每一個檔案都刻意寫出一種掃描器必須看得懂的寫法；檢查項在 SYNTHETIC_CHECKS。
SYNTHETIC_FILES = {
    "backend/db.py": (
        "# 反向控制：註解裡的 CREATE TABLE IF NOT EXISTS is a no-op 不可以變成表\n"
        "def init_db(conn):\n"
        "    conn.executescript(\"\"\"\n"
        "        CREATE TABLE IF NOT EXISTS zz_items (id INTEGER PRIMARY KEY, name TEXT);\n"
        "        CREATE TABLE IF NOT EXISTS zz_log (id INTEGER PRIMARY KEY);\n"
        "    \"\"\")\n"
        "def get_db():\n    return None\n"),
    "backend/main.py": (
        "from routers import zz_alpha, zz_beta\n"
        "app.include_router(zz_alpha.router)\napp.include_router(zz_beta.router)\n"),
    "backend/helpers/__init__.py": "from .zz_help import zz_fn\n",
    "backend/helpers/zz_help.py": (
        "from db import get_db\n"
        "def zz_fn(conn):\n    conn.execute(\"INSERT INTO zz_items (name) VALUES (?)\", ('x',))\n"),
    "backend/routers/zz_alpha.py": (
        "from fastapi import APIRouter\n"
        "from db import get_db\n"
        "from helpers import zz_fn                      # 經 helpers/__init__ 再匯出\n"
        "from routers.zz_beta import beta_public        # router → router（跨組邊的正對照）\n"
        "router = APIRouter(prefix=\"/api/zz-alpha\")\n"
        "@router.get(\"/items/{item_id}\")\n"
        "def get_item(item_id: int):\n"
        "    sql = f\"UPDATE zz_items SET name=? WHERE id=?\"\n"
        "    write_log(table=\"zz_log\")                  # 表名以參數交給別人寫\n"),
    "backend/routers/zz_beta.py": (
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n"
        "def beta_public():\n    return 1\n"
        "@router.get(\"/api/zz-beta/list\")\n"
        "def lst():\n    return \"SELECT * FROM zz_items\"\n"),
    "backend/core/zz_reg.py": "class Spec:\n    pass\n",
    "backend/modules/zz_mod/__init__.py": (
        "from core.zz_reg import Spec\nfrom modules.zz_mod import api\n"),
    "backend/modules/zz_mod/api.py": (
        "from fastapi import APIRouter\nfrom modules.zz_mod import work\nfrom . import util\n"
        "router = APIRouter()\n@router.get(\"/api/zz-mod/run\")\ndef run():\n    return work.go()\n"),
    "backend/modules/zz_mod/work.py": "def go():\n    return \"DELETE FROM zz_log\"\n",
    "backend/modules/zz_mod/util.py": "X = 1\n",
    "backend/modules/zz_mod/module.json": (
        '{"key": "zz_mod", "tables": ["zz_log"], "provides": {"api_prefixes": ["/api/zz-mod"]}}\n'),
    "frontend/pages/zz.html": (
        "<script src=\"../js/zz.js\"></script>\n<script>\nconst API = '/api'\n"
        "fetch(`${API}/zz-alpha/items/${id}`)\n</script>\n"),
    "frontend/js/zz.js": "fetch('/api/zz-mod/run')\n",
}

#: 合成樹的分組（check-modules 的正對照：zz_alpha → zz_beta 必須被列成跨組邊）
SYNTHETIC_MODULES = {
    "L1": {"units": ["core:db", "core:main", "helper:zz_help", "plat:zz_reg"], "tables": ["zz_items"]},
    "modules": {
        "MA": {"key": "zz_a", "name": "甲", "units": ["router:zz_alpha", "page:pages/zz.html", "js:js/zz.js"],
               "tables": [], "api_prefixes": ["/api/zz-alpha"]},
        "MB": {"key": "zz_b", "name": "乙", "units": ["router:zz_beta"], "tables": [], "api_prefixes": ["/api/zz-beta"]},
        "MC": {"key": "zz_mod", "name": "丙", "units": ["mod:zz_mod/__init__", "mod:zz_mod/api", "mod:zz_mod/work",
                                                    "mod:zz_mod/util"], "tables": ["zz_log"],
               "api_prefixes": ["/api/zz-mod"]},
    },
    "retired": {},
}


def _synthetic_checks(U: dict) -> list[tuple[str, bool]]:
    a = U.get("router:zz_alpha", {})
    return [
        ("router → helper（直接 import 經 __init__ 再匯出）", "helper:zz_help" in a.get("imports", [])),
        ("router → core:db", "core:db" in a.get("imports", [])),
        ("router → router", "router:zz_beta" in a.get("imports", [])),
        ("router 寫表（UPDATE）", "zz_items" in a.get("tables_w", [])),
        ("helper 寫表（INSERT）", "zz_items" in U.get("helper:zz_help", {}).get("tables_w", [])),
        ("router 讀表（SELECT）", "zz_items" in U.get("router:zz_beta", {}).get("tables_r", [])),
        ("表名以參數傳遞（tables_named）", "zz_log" in a.get("tables_named", [])),
        ("router 的 APIRouter prefix", "/api/zz-alpha" in a.get("api_prefixes", [])),
        ("頁面經基底常數＋../js 腳本呼叫到兩支 router",
         {"router:zz_alpha", "mod:zz_mod/api"} <= set(U.get("page:pages/zz.html", {}).get("routers_called_effective", []))),
        ("模組 router 角色與路由", U.get("mod:zz_mod/api", {}).get("role") == "router"
         and "/api/zz-mod" in U.get("mod:zz_mod/api", {}).get("api_prefixes", [])),
        ("模組內 import（modules.<key> 與相對 import）",
         {"mod:zz_mod/work", "mod:zz_mod/util"} <= set(U.get("mod:zz_mod/api", {}).get("imports", []))),
        ("模組 → 平台（core.<file>）", "plat:zz_reg" in U.get("mod:zz_mod/__init__", {}).get("imports", [])),
        ("模組寫表（DELETE）", "zz_log" in U.get("mod:zz_mod/work", {}).get("tables_w", [])),
        ("反向控制：註解不是表（table:IF 不存在）", "table:IF" not in U),
        ("反向控制：沒寫的邊不存在（zz_beta 不 import helper）",
         "helper:zz_help" not in U.get("router:zz_beta", {}).get("imports", [])),
    ]


def build_synthetic(tmp: Path) -> dict:
    for rel_path, text in SYNTHETIC_FILES.items():
        f = tmp / rel_path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    (tmp / "docs" / "platform").mkdir(parents=True, exist_ok=True)
    (tmp / "docs" / "platform" / "modules.json").write_text(
        json.dumps(SYNTHETIC_MODULES, ensure_ascii=False), encoding="utf-8")
    with use_root(tmp):
        return build()


def positive_controls(g: dict | None = None) -> list[str]:
    """掃描器自我檢查：在合成樹上抓得到已知的每一種邊，才有資格報「沒有其他的」。

    ⚠️ 不看真實 repo 的任何 L2 模組（MODULE-GUIDE：正對照不可以綁在特定 L2 上——拿掉那個模組，
    掃描器就會自判不可信，所有依賴它的守門跟著停擺）。`g`（真實圖）只做不綁模組的最低檢查。
    """
    fails = []
    with tempfile.TemporaryDirectory(prefix="dep_scan_synth_") as td:
        tmp = Path(td)
        U = build_synthetic(tmp)["units"]
        fails += [label for label, ok in _synthetic_checks(U) if not ok]
        with use_root(tmp):
            errors, edges = check_modules({"units": U}, tmp / "docs" / "platform" / "modules.json")
        if errors:
            fails.append(f"合成樹的分組應為 0 錯誤，實得 {errors}")
        if "MA router:zz_alpha → MB router:zz_beta" not in edges.get("L2→L2 import", []):
            fails.append("check-modules 未列出已知跨組邊 MA router:zz_alpha → MB router:zz_beta")
    if g is not None:
        # 真實圖：只驗 L0／L1（不隨 L2 模組增刪而變）
        R = g["units"]
        if "core:db" not in R or not any(u["kind"] == "table" for u in R.values()):
            fails.append("真實 repo 掃不到 core:db 或任何資料表（掃描根目錄錯了？）")
    return fails


MODULES = ROOT / "docs" / "platform" / "modules.json"
ASSIGNED_KINDS = ("router", "helper", "core", "page", "js", "mod", "plat")  # 皆須剛好歸屬一組


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


def check_module_folders(U: dict, path: Path = MODULES) -> list[str]:
    """backend/modules/<key>/：①整個資料夾歸同一組 ②該組 key＝資料夾名
    ③module.json 的 tables／provides.api_prefixes 與 modules.json 該組一致。"""
    m = json.loads(path.read_text(encoding="utf-8"))
    by_key = {g["key"]: (gid, g) for gid, g in m["modules"].items()}
    u2g, _, _ = load_groups(path)
    errors = []
    keys = sorted({u["module_key"] for u in U.values() if u["kind"] == "mod"})
    for key in keys:
        groups = {g for n, u in U.items() if u.get("module_key") == key for g in u2g.get(n, [])}
        if len(groups) != 1:
            errors.append(f"modules/{key}/: 資料夾內單位分屬 {sorted(groups) or '無'}（必須同一組）")
        if key not in by_key:
            errors.append(f"modules/{key}/: modules.json 沒有 key={key!r} 的模組（模組 key 必須等於資料夾名）")
            continue
        gid, grp = by_key[key]
        if groups and groups != {gid}:
            errors.append(f"modules/{key}/: 單位歸屬 {sorted(groups)}，但 key={key!r} 是 {gid}")
        mj = BACKEND / "modules" / key / "module.json"
        if not mj.is_file():
            errors.append(f"modules/{key}/module.json 不存在")
            continue
        spec = json.loads(mj.read_text(encoding="utf-8"))
        if spec.get("key") != key:
            errors.append(f"modules/{key}/module.json: key={spec.get('key')!r} ≠ 資料夾名")
        for field, mine, theirs in (
            ("tables", set(spec.get("tables", [])), set(grp.get("tables", []))),
            ("api_prefixes", set(spec.get("provides", {}).get("api_prefixes", [])), set(grp.get("api_prefixes", []))),
        ):
            if mine != theirs:
                errors.append(f"modules/{key}/module.json {field} 與 modules.json {gid} 不一致："
                              f"只在 module.json {sorted(mine - theirs)}；只在 modules.json {sorted(theirs - mine)}")
    return errors


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
    errors += check_module_folders(U, path)

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
        errors, edges = check_modules(g)       # 正對照（合成樹的已知跨組邊）已在 positive_controls 驗過
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
