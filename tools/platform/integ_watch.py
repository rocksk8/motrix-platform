# -*- coding: utf-8 -*-
"""整合分支的背景檢查（SPEEDUP-PREPUSH-T50 §3；第 51 班）：**只是狀態回報**。

每個新 commit（`.githooks/post-commit`，只在 train/* 分支）排一次：去抖 60 秒 → 確認機器閒著 → 跑
prepush_check 的整合模式（A0 check_only＋全模組 changelog＋便宜守門檔），結果寫
`tools/platform/full_results/integ_watch/{status.json,<sha>.json}`（full_results 已 gitignore）。
**絕不**：寫 run-stage／建包用的任何「綠燈紀錄」、取號、重產、commit、push、改追蹤檔、通知別人。
整合者想看就讀 status.json；紅燈只是提示，閘門仍以官方 run-stage 為準。

用法：integ_watch.py --spawn   （hook 呼叫：立刻返回，分離行程跑 --once）
      integ_watch.py --once    （前景跑一次；--no-wait 跳過去抖，供測試／手動）
      integ_watch.py --status  （印出最新狀態）
[單位] tools:integ_watch   [層] 工具   [穩定度] 內部
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

import nowindow  # noqa: E402

OUT = REPO / "tools" / "platform" / "full_results" / "integ_watch"
DEBOUNCE_SEC = 60
MIN_FREE_GB = 4.0


def _git(*args):
    r = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout.strip() if r.returncode == 0 else ""


def head_sha():
    return _git("rev-parse", "HEAD")


def free_gb():
    try:
        import psutil
        return psutil.virtual_memory().available / 2 ** 30
    except Exception:                                                        # noqa: BLE001
        return None


def other_pytest_running():
    """⇒ True/False/None（None＝判不了；呼叫端當『不確定』而照樣跑，狀態檔註明）。"""
    try:
        import psutil
    except Exception:                                                        # noqa: BLE001
        return None
    me = os.getpid()
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            cl = " ".join(p.info.get("cmdline") or [])
        except Exception:                                                    # noqa: BLE001
            continue
        if p.info["pid"] != me and "pytest" in cl and "integ_watch" not in cl:
            return True
    return False


def write_status(sha, **kw):
    OUT.mkdir(parents=True, exist_ok=True)
    data = dict(sha=sha, at=time.strftime("%Y-%m-%d %H:%M:%S"), **kw)
    for name in ("status.json", "%s.json" % sha[:9]):
        (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def once(wait=True, runner=None):
    sha = head_sha()
    if not sha:
        return write_status("unknown", state="error", note="讀不到 HEAD")
    if wait:
        deadline = time.time() + 600
        stable_since = time.time()
        while time.time() - stable_since < DEBOUNCE_SEC:
            time.sleep(5)
            cur = head_sha()
            if cur != sha:                                                    # 新 commit 來了：這一輪作廢，新的 hook 會再排
                return write_status(sha, state="superseded", note="去抖期間 HEAD 變成 %s" % cur[:9])
            if time.time() > deadline:
                break
    busy = other_pytest_running()
    gb = free_gb()
    if busy:
        return write_status(sha, state="skipped", note="機器上有別的 pytest 在跑（上限 2 組、閘門優先）")
    if gb is not None and gb < MIN_FREE_GB:
        return write_status(sha, state="skipped", note="可用記憶體 %.1f GB < %.0f GB" % (gb, MIN_FREE_GB))
    import prepush_check as PP
    polite_run.reason = ""
    code, text, data = PP.run(REPO, None, None, False, True, runner or polite_run)           # 預算＝prepush_check 的整合模式預設（300 秒）
    if polite_run.reason:                                                                    # 測試途中別的 pytest／記憶體吃緊 ⇒ 讓出，不當綠
        return write_status(sha, state="yielded", exit=code, reds=[x for x in data["findings"] if not x["msg"].startswith("未能檢查")],
                            warnings=data["warnings"], fails=data["fails"], tests=len(data["tests"]), note=polite_run.reason,
                            summary=text.splitlines()[-1])
    return write_status(sha, state="done", exit=code, reds=[x for x in data["findings"] if not x["msg"].startswith("未能檢查")],
                        warnings=data["warnings"], fails=data["fails"], tests=len(data["tests"]),
                        note=("psutil 不可用，沒檢查別的 pytest" if busy is None else "") or "只是提示；閘門以官方 run-stage 為準", summary=text.splitlines()[-1])


def polite_run(repo, tests, timeout):
    """逐檔跑（每檔一個 pytest 行程）；**每一檔開跑前**再查一次『別的 pytest 在跑』與可用記憶體——閘門（run-stage）在這一輪中途才開跑，
    就讓出（回 INCOMPLETE＝未完成，不可當綠；原因記在 polite_run.reason），不拖慢它。⇒ (rc, output, seconds)。"""
    import prepush_check as PP
    t0 = time.time()
    outs, rc_all = [], 0
    for item in tests:
        busy, gb = other_pytest_running(), free_gb()
        if busy:
            polite_run.reason = "測試途中偵測到別的 pytest 在跑（閘門優先）；已讓出，剩下的檔沒跑（已跑 %d／%d 個檔）" % (len(outs), len(tests))
            return PP.INCOMPLETE, chr(10).join(outs), time.time() - t0
        if gb is not None and gb < MIN_FREE_GB:
            polite_run.reason = "測試途中可用記憶體 %.1f GB < %.0f GB；已讓出（已跑 %d／%d 個檔）" % (gb, MIN_FREE_GB, len(outs), len(tests))
            return PP.INCOMPLETE, chr(10).join(outs), time.time() - t0
        left = timeout - (time.time() - t0)
        if left < 5:
            return PP.INCOMPLETE, chr(10).join(outs), time.time() - t0
        rc, out, _secs = PP.run_tests(repo, [item], left)
        outs.append(out)
        if rc == PP.INCOMPLETE:
            return PP.INCOMPLETE, chr(10).join(outs), time.time() - t0
        if rc not in (0,) and rc_all == 0:
            rc_all = rc
    return rc_all, chr(10).join(outs), time.time() - t0


polite_run.reason = ""


def spawn():
    flags = 0
    if os.name == "nt":
        flags = (getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                 | getattr(subprocess, "CREATE_NO_WINDOW", 0) | 0x00004000)    # BELOW_NORMAL_PRIORITY_CLASS
    subprocess.Popen([sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--once"], cwd=str(REPO), creationflags=flags,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--spawn", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--no-wait", action="store_true")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args(argv)
    if a.status:
        p = OUT / "status.json"
        print(p.read_text(encoding="utf-8") if p.is_file() else "（還沒有狀態）")
        return 0
    if a.spawn:
        spawn()
        return 0
    if a.once:
        d = once(wait=not a.no_wait)
        print(json.dumps(d, ensure_ascii=False))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    nowindow.install()                                   # 入口先裝（背景執行不彈主控台視窗）
    sys.exit(main())
