# -*- coding: utf-8 -*-
"""整合守門題組（T82，設計 docs/platform/PREFLIGHT-GUARDS-T82.md）：整合者每合併一支分支就跑一次，約 5 分鐘內把
「只在合併後才紅」的守門一次全列出來，並指出最近哪幾次合併最可能是肇因——不必等 80 分鐘的完整閘門才一個一個發現。

[單位] tools:preflight_guards   [層] 工具   [穩定度] 內部
[不變式] 題組清單只有 tools/platform/preflight_guards.json 一份（每組＝一類守門＋出紅標準修法＋肇因搜尋的 watch glob）；
    MOTRIX_TRAIN=1、不 fail-fast（不載 failfast 外掛）、-m "not e2e"；找不到 required 組的檔 ⇒ 結束碼 2（改名不會悄悄少跑）；
    不寫追蹤檔、不 commit、不 push；重型（-n≥2）一律經 heavy_run 排隊（閘門鎖期間要用持有者視窗，否則自動等）。
    與 train_preflight.py 的分工：那支是 A 靜態旗標（秒級）＋窄版便宜集合＋受影響模組；這支是「T76/T81 實際紅過的守門類別」
    的固定題組＋依守門種類分組＋肇因合併。A 靜態旗標這裡也順手跑一次（`--no-static` 可關）。

用法（在整合樹，Python 用 D:\\MOTRIX-PLATFORM\\.venv312\\Scripts\\python.exe；一律在 repo 根目錄下執行）：
  python tools/platform/preflight_guards.py                      跑題組（3 worker、排隊、預算 12 分）
  python tools/platform/preflight_guards.py --window <視窗>      閘門鎖持有者用自己的視窗名（才不會被自己的閘門鎖擋住）
  python tools/platform/preflight_guards.py --list               只列題組（每組幾個檔、找不到的）
  python tools/platform/preflight_guards.py --dry-run            印 pytest 指令與預估耗時，不跑
  python tools/platform/preflight_guards.py --only changelog,version_manifest    只跑指定組（修完紅後只重跑那幾組）
  python tools/platform/preflight_guards.py --with-e2e-goldens   另加 e2e golden（瀏覽器、獨佔排隊；約數分鐘）
  --since <rev>   肇因搜尋從這個 rev 之後的合併找（預設 origin/platform；沒有就最近 --merges 25 個）
結束碼：0 全綠；1 有紅（報告依守門種類分組、附肇因合併與標準修法）；2 工具本身出錯／required 組找不到檔；3 超過預算被停掉（不是綠）；75 排隊逾時。
"""
import argparse
import fnmatch
import glob
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
CONFIG = HERE / "preflight_guards.json"
DEFAULT_WORKERS = 3
DEFAULT_BUDGET_MIN = 12.0
DEFAULT_MERGES = 25
INCOMPLETE_RC = -999
_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)

sys.path.insert(0, str(HERE))


def _load(name):
    """同目錄的工具模組（heavy_run／pre_train_check／train_preflight）；找不到或匯入失敗 ⇒ None。"""
    p = HERE / (name + ".py")
    if not p.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location("_pfg_" + name, str(p))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:                                                        # noqa: BLE001
        return None


# ── 純函式（有題）────────────────────────────────────────────────────────────────

def load_config(path=None):
    cfg = json.loads(Path(path or CONFIG).read_text(encoding="utf-8"))
    ids = [g["id"] for g in cfg["groups"]]
    if len(ids) != len(set(ids)):
        raise ValueError("題組 id 重複：%s" % sorted({i for i in ids if ids.count(i) > 1}))
    for g in cfg["groups"]:
        if not g.get("paths") or not g.get("label"):
            raise ValueError("題組 %s 缺 paths／label" % g.get("id"))
    return cfg


def expand_groups(backend, cfg, only=None, with_e2e=False):
    """⇒ (targets 相對 backend/ 去重保序, file_group {相對檔: 組 id}, missing [(組 id, pattern, required)])。
    pattern 在 backend/ 底下 glob；`檔::nodeid` 原樣保留。組內一個 pattern 都找不到檔 ⇒ 列 missing。"""
    backend = Path(backend)
    targets, file_group, missing = [], {}, []
    groups = [dict(g) for g in cfg["groups"]]
    if with_e2e:
        groups.append({"id": "e2e_goldens", "label": "e2e golden 比對", "paths": cfg["e2e_goldens"]["paths"], "required": False})
    for g in groups:
        if only and g["id"] not in only:
            continue
        for pat in g["paths"]:
            file_pat, _, node = pat.partition("::")
            hits = sorted(Path(p).relative_to(backend).as_posix() for p in glob.glob(str(backend / file_pat)) if Path(p).is_file())
            if not hits:
                missing.append((g["id"], pat, g.get("required", True)))
                continue
            for h in hits:
                t = h + ("::" + node if node else "")
                if t not in targets:
                    targets.append(t)
                file_group.setdefault(h, g["id"])
    return targets, file_group, missing


