# -*- coding: utf-8 -*-
"""測試衛生靜態盤點（唯讀）。python hyg.py <repo> → 輸出 JSON 到 %TEMP%\da_hyg.json"""
import ast, hashlib, json, os, re, sys, tempfile
from collections import defaultdict
from pathlib import Path

REPO = Path(sys.argv[1]); B = REPO / "backend"
tests = sorted(p for p in B.rglob("test_*.py") if ".venv" not in str(p) and "__pycache__" not in str(p))
rel = lambda p: str(p.relative_to(REPO)).replace("\\", "/")
OUT = {"n_test_files": len(tests)}

def parse(p):
    try:
        return ast.parse(p.read_text(encoding="utf-8-sig"))
    except Exception as e:  # noqa
        return None

# ───────── (1) skip / xfail 靜態清單 ─────────
skips = []
def src(node, text):
    try: return ast.get_source_segment(text, node) or ""
    except Exception: return ""
for p in tests:
    t = p.read_text(encoding="utf-8-sig"); tree = parse(p)
    if not tree: continue
    for n in ast.walk(tree):
        kind = None; cond = ""; reason = ""
        if isinstance(n, ast.Call):
            f = src(n.func, t)
            if f in ("pytest.mark.skip", "pytest.mark.skipif", "pytest.mark.xfail", "pytest.skip", "pytest.importorskip", "pytest.xfail", "requires_module", "_requires.requires_module"):
                kind = f
                if f.endswith("skipif") and n.args: cond = src(n.args[0], t)
                for k in n.keywords:
                    if k.arg == "reason": reason = src(k.value, t)
                if not reason and n.args and f in ("pytest.skip", "pytest.mark.skip"): reason = src(n.args[0], t)
                if f == "pytest.importorskip" and n.args: cond = src(n.args[0], t)
                if f.endswith("requires_module"): cond = ",".join(src(a, t) for a in n.args[:3])
        if kind:
            skips.append({"file": rel(p), "line": n.lineno, "kind": kind, "cond": cond[:140], "reason": reason[:160]})
OUT["skips"] = skips

# ───────── 路由表 ─────────
routes = []
route_re = re.compile(r'@(?:router|app|[A-Za-z_]+_router)\.(?:get|post|put|patch|delete|api_route)\(\s*[rf]?["\']([^"\']*)["\']')
pref_re = re.compile(r'APIRouter\([^)]*prefix\s*=\s*["\']([^"\']*)["\']')
for p in B.rglob("*.py"):
    s = str(p)
    if "/tests/" in s.replace("\\", "/") or "test_" in p.name or ".venv" in s or "__pycache__" in s: continue
    try: t = p.read_text(encoding="utf-8-sig")
    except Exception: continue
    pm = pref_re.search(t); pre = pm.group(1) if pm else ""
    for m in route_re.finditer(t):
        routes.append(pre + m.group(1))
def tmpl_to_re(r):
    r = re.sub(r"\{[^}]*\}", "§", r)
    return re.compile("^" + re.escape(r).replace("§", "[^/]+") + "/?$")
route_res = [tmpl_to_re(r) for r in set(routes)]
OUT["n_routes"] = len(set(routes))
ROUTE_PAIRS = [(r, tmpl_to_re(r)) for r in set(routes)]
ROUTE_FIRST = sorted({r.split("{")[0].rstrip("/") for r in routes if r.split("{")[0].rstrip("/")})

# ───────── (2) 引用的對象不存在 ─────────
def module_file(dotted):
    parts = dotted.split(".")
    for base in (B,):
        f = base.joinpath(*parts)
        if f.with_suffix(".py").exists(): return f.with_suffix(".py")
        if (f / "__init__.py").exists(): return f / "__init__.py"
        if f.is_dir(): return f
    return None
TOPS = {p.name[:-3] for p in B.glob("*.py")} | {p.name for p in B.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
def defined_names(mf):
    if mf is None or mf.is_dir(): return None
    t = parse(mf)
    if not t: return None
    names = set()
    for n in t.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): names.add(n.name)
        elif isinstance(n, (ast.Assign, ast.AnnAssign)):
            for tg in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                for x in ast.walk(tg):
                    if isinstance(x, ast.Name): names.add(x.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names: names.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, (ast.If, ast.Try, ast.With)):
            for x in ast.walk(n):
                if isinstance(x, (ast.FunctionDef, ast.ClassDef)): names.add(x.name)
                elif isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store): names.add(x.id)
                elif isinstance(x, (ast.Import, ast.ImportFrom)):
                    for a in x.names: names.add((a.asname or a.name).split(".")[0])
    if any(isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names) for n in t.body): return None   # 星號匯入：無法判斷
    return names
