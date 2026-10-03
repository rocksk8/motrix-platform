# -*- coding: utf-8 -*-
"""測試時間預算警報（T35 item 4；只警告，永不擋建包）。

為什麼看 worker 秒、不看牆鐘：牆鐘隨機器負載亂跳（同一棵樹 -n2 下 55 分、-n4 下 25 分），警報會 flapping；
worker 秒＝各題 junit time 加總，與負載的關係小得多，而且能指到「是哪一個檔變慢／新增」。
2026-09-27→10-02 實測：測試數 +56%、全量時間 +50%，每題約 190 ms 沒變慢 ⇒ 成長來自測試數量，所以報告同時印題數與每題 ms。

規則（都是警告，記進 build_history.jsonl 的 tests.time_budget）：
  new_file     基準裡沒有的測試檔、worker 秒 > NEW_FILE_WS（預設 30）
  grown_file   基準裡有、增加 > NEW_FILE_WS 秒且 > 1.5 倍
  total_growth 全部 worker 秒 > 基準 × (1+TOTAL_PCT%)（預設 5%），而且 changelog 前 120 行沒有一行「- 時間預算：<理由>」
基準：tools/platform/time_budget_baseline.json（進 git）；每班列車由整合者用 `--update-baseline` 重量（junit 來自該班全量）。

用法：
  python tools/platform/time_budget.py check <junit.xml>... [--json] [--baseline P] [--changelog P]
  python tools/platform/time_budget.py update-baseline <junit.xml>... [--note 文字]
退出碼：永遠 0（警告用）；讀不到 junit／基準時印出原因仍回 0。
"""
import argparse
import collections
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BASELINE = HERE / "time_budget_baseline.json"
CHANGELOG = REPO / "docs" / "quick" / "changelog.md"
NEW_FILE_WS = 30.0
GROWN_FACTOR = 1.5
TOTAL_PCT = 5.0
JUSTIFY_RE = re.compile(r"^- 時間預算[:：]\s*\S", re.M)
JUSTIFY_LINES = 120


def classname_to_file(classname):
    """junit classname（tests.platform.test_x[.TestClass]）→ repo 相對路徑（backend/…/test_x.py）。"""
    parts = [p for p in (classname or "").split(".") if p]
    keep = []
    for p in parts:
        if p[:1].isupper():                      # 類別名：檔名到上一段為止
            break
        keep.append(p)
    return "backend/" + "/".join(keep) + ".py" if keep else ""


def seconds_by_file(junit_paths):
    """⇒ ({檔: worker 秒}, 題數)。多份 junit（非 e2e＋e2e）合併。"""
    per = collections.defaultdict(float)
    n = 0
    for p in junit_paths:
        root = ET.parse(str(p)).getroot()
        for c in root.iter("testcase"):
            f = classname_to_file(c.get("classname", ""))
            if not f:
                continue
            per[f] += float(c.get("time", 0) or 0)
            n += 1
    return {k: round(v, 2) for k, v in per.items()}, n


def load_baseline(path=None):
    p = Path(path or BASELINE)
    return json.loads(p.read_text(encoding="utf-8"))


def has_justification(changelog_text):
    head = "\n".join(changelog_text.splitlines()[:JUSTIFY_LINES])
    return bool(JUSTIFY_RE.search(head))


def check(current, n_tests, baseline, changelog_text="", new_file_ws=NEW_FILE_WS, total_pct=TOTAL_PCT):
    """⇒ {"alarms": [...], "total_ws", "baseline_ws", "tests", "baseline_tests", "ms_per_test", "baseline_ms_per_test"}。"""
    base_files = baseline.get("files", {})
    alarms = []
    for f, ws in sorted(current.items(), key=lambda kv: -kv[1]):
        b = base_files.get(f)
        if b is None:
            if ws > new_file_ws:
                alarms.append({"kind": "new_file", "file": f, "ws": ws, "baseline": None})
        elif ws - b > new_file_ws and ws > GROWN_FACTOR * b:
            alarms.append({"kind": "grown_file", "file": f, "ws": ws, "baseline": b})
    total = round(sum(current.values()), 1)
    btotal = float(baseline.get("total_ws") or sum(base_files.values()))
    btests = int(baseline.get("tests") or 0)
    res = {"total_ws": total, "baseline_ws": round(btotal, 1), "tests": n_tests, "baseline_tests": btests,
           "ms_per_test": round(1000.0 * total / n_tests, 1) if n_tests else None,
           "baseline_ms_per_test": round(1000.0 * btotal / btests, 1) if btests else None, "justified": False}
    if btotal and total > btotal * (1 + total_pct / 100.0):
        res["justified"] = has_justification(changelog_text)
        if not res["justified"]:
            alarms.append({"kind": "total_growth", "ws": total, "baseline": round(btotal, 1),
                           "pct": round(100.0 * (total / btotal - 1), 1)})
    res["alarms"] = alarms
    return res


