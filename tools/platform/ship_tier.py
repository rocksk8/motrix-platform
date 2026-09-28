"""出貨等級判定（CORE-SPEC「出貨前測試依改動範圍分級」、「單一模組更新包上線」；設計 docs/platform/MODULE-UPDATE-DELIVERY.md §4）。

用法：
  python tools/platform/ship_tier.py --prod <正式機 commit P> [--commit X] [--overlay key=sha256 ...] [--json]

依 P→X 的改動檔判出貨等級：
  1 ＝只改文件（完整包不出貨的路徑、docs/**）      ⇒ 沒有東西要出貨
  2 ＝只改單一 L2 模組（＋它宣告的頁面、它的 version_manifest 條目、文件） ⇒ 可以出單模組包
  3 ＝其他一切（L0／L1、main.py、fixture 層、requirements、更新工具、共用前端、兩個以上模組…） ⇒ 必須完整包
判不了 ⇒ 3（不猜）。

§4.3 提供者判斷點：模組提供串接點（capability）而且這次改到它的程式 ⇒ 依 PROVIDER_CHANGE_POLICY：
  "consumers"（甲，使用者裁示 CORE-SPEC ee383527）⇒ 仍是 2，另回消費端檔案（交給 modtest 當虛擬改動選題）；
      消費端判不了（任何一處取用呼叫解析不了）⇒ 退回乙
  "reject"（乙）⇒ 3
"""
import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

#: §4.3 判斷點（**唯一**設定處；工具與題都讀它）。使用者裁示＝甲（CORE-SPEC ee383527）。
PROVIDER_CHANGE_POLICY = "consumers"
POLICIES = ("consumers", "reject")

TIER_DOC, TIER_MODULE, TIER_FULL = 1, 2, 3

#: 改到就一定是 3 的路徑（先於「不出貨」比對：conftest 等雖然不出貨，但改變測試環境或建包工具）
FULL_PREFIXES = ("tools/", "backend/tools/")
MANIFEST = "backend/version_manifest.json"


def _pages_rel():
    """module.json 宣告的頁面（`pages[].path`）所在目錄，repo 相對路徑；由 core.paths 取得，不寫死（test_page_paths_centralized）。"""
    # 以檔案路徑載入**本 repo** 的 core/paths.py（不經 sys.path）：呼叫端（例：演練工具）可能已把別的安裝的 backend
    # 放進 sys.path，`from core import paths` 會拿到那一份 ⇒ 頁面目錄算到別的地方（B55 S6 演練實際踩到）
    import importlib.util
    spec = importlib.util.spec_from_file_location("_ship_tier_core_paths", str(REPO / "backend" / "core" / "paths.py"))
    _paths = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(_paths)
    return Path(_paths.FRONTEND_PAGES_DIR).resolve().relative_to(REPO.resolve()).as_posix()


PAGES_REL = _pages_rel()
REGISTRY = "backend/core/registry.py"
_MOD_RE = re.compile(r"^backend/modules/([^/]+)/")


def fixture_layer():
    import modtest
    return tuple(modtest.FIXTURE_LAYER)


# ── 分級（純函式）────────────────────────────────────────────────────────────

