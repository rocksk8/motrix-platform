# -*- coding: utf-8 -*-
"""建包優化項 3：離線重放（只讀 git＋fail_stream 摘要，不執行任何測試）。

把 BUILD-OPT-ITEM3-INCREMENTAL-DESIGN.md §3／§4 的重放固化成可重複的工具：
輸入一份列（JSON）：[{"id","stage","variant","base","head","actual_minutes","red_files","base_red_files","recall_base"}]
  stage            not_e2e | e2e
  base / head      基準 commit（null＝沒有可用基準 ⇒ 全量）／這一段建包的 commit
  actual_minutes   該段實際分鐘（[實測]）
  red_files        這一段實際紅的檔（nodeid 或檔路徑；召回用）
  base_red_files   基準那一段紅的檔（紅重選用）
  recall_base      召回用的基準（缺 ⇒ 用 base；供「base＝null」的首輪以正式機基準算召回）
每列以 stage_select.plan_stage 計畫（M 分層：只有硬底層⇒全量）估計增量分鐘；S 分層＝現行 scope_gate（底層⇒全量）。

耗時模型 [推論]（design §3.1）：每檔秒數＝fail_stream summary 的 slowest_files 中位數（有的話），否則 題數×係數×0.60 s（e2e 3.3 s）；
題數＝該 commit 上靜態計 `def test_`，乘校正係數（對齊收集 8022／754）；段牆鐘＝開銷（20／30 s）＋ worker‑秒／4。

用法：
  python tools/platform/replay_incremental.py tools/platform/replay_rows_t29_t30.json [--json out.json]
         [--fail-stream-dir D:/MOTRIX-PLATFORM/tools/platform/fail_stream] [--legacy-floor] [--release-ids t29f,t30f]
"""
import argparse
import collections
import glob
import json
import re
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import stage_select as SS  # noqa: E402

WORKERS = 4
OVERHEAD_S = {"not_e2e": 20.0, "e2e": 30.0}
PER_TEST_S = {"not_e2e": 0.60, "e2e": 3.3}
COLLECTED_REF = {"not_e2e": 8022, "e2e": 754}          # 對齊的實際收集題數（design §3.1）
FAIL_STREAM_DIR = "D:/MOTRIX-PLATFORM/tools/platform/fail_stream"
FAIL_STREAM_GLOB = "build_2026100[12]_*.jsonl"
#: 設計文件 §3.2 合計（分鐘）：版本 ⇒ (兩班建議後, 省)；用來對照本工具的重放
DOC_TOTALS = {"B·M": (204.3, 91.8), "A·M": (219.6, 76.5), "B·S": (261.3, 34.8), "A·S": (296.1, 0.0),
              "B·M·release-full": (None, 52.1)}
DOC_ACTUAL_TOTAL = 296.1
DOC_RECALL = (24, 26)       # §4.2：未補掃目錄型前 24／26；補 F0d 後 25／26


def load_file_seconds(dirpath=FAIL_STREAM_DIR, pattern=FAIL_STREAM_GLOB):
    """fail_stream 的完整跑 summary（passed≥7000 的非 e2e 段，或任何 e2e 段）⇒ {(repo 相對檔, stage): (中位秒, 題數)}。"""
    sec = collections.defaultdict(list)
    for f in glob.glob(str(Path(dirpath) / pattern)):
        for line in open(f, encoding="utf-8", errors="replace"):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") != "summary":
                continue
            if d.get("stage") == "not_e2e" and d.get("passed", 0) < 7000:
                continue
            for x in d.get("slowest_files", []):
                sec[("backend/" + x["file"], d.get("stage"))].append((x["seconds"], x["tests"]))
    return {k: (statistics.median(a for a, _ in v), v[0][1]) for k, v in sec.items()}


def static_counts(reader, tmap):
    """該 commit 的測試檔 ⇒ {(檔, stage): 靜態題數}。e2e 類的混合檔（同時有非 e2e 題）依 `mark.e2e` 數拆到兩段。"""
    out = {}
    for stage in SS.STAGES:
        files, _, _ = SS.collect_files(tmap, reader.tree(), reader, stage)
        got = reader.read_many(sorted(files))
        for f, b in got.items():
            src = (b or b"").decode("utf-8", "replace")
            n = len(re.findall(r"^\s*(?:async\s+)?def test_", src, re.M))
            if tmap["tests"].get(f, {}).get("kind") == "e2e" and SS.is_mixed_e2e(src):
                m = len(re.findall(r"mark\.e2e", src))
                n = max(0, n - m) if stage == "not_e2e" else m
            out[(f, stage)] = n
    return out


