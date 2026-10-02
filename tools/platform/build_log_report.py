# -*- coding: utf-8 -*-
"""建包 log 報表（唯讀；只讀文字，不跑 pytest、不動任何檔）。BUILD-OPTIMIZATION-2 §量測／§3 天檢查用。

用法：
  python tools/platform/build_log_report.py                      最近 3 份 build_*.log（%TEMP%，依修改時間）
  python tools/platform/build_log_report.py --last 5 --top 20
  python tools/platform/build_log_report.py --dir D:\\somewhere --glob "build_t30*.log"
  python tools/platform/build_log_report.py --json               機器可讀（貼進 BUILD-OPTIMIZATION-2 的量測表用）
  python tools/platform/build_log_report.py --budget             另印「<=30 分預算」對照（非 e2e 20／e2e 8／前後置 2）

每份 log 印：起訖時間與 exit、各段（非 e2e／e2e）秒數與題數、結果（綠／紅幾題）、沿用／跳過、
第一個紅的時間（讀 fail_stream JSONL：log 內有 `FAIL-STREAM run=... file=...`；讀不到就略過）、
「第一個紅之後白跑多久」（段結束 − 第一個紅）、--durations 最慢 N 題（依段分開）。
讀不到的欄位印 `-`，不推測。
"""
import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

START_RE = re.compile(r"^\ufeff?start (\d\d:\d\d:\d\d)")
END_RE = re.compile(r"^end exit=(\d+) (\d\d:\d\d:\d\d)")
STAGE_RE = re.compile(r"\[測試\] 執行 pytest（(非 e2e|e2e)")
SUMMARY_RE = re.compile(r"^=*\s*(?:(\d+) failed, )?(?:(\d+) passed)?.*?(?:, (\d+) errors?)?\s+in ([\d.]+)s")
SUMMARY2_RE = re.compile(r"\b((?:\d+ (?:failed|passed|skipped|xfailed|errors?|warnings?)(?:, )?)+) in ([\d.]+)s")
DUR_RE = re.compile(r"^\s*([\d.]+)s (call|setup|teardown)\s+(\S+)")
FS_RUN_RE = re.compile(r"FAIL-STREAM run=(\S+) file=(\S+?)(?: stage=(\S+))?\s*$")
TOTAL_RE = re.compile(r"total=([\d.]+)s\s+非e2e=([\d.]+)s\s+e2e=([\d.]+)s")
REUSE_RE = re.compile(r"(沿用|skipped \(scoped\)|範圍驗證)")
FAIL_RE = re.compile(r"^\[FAIL\]\s*(.*)")
BUDGET = {"非 e2e": 20 * 60, "e2e": 8 * 60, "前後置（preflight／archive／其他）": 2 * 60}


def _t(s):
    return datetime.strptime(s, "%H:%M:%S")


def _counts(text):
    out = {}
    for m in re.finditer(r"(\d+) (failed|passed|skipped|xfailed|errors?)", text):
        out[m.group(2).rstrip("s") if m.group(2).startswith("error") else m.group(2)] = int(m.group(1))
    return out


def parse_log(path, top=20):
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    r = {"log": str(path), "start": None, "end": None, "exit": None, "wall_s": None, "stages": [],
         "reuse": [], "fail": [], "total_line": None}
    cur = None
    in_dur = False
    for ln in lines:
        m = START_RE.match(ln)
        if m:
            r["start"] = m.group(1)
            continue
        m = END_RE.match(ln)
        if m:
            r["exit"], r["end"] = int(m.group(1)), m.group(2)
            continue
        m = STAGE_RE.search(ln)
        if m:
            cur = {"stage": m.group(1), "seconds": None, "counts": {}, "fs_run": None, "fs_file": None,
                   "slowest": [], "status": "進行中／被中斷（沒有 pytest 摘要行）"}
            r["stages"].append(cur)
            in_dur = False
            continue
        if REUSE_RE.search(ln) and "[測試]" in ln:
            r["reuse"].append(ln.strip()[:160])
        m = FAIL_RE.match(ln)
        if m:
            r["fail"].append(m.group(1)[:200])
        m = TOTAL_RE.search(ln)
        if m:
            r["total_line"] = {"total": float(m.group(1)), "not_e2e": float(m.group(2)), "e2e": float(m.group(3))}
        if cur is None:
            continue
        m = FS_RUN_RE.search(ln)
        if m and cur["fs_run"] is None:
            cur["fs_run"], cur["fs_file"] = m.group(1), m.group(2)
            continue
        if "slowest" in ln and "durations" in ln:
            in_dur = True
            continue
        if in_dur:
            m = DUR_RE.match(ln)
            if m:
                cur["slowest"].append((float(m.group(1)), m.group(2), m.group(3)))
                continue
            if ln.startswith("=") or (ln.strip() and not ln.startswith(" ")):
                in_dur = False
        m = SUMMARY2_RE.search(ln)
        if m and ln.lstrip("= ").split(" ")[0].isdigit() and cur["seconds"] is None and " in " in ln:
            cur["seconds"] = float(m.group(2))
            cur["counts"] = _counts(m.group(1))
            cur["status"] = "紅（%d 題）" % (cur["counts"].get("failed", 0) + cur["counts"].get("error", 0)) \
                if (cur["counts"].get("failed") or cur["counts"].get("error")) else "綠"
    for st in r["stages"]:
        st["slowest"] = sorted(st["slowest"], reverse=True)[:top]
        st["first_red"] = _first_red(st)
    if r["start"] and r["end"]:
        d = (_t(r["end"]) - _t(r["start"])).total_seconds()
        r["wall_s"] = d if d >= 0 else d + 86400
    return r


