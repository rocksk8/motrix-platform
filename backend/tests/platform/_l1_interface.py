"""G1：L0／L1 公開介面快照（MODULE-GUIDE §2「底層穩定契約」）。

範圍：docs/platform/modules.json 的 L1 單位中，Python 單位（plat:／core:／helper:）的
  - 公開的頂層函式與類別：參數簽章（名稱、有無預設值、*args、keyword-only、**kwargs）
    公開＝不以 _ 開頭，或列在該檔自己的 `__l1_public__`（L1 自己宣告；2026-09-26 起不再依「有沒有 L2 在用」決定——
    那會讓介面隨安裝了哪些模組而改變：拿掉 M04 ⇒ `_generate_contractor_voucher_pdf` 變成「刪除」、要升主版號）
  - 公開類別的公開方法簽章與 dataclass 欄位（有型別註記的類別屬性）
  - 全大寫的模組常數名稱（只記名稱，不記值）
⚠ 守不到：回傳形狀（靜態讀不出來）、L1 router 的 HTTP 端點、資料表欄位（MODULE-GUIDE 標「⚠ 未守門」）。

升版規則（`--update` 重產快照時強制）：
  只有新增 ⇒ CORE_VERSION 至少升次版號；有修改或刪除 ⇒ 升主版號；版號沒照規則升 ⇒ 拒絕重產。
用法：
  python backend/tests/platform/_l1_interface.py --diff      列出目前介面與快照的差異
  python backend/tests/platform/_l1_interface.py --update    依升版規則重產快照
"""
import ast
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
REPO = BACKEND.parent
MODULES_JSON = REPO / "docs" / "platform" / "modules.json"
SNAPSHOT = HERE / "l1_interface_snapshot.json"
REGISTRY = BACKEND / "core" / "registry.py"
#: 快照「看得見什麼」的定義版本。2＝納入跨模組在用的底線名稱與 async／posonly（稽核 G-1、G-2）。
#: 範圍變大時重產：只要求「舊快照看得見的名稱」沒有修改／刪除，新看見的不算新增介面。
SCOPE_VERSION = 2
CHANGELOG = BACKEND / "core" / "CHANGELOG.md"

_UPPER = re.compile(r"^[A-Z][A-Z0-9_]*$")


def unit_path(unit, backend=None):
    backend = Path(backend) if backend is not None else BACKEND
    kind, name = unit.split(":", 1)
    return {"plat": backend / "core" / (name + ".py"),
            "core": backend / (name + ".py"),
            "helper": backend / "helpers" / (name + ".py")}.get(kind)


#: L1 檔案自己宣告「這些底線名稱是公開介面」的模組變數名
DECL = "__l1_public__"


def declared_public(source):
    """原始碼頂層的 `__l1_public__ = ("_a", "_b")` ⇒ {"_a", "_b"}；沒有 ⇒ 空集合。
    格式不對（不是字串常數組成的 tuple／list、或名稱不以底線開頭）⇒ ValueError（不猜）。"""
    for node in ast.parse(source).body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if not any(isinstance(t, ast.Name) and t.id == DECL for t in targets):
            continue
        if not isinstance(node.value, (ast.Tuple, ast.List)) or not all(
                isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.value.elts):
            raise ValueError("%s 必須是字串常數組成的 tuple／list" % DECL)
        names = {e.value for e in node.value.elts}
        bad = sorted(n for n in names if not n.startswith("_"))
        if bad:
            raise ValueError("%s 只列底線開頭的名稱（其餘本來就公開）：%s" % (DECL, bad))
        ghost = sorted(names - _top_level_names(ast.parse(source)))
        if ghost:   # 稽核 G-S2：打錯字、或函式改名忘了改宣告 ⇒ 原本被靜默忽略
            raise ValueError("%s 宣告了檔案頂層沒有定義的名稱：%s" % (DECL, ghost))
        return names
    return set()


