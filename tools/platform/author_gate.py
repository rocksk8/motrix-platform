# -*- coding: utf-8 -*-
"""作者端守門集：作者推「最終 sha」之前跑的一支指令（建包優化 step 4；設計＝docs/platform/plans/AUTHOR-GATE-DESIGN.md）。

⚠️ 只是**作者端預檢**：把整合樹／建包才會紅的守門提早到作者手上。**絕不替代建包的完整階段**——結果檔只能當「部分證據／提示」，
不得讓建包或 pre_train_check 略過任何一題（建包整段 not_e2e／e2e 照跑）。

用法（repo 根目錄；工作樹必須乾淨，含未追蹤檔）：
  python tools/platform/author_gate.py [--base <ref>] [--head HEAD] [--workers 2] [--budget-min 12] [--json-out <路徑>]
                                       [--dry-run] [--skip-e2e] [--known-red <json>]
  python tools/platform/author_gate.py replay [--cases <json>] [--run] [--case <名稱> ...]

選題（去重取聯集）：
  A1 底板：stage_select 的 not_e2e floor（tests/platform 整個目錄、global_tests、unmapped、掃目錄型；**工具演練檔依 diff 觸發**——
     TOOL_DRILL_RE：只有動到 tools/、backend/tools/、core、modules.json 或選題器時才跑）
  A2 檔名樣式守門檔：PATTERNS（跨 backend/tests、modules/*/tests、core/tests）＋ pre_train_check.GUARDS
  A3 test_map／stage_select 對本分支改動檔選到的題（not_e2e；e2e 另成一段，單獨計時、不計入預算警告）
  A4 本分支新增／修改的測試檔本身
預算（--budget-min，預設 12）只警告、不截斷、不砍任何一項。workers 預設 2（全機測試名額），1＝不用 -n。
結果 JSON：tools/platform/author_gate_results/<head12>.json（不進 git）；綁 head／tree sha／selector sha；讀的人現場重算，不符＝沒有紀錄。
退出碼：0 綠；1 有紅；2 拒絕執行（工作樹不乾淨、基準不存在…）或工具出錯。
"""
import argparse
import fnmatch
import glob
import hashlib
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
sys.path.insert(0, str(HERE))

import guard_patterns as GP  # noqa: E402
import nowindow  # noqa: E402

#: A2：檔名樣式（比對 basename；跨所有測試根）——唯一一份在 tools/platform/guard_patterns.json（負責人 a3；增量選題底板共用）
PATTERNS = GP.patterns()
RESULT_DIR = HERE / "author_gate_results"
TIMES_FILE = HERE / "author_gate_times.json"
DEFAULT_FILE_SECONDS = 12.0          # 沒有歷史秒數的檔（序列秒數；實測 2267 題 1693 s ≈ 0.75 s／題，平均每檔 ~11 s）
DEFAULT_REPLAY_CASES = HERE / "author_gate_replay.json"
RESULT_VERSION = 1


# ── 純函式（有題）────────────────────────────────────────────────────────

def is_test_file(path):
    return GP.is_test_file(path)


def pattern_files(tree_files, patterns=PATTERNS):
    """git tree 的檔案清單 ⇒ 符合樣式的測試檔（排序、去重）。樣式預設取 guard_patterns.json。"""
    return GP.match_files(tree_files, pats=patterns)


