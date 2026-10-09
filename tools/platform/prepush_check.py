# -*- coding: utf-8 -*-
"""推送前檢查（第 51 班；設計 docs/platform/plans/SPEEDUP-PREPUSH-T50.md）。

把「整合期才紅」的登記／守門類紅燈提前到作者推送之前：目標閒置機器約 1 分鐘（硬上限 --budget-sec 90）、單一行程、只讀。
**絕不做**：取號（train_number assign）、重產（regen_all 只准 check_only）、commit／push／checkout、
設 MOTRIX_TRAIN=1（分支上的 `(next)` 佔位本來就合法）、e2e／瀏覽器、改任何追蹤檔、寫任何「綠燈紀錄」。
預檢綠 ≠ 閘門綠：完整 B／e2e 仍由 run-stage 負責。

[單位] tools:prepush_check   [層] 工具   [穩定度] 內部

用法（任一 worktree 根目錄；Python＝主工作樹 .venv312）：
  python tools/platform/prepush_check.py [--base <ref>] [--budget-sec N（預設 wip 90、--integration 300）] [--static-only] [--integration] [--json-out F]
  python tools/platform/prepush_check.py --hook      （git pre-push 呼叫：紅 ⇒ exit 1 擋推送；未完成／警告 ⇒ exit 0）
結束碼：0 綠（可含警告）；1 有紅；2 工具本身出錯；3 未完成（超過時間預算；hook 當警告放行）。
  --integration：整合分支模式（train/*、platform）：A0 產生檔過期（check_only）＋全模組 changelog 檢查；**只警告、不擋**。
                預算預設 300 秒（光靜態實測 ≈ 147 秒；wip 模式靜態約 14 秒）。
"""
import argparse
import importlib.util
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

import train_preflight as TP  # noqa: E402  重用 A1～A8 靜態檢查與 Finding／Unchecked

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
INCOMPLETE = 3

#: 產生檔：wip 分支依規定不得帶（列車取號後統一重產）；整合分支才要求「是最新的」
GENERATED = ("docs/platform/dep_graph.json", "docs/platform/UNIT-INDEX.md", "docs/platform/test_map.json")

#: 必跑的便宜守門檔（秒數取自 preflight_seconds.json；合計約 50 秒）。路徑相對 backend/；不存在的略過。
TIER1 = (
    ("tests/test_version_manifest_2026_09_22.py", 2), ("tests/platform/test_v9_baseline.py", 3),
    ("tests/platform/test_l1_interface_snapshot.py", 9), ("tests/test_begin_only_via_begin_write_2026_09_25.py", 6),
    ("tests/test_approval_flow_scope.py", 4), ("tests/test_approval_queue_covers_every_doc_type_2026_09_24.py", 6),
    ("tests/platform/test_version_slots.py", 3), ("tests/platform/test_wording_material_request_2026_10_02.py", 2),
    ("tests/test_form_version_bumped_2026_09_24.py", 1), ("tests/platform/test_dep_scan_controls.py", 1),
    ("tests/test_spec_coverage_2026_09_21.py", 14), ("tests/platform/test_changelog_sections.py", 1),
)
#: 依動到的路徑才加的較慢守門檔：(觸發路徑的正規表示式, 檔, 秒)
CONDITIONAL = (
    (r"^docs/platform/INTEGRATION-POINTS\.md$|register_provider|/api/", "tests/platform/test_integration_points_registered.py", 28),
    (r"^backend/modules/[^/]+/(api/|[^/]*\.py$)|^backend/routers/", "tests/platform/test_ship_tier_2026_09_28.py", 53),
    (r"^backend/modules/[^/]+/api/|^backend/routers/", "modules/case/tests/test_route_table_golden_2026_10_05.py", 15),
)
USER_VISIBLE = re.compile(r"^(frontend/pages/|backend/modules/[^/]+/api/|backend/routers/)")
FORM = "frontend/pages/quotation-form.html"


def _git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       creationflags=NOWIN)
    return r.stdout.strip() if r.returncode == 0 else ""


def default_base(repo):
    """分支與 platform 的分叉點；找不到 origin/platform ⇒ ''（呼叫端當「沒有變動」並警告）。"""
    return _git(repo, "merge-base", "HEAD", "origin/platform")


def changed_files(repo, base):
    out = _git(repo, "diff", "--name-only", "%s...HEAD" % base) if base else ""
    return [x.strip() for x in out.splitlines() if x.strip()]


def python_exe():
    return TP.python_exe()


def _load(path, name, backend=None):
    if backend:
        sys.path.insert(0, str(backend))
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 靜態：重用 train_preflight 的 A1～A8；A0 反向（wip 不得帶產生檔）─────────────────────