def _top_level_names(tree):
    """模組頂層定義的名稱（def／class／指派／import；含頂層 if／try／with 區塊裡的，不含函式與類別內部）。"""
    out = set()

    def visit(body):
        for n in body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out.add(n.name)
            elif isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                    out.update(x.id for x in ast.walk(t) if isinstance(x, ast.Name))
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                out.update((a.asname or a.name).split(".")[0] for a in n.names)
            elif isinstance(n, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
                for field in ("body", "orelse", "finalbody"):
                    visit(getattr(n, field, []) or [])
                for h in getattr(n, "handlers", []) or []:
                    visit(h.body)
    visit(tree.body)
    return out


def l1_python_units(modules_json=MODULES_JSON):
    data = json.loads(Path(modules_json).read_text(encoding="utf-8"))
    return sorted(u for u in data["L1"]["units"] if u.split(":", 1)[0] in ("plat", "core", "helper"))


def _sig(args):
    out = []
    pos = list(args.posonlyargs) + list(args.args)
    first_default = len(pos) - len(args.defaults)
    for i, a in enumerate(pos):
        out.append(a.arg + ("=…" if i >= first_default else ""))
        if args.posonlyargs and i == len(args.posonlyargs) - 1:
            out.append("/")                       # 僅限位置參數（G-2）
    if args.vararg:
        out.append("*" + args.vararg.arg)
    elif args.kwonlyargs:
        out.append("*")
    for a, d in zip(args.kwonlyargs, args.kw_defaults):
        out.append(a.arg + ("=…" if d is not None else ""))
    if args.kwarg:
        out.append("**" + args.kwarg.arg)
    return "(" + ", ".join(out) + ")"


def _kind(node):
    return "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"


def interface_of(source, extra_public=None):
    """一個模組的公開介面 ⇒ {名稱: 描述字串}。

    公開＝不以底線開頭，**或**列在 extra_public（預設＝原始碼自己的 `__l1_public__`，見 declared_public）。
    描述含 `async` 與僅限位置參數的 `/`（稽核 G-2）；**預設值的內容不納入**——預設值語意改變要自己升版並寫 CHANGELOG。
    """
    tree = ast.parse(source)
    out = {}
    if extra_public is None:
        extra_public = frozenset(declared_public(source))

    def pub(name):
        return not name.startswith("_") or name in extra_public

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and pub(node.name):
            out[node.name] = _kind(node) + _sig(node.args)
        elif isinstance(node, ast.ClassDef) and pub(node.name):
            out[node.name] = "class"
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and (not item.name.startswith("_") or item.name == "__init__"):
                    out["%s.%s" % (node.name, item.name)] = _kind(item) + _sig(item.args)
                elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name) \
                        and not item.target.id.startswith("_"):
                    out["%s.%s" % (node.name, item.target.id)] = "field" + ("=…" if item.value is not None else "")
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name) and (_UPPER.match(t.id) or t.id in extra_public):
                    out[t.id] = "const"
    return out


_SKIP_DIRS = ("tests", "tools", "scripts", "migrations_frozen", "__pycache__", ".venv")


def _module_to_unit(mod):
    """import 的模組名 ⇒ G1 的單位名（不是 L1 Python 單位 ⇒ None）。"""
    parts = mod.split(".")
    if parts[0] == "helpers" and len(parts) > 1:
        return "helper:" + parts[1]
    if parts[0] == "core" and len(parts) > 1:
        return "plat:" + parts[1]
    if len(parts) == 1 and parts[0] not in ("helpers", "core", "routers", "modules"):
        return "core:" + parts[0]
    return None


def cross_boundary_public(units=None, backend=None):
    """{單位: {底線名稱…}}：**實際**被當成跨模組 API 用的底線名稱（稽核 G-1）。

    ① `helpers/__init__.py` 的 `__all__` 列出的名稱（依它的 `from .x import` 對回原模組）
    ② L1 以外的產品碼（routers、modules、backend 頂層非 L1 檔）直接 import 的底線名稱
    ⚠ 2026-09-26 起**不決定介面**（介面看 `__l1_public__`）；只給守門用：用到的必須是宣告過的（undeclared_uses）。
    """
    backend = Path(backend) if backend is not None else BACKEND
    units = set(l1_python_units() if units is None else units)
    extra = {}
    init = backend / "helpers" / "__init__.py"
    reexport = {}
    if init.is_file():
        tree = ast.parse(init.read_text(encoding="utf-8-sig"))
        exported = set()
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module:
                unit = "helper:" + node.module.split(".")[-1] if node.level == 1 else _module_to_unit(node.module)
                for a in node.names:
                    reexport[a.asname or a.name] = (unit, a.name)
            elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
                exported |= {e.value for e in getattr(node.value, "elts", []) if isinstance(e, ast.Constant)}
        for name in exported:
            unit, orig = reexport.get(name, (None, None))
            if unit in units and orig.startswith("_"):
                extra.setdefault(unit, set()).add(orig)
    l1_files = {unit_path(u, backend).resolve() for u in units if unit_path(u, backend)}
    for f in backend.rglob("*.py"):
        rel = f.relative_to(backend)
        if any(x in rel.parts for x in _SKIP_DIRS) or f.name == "conftest.py" or f.resolve() in l1_files:
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8-sig"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.level != 0 or not node.module:
                continue
            for a in node.names:
                if not a.name.startswith("_"):
                    continue
                if node.module == "helpers":
                    unit, orig = reexport.get(a.name, (None, None))
                else:
                    unit, orig = _module_to_unit(node.module), a.name
                if unit in units:
                    extra.setdefault(unit, set()).add(orig)
    return extra


