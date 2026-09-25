"""分模組測試執行器：改了什麼 ⇒ 只跑受影響單位的測試＋契約測試。

用法（repo 根目錄）：
  python tools/platform/modtest.py                     工作樹相對 HEAD 的改動（含未追蹤）
  python tools/platform/modtest.py --base <SHA>        git diff --name-only <SHA>
  python tools/platform/modtest.py --commit <SHA>      該 commit 本身的改動（<SHA>^..<SHA>）
  python tools/platform/modtest.py --changed-since <SHA>  <SHA> 之後到 HEAD 的已提交改動（不含工作樹）
  python tools/platform/modtest.py --files a.py b.html 直接指定改動檔
  python tools/platform/modtest.py --rebase-check <GREEN> [--onto origin/platform]
              §C-11 判定：帶進來的有 fixture 層或兩邊改同檔 ⇒ 全量（exit 3），否則差異題＋tests/platform（exit 0）
  --dry-run   只印受影響單位、測試清單與題數（collect-only 全部一次再篩），不執行
  --full      跑全量：非 e2e（-n --workers）＋ e2e（-n --e2e-workers）兩段；basetemp 以 -full 結尾 ⇒ 由 conftest 搶全機鎖；
              結果（含失敗、中斷，ok=false）原子寫入主工作樹 tools/platform/.last_full.json（沒有這個檔＝沒跑過）
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
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_map import REPO, build as build_map, unit_name  # noqa: E402
import project_env  # noqa: E402

BACKEND = REPO / "backend"
MAP_PATH = REPO / "docs" / "platform" / "test_map.json"
MODULES_PATH = REPO / "docs" / "platform" / "modules.json"
GRAPH_PATH = REPO / "docs" / "platform" / "dep_graph.json"

#: 改到這些 ⇒ 所有測試的執行環境都變了，縮小不成立
FIXTURE_LAYER = (
    "backend/conftest.py",            # 2026-09-25 自 backend/tests/ 上移（modules/*/tests 共用）
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
#: 全量／計數的收集範圍（同 pytest.ini testpaths；modules/*/tests 是模組自己的測試）
TEST_ROOTS = ["tests", "modules"]


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


def _names(repo, *diff_args):
    out = subprocess.run(["git", "-C", str(repo), "diff", "--name-only", "--no-renames", *diff_args],
                         capture_output=True, text=True, encoding="utf-8", check=True).stdout
    return set(l for l in out.splitlines() if l.strip())


def rebase_check(green, onto, repo=None, head="HEAD"):
    """PLAYBOOK §C-11：全量綠在 green（rebase 前的分支尖端）之後 rebase 到 onto，要不要重跑全量。

    帶進來的＝merge-base..onto；本分支的＝merge-base..green。
    - 帶進來的碰到 FIXTURE_LAYER ⇒ 全量
    - 兩邊改了同一個程式檔 ⇒ 全量（以「同檔」近似「程式碼衝突」：比 git 文字衝突寬，寧可多跑）
    - 兩邊改了同一個 .md ⇒ 只列出、不觸發全量（讀文件的守門在 tests/platform，差異題本來就會跑）
    - 都沒有 ⇒ 只跑 after_green（全量之後本分支才改的檔）的差異題＋tests/platform：`modtest --files <after_green>`
      after_green＝(green 與 head 兩棵樹的差) − 帶進來的檔；帶進來的已由對方自己的全量驗過（§C-11 補充）。
      ☠️ 不建議 `--changed-since <green>`：它把帶進來的也算進去，對方改到 L0 時會挑出九成（2026-09-26 實測 90.7%）；
         也不建議 `--base <onto>`：本分支自己改過 fixture 層時一定被拒（同日實測）。
    - 帶進來的檔在 head 上又被本分支改過（head 與 onto 的內容不同）⇒ 視為程式碼衝突
    ⚠ 只看「帶進來的」：本分支自己改的 fixture 層由它自己的全量負責（§C-4），不在這裡判定。
    ⚠ 要在 rebase **之後**跑（head 已經在 onto 上）；rebase 之前跑，after_green 永遠是空的。
    """
    repo = repo or REPO
    mb = subprocess.run(["git", "-C", str(repo), "merge-base", green, onto], capture_output=True, text=True,
                        encoding="utf-8", check=True).stdout.strip()
    incoming, mine = _names(repo, mb, onto), _names(repo, mb, green)
    since_green = _names(repo, green, head)
    touched_again = {f for f in incoming & since_green if _names(repo, onto, head, "--", f)}
    fixture = sorted(f for f in incoming if f in FIXTURE_LAYER)
    both = (incoming & mine) | touched_again
    overlap = sorted(f for f in both if not f.endswith(".md"))
    rebased = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", onto, head]).returncode == 0
    return {"green": green, "onto": onto, "head": head, "merge_base": mb, "rebased": rebased,
            "incoming": sorted(incoming), "mine": sorted(mine),
            "after_green": sorted(since_green - incoming),
            "fixture_layer": fixture, "overlap": overlap, "overlap_docs": sorted(both - set(overlap)),
            "need_full": bool(fixture or overlap)}


def print_rebase_check(r):
    print("全量綠在 %s；rebase 到 %s（merge-base %s）" % (r["green"], r["onto"], r["merge_base"][:10]))
    print("帶進來的改動檔 %d；本分支改動檔 %d" % (len(r["incoming"]), len(r["mine"])))
    print("fixture 層：%s" % ("、".join(r["fixture_layer"]) or "無"))
    print("兩邊都改的程式檔（視為程式碼衝突）：%s" % ("、".join(r["overlap"]) or "無"))
    if r["overlap_docs"]:
        print("兩邊都改的文件（不觸發全量）：%s" % "、".join(r["overlap_docs"]))
    if r["need_full"]:
        print("🔴 判定：重跑全量（§C-11 例外）")
    elif not r["rebased"]:
        print("⚠ %s 還沒 rebase 到 %s ⇒ 全量之後改了什麼算不出來；先 rebase 再跑本判定" % (r["head"], r["onto"]))
    else:
        ag = r["after_green"]
        cmd = "modtest --files %s" % " ".join(ag) if ag else "tests/platform（全量之後本分支沒有再改）"
        print("✓ 判定：跑 `%s`（modtest 另帶 tests/platform）；回報寫「全量在 %s，差異題在 %s」"
              % (cmd, r["green"], r["onto"]))


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
    # 🔴 更正（保留原判斷）：09-25 全量三次「刪不乾淨」我先判成「檔案仍被佔用」而加長重試（6→30 次），
    #    實查留下的是測試在 tmp 建的 git repo，git 物件檔是**唯讀** ⇒ Windows 上 rmtree(ignore_errors=True)
    #    永遠刪不掉，重試多久都一樣。⇒ 先解除唯讀再刪；重試只留給真的被占用的情形。
    def _clear_readonly(func, path, _exc):
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except OSError:
            pass

    for _ in range(10):
        if not p.exists():
            break
        shutil.rmtree(p, onerror=_clear_readonly)
        if p.exists():
            time.sleep(2)
    if p.exists():
        print("[暫存] %s 仍有檔案刪不掉（被占用），請手動刪除（只刪這一個）" % p)


#: 跑 pytest 用的直譯器：預設主工作樹的專案 .venv（照 requirements 安裝）；由 main() 決定
PYEXE = None
#: PLAYBOOK §C-13（2026-09-25 使用者回報 CPU 100%）：全量 -n 4 以下、差異題 -n 2 以下、低優先權
FULL_MAX_WORKERS = 4
PARTIAL_MAX_WORKERS = 2


def cap_workers(extra, limit):
    """extra 裡的 -n N 超過上限 ⇒ 壓到上限並說出來。回傳新的 extra。"""
    out, i = list(extra), 0
    while i < len(out):
        a = out[i]
        val, j = None, None
        if a in ("-n", "--numprocesses") and i + 1 < len(out):
            val, j = out[i + 1], i + 1
        elif a.startswith("-n") and a[2:].isdigit():
            val, j = a[2:], i
        if val is not None:
            n = limit if val in ("auto", "logical") else int(val) if val.isdigit() else None
            if n is None or n > limit:
                print("⚠ -n %s 超過 §C-13 上限，改為 -n %d" % (val, limit))
                if j == i:
                    out[i] = "-n%d" % limit
                else:
                    out[j] = str(limit)
        i += 1
    return out


def _low_priority_flags():
    """Windows：低優先權（子行程——xdist worker、瀏覽器——會繼承）。"""
    return getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0) if os.name == "nt" else 0


def resolve_python(explicit=None):
    """--python 指定 ⇒ 用它；否則專案 .venv；都沒有 ⇒ **明確警告**再退回目前的直譯器（不默默退）。"""
    if explicit:
        return explicit
    py = project_env.venv_python()
    if py is not None:
        return str(py)
    print("⚠ 找不到專案 .venv（%s）⇒ 這一輪改用 %s，套件版本不一定等於 requirements.txt。"
          "\n  建立：python tools/platform/project_env.py create" % (project_env.main_worktree_root() / project_env.VENV_DIR,
                                                                    sys.executable))
    return sys.executable


def run_pytest(targets, extra, window, full, collect_only=False):
    """在 backend/ 下跑 pytest；basetemp 專屬、結束必刪。回傳 (exit code, stdout)。"""
    bt = _new_basetemp(window, full)
    rel = [str(Path(t).relative_to("backend")) if t.startswith("backend/") else t for t in targets]
    cmd = [PYEXE or sys.executable, "-m", "pytest", *rel, "--basetemp=%s" % bt, "-p", "no:cacheprovider"]
    if collect_only:
        cmd += ["--collect-only", "-q"]
    cmd += extra
    proc = None
    try:
        if collect_only:
            proc = subprocess.run(cmd, cwd=str(BACKEND), capture_output=True, text=True, encoding="utf-8",
                                  errors="replace")
            return proc.returncode, proc.stdout
        proc = subprocess.Popen(cmd, cwd=str(BACKEND), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                creationflags=_low_priority_flags())
        tail = []
        for raw in proc.stdout:                       # 照樣即時印出，另留尾段給摘要解析
            line = raw.decode("utf-8", errors="replace")
            sys.stdout.write(line)
            sys.stdout.flush()
            tail.append(line)
            if len(tail) > 400:
                del tail[:200]
        return proc.wait(), "".join(tail)
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
    code, out = run_pytest(TEST_ROOTS, [], window, full=False, collect_only=True)
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
    specs = [("L1", m["L1"])] + sorted(m["modules"].items()) \
        + [("retired:" + k, v) for k, v in sorted(m.get("retired", {}).items())]
    for g, spec in specs:
        names.setdefault(g, spec.get("name", g))
        for u in spec.get("units", []):
            owner.setdefault(u, g)
        if spec.get("key"):
            owner.setdefault("dir:backend/modules/%s/" % spec["key"], g)   # 模組測試目錄的歸屬
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


# ── 全量＋結果檔（部署儀表板 D6「測試閘門」讀它，CORE-SPEC §9e）──────────────────

#: 摘要行裡的各種計數：`3 failed, 3393 passed, 54 skipped, 3 xfailed, 2 errors in 697.60s`
_SUMMARY_ITEM = re.compile(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|deselected|warnings?)")


def parse_summary(out):
    """pytest 最後的摘要行 ⇒ {passed, failed, errors, skipped, ...}；找不到摘要行 ⇒ None（不是 0）。"""
    for line in reversed(out.splitlines()):
        if re.search(r" in [\d.]+s", line) and _SUMMARY_ITEM.search(line):
            got = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0, "xfailed": 0}
            for n, k in _SUMMARY_ITEM.findall(line):
                k = "errors" if k.startswith("error") else k
                if k in got:
                    got[k] = int(n)
            return got
    return None


def main_worktree_root():
    """主工作樹的位置：worktree 用完就刪，結果檔要落在主工作樹（`--git-common-dir` 的上一層）。"""
    common = git("rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    return Path(common).parent


def write_last_full(result):
    """原子寫入：同目錄暫存檔 → os.replace。"""
    dest = main_worktree_root() / "tools" / "platform" / ".last_full.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(".last_full.json.%d.tmp" % os.getpid())
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, dest)
    return dest


def _now():
    from datetime import datetime
    return datetime.now().astimezone().isoformat(timespec="seconds")


def run_full(extra, a):
    """全量＝兩段：非 e2e（-n workers）＋ e2e（-n e2e-workers）。結果（含失敗、中斷）一律寫進主工作樹的 .last_full.json。"""
    result = {
        "commit": git("rev-parse", "HEAD").strip(),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD").strip(),
        "dirty": bool(git("status", "--porcelain", "--untracked-files=no").strip()),
        "started": _now(), "finished": None,
        "passed": None, "failed": None, "errors": None, "skipped": None,
        "e2e": None, "ok": False, "interrupted": False,
        "python": PYEXE or sys.executable,
        "python_version": subprocess.run([PYEXE or sys.executable, "-c", "import sys;print(sys.version.split()[0])"],
                                         capture_output=True, text=True).stdout.strip(),
    }
    stages = [("main", cap_workers(["-m", "not e2e", "-n", str(a.workers)], FULL_MAX_WORKERS), a.window),
              ("e2e", cap_workers(["-m", "e2e", "-n", str(a.e2e_workers)], FULL_MAX_WORKERS), a.window + "e2e")]
    extra = cap_workers(extra, FULL_MAX_WORKERS)
    codes = {}
    try:
        for name, args, window in stages:
            code, out = run_pytest(TEST_ROOTS, args + extra, window, full=True)
            codes[name] = code
            counts = parse_summary(out) or {"passed": None, "failed": None, "errors": None, "skipped": None}
            part = dict(counts, exit=code)
            if name == "main":
                result.update(part)
            else:
                result["e2e"] = part
        result["ok"] = all(c == 0 for c in codes.values()) and len(codes) == len(stages)
        return 0 if result["ok"] else (codes.get("main") or codes.get("e2e") or 1)
    except KeyboardInterrupt:
        result["interrupted"] = True
        raise
    finally:
        result["finished"] = _now()
        try:
            dest = write_last_full(result)
            print("[全量結果] %s ok=%s → %s" % (result["commit"][:8], result["ok"], dest))
        except Exception as e:                      # noqa: BLE001 — 寫不出結果檔要說出來，不可靜默
            print("[全量結果] ⚠ 寫不出 .last_full.json：%r" % e)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--base")
    g.add_argument("--commit")
    g.add_argument("--changed-since", metavar="SHA", help="SHA 之後（不含）到 HEAD 的已提交改動")
    g.add_argument("--files", nargs="+")
    g.add_argument("--rebase-check", metavar="GREEN", help="§C-11：全量綠在 GREEN，rebase 到 --onto 之後要不要重跑全量（只判定、不執行）")
    ap.add_argument("--onto", default="origin/platform", help="--rebase-check 的 rebase 目標（預設 origin/platform）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--full", action="store_true", help="全量（非 e2e＋e2e 兩段）；結果寫主工作樹 tools/platform/.last_full.json")
    ap.add_argument("--workers", type=int, default=FULL_MAX_WORKERS, help="--full 非 e2e 段的 xdist worker 數（上限 %d，§C-13）" % FULL_MAX_WORKERS)
    ap.add_argument("--e2e-workers", type=int, default=FULL_MAX_WORKERS, help="--full e2e 段的 xdist worker 數（上限 %d，§C-13）" % FULL_MAX_WORKERS)
    ap.add_argument("--refresh-map", action="store_true", help="不讀 test_map.json，現場重算")
    ap.add_argument("--window", default="modtest")
    ap.add_argument("--python", help="指定跑 pytest 的直譯器（預設：主工作樹的專案 .venv）")
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
    if a.rebase_check:
        r = rebase_check(a.rebase_check, a.onto)
        if a.json:
            sys.stdout.buffer.write((json.dumps(r, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
        else:
            print_rebase_check(r)
        return 3 if r["need_full"] else (0 if r["rebased"] else 2)
    global PYEXE
    PYEXE = resolve_python(a.python)

    if a.full:
        if a.dry_run:
            per, tail = collect_per_file(a.window)
            print("全量：%s 題（%s）" % (sum(per.values()) if per is not None else None, tail))
            return 0
        return run_full(extra, a)

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
    code, _ = run_pytest(picked, cap_workers(extra, PARTIAL_MAX_WORKERS), a.window, full=False)
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