def group_of(nodeid, file_group):
    f = nodeid.split("::", 1)[0].replace("\\", "/").lstrip("/")
    f = f[len("backend/"):] if f.startswith("backend/") else f
    return file_group.get(f, "other")


def group_failures(failures, file_group):
    """⇒ {組 id: [failure…]}（依出現順序）。"""
    out = {}
    for f in failures:
        out.setdefault(group_of(f["nodeid"], file_group), []).append(f)
    return out


def _owner_key(nodeid):
    m = re.match(r"(?:backend/)?modules/([^/]+)/", nodeid.split("::", 1)[0].replace("\\", "/"))
    return m.group(1) if m else None


def attribute(nodeids, watch, merges, top=3):
    """可能肇因的合併。merges＝[{sha, subject, files}]（新的在前）。
    計分：合併動到這些紅題所在的測試檔 +3；動到紅題所屬模組目錄 +2；動到該組的 watch glob +1。⇒ 前 top 個 score>0，附命中的檔。"""
    test_files = {n.split("::", 1)[0].replace("\\", "/").lstrip("/") for n in nodeids}
    test_files = {t if t.startswith("backend/") else "backend/" + t for t in test_files}
    owners = {o for o in (_owner_key(n) for n in nodeids) if o}
    scored = []
    for m in merges:
        files = [f.replace("\\", "/") for f in m["files"]]
        hit_test = [f for f in files if f in test_files]
        hit_owner = [f for f in files if any(f.startswith("backend/modules/%s/" % o) for o in owners)]
        hit_watch = [f for f in files if any(fnmatch.fnmatch(f, w) for w in watch)]
        score = (3 if hit_test else 0) + (2 if hit_owner else 0) + (1 if hit_watch else 0)
        if score:
            scored.append((score, m, (hit_test + hit_owner + hit_watch)))
    scored.sort(key=lambda x: -x[0])                                         # sort 穩定：同分維持「新的在前」
    out = []
    for score, m, files in scored[:top]:
        out.append({"sha": m["sha"][:8], "subject": m["subject"], "score": score, "files": list(dict.fromkeys(files))[:3]})
    return out


def format_report(plan, static_findings, grouped, labels, fixes, watch, merges, rc, secs, passed_line, missing, nodeid_merges=None):
    L = ["═══ 整合守門題組 ═══"]
    L.append("題組：%d 組、%d 個測試檔%s" % (plan["groups"], len(plan["targets"]), "（含 e2e golden）" if plan.get("e2e") else ""))
    for gid, pat, required in missing:
        L.append("%s 找不到守門檔（改名或刪除了？）：[%s] %s" % ("✘" if required else "⚠", gid, pat))
    un = [f for f in static_findings if f.get("unchecked")]
    real = [f for f in static_findings if not f.get("unchecked")]
    for f in un:
        L.append("⚠ %s %s" % (f["code"], f["msg"]))
    if real:
        L.append("A 靜態旗標：%d 項" % len(real))
        for f in real:
            L.append("  [%s] %s\n      %s\n      修法：%s" % (f["code"], f["where"], f["msg"], f["fix"]))
    else:
        L.append("A 靜態旗標：0 項")
    if rc == INCOMPLETE_RC:
        L.append("⚠ 未完成：超過時間預算被停掉（%.0f 秒）；以下只含停掉前已出現的紅，**不能當作綠**" % secs)
    elif rc is not None:
        L.append("pytest：%s（%.0f 秒，exit %s）" % (passed_line or "-", secs, rc))
    total = sum(len(v) for v in grouped.values())
    if grouped:
        L.append("紅 %d 題，依守門種類（%d 類）：" % (total, len(grouped)))
        for gid, fs in grouped.items():
            L.append("■ [%s] %d 紅" % (labels.get(gid, gid), len(fs)))
            for f in fs[:8]:
                L.append("    %s %s%s" % (f["kind"], f["nodeid"], " — " + f["msg"][:100] if f["msg"] else ""))
            if len(fs) > 8:
                L.append("    … 另 %d 題" % (len(fs) - 8))
            cands = (nodeid_merges or {}).get(gid)
            if cands:
                L.append("    可能肇因（最近的合併）：")
                for c in cands:
                    L.append("      %s %s（動到 %s）" % (c["sha"], c["subject"][:70], "、".join(c["files"])))
            elif merges is not None:
                L.append("    可能肇因：最近 %d 次合併裡沒有動到相關檔的（可能是本樹未提交的改動，或更早的合併）" % len(merges))
            if fixes.get(gid):
                L.append("    修法：" + fixes[gid])
        first = next(iter(next(iter(grouped.values()))))["nodeid"]
        L.append("單獨重跑（在 backend/ 底下，MOTRIX_TRAIN=1）：python -m pytest \"%s\" -v" % first)
        L.append("修完只重跑出紅的組：python tools/platform/preflight_guards.py --only %s" % ",".join(g for g in grouped if g != "other"))
    ok = rc in (None, 0) and not real and not un and not any(r for _g, _p, r in missing)
    if rc == INCOMPLETE_RC:
        L.append("結果：未完成（incomplete，超過時間預算）")
    elif ok and not grouped:
        L.append("結果：題組全綠（題組綠 ≠ 閘門綠：只涵蓋已知的合併後守門類別；功能題的互踩要靠完整閘門）")
    else:
        L.append("結果：有紅／未能檢查")
    return "\n".join(L)