def _first_red(st):
    """讀 fail_stream JSONL：第一筆 type=fail 與該段 summary 的時間 ⇒ (第一個紅距該段開跑秒數, 該段結束距第一個紅秒數)。"""
    f = st.get("fs_file")
    if not f or not os.path.isfile(f):
        return None
    try:
        rows = [json.loads(x) for x in Path(f).read_text(encoding="utf-8").splitlines() if x.strip()]
    except Exception:  # noqa: BLE001 — 讀不到就不報
        return None
    stage = "not_e2e" if st["stage"].startswith("非") else "e2e"
    reds = [x for x in rows if x.get("type") in ("fail", "node_down") and (x.get("stage") in (None, stage))]
    sums = [x for x in rows if x.get("type") == "summary" and x.get("stage") == stage]
    if not reds or not sums:
        return {"reds": len(reds)} if reds else None
    fmt = "%Y-%m-%dT%H:%M:%S.%f"
    t0 = datetime.strptime(reds[0]["t"], fmt)
    t_end = datetime.strptime(sums[0]["t"], fmt)
    t_last = datetime.strptime(reds[-1]["t"], fmt)
    dur = sums[0].get("duration_s")
    started = datetime.fromtimestamp(t_end.timestamp() - dur) if dur else None
    return {"reds": len(reds), "first_red_after_start_s": (t0 - started).total_seconds() if started else None,
            "last_red_after_start_s": (t_last - started).total_seconds() if started else None,
            "wasted_after_first_red_s": (t_end - t0).total_seconds()}


def mmss(s):
    return "-" if s is None else "%d:%02d" % (int(s) // 60, int(s) % 60)


def render(r, top, budget):
    L = ["", "=" * 78, "%s" % Path(r["log"]).name,
         "  起訖 %s → %s  exit=%s  牆鐘 %s" % (r["start"] or "-", r["end"] or "-", r["exit"] if r["exit"] is not None else "-（沒有 end 行：進行中或被殺）",
                                             mmss(r["wall_s"]))]
    for x in r["reuse"]:
        L.append("  沿用／跳過：" + x)
    if not r["stages"]:
        L.append("  （沒有進到測試段）" + ("；[FAIL] " + r["fail"][0] if r["fail"] else ""))
    for st in r["stages"]:
        c = st["counts"]
        L.append("  [%s] %s  耗時 %s  passed=%s failed=%s error=%s skipped=%s" % (
            st["stage"], st["status"], mmss(st["seconds"]), c.get("passed", "-"), c.get("failed", "-"), c.get("error", "-"), c.get("skipped", "-")))
        fr = st.get("first_red")
        if fr and fr.get("first_red_after_start_s") is not None:
            L.append("      第一個紅：該段 +%s；最後一個紅：+%s；第一個紅之後又白跑 %s（共 %d 筆紅）" % (
                mmss(fr["first_red_after_start_s"]), mmss(fr["last_red_after_start_s"]), mmss(fr["wasted_after_first_red_s"]), fr["reds"]))
        if st["slowest"]:
            L.append("      --durations 最慢 %d：" % min(top, len(st["slowest"])))
            for sec, kind, nid in st["slowest"][:top]:
                L.append("        %6.2fs %-8s %s" % (sec, kind, nid))
    for x in r["fail"]:
        L.append("  [FAIL] " + x)
    if r["total_line"]:
        t = r["total_line"]
        L.append("  建包自報：total=%.0fs 非e2e=%.0fs e2e=%.0fs" % (t["total"], t["not_e2e"], t["e2e"]))
    if budget and r["stages"]:
        L.append("  預算對照（<=30 分）：")
        for st in r["stages"]:
            b = BUDGET["非 e2e"] if st["stage"].startswith("非") else BUDGET["e2e"]
            if st["seconds"] is not None:
                L.append("    %-6s 實測 %s／預算 %s  %s" % (st["stage"], mmss(st["seconds"]), mmss(b),
                                                           "超出 %s" % mmss(st["seconds"] - b) if st["seconds"] > b else "在預算內"))
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=os.environ.get("TEMP") or os.environ.get("TMP") or ".")
    ap.add_argument("--glob", default="build_*.log")
    ap.add_argument("--last", type=int, default=3)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--budget", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    files = sorted(glob.glob(os.path.join(a.dir, a.glob)), key=os.path.getmtime)[-a.last:]
    if not files:
        print("找不到 %s（%s）" % (a.glob, a.dir))
        return 1
    reports = [parse_log(f, a.top) for f in files]
    if a.json:
        print(json.dumps(reports, ensure_ascii=False, indent=1))
        return 0
    for r in reports:
        print(render(r, a.top, a.budget))
    return 0


if __name__ == "__main__":
    sys.exit(main())
