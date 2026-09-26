# -*- coding: utf-8 -*-
"""D7 演練工具（tools/platform/final_drill.py）的安全前提：來源只讀、路徑守門、複製範圍。"""
import os
import re
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


def _route_matches(template, path):
    """`/api/definitions/{kind}` 對得上 `/api/definitions/custom_module`（一個 {參數} 對一段）。"""
    parts = re.split(r"\{[^}]+\}", template)
    return re.fullmatch("[^/]+".join(re.escape(p) for p in parts), path) is not None


def test_smoke_route_matcher():
    assert _route_matches("/api/definitions/{kind}", "/api/definitions/custom_module")
    assert not _route_matches("/api/definitions/{kind}", "/api/definitions/a/b")
    assert _route_matches("/api/vouchers", "/api/vouchers") and not _route_matches("/api/voucher", "/api/vouchers")


def test_smoke_paths_are_real_routes_or_pages(client):
    """稽核 D：冒煙清單的每一條都必須是 app 的 GET 路由，或 frontend/ 底下真的有的頁面（打錯字不會在演練時才發現）。
    ⚠ 新版才有的端點（例：/api/definitions/{kind} 在第二批）要等那一包合回後才會在這裡成立 ⇒ 那時才加進清單。"""
    from tests._routes import all_routes
    gets = {p for p, methods, _r in all_routes(client.app) if "GET" in methods}
    front = REPO / "frontend"
    missing = []
    for name, method, path, skipped in FD.smoke_plan(str(REPO / "backend")):
        assert method == "GET", name
        if skipped:                       # 模組不在這棵樹（反向控制／產品選配）：它的路由本來就不在
            continue
        if path == "/" or path.endswith(".html"):
            target = front / ("index.html" if path == "/" else path.lstrip("/"))
            if not target.is_file():
                missing.append((name, path))
        elif not any(_route_matches(g, path) for g in gets):
            missing.append((name, path))
    assert not missing, "冒煙清單裡不存在的路徑：%s" % missing


def test_smoke_plan_skips_only_entries_of_absent_modules(tmp_path):
    """帶模組 key 的條目：模組不在包內 ⇒ 略過且寫出原因；在 ⇒ 照跑；不帶 key 的永遠照跑（合成樹，不綁真實模組）。"""
    keyed = [e for e in FD.SMOKE if len(e) > 3]
    if not keyed:
        pytest.skip("SMOKE 目前沒有帶模組 key 的條目 ⇒ 無對象")
    key = keyed[0][3]
    backend = tmp_path / "backend"
    (backend / "modules").mkdir(parents=True)
    absent = FD.smoke_plan(str(backend))
    assert [p[3] for p in absent if p[3]] and all(key in p[3] for p in absent if p[0] == keyed[0][0])
    assert all(p[3] is None for p, e in zip(absent, FD.SMOKE) if len(e) == 3)
    (backend / "modules" / key).mkdir()
    (backend / "modules" / key / "module.json").write_text("{}", encoding="utf-8")
    present = FD.smoke_plan(str(backend))
    assert all(p[3] is None for p, e in zip(present, FD.SMOKE) if len(e) == 3 or e[3] == key)


def test_logical_digest_ignores_bytes_but_not_content(tmp_path):
    """K-M1：6a 用邏輯內容比對「還原後＝原始庫」——Online Backup 的副本位元組不同也要相等；少一筆就不相等；檔案不在要報錯不是建空庫。"""
    src = tmp_path / "a.db"
    _db(src)
    cp = tmp_path / "b.db"
    FD.ro_backup(str(src), str(cp))
    assert FD.logical_digest(str(src)) == FD.logical_digest(str(cp))
    c = sqlite3.connect(str(cp))
    c.execute("INSERT INTO t VALUES (2)")
    c.commit()
    c.close()
    assert FD.logical_digest(str(src)) != FD.logical_digest(str(cp))
    with pytest.raises(FileNotFoundError):
        FD.logical_digest(str(tmp_path / "missing.db"))
    assert not (tmp_path / "missing.db").exists()


def _fake_6a(tmp_path, monkeypatch, *, equal=True, problems=()):
    """6a 的假環境：記下 rollback／start 的呼叫；source-backup 與還原後的主庫內容相同或不同。"""
    root = tmp_path / "drill"
    for rel in ("source-backup/backend", "v9-install/backend", FD.FIRST_BACKUP, FD.SECOND_BACKUP):
        (root / rel).mkdir(parents=True)
    _db(root / "source-backup" / "backend" / "motrix_erp.db")
    calls = []

    def rollback(install, backup_dir, mode, info):
        calls.append(("rollback", os.path.basename(backup_dir), mode))
        _db(Path(install) / "backend" / "motrix_erp.db")
        if not equal:
            c = sqlite3.connect(str(Path(install) / "backend" / "motrix_erp.db"))
            c.execute("INSERT INTO t VALUES (99)")
            c.commit()
            c.close()
        return list(problems)

    monkeypatch.setattr(FD.U, "rollback", rollback)
    monkeypatch.setattr(FD.T, "start_and_ping", lambda install, port: calls.append(("start",)) or {"ok": True, "status": 200})
    return str(root), calls


