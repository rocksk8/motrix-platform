# -*- coding: utf-8 -*-
"""列車預檢（第 47 班；設計 docs/platform/TRAIN-PREFLIGHT-T47.md）。

整合／取號之後、run-stage 之前跑一次：A 靜態旗標（六類已知的便宜登記紅燈，秒級）＋ B 便宜守門測試（單一行程、不 fail-fast）
＋ C 受影響模組測試；一份報告全列出。不寫追蹤檔、不 commit、不 push。

[單位] tools:train_preflight   [層] 工具   [穩定度] 內部
用法：python tools/platform/train_preflight.py [--base origin/platform] [--static-only] [--no-impacted] [--dry-run] [--json-out F]
      python tools/platform/train_preflight.py measure     （閒置時更新各測試檔耗時；寫 full_results/preflight_seconds.json）
結束碼：0 全綠；1 有紅（靜態發現或測試紅）；2 工具本身出錯。
"""
import argparse
import ast
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CHEAP_SECONDS = 10.0
#: 不論耗時資料有沒有，一定跑的便宜守門（這個班次實際抓到過的紅燈；ab 2026-10-08 清單）。路徑相對 backend/；不存在的略過。
ALWAYS_FILES = (
    "tests/platform/test_generated_maps.py", "tests/platform/test_module_changelog_follows_code.py", "tests/test_version_manifest_2026_09_22.py",
    "tests/platform/test_v9_baseline.py", "tests/platform/test_core_upgrade.py", "tests/platform/test_l1_interface_snapshot.py",
    "tests/platform/test_product_drill_probes.py", "tests/platform/test_integration_points_registered.py", "tests/platform/test_changelog_sections.py",
    "tests/test_begin_only_via_begin_write_2026_09_25.py", "tests/test_approval_flow_scope.py", "tests/test_approval_queue_covers_every_doc_type_2026_09_24.py",
)
SCAN_HINT = re.compile(r"rglob\(|\.glob\(|glob\.glob\(|ast\.parse\(|source_tree\.|product_files\(|os\.walk\(")

sys.path.insert(0, str(HERE))


def _git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout if r.returncode == 0 else ""


def changed_files(repo, base):
    """base...HEAD 的變動檔（posix 相對路徑）；base 不存在 ⇒ []（呼叫端會看到『沒有變動』）。"""
    out = _git(repo, "diff", "--name-only", "%s...HEAD" % base)
    return [l.strip() for l in out.splitlines() if l.strip()]


def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Finding:
    def __init__(self, code, where, msg, fix):
        self.code, self.where, self.msg, self.fix = code, where, msg, fix

    def as_dict(self):
        return {"code": self.code, "where": self.where, "msg": self.msg, "fix": self.fix}


class Unchecked(Finding):
    """掃描函式匯入／執行失敗：不靜默當綠。"""

    def __init__(self, code, why):
        super().__init__(code, "preflight", "未能檢查：%s" % why, "修好工具或單獨跑對應守門")


# ── A1 CHANGELOG ──────────────────────────────────────────────────────────

_NEXT = re.compile(r"^## +\(next\)", re.M)
_NUM = re.compile(r"^## +\d+(?:\.\d+)+(?![\d.])", re.M)


def check_changelogs(repo, sections_mod=None):
    out = []
    files = [Path(repo) / "backend" / "core" / "CHANGELOG.md"] + sorted((Path(repo) / "backend" / "modules").glob("*/CHANGELOG.md"))
    try:
        sm = sections_mod or _load_module(Path(repo) / "backend" / "tests" / "platform" / "test_changelog_sections.py", "_pf_cl")
    except Exception as e:                                                   # noqa: BLE001
        return [Unchecked("A1", "test_changelog_sections 匯入失敗：%s" % e)]
    for f in files:
        if not f.exists():
            continue
        rel = f.relative_to(repo).as_posix()
        text = f.read_text(encoding="utf-8")
        nums = [m.start() for m in _NUM.finditer(text)]
        for m in _NEXT.finditer(text):
            if nums and m.start() > nums[0]:
                out.append(Finding("A1", rel, "`## (next)` 佔位在版號標題之後（被埋住）", "把 `## (next)` 區塊移到檔案最上面（第一個版號標題之前）"))
                break
        for p in sm.problems(text):
            out.append(Finding("A1", rel, p, "修正標題順序／內文（取號後版號必須由上往下遞減、內文不重複）"))
    return out


