# -*- coding: utf-8 -*-
"""lodging v1（2026-09-28，E 線）：附近旅宿的四張表（docs/platform/LODGING-NEARBY.md §3.3）。

- lodging_catalog（T3）：觀光署「旅館民宿 - 觀光資訊資料庫」快照；整批替換、可隨時重抓。
  **不存電話、經營者、統編**（民宿經營者多為自然人；D 審 Q2）。
- lodging_searches（T1）：使用者存下的一次查詢。中心點來源是 Google ⇒ center_lat/lng 一律 NULL（LG-M2）。
- lodging_search_items（T1）：該次查詢的結果（官方資料的衍生物 ⇒ 顯示與匯出要帶顯名）。
  中心點來源是 Google ⇒ distance_m 一律 NULL（LG-M2）。
- lodging_quotes（T1）：使用者自己輸入的詢價紀錄。
- 冪等（IF NOT EXISTS）；不自己 commit（run_all 包 SAVEPOINT，稽核 D PM1）；
  凍住的歷史：SQL 寫在這裡，不 import 任何會演進的程式碼（tests/platform/test_module_migrations.py）。
"""


def up(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS lodging_catalog ("
        " source TEXT NOT NULL,"
        " source_id TEXT NOT NULL,"
        " license_no TEXT NOT NULL DEFAULT '',"
        " name TEXT NOT NULL,"
        " class INTEGER NOT NULL,"
        " city TEXT NOT NULL DEFAULT '',"
        " town TEXT NOT NULL DEFAULT '',"
        " address TEXT NOT NULL DEFAULT '',"
        " lat REAL NOT NULL,"
        " lng REAL NOT NULL,"
        " price_low INTEGER,"
        " price_high INTEGER,"
        " room_info TEXT NOT NULL DEFAULT '',"
        " record_updated_at TEXT NOT NULL DEFAULT '',"
        " dataset_updated_at TEXT NOT NULL,"
        " PRIMARY KEY (source, source_id))")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lodging_catalog_latlng ON lodging_catalog(lat, lng)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS lodging_searches ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " created_at TEXT NOT NULL,"
        " created_by TEXT NOT NULL,"
        " center_kind TEXT NOT NULL,"
        " center_label TEXT NOT NULL DEFAULT '',"
        " center_lat REAL,"
        " center_lng REAL,"
        " center_source TEXT NOT NULL DEFAULT '',"
        " center_precision TEXT NOT NULL DEFAULT '',"
        " radius_m INTEGER NOT NULL,"
        " filters_json TEXT NOT NULL DEFAULT '{}',"
        " dataset_updated_at TEXT NOT NULL DEFAULT '',"
        " result_count INTEGER NOT NULL DEFAULT 0,"
        " note TEXT NOT NULL DEFAULT '')")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lodging_searches_by ON lodging_searches(created_by, id)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS lodging_search_items ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " search_id INTEGER NOT NULL,"
        " source TEXT NOT NULL,"
        " source_id TEXT NOT NULL,"
        " license_no TEXT NOT NULL DEFAULT '',"
        " name TEXT NOT NULL,"
        " class INTEGER NOT NULL,"
        " address TEXT NOT NULL DEFAULT '',"
        " lat REAL NOT NULL,"
        " lng REAL NOT NULL,"
        " distance_m INTEGER,"
        " price_low INTEGER,"
        " price_high INTEGER,"
        " price_registered_at TEXT NOT NULL DEFAULT '',"
        " dataset_updated_at TEXT NOT NULL DEFAULT '')")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lodging_items_search ON lodging_search_items(search_id)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS lodging_quotes ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " source TEXT NOT NULL,"
        " source_id TEXT NOT NULL,"
        " quoted_on TEXT NOT NULL,"
        " room_type TEXT NOT NULL DEFAULT '',"
        " price INTEGER NOT NULL,"
        " unit TEXT NOT NULL,"
        " includes TEXT NOT NULL DEFAULT '',"
        " channel TEXT NOT NULL,"
        " note TEXT NOT NULL DEFAULT '',"
        " entered_by TEXT NOT NULL,"
        " entered_at TEXT NOT NULL)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lodging_quotes_place ON lodging_quotes(source, source_id, quoted_on)")
    return None
