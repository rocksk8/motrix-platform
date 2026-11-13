# -*- coding: utf-8 -*-
"""測試汙染偵測（原型）：每個測試檔（module）開始前對行程內的共用全域狀態拍快照，結束時（含 module 範圍 fixture 的收尾之後）比對，
有沒還原的就點名「哪個檔、改了哪個登記表的哪個鍵」。**只觀察，不改測試結果與 exit code。**

載入：`pytest -p pollution_detector`（tools/platform 在 PYTHONPATH）。
模式（環境變數 MOTRIX_POLLUTION）：
  report（預設）：逐檔記錄到 <MOTRIX_POLLUTION_DIR>/<run-id>.pollution.jsonl（預設與 fail_stream 同目錄）。
  gate：同 report，另在 session 結束時印出「汙染清單」並寫 <run-id>.pollution-list.json（仍不擋測試）。
  off：不啟用。

監看的狀態（分五類）：
  registry  登記表：core／helpers／routers／modules／根目錄 app 模組裡「名字是全大寫（可帶底線前綴）的模組級 dict／list／set」自動盤點，
            另有精準清單（_CURATED）保證一定被看（core.definitions 的 _EXTRA_KINDS／_VALIDATORS／_DEFAULTS、core.registry、core.events…）。
  cache     名字像快取的（CACHE／MEMO／LOGGED／ALERTED…）：照記，但標 class=cache，不列入閘門清單（它們本來就會隨使用長大）。
  env       os.environ（新增／刪除／改值）。
  modules   sys.modules：既有鍵被換掉（替身）、被刪；新增的若不是真模組（沒有 __file__／不是 ModuleType）標為疑似替身。
  process   cwd、sys.path、logging root handlers、warnings.filters 長度、threading.active_count、db.DB_PATH。
  db        行程的 session DB 檔（`db.DB_PATH` 指到的檔，含 -wal）在這個檔前後有沒有被寫過；檔案變了才去數各表筆數，點名「哪張表多了／少了幾列」
            （沒用 client 的題目讀到前一個檔留下的列，就是這一類：例 test_auth_lockout_alert 讀到 1001 列 audit_log）。
白名單（"不算汙染"的東西）一律寫死成下面的常數、每一項都註解理由；不從外部檔讀、不用環境變數開洞（PM 裁示 2026-11-13）。
成本：快照＝每個容器 O(筆數) 的雜湊（超過 BIG 筆只比長度）＋ environ／sys.modules 的 id 表；清單只在 sys.modules 變動時重掃。
"""
import json
import logging
import os
import re
import sys
import threading
import time
import types
import warnings
from pathlib import Path

try:
    import pytest
except ImportError:            # 純函式部分可以不裝 pytest 用
    pytest = None

BIG = 5000                       # 超過這個筆數的容器只比長度與雜湊總和（不留複本）
COPY_MAX = 600                   # 容器筆數 ≤ 這個才留複本（用來點名鍵）
_NAME_RE = re.compile(r"^_?[A-Z][A-Z0-9_]{2,}$")
# 名字像快取／記帳的全域容器：照記但標 class=cache，不進「汙染清單」（它們本來就會隨使用長大；要不要治理另案）
_CACHE_RE = re.compile(r"CACHE|MEMO|LOGGED|ALERTED|_SEEN|FAIL_LAST|FAIL_HOUR|POOL|WATCHERS|WRITE_TXNS|ERROR_UNTIL|MISS|PENDING|IMPACT|REWRITE|HIST|TRAIL|INCOMPLETE")
# ── 白名單（寫死；新增一項要在這裡寫理由）──
_ENV_IGNORE = frozenset({"PYTEST_CURRENT_TEST"})      # pytest 自己每題設／清，不是測試造成的
_PROC_IGNORE = frozenset({"warnings.filters"})        # pytest 的 catch_warnings 每題進出都會動長度；改用 sys.modules／registry 抓真正的洩漏
_PKGS = ("core", "helpers", "routers", "modules")
_CURATED = (                       # 一定要看的（即使名字不合自動盤點的規則）
    ("core.definitions", "_EXTRA_KINDS"), ("core.definitions", "_VALIDATORS"), ("core.definitions", "_DEFAULTS"),
    ("core.registry", "_LOADED"), ("core.registry", "_FAILED"), ("core.registry", "_STATES"), ("core.registry", "_DISABLED_LIST"),
    ("core.registry", "_LEGACY_PROVIDERS"), ("core.registry", "_UNLOAD_HOOKS"), ("core.registry", "_OWNED"),
    ("core.events", "_DECLS"), ("core.events", "_SUBS"),
    ("core.spine", "_FEATURES"), ("core.spine", "_KIND_GATES"), ("core.spine", "_MANAGED"), ("core.spine", "_HEALTH"),
    ("helpers.mail_types", "_REGISTRY"), ("helpers.settings_registry", "_GROUPS"), ("helpers.row_access", "_REGISTRY"),
    ("helpers.list_catalog", "_LISTS"), ("helpers.config_ledger", "_DOMAINS"), ("core.catalog", "_SECTIONS"),
)