# ── git：最近的合併 ─────────────────────────────────────────────────────────────

def _git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=_NOWIN)
    return r.stdout if r.returncode == 0 else ""


def recent_merges(repo, since=None, n=DEFAULT_MERGES):
    """⇒ [{sha, subject, files}]：first-parent 的合併提交（新的在前），每個的檔＝相對第一親的變動檔。since 給了就用 since..HEAD，沒有 rev 就退回最近 n 個。"""
    rng = ["%s..HEAD" % since] if since and _git(repo, "rev-parse", "--verify", "-q", since).strip() else []
    out = _git(repo, "log", "--first-parent", "--merges", "-n", str(n), "--format=%H%x1f%s", *rng)
    merges = []
    for line in out.splitlines():
        sha, _, subject = line.partition("\x1f")
        if not sha:
            continue
        files = _git(repo, "diff", "--name-only", sha + "^1", sha).split()
        merges.append({"sha": sha, "subject": subject, "files": files})
    return merges


# ── 執行 ───────────────────────────────────────────────────────────────────────

def python_exe():
    cand = Path("D:/MOTRIX-PLATFORM/.venv312/Scripts/python.exe")
    return str(cand) if cand.exists() else sys.executable


def build_cmd(python, targets, workers, basetemp, marker="not e2e"):
    return [python, "-m", "pytest", *targets, "-q", "-rfE", "--tb=short", "-m", marker,
            *(["-n", str(workers)] if workers and workers >= 2 else ["-p", "no:xdist"]), "-p", "no:cacheprovider", "--basetemp=%s" % basetemp]


def _make_runner(backend, holder, budget_s, tee=True):
    def runner(cmd, env, flags):
        e = dict(env, MOTRIX_TRAIN="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
        t0 = time.time()
        proc = subprocess.Popen(cmd, cwd=str(backend), env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=flags | _NOWIN)
        lines = []
        for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace")
            lines.append(line)
            if tee:
                sys.stdout.write(line)
                sys.stdout.flush()
            if budget_s and time.time() - t0 > budget_s:
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, creationflags=_NOWIN)   # 只結束自己起的這一棵
                holder.update(out="".join(lines), secs=time.time() - t0)
                proc.wait()
                return INCOMPLETE_RC
        rc = proc.wait()
        holder.update(out="".join(lines), secs=time.time() - t0)
        return rc
    return runner


def run_pytest(repo, targets, workers, window, marker="not e2e", queue_cls=None, budget_min=DEFAULT_BUDGET_MIN, max_wait=None, hr=None, tee=True):
    """⇒ (rc, 輸出全文, 秒數)。重型（-n≥2）經 heavy_run 排隊；排不到（75）⇒ rc 75、輸出空。"""
    backend = Path(repo) / "backend"
    basetemp = os.path.join(tempfile.gettempdir(), "pfg_%d_%d" % (os.getpid(), int(time.time())))
    cmd = build_cmd(python_exe(), targets, workers, basetemp, marker)
    holder = {"out": "", "secs": 0.0}
    runner = _make_runner(backend, holder, budget_min * 60 if budget_min else None, tee)
    cls = queue_cls or ("heavy" if workers and workers >= 2 else "light")
    try:
        hr = hr or _load("heavy_run")
        if hr is None:
            rc = runner(cmd, dict(os.environ), 0)
        else:
            rc = hr.run(cmd, cls, window, runner=runner, max_wait=max_wait, note=lambda m: print(m, flush=True))
        return rc, holder["out"], holder["secs"]
    finally:
        shutil.rmtree(basetemp, ignore_errors=True)


