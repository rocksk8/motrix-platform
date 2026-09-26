"""分模組測試執行器：改了什麼 ⇒ 只跑受影響單位的測試＋契約測試。

用法（repo 根目錄）：
  python tools/platform/modtest.py                     工作樹相對 HEAD 的改動（含未追蹤）
  python tools/platform/modtest.py --base <SHA>        git diff --name-only <SHA>
  python tools/platform/modtest.py --commit <SHA>      該 commit 本身的改動（<SHA>^..<SHA>）
  python tools/platform/modtest.py --changed-since <SHA>  <SHA> 之後到 HEAD 的已提交改動（不含工作樹）
  python tools/platform/modtest.py --files a.py b.html 直接指定改動檔
  python tools/platform/modtest.py --rebase-check <GREEN> [--onto origin/platform]
              §C-11 判定：帶進來的有 fixture 層或兩邊改同檔 ⇒ 影響大（exit 3）：差異題擴大到那些檔＋tests/platform＋改到頁面的 e2e，
              **全量交給列車**（§G3：各線不跑全量）並在月台註明；否則差異題＋tests/platform（exit 0）
  --dry-run   只印受影響單位、測試清單與題數（collect-only 全部一次再篩），不執行
  --full      跑全量：非 e2e（-n --workers）＋ e2e（-n --e2e-workers）兩段；basetemp 以 -full 結尾 ⇒ 由 conftest 搶全機鎖；
              結果（含失敗、中斷，ok=false）原子寫入主工作樹 tools/platform/full_results/<commit>.json（儀表板閘門讀這個；
              dirty 不寫）與 .last_full.json（最近一次，只供人看）
  --window X  basetemp 名稱中的視窗代號（預設 modtest）
  -- <pytest 參數>   其後原樣轉給 pytest

選題規則：
  1. 改動檔 → 單位（命名同 dep_graph.json）。
  2. 有 docs/platform/dep_graph.json ⇒ 沿 imports／routers_called 反向遞移擴大（改 core:* 自動擴到所有依賴者）；
     沒有 ⇒ 只用直接對應，並在輸出註明。
  3. 測試的 units 與受影響單位相交 ⇒ 選；dir: 單位涵蓋其下任一改動檔。
  4. 改動的測試檔本身必選；改到 fixture 層（conftest／pytest.ini／requirements）⇒ 差異題照跑，**全量交給列車**（§G3），閘門過了回 exit 3＝月台要註明、排車頭。
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


# ── 簿記檔：每次合回都會兩邊一起改，只在「同一個項目」被兩邊改時才算衝突（主持 2026-09-26：各線追著跑全量）──

def _show(repo, ref, rel):
    r = subprocess.run(["git", "-C", str(repo), "show", "%s:%s" % (ref, rel)], capture_output=True, text=True,
                       encoding="utf-8")
    return r.stdout if r.returncode == 0 else None


def _flat(obj, path=()):
    """JSON ⇒ {鍵: 值}。dict 逐鍵；純量清單 ⇒ 每個項目一個鍵；dict 清單以 version／key 為鍵（沒有就用位置）。"""
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_flat(v, path + (str(k),)))
    elif isinstance(obj, list):
        if all(not isinstance(x, (dict, list)) for x in obj):
            for x in obj:
                out[path + ("∋", json.dumps(x, ensure_ascii=False))] = True
        else:
            for i, x in enumerate(obj):
                ident = (x.get("version") or x.get("key")) if isinstance(x, dict) else None
                out.update(_flat(x, path + ("[%s]" % (ident or i),)))
    else:
        out[path] = obj
    return out


def _diff_keys(fa, fb):
    return {k for k in set(fa) | set(fb) if fa.get(k) != fb.get(k)}


def _changed_json(a, b):
    """一般 JSON（version_manifest 以條目 version 為鍵；modules.json 以群組／欄位／單位為鍵）。"""
    return _diff_keys(_flat(json.loads(a)), _flat(json.loads(b)))


def _changed_snapshot(a, b):
    """G1 快照：core_version 每次合回都變，不算；項目＝「interface／單位／名稱」。"""
    da, db = json.loads(a), json.loads(b)
    for d in (da, db):
        d.pop("core_version", None)
    return {k[:3] for k in _diff_keys(_flat(da), _flat(db))}


def _changed_registry(a, b):
    """registry.py：只改 CORE_VERSION 那一行 ⇒ 沒有項目；其餘任何改動 ⇒ 一個「其他」項目。"""
    import difflib
    keep = lambda t: [l for l in t.splitlines() if not re.match(r"\s*CORE_VERSION\s*=", l)]
    return {("registry", "其他改動")} if list(difflib.unified_diff(keep(a), keep(b), n=0)) else set()


#: 簿記檔 ⇒ 「這一側改了哪些項目」。項目有交集才算衝突。
BOOKKEEPING = {
    "backend/core/registry.py": _changed_registry,
    "backend/tests/platform/l1_interface_snapshot.json": _changed_snapshot,
    "backend/version_manifest.json": _changed_json,
    "docs/platform/modules.json": _changed_json,
}


def bookkeeping_overlap(repo, rel, mine_pair, incoming_pair):
    """兩側 (base, ref) 各自改了哪些項目；有交集或讀不到／解析不了 ⇒ (True, 說明)，否則 (False, 說明)。"""
    texts = [_show(repo, ref, rel) for ref in (*mine_pair, *incoming_pair)]
    if any(t is None for t in texts):
        return True, "有一側讀不到（新增或刪除）⇒ 保守判衝突"
    try:
        m = BOOKKEEPING[rel](texts[0], texts[1])
        i = BOOKKEEPING[rel](texts[2], texts[3])
    except (ValueError, TypeError, AttributeError) as e:
        return True, "解析不了（%s）⇒ 保守判衝突" % e
    both = sorted("/".join(map(str, k)) for k in m & i)
    return bool(both), ("兩邊都改：%s" % "、".join(both[:5])) if both else "項目不重疊（本分支 %d、帶進來 %d）" % (len(m), len(i))


def rebase_check(green, onto, repo=None, head="HEAD"):
    """PLAYBOOK §C-11：全量綠在 green（rebase 前的分支尖端）之後 rebase 到 onto，要跑哪些題。

    🔴 2026-09-26 起**不再判「重跑全量」**（§G3：全量只由列車跑一次；C 因為本判定同時起跑兩輪全量，全機 3 組，超過 §C-13）：
       原本判全量的情形改成 `high_impact`＝差異題擴大到帶進來的衝突檔＋tests/platform＋改到頁面的 e2e，全量交給列車，
       月台登記時註明（fixture 層那一包要排在列車最前面，§G3 例外條）。

    帶進來的＝merge-base..onto；本分支的＝merge-base..green。
    - 帶進來的碰到 FIXTURE_LAYER ⇒ 影響大
    - 兩邊改了同一個程式檔 ⇒ 影響大（以「同檔」近似「程式碼衝突」：比 git 文字衝突寬，寧可多選）
    - 兩邊改了同一個 .md ⇒ 只列出、不算影響大（讀文件的守門在 tests/platform，差異題本來就會跑）
    - 都沒有 ⇒ 只跑 after_green（全量之後本分支才改的檔）的差異題＋tests/platform：`modtest --files <after_green>`
      after_green＝(green 與 head 兩棵樹的差) − 帶進來的檔；帶進來的已由對方自己的全量驗過（§C-11 補充）。
      ☠️ 不建議 `--changed-since <green>`：它把帶進來的也算進去，對方改到 L0 時會挑出九成（2026-09-26 實測 90.7%）；
         也不建議 `--base <onto>`：本分支自己改過 fixture 層時一定被拒（同日實測）。
    - 帶進來的檔在 head 上又被本分支改過（head 與 onto 的內容不同）⇒ 視為程式碼衝突（影響大）
    - 例外：簿記檔（BOOKKEEPING：registry／G1 快照／version_manifest／modules.json）只在**同一個項目**被兩邊改時才算衝突
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
    # 簿記檔：兩邊的「項目」有交集才算衝突（全量前的改動看 mb..green；rebase 後才改的看 onto..head）
    bookkeeping = {}
    for f in sorted(both & set(BOOKKEEPING)):
        checks = []
        if f in incoming & mine:
            checks.append(bookkeeping_overlap(repo, f, (mb, green), (mb, onto)))
        if f in touched_again:
            checks.append(bookkeeping_overlap(repo, f, (onto, head), (mb, onto)))
        hit = [d for c, d in checks if c]
        bookkeeping[f] = {"conflict": bool(hit), "detail": "；".join(hit or [d for _, d in checks])}
    benign = {f for f, v in bookkeeping.items() if not v["conflict"]}
    overlap = sorted(f for f in both - benign if not f.endswith(".md"))
    rebased = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", onto, head]).returncode == 0
    return {"green": green, "onto": onto, "head": head, "merge_base": mb, "rebased": rebased,
            "incoming": sorted(incoming), "mine": sorted(mine),
            "after_green": sorted(since_green - incoming),
            "fixture_layer": fixture, "overlap": overlap,
            "overlap_docs": sorted(f for f in both - set(overlap) if f.endswith(".md")),
            "bookkeeping": bookkeeping,
            "high_impact": bool(fixture or overlap),
            "suggest": suggest_command(sorted(since_green - incoming), overlap)}