def build_selection(plan_n, plan_e, tree_files, changed, guard_args=(), patterns=PATTERNS, full_floor=False):
    """⇒ {"A1": [...], "A2": [...], "A3": [...], "A4": [...], "E": [...], "non_e2e": [...聯集...], "forced_full": [...]}
    全部是 repo 相對路徑（backend/…）。plan_*＝stage_select 的計畫 dict（floor／selected 一律取用，即使 mode=full——
    mode=full 只代表「建包會整段跑」，作者端仍只跑底板＋選題，並把原因印出來）。"""
    floor = (plan_n or {}).get("floor") or {}
    #: A1＝契約目錄（tests/platform 整個，F0a）＋依 diff 觸發的工具演練（F1）；其餘底板（F0b global_tests、F0c unmapped、F0d 掃目錄型）
    #: 是建包整段才需要的，作者端預設不跑（--full-floor 才加），以免預算被吃掉
    a1 = sorted(f for f, grp in floor.items() if any(g.startswith(("F0a", "F1")) for g in grp))
    a1x = sorted(set(floor) - set(a1))
    if full_floor:
        a1 = sorted(set(a1) | set(a1x))
    a3 = sorted((plan_n or {}).get("selected") or {})
    a2 = pattern_files(tree_files, patterns)
    guard_files = sorted({"backend/" + g.split("::", 1)[0] for g in guard_args})
    a2 = sorted(set(a2) | set(guard_files))
    changed_tests = sorted(f for f in changed if is_test_file(f))
    e2e_sel = set((plan_e or {}).get("selected") or {})
    e2e_collected = set((plan_e or {}).get("collected") or [])
    a4 = [f for f in changed_tests if f not in e2e_sel and f not in e2e_collected]        # e2e 類的測試檔改動 ⇒ 進 e2e 那一段
    e2e_files = sorted(e2e_sel | {f for f in changed_tests if f in e2e_collected})
    non_e2e = sorted(set(a1) | set(a2) | set(a3) | set(a4))
    forced = list(dict.fromkeys(((plan_n or {}).get("forced_full") or []) + ((plan_e or {}).get("forced_full") or [])))
    return {"A1": a1, "A1x": a1x, "A2": a2, "A3": a3, "A4": a4, "E": e2e_files, "non_e2e": non_e2e, "forced_full": forced}


def load_times(path=TIMES_FILE):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")).get("files", {})
    except (OSError, ValueError):
        return {}


SECONDS_PER_TEST = 0.75                # 實測：tests/platform 2267 題單行程 1693 s


def count_tests(path):
    """檔裡會在 `-m "not e2e"` 段跑的 `def test_` 數（不展開 parametrize；整檔 pytestmark e2e ⇒ 0；標了 mark.e2e 的題不算；讀不到 ⇒ None）。"""
    try:
        src = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if re.search(r"(?m)^pytestmark\s*=.*e2e", src):
        return 0
    lines, n = src.splitlines(), 0
    for i, ln in enumerate(lines):
        if re.match(r"\s*(?:async\s+)?def test_", ln):
            deco = " ".join(lines[max(0, i - 4):i])
            if "mark.e2e" not in deco:
                n += 1
    return n


def file_seconds(f, times, root=None):
    """單檔序列秒數：有歷史（author_gate_times.json）用歷史；沒有就「題數 × 0.75 s」（讀得到檔時），讀不到才用 DEFAULT_FILE_SECONDS。"""
    if f in times:
        return float(times[f])
    if root is not None:
        n = count_tests(Path(root) / f)
        if n is not None:
            return max(1.0, n * SECONDS_PER_TEST)
    return DEFAULT_FILE_SECONDS


def estimate_seconds(files, times, workers, root=None):
    """Σ 各檔序列秒數 ÷ 有效 worker 數（xdist 並行效率打 0.85 折）。近似值：只用來預警，不用來砍題。"""
    serial = sum(file_seconds(f, times, root) for f in files)
    eff = 1.0 if workers <= 1 else workers * 0.85
    return serial / eff


def budget_warning(estimate_s, budget_min, files, times, top=10, root=None):
    """超出預算 ⇒ 警告文字（含占時間最大的前幾個檔）；沒超出 ⇒ None。只警告，呼叫端不得因此砍題。"""
    if estimate_s <= budget_min * 60:
        return None
    big = sorted(files, key=lambda f: -file_seconds(f, times, root))[:top]
    return "預估 %.1f 分鐘超過預算 %d 分鐘（只警告、不砍任何一項）；占時間最多：%s" % (
        estimate_s / 60, budget_min, "、".join("%s(%.0fs)" % (f.rsplit("/", 1)[-1], file_seconds(f, times, root)) for f in big))


def parse_counts(text):
    """pytest 摘要行 ⇒ {"passed": N, "failed": N, "errors": N, "skipped": N}。"""
    out = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    for n, word in re.findall(r"(\d+) (passed|failed|error|errors|skipped)\b", text or ""):
        key = {"error": "errors"}.get(word, word)
        out[key] = max(out[key], int(n))
    return out