def classify(files, *, pages_by_module, not_shipped, manifest_modules=None, fixture=None):
    """改動檔 ⇒ {"tier", "key", "offenders", "categories"}。

    pages_by_module：{模組: 宣告的頁面（repo 相對路徑）集合}（P 與 X 的聯集由呼叫端給）
    not_shipped(path) -> bool：完整包不出貨的路徑（export-ignore）
    manifest_modules：P→X version_manifest 新增／改動條目所屬的模組集合；None ＝判不了；改到已出貨條目由呼叫端放 "<shipped>"
    """
    fixture = tuple(fixture if fixture is not None else fixture_layer())
    cats, offenders = {}, []
    for f in sorted(set(files)):
        if f in fixture or f.startswith(FULL_PREFIXES):
            cats[f] = "full"
            offenders.append((f, "fixture 層或更新／建包工具"))
            continue
        m = _MOD_RE.match(f)
        if m:
            cats[f] = "module:" + m.group(1)
            continue
        if f == MANIFEST:
            if manifest_modules is None:
                cats[f] = "full"
                offenders.append((f, "version_manifest 的改動判不了"))
            elif len(set(manifest_modules)) == 1 and not any(str(m).startswith("<") for m in manifest_modules):
                cats[f] = "module:" + next(iter(manifest_modules))
            elif not manifest_modules:
                cats[f] = "doc"
            else:
                cats[f] = "full"
                offenders.append((f, "version_manifest 夾帶多個模組或改到已出貨條目：%s" % sorted(manifest_modules)))
            continue
        if f.startswith("frontend/"):
            owners = sorted(k for k, pages in pages_by_module.items() if f in pages)
            if len(owners) == 1:
                cats[f] = "module:" + owners[0]
            else:
                cats[f] = "full"
                offenders.append((f, "前端檔不屬於恰好一個模組（宣告者：%s）" % (owners or "無")))
            continue
        if not_shipped(f) or f.startswith("docs/"):
            cats[f] = "doc"
            continue
        cats[f] = "full"
        offenders.append((f, "L0／L1、main、requirements 或其他會出貨的共用檔"))
    keys = sorted({c.split(":", 1)[1] for c in cats.values() if c.startswith("module:")})
    if offenders:
        tier = TIER_FULL
    elif len(keys) > 1:
        tier = TIER_FULL
        offenders = [(f, "兩個以上模組：%s" % keys) for f, c in cats.items() if c.startswith("module:")]
    elif keys:
        tier = TIER_MODULE
    else:
        tier = TIER_DOC
    return {"tier": tier, "key": keys[0] if tier == TIER_MODULE else None,
            "offenders": offenders, "categories": cats}


# ── 串接點：能力清單、取用函式、消費端（純函式，吃原始碼）─────────────────────────

class Unresolved(Exception):
    pass


def getter_names(registry_src):
    """core/registry.py ⇒ 「以 capability 取提供者」的函式名（公開介面列出、第一個參數叫 capability、不是 provide）。"""
    doc = ast.get_docstring(ast.parse(registry_src)) or registry_src
    m = re.search(r"\[公開介面\](.*?)(?:\n\s*\[|\Z)", doc, re.S) or re.search(r"\[公開介面\](.*?)(?:\n\s*\[|\n\"\"\")", registry_src, re.S)
    if not m:
        raise Unresolved("core/registry.py 找不到 [公開介面]")
    public = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", m.group(1)))
    out = set()
    for node in ast.parse(registry_src).body:
        if isinstance(node, ast.FunctionDef) and node.name in public and node.name != "provide":
            args = node.args.posonlyargs + node.args.args
            if args and args[0].arg == "capability":
                out.add(node.name)
    return out


def module_name_to_path(mod):
    """repo 內的模組名 ⇒ backend 相對路徑候選（x.y ⇒ backend/x/y.py 或 backend/x/y/__init__.py）。"""
    base = "backend/" + mod.replace(".", "/")
    return [base + ".py", base + "/__init__.py"]


def path_to_module_name(rel):
    p = rel[len("backend/"):] if rel.startswith("backend/") else rel
    p = p[:-3] if p.endswith(".py") else p
    if p.endswith("/__init__"):
        p = p[: -len("/__init__")]
    return p.replace("/", ".")


class _File:
    """一個檔的 import 表與模組層字串常數。"""

    def __init__(self, rel, src):
        self.rel = rel
        self.tree = ast.parse(src)
        self.names = {}          # 區域名稱 ⇒ 完整名稱（"core.registry"、"core.registry.single_provider"、"helpers.case_access.CASE_PRESENT"）
        pkg = path_to_module_name(rel).rsplit(".", 1)[0] if not rel.endswith("__init__.py") else path_to_module_name(rel)
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.asname:
                        self.names[a.asname] = a.name
                    else:
                        self.names[a.name.split(".")[0]] = a.name.split(".")[0]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    parts = pkg.split(".")
                    parts = parts[: len(parts) - (node.level - 1)] if node.level > 1 else parts
                    base = ".".join(parts + ([node.module] if node.module else []))
                for a in node.names:
                    self.names[a.asname or a.name] = (base + "." + a.name) if base else a.name
        self.consts, self.const_nodes, assigned = {}, {}, {}
        for node in ast.walk(self.tree):
            targets = []
            if isinstance(node, (ast.Assign,)):
                targets = node.targets
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                targets = [node.target]
            for t in targets:
                if isinstance(t, ast.Name):
                    assigned[t.id] = assigned.get(t.id, 0) + 1
        for node in self.tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                    and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str) \
                    and assigned.get(node.targets[0].id) == 1:
                self.consts[node.targets[0].id] = node.value.value
                self.const_nodes[node.targets[0].id] = node.value

    def full(self, expr):
        """運算式 ⇒ 完整名稱（Name／Attribute 鏈）；認不得 ⇒ None。"""
        if isinstance(expr, ast.Name):
            return self.names.get(expr.id)
        if isinstance(expr, ast.Attribute):
            base = self.full(expr.value)
            return base + "." + expr.attr if base else None
        return None