def suggest_command(after_green, overlap):
    """建議的差異題指令（永遠不是全量）：`modtest --files <全量之後本分支改的＋兩邊都改的程式檔>`；
    fixture 層檔不放進 --files——它們由列車的全量負責。"""
    files = sorted(f for f in set(after_green) | set(overlap) if f not in FIXTURE_LAYER)
    return "modtest --files %s" % " ".join(files) if files else "modtest --files <無：只跑 tests/platform>"


def print_rebase_check(r):
    print("全量綠在 %s；rebase 到 %s（merge-base %s）" % (r["green"], r["onto"], r["merge_base"][:10]))
    print("帶進來的改動檔 %d；本分支改動檔 %d" % (len(r["incoming"]), len(r["mine"])))
    print("fixture 層：%s" % ("、".join(r["fixture_layer"]) or "無"))
    print("兩邊都改的程式檔（視為程式碼衝突）：%s" % ("、".join(r["overlap"]) or "無"))
    if r["overlap_docs"]:
        print("兩邊都改的文件（不觸發全量）：%s" % "、".join(r["overlap_docs"]))
    for f, v in sorted(r.get("bookkeeping", {}).items()):
        print("簿記檔 %s：%s（%s）" % (f, "🔴 衝突" if v["conflict"] else "不重疊", v["detail"]))
    if not r["rebased"]:
        print("⚠ %s 還沒 rebase 到 %s ⇒ 全量之後改了什麼算不出來；先 rebase 再跑本判定" % (r["head"], r["onto"]))
    else:
        print("✓ 判定：跑 `%s`（modtest 另帶 tests/platform）＋改到頁面的 e2e；回報寫「全量在 %s，差異題在 %s」"
              % (r["suggest"], r["green"], r["onto"]))
        if r["high_impact"]:
            what = "、".join(r["fixture_layer"] + r["overlap"])
            print("⚠ 影響大（帶進 fixture 層或兩邊改同檔：%s）⇒ **不要自己跑全量**：全量交給列車（PLAYBOOK §G3）；"
                  "月台登記時註明這幾個檔%s" % (what, "，帶進 fixture 層的包排在列車最前面" if r["fixture_layer"] else ""))


