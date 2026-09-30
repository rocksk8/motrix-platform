# -*- coding: utf-8 -*-
"""預演列車：分支推上月台之前，先在拋棄式樹上「合進 origin/platform 之後」跑一次只在合併後才會紅的守門。

起因（2026-09-30 第二十六班重建 3 次）：有些守門在分支單獨跑是綠的，合在 platform 上才紅——
規格編號 C_OWNED、modules.json 歸屬、page_paths 棘輪、scope_gate 的 global_tests、單位卡／UNIT-INDEX、
L1 底線名稱、alpine double-init 頁母體、簽核提供者集合、產生檔。它們在列車（MOTRIX_TRAIN=1）才一起出現，
作者讀不到，列車長逐個修 ⇒ 每修一個重建一次。這支把「列車上會發生的事」提早到作者手上。

用法（在任何一棵 MOTRIX-PLATFORM 樹，Python 一律 D:\\MOTRIX-PLATFORM\\.venv312\\Scripts\\python.exe）：
  python tools/platform/pre_train_check.py <分支或 SHA> [--base origin/platform] [--workers 2] [--keep] [--no-fetch]
  python tools/platform/pre_train_check.py <分支> --skip-tests     只做「合併＋取號＋重產產生檔＋檢查」，不跑 pytest
退出碼：0 全綠；1 有紅（報告依歸屬分組）；2 合併衝突或工具本身出錯（不是守門紅）。

做的事（順序＝列車長清單 PLAYBOOK §G4 第 2～3 步的子集）：
  1. `git worktree add --detach D:\\開發測試檔\\pre-train-<分支>-<時間> <base>`（拋棄式；只動這一棵，用完只移除這一棵）
  2. `git merge --no-ff <分支 SHA>`：`-c rerere.enabled=false`（不讀、不寫 rerere 記錄）＋本機身分；**不 push、不動任何分支**。
     衝突 ⇒ 列出衝突檔、`merge --abort`、exit 2（列車上會退回月台的就是這種）。
  3. `setup_merge_drivers --check`（警告）→ `train_number assign`（號碼佔位取號，改動就提交）→ `train_number --check`
  4. 依序重產 dep_graph.json、UNIT-INDEX.md、test_map.json（各自提交，與列車相同）
  5. pytest（一個行程，`-n <workers>` 預設 2、低優先權、MOTRIX_TRAIN=1、`-m "not e2e"`）：
     tests/platform 全部＋GUARDS 列的非 platform 守門（spec_coverage、alpine double-init、公司設定輸出點、system_audit、
     e2e 檔裡的 raw-vh 靜態題、簽核提供者、頁面殼腳本）。-n≥2 屬重型 ⇒ 由 conftest 的全機測試鎖排隊，不繞過。
  6. 紅的題依歸屬分組印出（模組 key／共用核心；附守門種類與這個分支動到的相關檔），並印單獨重跑指令。
清理：`git worktree remove --force` 只移除步驟 1 建的那一棵；basetemp 一律刪。--keep 保留樹供查紅。
GUARDS 會長大：列車上又抓到「合併後才紅」的守門，就加一列（同時更新 PLAYBOOK §G5 第 19 項）。
"""
import argparse
import fnmatch
import glob
import importlib.util
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SCRATCH_ROOT_DEFAULT = "D:/開發測試檔"
SCRATCH_PREFIX = "pre-train-"
GIT_ID = ["-c", "user.name=pre-train-check", "-c", "user.email=pre-train-check@localhost",
          "-c", "rerere.enabled=false", "-c", "rerere.autoupdate=false", "-c", "commit.gpgsign=false"]