def classify_failures(failures, known_red):
    """⇒ (新的紅, 已登記的紅)。known_red＝nodeid 集合（可為檔路徑前綴）；只准縮短，不在這裡新增。"""
    new, known = [], []
    for f in failures:
        nid = f["nodeid"].replace("\\", "/")
        (known if any(nid == k or nid.startswith(k + "::") for k in known_red) else new).append(f)
    return new, known


def make_result(*, head, base, tree_sha, selector_sha, groups, counts, failures_new, failures_known, duration_s, estimate_s,
                workers, stopped_by_failfast, forced_full, started, finished, e2e=None):
    """結果 JSON（綠＝沒有任何「新的紅」且確實有題被收集；紅了不可能寫 green:true）。"""
    ran_any = counts.get("passed", 0) + counts.get("failed", 0) + counts.get("errors", 0) > 0
    green = bool(ran_any and not failures_new and counts.get("failed", 0) + counts.get("errors", 0) == len(failures_known)
                 and (e2e is None or e2e.get("green")))
    return {"version": RESULT_VERSION, "head": head, "base": base, "tree_sha": tree_sha, "selector_sha": selector_sha,
            "partial_evidence_only": True, "workers": workers,
            "groups": {k: {"files": len(v)} for k, v in groups.items() if k in ("A1", "A2", "A3", "A4", "E")},
            "ran": counts, "failed_new": [f["nodeid"] for f in failures_new], "failed_known": [f["nodeid"] for f in failures_known],
            "green": green, "duration_s": round(duration_s, 1), "estimate_s": round(estimate_s, 1),
            "stopped_by_failfast": bool(stopped_by_failfast), "forced_full_for_build": forced_full, "e2e": e2e,
            "started": started, "finished": finished}


def read_result(path, *, head, tree_sha, selector_sha):
    """讀端：現場重算的 head／tree／selector 與檔內不符 ⇒ None（當沒有紀錄）；格式不對 ⇒ None。"""
    try:
        r = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if r.get("version") != RESULT_VERSION or r.get("head") != head or r.get("tree_sha") != tree_sha or r.get("selector_sha") != selector_sha:
        return None
    return r


# ── git／執行 ───────────────────────────────────────────────────────────

def _git(*args, repo=REPO):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, r.stdout, r.stderr


def dirty_files(repo=REPO):
    """工作樹不乾淨的檔（含未追蹤，不含 .gitignore 的）。"""
    rc, out, err = _git("status", "--porcelain", "--untracked-files=all", repo=repo)
    if rc != 0:
        raise RuntimeError("git status 失敗：" + err.strip())
    return [ln[3:] for ln in out.splitlines() if ln.strip()]


def resolve(ref, repo=REPO):
    rc, out, err = _git("rev-parse", "--verify", ref + "^{commit}", repo=repo)
    if rc != 0:
        raise RuntimeError("找不到 %r：%s" % (ref, err.strip()))
    return out.strip()


def default_base(head, repo=REPO):
    for cand in ("origin/platform", "platform"):
        rc, out, _ = _git("merge-base", head, cand, repo=repo)
        if rc == 0 and out.strip():
            return out.strip()
    raise RuntimeError("找不到預設基準（merge-base HEAD origin/platform）；請用 --base 指定")


def tree_files_at(sha, repo=REPO):
    rc, out, err = _git("ls-tree", "-r", "--name-only", sha, repo=repo)
    if rc != 0:
        raise RuntimeError("git ls-tree 失敗：" + err.strip())
    return out.splitlines()


def changed_files(base, head, repo=REPO):
    rc, out, err = _git("diff", "--name-only", "--no-renames", base, head, repo=repo)
    if rc != 0:
        raise RuntimeError("git diff 失敗：" + err.strip())
    return [f for f in out.splitlines() if f]


def tree_sha_of(head, repo=REPO):
    rc, out, err = _git("rev-parse", head + "^{tree}", repo=repo)
    if rc != 0:
        raise RuntimeError(err.strip())
    return out.strip()


