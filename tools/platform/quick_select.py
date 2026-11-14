# -*- coding: utf-8 -*-
"""作者端快速守門的選題（T87 A2；author_gate --quick 用；設計＝docs/platform/plans/AUTHOR-GATE-QUICK-T87.md）。

[單位] tools:quick_select   [層] 工具   [穩定度] 內部
[不變式]
  * 只選題、不跑測試、不寫任何追蹤檔。所有資料來自 git（tree／diff／git grep），可以對任何 commit 離線重算（回放用）。
  * 「整合守門組」的清單與觸發條件只有一份：`tools/platform/preflight_guards.json`（整合者的 preflight 用同一份；`watch` ＝ 這種改動該跑這組）。
    這裡不另外維護第二份規則表（會漂移）。
  * 優先層（必跑 T0–T3、可砍 T4）：超過預算只砍 T4，**被砍的每一項都列在 skipped（輸出必須寫「未跑」）**；T0–T3 超預算只警告、不砍。
  * T2「diff 刪掉的字面值反查」：T86 診斷 32 個紅燈絕大多數是「來源檔改了字、舊測試還在斷言舊字」——
    作者自己的 diff 裡被刪掉、且沒有在新增行重新出現的字面值（中文詞、引號字串、長識別字），在哪些測試檔裡還出現，就是最可能紅的測試。
    太常見的字面值（命中超過 LITERAL_MAX_HITS 個檔）不選（寫進 notes，不當成已檢查）。
"""
import fnmatch
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

import guard_patterns as GP  # noqa: E402

PREFLIGHT_CFG = HERE / "preflight_guards.json"
#: 太大、不適合 5 分鐘版的整合守門組（整包由階段測試／整合者 preflight 涵蓋；輸出會把它們列為「未跑」）
HEAVY_GROUPS = ("static_scans2", "recent_interplay", "superadmin_login")
LITERAL_MAX_HITS = 25                  # 一個字面值命中超過這麼多個測試檔 ⇒ 太通用，不選
REF_MAX_HITS = 30                      # 一個檔名被超過這麼多個測試檔引用 ⇒ 太通用，不選
MAX_TEST_SUBSTRINGS = 120              # 另外最多反查幾個「測試裡的字面值 ⊂ 被刪文字」
MAX_LITERALS = 120                     # 每個 diff 最多反查幾個字面值（長的優先）
SOURCE_SUFFIXES = (".html", ".js", ".py", ".css", ".json", ".md", ".sql", ".yml", ".yaml", ".ps1", ".txt", ".csv")
SOURCE_PREFIXES = ("backend/", "frontend/", "tools/", "docs/")
TEST_PATHSPECS = (":(glob)backend/tests/**/*.py", ":(glob)backend/core/tests/**/*.py", ":(glob)backend/modules/*/tests/**/*.py")
GENERIC_NAMES = frozenset({"index.html", "__init__.py", "module.json", "main.py", "common.js", "style.css", "conftest.py", "config.py",
                           "db.py", "auth.py", "utils.py", "helpers.py", "api.py", "routes.py", "models.py"})
SECONDS_PER_TEST = 0.75                # 與 author_gate 同

_CJK_RUN = re.compile(r"[㐀-鿿]{2,}")
_QUOTED = re.compile(r"""(["'`])((?:\\.|(?!\1).){4,80})\1""")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_\-]{5,}")        # 再由 _ident_ok 篩：≥10 字，或 ≥6 字且有 -／_／駝峰
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_ATTR = re.compile(r"""(?:\bid|\bclass|\bdata-[\w-]+|\bx-[\w:.@-]+|@[\w.:-]+|\bname|\bfor)\s*=\s*(?:"([^"]{2,80})"|'([^']{2,80})')""")
_DIFF_FILE = re.compile(r"^diff --git a/(.*?) b/(.*)$")


# ── 整合守門組（preflight_guards.json 的單一來源）────────────────────────────