#: 「只在合併後才紅」的非 tests/platform 守門：(標籤, glob（相對 backend/，可含 ::nodeid）)。tests/platform 整個都跑，不列在這裡。
GUARDS = [
    ("規格編號 C_OWNED／規格覆蓋", "tests/test_spec_coverage_2026_09_21.py"),
    ("alpine double-init 頁母體", "tests/test_alpine_double_init_2026_09_23.py"),
    ("公司設定輸出點", "tests/test_company_setup_output_points_2026_09_28.py"),
    ("系統稽核（表分類）", "tests/test_system_audit_2026_09_14.py"),
    ("字級縮放 raw-vh 靜態題", "tests/test_e2e_font_zoom_fits_viewport_2026_09_24.py::test_fz_no_raw_vh_is_left_in_the_frontend"),
    ("簽核提供者集合", "modules/*/tests/test_approval_providers*.py"),
    ("頁面殼腳本", "tests/test_page_shell_scripts_2026_09_30.py"),
]
#: 依測試檔名判斷「這是哪一種守門」（報告分組用；順序＝先比先中）
GUARD_KINDS = [
    ("test_spec_coverage", "規格編號 C_OWNED"),
    ("test_route_ownership", "路由歸屬"),
    ("test_page_paths", "page_paths 棘輪"),
    ("test_scope_gate", "scope_gate／global_tests"),
    ("test_unit_cards", "單位卡／UNIT-INDEX"),
    ("test_generated_maps", "產生檔（dep_graph／test_map）"),
    ("test_l1_interface", "L1 介面／底線名稱"),
    ("test_l1_", "L1 邊界"),
    ("test_train_number", "版號佔位"),
    ("test_version_slots", "版號佔位"),
    ("test_module_changelog", "模組 CHANGELOG"),
    ("test_alpine_double_init", "alpine double-init"),
    ("approval_provider", "簽核提供者集合"),
    ("test_page_shell", "頁面殼腳本"),
    ("test_company_setup", "公司設定輸出點"),
    ("test_system_audit", "表分類"),
    ("test_module_", "modules.json／模組登記"),
    ("test_platform_catalog", "modules.json／模組登記"),
]
_FAIL_LINE = re.compile(r"^(FAILED|ERROR)\s+(\S+?)(?:\s+-\s+(.*))?$")


# ── 純函式（有題）────────────────────────────────────────────────────────────────

def slug(name):
    return re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-")[:40] or "branch"


def parse_failures(text):
    """pytest `-rfE` 摘要行 ⇒ [{nodeid, kind: FAILED|ERROR, msg}]（依出現順序、去重；收集錯誤的 nodeid 沒有 `::`）。"""
    seen, out = set(), []
    for line in (text or "").splitlines():
        m = _FAIL_LINE.match(line.strip())
        if not m or m.group(2) in seen:
            continue
        seen.add(m.group(2))
        out.append({"nodeid": m.group(2), "kind": m.group(1), "msg": (m.group(3) or "").strip()})
    return out


def guard_kind(nodeid):
    path = nodeid.split("::", 1)[0].replace("\\", "/").rsplit("/", 1)[-1]
    for needle, label in GUARD_KINDS:
        if needle in path:
            return label
    return "其他守門"


def owner_of(nodeid, modules_of=None):
    """⇒ 歸屬 key：modules/<key>/ 底下的題＝模組 key；其他查 test_map（modules_of 由呼叫端給，可為 None）；都沒有＝core。"""
    path = nodeid.split("::", 1)[0].replace("\\", "/")
    m = re.match(r"(?:backend/)?modules/([^/]+)/", path)
    if m:
        return m.group(1)
    if modules_of is not None:
        try:
            return modules_of(nodeid)[0]
        except Exception:                                   # noqa: BLE001 — 查不到就當共用核心
            pass
    return "core"


def branch_files_for(owner, changed):
    """這個分支動到的、和該歸屬相關的檔（模組＝modules/<key>/ 底下；core＝其餘的 L1／frontend／routers／tools）。"""
    if owner != "core":
        return [f for f in changed if re.match(r"(?:backend/)?modules/%s/" % re.escape(owner), f)]
    return [f for f in changed if not re.match(r"(?:backend/)?modules/", f)]


def group_reds(failures, changed, modules_of=None):
    """⇒ [{owner, count, kinds:{label:[failure…]}, branch_files}]，題數多的在前。"""
    groups = {}
    for f in failures:
        o = owner_of(f["nodeid"], modules_of)
        groups.setdefault(o, []).append(f)
    out = []
    for o, fs in groups.items():
        kinds = {}
        for f in fs:
            kinds.setdefault(guard_kind(f["nodeid"]), []).append(f)
        out.append({"owner": o, "count": len(fs), "kinds": kinds, "branch_files": branch_files_for(o, changed)})
    return sorted(out, key=lambda g: (-g["count"], g["owner"]))


