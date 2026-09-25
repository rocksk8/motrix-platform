# -*- coding: utf-8 -*-
"""core.upgrade 契約（CORE-SPEC §9b）：純函式層，用合成的安裝目錄，不啟動伺服器。

端到端演練（V9 c83dae6e 程式＋啟動 ping）在 tests/test_upgrade_drill_2026_09_25.py。
"""
import json
import os
import shutil
import sqlite3
from datetime import date, timedelta

import pytest

from core import upgrade as U


# ── 合成安裝目錄 ──────────────────────────────────────────────────────────

def _make_db(path, version=116, settings=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE schema_version (id INTEGER PRIMARY KEY CHECK (id=1), version INTEGER, applied_at TEXT);
        CREATE TABLE system_settings (key TEXT PRIMARY KEY, value_json TEXT, updated_at TEXT);
        CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT);
    """)
    c.execute("INSERT INTO schema_version VALUES (1, ?, '')", (version,))
    for k, v in (settings or {"company_profile": {"companyName": "X"}, "pdf_base_path": ""}).items():
        c.execute("INSERT INTO system_settings VALUES (?,?,?)", (k, json.dumps(v), "2026-01-01T00:00:00"))
    c.executemany("INSERT INTO customers (name) VALUES (?)", [("a",), ("b",)])
    c.commit()
    c.close()


def _write(root, rel, data=b"x"):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)
    return p


@pytest.fixture()
def inst(tmp_path):
    root = str(tmp_path / "install")
    _write(root, "backend/db.py", b"# v9 db")
    _write(root, "backend/main.py", b"# v9 main")
    _write(root, "backend/routers/old_only_in_v9.py", b"# gone in new")
    _write(root, "frontend/index.html", b"<html>v9</html>")
    _make_db(os.path.join(root, "backend", "motrix_erp.db"))
    _write(root, "uploads/projects/1/p.jpg", b"photo")
    _write(root, "報價單PDF/Q-1.pdf", b"%PDF q")
    _write(root, "backend/export_archive/PS-202609-001_1.pdf", b"%PDF ps")
    _write(root, "backend/license.key", b"lic")
    _write(root, "backend/heartbeat_config.json", b"{}")
    _write(root, "backend/db_backups/%s/.done" % date.today().isoformat(), b"ok")
    return root


@pytest.fixture()
def new_src(tmp_path):
    src = str(tmp_path / "new")
    _write(src, "backend/db.py", b"# new db")
    _write(src, "backend/main.py", b"# new main")
    _write(src, "backend/core/paths.py", b"# new")
    _write(src, "frontend/index.html", b"<html>new</html>")
    _write(src, "uploads/should_not_copy.jpg", b"no")          # 來源裡的資料不可以被帶進去
    return src


# ── classify ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rel,kind", [
    ("backend/main.py", "program"), ("frontend/pages/x.html", "program"), ("tools/platform/upgrade.py", "program"),
    ("backend/motrix_erp.db", "db"), ("backend/motrix_erp.db-wal", "db"), ("backend/motrix_erp_demo.db-shm", "db"),
    ("uploads/a.jpg", "data"), ("報價單PDF/a.pdf", "data"), ("結案報表PDF/a.pdf", "data"),
    ("backend/export_archive/a.pdf", "data"), ("backend/db_backups/2026-09-25/motrix_erp.db", "data"),
    ("backend/_demo_pdf_archive/a.pdf", "data"), ("backend/logs/server.log", "data"),
    ("backend/motrix.db", "data"), ("backup_alerts/BACKUP_ALERT.txt", "data"),
    ("backend/license.key", "config"), ("backend/certs/key.pem", "config"), (".env", "config"),
    ("backend/.env.local", "config"), ("backend/heartbeat_config.json", "config"), (".no_email_send", "config"),
    ("backend/autostart.bat", "config"),                  # 稽核 X-9b M-4：機器設定（對外連線總開關）
    ("backend/restart.bat", "program"),
    ("backend/.build_commit", "program"),                 # S-CU12：打包 commit 跟著程式走
    ("backend/.deployed_commit.json", "config"),          # 部署工具寫的「這台機器套用過什麼」
    ("backend/__pycache__/x.pyc", "skip"),
])
def test_classify(rel, kind):
    assert U.classify(rel) == kind


# ── 設定只准新增 ──────────────────────────────────────────────────────────

def test_new_settings_are_listed_with_their_defaults():
    """新增的設定鍵與預設值，逐一列出（新增一個卻沒列 ⇒ 改這裡時要有人做決定）。"""
    assert U.NEW_SETTINGS == {"payslip_archive_path": ""}


def test_add_missing_settings_never_touches_existing_values(tmp_path):
    db = str(tmp_path / "s.db")
    _make_db(db, settings={"payslip_archive_path": "D:/custom", "company_profile": {"companyName": "X"}})
    before = U.settings_rows(db)
    c = sqlite3.connect(db)
    upd_before = dict(c.execute("SELECT key, updated_at FROM system_settings").fetchall())
    c.close()
    added = U.add_missing_settings(db, {"payslip_archive_path": "", "brand_new_key": {"a": 1}})
    assert added == {"brand_new_key": {"a": 1}}
    after = U.settings_rows(db)
    for k, v in before.items():
        assert after[k] == v, k                       # 既有值逐位元組相同
    c = sqlite3.connect(db)
    upd_after = dict(c.execute("SELECT key, updated_at FROM system_settings").fetchall())
    c.close()
    assert {k: upd_after[k] for k in upd_before} == upd_before
    assert json.loads(after["brand_new_key"]) == {"a": 1}


# ── 預檢 ─────────────────────────────────────────────────────────────────

def test_preflight_passes_on_healthy_install(inst):
    r = U.preflight(inst, v9_port_open=False)
    assert r["ok"], r["problems"]
    assert r["facts"]["schema_version"] == 116


@pytest.mark.parametrize("break_it,needle", [
    (lambda root: shutil.rmtree(os.path.join(root, "backend", "db_backups")), ".done"),
    (lambda root: _write(root, "backup_alerts/BACKUP_ALERT.txt", b"x"), "告警"),
    (lambda root: _write(root, ".no_email_send", b""), "開發機標記"),
    (lambda root: os.remove(os.path.join(root, "backend", "motrix_erp.db")), "主庫"),
    (lambda root: os.remove(os.path.join(root, "backend", "db.py")), "db.py"),
])
def test_preflight_each_check_can_fail(inst, break_it, needle):
    break_it(inst)
    r = U.preflight(inst, v9_port_open=False)
    assert not r["ok"] and any(needle in p for p in r["problems"]), r["problems"]


def test_preflight_rejects_stale_snapshot(inst):
    old = (date.today() - timedelta(days=3)).isoformat()
    os.rename(os.path.join(inst, "backend", "db_backups", date.today().isoformat()),
              os.path.join(inst, "backend", "db_backups", old))
    assert not U.preflight(inst, v9_port_open=False)["ok"]


def test_preflight_rejects_running_service_and_newer_schema(inst):
    assert any("服務" in p for p in U.preflight(inst, v9_port_open=True)["problems"])
    c = sqlite3.connect(os.path.join(inst, "backend", "motrix_erp.db"))
    c.execute("UPDATE schema_version SET version=117")
    c.commit()
    c.close()
    assert any("v117" in p for p in U.preflight(inst, v9_port_open=False)["problems"])


def test_preflight_rejects_low_disk(inst, monkeypatch):
    import collections
    Usage = collections.namedtuple("Usage", "total used free")
    monkeypatch.setattr(U.shutil, "disk_usage", lambda p: Usage(1, 1, 10))
    assert any("磁碟" in p for p in U.preflight(inst, v9_port_open=False)["problems"])


# ── 備份＋試還原 ─────────────────────────────────────────────────────────

def test_backup_is_restorable_and_data_stays_in_place(inst, tmp_path):
    bd = str(tmp_path / "bk")
    m = U.backup(inst, bd)
    assert U.verify_backup_restorable(bd) == []
    assert "backend/motrix_erp.db" in m["db"]
    assert "uploads/projects/1/p.jpg" in m["data_inventory"]
    assert not any("uploads/" in k or "PDF/" in k or "export_archive" in k for k in m["files"])  # 資料不複製，只列清單
    assert "backend/license.key" in m["config"] and "backend/main.py" in m["program"]


@pytest.mark.parametrize("tamper", ["corrupt", "extra", "missing"])
def test_backup_verification_catches_tampering(inst, tmp_path, tamper):
    bd = str(tmp_path / "bk")
    U.backup(inst, bd)
    target = os.path.join(bd, "program", "backend", "main.py")
    if tamper == "corrupt":
        with open(target, "ab") as f:
            f.write(b"!")
    elif tamper == "extra":
        _write(bd, "program/unexpected.py", b"x")
    else:
        os.remove(target)
    assert U.verify_backup_restorable(bd) != []


def test_backup_refuses_non_empty_dir(inst, tmp_path):
    bd = str(tmp_path / "bk")
    _write(bd, "leftover.txt")
    with pytest.raises(RuntimeError):
        U.backup(inst, bd)


# ── 轉換＋驗證 ───────────────────────────────────────────────────────────

def _convert(inst, new_src, bd):
    m = U.backup(inst, bd)
    U.replace_program(inst, new_src)
    U.add_missing_settings(os.path.join(inst, "backend", "motrix_erp.db"))
    return m


def test_replace_program_swaps_code_only(inst, new_src, tmp_path):
    m = _convert(inst, new_src, str(tmp_path / "bk"))
    assert not os.path.exists(os.path.join(inst, "backend", "routers", "old_only_in_v9.py"))
    assert open(os.path.join(inst, "backend", "main.py"), "rb").read() == b"# new main"
    assert not os.path.exists(os.path.join(inst, "uploads", "should_not_copy.jpg"))
    assert U.verify_conversion(inst, m) == []


@pytest.mark.parametrize("damage,needle", [
    ("setting", "既有設定"), ("row", "列數"), ("undeclared", "未宣告"), ("data", "資料目錄"),
])
def test_verify_conversion_catches_non_additive_changes(inst, new_src, tmp_path, damage, needle):
    m = _convert(inst, new_src, str(tmp_path / "bk"))
    db = os.path.join(inst, "backend", "motrix_erp.db")
    c = sqlite3.connect(db)
    if damage == "setting":
        c.execute("UPDATE system_settings SET value_json='\"changed\"' WHERE key='pdf_base_path'")
    elif damage == "row":
        c.execute("DELETE FROM customers WHERE id=1")
    elif damage == "undeclared":
        c.execute("INSERT INTO system_settings VALUES ('sneaky', '1', '')")
    c.commit()
    c.close()
    if damage == "data":
        _write(inst, "uploads/projects/1/p.jpg", b"changed")
    assert any(needle in p for p in U.verify_conversion(inst, m))


# ── 回滾 ─────────────────────────────────────────────────────────────────

def test_full_rollback_restores_program_db_and_config_by_hash(inst, new_src, tmp_path):
    bd = str(tmp_path / "bk")
    _convert(inst, new_src, bd)
    db = os.path.join(inst, "backend", "motrix_erp.db")
    c = sqlite3.connect(db)
    c.execute("INSERT INTO customers (name) VALUES ('after')")
    c.commit()
    c.close()
    _write(inst, "backend/.initial_admin_credentials.txt", b"new-version-wrote-this")
    _write(inst, "backend/license.key", b"changed")
    assert U.rows_added_since(U.load_manifest(bd), db) == {"customers": 1, "system_settings": 1}
    assert U.rollback(inst, bd, "full") == []
    assert open(os.path.join(inst, "backend", "main.py"), "rb").read() == b"# v9 main"
    assert os.path.exists(os.path.join(inst, "backend", "routers", "old_only_in_v9.py"))
    assert not os.path.exists(os.path.join(inst, "backend", "core", "paths.py"))
    assert not os.path.exists(os.path.join(inst, "backend", ".initial_admin_credentials.txt"))
    assert open(os.path.join(inst, "backend", "license.key"), "rb").read() == b"lic"
    assert U.table_counts(db)["customers"] == 2


def test_code_only_rollback_keeps_new_data(inst, new_src, tmp_path):
    bd = str(tmp_path / "bk")
    _convert(inst, new_src, bd)
    db = os.path.join(inst, "backend", "motrix_erp.db")
    c = sqlite3.connect(db)
    c.execute("INSERT INTO customers (name) VALUES ('after')")
    c.commit()
    c.close()
    assert U.rollback(inst, bd, "code") == []
    assert open(os.path.join(inst, "frontend", "index.html"), "rb").read() == b"<html>v9</html>"
    assert U.table_counts(db)["customers"] == 3


def test_verify_rollback_catches_a_mismatch(inst, new_src, tmp_path):
    """反向控制：回滾後任何一個程式／設定／DB 雜湊不符，驗證都要報出來。"""
    bd = str(tmp_path / "bk")
    _convert(inst, new_src, bd)
    assert U.rollback(inst, bd, "full") == []
    m = U.load_manifest(bd)
    _write(inst, "backend/main.py", b"# tampered")
    assert any("程式檔" in p for p in U.verify_rollback(inst, m, "full"))
    U.rollback(inst, bd, "full")
    _write(inst, "backend/license.key", b"tampered")
    assert any("設定檔" in p for p in U.verify_rollback(inst, m, "full"))
    U.rollback(inst, bd, "full")
    c = sqlite3.connect(os.path.join(inst, "backend", "motrix_erp.db"))
    c.execute("INSERT INTO customers (name) VALUES ('z')")
    c.commit()
    c.close()
    assert any("資料庫" in p for p in U.verify_rollback(inst, m, "full"))


def test_layout_is_derived_from_core_paths():
    """版面常數從 core.paths 推導（單一來源）：PDF 目錄 7 個全在資料類。"""
    from core import paths
    for _k, (_key, d) in paths.PDF_ARCHIVES.items():
        rel = os.path.relpath(d, paths.INSTALL_ROOT).replace("\\", "/")
        assert U.classify(rel + "/x.pdf") == "data", rel


def test_backup_and_source_must_live_outside_the_install(inst, new_src):
    with pytest.raises(RuntimeError):
        U.backup(inst, os.path.join(inst, "upgrade_backup"))
    with pytest.raises(RuntimeError):
        U.replace_program(inst, os.path.join(inst, "backend"))


# ── 安裝目錄以外的 PDF 目錄（只記摘要；變少才算錯；連不到只警告）─────────────

def _set_pdf_base(inst, path):
    c = sqlite3.connect(os.path.join(inst, "backend", "motrix_erp.db"))
    c.execute("INSERT OR REPLACE INTO system_settings VALUES ('pdf_base_path', ?, '')", (json.dumps(path),))
    c.commit()
    c.close()


def test_external_pdf_dir_is_summarised_not_hashed(inst, tmp_path):
    ext = str(tmp_path / "netshare_pdf")
    _write(ext, "Q-1.pdf", b"%PDF 1")
    _write(ext, "sub/Q-2.pdf", b"%PDF 22")
    _set_pdf_base(inst, ext)
    m = U.backup(inst, str(tmp_path / "bk"))
    e = m["external_dirs"]["pdf_base_path"]
    assert e["status"] == "ok" and e["files"] == 2 and e["bytes"] == 13 and e["latest_mtime"]
    assert "sha256" not in json.dumps(e)
    assert U.preflight(inst, v9_port_open=False)["facts"]["external_pdf_dirs"] == {"pdf_base_path": ext}


def test_external_growth_is_fine_shrink_is_a_problem(inst, tmp_path):
    ext = str(tmp_path / "netshare_pdf")
    _write(ext, "Q-1.pdf", b"%PDF 1")
    _set_pdf_base(inst, ext)
    m = U.backup(inst, str(tmp_path / "bk"))
    _write(ext, "Q-new.pdf", b"%PDF new")                  # 轉換期間多了檔：可以
    assert U.verify_external(m) == []
    os.remove(os.path.join(ext, "Q-1.pdf"))
    os.remove(os.path.join(ext, "Q-new.pdf"))              # 變少：錯
    assert any("變少" in p for p in U.verify_external(m))


def test_unreachable_external_dir_only_warns(inst, tmp_path):
    ext = str(tmp_path / "netshare_pdf")
    _write(ext, "Q-1.pdf", b"%PDF 1")
    _set_pdf_base(inst, ext)
    m = U.backup(inst, str(tmp_path / "bk"))
    shutil.rmtree(ext)                                     # 模擬網路碟掛不上
    warnings = []
    assert U.verify_external(m, warnings) == []
    assert warnings and "無法確認" in warnings[0]


def test_external_scan_times_out_as_unreachable(tmp_path, monkeypatch):
    import time as _t
    ext = str(tmp_path / "slow")
    _write(ext, "a.pdf")
    real_walk = os.walk
    monkeypatch.setattr(U.os, "walk", lambda p: (_t.sleep(2), real_walk(p))[1])
    r = U.external_summary(ext, timeout=0.2)
    assert r["status"] == "unreachable" and "逾時" in r["reason"]


def test_default_pdf_dirs_inside_install_are_not_external(inst):
    assert U.external_pdf_dirs(inst, {"pdf_base_path": json.dumps(os.path.join(inst, "報價單PDF")),
                                      "shipping_pdf_base_path": json.dumps("")}) == {}


# ── 公司資料只補空值（A8c 的升級側）──────────────────────────────────────

def _profile_db(tmp_path, profile):
    db = str(tmp_path / "p.db")
    _make_db(db, settings={"company_profile": profile})
    return db


def _profile(db):
    return json.loads(U.settings_rows(db)["company_profile"])


def test_company_profile_blanks_are_filled_from_v9_constants(tmp_path):
    """V9 種子形狀（name／tax_id，沒有英文名、電話、email）⇒ 只補缺的三欄。"""
    db = _profile_db(tmp_path, {"name": "允碩整合集創股份有限公司", "tax_id": "60575481", "contact_info": ""})
    r = U.fill_company_profile_blanks(db)
    assert r["filled"] == {"company_name_en": "MOTRIX Synergy Integration Corp.",
                           "phone": "04-3610-6566", "email": "info@miactw.com"}
    p = _profile(db)
    assert p["name"] == "允碩整合集創股份有限公司" and p["tax_id"] == "60575481"
    assert "company_name" not in p and "taxId" not in p           # name／tax_id 已是 company_identity 讀得到的值 ⇒ 不補


def test_phone_and_email_inside_contact_info_count_as_existing(tmp_path):
    db = _profile_db(tmp_path, {"name": "允碩整合集創股份有限公司", "tax_id": "60575481",
                                "contact_info": "Tel: 02-1111-2222｜mine@example.invalid"})
    assert U.fill_company_profile_blanks(db)["filled"] == {"company_name_en": "MOTRIX Synergy Integration Corp."}


def test_existing_company_profile_values_are_never_overwritten(tmp_path):
    before = {"companyName": "允碩整合集創股份有限公司", "taxId": "60575481", "phone": "02-9999-0000",
              "email": "someone@example.invalid", "companyNameEn": "Custom EN"}
    db = _profile_db(tmp_path, before)
    assert U.fill_company_profile_blanks(db)["filled"] == {}
    assert _profile(db) == before


def test_other_companies_install_is_not_stamped_with_our_data(tmp_path):
    db = _profile_db(tmp_path, {"name": "別家公司", "tax_id": "12345678"})
    r = U.fill_company_profile_blanks(db)
    assert r["filled"] == {} and "看不出是本公司安裝" in r["skipped"]
    assert _profile(db) == {"name": "別家公司", "tax_id": "12345678"}


def test_verify_accepts_the_fill_but_not_a_rewrite(inst, new_src, tmp_path):
    db = os.path.join(inst, "backend", "motrix_erp.db")
    c = sqlite3.connect(db)
    c.execute("INSERT OR REPLACE INTO system_settings VALUES ('company_profile', ?, '')",
              (json.dumps({"name": "允碩整合集創股份有限公司", "tax_id": "60575481"}),))
    c.commit()
    c.close()
    m = _convert(inst, new_src, str(tmp_path / "bk"))
    U.fill_company_profile_blanks(db)
    assert U.verify_conversion(inst, m) == []                     # 只多出補的欄位 ⇒ 通過
    c = sqlite3.connect(db)
    c.execute("UPDATE system_settings SET value_json=? WHERE key='company_profile'",
              (json.dumps({"name": "改掉了", "tax_id": "60575481"}),))
    c.commit()
    c.close()
    assert any("company_profile" in p for p in U.verify_conversion(inst, m))



# ══════════════════════════════════════════════════════════════════════════════
# 稽核 X-9b（AUDIT-X-9b-upgrade-paths-pii.md）
# ══════════════════════════════════════════════════════════════════════════════

def _tool(monkeypatch):
    """tools/platform/upgrade.py（CLI 層）；migration 與啟動換成假的（不起子行程）。"""
    import importlib
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "platform"))
    T = importlib.import_module("upgrade")
    monkeypatch.setattr(T, "run_migrations",
                        lambda root: type("R", (), {"returncode": 0, "stdout": "MIGRATE_OK", "stderr": ""})())
    monkeypatch.setattr(T, "start_and_ping", lambda *a, **k: {"ok": True, "status": 200, "seconds": 0, "log": ""})
    return T


def _db(inst):
    return os.path.join(inst, "backend", "motrix_erp.db")


def _sql(inst, sql, args=()):
    c = sqlite3.connect(_db(inst))
    c.execute(sql, args)
    c.commit()
    c.close()


def _set_profile(inst, profile):
    _sql(inst, "INSERT OR REPLACE INTO system_settings VALUES ('company_profile', ?, '')",
         (json.dumps(profile, ensure_ascii=False),))


def _backup_verified(T, inst, bd):
    U.backup(inst, bd)
    T._write_log(bd, "backup_verify.json", {"problems": U.verify_backup_restorable(bd)})


# ── M-1：啟動後的比對與 verify_conversion 共用判準（補空值不是改寫）──────────

def test_m1_full_verify_accepts_the_company_fill(inst, new_src, tmp_path, monkeypatch):
    """本公司、欄位不齊 ⇒ 轉換補欄位 ⇒ **整個** T.verify（含啟動後比對）要過。修正前：exit 3 假紅。"""
    T = _tool(monkeypatch)
    _set_profile(inst, {"name": "允碩整合集創股份有限公司", "tax_id": "60575481", "contact_info": "04-3610-6566"})
    bd = str(tmp_path / "bk")
    _backup_verified(T, inst, bd)
    rep = T.convert(inst, bd, new_src)
    assert set(rep["company_profile"]["filled"]) == {"company_name_en", "email"}
    assert T.verify(inst, bd, 1) == []


def test_m1_rewrite_during_startup_is_still_caught(inst, new_src, tmp_path, monkeypatch):
    """反向控制：新版啟動時把既有設定改掉 ⇒ 啟動後比對要紅（共用判準沒有把它放寬成不看）。"""
    T = _tool(monkeypatch)
    _set_profile(inst, {"name": "允碩整合集創股份有限公司", "tax_id": "60575481", "contact_info": ""})
    bd = str(tmp_path / "bk")
    _backup_verified(T, inst, bd)
    T.convert(inst, bd, new_src)

    def start_and_rewrite(root, port, **k):
        _sql(root, "UPDATE system_settings SET value_json='\"rewritten\"' WHERE key='pdf_base_path'")
        return {"ok": True, "status": 200, "seconds": 0, "log": ""}
    monkeypatch.setattr(T, "start_and_ping", start_and_rewrite)
    assert any("新版啟動後改寫了既有設定：['pdf_base_path']" in p for p in T.verify(inst, bd, 1))


def test_m1_cli_verify_failure_suggests_rollback_with_commands(inst, new_src, tmp_path, monkeypatch, capsys):
    """CORE-SPEC §9b 主持裁示：驗證不過不自動回滾，明確建議並附指令。"""
    T = _tool(monkeypatch)
    bd = str(tmp_path / "bk")
    _backup_verified(T, inst, bd)
    T.convert(inst, bd, new_src)
    _sql(inst, "DELETE FROM customers WHERE id=1")
    assert T.main(["verify", "--root", inst, "--backup-dir", bd, "--port", "1"]) == 3
    out = capsys.readouterr().out
    assert "建議執行回滾" in out and "--mode code" in out and "--mode full" in out
    assert os.path.exists(os.path.join(inst, "backend", "core", "paths.py")), "驗證不過時工具自己動了程式檔"


# ── B-2（AUDIT-X-C-batch1）：鍵存在、值是空字串 ⇒ 補值不是改寫 ─────────────────

def test_b2_blank_string_fill_passes_verify(inst, new_src, tmp_path):
    _set_profile(inst, {"name": "允碩整合集創股份有限公司", "tax_id": "", "contact_info": "", "phone": "  "})
    m = _convert(inst, new_src, str(tmp_path / "bk"))
    filled = U.fill_company_profile_blanks(_db(inst))["filled"]
    assert {"tax_id", "phone"} <= set(filled)
    assert U.verify_conversion(inst, m) == []


@pytest.mark.parametrize("after", [
    {"name": "允碩整合集創股份有限公司", "tax_id": "99999999", "contact_info": ""},       # 空值補成不是補值的值
    {"name": "改掉了", "tax_id": "", "contact_info": ""},                                # 有值的欄位被改
    {"name": "允碩整合集創股份有限公司", "tax_id": ""},                                   # 刪鍵
    {"name": "允碩整合集創股份有限公司", "tax_id": "", "contact_info": "", "x": "1"},     # 未宣告的新欄
])
def test_b2_other_changes_to_company_profile_are_rewrites(inst, new_src, tmp_path, after):
    _set_profile(inst, {"name": "允碩整合集創股份有限公司", "tax_id": "", "contact_info": ""})
    m = _convert(inst, new_src, str(tmp_path / "bk"))
    _set_profile(inst, after)
    assert "既有設定被改寫或刪除：company_profile" in U.verify_conversion(inst, m)


# ── M-2：回滾只核對「備份時就在的檔」；新增的列成資訊 ──────────────────────────

def _after_conversion_files(inst):
    _write(inst, "uploads/projects/9/after.jpg", b"new")                       # 使用者上傳
    _write(inst, "backend/db_backups/2099-01-01/.done", b"ok")                  # 新版做的每日快照
    shutil.rmtree(os.path.join(inst, "backend", "db_backups", date.today().isoformat()))  # 保留期限清掉舊快照


@pytest.mark.parametrize("mode", ["code", "full"])
def test_m2_rollback_passes_when_new_version_wrote_files(inst, new_src, tmp_path, mode):
    bd = str(tmp_path / "bk")
    _convert(inst, new_src, bd)
    _after_conversion_files(inst)
    info = {}
    assert U.rollback(inst, bd, mode, info) == []
    assert "uploads/projects/9/after.jpg" in info["data_added"]
    assert "backend/db_backups/2099-01-01/.done" in info["data_added"]
    assert info["data_rotated"] == ["backend/db_backups/%s/.done" % date.today().isoformat()]
    assert os.path.isfile(os.path.join(inst, "uploads", "projects", "9", "after.jpg"))   # 回滾不動資料目錄


@pytest.mark.parametrize("damage", ["missing", "changed"])
@pytest.mark.parametrize("mode", ["code", "full"])
def test_m2_rollback_still_catches_lost_or_changed_data(inst, new_src, tmp_path, mode, damage):
    """反向控制：備份時就在的資料檔不見或被改 ⇒ 仍然是 problem（放寬的只有「新增」與快照輪替）。"""
    bd = str(tmp_path / "bk")
    _convert(inst, new_src, bd)
    target = os.path.join(inst, "uploads", "projects", "1", "p.jpg")
    if damage == "missing":
        os.remove(target)
    else:
        _write(inst, "uploads/projects/1/p.jpg", b"changed")
    probs = U.rollback(inst, bd, mode)
    assert any("uploads/projects/1/p.jpg" in p for p in probs), probs


# ── M-4：autostart.bat 是機器設定 ────────────────────────────────────────────

_AUTOSTART_MACHINE = b"::set MOTRIX_GEO=1\r\n"      # 這台機器關掉了對外連線
_AUTOSTART_PACKAGE = b"set MOTRIX_GEO=1\r\n"


def test_m4_autostart_is_kept_and_differences_are_reported(inst, new_src, tmp_path):
    _write(inst, "backend/autostart.bat", _AUTOSTART_MACHINE)
    _write(new_src, "backend/autostart.bat", _AUTOSTART_PACKAGE)
    bd = str(tmp_path / "bk")
    m = U.backup(inst, bd)
    assert "backend/autostart.bat" in m["config"] and "backend/autostart.bat" not in m["program"]
    U.replace_program(inst, new_src)
    rep = U.sync_package_default_config(inst, new_src)
    assert rep == {"added": [], "kept_differs_from_package": ["backend/autostart.bat"]}
    assert open(os.path.join(inst, "backend", "autostart.bat"), "rb").read() == _AUTOSTART_MACHINE
    assert U.verify_conversion(inst, m) == []


def test_m4_verify_sees_an_overwritten_autostart(inst, new_src, tmp_path):
    """反向控制：轉換（或任何人）把機器上的 autostart.bat 換掉 ⇒ verify 要看得到。"""
    _write(inst, "backend/autostart.bat", _AUTOSTART_MACHINE)
    m = _convert(inst, new_src, str(tmp_path / "bk"))
    _write(inst, "backend/autostart.bat", _AUTOSTART_PACKAGE)
    assert "設定檔被改寫或刪除：['backend/autostart.bat']" in U.verify_conversion(inst, m)


def test_m4_missing_autostart_is_added_from_the_package(inst, new_src):
    _write(new_src, "backend/autostart.bat", _AUTOSTART_PACKAGE)
    assert U.sync_package_default_config(inst, new_src)["added"] == ["backend/autostart.bat"]
    assert open(os.path.join(inst, "backend", "autostart.bat"), "rb").read() == _AUTOSTART_PACKAGE


def test_m4_only_declared_package_defaults_are_copied(inst, new_src):
    """新版包裡的其他設定類檔（開發機標記、授權）**不可以**被帶進安裝目錄。"""
    _write(new_src, ".no_email_send", b"")
    _write(new_src, "backend/license.key", b"dev-license")
    U.sync_package_default_config(inst, new_src)
    assert not os.path.exists(os.path.join(inst, ".no_email_send"))
    assert open(os.path.join(inst, "backend", "license.key"), "rb").read() == b"lic"


# ── S-1：回滾（與轉換）動手前重驗備份 ──────────────────────────────────────────

def _install_snapshot(root):
    return {rel: U.sha256_file(f) for rel, f in U.walk(root)}


def test_s1_rollback_refuses_another_installs_backup(inst, new_src, tmp_path):
    other = str(tmp_path / "other")
    shutil.copytree(inst, other)
    bd_other = str(tmp_path / "bk_other")
    U.backup(other, bd_other)
    _convert(inst, new_src, str(tmp_path / "bk"))
    before = _install_snapshot(inst)
    info = {}
    probs = U.rollback(inst, bd_other, "full", info)
    assert info.get("precheck_failed") and any("不是這個安裝目錄的" in p for p in probs)
    assert _install_snapshot(inst) == before, "拿別人的備份回滾，卻動了檔案"


def test_s1_rollback_with_damaged_backup_deletes_nothing(inst, new_src, tmp_path):
    bd = str(tmp_path / "bk")
    _convert(inst, new_src, bd)
    os.remove(os.path.join(bd, "program", "backend", "main.py"))
    before = _install_snapshot(inst)
    info = {}
    probs = U.rollback(inst, bd, "code", info)
    assert info.get("precheck_failed") and probs and all("沒有動任何檔案" in p for p in probs)
    assert _install_snapshot(inst) == before


def test_s1_convert_rechecks_the_backup(inst, new_src, tmp_path, monkeypatch):
    """RC1c：備份驗過之後才被改 ⇒ convert 拒絕，一個檔都不動。"""
    T = _tool(monkeypatch)
    bd = str(tmp_path / "bk")
    _backup_verified(T, inst, bd)
    with open(os.path.join(bd, "program", "backend", "main.py"), "ab") as f:
        f.write(b"!")
    before = _install_snapshot(inst)
    with pytest.raises(RuntimeError, match="重驗備份不通過"):
        T.convert(inst, bd, new_src)
    assert _install_snapshot(inst) == before


def test_s1_cli_precheck_failure_exits_7(inst, new_src, tmp_path, monkeypatch):
    T = _tool(monkeypatch)
    bd = str(tmp_path / "bk")
    _convert(inst, new_src, bd)
    os.remove(os.path.join(bd, "program", "backend", "main.py"))
    assert T.main(["rollback", "--root", inst, "--backup-dir", bd, "--mode", "code"]) == 7


# ── S-2／O-7：試還原可以重跑；DB 讀不了列成 problem ─────────────────────────────

def test_s2_restore_check_can_be_rerun_after_tool_logs(inst, tmp_path, monkeypatch):
    T = _tool(monkeypatch)
    bd = str(tmp_path / "bk")
    _backup_verified(T, inst, bd)
    for name in ("conversion_log.json", "verify_log.json", "rollback_code.json", "post_convert.json"):
        T._write_log(bd, name, {})
    assert U.verify_backup_restorable(bd) == []
    _write(bd, "program/stray.json", b"{}")                  # 反向控制：只有最上層的工具紀錄檔被排除
    assert U.verify_backup_restorable(bd) != []


@pytest.mark.parametrize("rel", ["backend/motrix_erp.db", "backend/motrix_erp_demo.db"])
def test_s2_corrupt_db_header_is_a_problem_not_an_exception(inst, tmp_path, rel):
    _make_db(os.path.join(inst, "backend", "motrix_erp_demo.db"))
    bd = str(tmp_path / "bk")
    m = U.backup(inst, bd)
    p = os.path.join(bd, "db", rel)
    with open(p, "r+b") as f:
        f.write(b"XXXX")                                     # 標頭 "SQLite format 3" 被毀
    m["files"]["db/" + rel] = U.sha256_file(p)               # 連 manifest 一起改（只剩 DB 檢查擋得住）
    probs = U.verify_backup_restorable(bd, m)
    assert any(rel in x for x in probs), probs


# ── S-3：只准新增 ⇒ 驗內容；完整回滾的提示說得出會失去什麼 ──────────────────────

def test_s3_rewrite_with_same_row_count_is_caught(inst, new_src, tmp_path):
    m = _convert(inst, new_src, str(tmp_path / "bk"))
    _sql(inst, "UPDATE customers SET name='rewritten' WHERE id=1")
    assert "既有資料被改寫（列數相同、內容不同）：['customers']" in U.verify_conversion(inst, m)


def test_s3_added_column_by_migration_is_not_a_rewrite(inst, new_src, tmp_path):
    m = _convert(inst, new_src, str(tmp_path / "bk"))
    _sql(inst, "ALTER TABLE customers ADD COLUMN new_col TEXT DEFAULT 'x'")
    assert U.verify_conversion(inst, m) == []


def test_s3_changes_since_conversion_excludes_the_conversion_itself(inst, new_src, tmp_path):
    bd = str(tmp_path / "bk")
    _convert(inst, new_src, bd)
    _sql(inst, "CREATE TABLE module_new (id INTEGER PRIMARY KEY)")
    U.record_post_conversion(inst, bd)
    empty = U.changes_since_conversion(bd, _db(inst))
    assert empty["baseline"] == "post_convert" and not U.has_changes(empty), empty
    _sql(inst, "INSERT INTO customers (name) VALUES ('after')")
    _sql(inst, "UPDATE customers SET name='rewritten' WHERE id=1")
    _sql(inst, "INSERT INTO module_new DEFAULT VALUES")
    rep = U.changes_since_conversion(bd, _db(inst))
    assert rep["rows_added"] == {"customers": 1, "module_new": 1} and rep["new_tables"] == {}
    _sql(inst, "DELETE FROM customers WHERE name='after'")
    rep = U.changes_since_conversion(bd, _db(inst))
    assert rep["rewritten"] == ["customers"] and rep["rows_added"] == {"module_new": 1}
    os.remove(os.path.join(bd, U.POST_CONVERT_NAME))          # 轉換沒做完 ⇒ 退回備份當下
    rep = U.changes_since_conversion(bd, _db(inst))
    assert rep["baseline"] == "backup" and rep["new_tables"] == {"module_new": 1}
    assert rep["rows_added"].get("system_settings") == 1       # 轉換本身寫的那一列也算進去（並註明）


def test_s3_cli_full_rollback_without_yes_lists_changes(inst, new_src, tmp_path, monkeypatch, capsys):
    T = _tool(monkeypatch)
    bd = str(tmp_path / "bk")
    _backup_verified(T, inst, bd)
    T.convert(inst, bd, new_src)
    _sql(inst, "INSERT INTO customers (name) VALUES ('after')")
    assert T.main(["rollback", "--root", inst, "--backup-dir", bd, "--mode", "full"]) == 4
    out = capsys.readouterr().out
    assert '新增的列：{"customers": 1}' in out and "轉換完成當下" in out
    assert os.path.exists(os.path.join(inst, "backend", "core", "paths.py")), "沒有 --yes 卻回滾了"


# ── S-4：回滾後自動 ping V9，只印結果 ─────────────────────────────────────────

@pytest.mark.parametrize("ping_ok,code", [(True, 0), (False, 6)])
def test_s4_rollback_pings_v9_and_reports(inst, new_src, tmp_path, monkeypatch, capsys, ping_ok, code):
    T = _tool(monkeypatch)
    seen = []

    def fake_ping(root, port, **k):
        seen.append((root, port, open(os.path.join(root, "backend", "main.py"), "rb").read()))
        return {"ok": ping_ok, "status": 200 if ping_ok else None, "seconds": 0, "log": "boom"}
    monkeypatch.setattr(T, "start_and_ping", fake_ping)
    bd = str(tmp_path / "bk")
    _backup_verified(T, inst, bd)
    T.convert(inst, bd, new_src)
    assert T.main(["rollback", "--root", inst, "--backup-dir", bd, "--mode", "code", "--ping-port", "6999"]) == code
    assert seen == [(inst, 6999, b"# v9 main")], "ping 的不是回滾後的 V9"
    out = capsys.readouterr().out
    assert ("200 OK" if ping_ok else "失敗") in out
    log = json.load(open(os.path.join(bd, "rollback_code.json"), encoding="utf-8"))
    assert log["v9_ping"]["ok"] is ping_ok


def test_s4_no_ping_skips_and_says_so(inst, new_src, tmp_path, monkeypatch, capsys):
    T = _tool(monkeypatch)
    monkeypatch.setattr(T, "start_and_ping", lambda *a, **k: pytest.fail("--no-ping 仍然啟動了 V9"))
    bd = str(tmp_path / "bk")
    _backup_verified(T, inst, bd)
    T.convert(inst, bd, new_src)
    assert T.main(["rollback", "--root", inst, "--backup-dir", bd, "--mode", "code", "--no-ping"]) == 0
    assert "手動確認" in capsys.readouterr().out


# ── S-7：被刪、新版沒有的檔要列出來 ──────────────────────────────────────────

def test_s7_removed_files_without_replacement_are_listed(inst, new_src):
    _write(inst, "運維備註.txt", b"note")
    rep = U.replace_program(inst, new_src)
    assert rep["removed_without_replacement"] == ["backend/routers/old_only_in_v9.py", "運維備註.txt"]


# ── O-1：full 回滾比「備份時原檔」的邏輯內容 ─────────────────────────────────

def test_o1_full_rollback_matches_the_original_logically(inst, new_src, tmp_path):
    orig = U.logical_digest(_db(inst))
    bd = str(tmp_path / "bk")
    m = _convert(inst, new_src, bd)
    assert m["pre"]["logical"]["backend/motrix_erp.db"] == orig
    info = {}
    assert U.rollback(inst, bd, "full", info) == []
    assert info["db_logical"] == {"backend/motrix_erp.db": "與備份時原檔的邏輯內容相同"}


def test_o1_logical_check_is_independent_of_the_backup_copy(inst, new_src, tmp_path):
    """反向控制：備份副本與 manifest 一起被換成別的內容 ⇒ 位元組比對會過（比的是副本自己），
    邏輯比對要紅（比的是備份時原檔的雜湊）。"""
    bd = str(tmp_path / "bk")
    m = _convert(inst, new_src, bd)
    assert U.rollback(inst, bd, "full") == []
    other = str(tmp_path / "other.db")
    _make_db(other, settings={"company_profile": {"companyName": "別的"}})
    copy = os.path.join(bd, "db", "backend", "motrix_erp.db")
    shutil.copy2(other, copy)
    m["db"]["backend/motrix_erp.db"] = U.sha256_file(copy)
    shutil.copy2(copy, _db(inst))
    probs = U.verify_rollback(inst, m, "full")
    assert probs == ["資料庫的邏輯內容與備份時的原檔不同：backend/motrix_erp.db"], probs


def test_o1_logical_digest_ignores_header_counters(tmp_path):
    src = str(tmp_path / "a.db")
    _make_db(src)
    dst = str(tmp_path / "b.db")
    U.online_backup(src, dst)
    c = sqlite3.connect(src)
    c.execute("INSERT INTO customers (name) VALUES ('x')")
    c.execute("DELETE FROM customers WHERE name='x'")         # 內容回原樣、file change counter 變了
    c.commit()
    c.close()
    assert U.logical_digest(src) == U.logical_digest(dst)
    c = sqlite3.connect(src)
    c.execute("UPDATE customers SET name='z' WHERE id=1")
    c.commit()
    c.close()
    assert U.logical_digest(src) != U.logical_digest(dst)


# ── S-CU12：`.build_commit` 是程式——轉換隨新版安裝，回滾還原成 V9 的 ─────────────────

_V9_SHA = "c83dae6e" + "9" * 32
_NEW_SHA = "0ddba11c" + "1" * 32


@pytest.fixture()
def auth(client, make_user):
    u, p = make_user("cu12_user", "Cu12-Pass-123", role="admin")[:2]
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _disk_commit(client, auth, monkeypatch, inst):
    """真的打版本端點（`/api/build-info` 的 `disk_commit`＝磁碟上是哪個 commit）。
    正式機沒有 `.git` ⇒ git 那一路換成不可得，端點只能讀安裝目錄的 `.build_commit`。
    沒有這個檔 ⇒ 回 None。"""
    from helpers import build_info as B
    monkeypatch.setattr(B, "_BUILD_FILE", os.path.join(inst, "backend", ".build_commit"))
    monkeypatch.setattr(B, "_from_git", lambda: (None, "正式機沒有 .git"))
    r = client.get("/api/build-info", headers=auth)
    assert r.status_code == 200, r.text
    j = r.json()
    if not j["disk_commit"]:
        return None
    assert j["disk_commit_source"] == ".build_commit", j
    return j["disk_commit"]


@pytest.mark.parametrize("mode", ["code", "full"])
def test_cu12_build_commit_follows_the_program(inst, new_src, tmp_path, monkeypatch, client, auth, mode):
    """轉換後版本端點回新版的 commit；回滾（兩種模式）後回 V9 的 commit。
    修正前：歸類成設定 ⇒ 轉換不帶新包的 `.build_commit`，轉換後仍回 V9。"""
    _write(inst, "backend/.build_commit", _V9_SHA.encode())
    _write(new_src, "backend/.build_commit", _NEW_SHA.encode())
    T = _tool(monkeypatch)
    bd = str(tmp_path / "bk")
    _backup_verified(T, inst, bd)
    m = U.load_manifest(bd)
    assert _disk_commit(client, auth, monkeypatch, inst) == _V9_SHA          # 前提
    T.convert(inst, bd, new_src)
    assert U.verify_conversion(inst, m) == []
    assert _disk_commit(client, auth, monkeypatch, inst) == _NEW_SHA         # 端點本身先說話
    assert U.rollback(inst, bd, mode) == []
    assert _disk_commit(client, auth, monkeypatch, inst) == _V9_SHA
    assert "backend/.build_commit" in m["program"] and "backend/.build_commit" not in m["config"]


def test_cu12_v9_without_build_commit_rolls_back_to_none(inst, new_src, tmp_path, monkeypatch, client, auth):
    """V9 安裝沒有 `.build_commit`（舊包）⇒ code 回滾後不可以留著新版那一份（否則版本端點說是新版）。"""
    _write(new_src, "backend/.build_commit", _NEW_SHA.encode())
    bd = str(tmp_path / "bk")
    _convert(inst, new_src, bd)
    assert _disk_commit(client, auth, monkeypatch, inst) == _NEW_SHA
    assert U.rollback(inst, bd, "code") == []
    assert _disk_commit(client, auth, monkeypatch, inst) is None


# ── 啟動時的執行期狀態（D7 預演抓到，2026-09-26）──────────────────────────────

def test_startup_throttle_dates_moving_forward_are_not_rewrites():
    """真實庫裡的每日掃描節流日期是舊的 ⇒ 新版一啟動就寫今天 ⇒ 不算改寫；日期往回或值不是日期 ⇒ 仍算改寫。"""
    before = {"security.last_weak_pw_scan": '"2026-09-20"', "security.last_unlock_pw_scan": '"2026-09-20"',
              "company_profile": '{"name": "甲"}'}
    fwd = dict(before, **{"security.last_weak_pw_scan": '"2026-09-26"', "security.last_unlock_pw_scan": '"2026-09-26"'})
    assert U.settings_changes(before, fwd) == []
    back = dict(before, **{"security.last_weak_pw_scan": '"2026-09-01"'})
    assert U.settings_changes(before, back) == ["security.last_weak_pw_scan"]
    junk = dict(before, **{"security.last_unlock_pw_scan": '"not a date"'})
    assert U.settings_changes(before, junk) == ["security.last_unlock_pw_scan"]
    gone = {k: v for k, v in before.items() if k != "security.last_weak_pw_scan"}
    assert U.settings_changes(before, gone) == ["security.last_weak_pw_scan"]           # 刪掉仍算
    other = dict(fwd, company_profile='{"name": "乙"}')
    assert U.settings_changes(before, other) == ["company_profile"]                      # 其他鍵照舊逐一比


def test_every_setting_written_at_startup_is_classified():
    """守門：helpers/startup.py 啟動時寫入的每一個設定鍵，都必須在 RUNTIME_STATE_SETTINGS（有人決定過它算執行期狀態）；
    否則新版一啟動就改到它，升級驗證會判失敗而回滾。"""
    import re
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "helpers" / "startup.py").read_text(encoding="utf-8")
    written = set(re.findall(r'_set_setting\(\s*"([^"]+)"', src))
    assert written, "掃不到任何寫入（正對照：至少有每日掃描的節流日期）"
    assert written <= U.RUNTIME_STATE_SETTINGS, "啟動時寫入、卻沒有分類的設定鍵：%s" % sorted(written - U.RUNTIME_STATE_SETTINGS)
