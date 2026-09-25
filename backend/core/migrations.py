# -*- coding: utf-8 -*-
"""每模組獨立版本的 migration（CORE-SPEC §6）。V9 基準（db._MIGRATIONS，v1~v116）凍結不動；
新的表一律由這裡的模組 migration 建立，版本記在 `module_schema_versions(module, version)`。

- `register(module, version, fn)`：登記一支 migration。版本從 1 起、連續、不可重複。
- `run_all(conn)`：依模組名排序，逐一把每個模組補跑到最新。每支跑完立刻記版本（中途失敗 ⇒ 停在上一版，
  修好後重跑從失敗那支接著跑；每支必須冪等，比照 V9 規則）。
- 只准新增（加表、加欄位），不可以刪欄位或改名——回退到舊程式碼時，舊程式碼讀不到的東西它就不讀（§6）。
- 模組沒安裝 ⇒ 它的 migration 沒登記 ⇒ 不建它的表（CORE-SPEC §6）。`core` 是 L1 自己，永遠登記。
"""
from datetime import datetime

_REGISTRY = {}          # module -> {version: fn}


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
    """回 `{module: (從, 到)}`（只列有跑的）。版本號不連續 ⇒ ValueError（不猜要跳過哪一支）。"""
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
            per[v](conn)
            conn.execute(
                "INSERT INTO module_schema_versions (module, version, applied_at) VALUES (?,?,?) "
                "ON CONFLICT(module) DO UPDATE SET version=excluded.version, applied_at=excluded.applied_at",
                (module, v, datetime.now().isoformat()))
            conn.commit()
        end = current_version(conn, module)
        if end != start:
            ran[module] = (start, end)
    return ran


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


register("core", 1, _core_v1_ui_definitions)
