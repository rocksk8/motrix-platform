# -*- coding: utf-8 -*-
"""建包優化項 3：依賴指紋增量段的「選題計畫」（DRY-RUN ONLY：只算、不跑測試、不接進建包）。

設計：docs/platform/plans/BUILD-OPT-ITEM3-INCREMENTAL-DESIGN.md §2、§5、§6。

    to_run  = selected ∪ floor ∪ red_reselect          （要跑）
    carried = collected − to_run                        （沿用基準的綠）
    不變式  : selected ∪ floor ∪ red_reselect ∪ carried ⊇ collected，且 carried ∩ to_run = ∅

用法（repo 根目錄）：
  python tools/platform/stage_select.py plan --stage not_e2e|e2e --base <commit> [--head HEAD] [--json]
        [--red-stream <fail_stream.jsonl> ...] [--red-file <檔> ...] [--repo <路徑>]
        [--chain-depth N] [--base-age-hours H] [--incr-streak N] [--max-chain 2] [--max-age-hours 6] [--max-streak 3]

fail closed：任何計算錯誤、基準缺失／非祖先、硬底層、選題器自己改了、unmapped_changes 非空、鏈長／年齡超限
⇒ mode="full"（forced_full 列出每一個原因）。純函式為主；git 讀取集中在 GitReader。
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

STAGES = ("not_e2e", "e2e")
TEST_MAP_REL = "docs/platform/test_map.json"
GRAPH_REL = "docs/platform/dep_graph.json"
CONFIG_REL = "tools/platform/bottom_layer.json"

#: 選題器自己（§5.2-2）：這些檔的內容變了 ⇒ 舊的選題結果不可信 ⇒ 全量
SELECTOR_FILES = (
    "tools/platform/scope_gate.py", "tools/platform/modtest.py", "tools/platform/test_map.py",
    "tools/platform/dep_scan.py", "tools/platform/bottom_layer.json", "tools/platform/stage_select.py",
    "tools/platform/ship_tier.py", "tools/platform/failfast.py", "tools/platform/fail_stream.py",
    "backend/tools/build_test_reuse.py",
)
#: 硬底層（§3.1 M 分層）：改到 ⇒ 該段全量；tools/**、backend/tools/**、frontend/static|js|css 是軟底層，走 test_map
HARD_BOTTOM_PATTERNS = (
    r"^backend/conftest\.py$", r"(?:^|/)conftest\.py$", r"^backend/pytest\.ini$", r"^backend/requirements",
    r"^backend/core/", r"^backend/helpers/", r"^backend/db\.py$", r"^backend/migrations_frozen/",
    r"^backend/main\.py$", r"^backend/routers/", r"^backend/modules/[^/]+/migrations/", r"^product/",
    r"^frontend/index\.html$",
)
CONTRACT_DIRS = ("backend/tests/platform", "backend/core/tests")   # 同 modtest.CONTRACT_DIRS
#: F1「測工具的演練」（§5.1）：依賴鍵控，只有動到工具／核心／模組清單／選題器才進底板
TOOL_DRILL_RE = re.compile(r"^test_(module_update_delivery|scope_gate|mail_registry|modtest_rebase_check|"
                           r"module_selection|stepfile_drill|ship_tier|modtest_json_stdout|modtest_scope)(?:_|\.)")
TOOL_DRILL_TRIGGERS = (r"^tools/", r"^backend/tools/", r"^backend/core/", r"^docs/platform/modules\.json$")
#: e2e 段的登入送簽冒煙（§2.3）
E2E_SMOKE_FILES = ("backend/tests/test_e2e_playwright_2026_09_07.py",)
DEFAULT_LIMITS = {"max_chain": 2, "max_age_hours": 6.0, "max_streak": 3}

#: 掃目錄型偵測（§4.1-1）：測試程式（去註解）用這些 API 掃目錄 ⇒ test_map 記不到被掃的檔
DIR_SCAN_PATTERNS = {
    "os.listdir": re.compile(r"\bos\.listdir\("),
    "glob": re.compile(r"\bglob\.glob\(|\.glob\(|(?<![\w.])glob\("),
    "rglob": re.compile(r"\.rglob\("),
    "os.walk": re.compile(r"\bos\.walk\("),
    "iterdir": re.compile(r"\.iterdir\("),
}


# ── git 讀取 ───────────────────────────────────────────────────────────────────

def _git(*args, repo=REPO, check=True):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError("git %s 失敗：%s" % (" ".join(args), (r.stderr or r.stdout).strip()))
    return r.stdout


def rev(ref, repo=REPO):
    return _git("rev-parse", "--verify", ref + "^{commit}", repo=repo).strip()


def is_ancestor(a, b, repo=REPO):
    return subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", a, b],
                          capture_output=True).returncode == 0


class GitReader:
    """某個 commit 的檔案內容（一次 `git cat-file --batch`，快取）。"""

    def __init__(self, repo, commit):
        self.repo, self.commit = str(repo), commit
        self._cache, self._tree = {}, None

    def tree(self):
        if self._tree is None:
            out = subprocess.run(["git", "-C", self.repo, "ls-tree", "-r", "-z", "--name-only", self.commit],
                                 capture_output=True)
            if out.returncode != 0:
                raise RuntimeError("git ls-tree 失敗：" + out.stderr.decode("utf-8", "replace"))
            self._tree = {p.decode("utf-8", "replace") for p in out.stdout.split(b"\0") if p}
        return self._tree

    def read_many(self, paths):
        todo = [p for p in dict.fromkeys(paths) if p not in self._cache]
        if todo:
            req = "".join("%s:%s\n" % (self.commit, p) for p in todo).encode("utf-8")
            r = subprocess.run(["git", "-C", self.repo, "cat-file", "--batch"], input=req, capture_output=True)
            buf, pos = r.stdout, 0
            for p in todo:
                nl = buf.index(b"\n", pos)
                head = buf[pos:nl].decode("utf-8", "replace").split()
                pos = nl + 1
                if len(head) == 3 and head[1] == "blob":
                    size = int(head[2])
                    self._cache[p] = buf[pos:pos + size]
                    pos += size + 1
                else:
                    self._cache[p] = None
        return {p: self._cache[p] for p in paths}

    def read(self, path):
        return self.read_many([path])[path]

    def text(self, path):
        b = self.read(path)
        return None if b is None else b.decode("utf-8", "replace")


# ── 選題器指紋（§2.1 selector_sha）────────────────────────────────────────────────

def selector_sha(reader, files=SELECTOR_FILES):
    """選題器檔案內容的雜湊；檔不存在記成 MISSING（缺／有 的差別也算改了）。"""
    got = reader.read_many(list(files))
    h = hashlib.sha256()
    for f in sorted(files):
        b = got[f]
        h.update(("%s\0%s\n" % (f, "MISSING" if b is None else hashlib.sha256(b).hexdigest())).encode("utf-8"))
    return h.hexdigest()


# ── 掃目錄型偵測 ─────────────────────────────────────────────────────────────────

def _strip_comments(src):
    try:
        import scope_gate
        return scope_gate._code_without_comments(src)
    except Exception:                                                  # noqa: BLE001 退回原文（只會多報，不會少報）
        return src


def detect_dir_scan(src):
    """測試原始碼 ⇒ 命中的目錄掃描 API 清單（空＝沒有）。去註解後比對。"""
    code = _strip_comments(src)
    return [name for name, rx in DIR_SCAN_PATTERNS.items() if rx.search(code)]


def scan_dir_tests(reader, test_files):
    """⇒ {檔: [API]}：reader 讀得到、且命中掃目錄 API 的測試檔。"""
    got = reader.read_many(sorted(test_files))
    out = {}
    for f, b in got.items():
        if b is None:
            continue
        hit = detect_dir_scan(b.decode("utf-8", "replace"))
        if hit:
            out[f] = hit
    return out


# ── fail_stream 紅檔 ─────────────────────────────────────────────────────────────

def nodeid_file(nodeid):
    """pytest nodeid（相對 backend/）⇒ repo 相對檔路徑；不是檔路徑（如 'gw2'）⇒ None。"""
    path = (nodeid or "").split("::", 1)[0].replace("\\", "/")
    if not path.endswith(".py"):
        return None
    return path if path.startswith("backend/") else "backend/" + path


def red_files_from_records(records, stage=None):
    """fail_stream 紀錄（type=fail|node_down；aborted 不算紅）⇒ 紅檔集合。stage 給了就只取該段。"""
    out = set()
    for r in records or []:
        if not isinstance(r, dict) or r.get("type") not in ("fail", "node_down"):
            continue
        if stage and r.get("stage") and r["stage"] != stage:
            continue
        f = nodeid_file(r.get("nodeid"))
        if f:
            out.add(f)
    return out


def load_fail_stream(path):
    recs = []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            recs.append(json.loads(line))
        except ValueError:
            continue
    return recs


def normalize_red(red_files):
    out = set()
    for x in red_files or []:
        f = nodeid_file(x)
        if f:
            out.add(f)
    return out


# ── 收集集合與底板 ───────────────────────────────────────────────────────────────

_TEST_ROOT_RE = re.compile(r"^backend/(?:tests/|modules/[^/]+/tests/|core/tests/)")


def discover_tests(tree):
    """git tree ⇒ 磁碟上的測試檔（test_*.py，在 backend/tests、modules/*/tests、core/tests 下）。"""
    return {p for p in tree if _TEST_ROOT_RE.match(p) and p.rsplit("/", 1)[-1].startswith("test_")
            and p.endswith(".py") and "/node_modules/" not in p and "__pycache__" not in p}


def _looks_e2e(path, src):
    """test_map 沒有的檔（新增／未收錄）才用的啟發式；有 test_map 紀錄的以 kind 為準。"""
    return "e2e" in path.rsplit("/", 1)[-1] or bool(re.search(r"mark\.e2e|playwright", src or ""))


def collect_files(tmap, tree, reader, stage):
    """⇒ (本段收集的測試檔集合, 全部收集的測試檔集合, 發現但不在 test_map 的檔)。收集＝test_map ∪ 磁碟發現，限 git tree 內存在者。"""
    tests = tmap["tests"]
    disc = discover_tests(tree)
    extra = sorted(f for f in disc if f not in tests)
    allf = {f for f in tests if f in tree} | set(extra)
    kinds = {f: tests[f]["kind"] for f in tests}
    got = reader.read_many(extra) if extra else {}
    for f in extra:
        kinds[f] = "e2e" if _looks_e2e(f, (got.get(f) or b"").decode("utf-8", "replace")) else "other"
    want_e2e = stage == "e2e"
    out = {f for f in allf if (kinds.get(f) == "e2e") == want_e2e}
    if not want_e2e:
        # 一個檔同時有 e2e 與非 e2e 題（例 test_module_registry）：非 e2e 段也要收（fail closed：寧可多收）
        e2e_files = sorted(f for f in allf if kinds.get(f) == "e2e")
        for f, b in reader.read_many(e2e_files).items():
            if b is not None and is_mixed_e2e(b.decode("utf-8", "replace")):
                out.add(f)
    return out, allf, extra


def is_mixed_e2e(src):
    """e2e 類的檔裡有沒有標 e2e 的題以外的題：`def test_` 數 > `mark.e2e` 數，且沒有整檔的 pytestmark e2e。"""
    if re.search(r"pytestmark\s*=.*e2e", src):
        return False
    n = len(re.findall(r"^\s*(?:async\s+)?def test_", src, re.M))
    return len(re.findall(r"mark\.e2e", src)) < n


def is_tool_drill(path):
    return bool(path.startswith("backend/tests/platform/") and TOOL_DRILL_RE.match(path.rsplit("/", 1)[-1]))


def drill_triggered(changed, selector_changed, force=False):
    return bool(force or selector_changed or any(re.search(p, f) for f in changed for p in TOOL_DRILL_TRIGGERS))


def compute_floor(stage, stage_files, tmap, global_tests, reader, drill_on, legacy=False):
    """底板（§5.1）⇒ {檔: [群組]}，限本段收集的檔。
    F0a 契約目錄全部（扣 F1）、F0b global_tests、F0c unmapped、F0d 掃目錄型（無 dir: 單位者）、F1 演練（drill_on 時）、e2e 冒煙。
    legacy＝重放舊版（§3.1）：F1 不扣、不含 F0d。"""
    floor = {}

    def add(f, grp):
        if f in stage_files:
            floor.setdefault(f, []).append(grp)

    for f in sorted(stage_files):
        if any(f.startswith(d + "/") for d in CONTRACT_DIRS):
            add(f, "F0a:契約目錄")
    for f in global_tests or []:
        add(f, "F0b:global_tests")
    for f in (tmap.get("unmapped") or []):
        add(f, "F0c:unmapped")
    if not legacy:
        tests = tmap["tests"]
        for f, apis in sorted(scan_dir_tests(reader, stage_files).items()):
            has_dir = f in tests and any(u.startswith("dir:") for u in tests[f]["units"])
            if not has_dir:
                add(f, "F0d:掃目錄(%s)" % ",".join(apis))
        if stage == "e2e":
            for f in E2E_SMOKE_FILES:
                add(f, "E2E:登入冒煙")
    # F1：依賴鍵控。未觸發 ⇒ 從所有群組拿掉（交給 carried）；觸發 ⇒ 標記
    if not legacy:
        for f in [x for x in floor if is_tool_drill(x)]:
            if drill_on:
                floor[f].append("F1:工具演練(觸發)")
            else:
                del floor[f]
    return floor


# ── 集合守恆（R3-b）─────────────────────────────────────────────────────────────

def _carried(collected, to_run):
    return sorted(set(collected) - set(to_run))


def check_invariant(collected, selected, floor, red_reselect, carried):
    """selected ∪ floor ∪ red_reselect ∪ carried ⊇ collected，且 carried ∩ (selected ∪ floor ∪ red_reselect) = ∅。
    ⇒ {"ok", "missing", "overlap"}。"""
    ran = set(selected) | set(floor) | set(red_reselect)
    covered = ran | set(carried)
    missing = sorted(set(collected) - covered)
    overlap = sorted(ran & set(carried))
    return {"ok": not missing and not overlap, "missing": missing, "overlap": overlap}  # [M:invariant]


# ── 選題 ────────────────────────────────────────────────────────────────────────

def _hard_files(files, rules_fixture_layer):
    pats = [re.compile(p) for p in HARD_BOTTOM_PATTERNS]
    return sorted(f for f in files if f in rules_fixture_layer or any(p.search(f) for p in pats))


def _select(changed, tmap, graph):
    """modtest.select（iface=None＝遞移，閘門寧寬）。獨立成函式方便測試注入／替換。"""
    import modtest as MT
    return MT.select(changed, tmap, graph, None)


def _full_plan(stage, base, head, reasons, extra=None):
    p = {"stage": stage, "base": base, "head": head, "mode": "full", "forced_full": list(reasons),
         "changed_files": [], "selector_sha": {}, "collected": [], "selected": {}, "floor": {}, "red_reselect": [],
         "carried": [], "to_run": [], "to_run_all": True, "invariant": {"ok": True, "missing": [], "overlap": []},
         "scope_gate_mode": None, "soft_bottom": [], "notes": []}
    p.update(extra or {})
    return p


def compute_plan(stage, base, head="HEAD", repo=REPO, *, red_files=None, fail_records=None, base_info=None,
                 limits=None, tmap=None, graph=None, pages=None, reader=None, base_reader=None, legacy_floor=False,
                 force_drill=False, selector_files=SELECTOR_FILES):
    """⇒ 計畫 dict（見模組說明）。可能丟例外；呼叫端用 plan_stage（fail closed）。
    base_info＝基準紀錄的中繼資料（可缺，缺的項目不判，記在 notes）：chain_depth、age_hours、root_full、env_same、aborted_by、incr_streak。"""
    import scope_gate as SG
    import ship_tier as ST
    if stage not in STAGES:
        raise ValueError("stage 必須是 %s" % (STAGES,))
    lim = dict(DEFAULT_LIMITS, **(limits or {}))
    info = base_info or {}
    head_sha = rev(head, repo)
    reasons, notes = [], []

    # ── 基準 ──
    base_sha = None
    try:
        base_sha = rev(base, repo) if base else None
    except RuntimeError:
        base_sha = None
    if not base_sha:
        reasons.append("基準不存在或缺失（%r）" % (base,))
    elif not is_ancestor(base_sha, head_sha, repo):
        reasons.append("基準 %s 不是 %s 的祖先" % (base_sha[:8], head_sha[:8]))
    if info.get("chain_depth") is not None and info["chain_depth"] > lim["max_chain"]:
        reasons.append("鏈長 %s > %s" % (info["chain_depth"], lim["max_chain"]))
    if info.get("age_hours") is not None and info["age_hours"] > lim["max_age_hours"]:
        reasons.append("基準年齡 %.1f 小時 > %s" % (info["age_hours"], lim["max_age_hours"]))
    if info.get("root_full") is False:
        reasons.append("鏈根不是真全量")
    if info.get("env_same") is False:
        reasons.append("環境指紋不同")
    if info.get("aborted_by"):
        reasons.append("基準段被中斷（aborted_by=%s）" % info["aborted_by"])
    if info.get("incr_streak") is not None and info["incr_streak"] >= lim["max_streak"]:
        reasons.append("連續 %s 次增量 ⇒ 重置為全量" % info["incr_streak"])
    unchecked = [k for k in ("chain_depth", "age_hours", "root_full", "env_same", "incr_streak") if info.get(k) is None]
    if unchecked:
        notes.append("未提供基準中繼資料（未判）：" + "、".join(unchecked))

    reader = reader or GitReader(repo, head_sha)
    if tmap is None:
        t = reader.text(TEST_MAP_REL)
        tmap = json.loads(t) if t else None
    if graph is None:
        t = reader.text(GRAPH_REL)
        if t:
            g = json.loads(t)
            graph = g.get("units", g)
    if not isinstance(tmap, dict) or not isinstance(tmap.get("tests"), dict) or not tmap["tests"]:
        raise ValueError("test_map 缺或壞掉")
    if graph is None:
        raise ValueError("dep_graph 缺或壞掉")

    tree = reader.tree()
    stage_files, all_files, discovered = collect_files(tmap, tree, reader, stage)
    if discovered:
        notes.append("磁碟上有 %d 個測試檔不在 test_map（已併入收集）" % len(discovered))

    # ── 選題器自己 ──
    changed, sel_changed = [], False
    if base_sha:
        changed = [f for f in _git("diff", "--name-only", "--no-renames", base_sha, head_sha, repo=repo).splitlines() if f]
        breader = base_reader or GitReader(repo, base_sha)
        shas = {"base": selector_sha(breader, selector_files), "head": selector_sha(reader, selector_files)}
        sel_changed = shas["base"] != shas["head"] or any(f in selector_files for f in changed)      # [M:selector]
        if sel_changed:
            reasons.append("選題器自己改了（selector_sha 變：%s）" % "、".join(f for f in changed if f in selector_files)[:200])
    else:
        shas = {}

    # ── 層級判定（scope_gate.decide）＋硬底層 ──
    cfg_text = reader.text(CONFIG_REL)
    if cfg_text is None:
        raise ValueError("head 上沒有 bottom_layer.json")
    rules = SG.load_rules(text=cfg_text)
    glob_tests = json.loads(cfg_text).get("global_tests") or []
    if pages is None:
        pages = ST.pages_at(base_sha or head_sha, repo) if base_sha else {}
        for k, v in ST.pages_at(head_sha, repo).items():
            pages[k] = pages.get(k, set()) | v
    decision = SG.decide(changed, rules, pages)
    cats = decision["categories"]
    try:
        import modtest as MT
        fixture_layer = set(MT.FIXTURE_LAYER)
    except Exception:                                                  # noqa: BLE001
        fixture_layer = {"backend/conftest.py", "backend/tests/conftest.py", "backend/pytest.ini",
                         "backend/requirements.txt", "backend/requirements-dev.txt"}
    hard = _hard_files(changed, fixture_layer)
    unknown_rule = [f for f, why in decision["bottom"] if why.startswith("沒有任何規則符合")]
    for f in unknown_rule:
        if f not in hard:
            hard.append(f)
    if hard:                                                                                          # [M:hard]
        reasons.append("硬底層／fixture 層改動：%s%s" % ("、".join(hard[:6]), "…另 %d 檔" % (len(hard) - 6) if len(hard) > 6 else ""))
    soft_bottom = sorted(f for f, _ in decision["bottom"] if f not in hard)

    # ── 選題 ──
    chg, extra_tests = [], set()
    for f in changed:
        c = cats.get(f, "")
        if c.startswith("doc") or f.startswith("docs/") or f.endswith(".md"):
            continue
        if c == "bookkeeping":
            for r in rules:
                if r["re"].match(f):
                    extra_tests |= set(r["tests"])
            continue
        chg.append(f)
    picked, rep = _select(chg, tmap, graph)
    reasons_by_file = {}
    for f in picked:
        rs = [u for u in rep["reasons"].get(f, []) if u != "契約測試"]
        if rs:                                   # 只有「契約測試」理由的檔已在底板 F0a，不算選題
            reasons_by_file[f] = rs
    for f in sorted(extra_tests):
        if f in all_files:
            reasons_by_file.setdefault(f, []).append("規則附帶題")
    disc_set = set(discovered)
    for f in chg:
        if f in disc_set:                        # test_map 沒收錄的測試檔被改 ⇒ 必選
            reasons_by_file.setdefault(f, []).append("改動的測試檔")
    selected = {f: sorted(set(v)) for f, v in sorted(reasons_by_file.items()) if f in stage_files}
    unmapped = [f for f in rep["unmapped_changes"] if f not in disc_set]      # 新測試檔已由「改動的測試檔」必選
    if unmapped:
        reasons.append("unmapped_changes 非空（改動檔沒對到任何題）：%s" % "、".join(unmapped[:6]))

    # ── 底板、紅重選 ──
    drill_on = drill_triggered(changed, sel_changed, force_drill)
    floor = compute_floor(stage, stage_files, tmap, glob_tests, reader, drill_on, legacy_floor)        # [M:floor]
    reds = normalize_red(red_files) | red_files_from_records(fail_records)
    red_reselect = sorted(f for f in reds if f in stage_files)                                         # [M:red]
    red_other = sorted(f for f in reds if f not in stage_files)
    if red_other:
        notes.append("紅檔不在本段收集（其他段或已刪除）：%d 檔" % len(red_other))

    run = set(selected) | set(floor) | set(red_reselect)
    carried = _carried(stage_files, run)
    inv = check_invariant(sorted(stage_files), selected, floor, red_reselect, carried)
    if not inv["ok"]:
        reasons.append("集合守恆不成立（缺 %d、重疊 %d）" % (len(inv["missing"]), len(inv["overlap"])))

    plan = {"stage": stage, "base": base_sha, "head": head_sha, "mode": "full" if reasons else "incremental",
            "forced_full": reasons, "changed_files": changed, "selector_sha": shas,
            "collected": sorted(stage_files), "selected": selected, "floor": floor, "red_reselect": red_reselect,
            "carried": carried, "to_run": sorted(run), "to_run_all": False, "invariant": inv,
            "scope_gate_mode": decision["mode"], "soft_bottom": soft_bottom, "drill_triggered": drill_on,
            "notes": notes, "unmapped_changes": unmapped}
    if reasons:                                   # 強制全量：全部要跑、沒有沿用
        plan.update(to_run=sorted(stage_files), to_run_all=True, carried=[])
    return plan


def plan_stage(stage, base, head="HEAD", repo=REPO, **kw):
    """fail closed 包裝：任何例外 ⇒ mode=full、forced_full 帶錯誤。"""
    try:
        return compute_plan(stage, base, head, repo, **kw)
    except Exception as e:                                                                              # noqa: BLE001
        return _full_plan(stage, base, head, ["計算失敗 ⇒ 全量（fail closed）：%s: %s" % (type(e).__name__, e)])


# ── CLI ─────────────────────────────────────────────────────────────────────────

def format_plan(p):
    lines = ["stage=%s  base=%s  head=%s  mode=%s" % (p["stage"], (p["base"] or "-")[:8], (p["head"] or "-")[:8], p["mode"].upper())]
    for r in p["forced_full"]:
        lines.append("  強制全量：" + r)
    if p.get("to_run_all") and not p["collected"]:
        lines.append("  （沒有收集集合：全部要跑）")
        return "\n".join(lines)
    n = len(p["collected"])
    lines.append("  收集 %d 檔｜selected %d｜floor %d｜red_reselect %d｜carried %d｜to_run %d（%.0f%%）" % (
        n, len(p["selected"]), len(p["floor"]), len(p["red_reselect"]), len(p["carried"]), len(p["to_run"]),
        100.0 * len(p["to_run"]) / max(1, n)))
    lines.append("  不變式：%s%s" % ("成立" if p["invariant"]["ok"] else "不成立", ""))
    for f, rs in list(p["selected"].items())[:40]:
        lines.append("    selected %s  ← %s" % (f, "、".join(rs[:3])))
    if len(p["selected"]) > 40:
        lines.append("    …另 %d 檔" % (len(p["selected"]) - 40))
    for n_ in p["notes"]:
        lines.append("  註：" + n_)
    return "\n".join(lines)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                                  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="增量段選題計畫（只算不跑）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("plan")
    pl.add_argument("--stage", required=True, choices=STAGES)
    pl.add_argument("--base", required=True)
    pl.add_argument("--head", default="HEAD")
    pl.add_argument("--repo", default=str(REPO))
    pl.add_argument("--json", action="store_true")
    pl.add_argument("--red-stream", action="append", default=[], help="基準那次的 fail_stream JSONL（紅檔重選）")
    pl.add_argument("--red-file", action="append", default=[])
    pl.add_argument("--chain-depth", type=int)
    pl.add_argument("--base-age-hours", type=float)
    pl.add_argument("--incr-streak", type=int)
    pl.add_argument("--max-chain", type=int, default=DEFAULT_LIMITS["max_chain"])
    pl.add_argument("--max-age-hours", type=float, default=DEFAULT_LIMITS["max_age_hours"])
    pl.add_argument("--max-streak", type=int, default=DEFAULT_LIMITS["max_streak"])
    a = ap.parse_args(argv)
    recs = []
    for s in a.red_stream:
        recs += load_fail_stream(s)
    p = plan_stage(a.stage, a.base, a.head, a.repo, red_files=a.red_file, fail_records=recs,
                   base_info={"chain_depth": a.chain_depth, "age_hours": a.base_age_hours, "incr_streak": a.incr_streak},
                   limits={"max_chain": a.max_chain, "max_age_hours": a.max_age_hours, "max_streak": a.max_streak})
    print(json.dumps(p, ensure_ascii=False, indent=1) if a.json else format_plan(p))
    return 0


if __name__ == "__main__":
    import nowindow                                      # 預設不跳視窗（背景執行時 git／python 子行程不彈主控台）；放在入口：被 import／load_module 時不受影響
    nowindow.install()
    sys.exit(main())