#: quick 專用的補充觸發規則（整合者的 preflight_guards.json 不動）。每條都對應一個 T86 紅燈類型（見 docs/platform/plans/AUTHOR-GATE-QUICK-T87.md 的對照表）。
#: 格式同 preflight 組；paths 相對 backend/。只加「preflight 的 watch 沒涵蓋到、但作者端很便宜就能先跑」的守門。
QUICK_EXTRA_GROUPS = [
    {"id": "q_boundaries", "label": "L1／L2 邊界（路由／核心不得 import 模組內部）", "min_tests": 1,
     "paths": ["tests/platform/test_module_boundaries.py"], "watch": ["backend/routers/**", "backend/core/**", "backend/helpers/**", "backend/modules/*/__init__.py"]},
    {"id": "q_e2e_lint", "label": "e2e 寫法靜態檢查（新增／改動任何測試時；e2e 不一定叫 test_e2e_*）", "min_tests": 1,
     "paths": ["tests/platform/test_e2e_lint_2026_11_13.py"], "watch": ["backend/**/test_*.py", "backend/tests/platform/e2e_lint_baseline.json"]},
    {"id": "q_page_paths", "label": "page_paths／JS 列舉共用入口（任何位置的測試檔）", "min_tests": 1,
     "paths": ["tests/platform/test_page_paths_centralized.py", "tests/platform/test_no_direct_js_enumeration_2026_11_08.py"], "watch": ["backend/**/test_*.py"]},
    {"id": "q_unit_cards", "label": "單位卡公開名稱對照 L1 快照（T86 bae0c67e0）", "min_tests": 1,
     "paths": ["tests/platform/test_unit_cards.py"], "watch": ["backend/helpers/**", "backend/core/**", "backend/routers/**", "docs/platform/**"]},
    {"id": "q_platform_catalog", "label": "平台目錄／輸出點名稱（T86 12e5a7ca8 的 output-points 名稱衝突）", "min_tests": 1,
     "paths": ["tests/platform/test_platform_catalog.py"], "watch": ["backend/helpers/**", "backend/routers/**", "backend/modules/*/api/**", "backend/core/**"]},
]


def load_groups(path=PREFLIGHT_CFG, extra=True):
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    groups = list(cfg["groups"])
    if extra:
        have = {g["id"] for g in groups}
        groups += [g for g in QUICK_EXTRA_GROUPS if g["id"] not in have]
    return groups


def groups_from_tree(groups, tree_files, skip=HEAVY_GROUPS):
    """⇒ {gid: {"label", "watch", "files": [repo 相對檔], "nodes": ["backend/…::node"], "min_tests", "heavy"}}。
    pattern 相對 backend/，對 git tree 清單做 fnmatch（不讀磁碟，所以對任何 commit 都能算）。"""
    out = {}
    tree = [f for f in tree_files if f.startswith("backend/")]
    for g in groups:
        files, nodes = [], []
        for pat in g["paths"]:
            file_pat, _, node = pat.partition("::")
            hits = sorted(f for f in tree if fnmatch.fnmatchcase(f, "backend/" + file_pat))
            for h in hits:
                if node:
                    nodes.append(h + "::" + node)
                elif h not in files:
                    files.append(h)
        out[g["id"]] = {"label": g.get("label", g["id"]), "watch": g.get("watch") or [], "files": files, "nodes": nodes,
                        "min_tests": g.get("min_tests", 0), "heavy": g["id"] in skip}
    return out


def watch_hits(changed, watch):
    return [f for f in changed if any(fnmatch.fnmatchcase(f, w) for w in watch)]


def triggered_groups(changed, groups):
    """⇒ [(gid, 命中的改動檔[:3])]，依「命中的 watch 越具體越前面」排序（只靠 backend/** 這類寬 glob 命中的排後面）。"""
    out = []
    for gid, g in groups.items():
        hit = watch_hits(changed, g["watch"])
        if hit:
            narrow = [f for f in hit if any(fnmatch.fnmatchcase(f, w) and w.count("*") <= 2 and not w.endswith(("/**", "/*/**", "backend/**")) for w in g["watch"])]
            out.append((gid, hit[:3], 0 if narrow else 1))
    out.sort(key=lambda x: x[2])
    return [(gid, hit) for gid, hit, _ in out]


# ── 字面值反查（T2）────────────────────────────────────────────────────────

def is_source_file(path):
    return path.startswith(SOURCE_PREFIXES) and path.endswith(SOURCE_SUFFIXES) and not GP.is_test_file(path) and "/tests/" not in path