def static_findings(repo, base):
    """train_preflight 的 A 靜態旗標 ⇒ [{code, where, msg, fix, unchecked}]；工具載不起來 ⇒ 一筆 unchecked（不當綠）。"""
    tp = _load("train_preflight")
    if tp is None:
        return [{"code": "A", "where": "preflight", "msg": "未能檢查：train_preflight 載入失敗", "fix": "單獨跑 train_preflight.py --static-only", "unchecked": True}]
    try:
        out = tp.static_checks(Path(repo), tp.changed_files(repo, base), base)
        return [dict(f.as_dict(), unchecked=isinstance(f, tp.Unchecked)) for f in out]
    except Exception as e:                                                   # noqa: BLE001
        return [{"code": "A", "where": "preflight", "msg": "未能檢查：%s" % e, "fix": "單獨跑 train_preflight.py --static-only", "unchecked": True}]


def estimate(repo, targets):
    """依 preflight_seconds.json 估 worker-秒（量過的檔加總；沒量過的檔數另列）。⇒ (秒, 沒量過的檔數)。"""
    try:
        sec = json.loads((HERE / "preflight_seconds.json").read_text(encoding="utf-8")).get("seconds", {})
    except (OSError, ValueError):
        return 0.0, len(targets)
    total, unknown = 0.0, 0
    for t in targets:
        f = t.split("::", 1)[0]
        v = sec.get("backend/" + f, sec.get(f))
        if v is None:
            unknown += 1
        else:
            total += float(v)
    return total, unknown


def preflight(repo=REPO, only=None, workers=DEFAULT_WORKERS, window="x", with_e2e=False, run_static=True, base="origin/platform", since=None,
              n_merges=DEFAULT_MERGES, dry_run=False, budget_min=DEFAULT_BUDGET_MIN, max_wait=None, runner=None, merges_fn=None, config=None, hr=None):
    """⇒ (exit_code, report_text, data)。runner(repo, targets, marker) ⇒ (rc, out, secs) 供測試注入。"""
    repo = Path(repo)
    cfg = config or load_config()
    only = set(only) if only else None
    if only:
        unknown = only - {g["id"] for g in cfg["groups"]} - ({"e2e_goldens"} if with_e2e else set())
        if unknown:
            return 2, "未知的題組 id：%s（--list 看全部）" % "、".join(sorted(unknown)), {}
    targets, file_group, missing = expand_groups(repo / "backend", cfg, only, with_e2e)
    labels = {g["id"]: g["label"] for g in cfg["groups"]}
    labels["e2e_goldens"] = "e2e golden 比對"
    labels["other"] = "其他"
    fixes = {g["id"]: g.get("fix", "") for g in cfg["groups"]}
    watch = {g["id"]: g.get("watch", []) for g in cfg["groups"]}
    non_e2e = [t for t in targets if group_of(t, file_group) != "e2e_goldens"]
    e2e_t = [t for t in targets if group_of(t, file_group) == "e2e_goldens"]
    plan = {"groups": len({file_group[t.split('::')[0]] for t in targets}), "targets": targets, "e2e": bool(e2e_t)}
    if any(req for _g, _p, req in missing) and not targets:
        return 2, format_report(plan, [], {}, labels, fixes, watch, None, None, 0, "", missing), {}
    findings = static_findings(repo, base) if (run_static and not dry_run) else []
    if dry_run:
        est, unk = estimate(repo, targets)
        lines = ["[dry-run] %d 組、%d 個測試檔；估計 %.0f worker-秒（≈ %.1f 分 @ %d worker；%d 個檔沒量過耗時）" % (plan["groups"], len(targets), est, est / max(1, workers) / 60, workers, unk)]
        lines += ["  找不到：[%s] %s%s" % (g, p, "" if r else "（選用）") for g, p, r in missing]
        lines.append(" ".join(build_cmd("python", non_e2e, workers, "<basetemp>")))
        return (2 if any(r for _g, _p, r in missing) else 0), "\n".join(lines), {"plan": plan}
    rc, out, secs = (None, "", 0.0)
    fails = []
    pt = _load("pre_train_check")
    if pt is None:
        return 2, "預檢工具出錯：pre_train_check 載入失敗（parse_failures 用它）", {}

    def go(ts, marker, w, cls=None):
        if runner is not None:
            return runner(repo, ts, marker)
        return run_pytest(repo, ts, w, window, marker, cls, budget_min, max_wait, hr)
    if non_e2e:
        rc, out, secs = go(non_e2e, "not e2e", workers)
    if e2e_t and rc not in (INCOMPLETE_RC, 75):
        rc2, out2, secs2 = go(e2e_t, "e2e", 1, "e2e")
        out += "\n" + out2
        secs += secs2
        rc = rc if rc not in (None, 0) else rc2
    if rc == 75:
        return 75, "[preflight_guards] 排隊等超過上限，沒有跑（75）", {"rc": 75}
    fails = pt.parse_failures(out)
    grouped = group_failures(fails, file_group)
    passed_line = (re.findall(r"^.*\d+ (?:passed|failed).*$", out, re.M) or [""])[-1].strip()
    merges, cands = None, {}
    if grouped:
        merges = (merges_fn or recent_merges)(repo, since or base, n_merges)
        for gid, fs in grouped.items():
            cands[gid] = attribute([f["nodeid"] for f in fs], watch.get(gid, []), merges)
    text = format_report(plan, findings, grouped, labels, fixes, watch, merges, rc, secs, passed_line, missing, cands)
    bad = bool(grouped) or any(not f.get("unchecked") for f in findings) or (rc not in (None, 0, INCOMPLETE_RC))
    miss_req = any(r for _g, _p, r in missing)
    code = 3 if rc == INCOMPLETE_RC else 1 if (bad or any(f.get("unchecked") for f in findings)) else 2 if miss_req else 0
    return code, text, {"rc": rc, "failures": fails, "grouped": {k: [f["nodeid"] for f in v] for k, v in grouped.items()}, "candidates": cands, "findings": findings}


