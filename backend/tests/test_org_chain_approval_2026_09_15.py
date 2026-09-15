"""組織流程簽核鏈＋同一人連任多層一次簽完（2026-09-15 使用者交辦）。

使用者原話：「當超級管理員解鎖報價單編輯，簽核要按照組織流程簽核，高晟耀報價單
編輯(解鎖)，目前是要我同樣最高管理員簽核，實際要組織流程高晟耀他自己簽核兩次，
我這邊只做知會，另外修復一個問題，當某位主管同時為兩層以上簽核人，只要跳通知做
確認，可直接簽核兩次以上，避免重複簽核兩次的狀態」。

實際情境（正式機組織架構）：`corbin` 同時是「策略開發整合中心」部門主管與
「總經理辦公室」處主管，他自己送的單在舊規則下會一路往上跳過自己、最後硬抓另一位
超級管理員（`jeff`）當簽核人——他在組織上的那兩關完全沒有留下任何紀錄。

這裡釘住四件事：
1. 一般員工的簽核鏈**不變**（只有部門主管一層）——這是回歸基準，少了它，
   下面那些「多一層」的斷言可以靠「無條件加兩層」變綠。
2. 申請人身兼部門主管 → 兩層（本人 + 處主管），本人那層標 selfApproval。
3. 申請人身兼部門主管＋處主管 → 兩層都是本人，**不再指派其他超級管理員**，
   改成送出時知會在職的最高管理者（notifications 表要真的有那一列）。
4. 同一人連任多層時帶 cascade=true 一次簽完，且 cascade **不得跨過別人的層**。

⚠️ 斷言刻意挑「成功後才會被寫入的下游欄位」：簽核結果看 DB 裡的 status/
currentTier/approvedAt，不是看自己送進去的 request body。
"""
import json

import pytest


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _org(dept_manager=None, div_manager=None, dept_name="測試部", div_name="測試處"):
    """建一個處＋部門，回傳 (division_id, department_id)。"""
    from db import get_db
    conn = get_db()
    try:
        div_id = conn.execute(
            "INSERT INTO divisions (name, sort_order, created_at, manager_user_id) VALUES (?,?,?,?)",
            (div_name, 0, "2026-01-01T00:00:00", div_manager)).lastrowid
        dept_id = conn.execute(
            "INSERT INTO departments (division_id, name, sort_order, manager_user_id, created_at) "
            "VALUES (?,?,?,?,?)",
            (div_id, dept_name, 0, dept_manager, "2026-01-01T00:00:00")).lastrowid
        conn.commit()
        return div_id, dept_id
    finally:
        conn.close()


def _uid(username):
    from db import get_db
    conn = get_db()
    try:
        return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    finally:
        conn.close()


def _set_dept(username, dept_id):
    from db import get_db
    conn = get_db()
    try:
        conn.execute("UPDATE users SET department_id=? WHERE username=?", (dept_id, username))
        conn.commit()
    finally:
        conn.close()


