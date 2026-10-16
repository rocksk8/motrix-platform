# -*- coding: utf-8 -*-
"""T69 SO-S3：刪除暫存區頁的『隔離目錄』設定面板（PM 裁示採案 1：面板放 recycle-bin.html，呼叫既有 PUT /api/recycle-bin/settings）。

① 頁面真的呼叫既有端點，並有停用說明、改回預設的按鈕
② 頁面用到的狀態鍵（dir／defaultDir／counts.in_bin／counts.restore_failed）＝後端 status 真的回的鍵
③ 端點權限不變：非最高管理者 403；最高管理者留空＝改回預設 200（真實使用者＋HTTP）
④ 暫存區有項目時伺服器拒絕改目錄（面板停用只是提示，伺服器自己守）
⑤ 沒破壞 AL1：只有一個 x-init、_initDone 守衛仍在
"""
import re

from core import source_tree

PAGE = "recycle-bin.html"


def _page():
    return source_tree.page_file(PAGE).read_text(encoding="utf-8")


def test_page_calls_the_existing_settings_endpoint_and_explains_the_lock():
    s = _page()
    assert "/api/recycle-bin/settings" in s and "method: 'PUT'" in s
    assert "暫存區還有項目時不能換目錄" in s              # 停用時的白話說明
    assert "不可放在網站上傳資料夾（uploads）底下" in s    # 提示和伺服器規則一致
    assert "rb-dir-default" in s and "改回預設位置" in s
    assert "dirLocked" in s


def _login(client, make_user, name, role):
    u, p = make_user(username=name, role=role)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_status_has_the_keys_the_panel_reads(client, make_user):
    su = _login(client, make_user, "rbd_su", "superadmin")
    st = client.get("/api/recycle-bin/status", headers=su).json()
    s = _page()
    for key in ("dir", "defaultDir"):
        assert key in st and ("st.%s" % key) in s, key
    for key in ("in_bin", "restore_failed"):
        assert key in st["counts"] and ("counts.%s" % key) in s, key


def test_settings_endpoint_permission_is_unchanged(client, make_user):
    su = _login(client, make_user, "rbd_su2", "superadmin")
    ad = _login(client, make_user, "rbd_ad", "admin")
    assert client.put("/api/recycle-bin/settings", headers=ad, json={"dir": ""}).status_code == 403
    r = client.put("/api/recycle-bin/settings", headers=su, json={"dir": ""})
    assert r.status_code == 200 and r.json()["ok"] is True, r.text


def test_server_refuses_a_new_directory_while_items_are_in_the_bin(client, make_user):
    import db
    su = _login(client, make_user, "rbd_su3", "superadmin")
    cn = db.get_db()
    rid = None
    try:
        cols = {c["name"]: c for c in cn.execute("PRAGMA table_info(recycle_bin)").fetchall()}
        vals = {}
        for n, c in cols.items():
            if n == "restore_status":
                vals[n] = "in_bin"
            elif c["notnull"] and c["dflt_value"] is None and not c["pk"]:
                vals[n] = 0 if "INT" in (c["type"] or "").upper() else "x"
        rid = cn.execute("INSERT INTO recycle_bin (%s) VALUES (%s)" % (",".join(vals), ",".join("?" * len(vals))), tuple(vals.values())).lastrowid
        cn.commit()
        r = client.put("/api/recycle-bin/settings", headers=su, json={"dir": ""})
        assert r.status_code == 409 and "暫存區還有" in r.text, r.text
    finally:
        if rid is not None:
            cn.execute("DELETE FROM recycle_bin WHERE id=?", (rid,))      # 只清自己插的那一列
        cn.commit()
        cn.close()


def test_panel_does_not_add_a_second_init():
    s = _page()
    assert len(re.findall(r"x-init=", s)) == 1
    assert s.count("_initDone") >= 2
