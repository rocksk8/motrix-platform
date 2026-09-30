# -*- coding: utf-8 -*-
"""失敗先行出 log：列車／全量／差異跑的當下，每一題失敗立刻寫進 JSONL，讓別的視窗不必等整輪結束就能開始處理自己模組的失敗。

（使用者 2026-09-30：「列車是否能改成有失敗錯誤先行出log，讓視窗能同步處理」；PLAYBOOK §G-瓶頸的第一個實例。）

## 這是 pytest plugin（`modtest` 所有模式自動以 `-p fail_stream` 載入；也可手動 `pytest -p fail_stream`，需 tools/platform 在 PYTHONPATH）
每一題失敗**當下**（含 setup／teardown error、collection error、xdist worker 掛掉）：
  ① stdout 立即印一行  `FAIL-EARLY <nodeid> <模組> <一行錯誤摘要>`
  ② 以單次 append 寫一行 JSON 到  <主工作樹>/tools/platform/fail_stream/<run-id>.jsonl
     欄位：type(fail|node_down|aborted|summary)、seq、t、nodeid、when(setup|call|teardown|collect)、module、modules、summary、longrepr（截 4KB）、worker
  ③ run 開始印 `FAIL-STREAM run=<id> file=<路徑>`；結束寫一筆 `type=summary`（各結果數、耗時、**每個測試檔耗時前 20 名**）。
xdist 下只在 controller 端收（`pytest_runtest_logreport` 在 controller 會收到 worker 的報告）⇒ 單一寫入者、不重複。
**只觀察、不改測試結果與 exit code**：所有處理包在 try/except，出錯只在 stderr 說一次。

## 外部終止（type=aborted；不算失敗）
`timeout`／TaskStop／Ctrl-C 終止整個 run 時，xdist worker 會先掉線，舊版把它們記成 FAIL-EARLY（W2：rc-modtest3 exit=124）。
現在崩潰類紀錄（worker 掉線、`crashed while running`）先保留 `MOTRIX_FAIL_STREAM_GRACE` 秒（預設 3）再判定：
- controller 收到中斷（KeyboardInterrupt／SIGINT／SIGTERM／SIGBREAK），或 pytest 以 INTERRUPTED 結束 ⇒ `aborted`；
- 所有 worker 都掉了、期間也沒有替補的 worker 起來 ⇒ `aborted`；
- 其餘（個別 worker 崩潰、別的 worker／替補還活著）⇒ 照舊 `fail`／`node_down`。
controller 自己也被殺時保留區來不及寫 ⇒ 什麼都不記。summary 帶 `aborted`（布林）與 `aborted_records`；`tail` 不把 aborted 算進失敗數。
已知限制：`-n 1` 且 xdist 不再重啟 worker 的真崩潰，會被誤判為 aborted（summary 的 exitstatus 仍是失敗）。

## 同一次 modtest 的多段（非 e2e／e2e／分批）共用一個 run-id（環境變數 MOTRIX_FAIL_STREAM_RUN），各段各寫一筆 summary（stage 欄）。
檔案不進 git（.gitignore）。環境變數 MOTRIX_FAIL_STREAM_DIR 可改目錄（測試用）。

## 視窗追自己模組的失敗
  python tools/platform/fail_stream.py tail <run-id|latest> [--module X] [--follow] [--json]
  python tools/platform/fail_stream.py list
模組 key 由路徑推（modules/<key>/…）；backend/tests 下的題查 docs/platform/test_map.json 的 units（dir:backend/modules/<key>/、mod:<key>/…）；都沒有 ⇒ `core`。
"""
import argparse
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    import pytest
except ImportError:            # CLI（tail／list）不需要 pytest
    pytest = None


def _optional_hook(fn):
    """xdist 才有的 hook（pytest_testnodedown）：沒裝 xdist 時 pytest 不認得它 ⇒ 要標 optionalhook，否則 plugin 驗證會丟例外。"""
    return pytest.hookimpl(optionalhook=True)(fn) if pytest else fn

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
LONGREPR_MAX = 4096
TOP_FILES = 20
DIR_ENV, RUN_ENV, STAGE_ENV = "MOTRIX_FAIL_STREAM_DIR", "MOTRIX_FAIL_STREAM_RUN", "MOTRIX_FAIL_STREAM_STAGE"
GRACE_ENV = "MOTRIX_FAIL_STREAM_GRACE"          # 崩潰類紀錄的保留秒數（預設 3）：等「是不是整個 run 被外部終止」弄清楚再寫
CRASH_TEXT = "crashed while running"            # xdist 對「worker 在跑某題時掉線」的那題失敗報告用的字樣


