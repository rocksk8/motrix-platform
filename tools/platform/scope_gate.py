"""範圍驗證閘門（PLAYBOOK §D-1a；使用者 2026-09-30：「如果未影響到底層，審核測試上包可由獨立模組，不需要跑全域」）。

正式機基準 P → 要打包的 commit X 的改動檔**一個都不在底層**（底層清單唯一來源：X 上的 tools/platform/bottom_layer.json）
⇒ 出包接受「這個 commit 的範圍驗證綠燈」代替全量；任何一個在底層（或判不了）⇒ 照舊要全量。

用法（repo 根目錄；python＝主工作樹 .venv312）：
  python tools/platform/scope_gate.py plan  [--commit X] [--json]   判定＋選題（不跑）
  python tools/platform/scope_gate.py run   [--window W]            在乾淨的 HEAD 上跑範圍驗證，結果寫
                                                                      主工作樹 tools/platform/full_results/scoped/<X>.json
  python tools/platform/scope_gate.py gate  [--commit X] [--json]   閘門判定：接受 ⇒ exit 0；不接受 ⇒ exit 3

範圍驗證＝modtest --train 同型：改動模組的題（遞移選題，不用名稱層級縮小——閘門寧寬）＋改到的提供者的消費端
（ship_tier.provider_check）＋改到頁面的 e2e＋tests/platform 全部（MOTRIX_TRAIN=1，「是否最新」三題不可以被 skip）
＋規則附帶的題（bottom_layer.json 的 tests；"@global_tests"＝掃整棵樹的全域釘子）。非 e2e、e2e 兩段都要綠。

信任邊界（稽核 W4 M2～M4）：
- 基準 P：X 上 _prod_baseline.py 的 BASELINE **必須等於受信來源**＝最新的 git tag `prod/<sha>`（主持在正式機確認部署後打）；
  tag 不在或不符 ⇒ 全量（候選 commit 不可以自己把基準往後移）。
- 規則：一律讀 `git show X:tools/platform/bottom_layer.json`，不讀工作樹。
- gate 只在 HEAD＝X、而且 tools/、backend/tools/、product/ 沒有未 commit 的改動時判定（跑判定的程式就是 X 的版本）。
- 紀錄是未簽章的 JSON：gate 現場重算判定與選題，紀錄的 commit、基準、模組集合、規則雜湊、題目（⊇ 重算結果）、
  題數與兩段 exit 都要對得上；任何一項不成立 ⇒ 不接受。
"""
import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
import tokenize
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

CONFIG = HERE / "bottom_layer.json"
CONFIG_REL = "tools/platform/bottom_layer.json"
BASELINE_REL = "backend/tests/_prod_baseline.py"
#: 受信的正式機基準：主持在正式機確認部署後打的 tag（prod/<sha>）
PROD_TAG_GLOB = "refs/tags/prod/*"
#: gate 判定時這些路徑不可以有未 commit 的改動（判定程式、建包工具、產品設定）
GATE_CLEAN_PATHS = ("tools", "backend/tools", "product")
FORMAT = 1
LAYERS = ("bottom", "module", "page", "test", "doc", "bookkeeping")
_MOD_RE = re.compile(r"^backend/modules/([^/]+)/")


# ── 規則（純函式）──────────────────────────────────────────────────────────