# ── A2 IP registry ────────────────────────────────────────────────────────

def check_ip_registry(repo):
    try:
        backend = str(Path(repo) / "backend")
        if backend not in sys.path:
            sys.path.insert(0, backend)
        m = _load_module(Path(repo) / "backend" / "tests" / "platform" / "test_integration_points_registered.py", "_pf_ip")
        provided, consumed = m._real()
        text = m.DOC.read_text(encoding="utf-8")
        bad = m.mismatches(m.doc_capabilities(text), provided, consumed, m.absent_module_capabilities(text))
    except Exception as e:                                                   # noqa: BLE001
        return [Unchecked("A2", "IP 登記表比對失敗：%s" % e)]
    return [Finding("A2", "docs/platform/INTEGRATION-POINTS.md", b, "補 `## IP-NNN `cap`` 節（提供方／使用方／形式＝provider…／回傳／契約版本／守門）") for b in bad]


# ── A3 bottom_layer global_tests ─────────────────────────────────────────

def check_global_tests(repo):
    try:
        import scope_gate
        cands = set(scope_gate.global_test_candidates(repo))
        listed = set(json.loads((Path(repo) / "tools" / "platform" / "bottom_layer.json").read_text(encoding="utf-8"))["global_tests"])
    except Exception as e:                                                   # noqa: BLE001
        return [Unchecked("A3", "global_tests 比對失敗：%s" % e)]
    out = [Finding("A3", "tools/platform/bottom_layer.json", "掃整棵樹的測試沒登記：%s" % p, "加進 global_tests") for p in sorted(cands - listed)]
    out += [Finding("A3", "tools/platform/bottom_layer.json", "global_tests 登記了已不是全域測試的檔：%s" % p, "從 global_tests 移除") for p in sorted(listed - cands)]
    return out


# ── A4 doc types ──────────────────────────────────────────────────────────

_REG = re.compile(r"register_doc_type\(\s*([A-Za-z_][A-Za-z_0-9]*|\"[^\"]+\"|'[^']+')")
_CONST = re.compile(r"^%s\s*=\s*[\"']([^\"']+)[\"']", re.M)


def registered_doc_types(repo):
    """modules/*/ 底下 register_doc_type 的第一個參數（字面值或同檔常數）⇒ {code: 檔}。"""
    out = {}
    for p in sorted((Path(repo) / "backend" / "modules").rglob("*.py")):
        if "/tests/" in p.as_posix():
            continue
        try:
            src = p.read_text(encoding="utf-8")
        except OSError:
            continue
        for m in _REG.finditer(src):
            a = m.group(1)
            if a[0] in "\"'":
                code = a.strip("\"'")
            else:
                cm = re.search(r"^%s\s*=\s*[\"']([^\"']+)[\"']" % re.escape(a), src, re.M)
                code = cm.group(1) if cm else None
            if code:
                out[code] = p.relative_to(repo).as_posix()
    return out