def _fp(c):
    """容器的便宜指紋：dict＝(鍵雜湊和, 值 id 和)；list＝(id 和,)；set＝(雜湊和,)。"""
    try:
        if isinstance(c, dict):
            return (len(c), sum(hash(k) for k in c) & 0xFFFFFFFF, sum(id(v) for v in c.values()) & 0xFFFFFFFF)
        if isinstance(c, list):
            return (len(c), sum(id(v) for v in c) & 0xFFFFFFFF)
        return (len(c), sum(hash(v) for v in c) & 0xFFFFFFFF)
    except Exception:                                     # noqa: BLE001 — 不可雜湊／並行修改：退回只比長度
        return (len(c),)


def _copy(c):
    if len(c) > COPY_MAX:
        return None
    try:
        return dict(c) if isinstance(c, dict) else (list(c) if isinstance(c, list) else set(c))
    except Exception:                                     # noqa: BLE001
        return None


class Watch:
    """一個被監看的容器：(模組, 名稱) 與開始時的物件、指紋、複本。"""
    __slots__ = ("mod", "name", "obj", "fp", "copy", "klass")

    def __init__(self, mod, name, obj):
        self.mod, self.name, self.obj = mod, name, obj
        self.klass = "cache" if _CACHE_RE.search(name) else "registry"
        self.fp = _fp(obj)
        self.copy = _copy(obj)


