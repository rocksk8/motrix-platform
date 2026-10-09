# -*- coding: utf-8 -*-
"""測試結果快取的『影子錄製器』（第 51 班；設計 docs/platform/plans/SPEEDUP-CACHE-T50.md）。

🔴 **只觀察、不決定任何事**：不跳過任何一題、不改 outcome／exit code、不寫 repo 內任何檔。預設**關閉**，只有 `MOTRIX_TESTCACHE_SHADOW=1` 才啟動；
任何內部錯誤 ⇒ 該次錄製自我停用並在 stderr 說一次，測試照跑。命中判定（L1／L2 的『沿用』）需要使用者書面核准，這裡完全沒有。

## 用法（pytest plugin；`tools/platform` 要在 PYTHONPATH）
  MOTRIX_TESTCACHE_SHADOW=1 python -m pytest -p testcache_shadow <測試…>        （xdist 照用；每個 worker 各寫一份）
  python tools/platform/testcache_shadow.py report [--last N] [--dir D]           統計『若啟用會命中幾檔、省多少秒』（只讀）
環境變數：`MOTRIX_TESTCACHE_DIR`（預設 D:\\MOTRIX-TESTCACHE）、`MOTRIX_TESTCACHE_SHADOW_EXEC=1`（另用 sys.monitoring 記『實際執行到的 .py 檔』，供之後評估 L2 區塊粒度；有開銷，預設不開）。

## 記什麼（每個測試檔一筆；檔案 <DIR>/shadow/<run_id>/<worker>.json）
- `deps`：該檔收集＋執行期間**觀測到**的讀取（`open` 稽核事件、`os.listdir／scandir` 的目錄清單、**打開失敗的路徑＝ABSENT**）→ 內容 sha256；只收 repo 內的路徑
  （site-packages 由環境指紋涵蓋；暫存目錄、__pycache__、.git/ 不收）。
- session 級夾具／conftest／套件層收集期間的讀取記在 `session_deps`（所有檔共用；避免『第一個用到的檔記了、後面的檔漏記』的低估）。
- `flags`：`git`（子行程呼叫 git ⇒ 結果取決於 git 狀態，永遠不可快取）、`time`（原始碼讀現在時間 ⇒ 鍵要含日期）、`subprocess`、`external_read`（讀了 repo 外、非暫存的檔）。
- `key`：sha256(deps ‖ session_deps ‖ env_fp ‖ 日期〔僅 time 旗標〕)；`nodeids`：{id: outcome}；`secs`：該檔各題耗時合計。
- `report` 以後來的 run 對照先前**全綠且無 git 旗標**的同鍵紀錄，回報『會命中』的檔數與可省秒數——**純統計，沒有任何地方依它跳過測試**。
"""
import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

FLAG = "MOTRIX_TESTCACHE_SHADOW"
FORMAT = 1
_REPO = Path(__file__).resolve().parents[2]
_TIME_RE = re.compile(r"datetime\.now\(|date\.today\(|time\.time\(|datetime\.utcnow\(|time\.localtime\(")
_MAX_HASH_BYTES = 8 * 1024 * 1024
_GIT_RE = re.compile(r"(^|[\\/ '\"])git(\.exe)?([ '\",\]]|$)")


def root() -> Path:
    """被觀察的 repo 根（預設＝本檔所在 repo；測試用 MOTRIX_TESTCACHE_ROOT 指到暫存專案）。"""
    return Path(os.environ.get("MOTRIX_TESTCACHE_ROOT") or _REPO).resolve()


def enabled() -> bool:
    return os.environ.get(FLAG, "").strip() == "1"


def cache_dir() -> Path:
    return Path(os.environ.get("MOTRIX_TESTCACHE_DIR") or r"D:\MOTRIX-TESTCACHE")


def _sha_file(p: Path):
    try:
        if p.stat().st_size > _MAX_HASH_BYTES:
            return "BIG:%d" % p.stat().st_size
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return "ABSENT"


def _dir_sig(p: Path):
    try:
        return "DIR:" + hashlib.sha256("\n".join(sorted(os.listdir(p))).encode("utf-8", "replace")).hexdigest()
    except OSError:
        return "ABSENT"


def _under(p: Path, root: Path) -> bool:
    try:
        p.relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