def _read_map_file():
    return json.loads(MAP_PATH.read_text(encoding="utf-8")) if MAP_PATH.exists() else None


def _read_graph_file():
    if not GRAPH_PATH.exists():
        return None
    g = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    return g.get("units", g)


def load_map(use_files=False):
    """test_map：預設**現場算**（產生檔只由列車提交，分支上的檔是 origin 版——GENERATED-FILES-PROPOSAL §2：
    讀檔會漏掉新增／搬家的測試檔，回放最多漏 13 檔）。use_files ⇒ 讀 docs/platform/test_map.json（除錯用）。
    現場算失敗 ⇒ 說出來、退回讀檔（不可以靜默變成「不選題」）。"""
    if use_files:
        return _read_map_file() or build_map()
    try:
        return build_map()
    except Exception as e:                                   # noqa: BLE001 退回讀檔並明說
        _say("[modtest] ⚠ 現場建 test_map 失敗（%r）⇒ 退回讀 %s（可能漏掉本分支新增的測試檔）" % (e, MAP_PATH.name))
        return _read_map_file()


def load_graph(use_files=False):
    """dep_graph：預設**現場算**（dep_scan.build()）；回放顯示只換 test_map 仍會漏題（改動沿反向 import 擴散靠它）。"""
    if use_files:
        return _read_graph_file()
    try:
        import dep_scan
        g = dep_scan.build()
        return g.get("units", g)
    except Exception as e:                                   # noqa: BLE001 退回讀檔並明說
        _say("[modtest] ⚠ 現場建 dep_graph 失敗（%r）⇒ 退回讀 %s（反向遞移可能不準）" % (e, GRAPH_PATH.name))
        return _read_graph_file()


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


def direct_dependents(start, units):
    """start 單位集合 ⇒ 自己＋**直接** import 它們的單位＋直接呼叫它們的頁面／js（一跳，不遞移；彙整點不算）。
    PLAYBOOK §C-11a ①：改動單位的介面沒變時用這個（遞移擴散只在介面有變時才需要）。"""
    out = set(start)
    for name, u in units.items():
        if name in AGGREGATORS:
            continue
        called = set(u.get("routers_called", [])) | set(u.get("routers_called_effective", []))
        if set(u.get("imports", [])) & start or called & start:
            out.add(name)
    return out


def _interface_tools():
    sys.path.insert(0, str(REPO / "backend" / "tests" / "platform"))
    import _l1_interface as G   # noqa: E402
    return G


def interface_changed(rel, old_ref, new_ref=None):
    """rel 在 old_ref 與 new_ref（None＝工作樹）之間，公開介面（G1 的描述：名稱、簽名、async、僅限位置參數）有沒有變。
    非 .py、新增／刪除、讀不到、語法錯誤 ⇒ True（保守：沿用遞移擴散）。"""
    if not rel.endswith(".py"):
        return True
    old = _show(REPO, old_ref, rel)
    if new_ref is None:
        p = REPO / rel
        new = p.read_text(encoding="utf-8-sig") if p.is_file() else None
    else:
        new = _show(REPO, new_ref, rel)
    if old is None or new is None:
        return True
    G = _interface_tools()
    # 稽核 D O-2：與 G1 守門同一個範圍——跨模組在用的底線名稱（_require_user、_get_setting…）也算介面
    extra = frozenset(_cross_boundary().get(unit_name(rel), ()))
    try:
        return G.interface_of(old.lstrip("﻿"), extra) != G.interface_of(new, extra)
    except SyntaxError:
        return True


_CROSS = None


def _cross_boundary():
    """G1 的 cross_boundary_public()（掃全部產品碼，一次執行只算一次）；算不出來 ⇒ 空（退回只看公開名稱）。"""
    global _CROSS
    if _CROSS is None:
        try:
            _CROSS = _interface_tools().cross_boundary_public()
        except Exception:        # noqa: BLE001
            _CROSS = {}
    return _CROSS


