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
