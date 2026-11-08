# -*- coding: utf-8 -*-
"""stage_select 的『影子模式』紀錄器（2026-11-08；使用者裁示：增量測試先走影子、正式建包仍以全量為唯一真相）。

🔴 **只記錄、不決定任何事**：不跳過任何一題、不改建包結果／exit code、不是閘門、不寫 repo 內任何檔。
    任何內部錯誤 ⇒ 在紀錄檔寫一筆 `type=error` 後離開（exit 0）；建包端以背景程序呼叫、不等它。

## 回答的問題
「這一次建包（head），若當時只跑 `stage_select` 選中的範圍（以前一次**跑完**的同段紀錄為基準），
  會不會漏掉這次**全量**測試實際抓到的任何失敗？」——每個（建包 run × 段）一行。

## 紀錄檔（獨立一份，不進 test_results.jsonl）
`<主工作樹>/backend/tools/deploy_logs/stage_select_shadow.jsonl`（已在 .gitignore 的 deploy_logs/ 內；`--log` 可改）。
一行一筆 JSON，`v=1`，`type=shadow`（或 `type=error`）。欄位：
- `run_id`／`stage`／`commit`／`dirty`（建包當下追蹤檔有未提交變更 ⇒ 計畫以 commit 算、僅供參考）／`recorded_at`
- `base`：基準（同段、最近一筆**跑完**〔未被 fail-fast／中斷〕且 commit ≠ head 的紀錄）；沒有 ⇒ null（計畫＝全量，原因「基準缺失」）
- `full`：這次全量實際結果——`green`、`complete`（沒被 fail-fast／中斷；不完整＝紅檔只是下限）、`reds_files`（紅檔，已扣偶發放行）、
  `reds_raw_files`、`reds_unmapped`（非檔路徑的紅，如 worker 掉線）、`evidence`（`fail_stream`｜`none`）
- `plan`：`stage_select.plan_stage` 的摘要——`mode`（incremental｜full）、`forced_full`（強制全量的每個原因）、各集合大小、
  `selected`（檔→理由）、`red_reselect`、`to_run_share_files`／`to_run_share_tests`
- `verdict`：
  - `policy`：依真實政策（強制全量 ⇒ 全跑、不會漏）⇒ `miss`｜`covered`｜`no_reds`｜`unknown`；`missed_files` 是漏掉的紅檔
  - `no_escape`：**不算全量逃生門**，只看 selected∪floor∪red_reselect 有沒有蓋住紅檔 ⇒ 同上四值；`missed_files_no_escape`
    （這才是「選題本身的召回」；forced_full 多時 policy 會太樂觀，轉正前要看這個）

## 用法（repo 根目錄）
  python tools/platform/stage_select_shadow.py record   --run-id <build_…> --stage not_e2e|e2e --green 1|0 [--head HEAD] [--flaky-from <retry.json>]
  python tools/platform/stage_select_shadow.py backfill [--since 2026-11-01] [--limit N]    # 用既有 fail_stream＋test_results 補歷史（依時間配對，commit_source 標明）
  python tools/platform/stage_select_shadow.py report   [--since …] [--json]                # 準確率／省時彙總
  環境變數：MOTRIX_FAIL_STREAM_DIR（fail_stream 目錄）、建包端 MOTRIX_STAGE_SHADOW=0 關閉紀錄。

## 已知限制（記錄在案，不是缺陷）
- 基準的『環境指紋相同』未判（notes 記「未提供基準中繼資料」）；基準鏈長固定 1、鏈根固定為真全量（影子期每次建包都跑全量）。
- 基準年齡上限沿用 stage_select 預設 6 小時：隔夜／久未建包的紀錄會 forced_full（policy 看起來安全，要看 no_escape）。
- fail-fast 提前停的段（`complete=false`）沒跑完，沒看到紅 ≠ 沒有紅；彙總把它單列。
- 偶發紅：該段最後被判綠（偶發重跑放行）⇒ `reds_files` 為空（不算『該抓的失敗』）；原始紅仍留在 `reds_raw_files`。
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import stage_select as SS  # noqa: E402

VERSION = 1
LOG_NAME = "stage_select_shadow.jsonl"
TS = "%Y-%m-%d %H:%M:%S"
#: 配對 fail_stream 摘要 ↔ test_results 的容許秒數（偶發重跑會讓 Record-Stage 比摘要晚數分鐘）
JOIN_WINDOW_S = 900


# ── 位置 ───────────────────────────────────────────────────────────────────────

def _git_common_parent(repo):
    r = subprocess.run(["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError("找不到主工作樹：" + (r.stderr or "").strip())
    return Path(r.stdout.strip()).parent


def default_log(repo=REPO):
    """主工作樹的 deploy_logs（worktree 用完就刪；各 worktree 建包寫同一份）。"""
    return _git_common_parent(repo) / "backend" / "tools" / "deploy_logs" / LOG_NAME


def default_results(repo=REPO):
    return default_log(repo).with_name("test_results.jsonl")


def default_stream_dir(repo=REPO):
    d = os.environ.get("MOTRIX_FAIL_STREAM_DIR")
    return Path(d) if d else _git_common_parent(repo) / "tools" / "platform" / "fail_stream"


# ── 讀寫 ───────────────────────────────────────────────────────────────────────

def read_jsonl(path):
    out = []
    p = Path(path)
    if not p.is_file():
        return out
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def append_line(path, obj):
    """單次 os.write（O_APPEND）：多個建包同時寫（不同 worktree）整行不交錯。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(p), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def _parse_ts(s):
    s = (s or "").replace("T", " ")
    for fmt in (TS, TS + ".%f"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


# ── 這次全量的實際結果（純函式）──────────────────────────────────────────────────

def full_result(records, stage, green):
    """fail_stream 紀錄（同一個 run 的全部行）⇒ 該段全量的結果摘要。stage 必須完全相等（`<stage>-retry` 是重跑，不算）。
    green＝該段最後的判定（含偶發重跑放行）：True ⇒ 紅檔視為偶發已放行（reds_files 空）；None ⇒ 不知道（backfill 配不到）。"""
    mine = [r for r in records if isinstance(r, dict) and r.get("stage") == stage]
    summaries = [r for r in mine if r.get("type") == "summary"]
    if not summaries:
        return {"evidence": "none", "green": green, "complete": False, "aborted_by": "", "reds_files": [], "reds_raw_files": [],
                "reds_unmapped": [], "finished_at": None, "duration_s": None, "passed": None, "failed": None}
    s = summaries[-1]
    raw_files, unmapped = set(), []
    for r in mine:
        if r.get("type") not in ("fail", "node_down"):
            continue
        f = SS.nodeid_file(r.get("nodeid"))
        if f:
            raw_files.add(f)
        elif r.get("nodeid"):
            unmapped.append(r["nodeid"])
    complete = not s.get("aborted") and not s.get("aborted_by")
    return {"evidence": "fail_stream", "green": green, "complete": bool(complete), "aborted_by": s.get("aborted_by") or ("aborted" if s.get("aborted") else ""),
            "reds_files": [] if green else sorted(raw_files), "reds_raw_files": sorted(raw_files),
            "reds_unmapped": sorted(set(unmapped)) if not green else [],
            "finished_at": s.get("t"), "duration_s": s.get("duration_s"), "passed": s.get("passed"), "failed": s.get("failed")}


# ── 判定（純函式）────────────────────────────────────────────────────────────────

def judge(full, plan):
    """⇒ verdict dict。plan 是 stage_select 計畫（或 `_plan_summary` 的摘要，要有 mode/to_run/selected/floor/red_reselect/plan_error）。"""
    reds = list(full.get("reds_files") or [])
    out = {"reds_n": len(reds), "reds_unmapped_n": len(full.get("reds_unmapped") or []), "full_complete": bool(full.get("complete"))}
    if full.get("evidence") != "fail_stream" or full.get("green") is None:
        out.update(policy="unknown", no_escape="unknown", missed_files=[], missed_files_no_escape=[])
        return out
    if not reds:
        out.update(policy="no_reds", no_escape="no_reds", missed_files=[], missed_files_no_escape=[])
        return out
    if plan.get("plan_error") or not plan.get("base_commit"):     # 計算壞了／沒有基準 ⇒ fail closed 全量；選題本身無從評估
        out.update(policy="covered", no_escape="unknown", missed_files=[], missed_files_no_escape=[])
        return out
    cover = set(plan.get("selected_files") or []) | set(plan.get("floor_files") or []) | set(plan.get("red_reselect") or [])
    miss_ne = sorted(f for f in reds if f not in cover)
    if plan.get("mode") == "full":
        miss_pol = []
    else:
        run = set(plan.get("to_run") or [])
        miss_pol = sorted(f for f in reds if f not in run)
    out.update(policy="miss" if miss_pol else "covered", no_escape="miss" if miss_ne else "covered",
               missed_files=miss_pol, missed_files_no_escape=miss_ne)
    return out


# ── 計畫摘要 ─────────────────────────────────────────────────────────────────────

def _share_tests(head_sha, repo, collected, to_run):
    """to_run 占收集題數的比例（靜態題數估計）；失敗 ⇒ None。"""
    try:
        import replay_incremental as RI
        rd = SS.GitReader(repo, head_sha)
        tmap = json.loads(rd.text(SS.TEST_MAP_REL))
        cm = RI.CostModel(RI.static_counts(rd, tmap), {})
        tot = sum(cm.tests(f, st) for st in SS.STAGES for f in collected if (f, st) in cm.counts)
        run = sum(cm.tests(f, st) for st in SS.STAGES for f in to_run if (f, st) in cm.counts)
        return round(run / tot, 4) if tot else None
    except Exception:                                                  # noqa: BLE001 附帶指標，不影響紀錄
        return None


def plan_summary(plan, repo=None, with_tests=True):
    """stage_select 計畫 ⇒ 紀錄用摘要（selected 只記前 200 筆理由；floor 只記檔名）。"""
    err = next((r for r in plan.get("forced_full", []) if r.startswith("計算失敗")), None)
    coll = plan.get("collected") or []
    to_run = plan.get("to_run") or []
    s = {"mode": plan.get("mode"), "base_commit": plan.get("base"), "forced_full": list(plan.get("forced_full") or []), "plan_error": err,
         "collected_n": len(coll), "selected_n": len(plan.get("selected") or {}), "floor_n": len(plan.get("floor") or {}),
         "red_reselect_n": len(plan.get("red_reselect") or []), "to_run_n": len(to_run),
         "to_run_share_files": round(len(to_run) / len(coll), 4) if coll else None,
         "changed_n": len(plan.get("changed_files") or []), "scope_gate_mode": plan.get("scope_gate_mode"),
         "soft_bottom_n": len(plan.get("soft_bottom") or []), "drill_triggered": plan.get("drill_triggered"),
         "invariant_ok": (plan.get("invariant") or {}).get("ok"), "unmapped_changes": (plan.get("unmapped_changes") or [])[:20],
         "notes": list(plan.get("notes") or []),
         "selected": dict(list((plan.get("selected") or {}).items())[:200]), "red_reselect": list(plan.get("red_reselect") or []),
         "selected_files": sorted(plan.get("selected") or {}), "floor_files": sorted(plan.get("floor") or {}), "to_run": [] if plan.get("to_run_all") else list(to_run)}
    if plan.get("to_run_all"):                       # 強制全量：to_run＝全部收集；紀錄不重複存清單
        s["to_run_all"] = True
    s["to_run_share_tests"] = None
    if with_tests and not err and plan.get("head") and repo is not None:
        s["to_run_share_tests"] = _share_tests(plan["head"], repo, coll, to_run)
    return s


# ── 基準 ─────────────────────────────────────────────────────────────────────────

def pick_base(entries, stage, head_sha, now=None):
    """影子紀錄 ⇒ 同段、最近一筆『跑完且有 fail_stream 證據』且 commit ≠ head 的紀錄；沒有 ⇒ None。"""
    for e in reversed(entries):
        if e.get("type") != "shadow" or e.get("stage") != stage:
            continue
        f = e.get("full") or {}
        if f.get("evidence") != "fail_stream" or not f.get("complete") or not e.get("commit"):
            continue
        if e["commit"] == head_sha:
            continue
        fin = _parse_ts(f.get("finished_at")) or _parse_ts(e.get("recorded_at"))
        age = ((now or datetime.now()) - fin).total_seconds() / 3600.0 if fin else None
        return {"commit": e["commit"], "run_id": e.get("run_id"), "finished_at": f.get("finished_at"), "age_hours": age,
                "red_files": list(f.get("reds_raw_files") or [])}
    return None


# ── 一筆紀錄 ─────────────────────────────────────────────────────────────────────

def build_entry(repo, run_id, stage, commit, green, stream_records, entries, dirty=False, now=None, commit_source="build", plan_fn=None):
    """⇒ 一行 shadow 紀錄（dict）。plan_fn 供測試注入；預設 stage_select.plan_stage。"""
    now = now or datetime.now()
    head_sha = SS.rev(commit, repo)
    full = full_result(stream_records, stage, green)
    base = pick_base(entries, stage, head_sha, now)
    info = {"chain_depth": 1, "root_full": True, "incr_streak": 0, "age_hours": base["age_hours"] if base else None}
    pf = plan_fn or SS.plan_stage
    plan = pf(stage, base["commit"] if base else None, head_sha, repo, red_files=base["red_files"] if base else [], base_info=info)
    summ = plan_summary(plan, repo)
    e = {"v": VERSION, "type": "shadow", "recorded_at": now.strftime(TS), "run_id": run_id, "stage": stage, "commit": head_sha,
         "commit_source": commit_source, "dirty": bool(dirty),
         "base": None if not base else {k: base[k] for k in ("commit", "run_id", "finished_at")} | {"age_hours": round(base["age_hours"], 2) if base["age_hours"] is not None else None},
         "full": full, "plan": {k: v for k, v in summ.items() if k not in ("selected_files", "floor_files", "to_run")},
         "verdict": judge(full, summ)}
    return e


def _is_dirty(repo):
    r = subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return bool(r.stdout.strip())


def _flaky_nodeids(path):
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        return [r["nodeid"] for r in d.get("flaky_retried", [])]
    except Exception:                                                  # noqa: BLE001
        return []


def cmd_record(a):
    log = Path(a.log) if a.log else default_log(a.repo)
    try:
        if not a.force and any(e.get("run_id") == a.run_id and e.get("stage") == a.stage and e.get("type") == "shadow" for e in read_jsonl(log)):
            return 0
        sd = Path(a.stream_dir) if a.stream_dir else default_stream_dir(a.repo)
        recs = read_jsonl(sd / (a.run_id + ".jsonl"))
        e = build_entry(a.repo, a.run_id, a.stage, a.head, bool(int(a.green)), recs, read_jsonl(log), dirty=_is_dirty(a.repo))
        if a.flaky_from:
            e["full"]["flaky_retried"] = _flaky_nodeids(a.flaky_from)
        append_line(log, e)
        if a.verbose:
            print(format_entry(e))
    except Exception as ex:                                            # noqa: BLE001 影子永不擋建包
        try:
            append_line(log, {"v": VERSION, "type": "error", "recorded_at": datetime.now().strftime(TS), "run_id": a.run_id,
                              "stage": a.stage, "error": "%s: %s" % (type(ex).__name__, ex)})
        except Exception:                                              # noqa: BLE001
            pass
    return 0


# ── 歷史補錄 ─────────────────────────────────────────────────────────────────────

def join_commits(stream_files, results):
    """fail_stream 的 build_* 檔 ⇒ [(run_id, stage, 摘要時間, commit, green)]，依 test_results 的『分段紀錄』按時間配對。
    每個 test_results 紀錄只配一次；配不到的 run×段略過（不猜）。"""
    rows = []
    for r in results:
        for st, ent in (r.get("stages") or {}).items():
            t = _parse_ts(ent.get("tested_at"))
            if t and r.get("source") == "build" and r.get("commit"):
                rows.append({"t": t, "stage": st, "commit": r["commit"], "green": bool(ent.get("green")), "used": False})
    rows.sort(key=lambda x: x["t"])
    out = []
    for f in sorted(stream_files, key=lambda p: p.name):
        recs = read_jsonl(f)
        for s in [r for r in recs if r.get("type") == "summary" and r.get("stage") in SS.STAGES]:
            ts = _parse_ts(s.get("t"))
            if not ts:
                continue
            for row in rows:
                if row["used"] or row["stage"] != s["stage"]:
                    continue
                dt = (row["t"] - ts).total_seconds()
                if -5 <= dt <= JOIN_WINDOW_S:
                    row["used"] = True
                    out.append((f.stem, s["stage"], ts, row["commit"], row["green"], recs))
                    break
    out.sort(key=lambda x: x[2])
    return out


def cmd_backfill(a):
    log = Path(a.log) if a.log else default_log(a.repo)
    sd = Path(a.stream_dir) if a.stream_dir else default_stream_dir(a.repo)
    results = read_jsonl(a.results or default_results(a.repo))
    since = datetime.strptime(a.since, "%Y-%m-%d") if a.since else None
    files = [p for p in sd.glob("build_*.jsonl")] if sd.is_dir() else []
    pairs = join_commits(files, results)
    done = {(e.get("run_id"), e.get("stage")) for e in read_jsonl(log) if e.get("type") == "shadow"}
    n = skipped = 0
    for run_id, stage, ts, commit, green, recs in pairs:
        if since and ts < since:
            continue
        if (run_id, stage) in done:
            continue
        if a.limit and n >= a.limit:
            break
        try:
            e = build_entry(a.repo, run_id, stage, commit, green, recs, read_jsonl(log), now=ts, commit_source="joined_by_time")
        except Exception as ex:                                        # noqa: BLE001 commit 已不在 repo 等
            skipped += 1
            append_line(log, {"v": VERSION, "type": "error", "recorded_at": datetime.now().strftime(TS), "run_id": run_id,
                              "stage": stage, "commit": commit, "error": "%s: %s" % (type(ex).__name__, ex)})
            continue
        append_line(log, e)
        n += 1
        print(format_entry(e))
    print("補錄 %d 筆，略過 %d 筆（commit 不在 repo 等，已寫 error 行）；可配對 %d 筆。" % (n, skipped, len(pairs)))
    return 0


# ── 彙總 ─────────────────────────────────────────────────────────────────────────

def summarize(entries):
    """影子紀錄 ⇒ 彙總 dict（純函式）。"""
    sh = [e for e in entries if e.get("type") == "shadow"]
    s = {"entries": len(sh), "errors": sum(1 for e in entries if e.get("type") == "error"), "by_stage": {}}
    for st in SS.STAGES:
        rows = [e for e in sh if e.get("stage") == st]
        inc = [e for e in rows if (e.get("plan") or {}).get("mode") == "incremental"]
        forced = [e for e in rows if (e.get("plan") or {}).get("mode") == "full"]
        why = {}
        for e in forced:
            for r in (e["plan"].get("forced_full") or [])[:1]:
                k = r.split("：")[0].split("（")[0][:40]
                why[k] = why.get(k, 0) + 1
        with_reds = [e for e in rows if (e.get("verdict") or {}).get("reds_n")]
        def cnt(key, val, rr=rows):
            return sum(1 for e in rr if (e.get("verdict") or {}).get(key) == val)
        shares = [e["plan"]["to_run_share_tests"] for e in inc if (e["plan"].get("to_run_share_tests") is not None)]
        shares_f = [e["plan"]["to_run_share_files"] for e in inc if (e["plan"].get("to_run_share_files") is not None)]
        s["by_stage"][st] = {
            "entries": len(rows), "incremental": len(inc), "forced_full": len(forced), "forced_full_why": why,
            "with_reds": len(with_reds), "policy_miss": cnt("policy", "miss"), "policy_covered": cnt("policy", "covered"),
            "no_escape_miss": cnt("no_escape", "miss"), "no_escape_covered": cnt("no_escape", "covered"),
            "unknown": cnt("policy", "unknown"), "incomplete_full_runs": sum(1 for e in rows if not (e.get("full") or {}).get("complete")),
            "reds_total": sum(e["verdict"]["reds_n"] for e in rows if e.get("verdict")),
            "reds_missed_policy": sum(len(e["verdict"].get("missed_files") or []) for e in rows if e.get("verdict")),
            "reds_missed_no_escape": sum(len(e["verdict"].get("missed_files_no_escape") or []) for e in rows if e.get("verdict")),
            "mean_to_run_share_tests_incremental": round(sum(shares) / len(shares), 4) if shares else None,
            "mean_to_run_share_files_incremental": round(sum(shares_f) / len(shares_f), 4) if shares_f else None,
            "misses": [{"run": e["run_id"], "commit": e["commit"][:9], "policy": e["verdict"].get("missed_files"),
                        "no_escape": e["verdict"].get("missed_files_no_escape")} for e in with_reds
                       if e["verdict"].get("policy") == "miss" or e["verdict"].get("no_escape") == "miss"]}
    return s


def format_summary(s):
    L = ["影子紀錄 %d 筆（error 行 %d）" % (s["entries"], s["errors"])]
    for st, d in s["by_stage"].items():
        L.append("[%s] %d 筆｜增量 %d｜強制全量 %d %s" % (st, d["entries"], d["incremental"], d["forced_full"], d["forced_full_why"] or ""))
        L.append("    有紅的建包 %d｜政策漏抓 %d（紅檔 %d／%d）｜不算逃生門漏抓 %d（紅檔 %d／%d）｜全量未跑完 %d｜無法判定 %d" % (
            d["with_reds"], d["policy_miss"], d["reds_missed_policy"], d["reds_total"], d["no_escape_miss"],
            d["reds_missed_no_escape"], d["reds_total"], d["incomplete_full_runs"], d["unknown"]))
        L.append("    增量時平均要跑：題數 %s｜檔數 %s" % (d["mean_to_run_share_tests_incremental"], d["mean_to_run_share_files_incremental"]))
        for m in d["misses"][:10]:
            L.append("    漏：%s @%s  policy=%s  no_escape=%s" % (m["run"], m["commit"], m["policy"], m["no_escape"]))
    return "\n".join(L)


def format_entry(e):
    p, v, f = e["plan"], e["verdict"], e["full"]
    return "%s %-7s %s base=%s mode=%s(%s) to_run=%s/%s reds=%d → policy=%s no_escape=%s%s" % (
        e["run_id"], e["stage"], e["commit"][:9], ((e.get("base") or {}).get("commit") or "-")[:9], p["mode"],
        (p["forced_full"][0][:28] if p["forced_full"] else "-"), p["to_run_n"], p["collected_n"], v["reds_n"], v["policy"], v["no_escape"],
        "" if f.get("complete") else "  [全量未跑完]")


def cmd_report(a):
    log = Path(a.log) if a.log else default_log(a.repo)
    entries = read_jsonl(log)
    if a.since:
        cut = a.since + " 00:00:00"
        entries = [e for e in entries if (e.get("recorded_at") or "") >= cut]
    s = summarize(entries)
    print(json.dumps(s, ensure_ascii=False, indent=1) if a.json else format_summary(s))
    return 0


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                                  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="stage_select 影子模式紀錄器（只記錄，不影響建包）")
    ap.add_argument("--repo", default=str(REPO))
    ap.add_argument("--log", help="影子紀錄檔（預設主工作樹 backend/tools/deploy_logs/stage_select_shadow.jsonl）")
    ap.add_argument("--stream-dir")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("--run-id", required=True)
    r.add_argument("--stage", required=True, choices=SS.STAGES)
    r.add_argument("--green", required=True, choices=["0", "1"])
    r.add_argument("--head", default="HEAD")
    r.add_argument("--flaky-from")
    r.add_argument("--force", action="store_true")
    r.add_argument("--verbose", "-v", action="store_true")
    b = sub.add_parser("backfill")
    b.add_argument("--since")
    b.add_argument("--limit", type=int)
    b.add_argument("--results", help="test_results.jsonl（預設主工作樹）")
    rp = sub.add_parser("report")
    rp.add_argument("--since")
    rp.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    return {"record": cmd_record, "backfill": cmd_backfill, "report": cmd_report}[a.cmd](a)


if __name__ == "__main__":
    import nowindow
    nowindow.install()
    sys.exit(main())
