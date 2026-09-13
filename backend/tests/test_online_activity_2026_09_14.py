"""在線成員與在線時數統計（2026-09-14，DB v79）。

使用者要求：「右上角可顯示在線成員跟數量，並且後台統計每個成員包含管理員、
最高管理者在線上的時間，這些數據只有超級管理員看得到」。

三個重點：
1. **兩支端點都限最高管理者**——在線名單本身就是行蹤資訊，時數更是
2. **累加是活躍時間不是登入時長**：由 `main.py::auth_middleware` 沿用既有的
   `last_active` 節流點累加（每 5 分鐘一次），沒有請求就不會累加
3. **「在線」＝ 5 分鐘內有活動**，資料來源是 sessions.last_active，不另做心跳
"""
import json
from datetime import datetime, timedelta


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _touch_session(token, seconds_ago):
    """把某個 session 的 last_active 往前挪，模擬「幾秒前活動過」。"""
    import db
    conn = db.get_db()
    try:
        stamp = (datetime.now() - timedelta(seconds=seconds_ago)).isoformat()
        conn.execute("UPDATE sessions SET last_active=? WHERE token=?", (stamp, token))
        conn.commit()
    finally:
        conn.close()


# ── 權限 ─────────────────────────────────────────────────────────────────────

def test_only_superadmin_can_read_online_users(client, make_user):
    u, p = make_user(username="on_admin", role="admin")
    r = client.get("/api/online-users", headers=_auth(_login(client, u, p)))
    assert r.status_code == 403, f"admin 不該看得到在線名單：{r.status_code}"

    su, sp = make_user(username="on_super", role="superadmin")
    assert client.get("/api/online-users",
                      headers=_auth(_login(client, su, sp))).status_code == 200


def test_only_superadmin_can_read_activity_stats(client, make_user):
    u, p = make_user(username="act_admin", role="admin")
    assert client.get("/api/user-activity",
                      headers=_auth(_login(client, u, p))).status_code == 403

    su, sp = make_user(username="act_super", role="superadmin")
    assert client.get("/api/user-activity",
                      headers=_auth(_login(client, su, sp))).status_code == 200


# ── 在線判定 ─────────────────────────────────────────────────────────────────

def test_online_list_uses_the_five_minute_window(client, make_user):
    """在線＝5 分鐘內有活動；更早的不算。

    觀測點是**名單內容**而不是只看 count——count 對了但列錯人的話，右上角那顆
    按鈕會顯示正確數字、下拉卻是錯的名字。
    """
    su, sp = make_user(username="win_super", role="superadmin")
    recent_u, recent_p = make_user(username="win_recent", role="sales")
    stale_u, stale_p = make_user(username="win_stale", role="engineer")

    su_tok = _login(client, su, sp)
    recent_tok = _login(client, recent_u, recent_p)
    stale_tok = _login(client, stale_u, stale_p)

    _touch_session(recent_tok, 60)       # 1 分鐘前 → 在線
    _touch_session(stale_tok, 3600)      # 1 小時前 → 不在線

    body = client.get("/api/online-users", headers=_auth(su_tok)).json()
    names = {u["username"] for u in body["users"]}
    assert "win_recent" in names, body
    assert "win_stale" not in names, body
    assert body["count"] == len(body["users"])


def test_online_list_includes_admins_and_superadmins(client, make_user):
    """使用者特別點名「包含管理員、最高管理者」——他們不能被排除在統計之外。"""
    su, sp = make_user(username="inc_super", role="superadmin")
    ad_u, ad_p = make_user(username="inc_admin", role="admin")
    su_tok = _login(client, su, sp)
    ad_tok = _login(client, ad_u, ad_p)
    _touch_session(su_tok, 30)
    _touch_session(ad_tok, 30)

    body = client.get("/api/online-users", headers=_auth(su_tok)).json()
    names = {u["username"] for u in body["users"]}
    assert {"inc_super", "inc_admin"} <= names, body


# ── 時數累加 ─────────────────────────────────────────────────────────────────

def test_activity_accumulates_on_requests(client, make_user):
    """把 last_active 挪到 6 分鐘前再打一次 API，那段間隔要被累加進當天時數。

    觀測點放在**資料表的秒數**（成功才會被寫入的下游），不是回傳碼。
    """
    import db
    su, sp = make_user(username="acc_super", role="superadmin")
    tok = _login(client, su, sp)

    _touch_session(tok, 360)                      # 6 分鐘前活動過
    client.get("/api/ping", headers=_auth(tok))   # 這一下會觸發累加
    client.get("/api/auth/me", headers=_auth(tok))

    conn = db.get_db()
    try:
        row = conn.execute(
            "SELECT SUM(active_seconds) s FROM user_activity_daily a "
            "JOIN users u ON u.id=a.user_id WHERE u.username='acc_super'").fetchone()
    finally:
        conn.close()
    assert row["s"] and row["s"] >= 300, f"沒有累加到在線時數：{row['s']}"

    body = client.get("/api/user-activity", headers=_auth(tok)).json()
    mine = [i for i in body["items"] if i["username"] == "acc_super"]
    assert mine and mine[0]["totalSeconds"] >= 300, body