def _unified_flow(tiers=None, include_builtin=True):
    """把統一簽核流程設成指定內容（預設只有系統內建那一層）。"""
    from db import get_db
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO system_settings (key, value_json, updated_at) VALUES (?,?,?)",
            ("unified_approval_flow",
             json.dumps({"tiers": tiers or [], "includeSubmitterManagerTier": include_builtin},
                        ensure_ascii=False),
             "2026-09-15T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _tiers_for(username):
    """直接呼叫共用的送審展開邏輯（不經 HTTP），拿到該人送審時會產生的簽核層。"""
    from db import get_db
    from helpers import setting_to_active_tiers, resolve_active_flow_setting
    conn = get_db()
    try:
        return setting_to_active_tiers(resolve_active_flow_setting("quotation"), conn, username)
    finally:
        conn.close()


def _names(tiers):
    return [[a["username"] for a in t["approvers"]] for t in tiers]


# ── ① 一般員工：鏈不變（回歸基準）────────────────────────────────────────────

def test_plain_employee_chain_is_single_manager_tier(client, make_user):
    """部門主管不是自己 → 就只有那一層，跟 2026-09-15 之前完全一樣。"""
    staff, _ = make_user(username="oc_staff", role="sales")
    mgr, _ = make_user(username="oc_mgr", role="admin")
    boss, _ = make_user(username="oc_boss", role="superadmin")
    _, dept = _org(dept_manager=_uid(mgr), div_manager=_uid(boss))
    _set_dept(staff, dept)
    _unified_flow()

    assert _names(_tiers_for(staff)) == [[mgr]], "一般員工的簽核鏈被改動了"


# ── ② 申請人身兼部門主管：本人簽自己那層 ＋ 再加一層處主管 ──────────────────

def test_department_manager_signs_own_tier_then_division_manager(client, make_user):
    me, _ = make_user(username="oc_deptmgr", role="admin")
    boss, _ = make_user(username="oc_divmgr", role="superadmin")
    _, dept = _org(dept_manager=_uid(me), div_manager=_uid(boss))
    _set_dept(me, dept)
    _unified_flow()

    tiers = _tiers_for(me)
    assert _names(tiers) == [[me], [boss]], (
        "申請人身兼部門主管時應該是『本人 → 處主管』兩層，"
        f"實際為 {_names(tiers)}（舊行為是直接跳過本人、只留處主管一層）")
    assert tiers[0]["approvers"][0]["selfApproval"] is True
    assert tiers[1]["approvers"][0].get("selfApproval") is False


# ── ③ 身兼部門＋處主管：自己簽兩次，最高管理者只收知會 ──────────────────────

def test_division_manager_self_signs_twice_and_superadmin_only_gets_notice(client, make_user):
    """使用者要的那件事本身：高晟耀自己簽兩次、最高管理者只做知會。"""
    from db import get_db

    me, pw = make_user(username="oc_top", role="superadmin")
    other_sa, _ = make_user(username="oc_other_sa", role="superadmin")
    _, dept = _org(dept_manager=_uid(me), div_manager=_uid(me))
    _set_dept(me, dept)
    _unified_flow()

    tiers = _tiers_for(me)
    assert _names(tiers) == [[me], [me]], (
        f"應該是本人連簽兩層，實際為 {_names(tiers)}"
        "（舊行為：抓另一位超級管理員來簽）")
    assert other_sa not in [u for t in _names(tiers) for u in t], (
        "最高管理者不該再出現在簽核鏈裡——使用者說『我這邊只做知會』")

    # 走真正的 HTTP 送審路徑，確認知會通知有真的寫進去
    headers = _login(client, me, pw)
    r = client.post("/api/quotations", headers=headers, json={
        "status": "待審核",
        "data": {"customerName": "知會客戶", "projectName": "知會案",
                 "items": [{"description": "品項"}],
                 "approval": {"requestedBy": me, "requestedByDisplay": me,
                              "requestedAt": "2026-09-15T02:00:00"}},
    })
    assert r.status_code == 201, r.text
    quote_no = r.json()["quote_no"]

    conn = get_db()
    try:
        notices = conn.execute(
            "SELECT username, message FROM notifications WHERE type='approval_notice' AND ref_id=?",
            (quote_no,)).fetchall()
        rows = {n["username"] for n in notices}
        appr = json.loads(conn.execute(
            "SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)
        ).fetchone()["data_json"])["approval"]
    finally:
        conn.close()

    # 收件者是「其他在職的超級管理員」，測試環境還有系統預設的 demo 帳號，
    # 所以比對的是「有通知到另一位、且沒有通知申請人自己」這兩件事
    assert other_sa in rows, f"其他最高管理者沒有收到知會通知，實際 {rows}"
    assert me not in rows, "申請人自己不該收到知會通知"
    assert _names(appr["tiers"]) == [[me], [me]], (
        "存進 data_json 的簽核層被 _exclude_requester() 剔掉了——"
        "組織自簽層不可以被剔除，否則整關消失")


def test_no_notice_when_someone_else_is_in_the_chain(client, make_user):
    """正向控制：鏈裡只要有別人，就不該發知會（否則上一題可以靠『一律發』變綠）。"""
    from db import get_db

    me, pw = make_user(username="oc_dm2", role="admin")
    boss, _ = make_user(username="oc_dv2", role="superadmin")
    _, dept = _org(dept_manager=_uid(me), div_manager=_uid(boss))
    _set_dept(me, dept)
    _unified_flow()
    headers = _login(client, me, pw)

    r = client.post("/api/quotations", headers=headers, json={
        "status": "待審核",
        "data": {"customerName": "一般客戶", "projectName": "一般案",
                 "items": [{"description": "品項"}],
                 "approval": {"requestedBy": me, "requestedByDisplay": me,
                              "requestedAt": "2026-09-15T02:00:00"}},
    })
    assert r.status_code == 201, r.text
    conn = get_db()
    try:
        n = conn.execute(
            "SELECT COUNT(*) c FROM notifications WHERE type='approval_notice' AND ref_id=?",
            (r.json()["quote_no"],)).fetchone()["c"]
    finally:
        conn.close()
    assert n == 0, "簽核鏈裡還有別人要簽，不該發知會通知"


# ── ④ 解鎖編輯後的重新簽核走組織流程 ───────────────────────────────────────

def test_unlock_edit_rebuilds_org_chain_for_the_editor(client, make_user):
    """使用者回報的入口：superadmin 解鎖改版後，簽核層要照組織流程重建。"""
    from db import get_db

    me, pw = make_user(username="oc_unlock", role="superadmin")
    make_user(username="oc_unlock_sa2", role="superadmin")
    _, dept = _org(dept_manager=_uid(me), div_manager=_uid(me))
    _set_dept(me, dept)
    _unified_flow()
    headers = _login(client, me, pw)

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, "
            "data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            ("MQ-202609-950", "已送出", "解鎖客戶", "解鎖案", 1000,
             json.dumps({"customerName": "解鎖客戶", "projectName": "解鎖案",
                         "items": [{"description": "品項"}]}, ensure_ascii=False),
             "2026-09-01", "2026-09-01"))
        conn.commit()
    finally:
        conn.close()

    r = client.put("/api/quotations/MQ-202609-950", headers=headers, json={
        "status": "待審核",
        "data": {"customerName": "解鎖客戶", "projectName": "解鎖案",
                 "items": [{"description": "品項（改）"}], "_isUnlockEdit": True},
    })
    assert r.status_code == 200, r.text

    conn = get_db()
    try:
        d = json.loads(conn.execute(
            "SELECT data_json FROM quotations WHERE quote_no=?", ("MQ-202609-950",)
        ).fetchone()["data_json"])
    finally:
        conn.close()
    assert _names(d["approval"]["tiers"]) == [[me], [me]], (
        "解鎖改版後的簽核層沒有照組織流程重建"
        f"（實際 {_names(d['approval']['tiers'])}）")


