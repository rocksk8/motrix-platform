# -*- coding: utf-8 -*-
"""V9 → 新版 升級轉換與回滾的核心（CORE-SPEC §9b）。L0 工具，不是業務模組。

五個階段：預檢 → 備份（＋試還原比對雜湊）→ 轉換 → 驗證 → 回滾（完整／只回程式）。
這支檔只放「對一個明確給定的安裝根目錄做事」的函式；啟動伺服器、ping、互動確認在
`tools/platform/upgrade.py`。

🔴 原則
- **不猜路徑**：安裝根目錄一律由呼叫者明確給；這裡不讀 `core.paths` 的錨點當目標
  （`core.paths` 描述的是「這份程式碼」的安裝，不是要被升級的那一份）。
  版面（哪個相對路徑是 DB、資料、設定）則從 `core.paths` 推導，維持單一來源。
- **資料原地不動**：資料目錄只做清單（大小＋SHA256）以驗證沒被動過；不搬、不複製。
- **轉換只准新增**：設定只補缺的鍵（`NEW_SETTINGS`），既有值一個位元組都不改。
- **任一步驟不過 ⇒ 不往下走**；回滾以備份時的雜湊逐一比對為準。
"""
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from datetime import date, datetime, timedelta

from core import paths as _p

MANIFEST_NAME = "upgrade_manifest.json"
#: 新版認得的 V9 基準（與 db.V9_BASELINE 相同；這裡不 import db，避免拉進整個 app）
V9_BASELINE = 116

#: 新版新增、V9 沒有的設定鍵與預設值（轉換時只補缺的鍵）。
#: ⚠️ 新增設定鍵時要加在這裡——`tests/platform/test_core_upgrade.py` 會列出並比對。
#: `pii_archive_state` 是執行期狀態（排程第一次觀察時寫），不預寫。
NEW_SETTINGS = {
    "payslip_archive_path": "",      # 空字串＝用預設 backend/export_archive（routers/payslips._archive_dir）
}


def _rel(abs_path: str) -> str:
    return os.path.relpath(abs_path, _p.INSTALL_ROOT).replace("\\", "/")


#: 主庫／demo 庫（相對安裝根目錄）
DB_FILES = (_rel(_p.DB_PATH), _rel(_p.DEMO_DB_PATH))
_DB_SIDECARS = ("-wal", "-shm", "-journal")

#: 資料目錄（相對安裝根目錄）：原地不動，只做清單
DATA_DIRS = tuple(sorted({
    _rel(_p.UPLOADS_ROOT),
    *[_rel(d) for _k, (_key, d) in _p.PDF_ARCHIVES.items()],
    _rel(_p.LOCAL_DB_BACKUP_DIR),
    _rel(_p.BACKUP_ALERT_DIR),
    _rel(_p.LOGS_DIR),
    "backend/rollback_snapshots",
    "exports",
}))
#: demo 隔離目錄（backend/_demo_*）視為資料
_DATA_PREFIXES = ("backend/_demo_",)

#: 設定與身分檔（相對安裝根目錄）：備份、完整回滾時還原
CONFIG_FILES = tuple(sorted({
    _rel(_p.HEARTBEAT_CONFIG),
    _rel(_p.LICENSE_PATH),
    _rel(_p.INITIAL_ADMIN_CREDENTIALS),
    _rel(_p.INITIAL_DEMO_CREDENTIALS),
    _rel(_p.DEPLOYED_COMMIT_FILE),
    _rel(_p.BUILD_COMMIT_FILE),
    _rel(_p.NO_CLOUD_MARKER),
    _rel(_p.NO_EMAIL_SEND_MARKER),
}))
CONFIG_DIRS = (_rel(_p.CERTS_DIR),)
_SKIP_DIR_NAMES = ("__pycache__", ".git", ".pytest_cache")