def project_python(repo=REPO):
    """專案專用 venv 的 python（共用樹的 .venv312；worktree 沒有自己的就往主工作樹找）。找不到 ⇒ None。"""
    cands = [Path(repo) / ".venv312" / "Scripts" / "python.exe"]
    rc, out, _ = _git("rev-parse", "--git-common-dir", repo=repo)
    if rc == 0 and out.strip():
        common = Path(out.strip())
        common = common if common.is_absolute() else Path(repo) / common
        cands.append(common.resolve().parent / ".venv312" / "Scripts" / "python.exe")
    for c in cands:
        if c.is_file():
            return c
    return None


def venv_warning(repo=REPO, exe=None):
    """目前的 python 不是專案 venv ⇒ 警告文字（否則 requirements 涵蓋題會因『別人的 venv 什麼都有』而紅或綠不準）；沒問題 ⇒ None。"""
    want = project_python(repo)
    cur = Path(exe or sys.executable)
    try:
        if want is None or cur.resolve() == want.resolve():
            return None
    except OSError:
        return None
    return "目前的 python（%s）不是專案 venv（%s）：requirements 涵蓋題的結果會和列車不同；請用專案 venv 的 python 執行本工具" % (cur, want)


#: Windows 命令列上限約 32767 字元；留餘裕。超過就把 pytest 參數放進 @argsfile（pytest ≥ 8.2 支援，一行一個參數）
ARGV_LIMIT = 24000


def spill_argv(argv, limit=ARGV_LIMIT):
    """⇒ (實際 argv, 暫存 argsfile 路徑或 None)。argv 形如 [python, -m, pytest, 其餘…]；過長時其餘參數改走 @file。"""
    if sum(len(a) + 1 for a in argv) <= limit:
        return list(argv), None
    i = argv.index("pytest") + 1 if "pytest" in argv else 0
    fd, path = tempfile.mkstemp(prefix="author_gate_args_", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(argv[i:]) + "\n")
    return list(argv[:i]) + ["@" + path], path


def run_pytest(argv, cwd, env, stream=True):
    argv, spilled = spill_argv(argv)
    try:
        return _run_pytest(argv, cwd, env, stream)
    finally:
        if spilled:
            try:
                os.remove(spilled)
            except OSError:
                pass


def _run_pytest(argv, cwd, env, stream=True):
    e = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    e.update(env or {})
    flags = (getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0) | nowindow.CREATE_NO_WINDOW) if os.name == "nt" else 0       # 低優先權、不跳視窗
    proc = subprocess.Popen(argv, cwd=str(cwd), env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=flags)
    lines = []
    for raw in proc.stdout:
        line = raw.decode("utf-8", errors="replace")
        lines.append(line)
        if stream:
            sys.stdout.write(line)
            sys.stdout.flush()
    return proc.wait(), "".join(lines)


def build_cmds(python, backend_rel_files, guard_args, e2e_files, basetemp, workers):
    """⇒ (not_e2e 指令, e2e 指令或 None)。檔路徑相對 backend/。"""
    plain = sorted(set(backend_rel_files))
    nodes = sorted({g for g in guard_args if "::" in g and g.split("::", 1)[0] not in set(plain)})     # 整檔已在，就不再重複點名
    non = [python, "-m", "pytest", *plain, *nodes, "-q", "-rfE", "--tb=short", "-m", "not e2e", "-p", "no:cacheprovider",
           "--basetemp=%s" % basetemp]
    if workers > 1:
        non += ["-n", str(workers)]
    e2e = None
    if e2e_files:
        e2e = [python, "-m", "pytest", *e2e_files, "-q", "-rfE", "--tb=short", "-m", "e2e", "-p", "no:cacheprovider",
               "--basetemp=%s-e2e" % basetemp]
    return non, e2e


def strip_backend(paths):
    return [p[len("backend/"):] if p.startswith("backend/") else p for p in paths]


# ── 主流程 ───────────────────────────────────────────────────────────────