class Detector:
    def __init__(self, backend_root):
        self.root = str(Path(backend_root).resolve()).lower()
        self._targets = []                 # [(modname, attr)]
        self._seen_mods = -1
        self._start = None
        self._db_cache = None              # (路徑, {表: 筆數}, stat)：上一次數過的；檔案沒變就不重數
        self.cost_ms = 0.0
        self.files = 0

    # ── 清單 ──────────────────────────────────────────────────────────────────────
    def _is_app_module(self, name, mod):
        if name == "conftest" or name.split(".")[0] in ("tests", "conftest"):
            return False                   # 測試基礎設施自己的記帳（_BK19_WRITES 等）不算被測程式的全域狀態
        if not (name.split(".")[0] in _PKGS or "." not in name):
            return False
        f = getattr(mod, "__file__", None)
        return bool(f) and str(f).lower().startswith(self.root) and "\\tests\\" not in str(f).lower() and "/tests/" not in str(f).lower()

    def _discover(self):
        n = len(sys.modules)
        if n == self._seen_mods:
            return
        self._seen_mods = n
        seen, out = set(), []
        for modname, attr in _CURATED:
            out.append((modname, attr))
            seen.add((modname, attr))
        for name, mod in list(sys.modules.items()):
            if mod is None or not isinstance(mod, types.ModuleType) or not self._is_app_module(name, mod):
                continue
            for attr, v in list(vars(mod).items()):
                if (name, attr) in seen or not _NAME_RE.match(attr) or not isinstance(v, (dict, list, set)):
                    continue
                out.append((name, attr))
        self._targets = out

    # ── 快照 ──────────────────────────────────────────────────────────────────────
    def snapshot(self):
        t0 = time.perf_counter()
        self._discover()
        watches = {}
        for modname, attr in self._targets:
            m = sys.modules.get(modname)
            v = getattr(m, attr, None) if m is not None else None
            if isinstance(v, (dict, list, set)):
                watches[(modname, attr)] = Watch(modname, attr, v)
        snap = {
            "watches": watches,
            "env": dict(os.environ),
            "mods": {k: id(v) for k, v in sys.modules.items()},
            "proc": self._proc(),
            "db": self._dbstat(),
        }
        st = snap["db"]
        if st is not None and (self._db_cache is None or self._db_cache[0] != st[0] or self._db_cache[2] != st):      # 檔案在兩個檔之間被動過 ⇒ 基線重數，免得誤報
            c = self._db_counts(st[0])
            if c is not None:
                self._db_cache = (st[0], c, st)
        self.cost_ms += (time.perf_counter() - t0) * 1000
        return snap

    # ── session DB（class=db）──
    @staticmethod
    def _dbstat():
        """⇒ (路徑, 主檔 size／mtime, -wal size／mtime)；路徑空或檔不存在 ⇒ None。只做 os.stat，便宜。"""
        try:
            import db as _db
            p = str(getattr(_db, "DB_PATH", "") or "")
        except Exception:                                 # noqa: BLE001
            return None
        if not p or not os.path.isfile(p):
            return None
        out = [p]
        for suffix in ("", "-wal"):
            try:
                st = os.stat(p + suffix)
                out.append((st.st_size, st.st_mtime_ns))
            except OSError:
                out.append(None)
        return tuple(out)

    def _db_counts(self, path):
        """⇒ {表: 筆數}（唯讀開檔；任何錯誤 ⇒ None）。只在 _dbstat 變了才呼叫。"""
        import sqlite3
        try:
            con = sqlite3.connect("file:%s?mode=ro" % Path(path).as_posix(), uri=True, timeout=1)
        except Exception:                                 # noqa: BLE001
            return None
        try:
            names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            return {n: con.execute('SELECT COUNT(*) FROM "%s"' % n.replace('"', '""')).fetchone()[0] for n in names}
        except Exception:                                 # noqa: BLE001
            return None
        finally:
            con.close()

    @staticmethod
    def _proc():
        try:
            import db as _db
            dbp = str(getattr(_db, "DB_PATH", ""))
        except Exception:                                 # noqa: BLE001
            dbp = ""
        return {"cwd": os.getcwd(), "sys.path": list(sys.path), "logging.root.handlers": len(logging.getLogger().handlers),
                "warnings.filters": len(warnings.filters), "threads": threading.active_count(), "db.DB_PATH": dbp}

    # ── 比對 ──────────────────────────────────────────────────────────────────────
    def diff(self, a, b):
        t0 = time.perf_counter()
        out = []
        # registry／cache
        for key, w0 in a["watches"].items():
            m = sys.modules.get(key[0])
            cur = getattr(m, key[1], None) if m is not None else None
            if cur is not w0.obj:
                out.append({"class": w0.klass, "state": "%s.%s" % key, "change": "rebound（換成另一個物件）"})
                continue
            if _fp(cur) == w0.fp:
                continue
            item = {"class": w0.klass, "state": "%s.%s" % key, "change": "changed"}
            if w0.copy is not None and isinstance(cur, dict):
                add = sorted(str(k) for k in cur if k not in w0.copy)
                rem = sorted(str(k) for k in w0.copy if k not in cur)
                chg = sorted(str(k) for k in cur if k in w0.copy and cur[k] is not w0.copy[k])
                item.update(added=add[:20], removed=rem[:20], replaced=chg[:20])
            elif w0.copy is not None and isinstance(cur, set):
                item.update(added=sorted(map(str, cur - w0.copy))[:20], removed=sorted(map(str, w0.copy - cur))[:20])
            elif w0.copy is not None and isinstance(cur, list):
                item.update(len_before=len(w0.copy), len_after=len(cur))
            else:
                item.update(len_before=w0.fp[0], len_after=len(cur))
            out.append(item)
        # 在這個檔裡新出現的登記表（例如 import 時才建立）不算汙染：下一個檔的快照會把它納入。
        # env
        e0, e1 = {k: v for k, v in a["env"].items() if k not in _ENV_IGNORE}, {k: v for k, v in os.environ.items() if k not in _ENV_IGNORE}
        if e0 != e1:
            out.append({"class": "env", "state": "os.environ",
                        "added": sorted(k for k in e1 if k not in e0)[:20], "removed": sorted(k for k in e0 if k not in e1)[:20],
                        "changed": sorted(k for k in e1 if k in e0 and e1[k] != e0[k])[:20]})
        # sys.modules
        m0 = a["mods"]
        replaced = sorted(k for k, i in m0.items() if k in sys.modules and id(sys.modules[k]) != i)
        removed = sorted(k for k in m0 if k not in sys.modules)
        stubs = sorted(k for k, v in sys.modules.items()
                       if k not in m0 and (not isinstance(v, types.ModuleType) or not getattr(v, "__file__", None) and not getattr(v, "__path__", None)))
        if replaced or removed or stubs:
            out.append({"class": "modules", "state": "sys.modules", "replaced": replaced[:20], "removed": removed[:20], "suspected_stubs": stubs[:20]})
        # db：只在 session DB 檔被寫過時才數表（先比 stat；基線筆數在 snapshot 時就備好）
        d0, d1 = a.get("db"), self._dbstat()
        if d0 is not None and d1 is not None and d0[0] == d1[0] and d0 != d1:
            before = self._db_cache[1] if self._db_cache and self._db_cache[0] == d0[0] else {}
            after = self._db_counts(d1[0])
            if after is not None:
                grew = sorted("%s +%d" % (t, n - before.get(t, 0)) for t, n in after.items() if n > before.get(t, 0))
                shrank = sorted("%s %d" % (t, n - before.get(t, 0)) for t, n in after.items() if n < before.get(t, 0))
                if grew or shrank:
                    out.append({"class": "db", "state": "session DB（%s）" % Path(d1[0]).name, "added": grew[:20], "removed": shrank[:20]})
                self._db_cache = (d1[0], after, d1)
        # process
        p1 = self._proc()
        for k, v0 in a["proc"].items():
            if k not in _PROC_IGNORE and p1[k] != v0:
                out.append({"class": "process", "state": k, "before": _short(v0), "after": _short(p1[k])})
        self.cost_ms += (time.perf_counter() - t0) * 1000
        return out


