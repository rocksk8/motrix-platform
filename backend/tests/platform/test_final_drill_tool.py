# -*- coding: utf-8 -*-
"""D7 演練工具（tools/platform/final_drill.py）的安全前提：來源只讀、路徑守門、複製範圍。"""
import os
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
import final_drill as FD  # noqa: E402


def _db(path, wal=False):
    c = sqlite3.connect(str(path))
    if wal:
        c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE t (x)")
    c.execute("INSERT INTO t VALUES (1)")
    c.commit()
    c.close()


@pytest.mark.parametrize("wal", [False, True])
def test_ro_backup_does_not_touch_the_source(tmp_path, wal):
    src = tmp_path / "src" / "motrix_erp.db"
    src.parent.mkdir()
    _db(src, wal)
    before = (src.read_bytes(), src.stat().st_mtime_ns, sorted(p.name for p in src.parent.iterdir()))
    FD.ro_backup(str(src), str(tmp_path / "dst" / "motrix_erp.db"))
    assert (src.read_bytes(), src.stat().st_mtime_ns, sorted(p.name for p in src.parent.iterdir())) == before
    c = sqlite3.connect(str(tmp_path / "dst" / "motrix_erp.db"))
    assert c.execute("SELECT x FROM t").fetchall() == [(1,)]
    c.close()


def test_ro_backup_refuses_to_write_into_the_source(tmp_path):
    """反向控制：唯讀連線真的是唯讀（寫入會失敗）——證明上一題不是剛好沒寫。"""
    src = tmp_path / "a.db"
    _db(src)
    c = sqlite3.connect("file:%s?mode=ro" % src.as_posix(), uri=True)
    with pytest.raises(sqlite3.OperationalError):
        c.execute("INSERT INTO t VALUES (2)")
    c.close()


def test_install_path_with_v9_0_is_refused(tmp_path):
    with pytest.raises(AssertionError, match="V9.0"):
        FD.build_install(str(tmp_path), str(tmp_path / "V9.0" / "v9-install"))


def test_copy_skips_repo_and_env_directories(tmp_path):
    root = tmp_path / "v9"
    for rel in (".git/HEAD", "node_modules/x.js", ".venv312/lib.py", "deploy_packages/p.zip",
                "backend/__pycache__/a.pyc", "backend/main.py", "frontend/index.html"):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    got = sorted(os.path.relpath(p, root).replace("\\", "/") for p in FD._walk(str(root)))
    assert got == ["backend/main.py", "frontend/index.html"]


def test_ro_backup_captures_uncheckpointed_wal_content(tmp_path):
    """來源的最新資料還在 -wal 裡（另一條連線開著、還沒 checkpoint）⇒ 備份也要有那一筆；來源目錄的檔案清單不變。"""
    src = tmp_path / "src" / "motrix_erp.db"
    src.parent.mkdir()
    c = sqlite3.connect(str(src))
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA wal_autocheckpoint=0")
    c.execute("CREATE TABLE t (x)")
    c.execute("INSERT INTO t VALUES (42)")
    c.commit()                                                     # 連線不關 ⇒ 資料留在 -wal
    try:
        before = sorted(p.name for p in src.parent.iterdir())
        assert "motrix_erp.db-wal" in before
        FD.ro_backup(str(src), str(tmp_path / "dst" / "motrix_erp.db"))
        assert sorted(p.name for p in src.parent.iterdir()) == before
    finally:
        c.close()
    d = sqlite3.connect(str(tmp_path / "dst" / "motrix_erp.db"))
    assert d.execute("SELECT x FROM t").fetchall() == [(42,)]
    d.close()
