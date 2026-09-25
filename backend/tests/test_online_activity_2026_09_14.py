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
    # 2026-09-15：模組名從「客戶管理」改成「客戶」，因為它現在會被組進一整句
    # （「查看客戶清單」）。觀測點跟著改成那句話——它才是畫面上真正顯示的東西。
    summaries = {i["path"]: i["summary"] for i in body["items"]}
    assert summaries.get("/api/customers") == "查看客戶清單", summaries
    assert summaries.get("/api/parts") == "查看料號清單", summaries


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
    from helpers.system_checks import _prune_request_log

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


# ── 人話 + 篩選每個使用者（2026-09-15 使用者要求）─────────────────────────────
#
# 「在更直覺的語言，在線時數統計的操作軌跡，要能篩選每個使用者」。
# 三件事要釘住：①每列是一句人話而不是路徑＋狀態碼；②頁面自己打的請求不進來；
# ③收斂「一次點擊的連鎖請求」時，不能把真正的動作藏進去。

def test_trail_summary_is_a_human_sentence(client, make_user):
    """每一列要能直接讀出「誰做了什麼、結果如何」。"""
    su, sp = make_user(username="tr_lang", role="superadmin")
    tok = _login(client, su, sp)
    client.get("/api/customers", headers=_auth(tok))

    body = client.get("/api/user-activity/trail?user=tr_lang", headers=_auth(tok)).json()
    rows = [i for i in body["items"] if i["path"] == "/api/customers"]
    assert rows, body["items"]
    row = rows[0]
    assert row["summary"] == "查看客戶清單", row
    assert row["kindLabel"] == "檢視", row
    assert row["resultLabel"] == "成功", row
    assert row["ok"] is True, row


def test_trail_blocked_attempt_says_why_in_words(client, make_user):
    """被擋下來的那一列要寫「沒有權限」，而不是丟一個 403 給人自己查。"""
    su, sp = make_user(username="tr_words_su", role="superadmin")
    u, p = make_user(username="tr_words", role="viewer", modules=["dashboard"])
    assert client.get("/api/parts", headers=_auth(_login(client, u, p))).status_code == 403

    body = client.get("/api/user-activity/trail?user=tr_words",
                      headers=_auth(_login(client, su, sp))).json()
    rows = [i for i in body["items"] if i["path"] == "/api/parts"]
    assert rows, body["items"]
    assert rows[0]["resultLabel"] == "沒有權限（被擋下）", rows[0]
    assert rows[0]["ok"] is False, rows[0]
    assert rows[0]["kindLabel"] == "檢視", rows[0]


def test_trail_skips_requests_the_page_fires_by_itself(client, make_user):
    """心跳、紅點、下拉選單資料、欄位偏好都是頁面自己打的，不是人做的動作。

    斷言裡刻意包含一筆**應該要留下**的請求：只檢查「雜訊不在」的話，整張軌跡
    是空的（例如記錄功能整個壞掉）也會過。
    """
    su, sp = make_user(username="tr_auto", role="superadmin")
    tok = _login(client, su, sp)

    client.get("/api/customers", headers=_auth(tok))                      # 人做的
    client.post("/api/edit-presence", json={"doc_type": "quotation", "doc_id": "MQ-AUTO-1"},
                headers=_auth(tok))                                       # 同時編輯心跳
    client.get("/api/approval-queue/count", headers=_auth(tok))           # 側欄紅點
    client.get("/api/users/selectable", headers=_auth(tok))               # 下拉選單資料
    client.get("/api/list-prefs/quotations", headers=_auth(tok))          # 欄位偏好

    body = client.get("/api/user-activity/trail?user=tr_auto", headers=_auth(tok)).json()
    paths = [i["path"] for i in body["items"]]
    assert "/api/customers" in paths, paths
    noisy = [p for p in paths
             if p.startswith(("/api/edit-presence", "/api/approval-queue/count",
                              "/api/list-prefs")) or p.endswith("/selectable")]
    assert not noisy, f"頁面自動發的請求被記進軌跡：{noisy}"