dang_imp, dang_name = [], []
cache = {}
for p in tests:
    tree = parse(p)
    if not tree: continue
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            top = n.module.split(".")[0]
            if top not in TOPS and top not in ("tests",): continue
            if n.module.startswith("tests"):
                mf = module_file(n.module)
            else:
                mf = module_file(n.module)
            if mf is None:
                dang_imp.append((rel(p), n.lineno, n.module)); continue
            if mf not in cache: cache[mf] = defined_names(mf)
            dn = cache[mf]
            if dn is None: continue
            for a in n.names:
                if a.name == "*": continue
                if a.name in dn: continue
                sub = module_file(n.module + "." + a.name)
                if sub is not None: continue
                dang_name.append((rel(p), n.lineno, n.module, a.name))
        elif isinstance(n, ast.Import):
            for a in n.names:
                top = a.name.split(".")[0]
                if top in TOPS and module_file(a.name) is None:
                    dang_imp.append((rel(p), n.lineno, a.name))
OUT["dangling_imports"] = dang_imp; OUT["dangling_names"] = dang_name
# importlib / 字串模組名
str_mod = []
for p in tests:
    t = p.read_text(encoding="utf-8-sig")
    for m in re.finditer(r'import_module\(\s*["\']([\w\.]+)["\']', t):
        if m.group(1).split(".")[0] in TOPS and module_file(m.group(1)) is None: str_mod.append((rel(p), m.group(1)))
OUT["dangling_import_module_strings"] = str_mod
# 端點字串
lit_re = re.compile(r'["\'](/api/[A-Za-z0-9_\-/%\{\}\.\$]+)')
dang_ep = defaultdict(list)
for p in tests:
    t = p.read_text(encoding="utf-8-sig")
    for m in lit_re.finditer(t):
        raw = m.group(1)
        path = re.sub(r"%[sd]|\{[^}]*\}|\$\{[^}]*\}", "§", raw).rstrip("/")
        if path in ("/api", "/api/") or "§" == path[-1:] and path.count("/") <= 2: continue
        cand = re.compile("^" + re.escape(path).replace("§", "[^/]+") + "/?$")
        probe = path.replace("§", "x")
        ok = any(rr.match(probe) for _r, rr in ROUTE_PAIRS)
        if not ok:
            # 前綴放寬：測試可能只引用到前綴（例如 /api/foo/）
            if any(r.startswith(path) for r in ROUTE_FIRST) or any(path.startswith(f) for f in ROUTE_FIRST):
                continue
            dang_ep[raw].append(rel(p))
OUT["dangling_endpoints"] = {k: sorted(set(v)) for k, v in dang_ep.items()}
# 頁面／js
FRONT = REPO / "frontend"
pages = {p.name for p in (FRONT / "pages").glob("*.html")} if (FRONT / "pages").exists() else set()
jsf = {p.name for p in FRONT.rglob("*.js")}
dang_pg, dang_js = defaultdict(list), defaultdict(list)
for p in tests:
    t = p.read_text(encoding="utf-8-sig")
    for m in re.finditer(r'["\'/]((?:[\w\-]+)\.html)\b', t):
        n = m.group(1)
        if n not in pages and not (FRONT / n).exists() and not n.startswith("test"): dang_pg[n].append(rel(p))
    for m in re.finditer(r'["\'/]((?:[\w\-]+)\.js)\b', t):
        n = m.group(1)
        if n not in jsf and n not in ("conftest.js",): dang_js[n].append(rel(p))
OUT["dangling_pages"] = {k: sorted(set(v)) for k, v in dang_pg.items()}
OUT["dangling_js"] = {k: sorted(set(v)) for k, v in dang_js.items()}

