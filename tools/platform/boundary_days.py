# -*- coding: utf-8 -*-
"""邊界日矩陣：標了 `date_sensitive` 的測試，用固定時鐘在「容易出事的日子」各跑一次（PLAYBOOK §G5 第 20 項）。

起因（2026-10-01，建包連敗七次，其中四次是時間相依）：跨午夜、每月 1 號的月備份保留份、換日後版本紀錄比 commit 舊、
收集與執行之間換日。這些都是「平常綠、某一天紅」——等實際跨日才發現，出貨當天就卡住。這支把那幾天提前到任何一天都能演練。

用法（任一棵 MOTRIX-PLATFORM 樹，Python 用 .venv312）：
  python tools/platform/boundary_days.py [--ref YYYY-MM-DD] [--only month_first,pre_midnight] [--list]
情境（以 --ref 所在的年月為準，預設今天）：
  month_first  當月 1 號 12:00        month_end  當月最後一天 12:00     year_end  12/31 12:00
  pre_midnight --ref 當天 23:59:00    post_midnight  隔天 00:01:00      leap_day  下一個 2/29 12:00
做法：
  1. 收集一次 `-m date_sensitive`（清單 backend/tests/date_sensitive.json ＋ 直接寫 @pytest.mark.date_sensitive 的題）⇒ 檔案清單
  2. **control**：真實時鐘跑一次。control 紅的題＝與日期無關的壞（不算邊界日紅）
  3. 每個情境：`-p fake_clock`（tools/platform/fake_clock.py，行程時鐘平移到該時刻、照常往前走）＋MOTRIX_TEST_TODAY＝該日
     ⇒ **情境紅且 control 綠** 才是「邊界日紅」，依歸屬列出＋單獨重跑指令
單程序、低優先權、不搶全機測試鎖（輕）；建包獨佔中 conftest 會拒絕（exit 2，等建包結束）。
退出碼：0 沒有邊界日紅；1 有；2 工具出錯／被建包擋下。
⚠ 假時鐘只平移本行程的 Python 時鐘（見 fake_clock.py 檔頭限制）——紅燈是「請人看」的線索，不是產品有 bug 的判決。
"""
import argparse
import calendar
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
from pre_train_check import Runner, parse_failures, owner_of   # noqa: E402

SCENARIO_NAMES = ("month_first", "month_end", "year_end", "pre_midnight", "post_midnight", "leap_day")


def next_leap_day(ref):
    y = ref.year
    while True:
        if calendar.isleap(y) and date(y, 2, 29) >= ref:
            return date(y, 2, 29)
        y += 1


def scenarios(ref):
    """⇒ [(名稱, datetime)]；純函式。"""
    noon = lambda d: datetime(d.year, d.month, d.day, 12, 0, 0)            # noqa: E731
    last = calendar.monthrange(ref.year, ref.month)[1]
    return [
        ("month_first", noon(date(ref.year, ref.month, 1))),
        ("month_end", noon(date(ref.year, ref.month, last))),
        ("year_end", noon(date(ref.year, 12, 31))),
        ("pre_midnight", datetime(ref.year, ref.month, ref.day, 23, 59, 0)),
        ("post_midnight", datetime.combine(ref + timedelta(days=1), datetime.min.time()).replace(minute=1)),
        ("leap_day", noon(next_leap_day(ref))),
    ]


def files_from_collect(out):
    """`--collect-only -q` 的輸出 ⇒ 測試檔（相對 backend/，依出現順序、去重）。"""
    files = []
    for line in (out or "").splitlines():
        m = re.match(r"^(\S+?\.py)::", line.strip().replace("\\", "/"))
        if m and m.group(1) not in files:
            files.append(m.group(1))
    return files


def judge(control_fails, scenario_fails):
    """⇒ 邊界日才紅的題（情境紅、control 綠）依出現順序。"""
    base = {f["nodeid"] for f in control_fails}
    return [f for f in scenario_fails if f["nodeid"] not in base]


def build_cmd(python, files, basetemp):
    return [python, "-m", "pytest", *files, "-m", "date_sensitive", "-q", "-rfE", "--tb=line", "-p", "no:cacheprovider",
            "--basetemp=%s" % basetemp]


def scenario_env(dt):
    return {"MOTRIX_FAKE_NOW": dt.strftime("%Y-%m-%dT%H:%M:%S"), "MOTRIX_TEST_TODAY": dt.date().isoformat(),
            "PYTHONPATH": str(HERE)}


def _rm(path):
    def _clear(func, p, _e):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    if Path(path).exists():
        shutil.rmtree(str(path), onerror=_clear)


def blocked_by_build(rc, out):
    return rc == 4 and "建包獨佔中" in out


