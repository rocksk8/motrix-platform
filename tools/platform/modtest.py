"""分模組測試執行器：改了什麼 ⇒ 只跑受影響單位的測試＋契約測試。

用法（repo 根目錄）：
  python tools/platform/modtest.py                     工作樹相對 HEAD 的改動（含未追蹤）
  python tools/platform/modtest.py --base <SHA>        git diff --name-only <SHA>
  python tools/platform/modtest.py --commit <SHA>      該 commit 本身的改動（<SHA>^..<SHA>）
  python tools/platform/modtest.py --changed-since <SHA>  <SHA> 之後到 HEAD 的已提交改動（不含工作樹）
  python tools/platform/modtest.py --files a.py b.html 直接指定改動檔
  --dry-run   只印受影響單位、測試清單與題數（collect-only 全部一次再篩），不執行
  --full      跑全量（basetemp 以 -full 結尾 ⇒ 由 conftest 搶全機鎖）
  --window X  basetemp 名稱中的視窗代號（預設 modtest）
  -- <pytest 參數>   其後原樣轉給 pytest

選題規則：
  1. 改動檔 → 單位（命名同 dep_graph.json）。
  2. 有 docs/platform/dep_graph.json ⇒ 沿 imports／routers_called 反向遞移擴大（改 core:* 自動擴到所有依賴者）；
     沒有 ⇒ 只用直接對應，並在輸出註明。
  3. 測試的 units 與受影響單位相交 ⇒ 選；dir: 單位涵蓋其下任一改動檔。
  4. 改動的測試檔本身必選；改到 fixture 層（conftest／pytest.ini／requirements）⇒ 必須全量，拒絕縮小。
  5. core:main 經 client／live_server fixture 被所有 api／e2e 測試隱含依賴 ⇒ 一併選入。
  6. 契約測試（backend/tests/platform/、backend/core/tests/ 下所有 test_*.py）每次必跑；目錄不存在則略過並註明。

暫存：basetemp＝%TEMP%/motrix-pytest-<window>-modtest-<隨機>；結束（綠／紅／Ctrl-C）一律刪除，只刪這一個目錄。
"""
import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_map import REPO, build as build_map, unit_name  # noqa: E402

BACKEND = REPO / "backend"
MAP_PATH = REPO / "docs" / "platform" / "test_map.json"
MODULES_PATH = REPO / "docs" / "platform" / "modules.json"
GRAPH_PATH = REPO / "docs" / "platform" / "dep_graph.json"

#: 改到這些 ⇒ 所有測試的執行環境都變了，縮小不成立
FIXTURE_LAYER = (
    "backend/tests/conftest.py",
    "backend/pytest.ini",
    "backend/requirements.txt",
    "backend/requirements-dev.txt",
)
#: api／e2e 測試經 fixture 隱含依賴的單位
FIXTURE_IMPLIED = {"core:main"}
#: 契約測試所在（存在才算）
CONTRACT_DIRS = ("backend/tests/platform", "backend/core/tests")
TEMP_PREFIX = "motrix-pytest-"


def git(*args):
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


def changed_files(a):
    if a.files:
        return sorted({f.replace("\\", "/") for f in a.files})
    # --no-renames：搬檔時新舊路徑都要算（舊路徑的單位才對得到既有測試）
    if a.commit:
        out = git("diff-tree", "--no-commit-id", "--name-only", "--no-renames", "-r", "--root", a.commit)
        return sorted(set(l for l in out.splitlines() if l.strip()))
    if a.changed_since:
        out = git("diff", "--name-only", "--no-renames", a.changed_since, "HEAD")
        return sorted(set(l for l in out.splitlines() if l.strip()))
    base = a.base or "HEAD"
    out = git("diff", "--name-only", "--no-renames", base)
    if not a.base:
        out += git("ls-files", "--others", "--exclude-standard")
    return sorted(set(l for l in out.splitlines() if l.strip()))


def load_map(refresh):
    if refresh or not MAP_PATH.exists():
        return build_map()
    return json.loads(MAP_PATH.read_text(encoding="utf-8"))


def load_graph():
    if not GRAPH_PATH.exists():
        return None
    g = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    return g.get("units", g)


#: 彙整點：它 import 所有 router，被它依賴不代表它的依賴者受影響；只有它本身被改才往上傳
AGGREGATORS = {"core:main"}