def static_findings(repo, changed, base, integration=False):
    f = []
    gen = [p for p in changed if p in GENERATED]
    if integration:
        try:
            f += TP.check_generated(repo)                                   # check_only，不寫檔
        except Exception as e:                                              # noqa: BLE001
            f.append(TP.Unchecked("A0", "%s" % e))
    elif gen:
        f.append(TP.Finding("P0", ", ".join(gen), "wip 分支不可帶產生檔（列車取號後統一重產；帶了會與別支衝突）",
                            "從這個分支還原這幾個檔：git checkout %s -- <檔>" % (base or "origin/platform")))
    for fn in (lambda: TP.check_changelogs(repo), lambda: TP.check_ip_registry(repo), lambda: TP.check_global_tests(repo),
               lambda: TP.check_doc_types(repo), lambda: TP.check_begin_sites(repo), lambda: TP.check_golden(repo, changed, base or "origin/platform"),
               lambda: TP.check_db_version_literals(repo), lambda: TP.check_bare_get_db(repo, changed)):
        try:
            f += fn()
        except Exception as e:                                              # noqa: BLE001
            f.append(TP.Unchecked("A?", "%s" % e))
    return f


def touched_modules(changed):
    return sorted({m.group(1) for p in changed for m in [re.match(r"^backend/modules/([^/]+)/", p)] if m})


def changelog_findings(repo, mods):
    """只對『動到的模組』跑 test_module_changelog_follows_code.check_module（整支測試 72 秒是因為掃全部模組）。"""
    path = Path(repo) / "backend" / "tests" / "platform" / "test_module_changelog_follows_code.py"
    if not path.is_file() or not mods:
        return []
    try:
        mod = _load(path, "_pp_changelog_follows", backend=Path(repo) / "backend")
    except Exception as e:                                                  # noqa: BLE001
        return [TP.Unchecked("C1", "匯入 changelog_follows_code 失敗：%s" % e)]
    out = []
    for m in mods:
        rel = "backend/modules/%s" % m
        if not (Path(repo) / rel).is_dir():
            continue
        try:
            for problem in mod.check_module(repo, rel):
                out.append(TP.Finding("C1", rel, problem, "在最後一次程式改動之後，於該模組 CHANGELOG 最上面寫（或改寫）版號條目（分支：`## (next)`）"))
        except Exception as e:                                              # noqa: BLE001
            out.append(TP.Unchecked("C1", "%s：%s" % (m, e)))
    return out


def form_version_findings(repo, changed):
    if FORM not in changed:
        return []
    path = Path(repo) / "backend" / "tests" / "test_form_version_bumped_2026_09_24.py"
    try:
        mod = _load(path, "_pp_form_version")
        ok, msg = mod.verdict((Path(repo) / FORM).read_text(encoding="utf-8"), mod.LEDGER)
    except Exception as e:                                                  # noqa: BLE001
        return [TP.Unchecked("F1", "FORM_VERSION 判定失敗：%s" % e)]
    return [] if ok else [TP.Finding("F1", FORM, msg.splitlines()[0] if msg else "FORM_VERSION 未升", "照 test_form_version_bumped 的紅燈訊息升版並登記 LEDGER")]


def warnings(changed):
    """不擋、只提醒：動了使用者看得到的檔卻沒碰 version_manifest.json。"""
    w = []
    if any(USER_VISIBLE.match(p) and "/tests/" not in p for p in changed) and "backend/version_manifest.json" not in changed:
        w.append("動到使用者看得到的檔（頁面／API）但 backend/version_manifest.json 沒有新條目（更新登記：PLAYBOOK §G6／START-HERE §4）；純內部修正可忽略")
    return w


# ── 測試：便宜守門檔，單進程，依路徑選 ────────────────────────────────────

def select_tests(repo, changed):
    backend = Path(repo) / "backend"
    sel = [(t, s) for t, s in TIER1 if (backend / t).is_file()]
    blob = "\n".join(changed)
    for rx, t, s in CONDITIONAL:
        if re.search(rx, blob, re.M) and (backend / t).is_file() and all(t != x for x, _ in sel):
            sel.append((t, s))
    return sel


def run_tests(repo, tests, timeout):
    """⇒ (rc, output, seconds)。rc＝INCOMPLETE 代表逾時被停（不可當綠）。不設 MOTRIX_TRAIN。"""
    basetemp = os.path.join(tempfile.gettempdir(), "pt_prepush_%d" % os.getpid())
    env = {k: v for k, v in os.environ.items() if k != "MOTRIX_TRAIN"}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    cmd = [python_exe(), "-m", "pytest", *[t for t, _ in tests], "-q", "-rfE", "--tb=line", "-m", "not e2e", "-p", "no:xdist", "-p", "no:cacheprovider",
           "--basetemp=%s" % basetemp]
    t0 = time.time()
    try:
        try:
            r = subprocess.run(cmd, cwd=str(Path(repo) / "backend"), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=max(5, timeout), creationflags=NOWIN)
        except subprocess.TimeoutExpired:
            return INCOMPLETE, "", time.time() - t0
        return r.returncode, r.stdout + r.stderr, time.time() - t0
    finally:
        shutil.rmtree(basetemp, ignore_errors=True)


# ── 主流程 ─────────────────────────────────────────────