def select_for(base, head, repo=REPO, full_floor=False):
    import stage_select as SS
    from pre_train_check import GUARDS, expand_guards
    plan_n = SS.plan_stage("not_e2e", base, head, str(repo))
    plan_e = SS.plan_stage("e2e", base, head, str(repo))
    guard_args, missing = expand_guards(Path(repo) / "backend", GUARDS)
    sel = build_selection(plan_n, plan_e, tree_files_at(head, repo), changed_files(base, head, repo), guard_args, full_floor=full_floor)
    sel["guard_args"], sel["guards_missing"] = guard_args, missing
    return sel, plan_n, plan_e


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    nowindow.install()                                   # 預設不跳視窗（MOTRIX_SHOW_WINDOWS=1 可關掉）
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "replay":
        return replay_main(argv[1:])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--workers", type=int, default=2, help="pytest -n（預設 2＝全機測試名額；1＝不用 -n）")
    ap.add_argument("--budget-min", type=int, default=12)
    ap.add_argument("--json-out")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-e2e", action="store_true")
    ap.add_argument("--full-floor", action="store_true", help="連建包底板的 F0b／F0c／F0d（global_tests、unmapped、掃目錄型）也跑；預設不含")
    ap.add_argument("--known-red", help="已登記的既有紅（JSON：{\"nodeids\": [...]}）；只准縮短，列出但不計入")
    ap.add_argument("--repo", default=str(REPO))
    a = ap.parse_args(argv)
    repo = Path(a.repo)
    try:
        dirty = dirty_files(repo)
        if dirty and not a.dry_run:
            print("作者閘門拒絕執行：工作樹不乾淨（%d 個檔）：\n  %s\n請先 commit 或清掉；結果檔綁 commit，髒樹的結果沒有意義。" % (len(dirty), "\n  ".join(dirty[:20])))
            return 2
        head = resolve(a.head, repo)
        base = resolve(a.base, repo) if a.base else default_base(head, repo)
        sel, plan_n, plan_e = select_for(base, head, repo, a.full_floor)
    except RuntimeError as e:
        print("作者閘門：%s" % e)
        return 2
    times = load_times()
    workers = max(1, a.workers)
    est = estimate_seconds(sel["non_e2e"], times, workers, repo)
    print("作者閘門 %s → 基準 %s" % (head[:8], base[:8]))
    print("  A1 底板 %d 檔（不含建包才需要的底板 %d 檔，--full-floor 加入）｜A2 樣式守門 %d 檔｜A3 受影響 %d 檔｜A4 改動測試 %d 檔｜不含 e2e 共 %d 檔｜e2e %d 檔（單獨一段）" % (
        len(sel["A1"]), len(sel["A1x"]), len(sel["A2"]), len(sel["A3"]), len(sel["A4"]), len(sel["non_e2e"]), len(sel["E"])))
    print("  預估 %.1f 分鐘（workers=%d）；預算 %d 分鐘" % (est / 60, workers, a.budget_min))
    if sel["guards_missing"]:
        print("  ⚠ GUARDS 找不到檔（被改名？）：" + "、".join(sel["guards_missing"]))
    if sel["forced_full"]:
        print("  ℹ 建包這個 diff 會整段全量（作者端仍只跑上面的集合）：" + "；".join(sel["forced_full"])[:300])
    vw = venv_warning(repo)
    if vw:
        print("  ⚠ " + vw)
    w = budget_warning(est, a.budget_min, sel["non_e2e"], times, root=repo)
    if w:
        print("  ⚠ " + w)
    if a.dry_run:
        return 0
    py = sys.executable
    basetemp = os.path.join(tempfile.gettempdir(), "motrix-pytest-authorgate-%s-%s" % (head[:8], time.strftime("%H%M%S")))
    cmd, cmd_e = build_cmds(py, strip_backend(sel["non_e2e"]), sel["guard_args"], [] if a.skip_e2e else strip_backend(sel["E"]), basetemp, workers)
    env = {"MOTRIX_FAILFAST": "1", "MOTRIX_FAILFAST_N": "10", "MOTRIX_FAILFIRST": "1", "MOTRIX_FAILFIRST_BASE": base}
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    t0 = time.time()
    from pre_train_check import parse_failures
    known = set()
    if a.known_red:
        try:
            known = set(json.loads(Path(a.known_red).read_text(encoding="utf-8")).get("nodeids", []))
        except (OSError, ValueError) as e:
            print("作者閘門：讀不到 --known-red（%s）" % e)
            return 2
    try:
        print("[pytest] " + " ".join(cmd[3:8]) + " … (%d 檔)" % len(sel["non_e2e"]))
        rc, out = run_pytest(cmd, repo / "backend", env)
        counts = parse_counts(out)
        fails = parse_failures(out)
        stopped = "failfast:" in out
        e2e = None
        if cmd_e and rc in (0, 1) and not (fails and stopped):
            t1 = time.time()
            print("[pytest e2e] %d 檔" % len(sel["E"]))
            rc_e, out_e = run_pytest(cmd_e, repo / "backend", env)
            fe = parse_failures(out_e)
            e2e = {"files": len(sel["E"]), "ran": parse_counts(out_e), "failed": [f["nodeid"] for f in fe], "seconds": round(time.time() - t1, 1),
                   "green": rc_e == 0 and not fe}
        new, kn = classify_failures(fails, known)
    finally:
        shutil.rmtree(basetemp, ignore_errors=True)
        shutil.rmtree(basetemp + "-e2e", ignore_errors=True)
    dur = time.time() - t0
    import stage_select as SS
    res = make_result(head=head, base=base, tree_sha=tree_sha_of(head, repo), selector_sha=SS.selector_sha(SS.GitReader(str(repo), head)),
                      groups=sel, counts=counts, failures_new=new, failures_known=kn, duration_s=dur, estimate_s=est, workers=workers,
                      stopped_by_failfast=stopped, forced_full=sel["forced_full"], started=started, finished=time.strftime("%Y-%m-%dT%H:%M:%S"), e2e=e2e)
    outp = Path(a.json_out) if a.json_out else RESULT_DIR / (head[:12] + ".json")
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("作者閘門：%s，實跑 %d 題，%.1f 分鐘（預估 %.1f 分），tree=%s，結果檔=%s" % (
        "綠" if res["green"] else "紅", sum(counts.get(k, 0) for k in ("passed", "failed", "errors")), dur / 60, est / 60, res["tree_sha"][:12], outp))
    if new:
        print("紅（新）：" + "\n  ".join(f["nodeid"] for f in new[:30]))
    if kn:
        print("紅（已登記）：" + "\n  ".join(f["nodeid"] for f in kn[:30]))
    print("提醒：這只是作者端預檢；建包仍整段跑，不會因為這份結果略過任何題。")
    return 0 if res["green"] else 1