def reverse_closure(start, units):
    """start 單位集合 ⇒ 所有（遞移）依賴它們的單位，含自己。

    - imports 邊（python import、頁面 <script src>）：遞移。
    - 呼叫邊（頁面／js 呼叫 router）：加入呼叫者但不再往上傳（否則 static/sidebar.js 呼叫 system
      ⇒ 所有引用 sidebar 的頁面都被拖進來；那些頁面的 e2e 驗的不是這個 router）。
    - 彙整點（core:main）只在自身為起點時才往上傳。
    """
    rimp, rcall = {}, {}
    for name, u in units.items():
        for d in u.get("imports", []):
            rimp.setdefault(d, set()).add(name)
        for d in set(u.get("routers_called", [])) | set(u.get("routers_called_effective", [])):
            rcall.setdefault(d, set()).add(name)
    seen = set(start)
    expanded = set(start)             # 經 import 邊（或起點）到達者才往上傳；只經呼叫邊到達者不傳
    stack = list(start)
    while stack:
        n = stack.pop()
        for r in rcall.get(n, ()):
            seen.add(r)
        for r in rimp.get(n, ()):
            if r in AGGREGATORS:
                continue
            seen.add(r)
            if r not in expanded:
                expanded.add(r)
                stack.append(r)
    return seen


def frontend_callers(targets, units):
    """直接呼叫 targets（router）的頁面／js。"""
    out = set()
    for name, u in units.items():
        if u.get("kind") in ("page", "js"):
            called = set(u.get("routers_called", [])) | set(u.get("routers_called_effective", []))
            if called & targets:
                out.add(name)
    return out


def table_hop(changed_units, units, conservative):
    """資料表一跳（只從直接改動的單位出發，不串接第二跳）：
    - 寫入／DDL／表名以字串交出（tables_named，方向不明）的表 ⇒ 該表的 readers＋named_by
    - dynamic_sql（f-string 組表名，表可能漏列）⇒ 保守擴大：所有已知讀寫表的 readers＋writers＋named_by
    """
    out = set()
    for n in changed_units:
        u = units.get(n, {})
        wt = set(u.get("tables_w", [])) | set(u.get("tables_ddl", [])) | set(u.get("tables_named", []))
        rt = set(u.get("tables_r", []))
        dyn = bool(u.get("dynamic_sql"))
        if dyn:
            conservative.append(n)
        for t in (wt | rt if dyn else wt):
            tu = units.get("table:" + t)
            if not tu:
                continue
            out.add("table:" + t)
            out |= set(tu.get("readers", [])) | set(tu.get("named_by", []))
            if dyn:
                out |= set(tu.get("writers", []))
    return out


def select(changed, tmap, graph):
    tests = tmap["tests"]
    report = {"changed": changed, "direct_units": [], "affected_units": [], "graph": graph is not None,
              "need_full": [], "unmapped_changes": [], "reasons": {}}
    need_full = [f for f in changed if f in FIXTURE_LAYER]
    report["need_full"] = need_full

    direct = set()
    changed_tests = set()
    for f in changed:
        if f in tests:
            changed_tests.add(f)
        direct.add(unit_name(f))
    report["direct_units"] = sorted(direct)

    affected = set(direct)
    conservative = []
    if graph is not None:
        seeds = {u for u in direct if u in graph}
        # 直接改動：沿 imports／routers_called 反向遞移（core:main 是彙整點，不往上傳）
        affected = reverse_closure(seeds, graph) | direct
        # 資料表一跳：只加該單位本身＋直接呼叫它的頁面／js，不再沿 import 遞移（否則 archive／trail 會拖進全部）
        hop = table_hop(seeds, graph, conservative) - affected
        report["table_hop_units"] = sorted(hop)
        affected |= hop | frontend_callers(hop, graph)
    report["affected_units"] = sorted(affected)
    report["conservative"] = sorted(conservative)

    picked = {}
    for t in changed_tests:
        picked.setdefault(t, []).append("改動的測試檔")
    implied = affected & FIXTURE_IMPLIED
    for t, v in tests.items():
        # 稽核類讀的是原始碼本身 ⇒ 只有它讀的檔被改才受影響，不走相依擴散
        hit = set(v["units"]) & (direct if v["kind"] == "audit" else affected)
        for u in v["units"]:
            if u.startswith("dir:"):
                d = u[4:]
                if any(f.startswith(d) for f in changed):
                    hit.add(u)
        if implied and v["kind"] in ("api", "e2e"):
            hit |= {"%s（fixture 隱含）" % x for x in implied}
        if hit:
            picked.setdefault(t, []).extend(sorted(hit))

    for d in CONTRACT_DIRS:
        p = REPO / d
        if p.is_dir():
            for f in sorted(p.rglob("test_*.py")):
                picked.setdefault(f.relative_to(REPO).as_posix(), []).append("契約測試")
    report["contract_dirs_present"] = [d for d in CONTRACT_DIRS if (REPO / d).is_dir()]

    # 改動檔沒有任何測試對到、也沒有經相依圖擴散出去
    covered_units = {u for v in picked.values() for u in v}
    for f in changed:
        u = unit_name(f)
        if f in tests or f in FIXTURE_LAYER:
            continue
        spread = graph is not None and u in graph and len(reverse_closure({u}, graph)) > 1
        if u not in covered_units and not any(c.startswith("dir:") and f.startswith(c[4:]) for c in covered_units) \
                and not spread:
            report["unmapped_changes"].append(f)
    report["reasons"] = {k: sorted(set(v)) for k, v in sorted(picked.items())}
    return sorted(picked), report


