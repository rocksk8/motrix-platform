"""測試檔 → 被測單位 對照表（靜態分析，不 import、不執行測試）。

用法：
  python tools/platform/test_map.py                 產出 docs/platform/test_map.json
  python tools/platform/test_map.py --stdout        印出不寫檔
  python tools/platform/test_map.py --check         與已提交的 test_map.json 比對，不同 ⇒ exit 1

單位命名同 dep_graph.json（router:/helper:/core:/page:/js:/mod:<key>/<file>/plat:），其餘 file:<路徑>、dir:<目錄>/。對應來源：
  import     import／from ... import（backend 模組、tests 內的共用檔與被引用的測試檔）
  api        字串中的 /api/... 路徑對到 router 的路由表（@router.xxx＋APIRouter/include_router prefix）
  page       字串中出現的 frontend 頁面／js／css 檔名
  path       以 Path / 或 os.path.join 拼出的 repo 路徑（稽核類測試讀原始碼）
對不到任何單位 ⇒ kind 照填、units 空、列入 unmapped；不猜。
"""
import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BACKEND = "backend"
TESTS_DIR = "backend/tests"
OUT = REPO / "docs" / "platform" / "test_map.json"

HTTP_METHODS = {"get", "post", "put", "delete", "patch", "api_route", "websocket"}
_API_RE = re.compile(r"^/api(/|$)")
_MOD_TEST_RE = re.compile(r"^backend/modules/([^/]+)/tests/")
AUTH_ROUTER = "backend/routers/auth.py"
_LOGIN_SEGS = ("api", "auth", "login")
_AUTH_TEST_NAME = re.compile(r"auth|login|session|totp|webauthn|passkey|password", re.I)
_DOTTED_RE = re.compile(r"(?:routers|helpers|tests|core|modules|platform)(?:\.[A-Za-z_][A-Za-z0-9_]*)+")
_FMT_RE = re.compile(r"%[sdr]|\{[^/{}]*\}")
_ASSET_RE = re.compile(r"[\w\-./]*?[\w\-]+\.(?:html|js|css)\b")


def tracked_files():
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"], capture_output=True, check=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def _parse(path):
    try:
        return ast.parse((REPO / path).read_text(encoding="utf-8-sig"), filename=path)
    except (SyntaxError, UnicodeDecodeError, OSError):
        return None


# ── 單位命名（與 tools/platform/dep_scan.py 一致）────────────────────────────

