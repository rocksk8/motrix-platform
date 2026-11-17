# -*- coding: utf-8 -*-
"""測試執行包裝：完整輸出寫檔，螢幕只印「過／紅／略過」數字與失敗題 id（≤ 20 行）；`--affected` 只跑跟改動檔有關的測試。

[單位] tools:run_tests_summary   [層] 工具   [穩定度] 內部
[公開介面] parse_junit_failures, summarize, render, affected_tests, main
[不變式] 只包 pytest（走 preflight_guards.run_pytest：同一套環境變數、分支佔位模式、basetemp 清理、重型排隊）；不改測試結果與 exit code；
    螢幕輸出行數有硬上限（MAX_LINES）；完整 log 一定落檔（路徑印在最後一行），紅燈細節看 log。不寫追蹤檔、不 commit。

用法（repo 任一棵工作樹的根目錄；Python 用 .venv312）：
  python tools/platform/run_tests_summary.py tests/test_x.py [tests/platform/test_y.py ...]   指定檔／題（可加 ::nodeid）
  python tools/platform/run_tests_summary.py --affected                  只跑受影響的測試：本分支相對基準（預設 merge-base origin/platform）的改動檔 → test_map／dep_graph 選題
  python tools/platform/run_tests_summary.py --affected --base <ref>     指定基準
  python tools/platform/run_tests_summary.py --affected --dry-run        只列選到的檔，不跑
  選項：--workers N（預設 1＝不用 -n；≥2 走 heavy 排隊）、--marker EXPR（預設 "not e2e"）、--log <檔>（預設放暫存目錄）、--window <代號>
結束碼：pytest 的結束碼（0 全綠）；--affected 沒選到任何檔 ⇒ 0 並明說「沒有受影響的測試」；2 工具本身出錯。
"""
import argparse
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
MAX_LINES = 20
DETAIL_LINES = 6                    # 失敗訊息第一行之後最多帶幾行（守門的違規清單通常在這裡）
_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
sys.path.insert(0, str(HERE))


def _load(name):
    p = HERE / (name + ".py")
    spec = importlib.util.spec_from_file_location("_rts_" + name, str(p))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod                     # dataclass／pickle 之類需要
    spec.loader.exec_module(mod)
    return mod


def _git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=_NOWIN)
    return r.stdout.strip() if r.returncode == 0 else ""


# ── 純函式（有題）────────────────────────────────────────────────────────

def _nodeid(backend, classname, name):
    """junit 的 classname（tests.platform.test_x.TestCls）＋ name ⇒ `tests/platform/test_x.py::TestCls::name`；對不到檔就原樣用點號。"""
    parts = (classname or "").split(".")
    for k in range(len(parts), 0, -1):
        rel = "/".join(parts[:k]) + ".py"
        if backend is None or (Path(backend) / rel).is_file():
            rest = parts[k:]
            return "::".join([rel, *rest, name])
    return "%s::%s" % (classname, name)


def parse_junit_failures(xml_text, backend=None):
    """⇒ (counts{passed,failed,skipped,error}, failures[{nodeid,kind,message}])；xml 壞掉／空 ⇒ (None, [])。
    紅＝<failure>；error（setup／collection）也算紅，kind 分開記。"""
    try:
        root = ET.fromstring(xml_text)
    except (ET.ParseError, TypeError, ValueError):
        return None, []
    counts = {"passed": 0, "failed": 0, "skipped": 0, "error": 0}
    fails = []
    for tc in root.iter("testcase"):
        bad = tc.find("failure")
        kind = "failed"
        if bad is None:
            bad = tc.find("error")
            kind = "error"
        if bad is not None:
            counts[kind] += 1
            msg = [x for x in (bad.get("message") or (bad.text or "")).strip().splitlines() if x.strip()]
            fails.append({"nodeid": _nodeid(backend, tc.get("classname"), tc.get("name")), "kind": kind, "message": msg[0] if msg else "",
                          "detail": [x.strip() for x in msg[1:1 + DETAIL_LINES]]})
        elif tc.find("skipped") is not None:
            counts["skipped"] += 1
        else:
            counts["passed"] += 1
    return counts, fails


def summarize(counts, failures, secs, log_path, rc, note=""):
    """⇒ dict：給 render 與（別的工具）重用。"""
    return {"counts": counts, "failures": failures, "secs": secs, "log": str(log_path), "rc": rc, "note": note}


def render(s, max_lines=MAX_LINES):
    """⇒ 行清單（長度 ≤ max_lines）。第一行是總數，最後一行是 log 路徑；中間是失敗題 id（超出的以「…另 N 題」收尾）。"""
    c = s["counts"]
    if c is None:
        head = "沒有拿到 junit 結果（pytest exit %s）：無法列出題數；細節見 log" % s["rc"]
    else:
        head = "%s  過 %d　紅 %d　略過 %d%s  （%.0f 秒）" % (
            "PASS" if s["rc"] == 0 else "FAIL", c["passed"], c["failed"] + c["error"], c["skipped"],
            "　其中 error %d" % c["error"] if c["error"] else "", s["secs"])
    lines = [head]
    if s.get("note"):
        lines.append(s["note"])
    fails = s["failures"]
    room = max_lines - len(lines) - 1                           # 留一行給 log 路徑
    if fails:
        show = fails if len(fails) <= room else fails[:max(room - 1, 0)]
        for f in show:
            line = "  ✗ %s" % f["nodeid"]
            if f.get("message") and len(line) < 100:
                line += "  — " + f["message"][:max(100 - len(line), 0)]
            lines.append(line)
        if len(show) < len(fails):
            lines.append("  …另 %d 題見 log" % (len(fails) - len(show)))
    lines.append("log：%s" % s["log"])
    return lines[:max_lines]