def glob_re(pat):
    """** 跨目錄、* 不跨目錄、? 單一字元（不含 /）；其餘字面。"""
    out, i = [], 0
    while i < len(pat):
        if pat.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pat.startswith("**", i):
            out.append(".*")
            i += 2
        elif pat[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pat[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pat[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def pages_rel():
    import ship_tier
    return ship_tier.PAGES_REL


def parse_config(text):
    raw = json.loads(text)
    if raw.get("format") != FORMAT or not isinstance(raw.get("rules"), list) or not raw["rules"]:
        raise ValueError("bottom_layer.json 格式不對（format=%r）" % raw.get("format"))
    return raw


def load_rules(path=None, pages=None, text=None):
    """bottom_layer.json ⇒ [{"pattern", "layer", "why", "tests", "re"}]（照檔案順序）。格式不對 ⇒ ValueError（不猜）。
    tests 裡的 "@global_tests" 展開成最上層 global_tests 清單。"""
    raw = parse_config(text if text is not None else Path(path or CONFIG).read_text(encoding="utf-8"))
    glob_tests = raw.get("global_tests") or []
    pages = pages if pages is not None else pages_rel()
    rules = []
    for r in raw["rules"]:
        if r.get("layer") not in LAYERS or not r.get("pattern") or not r.get("why"):
            raise ValueError("bottom_layer.json 規則不完整：%r" % r)
        tests = []
        for t in r.get("tests") or []:
            tests += list(glob_tests) if t == "@global_tests" else [t]
        pat = r["pattern"].replace("{PAGES}", pages)
        rules.append(dict(r, pattern=pat, tests=tests, re=glob_re(pat)))
    return rules


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def classify_path(f, rules, pages_by_module):
    """一個改動檔 ⇒ {"layer", "key", "why", "tests"}。第一條符合的規則決定；都不符合 ⇒ bottom（fail closed）。"""
    for r in rules:
        if not r["re"].match(f):
            continue
        if r["layer"] == "module":
            return {"layer": "module", "key": _MOD_RE.match(f).group(1), "why": r["why"], "tests": r["tests"]}
        if r["layer"] == "page":
            owners = sorted(k for k, pages in (pages_by_module or {}).items() if f in pages)
            if len(owners) != 1:
                return {"layer": "bottom", "key": None, "tests": [],
                        "why": "頁面不屬於恰好一個模組（宣告者：%s）⇒ 共用頁" % ("、".join(owners) or "無")}
            return {"layer": "page", "key": owners[0], "why": r["why"], "tests": r["tests"]}
        return {"layer": r["layer"], "key": None, "why": r["why"], "tests": r["tests"]}
    return {"layer": "bottom", "key": None, "why": "沒有任何規則符合 ⇒ 當成底層（fail closed）", "tests": []}


def decide(files, rules, pages_by_module):
    """改動檔 ⇒ {"mode": "scoped"|"full", "bottom": [[檔, 原因]], "modules": [...], "categories": {檔: 層}, "extra_tests": [...]}。
    modules＝改到程式或宣告頁面的模組（範圍驗證的單位）。"""
    cats, bottom, mods, extra = {}, [], set(), set()
    for f in sorted(set(files)):
        c = classify_path(f, rules, pages_by_module)
        cats[f] = c["layer"] + (":" + c["key"] if c["key"] else "")
        extra.update(c["tests"])
        if c["layer"] == "bottom":
            bottom.append([f, c["why"]])
        elif c["key"]:
            mods.add(c["key"])
    return {"mode": "full" if bottom else "scoped", "bottom": bottom, "modules": sorted(mods),
            "categories": cats, "extra_tests": sorted(extra)}


def judge(record, commit, base, decision, config_sha=None, expected_tests=None):
    """閘門判定（純函式）⇒ (accepted, detail)。record＝範圍驗證紀錄（None＝沒有）；commit／base＝完整 SHA；
    decision＝現場重算的 decide()（含提供者檢查）；config_sha＝X 上 bottom_layer.json 的雜湊；
    expected_tests＝現場重算的選題（None＝沒有重算 ⇒ 不接受）。任何一項對不上 ⇒ 不接受。"""
    if decision.get("mode") != "scoped":
        why = "；".join("%s（%s）" % (f, w) for f, w in decision.get("bottom", [])[:6])
        more = len(decision.get("bottom", [])) - 6
        return False, "這一包動到底層 ⇒ 必須全量：%s%s" % (why, "…另 %d 檔" % more if more > 0 else "")
    if not record:
        return False, "這個 commit 沒有範圍驗證紀錄（scope_gate.py run）"
    if record.get("kind") != "scoped" or record.get("format") != FORMAT:
        return False, "紀錄不是範圍驗證（kind=%r format=%r）" % (record.get("kind"), record.get("format"))
    if (record.get("commit") or "") != commit:
        return False, "範圍驗證紀錄是 %s，不是要打包的 %s" % (str(record.get("commit"))[:8], commit[:8])
    if record.get("dirty") is not False:
        return False, "那次範圍驗證跑的時候工作樹有未 commit 的改動（或判不了），不代表這個 commit"
    if record.get("ok") is not True:
        return False, "這個 commit 的範圍驗證沒有全綠"
    if (record.get("base") or "") != base:
        return False, "範圍驗證的基準是 %s，現在的正式機基準是 %s ⇒ 重跑" % (str(record.get("base"))[:8], base[:8])
    if sorted(record.get("units") or []) != sorted(decision.get("modules") or []):
        return False, "範圍驗證的模組 %s 與現場判定 %s 不一致 ⇒ 重跑" % (record.get("units"), decision.get("modules"))
    if not config_sha or record.get("config_sha256") != config_sha:
        return False, "範圍驗證用的底層清單（雜湊 %s）不是 X 上的 bottom_layer.json（%s）⇒ 重跑" % (
            str(record.get("config_sha256"))[:12], str(config_sha)[:12])
    tests = record.get("tests")
    if not isinstance(tests, list) or not tests:
        return False, "範圍驗證紀錄沒有題目清單"
    main, e2e = record.get("main") or {}, record.get("e2e") or {}
    if main.get("exit") != 0 or not isinstance(main.get("passed"), int) or main["passed"] <= 0:
        return False, "範圍驗證的非 e2e 段不是 exit 0 且有題通過（%s）" % main
    if e2e.get("exit") not in (0, 5):
        return False, "範圍驗證的 e2e 段 exit=%r（只接受 0，或 5＝沒選到 e2e 題）" % e2e.get("exit")
    if expected_tests is None:
        return False, "沒有現場重算選題（HEAD 不是 X）⇒ 不接受"
    missing = sorted(set(expected_tests) - set(tests))
    if missing:
        return False, "範圍驗證少跑了現場選到的 %d 檔：%s" % (len(missing), "、".join(missing[:5]))
    return True, "這一包沒有動到底層；範圍驗證全綠（模組：%s）" % ("、".join(decision["modules"]) or "無，只有文件／紀錄")


# ── 全域釘子：不靠 import、掃整棵樹的測試（稽核 W4 M1）──────────────────────────────

#: 測試的程式碼（去掉註解）命中任一條 ⇒ 它掃的是整個母體（所有表、所有模組、所有頁），改任何模組都可能讓它紅
_GLOBAL_SIGNALS = {
    "sqlite_master": re.compile(r"sqlite_master"),
    "module.json 巡覽": re.compile(r"module\.json[\s\S]{0,400}?(?:glob|iterdir|listdir|os\.walk)\(|"
                                 r"(?:glob|iterdir|listdir|os\.walk)\([\s\S]{0,400}?module\.json"),
    "頁面／全庫 glob": re.compile(r"glob\([^)\n]*(?:\*\*|[\"']pages[\"'])|page_files\("),
    "權限目錄": re.compile(r"(?:from\s+helpers\.module_registry\s+import|import\s+helpers\.module_registry|"
                        r"from\s+helpers\s+import\s+[^\n]*\bmodule_registry\b)"),
}


def _code_without_comments(src):
    try:
        toks = [t for t in tokenize.generate_tokens(io.StringIO(src).readline) if t.type != tokenize.COMMENT]
        return tokenize.untokenize(toks)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return src


def global_test_candidates(root=REPO):
    """backend/tests（tests/platform 除外：每次必跑）與 modules/*/tests 的 test_*.py 裡，命中 _GLOBAL_SIGNALS 的檔 ⇒ {檔: [訊號]}。"""
    root = Path(root)
    out = {}
    roots = [root / "backend" / "tests"] + sorted((root / "backend" / "modules").glob("*/tests"))
    for base in roots:
        for p in sorted(base.rglob("test_*.py")):
            rel = p.relative_to(root).as_posix()
            if rel.startswith("backend/tests/platform/") or "__pycache__" in p.parts:
                continue
            code = _code_without_comments(p.read_text(encoding="utf-8", errors="replace"))
            hit = [k for k, r in _GLOBAL_SIGNALS.items() if r.search(code)]
            if hit:
                out[rel] = hit
    return out


# ── git 與選題 ──────────────────────────────────────────────────────────────

def _git(*args, repo=REPO, check=True):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError("git %s 失敗：%s" % (" ".join(args), (r.stderr or r.stdout).strip()))
    return r.stdout


def rev(ref, repo=REPO):
    return _git("rev-parse", "--verify", ref + "^{commit}", repo=repo).strip()


def show_bytes(commit, rel, repo=REPO):
    r = subprocess.run(["git", "-C", str(repo), "show", "%s:%s" % (commit, rel)], capture_output=True)
    return r.stdout if r.returncode == 0 else None


def config_at(commit, repo=REPO):
    """X 上的 bottom_layer.json ⇒ (文字, sha256)；X 上沒有 ⇒ (None, None)。"""
    b = show_bytes(commit, CONFIG_REL, repo)
    return (b.decode("utf-8"), sha256_bytes(b)) if b is not None else (None, None)


def baseline_at(commit, repo=REPO):
    """X 上 _prod_baseline.py 的 BASELINE（完整 SHA）；讀不到 ⇒ None。"""
    src = _git("show", "%s:%s" % (commit, BASELINE_REL), repo=repo, check=False)
    m = re.search(r'^BASELINE\s*=\s*"([0-9a-f]{7,40})"', src or "", re.M)
    if not m:
        return None
    try:
        return rev(m.group(1), repo)
    except RuntimeError:
        return None


def trusted_base(repo=REPO):
    """受信的正式機基準＝最新的 prod/<sha> tag 指向的 commit（依 tag 建立時間）；沒有 ⇒ None。"""
    out = _git("for-each-ref", "--sort=-creatordate", "--format=%(refname)", PROD_TAG_GLOB, repo=repo, check=False)
    for ref in out.splitlines():
        if ref.strip():
            try:
                return rev(ref.strip(), repo)
            except RuntimeError:
                return None
    return None


def is_ancestor(a, b, repo=REPO):
    return subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", a, b],
                          capture_output=True).returncode == 0


def _full(out, rel, why):
    out["decision"] = {"mode": "full", "bottom": [[rel, why]], "modules": [], "categories": {}, "extra_tests": []}
    return out


def assess(commit="HEAD", repo=REPO):
    """P→X 現場判定 ⇒ {"commit", "base", "trusted", "config_sha256", "files", "decision", "consumers"}。
    判不了的一律讓 decision.mode＝full。"""
    import ship_tier as ST
    commit = rev(commit, repo)
    base, trusted = baseline_at(commit, repo), trusted_base(repo)
    text, csha = config_at(commit, repo)
    out = {"commit": commit, "base": base, "trusted": trusted, "config_sha256": csha, "files": [], "consumers": [],
           "decision": None}
    if not base:
        return _full(out, BASELINE_REL, "讀不到正式機基準")
    if not trusted:
        return _full(out, BASELINE_REL, "沒有受信的正式機基準（git tag prod/<sha>）⇒ 不能證明基準是真的正式機")
    if base != trusted:
        return _full(out, BASELINE_REL, "基準 %s 與受信 tag prod/* 指向的 %s 不符" % (base[:8], trusted[:8]))
    if not is_ancestor(base, commit, repo):
        return _full(out, BASELINE_REL, "正式機基準 %s 不是 %s 的祖先" % (base[:8], commit[:8]))
    if text is None:
        return _full(out, CONFIG_REL, "X 上沒有底層清單")
    files = [f for f in _git("diff", "--name-only", "--no-renames", base, commit, repo=repo).splitlines() if f]
    pages = ST.pages_at(base, repo)
    for k, v in ST.pages_at(commit, repo).items():
        pages[k] = pages.get(k, set()) | v
    d = decide(files, load_rules(text=text), pages)
    out["files"] = files
    if d["mode"] == "scoped" and d["modules"]:
        srcs = ST.Repo(ST.sources_at(commit, repo))
        for key in d["modules"]:
            pc = ST.provider_check(srcs, key, files, policy="consumers")
            if pc["reject"]:
                d["bottom"].append(["backend/modules/%s/" % key, "提供者的消費端判不了 ⇒ 全量：%s" % pc["reason"][:300]])
            out["consumers"] += pc["consumers"]
        if d["bottom"]:
            d["mode"] = "full"
    out["consumers"] = sorted(set(out["consumers"]))
    out["decision"] = d
    return out


def select_tests(changed, consumers, extra_tests):
    """選題（在 X 的工作樹上）：modtest.select 遞移規則（不縮小）⇒ 改動檔＋消費端當虛擬改動；契約目錄必選；另加規則附帶的題。"""
    import modtest as MT
    picked, rep = MT.select(sorted(set(changed) | set(consumers)), MT.load_map(False), MT.load_graph(), None)
    tests = set(picked) | {t for t in extra_tests if (MT.REPO / t).is_file()}
    return sorted(tests), rep


# ── 紀錄 ────────────────────────────────────────────────────────────────────

def results_dir(root=None):
    import modtest as MT
    return Path(root or MT.main_worktree_root()) / "tools" / "platform" / "full_results" / "scoped"


def record_path(rdir, commit):
    name = commit if re.fullmatch(r"[0-9a-f]{40}", commit or "") else "_invalid_"
    return Path(rdir) / (name + ".json")


def read_record(rdir, commit):
    p = record_path(rdir, commit)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"kind": "unreadable"}


def gate(commit="HEAD", repo=REPO, rdir=None, selector=None):
    """⇒ {"accepted", "mode", "detail", "record_present", "commit", "base", "units", "tests", "record_path"}。
    先看紀錄檔在不在（便宜）：不在 ⇒ 不做 git 判定，直接回不接受（儀表板每次開頁都會呼叫）。
    選題現場重算：selector 沒給 ⇒ repo 是本工具所在的 repo 時用 select_tests；別的 repo（題目的暫存 repo）沒給 selector ⇒
    不重算 ⇒ judge 一律不接受。selector(改動檔, 消費端, 附帶題) -> 題目清單。"""
    commit = rev(commit, repo)
    rdir = Path(rdir) if rdir else results_dir()
    rec = read_record(rdir, commit)
    res = {"accepted": False, "mode": None, "record_present": rec is not None, "commit": commit, "base": None,
           "units": [], "tests": None, "record_path": str(record_path(rdir, commit))}
    if rec is None:
        res["detail"] = "這個 commit 沒有範圍驗證紀錄（scope_gate.py run）"
        return res
    if rev("HEAD", repo) != commit:
        res["detail"] = "判定只在 HEAD＝要打包的 commit 時做（跑判定的程式要是那一版）；HEAD 是 %s" % rev("HEAD", repo)[:8]
        return res
    dirty = _git("status", "--porcelain", "--untracked-files=normal", "--", *GATE_CLEAN_PATHS, repo=repo).strip()
    if dirty:
        res["detail"] = "%s 有未 commit 的改動 ⇒ 判定程式不是 X 的版本，不接受：%s" % (
            "／".join(GATE_CLEAN_PATHS), dirty.splitlines()[0])
        return res
    a = assess(commit, repo)
    d = a["decision"]
    expected = None
    if d["mode"] == "scoped":
        if selector is not None:
            expected = list(selector(a["files"], a["consumers"], d["extra_tests"]))
        elif Path(repo).resolve() == REPO.resolve():
            expected, _ = select_tests(a["files"], a["consumers"], d["extra_tests"])
    ok, detail = judge(rec, commit, a["base"] or "", d, a["config_sha256"], expected)
    res.update(accepted=ok, mode="scoped" if ok else None, detail=detail, base=a["base"],
               units=d["modules"], consumers=a["consumers"], bottom=d["bottom"],
               tests=len(rec.get("tests") or []) if ok else None,
               counts={"main": rec.get("main"), "e2e": rec.get("e2e")} if ok else None,
               finished=rec.get("finished") if ok else None)
    return res


# ── run ─────────────────────────────────────────────────────────────────────

def _counts(out, code):
    import modtest as MT
    return dict(MT.parse_summary(out) or {"passed": None, "failed": None, "errors": None, "skipped": None}, exit=code)


def run_ok(main_code, main_out, e2e_code, guards_collected):
    """範圍驗證綠不綠（純函式）⇒ (ok, reasons)。非 e2e 段必須 exit 0（契約目錄必有題）；e2e 段 0，或 5＝沒選到 e2e 題；
    「是否最新」三題要收集得到而且沒有因 MOTRIX_TRAIN 被 skip（同 modtest.train_judge）。"""
    import modtest as MT
    reasons = []
    if main_code != 0:
        reasons.append("非 e2e 段 exit=%s" % main_code)
    if e2e_code not in (0, 5):
        reasons.append("e2e 段 exit=%s" % e2e_code)
    _ok, more = MT.train_judge(None, 0, main_out, guards_collected)
    return not (reasons + more), reasons + more


def run(window="scopegate"):
    """在乾淨的 HEAD 上跑範圍驗證並寫紀錄（含紅、含 dirty 的也寫——閘門自己判）。exit：0 綠／1 紅／3 這一包要全量（不跑）。"""
    import modtest as MT
    MT.PYEXE = MT.resolve_python(None)
    start = MT.tree_state()
    a = assess(start[0])
    d = a["decision"]
    if d["mode"] != "scoped":
        print("[scope_gate] 這一包必須全量（modtest --full）：")
        for f, w in d["bottom"][:30]:
            print("  ✗ %s：%s" % (f, w))
        return 3
    tests, rep = select_tests(a["files"], a["consumers"], d["extra_tests"])
    print("[scope_gate] 基準 %s → %s；模組 %s；消費端 %d 檔；選題 %d 檔" % (
        a["base"][:8], a["commit"][:8], "、".join(d["modules"]) or "無", len(a["consumers"]), len(tests)))
    rec = {"kind": "scoped", "format": FORMAT, "commit": a["commit"], "base": a["base"],
           "branch": MT.git("rev-parse", "--abbrev-ref", "HEAD").strip(), "units": d["modules"],
           "consumers": a["consumers"], "categories": d["categories"], "tests": tests,
           "config_sha256": a["config_sha256"], "started": MT._now(), "finished": None, "ok": False,
           "dirty": MT.run_dirty(start, start), "python": MT.PYEXE, "main": None, "e2e": None}
    prev = os.environ.get("MOTRIX_TRAIN")
    os.environ["MOTRIX_TRAIN"] = "1"
    t0 = time.monotonic()
    try:
        cap = MT.full_max_workers()
        c1, o1 = MT.run_pytest(tests, MT.cap_workers(["-m", "not e2e", "-n", str(cap), "-rs"], cap), window, full=False)
        rec["main"] = _counts(o1, c1)
        e2e_cap = MT.e2e_max_workers()
        c2, o2 = MT.run_pytest(tests, MT.cap_workers(["-m", "e2e", "-n", str(e2e_cap)], e2e_cap), window + "e2e",
                               full=False)
        rec["e2e"] = _counts(o2, c2)
        _cc, cout = MT.run_pytest(list(MT.TRAIN_GUARDS), [], window + "tg", full=False, collect_only=True)
        collected = {g for g in MT.TRAIN_GUARDS if g.split("tests/", 1)[-1] in cout or g in cout}
        ok, reasons = run_ok(c1, o1, c2, collected)
        rec["ok"] = ok
        rec["reasons"] = reasons
    finally:
        if prev is None:
            os.environ.pop("MOTRIX_TRAIN", None)
        else:
            os.environ["MOTRIX_TRAIN"] = prev
        rec["finished"] = MT._now()
        rec["seconds"] = round(time.monotonic() - t0, 1)
        end = MT.tree_state()
        rec["dirty"] = MT.run_dirty(start, end)
        dest = record_path(results_dir(), rec["commit"])
        MT._atomic_write_json(dest, rec)
        print("[scope_gate] %s ok=%s dirty=%s → %s" % (rec["commit"][:8], rec["ok"], rec["dirty"], dest))
    return 0 if rec["ok"] and not rec["dirty"] else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=("plan", "run", "gate"))
    ap.add_argument("--commit", default="HEAD")
    ap.add_argument("--window", default="scopegate")
    ap.add_argument("--results-dir", help="範圍驗證紀錄所在（預設主工作樹 tools/platform/full_results/scoped）")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_]+", a.window):
        ap.error("--window 只能是英數底線")
    if a.action == "run":
        return run(a.window)
    if a.action == "gate":
        res = gate(a.commit, rdir=a.results_dir)
        if a.json:
            # ASCII 跳脫：PowerShell 5.1 以系統字碼頁（cp950）解讀原生程式的輸出，中文會變亂碼（建包讀的就是這一份）
            sys.stdout.buffer.write((json.dumps(res, ensure_ascii=True) + "\n").encode("ascii"))
        else:
            print("%s：%s" % ("接受範圍驗證" if res["accepted"] else "不接受", res["detail"]))
        return 0 if res["accepted"] else 3
    a2 = assess(a.commit)
    d = a2["decision"]
    if d["mode"] == "scoped" and rev("HEAD") == a2["commit"]:
        a2["tests"], _ = select_tests(a2["files"], a2["consumers"], d["extra_tests"])
    if a.json:
        sys.stdout.buffer.write((json.dumps(a2, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    else:
        print("基準 %s（受信 %s）→ %s：%s" % ((a2["base"] or "?")[:8], (a2["trusted"] or "無 prod/* tag")[:12],
                                          a2["commit"][:8], "範圍驗證可用" if d["mode"] == "scoped" else "必須全量"))
        for f, w in d["bottom"][:30]:
            print("  ✗ %s：%s" % (f, w))
        if d["mode"] == "scoped":
            print("  模組：%s；消費端 %d 檔；選題 %s 檔" % ("、".join(d["modules"]) or "無", len(a2["consumers"]),
                                                    len(a2.get("tests") or []) if "tests" in a2 else "（HEAD 不是 X，未選）"))
    return 0 if d["mode"] == "scoped" else 3


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