def _dep_scan_consts():
    """core: 的排除規則以 dep_scan.py 為唯一來源（不複製常數，免得兩邊漂移）。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_dep_scan_consts", Path(__file__).with_name("dep_scan.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return tuple(mod.CORE_SKIP_PREFIX), tuple(mod.CORE_SKIP_SUFFIX)


_CORE_SKIP_PREFIX, _CORE_SKIP_SUFFIX = _dep_scan_consts()


def unit_name(path):
    """repo 相對路徑 → 單位名。dep_scan 沒有的單位用 file:／dir: 前綴。"""
    if path.endswith("/"):
        return "dir:" + path
    parts = path.split("/")
    name = parts[-1]
    if len(parts) == 3 and parts[0] == BACKEND and parts[1] in ("routers", "helpers") \
            and name.endswith(".py") and name != "__init__.py":
        return ("router:" if parts[1] == "routers" else "helper:") + name[:-3]
    if len(parts) >= 4 and parts[:2] == [BACKEND, "modules"] and name.endswith(".py"):
        return "mod:%s/%s" % (parts[2], "/".join(parts[3:])[:-3])        # mod:<key>/<file>
    if len(parts) == 3 and parts[:2] == [BACKEND, "core"] and name.endswith(".py"):
        return "plat:" + name[:-3]                                          # L0 平台
    if len(parts) == 2 and parts[0] == BACKEND and name.endswith(".py") \
            and not name.startswith(_CORE_SKIP_PREFIX) and not name.endswith(_CORE_SKIP_SUFFIX):
        return "core:" + name[:-3]
    if parts[0] == "frontend" and len(parts) > 1:
        sub = "/".join(parts[1:])
        if name.endswith(".html"):
            return "page:" + sub
        if name.endswith(".js") and "vendor" not in parts:
            return "js:" + sub
    return "file:" + path


# ── 路由表 ────────────────────────────────────────────────────────────────

def _router_prefix(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            f = node.value.func
            if getattr(f, "id", None) == "APIRouter" or getattr(f, "attr", None) == "APIRouter":
                for kw in node.value.keywords:
                    if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                        return kw.value.value
    return ""


def _include_prefixes(main_tree):
    """main.py：include_router(x.router, prefix="...") ⇒ {x: prefix}"""
    res = {}
    for node in ast.walk(main_tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "include_router" and node.args:
            a = node.args[0]
            if isinstance(a, ast.Attribute) and isinstance(a.value, ast.Name):
                for kw in node.keywords:
                    if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                        res[a.value.id] = kw.value.value
    return res


def build_routes(files):
    """[(segments, method, owner_file)]；segment 為 None 表示路徑參數。"""
    main = f"{BACKEND}/main.py"
    main_tree = _parse(main)
    inc = _include_prefixes(main_tree) if main_tree else {}
    routes = []
    sources = [p for p in files if p.endswith(".py") and p.startswith((f"{BACKEND}/routers/", f"{BACKEND}/modules/"))]
    sources.append(main)
    for path in sources:
        tree = _parse(path)
        if tree is None:
            continue
        prefix = inc.get(Path(path).stem, "") + (_router_prefix(tree) if path != main else "")
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for d in node.decorator_list:
                if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                        and d.func.attr in HTTP_METHODS and d.args
                        and isinstance(d.args[0], ast.Constant) and isinstance(d.args[0].value, str)):
                    full = prefix + d.args[0].value
                    routes.append((_route_segments(full), d.func.attr, path))
    return routes


def _route_segments(p):
    return [None if (s.startswith("{") and s.endswith("}")) else s for s in p.strip("/").split("/")]


# ── 測試檔掃描 ────────────────────────────────────────────────────────────

class _Scan(ast.NodeVisitor):
    def __init__(self):
        self.imports = set()           # dotted names
        self.strings = []              # 完整字串常數
        self.fstrings = []             # [(parts)]：str 或 None（插值）
        self.path_frags = []           # Path / os.path.join 拼出的片段
        self.glob_dirs = []            # 被 glob/rglob/iterdir 的片段
        self.consts = {}               # 模組層 NAME = "str"
        self.flags = set()

    # imports
    def visit_Import(self, node):
        for a in node.names:
            self.imports.add(a.name)

    def visit_ImportFrom(self, node):
        if node.level == 0 and node.module:
            self.imports.add(node.module)
            for a in node.names:
                self.imports.add(f"{node.module}.{a.name}")

    def visit_Assign(self, node):
        if (len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            self.consts[node.targets[0].id] = node.value.value
        self.generic_visit(node)

    def visit_Constant(self, node):
        if isinstance(node.value, str):
            self.strings.append(node.value)

    def visit_JoinedStr(self, node):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                parts.append(v.value)
            elif isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Name):
                parts.append(("name", v.value.id))
            else:
                parts.append(None)
        self.fstrings.append(parts)
        self.generic_visit(node)

    def visit_BinOp(self, node):
        if isinstance(node.op, ast.Div):
            frag = _flatten_div(node)
            if frag:
                self.path_frags.append(frag)
        elif isinstance(node.op, ast.Add):
            # "/api/x/" + id ⇒ 視為 f-string
            parts = _flatten_add(node)
            if parts and any(isinstance(p, str) for p in parts):
                self.fstrings.append(parts)
        self.generic_visit(node)

    def visit_Call(self, node):
        f = node.func
        name = getattr(f, "attr", None) or getattr(f, "id", None)
        if name == "join" or name in ("Path", "PurePath"):
            strs = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            if strs:
                self.path_frags.append("/".join(strs))
        if name in ("glob", "rglob", "iterdir") and isinstance(f, ast.Attribute):
            frag = _flatten_div(f.value) if isinstance(f.value, ast.BinOp) else None
            if frag:
                self.glob_dirs.append(frag)
        if name in ("read_text", "read_bytes", "open"):
            self.flags.add("reads_file")
        if name == "parse" and isinstance(f, ast.Attribute) and getattr(f.value, "id", None) == "ast":
            self.flags.add("ast")
        if name in ("TestClient",):
            self.flags.add("testclient")
        if name == "goto":
            self.flags.add("goto")
        self.generic_visit(node)

    def visit_Attribute(self, node):
        if node.attr == "e2e" and getattr(node.value, "attr", None) == "mark":
            self.flags.add("mark_e2e")
        self.generic_visit(node)

    def visit_arg(self, node):
        if node.arg in ("client", "admin_client", "live_server", "page", "browser", "e2e_browser", "new_context"):
            self.flags.add("fixture_" + node.arg)

    def visit_Name(self, node):
        if node.id in ("live_server", "sync_playwright"):
            self.flags.add("fixture_" + node.id)


def _flatten_div(node):
    parts = []

    def walk(n):
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div):
            walk(n.left)
            walk(n.right)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            parts.append(n.value)
        else:
            parts.append(None)

    walk(node)
    # 取最後一段連續的字串常數（前面通常是 ROOT 變數）
    tail = []
    for p in reversed(parts):
        if p is None:
            break
        tail.append(p)
    return "/".join(reversed(tail)) if tail else None


def _flatten_add(node):
    parts = []

    def walk(n):
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
            walk(n.left)
            walk(n.right)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            parts.append(n.value)
        elif isinstance(n, ast.Name):
            parts.append(("name", n.id))
        else:
            parts.append(None)

    walk(node)
    return parts


# ── 解析 ────────────────────────────────────────────────────────────────

class Resolver:
    def __init__(self, files):
        self.files = set(files)
        self.dirs = set()
        for f in files:
            parts = f.split("/")
            for i in range(1, len(parts)):
                self.dirs.add("/".join(parts[:i]))
        self.by_base = {}
        for f in files:
            if f.startswith((BACKEND + "/", "frontend/")):
                self.by_base.setdefault(f.rsplit("/", 1)[-1], []).append(f)
        self.routes = build_routes(files)

    def module(self, dotted):
        rel = dotted.replace(".", "/")
        for cand in (f"{BACKEND}/{rel}.py", f"{BACKEND}/{rel}/__init__.py", f"{TESTS_DIR}/{rel}.py"):
            if cand in self.files:
                return cand
        return None

    def fragment(self, frag, as_dir=False):
        """repo 路徑片段 → 檔案或目錄單位（目錄以 / 結尾）。唯一才算，否則 None。"""
        frag = frag.strip().lstrip("./").rstrip("/").replace("\\", "/")
        if not frag or "*" in frag:
            return None
        if frag in self.files:
            return frag
        if frag in self.dirs and "/" in frag:
            return frag + "/"
        hits = [f for f in self.files if f.endswith("/" + frag)]
        if len(hits) == 1:
            return hits[0]
        dhits = [d for d in self.dirs if d.endswith("/" + frag) or d == frag]
        if as_dir and len(dhits) == 1:
            return dhits[0] + "/"
        if "/" in frag and len(dhits) == 1:
            return dhits[0] + "/"
        return None

    def asset(self, name):
        """xxx.html／js/foo.js 等前端檔。"""
        name = name.split("?")[0].split("#")[0].lstrip("./")
        if "/" in name:
            u = self.fragment(name)
            if u and not u.endswith("/"):
                return u
            name = name.rsplit("/", 1)[-1]
        hits = [f for f in self.by_base.get(name, []) if f.startswith("frontend/")]
        return hits[0] if len(hits) == 1 else None

    def api(self, segs):
        """segs：str 或 None（萬用）。回傳 (owners, how)。"""
        full = set()
        for rsegs, _m, owner in self.routes:
            if len(rsegs) == len(segs) and all(a is None or b is None or a == b for a, b in zip(rsegs, segs)):
                full.add(owner)
        if full:
            return full, "exact"
        # 前綴：取測試路徑的固定前段（至少 /api/<x>），找共用該前段的路由
        fixed = []
        for s in segs:
            if s is None:
                break
            fixed.append(s)
        if len(fixed) >= 2:
            pre = set(o for rsegs, _m, o in self.routes if rsegs[:len(fixed)] == fixed)
            if pre:
                return pre, "prefix"
        return set(), "none"


def _api_segments(parts, consts):
    """f-string／字串相加的片段 → 路徑 segment 列表；不是 /api 開頭 ⇒ None。"""
    s = ""
    for p in parts:
        if isinstance(p, str):
            s += p
        elif isinstance(p, tuple) and p[0] == "name" and p[1] in consts:
            s += consts[p[1]]
        else:
            s += "\x00"
    s = _FMT_RE.sub(chr(0), s.split("?")[0])
    if not _API_RE.match(s) or s.strip("/") == "api" or " " in s:
        return None
    segs = []
    for seg in s.strip("/").split("/"):
        if "\x00" in seg:
            segs.append(None)
        elif seg:
            segs.append(seg)
        else:
            segs.append(None)
    # 結尾是插值且後面已沒有 /（f"/api/x/{rest}"）：保留為單一萬用
    return segs


#: e2e 的判定（**不看檔名**；wip/b-modtest-batch 主持派工）：e2e marker、瀏覽器夾具（live_server、e2e_browser、
#: new_context）、import playwright、page.goto。有 36 個 e2e 檔不叫 test_e2e_*（2026-09-26 實數），檔名判定會把它們
#: 當成非 e2e（-n 4、沒有 e2e 上限）。守門：backend/tests/platform/test_e2e_classification.py。
E2E_FLAGS = frozenset({"mark_e2e", "fixture_live_server", "fixture_sync_playwright", "goto",
                       "fixture_e2e_browser", "fixture_new_context", "imports_playwright"})


def _scan_flags(tree):
    sc = _Scan()
    sc.visit(tree)
    if any(m == "playwright" or m.startswith("playwright.") for m in sc.imports):
        sc.flags.add("imports_playwright")
    return sc


def file_is_e2e(path) -> bool:
    """單一測試檔是不是 e2e（與 test_map 的 kind＝e2e 同判準；不需要路由解析，給 test_map 沒有那一檔時用）。"""
    tree = _parse(path)
    return tree is not None and bool(_scan_flags(tree).flags & E2E_FLAGS)


def scan_test(path, R):
    tree = _parse(path)
    if tree is None:
        return {"kind": "unit", "units": [], "evidence": {}, "error": "parse"}
    sc = _scan_flags(tree)
    ev = {"import": set(), "api": set(), "page": set(), "path": set()}
    unresolved_api = set()

    for d in sc.imports:
        u = R.module(d)
        if u and u != path:
            ev["import"].add(u)
    # 字串形式的模組名：importlib.import_module("routers.x")、monkeypatch.setattr("helpers.y.z", ...)
    for t in sc.strings:
        if _DOTTED_RE.fullmatch(t):
            parts = t.split(".")
            for i in range(len(parts), 1, -1):
                u = R.module(".".join(parts[:i]))
                if u:
                    if u != path:
                        ev["import"].add(u)
                    break

    api_items = [[s] for s in sc.strings] + sc.fstrings
    auth_calls = set()
    for parts in api_items:
        segs = _api_segments(parts, sc.consts)
        if segs is None:
            continue
        owners, _how = R.api(segs)
        if owners:
            ev["api"].update(owners)
            if AUTH_ROUTER in owners:
                auth_calls.add(tuple(segs))
        else:
            unresolved_api.add("/" + "/".join(x if x is not None else "{}" for x in segs))
    # 只為了取得登入狀態而打 /api/auth/login ⇒ 視為 fixture，不算依賴 router:auth（主持裁示 2026-09-25）。
    # 仍算依賴：檔名像 auth 類測試，或打了 login 以外任何落在 router:auth 的端點（含萬用段）。
    # 保護：backend/tests/platform/test_auth_login_contract.py 每次必跑。
    login_fixture = (auth_calls and auth_calls <= {_LOGIN_SEGS}
                     and not _AUTH_TEST_NAME.search(path.rsplit("/", 1)[-1]))
    if login_fixture:
        ev["api"].discard(AUTH_ROUTER)

    texts = list(sc.strings) + list(sc.consts.values())
    for parts in sc.fstrings:
        texts.append("".join(p if isinstance(p, str) else " " for p in parts))
    for t in texts:
        if len(t) > 2000:
            continue
        for m in _ASSET_RE.findall(t):
            u = R.asset(m)
            if u:
                ev["page"].add(u)

    for frag in sc.path_frags:
        u = R.fragment(frag)
        if u:
            ev["path"].add(u)
    for frag in sc.glob_dirs:
        u = R.fragment(frag, as_dir=True)
        if u:
            ev["path"].add(u if u.endswith("/") else u)
    # 字串形式的 repo 路徑（"routers/bonus.py"、"frontend/static/sidebar.js"）
    for t in sc.strings:
        if "/" in t and len(t) < 200 and "\n" not in t and not _API_RE.match(t) and re.fullmatch(r"[\w\-./]+", t):
            u = R.fragment(t)
            if u:
                ev["path"].add(u)

    f = sc.flags
    if f & E2E_FLAGS:
        kind = "e2e"
    elif f & {"fixture_client", "fixture_admin_client", "testclient"} or ev["api"]:
        kind = "api"
    elif ev["path"] and (f & {"reads_file", "ast"}):
        kind = "audit"
    else:
        kind = "unit"

    paths = set().union(*ev.values())
    paths.discard(path)
    out = {
        "kind": kind,
        "units": sorted({unit_name(p) for p in paths}),
        "evidence": {k: sorted(v) for k, v in ev.items() if v},
    }
    if unresolved_api:
        out["unresolved_api"] = sorted(unresolved_api)
    if login_fixture:
        out["login_fixture"] = True
    return out


def build():
    files = tracked_files()
    R = Resolver(files)
    tests = sorted(p for p in files if (p.startswith(TESTS_DIR + "/") or _MOD_TEST_RE.match(p))
                   and re.search(r"/test_[^/]*\.py$", p))
    result = {}
    for t in tests:
        result[t] = scan_test(t, R)
        m = _MOD_TEST_RE.match(t)
        if m:
            # 模組自己的測試（CORE-SPEC §3 modules/<key>/tests/）⇒ 歸屬該模組：模組資料夾內任一檔改動都挑它
            key = m.group(1)
            r = result[t]
            r["module"] = key
            r["units"] = sorted(set(r["units"]) | {"dir:%s/modules/%s/" % (BACKEND, key)})
            r["evidence"]["module_dir"] = ["%s/modules/%s/" % (BACKEND, key)]
    unmapped = sorted(t for t, v in result.items() if not v["units"])
    kinds = {}
    for v in result.values():
        kinds[v["kind"]] = kinds.get(v["kind"], 0) + 1
    return {
        "generated_by": "tools/platform/test_map.py",
        "note": ("units 命名同 dep_graph.json（router:/helper:/core:/page:/js:），其餘 file:<路徑>、"
                 "dir:<目錄>/（該目錄下任一檔）；evidence 為 repo 路徑。靜態分析，對不到的列 unmapped 不猜。"),
        "summary": {"tests": len(result), "unmapped": len(unmapped), "kinds": kinds,
                    "routes": len(R.routes)},
        "unmapped": unmapped,
        "tests": result,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--stdout", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    data = build()
    text = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=False) + "\n"
    if a.stdout:
        sys.stdout.buffer.write(text.encode("utf-8"))
        return 0
    if a.check:
        old = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if old != text:
            print("test_map.json 與現況不一致，請重跑 tools/platform/test_map.py")
            return 1
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    s = data["summary"]
    print(f"tests={s['tests']} unmapped={s['unmapped']} kinds={s['kinds']} routes={s['routes']} → {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