def iface_checker(a):
    """依 CLI 參數決定介面比對的兩端：--commit X ⇒ X^ 對 X；--changed-since X ⇒ X 對 HEAD；
    --base X ⇒ X 對工作樹；其餘（工作樹、--files）⇒ HEAD 對工作樹。"""
    if a.commit:
        old, new = a.commit + "^", a.commit
    elif a.changed_since:
        old, new = a.changed_since, "HEAD"
    elif a.base:
        old, new = a.base, None
    else:
        old, new = "HEAD", None
    fn = lambda rel: interface_changed(rel, old, new)   # noqa: E731
    fn.refs = (old, new)                                 # select() 用來做名稱層級（§C-11a ③）
    return fn


def _source(rel, ref):
    """rel 在 ref（None＝工作樹）的原始碼；讀不到 ⇒ None。"""
    if ref is None:
        p = REPO / rel
        return p.read_text(encoding="utf-8-sig") if p.is_file() else None
    t = _show(REPO, ref, rel)
    return t.lstrip("﻿") if t is not None else None


def name_filter(seeds, deps, by_unit, graph, refs, report):
    """§C-11a ③：seeds（介面不變的改動單位）的直接使用者 deps ⇒ 只留用到「這次被改的名稱」的那些。
    判斷不了（ALL、找不到 import、讀不到原始碼、頁面／js 的呼叫邊）一律保留。report["names"] 記下每個 seed 被改的名稱。"""
    import scope_names as SN
    from dep_scan import helper_reexports, known_tables
    old, new = refs
    reexp = helper_reexports()
    try:
        known = set(known_tables())
    except Exception:            # noqa: BLE001 — 讀不到表清單 ⇒ 資料表一跳退回整個單位（保守）
        known = None
    keep = set(seeds)
    report.setdefault("names", {})
    for s in seeds:
        users = {d for d in deps - seeds
                 if s in graph.get(d, {}).get("imports", [])
                 or s in set(graph.get(d, {}).get("routers_called", [])) | set(graph.get(d, {}).get("routers_called_effective", []))}
        ch = SN.ALL
        for f in by_unit.get(s, []):
            a, b = _source(f, old), _source(f, new)
            c = SN.changed_names(a, b) if a is not None and b is not None else SN.ALL
            if c is SN.ALL:
                ch = SN.ALL
                break
            ch = (ch or set()) | c
        srcs = [t for f in by_unit.get(s, []) for t in (_source(f, old), _source(f, new)) if t is not None]
        if ch is not SN.ALL:
            # 稽核 D S-M1：模組內引用閉包——改私有 _a，呼叫它的公開 b 也算被改（否則只 import b 的使用者全被拿掉）
            report.setdefault("names_direct", {})[s] = sorted(ch)
            ch = SN.expand_internal(srcs, ch)
        report["names"][s] = "全部（判斷不了）" if ch is SN.ALL else sorted(ch)
        if ch is SN.ALL:
            keep |= users
            continue
        # 資料表一跳也細到被改的名稱（閉包後；否則 db.py 這類帶 dynamic_sql 的單位，改哪個函式都擴到所有表）
        nt = SN.name_tables(srcs, ch, known) if known is not None else None
        if nt is not None:
            report.setdefault("name_tables", {})[s] = nt
        target = SN.dotted(graph[s].get("path") or "")
        for d in users:
            u = graph.get(d, {})
            if u.get("kind") in ("page", "js") or not u.get("path", "").endswith(".py"):
                keep.add(d)
                continue
            src = _source(u["path"], new)
            used = SN.used_names(src, target, reexp) if src is not None else SN.ALL
            if used is SN.ALL or not used or used & ch:
                keep.add(d)
    return keep


#: §C-11a ⑥：每次選題的統計（主工作樹，gitignored；D1b「常用 helper ≤30%」以這份驗收）
STATS_REL = ("tools", "platform", "full_results", "modtest_stats.jsonl")


def record_stats(changed, picked, tmap, rep, items, full_items, seconds, dry_run, exit_code=None, root=None):
    """附加一行 JSON。寫不出來只提示、不影響選題結果。"""
    row = {"at": _now(), "rule": rep.get("rule"), "dry_run": dry_run, "changed": changed,
           "files": len(picked), "files_total": len(tmap["tests"]),
           "files_ratio": round(len(picked) / max(len(tmap["tests"]), 1), 4),
           "items": items, "items_total": full_items,
           "items_ratio": round(items / full_items, 4) if items is not None and full_items else None,
           "seconds": round(seconds, 1) if seconds is not None else None, "exit": exit_code,
           "iface": rep.get("iface")}
    try:
        p = Path(root or main_worktree_root()).joinpath(*STATS_REL)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as e:
        _say("⚠ 選題統計寫不出來：%r" % e)
    return row


def frontend_callers(targets, units):
    """直接呼叫 targets（router）的頁面／js。"""
    out = set()
    for name, u in units.items():
        if u.get("kind") in ("page", "js"):
            called = set(u.get("routers_called", [])) | set(u.get("routers_called_effective", []))
            if called & targets:
                out.add(name)
    return out