# ── ⑤ 同一人連任多層：一次簽完 ─────────────────────────────────────────────

def _seed_pending_quote(quote_no, tiers, requested_by="oc_requester"):
    from db import get_db
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, "
            "data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (quote_no, "待審核", "客戶", "專案", 1000,
             json.dumps({"customerName": "客戶", "projectName": "專案",
                         "items": [{"description": "品項"}],
                         "approval": {"requestedBy": requested_by,
                                      "requestedByDisplay": requested_by,
                                      "requestedAt": "2026-09-15T01:00:00",
                                      "currentTier": 0, "tiers": tiers}},
                        ensure_ascii=False),
             "2026-09-15", "2026-09-15"))
        conn.commit()
    finally:
        conn.close()


def _approval_of(quote_no):
    from db import get_db
    conn = get_db()
    try:
        row = conn.execute("SELECT status, data_json FROM quotations WHERE quote_no=?",
                           (quote_no,)).fetchone()
        return row["status"], json.loads(row["data_json"])["approval"]
    finally:
        conn.close()


def test_cascade_signs_consecutive_self_tiers_in_one_call(client, make_user):
    me, pw = make_user(username="oc_two_tiers", role="admin")
    headers = _login(client, me, pw)
    tiers = [{"order": 0, "approvers": [{"username": me, "displayName": me, "status": "pending"}]},
             {"order": 1, "approvers": [{"username": me, "displayName": me, "status": "pending"}]}]
    _seed_pending_quote("MQ-202609-951", tiers)

    r = client.post("/api/quotations/MQ-202609-951/approve", headers=headers,
                    json={"approvedByDisplay": me, "cascade": True})
    assert r.status_code == 200, r.text
    assert r.json()["allDone"] is True
    assert r.json()["signedTiers"] == [1, 2]

    status, appr = _approval_of("MQ-202609-951")
    assert status == "已送出", f"兩層都簽完了，狀態應該是已送出，實際 {status}"
    assert all(a["status"] == "approved" for t in appr["tiers"] for a in t["approvers"])
    assert appr["currentTier"] == 2