# ───────── (3) 無效測試（靜態） ─────────
HELP = re.compile(r"^(_?assert|_?expect|_?check|_?verify|_?must|_?ensure|_?require|_?same|_?is_)", re.I)
noassert, tauto, swallow = [], [], []
for p in tests:
    t = p.read_text(encoding="utf-8-sig"); tree = parse(p)
    if not tree: continue
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name.startswith("test")]:
        has = False; calls_help = False
        for x in ast.walk(fn):
            if isinstance(x, ast.Assert):
                has = True
                tt = x.test
                if isinstance(tt, ast.Constant) and tt.value: tauto.append((rel(p), fn.name, x.lineno, "assert const"))
                if isinstance(tt, ast.Compare) and len(tt.ops) == 1 and isinstance(tt.ops[0], (ast.Eq, ast.Is)) and ast.dump(tt.left) == ast.dump(tt.comparators[0]):
                    tauto.append((rel(p), fn.name, x.lineno, "assert x == x"))
            if isinstance(x, ast.With):
                for it in x.items:
                    if "raises" in src(it.context_expr, t) or "warns" in src(it.context_expr, t): has = True
            if isinstance(x, ast.Call):
                nm = src(x.func, t).split(".")[-1]
                if HELP.match(nm) or "raises" in nm or nm in ("fail", "xfail"): calls_help = True
            if isinstance(x, ast.Try):
                body_has_assert = any(isinstance(y, ast.Assert) for b in x.body for y in ast.walk(b))
                for h in x.handlers:
                    swallowed = all(isinstance(s, (ast.Pass, ast.Continue)) or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)) for s in h.body)
                    broad = h.type is None or src(h.type, t) in ("Exception", "BaseException", "AssertionError")
                    if body_has_assert and swallowed and broad: swallow.append((rel(p), fn.name, x.lineno))
        # fixture 內含斷言的測試（例如 page fixture yield 後 assert）不算
        if not has and not calls_help:
            deco = " ".join(src(d, t) for d in fn.decorator_list)
            noassert.append((rel(p), fn.name, fn.lineno, "param" if "parametrize" in deco else ""))
OUT["no_assert_tests"] = noassert; OUT["tautologies"] = tauto; OUT["swallowed_asserts"] = swallow

# ───────── (4) 重複覆蓋：函式本體正規化後完全相同、跨檔 ─────────
def norm_body(fn, t):
    s = ast.get_source_segment(t, fn) or ""
    s = re.sub(r"#.*", "", s); s = re.sub(r'""".*?"""', "", s, flags=re.S)
    s = re.sub(r"def test\w+", "def T", s); s = re.sub(r"\s+", " ", s)
    return s
bodies = defaultdict(list)
for p in tests:
    t = p.read_text(encoding="utf-8-sig"); tree = parse(p)
    if not tree: continue
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name.startswith("test")]:
        s = norm_body(fn, t)
        if len(s) > 120: bodies[hashlib.sha1(s.encode()).hexdigest()].append((rel(p), fn.name))
dups = [v for v in bodies.values() if len({f for f, _ in v}) > 1]
OUT["duplicate_bodies"] = dups
# 檔名只差日期／副本的測試檔
byname = defaultdict(list)
for p in tests: byname[re.sub(r"_\d{4}_\d{2}_\d{2}", "", p.name).replace("_from_tests", "")].append(rel(p))
OUT["same_stem_files"] = {k: v for k, v in byname.items() if len(v) > 1}

# ───────── (5) 時間（author_gate_times.json） ─────────
tm = json.load(open(REPO / "tools/platform/author_gate_times.json", encoding="utf-8"))
files = tm.get("files") or {}
rows = sorted(((v if isinstance(v, (int, float)) else (v.get("seconds") or v.get("s") or 0), k) for k, v in files.items()), reverse=True)
OUT["slowest"] = rows[:40]; OUT["times_meta"] = {k: tm[k] for k in tm if k != "files"}
# ───────── test_map ─────────
tmap = json.load(open(REPO / "docs/platform/test_map.json", encoding="utf-8"))
OUT["unmapped"] = tmap.get("unmapped"); OUT["test_map_summary"] = tmap.get("summary")
json.dump(OUT, open(os.path.join(tempfile.gettempdir(), "da_hyg.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
print({k: (len(v) if hasattr(v, "__len__") else v) for k, v in OUT.items()})