def table_hop(changed_units, units, conservative, override=None):
    """override：{單位: {"tables_r", "tables_w", "tables_ddl", "tables_named", "dynamic_sql"}}——§C-11a ③ 名稱層級時，
    改用「這次被改的函式」自己的資料表，不用整個單位的（db.py 帶 dynamic_sql ⇒ 否則一律擴到所有表）。"""
    return _table_hop(changed_units, {**units, **{k: dict(units.get(k, {}), **v) for k, v in (override or {}).items()}},
                      conservative)


def _table_hop(changed_units, units, conservative):
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


def select(changed, tmap, graph, iface_changed=None):
    """iface_changed(檔) -> bool：有給 ⇒ 介面沒變的單位只擴到直接依賴（§C-11a ①②）；沒給 ⇒ 全部遞移（舊規則）。"""
    tests = tmap["tests"]
    report = {"changed": changed, "direct_units": [], "affected_units": [], "graph": graph is not None,
              "need_full": [], "unmapped_changes": [], "reasons": {},
              "rule": "direct+iface" if iface_changed else "transitive", "iface": {}}
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
        if iface_changed is None:
            # 舊規則：沿 imports／routers_called 反向遞移（core:main 是彙整點，不往上傳）
            affected = reverse_closure(seeds, graph) | direct
        else:
            # §C-11a ①②：介面有變 ⇒ 遞移；沒變（只改內部）⇒ 只到直接依賴
            by_unit = {}
            for f in changed:
                by_unit.setdefault(unit_name(f), []).append(f)
            wide = {u for u in seeds if any(iface_changed(f) for f in by_unit.get(u, []))}
            report["iface"] = {u: ("介面有變 ⇒ 遞移" if u in wide else "介面不變 ⇒ 只到直接依賴") for u in sorted(seeds)}
            narrow = direct_dependents(seeds - wide, graph)
            if getattr(iface_changed, "refs", None):
                narrow = name_filter(seeds - wide, narrow, by_unit, graph, iface_changed.refs, report)
            affected = reverse_closure(wide, graph) | narrow | direct
        # 資料表一跳：只加該單位本身＋直接呼叫它的頁面／js，不再沿 import 遞移（否則 archive／trail 會拖進全部）
        hop = table_hop(seeds, graph, conservative, report.get("name_tables")) - affected
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
    if report.get("names") and iface_changed is not None and getattr(iface_changed, "refs", None):
        _test_name_filter(picked, changed, graph, iface_changed.refs, report)
    report["reasons"] = {k: sorted(set(v)) for k, v in sorted(picked.items())}
    return sorted(picked), report


def _test_name_filter(picked, changed, graph, refs, report):
    """§C-11a ③（測試檔）：只因命中「名稱層級的改動單位」而被選中的測試，也看它用了那個單位的哪些名稱——
    沒用到這次被改的名稱 ⇒ 不選（db.py 有 302 個測試檔直接 import 它建測試資料）。
    ⚠ conftest.py 用到被改的名稱（或判斷不了）⇒ 那個單位不過濾：fixture 會經它影響所有測試。"""
    import scope_names as SN
    from dep_scan import helper_reexports
    reexp = helper_reexports()
    scoped = {s: set(ch) for s, ch in report["names"].items() if isinstance(ch, list)}
    conftest = _source("backend/conftest.py", refs[1])
    for s in list(scoped):
        target = SN.dotted(graph.get(s, {}).get("path") or "")
        used = SN.used_names(conftest, target, reexp) if conftest is not None else SN.ALL
        if used is SN.ALL or (used & scoped[s]):
            report.setdefault("names_conftest", {})[s] = "conftest 用到被改的名稱 ⇒ 測試檔不過濾"
            del scoped[s]
    dropped = []
    for t, reasons in list(picked.items()):
        if t in changed or not reasons or not set(reasons) <= set(scoped):
            continue
        src = _source(t, refs[1])
        keepit = src is None
        for s in set(reasons):
            used = SN.used_names(src, SN.dotted(graph[s].get("path") or ""), reexp) if src is not None else SN.ALL
            if used is SN.ALL or not used or used & scoped[s]:
                keepit = True
        if not keepit:
            dropped.append(t)
            del picked[t]
    report["names_dropped_tests"] = len(dropped)


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
#: 這兩個是**預設值**；實際上限由 full_max_workers()／partial_max_workers() 決定（可用環境變數覆寫，見下）
FULL_MAX_WORKERS = 4
PARTIAL_MAX_WORKERS = 2
#: e2e 每個 worker 各開 headless 瀏覽器＋測試伺服器 ⇒ 記憶體比 CPU 先滿（2026-09-26 13:2x 全部 e2e -n 4 被記憶體不足停掉；
#: 主持修正「e2e 一律 -n 2」）⇒ --full 的 e2e 段另有上限，不跟全量上限走
E2E_MAX_WORKERS = 2
#: 覆寫用的環境變數（2026-09-26 使用者裁示「離開期間可以全速」，CORE-SPEC 使用者裁示表）：
#: 全速時設定、使用者回來後拿掉即恢復——不必改程式。值必須是 1～CPU 數的整數；其他值不採用、說出來、用預設
FULL_ENV = "MOTRIX_FULL_MAX_WORKERS"
PARTIAL_ENV = "MOTRIX_PARTIAL_MAX_WORKERS"
E2E_ENV = "MOTRIX_E2E_MAX_WORKERS"