#: 時間預算（秒）。wip 推送前：閒置機器約 1 分鐘、硬上限 90；整合模式（train/*、platform 的背景檢查，只警告）要多做 A0 產生檔檢查＋全模組
#: changelog 檢查，實測光靜態就 ≈ 147 秒（第 51 班 1d 量測）⇒ 預算 300。沒指定 --budget-sec 才用這兩個預設。
WIP_BUDGET_SEC = 90
INTEGRATION_BUDGET_SEC = 300


def run(repo=REPO, base=None, budget_sec=None, static_only=False, integration=False, runner=None):
    """⇒ (exit_code, report_text, data)。runner 供測試注入：runner(repo, tests, timeout) ⇒ (rc, out, secs)。
    budget_sec=None ⇒ wip 90、整合模式 300。"""
    t0 = time.time()
    if budget_sec is None:
        budget_sec = INTEGRATION_BUDGET_SEC if integration else WIP_BUDGET_SEC
    repo = Path(repo)
    base = base or default_base(repo)
    changed = changed_files(repo, base)
    findings = static_findings(repo, changed, base, integration)
    mods = touched_modules(changed)
    if integration:
        mods = sorted(p.name for p in (repo / "backend" / "modules").iterdir() if p.is_dir() and (p / "module.json").is_file())
    findings += changelog_findings(repo, mods)
    findings += form_version_findings(repo, changed)
    warns = warnings(changed)
    static_secs = time.time() - t0
    if not base:
        warns.append("找不到 origin/platform 的分叉點（先 git fetch）；沒有比較基準 ⇒ 靜態檢查幾乎沒有東西可看")
    tests, rc, out, secs = [], None, "", 0.0
    if not static_only:
        tests = select_tests(repo, changed)
        remaining = budget_sec - (time.time() - t0)
        if remaining < 8:
            rc = INCOMPLETE
        else:
            rc, out, secs = (runner or run_tests)(repo, tests, remaining)
    reds = [x for x in findings if not isinstance(x, TP.Unchecked)]
    unchecked = [x for x in findings if isinstance(x, TP.Unchecked)]
    fails = re.findall(r"^FAILED (\S+)", out or "", re.M)
    test_red = rc not in (None, 0, INCOMPLETE)
    lines = ["═══ 推送前檢查（%s；%d 個變動檔；%.0f 秒）═══" % ("整合模式·只警告" if integration else "wip", len(changed), time.time() - t0)]
    for x in unchecked:
        lines.append("⚠ %s %s" % (x.code, x.msg))
    for w in warns:
        lines.append("⚠ 提醒：%s" % w)
    lines.append("靜態：%d 項紅（%.0f 秒；預算 %d 秒）" % (len(reds), static_secs, budget_sec))
    for x in reds:
        lines.append("  [%s] %s\n      %s\n      修法：%s" % (x.code, x.where, x.msg, x.fix))
    if not static_only:
        if rc == INCOMPLETE:
            lines.append("測試：⚠ 未完成（超過 %ds 預算）；已選 %d 個檔，**不可當綠**" % (budget_sec, len(tests)))
        else:
            lines.append("測試：%d 個守門檔，exit %s（%.0f 秒）" % (len(tests), rc, secs))
            for nid in fails:
                lines.append("  - %s" % nid)
    bad = bool(reds) or test_red
    code = 1 if bad else (INCOMPLETE if rc == INCOMPLETE else 0)
    lines.append("結果：%s（預檢綠 ≠ 閘門綠）" % ("有紅" if bad else "未完成" if code == INCOMPLETE else "綠"))
    data = {"base": base, "changed": len(changed), "findings": [x.as_dict() for x in findings], "warnings": warns,
            "tests": [t for t, _ in tests], "rc": rc, "fails": fails, "exit": code, "integration": integration,
            "static_secs": round(static_secs, 1), "budget_sec": budget_sec}
    return code, "\n".join(lines), data


def main(argv=None):
    ap = argparse.ArgumentParser(description="推送前檢查（只讀；預算 wip 90 秒、整合模式 300 秒）")
    ap.add_argument("--base")
    ap.add_argument("--budget-sec", type=int, default=None, help="時間預算（秒）；沒給 ⇒ wip 90、--integration 300")
    ap.add_argument("--static-only", action="store_true")
    ap.add_argument("--integration", action="store_true")
    ap.add_argument("--hook", action="store_true", help="git pre-push：紅 ⇒ 1；未完成／整合模式 ⇒ 0（只警告）")
    ap.add_argument("--json-out")
    a = ap.parse_args(argv)
    try:
        code, text, data = run(REPO, a.base, a.budget_sec, a.static_only, a.integration)
    except Exception as e:                                                  # noqa: BLE001
        print("prepush_check 本身出錯：%s" % e)
        return 2
    print(text)
    if a.json_out:
        Path(a.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json_out).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.hook:
        if a.integration:
            return 0
        return 1 if code == 1 else 0
    return code


if __name__ == "__main__":
    sys.exit(main())