def run_matrix(ref, only=None, runner=None, backend=None, python=None, out=print, list_only=False):
    """⇒ (exit code, 報告文字)。"""
    runner = runner or Runner()
    backend = Path(backend or REPO / "backend")
    python = python or sys.executable
    t0 = time.time()
    chosen = [s for s in scenarios(ref) if not only or s[0] in only]
    rc, o = runner.run([python, "-m", "pytest", "-m", "date_sensitive", "--collect-only", "-q", "-p", "no:cacheprovider",
                        "--basetemp=%s" % os.path.join(tempfile.gettempdir(), "motrix-pytest-boundary-collect-%d" % os.getpid())],
                       backend, low=True)
    if blocked_by_build(rc, o):
        return 2, "建包獨佔中，conftest 拒絕臨時 pytest——等建包結束再跑。"
    files = files_from_collect(o)
    if rc not in (0, 5) or not files:
        return 2, "收集不到 date_sensitive 的題（exit %s）：\n%s" % (rc, o[-600:])
    if list_only:
        return 0, "date_sensitive 測試檔 %d 個：\n  " % len(files) + "\n  ".join(files) + "\n情境：" + "、".join(
            "%s=%s" % (n, d.strftime("%Y-%m-%d %H:%M")) for n, d in chosen)
    results, control = [], []
    uniq = "%d-%s" % (os.getpid(), time.strftime("%H%M%S"))

    def one(name, extra_env):
        bt = os.path.join(tempfile.gettempdir(), "motrix-pytest-boundary-%s-%s" % (name, uniq))
        try:
            rc_, o_ = runner.run(build_cmd(python, files, bt), backend, env=extra_env, stream=False, low=True)
        finally:
            _rm(bt)
        return rc_, o_, parse_failures(o_)

    rc_c, o_c, control = one("control", {})
    if blocked_by_build(rc_c, o_c):
        return 2, "建包獨佔中，conftest 拒絕臨時 pytest——等建包結束再跑。"
    out("[control] 真實時鐘：exit %s，紅 %d 題" % (rc_c, len(control)))
    bad = False
    for name, dt in chosen:
        rc_s, o_s, fails = one(name, scenario_env(dt))
        only_here = judge(control, fails)
        unknown = rc_s != 0 and not fails                      # 非 0 卻認不出哪一題（收集錯誤／行程被殺）
        results.append((name, dt, rc_s, fails, only_here, unknown))
        out("[%s] %s：exit %s，紅 %d 題（邊界日才紅 %d）" % (name, dt.strftime("%Y-%m-%d %H:%M"), rc_s, len(fails), len(only_here)))
        bad = bad or bool(only_here) or unknown
    return (1 if bad else 0), format_report(ref, files, control, rc_c, results, time.time() - t0)


def format_report(ref, files, control, rc_c, results, runtime):
    L = ["", "═" * 72, "邊界日矩陣 ref=%s   date_sensitive 檔 %d 個   %.0f 秒" % (ref.isoformat(), len(files), runtime),
         "control（真實時鐘）：%s" % ("全綠" if rc_c == 0 and not control else "紅 %d 題（與日期無關，先修這些）" % len(control))]
    for f in control[:10]:
        L.append("   %s %s" % (f["kind"], f["nodeid"]))
    L.append("%-14s %-17s %s" % ("情境", "時刻", "結果"))
    for name, dt, rc, fails, only_here, unknown in results:
        verdict = "綠" if rc == 0 else ("紅但認不出是哪一題（輸出被截斷／收集錯誤）" if unknown else "邊界日紅 %d 題" % len(only_here) if only_here else "紅（都與 control 相同）")
        L.append("%-14s %-17s %s" % (name, dt.strftime("%Y-%m-%d %H:%M"), verdict))
    first = None
    for name, dt, rc, fails, only_here, unknown in results:
        if only_here:
            L.append("── %s（%s）邊界日才紅：" % (name, dt.strftime("%Y-%m-%d %H:%M")))
            for f in only_here[:12]:
                L.append("   [%s] %s%s" % (owner_of(f["nodeid"]), f["nodeid"], " — " + f["msg"][:100] if f["msg"] else ""))
            if len(only_here) > 12:
                L.append("   … 另 %d 題" % (len(only_here) - 12))
            first = first or (only_here[0]["nodeid"], scenario_env(dt))
    if first:
        env = first[1]
        L.append("單獨重跑（PowerShell，在 backend\\ 底下）：$env:PYTHONPATH='%s'; $env:MOTRIX_FAKE_NOW='%s'; $env:MOTRIX_TEST_TODAY='%s'; "
                 "python -m pytest -p fake_clock \"%s\" -v" % (env["PYTHONPATH"], env["MOTRIX_FAKE_NOW"], env["MOTRIX_TEST_TODAY"], first[0]))
    return "\n".join(L)


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref", default=None, help="YYYY-MM-DD（預設今天）")
    ap.add_argument("--only", default="", help="逗號分隔的情境名")
    ap.add_argument("--list", action="store_true", help="只列出會跑的檔與情境")
    ap.add_argument("--python", default=sys.executable)
    a = ap.parse_args(argv)
    ref = datetime.strptime(a.ref, "%Y-%m-%d").date() if a.ref else date.today()
    only = [x.strip() for x in a.only.split(",") if x.strip()]
    bad = [x for x in only if x not in SCENARIO_NAMES]
    if bad:
        ap.error("未知情境：%s（可用：%s）" % (",".join(bad), ",".join(SCENARIO_NAMES)))
    code, rep = run_matrix(ref, only or None, python=a.python, list_only=a.list)
    print(rep)
    return code


if __name__ == "__main__":
    sys.exit(main())