def _dict_keys_named(tree, name):
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets) and isinstance(n.value, ast.Dict):
            return {k.value for k in n.value.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    return None


def check_doc_types(repo):
    out = []
    try:
        regs = registered_doc_types(repo)
        t1 = ast.parse((Path(repo) / "backend" / "tests" / "test_approval_flow_scope.py").read_text(encoding="utf-8"))
        t2 = ast.parse((Path(repo) / "backend" / "tools" / "check_approval_queue_coverage.py").read_text(encoding="utf-8"))
    except Exception as e:                                                   # noqa: BLE001
        return [Unchecked("A4", "doc type 比對失敗：%s" % e)]
    tables = [("backend/tests/test_approval_flow_scope.py", "EXPECTED_SCOPE", t1), ("backend/tests/test_approval_flow_scope.py", "FULL_SCOPE_BODY", t1),
              ("backend/tools/check_approval_queue_coverage.py", "_QUEUE_TYPE_FOR_DOC_TYPE", t2), ("backend/tools/check_approval_queue_coverage.py", "_OWNER_MODULE", t2)]
    for rel, name, tree in tables:
        keys = _dict_keys_named(tree, name)
        if keys is None:
            out.append(Unchecked("A4", "%s 找不到 %s" % (rel, name)))
            continue
        for code, src in sorted(regs.items()):
            if code not in keys:
                out.append(Finding("A4", rel, "%s 沒有單據類型 `%s`（%s 登記了它）" % (name, code, src), "在 %s 補一行 `\"%s\": …`" % (name, code)))
    return out


# ── A5 BEGIN sites ────────────────────────────────────────────────────────

def check_begin_sites(repo):
    try:
        backend = Path(repo) / "backend"
        m = _load_module(backend / "tests" / "test_begin_only_via_begin_write_2026_09_25.py", "_pf_begin")
        m.BACKEND = backend
        bad = [s for s in m._all_sites() if (s[0], s[1]) not in m.ALLOWED]
    except Exception as e:                                                   # noqa: BLE001
        return [Unchecked("A5", "BEGIN 掃描失敗：%s" % e)]
    return [Finding("A5", "%s:%s" % (s[0], s[2]), "新的 BEGIN 出處（函式 %s）不在白名單" % s[1],
                    "改用 core.txn.begin_write／write_txn；或比照 bonus.py 把 (檔, 函式) 加進 ALLOWED（需 try/finally 保護）") for s in bad]


# ── A6 golden ────────────────────────────────────────────────────────────

_GOLDEN_REF = re.compile(r"with_name\(\s*[\"'](golden_[^\"']+\.json)[\"']")
_PAGE_REF = re.compile(r"([A-Za-z0-9_-]+\.html)")


def golden_map(repo):
    """⇒ {golden 檔名: {pages:set(頁面檔名), js:set(同名前綴 js), tests:[e2e 檔]}}（頁面取自引用它的 e2e 檔內的 `*.html` 字面值）。"""
    out = {}
    tdir = Path(repo) / "backend" / "tests"
    jsdir = Path(repo) / "frontend" / "js"
    for p in sorted(tdir.glob("test_*.py")):
        src = p.read_text(encoding="utf-8", errors="replace")
        for g in _GOLDEN_REF.findall(src):
            ent = out.setdefault(g, {"pages": set(), "js": set(), "tests": []})
            ent["tests"].append(p.relative_to(repo).as_posix())
            for pg in _PAGE_REF.findall(src):
                if (Path(repo) / "frontend" / "pages" / pg).exists():
                    ent["pages"].add(pg)
    for ent in out.values():
        for pg in list(ent["pages"]):
            stem = pg[:-5]
            ent["js"].update(j.relative_to(repo).as_posix() for j in jsdir.glob(stem + "*.js"))
    return out


def check_golden(repo, changed):
    out = []
    try:
        gm = golden_map(repo)
    except Exception as e:                                                   # noqa: BLE001
        return [Unchecked("A6", "golden 對照失敗：%s" % e)]
    ch = set(changed)
    for g, ent in sorted(gm.items()):
        if "backend/tests/" + g in ch:                       # golden 檔本身也在這次變動裡 ⇒ 已重錄，不再旗標
            continue
        hit = sorted([("frontend/pages/" + pg) for pg in ent["pages"] if "frontend/pages/" + pg in ch] + [j for j in ent["js"] if j in ch])
        if hit:
            out.append(Finding("A6", ", ".join(hit), "這支改動的頁面／JS 被 golden `%s` 涵蓋（%s），golden 檔本身沒在這次變動裡" % (g, "、".join(ent["tests"])),
                               "跑該 e2e；若紅，以該 e2e 的角色重錄 golden（差異應只有預期的那幾行，附在提交說明）；沒紅則可忽略"))
    return out


# ── A7 寫死的 DB 版本字面值 ──────────────────────────────────────────────

_EXPECT_DB = re.compile(r"--expect-db-version[\"'\s,]+(\d+)")


def current_db_version(repo):
    m = re.search(r"^CURRENT_VERSION\s*=\s*(\d+)", (Path(repo) / "backend" / "db.py").read_text(encoding="utf-8"), re.M)
    return int(m.group(1)) if m else None


def check_db_version_literals(repo):
    """測試裡寫死的 `--expect-db-version N`（N ≠ db.CURRENT_VERSION）：換版後 stepfile 演練（慢，~80 秒）才會紅，靜態先抓。"""
    try:
        cur = current_db_version(repo)
        if cur is None:
            return [Unchecked("A7", "讀不到 db.CURRENT_VERSION")]
    except OSError as e:
        return [Unchecked("A7", "讀 db.py 失敗：%s" % e)]
    out = []
    for p in sorted((Path(repo) / "backend" / "tests").rglob("test_*.py")):
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if re.search(r"CURRENT_VERSION\s*=\s*\d+", src):          # 檔內自己造了假的 db.py（固定版號的夾具）⇒ 字面值是夾具的一部分，不是漂移
            continue
        for m in _EXPECT_DB.finditer(src):
            if int(m.group(1)) != cur:
                line = src[:m.start()].count(chr(10)) + 1
                out.append(Finding("A7", "%s:%d" % (p.relative_to(repo).as_posix(), line), "寫死 --expect-db-version %s，但 CURRENT_VERSION=%s" % (m.group(1), cur),
                                   "改成引用 db.CURRENT_VERSION（或確認這題真的要釘舊版）"))
    return out


# ── A8 測試直接 get_db() 卻沒有 DB 夾具 ─────────────────────────────────

_DB_FIXTURES = {"client", "actors", "make_user", "app", "_app", "tmp_db", "db_conn", "live_server", "login_as"}


def check_bare_get_db(repo, changed):
    """只掃這次新增／修改的測試檔：測試函式呼叫 get_db() 卻沒有 client／make_user 等夾具 ⇒ 在 xdist worker 第一題時會 no such table。"""
    out = []
    for rel in changed:
        if not (rel.startswith("backend/") and "/test_" in rel and rel.endswith(".py")):
            continue
        p = Path(repo) / rel
        if not p.exists():
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]:
            args = {a.arg for a in fn.args.args}
            if args & _DB_FIXTURES:
                continue
            calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call) and ((isinstance(c.func, ast.Attribute) and c.func.attr == "get_db")
                                                                              or (isinstance(c.func, ast.Name) and c.func.id == "get_db"))]
            if calls:
                out.append(Finding("A8", "%s:%d" % (rel, fn.lineno), "測試 %s 呼叫 get_db() 但沒有 client／make_user 等夾具" % fn.name,
                                   "加上 client 夾具（否則當 xdist worker 的第一題會 no such table）"))
    return out