def classify(rel: str) -> str:
    """相對安裝根目錄的路徑 → `db`／`data`／`config`／`skip`／`program`。"""
    rel = rel.replace("\\", "/")
    parts = rel.split("/")
    if any(p in _SKIP_DIR_NAMES for p in parts):
        return "skip"
    for db in DB_FILES:
        if rel == db or any(rel == db + s for s in _DB_SIDECARS):
            return "db"
    if any(rel == d or rel.startswith(d + "/") for d in DATA_DIRS) or rel.startswith(_DATA_PREFIXES):
        return "data"
    base = parts[-1]
    if rel in CONFIG_FILES or any(rel.startswith(d + "/") for d in CONFIG_DIRS) \
            or base == ".env" or base.startswith(".env."):
        return "config"
    if base.endswith((".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3")):
        return "data"            # 其他資料庫檔（例：遺留的 backend/motrix.db）一律不當程式動
    return "program"


def walk(root: str):
    """(相對路徑, 絕對路徑)；略過 `_SKIP_DIR_NAMES`。"""
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in _SKIP_DIR_NAMES]
        for fn in fns:
            full = os.path.join(dp, fn)
            yield os.path.relpath(full, root).replace("\\", "/"), full


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


#: 清單比對不收的資料（F4 可重建：伺服器啟動就可能寫 log）
_INVENTORY_EXCLUDE = (_rel(_p.LOGS_DIR) + "/",)


def inventory(root: str, kinds=("data",)) -> dict:
    """{相對路徑: [大小, sha256]}，只收 `kinds` 類別；log（F4）不收。"""
    out = {}
    for rel, full in walk(root):
        if rel.startswith(_INVENTORY_EXCLUDE):
            continue
        if classify(rel) in kinds:
            out[rel] = [os.path.getsize(full), sha256_file(full)]
    return out


# ── SQLite ────────────────────────────────────────────────────────────────

def _ro(path: str):
    conn = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def schema_version(db_path: str):
    conn = _ro(db_path)
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'").fetchone():
            return 0
        row = conn.execute("SELECT version FROM schema_version WHERE id=1").fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def table_counts(db_path: str) -> dict:
    conn = _ro(db_path)
    try:
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {n: conn.execute('SELECT COUNT(*) FROM "%s"' % n.replace('"', '""')).fetchone()[0] for n in names}
    finally:
        conn.close()


def settings_rows(db_path: str) -> dict:
    conn = _ro(db_path)
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='system_settings'").fetchone():
            return {}
        return {r["key"]: r["value_json"] for r in conn.execute("SELECT key, value_json FROM system_settings")}
    finally:
        conn.close()


def integrity_ok(db_path: str) -> bool:
    conn = _ro(db_path)
    try:
        return conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def online_backup(src: str, dst: str) -> None:
    """SQLite Online Backup API（WAL 安全；不直接複製 .db）。"""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    s = sqlite3.connect(src)
    d = sqlite3.connect(dst)
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()


# ── 階段 0：預檢 ──────────────────────────────────────────────────────────