def affected_tests(repo, base, changed=None):
    """依 modtest 的選題規則（test_map／dep_graph，現場算）找出跟改動檔有關的測試檔。
    ⇒ (測試檔 [相對 repo]、報告 dict)。改動檔 = git diff <base>（含工作樹）＋未追蹤檔；--files 以外一律由 git 取。"""
    mt = _load("modtest")
    if changed is None:
        out = _git(repo, "diff", "--name-only", "--no-renames", base) if base else _git(repo, "diff", "--name-only", "--no-renames", "HEAD")
        out += "\n" + _git(repo, "ls-files", "--others", "--exclude-standard")
        changed = sorted({x.strip().replace("\\", "/") for x in out.splitlines() if x.strip()})
    if not changed:
        return [], {"changed": [], "unmapped_changes": []}
    ns = argparse.Namespace(files=None, commit=None, changed_since=None, base=base or None)
    picked, rep = mt.select(changed, mt.load_map(False), mt.load_graph(False), mt.iface_checker(ns))
    rep["changed"] = changed
    return picked, rep


# ── 執行 ──────────────────────────────────────────────────────────────

def default_base(repo):
    return _git(repo, "merge-base", "HEAD", "origin/platform")


def run(targets, repo=REPO, workers=1, marker="not e2e", window="rts", log=None, budget_min=30.0):
    """⇒ summarize() 的 dict。targets 相對 backend/ 或 repo；一律轉成相對 backend/。"""
    pg = _load("preflight_guards")
    backend = Path(repo) / "backend"
    rel = [_to_backend_rel(t, repo) for t in targets]
    t0 = time.time()
    rc, out, secs, xml = pg.run_pytest(repo, rel, workers, window, marker=marker, budget_min=budget_min, tee=False, tb="line")
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD") or "detached"
    log_path = Path(log) if log else Path(tempfile.gettempdir()) / ("rts_%s_%d.log" % (re.sub(r"[^\w.-]", "_", branch), int(t0)))
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(out or "", encoding="utf-8")
    except OSError as e:
        log_path = "（log 寫檔失敗：%s）" % e
    counts, fails = parse_junit_failures(xml, backend) if xml else (None, [])
    note = ""
    if rc == pg.INCOMPLETE_RC:
        note = "⚠ 超過時間預算被停掉：結果不完整，不可當綠"
    elif rc == 75:
        note = "⚠ 排隊逾時（有人持有全機閘門鎖）：沒有跑，不可當綠"
    return summarize(counts, fails, secs, log_path, rc, note)


def _to_backend_rel(t, repo):
    t = t.replace("\\", "/")
    if t.startswith("backend/"):
        return t[len("backend/"):]
    return t


def main(argv=None):
    ap = argparse.ArgumentParser(description="測試執行包裝：螢幕只印數字與失敗題 id，完整輸出寫檔")
    ap.add_argument("targets", nargs="*", help="測試檔／題（相對 backend/ 或 repo 根目錄）")
    ap.add_argument("--affected", action="store_true", help="只跑跟改動檔有關的測試（modtest 選題規則）")
    ap.add_argument("--base", help="--affected 的比較基準（預設 merge-base origin/platform）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--marker", default="not e2e")
    ap.add_argument("--log")
    ap.add_argument("--window", default=os.environ.get("MOTRIX_WINDOW", "rts"))
    ap.add_argument("--repo", default=str(REPO))
    a = ap.parse_args(argv)
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    targets = list(a.targets)
    try:
        if a.affected:
            base = a.base or default_base(a.repo)
            picked, rep = affected_tests(a.repo, base)
            if not rep["changed"]:
                print("沒有改動檔（相對 %s）⇒ 沒有受影響的測試" % (base[:10] if base else "HEAD"))
                return 0
            print("改動 %d 檔 → 選到 %d 個測試檔%s" % (len(rep["changed"]), len(picked),
                  "；⚠ 對不到測試的改動檔 %d 個（不代表安全，另行檢查）" % len(rep.get("unmapped_changes", [])) if rep.get("unmapped_changes") else ""))
            if a.dry_run:
                for p in picked:
                    print("  " + p)
                return 0
            targets += picked
        if not targets:
            ap.error("沒有指定測試：給檔名，或用 --affected")
        if a.dry_run:
            print("\n".join(targets))
            return 0
        s = run(targets, a.repo, a.workers, a.marker, a.window, a.log)
    except Exception as e:                                                   # noqa: BLE001
        print("run_tests_summary 本身出錯：%s" % e, file=sys.stderr)
        return 2
    print("\n".join(render(s)))
    return s["rc"] if isinstance(s["rc"], int) and s["rc"] >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
