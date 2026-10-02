# -*- coding: utf-8 -*-
"""建包的偶發重跑（2026-09-30 使用者「安排建包的優化方式，避免非正常情況的失敗」；政策與正反論證見 PLAYBOOK §D-建包）。

建包某一段 pytest 紅了 ⇒ 由 build_deploy_package.ps1 呼叫：
  python tools/platform/flaky_retry.py --run-id R --stage S --exit-code N --output-file O --python PY
         --basetemp-prefix P --result-out J [--attempts 2] [--max-failed 5] [--registry F]
1. 紅的是哪幾題：fail_stream 的 JSONL（同 run-id、同 stage）∪ pytest 輸出的 `FAILED／ERROR <nodeid>` 行。
2. 不重跑、直接擋：exit code 不是 1（中斷、內部錯誤、用法錯、沒題）、有收集錯誤、紅的題超過 --max-failed
   （一次紅很多題是真的壞了，不是偶發；重跑只是浪費時間）、認不出任何一題（fail closed）。
3. 每一題**單獨、循序**重跑（單程序、不帶 -n），最多 --attempts 次，一過就停。
4. 判定交給 known_flakes.decide：重跑通過且已登記未過期 ⇒ exit 0（建包繼續，記 flaky_retried）；其餘 exit 1。
結果寫 --result-out（JSON），並在 fail_stream 同一個 run 檔附加 `type=flaky_retried／flaky_blocked` 各一筆。
**只重跑紅的題、不改測試結果本身**：原本那一段的紅照樣留在 fail_stream 與建包輸出裡。
"""
import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import zlib
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fail_stream  # noqa: E402
import known_flakes  # noqa: E402

BACKEND = HERE.parents[1] / "backend"
ATTEMPT_TIMEOUT = 15 * 60
# pytest -rfE 摘要行只長 `FAILED path.py::t - msg`／`ERROR path.py - msg`；日誌行 `ERROR    logger:file.py:200 msg` 不是（2026-10-01 第29班：被當成收集錯誤，擋掉偶發重跑）
_LINE_RE = re.compile(r"^(FAILED|ERROR)\s+([\w./\-]+\.py(?:::\S+)?)(?:\s+-\s.*)?$")


def read_stream(path, stage):
    out = []
    try:
        for raw in Path(path).read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(raw)
            except ValueError:
                continue
            if rec.get("stage", "") == stage:
                out.append(rec)
    except OSError:
        pass
    return out


def failed_nodeids(stream_records, output_text):
    """⇒ (nodeids 依出現順序去重, 擋下的原因清單)。"""
    ids, blockers = [], []

    def add(nid):
        if nid not in ids:
            ids.append(nid)

    for rec in stream_records:
        if rec.get("type") != "fail":
            continue
        if rec.get("when") == "collect":
            blockers.append("收集錯誤：%s" % rec.get("nodeid"))
        elif rec.get("nodeid"):
            add(rec["nodeid"])
    for line in (output_text or "").splitlines():
        m = _LINE_RE.match(line.strip())
        if not m:
            continue
        nid = m.group(2)
        if "::" not in nid:                 # `ERROR path.py - ImportError` ＝收集錯誤
            blockers.append("收集錯誤：%s" % nid)
        else:
            add(nid)
    return ids, blockers


def precheck(exit_code, ids, blockers, max_failed):
    """不值得重跑的情形 ⇒ 擋下的訊息清單（空＝可以重跑）。"""
    msgs = list(dict.fromkeys(blockers))
    if exit_code != 1:
        msgs.append("pytest 結束碼 %s（1＝有題目紅才重跑；2 中斷、3 內部錯誤、4 用法、5 沒題）——不重跑" % exit_code)
    if len(ids) > max_failed:
        msgs.append("紅了 %d 題（上限 %d）——一次紅這麼多不是偶發，不重跑" % (len(ids), max_failed))
    if not ids and not msgs:
        msgs.append("結束碼 1 但認不出任何一題（輸出被截斷或行程被殺）——無法確認驗過，不重跑")
    return msgs


def retry_all(ids, attempts, runner):
    """每題最多 attempts 次，過了就停。runner(nodeid, attempt) ⇒ exit code。"""
    results = []
    for nid in ids:
        codes = []
        for k in range(1, attempts + 1):
            codes.append(runner(nid, k))
            if codes[-1] == 0:
                break
        results.append({"nodeid": nid, "attempts": codes, "passed": bool(codes) and codes[-1] == 0})
    return results