def test_without_cascade_flag_only_one_tier_is_signed(client, make_user):
    """正向控制：沒帶 cascade 就維持原本「一次一層」的行為，不會擅自替人多簽。"""
    me, pw = make_user(username="oc_two_tiers_b", role="admin")
    headers = _login(client, me, pw)
    tiers = [{"order": 0, "approvers": [{"username": me, "displayName": me, "status": "pending"}]},
             {"order": 1, "approvers": [{"username": me, "displayName": me, "status": "pending"}]}]
    _seed_pending_quote("MQ-202609-952", tiers)

    r = client.post("/api/quotations/MQ-202609-952/approve", headers=headers,
                    json={"approvedByDisplay": me})
    assert r.status_code == 200, r.text
    assert r.json()["allDone"] is False

    status, appr = _approval_of("MQ-202609-952")
    assert appr["currentTier"] == 1
    assert appr["tiers"][1]["approvers"][0]["status"] != "approved"


def test_cascade_stops_at_a_tier_that_needs_someone_else(client, make_user):
    """**安全邊界**：中間夾著別人的層時，cascade 只能停在他前面。
    跨過去就等於替別人簽核。"""
    me, pw = make_user(username="oc_casc_me", role="admin")
    other, _ = make_user(username="oc_casc_other", role="admin")
    headers = _login(client, me, pw)
    tiers = [{"order": 0, "approvers": [{"username": me, "displayName": me, "status": "pending"}]},
             {"order": 1, "approvers": [{"username": other, "displayName": other, "status": "pending"}]},
             {"order": 2, "approvers": [{"username": me, "displayName": me, "status": "pending"}]}]
    _seed_pending_quote("MQ-202609-953", tiers)

    r = client.post("/api/quotations/MQ-202609-953/approve", headers=headers,
                    json={"approvedByDisplay": me, "cascade": True})
    assert r.status_code == 200, r.text
    assert r.json()["signedTiers"] == [1], "cascade 跨過了別人要簽的那一層"

    status, appr = _approval_of("MQ-202609-953")
    assert appr["currentTier"] == 1
    assert appr["tiers"][1]["approvers"][0]["status"] != "approved"
    assert appr["tiers"][2]["approvers"][0]["status"] != "approved"


def test_cascade_does_not_skip_a_tier_with_a_second_pending_approver(client, make_user):
    """同層有兩位簽核人、其中一位不是我 → 那一層不算『簽下去就完成』，不併簽。"""
    me, pw = make_user(username="oc_casc_me2", role="admin")
    other, _ = make_user(username="oc_casc_other2", role="admin")
    headers = _login(client, me, pw)
    tiers = [{"order": 0, "approvers": [{"username": me, "displayName": me, "status": "pending"}]},
             {"order": 1, "approvers": [{"username": me, "displayName": me, "status": "pending"},
                                        {"username": other, "displayName": other, "status": "pending"}]}]
    _seed_pending_quote("MQ-202609-954", tiers)

    r = client.post("/api/quotations/MQ-202609-954/approve", headers=headers,
                    json={"approvedByDisplay": me, "cascade": True})
    assert r.status_code == 200, r.text
    assert r.json()["signedTiers"] == [1]
    _, appr = _approval_of("MQ-202609-954")
    assert appr["tiers"][1]["approvers"][0]["status"] != "approved"


def test_requester_can_sign_own_org_tier_end_to_end(client, make_user):
    """把①～⑤串起來：身兼兩職的人送審 → 一次確認簽完兩層 → 狀態變已送出。
    這條路在 2026-09-15 之前是走不通的（申請人會被 _exclude_requester() 剔掉）。"""
    me, pw = make_user(username="oc_e2e", role="superadmin")
    make_user(username="oc_e2e_sa2", role="superadmin")
    _, dept = _org(dept_manager=_uid(me), div_manager=_uid(me))
    _set_dept(me, dept)
    _unified_flow()
    headers = _login(client, me, pw)

    r = client.post("/api/quotations", headers=headers, json={
        "status": "待審核",
        "data": {"customerName": "端到端", "projectName": "端到端案",
                 "items": [{"description": "品項"}],
                 "approval": {"requestedBy": me, "requestedByDisplay": me,
                              "requestedAt": "2026-09-15T03:00:00"}},
    })
    assert r.status_code == 201, r.text
    quote_no = r.json()["quote_no"]

    a = client.post(f"/api/quotations/{quote_no}/approve", headers=headers,
                    json={"approvedByDisplay": me, "cascade": True})
    assert a.status_code == 200, a.text
    status, appr = _approval_of(quote_no)
    assert status == "已送出", f"自簽兩層後應該完成，實際 {status}"
    assert appr["approvedBy"] == me