class CostModel:
    def __init__(self, counts, known):
        self.counts, self.known = counts, known
        tot = collections.Counter()
        for (f, st), n in counts.items():
            tot[st] += n
        self.scale = {s: COLLECTED_REF[s] / tot[s] if tot[s] else 1.0 for s in SS.STAGES}

    def tests(self, f, stage):
        return self.counts.get((f, stage), 0) * self.scale[stage]

    def seconds(self, f, stage):
        if (f, stage) in self.known:
            return self.known[(f, stage)][0]
        return self.tests(f, stage) * PER_TEST_S[stage]

    def cost(self, files, stage):
        return sum(self.tests(f, stage) for f in files), sum(self.seconds(f, stage) for f in files)


def short(reasons, n=60):
    return (reasons[0] if reasons else "")[:n]


def replay_row(row, known, repo=REPO, legacy_floor=False, release_ids=(), cache=None, guard=False):
    """⇒ 一列結果 dict。"""
    cache = cache if cache is not None else {}
    stage, head, base = row["stage"], row["head"], row.get("base")
    act = float(row["actual_minutes"])
    res = {k: row.get(k) for k in ("id", "stage", "variant", "base", "head")}
    res["actual_min"] = act
    hs = SS.rev(head, repo)
    if hs not in cache:
        rd = SS.GitReader(repo, hs)
        tmap = json.loads(rd.text(SS.TEST_MAP_REL))
        cache[hs] = (rd, tmap, CostModel(static_counts(rd, tmap), known))
    rd, tmap, cm = cache[hs]
    total_tests, total_sec = cm.cost(SS.collect_files(tmap, rd.tree(), rd, stage)[0], stage)
    res["model_full_min"] = (OVERHEAD_S[stage] + total_sec / WORKERS) / 60.0

    guard_files = set()
    if guard:                                                                   # 共用樣式清單（guard_patterns.json）：該段收集範圍內命中的守門檔併入底板
        import guard_patterns as GP
        collected_here = set(SS.collect_files(tmap, rd.tree(), rd, stage)[0])
        guard_files = set(GP.match_files(rd.tree())) & collected_here
    res["guard_files"] = len(guard_files)

    def plan_for(b, reds=None):
        return SS.plan_stage(stage, b, head, repo, reader=rd, tmap=tmap, legacy_floor=legacy_floor,
                             red_files=reds or [], pages=None)

    # 增量估計
    if base:
        p = plan_for(base, row.get("base_red_files"))
        res["mode"], res["why"] = p["mode"], short(p["forced_full"])
        res["scope_gate_mode"] = p.get("scope_gate_mode")
        if p["mode"] == "full":
            run = p["collected"]
        else:
            run = sorted(set(p["to_run"]) | guard_files)
        t_run, s_run = cm.cost(run, stage)
        res["files"], res["collected_files"] = len(run), len(p["collected"])
        res["share"] = t_run / total_tests if total_tests else 1.0
        inc_min = (OVERHEAD_S[stage] + s_run / WORKERS) / 60.0
        res["est_M_min"] = act if p["mode"] == "full" else min(act, inc_min)
        res["est_S_min"] = act if (p["mode"] == "full" or p.get("scope_gate_mode") == "full") else res["est_M_min"]
        res["floor_files"] = len(p["floor"])
        res["floor_min"] = (OVERHEAD_S[stage] + cm.cost(p["floor"], stage)[1] / WORKERS) / 60.0
    else:
        res.update(mode="full", why="沒有可用基準", share=1.0, est_M_min=act, est_S_min=act, files=None,
                   collected_files=None, floor_files=None, floor_min=None, scope_gate_mode=None)
    res["est_M_release_min"] = act if row.get("id") in release_ids else res["est_M_min"]
    # 召回：以「選題＋底板」（不含全量逃生門）覆蓋這段實際紅的檔
    reds = SS.normalize_red(row.get("red_files"))
    rb = row.get("recall_base") or base
    if reds and rb:
        q = plan_for(rb)
        covered = set(q["selected"]) | set(q["floor"]) | guard_files
        res["recall"] = {"reds": len(reds), "hit": sorted(f for f in reds if f in covered),
                         "miss": sorted(f for f in reds if f not in covered), "base": rb,
                         "via_full_only": q["mode"] == "full"}
    return res


def totals(rows, variant, key):
    sel = [r for r in rows if r.get("variant") == variant]
    return sum(r["actual_min"] for r in sel), sum(r[key] for r in sel)


