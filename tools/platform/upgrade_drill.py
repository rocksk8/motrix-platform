# -*- coding: utf-8 -*-
"""升級轉換與回滾的自動化演練（CORE-SPEC §9b；只在開發機、只用測試資料）。

  python tools/platform/upgrade_drill.py --mode code|full|both [--source-db <V9 開發機測試庫>] [--keep]

流程：建一個 V9 形狀的安裝目錄（程式取 `c83dae6e`＝V9 基準）→ 預檢 → 備份＋試還原 →
轉換（新版程式取本 repo HEAD）→ 驗證（新版啟動 ping）→ 寫入一筆「轉換後的新資料」→
回滾 → 雜湊逐一相等 → V9 啟動 ping。

🔴 安全
- 演練目錄在 %TEMP% 底下，而且路徑**不可以含 `V9.0`**：V9 的寄信判定是「安裝路徑含 \\V9.0\\
  就當正式機」，含了就會真的寄信（DATA-COMPAT §0-3）。
- 啟動一律帶 SAFE_ENV（不跑排程、不上雲、不寄信）；演練根目錄另放 `.no_cloud_archive`（V9 認得）。
- `--source-db` 只接受讀取：用 SQLite Online Backup API 複製進演練目錄，來源檔不被寫入。
- 結束後刪掉演練目錄（`--keep` 保留以便檢查）。
"""
import argparse
import io
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import uuid
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import upgrade as T  # noqa: E402  tools/platform/upgrade.py
U = T.U