def expand_guards(backend, guards=GUARDS):
    """GUARDS 展開成 (pytest 參數清單, 找不到的標籤清單)。glob 在 backend/ 底下展開；找不到檔 ⇒ 列在 missing（守門被改名也要看得見）。"""
    args, missing = [], []
    for label, pat in guards:
        file_pat, _, node = pat.partition("::")
        hits = sorted(Path(p).relative_to(backend).as_posix() for p in glob.glob(str(Path(backend) / file_pat)))
        if not hits:
            missing.append("%s（%s）" % (label, pat))
            continue
        args += [h + ("::" + node if node else "") for h in hits]
    return args, missing


def build_pytest_cmd(python, guard_args, basetemp, workers=2):
    return [python, "-m", "pytest", "tests/platform", *guard_args, "-q", "-rfE", "--tb=short", "-m", "not e2e",
            "-n", str(workers), "-p", "no:cacheprovider", "--basetemp=%s" % basetemp]


def safe_scratch(path, root):
    """只准移除 root 底下、名字以 pre-train- 開頭的目錄（一棵自己建的樹）。"""
    try:
        p, r = Path(path).resolve(), Path(root).resolve()
    except OSError:
        return False
    return p.parent == r and p.name.startswith(SCRATCH_PREFIX)


def format_report(branch, sha, base, steps, groups, missing, runtime, total_failed, passed_line):
    L = ["", "═" * 72, "預演列車 %s（%s）→ %s   %.0f 分鐘" % (branch, sha[:8], base, runtime / 60)]
    for name, ok, note in steps:
        L.append("  %s %s%s" % ("✔" if ok else "✘", name, "：" + note if note else ""))
    for m in missing:
        L.append("  ⚠ 找不到守門檔（改名或刪除了？）：" + m)
    if passed_line:
        L.append("  pytest：" + passed_line)
    if not groups:
        L.append("結果：無紅。" if all(ok for _, ok, _ in steps) else "結果：有步驟未過（見上）。")
    else:
        L.append("紅 %d 題，依歸屬分組（歸屬提示＝題所在的模組／共用核心；列車上這些會逐個退回，現在先修）：" % total_failed)
        for g in groups:
            L.append("── 歸屬 %s：%d 題" % (g["owner"], g["count"]))
            if g["branch_files"]:
                L.append("   本分支動到的相關檔：" + "、".join(g["branch_files"][:6]) + (" …共 %d 檔" % len(g["branch_files"]) if len(g["branch_files"]) > 6 else ""))
            for kind, fs in g["kinds"].items():
                L.append("   [%s]" % kind)
                for f in fs[:8]:
                    L.append("     %s %s%s" % (f["kind"], f["nodeid"], " — " + f["msg"][:110] if f["msg"] else ""))
                if len(fs) > 8:
                    L.append("     … 另 %d 題" % (len(fs) - 8))
        first = groups[0]["kinds"][next(iter(groups[0]["kinds"]))][0]["nodeid"]
        L.append("單獨重跑（在 backend\\ 底下，MOTRIX_TRAIN=1）：python -m pytest \"%s\" -v" % first)
    return "\n".join(L)


# ── 執行 ───────────────────────────────────────────────────────────────────────

class Runner:
    """所有外部指令都經過這裡（測試換掉它）。run ⇒ (returncode, 輸出全文)；stream=True 邊跑邊印。"""

    def run(self, argv, cwd, env=None, stream=False, low=False, timeout=None):
        flags = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0) if (low and os.name == "nt") else 0
        e = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        e.update(env or {})
        proc = subprocess.Popen(argv, cwd=str(cwd), env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=flags)
        lines = []
        deadline = time.time() + timeout if timeout else None
        for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace")
            lines.append(line)
            if stream:
                sys.stdout.write(line)
                sys.stdout.flush()
            if deadline and time.time() > deadline:
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)   # 只結束自己起的這一棵
                lines.append("[pre_train_check] 逾時 %ds，已結束該行程\n" % timeout)
                break
        return proc.wait(), "".join(lines)