class Repo:
    """原始碼集合 {repo 相對路徑: 原始碼}（呼叫端從 git 或工作樹讀）。"""

    def __init__(self, sources):
        self.sources = sources
        self._files = {}
        #: 解析取用／登記呼叫時實際用到的常數定義節點 id（DB4-S1 ③：定義處不算「散落的能力字串」）
        self.used_const_nodes = set()
        #: 解析成功的取用呼叫 capability 引數節點 id（DB4-S1 ③：只有這些位置算「已解析的取用」）
        self.used_arg_nodes = set()

    def _use(self, f, name):
        self.used_const_nodes.add(id(f.const_nodes[name]))
        return f.consts[name]

    def file(self, rel):
        if rel not in self._files:
            self._files[rel] = _File(rel, self.sources[rel])
        return self._files[rel]

    def const(self, fullname, depth=0):
        """"helpers.case_access.CASE_PRESENT" ⇒ 字串；解析不了 ⇒ Unresolved。"""
        if depth > 5 or "." not in fullname:
            raise Unresolved(fullname)
        mod, name = fullname.rsplit(".", 1)
        for rel in module_name_to_path(mod):
            if rel in self.sources:
                f = self.file(rel)
                if name in f.consts:
                    return self._use(f, name)
                if name in f.names:                     # 再從別處 import 進來
                    return self.const(f.names[name], depth + 1)
        raise Unresolved(fullname)

    def arg_value(self, f, expr):
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            return expr.value
        if isinstance(expr, ast.Name):
            if expr.id in f.consts:
                return self._use(f, expr.id)
            if expr.id in f.names:
                return self.const(f.names[expr.id])
            raise Unresolved("%s：%s 不是模組層字串常數" % (f.rel, expr.id))
        if isinstance(expr, ast.Attribute):
            full = f.full(expr)
            if full:
                return self.const(full)
        raise Unresolved("%s:%s 的 capability 不是字串常數" % (f.rel, getattr(expr, "lineno", "?")))


def _cap_arg(call):
    if call.args:
        return call.args[0]
    for kw in call.keywords:
        if kw.arg == "capability":
            return kw.value
    return None


def registry_refs(repo, rel, names):
    """檔裡對 core.registry.<names> 的引用 ⇒ [(Call 或 None, 函式名, 行號)]；None ＝不是直接呼叫（當值傳遞等）。"""
    f = repo.file(rel)
    wanted = {"core.registry." + n: n for n in names}
    calls, out = set(), []
    for node in ast.walk(f.tree):
        if isinstance(node, ast.Call):
            full = f.full(node.func)
            if full in wanted:
                calls.add(id(node.func))
                out.append((node, wanted[full], node.lineno))
    for node in ast.walk(f.tree):
        if isinstance(node, (ast.Name, ast.Attribute)) and id(node) not in calls:
            full = f.full(node)
            if full in wanted and not (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)):
                # import 敘述本身不是 Name 節點；這裡只剩「引用了、但不是被呼叫」的
                out.append((None, wanted[full], getattr(node, "lineno", 0)))
    return f, out


