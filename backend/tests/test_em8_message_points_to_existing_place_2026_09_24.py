"""`EM8` · 訊息不可以指向畫面上不存在的東西（`STATE.md` 總表 `EM8`，2 條）。

```
dashboard.py   「需要調整請在系統設定修改 gcis_daily_limit」 —— 前端沒有這個設定
inventory.py   400 訊息列出 `edit_note` —— 畫面上沒有任何按鈕做這件事
```
🔑 比「讀者看不懂」嚴重：**他看懂了、照做了，而那個地方不存在。**
⚙️ 斷言打在**訊息本身**（dashboard 用 `ast` 取字串常數；inventory 真的打端點拿 detail），
   不是打在「前端有沒有那個設定」—— 修法可以是補 UI 也可以是改文案，
   這一題只要求「訊息不再指向不存在的地方」。
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _strings(rel):
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append(node.value)
    return out


def test_em8_the_gcis_limit_message_does_not_send_users_to_a_missing_setting():
    msgs = [s for s in _strings("backend/routers/company_lookup.py") if "明天會自動恢復" in s]
    assert msgs, "找不到那句上限訊息（錨點「明天會自動恢復」）—— 退回改本檔的錨點。"
    front = "".join(p.read_text(encoding="utf-8", errors="replace")
                    for p in (ROOT / "frontend").rglob("*.html"))
    assert "gcis_daily_limit" not in front, (
        "前端現在有 gcis_daily_limit 的設定了 —— 本題前提改變，改成驗「訊息指到那一格」。")
    for m in msgs:
        assert "gcis_daily_limit" not in m, (
            "訊息仍叫使用者去改 `gcis_daily_limit`：%r\n" % m
            + "☠️ 前端沒有這個設定 —— 他照做了，而那個地方不存在。")


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
