# -*- coding: utf-8 -*-
"""author_gate --quick 的回放驗收（T87 A2）：拿 T86 的紅燈修復 commit 回放，看 quick 在「作者推送前」抓不抓得到。

用法（repo 根目錄；唯讀 git，不跑 pytest）：
  python tools/platform/quickgate_replay.py [--cases tools/platform/quickgate_replay_cases.json] [--case <名稱> ...] [--json-out <路徑>]

一個案例＝一個紅燈修復 commit（fix）。回放分三步：
  1. 找「弄壞的 commit」（breaker）：案例寫了 breaker 就用；沒寫（kind=stale）就用 pickaxe：
     取 fix 在測試檔刪掉的字面值（舊斷言），`git log -S<字面值> <base>..fix^` 在非測試來源檔找「最後動過它的 commit」。找不到＝這個案例記為「未歸因」，
     算漏抓（不是略過）。
  2. 在 breaker 當時的樹上，用 breaker 自己的 diff 跑 quick 選題（plan_quick，預算放大到不砍，避免用預算偷掉分母；被砍的另計）。
  3. 判定：fix 修改的測試檔（或案例寫的 expect_files）有任一個在 quick 選到要跑的檔（T0–T4 run）裡＝抓到；只在 skipped（未跑）裡＝漏抓。

輸出分兩欄：「預估」＝這支離線選題的命中率（不是真的跑紅）；「實測」＝解除安靜期後用 --run 真的在 breaker 樹跑 quick 並確認該檔紅（本版未實作 --run，
由 author_gate replay --run 的作法照辦，見設計文件 §驗收）。兩欄不得混報。
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


def plan_for(breaker, repo=REPO):
    import author_gate as AG
    rc, names = _git("diff", "--no-renames", "--name-only", breaker + "^", breaker, repo=repo)
    changed = [f for f in names.splitlines() if f]
    rc, diff = _git("diff", "--no-renames", "-U0", breaker + "^", breaker, repo=repo)
    rc, tree = _git("ls-tree", "-r", "--name-only", breaker, repo=repo)
    tree_files = tree.splitlines()
    a2 = AG.pattern_files(tree_files, AG.PATTERNS)
    a4 = sorted(f for f in changed if is_test(f) and f.endswith(".py"))
    return QS.plan_quick(changed=changed, diff_text=diff, tree_files=tree_files, a2=a2, a4=a4, extra_t4=[], repo=str(repo), ref=breaker,
                         seconds_fn=lambda f: 5.0, workers=2, budget_s=10 ** 9)


_PLANS = {}


def _plan_cached(b, repo):
    if b not in _PLANS:
        _PLANS[b] = plan_for(b, repo)
    return _PLANS[b]


def _selected_tier(plan, f):
    for tier in ("T0", "T1", "T2", "T3", "T4"):
        t = plan["tiers"][tier]
        run = t.get("run", t["files"]) if tier == "T4" else t["files"]
        if f in run:
            return tier
    return None


def evaluate_stale(case, base, repo=REPO):
    """過期斷言類：逐個被 fix 改的測試檔各自歸因（各自的舊斷言字面值→pickaxe→breaker），各自判定 quick 有沒有選到它。⇒ 每檔一列。"""
    fix = case["fix"]
    files = case.get("expect_files") or fix_changed_tests(fix, repo)
    rows = []
    for f in files:
        breakers = find_breakers(fix, base, repo, literals=removed_test_literals(fix, repo, only=f))
        tier, by = None, None
        for b in breakers:
            tier = _selected_tier(_plan_cached(b, repo), f)
            if tier:
                by = b
                break
        rows.append({"file": f, "breakers": breakers, "caught": bool(tier), "tier": tier, "breaker": by,
                     "why": "" if tier else ("未歸因（pickaxe 找不到弄壞的 commit）" if not breakers else "選題沒有包含這個測試檔")})
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
        res.update(caught=False, why="未歸因（找不到弄壞的 commit）" if not breakers else "沒有可比對的測試檔", tier=None)
        return res
    best = None
    for b in breakers:
        plan = plan_for(b, repo)
        for tier in ("T0", "T1", "T2", "T3", "T4"):
            t = plan["tiers"][tier]
            run = t.get("run", t["files"]) if tier == "T4" else t["files"]
            hit = [f for f in expect if f in run]
            if hit:
                if best is None or tier < best[0]:
                    best = (tier, b, hit)
                break
    if best:
        res.update(caught=True, tier=best[0], breaker=best[1], hit=best[2])
    else:
        res.update(caught=False, tier=None, why="選題沒有包含預期測試檔")
    return res


def tally(row):
    """⇒ (抓到數, 總數)：stale 案例逐檔計；rule 案例 1 或 0（沒有預期檔也算 1 個漏抓）。"""
    if "items" in row:
        return row["caught"], row["total"]
    return (1 if row["caught"] else 0), 1


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
            print("      %s %-4s %s %s" % ("✓" if it["caught"] else "✗", it["tier"] or "--", it["file"].rsplit("/", 1)[-1][:58], it["why"]))
        if "items" not in r:
            print("      %s %s %s" % (r.get("tier") or "--", ",".join(r.get("hit", []))[:60], r.get("why", "")))
        if r["scope"] == "out":
            print("      範圍外：%s" % r["reason"])
    tot = [tally(r) for r in rows]
    caught, total = sum(c for c, _ in tot), sum(t for _, t in tot)
    sc_t = [tally(r) for r in rows if r["scope"] != "out"]
    sc, stot = sum(c for c, _ in sc_t), sum(t for _, t in sc_t)
    rate, srate = (caught / total if total else 0.0), (sc / stot if stot else 0.0)
    print("預估（離線選題，未真的跑紅；以測試檔為單位）：全部 %d/%d＝%.0f%%；範圍內 %d/%d＝%.0f%%（目標 ≥%d%%）；實測：尚未執行（安靜期結束後）"
          % (caught, total, rate * 100, sc, stot, srate * 100, TARGET * 100))
    if a.json_out:
        Path(a.json_out).write_text(json.dumps({"estimate": {"caught": caught, "total": total, "rate": rate, "scoped_caught": sc, "scoped_total": stot, "scoped_rate": srate},
                                                "measured": None, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if rate >= TARGET else 1          # 以「全部」分母為準（範圍外也算漏）


if __name__ == "__main__":
    sys.exit(main())