def format_report(r):
    out = ["[時間預算] worker 秒 %.0f（基準 %.0f）｜題數 %d（基準 %d）｜每題 %s ms（基準 %s ms）" % (
        r["total_ws"], r["baseline_ws"], r["tests"], r["baseline_tests"], r["ms_per_test"], r["baseline_ms_per_test"])]
    if not r["alarms"]:
        out.append("  無警報" + ("（總量成長已有 changelog『- 時間預算：』理由）" if r.get("justified") else ""))
    for a in r["alarms"]:
        if a["kind"] == "total_growth":
            out.append("  ⚠ 總量成長 %.1f%%（%.0f → %.0f worker 秒）且 changelog 前 %d 行沒有『- 時間預算：<理由>』" % (
                a["pct"], a["baseline"], a["ws"], JUSTIFY_LINES))
        elif a["kind"] == "new_file":
            out.append("  ⚠ 新測試檔 %s：%.0f worker 秒（> %.0f）" % (a["file"], a["ws"], NEW_FILE_WS))
        else:
            out.append("  ⚠ %s：%.0f 秒（基準 %.0f，增加 > %.0f 且 > %.1f 倍）" % (a["file"], a["ws"], a["baseline"], NEW_FILE_WS, GROWN_FACTOR))
    return "\n".join(out)


def run_check(junits, baseline_path=None, changelog_path=None):
    """建包呼叫的入口：任何錯誤都回 {"error": 原因}，不丟例外（警告機制不可擋建包）。"""
    try:
        cur, n = seconds_by_file(junits)
        base = load_baseline(baseline_path)
        cl = Path(changelog_path or CHANGELOG)
        text = cl.read_text(encoding="utf-8") if cl.exists() else ""
        return check(cur, n, base, text)
    except Exception as e:                       # noqa: BLE001 — 警告用，不擋
        return {"error": "%s: %s" % (type(e).__name__, e), "alarms": []}


def update_baseline(junits, note="", path=None):
    cur, n = seconds_by_file(junits)
    data = {"_doc": "T35 時間預算基準（worker 秒＝junit time 加總；由 time_budget.py update-baseline 產生）",
            "measured_at": time.strftime("%Y-%m-%d %H:%M"), "note": note, "tests": n,
            "total_ws": round(sum(cur.values()), 1), "files": dict(sorted(cur.items()))}
    Path(path or BASELINE).write_text(json.dumps(data, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    return data


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                        # noqa: BLE001
            pass
    ap = argparse.ArgumentParser(description="測試時間預算警報（warn-only）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("junit", nargs="+")
    c.add_argument("--baseline")
    c.add_argument("--changelog")
    c.add_argument("--json", action="store_true")
    u = sub.add_parser("update-baseline")
    u.add_argument("junit", nargs="+")
    u.add_argument("--note", default="")
    u.add_argument("--baseline")
    a = ap.parse_args(argv)
    if a.cmd == "update-baseline":
        d = update_baseline(a.junit, a.note, a.baseline)
        print("基準已更新：%d 題、%.0f worker 秒、%d 檔" % (d["tests"], d["total_ws"], len(d["files"])))
        return 0
    r = run_check(a.junit, a.baseline, a.changelog)
    print(json.dumps(r, ensure_ascii=False) if a.json else (format_report(r) if "error" not in r else "[時間預算] 略過：" + r["error"]))
    return 0                                     # 警告用：永遠 0


if __name__ == "__main__":
    sys.exit(main())