def capabilities(repo, key):
    """模組 <key> 提供的 capability ⇒ (集合, 判不了的位置清單)。"""
    caps, unresolved = set(), []
    prefix = "backend/modules/%s/" % key
    init = prefix + "__init__.py"
    if init in repo.sources:
        f = repo.file(init)
        for node in ast.walk(f.tree):
            if isinstance(node, ast.Call) and (f.full(node.func) or "").endswith("ModuleSpec"):
                for kw in node.keywords:
                    if kw.arg != "providers":
                        continue
                    if not isinstance(kw.value, ast.Dict):
                        unresolved.append("%s:%s providers 不是字面 dict" % (init, kw.value.lineno))
                        continue
                    for k in kw.value.keys:
                        try:
                            if isinstance(k, ast.Tuple) and k.elts:
                                caps.add(repo.arg_value(f, k.elts[0]))
                            else:
                                raise Unresolved("%s:%s providers 的 key 不是 (capability, name)" % (init, k.lineno))
                        except Unresolved as e:
                            unresolved.append(str(e))
    for rel in sorted(r for r in repo.sources if r.startswith(prefix) and r.endswith(".py") and "/tests/" not in r):
        f, refs = registry_refs(repo, rel, {"provide"})
        top = {id(n) for stmt in f.tree.body for n in ast.walk(stmt)
               if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
        for call, _name, line in refs:
            if call is None:
                unresolved.append("%s:%s 引用了 provide 但不是直接呼叫" % (rel, line))
            elif id(call) not in top:
                unresolved.append("%s:%s provide 在函式／類別內呼叫（登記時機判不了）" % (rel, line))   # DB3-S2
            else:
                try:
                    arg = _cap_arg(call)
                    if arg is None:
                        raise Unresolved("%s:%s provide 沒有 capability 引數" % (rel, line))
                    caps.add(repo.arg_value(f, arg))
                except Unresolved as e:
                    unresolved.append(str(e))
    return caps, unresolved


def _is_consumer_scope(rel, key):
    if not rel.startswith("backend/") or not rel.endswith(".py"):
        return False
    if rel.startswith("backend/modules/%s/" % key) or rel == REGISTRY:
        return False
    parts = rel.split("/")
    return "tests" not in parts and rel != "backend/conftest.py" and not rel.startswith("backend/tools/")


def consumers(repo, key, caps, getters):
    """<key> 以外的後端程式中取用 caps 的檔 ⇒ (消費端檔集合, 判不了的位置清單)。

    🔴 任何一處取用呼叫判不了（不論它最後是不是在取 <key> 的能力）都列進判不了——「找不到」不可以等於「沒有」。"""
    found, unresolved = set(), []
    for rel in sorted(r for r in repo.sources if _is_consumer_scope(r, key)):
        f, refs = registry_refs(repo, rel, getters)
        for call, name, line in refs:
            if call is None:
                unresolved.append("%s:%s 引用了 %s 但不是直接呼叫" % (rel, line, name))
                continue
            try:
                arg = _cap_arg(call)
                if arg is None:
                    raise Unresolved("%s:%s %s 沒有 capability 引數" % (rel, line, name))
                value = repo.arg_value(f, arg)
                repo.used_arg_nodes.add(id(arg))
                if value in caps:
                    found.add(rel)
            except Unresolved as e:
                unresolved.append(str(e))
    return found, unresolved


#: 可以讀 core.registry 內部（底線名稱）、或以非取用函式的方式碰到能力字串的檔（DB4-S1 ①③）。
#: 只收**核心**自己的彙整工具；新增一筆＝有人決定「這個讀法不必算消費端」，要有理由寫在這裡。
REGISTRY_INTERNALS_ALLOWED = {
    "backend/core/catalog.py": "平台目錄頁：列出所有提供者供顯示，不依賴任何一個能力的回傳形狀",
}


#: 能力字串在非取用位置出現、但確認不是在取提供者的（DB4-S1 ③ 的例外）：{(檔, 能力): 理由}。
#: 以「檔＋字串」為鍵（不寫行號：行號一動就失效）。守門題驗每一筆今天仍然對得上（過期就刪）。
CAPABILITY_STRING_ALLOWED = {
    ("backend/routers/approval_queue.py", "approval.reassign"): "稽核動作名稱 _audit(…, \"approval.reassign\", …)，與能力同名，不是取用",
}


def registry_bypasses(repo, key):
    """DB4-S1 ①②：<key> 以外的後端程式裡，讀 core.registry 內部（底線名稱）或星號 import registry 的位置 ⇒ 判不了清單。"""
    out = []
    for rel in sorted(r for r in repo.sources if _is_consumer_scope(r, key)):
        if rel in REGISTRY_INTERNALS_ALLOWED:
            continue
        f = repo.file(rel)
        for node in ast.walk(f.tree):
            if isinstance(node, ast.ImportFrom) and any(a.name == "*" for a in node.names) \
                    and (node.module or "").startswith("core"):
                out.append("%s:%s 星號 import（%s）⇒ 取用關係判不了" % (rel, node.lineno, node.module))
            elif isinstance(node, ast.ImportFrom) and node.module == "core.registry" \
                    and any(a.name.startswith("_") for a in node.names):
                out.append("%s:%s import 了 core.registry 的內部名稱" % (rel, node.lineno))
            elif isinstance(node, ast.Attribute) and node.attr.startswith("_"):
                base = f.full(node.value)
                if base == "core.registry":
                    out.append("%s:%s 讀 core.registry.%s（內部）" % (rel, node.lineno, node.attr))
    return out


def stray_capability_strings(repo, key, caps, consumer_files):
    """DB4-S1 ③：能力字串在後端每一次出現（字串常數，完全相等）都要落在提供者（<key> 自己）、已解析的消費端或白名單；
    其他位置 ⇒ 判不了（可能以取用函式以外的方式拿到提供者，例：registry._LEGACY_PROVIDERS[("case.access", "case")]）。"""
    out = []
    for rel in sorted(r for r in repo.sources if _is_consumer_scope(r, key)):
        if rel in REGISTRY_INTERNALS_ALLOWED:
            continue
        f = repo.file(rel)
        allowed = _provider_sites(f) | repo.used_arg_nodes | repo.used_const_nodes
        for node in ast.walk(f.tree):
            if id(node) in allowed:
                continue
            value = None
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) \
                    and (node.id in f.consts or node.id in f.names):
                value = _try_value(repo, f, node)
            elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                value = _try_value(repo, f, node)
            if value in caps and (rel, value) not in CAPABILITY_STRING_ALLOWED:
                out.append("%s:%s 出現能力 %r（字串或常數），但不是已解析的取用呼叫" % (rel, node.lineno, value))
    return out


