"""自 `tests/test_queue_and_feed_scoping_2026_09_15.py` 拆出（M08 搬遷反向控制：這幾題需要營運分析模組，拿掉模組時一起消失）。"""
import json
from datetime import date, timedelta
from tests.test_queue_and_feed_scoping_2026_09_15 import (  # noqa: E402,F401  含 fixture
    _feed_serials,
    _insert_stock_item,
    _login,
)


def test_feed_hides_other_peoples_stock_movements(client, make_user):
    """只有 dashboard 模組的檢視者，不該在首頁看到別人的料件流向。"""
    viewer, vp = make_user(username="fd_viewer", role="viewer", modules=["dashboard"])
    _insert_stock_item("SN-OTHER-1", "別人")

    assert _feed_serials(client, _login(client, viewer, vp)) == set()

    # 正向控制：有庫存模組的人看得到同一筆（證明資料真的在、端點沒壞）
    keeper, kp = make_user(username="fd_keeper", role="viewer",
                           modules=["dashboard", "inventory"])
    assert "PART-X / SN-OTHER-1" in _feed_serials(client, _login(client, keeper, kp))


def test_feed_still_shows_the_users_own_stock_movements(client, make_user):
    """自己動過的要留著——「只能看到自己的」不是「什麼都看不到」。"""
    viewer, vp = make_user(username="fd_own", role="viewer", modules=["dashboard"])
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT display_name FROM users WHERE username='fd_own'").fetchone()
        my_display = row["display_name"]
    finally:
        conn.close()

    _insert_stock_item("SN-MINE-1", my_display)
    _insert_stock_item("SN-THEIRS-1", "別人")

    seen = _feed_serials(client, _login(client, viewer, vp))
    assert "PART-X / SN-MINE-1" in seen, seen
    assert "PART-X / SN-THEIRS-1" not in seen, seen


def test_feed_blank_actor_is_not_treated_as_mine(client, make_user):
    """歸屬欄位空白的紀錄不給——無法證明是自己的，就不是自己的。

    這張表沒有 user id 欄位，只能比對顯示名稱字串；空字串如果當成「符合」，
    等於所有沒填操作者的紀錄全部外洩（而那是最常見的舊資料樣態）。
    """
    viewer, vp = make_user(username="fd_blank", role="viewer", modules=["dashboard"])
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO stock_items (part_no, serial_no, status, quote_no, consumed_by, "
            "created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            ("PART-X", "SN-BLANK-1", "已出貨", "MQ-FEED-001", "", "",
             "2026-09-01T00:00:00", "2026-09-14T10:00:00"))
        conn.commit()
    finally:
        conn.close()

    assert _feed_serials(client, _login(client, viewer, vp)) == set()
