"""`JV13` · 傳票的製票／覆核／主管要印**顯示名稱**，不是帳號。

規格（`STATE.md` 總表 `JV13`）：`signatures_of()` 取 `created_by`（**username**），
而印在紙上／畫面上的要是顯示名稱。實作在 `helpers/voucher.py::resolve_display_names()`，
由 `read_voucher()` 套在 `signatures_of()` 的輸出上。

⚠️ 觀測點：**走 API 讀回來的 `signatures`**（前端與 PDF 讀的是同一份），
   而測試帳號要刻意讓 `display_name != username` —— `make_user` 預設兩者相同，
   不改的話「印帳號」與「印顯示名稱」分不出來，這一題會空綠。
"""
import pytest


_LINES = [{"account_code": "1113", "debit": 1000, "credit": 0},
          {"account_code": "4111", "debit": 0, "credit": 1000}]


def _hdr(client, make_user, username, display_name):
    u, p = make_user(username=username, role="superadmin", modules=["cashier"])
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE users SET display_name=? WHERE username=?", (display_name, u))
        conn.commit()
    finally:
        conn.close()
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def test_jv13_the_maker_slot_shows_the_display_name_not_the_username(client, make_user):
    u, hdr = _hdr(client, make_user, "jv13_maker", "王製票")
    assert u != "王製票", "量尺：帳號與顯示名稱必須不同，否則這一題分不出兩種實作"

    r = client.post("/api/vouchers", json={"summary": "JV13", "lines": _LINES}, headers=hdr)
    assert r.status_code in (200, 201), r.text[:200]
    vid = r.json().get("id") or r.json().get("voucher_id")

    v = client.get("/api/vouchers/%s" % vid, headers=hdr)
    assert v.status_code == 200, v.text[:200]
    sigs = v.json().get("signatures")
    assert isinstance(sigs, dict) and "製票" in sigs, "讀回來沒有簽核格：%r" % (sigs,)

    by = sigs["製票"]["by"]
    assert by == "王製票", (
        "製票那一格印的是 %r —— 預期顯示名稱「王製票」。\n" % by
        + "☠️ 印帳號（%r）的話，紙上的簽名欄是一串登入代號。" % u)


def test_jv13_an_unknown_username_falls_back_to_the_username_not_blank(client):
    """反向控制：查不到顯示名稱時要留帳號，不可以變空白（帳號至少查得到是誰）。

    ⚠️ `client` 不可以拿掉：DB 隔離是它建起來的，少了它 `db.get_db()` 會指到真的資料庫。
    """
    import db
    from helpers.voucher import resolve_display_names
    conn = db.get_db()
    try:
        out = resolve_display_names(conn, {"製票": {"by": "no_such_user_jv13", "at": "x"}})
    finally:
        conn.close()
    assert out["製票"]["by"] == "no_such_user_jv13", out
