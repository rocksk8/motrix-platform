"""STATES-PLATFORM R2：停用清單含不存在的 key；主庫被排他鎖住時讀停用清單。
用法（repo 根目錄）：python docs/platform/states/repro/r2_disabled_list.py"""
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "backend"))
from helpers import module_switches as ms  # noqa: E402

d = tempfile.mkdtemp(prefix="motrix-pytest-A-repro-")
p = os.path.join(d, "m.db")
c = sqlite3.connect(p)
c.execute("CREATE TABLE system_settings (key TEXT PRIMARY KEY, value_json TEXT, updated_at TEXT)")
c.execute("INSERT INTO system_settings VALUES ('modules_disabled', '[\"tender_radar\", \"ghost_module\"]', '')")
c.commit()
c.close()
print("含不存在的 key：", sorted(ms.read_disabled_at_startup(p)))
w = sqlite3.connect(p, isolation_level=None)
w.execute("BEGIN EXCLUSIVE")
t0 = time.time()
r = ms.read_disabled_at_startup(p)
print("排他鎖期間讀到：", sorted(r), "耗時 %.1fs" % (time.time() - t0))
w.execute("ROLLBACK")
w.close()
shutil.rmtree(d)