def _short(v):
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
    return s if len(s) <= 300 else s[:300] + "…"


# ── pytest plugin ───────────────────────────────────────────────────────────────────
_MODE = (os.environ.get("MOTRIX_POLLUTION") or "report").strip().lower()
_det = None
_state = {"mod": None, "snap": None, "setting_up": False}
PROP = "pollution"


def _enabled():
    return pytest is not None and _MODE in ("report", "gate")


def pytest_configure(config):
    global _det
    if not _enabled():
        return
    root = getattr(config, "rootpath", None) or Path.cwd()
    _det = Detector(root)
    config._pollution_findings = []          # controller 端收集（gate 清單用）
    config._pollution_files = 0


if pytest is not None:
    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_setup(item):
        if _det is None:
            return
        mod = getattr(item, "module", None)
        if _state["mod"] is mod and _state["snap"] is not None:
            return
        _state["mod"], _state["snap"], _state["setting_up"] = mod, _det.snapshot(), True

    @pytest.hookimpl(hookwrapper=True)
    def pytest_fixture_setup(fixturedef, request):
        """session 範圍 fixture（例如 `_app`：載入 main、模組登記 kind）建好之後，若還在本檔第一題的 setup 階段，重拍基線：
        否則第一個檔的基線太早（core.definitions 都還沒 import），洩漏的登記看不到、bootstrap 又會被算成這個檔的改動。"""
        yield
        if _det is not None and _state["snap"] is not None and fixturedef.scope == "session":
            _state["snap"] = _det.snapshot()

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_call(item):
        _state["setting_up"] = False

    @pytest.hookimpl(trylast=True)
    def pytest_runtest_teardown(item, nextitem):
        """module 的最後一題收尾之後（module 範圍 fixture 已還原）才比對。trylast＝在 pytest 自己的 teardown（含 fixture finalizer）之後。"""
        if _det is None or _state["snap"] is None:
            return
        if nextitem is not None and getattr(nextitem, "module", None) is _state["mod"]:
            return
        try:
            findings = _det.diff(_state["snap"], _det.snapshot())
            _det.files += 1
            item.user_properties.append((PROP, json.dumps({"file": item.nodeid.split("::")[0], "findings": findings}, ensure_ascii=False)))
        except Exception as exc:                          # noqa: BLE001 — 只觀察，出錯不影響測試
            sys.stderr.write("pollution_detector: %r\n" % (exc,))
        finally:
            _state["mod"], _state["snap"] = None, None

    def pytest_runtest_logreport(report):
        """controller 端（xdist 下 worker 的報告也會到這裡）：單一寫入者。"""
        if report.when != "teardown":
            return
        for k, v in getattr(report, "user_properties", ()):
            if k != PROP:
                continue
            try:
                rec = json.loads(v)
            except Exception:                             # noqa: BLE001
                continue
            _write(rec)

    def pytest_sessionfinish(session, exitstatus):
        if _det is None or _MODE != "gate":
            return
        try:
            _emit_list()
        except Exception as exc:                          # noqa: BLE001
            sys.stderr.write("pollution_detector list: %r\n" % (exc,))