def test_trail_collapses_one_click_fanout_into_one_row(client, make_user):
    """開一張案件會連帶撈 base + 財務彙總 + 材料採購 + 額外支出——那是一次點擊。"""
    su, sp = make_user(username="tr_fanout", role="superadmin")
    tok = _login(client, su, sp)
    q = "MQ-209901-001"        # 單號不存在也沒差：軌跡記的是「誰對誰做了什麼」
    for suffix in ("", "/finance-summary", "/material-orders", "/extra-expenses"):
        client.get(f"/api/quotations/{q}{suffix}", headers=_auth(tok))

    items = client.get("/api/user-activity/trail?user=tr_fanout", headers=_auth(tok)).json()["items"]
    opened = [i for i in items if i["summary"] == f"開啟報價單／案件 {q}"]
    assert len(opened) == 1, [i["summary"] for i in items]


def test_trail_never_hides_a_real_action_inside_the_open_record_row():
    """收斂只吃「開頁順手撈的子資源」白名單；動作與敏感資源一律自己一列。

    直接測 `trail.py` 的規則：這條規則漏掉一項就會把事情藏起來（把「看了某人的
    身分證影像」併進「開啟外包人員 #3」），所以逐項釘住，不繞 HTTP。
    """
    import trail

    assert trail.collapse_group("GET", "/api/quotations/MQ-202607-047") is not None
    assert trail.collapse_group("GET", "/api/quotations/MQ-202607-047/finance-summary") is not None

    for method, path in [
        ("GET", "/api/contractors/3/id-card"),              # 身分證影像
        ("GET", "/api/vendor-contractors/3/passbook"),      # 存摺影像
        ("GET", "/api/completion-notes/12/pdf-download"),   # 下載
        ("POST", "/api/quotations/MQ-202607-047/approve"),  # 簽核
        ("DELETE", "/api/dev-logs/503"),                    # 刪除
    ]:
        assert trail.collapse_group(method, path) is None, path

    assert trail.describe("GET", "/api/contractors/3/id-card")["summary"] \
        == "查看外包人員 #3 的身分證影像"
    assert trail.describe("GET", "/api/completion-notes/12/pdf-download")["kind"] == "export"
    assert trail.describe("POST", "/api/users/9/unlock-password")["summary"] == "解鎖使用者 #9 的密碼"


def test_trail_filter_shows_only_the_chosen_member(client, make_user):
    """篩選某個人時，只能看到那個人的紀錄（全部成員時兩個人都要在）。"""
    a_u, a_p = make_user(username="flt_a", role="admin")
    b_u, b_p = make_user(username="flt_b", role="admin")
    su, sp = make_user(username="flt_su", role="superadmin")
    client.get("/api/customers", headers=_auth(_login(client, a_u, a_p)))
    client.get("/api/parts", headers=_auth(_login(client, b_u, b_p)))
    tok = _login(client, su, sp)

    only_a = client.get("/api/user-activity/trail?user=flt_a", headers=_auth(tok)).json()["items"]
    assert only_a, "篩選後不該是空的"
    assert {i["username"] for i in only_a} == {"flt_a"}, [i["username"] for i in only_a]

    everyone = {i["username"] for i in
                client.get("/api/user-activity/trail", headers=_auth(tok)).json()["items"]}
    assert {"flt_a", "flt_b"} <= everyone, everyone


def test_member_list_covers_everyone_not_just_people_with_hours(client, make_user):
    """下拉選單要能選到「這段期間沒有時數」的人——那常常正是想查的那個人。"""
    su, sp = make_user(username="mem_super", role="superadmin")
    make_user(username="mem_quiet", role="sales")        # 建好就沒再動過
    tok = _login(client, su, sp)

    body = client.get("/api/user-activity", headers=_auth(tok)).json()
    with_hours = {i["username"] for i in body["items"]}
    members = {m["username"] for m in body["members"]}
    assert "mem_quiet" not in with_hours, "這個帳號本來就不該有活躍時數"
    assert "mem_quiet" in members, members
    assert "mem_super" in members, members


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