def parse_diff(diff_text):
    """unified diff ⇒ {檔(新路徑): {"removed": [行], "added": [行], "ranges": [(新檔起行, 迄行)]}}。含被刪除的檔（removed 有內容、ranges 為空）。"""
    out, cur = {}, None
    new_ln = 0
    for ln in (diff_text or "").splitlines():
        m = _DIFF_FILE.match(ln)
        if m:
            cur = m.group(2)
            out.setdefault(cur, {"removed": [], "added": [], "ranges": []})
            continue
        if cur is None:
            continue
        h = _HUNK.match(ln)
        if h:
            start, cnt = int(h.group(1)), int(h.group(2) if h.group(2) is not None else 1)
            new_ln = start
            if cnt:
                out[cur]["ranges"].append((start, start + cnt - 1))
            continue
        if ln.startswith("---") or ln.startswith("+++"):
            continue
        if ln.startswith("-"):
            out[cur]["removed"].append(ln[1:])
        elif ln.startswith("+"):
            out[cur]["added"].append(ln[1:])
    return out


def split_diff_lines(diff_text):
    """unified diff ⇒ (removed 行, added 行)；只看非測試的程式／頁面／文件檔（測試檔自己的改動不是『來源變了』）。"""
    removed, added = [], []
    for f, d in parse_diff(diff_text).items():
        if is_source_file(f):
            removed += d["removed"]
            added += d["added"]
    return removed, added


def _ident_ok(t):
    return len(t) >= 10 or (len(t) >= 6 and ("-" in t or "_" in t or re.search(r"[a-z][A-Z]", t) is not None))


def literals_of(lines):
    toks = set()
    for ln in lines:
        for m in _CJK_RUN.finditer(ln):
            if len(m.group()) <= 40:
                toks.add(m.group())
        for m in _QUOTED.finditer(ln):
            s = m.group(2).strip()
            if len(s) >= 4 and not s.isdigit() and sum(1 for c in s if not c.isspace()) >= 4:
                toks.add(s)
        for m in _IDENT.finditer(ln):
            if _ident_ok(m.group()):
                toks.add(m.group())
        for m in _ATTR.finditer(ln):                                   # id／class／data-*／x-*／@事件 的屬性值（任何長度≥2；class 拆成單字）
            v = (m.group(1) or m.group(2) or "").strip()
            if len(v) >= 2:
                toks.add(v)
                for w in v.split():
                    if len(w) >= 3:
                        toks.add(w)
    return toks


def diff_literals_ex(diff_text, test_tokens=None):
    """⇒ (kept 字面值清單, truncated {"direct": 被 MAX_LITERALS 截掉幾個, "reverse": 被 MAX_TEST_SUBSTRINGS 截掉幾個})。

    只認「被刪掉、而且沒有在『同一個檔』的新增行重新出現」的字面值（別的檔或註解裡出現同一個字，不代表這個檔還有它）。
    test_tokens＝測試檔裡出現的字面值集合（load_test_tokens）：測試常斷言「來源文字的一小段」（來源刪的是 `您沒有任何變動可儲存`、測試寫 `沒有任何變動`），
    只拿來源整段去 grep 會漏；所以另外把「測試裡的字面值 ⊂ 該檔被刪掉的文字、且不在該檔新增行」的也算進來（反向：以測試字面值為準，保證 grep 得到）。"""
    files = {f: d for f, d in parse_diff(diff_text).items() if is_source_file(f)}
    gone, removed_by_file = set(), []
    for f, d in files.items():
        added_blob = "\n".join(d["added"])
        gone |= {t for t in literals_of(d["removed"]) if t not in added_blob}
        if d["removed"]:
            removed_by_file.append(("\n".join(d["removed"]), added_blob))
    ordered = sorted(gone, key=lambda t: (-len(t), t))
    kept, direct_cut = [], 0
    for t in ordered:
        if any(t in k for k in kept):
            continue
        if len(kept) >= MAX_LITERALS:
            direct_cut += 1
            continue
        kept.append(t)
    sub_cut = 0
    if test_tokens:
        sub = set()
        for removed_blob, added_blob in removed_by_file:
            sub |= {t for t in test_tokens if t in removed_blob and t not in added_blob}
        sub = sorted((t for t in sub if t not in kept), key=lambda t: (-len(t), t))
        kept += sub[:MAX_TEST_SUBSTRINGS]
        sub_cut = max(0, len(sub) - MAX_TEST_SUBSTRINGS)
    return kept, {"direct": direct_cut, "reverse": sub_cut}


def diff_literals(diff_text, test_tokens=None):
    return diff_literals_ex(diff_text, test_tokens)[0]