def test_long_gap_is_not_counted_as_online_time(client, make_user):
    """關機一晚隔天再開，不可以被算成連續在線——超過門檻只重新起算。"""
    import db
    su, sp = make_user(username="gap_super", role="superadmin")
    tok = _login(client, su, sp)

    _touch_session(tok, 8 * 3600)                 # 8 小時前（超過 _ACTIVITY_GAP_MAX）
    client.get("/api/ping", headers=_auth(tok))

    conn = db.get_db()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(active_seconds), 0) s FROM user_activity_daily a "
            "JOIN users u ON u.id=a.user_id WHERE u.username='gap_super'").fetchone()
    finally:
        conn.close()
    assert row["s"] == 0, f"長時間離線被算進時數了：{row['s']} 秒"


def test_activity_range_filter(client, make_user):
    """統計要能依日期區間查；區間外的不該混進來。"""
    import db
    su, sp = make_user(username="rng_super", role="superadmin")
    tok = _login(client, su, sp)
    conn = db.get_db()
    try:
        uid = conn.execute("SELECT id FROM users WHERE username='rng_super'").fetchone()["id"]
        for day, secs in (("2026-01-05", 3600), ("2026-02-05", 7200)):
            conn.execute(
                "INSERT INTO user_activity_daily (user_id, day, active_seconds, first_seen_at, last_seen_at) "
                "VALUES (?,?,?,?,?)", (uid, day, secs, day + "T09:00:00", day + "T18:00:00"))
        conn.commit()
    finally:
        conn.close()

    body = client.get("/api/user-activity?start=2026-01-01&end=2026-01-31",
                      headers=_auth(tok)).json()
    mine = [i for i in body["items"] if i["username"] == "rng_super"]
    assert mine and mine[0]["totalSeconds"] == 3600, body
    assert list(mine[0]["days"].keys()) == ["2026-01-05"], mine[0]["days"]


# ── 逐條操作軌跡（2026-09-14 使用者要求）────────────────────────────────────

def test_trail_records_what_a_user_looked_at(client, make_user):
    """使用者開了哪一頁、動了哪個資源，要逐條留下來（含被擋下來的）。

    觀測點是**軌跡表的內容**而不是端點回傳碼：這支功能的價值就在內容本身。
    """
    su, sp = make_user(username="tr_super", role="superadmin")
    tok = _login(client, su, sp)

    client.get("/api/customers", headers=_auth(tok))
    client.get("/api/parts", headers=_auth(tok))

    body = client.get("/api/user-activity/trail?user=tr_super", headers=_auth(tok)).json()
    paths = [i["path"] for i in body["items"]]
    assert "/api/customers" in paths, paths
    assert "/api/parts" in paths, paths
    labels = {i["path"]: i["label"] for i in body["items"]}
    assert labels.get("/api/customers") == "客戶管理", labels


def test_trail_skips_polling_endpoints(client, make_user):
    """輪詢類請求不記——否則每個開著的分頁每分鐘就把真正的動作洗掉。"""
    su, sp = make_user(username="tr_poll", role="superadmin")
    tok = _login(client, su, sp)
    for _ in range(3):
        client.get("/api/ping", headers=_auth(tok))
        client.get("/api/auth/me", headers=_auth(tok))
        client.get("/api/online-users", headers=_auth(tok))

    body = client.get("/api/user-activity/trail?user=tr_poll", headers=_auth(tok)).json()
    noisy = [i["path"] for i in body["items"]
             if i["path"].startswith(("/api/ping", "/api/auth/me", "/api/online-users"))]
    assert not noisy, f"輪詢端點被記進軌跡：{noisy}"


def test_trail_dedupes_repeated_calls(client, make_user):
    """同一支端點 30 秒內連打多次只記一次（防自動存檔／搜尋輸入洗版）。"""
    su, sp = make_user(username="tr_dedupe", role="superadmin")
    tok = _login(client, su, sp)
    for _ in range(5):
        client.get("/api/customers", headers=_auth(tok))

    body = client.get("/api/user-activity/trail?user=tr_dedupe", headers=_auth(tok)).json()
    hits = [i for i in body["items"] if i["path"] == "/api/customers"]
    assert len(hits) == 1, f"重複請求沒有收斂：{len(hits)} 筆"


