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
import re
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
    _rel(_p.NO_CLOUD_MARKER),
    _rel(_p.NO_EMAIL_SEND_MARKER),
    _rel(_p.AUTOSTART_BAT),
}))
# ⚠ `.build_commit`（`_p.BUILD_COMMIT_FILE`）**不是**設定：它是打包時寫下「這份程式碼是哪個 commit」，
#   跟著程式走 ⇒ 歸類成程式（classify 的預設）：轉換時隨新版包安裝、兩種回滾都還原成 V9 的那一份。
#   歸成設定的話轉換後版本端點仍回 V9 的 commit（STATES-DATA-OPS S-CU12）。
#   `.deployed_commit.json` 是部署工具寫的「這台機器套用過什麼」，仍屬設定。
CONFIG_DIRS = (_rel(_p.CERTS_DIR),)
#: 設定類、但部署包也帶一份預設的檔（稽核 X-9b M-4）。`autostart.bat` 裡有這台機器的對外連線總開關
#: （MOTRIX_TENDER_RADAR／MOTRIX_GEO），被新版包覆蓋 ＝ 在沒有人知道的情況下改變機器設定。
#: 轉換規則：安裝目錄有 ⇒ 保留機器上的版本；沒有 ⇒ 從新版包補上（只新增）；兩邊不同 ⇒ 記進轉換紀錄提示人比對。
PACKAGE_DEFAULT_CONFIG = (_rel(_p.AUTOSTART_BAT),)
#: 升級工具自己寫進備份目錄的紀錄檔：試還原比對時不算「多出來的備份檔」（稽核 X-9b S-2）
TOOL_LOG_NAMES = ("backup_verify.json", "conversion_log.json", "verify_log.json", "post_convert.json")
#: 會輪替的資料（每日快照依保留期限清除、新版每天新增）：回滾比對時缺少或改變只列資訊，不算問題（稽核 X-9b M-2）
_ROTATING_DATA_PREFIXES = (_rel(_p.LOCAL_DB_BACKUP_DIR) + "/",)
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


def quick_check(db_path: str) -> str:
    """`PRAGMA quick_check`；"ok"＝通過，其餘（含丟例外）回錯誤字串。與 db.quick_check 同義（本檔不 import db）。"""
    try:
        conn = _ro(db_path)
        try:
            msgs = [r[0] for r in conn.execute("PRAGMA quick_check").fetchall()]
        finally:
            conn.close()
    except Exception as exc:                                  # noqa: BLE001
        return "%s: %s" % (type(exc).__name__, exc)
    return "ok" if msgs == ["ok"] else "；".join(str(m) for m in msgs[:5])


def integrity_ok(db_path: str) -> bool:
    conn = _ro(db_path)
    try:
        return conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def table_digests(db_path: str, columns: dict = None) -> dict:
    """{表: {"columns": [...], "rows": n, "sha256": ...}}：各表**內容**的雜湊（只讀）。

    - 列序：rowid；WITHOUT ROWID 表改依全部欄位排序。
    - `columns`＝{表: [欄]} ⇒ 只算這些欄（轉換後 migration 新增的欄不影響比對）；
      原本的欄不見了 ⇒ `sha256` 為 None、`missing_columns` 列出來。
    稽核 X-9b S-3（「只准新增」原本只驗列數）與 O-1（full 回滾比「邏輯內容」而不是位元組）。
    """
    conn = sqlite3.connect("file:%s?mode=ro" % db_path.replace("\\", "/"), uri=True)
    try:
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        out = {}
        for n in names:
            q = '"%s"' % n.replace('"', '""')
            cols = [r[1] for r in conn.execute("PRAGMA table_info(%s)" % q)]
            want = list(columns[n]) if columns and n in columns else cols
            missing = sorted(set(want) - set(cols))
            if missing:
                out[n] = {"columns": want, "rows": None, "sha256": None, "missing_columns": missing}
                continue
            sel = ", ".join('"%s"' % c.replace('"', '""') for c in want) or "1"
            try:
                cur = conn.execute("SELECT %s FROM %s ORDER BY rowid" % (sel, q))
            except sqlite3.OperationalError:              # WITHOUT ROWID
                cur = conn.execute("SELECT %s FROM %s ORDER BY %s"
                                   % (sel, q, ", ".join(str(i + 1) for i in range(max(len(want), 1)))))
            h = hashlib.sha256()
            rows = 0
            for row in cur:
                h.update(repr(tuple(row)).encode("utf-8", "surrogatepass"))
                h.update(b"\n")
                rows += 1
            out[n] = {"columns": want, "rows": rows, "sha256": h.hexdigest()}
        return out
    finally:
        conn.close()