def _new_basetemp(window, full):
    name = "%s%s-modtest-%s%s" % (TEMP_PREFIX, window, uuid.uuid4().hex[:8], "-full" if full else "")
    return Path(tempfile.gettempdir()) / name


def _remove_basetemp(p):
    """只刪本次建立的那一個目錄：必須在 TEMP 底下、名稱以 motrix-pytest-<window>-modtest- 開頭。"""
    p = Path(p)
    try:
        ok = p.parent.resolve() == Path(tempfile.gettempdir()).resolve() and p.name.startswith(TEMP_PREFIX) \
            and "-modtest-" in p.name
    except OSError:
        ok = False
    if not ok:
        print("[暫存] 拒絕刪除非本工具建立的路徑：%s" % p)
        return
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)
    if p.exists():
        print("[暫存] %s 仍有檔案被佔用、未刪乾淨，請手動刪除（只刪這一個）" % p)


def run_pytest(targets, extra, window, full, collect_only=False):
    """在 backend/ 下跑 pytest；basetemp 專屬、結束必刪。回傳 (exit code, stdout)。"""
    bt = _new_basetemp(window, full)
    rel = [str(Path(t).relative_to("backend")) if t.startswith("backend/") else t for t in targets]
    cmd = [sys.executable, "-m", "pytest", *rel, "--basetemp=%s" % bt, "-p", "no:cacheprovider"]
    if collect_only:
        cmd += ["--collect-only", "-q"]
    cmd += extra
    proc = None
    try:
        if collect_only:
            proc = subprocess.run(cmd, cwd=str(BACKEND), capture_output=True, text=True, encoding="utf-8",
                                  errors="replace")
            return proc.returncode, proc.stdout
        proc = subprocess.Popen(cmd, cwd=str(BACKEND))
        return proc.wait(), ""
    except KeyboardInterrupt:
        if proc is not None and hasattr(proc, "poll") and proc.poll() is None:
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
                proc.wait()
        raise
    finally:
        _remove_basetemp(bt)


_COUNT_RE = re.compile(r"(\d+)\s+tests?\s+collected|collected\s+(\d+)\s+items?|^(\d+)\s+tests?\s+collected", re.M)


def collect_per_file(window):
    """collect-only 全部 tests/ 一次（數秒）⇒ {repo 相對檔名: 題數}。
    ⚠ 逐檔傳給 pytest 收集反而慢十倍以上（實測 300 檔 60 秒 vs 全部 5 秒）。"""
    code, out = run_pytest(["tests"], [], window, full=False, collect_only=True)
    tail = out.strip().splitlines()[-1] if out.strip() else ""
    per = {}
    for l in out.splitlines():
        if "::" in l:
            f = "backend/" + l.split("::", 1)[0].replace("\\", "/")
            per[f] = per.get(f, 0) + 1
    if code not in (0, 5) and not per:
        return None, tail
    # 有收集錯誤但仍收到題目 ⇒ 照算，另在輸出標明（錯誤檔的題數算不到）
    return per, (tail if code not in (0, 5) else "")


def load_groups():
    """modules.json ⇒ ({unit: 群組}, {群組: 顯示名})；不存在 ⇒ (None, None)。"""
    if not MODULES_PATH.exists():
        return None, None
    m = json.loads(MODULES_PATH.read_text(encoding="utf-8"))
    owner, names = {}, {"L1": "共用核心"}
    specs = [("L1", m["L1"])] + sorted(m["modules"].items())         + [("retired:" + k, v) for k, v in sorted(m.get("retired", {}).items())]
    for g, spec in specs:
        names.setdefault(g, spec.get("name", g))
        for u in spec.get("units", []):
            owner.setdefault(u, g)
    return owner, names