def _try_value(repo, f, node):
    """名稱／屬性若是（跨檔）模組層字串常數 ⇒ 它的值；不是 ⇒ None（不記「用到」）。"""
    saved = set(repo.used_const_nodes)
    try:
        return repo.arg_value(f, node)
    except Unresolved:
        return None
    finally:
        repo.used_const_nodes = saved


def _provider_sites(f):
    """檔內「登記提供者」位置的字串節點 id：ModuleSpec(providers={(cap, name): …}) 的 cap、provide(cap, …) 的 cap。
    同一能力可以有多個提供者（例：approval.*、attachments.for_document）——別的模組／L1 登記同一能力不是在取用它。"""
    out = set()
    for node in ast.walk(f.tree):
        if not isinstance(node, ast.Call):
            continue
        full = f.full(node.func) or ""
        if full.endswith("ModuleSpec"):
            for kw in node.keywords:
                if kw.arg == "providers" and isinstance(kw.value, ast.Dict):
                    for k in kw.value.keys:
                        if isinstance(k, ast.Tuple) and k.elts:
                            out.add(id(k.elts[0]))
        elif full == "core.registry.provide":
            arg = _cap_arg(node)
            if arg is not None:
                out.add(id(arg))
    return out


def provider_check(repo, key, changed_files, policy=None, registry_src=None):
    """§4.3 ⇒ {"provider_changed", "caps", "consumers", "unresolved", "reject"(bool), "reason"}。"""
    policy = policy or PROVIDER_CHANGE_POLICY
    if policy not in POLICIES:
        raise ValueError("PROVIDER_CHANGE_POLICY 不認得：%r" % policy)
    caps, unresolved = capabilities(repo, key)
    code_changed = any(f.startswith("backend/modules/%s/" % key) and f.endswith(".py") and "/tests/" not in f
                       for f in changed_files)
    changed = code_changed and (bool(caps) or bool(unresolved))      # 讀不出來 ⇒ 當成有
    out = {"provider_changed": changed, "caps": sorted(caps), "consumers": [], "unresolved": list(unresolved),
           "reject": False, "reason": ""}
    if not changed:
        return out
    if policy == "reject":
        out.update(reject=True, reason="%s 提供串接點 %s，而這次改到它的程式 ⇒ 必須完整包（PROVIDER_CHANGE_POLICY=reject）"
                   % (key, "、".join(sorted(caps)) or "（判不了）"))
        return out
    try:
        getters = getter_names(registry_src if registry_src is not None else repo.sources[REGISTRY])
    except (Unresolved, KeyError) as e:
        out.update(reject=True, reason="取用函式清單判不了（%s）⇒ 退回乙" % e)
        return out
    found, un2 = consumers(repo, key, caps, getters)
    out["consumers"] = sorted(found)
    out["unresolved"] += un2
    out["unresolved"] += registry_bypasses(repo, key)                       # DB4-S1 ①②
    out["unresolved"] += stray_capability_strings(repo, key, caps, found)    # DB4-S1 ③（要在 consumers() 之後：用它記下的已解析位置）
    if out["unresolved"]:
        out.update(reject=True, reason="消費端判不了 ⇒ 退回乙（拒絕出單模組包）：\n  " + "\n  ".join(out["unresolved"]))
    return out