# ── 回放驗證 ─────────────────────────────────────────────────────────────

def load_cases(path=DEFAULT_REPLAY_CASES):
    return json.loads(Path(path).read_text(encoding="utf-8"))["cases"]


def _load_scanner(repo, ref_path, func):
    """從目前工作樹載入守門檔裡的掃描函式（守門是新的、被掃的原始碼是舊的）。"""
    import importlib.util
    path = Path(repo) / ref_path
    spec = importlib.util.spec_from_file_location("_ag_scanner_" + path.stem, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, func)


def replay_offline(case, repo=REPO, patterns=PATTERNS):
    """離線（不跑測試）：紅燈 commit 之前的樹上，聯集（A1 底板目錄 ∪ A2 樣式 ∪ GUARDS）是否包含該輪預期紅的檔。
    ⇒ {"name", "covered": bool, "missing": [...], "by": {檔: 組}}。
    其他兩種案例：`scanner`＝靜態掃描型守門（在 fix^ 的原始碼上必須有命中、fix 上沒有）；`uncatchable`＝靜態選題抓不到的偶發（只記錄，covered 為 None，不算缺漏）。"""
    if case.get("uncatchable"):
        return {"name": case["name"], "covered": None, "missing": [], "by": {}, "uncatchable": case["uncatchable"], "red_parent": ""}
    red_parent = resolve(case["fix"] + "^", repo)
    if case.get("scanner"):
        sc = case["scanner"]
        scan = _load_scanner(repo, sc["module"], sc["func"])
        def src_at(ref):
            rc, out, _ = _git("show", "%s:%s" % (ref, sc["file"]), repo=repo)
            return out if rc == 0 else ""
        hit_before = len(scan(src_at(red_parent)))
        hit_after = len(scan(src_at(resolve(case["fix"], repo))))
        ok = hit_before > 0 and hit_after == 0
        return {"name": case["name"], "covered": ok, "missing": [] if ok else [sc["file"]], "red_parent": red_parent[:10],
                "by": {sc["file"]: "scanner(hits before=%d after=%d)" % (hit_before, hit_after)}}
    tree = tree_files_at(red_parent, repo)
    a2 = set(pattern_files(tree, patterns))
    from pre_train_check import GUARDS
    guard_files = set()
    for _label, pat in GUARDS:
        file_pat = pat.split("::", 1)[0]
        guard_files |= {f for f in tree if fnmatch.fnmatch(f, "backend/" + file_pat)}
    by, missing = {}, []
    for f in case["expect_files"]:
        if f.startswith("backend/tests/platform/"):
            by[f] = "A1" if f in tree else None
        elif f in a2:
            by[f] = "A2"
        elif f in guard_files:
            by[f] = "A2(GUARDS)"
        else:
            by[f] = None
        if by[f] is None:
            missing.append(f)
    return {"name": case["name"], "covered": not missing, "missing": missing, "by": by, "red_parent": red_parent[:10]}


