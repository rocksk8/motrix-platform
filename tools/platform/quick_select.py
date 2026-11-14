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
SOURCE_SUFFIXES = (".html", ".js", ".py", ".css", ".json")
SOURCE_PREFIXES = ("backend/", "frontend/", "tools/")
TEST_PATHSPECS = (":(glob)backend/tests/**/*.py", ":(glob)backend/core/tests/**/*.py", ":(glob)backend/modules/*/tests/**/*.py")
GENERIC_NAMES = frozenset({"index.html", "__init__.py", "module.json", "main.py", "common.js", "style.css", "conftest.py", "config.py",
                           "db.py", "auth.py", "utils.py", "helpers.py", "api.py", "routes.py", "models.py"})
SECONDS_PER_TEST = 0.75                # 與 author_gate 同

_CJK_RUN = re.compile(r"[㐀-鿿]{3,}")
_QUOTED = re.compile(r"""(["'`])((?:\\.|(?!\1).){4,80})\1""")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_\-]{9,}")
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


def split_diff_lines(diff_text):
    """unified diff ⇒ (removed 行, added 行)；只看非測試的程式／頁面檔（測試檔自己的改動不是『來源變了』）。"""
    removed, added, cur = [], [], None
    for ln in (diff_text or "").splitlines():
        m = _DIFF_FILE.match(ln)
        if m:
            cur = m.group(2)
            continue
        if cur is None or not is_source_file(cur):
            continue
        if ln.startswith("---") or ln.startswith("+++"):
            continue
        if ln.startswith("-"):
            removed.append(ln[1:])
        elif ln.startswith("+"):
            added.append(ln[1:])
    return removed, added


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
            toks.add(m.group())
    return toks


def diff_literals(diff_text, test_tokens=None):
    """被刪掉、而且沒有在新增行重新出現的字面值（長的優先、去掉被更長字面值完全包含的短詞）。

    test_tokens＝測試檔裡出現的字面值集合（load_test_tokens）：測試常斷言「來源文字的一小段」（來源刪的是 `您沒有任何變動可儲存`、測試寫 `沒有任何變動`），
    只拿來源整段去 grep 會漏；所以另外把「測試裡的字面值 ⊂ 被刪掉的文字、且不在新增行」的也算進來（反向：以測試字面值為準，保證 grep 得到）。"""
    removed, added = split_diff_lines(diff_text)
    added_blob = "\n".join(added)
    gone = {t for t in literals_of(removed) if t not in added_blob}
    ordered = sorted(gone, key=lambda t: (-len(t), t))
    kept = []
    for t in ordered:
        if not any(t in k for k in kept):
            kept.append(t)
        if len(kept) >= MAX_LITERALS:
            break
    if test_tokens:
        removed_blob = "\n".join(removed)
        sub = sorted((t for t in test_tokens if t in removed_blob and t not in added_blob and t not in kept), key=lambda t: (-len(t), t))
        kept += sub[:MAX_TEST_SUBSTRINGS]
    return kept


def load_test_tokens(repo, ref=None):
    """測試檔裡所有字面值（CJK 連續字、引號字串、長識別字）。一次 git grep 取全部測試文字（約 20MB、~1 s），去重行後抽取。取不到 ⇒ 空集合。"""
    args = ["grep", "-h", "-I", "-e", "."]
    if ref:
        args.append(ref)
    args += ["--", *TEST_PATHSPECS]
    rc, out = _git(repo, *args)
    if rc not in (0, 1):
        return set()
    return literals_of(set(out.splitlines()))


def _git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, r.stdout


def git_grep_files(token, repo, ref=None):
    """token（固定字串）出現在哪些測試檔（git grep；ref=None ⇒ 工作樹；有 ref ⇒ 那個 commit 的 tree）。"""
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