# ── git 包裝 ────────────────────────────────────────────────────────────────

def _git(*args, repo=REPO, binary=False):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if r.returncode != 0:
        raise RuntimeError("git %s 失敗：%s" % (" ".join(args), r.stderr.decode("utf-8", "replace").strip()))
    return r.stdout if binary else r.stdout.decode("utf-8")


def _show(commit, rel, repo=REPO):
    r = subprocess.run(["git", "-C", str(repo), "show", "%s:%s" % (commit, rel)], capture_output=True)
    return r.stdout.decode("utf-8") if r.returncode == 0 else None


def pages_at(commit, repo=REPO):
    return {k: {"%s/%s" % (PAGES_REL, p["path"]) for p in man.get("pages", [])}
            for k, man in _manifests_at(commit, repo).items()}


def not_shipped_at(commit, files, repo=REPO):
    """export-ignore（以 X 的 .gitattributes 為準）⇒ 集合。"""
    if not files:
        return set()
    r = subprocess.run(["git", "-C", str(repo), "check-attr", "--source", commit, "--stdin", "export-ignore"],
                       input="\n".join(files).encode("utf-8"), capture_output=True)
    if r.returncode != 0:
        raise RuntimeError("git check-attr 失敗：%s" % r.stderr.decode("utf-8", "replace"))
    out = set()
    for line in r.stdout.decode("utf-8").splitlines():
        path, _attr, val = line.rsplit(": ", 2)
        if val.strip() == "set":
            out.add(path)
    return out


def manifest_modules(p, x, repo=REPO):
    """P→X version_manifest 新增或改動的條目 ⇒ 模組集合；改到／刪掉 P 已有的條目 ⇒ 含 "<shipped>"；讀不了 ⇒ None。"""
    try:
        a = json.loads(_show(p, MANIFEST, repo) or "[]")
        b = json.loads(_show(x, MANIFEST, repo) or "[]")
    except ValueError:
        return None
    ka = {(e.get("module"), e.get("version")): e for e in a}
    kb = {(e.get("module"), e.get("version")): e for e in b}
    mods = set()
    for k, e in kb.items():
        if k not in ka:
            mods.add(e.get("module"))
        elif ka[k] != e:
            mods.add("<shipped>")
    if set(ka) - set(kb):
        mods.add("<shipped>")
    # version_manifest 的 module 是顯示名（例「標案雷達」）⇒ 換成代號
    names = {}
    for key, man in _manifests_at(x, repo).items():
        for n in {man.get("name"), man.get("manifest_name"), key} - {None}:
            names[n] = key
    return {names.get(n, n if n == "<shipped>" else "<unknown:%s>" % n) for n in mods}