V9_REV = "c83dae6e"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def git_export(rev: str, dest: str) -> None:
    raw = subprocess.run(["git", "-C", str(T.REPO), "archive", "--format=tar", rev],
                         capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
        tf.extractall(dest)


def _v9_init_db(install: str) -> None:
    env = {**os.environ, **T.SAFE_ENV}
    r = subprocess.run([sys.executable, "-c", "import db; db.init_db(); db.init_db(db.DEMO_DB_PATH); print('OK')"],
                       cwd=os.path.join(install, "backend"), env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if "OK" not in r.stdout:
        raise RuntimeError("V9 init_db 失敗：%s" % r.stderr[-800:])


def build_v9_install(drill_root: str, source_db: str = None, company_incomplete: bool = True) -> str:
    install = os.path.join(drill_root, "install")
    os.makedirs(install)
    git_export(V9_REV, install)
    backend = os.path.join(install, "backend")
    if source_db:
        U.online_backup(source_db, os.path.join(backend, "motrix_erp.db"))
    _v9_init_db(install)                                   # 補 demo 庫；主庫已存在時只是 no-op 升級檢查
    # 資料與設定樣本（清單比對與回滾比對的對象）
    samples = {
        "uploads/projects/1/photo.jpg": b"\xff\xd8drill-photo",
        "報價單PDF/Q-DRILL-1.pdf": b"%PDF-1.4 drill quotation",
        "backend/export_archive/PS-202609-001_1.pdf": b"%PDF-1.4 drill payslip",
        "backend/heartbeat_config.json": b'{"ping_url": ""}',
        "backend/license.key": b"drill-license-not-real",
        ".no_cloud_archive": b"drill",                     # V9 認得：演練機不上雲
    }
    for rel, data in samples.items():
        p = os.path.join(install, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)
    snap = os.path.join(backend, "db_backups", date.today().isoformat())
    os.makedirs(snap)
    U.online_backup(os.path.join(backend, "motrix_erp.db"), os.path.join(snap, "motrix_erp.db"))
    with open(os.path.join(snap, ".done"), "w", encoding="utf-8") as f:
        f.write("drill")
    if company_incomplete:
        _make_company_profile_incomplete(install)
    return install


#: 稽核 X-9b S-6：全新 V9 庫的統編空白 ⇒ 轉換不補欄位 ⇒ M-1（啟動後比對沒有補空值例外）在綠燈下漏掉。
#: 改成「本公司、欄位不齊」：統編有值、聯絡方式只有電話 ⇒ 轉換會補英文名與 email。
DRILL_COMPANY_PROFILE = {"name": "允碩整合集創股份有限公司", "tax_id": "60575481",
                         "contact_info": "Tel: 04-3610-6566"}


def _make_company_profile_incomplete(install: str) -> None:
    conn = sqlite3.connect(os.path.join(install, U.DB_FILES[0]))
    try:
        conn.execute("UPDATE system_settings SET value_json=? WHERE key='company_profile'",
                     (json.dumps(DRILL_COMPANY_PROFILE, ensure_ascii=False),))
        if conn.total_changes != 1:
            raise RuntimeError("演練庫沒有 company_profile 這一列（V9 種子改了？）")
        conn.commit()
    finally:
        conn.close()


def _insert_new_data(install: str) -> None:
    """模擬「轉換後、回滾前」新版寫入的資料。"""
    conn = sqlite3.connect(os.path.join(install, U.DB_FILES[0]))
    try:
        conn.execute("INSERT INTO customers (name, created_at, updated_at) VALUES (?,?,?)",
                     ("演練轉換後新增客戶", "2026-09-25", "2026-09-25"))
        conn.commit()
    finally:
        conn.close()


def _write_new_files(install: str) -> list:
    """稽核 X-9b S-6／M-2：新版上線後一定會寫檔——使用者上傳、每日快照。回寫入的相對路徑。"""
    rels = ["uploads/projects/1/after_upgrade.jpg",
            "backend/db_backups/2099-01-01/.done"]           # 不與今天的快照撞名；只要是「轉換後才出現」
    for rel in rels:
        p = os.path.join(install, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(b"written-after-conversion")
    return rels


def _count(install: str, table: str) -> int:
    conn = sqlite3.connect(os.path.join(install, U.DB_FILES[0]))
    try:
        return conn.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
    finally:
        conn.close()


def drill(mode: str, source_db: str = None, keep: bool = False,
          company_incomplete: bool = True, write_files: bool = True) -> dict:
    drill_root = tempfile.mkdtemp(prefix="motrix-upgrade-drill-")
    assert "V9.0" not in drill_root, "演練路徑含 V9.0（V9 會把它當正式機寄信）：%s" % drill_root
    rep = {"mode": mode, "drill_root": drill_root, "steps": {}}
    try:
        install = build_v9_install(drill_root, source_db, company_incomplete)
        new_src = os.path.join(drill_root, "new")
        os.makedirs(new_src)
        git_export("HEAD", new_src)
        backup_dir = os.path.join(drill_root, "backup")
        s = rep["steps"]

        # 預檢：演練目錄故意放了 .no_cloud_archive，所以不要求「沒有開發機標記」
        pf = U.preflight(install, v9_port_open=False, require_no_dev_markers=False)
        s["preflight"] = pf
        if not pf["ok"]:
            return rep
        m = U.backup(install, backup_dir)
        s["backup"] = {"files": len(m["files"]), "program": len(m["program"]), "config": len(m["config"]),
                       "db": list(m["db"]), "data": len(m["data_inventory"])}
        s["backup_verify"] = U.verify_backup_restorable(backup_dir)
        T._write_log(backup_dir, "backup_verify.json", {"problems": s["backup_verify"]})
        if s["backup_verify"]:
            return rep
        s["convert"] = T.convert(install, backup_dir, new_src)
        s["verify"] = T.verify(install, backup_dir, free_port())
        if s["verify"]:
            return rep
        before_new = _count(install, "customers")
        _insert_new_data(install)
        s["files_written_after_conversion"] = _write_new_files(install) if write_files else []
        s["rows_added_before_rollback"] = U.rows_added_since(m, os.path.join(install, U.DB_FILES[0]))
        s["changes_since_conversion"] = U.changes_since_conversion(backup_dir, os.path.join(install, U.DB_FILES[0]))
        # 走 CLI 同一條路：回滾 → 比對 → 自動啟動 V9 ping（只記結果）
        s["rollback_exit"], rlog = T.rollback_and_ping(install, backup_dir, mode, free_port())
        s["rollback"], s["rollback_info"] = rlog["problems"], rlog["info"]
        s["new_row_kept"] = _count(install, "customers") == before_new + 1
        s["v9_start"] = rlog["v9_ping"] if isinstance(rlog["v9_ping"], dict) else {"ok": False}
        s["v9_after_start_row_kept"] = _count(install, "customers") >= before_new + (1 if mode == "code" else 0)
        s["new_files_kept"] = all(os.path.isfile(os.path.join(install, r))
                                  for r in s["files_written_after_conversion"])
        rep["ok"] = (not s["rollback"] and s["v9_start"]["ok"] and s["v9_after_start_row_kept"]
                     and s["new_files_kept"]
                     and (s["new_row_kept"] if mode == "code" else not s["new_row_kept"]))
        return rep
    finally:
        rep.setdefault("ok", False)
        if not keep:
            shutil.rmtree(drill_root, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("code", "full", "both"), default="both")
    ap.add_argument("--source-db")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args(argv)
    modes = ("code", "full") if a.mode == "both" else (a.mode,)
    results = [drill(m, a.source_db, a.keep) for m in modes]
    print(json.dumps(results, ensure_ascii=False, indent=1, default=str))
    return 0 if all(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
