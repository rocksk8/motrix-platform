# -*- coding: utf-8 -*-
"""服務啟動時的資料庫寫入從哪裡來（CORE-SPEC 裁示 K-O2：啟動時寫 DB 只能經 `helpers/startup.py`）。

作法：把產品碼複製到拋棄式目錄，第一次啟動（`import main`）建庫，第二次啟動時包住 `sqlite3.connect`，
以 trace callback 記下每一句寫入 SQL 與當下的呼叫堆疊。堆疊裡有允許的檔案 ⇒ 合規：
- `helpers/startup.py`：啟動時的寫入全部列在這裡，每個設定鍵在 `core.upgrade` 分類（RUNTIME_STATE_SETTINGS）
- `db.py`、`core/migrations.py`：結構與 migration（冪等的 CREATE … IF NOT EXISTS、版本表）

只量「已經建好的庫再啟動一次」：升級驗證（tools/platform/upgrade.py::verify）看的就是這個情境。
量的是**執行的**寫入語句（含 INSERT OR IGNORE 這類不一定改到列的），不是改到的列數——要守的是「誰可以在啟動時寫」。

用法：python tools/platform/startup_writes.py            在目前的工作樹量一次並列出違規
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ALLOWED = ("helpers/startup.py", "db.py", "core/migrations.py")
SAFE_ENV = {"MOTRIX_DISABLE_SCHEDULERS": "1", "MOTRIX_CLOUD_ARCHIVE": "off", "MOTRIX_EMAIL_SEND": "off",
            "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
_IGNORE = shutil.ignore_patterns("tests", "__pycache__", "*.db", "*.db-wal", "*.db-shm", "uploads", "logs",
                                 "db_backups", "rollback_snapshots", "node_modules", ".venv*")

# 在子行程裡執行：包 sqlite3.connect、import main、等背景執行緒、寫出紀錄
_PROBE = r'''
import json, os, sqlite3, sys, threading, time, traceback
backend, out = os.path.abspath(sys.argv[1]), sys.argv[2]
os.chdir(backend); sys.path.insert(0, backend)
WRITE = ("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER")
rec, lock, real = [], threading.Lock(), sqlite3.connect
def connect(*a, **k):
    conn = real(*a, **k)
    def trace(sql):
        s = sql.strip()
        if s and s.split(None, 1)[0].upper() in WRITE:
            st = [(os.path.relpath(f.filename, backend).replace(os.sep, "/"), f.lineno, f.name)
                  for f in traceback.extract_stack()[:-1] if os.path.abspath(f.filename).startswith(backend)]
            with lock:
                rec.append({"sql": " ".join(s.split())[:200], "stack": st})
    conn.set_trace_callback(trace)
    return conn
sqlite3.connect = connect
import main  # noqa
time.sleep(float(os.environ.get("PROBE_SETTLE", "2")))
json.dump(rec, open(out, "w", encoding="utf-8"), ensure_ascii=False)
os._exit(0)
'''


def copy_product(dest: str) -> str:
    """複製 backend（不含測試、資料、快取）與 frontend 到 dest；回 dest/backend。"""
    shutil.copytree(REPO / "backend", os.path.join(dest, "backend"), ignore=_IGNORE)
    shutil.copytree(REPO / "frontend", os.path.join(dest, "frontend"), ignore=_IGNORE)
    return os.path.join(dest, "backend")


def _env(extra=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("MOTRIX_")}   # 測試行程的旗標不可以漏進來
    env.update(SAFE_ENV)
    env.update(extra or {})
    return env


def start_and_record(backend: str, out: str, create: bool = False, timeout: int = 240) -> list:
    probe = os.path.join(os.path.dirname(backend), "_startup_probe.py")
    Path(probe).write_text(_PROBE, encoding="utf-8")
    r = subprocess.run([sys.executable, probe, backend, out], cwd=backend, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout,
                       env=_env({"MOTRIX_CREATE_NEW_DB": "1"} if create else None))
    if r.returncode != 0 or not os.path.exists(out):
        raise RuntimeError("啟動失敗（exit %s）：%s" % (r.returncode, (r.stdout + r.stderr)[-2000:]))
    return json.loads(Path(out).read_text(encoding="utf-8"))


def violations(records) -> list:
    """堆疊裡沒有任何允許檔案的寫入。回 [(sql, 呼叫鏈)]，同一組只列一次。"""
    out, seen = [], set()
    for r in records:
        files = {f for f, _, _ in r["stack"]}
        if files & set(ALLOWED):
            continue
        chain = " > ".join("%s:%s" % (f, n) for f, _, n in r["stack"] if not f.startswith("<"))
        key = (r["sql"][:80], chain)
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def measure(backend: str, work: str) -> list:
    """已複製好的 backend：建庫一次、再啟動一次並回傳第二次的紀錄。"""
    start_and_record(backend, os.path.join(work, "first.json"), create=True)
    return start_and_record(backend, os.path.join(work, "second.json"))


def main():
    work = tempfile.mkdtemp(prefix="startup_writes_")
    try:
        rec = measure(copy_product(work), work)
        bad = violations(rec)
        print("寫入 %d 句；經 startup.py %d 句；違規 %d 組" % (
            len(rec), sum(1 for r in rec if "helpers/startup.py" in {f for f, _, _ in r["stack"]}), len(bad)))
        for sql, chain in bad:
            print("  %s\n    ← %s" % (sql, chain))
        return 1 if bad else 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