def module_summary(picked, reasons, per, owner):
    """依「被挑中的原因單位」歸組：{群組: [檔…]}。一個檔可同時算進多組。"""
    out = {}
    for t in picked:
        gs = set()
        for r in reasons[t]:
            u = r.split("（", 1)[0]
            if u == "契約測試":
                gs.add("契約")
            elif u == "改動的測試檔":
                gs.add("改動的測試檔")
            else:
                gs.add(owner.get(u, "其他（file:／dir:／未列入 modules.json）"))
        for g in gs:
            out.setdefault(g, []).append(t)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--base")
    g.add_argument("--commit")
    g.add_argument("--changed-since", metavar="SHA", help="SHA 之後（不含）到 HEAD 的已提交改動")
    g.add_argument("--files", nargs="+")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--refresh-map", action="store_true", help="不讀 test_map.json，現場重算")
    ap.add_argument("--window", default="modtest")
    ap.add_argument("--json", action="store_true", help="dry-run 以 JSON 輸出")
    ap.add_argument("--list", action="store_true", help="dry-run 另列每個測試檔與原因")
    argv = list(sys.argv[1:] if argv is None else argv)
    extra = []
    if "--" in argv:
        i = argv.index("--")
        argv, extra = argv[:i], argv[i + 1:]
    a = ap.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_]+", a.window):
        ap.error("--window 只能是英數底線")

    if a.full:
        if a.dry_run:
            per, tail = collect_per_file(a.window)
            print("全量：%s 題（%s）" % (sum(per.values()) if per is not None else None, tail))
            return 0
        code, _ = run_pytest(["tests"], extra, a.window, full=True)
        return code

    changed = changed_files(a)
    tmap = load_map(a.refresh_map)
    graph = load_graph()
    picked, rep = select(changed, tmap, graph)

    n_items, tail, full_n, per = None, "", None, None
    if a.dry_run:
        per, tail = collect_per_file(a.window)
        if per is not None:
            n_items = sum(per.get(t, 0) for t in picked)
            full_n = sum(per.values())

    owner, gnames = load_groups()
    summary = module_summary(picked, rep["reasons"], per if a.dry_run else None, owner) if owner else None
    if a.json:
        rep["tests"] = picked
        rep["by_module"] = ({g: {"files": len(v), "items": sum(per.get(t, 0) for t in v) if per else None}
                             for g, v in sorted(summary.items())} if summary else None)
        rep["items"] = n_items
        rep["full_items"] = full_n
        sys.stdout.buffer.write((json.dumps(rep, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    else:
        print("改動檔 %d：%s" % (len(changed), ", ".join(changed[:12]) + (" …" if len(changed) > 12 else "")))
        print("相依圖：%s" % ("dep_graph.json（反向遞移）" if graph is not None else "無 ⇒ 只用直接對應"))
        print("受影響單位 %d：%s" % (len(rep["affected_units"]), ", ".join(rep["affected_units"][:20])
                                  + (" …" if len(rep["affected_units"]) > 20 else "")))
        if rep["conservative"]:
            print("保守擴大（dynamic_sql，表可能漏列）：%s" % ", ".join(rep["conservative"]))
        if not rep["contract_dirs_present"]:
            print("契約測試：目錄尚未建立（%s）" % "、".join(CONTRACT_DIRS))
        if rep["unmapped_changes"]:
            print("⚠ 無測試對應的改動檔 %d：%s" % (len(rep["unmapped_changes"]), ", ".join(rep["unmapped_changes"])))
        if rep["need_full"]:
            print("🔴 改到 fixture 層（%s）⇒ 須全量（--full）；不縮小" % ", ".join(rep["need_full"]))
        print("挑出測試檔 %d／%d" % (len(picked), len(tmap["tests"])))
        if a.dry_run:
            if summary is None:
                print("（無 docs/platform/modules.json ⇒ 不做模組彙總）")
            else:
                print("依模組（一檔可跨組，合計會大於總數）：")
                for g in sorted(summary, key=lambda k: (not k.startswith(("L1", "M")), k)):
                    fs = summary[g]
                    print("  %-6s %-10s %4d 檔／%5s 題" % (g, gnames.get(g, ""), len(fs),
                                                        sum(per.get(t, 0) for t in fs) if per else "?"))
            if a.list:
                for t in picked:
                    print("  %s  ← %s" % (t, "、".join(rep["reasons"][t][:4])))
            if n_items is None:
                print("題數：收集失敗（%s）" % tail)
            else:
                print("題數（collect-only）：%d／全量 %d（%.1f%%）" % (n_items, full_n, 100.0 * n_items / max(full_n, 1)))
                if tail:
                    print("⚠ 收集有錯誤，出錯的檔不計入題數：%s" % tail)

    if a.dry_run:
        return 0
    if rep["need_full"]:
        return 3
    if not picked:
        print("沒有受影響的測試。")
        return 0
    code, _ = run_pytest(picked, extra, a.window, full=False)
    return code


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")   # 導向檔案時預設 locale（cp932／cp950）會炸在中文
        except (AttributeError, ValueError):
            pass
    if hasattr(signal, "SIGBREAK"):
        # Windows：Ctrl-Break／關閉主控台視窗送的是 SIGBREAK，預設直接結束行程 ⇒ finally 不會跑、暫存留下
        def _on_break(signum, frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGBREAK, _on_break)
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n中斷。")
        sys.exit(130)
