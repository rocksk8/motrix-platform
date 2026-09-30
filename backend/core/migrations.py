# -*- coding: utf-8 -*-
"""每模組獨立版本的 migration（CORE-SPEC §6）。

[單位] plat:migrations    [層] L0    [穩定度] 契約（改介面照 PLAYBOOK §C-7 升版）
[公開介面] current_version, incomplete, register, registered, run_all
[不變式] 版本從 1 起、連續、不可重複；每支**回 None** 才記版本（回原因字串＝未完成：不記、ERROR、該模組後面的這次不跑、其他模組照跑、
         不丟例外）；只准新增（加表、加欄位），不刪欄位、不改名；每支必須冪等
         core 以外的模組逐支 SAVEPOINT：**丟例外＝未完成**（原因「例外：<型別>: <訊息>」、撤回這一支的寫入、不往上丟，稽核 D PM1）；
         core 的例外照舊往上丟；模組 migration 不准自己 commit（run_all 負責）
[契約題] tests/test_definitions_store_2026_09_25.py、tests/platform/test_migration_incomplete.py
[注意] V9 基準（db._MIGRATIONS v1~v116）凍結不動，新表一律由這裡建；模組沒安裝 ⇒ migration 沒登記 ⇒ 不建它的表

V9 基準（db._MIGRATIONS，v1~v116）凍結不動；
新的表一律由這裡的模組 migration 建立，版本記在 `module_schema_versions(module, version)`。

- `register(module, version, fn)`：登記一支 migration。版本從 1 起、連續、不可重複。
- `run_all(conn)`：依模組名排序，逐一把每個模組補跑到最新。每支跑完立刻記版本（中途失敗 ⇒ 停在上一版，
  修好後重跑從失敗那支接著跑；每支必須冪等，比照 V9 規則）。
- **回傳值慣例**（CORE 1.58，2026-09-28 使用者裁示「該補就補」）：migration 函式回 `None`＝完成 ⇒ 記版號；
  回**非空字串**＝這次做不了、字串是原因 ⇒ **不記版號**、記 ERROR、該模組後面的版號這次也不跑（不跳號）、其他模組照跑、
  `run_all` 不丟例外（服務照常起來），下次再從同一版試；回其他值（True、數字…）＝寫錯 ⇒ 同樣不記＋ERROR（不猜）。
  用回傳值不用例外：migration 檔不准 import 會演進的程式碼（含 core），丟不出 core 定義的例外。
  回報未完成的函式自己負責不留半套（先檢查、後動手；不 commit 半套）。
- `incomplete(db_path)`：最近一次對**該庫**跑 `run_all` 時沒完成的，見其 docstring（乾跑工具據此判失敗）。
- 只准新增（加表、加欄位），不可以刪欄位或改名——回退到舊程式碼時，舊程式碼讀不到的東西它就不讀（§6）。
- 模組沒安裝 ⇒ 它的 migration 沒登記 ⇒ 不建它的表（CORE-SPEC §6）。`core` 是 L1 自己，永遠登記。
"""
import logging
import os
import sqlite3
from datetime import datetime

_REGISTRY = {}          # module -> {version: fn}
_INCOMPLETE = {}        # 正規化的庫路徑 -> {module: (version, reason)}；主庫、demo 庫各一份，互不覆蓋
_log = logging.getLogger("motrix.migrations")


def register(module: str, version: int, fn) -> None:
    per = _REGISTRY.setdefault(module, {})
    if version in per and per[version] is not fn:
        raise ValueError("migration %s v%d 已登記為另一支函式" % (module, version))
    per[version] = fn


def registered() -> dict:
    return {m: sorted(v) for m, v in _REGISTRY.items()}


def current_version(conn, module: str) -> int:
    row = conn.execute("SELECT version FROM module_schema_versions WHERE module=?", (module,)).fetchone()
    return row[0] if row else 0