def test_trail_records_blocked_attempts(client, make_user):
    """被擋下來的操作也要留痕——那往往比成功的更需要查。"""
    su, sp = make_user(username="tr_watcher", role="superadmin")
    u, p = make_user(username="tr_viewer", role="viewer", modules=["dashboard"])
    tok = _login(client, u, p)
    assert client.get("/api/parts", headers=_auth(tok)).status_code == 403

    body = client.get("/api/user-activity/trail?user=tr_viewer",
                      headers=_auth(_login(client, su, sp))).json()
    blocked = [i for i in body["items"] if i["path"] == "/api/parts" and i["status"] == 403]
    assert blocked, body["items"]


def test_trail_is_superadmin_only(client, make_user):
    u, p = make_user(username="tr_admin", role="admin")
    assert client.get("/api/user-activity/trail",
                      headers=_auth(_login(client, u, p))).status_code == 403


def test_trail_prune_keeps_recent_and_drops_old(client, make_user):
    """保留 90 天：舊的清掉、近期的留著（每日排程會呼叫）。"""
    import db
    from datetime import datetime, timedelta
    from routers.daily_tasks import _prune_request_log

    su, sp = make_user(username="tr_prune", role="superadmin")
    tok = _login(client, su, sp)
    conn = db.get_db()
    try:
        uid = conn.execute("SELECT id FROM users WHERE username='tr_prune'").fetchone()["id"]
        old = (datetime.now() - timedelta(days=120)).isoformat()
        new = (datetime.now() - timedelta(days=3)).isoformat()
        for at in (old, new):
            conn.execute("INSERT INTO user_request_log (user_id, at, method, path, page, status) "
                         "VALUES (?,?,?,?,?,?)", (uid, at, "GET", "/api/customers", "customers.html", 200))
        conn.commit()
    finally:
        conn.close()

    _prune_request_log()

    conn = db.get_db()
    try:
        rows = conn.execute("SELECT at FROM user_request_log WHERE user_id=?", (uid,)).fetchall()
    finally:
        conn.close()
    ats = [r["at"] for r in rows]
    assert all(a >= (datetime.now() - timedelta(days=91)).isoformat() for a in ats), ats
    assert len(ats) >= 1, "近期的紀錄被一起清掉了"


# ── 同時編輯警示（2026-09-14 使用者要求）──────────────────────────────────────
#
# 「兩個人同時進入報價單、或是修改同一個表格，需跳出警示，避免兩人同時修改
# 損失一方資料」。兩道防線：
#   ①**進入時**的 presence 警示（這一節）——讓人來得及先喊一聲
#   ②**存檔時**的樂觀鎖 409（下面兩題）——資料不會被無聲覆蓋
# 兩道都要，缺一不可：只有①，忽略警示照樣覆蓋；只有②，打完 20 分鐘的字才發現白做。

def test_presence_shows_other_editors(client, make_user):
    """B 進入同一份單據時，要看得到 A 也在編。"""
    a_u, a_p = make_user(username="pres_a", role="admin")
    b_u, b_p = make_user(username="pres_b", role="admin")
    a_tok, b_tok = _login(client, a_u, a_p), _login(client, b_u, b_p)

    body = {"doc_type": "quotation", "doc_id": "MQ-PRES-001"}
    r_a = client.post("/api/edit-presence", json=body, headers=_auth(a_tok))
    assert r_a.status_code == 200, r_a.text
    assert r_a.json()["others"] == [], "只有自己時不該出現警示"

    r_b = client.post("/api/edit-presence", json=body, headers=_auth(b_tok))
    others = r_b.json()["others"]
    assert [o["username"] for o in others] == ["pres_a"], others
    # A 再回報一次也要看到 B（雙向）
    assert [o["username"] for o in
            client.post("/api/edit-presence", json=body, headers=_auth(a_tok)).json()["others"]] == ["pres_b"]


def test_presence_is_scoped_to_one_document(client, make_user):
    """不同單據互不干擾——否則整個系統會變成「隨時都有人在編」。"""
    a_u, a_p = make_user(username="pres_c", role="admin")
    b_u, b_p = make_user(username="pres_d", role="admin")
    client.post("/api/edit-presence", json={"doc_type": "quotation", "doc_id": "MQ-A"},
                headers=_auth(_login(client, a_u, a_p)))
    r = client.post("/api/edit-presence", json={"doc_type": "quotation", "doc_id": "MQ-B"},
                    headers=_auth(_login(client, b_u, b_p)))
    assert r.json()["others"] == [], r.json()