def fmt(m):
    sec = int(round(abs(m) * 60))
    return "%s%d:%02d" % ("-" if m < 0 else "", sec // 60, sec % 60)


def report(rows, release_ids):
    out = []
    out.append("| 段 | stage | var | 基準→head | 模式 | 選到題數占比 | 實際 | 增量估計(M) | 省(M) | 模型全量(驗算) |")
    out.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        out.append("| %s | %s | %s | %s→%s | %s | %s | %s | %s | %s | %s |" % (
            r["id"], r["stage"], r["variant"], (r["base"] or "-")[:8], r["head"][:8],
            "全量(" + r["why"] + ")" if r["mode"] == "full" else "增量",
            "%.0f%%" % (100 * r["share"]) if r["mode"] != "full" else "全量",
            fmt(r["actual_min"]), fmt(r["est_M_min"]), fmt(r["actual_min"] - r["est_M_min"]), fmt(r["model_full_min"])))
    out.append("")
    out.append("合計（分鐘；實際 → 估計，省）— 對照設計文件 §3.2：")
    summ = {}
    for var in ("A", "B"):
        for pol, key in (("S", "est_S_min"), ("M", "est_M_min")):
            a, e = totals(rows, var, key)
            summ["%s·%s" % (var, pol)] = (a, e)
    a, e = totals(rows, "B", "est_M_release_min")
    summ["B·M·release-full"] = (a, e)
    for k, (a, e) in summ.items():
        doc_e, doc_save = DOC_TOTALS.get(k, (None, None))
        out.append("  %-18s 實際 %6.1f → %6.1f，省 %5.1f（%.0f%%）｜文件：省 %s｜差 %s" % (
            k, a, e, a - e, 100 * (a - e) / a if a else 0, "%.1f" % doc_save if doc_save is not None else "-",
            "%+.1f" % ((a - e) - doc_save) if doc_save is not None else "-"))
    for grp in ("t29", "t30"):
        sel = [r for r in rows if r.get("variant") == "B" and r["id"].startswith(grp)]
        a, e = sum(r["actual_min"] for r in sel), sum(r["est_M_min"] for r in sel)
        out.append("  B·M %s：實際 %.1f → %.1f，省 %.1f" % (grp, a, e, a - e))
    a_all = sum(r["actual_min"] for r in rows if r.get("variant") == "B")
    out.append("  實際總分鐘（B 列合計）%.1f｜文件 %.1f" % (a_all, DOC_ACTUAL_TOTAL))
    # 底板
    fl = [r for r in rows if r.get("variant") == "B" and r.get("floor_min")]
    if fl:
        out.append("  底板（含段開銷；增量列）：%s" % "、".join("%s/%s %.1f 分(%d 檔)" % (r["id"], r["stage"], r["floor_min"], r["floor_files"]) for r in fl[:4]))
    # 召回
    seen, hit, tot, miss = set(), 0, 0, []
    for r in rows:
        if r.get("variant") != "B":              # 每組紅只算一次（B 列的 recall_base 是該紅的對應基準）
            continue
        rc = r.get("recall")
        if not rc:
            continue
        key = (r["id"], r["stage"], rc["base"])
        if key in seen:
            continue
        seen.add(key)
        hit += len(rc["hit"])
        tot += rc["reds"]
        miss += ["%s/%s:%s" % (r["id"], r["stage"], f.rsplit("/", 1)[-1]) for f in rc["miss"]]
    out.append("  召回（選題＋底板，無全量逃生門）：%d／%d（%.1f%%）｜文件 %d／%d（補 F0d 後 25／26）｜漏：%s" % (
        hit, tot, 100.0 * hit / tot if tot else 0, DOC_RECALL[0], DOC_RECALL[1], "、".join(miss) or "無"))
    return "\n".join(out), summ, (hit, tot, miss)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                                  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="增量段離線重放")
    ap.add_argument("rows")
    ap.add_argument("--json")
    ap.add_argument("--repo", default=str(REPO))
    ap.add_argument("--fail-stream-dir", default=FAIL_STREAM_DIR)
    ap.add_argument("--guard-patterns", action="store_true", help="底板併入 guard_patterns.json 命中的守門檔（與作者閘門 A2 共用）")
    ap.add_argument("--legacy-floor", action="store_true", help="用 §3.1 舊底板（契約目錄＋global＋unmapped，F1 不扣、無 F0d）")
    ap.add_argument("--release-ids", default="t29f,t30f", help="出貨包（強制全量情境）的 id，逗號分隔")
    a = ap.parse_args(argv)
    rows_in = json.loads(Path(a.rows).read_text(encoding="utf-8"))
    known = load_file_seconds(a.fail_stream_dir)
    print("已知檔秒數：%d 檔（%s）" % (len(known), a.fail_stream_dir), file=sys.stderr)
    cache, rel = {}, tuple(x for x in a.release_ids.split(",") if x)
    rows = [replay_row(r, known, a.repo, a.legacy_floor, rel, cache, a.guard_patterns) for r in rows_in]
    text, summ, rec = report(rows, rel)
    print(text)
    if a.json:
        Path(a.json).write_text(json.dumps({"rows": rows, "totals": summ, "recall": rec}, ensure_ascii=False, indent=1),
                                encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