def load_test_tokens(repo, ref=None):
    """測試檔裡所有字面值。一次 git grep 取全部測試文字（約 20MB、~1 s），去重行後抽取。**取不到 ⇒ None**（呼叫端必須把「反向探針不可用」列為未跑，不能當作沒有）。"""
    args = ["grep", "-h", "-I", "-e", "."]
    if ref:
        args.append(ref)
    args += ["--", *TEST_PATHSPECS]
    rc, out = _git(repo, *args)
    if rc not in (0, 1):
        return None
    return literals_of(set(out.splitlines()))


def _git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, r.stdout


def git_grep_files(token, repo, ref=None):
    """token（固定字串）出現在哪些測試根底下的 .py（git grep；ref=None ⇒ 工作樹；有 ref ⇒ 那個 commit 的 tree）。"""
    args = ["grep", "-l", "-F", "-I", "-e", token]
    if ref:
        args.append(ref)
    args += ["--", *TEST_PATHSPECS]
    rc, out = _git(repo, *args)
    if rc not in (0, 1):
        return []
    files = []
    for ln in out.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        files.append(ln.split(":", 1)[1] if ref and ":" in ln else ln)
    return files


def git_importers(helper_file, repo, ref=None):
    """測試根底下 import 了這個輔助模組（檔名去 .py）的 test_*.py。"""
    name = helper_file.rsplit("/", 1)[-1][:-3]
    args = ["grep", "-l", "-E", "-I", r"(^|\s)(from|import)\s+[A-Za-z0-9_.]*\b%s\b" % re.escape(name)]
    if ref:
        args.append(ref)
    args += ["--", *TEST_PATHSPECS]
    rc, out = _git(repo, *args)
    files = []
    for ln in out.splitlines() if rc in (0, 1) else []:
        ln = ln.strip()
        f = ln.split(":", 1)[1] if ref and ":" in ln else ln
        if f and is_test_basename(f):
            files.append(f)
    return files


def is_test_basename(f):
    b = f.rsplit("/", 1)[-1]
    return b.startswith("test_") and b.endswith(".py")


def grep_tests(tokens, repo, ref=None, max_hits=LITERAL_MAX_HITS, grep_fn=None, workers=6):
    """⇒ (hits {檔: [命中的 token]}, generic {太通用的 token: [它命中的所有檔]})。grep_fn 可注入（單元測試用）。"""
    fn = grep_fn or (lambda t: git_grep_files(t, repo, ref))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(fn, tokens))
    hits, generic = {}, {}
    for tok, files in zip(tokens, results):
        if len(files) > max_hits:
            generic[tok] = list(files)
            continue
        for f in files:
            hits.setdefault(f, []).append(tok)
    return hits, generic


def module_dir(path):
    m = re.match(r"(backend/modules/[^/]+/)", path)
    return m.group(1) if m else None


def narrow_generic(generic, changed, all_hit_counts, per_token=10):
    """太通用的字面值不丟掉：只選最窄的子集——同模組目錄的測試、或被 ≥2 個不同被刪字面值同時命中的測試。⇒ (選到的 {檔: [token]}, 其餘 [(token, 總數, 選了幾個)])。"""
    mods = {module_dir(c) for c in changed if module_dir(c)}
    picked, rest = {}, []
    for tok, files in generic.items():
        pick = [f for f in files if (module_dir(f) in mods) or all_hit_counts.get(f, 0) >= 2][:per_token]
        for f in pick:
            picked.setdefault(f, []).append(tok)
        rest.append((tok, len(files), len(pick)))
    return picked, rest


def split_helper_hits(hits, repo, ref, grep_fn):
    """hits 裡不是 test_*.py 的檔（conftest.py、`_xyz.py` 輔助檔）收集不到任何測試：
    輔助檔 ⇒ 換成 import 它的 test_*.py；conftest.py ⇒ 記錄未選題。⇒ (只含 test_*.py 的 hits, skipped 項目)。"""
    out, skipped = {}, []
    for f, toks in hits.items():
        if is_test_basename(f):
            out.setdefault(f, []).extend(toks)
            continue
        if f.endswith("/conftest.py") or grep_fn is not None:
            skipped.append({"tier": "T2", "item": f, "reason": "命中的是 %s（不是 test_*.py）；改動影響它所在目錄的測試，未選題（未跑）" % f.rsplit("/", 1)[-1]})
            continue
        users = git_importers(f, repo, ref)
        if not users:
            skipped.append({"tier": "T2", "item": f, "reason": "命中輔助檔 %s，找不到 import 它的測試，未選題（未跑）" % f.rsplit("/", 1)[-1]})
        for u in users[:LITERAL_MAX_HITS]:
            out.setdefault(u, []).extend(toks)
    return out, skipped