def read_many(commit, rels, repo=REPO):
    """一個 `git cat-file --batch` 讀多個檔 ⇒ {rel: 原始碼}（不存在的略過）。每檔一個 git show 會慢到數分鐘。"""
    rels = list(rels)
    if not rels:
        return {}
    inp = "".join("%s:%s\n" % (commit, r) for r in rels).encode("utf-8")
    r = subprocess.run(["git", "-C", str(repo), "cat-file", "--batch"], input=inp, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError("git cat-file 失敗：%s" % r.stderr.decode("utf-8", "replace"))
    data, pos, out = r.stdout, 0, {}
    for rel in rels:
        nl = data.index(b"\n", pos)
        header = data[pos:nl].decode("utf-8", "replace")
        pos = nl + 1
        if header.endswith(" missing"):
            continue
        size = int(header.rsplit(" ", 1)[1])
        out[rel] = data[pos:pos + size].decode("utf-8")
        pos += size + 1
    return out


def sources_at(commit, repo=REPO):
    rels = [r for r in _git("ls-tree", "-r", "--name-only", commit, "backend/", repo=repo).splitlines() if r.endswith(".py")]
    return read_many(commit, rels, repo)


def _manifests_at(commit, repo=REPO):
    rels = [r for r in _git("ls-tree", "-r", "--name-only", commit, "backend/modules/", repo=repo).splitlines()
            if re.match(r"^backend/modules/[^/]+/module\.json$", r)]
    return {r.split("/")[2]: json.loads(t) for r, t in read_many(commit, rels, repo).items()}


def tier_for(p, x="HEAD", overlays=None, policy=None, repo=REPO):
    """P→X ⇒ classify 結果＋provider_check（tier 2 時）。overlays：{模組: 正式機 lock 的 sha256}（已覆蓋且相等 ⇒ 扣除）。"""
    x = _git("rev-parse", x, repo=repo).strip()
    files = [f for f in _git("diff", "--name-only", "--no-renames", p, x, repo=repo).splitlines() if f]
    pages = pages_at(p, repo)
    for k, v in pages_at(x, repo).items():
        pages[k] = pages.get(k, set()) | v
    removed = []
    for key, sha in (overlays or {}).items():
        if sha and sha == module_digest_at(x, key, repo):
            gone = [f for f in files if f.startswith("backend/modules/%s/" % key) or f in pages.get(key, set())]
            removed += gone
            files = [f for f in files if f not in gone]
    res = classify(files, pages_by_module=pages, not_shipped=not_shipped_at(x, files, repo).__contains__,
                   manifest_modules=manifest_modules(p, x, repo))
    res.update(prod=p, commit=x, overlay_removed=removed, provider=None)
    if res["tier"] == TIER_MODULE:
        pc = provider_check(Repo(sources_at(x, repo)), res["key"], files, policy)
        res["provider"] = pc
        if pc["reject"]:
            res["tier"] = TIER_FULL
            res["offenders"] = [("backend/modules/%s/" % res["key"], pc["reason"])]
    return res


def module_digest_at(commit, key, repo=REPO):
    """X 時模組資料夾的 product_select.module_digest（與正式機 lock 的 sha256 同一支算法）。"""
    import io
    import tarfile
    import tempfile
    import product_select as PS
    tar = _git("archive", "--format=tar", commit, "backend/modules/%s" % key, repo=repo, binary=True)
    with tempfile.TemporaryDirectory(prefix="motrix-shiptier-") as td:
        with tarfile.open(fileobj=io.BytesIO(tar)) as t:
            t.extractall(td)
        return PS.module_digest(Path(td) / "backend" / "modules" / key)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prod", required=True, help="正式機目前的 commit（P）")
    ap.add_argument("--commit", default="HEAD", help="要出貨的 commit（X）")
    ap.add_argument("--overlay", action="append", default=[], help="正式機已套用的模組覆蓋 key=sha256")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    overlays = dict(o.split("=", 1) for o in a.overlay)
    res = tier_for(a.prod, a.commit, overlays)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1, default=sorted))
    else:
        print("等級 %s%s" % (res["tier"], "（模組 %s）" % res["key"] if res["key"] else ""))
        for f, why in res["offenders"]:
            print("  ✗ %s：%s" % (f, why))
        pc = res.get("provider")
        if pc and pc["provider_changed"]:
            print("  提供者有改：%s；消費端 %d 個檔" % ("、".join(pc["caps"]), len(pc["consumers"])))
    return 0 if res["tier"] == TIER_MODULE else 3


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