def test_full_rollback_uses_the_first_backup_and_checks_the_source(tmp_path, monkeypatch):
    """K-M1：6a 用第一份備份（轉換前的原始庫）做完整回滾；內容等於 source-backup ⇒ 才啟動 V9、判通過。"""
    root, calls = _fake_6a(tmp_path, monkeypatch)
    out = FD.full_rollback_step(root)
    assert calls == [("rollback", FD.FIRST_BACKUP, "full"), ("start",)]
    assert out["ok"] is True and out["logical_equal_to_source"] is True and out["backup"] == FD.FIRST_BACKUP


@pytest.mark.parametrize("equal,problems", [(False, ()), (True, ("雜湊不符",))])
def test_full_rollback_fails_when_not_equal_to_the_source(tmp_path, monkeypatch, equal, problems):
    """K-M1 反向控制：還原後內容與原始庫不同、或還原回報問題 ⇒ 判失敗，而且不啟動 V9。"""
    root, calls = _fake_6a(tmp_path, monkeypatch, equal=equal, problems=problems)
    out = FD.full_rollback_step(root)
    assert out["ok"] is False and ("start",) not in calls
    assert out["logical_equal_to_source"] is equal


def test_cleanup_keeps_the_scene_when_the_drill_failed(tmp_path):
    """K-S3：失敗 ⇒ 演練目錄全部保留並回傳路徑（寫進報告）；通過 ⇒ 刪；--keep-install ⇒ 保留。source-backup 一律不動。"""
    def make():
        for d in FD.DRILL_DIRS + ("source-backup",):
            (tmp_path / d).mkdir(exist_ok=True)
    make()
    kept = FD.cleanup(str(tmp_path), ok=False, keep=False)
    assert sorted(os.path.basename(k) for k in kept) == sorted(FD.DRILL_DIRS)
    assert all((tmp_path / d).is_dir() for d in FD.DRILL_DIRS)
    assert len(FD.cleanup(str(tmp_path), ok=True, keep=True)) == len(FD.DRILL_DIRS)
    assert FD.cleanup(str(tmp_path), ok=True, keep=False) == []
    assert not any((tmp_path / d).exists() for d in FD.DRILL_DIRS) and (tmp_path / "source-backup").is_dir()


def test_report_names_the_kept_directories(tmp_path):
    rep = {"at": "t", "v9_dir": "v", "drill_root": "r", "new_source": "n", "steps": [{"name": "6a", "ok": False}],
           "ok": False, "stopped_at": "6a", "kept_for_diagnosis": [str(tmp_path / "v9-install")]}
    FD.write_report(rep, str(tmp_path / "r.md"))
    text = (tmp_path / "r.md").read_text(encoding="utf-8")
    assert "保留" in text and str(tmp_path / "v9-install") in text


def test_every_smoke_module_key_is_registered():
    """稽核 ⑰ S-1：SMOKE 條目帶的模組 key 必須在 modules.json 登記（用 repo 的登記表，不用「樹上有沒有」判斷）。"""
    keys = {e[3] for e in FD.SMOKE if len(e) > 3}
    assert keys and keys <= FD.registered_module_keys(), keys - FD.registered_module_keys()


def test_rc_a_misspelled_smoke_key_is_not_a_legitimate_skip(tmp_path, monkeypatch):
    """反向控制：key 打錯（analytcs）⇒ smoke_plan 標成「未登記」而不是「不在包內」；smoke_ok 判不過。"""
    real = [e for e in FD.SMOKE if len(e) > 3][0]
    monkeypatch.setattr(FD, "SMOKE", [("首頁", "GET", "/"), (real[0], real[1], real[2], real[3] + "_typo")])
    plan = FD.smoke_plan(str(tmp_path), registered=FD.registered_module_keys())
    reasons = [p[3] for p in plan if p[3]]
    assert reasons and FD.UNREGISTERED in reasons[0], plan
    out = {"checks": [{"name": "首頁", "ok": True}],
           "skipped": [{"name": real[0], "path": real[2], "reason": reasons[0]}]}
    assert FD.smoke_ok(out) is False and out["unregistered_skips"]
    ok = {"checks": [{"name": "首頁", "ok": True}],
          "skipped": [{"name": real[0], "path": real[2], "reason": "模組 %s 不在安裝包" % real[3]}]}
    assert FD.smoke_ok(ok) is True                     # 正對照：真的不在包內的略過是合法的