def _env_cap(name, default):
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        n = int(raw.strip())
    except ValueError:
        n = None
    cpus = os.cpu_count() or 1
    if n is None or n < 1 or n > cpus:
        _say("[modtest] %s=%r 不採用（要 1～%d 的整數）⇒ 用預設 %d" % (name, raw, cpus, default))
        return default
    if n != default:
        _say("[modtest] %s=%d（預設 %d）" % (name, n, default))
    return n


def full_max_workers():
    """全量的 worker 上限：環境變數 MOTRIX_FULL_MAX_WORKERS，沒設（或不合法）⇒ FULL_MAX_WORKERS。每次呼叫現讀。"""
    return _env_cap(FULL_ENV, FULL_MAX_WORKERS)


def e2e_max_workers():
    """--full e2e 段的 worker 上限：環境變數 MOTRIX_E2E_MAX_WORKERS，沒設（或不合法）⇒ E2E_MAX_WORKERS。"""
    return _env_cap(E2E_ENV, E2E_MAX_WORKERS)


def partial_cap(picked, tmap):
    """差異題的 worker 上限：選到的題裡有 e2e ⇒ 取 partial 與 e2e 上限較小者（D 抽查 MT-O1：設 PARTIAL=4 時 e2e 會用 -n 4 跑）。
    e2e 的判定：test_map 的 kind＝e2e；test_map 沒有那一檔時退回看檔名（test_e2e_*）。"""
    cap = partial_max_workers()
    tests = (tmap or {}).get("tests") or {}
    if any((tests.get(t) or {}).get("kind") == "e2e" or Path(t).name.startswith("test_e2e") for t in picked):
        cap = min(cap, e2e_max_workers())
    return cap


def partial_max_workers():
    """差異題的 worker 上限：環境變數 MOTRIX_PARTIAL_MAX_WORKERS，沒設（或不合法）⇒ PARTIAL_MAX_WORKERS。"""
    return _env_cap(PARTIAL_ENV, PARTIAL_MAX_WORKERS)


def _say(msg):
    """印中文提示：被別的程式 import 呼叫時，主控台可能是 cp932／cp950（稽核 B-M1 附帶）⇒ 以 utf-8 寫、壞字取代。"""
    try:
        print(msg)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((msg + "\n").encode("utf-8", errors="replace"))
        sys.stdout.flush()


def cap_workers(extra, limit):
    """extra 裡的 xdist worker 數超過上限 ⇒ 壓到上限並說出來。回傳新的 extra。

    認得的寫法：`-n X`、`-nX`、`-n=X`、`--numprocesses X`、`--numprocesses=X`（稽核 B-M1：原本 `-nauto`、
    `--numprocesses=8` 沒被解析）。`auto`／`logical`／非數字／負數 ⇒ **一律改成上限**（原本 auto 被當成
    「等於上限」而原樣放行 ⇒ 12 核機器開 12 個 worker）。
    """
    out, i = list(extra), 0
    while i < len(out):
        a = out[i]
        val, kind = None, None
        if a in ("-n", "--numprocesses") and i + 1 < len(out):
            val, kind = out[i + 1], "next"
        elif a.startswith("--numprocesses="):
            val, kind = a[len("--numprocesses="):], "long="
        elif a.startswith("-n="):
            val, kind = a[3:], "short="
        elif a.startswith("-n") and len(a) > 2:
            val, kind = a[2:], "short"
        if val is not None:
            if not (val.isdigit() and int(val) <= limit):
                _say("⚠ -n %s 超過 §C-13 上限（或不是具體數字），改為 -n %d" % (val, limit))
                if kind == "next":
                    out[i + 1] = str(limit)
                elif kind == "long=":
                    out[i] = "--numprocesses=%d" % limit
                elif kind == "short=":
                    out[i] = "-n=%d" % limit
                else:
                    out[i] = "-n%d" % limit
            if kind == "next":
                i += 1
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


#: 全量記最慢幾題（IMPROVEMENT-REPORT §4-1：full_results 只有總數，看不出慢在哪）
DURATIONS = 30
#: pytest --durations 的每一行：`12.34s call     backend/tests/test_x.py::test_a[1]`
_DURATION_LINE = re.compile(r"^\s*(\d+(?:\.\d+)?)s\s+(setup|call|teardown)\s+(\S.*?)\s*$")


def parse_durations(out):
    """pytest 輸出裡「slowest N durations」那一段 ⇒ [{"test", "seconds", "phase"}]（照輸出順序）；沒有那一段 ⇒ []。"""
    rows, inside = [], False
    for line in (out or "").splitlines():
        if "slowest" in line and "durations" in line:
            inside = True
            continue
        if not inside:
            continue
        m = _DURATION_LINE.match(line)
        if m:
            rows.append({"test": m.group(3), "seconds": float(m.group(1)), "phase": m.group(2)})
        elif line.startswith("=") or (rows and not line.strip()):
            if rows:
                break
    return rows


