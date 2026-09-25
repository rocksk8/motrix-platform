"""測試用：建立一筆今天有效的簽核代理（L1 `approval_delegates`）。

2026-09-26 自 test_bonus_case_api 抽出：M07 搬進 modules/ 之後，模組外的題（連簽紀錄、額外支出）不可以再 import
模組的測試檔（M07 不在時會 ImportError），而這支本來就只碰 L1 的表。
"""
from datetime import date, timedelta


def delegate(delegator, delegate_to):
    import db
    today = date.today()
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO approval_delegates (delegator_username, delegate_username, start_date, end_date,"
            " active, created_at, updated_at) VALUES (?,?,?,?,1,?,?)",
            (delegator, delegate_to, (today - timedelta(days=1)).isoformat(),
             (today + timedelta(days=1)).isoformat(), "t", "t"))
        conn.commit()
    finally:
        conn.close()