def test_presence_expires_without_heartbeat(client, make_user):
    """心跳停了就該消失——不能依賴「關頁面時要記得通知伺服器」。"""
    import db
    a_u, a_p = make_user(username="pres_e", role="admin")
    b_u, b_p = make_user(username="pres_f", role="admin")
    body = {"doc_type": "quotation", "doc_id": "MQ-PRES-TTL"}
    client.post("/api/edit-presence", json=body, headers=_auth(_login(client, a_u, a_p)))

    conn = db.get_db()      # 把 A 的心跳往前挪到 TTL 之外
    try:
        stale = (datetime.now() - timedelta(seconds=600)).isoformat()
        conn.execute("UPDATE edit_presence SET last_seen_at=? WHERE doc_id='MQ-PRES-TTL'", (stale,))
        conn.commit()
    finally:
        conn.close()

    r = client.post("/api/edit-presence", json=body, headers=_auth(_login(client, b_u, b_p)))
    assert r.json()["others"] == [], "心跳停掉的人還掛在警示上"


def test_presence_release(client, make_user):
    """正常離開會立刻釋放（不必等 TTL）。"""
    a_u, a_p = make_user(username="pres_g", role="admin")
    b_u, b_p = make_user(username="pres_h", role="admin")
    body = {"doc_type": "quotation", "doc_id": "MQ-PRES-REL"}
    a_tok = _login(client, a_u, a_p)
    b_tok = _login(client, b_u, b_p)
    client.post("/api/edit-presence", json=body, headers=_auth(a_tok))
    assert len(client.post("/api/edit-presence", json=body, headers=_auth(b_tok)).json()["others"]) == 1

    client.request("DELETE", "/api/edit-presence", json=body, headers=_auth(a_tok))
    assert client.post("/api/edit-presence", json=body, headers=_auth(b_tok)).json()["others"] == []


def test_completion_note_rejects_stale_save(client, make_user):
    """完工單補上樂觀鎖：B 拿舊版本存檔要被擋下，而且**內容不能被蓋掉**。"""
    import db
    u, p = make_user(username="cn_lock", role="admin", modules=["case_manage"])
    tok = _login(client, u, p)
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, sales_person, assigned_user_ids) "
            "VALUES ('MQ-CN-LOCK','已送出','測客','測專',1000,952,'{}','2026-01-01T00:00:00',"
            "'2026-01-01T00:00:00','已成案','',  '[]')")
        conn.execute(
            "INSERT INTO completion_notes (note_no, quote_no, status, data_json, created_by, "
            "created_at, updated_at, work_summary) VALUES (?,?,?,?,?,?,?,?)",
            ("CN-LOCK-001", "MQ-CN-LOCK", "草稿", "{}", "cn_lock",
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "原始內容"))
        conn.commit()
    finally:
        conn.close()

    payload = {"quote_no": "MQ-CN-LOCK", "work_summary": "B 寫的內容",
               "expected_updated_at": "2020-01-01T00:00:00"}      # 明顯過期的版本
    r = client.put("/api/completion-notes/CN-LOCK-001", json=payload, headers=_auth(tok))
    assert r.status_code == 409, f"舊版本竟然存得進去：{r.status_code} {r.text}"

    conn = db.get_db()
    try:
        row = conn.execute("SELECT work_summary FROM completion_notes WHERE note_no='CN-LOCK-001'").fetchone()
    finally:
        conn.close()
    assert row["work_summary"] == "原始內容", "409 了但內容還是被蓋掉"


def test_completion_note_saves_with_current_version(client, make_user):
    """反向控制：帶著正確版本就存得進去（否則上一題可能只是「什麼都存不了」）。"""
    import db
    u, p = make_user(username="cn_lock2", role="admin", modules=["case_manage"])
    tok = _login(client, u, p)
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, sales_person, assigned_user_ids) "
            "VALUES ('MQ-CN-LOCK2','已送出','測客','測專',1000,952,'{}','2026-01-01T00:00:00',"
            "'2026-01-01T00:00:00','已成案','','[]')")
        conn.execute(
            "INSERT INTO completion_notes (note_no, quote_no, status, data_json, created_by, "
            "created_at, updated_at, work_summary) VALUES (?,?,?,?,?,?,?,?)",
            ("CN-LOCK-002", "MQ-CN-LOCK2", "草稿", "{}", "cn_lock2",
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "原始內容"))
        conn.commit()
        current = conn.execute(
            "SELECT updated_at FROM completion_notes WHERE note_no='CN-LOCK-002'").fetchone()["updated_at"]
    finally:
        conn.close()

    r = client.put("/api/completion-notes/CN-LOCK-002",
                   json={"quote_no": "MQ-CN-LOCK2", "work_summary": "新內容",
                         "expected_updated_at": current}, headers=_auth(tok))
    assert r.status_code == 200, r.text

    conn = db.get_db()
    try:
        row = conn.execute("SELECT work_summary FROM completion_notes WHERE note_no='CN-LOCK-002'").fetchone()
    finally:
        conn.close()
    assert row["work_summary"] == "新內容"