def reference_keys(changed):
    """改動（含被刪除／改名走的舊路徑）的頁面／前端 js／工具檔名（測試通常用檔名引用它們）。太通用的檔名不用。"""
    keys = []
    for f in changed:
        if GP.is_test_file(f) or "/tests/" in f:
            continue
        base = f.rsplit("/", 1)[-1]
        if base in GENERIC_NAMES:
            continue
        if f.endswith((".html", ".js")) and f.startswith("frontend/"):
            keys.append(base)
        elif f.endswith(".py") and f.startswith("tools/"):
            keys.append(base[:-3])
    return sorted(set(keys))


def referencing_tests(changed, repo, ref=None, grep_fn=None):
    keys = reference_keys(changed)
    hits, generic = grep_tests(keys, repo, ref, max_hits=REF_MAX_HITS, grep_fn=grep_fn)
    return sorted(hits), generic


# ── 路由 → 打這些路由的測試（T4）────────────────────────────────────────────

def routes_in_ranges(src, ranges):
    """⇒ [路由路徑]：source 裡「處理函式範圍和 diff 新檔改動行有交集」的路由（`@x.get/post/put/delete/patch("/p")`，加上檔內 APIRouter(prefix=…)）。
    路徑只留 `{參數}` 之前的固定前綴（測試用具體 id 呼叫），例如 /api/quotations/{no} ⇒ /api/quotations/。"""
    import ast
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    prefix = ""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) == "APIRouter":
            for kw in node.keywords:
                if kw.arg == "prefix" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    prefix = kw.value.value
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        lo = min([node.lineno] + [d.lineno for d in node.decorator_list])
        hi = getattr(node, "end_lineno", node.lineno)
        if not any(a <= hi and b >= lo for a, b in ranges):
            continue
        for d in node.decorator_list:
            if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in ("get", "post", "put", "delete", "patch") and d.args \
                    and isinstance(d.args[0], ast.Constant) and isinstance(d.args[0].value, str):
                path = prefix + d.args[0].value
                fixed = path.split("{", 1)[0]
                if len(fixed.strip("/")) >= 3:
                    out.append(fixed)
    return sorted(set(out))


def route_tests(parsed, repo, ref, grep_fn=None):
    """改動的路由檔（backend/routers、backend/modules/*/api、backend/main.py）裡被改到的路由 ⇒ 打這些路由路徑的測試。⇒ (hits {檔: [路徑]}, 路徑清單, generic)。"""
    paths = []
    for f, d in parsed.items():
        if not f.endswith(".py") or GP.is_test_file(f) or "/tests/" in f or not d["ranges"]:
            continue
        if not (f.startswith("backend/routers/") or re.match(r"backend/modules/[^/]+/api/", f) or f == "backend/main.py"):
            continue
        rc, src = _git(repo, "show", "%s:%s" % (ref, f)) if ref else (0, _read_worktree(repo, f))
        if rc == 0 and src:
            paths += routes_in_ranges(src, d["ranges"])
    paths = sorted(set(paths))
    if not paths:
        return {}, [], {}
    hits, generic = grep_tests(paths, repo, ref, max_hits=REF_MAX_HITS, grep_fn=grep_fn)
    return hits, paths, generic