def check_generated(repo):
    """A0：產生檔（dep_graph／test_map／UNIT-INDEX…）是否過期。重用 tools/platform/regen_all.py --check（ab 的 wip/t47-build-optimization；
    還沒進樹 ⇒ 略過，B 層的 test_generated_maps 仍會抓到）。"""
    exe = Path(repo) / "tools" / "platform" / "regen_all.py"
    if not exe.is_file():
        return []
    r = subprocess.run([python_exe(), str(exe), "--check"], cwd=str(repo), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode == 0:
        return []
    stale = [l.strip() for l in (r.stdout or "").splitlines() if l.strip()] or ["（regen_all --check 回 %s）" % r.returncode]
    return [Finding("A0", "產生檔", "過期：%s" % "；".join(stale[:8]), "python tools/platform/regen_all.py 後提交（順序：取號→dep_scan→test_map→unit_index）")]


def static_checks(repo, changed):
    f = []
    for fn in (lambda: check_generated(repo), lambda: check_changelogs(repo), lambda: check_ip_registry(repo), lambda: check_global_tests(repo), lambda: check_doc_types(repo),
               lambda: check_begin_sites(repo), lambda: check_golden(repo, changed), lambda: check_db_version_literals(repo),
               lambda: check_bare_get_db(repo, changed)):
        try:
            f += fn()
        except Exception as e:                                               # noqa: BLE001
            f.append(Unchecked("A?", "%s" % e))
    return f


# ── B 便宜守門測試選擇 ───────────────────────────────────────────────────

def load_seconds(repo):
    """測試檔 ⇒ 秒。後者蓋前者：種子 gate_file_seconds.json → full_results/file_seconds.json → full_results/preflight_seconds.json。"""
    sec = {}
    for rel, key in (("tools/platform/gate_file_seconds.json", "seconds"), ("tools/platform/full_results/file_seconds.json", None),
                     ("tools/platform/full_results/preflight_seconds.json", None)):
        p = Path(repo) / rel
        if not p.exists():
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            d = d.get(key, d) if key else d
            sec.update({k: float(v) for k, v in d.items() if not str(k).startswith("_") and isinstance(v, (int, float))})
        except (OSError, ValueError, AttributeError):
            continue
    return sec


def _all_test_files(backend):
    files = set()
    for base in [backend / "tests"] + sorted((backend / "modules").glob("*/tests")):
        files |= {p.relative_to(backend).as_posix() for p in base.rglob("test_*.py") if "__pycache__" not in p.parts}
    return sorted(files)


def select_cheap(repo, seconds=None, threshold=CHEAP_SECONDS):
    """⇒ (檔清單（相對 backend/）, 說明 {檔: 入選理由})。e2e 檔不選（-m "not e2e" 本來就跳，且慢）。"""
    repo = Path(repo)
    backend = repo / "backend"
    seconds = load_seconds(repo) if seconds is None else seconds
    why = {}
    slow_excl = set()
    try:
        import gate_slices
        data = gate_slices.load(repo / "tools" / "platform" / "gate_slices.json") or {}
        slow_excl = set((data.get("slice0") or {}).get("exclude") or [])
        for _label, pat in gate_slices.guards(data):
            fp = pat.partition("::")[0]
            for h in sorted(backend.glob(fp)):
                if h.is_file():
                    why.setdefault(h.relative_to(backend).as_posix(), "slice0 守門")
    except Exception:                                                        # noqa: BLE001
        pass
    for p in sorted((backend / "tests" / "platform").glob("test_*.py")):
        rel = p.relative_to(backend).as_posix()
        if rel not in slow_excl:
            why.setdefault(rel, "tests/platform")
    try:
        import scope_gate
        for rel in scope_gate.global_test_candidates(repo):
            why.setdefault(rel[len("backend/"):] if rel.startswith("backend/") else rel, "掃整棵樹（全域訊號）")
    except Exception:                                                        # noqa: BLE001
        pass
    for rel in ALWAYS_FILES:
        if (backend / rel).is_file():
            why.setdefault(rel, "固定清單")
    for rel in _all_test_files(backend):
        if rel in why or "e2e" in Path(rel).name:
            continue
        key = "backend/" + rel
        s = seconds.get(key, seconds.get(rel))
        try:
            src = (backend / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if SCAN_HINT.search(src) and (s is None or s < threshold * 3):       # 掃描特徵；已知很慢（>3 倍門檻）的不選
            why[rel] = "掃描特徵"
        elif s is not None and s < threshold:
            why[rel] = "實測 %.1fs" % s
    return sorted(why), why


def impacted_dirs(repo, changed):
    import pre_train_check as PT
    keys = PT.touched_modules(changed)
    dirs, none = PT.module_test_dirs(Path(repo) / "backend", keys)
    return dirs, none, keys


def build_targets(repo, changed, include_impacted=True, seconds=None):
    cheap, why = select_cheap(repo, seconds)
    targets = list(cheap)
    dirs, none, keys = ([], [], [])
    if include_impacted:
        dirs, none, keys = impacted_dirs(repo, changed)
        targets += [d for d in dirs if not any(t == d or t.startswith(d + "/") for t in cheap)]
    return {"cheap": cheap, "why": why, "impacted_dirs": dirs, "impacted_keys": keys, "no_test_dir": none,
            "targets": list(dict.fromkeys(targets))}


# ── 執行與報告 ───────────────────────────────────────────────────────────

def python_exe():
    cand = Path("D:/MOTRIX-PLATFORM/.venv312/Scripts/python.exe")
    return str(cand) if cand.exists() else sys.executable


def run_pytest(repo, targets, tag="preflight", extra=None):
    basetemp = os.path.join(tempfile.gettempdir(), "pt_%s_%d" % (tag, os.getpid()))
    env = dict(os.environ, MOTRIX_TRAIN="1", PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    cmd = [python_exe(), "-m", "pytest", *targets, "-q", "-rfE", "--tb=short", "-m", "not e2e", "-p", "no:xdist", "-p", "no:cacheprovider",
           "--basetemp=%s" % basetemp, *(extra or [])]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=str(Path(repo) / "backend"), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        return r.returncode, r.stdout + r.stderr, time.time() - t0
    finally:
        shutil.rmtree(basetemp, ignore_errors=True)


def format_report(findings, test_groups, plan, rc, secs, passed_line):
    L = ["═══ 列車預檢 ═══"]
    un = [f for f in findings if isinstance(f, Unchecked)]
    real = [f for f in findings if not isinstance(f, Unchecked)]
    for f in un:
        L.append("⚠ %s %s" % (f.code, f.msg))
    L.append("A 靜態旗標：%d 項" % len(real))
    for f in real:
        L.append("  [%s] %s\n      %s\n      修法：%s" % (f.code, f.where, f.msg, f.fix))
    if plan is not None:
        L.append("B/C 測試：選 %d 個檔（便宜 %d＋受影響目錄 %d）%s" % (len(plan["targets"]), len(plan["cheap"]), len(plan["impacted_dirs"]),
                                                                      ("；動到但沒有 tests/ 的模組：%s" % "、".join(plan["no_test_dir"])) if plan["no_test_dir"] else ""))
    if rc is not None:
        L.append("pytest：%s（%.0f 秒，exit %s）" % (passed_line or "-", secs, rc))
        for g in test_groups:
            L.append("  歸屬 %s：%d 題紅" % (g["owner"], g["count"]))
            for kind, fs in g["kinds"].items():
                for x in fs:
                    L.append("    - [%s] %s" % (kind, x["nodeid"]))
    ok = not real and not un and (rc in (None, 0))
    L.append("結果：%s" % ("全綠（預檢綠 ≠ 閘門綠）" if ok else "有紅／未能檢查"))
    return "\n".join(L)


def preflight(repo=REPO, base="origin/platform", static_only=False, impacted=True, dry_run=False, runner=None, seconds=None):
    """⇒ (exit_code, report_text, data)。runner 供測試注入：runner(repo, targets) ⇒ (rc, out, secs)。"""
    repo = Path(repo)
    changed = changed_files(repo, base)
    findings = static_checks(repo, changed)
    plan = None
    rc = secs = None
    groups, passed_line = [], ""
    if not static_only:
        plan = build_targets(repo, changed, impacted, seconds)
        if not dry_run:
            import pre_train_check as PT
            rc, out, secs = (runner or run_pytest)(repo, plan["targets"])
            fails = PT.parse_failures(out)
            groups = PT.group_reds(fails, changed)
            m = re.findall(r"^.*\d+ (?:passed|failed).*$", out, re.M)
            passed_line = m[-1].strip() if m else ""
    text = format_report(findings, groups, plan, rc, secs, passed_line)
    bad = any(not isinstance(f, Unchecked) for f in findings) or bool(findings) or (rc not in (None, 0))
    return (1 if bad else 0), text, {"findings": [f.as_dict() for f in findings], "plan": plan, "rc": rc}


def measure(repo=REPO):
    """閒置時更新耗時：對候選（便宜＋掃描特徵＋未量測的非 e2e 檔）單行程跑 --durations=0，累計每檔 call 秒數。"""
    repo = Path(repo)
    backend = repo / "backend"
    files = [f for f in _all_test_files(backend) if "e2e" not in Path(f).name]
    rc, out, secs = run_pytest(repo, files, tag="pfmeasure", extra=["--durations=0", "--durations-min=0"])
    per = {}
    for m in re.finditer(r"^\s*([\d.]+)s (?:call|setup|teardown)\s+(\S+?)::", out, re.M):
        per["backend/" + m.group(2).replace("\\", "/").lstrip("/").replace("backend/", "", 1)] = per.get("backend/" + m.group(2).replace("\\", "/").lstrip("/").replace("backend/", "", 1), 0.0) + float(m.group(1))
    dest = repo / "tools" / "platform" / "full_results"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "preflight_seconds.json").write_text(json.dumps({"_about": "train_preflight measure（worker-秒；不進 git）", **per}, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(per), secs


def main(argv=None):
    ap = argparse.ArgumentParser(description="列車預檢")
    ap.add_argument("cmd", nargs="?", default="run", choices=["run", "measure"])
    ap.add_argument("--base", default="origin/platform")
    ap.add_argument("--static-only", action="store_true")
    ap.add_argument("--no-impacted", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json-out")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "measure":
            n, secs = measure()
            print("已量測 %d 個測試檔（%.0f 秒）" % (n, secs))
            return 0
        code, text, data = preflight(REPO, a.base, a.static_only, not a.no_impacted, a.dry_run)
    except Exception as e:                                                   # noqa: BLE001
        print("預檢工具出錯：%s" % e, file=sys.stderr)
        return 2
    print(text)
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(data, ensure_ascii=False, indent=1, default=list), encoding="utf-8")
    return code


if __name__ == "__main__":
    sys.exit(main())