# ── 位置 ─────────────────────────────────────────────────────────────────────────

def stream_dir():
    d = os.environ.get(DIR_ENV)
    if d:
        return Path(d)
    try:
        r = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--path-format=absolute", "--git-common-dir"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return Path(r.stdout.strip()).parent / "tools" / "platform" / "fail_stream"
    except (OSError, subprocess.TimeoutExpired):
        pass
    return REPO / "tools" / "platform" / "fail_stream"


def new_run_id():
    return "%s_%d" % (time.strftime("%Y%m%d_%H%M%S"), os.getpid())


# ── nodeid → 模組 ─────────────────────────────────────────────────────────────────

_MAP = None


def _test_map():
    global _MAP
    if _MAP is None:
        try:
            _MAP = json.loads((REPO / "docs" / "platform" / "test_map.json").read_text(encoding="utf-8")).get("tests", {})
        except (OSError, ValueError):
            _MAP = {}
    return _MAP


def modules_of(nodeid):
    """⇒ (主要模組 key, 全部 key 清單)。"""
    path = nodeid.split("::", 1)[0].replace("\\", "/")
    m = re.match(r"(?:backend/)?modules/([^/]+)/", path)
    if m:
        return m.group(1), [m.group(1)]
    keys = []
    for u in (_test_map().get("backend/" + path) or {}).get("units", []):
        mm = re.match(r"(?:dir:backend/modules/|mod:|moddir:)([a-z0-9_]+)[/]?", u)
        if mm and mm.group(1) not in keys:
            keys.append(mm.group(1))
    return (keys[0] if keys else "core"), (keys or ["core"])


def one_line(text):
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    # 第一條 `E ` 行＝例外型別與訊息（後面的 E 行是斷言展開的細節）；沒有 E 行（收集／crash 訊息）就取最後一行
    pick = next((l for l in lines if l.startswith("E ")), lines[-1] if lines else "")
    return re.sub(r"^E\s+", "", re.sub(r"\s+", " ", pick))[:200]


# ── plugin ───────────────────────────────────────────────────────────────────────