class Recorder:
    """目前的『桶』（檔或 session）收集到的路徑；稽核鉤子只做 set.add，保持極輕。"""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.safe_roots = [Path(tempfile.gettempdir()).resolve(), Path(sys.prefix).resolve(), Path(getattr(sys, "base_prefix", sys.prefix)).resolve()]
        self.buckets = {}          # name -> {"paths": set, "dirs": set, "flags": set, "execs": set}
        self.current = "session"
        self.dead = False
        self.summary_line = ""
        self._mon = None

    def bucket(self, name):
        b = self.buckets.get(name)
        if b is None:
            b = self.buckets[name] = {"paths": set(), "dirs": set(), "flags": set(), "execs": set()}
        return b

    def _classify(self, s: str):
        """⇒ ("IN", repo 相對路徑) ｜ ("EXT", Path) ｜ None（雜訊）。"""
        try:
            p = Path(s)
            if not p.is_absolute():
                p = Path.cwd() / p
            p = Path(os.path.normpath(p))
        except (OSError, ValueError, TypeError):
            return None
        try:
            rel = p.relative_to(self.root)
        except ValueError:
            return ("EXT", p)
        parts = rel.parts
        if not parts or "__pycache__" in parts or parts[0] == ".git" or p.suffix == ".pyc" or ".pytest_cache" in parts:
            return None
        return ("IN", rel.as_posix())

    def on_event(self, event, args):
        if self.dead:
            return
        try:
            if event == "open":
                path = args[0]
                if isinstance(path, int) or not isinstance(path, (str, bytes, os.PathLike)):
                    return
                k = self._classify(os.fsdecode(path))
                if k is None:
                    return
                b = self.bucket(self.current)
                if k[0] == "IN":
                    b["paths"].add(k[1])
                else:
                    ep = k[1]
                    if not any(_under(ep, t) for t in self.safe_roots) and "site-packages" not in ep.parts and "ms-playwright" not in ep.parts:
                        b["flags"].add("external_read")
            elif event in ("os.listdir", "os.scandir"):
                path = args[0]
                if isinstance(path, (str, bytes, os.PathLike)):
                    k = self._classify(os.fsdecode(path))
                    if k and k[0] == "IN":
                        self.bucket(self.current)["dirs"].add(k[1])
            elif event in ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn"):
                b = self.bucket(self.current)
                b["flags"].add("subprocess")
                if _GIT_RE.search(" ".join(str(a) for a in args)[:2000].lower()):
                    b["flags"].add("git")
        except Exception:                                   # noqa: BLE001 — 鉤子絕不丟例外
            self.dead = True


_REC = None
_HOOKED = False
#: 本檔被載入（-p）當下的環境：早於 conftest 動手。backend/conftest.py 在 import 時設一堆每次不同的 MOTRIX_* 暫存路徑，不能進環境指紋
_ENV_AT_IMPORT = dict(os.environ)