def logical_digest(db_path: str) -> str:
    """整庫的邏輯內容雜湊：schema（sqlite_master）＋各表全部欄位的內容。

    與檔案位元組無關：Online Backup API 產生的副本，SQLite 標頭的 file change counter
    （offset 24-27）與 version-valid-for（offset 92-95）會與原檔不同，但邏輯內容相同（稽核 X-9b O-1）。
    """
    conn = sqlite3.connect("file:%s?mode=ro" % db_path.replace("\\", "/"), uri=True)
    try:
        schema = sorted(tuple(r) for r in conn.execute(
            "SELECT type, name, tbl_name, COALESCE(sql,'') FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
    finally:
        conn.close()
    h = hashlib.sha256(repr(schema).encode("utf-8"))
    for n, d in sorted(table_digests(db_path).items()):
        h.update(("%s|%s|%s\n" % (n, d["rows"], d["sha256"])).encode("utf-8"))
    return h.hexdigest()


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


# ── 安裝目錄以外的 PDF 存檔目錄（system_settings 的 *_pdf_base_path）──────────
#
# 主持裁示（2026-09-25）：納入，但**只記清單不算雜湊**（網路碟整個算雜湊太慢，也可能讓升級卡在網路上）。
# 記路徑、檔案數、總大小、最新 mtime；驗證只比「檔案數與總大小沒有變少」。
# 連不到 ⇒ 標「無法確認」＝警告，不擋升級。
EXTERNAL_SCAN_TIMEOUT = 60.0


def external_pdf_dirs(root: str, settings: dict) -> dict:
    """{設定鍵: 絕對路徑}：設定了、而且不在安裝目錄內的 PDF 存檔目錄。"""
    out = {}
    for _k, (key, _default) in _p.PDF_ARCHIVES.items():
        raw = settings.get(key)
        try:
            val = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:                                    # noqa: BLE001
            val = raw
        if isinstance(val, str) and val.strip() and os.path.isabs(val.strip()) \
                and not _inside(val.strip(), root):
            out[key] = val.strip()
    return out


def external_summary(path: str, timeout: float = None) -> dict:
    """{path, status: ok／unreachable, files, bytes, latest_mtime}；逾時或讀不到 ⇒ unreachable。"""
    import threading
    timeout = EXTERNAL_SCAN_TIMEOUT if timeout is None else timeout
    res = {"path": path, "status": "unreachable", "files": None, "bytes": None, "latest_mtime": None}

    def scan():
        if not os.path.isdir(path):
            return
        n = b = 0
        latest = 0.0
        for dp, _dn, fns in os.walk(path):
            for fn in fns:
                st = os.stat(os.path.join(dp, fn))
                n += 1
                b += st.st_size
                latest = max(latest, st.st_mtime)
        res.update(status="ok", files=n, bytes=b,
                   latest_mtime=datetime.fromtimestamp(latest).isoformat(timespec="seconds") if n else None)

    t = threading.Thread(target=scan, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return {"path": path, "status": "unreachable", "files": None, "bytes": None, "latest_mtime": None,
                "reason": "逾時 %.0f 秒" % timeout}
    return res


def verify_external(manifest: dict, warnings: list = None) -> list:
    """外部 PDF 目錄：檔案數與總大小不可以變少（problems）；連不到 ⇒ 只記 warnings。"""
    problems = []
    warnings = [] if warnings is None else warnings
    for key, before in (manifest.get("external_dirs") or {}).items():
        if before["status"] != "ok":
            warnings.append("無法確認（備份時就連不到）：%s %s" % (key, before["path"]))
            continue
        now = external_summary(before["path"])
        if now["status"] != "ok":
            warnings.append("無法確認（現在連不到）：%s %s" % (key, before["path"]))
            continue
        if now["files"] < before["files"] or now["bytes"] < before["bytes"]:
            problems.append("外部 PDF 目錄變少：%s %s（檔案 %d → %d，大小 %d → %d）"
                            % (key, before["path"], before["files"], now["files"], before["bytes"], now["bytes"]))
    return problems


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
        # S-CU10（STATES-DATA-OPS）：損毀的主庫原本能通過預檢，到備份讀列數時才以 traceback 崩潰
        qc = quick_check(db)
        if qc != "ok":
            problems.append("主庫 quick_check 不通過（資料庫檔可能損毀）：%s —— 先從快照還原再升級" % qc[:200])
        size = os.path.getsize(db)
        free = shutil.disk_usage(root).free
        facts.update(db_bytes=size, free_bytes=free)
        if free < size * 3:
            problems.append("磁碟空間不足：剩 %d bytes，需要至少 DB×3＝%d" % (free, size * 3))
    if os.path.isfile(db):
        try:
            facts["external_pdf_dirs"] = external_pdf_dirs(root, settings_rows(db))
        except Exception:                                    # noqa: BLE001
            facts["external_pdf_dirs"] = "讀不到 system_settings"
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
    return c == p or c.startswith(p.rstrip("\\/") + os.sep)


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
    # 各表內容雜湊（S-3：轉換只准新增）；**原檔**的邏輯內容雜湊（O-1：full 回滾的獨立證據，
    # 不是拿剛從備份複製回來的那一份比對它自己）
    m["pre"]["digests"] = table_digests(main_db)
    m["pre"]["logical"] = {rel: logical_digest(os.path.join(root, rel))
                           for rel in DB_FILES if os.path.isfile(os.path.join(root, rel))}
    # ② 程式快照 ③ 設定與身分檔
    for rel, full in walk(root):
        kind = classify(rel)
        if kind in ("program", "config"):
            dst = os.path.join(backup_dir, kind, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(full, dst)
            m[kind][rel] = sha256_file(dst)
    # ④ 資料目錄清單（原地不動）；安裝目錄以外的 PDF 目錄只記摘要
    m["data_inventory"] = inventory(root, kinds=("data",))
    m["external_dirs"] = {k: external_summary(v)
                          for k, v in external_pdf_dirs(root, m["pre"]["settings"]).items()}
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


def _is_tool_log(rel: str) -> bool:
    """升級工具自己寫在備份目錄最上層的紀錄檔（不是備份內容）。"""
    return "/" not in rel and (rel in TOOL_LOG_NAMES or (rel.startswith("rollback_") and rel.endswith(".json")))


def manifest_sha256(backup_dir: str) -> str:
    """manifest 本身的雜湊。manifest 沒有外部錨點（稽核 X-9b O-2）：備份時把這個值抄到備份目錄以外，
    回滾前對照，才偵測得到「檔案與 manifest 一起被改」。"""
    return sha256_file(os.path.join(backup_dir, MANIFEST_NAME))


def verify_backup_restorable(backup_dir: str, manifest: dict = None) -> list:
    """試還原到暫存位置並比對雜湊；回 problems（空＝通過）。可以重跑（工具自己的紀錄檔不算備份檔）。"""
    manifest = manifest or load_manifest(backup_dir)
    problems = []
    tmp = tempfile.mkdtemp(prefix="motrix-upgrade-restore-")
    try:
        on_disk = {rel for rel, _f in walk(backup_dir) if rel != MANIFEST_NAME and not _is_tool_log(rel)}
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
        # 主庫與 demo 庫都做 integrity_check（O-7）；讀不了（例：標頭損毀）⇒ 列成 problem，不丟例外（S-2）
        for rel in DB_FILES:
            p = os.path.join(tmp, "db", rel)
            if not os.path.isfile(p):
                if rel == DB_FILES[0]:
                    problems.append("備份裡沒有主庫")
                continue
            try:
                if not integrity_ok(p):
                    problems.append("還原後的 %s integrity_check 不是 ok" % rel)
                elif rel == DB_FILES[0] and table_counts(p) != manifest["pre"]["counts"]:
                    problems.append("還原後的主庫各表列數與備份時不同")
            except Exception as exc:                          # noqa: BLE001
                problems.append("還原後的 %s 讀不了（%s: %s）" % (rel, type(exc).__name__, exc))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return problems


def check_backup(root: str, backup_dir: str) -> list:
    """轉換與回滾**動手之前**重驗備份（稽核 X-9b S-1）：manifest 讀得到、備份的是這個安裝根目錄、
    逐檔雜湊與試還原通過。回 problems（空＝可以動手）。不看 `backup_verify.json`（那是過去的結果）。"""
    try:
        manifest = load_manifest(backup_dir)
    except Exception as exc:                                  # noqa: BLE001
        return ["讀不到備份的 manifest：%s: %s" % (type(exc).__name__, exc)]
    problems = []
    want, got = os.path.normcase(os.path.abspath(manifest.get("root") or "")), os.path.normcase(os.path.abspath(root))
    if want != got:
        problems.append("這份備份不是這個安裝目錄的：備份時 %s，現在 %s" % (manifest.get("root"), os.path.abspath(root)))
        return problems                       # 別人的備份：不必再試還原
    try:
        problems += verify_backup_restorable(backup_dir, manifest)
    except Exception as exc:                                  # noqa: BLE001
        problems.append("試還原失敗：%s: %s" % (type(exc).__name__, exc))
    return problems


# ── 階段 2：轉換 ──────────────────────────────────────────────────────────

def program_files(root: str) -> dict:
    return {rel: full for rel, full in walk(root) if classify(rel) == "program"}


def replace_program(root: str, new_source: str) -> dict:
    """刪掉現有程式檔、換上 `new_source` 的程式檔。資料／DB／設定一律不碰。

    回 {removed, added, removed_without_replacement}。最後一項列出「被刪、而新版沒有同路徑檔」的檔
    （例：人放在安裝目錄的備註、臨時腳本；只留在備份裡）——讓人看得到（稽核 X-9b S-7）。
    """
    if _inside(new_source, root):
        raise RuntimeError("新版程式來源不可以在安裝目錄裡：%s" % new_source)
    incoming = {rel: full for rel, full in walk(new_source) if classify(rel) == "program"}
    removed = 0
    gone = []
    for rel, full in program_files(root).items():
        os.remove(full)
        removed += 1
        if rel not in incoming:
            gone.append(rel)
    _prune_empty_dirs(root)
    added = 0
    for rel, full in incoming.items():    # 新版來源裡的資料／設定（若有）不帶進來
        dst = os.path.join(root, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(full, dst)
        added += 1
    return {"removed": removed, "added": added, "removed_without_replacement": sorted(gone)}


def sync_package_default_config(root: str, new_source: str) -> dict:
    """`PACKAGE_DEFAULT_CONFIG`：機器上有 ⇒ 保留不動；沒有 ⇒ 從新版包補上；兩邊不同 ⇒ 列出來請人比對。

    回 {"added": [...], "kept_differs_from_package": [...]}（稽核 X-9b M-4）。
    """
    rep = {"added": [], "kept_differs_from_package": []}
    for rel in PACKAGE_DEFAULT_CONFIG:
        src, dst = os.path.join(new_source, rel), os.path.join(root, rel)
        if not os.path.isfile(src):
            continue
        if not os.path.isfile(dst):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            rep["added"].append(rel)
        elif sha256_file(src) != sha256_file(dst):
            rep["kept_differs_from_package"].append(rel)
    return rep


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




# ── 公司資料只補空值（主持 2026-09-25，A8c 的升級側）────────────────────────────
#
# A8c 把報表／網路規劃裡寫死的聯絡資料改從 company_identity 取；正式機的 company_profile
# 若缺這幾欄，換版後那些位置會悄悄變空白。⇒ 轉換時**只補空值**，已有值的欄位一律不動
# （§9b「轉換只准新增」）。值照抄 V9 原始碼（c83dae6e）裡被 A8c 刪掉的常數：
#   backend/routers/reports.py:66      _COMPANY2 = "統一編號 60575481 ｜ Tel: 04-3610-6566 ｜ info@miactw.com"
#   backend/network_plan_export.py:19  _COMPANY  = "允碩整合集創股份有限公司"
#   backend/network_plan_export.py:20  _COMPANY2 = "MOTRIX Synergy Integration Corp."
# 🔴 只在**看得出是本公司安裝**時才補（統編是 60575481，或公司名含「允碩」）：
#    新版會賣給客戶，不可以把我們的聯絡資料蓋進別人的安裝（比照 db._m106 只認統編）。
V9_COMPANY_DEFAULTS = {
    "company_name": "允碩整合集創股份有限公司",
    "company_name_en": "MOTRIX Synergy Integration Corp.",
    "tax_id": "60575481",
    "phone": "04-3610-6566",
    "email": "info@miactw.com",
}
#: company_identity 讀的別名（任一個有值就算「已有值」）。⚠ 必須與 helpers.company_identity._PROFILE_ALIASES
#: 相同（本檔不 import app；tests/test_company_contact_a8c 比對兩份）。注意 V9 種子形狀的 `name`
#: **不在**別名裡——company_identity 不讀它 ⇒ 公司名空白時先沿用 `name`（使用者自己的資料），沒有才用常數。
_PROFILE_ALIASES = {
    "company_name": ("companyName", "company_name", "name"),
    "company_name_en": ("companyNameEn", "company_name_en"),
    "tax_id": ("taxId", "tax_id"),
    "phone": ("phone",),
    "email": ("email",),
}


def _contact_info_parts(profile: dict) -> dict:
    """與 helpers.company_identity.contact_info_parts 相同（本檔不 import app；測試比對兩份）。"""
    contact = str((profile or {}).get("contact_info") or "")
    m = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", contact)
    email = m.group(0) if m else ""
    rest = (contact[:m.start()] + " " + contact[m.end():]) if m else contact
    # X 稽核 B-3：電話只接受「以數字為主」的片段；地址等自由文字不可以被印成 Tel（找不到就留空）
    p = re.search(r"[+(]?\d[\d\-\s()#轉]{5,}\d", rest)
    return {"phone": p.group(0).strip() if p else "", "email": email}


def _is_our_install(profile: dict) -> bool:
    tax = str(profile.get("taxId") or profile.get("tax_id") or "").strip()
    names = " ".join(str(profile.get(k) or "") for k in ("companyName", "company_name", "name"))
    return tax == V9_COMPANY_DEFAULTS["tax_id"] or "允碩" in names


def fill_company_profile_blanks(db_path: str) -> dict:
    """回 `{"filled": {欄: 值}, "skipped": 原因或 None}`。已有值的欄位不動；不是本公司安裝就不補。"""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT value_json FROM system_settings WHERE key='company_profile'").fetchone()
        try:
            profile = json.loads(row[0]) if row and row[0] else {}
        except (TypeError, ValueError):
            return {"filled": {}, "skipped": "company_profile 讀不懂，不動"}
        if not isinstance(profile, dict):
            return {"filled": {}, "skipped": "company_profile 不是物件，不動"}
        if not _is_our_install(profile):
            return {"filled": {}, "skipped": "看不出是本公司安裝（統編與公司名都對不上），不補"}
        filled = {}
        for field, value in V9_COMPANY_DEFAULTS.items():
            if any(str(profile.get(a) or "").strip() for a in _PROFILE_ALIASES[field]):
                continue
            if field in ("phone", "email") and _contact_info_parts(profile)[field]:
                continue                     # company_identity 會從「聯絡方式」讀到 ⇒ 已有值
            profile[field] = value
            filled[field] = value
        if filled:
            conn.execute("UPDATE system_settings SET value_json=? WHERE key='company_profile'",
                         (json.dumps(profile, ensure_ascii=False),))
            conn.commit()
        return {"filled": filled, "skipped": None}
    finally:
        conn.close()


def _blank(v) -> bool:
    """與 fill_company_profile_blanks 的「空值」判準相同：`str(v or "").strip()` 為空。"""
    return not str(v or "").strip()


def _fill_only_json_change(before: str, after: str, fill: dict) -> bool:
    """`after` 相對 `before` 只做了「補空值」：
    - 既有鍵：值相同；或原值是空值（None／空字串／只有空白，稽核 X-C-batch1 B-2）而新值等於 `fill` 裡那一欄的補值；
    - 新鍵：必須在 `fill` 裡，而且值等於補值；
    - 不可以刪鍵。
    判準與 `fill_company_profile_blanks` 相同，兩邊不再各寫一份。
    """
    try:
        b, a = json.loads(before), json.loads(after)
    except (TypeError, ValueError):
        return False
    if not isinstance(b, dict) or not isinstance(a, dict):
        return False
    if set(b) - set(a):
        return False
    for k, v in a.items():
        if k in b and b[k] == v:
            continue
        if k in fill and v == fill[k] and (k not in b or _blank(b[k])):
            continue
        return False
    return True


def settings_changes(before: dict, after: dict) -> list:
    """`before` 的既有設定鍵，在 `after` 被改寫或刪除的鍵（排序）。

    唯一的例外：`company_profile` 只做了「補空值」（fill_company_profile_blanks）。
    轉換後驗證（verify_conversion）與新版啟動後的比對（tools/platform/upgrade.py verify）**共用這一支**
    ——稽核 X-9b M-1：啟動後那一份自己逐鍵比、沒有這個例外，只要補過欄位驗證就一定不過。
    """
    changed = []
    for k, v in before.items():
        if after.get(k) == v:
            continue
        if k == "company_profile" and after.get(k) is not None \
                and _fill_only_json_change(v, after[k], V9_COMPANY_DEFAULTS):
            continue
        changed.append(k)
    return sorted(changed)


# ── 階段 3：驗證（不含啟動伺服器）─────────────────────────────────────────

def _rewritten_tables(db_path: str, pre_digests: dict, counts_after: dict) -> list:
    """列數沒變、內容卻變了的表（只比轉換前就有的欄；system_settings 另外逐鍵比）。"""
    if not pre_digests:
        return []                                     # 舊版工具做的備份沒有內容雜湊
    cols = {t: d["columns"] for t, d in pre_digests.items()}
    now = table_digests(db_path, cols)
    out = []
    for t, d in pre_digests.items():
        if t == "system_settings" or t not in now:
            continue
        if counts_after.get(t) != d["rows"]:
            continue                                  # 列數改變另有訊息
        if now[t]["sha256"] != d["sha256"]:
            out.append(t)
    return sorted(out)


def verify_conversion(root: str, manifest: dict, warnings: list = None) -> list:
    """列數、各表內容、既有設定、設定檔、資料目錄清單都要與轉換前相同；新版只准新增。
    外部 PDF 目錄見 verify_external。"""
    problems = verify_external(manifest, warnings)
    main = os.path.join(root, DB_FILES[0])
    after = table_counts(main)
    for t, n in manifest["pre"]["counts"].items():
        if t not in after:
            problems.append("表消失：%s" % t)
        elif t == "system_settings":
            continue                                  # 下面逐鍵比
        elif after[t] != n:
            problems.append("列數改變：%s %d → %d" % (t, n, after[t]))
    rewritten = _rewritten_tables(main, manifest["pre"].get("digests"), after)
    if rewritten:
        problems.append("既有資料被改寫（列數相同、內容不同）：%s" % rewritten)
    s_after = settings_rows(main)
    for k in settings_changes(manifest["pre"]["settings"], s_after):
        problems.append("既有設定被改寫或刪除：%s" % k)
    extra = set(s_after) - set(manifest["pre"]["settings"])
    unexpected = extra - set(NEW_SETTINGS)
    if unexpected:
        problems.append("出現未宣告的新設定鍵：%s" % sorted(unexpected))
    # 設定檔（含 autostart.bat）：轉換不可以改寫或刪除（稽核 X-9b M-4）
    cfg_changed = sorted(rel for rel, want in manifest["config"].items()
                         if not os.path.isfile(os.path.join(root, rel))
                         or sha256_file(os.path.join(root, rel)) != want)
    if cfg_changed:
        problems.append("設定檔被改寫或刪除：%s" % cfg_changed)
    if inventory(root, kinds=("data",)) != manifest["data_inventory"]:
        problems.append("資料目錄內容與轉換前不同")
    return problems


# ── 轉換後的基準（完整回滾前列出「轉換後才寫入」的資料用；稽核 X-9b S-3）──────

POST_CONVERT_NAME = "post_convert.json"


def record_post_conversion(root: str, backup_dir: str) -> dict:
    """轉換完成當下的各表列數與內容雜湊 → `<BK>/post_convert.json`。"""
    main = os.path.join(root, DB_FILES[0])
    snap = {"at": datetime.now().isoformat(timespec="seconds"), "digests": table_digests(main)}
    with open(os.path.join(backup_dir, POST_CONVERT_NAME), "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1, sort_keys=True)
    return snap


def changes_since_conversion(backup_dir: str, db_path: str) -> dict:
    """完整回滾會丟掉的東西：{"baseline", "rows_added", "rows_removed", "rewritten", "new_tables"}。

    基準＝轉換完成當下（`post_convert.json`）⇒ 轉換本身寫的那幾列（新設定鍵、補空值、模組表）不算。
    轉換沒做完（沒有基準檔）⇒ 退回用備份時的狀態當基準，`baseline`＝"backup"（含轉換本身的寫入）。
    """
    path = os.path.join(backup_dir, POST_CONVERT_NAME)
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            base, baseline = json.load(f)["digests"], "post_convert"
    else:
        base, baseline = load_manifest(backup_dir)["pre"].get("digests") or {}, "backup"
    now = table_digests(db_path, {t: d["columns"] for t, d in base.items()})
    now_all = table_counts(db_path)
    rep = {"baseline": baseline, "rows_added": {}, "rows_removed": {}, "rewritten": [], "new_tables": {}}
    for t, d in base.items():
        if t not in now or d["rows"] is None:
            continue
        n = now[t]
        if n["rows"] is None:
            rep["rewritten"].append(t)
        elif n["rows"] > d["rows"]:
            rep["rows_added"][t] = n["rows"] - d["rows"]
        elif n["rows"] < d["rows"]:
            rep["rows_removed"][t] = d["rows"] - n["rows"]
        elif n["sha256"] != d["sha256"]:
            rep["rewritten"].append(t)
    rep["new_tables"] = {t: c for t, c in now_all.items() if t not in base and c}
    return rep


def has_changes(rep: dict) -> bool:
    return bool(rep["rows_added"] or rep["rows_removed"] or rep["rewritten"] or rep["new_tables"])


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


def data_changes(root: str, manifest: dict) -> dict:
    """資料目錄與備份時清單的差異：{"missing", "changed", "added", "rotated"}（相對路徑，排序）。

    `rotated`＝會輪替的資料（本機每日快照 db_backups）缺少或改變——保留期限清掉舊快照是正常行為。
    """
    before, now = manifest["data_inventory"], inventory(root, kinds=("data",))
    rep = {"missing": [], "changed": [], "added": sorted(set(now) - set(before)), "rotated": []}
    for rel, want in sorted(before.items()):
        got = now.get(rel)
        if got == want:
            continue
        if rel.startswith(_ROTATING_DATA_PREFIXES):
            rep["rotated"].append(rel)
        else:
            rep["missing" if got is None else "changed"].append(rel)
    return rep


def rollback(root: str, backup_dir: str, mode: str, info: dict = None) -> list:
    """`mode`＝"full"（程式＋DB＋設定）或 "code"（只回程式，保留轉換後的資料）。回驗證 problems。

    動手之前先 `check_backup`（稽核 X-9b S-1）：備份不是這個安裝的、或逐檔雜湊／試還原不過 ⇒
    **一個檔都不動**，回 problems，並設 `info["precheck_failed"]=True`。
    `info`（選填）另收：資料目錄新增／輪替的檔（不算問題）、DB 邏輯內容比對結果。
    """
    if mode not in ("full", "code"):
        raise ValueError(mode)
    info = {} if info is None else info
    pre = check_backup(root, backup_dir)
    if pre:
        info["precheck_failed"] = True
        return ["回滾前檢查不通過（沒有動任何檔案）：%s" % p for p in pre]
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
    return verify_rollback(root, manifest, mode, info)


def verify_rollback(root: str, manifest: dict, mode: str, info: dict = None) -> list:
    """回滾後的比對。

    - 程式檔（兩種模式）；設定檔與 DB（full）：與備份逐檔雜湊相等。
    - full 的 DB 另比**邏輯內容**：與備份時**原檔**的 `logical_digest` 相同（稽核 X-9b O-1；
      位元組只會等於備份副本，SQLite 標頭計數欄位與原檔不同）。
    - 資料目錄（稽核 X-9b M-2）：只核對備份時就在的檔都還在、雜湊相同；轉換後新增的檔（上傳、每日快照）
      列進 `info["data_added"]`，不算問題；本機每日快照被保留期限清掉列進 `info["data_rotated"]`。
    """
    info = {} if info is None else info
    problems = []
    now_prog = {rel: sha256_file(f) for rel, f in program_files(root).items()}
    if now_prog != manifest["program"]:
        diff = set(now_prog.items()) ^ set(manifest["program"].items())
        problems.append("程式檔與備份不一致：%s" % sorted({d[0] for d in diff})[:10])
    if mode == "full":
        now_cfg = {rel: sha256_file(f) for rel, f in walk(root) if classify(rel) == "config"}
        if now_cfg != manifest["config"]:
            problems.append("設定檔與備份不一致")
        info["db_logical"] = {}
        for rel, want in manifest["db"].items():
            p = os.path.join(root, rel)
            if sha256_file(p) != want:
                problems.append("資料庫與備份副本的位元組不一致：%s" % rel)
            orig = (manifest["pre"].get("logical") or {}).get(rel)
            if orig is None:
                info["db_logical"][rel] = "備份沒有原檔的邏輯雜湊（舊版工具的備份）"
                continue
            try:
                same = logical_digest(p) == orig
            except Exception as exc:                          # noqa: BLE001
                problems.append("資料庫讀不了：%s（%s: %s）" % (rel, type(exc).__name__, exc))
                continue
            info["db_logical"][rel] = "與備份時原檔的邏輯內容相同" if same else "不同"
            if not same:
                problems.append("資料庫的邏輯內容與備份時的原檔不同：%s" % rel)
    dc = data_changes(root, manifest)
    info["data_added"], info["data_rotated"] = dc["added"], dc["rotated"]
    if dc["missing"] or dc["changed"]:
        problems.append("備份時就在的資料檔不見或被改（回滾不動資料目錄；是新版執行期間造成的）："
                        "不見 %s／被改 %s" % (dc["missing"][:10], dc["changed"][:10]))
    return problems