def _read_worktree(repo, rel):
    try:
        return (Path(repo) / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# ── 預算與優先層 ───────────────────────────────────────────────────────────

def count_tests(root, rel):
    """檔裡 `def test_` 的題數（不展開 parametrize；讀不到 ⇒ None）。"""
    try:
        src = (Path(root) / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return sum(1 for ln in src.splitlines() if re.match(r"\s*(?:async\s+)?def test_", ln))


def estimate_seconds(files, seconds_fn, workers):
    serial = sum(seconds_fn(f) for f in files)
    return serial / (1.0 if workers <= 1 else workers * 0.85)


TIER_NAMES = {
    "T0": "本分支改動的測試檔",
    "T1": "整合守門組（依 diff 觸發，同 preflight_guards.json）",
    "T2": "diff 刪掉的字面值反查（舊斷言最可能紅的測試）",
    "T3": "檔名樣式守門檔（guard_patterns.json）",
    "T4": "改動模組自己的測試／引用改動頁面或前端 js 的測試／打改動路由的測試／e2e（最後；可被預算砍掉）",
}


def plan_quick(*, changed, diff_text, tree_files, a2, a4, extra_t4, repo, ref, seconds_fn, workers, budget_s,
               groups=None, grep_fn=None, heavy=HEAVY_GROUPS, test_tokens=None, deleted=(), is_e2e=None):
    """⇒ {"tiers": {Tn: {files, why}}, "files": 依優先序去重後「要跑」的檔, "skipped": [{tier, item, reason}], "notes": [...], "estimate_s", "over_budget"}。

    T0–T3 一律要跑（超預算只警告、over_budget=True）；T4 依預算由後往前砍（e2e 排最後＝最先砍），**被砍的每一個檔都記在 skipped**。
    凡是「沒有選到、或只選了一部分」的都要進 skipped：重的守門組、太通用字面值沒選到的檔、被截掉的字面值、不可用的反向探針、輔助檔命中——
    不能看起來像通過。deleted＝被刪除／改名走的舊路徑（只用在觸發規則與檔名引用，不進 pytest）。"""
    groups = groups if groups is not None else groups_from_tree(load_groups(), tree_files, heavy)
    is_e2e = is_e2e or (lambda f: "test_e2e_" in f.rsplit("/", 1)[-1])
    notes, skipped = [], []
    trig_changed = list(changed) + [d for d in deleted if d not in changed]

    t1_files, t1_why, t1_nodes = [], {}, []
    for gid, hit in triggered_groups(trig_changed, groups):
        g = groups[gid]
        if g["heavy"]:
            skipped.append({"tier": "T1", "item": "組 %s（%s）" % (gid, g["label"]), "reason": "太大，整包由階段測試／整合者 preflight 涵蓋"})
            continue
        for f in g["files"]:
            if f not in t1_why:
                t1_files.append(f)
                t1_why[f] = "組 %s（%s 觸發）" % (gid, "、".join(h.rsplit("/", 1)[-1] for h in hit))
        for n in g["nodes"]:
            if n not in t1_nodes:
                t1_nodes.append(n)

    tokens = test_tokens if test_tokens is not None else (load_test_tokens(repo, ref) if grep_fn is None else None)
    if test_tokens is None and grep_fn is None and tokens is None:
        skipped.append({"tier": "T2", "item": "反向探針（測試字面值 ⊂ 被刪文字）", "reason": "git grep 讀不到測試文字，探針不可用（未跑）"})
    lits, cut = diff_literals_ex(diff_text, tokens)
    if cut["direct"] or cut["reverse"]:
        skipped.append({"tier": "T2", "item": "字面值截斷", "reason": "T2 截斷：另有 %d 個字面值（來源 %d、反向 %d）未反查（未跑）；短字、短識別字最先被截" % (cut["direct"] + cut["reverse"], cut["direct"], cut["reverse"])})
    lit_hits, lit_generic = grep_tests(lits, repo, ref, grep_fn=grep_fn) if lits else ({}, {})
    if lit_generic:
        counts = {}
        for fl in lit_generic.values():
            for f in fl:
                counts[f] = counts.get(f, 0) + 1
        for f, toks in lit_hits.items():
            counts[f] = counts.get(f, 0) + len(toks)
        picked, rest = narrow_generic(lit_generic, trig_changed, counts)
        for f, toks in picked.items():
            lit_hits.setdefault(f, []).extend(toks)
        notes.append("字面值反查：%d 個字面值太通用（命中超過 %d 個測試檔）；只選最窄子集（同模組目錄或被 ≥2 個被刪字面值同時命中），例：%s" % (
            len(lit_generic), LITERAL_MAX_HITS, "、".join(list(lit_generic)[:3])))
        for tok, total, n in rest:
            skipped.append({"tier": "T2", "item": "字面值 %r" % tok[:30], "reason": "命中 %d 檔、太通用，選了 %d 檔，其餘 %d 檔未選題（未跑）" % (total, n, total - n)})
    lit_hits, helper_skips = split_helper_hits(lit_hits, repo, ref, grep_fn)
    skipped += helper_skips
    t2_files = sorted(lit_hits)
    t2_why = {f: "刪掉的字面值 " + "、".join(repr(t) for t in lit_hits[f][:2]) for f in t2_files}

    # T4：①呼叫端給的（改動模組自己的測試、頁面關聯）②引用改動頁面／js／工具檔名的測試 ③打改動路由的測試；e2e 一律排最後
    t4_why = {f: "選題" for f in extra_t4}
    t4_list = list(extra_t4)
    ref_files, ref_generic = referencing_tests(trig_changed, repo, ref, grep_fn)
    for f in ref_files:
        if f not in t4_why:
            t4_list.append(f)
            t4_why[f] = "引用改動的頁面／js／工具檔名"
    if ref_generic:
        for tok, files in ref_generic.items():
            skipped.append({"tier": "T4", "item": "檔名 %s" % tok, "reason": "被 %d 個測試檔引用、太通用，未選題（未跑）" % len(files)})
    parsed = parse_diff(diff_text)
    r_hits, r_paths, r_generic = route_tests(parsed, repo, ref, grep_fn)
    for f, ps in r_hits.items():
        if f not in t4_why:
            t4_list.append(f)
            t4_why[f] = "打改動的路由 " + "、".join(ps[:2])
    for p, files in r_generic.items():
        skipped.append({"tier": "T4", "item": "路由 %s" % p, "reason": "被 %d 個測試檔打到、太通用，未選題（未跑）" % len(files)})
    t4_list = sorted(set(t4_list), key=lambda f: (is_e2e(f), t4_list.index(f)))

    order = [("T0", sorted(a4), {f: "本分支改動" for f in a4}), ("T1", t1_files, t1_why), ("T2", t2_files, t2_why),
             ("T3", sorted(a2), {f: "檔名樣式" for f in a2}), ("T4", t4_list, t4_why)]
    seen, tiers = set(), {}
    for name, files, why in order:
        keep = []
        for f in files:
            if f in seen:
                continue
            seen.add(f)
            keep.append(f)
        tiers[name] = {"files": keep, "why": {f: why.get(f, "") for f in keep}}
    must = [f for n in ("T0", "T1", "T2", "T3") for f in tiers[n]["files"]]
    est_must = estimate_seconds(must, seconds_fn, workers)
    t4_run, spent = [], est_must
    for f in tiers["T4"]["files"]:
        cost = estimate_seconds([f], seconds_fn, workers)
        if spent + cost <= budget_s:
            t4_run.append(f)
            spent += cost
        else:
            skipped.append({"tier": "T4", "item": f, "reason": "超過 %.0f 分鐘預算（未跑）" % (budget_s / 60)})
    tiers["T4"]["run"] = t4_run
    files = must + t4_run
    over = est_must > budget_s
    if over:
        notes.append("T0–T3 必跑部分預估 %.1f 分鐘已超過預算 %.0f 分鐘（必跑層不砍；5 分鐘是目標不是保證）" % (est_must / 60, budget_s / 60))
    return {"tiers": tiers, "files": files, "nodes": t1_nodes, "skipped": skipped, "notes": notes, "estimate_s": spent, "must_estimate_s": est_must,
            "literals": len(lits), "over_budget": over, "routes": r_paths}


def format_plan(plan):
    lines = []
    for name in ("T0", "T1", "T2", "T3", "T4"):
        t = plan["tiers"][name]
        n_run = len(t.get("run", t["files"]))
        lines.append("  %s %s：%d 檔%s" % (name, TIER_NAMES[name], n_run, "" if n_run == len(t["files"]) else "（選 %d、預算內只跑 %d）" % (len(t["files"]), n_run)))
    if plan.get("over_budget"):
        lines.append("  ⚠ 超過預算：必跑的 T0–T3 預估 %.1f 分鐘（不砍；實際耗時會超過目標）" % (plan["must_estimate_s"] / 60))
    if plan["skipped"]:
        lines.append("  ⚠ 未跑（不是通過）%d 項：" % len(plan["skipped"]))
        for s in plan["skipped"][:12]:
            lines.append("    - [%s] %s：%s" % (s["tier"], s["item"], s["reason"]))
        if len(plan["skipped"]) > 12:
            lines.append("    … 另 %d 項" % (len(plan["skipped"]) - 12))
    for n in plan["notes"]:
        lines.append("  ℹ " + n)
    return "\n".join(lines)
