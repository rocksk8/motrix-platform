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
  MOTRIX_FAILFIRST_BASE=<ref>  ⒝的比較基準（沒設＝不做 ⒝）
  MOTRIX_FAILFIRST_HISTORY=10  ⒜讀最近幾份 fail_stream JSONL

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


def changed_files(base):
    """`git diff --name-only <base>`（含未提交）⇒ 正規化後的路徑清單；任何錯誤 ⇒ 空。"""
    if not base:
        return []
    try:
        r = subprocess.run(["git", "-C", str(REPO), "diff", "--name-only", base], capture_output=True, text=True, timeout=30)
        return [_norm(x) for x in r.stdout.splitlines() if x.strip()] if r.returncode == 0 else []
    except (OSError, subprocess.TimeoutExpired):
        return []


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
    before = [it.nodeid for it in items]
    new = sorted(items, key=lambda it: priority_key(it.nodeid, red_ids, changed))
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
        if _truthy(FIRST_ON):
            hist = int(os.environ.get(HIST_ENV, "10") or 10)
            self.prio = {"ids": recent_red_nodeids(hist), "files": changed_files(os.environ.get(BASE_ENV, ""))}

    # xdist：把優先清單交給 worker（順序要與 controller 一致）
    @pytest.hookimpl(optionalhook=True)
    def pytest_configure_node(self, node):
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

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session, exitstatus):
        if self.reason:
            session.exitstatus = int(pytest.ExitCode.TESTS_FAILED)   # 不是 INTERRUPTED(2)：紅是真的紅，不是外部中斷

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, session, config, items):
        prio = self.prio if self.prio is not None else (getattr(config, "workerinput", {}) or {}).get("failfirst")
        if prio is not None and not reorder(items, prio):
            sys.stderr.write("[failfast] 重排後題集合不同，已放棄重排（照原順序）。\n")


class _Worker:
    """xdist worker：只做重排（優先清單由 controller 經 workerinput 給）。"""

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, session, config, items):
        prio = (getattr(config, "workerinput", {}) or {}).get("failfirst")
        if prio is not None and not reorder(items, prio):
            sys.stderr.write("[failfast] 重排後題集合不同，已放棄重排（照原順序）。\n")


def pytest_configure(config):
    if hasattr(config, "workerinput"):
        config.pluginmanager.register(_Worker(), "failfast_worker")
    else:
        config.pluginmanager.register(FailFast(config), "failfast_impl")
