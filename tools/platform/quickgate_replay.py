# -*- coding: utf-8 -*-
"""author_gate --quick 的回放驗收（T87 A2）：拿 T86 的紅燈修復 commit 回放，看 quick 在「作者推送前」抓不抓得到。

用法（repo 根目錄；唯讀 git，不跑 pytest）：
  python tools/platform/quickgate_replay.py [--cases tools/platform/quickgate_replay_cases.json] [--case <名稱> ...] [--json-out <路徑>]

一個案例＝一個紅燈修復 commit（fix）。回放分三步：
  1. 找「弄壞的 commit」（breaker）：案例寫了 breaker 就用；沒寫（kind=stale）就用 pickaxe：
     取 fix 在測試檔刪掉的字面值（舊斷言），`git log -S<字面值> <base>..fix^` 在非測試來源檔找「最後動過它的 commit」。找不到＝這個案例記為「未歸因」，
     算漏抓（不是略過）。
  2. 在 breaker 當時的樹上，用 breaker 自己的 diff 跑 quick 選題（plan_quick）。跑兩次：不限預算（看選題本身的上限）、真實預算
     （author_gate 的歷史秒數／題數×0.75 s／e2e 20 s，5 分鐘；看實際會不會被砍）。
  3. 判定：fix 修改的測試檔（或案例寫的 expect_files）有任一個在 quick 選到要跑的檔（T0–T4 run）裡＝抓到；只在 skipped（未跑）裡＝漏抓。

輸出分兩欄：「預估」＝這支離線選題的命中率（不是真的跑紅）；「實測」＝解除安靜期後在 breaker 樹真的跑 quick 並確認該檔紅（本工具不做，
由 author_gate replay --run 的作法照辦，見設計文件 §驗收）。兩欄不得混報。
已知偏差（h11 S7）：stale 案例的歸因與選題用同一組舊斷言字面值（循環），所以另報：分層直方圖、「只算 T0–T3」的比率、未歸因數、範圍外數；分母一律含範圍外與未歸因。
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

import quick_select as QS  # noqa: E402

DEFAULT_CASES = HERE / "quickgate_replay_cases.json"
TARGET = 0.80


def _git(*args, repo=REPO):
    p = subprocess.run(["git", "-C", str(repo)] + list(args), capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, p.stdout


def is_test(f):
    import guard_patterns as GP
    return GP.is_test_file(f)


def fix_changed_tests(fix, repo=REPO):
    rc, out = _git("show", "--no-renames", "--name-only", "--format=", fix, repo=repo)
    return sorted(f for f in out.split() if is_test(f) and f.endswith(".py")) if rc == 0 else []


def removed_test_literals(fix, repo=REPO, limit=12, only=None):
    """fix 在測試檔『刪掉』的字面值（舊斷言用的字）⇒ 依長度由長到短。only＝只看這個測試檔。"""
    rc, diff = _git("show", "--no-renames", "-U0", "--format=", fix, *(["--", only] if only else []), repo=repo)
    if rc != 0:
        return []
    cur, removed, added = None, [], set()
    for ln in diff.splitlines():
        if ln.startswith("+++ "):
            cur = ln[6:] if ln.startswith("+++ b/") else None
        elif cur and is_test(cur):
            if ln.startswith("-") and not ln.startswith("---"):
                removed.append(ln[1:])
            elif ln.startswith("+") and not ln.startswith("+++"):
                added.add(ln[1:])
    lits = []
    for ln in removed:
        for tok in QS.literals_of([ln]):
            if not any(tok in a for a in added):
                lits.append(tok)
    return sorted(dict.fromkeys(lits), key=lambda t: -len(t))[:limit]


def find_breakers(fix, base, repo=REPO, literals=None):
    """pickaxe：⇒ [commit]（動過那些字面值的非測試來源檔的 commit，近的在前，去重）。"""
    found = []
    for lit in literals if literals is not None else removed_test_literals(fix, repo):
        rc, out = _git("log", "--no-merges", "--format=%h", "-S" + lit, "%s..%s^" % (base, fix), "--", ":(exclude)backend/**/tests/**", ":(exclude)backend/tests/**", repo=repo)
        if rc == 0:
            found += [h for h in out.split() if h not in found]
        if len(found) >= 3:
            break
    return found[:3]


def approx_breakers(f, fix, base, repo=REPO, limit=3):
    """pickaxe 找不到時的近似歸因（行為改變型：舊斷言不是文字，而是頁面／路由行為變了）：
    這個測試檔（fix 之前的版本）引用了哪些頁面／前端 js 檔名，base..fix^ 之間最近動過那些檔的 commit。
    **近似**：這個關聯與 quick 的 T4 選題用的是同一種（檔名引用），所以抓得到幾乎是循環；結果只能分開報，不能當成確證，真值以解凍後實跑為準。"""
    import re
    rc, src = _git("show", "%s^:%s" % (fix, f), repo=repo)
    if rc != 0:
        return []
    names = sorted({n for n in re.findall(r"[A-Za-z0-9_\-]+\.(?:html|js)", src) if n not in QS.GENERIC_NAMES})
    found = []
    for n in names:
        rc, out = _git("log", "--no-merges", "--format=%h", "-3", "%s..%s^" % (base, fix), "--", ":(glob)frontend/**/" + n, repo=repo)
        if rc == 0:
            found += [h for h in out.split() if h not in found]
    return found[:limit]


def plan_for(breaker, repo=REPO, real=False):
    """real=False：預算放大到不砍（看選題本身的上限）；real=True：author_gate 的真實秒數（歷史／題數×0.75 s；e2e 20 s）＋真實 5 分鐘預算。"""
    import author_gate as AG
    rc, names = _git("diff", "--no-renames", "--name-only", breaker + "^", breaker, repo=repo)
    changed = [f for f in names.splitlines() if f]
    rc, gone = _git("diff", "--no-renames", "--name-only", "--diff-filter=D", breaker + "^", breaker, repo=repo)
    deleted = [f for f in gone.splitlines() if f]
    rc, diff = _git("diff", "--no-renames", "-U0", breaker + "^", breaker, repo=repo)
    rc, tree = _git("ls-tree", "-r", "--name-only", breaker, repo=repo)
    tree_files = tree.splitlines()
    a2 = AG.pattern_files(tree_files, AG.PATTERNS)
    a4 = sorted(f for f in changed if is_test(f) and f.endswith(".py") and f not in deleted)
    if real:
        times = AG.load_times()
        secs = lambda f: AG.E2E_FILE_SECONDS if "test_e2e_" in f.rsplit("/", 1)[-1] else AG.file_seconds(f, times, repo)      # noqa: E731
        budget = 5 * 60
    else:
        secs, budget = (lambda f: 5.0), 10 ** 9
    return QS.plan_quick(changed=changed, deleted=deleted, diff_text=diff, tree_files=tree_files, a2=a2, a4=a4, extra_t4=[], repo=str(repo), ref=breaker,
                         seconds_fn=secs, workers=2, budget_s=budget)


_PLANS = {}


def _plan_cached(b, repo, real=False):
    if (b, real) not in _PLANS:
        _PLANS[(b, real)] = plan_for(b, repo, real)
    return _PLANS[(b, real)]


def _first_tier(breakers, files, repo, real):
    """⇒ (tier, breaker, 命中檔) 或 None：所有 breaker 的選題裡最早的層。"""
    best = None
    for b in breakers:
        plan = _plan_cached(b, repo, real)
        for tier in ("T0", "T1", "T2", "T3", "T4"):
            t = plan["tiers"][tier]
            run = t.get("run", t["files"]) if tier == "T4" else t["files"]
            hit = [f for f in files if f in run]
            if hit:
                if best is None or tier < best[0]:
                    best = (tier, b, hit)
                break
    return best


def evaluate_stale(case, base, repo=REPO):
    """過期斷言類：逐個被 fix 改的測試檔各自歸因（各自的舊斷言字面值→pickaxe→breaker），各自判定 quick 有沒有選到它。⇒ 每檔一列。
    歸因與選題用同一組字面值（循環），所以另報未歸因數、分層與真實預算下的結果。"""
    fix = case["fix"]
    files = case.get("expect_files") or fix_changed_tests(fix, repo)
    rows = []
    for f in files:
        breakers = find_breakers(fix, base, repo, literals=removed_test_literals(fix, repo, only=f))
        how = "pickaxe" if breakers else None
        if not breakers:
            breakers = approx_breakers(f, fix, base, repo)
            how = "page-ref" if breakers else None
        best = _first_tier(breakers, [f], repo, False)
        best_real = _first_tier(breakers, [f], repo, True)
        rows.append({"file": f, "breakers": breakers, "caught": bool(best), "tier": best[0] if best else None, "breaker": best[1] if best else None,
                     "caught_real": bool(best_real), "tier_real": best_real[0] if best_real else None, "attributed": bool(breakers), "attribution": how,
                     "why": "" if best else ("未歸因（pickaxe 與檔名引用都找不到弄壞的 commit）" if not breakers else "選題沒有包含這個測試檔")})
    return {"name": case["name"], "fix": fix, "kind": "stale", "scope": case.get("scope", "in"), "reason": case.get("reason", ""), "items": rows,
            "caught": sum(1 for r in rows if r["caught"]), "total": len(rows)}


def evaluate(case, base, repo=REPO):
    if case.get("kind", "stale") == "stale" and not case.get("breaker"):
        return evaluate_stale(case, base, repo)
    fix = case["fix"]
    expect = case.get("expect_files") or fix_changed_tests(fix, repo)
    breakers = case.get("breaker")
    breakers = [breakers] if isinstance(breakers, str) else breakers
    attributed = "explicit"
    if not breakers:
        breakers, attributed = find_breakers(fix, base, repo), "pickaxe"
    res = {"name": case["name"], "fix": fix, "kind": case.get("kind", "stale"), "expect": expect, "breakers": breakers, "attribution": attributed if breakers else "none",
           "scope": case.get("scope", "in"), "reason": case.get("reason", "")}
    if not breakers or not expect:
        res.update(caught=False, caught_real=False, why="未歸因（找不到弄壞的 commit）" if not breakers else "沒有可比對的測試檔", tier=None, tier_real=None)
        return res
    best, best_real = _first_tier(breakers, expect, repo, False), _first_tier(breakers, expect, repo, True)
    res.update(caught=bool(best), tier=best[0] if best else None, caught_real=bool(best_real), tier_real=best_real[0] if best_real else None)
    if best:
        res.update(breaker=best[1], hit=best[2])
    else:
        res.update(why="選題沒有包含預期測試檔")
    return res


def _units(row):
    """⇒ [{caught, caught_real, tier, tier_real, attributed}]：stale 案例逐檔一列；rule 案例一列。"""
    if "items" in row:
        return row["items"]
    return [{"caught": row["caught"], "caught_real": row.get("caught_real", False), "tier": row.get("tier"), "tier_real": row.get("tier_real"),
             "attributed": bool(row.get("breakers")), "attribution": row.get("attribution")}]


def tally(row):
    """⇒ (抓到數, 總數)（不限預算的選題）。"""
    u = _units(row)
    return sum(1 for x in u if x["caught"]), len(u)


def summarize(rows):
    """⇒ 彙總 dict：不限預算／真實預算／只算 T0–T3 的抓到數與比率、分層直方圖、未歸因數、範圍外數。以測試檔為單位，分母含範圍外與未歸因。"""
    units = [(x, r["scope"]) for r in rows for x in _units(r)]
    n = len(units)
    by_tier, by_tier_real = {}, {}
    for x, _s in units:
        if x["tier"]:
            by_tier[x["tier"]] = by_tier.get(x["tier"], 0) + 1
        if x.get("tier_real"):
            by_tier_real[x["tier_real"]] = by_tier_real.get(x["tier_real"], 0) + 1
    unb = sum(1 for x, _ in units if x["caught"])
    real = sum(1 for x, _ in units if x.get("caught_real"))
    t03 = sum(1 for x, _ in units if x.get("tier_real") in ("T0", "T1", "T2", "T3"))
    scoped = [(x, s) for x, s in units if s != "out"]
    return {"total": n, "caught_unbounded": unb, "caught_real_budget": real, "caught_t0_t3_only": t03, "by_tier": by_tier, "by_tier_real_budget": by_tier_real,
            "unattributed": sum(1 for x, _ in units if not x.get("attributed", True)),
            "caught_real_budget_strict": sum(1 for x, _ in units if x.get("caught_real") and x.get("attribution") != "page-ref"),
            "approx_attributed": sum(1 for x, _ in units if x.get("attribution") == "page-ref"),
            "approx_caught_real_budget": sum(1 for x, _ in units if x.get("caught_real") and x.get("attribution") == "page-ref"), "out_of_scope": n - len(scoped),
            "scoped_total": len(scoped), "scoped_caught_real_budget": sum(1 for x, _ in scoped if x.get("caught_real")),
            "rate_unbounded": unb / n if n else 0.0, "rate_real_budget": real / n if n else 0.0, "rate_t0_t3_only": t03 / n if n else 0.0}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=str(DEFAULT_CASES))
    ap.add_argument("--case", action="append", default=[])
    ap.add_argument("--json-out")
    a = ap.parse_args(argv)
    spec = json.loads(Path(a.cases).read_text(encoding="utf-8"))
    base = spec.get("base", "558352168")
    cases = [c for c in spec["cases"] if not a.case or c["name"] in a.case]
    rows = [evaluate(c, base) for c in cases]
    for r in rows:
        c, t = tally(r)
        print("%s %-42s %d/%d" % ("✓" if c == t and t else "✗", r["name"], c, t))
        for it in r.get("items", []):
            print("      %s %-4s(真實預算 %-4s) %s %s" % ("✓" if it["caught"] else "✗", it["tier"] or "--", it["tier_real"] or "--", it["file"].rsplit("/", 1)[-1][:52], it["why"]))
        if "items" not in r:
            print("      %s（真實預算 %s） %s %s" % (r.get("tier") or "--", r.get("tier_real") or "--", ",".join(r.get("hit", []))[:60], r.get("why", "")))
        if r["scope"] == "out":
            print("      範圍外：%s" % r["reason"])
    sm = summarize(rows)
    print("預估（離線選題，未真的跑紅；以測試檔為單位，分母含範圍外與未歸因）：")
    print("  不限預算 %d/%d＝%.0f%%；真實 5 分鐘預算（歷史秒數／題數×0.75 s／e2e 20 s）%d/%d＝%.0f%%；只算 T0–T3（不靠 T4）%d/%d＝%.0f%%（目標 ≥%d%%）"
          % (sm["caught_unbounded"], sm["total"], sm["rate_unbounded"] * 100, sm["caught_real_budget"], sm["total"], sm["rate_real_budget"] * 100,
             sm["caught_t0_t3_only"], sm["total"], sm["rate_t0_t3_only"] * 100, TARGET * 100))
    print("  其中嚴格歸因（pickaxe／案例明寫 breaker）抓到 %d；近似歸因（檔名引用，循環，不當確證）%d 個、其中抓到 %d"
          % (sm["caught_real_budget_strict"], sm["approx_attributed"], sm["approx_caught_real_budget"]))
    print("  抓到的分層（不限預算）%s；（真實預算）%s；未歸因 %d；範圍外 %d" % (sm["by_tier"], sm["by_tier_real_budget"], sm["unattributed"], sm["out_of_scope"]))
    print("  離線 T4 只含「引用改動檔名／打改動路由」的選題，不含 author_gate 的改動模組自己的測試與 e2e 選題（實跑只會更多）。實測：尚未執行（安靜期結束後）")
    if a.json_out:
        Path(a.json_out).write_text(json.dumps({"estimate": sm, "measured": None, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if sm["rate_real_budget"] >= TARGET else 1          # 以真實預算＋「全部」分母為準（範圍外與未歸因也算漏）


if __name__ == "__main__":
    sys.exit(main())