def replay_run(case, repo=REPO, workers=2, python=sys.executable):
    """實跑（獨佔窗口才用）：在 fix^ 的拋棄式 worktree 跑預期檔 ⇒ 必須紅；fix 本身再跑一次 ⇒ 必須綠。"""
    out = {"name": case["name"]}
    for label, ref, want_red in (("red", case["fix"] + "^", True), ("fixed", case["fix"], False)):
        sha = resolve(ref, repo)
        wt = Path(tempfile.gettempdir()) / ("authorgate-replay-%s-%s" % (label, sha[:8]))
        shutil.rmtree(wt, ignore_errors=True)
        subprocess.run(["git", "-C", str(repo), "worktree", "add", "--detach", str(wt), sha], capture_output=True)
        try:
            files = strip_backend(case["expect_files"])
            argv = [python, "-m", "pytest", *files, "-q", "-rfE", "--tb=short", "-m", "not e2e", "-p", "no:cacheprovider",
                    "--basetemp=%s" % (str(wt) + "-bt")]
            rc, text = run_pytest(argv, wt / "backend", {}, stream=False)
            counts = parse_counts(text)
            out[label] = {"rc": rc, "counts": counts, "ok": (rc != 0) if want_red else (rc == 0)}
        finally:
            subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force", str(wt)], capture_output=True)
            shutil.rmtree(str(wt) + "-bt", ignore_errors=True)
    out["ok"] = out.get("red", {}).get("ok") and out.get("fixed", {}).get("ok")
    return out


def replay_main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=str(DEFAULT_REPLAY_CASES))
    ap.add_argument("--run", action="store_true", help="實跑（獨佔窗口）：fix^ 必須紅、fix 必須綠")
    ap.add_argument("--case", action="append", default=[])
    ap.add_argument("--repo", default=str(REPO))
    a = ap.parse_args(argv)
    cases = [c for c in load_cases(a.cases) if not a.case or c["name"] in a.case]
    bad = 0
    for c in cases:
        r = replay_offline(c, Path(a.repo))
        label = "靜態抓不到(已記錄)" if r["covered"] is None else ("涵蓋" if r["covered"] else "缺漏")
        print("[離線] %-28s %s  紅前樹 %s  %s" % (c["name"], label, r["red_parent"], json.dumps(r["by"] or r.get("uncatchable", ""), ensure_ascii=False)))
        bad += 0 if r["covered"] in (True, None) else 1
        if a.run and not c.get("scanner") and not c.get("uncatchable"):
            rr = replay_run(c, Path(a.repo))
            print("[實跑] %-28s %s  %s" % (c["name"], "OK" if rr["ok"] else "不符", json.dumps({k: v for k, v in rr.items() if k in ("red", "fixed")}, ensure_ascii=False)))
            bad += 0 if rr["ok"] else 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