def git(runner, cwd, *args, ident=False):
    return runner.run(["git", *(GIT_ID if ident else []), *args], cwd)


def rmtree_force(path):
    def _clear(func, p, _e):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    if Path(path).exists():
        shutil.rmtree(str(path), onerror=_clear)


def load_fail_stream(root):
    """載入「合併後那棵樹」的 fail_stream（它的 REPO＝那棵樹 ⇒ modules_of 讀的是重產後的 test_map）。"""
    p = Path(root) / "tools" / "platform" / "fail_stream.py"
    if not p.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location("_pt_fail_stream", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:                                       # noqa: BLE001
        return None


def merge_into(runner, tree, sha, branch):
    """合併。⇒ (ok, conflicts)。衝突 ⇒ merge --abort。"""
    rc, out = git(runner, tree, "merge", "--no-ff", "--no-edit", "-m", "pre-train-check: merge %s" % branch, sha, ident=True)
    if rc == 0:
        return True, []
    _, u = git(runner, tree, "diff", "--name-only", "--diff-filter=U")
    conflicts = [x for x in u.splitlines() if x.strip()]
    git(runner, tree, "merge", "--abort")
    return False, conflicts


def commit_if_dirty(runner, tree, message):
    _, st = git(runner, tree, "status", "--porcelain")
    if not st.strip():
        return False
    git(runner, tree, "add", "-A")
    git(runner, tree, "commit", "-q", "-m", message, ident=True)
    return True


def run_check(argv, runner=None, root_repo=None, scratch_root=None, keep=False, fetch=True, workers=2, skip_tests=False,
              python=None, out=print):
    """主流程。⇒ (exit code, 報告文字)。"""
    runner = runner or Runner()
    root_repo = Path(root_repo or REPO)
    scratch_root = Path(scratch_root or SCRATCH_ROOT_DEFAULT)
    branch, base = argv["branch"], argv["base"]
    python = python or sys.executable
    t0 = time.time()
    steps, tree = [], None

    def step(name, ok, note=""):
        steps.append((name, ok, note))
        out("[%s] %s%s" % ("OK" if ok else "紅", name, "：" + note if note else ""))
        return ok

    try:
        if fetch:
            git(runner, root_repo, "fetch", "-q", "origin")
        rc, sha = git(runner, root_repo, "rev-parse", "--verify", "--quiet", "%s^{commit}" % branch)
        if rc != 0:
            rc, sha = git(runner, root_repo, "rev-parse", "--verify", "--quiet", "origin/%s^{commit}" % branch)
        rcb, base_sha = git(runner, root_repo, "rev-parse", "--verify", "--quiet", "%s^{commit}" % base)
        if rc != 0 or rcb != 0:
            return 2, "找不到%s：%s" % ("分支" if rc != 0 else "base", branch if rc != 0 else base)
        sha, base_sha = sha.strip().splitlines()[-1], base_sha.strip().splitlines()[-1]
        tree = scratch_root / ("%s%s-%s" % (SCRATCH_PREFIX, slug(branch), time.strftime("%H%M%S")))
        if not safe_scratch(tree, scratch_root):
            return 2, "拋棄式樹路徑不在允許範圍：%s" % tree
        rc, o = git(runner, root_repo, "worktree", "add", "--detach", str(tree), base_sha)
        if rc != 0:
            return 2, "建不出拋棄式樹：" + o.strip()[-300:]
        _, changed = git(runner, tree, "diff", "--name-only", "%s...%s" % (base_sha, sha))
        changed = [x for x in changed.splitlines() if x.strip()]
        ok, conflicts = merge_into(runner, tree, sha, branch)
        if not ok:
            step("合併 %s → %s" % (branch, base), False, "衝突 %d 檔：%s" % (len(conflicts), "、".join(conflicts[:8])))
            return 2, format_report(branch, sha, base, steps, [], [], time.time() - t0, 0, "")
        step("合併 %s → %s" % (branch, base), True, "動到 %d 檔" % len(changed))

        py = python
        tool = lambda name: str(tree / "tools" / "platform" / name)      # noqa: E731
        rc, o = runner.run([py, tool("setup_merge_drivers.py"), "--check", "--repo", str(tree)], tree)
        step("合併驅動登記", rc == 0, "" if rc == 0 else "未登記（先跑 setup_merge_drivers.py）；CHANGELOG／manifest 的合併結果可能與列車不同")
        rc, o = runner.run([py, tool("train_number.py"), "assign", "--base", base_sha, "--root", str(tree)], tree)
        if rc != 0:
            step("train_number assign", False, o.strip()[-300:])
        else:
            commit_if_dirty(runner, tree, "pre-train-check: train_number assign")
            rc2, o2 = runner.run([py, tool("train_number.py"), "--check", "--base", base_sha, "--root", str(tree)], tree)
            step("train_number assign＋--check", rc2 == 0, "" if rc2 == 0 else o2.strip()[-400:])
        for name, cmd in (("重產 dep_graph.json", [py, tool("dep_scan.py")]), ("重產 UNIT-INDEX.md", [py, tool("unit_index.py")]),
                          ("重產 test_map.json", [py, tool("test_map.py")])):
            rc, o = runner.run(cmd, tree)
            step(name, rc == 0, "" if rc == 0 else o.strip()[-300:])
        commit_if_dirty(runner, tree, "pre-train-check: regenerate derived files")

        groups, missing, passed_line, total = [], [], "", 0
        if not skip_tests:
            guard_args, missing = expand_guards(tree / "backend")
            basetemp = os.path.join(tempfile.gettempdir(), "motrix-pytest-pretrain-%s-%s" % (slug(branch), time.strftime("%H%M%S")))
            cmd = build_pytest_cmd(py, guard_args, basetemp, workers)
            out("[pytest] %s" % " ".join(cmd[3:]))
            try:
                rc, o = runner.run(cmd, tree / "backend", env={"MOTRIX_TRAIN": "1"}, stream=True, low=True)
            finally:
                rmtree_force(basetemp)
            fails = parse_failures(o)
            tail = [l for l in o.splitlines() if re.search(r"\d+ (passed|failed|error)", l)]
            passed_line = tail[-1].strip() if tail else ""
            step("pytest（tests/platform＋%d 個守門檔）" % len(guard_args), rc == 0 and not fails,
                 "" if rc == 0 else "exit %d，紅 %d 題" % (rc, len(fails)))
            if rc != 0 and not fails:
                step("紅但認不出是哪一題", False, "輸出被截斷／行程被殺／收集錯誤 ⇒ 不可當綠；看上方輸出")
            fs = load_fail_stream(tree)
            groups = group_reds(fails, changed, getattr(fs, "modules_of", None))
            total = len(fails)
        rep = format_report(branch, sha, base, steps, groups, missing, time.time() - t0, total, passed_line)
        return (0 if all(ok for _, ok, _ in steps) and not groups else 1), rep
    finally:
        if tree is not None and not keep and safe_scratch(tree, scratch_root):
            git(runner, root_repo, "worktree", "remove", "--force", str(tree))
            rmtree_force(tree)
            git(runner, root_repo, "worktree", "prune")


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("branch")
    ap.add_argument("--base", default="origin/platform")
    ap.add_argument("--workers", type=int, default=2, help="pytest -n（上限 2，全機測試名額）")
    ap.add_argument("--keep", action="store_true", help="保留拋棄式樹（查紅用；用完自己 git worktree remove）")
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--skip-tests", action="store_true")
    ap.add_argument("--scratch-root", default=SCRATCH_ROOT_DEFAULT)
    ap.add_argument("--python", default=sys.executable)
    a = ap.parse_args(argv)
    workers = max(1, min(a.workers, 2))
    code, rep = run_check({"branch": a.branch, "base": a.base}, scratch_root=a.scratch_root, keep=a.keep, fetch=not a.no_fetch,
                          workers=workers, skip_tests=a.skip_tests, python=a.python)
    print(rep)
    return code


if __name__ == "__main__":
    sys.exit(main())