def _env_fp():
    snap = {k: v for k, v in _ENV_AT_IMPORT.items() if k.startswith("MOTRIX_") and not k.startswith("MOTRIX_TESTCACHE") and k != FLAG}
    parts = {"python": sys.version.split()[0], "platform": sys.platform, "motrix_env": dict(sorted(snap.items()))}
    if "PYTEST_ADDOPTS" in _ENV_AT_IMPORT:
        parts["pytest_addopts"] = _ENV_AT_IMPORT["PYTEST_ADDOPTS"]
    bt = str(_REPO / "backend" / "tools")
    try:
        sys.path.insert(0, bt)
        import build_test_reuse as _b
        env = _b.current_env()
        env.pop("motrix_env", None)                         # 這兩項改用 import 當下的快照（見 _ENV_AT_IMPORT）
        env.pop("pytest_addopts", None)
        parts["env"] = hashlib.sha256(json.dumps(env, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    except Exception:                                       # noqa: BLE001 — 取不到就只用上面幾項
        parts["env"] = "n/a"
    finally:
        try:
            sys.path.remove(bt)
        except ValueError:
            pass
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _rel(nodeid: str) -> str:
    return nodeid.split("::", 1)[0].replace("\\", "/")


def _start_monitoring(rec):
    mon = getattr(sys, "monitoring", None)
    if mon is None:
        return
    tool = getattr(mon, "PROFILER_ID", 2)
    try:
        mon.use_tool_id(tool, "motrix_testcache_shadow")
    except ValueError:
        return

    def on_start(code, offset):
        try:
            fn = code.co_filename
            if fn and not fn.startswith("<"):
                k = rec._classify(fn)
                if k and k[0] == "IN":
                    rec.bucket(rec.current)["execs"].add(k[1])
        except Exception:                                   # noqa: BLE001
            pass
        return mon.DISABLE                                  # 同一個 code object 在本檔內只回報一次（檔界線用 restart_events 重新啟用）

    mon.register_callback(tool, mon.events.PY_START, on_start)
    mon.set_events(tool, mon.events.PY_START)
    rec._mon = mon


# ── pytest plugin hooks ─────────────────────────────────────────────────────────────────────────
def pytest_configure(config):
    global _REC, _HOOKED
    if not enabled():
        return
    try:
        _REC = Recorder(root())
        config._tcs_start = time.time()
        config._tcs_env = _env_fp()          # 在任何夾具動手之前算：conftest／_app 會設 MOTRIX_* 暫存路徑（每次不同），晚算會讓環境指紋每次都不一樣
        config._tcs_results = {}
        config._tcs_secs = {}
        if not _HOOKED:
            sys.addaudithook(lambda ev, a: _REC.on_event(ev, a) if _REC is not None else None)
            _HOOKED = True
        if os.environ.get("MOTRIX_TESTCACHE_SHADOW_EXEC", "").strip() == "1":
            _start_monitoring(_REC)
    except Exception as exc:                                # noqa: BLE001
        _REC = None
        sys.stderr.write("testcache_shadow: 停用（%s: %s）\n" % (type(exc).__name__, exc))


try:
    import pytest

    @pytest.hookimpl(hookwrapper=True)
    def pytest_make_collect_report(collector):
        if _REC is None:
            yield
            return
        prev = _REC.current
        try:
            _REC.current = (_rel(getattr(collector, "nodeid", "")) or prev) if collector.__class__.__name__ == "Module" else "session"
        except Exception:                                   # noqa: BLE001
            pass
        yield
        _REC.current = prev

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_protocol(item, nextitem):
        if _REC is None:
            yield
            return
        prev = _REC.current
        name = _rel(item.nodeid)
        _REC.current = name
        t0 = time.time()
        try:
            if _REC._mon is not None and prev != name:
                _REC._mon.restart_events()                  # 檔界線：重新啟用已 DISABLE 的位置，讓這個檔也記得到
        except Exception:                                   # noqa: BLE001
            pass
        yield
        try:
            item.config._tcs_secs[name] = item.config._tcs_secs.get(name, 0.0) + (time.time() - t0)
        except Exception:                                   # noqa: BLE001
            pass
        _REC.current = prev

    @pytest.hookimpl(hookwrapper=True)
    def pytest_fixture_setup(fixturedef, request):
        """session 級夾具的讀取（模板庫、app 啟動…）記到 session 桶，而不是剛好第一個用到它的檔。"""
        if _REC is None or getattr(fixturedef, "scope", "") != "session":
            yield
            return
        prev = _REC.current
        _REC.current = "session"
        yield
        _REC.current = prev

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(item, call):
        out = yield
        if _REC is None:
            return
        try:
            rep = out.get_result()
            res = item.config._tcs_results.setdefault(_rel(item.nodeid), {})
            if rep.when == "call":
                res[item.nodeid] = "passed" if rep.passed else ("skipped" if rep.skipped else "failed")
            elif rep.when == "setup" and not rep.passed:
                res[item.nodeid] = "skipped" if rep.skipped else "failed"
            elif rep.when == "teardown" and not rep.passed:
                res[item.nodeid] = "failed"
        except Exception:                                   # noqa: BLE001
            pass

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(session, exitstatus):
        if _REC is None:
            return
        try:
            _write(session)
        except Exception as exc:                            # noqa: BLE001
            sys.stderr.write("testcache_shadow: 寫入失敗，略過（%s: %s）\n" % (type(exc).__name__, exc))

    def pytest_terminal_summary(terminalreporter):
        if _REC is not None and _REC.summary_line:
            terminalreporter.write_line(_REC.summary_line)
except ImportError:                                         # 當 CLI 用、沒有 pytest 也能 import
    pass


def _hash_bucket(b):
    deps = {}
    for p in sorted(b["paths"]):
        deps[p] = _sha_file(root() / p)
    for d in sorted(b["dirs"]):
        deps["DIR:" + d] = _dir_sig(root() / d)
    return deps


def _write(session):
    rec = _REC
    config = session.config
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    run_id = os.environ.get("MOTRIX_TESTCACHE_RUN") or os.environ.get("PYTEST_XDIST_TESTRUNUID") or \
        "%s_%d" % (time.strftime("%Y%m%d_%H%M%S", time.localtime(config._tcs_start)), os.getppid() if worker != "main" else os.getpid())
    session_deps = _hash_bucket(rec.buckets["session"]) if "session" in rec.buckets else {}
    env_fp = getattr(config, "_tcs_env", None) or _env_fp()
    files = {}
    for name, b in sorted(rec.buckets.items()):
        if name == "session" or not name.endswith(".py"):
            continue
        deps = _hash_bucket(b)
        flags = set(b["flags"])
        rt = root()
        src_path = rt / name if (rt / name).exists() else rt / "backend" / name
        try:
            if _TIME_RE.search(src_path.read_text(encoding="utf-8", errors="replace")):
                flags.add("time")
        except OSError:
            pass
        deps.setdefault(src_path.relative_to(rt).as_posix() if src_path.exists() else name, _sha_file(src_path))
        results = config._tcs_results.get(name, {})
        green = bool(results) and all(v in ("passed", "skipped") for v in results.values())
        blob = json.dumps({"deps": deps, "session": session_deps, "env": env_fp, "day": time.strftime("%Y-%m-%d") if "time" in flags else ""},
                          sort_keys=True, ensure_ascii=False)
        files[name] = {"key": hashlib.sha256(blob.encode("utf-8")).hexdigest(), "deps": deps, "flags": sorted(flags), "execs": sorted(b["execs"]),
                       "nodeids": results, "green": green, "secs": round(config._tcs_secs.get(name, 0.0), 3)}
    out = cache_dir() / "shadow" / run_id
    out.mkdir(parents=True, exist_ok=True)
    doc = {"format": FORMAT, "run_id": run_id, "worker": worker, "created": time.strftime("%Y-%m-%d %H:%M:%S"), "env_fp": env_fp,
           "session_deps": session_deps, "files": files}
    tmp = out / (worker + ".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, out / (worker + ".json"))
    rec.summary_line = "testcache_shadow: 錄了 %d 個檔的依賴（只觀察，沒跳過任何一題）→ %s" % (len(files), out)


# ── report（只讀統計）────────────────────────────────────────────────────────────────────────────
def _load_runs(d: Path, last: int):
    runs = []
    root = d / "shadow"
    if not root.is_dir():
        return runs
    for r in sorted(root.iterdir(), key=lambda p: p.stat().st_mtime):
        files = {}
        for f in r.glob("*.json"):
            try:
                doc = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for name, e in doc.get("files", {}).items():
                cur = files.get(name)
                if cur is None:
                    files[name] = dict(e)
                else:                                       # 同一個檔被分到多個 worker：標記 multi（鍵不可靠 ⇒ report 當作不可快取）
                    cur["multi_worker"] = True
                    cur["secs"] = round(cur.get("secs", 0) + e.get("secs", 0), 3)
                    cur["green"] = cur.get("green", False) and e.get("green", False)
                    cur["flags"] = sorted(set(cur.get("flags", [])) | set(e.get("flags", [])))
        runs.append({"run_id": r.name, "files": files})
    return runs[-last:] if last else runs


def report(d: Path, last: int = 10):
    runs = _load_runs(d, last)
    if len(runs) < 2:
        print("影子紀錄不足（%d 個 run）；至少要 2 個 run 才能統計『會命中』" % len(runs))
        return 0
    seen = {}      # name -> {key: secs}：先前 run、全綠、無 git 旗標、非多 worker
    rows = []
    for run in runs:
        hit = miss = unc = 0
        saved = total = 0.0
        for name, e in run["files"].items():
            total += e.get("secs", 0)
            if "git" in e.get("flags", []) or e.get("multi_worker"):
                unc += 1
            elif e["key"] in seen.get(name, {}):
                hit += 1
                saved += seen[name][e["key"]]
            else:
                miss += 1
        rows.append((run["run_id"], len(run["files"]), hit, miss, unc, saved, total))
        for name, e in run["files"].items():
            if e.get("green") and "git" not in e.get("flags", []) and not e.get("multi_worker"):
                seen.setdefault(name, {})[e["key"]] = e.get("secs", 0)
    print("%-26s %6s %8s %6s %7s %10s %10s" % ("run", "files", "wouldHit", "miss", "uncach", "saved_s", "total_s"))
    for r in rows:
        print("%-26s %6d %8d %6d %7d %10.0f %10.0f" % r)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="測試結果快取影子錄製器的統計")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("report")
    p.add_argument("--last", type=int, default=10)
    p.add_argument("--dir", default="")
    a = ap.parse_args(argv)
    if a.cmd == "report":
        return report(Path(a.dir) if a.dir else cache_dir(), a.last)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                       # noqa: BLE001
        pass
    sys.exit(main())
