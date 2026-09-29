"""範圍驗證閘門（PLAYBOOK §D-1a；使用者 2026-09-30：「如果未影響到底層，審核測試上包可由獨立模組，不需要跑全域」）。

正式機基準 P（要打包的 commit X 上 backend/tests/_prod_baseline.py 的 BASELINE）→ X 的改動檔**一個都不在底層**
（底層清單唯一來源：tools/platform/bottom_layer.json）⇒ 出包接受「這個 commit 的範圍驗證綠燈」代替全量；
任何一個在底層（或判不了）⇒ 照舊要全量。

用法（repo 根目錄；python＝主工作樹 .venv312）：
  python tools/platform/scope_gate.py plan  [--commit X] [--json]   判定＋選題（不跑）
  python tools/platform/scope_gate.py run   [--window W]            在乾淨的 HEAD 上跑範圍驗證，結果寫
                                                                      主工作樹 tools/platform/full_results/scoped/<X>.json
  python tools/platform/scope_gate.py gate  [--commit X] [--json]   閘門判定：接受 ⇒ exit 0；不接受 ⇒ exit 3

範圍驗證＝modtest --train 同型：改動模組的題（遞移選題，不用名稱層級縮小——閘門寧寬）＋改到的提供者的消費端
（ship_tier.provider_check）＋改到頁面的 e2e＋tests/platform 全部（MOTRIX_TRAIN=1，「是否最新」三題不可以被 skip）
＋規則附帶的題（bottom_layer.json 的 tests）。非 e2e、e2e 兩段都要綠。

閘門（gate）**現場重算**判定，不相信紀錄自己寫的 mode：紀錄的 commit、基準、模組集合都要與現場一致；
基準讀不到、不是 X 的祖先、提供者的消費端判不了 ⇒ 不接受（fail closed）。
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

CONFIG = HERE / "bottom_layer.json"
BASELINE_REL = "backend/tests/_prod_baseline.py"
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


def load_rules(path=CONFIG, pages=None):
    """bottom_layer.json ⇒ [{"pattern", "layer", "why", "tests", "re"}]（照檔案順序）。格式不對 ⇒ ValueError（不猜）。"""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("format") != FORMAT or not isinstance(raw.get("rules"), list) or not raw["rules"]:
        raise ValueError("bottom_layer.json 格式不對（format=%r）" % raw.get("format"))
    pages = pages if pages is not None else pages_rel()
    rules = []
    for r in raw["rules"]:
        if r.get("layer") not in LAYERS or not r.get("pattern") or not r.get("why"):
            raise ValueError("bottom_layer.json 規則不完整：%r" % r)
        pat = r["pattern"].replace("{PAGES}", pages)
        rules.append(dict(r, pattern=pat, tests=list(r.get("tests") or []), re=glob_re(pat)))
    return rules


def config_sha256(path=CONFIG):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


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


def judge(record, commit, base, decision):
    """閘門判定（純函式）⇒ (accepted, detail)。record＝範圍驗證紀錄（None＝沒有）；commit／base＝完整 SHA；
    decision＝現場重算的 decide()（含提供者檢查）。任何一項對不上 ⇒ 不接受。"""
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
    return True, "這一包沒有動到底層；範圍驗證全綠（模組：%s）" % ("、".join(decision["modules"]) or "無，只有文件／紀錄")


# ── git 與選題 ──────────────────────────────────────────────────────────────

def _git(*args, repo=REPO, check=True):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError("git %s 失敗：%s" % (" ".join(args), (r.stderr or r.stdout).strip()))
    return r.stdout


def rev(ref, repo=REPO):
    return _git("rev-parse", "--verify", ref + "^{commit}", repo=repo).strip()


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


def is_ancestor(a, b, repo=REPO):
    return subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", a, b],
                          capture_output=True).returncode == 0


def assess(commit="HEAD", repo=REPO, rules=None):
    """P→X 現場判定 ⇒ {"commit", "base", "files", "decision", "consumers"}。判不了的一律讓 decision.mode＝full。"""
    import ship_tier as ST
    commit = rev(commit, repo)
    base = baseline_at(commit, repo)
    out = {"commit": commit, "base": base, "files": [], "consumers": [], "decision": None}
    if not base or not is_ancestor(base, commit, repo):
        why = "讀不到正式機基準（%s）" % BASELINE_REL if not base else "正式機基準 %s 不是 %s 的祖先" % (base[:8], commit[:8])
        out["decision"] = {"mode": "full", "bottom": [[BASELINE_REL, why]], "modules": [], "categories": {},
                           "extra_tests": []}
        return out
    files = [f for f in _git("diff", "--name-only", "--no-renames", base, commit, repo=repo).splitlines() if f]
    pages = ST.pages_at(base, repo)
    for k, v in ST.pages_at(commit, repo).items():
        pages[k] = pages.get(k, set()) | v
    d = decide(files, rules if rules is not None else load_rules(), pages)
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


def gate(commit="HEAD", repo=REPO, rdir=None):
    """⇒ {"accepted", "mode", "detail", "record_present", "commit", "base", "units", "tests", "record_path"}。
    先看紀錄檔在不在（便宜）：不在 ⇒ 不做 git 判定，直接回不接受（儀表板每次開頁都會呼叫）。"""
    commit = rev(commit, repo)
    rdir = Path(rdir) if rdir else results_dir()
    rec = read_record(rdir, commit)
    res = {"accepted": False, "mode": None, "record_present": rec is not None, "commit": commit, "base": None,
           "units": [], "tests": None, "record_path": str(record_path(rdir, commit))}
    if rec is None:
        res["detail"] = "這個 commit 沒有範圍驗證紀錄（scope_gate.py run）"
        return res
    a = assess(commit, repo)
    ok, detail = judge(rec, commit, a["base"] or "", a["decision"])
    res.update(accepted=ok, mode="scoped" if ok else None, detail=detail, base=a["base"],
               units=a["decision"]["modules"], consumers=a["consumers"], bottom=a["decision"]["bottom"],
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
        print("[scope_gate] 動到底層 ⇒ 這一包必須全量（modtest --full）：")
        for f, w in d["bottom"][:30]:
            print("  ✗ %s：%s" % (f, w))
        return 3
    tests, rep = select_tests(a["files"], a["consumers"], d["extra_tests"])
    print("[scope_gate] 基準 %s → %s；模組 %s；消費端 %d 檔；選題 %d 檔" % (
        a["base"][:8], a["commit"][:8], "、".join(d["modules"]) or "無", len(a["consumers"]), len(tests)))
    rec = {"kind": "scoped", "format": FORMAT, "commit": a["commit"], "base": a["base"],
           "branch": MT.git("rev-parse", "--abbrev-ref", "HEAD").strip(), "units": d["modules"],
           "consumers": a["consumers"], "categories": d["categories"], "tests": tests,
           "config_sha256": config_sha256(), "started": MT._now(), "finished": None, "ok": False,
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
        print("基準 %s → %s：%s" % ((a2["base"] or "?")[:8], a2["commit"][:8],
                                  "範圍驗證可用" if d["mode"] == "scoped" else "必須全量"))
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