def current_interface(units=None):
    """L1 自己宣告的介面：只讀 L1 檔案本身（不掃 L2）⇒ 裝了哪些模組都算出同一份。"""
    units = l1_python_units() if units is None else units
    res = {}
    for u in units:
        p = unit_path(u)
        if p is None or not p.is_file():
            res[u] = {"__missing__": "unit"}
            continue
        res[u] = interface_of(p.read_text(encoding="utf-8-sig"))
    return res


def undeclared_uses(units=None, backend=None):
    """{單位: {名稱…}}：L1 以外（或 helpers.__all__）用到、而該 L1 檔 `__l1_public__` 沒宣告的底線名稱。
    非空 ⇒ 有人在用 L1 的私有名稱（要嘛宣告成公開、要嘛改用公開名稱）。"""
    backend = Path(backend) if backend is not None else BACKEND
    units = set(l1_python_units() if units is None else units)
    out = {}
    for u, names in cross_boundary_public(units, backend).items():
        p = unit_path(u, backend)
        declared = declared_public(p.read_text(encoding="utf-8-sig")) if p and p.is_file() else set()
        missing = names - declared
        if missing:
            out[u] = missing
    return out


def _params(desc):
    m = __import__("re").match(r"^def\((.*)\)$", desc) or __import__("re").match(r"^async def\((.*)\)$", desc)
    if not m:
        return None
    return [p.strip() for p in m.group(1).split(",") if p.strip()]


def compatible_extension(old_desc, new_desc):
    """相容擴充：舊參數原樣、原順序保留在前面，新加的都有預設值（或是 *args／**kwargs／keyword-only 分隔）。"""
    o, n = _params(old_desc), _params(new_desc)
    if old_desc.startswith("async") != new_desc.startswith("async"):
        return False                              # def ⇄ async def：呼叫端 await 與否全變 ⇒ 修改
    if o is None or n is None or n[:len(o)] != o:
        return False
    return all(p.endswith("=…") or p.startswith("*") for p in n[len(o):])


def diff(old, new):
    """(added, changed, removed)：各為 ["unit::name", ...]。整個單位新增／刪除也算。
    簽章只在尾端加了有預設值的參數 ⇒ 算「新增」（相容擴充，升次版號即可）。"""
    added, changed, removed = [], [], []
    for u in sorted(set(old) | set(new)):
        o, n = old.get(u, {}), new.get(u, {})
        for k in sorted(set(o) | set(n)):
            key = "%s::%s" % (u, k)
            if k not in o:
                added.append(key)
            elif k not in n:
                removed.append(key)
            elif o[k] != n[k]:
                if compatible_extension(o[k], n[k]):
                    added.append("%s  %s → %s（相容擴充）" % (key, o[k], n[k]))
                else:
                    changed.append("%s  %s → %s" % (key, o[k], n[k]))
    return added, changed, removed


def parse_version(v):
    m = re.fullmatch(r"(\d+)\.(\d+)", str(v).strip())
    if not m:
        raise ValueError("CORE_VERSION 格式要是「主.次」：%r" % v)
    return int(m.group(1)), int(m.group(2))


def required_bump(added, changed, removed):
    """需要的升版等級：None／"minor"／"major"。"""
    if changed or removed:
        return "major"
    if added:
        return "minor"
    return None


def bump_ok(old_version, new_version, need):
    """新版號是否滿足需要的升版等級（等級不足或倒退都算不滿足）。"""
    o, n = parse_version(old_version), parse_version(new_version)
    if need is None:
        return n >= o
    if need == "major":
        return n[0] > o[0]
    return n > o


