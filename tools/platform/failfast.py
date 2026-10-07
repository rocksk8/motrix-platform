# -*- coding: utf-8 -*-
"""建包優化 2 · 項 1：紅了就停（fail-fast）＋最可能紅的先跑（failure-first）。pytest plugin，**預設關**（環境變數開）。

為什麼（docs/platform/plans/BUILD-OPTIMIZATION-2.md §3 項 1）：兩班建包裡 194 分鐘已完成的測試段，有 78 分鐘（40%）是第一個紅出現「之後」才跑的。
紅的當下 `fail_stream` 已經印 `FAIL-EARLY`，但沒有人停下來——建包要等整段 26 分鐘跑完才說「紅」。

## 開關（全部是環境變數；沒設＝行為與沒有這個 plugin 完全一樣）
  MOTRIX_FAILFAST=1            開「紅了就停」
  MOTRIX_FAILFAST_N=10         未登記的紅累計達 N 筆就停
  MOTRIX_FAILFAST_QUIET_MIN=4  已有紅之後，連續這麼多**分鐘**沒有新的紅就停（可小數；0＝關掉這一條）
  MOTRIX_FAILFAST_FLAKES=路徑  偶發登記簿（預設 tools/platform/known_flakes.json）：**已登記且未過期的紅不計入**（交 flaky_retry 照舊處理）
  MOTRIX_FAILFIRST=1           開「先跑最可能紅的」：⒜最近的 fail_stream 紅過的題 ⒝自 MOTRIX_FAILFIRST_BASE 起 diff 動到的測試檔
                               ⒞tests/platform 的守門題 ⒟其餘照原順序。**只改順序、不刪不增題**（集合不同就放棄重排並印警告）。
  MOTRIX_FAILFIRST_BASE=<ref>  ⒝的比較基準（沒設＝不做 ⒝；`auto`＝該段最近一次綠的 commit，讀 test_results.jsonl）
  MOTRIX_FAILFIRST_HISTORY=10  ⒜讀最近幾份 fail_stream JSONL
  MOTRIX_GATE_LPT=1            （預設開，只在 FAILFIRST 開時有作用；0＝關）同一優先群組內「檔案耗時大的先跑」（O6，第 45 班）：
                               耗時來源＝gate_file_seconds.json（種子）被 full_results/file_seconds.json（累積實測）蓋過；
                               MOTRIX_GATE_RECORD=1（預設關；modtest --full 的全閘門會帶）時，controller 在 sessionfinish 把這輪各檔耗時併進累積檔。只改順序，題集合不變。

## 不吞資訊、不放水（反向控制見 backend/tests/platform/test_failfast_2026_10_02.py）
- 停止時照樣印紅清單、fail_stream 照樣寫 summary（帶 `aborted_by: failfast`，**不是** aborted——紅是真的紅）；
- **exit code 一律 1（測試失敗）**：xdist 的 shouldstop 預設會變成 INTERRUPTED(2)，那會被 fail_stream／建包當成「外部中斷」；這裡在 sessionfinish 改回 1。
- 停止條件只在「已經有（未登記的）紅」時才可能成立——全綠的 run 不可能被截斷（執行題數＝收集題數）。
- 只在 controller 端判斷（xdist worker 不註冊停止邏輯；重排兩邊都做，順序由 controller 經 workerinput 交給 worker，確保一致）。
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ON, N_ENV, QUIET_ENV, FLAKES_ENV = "MOTRIX_FAILFAST", "MOTRIX_FAILFAST_N", "MOTRIX_FAILFAST_QUIET_MIN", "MOTRIX_FAILFAST_FLAKES"
FIRST_ON, BASE_ENV, HIST_ENV = "MOTRIX_FAILFIRST", "MOTRIX_FAILFIRST_BASE", "MOTRIX_FAILFIRST_HISTORY"
NODEID_STRIP = ("backend/",)


def _norm(p):
    p = p.replace("\\", "/")
    for s in NODEID_STRIP:
        if p.startswith(s):
            return p[len(s):]
    return p


def _truthy(name):
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def registered_flakes(path=None):
    """已登記且未過期的偶發題 nodeid 集合（讀不懂登記簿 ⇒ 空集合＝全部照紅計，不放水）。"""
    try:
        sys.path.insert(0, str(HERE))
        import known_flakes as kf
        from datetime import date
        entries, problems = kf.load(path or os.environ.get(FLAKES_ENV) or None)
        if problems:
            return set()
        today = date.today()
        return {_norm(e["nodeid"]) for e in entries if kf._date(e["expires"]) >= today}
    except Exception:                                           # noqa: BLE001
        return set()


# ── 重排的優先清單 ─────────────────────────────────────────────────────────────

def recent_red_nodeids(history, exclude_run=""):
    """最近 `history` 份 fail_stream JSONL（依修改時間）裡 type=fail 的 nodeid。讀不到就空。"""
    try:
        sys.path.insert(0, str(HERE))
        import fail_stream as fs
        d = fs.stream_dir()
    except Exception:                                           # noqa: BLE001
        return []
    out = []
    try:
        files = sorted((p for p in d.glob("*.jsonl") if p.stem != exclude_run), key=lambda p: p.stat().st_mtime)[-history:]
    except OSError:
        return []
    for p in files:
        try:
            for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                if r.get("type") == "fail" and r.get("nodeid") and not r["nodeid"].startswith("("):
                    out.append(_norm(r["nodeid"]))
        except OSError:
            continue
    return list(dict.fromkeys(out))


def auto_base(stage="", records=None):
    """MOTRIX_FAILFIRST_BASE=auto：最近一次「該段綠」的建包／modtest 紀錄的 commit（讀 build 共用的 test_results.jsonl）；沒有 ⇒ ''（不做 ⒝）。"""
    try:
        path = records or os.environ.get("MOTRIX_FAILFIRST_RECORDS")
        if not path:
            sys.path.insert(0, str(REPO / "backend" / "tools"))
            import build_test_reuse as btr
            path = btr.default_records()
        last = ""
        for ln in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            st = (r.get("stages") or {}).get(stage) if stage else None
            ok = bool(st.get("green")) if isinstance(st, dict) else (bool(r.get("green")) if not stage else False)
            if ok and r.get("commit"):
                last = str(r["commit"])
        return last
    except Exception:                                           # noqa: BLE001
        return ""


def changed_files(base):
    """`git diff --name-only <base>`（含未提交）⇒ 正規化後的路徑清單；任何錯誤 ⇒ 空。base＝auto ⇒ 見 auto_base。"""
    if base == "auto":
        base = auto_base(os.environ.get("MOTRIX_FAIL_STREAM_STAGE", ""))
    if not base:
        return []
    try:
        r = subprocess.run(["git", "-C", str(REPO), "diff", "--name-only", base], capture_output=True, text=True, timeout=30)
        return [_norm(x) for x in r.stdout.splitlines() if x.strip()] if r.returncode == 0 else []
    except (OSError, subprocess.TimeoutExpired):
        return []


SEED_SECONDS = HERE / "gate_file_seconds.json"
SECONDS_REL = ("full_results", "file_seconds.json")


def _lpt_on():
    return os.environ.get("MOTRIX_GATE_LPT", "1").strip().lower() not in ("0", "false", "no", "off")


def _seconds_path():
    return HERE.joinpath(*SECONDS_REL)


def file_seconds(seed=None, local=None):
    """檔 ⇒ 耗時秒。種子被累積實測蓋過；讀不到／格式不對 ⇒ 空 dict（不排序，不報錯）。"""
    out = {}
    for path, key in ((seed or SEED_SECONDS, "seconds"), (local or _seconds_path(), None)):
        try:
            d = json.loads(Path(path).read_text(encoding="utf-8"))
            d = d.get(key) if key else d
            out.update({_norm(k): float(v) for k, v in (d or {}).items() if not k.startswith("_") and float(v) >= 0})
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return out


def merge_seconds(old, new, keep=0.5):
    """累積實測：新的一輪與舊值以指數平均合併（單輪抖動不會把順序洗掉）；沒跑到的檔保留舊值。"""
    out = dict(old)
    for k, v in new.items():
        out[k] = round(old[k] * keep + v * (1 - keep), 2) if k in old else round(v, 2)
    return out


def priority_key(nodeid, red_ids, changed):
    path = _norm(nodeid.split("::", 1)[0])
    n = _norm(nodeid)
    if n in red_ids:
        return 0
    if path in changed:
        return 1
    if path.startswith("tests/platform/") or "/tests/platform/" in path:
        return 2
    return 3


def reorder(items, prio):
    """穩定排序；題集合不變才套用。回 True＝有套用。"""
    red_ids = set(prio.get("ids", []))
    changed = set(prio.get("files", []))
    secs = prio.get("secs") or {}
    before = [it.nodeid for it in items]
    # 同一優先群組內耗時大的檔先跑（LPT）；同一檔內維持原順序（sorted 穩定、同檔同 key）
    new = sorted(items, key=lambda it: (priority_key(it.nodeid, red_ids, changed), -secs.get(_norm(it.nodeid.split("::", 1)[0]), 0.0)))
    if sorted(it.nodeid for it in new) != sorted(before):         # 重排不刪題：理論上不會發生，發生就放棄
        return False
    items[:] = new
    return True


# ── plugin ───────────────────────────────────────────────────────────────────

class FailFast:
    def __init__(self, config):
        self.config = config
        self.enabled = _truthy(ON)
        self.n = int(os.environ.get(N_ENV, "10") or 10)
        self.quiet = float(os.environ.get(QUIET_ENV, "4") or 0) * 60.0
        self.flakes = registered_flakes() if self.enabled else set()
        self.reds, self.last_red = set(), None
        self.reason = ""
        self.session = None
        self.prio = None
        # xdist 的 controller 端 shouldstop 只是在每個 worker「已分到的題」之後排一個 SHUTDOWN 標記 ⇒ worker 會把手上排的幾百題跑完才收工
        # （W2 實測：+4:07 發出停止，+16:05 才結束）。所以另用「停止旗標檔」讓 worker 每跑完一題就自己收工（worker 端見 _Worker）。
        self.stopfile = os.path.join(tempfile.gettempdir(), "motrix-failfast-%d-%d.stop" % (os.getpid(), int(time.time() * 1000)))
        if _truthy(FIRST_ON):
            hist = int(os.environ.get(HIST_ENV, "10") or 10)
            self.prio = {"ids": recent_red_nodeids(hist), "files": changed_files(os.environ.get(BASE_ENV, "")),
                         "secs": file_seconds() if _lpt_on() else {}}
        self.durations = {}                                      # 本輪各檔 call 耗時合計（只在 controller 累計）

    # xdist：把優先清單交給 worker（順序要與 controller 一致）
    @pytest.hookimpl(optionalhook=True)
    def pytest_configure_node(self, node):
        node.workerinput["failfast_stopfile"] = self.stopfile
        if self.prio is not None:
            node.workerinput["failfirst"] = self.prio

    def pytest_sessionstart(self, session):
        self.session = session

    def _stop(self, why):
        if self.reason:
            return
        self.reason = why
        self.config._failfast_reason = why
        try:
            tr = self.config.pluginmanager.get_plugin("terminalreporter")
            line = "FAIL-FAST: %s ⇒ 停止本段（未登記的紅 %d 筆；已跑的紅清單與 summary 照常輸出）" % (why, len(self.reds))
            (tr.write_line(line) if tr else print(line, flush=True))
        except Exception:                                       # noqa: BLE001
            pass
        try:
            Path(self.stopfile).write_text(why, encoding="utf-8")   # worker 端每題之後看這個檔，有就自己收工（不把排隊的題跑完）
        except OSError:
            pass
        ds = self.config.pluginmanager.get_plugin("dsession")
        if ds is not None:
            ds.shouldstop = "failfast: " + why                   # xdist controller：收尾並關掉 worker
        elif self.session is not None:
            self.session.shouldfail = "failfast: " + why         # 單程序：pytest 在下一題前停

    def _check(self):
        if not self.enabled or self.reason or not self.reds:
            return
        if len(self.reds) >= self.n:
            self._stop("未登記的紅達 %d 筆" % self.n)
        elif self.quiet > 0 and self.last_red is not None and time.time() - self.last_red >= self.quiet:
            self._stop("第一個紅之後已 %.1f 分鐘沒有新的紅" % (self.quiet / 60.0))

    def pytest_runtest_logreport(self, report):
        if not self.enabled:
            return
        try:
            if report.when == "call" and getattr(report, "duration", None):
                f = _norm(report.nodeid.split("::", 1)[0])
                self.durations[f] = self.durations.get(f, 0.0) + float(report.duration)
        except Exception:                                       # noqa: BLE001
            pass
        try:
            if report.failed and _norm(report.nodeid) not in self.flakes:
                self.reds.add(report.nodeid)
                self.last_red = time.time()
            self._check()
        except Exception:                                       # noqa: BLE001 — 加速器不可以弄壞測試
            pass

    def pytest_collectreport(self, report):
        if self.enabled and report.failed:
            self.reds.add(report.nodeid or "(collect)")
            self.last_red = time.time()

    def _save_seconds(self):
        """累積各檔耗時（原子寫）。只在「整輪跑完、沒被 fail-fast 截斷」時寫，截斷的一輪耗時不完整會讓慢檔看起來快。"""
        if self.reason or not self.durations or not _lpt_on() or os.environ.get("MOTRIX_GATE_RECORD", "0").strip() != "1":
            return
        p = _seconds_path()
        try:
            old = {}
            try:
                old = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                old = {}
            merged = merge_seconds({k: float(v) for k, v in old.items() if not k.startswith("_")}, self.durations)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.name + ".%d.tmp" % os.getpid())
            tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=0), encoding="utf-8")
            os.replace(str(tmp), str(p))
        except Exception:                                       # noqa: BLE001 — 記錄失敗不影響測試結果
            pass

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session, exitstatus):
        self._save_seconds()
        try:
            os.remove(self.stopfile)
        except OSError:
            pass
        if self.reason:
            session.exitstatus = int(pytest.ExitCode.TESTS_FAILED)   # 不是 INTERRUPTED(2)：紅是真的紅，不是外部中斷

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, session, config, items):
        prio = self.prio if self.prio is not None else (getattr(config, "workerinput", {}) or {}).get("failfirst")
        if prio is not None and not reorder(items, prio):
            sys.stderr.write("[failfast] 重排後題集合不同，已放棄重排（照原順序）。\n")


class _Worker:
    """xdist worker：重排（優先清單由 controller 經 workerinput 給）＋看停止旗標檔：有 ⇒ 這一題跑完就收工（session.shouldstop；xdist worker 迴圈每題後檢查它）。"""

    def pytest_runtest_logfinish(self, nodeid, location):
        try:
            sf = (getattr(self.config, "workerinput", {}) or {}).get("failfast_stopfile")
            if sf and os.path.exists(sf):
                self.session.shouldstop = "failfast（controller 已停止本段）"
        except Exception:                                       # noqa: BLE001
            pass

    def pytest_sessionstart(self, session):
        self.session = session

    @property
    def config(self):
        return self._config

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, session, config, items):
        prio = (getattr(config, "workerinput", {}) or {}).get("failfirst")
        if prio is not None and not reorder(items, prio):
            sys.stderr.write("[failfast] 重排後題集合不同，已放棄重排（照原順序）。\n")


def pytest_configure(config):
    if hasattr(config, "workerinput"):
        w = _Worker()
        w._config = config
        config.pluginmanager.register(w, "failfast_worker")
    else:
        config.pluginmanager.register(FailFast(config), "failfast_impl")