def run_all(conn) -> dict:
    """回 `{module: (從, 到)}`（只列版號有前進的）。版本號不連續 ⇒ ValueError（不猜要跳過哪一支）。
    未完成的（見回傳值慣例）不丟例外，記在 `incomplete(該庫路徑)`；每次呼叫先清掉該庫上一次的紀錄。"""
    key = _conn_path(conn)
    todo = {}
    _INCOMPLETE[key] = todo
    ran = {}
    for module in sorted(_REGISTRY):
        per = _REGISTRY[module]
        versions = sorted(per)
        if versions != list(range(1, len(versions) + 1)):
            raise ValueError("migration %s 的版本號必須從 1 連續：%s" % (module, versions))
        start = current_version(conn, module)
        for v in versions:
            if v <= start:
                continue
            if module == "core":
                res = per[v](conn)              # core（L1）不完整就不該起來 ⇒ 例外照舊往上丟
            else:
                # 稽核 D PM1：L2 的 migration 在啟動必經路徑上 ⇒ 比照 loader「一個模組壞掉不拖垮整台」。
                # 逐支 SAVEPOINT：丟例外或回原因 ⇒ 撤回這一支做到一半的寫入（含 DDL），記進 incomplete；
                # 由 fail_incomplete_modules 讓該模組下線，其他模組與服務照常。migration 不准自己 commit（會讓 savepoint 失效，守門見契約題）。
                conn.execute("SAVEPOINT motrix_module_migration")
                try:
                    res = per[v](conn)
                except Exception as exc:        # noqa: BLE001 — 任何例外都只算這一個模組未完成
                    res = "例外：%s: %s" % (type(exc).__name__, exc)
                try:
                    if res is None:
                        conn.execute("RELEASE motrix_module_migration")
                    else:
                        conn.execute("ROLLBACK TO motrix_module_migration")
                        conn.execute("RELEASE motrix_module_migration")
                except sqlite3.OperationalError as exc:
                    # savepoint 不在了＝這支 migration 自己結束了交易（commit／executescript）：寫進去的撤不回，
                    # 但不可以因此讓整台起不來；不記版號、記未完成（repo 內的由守門擋，這裡擋第三方）
                    res = ("違規：migration 自己結束了交易（commit／executescript），寫入無法撤回、版號不前進"
                           "（%s）；原本的結果：%s" % (exc, "完成" if res is None else res))
            if res is not None:
                why = res.strip() if isinstance(res, str) and res.strip() else (
                    "migration 回傳值只能是 None（完成）或原因字串（未完成），收到 %r" % (res,))
                todo[module] = (v, why)
                _log.error("模組 migration 未完成：%s v%d（%s），版號不前進，下次啟動再試：%s", module, v, key or "記憶體庫", why)
                break
            conn.execute(
                "INSERT INTO module_schema_versions (module, version, applied_at) VALUES (?,?,?) "
                "ON CONFLICT(module) DO UPDATE SET version=excluded.version, applied_at=excluded.applied_at",
                (module, v, datetime.now().isoformat()))
            conn.commit()
        end = current_version(conn, module)
        if end != start:
            ran[module] = (start, end)
    return ran


def _norm(path) -> str:
    return os.path.normcase(os.path.abspath(path)) if path else ""


def _conn_path(conn) -> str:
    """連線的主庫檔路徑（正規化）；記憶體庫／讀不到 ⇒ ""。"""
    try:
        for row in conn.execute("PRAGMA database_list").fetchall():
            if row[1] == "main":
                return _norm(row[2] or "")
    except Exception:        # noqa: BLE001 — 只影響未完成紀錄的分組，不擋 migration
        pass
    return ""


def incomplete(db_path):
    """🔒 介面（H12 乾跑工具依此判定；改形狀要升主版號）：

    `incomplete(db_path: str) -> dict[str, tuple[int, str]] | None`

    - `dict`：本行程**最近一次**對 `db_path` 那個庫跑 `run_all` 時沒完成的 `{模組: (停在的版號, 原因)}`；
      空 dict ＝ 那一次全部完成。**非空 ⇒ 乾跑失敗**。
    - `None`：本行程沒有對這個庫跑過 `run_all`——**不是**「全部完成」，呼叫端不可以當成通過。
    - 依庫分開記（路徑正規化後比對）：主庫、demo 庫各跑一次，互不覆蓋。回傳複本。"""
    got = _INCOMPLETE.get(_norm(db_path))
    return None if got is None else dict(got)


# ── core（L1）自己的 migration ───────────────────────────────────────────────

def _core_v1_ui_definitions(conn):
    """定義文件庫（CUSTOMIZATION-SPEC §3.5）：版面／輸出版型覆寫／自訂欄位／自訂模組共用。"""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS ui_definitions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            kind         TEXT    NOT NULL,
            key          TEXT    NOT NULL,
            scope        TEXT    NOT NULL DEFAULT 'company',
            version      INTEGER NOT NULL DEFAULT 0,
            status       TEXT    NOT NULL DEFAULT 'draft',
            body_json    TEXT    NOT NULL DEFAULT '{}',
            note         TEXT    NOT NULL DEFAULT '',
            created_by   TEXT    NOT NULL DEFAULT '',
            created_at   TEXT    NOT NULL DEFAULT '',
            published_by TEXT    NOT NULL DEFAULT '',
            published_at TEXT    NOT NULL DEFAULT '',
            UNIQUE(kind, key, scope, version)
        );
        CREATE INDEX IF NOT EXISTS idx_ui_definitions_lookup ON ui_definitions(kind, key, scope, status, version);
    """)
    conn.commit()


def _core_v2_custom_records(conn):
    """自訂模組的單據（P8，CUSTOMIZATION-SPEC §1「文件式」）：每筆一份 JSON；欄位值另存索引表供查詢排序；
    建立或修改模組不用改資料庫結構。T1（每日 JSON 匯出、跟著資料庫備份）。"""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS custom_records (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            module_key    TEXT    NOT NULL,
            record_no     TEXT    NOT NULL,
            def_version   INTEGER NOT NULL,
            status        TEXT    NOT NULL DEFAULT '',
            data_json     TEXT    NOT NULL DEFAULT '{}',
            approval_json TEXT    NOT NULL DEFAULT '{}',
            created_by    TEXT    NOT NULL DEFAULT '',
            created_at    TEXT    NOT NULL DEFAULT '',
            updated_by    TEXT    NOT NULL DEFAULT '',
            updated_at    TEXT    NOT NULL DEFAULT '',
            UNIQUE(module_key, record_no)
        );
        CREATE INDEX IF NOT EXISTS idx_custom_records_status ON custom_records(module_key, status);
        CREATE TABLE IF NOT EXISTS custom_record_values (
            record_id  INTEGER NOT NULL,
            module_key TEXT    NOT NULL,
            field      TEXT    NOT NULL,
            value_text TEXT,
            value_num  REAL
        );
        CREATE INDEX IF NOT EXISTS idx_custom_record_values_field ON custom_record_values(module_key, field, value_text);
        CREATE INDEX IF NOT EXISTS idx_custom_record_values_record ON custom_record_values(record_id);
        CREATE TABLE IF NOT EXISTS custom_record_counters (
            module TEXT    NOT NULL,
            period TEXT    NOT NULL,
            seq    INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(module, period)
        );
        CREATE TABLE IF NOT EXISTS custom_record_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id  INTEGER NOT NULL,
            action     TEXT    NOT NULL,
            from_state TEXT    NOT NULL DEFAULT '',
            to_state   TEXT    NOT NULL DEFAULT '',
            by_user    TEXT    NOT NULL DEFAULT '',
            note       TEXT    NOT NULL DEFAULT '',
            at         TEXT    NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_custom_record_log_record ON custom_record_log(record_id);
    """)
    conn.commit()