def _rm(path):
    def _clear(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    if Path(path).exists():
        shutil.rmtree(str(path), onerror=_clear)


def make_runner(python, basetemp_prefix, stage, timeout=ATTEMPT_TIMEOUT):
    def run(nid, attempt):
        idx = zlib.crc32(nid.encode("utf-8")) % 100000
        bt = "%s-%s-%05d-%d" % (basetemp_prefix, stage, idx, attempt)
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join([str(HERE)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
        env[fail_stream.STAGE_ENV] = stage + "-retry"
        cmd = [python, "-m", "pytest", nid, "-q", "-rf", "-p", "no:cacheprovider", "-p", "fail_stream", "--basetemp=%s" % bt]
        print("[重跑 %d] %s" % (attempt, nid), flush=True)
        t0 = time.time()
        proc = subprocess.Popen(cmd, cwd=str(BACKEND), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            out, _ = proc.communicate(timeout=timeout)
            code = proc.returncode
        except subprocess.TimeoutExpired:
            # 只結束**自己起的**這一個子行程樹
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
            out, _ = proc.communicate()
            code = 124
        finally:
            _rm(bt)
        text = (out or b"").decode("utf-8", errors="replace")
        print("  ⇒ exit %s（%.0f 秒）" % (code, time.time() - t0), flush=True)
        if code != 0:
            print("\n".join("    " + l for l in text.splitlines()[-15:]), flush=True)
        return code
    return run


def append_stream(path, rec):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, (json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8"))
        finally:
            os.close(fd)
    except OSError as e:
        print("[flaky_retry] 寫不進 fail_stream（%r）" % e)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--stage", required=True)
    ap.add_argument("--exit-code", type=int, required=True)
    ap.add_argument("--output-file")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--basetemp-prefix", required=True)
    ap.add_argument("--result-out", required=True)
    ap.add_argument("--attempts", type=int, default=2)
    ap.add_argument("--max-failed", type=int, default=5)
    ap.add_argument("--registry")
    a = ap.parse_args(argv)
    stream = fail_stream.stream_dir() / (a.run_id + ".jsonl")
    output = ""
    if a.output_file:
        try:
            output = Path(a.output_file).read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            output = ""
    ids, blockers = failed_nodeids(read_stream(stream, a.stage), output)
    msgs = precheck(a.exit_code, ids, blockers, a.max_failed)
    results = []
    if msgs:
        ok, flaky = False, []
    else:
        print("[偶發重跑] %s 段紅 %d 題 ⇒ 逐題單獨重跑（最多 %d 次）" % (a.stage, len(ids), a.attempts), flush=True)
        results = retry_all(ids, a.attempts, make_runner(a.python, a.basetemp_prefix, a.stage))
        entries, problems = known_flakes.load(a.registry)
        if problems:
            ok, flaky, msgs = False, [], problems
        else:
            ok, flaky, msgs = known_flakes.decide(results, entries, date.today())
    res = {"stage": a.stage, "run": a.run_id, "exit_code": a.exit_code, "failed": ids, "results": results,
           "ok": ok, "flaky_retried": flaky, "messages": msgs}
    Path(a.result_out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    append_stream(stream, {"type": "flaky_retried" if ok else "flaky_blocked", "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                           "run": a.run_id, "stage": a.stage, "nodeid": ",".join(ids), "when": "retry", "module": "core",
                           "modules": ["core"], "summary": ("; ".join(f["nodeid"] for f in flaky) if ok else " | ".join(msgs))[:500],
                           "results": results})
    if ok:
        print("[偶發重跑] 通過：%d 題重跑綠且已登記（flaky_retried）——繼續打包" % len(flaky))
        for f in flaky:
            print("  %s（重跑 %s；%s，%s 到期）" % (f["nodeid"], f["attempts"], f["ticket"], f["expires"]))
        return 0
    print("[偶發重跑] 擋下：")
    for m in msgs:
        print("  " + m)
    return 1


if __name__ == "__main__":
    try:                                                              # 背景執行不彈視窗（tools/platform/nowindow.py；MOTRIX_SHOW_WINDOWS=1 可關）
        import sys as _s, pathlib as _p
        _s.path.insert(0, str(_p.Path(__file__).resolve().parents[1] / "tools" / "platform"))
        import nowindow as _nw
        _nw.install()
    except ImportError:
        pass
    sys.exit(main())
