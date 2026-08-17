"""一次性資料同步：補齊過去兩筆只在開發機做過、從未隨部署包搬到正式機的資料異動。

背景：
  1. 2026-08-08s — 公司電話改為 04-3610-6566，但 system_settings.company_profile
     只在 init_db() 首次建立資料庫時寫入種子值，之後改程式碼種子常數不會回溯更新
     既有資料庫；當時只手動同步了開發機。
  2. 2026-08-06 — 供應商「聯洲國際有限公司」（S-202607-003）補上 VIGI 標籤（原本只有
     Omada），是直接改資料庫的異動，不隨部署包（只含程式碼）搬移。

冪等：兩項都先檢查現況，已經是正確值就跳過、不會重複套用或覆蓋其他欄位。

用法（於正式機 backend/ 目錄下執行，套用完部署包、確認伺服器已重啟之後再跑）：
    python tools/sync_pending_data_20260817.py
"""
import json
import sqlite3
from datetime import datetime

DB_PATH = "motrix_erp.db"

CORRECT_CONTACT_INFO = "Tel: 04-3610-6566｜info@miactw.com"
SUPPLIER_CODE = "S-202607-003"
REQUIRED_TAG = "VIGI"


def sync_company_profile(conn):
    row = conn.execute(
        "SELECT value_json FROM system_settings WHERE key='company_profile'"
    ).fetchone()
    if not row:
        print("[公司資料] 找不到 company_profile 設定，跳過（不應發生，請人工檢查）。")
        return
    profile = json.loads(row["value_json"])
    current = profile.get("contact_info", "")
    if current == CORRECT_CONTACT_INFO:
        print(f"[公司資料] 已是最新（{current}），無需異動。")
        return
    print(f"[公司資料] 目前值：{current!r} → 更新為：{CORRECT_CONTACT_INFO!r}")
    profile["contact_info"] = CORRECT_CONTACT_INFO
    conn.execute(
        "UPDATE system_settings SET value_json=?, updated_at=? WHERE key='company_profile'",
        (json.dumps(profile, ensure_ascii=False), datetime.now().isoformat()),
    )
    print("[公司資料] 已更新。")


def sync_supplier_tag(conn):
    row = conn.execute(
        "SELECT data_json, updated_at FROM suppliers WHERE code=?", (SUPPLIER_CODE,)
    ).fetchone()
    if not row:
        print(f"[供應商標籤] 找不到 {SUPPLIER_CODE}，跳過（正式機供應商代碼可能不同，請人工確認）。")
        return
    data = json.loads(row["data_json"] or "{}")
    tags = data.get("tags") or []
    if REQUIRED_TAG in tags:
        print(f"[供應商標籤] {SUPPLIER_CODE} 已含 {REQUIRED_TAG}（現有標籤：{tags}），無需異動。")
        return
    print(f"[供應商標籤] {SUPPLIER_CODE} 目前標籤：{tags} → 新增 {REQUIRED_TAG}")
    tags.append(REQUIRED_TAG)
    data["tags"] = tags
    conn.execute(
        "UPDATE suppliers SET data_json=?, updated_at=? WHERE code=?",
        (json.dumps(data, ensure_ascii=False), datetime.now().isoformat(), SUPPLIER_CODE),
    )
    print("[供應商標籤] 已更新。")


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        sync_company_profile(conn)
        sync_supplier_tag(conn)
        conn.commit()
    finally:
        conn.close()
    print("完成。")


if __name__ == "__main__":
    main()