def slowest(per_stage, n=DURATIONS):
    """{段別: [durations]} ⇒ 兩段合併、依秒數由大到小取前 n，每筆帶 stage。"""
    allrows = [dict(r, stage=stage) for stage, rows in per_stage.items() for r in rows]
    return sorted(allrows, key=lambda r: -r["seconds"])[:n]


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


def _atomic_write_json(dest, result):
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name("%s.%d.tmp" % (dest.name, os.getpid()))
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, dest)


def write_last_full(result, root=None):
    """原子寫入（同目錄暫存檔 → os.replace）兩處，都在主工作樹 tools/platform/：
    - `full_results/<commit>.json`：依 commit 分檔，儀表板閘門讀這個（2026-09-26：單一檔會被別的 worktree 的全量蓋掉）。
      ⚠ dirty（跑的時候有未 commit 的改動）**不寫**：結果不代表這個 commit，而且會蓋掉同一個 commit 乾淨的綠燈。
    - `.last_full.json`：最近一次（任何 commit、含 dirty），只供人看。
    回傳 per-commit 檔的路徑（沒寫 ⇒ .last_full.json 的路徑）。"""
    base = Path(root or main_worktree_root()) / "tools" / "platform"
    latest = base / ".last_full.json"
    _atomic_write_json(latest, result)
    sha = result.get("commit") or ""
    if result.get("dirty") or not re.fullmatch(r"[0-9a-f]{40}", sha):
        return latest
    per = base / "full_results" / (sha + ".json")
    # 稽核 B-S4：同一個 commit 重跑時保留先前每一輪的摘要——偶發紅之後重跑一次綠，閘門照樣放行（以最新一輪為準），
    # 但看得到「這個 commit 曾經紅過」（〈偶發失敗先當產品競態〉）。
    history = []
    if per.is_file():
        try:
            prev = json.loads(per.read_text(encoding="utf-8"))
            history = list(prev.get("history") or []) + [_run_summary(prev)]
        except (OSError, ValueError):
            history = [{"unreadable": True}]
    _atomic_write_json(per, dict(result, history=history))
    return per


def _run_summary(r):
    e2e = r.get("e2e") or {}
    return {"started": r.get("started"), "finished": r.get("finished"), "ok": r.get("ok"),
            "interrupted": r.get("interrupted"), "failed": r.get("failed"), "e2e_failed": e2e.get("failed")}


def _now():
    from datetime import datetime
    return datetime.now().astimezone().isoformat(timespec="seconds")


def tree_state(repo=None):
    """(HEAD, 工作樹狀態)。狀態**含未追蹤檔**（gitignored 的照樣排除）——稽核 B-M3：原本 `--untracked-files=no`，
    忘了 git add 的產品檔、未追蹤的測試／conftest 外掛都會影響一輪全量，卻記成 dirty=false。"""
    def g(*args):
        return subprocess.run(["git", "-C", str(repo or REPO), *args], capture_output=True, text=True,
                              encoding="utf-8", check=True).stdout
    return g("rev-parse", "HEAD").strip(), g("status", "--porcelain", "--untracked-files=normal")


def run_dirty(start, end):
    """這一輪全量能不能代表 start 的 commit：開跑時不乾淨、或跑到一半 HEAD／工作樹變了 ⇒ dirty（稽核 B-M3）。"""
    (h0, s0), (h1, s1) = start, end
    return bool(s0.strip()) or h0 != h1 or s0 != s1