def grep_tests(tokens, repo, ref=None, max_hits=LITERAL_MAX_HITS, grep_fn=None, workers=6):
    """⇒ (hits {測試檔: [命中的 token]}, generic [太通用被略過的 token])。grep_fn 可注入（單元測試用）。"""
    fn = grep_fn or (lambda t: git_grep_files(t, repo, ref))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(fn, tokens))
    hits, generic = {}, []
    for tok, files in zip(tokens, results):
        if len(files) > max_hits:
            generic.append(tok)
            continue
        for f in files:
            hits.setdefault(f, []).append(tok)
    return hits, generic


def reference_keys(changed):
    """改動的頁面／前端 js／工具檔名（測試通常用檔名引用它們）。太通用的檔名不用。"""
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
    "T4": "改動模組自己的測試／引用改動頁面或前端 js 的測試／全域掃描守門（可被預算砍掉）",
}


def plan_quick(*, changed, diff_text, tree_files, a2, a4, extra_t4, repo, ref, seconds_fn, workers, budget_s,
               groups=None, grep_fn=None, heavy=HEAVY_GROUPS, test_tokens=None):
    """⇒ {"tiers": {Tn: {files, why}}, "files": 依優先序去重後「要跑」的檔, "skipped": [{tier, item, reason}], "notes": [...], "estimate_s"}。

    T0–T3 一律要跑（超預算只警告）；T4 依預算由後往前砍，**被砍的每一個檔都記在 skipped**。
    重的整合守門組（HEAVY_GROUPS）整組記在 skipped（reason＝太大，整包由階段測試涵蓋）——不能看起來像通過。"""
    groups = groups if groups is not None else groups_from_tree(load_groups(), tree_files, heavy)
    notes, skipped = [], []

    t1_files, t1_why, t1_nodes = [], {}, []
    for gid, hit in triggered_groups(changed, groups):
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
    lits = diff_literals(diff_text, tokens)
    lit_hits, lit_generic = grep_tests(lits, repo, ref, grep_fn=grep_fn) if lits else ({}, [])
    if lit_generic:
        notes.append("字面值反查：%d 個字面值太通用（命中超過 %d 個測試檔）沒有選題，例：%s" % (len(lit_generic), LITERAL_MAX_HITS, "、".join(lit_generic[:3])))
    t2_files = sorted(lit_hits)
    t2_why = {f: "刪掉的字面值 " + "、".join(repr(t) for t in lit_hits[f][:2]) for f in t2_files}

    order = [("T0", sorted(a4), {f: "本分支改動" for f in a4}), ("T1", t1_files, t1_why), ("T2", t2_files, t2_why),
             ("T3", sorted(a2), {f: "檔名樣式" for f in a2}), ("T4", sorted(extra_t4), {f: "選題" for f in extra_t4})]
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
    if est_must > budget_s:
        notes.append("T0–T3 必跑部分預估 %.1f 分鐘已超過預算 %.0f 分鐘（只警告、不砍）" % (est_must / 60, budget_s / 60))
    return {"tiers": tiers, "files": files, "nodes": t1_nodes, "skipped": skipped, "notes": notes, "estimate_s": spent, "must_estimate_s": est_must,
            "literals": len(lits)}


def format_plan(plan):
    lines = []
    for name in ("T0", "T1", "T2", "T3", "T4"):
        t = plan["tiers"][name]
        n_run = len(t.get("run", t["files"]))
        lines.append("  %s %s：%d 檔%s" % (name, TIER_NAMES[name], n_run, "" if n_run == len(t["files"]) else "（選 %d、預算內只跑 %d）" % (len(t["files"]), n_run)))
    if plan["skipped"]:
        lines.append("  ⚠ 未跑（不是通過）%d 項：" % len(plan["skipped"]))
        for s in plan["skipped"][:12]:
            lines.append("    - [%s] %s：%s" % (s["tier"], s["item"], s["reason"]))
        if len(plan["skipped"]) > 12:
            lines.append("    … 另 %d 項" % (len(plan["skipped"]) - 12))
    for n in plan["notes"]:
        lines.append("  ℹ " + n)
    return "\n".join(lines)