class FailStream:
    def __init__(self, config):
        self.config = config
        self.run_id = os.environ.get(RUN_ENV) or new_run_id()
        self.stage = os.environ.get(STAGE_ENV, "")
        self.path = stream_dir() / (self.run_id + ".jsonl")
        self.seq = 0
        self.t0 = time.time()
        self.failed, self.errored = set(), set()
        self.counts = {"passed": 0, "skipped": 0, "xfailed": 0}
        self.files = {}
        self.broken = False
        # 外部終止判斷（type=aborted）：崩潰類紀錄（worker 掉線、xdist 的 crashed while running）先保留一小段時間，
        # 期間若①controller 收到中斷（Ctrl-C／SIGTERM／SIGBREAK）或②所有 worker 都掉了、也沒有替補的 worker 起來 ⇒ 整個 run 是被外部終止，
        # 這些記 type=aborted（不算失敗）；否則照舊記 fail／node_down。controller 自己也被殺時保留區沒機會寫 ⇒ 什麼都不記（正確）。
        self.grace = float(os.environ.get(GRACE_ENV, "3") or 3)
        self.lock = threading.RLock()
        self.pending, self.timer = [], None
        self.live = set()
        self.interrupted = False
        self.aborted = set()

    # 寫檔：單次 os.write（O_APPEND）；任何錯誤只說一次
    def _write(self, rec):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = (json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8")
            fd = os.open(str(self.path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
            try:
                os.write(fd, data)
                os.fsync(fd)
            finally:
                os.close(fd)
        except Exception as e:                                   # noqa: BLE001 — 觀察者不可以弄壞測試
            self._complain(e)

    def _complain(self, e):
        if not self.broken:
            self.broken = True
            sys.stderr.write("[fail_stream] 寫不出失敗紀錄（%r）；測試照跑，只是沒有 JSONL。\n" % (e,))

    def _say(self, line):
        try:
            tr = self.config.pluginmanager.get_plugin("terminalreporter")
            if tr is not None:
                tr.write_line(line)
            else:
                sys.__stdout__.write(line + "\n")
                sys.__stdout__.flush()
        except Exception as e:                                   # noqa: BLE001
            self._complain(e)

    def _stamp(self):
        return time.strftime("%Y-%m-%dT%H:%M:%S") + ".%03d" % (int(time.time() * 1000) % 1000)

    def _next(self):
        self.seq += 1
        return self.seq

    # ── hooks ──
    def _install_signals(self):
        """只記旗標、再交還原本的處理（不改變行程對信號的反應）；只在主執行緒裝得起來。"""
        for n in ("SIGINT", "SIGTERM", "SIGBREAK"):
            sig = getattr(signal, n, None)
            if sig is None:
                continue
            try:
                prev = signal.getsignal(sig)

                def handler(signum, frame, _prev=prev):
                    self.interrupted = True
                    if callable(_prev):
                        return _prev(signum, frame)
                    signal.signal(signum, signal.SIG_DFL)          # 原本是預設 ⇒ 還原預設後再送一次給自己，行為與沒裝一樣
                    os.kill(os.getpid(), signum)
                signal.signal(sig, handler)
            except Exception:                                       # noqa: BLE001 — 非主執行緒／平台不支援：略過，仍有「集體掉線」判斷
                pass

    def pytest_sessionstart(self, session):
        self._install_signals()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.touch(exist_ok=True)
            self._say("FAIL-STREAM run=%s file=%s%s" % (self.run_id, self.path, (" stage=" + self.stage) if self.stage else ""))
        except Exception as e:                                   # noqa: BLE001
            self._complain(e)

    def _fail(self, nodeid, when, longrepr, worker, rtype="fail"):
        try:
            mod, mods = modules_of(nodeid)
            summ = one_line(longrepr)
            self._write({"type": rtype, "seq": self._next(), "t": self._stamp(), "run": self.run_id, "stage": self.stage, "nodeid": nodeid,
                         "when": when, "module": mod, "modules": mods, "summary": summ, "longrepr": (longrepr or "")[:LONGREPR_MAX],
                         "worker": worker})
            self._say("%s %s %s %s" % ("FAIL-EARLY" if rtype == "fail" else "ABORTED", nodeid, mod, summ))
        except Exception as e:                                   # noqa: BLE001
            self._complain(e)

    # ── 崩潰類紀錄的保留與判定 ──
    def _hold(self, item):
        with self.lock:
            self.pending.append(item)
            if self.timer is None:
                self.timer = threading.Timer(self.grace, self._flush, kwargs={"final": False})
                self.timer.daemon = True
                self.timer.start()

    def _is_aborted(self, final=False, exitstatus=None):
        if self.interrupted:
            return True
        if final and exitstatus == 2:                             # pytest.ExitCode.INTERRUPTED
            return True
        return not self.live and bool(self.pending)

    def _flush(self, final=False, exitstatus=None):
        try:
            with self.lock:
                if not self.pending:
                    return
                aborted = self._is_aborted(final, exitstatus)
                items, self.pending = self.pending, []
                if self.timer is not None:
                    self.timer.cancel()
                    self.timer = None
                for kind, args in items:
                    if kind == "fail":
                        nodeid, when, longrepr, worker = args
                        if aborted:
                            self.aborted.add(nodeid)
                            self._fail(nodeid, when, longrepr, worker, "aborted")
                        else:
                            self.failed.add(nodeid)
                            self._fail(nodeid, when, longrepr, worker)
                    else:
                        rec, line = args
                        if aborted:
                            rec = dict(rec, type="aborted")
                            line = line.replace("FAIL-EARLY", "ABORTED", 1)
                            self.aborted.add(rec["nodeid"])
                        rec["seq"] = self._next()
                        self._write(rec)
                        self._say(line)
        except Exception as e:                                   # noqa: BLE001
            self._complain(e)

    @_optional_hook
    def pytest_testnodeready(self, node):
        with self.lock:
            self.live.add(getattr(getattr(node, "gateway", None), "id", None))
            if self.pending:
                self._flush()                                      # 有替補的 worker 起來（live 不空）⇒ 是個別崩潰，不是整個 run 被終止 ⇒ 立刻照 fail 寫

    def pytest_keyboard_interrupt(self, excinfo):
        self.interrupted = True

    @staticmethod
    def _worker(rep):
        try:
            return rep.node.gateway.id
        except Exception:                                        # noqa: BLE001
            return None

    def pytest_runtest_logreport(self, report):
        try:
            f = report.nodeid.split("::", 1)[0]
            d = self.files.setdefault(f, [0.0, set()])
            d[0] += float(getattr(report, "duration", 0) or 0)
            d[1].add(report.nodeid)
            if report.failed:
                text = getattr(report, "longreprtext", "") or str(report.longrepr)
                if CRASH_TEXT in text:                             # worker 崩潰類：先保留，等判定是不是外部終止
                    self._hold(("fail", (report.nodeid, report.when, text, self._worker(report))))
                    return
                (self.failed if report.when == "call" else self.errored).add(report.nodeid)
                self._fail(report.nodeid, report.when, text, self._worker(report))
            elif report.skipped:
                if hasattr(report, "wasxfail"):
                    self.counts["xfailed"] += 1
                elif report.when in ("setup", "call"):
                    self.counts["skipped"] += 1
            elif report.passed and report.when == "call":
                if hasattr(report, "wasxfail"):
                    pass
                self.counts["passed"] += 1
        except Exception as e:                                   # noqa: BLE001
            self._complain(e)

    def pytest_collectreport(self, report):
        try:
            if report.failed:
                self._fail(report.nodeid or "(collect)", "collect", getattr(report, "longreprtext", "") or str(report.longrepr), None)
        except Exception as e:                                   # noqa: BLE001
            self._complain(e)

    @_optional_hook
    def pytest_testnodedown(self, node, error):
        """xdist：worker 掉線。掉線時正在跑的題會另有一筆 fail（logreport）；這筆記「這個 worker 掉了」。
        崩潰類先保留（見 _hold）：整個 run 被外部終止時 worker 會集體掉線，那不是這些題的失敗。"""
        try:
            wid = getattr(getattr(node, "gateway", None), "id", None)
            with self.lock:
                self.live.discard(wid)
            if error:
                rec = {"type": "node_down", "t": self._stamp(), "run": self.run_id, "stage": self.stage,
                       "nodeid": "(worker %s)" % wid, "when": "node_down", "module": "core", "modules": ["core"],
                       "summary": one_line(str(error)), "longrepr": str(error)[:LONGREPR_MAX], "worker": wid}
                self._hold(("node_down", (rec, "FAIL-EARLY (worker %s) core node down: %s" % (wid, one_line(str(error))))))
        except Exception as e:                                   # noqa: BLE001
            self._complain(e)

    def pytest_sessionfinish(self, session, exitstatus):
        self._flush(final=True, exitstatus=int(exitstatus))
        try:
            slow = sorted(({"file": k, "seconds": round(v[0], 2), "tests": len(v[1])} for k, v in self.files.items()),
                          key=lambda x: -x["seconds"])[:TOP_FILES]
            rec = {"type": "summary", "seq": self._next(), "t": self._stamp(), "run": self.run_id, "stage": self.stage,
                   "exitstatus": int(exitstatus), "duration_s": round(time.time() - self.t0, 1), "passed": self.counts["passed"],
                   "skipped": self.counts["skipped"], "xfailed": self.counts["xfailed"], "failed": len(self.failed),
                   "errors": len(self.errored - self.failed), "aborted": bool(self.interrupted or self.aborted or int(exitstatus) == 2),
                   "aborted_records": len(self.aborted), "slowest_files": slow}
            self._write(rec)
            self._say("FAIL-STREAM summary run=%s failed=%d errors=%d passed=%d exit=%s%s → %s" % (
                self.run_id, rec["failed"], rec["errors"], rec["passed"], rec["exitstatus"], " aborted（外部終止／中斷，不是測試失敗）" if rec["aborted"] else "", self.path))
        except Exception as e:                                   # noqa: BLE001
            self._complain(e)


def pytest_configure(config):
    """只在 controller（或單程序）註冊；xdist worker 不註冊（避免多個寫入者）。"""
    if hasattr(config, "workerinput"):
        return
    config.pluginmanager.register(FailStream(config), "fail_stream_impl")


# ── CLI ──────────────────────────────────────────────────────────────────────────

def _files(d):
    return sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime) if d.is_dir() else []


def _resolve(d, which):
    if which == "latest":
        fs = _files(d)
        return fs[-1] if fs else None
    p = d / (which if which.endswith(".jsonl") else which + ".jsonl")
    return p if p.is_file() else None


def _wanted(rec, module):
    return not module or rec.get("type") == "summary" or module == rec.get("module") or module in (rec.get("modules") or [])


def _render(rec, as_json):
    if as_json:
        return json.dumps(rec, ensure_ascii=False)
    if rec.get("type") == "summary":
        s = "SUMMARY %s stage=%s exit=%s failed=%s errors=%s passed=%s %.0fs%s" % (rec.get("t"), rec.get("stage") or "-", rec.get("exitstatus"), rec.get("failed"),
                                                                                rec.get("errors"), rec.get("passed"), rec.get("duration_s", 0),
                                                                                " ABORTED（外部終止，不是測試失敗）" if rec.get("aborted") else "")
        slow = rec.get("slowest_files") or []
        return s + ("\n  最慢的檔：" + "；".join("%s %.1fs" % (x["file"], x["seconds"]) for x in slow[:5]) if slow else "")
    # flaky_retried／flaky_blocked：建包的偶發重跑結果（tools/platform/flaky_retry.py 附加）
    label = {"fail": "FAIL", "node_down": "NODE-DOWN", "aborted": "ABORTED"}.get(rec.get("type"), str(rec.get("type") or "?").upper().replace("_", "-"))
    return "%s %s [%s] %s %s" % (rec.get("t"), label, rec.get("when"), rec.get("nodeid"),
                                 "(%s) %s" % (rec.get("module"), rec.get("summary")))


def cmd_tail(a):
    d = Path(a.dir) if a.dir else stream_dir()
    p = _resolve(d, a.run)
    deadline = time.time() + a.timeout if a.follow and a.timeout else None
    while p is None and a.follow and (deadline is None or time.time() < deadline):
        time.sleep(a.interval)
        p = _resolve(d, a.run)
    if p is None:
        print("找不到 run：%s（目錄 %s）" % (a.run, d))
        return 1
    print("# %s" % p)
    pos, n_fail, done = 0, 0, False
    while True:
        with open(p, "rb") as f:
            f.seek(pos)
            chunk = f.read()
        # 只處理完整的行（寫入端單次 write 一整行，讀到半行就留到下一輪）
        end = chunk.rfind(b"\n") + 1
        for raw in chunk[:end].splitlines():
            try:
                rec = json.loads(raw.decode("utf-8"))
            except ValueError:
                continue
            if rec.get("type") in ("fail", "node_down") and _wanted(rec, a.module):
                n_fail += 1
            if _wanted(rec, a.module):
                print(_render(rec, a.json), flush=True)
            if rec.get("type") == "summary":
                done = True
        pos += end
        if not a.follow or done:
            break
        if deadline and time.time() > deadline:
            break
        time.sleep(a.interval)
    print("# %d 筆失敗%s%s" % (n_fail, "（模組 %s）" % a.module if a.module else "", "" if done else "；run 尚未結束或沒有 summary"))
    return 0


def cmd_list(a):
    d = Path(a.dir) if a.dir else stream_dir()
    for p in reversed(_files(d)[-20:]):
        n = sum(1 for _ in open(p, "rb"))
        print("%s  %s  %d 行" % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p.stat().st_mtime)), p.stem, n))
    return 0


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tail")
    t.add_argument("run", help="run-id 或 latest")
    t.add_argument("--module")
    t.add_argument("--follow", action="store_true", help="持續追到 summary 出現")
    t.add_argument("--interval", type=float, default=2.0)
    t.add_argument("--timeout", type=float, default=0, help="--follow 的總時限（秒）；0＝不限")
    t.add_argument("--json", action="store_true")
    sub.add_parser("list")
    a = ap.parse_args(argv)
    return cmd_tail(a) if a.cmd == "tail" else cmd_list(a)


if __name__ == "__main__":
    sys.exit(main())