def preflight(root: str, *, v9_port_open: bool, today: date = None, require_no_dev_markers: bool = True) -> dict:
    """回 `{"ok": bool, "problems": [...], "facts": {...}}`；任一 problem ⇒ 不動任何東西。

    健康檢查（記憶〈出修補包前先查正式機健康〉）：最近一次本機快照 `.done` 必須是今天或昨天；
    `backup_alerts/BACKUP_ALERT.txt` 不可以存在（有告警先處理）。
    """
    today = today or date.today()
    problems, facts = [], {}
    root = os.path.abspath(root or "")
    if not root or not os.path.isdir(root):
        return {"ok": False, "problems": ["安裝根目錄不存在：%s" % root], "facts": facts}
    db = os.path.join(root, DB_FILES[0])
    if not os.path.isfile(os.path.join(root, "backend", "db.py")):
        problems.append("不像 MOTRIX 安裝目錄（找不到 backend/db.py）")
    if not os.path.isfile(db):
        problems.append("找不到主庫 %s" % DB_FILES[0])
    else:
        try:
            v = schema_version(db)
            facts["schema_version"] = v
            if v > V9_BASELINE:
                problems.append("schema_version=v%d 大於新版認得的 V9 基準 v%d（V9 有未追進的 migration）"
                                % (v, V9_BASELINE))
        except Exception as e:                               # noqa: BLE001
            problems.append("讀不到 schema_version：%s" % e)
        size = os.path.getsize(db)
        free = shutil.disk_usage(root).free
        facts.update(db_bytes=size, free_bytes=free)
        if free < size * 3:
            problems.append("磁碟空間不足：剩 %d bytes，需要至少 DB×3＝%d" % (free, size * 3))
    # 健康
    backups = os.path.join(root, _rel(_p.LOCAL_DB_BACKUP_DIR))
    latest = None
    if os.path.isdir(backups):
        for name in os.listdir(backups):
            try:
                d = date.fromisoformat(name)
            except ValueError:
                continue
            if os.path.isfile(os.path.join(backups, name, ".done")) and (latest is None or d > latest):
                latest = d
    facts["latest_snapshot_done"] = latest.isoformat() if latest else None
    if latest is None or latest < today - timedelta(days=1):
        problems.append("最近一次本機快照 .done 不是今天或昨天（%s）——先確認備份正常" % facts["latest_snapshot_done"])
    alert = os.path.join(root, _rel(_p.BACKUP_ALERT_DIR), "BACKUP_ALERT.txt")
    if os.path.isfile(alert):
        problems.append("有未處理的備份告警：%s" % _rel(_p.BACKUP_ALERT_DIR) + "/BACKUP_ALERT.txt")
    if v9_port_open:
        problems.append("V9 服務仍在執行（port 有人在聽）——先停服務")
    if require_no_dev_markers:
        for m in (_rel(_p.NO_EMAIL_SEND_MARKER), _rel(_p.NO_CLOUD_MARKER)):
            if os.path.exists(os.path.join(root, m)):
                problems.append("安裝目錄有開發機標記 %s——轉換後會不寄信／不上雲" % m)
    return {"ok": not problems, "problems": problems, "facts": facts}


# ── 階段 1：備份 ──────────────────────────────────────────────────────────

def _inside(child: str, parent: str) -> bool:
    c, p = os.path.normcase(os.path.abspath(child)), os.path.normcase(os.path.abspath(parent))
    return c == p or c.startswith(p.rstrip("\/") + os.sep)