def core_version():
    m = re.search(r'^CORE_VERSION\s*=\s*"([^"]+)"', REGISTRY.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else None


def changelog_top_version(text=None):
    """最上面一個「## 主.次」。三段版號（## 1.4.1）不算成 1.4（稽核 O-2），直接讀不到 ⇒ None。"""
    text = CHANGELOG.read_text(encoding="utf-8") if text is None else text
    m = re.search(r"^##\s+(\d+(?:\.\d+)+)", text, re.M)
    if not m or m.group(1).count(".") != 1:
        return None
    return m.group(1)


def _scope1_desc(v):
    """範圍 2 的描述 ⇒ 範圍 1 的格式（拿掉 async 前綴與 `/` 標記），用來和舊快照比對「本來就看得見的」有沒有變。"""
    v = v[len("async "):] if v.startswith("async ") else v
    return v.replace(", /", "").replace("(/, ", "(").replace("(/)", "()")


def load_snapshot():
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def _arg(argv, name):
    """--name value／--name=value ⇒ value；沒有 ⇒ None。"""
    for i, a in enumerate(argv):
        if a == name and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


#: 範圍變動時必須一起改的規則說明（至少一份）
RULE_DOCS = ("docs/platform/MODULE-GUIDE.md", "docs/platform/CORE-SPEC.md")


def scope_changes_without_rule_docs(repo=None, snapshot_rel=None):
    """改到快照 scope_version 的 commit，若沒有同時改 RULE_DOCS 之一 ⇒ 列出（含工作樹未提交的改動）。"""
    import subprocess
    repo = Path(repo or REPO)
    snapshot_rel = snapshot_rel or SNAPSHOT.relative_to(REPO).as_posix()

    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                              encoding="utf-8", check=True).stdout

    bad = []
    commits = git("log", "--format=%H", "-G", '"scope_version"', "--", snapshot_rel).split()
    for c in commits:
        files = set(git("show", "--name-only", "--format=", c).split())
        if not files & set(RULE_DOCS):
            bad.append(c[:8])
    if '"scope_version"' in git("diff", "HEAD", "--", snapshot_rel):
        dirty = set(git("diff", "HEAD", "--name-only").split())
        if not dirty & set(RULE_DOCS):
            bad.append("（工作樹未提交）")
    return bad


def main(argv):
    cur = current_interface()
    ver = core_version()
    if "--update" in argv:
        if SNAPSHOT.exists():
            snap = load_snapshot()
            old = snap["interface"]
            scope_change = snap.get("scope_version", 1) < SCOPE_VERSION
            if scope_change and not _arg(argv, "--reason"):
                print("拒絕重產：快照範圍 %s → %s 要附原因（--reason \"…\"），並在同一個 commit 修改 MODULE-GUIDE／CORE-SPEC 的規則說明"
                      % (snap.get("scope_version", 1), SCOPE_VERSION))
                return 1
            if scope_change:
                # 範圍變大：只比舊快照看得見的名稱（描述格式也跟著變 ⇒ 用新規則重算舊快照看得見的那些）
                cur_cmp = {u: {k: _scope1_desc(v) for k, v in cur.get(u, {}).items() if k in old.get(u, {})} for u in old}
                a, c, r = diff(old, cur_cmp)
                print("快照範圍 %s → %s：只比對舊快照看得見的名稱" % (snap.get("scope_version", 1), SCOPE_VERSION))
            else:
                a, c, r = diff(old, cur)
            need = required_bump(a, c, r)
            if not bump_ok(snap["core_version"], ver, need):
                print("拒絕重產：介面差異需要 %s 升版，而 CORE_VERSION %s → %s 不足。"
                      % (need, snap["core_version"], ver))
                return 1
        history = []
        if SNAPSHOT.exists():
            snap = load_snapshot()
            history = snap.get("scope_history", [])
            if snap.get("scope_version", 1) < SCOPE_VERSION:
                old = snap["interface"]
                widened = sorted("%s::%s" % (u, k) for u, items in cur.items() for k in items if k not in old.get(u, {}))
                history.append({"from": snap.get("scope_version", 1), "to": SCOPE_VERSION,
                                "reason": _arg(argv, "--reason"), "newly_visible": widened})
        SNAPSHOT.write_text(json.dumps({"core_version": ver, "scope_version": SCOPE_VERSION, "scope_history": history,
                                        "interface": cur},
                                       ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                            encoding="utf-8", newline="\n")
        print("已重產：CORE_VERSION %s，%d 個單位" % (ver, len(cur)))
        return 0
    snap = load_snapshot()
    a, c, r = diff(snap["interface"], cur)
    print("快照 %s／目前 %s；新增 %d、修改 %d、刪除 %d" % (snap["core_version"], ver, len(a), len(c), len(r)))
    for label, items in (("新增", a), ("修改", c), ("刪除", r)):
        for x in items:
            print("  %s  %s" % (label, x))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main(sys.argv[1:]))