def _utf8_console():
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv=None):
    _utf8_console()
    ap = argparse.ArgumentParser(description="整合守門題組")
    ap.add_argument("--window", default=os.environ.get("MOTRIX_WINDOW", "x"), help="排隊用的視窗名；閘門鎖持有者要與取鎖的視窗相同")
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    ap.add_argument("--only", help="只跑這些組 id（逗號分隔；--list 看全部）")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--with-e2e-goldens", action="store_true")
    ap.add_argument("--no-static", action="store_true", help="不跑 train_preflight 的 A 靜態旗標")
    ap.add_argument("--base", default="origin/platform")
    ap.add_argument("--since", default=None, help="肇因搜尋起點 rev（預設同 --base）")
    ap.add_argument("--merges", type=int, default=DEFAULT_MERGES)
    ap.add_argument("--budget-min", type=float, default=DEFAULT_BUDGET_MIN)
    ap.add_argument("--max-wait", type=int, default=None, help="排隊最多等幾秒（逾時 75）")
    ap.add_argument("--json-out")
    a = ap.parse_args(argv)
    try:
        cfg = load_config()
        if a.list:
            targets, fg, missing = expand_groups(REPO / "backend", cfg, None, a.with_e2e_goldens)
            for g in cfg["groups"] + ([{"id": "e2e_goldens", "label": "e2e golden 比對"}] if a.with_e2e_goldens else []):
                n = sum(1 for v in fg.values() if v == g["id"])
                print("%-18s %2d 檔  %s" % (g["id"], n, g["label"]))
            for g, p, r in missing:
                print("  找不到：[%s] %s%s" % (g, p, "" if r else "（選用）"))
            return 2 if any(r for _g, _p, r in missing) else 0
        code, text, data = preflight(REPO, a.only.split(",") if a.only else None, a.workers, a.window, a.with_e2e_goldens, not a.no_static, a.base,
                                     a.since, a.merges, a.dry_run, a.budget_min, a.max_wait, config=cfg)
    except Exception as e:                                                   # noqa: BLE001
        print("預檢工具出錯：%s" % e, file=sys.stderr)
        return 2
    print(text)
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(data, ensure_ascii=False, indent=1, default=list), encoding="utf-8")
    return code


if __name__ == "__main__":
    sys.exit(main())