def backup(root: str, backup_dir: str) -> dict:
    """寫出備份與 `upgrade_manifest.json`，回 manifest。`backup_dir` 必須是新的空目錄，且不在安裝目錄內。"""
    root = os.path.abspath(root)
    if _inside(backup_dir, root):
        raise RuntimeError("備份目錄不可以在安裝目錄裡（會被當成程式備份進自己、回滾時被刪）：%s" % backup_dir)
    if os.path.exists(backup_dir) and os.listdir(backup_dir):
        raise RuntimeError("備份目錄不是空的：%s" % backup_dir)
    os.makedirs(backup_dir, exist_ok=True)
    m = {"created_at": datetime.now().isoformat(timespec="seconds"), "root": root,
         "files": {}, "program": {}, "config": {}, "db": {}, "data_inventory": {},
         "pre": {}}
    # ① DB（Online Backup API）
    for rel in DB_FILES:
        src = os.path.join(root, rel)
        if os.path.isfile(src):
            dst = os.path.join(backup_dir, "db", rel)
            online_backup(src, dst)
            m["db"][rel] = sha256_file(dst)
    main_db = os.path.join(root, DB_FILES[0])
    m["pre"]["counts"] = table_counts(main_db)
    m["pre"]["settings"] = settings_rows(main_db)
    m["pre"]["schema_version"] = schema_version(main_db)
    # ② 程式快照 ③ 設定與身分檔
    for rel, full in walk(root):
        kind = classify(rel)
        if kind in ("program", "config"):
            dst = os.path.join(backup_dir, kind, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(full, dst)
            m[kind][rel] = sha256_file(dst)
    # ④ 資料目錄清單（原地不動）
    m["data_inventory"] = inventory(root, kinds=("data",))
    # ⑤ manifest：每個備份檔的 SHA256
    for rel, full in walk(backup_dir):
        if rel != MANIFEST_NAME:
            m["files"][rel] = sha256_file(full)
    with open(os.path.join(backup_dir, MANIFEST_NAME), "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1, sort_keys=True)
    return m


def load_manifest(backup_dir: str) -> dict:
    with open(os.path.join(backup_dir, MANIFEST_NAME), encoding="utf-8") as f:
        return json.load(f)


def verify_backup_restorable(backup_dir: str, manifest: dict = None) -> list:
    """試還原到暫存位置並比對雜湊；回 problems（空＝通過）。"""
    manifest = manifest or load_manifest(backup_dir)
    problems = []
    tmp = tempfile.mkdtemp(prefix="motrix-upgrade-restore-")
    try:
        on_disk = {rel for rel, _f in walk(backup_dir) if rel != MANIFEST_NAME}
        if on_disk != set(manifest["files"]):
            problems.append("備份檔集合與 manifest 不一致：多 %s／少 %s"
                            % (sorted(on_disk - set(manifest["files"]))[:5],
                               sorted(set(manifest["files"]) - on_disk)[:5]))
        for rel, want in manifest["files"].items():
            src = os.path.join(backup_dir, rel)
            if not os.path.isfile(src):
                continue
            dst = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            if sha256_file(dst) != want:
                problems.append("雜湊不符：%s" % rel)
        main = os.path.join(tmp, "db", DB_FILES[0])
        if os.path.isfile(main):
            if not integrity_ok(main):
                problems.append("還原後的主庫 integrity_check 不是 ok")
            elif table_counts(main) != manifest["pre"]["counts"]:
                problems.append("還原後的主庫各表列數與備份時不同")
        else:
            problems.append("備份裡沒有主庫")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return problems


# ── 階段 2：轉換 ──────────────────────────────────────────────────────────

def program_files(root: str) -> dict:
    return {rel: full for rel, full in walk(root) if classify(rel) == "program"}


def replace_program(root: str, new_source: str) -> dict:
    """刪掉現有程式檔、換上 `new_source` 的程式檔。資料／DB／設定一律不碰。回 {removed, added}。"""
    if _inside(new_source, root):
        raise RuntimeError("新版程式來源不可以在安裝目錄裡：%s" % new_source)
    removed = 0
    for rel, full in program_files(root).items():
        os.remove(full)
        removed += 1
    _prune_empty_dirs(root)
    added = 0
    for rel, full in walk(new_source):
        if classify(rel) != "program":
            continue                      # 新版來源裡的資料／設定（若有）不帶進來
        dst = os.path.join(root, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(full, dst)
        added += 1
    return {"removed": removed, "added": added}


def _prune_empty_dirs(root: str) -> None:
    for dp, dns, fns in os.walk(root, topdown=False):
        if dp == root:
            continue
        rel = os.path.relpath(dp, root).replace("\\", "/")
        if classify(rel + "/x") != "program":
            continue
        try:
            if not os.listdir(dp):
                os.rmdir(dp)
        except OSError:
            pass


def add_missing_settings(db_path: str, new_settings: dict = None) -> dict:
    """只補缺的鍵；既有鍵一律不動。回 {新增的鍵: 值}。"""
    new_settings = NEW_SETTINGS if new_settings is None else new_settings
    conn = sqlite3.connect(db_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(system_settings)")}
        existing = {r[0] for r in conn.execute("SELECT key FROM system_settings")}
        added = {}
        now = datetime.now().isoformat()
        for k, v in new_settings.items():
            if k in existing:
                continue
            if "updated_at" in cols:
                conn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?)",
                             (k, json.dumps(v, ensure_ascii=False), now))
            else:
                conn.execute("INSERT INTO system_settings (key, value_json) VALUES (?,?)",
                             (k, json.dumps(v, ensure_ascii=False)))
            added[k] = v
        conn.commit()
        return added
    finally:
        conn.close()


# ── 階段 3：驗證（不含啟動伺服器）─────────────────────────────────────────

def verify_conversion(root: str, manifest: dict) -> list:
    """列數、既有設定、資料目錄清單都要與轉換前相同；新版只准新增。"""
    problems = []
    main = os.path.join(root, DB_FILES[0])
    after = table_counts(main)
    for t, n in manifest["pre"]["counts"].items():
        if t not in after:
            problems.append("表消失：%s" % t)
        elif t == "system_settings":
            continue                                  # 下面逐鍵比
        elif after[t] != n:
            problems.append("列數改變：%s %d → %d" % (t, n, after[t]))
    s_after = settings_rows(main)
    for k, v in manifest["pre"]["settings"].items():
        if s_after.get(k) != v:
            problems.append("既有設定被改寫或刪除：%s" % k)
    extra = set(s_after) - set(manifest["pre"]["settings"])
    unexpected = extra - set(NEW_SETTINGS)
    if unexpected:
        problems.append("出現未宣告的新設定鍵：%s" % sorted(unexpected))
    if inventory(root, kinds=("data",)) != manifest["data_inventory"]:
        problems.append("資料目錄內容與轉換前不同")
    return problems


# ── 階段 4：回滾 ──────────────────────────────────────────────────────────

def rows_added_since(manifest: dict, db_path: str) -> dict:
    """轉換後新增的列數（完整回滾前要列給人確認）。"""
    after = table_counts(db_path)
    return {t: after.get(t, 0) - n for t, n in manifest["pre"]["counts"].items() if after.get(t, 0) > n}


def _restore_tree(root: str, backup_dir: str, manifest: dict, kind: str) -> None:
    for rel in manifest[kind]:
        dst = os.path.join(root, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(backup_dir, kind, rel), dst)


def rollback(root: str, backup_dir: str, mode: str) -> list:
    """`mode`＝"full"（程式＋DB＋設定）或 "code"（只回程式，保留轉換後的資料）。回驗證 problems。"""
    if mode not in ("full", "code"):
        raise ValueError(mode)
    manifest = load_manifest(backup_dir)
    for _rel_, full in program_files(root).items():
        os.remove(full)
    _prune_empty_dirs(root)
    _restore_tree(root, backup_dir, manifest, "program")
    if mode == "full":
        for rel, full in walk(root):
            if classify(rel) == "config" and rel not in manifest["config"]:
                os.remove(full)                        # 轉換後才出現的設定檔
        _restore_tree(root, backup_dir, manifest, "config")
        for rel in manifest["db"]:
            dst = os.path.join(root, rel)
            for s in _DB_SIDECARS:
                if os.path.exists(dst + s):
                    os.remove(dst + s)
            shutil.copy2(os.path.join(backup_dir, "db", rel), dst)
    return verify_rollback(root, manifest, mode)


def verify_rollback(root: str, manifest: dict, mode: str) -> list:
    problems = []
    now_prog = {rel: sha256_file(f) for rel, f in program_files(root).items()}
    if now_prog != manifest["program"]:
        diff = set(now_prog.items()) ^ set(manifest["program"].items())
        problems.append("程式檔與備份不一致：%s" % sorted({d[0] for d in diff})[:10])
    if mode == "full":
        now_cfg = {rel: sha256_file(f) for rel, f in walk(root) if classify(rel) == "config"}
        if now_cfg != manifest["config"]:
            problems.append("設定檔與備份不一致")
        for rel, want in manifest["db"].items():
            if sha256_file(os.path.join(root, rel)) != want:
                problems.append("資料庫與備份不一致：%s" % rel)
    if inventory(root, kinds=("data",)) != manifest["data_inventory"]:
        problems.append("資料目錄與轉換前不同")
    return problems
