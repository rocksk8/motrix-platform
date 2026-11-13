# -*- coding: utf-8 -*-
"""偶發排行榜（T84，2026-11-13）：記下「哪些題在建包／全跑時紅了又在隔離重跑中變綠」，累積成排行，讓人知道先查哪一題的根因。

**只記錄、不影響任何結果**（硬規則）：
- 排行榜不參與 `known_flakes.decide`、不影響建包綠／紅、不會自動登記或延期偶發題（known_flakes.json 只由人登記）。
- 唯一的寫入點是 `flaky_retry.main()` 末尾的一段 try/except（任何例外吞掉）；除此之外沒有任何檔案引用本模組。
- 本模組不讀 known_flakes、failfast、build_test_reuse；只讀寫自己的 JSONL。

檔案：`tools/platform/flaky_leaderboard.jsonl`（git 忽略；放在 git common dir 的上層，跟 fail_stream 一樣所有 worktree 共用一份）。
  環境變數 MOTRIX_FLAKY_LEADERBOARD 可指到別的檔（測試用）。每行一筆：`{t, run, stage, nodeid, attempts, passed}`。
  `passed`＝重跑中有一次綠（疑似偶發）；`false`＝每次都紅（真紅，不算偶發）。
  大小有上限：超過 MAX_BYTES 就丟掉超過 KEEP_DAYS 天的、再只留最後 MAX_LINES 筆（整檔以 tmp＋replace 換掉，失敗就算了）。

用法：
  python tools/platform/flaky_leaderboard.py [--days 7|30] [--json] [--top N] [--path F]
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
PATH_ENV = "MOTRIX_FLAKY_LEADERBOARD"
FILE_NAME = "flaky_leaderboard.jsonl"
MAX_BYTES = 512 * 1024
MAX_LINES = 3000
KEEP_DAYS = 90
TS_FMT = "%Y-%m-%dT%H:%M:%S"


def default_path():
    env = os.environ.get(PATH_ENV)
    if env:
        return Path(env)
    sys.path.insert(0, str(HERE))
    try:
        import fail_stream
        return fail_stream.stream_dir().parent / FILE_NAME
    except Exception:  # noqa: BLE001  找不到 git／fail_stream ⇒ 退回本目錄
        return HERE / FILE_NAME


def make_events(results, run_id, stage, now=None):
    """flaky_retry 的重跑結果 ⇒ 要記的列。results＝[{nodeid, attempts:[exit…], passed}]。"""
    t = (now or datetime.now()).strftime(TS_FMT)
    return [{"t": t, "run": str(run_id), "stage": str(stage), "nodeid": str(r.get("nodeid") or ""),
             "attempts": list(r.get("attempts") or []), "passed": bool(r.get("passed"))}
            for r in (results or []) if r.get("nodeid")]


def _trim(path, now):
    """超過大小上限 ⇒ 丟掉太舊的、再只留最後 MAX_LINES 筆。整檔換掉；任何失敗都算了（下次再說）。"""
    try:
        if path.stat().st_size <= MAX_BYTES:
            return
        cutoff = (now - timedelta(days=KEEP_DAYS)).strftime(TS_FMT)
        kept = [ln for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()
                if ln.strip() and _line_time(ln) >= cutoff]
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text("\n".join(kept[-MAX_LINES:]) + "\n", encoding="utf-8")
        os.replace(str(tmp), str(path))
    except OSError:
        pass


def _line_time(line):
    try:
        return str(json.loads(line).get("t") or "")
    except ValueError:
        return ""                    # 讀不懂的行：時間空字串 ⇒ 修剪時被丟掉


def record(results, run_id, stage, path=None, now=None):
    """追加一批列到排行榜檔。沒東西就什麼都不做。呼叫端（flaky_retry）把整個呼叫包在 try/except 裡；這裡本身也不吞例外，
    好讓測試看得到真的壞了（「吞掉」只在呼叫點做一次）。"""
    now = now or datetime.now()
    events = make_events(results, run_id, stage, now)
    if not events:
        return 0
    p = Path(path) if path else default_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    data = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events).encode("utf-8")
    fd = os.open(str(p), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    _trim(p, now)
    return len(events)


def load_events(path=None):
    p = Path(path) if path else default_path()
    out = []
    try:
        for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                e = json.loads(ln)
            except ValueError:
                continue
            if isinstance(e, dict) and e.get("nodeid") and e.get("t"):
                out.append(e)
    except OSError:
        pass
    return out


def aggregate(events, days, now=None):
    """近 days 天的事件 ⇒ 排行（疑似偶發次數多的在前；同次數看總紅次數、再看 nodeid 字母序）。
    每題：flaky（重跑中有綠）、hard_fail（每次都紅）、runs（涉及幾個 run）、stages、first／last。"""
    now = now or datetime.now()
    cutoff = (now - timedelta(days=days)).strftime(TS_FMT)
    rows = {}
    for e in events:
        if str(e["t"]) < cutoff:
            continue
        r = rows.setdefault(e["nodeid"], {"nodeid": e["nodeid"], "flaky": 0, "hard_fail": 0, "runs": set(), "stages": set(),
                                          "first": e["t"], "last": e["t"]})
        r["flaky" if e.get("passed") else "hard_fail"] += 1
        r["runs"].add(e.get("run", ""))
        r["stages"].add(e.get("stage", ""))
        r["first"], r["last"] = min(r["first"], e["t"]), max(r["last"], e["t"])
    out = []
    for r in rows.values():
        out.append({"nodeid": r["nodeid"], "flaky": r["flaky"], "hard_fail": r["hard_fail"], "runs": len(r["runs"]),
                    "stages": sorted(s for s in r["stages"] if s), "first": r["first"], "last": r["last"]})
    out.sort(key=lambda x: (-x["flaky"], -(x["flaky"] + x["hard_fail"]), x["nodeid"]))
    return out


def render(rows, days):
    if not rows:
        return "近 %d 天沒有偶發紀錄。" % days
    lines = ["近 %d 天的偶發排行（疑似偶發＝紅了、隔離重跑變綠；真紅＝每次都紅。只是紀錄，不影響建包結果）：" % days,
             "%4s %4s %4s  %s" % ("偶發", "真紅", "run", "題目（最後一次）")]
    for r in rows:
        lines.append("%4d %4d %4d  %s（%s）" % (r["flaky"], r["hard_fail"], r["runs"], r["nodeid"], r["last"]))
    return "\n".join(lines)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=7, help="看近幾天（7 或 30；預設 7）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--top", type=int, default=0, help="只列前 N 題（0＝全部）")
    ap.add_argument("--path", help="排行榜檔（預設 tools/platform/flaky_leaderboard.jsonl）")
    a = ap.parse_args(argv)
    if a.days < 1:
        ap.error("--days 要 ≥ 1")
    rows = aggregate(load_events(a.path), a.days)
    if a.top > 0:
        rows = rows[:a.top]
    if a.json:
        print(json.dumps({"days": a.days, "rows": rows}, ensure_ascii=False, indent=1))
    else:
        print(render(rows, a.days))
    return 0


if __name__ == "__main__":
    sys.exit(main())
