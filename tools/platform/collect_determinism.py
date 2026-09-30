# -*- coding: utf-8 -*-
"""收集決定性檢查：`pytest --collect-only -q` 連跑兩次（間隔 2 秒）比對測試 id；不同 ⇒ exit 1 並印出差異的 id。

起因（2026-10-01，第二十七班建包）：測試的參數 id 帶「現在時間」（zip writestr 預設時間戳、date.today()、uuid、random）⇒ xdist 各 worker
收集到不同的 id ⇒ pytest-xdist 拒絕開跑（或跑到一半才炸）。這在 20 分鐘的測試階段之前幾十秒就查得到——fail fast。
建包腳本 build_deploy_package.ps1 在登記獨佔、跑測試之前呼叫（-NoCollectCheck 可略過）。

用法：python tools/platform/collect_determinism.py [--backend <dir>] [--interval 2] [--python PY] [-- <多給 pytest 的參數>]
退出碼：0 兩次相同；1 不同（印差異）；2 收集本身失敗（exit≠0/5 或沒收到任何 id）。收集是 `--collect-only`，不搶測試鎖、不被建包守門擋。
"""
import argparse
import os
import re
import shutil
import stat
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
from pre_train_check import Runner   # noqa: E402

_ID = re.compile(r"^\S+\.py::\S")


def ids_of(out):
    """`--collect-only -q` 的輸出 ⇒ 測試 id 清單（保留順序與重複）。"""
    return [l.strip() for l in (out or "").splitlines() if _ID.match(l.strip())]


def diff_ids(a, b):
    """⇒ (只在第一次, 只在第二次, 順序不同)。多重集合比較（重複的 id 也算）。"""
    from collections import Counter
    ca, cb = Counter(a), Counter(b)
    only_a = sorted((ca - cb).elements())
    only_b = sorted((cb - ca).elements())
    order_differs = not only_a and not only_b and a != b
    return only_a, only_b, order_differs


def format_diff(only_a, only_b, order_differs, limit=30):
    L = []
    if only_a:
        L.append("只在第一次收集（%d）：" % len(only_a))
        L += ["  - " + x for x in only_a[:limit]] + (["  … 另 %d" % (len(only_a) - limit)] if len(only_a) > limit else [])
    if only_b:
        L.append("只在第二次收集（%d）：" % len(only_b))
        L += ["  + " + x for x in only_b[:limit]] + (["  … 另 %d" % (len(only_b) - limit)] if len(only_b) > limit else [])
    if order_differs:
        L.append("兩次收集的 id 集合相同，但順序不同（xdist 依順序分派 ⇒ 同樣會出問題）")
    if L:
        L.append("⇒ 參數 id 帶了『現在時間／隨機值』：找出這些 id 的 parametrize 來源（date.today()、datetime.now()、time.time()、uuid、"
                 "random、zip writestr 沒給 date_time）改成固定值，或改在測試函式內取值。")
    return "\n".join(L)


def _rm(path):
    def _clear(func, p, _e):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    if Path(path).exists():
        shutil.rmtree(str(path), onerror=_clear)


def collect(runner, python, backend, extra, tag):
    bt = os.path.join(tempfile.gettempdir(), "motrix-pytest-collectcheck-%d-%s" % (os.getpid(), tag))
    try:
        rc, out = runner.run([python, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "--basetemp=%s" % bt, *extra],
                             backend, low=True)
    finally:
        _rm(bt)
    return rc, out


def check(runner, python, backend, extra=(), interval=2.0, sleep=time.sleep, out=print):
    """⇒ exit code（0／1／2）。"""
    rc1, o1 = collect(runner, python, backend, list(extra), "a")
    a = ids_of(o1)
    if rc1 not in (0, 5) or not a:
        out("收集失敗（exit %s，收到 %d 個 id）：\n%s" % (rc1, len(a), o1[-800:]))
        return 2
    sleep(interval)
    rc2, o2 = collect(runner, python, backend, list(extra), "b")
    b = ids_of(o2)
    if rc2 not in (0, 5) or not b:
        out("第二次收集失敗（exit %s，收到 %d 個 id）：\n%s" % (rc2, len(b), o2[-800:]))
        return 2
    only_a, only_b, order = diff_ids(a, b)
    if only_a or only_b or order:
        out("收集不決定：兩次 `--collect-only`（間隔 %.0f 秒）的測試 id 不同：\n%s" % (interval, format_diff(only_a, only_b, order)))
        return 1
    out("收集決定：兩次收集的 %d 個測試 id 完全相同（間隔 %.0f 秒）。" % (len(a), interval))
    return 0


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    argv = list(sys.argv[1:] if argv is None else argv)
    extra = []
    if "--" in argv:
        i = argv.index("--")
        argv, extra = argv[:i], argv[i + 1:]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", default=str(REPO / "backend"))
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--python", default=sys.executable)
    a = ap.parse_args(argv)
    return check(Runner(), a.python, Path(a.backend), extra, a.interval)


if __name__ == "__main__":
    sys.exit(main())