register("core", 1, _core_v1_ui_definitions)
register("core", 2, _core_v2_custom_records)


# ── core v3：歷史紀錄分層搜尋（2026-09-30）───────────────────────────────────
# 凍結的規則副本（migration 不准 import 會演進的程式）；與 helpers/audit.py::_derive_fields 同一份規則，
# tests/test_audit_search_2026_09_30.py 逐列驗證兩邊算出同樣的結果。
_V3_DOC_TARGET_TYPES = frozenset({
    "vouchers", "contractor_dispatch", "shipping_note", "payslip", "completion_note", "invoice_voucher", "payment_request",
    "bonus_awards", "bonus_case_awards", "contractor_payment_voucher", "custom_record", "stock_batch", "network_plan",
    "case_action_item", "case_update",
})
_V3_BATCH = 5000


def _v3_derive(action, target_type, target_id, target_label, detail):
    import json as _json
    import re as _re
    rx = _re.compile(r"MQ-\d{6}-\d{3}")
    module = (action or "").split(".", 1)[0]
    hay = [str(target_id or ""), str(target_label or "")]
    try:
        d = _json.loads(detail or "{}")
    except ValueError:
        d = detail
    if isinstance(d, dict):
        hay += [v for v in d.values() if isinstance(v, str)]
    elif isinstance(d, str):
        hay.append(d)
    case_no = ""
    for h in hay:
        m = rx.search(h)
        if m:
            case_no = m.group(0)
            break
    ref_no = str(target_id or "") if (target_type or "") in _V3_DOC_TARGET_TYPES else ""
    return module, case_no, ref_no


def _core_v3_audit_search(conn):
    """audit_log 加 module／case_no／ref_no／result／reason_code／status_code＋搜尋索引；舊列分批回填（每批 commit、可重入）。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(audit_log)").fetchall()}
    if not cols:
        return "audit_log 表不存在"
    for name, ddl in (("module", "TEXT NOT NULL DEFAULT ''"), ("case_no", "TEXT NOT NULL DEFAULT ''"),
                      ("ref_no", "TEXT NOT NULL DEFAULT ''"), ("result", "TEXT NOT NULL DEFAULT 'ok'"),
                      ("reason_code", "TEXT NOT NULL DEFAULT ''"), ("status_code", "INTEGER NOT NULL DEFAULT 0")):
        if name not in cols:
            conn.execute("ALTER TABLE audit_log ADD COLUMN %s %s" % (name, ddl))
    for idx, cols_ in (("idx_audit_module", "module, id"), ("idx_audit_case", "case_no, id"), ("idx_audit_ref", "ref_no, id"),
                       ("idx_audit_result", "result, id"), ("idx_audit_user", "username, id"), ("idx_audit_at", "at"),
                       ("idx_audit_action", "action, id")):
        conn.execute("CREATE INDEX IF NOT EXISTS %s ON audit_log(%s)" % (idx, cols_))
    conn.commit()
    last = 0
    while True:
        rows = conn.execute(
            "SELECT id, action, target_type, target_id, target_label, detail FROM audit_log "
            "WHERE id>? AND module='' ORDER BY id LIMIT ?", (last, _V3_BATCH)).fetchall()
        if not rows:
            break
        conn.executemany(
            "UPDATE audit_log SET module=?, case_no=?, ref_no=? WHERE id=?",
            [_v3_derive(r[1], r[2], r[3], r[4], r[5]) + (r[0],) for r in rows])
        conn.commit()
        last = rows[-1][0]
    return None


register("core", 3, _core_v3_audit_search)