def run_full(extra, a):
    """全量＝兩段：非 e2e（-n workers）＋ e2e（-n e2e-workers）。結果（含失敗、中斷）一律寫進主工作樹（write_last_full：full_results/<commit>.json＋.last_full.json）。
    dirty：開跑與結束各取一次 tree_state()，由 run_dirty() 判定。"""
    start = tree_state()
    result = {
        "commit": start[0],
        "branch": git("rev-parse", "--abbrev-ref", "HEAD").strip(),
        "dirty": run_dirty(start, start),
        "started": _now(), "finished": None,
        "passed": None, "failed": None, "errors": None, "skipped": None,
        "e2e": None, "ok": False, "interrupted": False,
        "python": PYEXE or sys.executable,
        "python_version": subprocess.run([PYEXE or sys.executable, "-c", "import sys;print(sys.version.split()[0])"],
                                         capture_output=True, text=True).stdout.strip(),
    }
    cap = full_max_workers()
    stages = [("main", cap_workers(["-m", "not e2e", "-n", str(a.workers)], cap), a.window),
              ("e2e", cap_workers(["-m", "e2e", "-n", str(a.e2e_workers)], e2e_max_workers()), a.window + "e2e")]
    extra = cap_workers(extra, cap)
    want_durations = getattr(a, "durations", True)
    if want_durations:
        extra = extra + ["--durations=%d" % DURATIONS]
    codes, per_stage = {}, {}
    try:
        for name, args, window in stages:
            code, out = run_pytest(TEST_ROOTS, args + extra, window, full=True)
            codes[name] = code
            if want_durations:
                per_stage[name] = parse_durations(out)
                result["slowest"] = slowest(per_stage)
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
            end = tree_state()
            if run_dirty(start, end) and not result["dirty"]:
                print("[全量結果] ⚠ 跑到一半 HEAD 或工作樹變了（%s → %s）⇒ 記為 dirty，不代表這個 commit"
                      % (start[0][:8], end[0][:8]))
            result["dirty"] = run_dirty(start, end)
            result["head_at_end"] = end[0]
        except Exception as e:                      # noqa: BLE001 — 判不出來 ⇒ 當成 dirty（寧可擋）
            print("[全量結果] ⚠ 結束時讀不到工作樹狀態：%r ⇒ 記為 dirty" % e)
            result["dirty"] = True
        try:
            dest = write_last_full(result)
            print("[全量結果] %s ok=%s → %s" % (result["commit"][:8], result["ok"], dest))
        except Exception as e:                      # noqa: BLE001 — 寫不出結果檔要說出來，不可靜默
            print("[全量結果] ⚠ 寫不出全量結果檔：%r" % e)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--base")
    g.add_argument("--commit")
    g.add_argument("--changed-since", metavar="SHA", help="SHA 之後（不含）到 HEAD 的已提交改動")
    g.add_argument("--files", nargs="+")
    g.add_argument("--rebase-check", metavar="GREEN", help="§C-11：全量綠在 GREEN，rebase 到 --onto 之後該跑哪些題（只判定、不執行；永遠不建議各線跑全量，§G3）")
    ap.add_argument("--onto", default="origin/platform", help="--rebase-check 的 rebase 目標（預設 origin/platform）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--full", action="store_true", help="全量（非 e2e＋e2e 兩段）；結果寫主工作樹 tools/platform/full_results/<commit>.json（dirty 不寫）＋.last_full.json")
    _full = full_max_workers()
    ap.add_argument("--workers", type=int, default=_full,
                    help="--full 非 e2e 段的 xdist worker 數（上限 %d，§C-13；%s 可覆寫）" % (_full, FULL_ENV))
    _e2e = e2e_max_workers()
    ap.add_argument("--e2e-workers", type=int, default=_e2e,
                    help="--full e2e 段的 xdist worker 數（上限 %d，§C-13；%s 可覆寫）" % (_e2e, E2E_ENV))
    ap.add_argument("--refresh-map", action="store_true", help="（已是預設：現場算 test_map 與 dep_graph；保留相容，無作用）")
    ap.add_argument("--use-files", action="store_true",
                    help="讀已提交的 test_map.json／dep_graph.json，不現場算（除錯用；分支上的檔是 origin 版，會漏題）")
    ap.add_argument("--no-durations", dest="durations", action="store_false",
                    help="--full 不記最慢 %d 題（預設會記，寫進 full_results/<commit>.json 的 slowest）" % DURATIONS)
    ap.add_argument("--window", default="modtest")
    ap.add_argument("--python", help="指定跑 pytest 的直譯器（預設：主工作樹的專案 .venv）")
    ap.add_argument("--json", action="store_true", help="dry-run 以 JSON 輸出")
    ap.add_argument("--list", action="store_true", help="dry-run 另列每個測試檔與原因")
    ap.add_argument("--transitive", action="store_true", help="舊規則：改動單位一律沿反向 import 遞移擴散（預設：介面沒變只到直接依賴，§C-11a）")
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
        return 2 if not r["rebased"] else (3 if r["high_impact"] else 0)   # 3＝影響大（差異題擴大＋月台註明），不是「跑全量」
    global PYEXE
    PYEXE = resolve_python(a.python)

    if a.full:
        if a.dry_run:
            per, tail = collect_per_file(a.window)
            print("全量：%s 題（%s）" % (sum(per.values()) if per is not None else None, tail))
            return 0
        return run_full(extra, a)

    changed = changed_files(a)
    tmap = load_map(a.use_files)
    graph = load_graph(a.use_files)
    t0 = time.monotonic()
    picked, rep = select(changed, tmap, graph, None if a.transitive else iface_checker(a))

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
            print("⚠ 改到 fixture 層（%s）⇒ 差異題照跑（另帶 tests/platform）＋改到頁面的 e2e；**不要自己跑全量**："
                  "全量交給列車（PLAYBOOK §G3），月台登記註明 fixture 層、排在列車最前面" % ", ".join(rep["need_full"]))
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
        record_stats(changed, picked, tmap, rep, n_items, full_n, None, dry_run=True)
        return 0
    if not picked:
        print("沒有受影響的測試。")
        return 3 if rep["need_full"] else 0
    code, _ = run_pytest(picked, cap_workers(extra, partial_cap(picked, tmap)), a.window, full=False)
    record_stats(changed, picked, tmap, rep, None, None, time.monotonic() - t0, dry_run=False, exit_code=code)
    if code == 0 and rep["need_full"]:
        return 3          # 閘門過了，但動到 fixture 層：月台要註明、排車頭（全量由列車跑，§G3）
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
