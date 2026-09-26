"""EM8：訊息指向畫面上不存在的東西——庫存那一條（M03）。

2026-09-26 自 `backend/tests/test_em8_message_points_to_existing_place_2026_09_24.py` 移入，**沿用原檔名**：
規格涵蓋守門以檔名判斷同一編號是否分散在不相干的檔（PLAYBOOK §B-11：拿掉 M03 時這一題跟著消失）。
"""


def test_em8_the_inventory_action_message_does_not_offer_an_action_without_a_button(client, make_user):
    import db
    u, p = make_user("em8_admin", role="admin")
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    conn = db.get_db()
    try:
        cur = conn.execute(
            "INSERT INTO stock_items (part_no, serial_no, status, created_at, updated_at)"
            " VALUES ('EM8-P','EM8-S','in_stock','2026-09-24','2026-09-24')")
        conn.commit()
        iid = cur.lastrowid
    finally:
        conn.close()
    r = client.post("/api/inventory/stock-items/%d/adjust" % iid,
                    json={"action": "nonsense"}, headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 400, r.text[:200]
    detail = r.json().get("detail", "")
    assert "edit_note" not in detail, (
        "400 訊息列出了 `edit_note`：%r\n" % detail
        + "☠️ 畫面上沒有任何按鈕做「修改備註」—— 訊息提供了一條不存在的路。")