_RECS = []


def _outdir():
    d = os.environ.get("MOTRIX_POLLUTION_DIR") or os.environ.get("MOTRIX_FAIL_STREAM_DIR")
    return Path(d) if d else Path(__file__).resolve().parent / "fail_stream"


def _run_id():
    return os.environ.get("MOTRIX_FAIL_STREAM_RUN") or time.strftime("%Y%m%d_%H%M%S") + "_%d" % os.getpid()


_RID = None


def _write(rec):
    global _RID
    _RECS.append(rec)
    if not rec.get("findings"):
        return
    _RID = _RID or _run_id()
    d = _outdir()
    d.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "run": _RID, **rec}, ensure_ascii=False) + "\n"
    fd = os.open(str(d / (_RID + ".pollution.jsonl")), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


def pollution_list(recs):
    """⇒ 汙染清單：只列 class≠cache 的發現；依 (state, 鍵) 彙整是哪些檔留下的。"""
    agg = {}
    for r in recs:
        for f in r.get("findings", ()):
            if f.get("class") == "cache":
                continue
            keys = tuple(f.get("added", ())) + tuple("-" + x for x in f.get("removed", ())) + tuple("~" + x for x in f.get("replaced", ()))
            k = (f["state"], keys or (f.get("change") or ""))
            agg.setdefault(k, []).append(r["file"])
    return [{"state": s, "keys": list(ks), "files": sorted(set(fs))} for (s, ks), fs in sorted(agg.items())]


def _emit_list():
    lst = pollution_list(_RECS)
    rid = _RID or _run_id()
    d = _outdir()
    d.mkdir(parents=True, exist_ok=True)
    (d / (rid + ".pollution-list.json")).write_text(json.dumps({"run": rid, "files_checked": len(_RECS), "cost_ms_this_process": round(_det.cost_ms, 2), "files_this_process": _det.files, "polluters": lst}, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.stdout.write("\nPOLLUTION-LIST run=%s files=%d polluters=%d → %s\n" % (rid, len(_RECS), len(lst), d / (rid + ".pollution-list.json")))
    for p in lst[:30]:
        sys.stdout.write("  %s %s ← %s\n" % (p["state"], p["keys"][:6], ", ".join(p["files"][:4])))
