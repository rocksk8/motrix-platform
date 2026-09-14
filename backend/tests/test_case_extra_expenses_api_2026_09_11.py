"""案件額外支出 CRUD ＋ 送審 API（2026-09-11，改版第二段）。

規格見 `MOTRIX-ERP-QUICK.md` §5.10。重點在使用者指定的六項裡屬於後端的那幾項：
填寫人由後端帶入（不吃前端傳的值）、支出人可選可自由文字、送審走共用分層簽核、
已結案照樣可以編、送審中的金額照樣算進成本。
"""
import json


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _user_id(username):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    finally:
        conn.close()


def _make_case(quote_no="MQ-XE-001", deal_tag="已成案", sales_person="", assigned=None):
    """建案件。`assigned` 是被指派到這張案件的 user id 清單。

    ⚠️ 非 admin 一定要在 assigned 裡（或本身是該案業務）才碰得到這些端點——
    `_check_quotation_owner()` 的既有 IDOR 規則，quote_no 可列舉所以不能省。
    實務上這代表**現場花錢的工程師必須先被指派到案件**才填得了額外支出。
    """
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, sales_person, assigned_user_ids) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測客", "測專", 100000, 95238,
             json.dumps({"dealTag": deal_tag}, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", deal_tag, sales_person,
             json.dumps(assigned or [])),
        )
        conn.commit()
    finally:
        conn.close()


def _set_empty_approval_flow():
    """把統一簽核流程設成「沒有任何層」。

    ⚠️ 只把 tiers 設成空陣列**不夠**：`setting_to_active_tiers()` 會自動在最前面
    插入一層「申請人部門主管自動簽核」（`includeSubmitterManagerTier` 沒設定時
    視為 True，見該函式 docstring），申請人沒有部門歸屬時就會被擋下
    （「申請人尚未歸屬任何部門」）。真正的「完全沒有簽核層」要同時關掉它。

    順帶一提，這代表**預設情況下每一種單據都要求申請人有部門歸屬**才送得出去
    ——目前正式機 12 個帳號都有部門，所以碰不到，但新帳號忘了設部門就會卡。"""
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
            ("unified_approval_flow",
             json.dumps({"tiers": [], "includeSubmitterManagerTier": False}),
             "2026-01-01T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()


def _base(no="MQ-XE-001"):
    return f"/api/quotations/{no}/extra-expenses"


def _payload(**over):
    d = {"category": "差旅", "description": "北上出差", "qty": 2, "unit": "天",
         "unitCost": 1500, "expenseDate": "2026-08-05"}
    d.update(over)
    return d


# ── 建立 ────────────────────────────────────────────────────────────────────

def test_create_fills_in_author_from_session_not_client(client, make_user):
    """填寫人一律由後端帶入。

    這是整個改版的起點之一：舊的精算表單把填寫人交給前端填，而前端取的是一個
    不存在的 session 路徑（`this.session?.user?.display_name`），結果實測 7 筆
    既有資料 0 筆有值。所以現在前端傳什麼都不採用。
    """
    username, password = make_user(username="author1", role="admin")
    token = _login(client, username, password)
    _make_case()

    r = client.post(_base(), headers=_auth(token), json=_payload())
    assert r.status_code == 201, r.text

    items = client.get(_base(), headers=_auth(token)).json()["items"]
    assert len(items) == 1
    assert items[0]["createdBy"] == username
    assert items[0]["createdByName"] == username
    assert items[0]["createdByInferred"] is False, "現場填的不是推定值"
    assert items[0]["createdAt"] and items[0]["updatedAt"], "填寫日期與更動日期都要有"


def test_total_cost_is_computed_server_side(client, make_user):
    """小計後端算，不吃前端傳的值。"""
    username, password = make_user(username="author2", role="admin")
    token = _login(client, username, password)
    _make_case()

    r = client.post(_base(), headers=_auth(token),
                    json=_payload(qty=3, unitCost=250, totalCost=999999))
    assert r.status_code == 201, r.text
    assert r.json()["totalCost"] == 750


def test_payer_can_be_picked_or_free_text(client, make_user):
    """支出人「可選可自由文字」：從清單選時兩個欄位都有，自由文字時只有名字。"""
    username, password = make_user(username="author3", role="admin")
    other, _ = make_user(username="spender", role="engineer")
    token = _login(client, username, password)
    _make_case()

    client.post(_base(), headers=_auth(token),
                json=_payload(description="選清單", payerUsername=other, payerName=other))
    client.post(_base(), headers=_auth(token),
                json=_payload(description="自由文字", payerName="王小明（外包）"))

    items = client.get(_base(), headers=_auth(token)).json()["items"]
    picked = next(i for i in items if i["description"] == "選清單")
    freetext = next(i for i in items if i["description"] == "自由文字")
    assert picked["payerUsername"] == other and picked["payerName"] == other
    assert freetext["payerUsername"] == "" and freetext["payerName"] == "王小明（外包）"


def test_description_is_required(client, make_user):
    username, password = make_user(username="author4", role="admin")
    token = _login(client, username, password)
    _make_case()
    r = client.post(_base(), headers=_auth(token), json=_payload(description="  "))
    assert r.status_code == 400 and "品項說明" in r.json()["detail"]


def test_unknown_category_rejected(client, make_user):
    username, password = make_user(username="author5", role="admin")
    token = _login(client, username, password)
    _make_case()
    r = client.post(_base(), headers=_auth(token), json=_payload(category="亂填"))
    assert r.status_code == 400 and "類別" in r.json()["detail"]


def test_closed_case_can_still_be_edited(client, make_user):
    """使用者指定第 5 點：已結案也可以新增／編輯額外支出。"""
    username, password = make_user(username="author6", role="admin")
    token = _login(client, username, password)
    _make_case("MQ-XE-CLOSED", deal_tag="已結案")

    r = client.post(_base("MQ-XE-CLOSED"), headers=_auth(token), json=_payload())
    assert r.status_code == 201, "已結案案件不該被擋下"


# ── 編輯／刪除 ──────────────────────────────────────────────────────────────

def test_update_bumps_updated_at_and_updater(client, make_user):
    username, password = make_user(username="author7", role="admin")
    token = _login(client, username, password)
    _make_case()
    exp_id = client.post(_base(), headers=_auth(token), json=_payload()).json()["id"]

    r = client.patch(f"{_base()}/{exp_id}", headers=_auth(token),
                     json=_payload(description="改過的說明", qty=1, unitCost=800))
    assert r.status_code == 200, r.text

    it = client.get(_base(), headers=_auth(token)).json()["items"][0]
    assert it["description"] == "改過的說明"
    assert it["totalCost"] == 800
    assert it["updatedByName"] == username


def test_other_user_cannot_edit_someone_elses_entry(client, make_user):
    """別人填的支出不該被隨手改掉——非 admin 只能改自己的。"""
    owner, owner_pw = make_user(username="owner_e", role="engineer")
    other, other_pw = make_user(username="other_e", role="engineer")
    _make_case(assigned=[_user_id(owner), _user_id(other)])
    t1 = _login(client, owner, owner_pw)
    exp_id = client.post(_base(), headers=_auth(t1), json=_payload()).json()["id"]

    t2 = _login(client, other, other_pw)
    r = client.patch(f"{_base()}/{exp_id}", headers=_auth(t2), json=_payload(description="亂改"))
    assert r.status_code == 403, r.text


def test_admin_can_edit_others_entry(client, make_user):
    owner, owner_pw = make_user(username="owner_f", role="engineer")
    admin, admin_pw = make_user(username="admin_f", role="admin")
    _make_case(assigned=[_user_id(owner)])
    t1 = _login(client, owner, owner_pw)
    exp_id = client.post(_base(), headers=_auth(t1), json=_payload()).json()["id"]

    t2 = _login(client, admin, admin_pw)
    r = client.patch(f"{_base()}/{exp_id}", headers=_auth(t2), json=_payload(description="管理員修正"))
    assert r.status_code == 200, r.text


def test_approved_entry_cannot_be_edited_or_deleted(client, make_user, seed_extra_expense):
    """已核准的金額已經進了成本與報表，不該被單方面改掉或刪掉。"""
    username, password = make_user(username="author8", role="superadmin")
    token = _login(client, username, password)
    _make_case()
    exp_id = seed_extra_expense("MQ-XE-001", total_cost=500, description="已核准的",
                                status="已核准")

    assert client.patch(f"{_base()}/{exp_id}", headers=_auth(token),
                        json=_payload()).status_code == 409
    assert client.delete(f"{_base()}/{exp_id}", headers=_auth(token)).status_code == 409


# ── 送審 ────────────────────────────────────────────────────────────────────

def test_submit_without_any_tier_auto_approves(client, make_user):
    """沒有設定任何簽核層時直接視為核准。

    這個專案的簽核設定是選配的；若因為沒設定就把單據永久卡在「待審核」，
    等於新功能一上線就把所有人擋住。
    """
    username, password = make_user(username="author9", role="admin")
    token = _login(client, username, password)
    _make_case()
    _set_empty_approval_flow()
    exp_id = client.post(_base(), headers=_auth(token), json=_payload()).json()["id"]

    r = client.post(f"{_base()}/{exp_id}/submit", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "已核准"
    assert r.json()["autoApproved"] is True


def test_pending_amount_still_counts_toward_total(client, make_user, seed_extra_expense):
    """送審中的金額**照樣算進總額**，但另外用 totalPending 標出來。

    使用者指定的規則：不算進去會讓當月已經花掉的錢在報表上消失（2026-09-09 修過
    的那一類問題）；不標示則看報表的人不知道數字還可能被駁回而改變。
    """
    username, password = make_user(username="author10", role="admin")
    token = _login(client, username, password)
    _make_case()
    seed_extra_expense("MQ-XE-001", total_cost=1000, description="已核准", status="已核准")
    seed_extra_expense("MQ-XE-001", total_cost=400, description="送審中", status="待審核")

    body = client.get(_base(), headers=_auth(token)).json()
    assert body["totalAmount"] == 1400, "送審中的也要算進總額"
    assert body["totalPending"] == 400, "但要單獨標出還沒核准的部分"
    assert body["pendingCount"] == 1


def test_reject_returns_to_editable_state(client, make_user, seed_extra_expense):
    """駁回不是刪除——回到可編輯狀態，改完可以再送一次。"""
    username, password = make_user(username="author11", role="superadmin")
    token = _login(client, username, password)
    _make_case()
    exp_id = client.post(_base(), headers=_auth(token), json=_payload()).json()["id"]

    # 手動塞一個單層簽核（簽核人是自己以外的人會擋自審，這裡用 superadmin 自己送、
    # 再由同一人核准會被 check_no_tier_self_approval 擋，所以只驗駁回路徑）
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "UPDATE case_extra_expenses SET status='待審核', approval_json=? WHERE id=?",
            (json.dumps({"requestedBy": "someone_else", "tiers": [
                {"approvers": [{"username": username, "display_name": username}]}],
                "currentTier": 0}, ensure_ascii=False), exp_id),
        )
        conn.commit()
    finally:
        conn.close()

    r = client.post(f"{_base()}/{exp_id}/reject", headers=_auth(token),
                    json={"reason": "金額要再確認"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "已駁回"

    it = next(i for i in client.get(_base(), headers=_auth(token)).json()["items"]
              if i["id"] == exp_id)
    assert it["approval"]["rejectReason"] == "金額要再確認"

    # 已駁回可以再編輯
    assert client.patch(f"{_base()}/{exp_id}", headers=_auth(token),
                        json=_payload(description="改好了")).status_code == 200


def test_requires_auth(client):
    assert client.get(_base()).status_code in (401, 403)
    assert client.post(_base(), json=_payload()).status_code in (401, 403)


def test_unknown_quote_returns_404(client, make_user):
    username, password = make_user(username="author12", role="admin")
    token = _login(client, username, password)
    assert client.get(_base("MQ-NOPE-999"), headers=_auth(token)).status_code == 404


# ── 統一簽核佇列 ────────────────────────────────────────────────────────────

def test_submitted_expense_appears_in_approval_queue(client, make_user, seed_extra_expense):
    """送審中的額外支出要出現在統一簽核佇列。

    不進佇列的話，送審之後簽核人只會收到站內通知，沒有任何地方列得出「該我簽的」
    ——那正是「送審了但沒人知道要簽」的典型來源。
    """
    approver, approver_pw = make_user(username="xq_appr", role="superadmin")
    token = _login(client, approver, approver_pw)
    _make_case("MQ-XQ-001")

    import json as _json
    exp_id = seed_extra_expense("MQ-XQ-001", total_cost=2500, description="佇列測試用",
                                status="待審核")
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "UPDATE case_extra_expenses SET approval_json=? WHERE id=?",
            (_json.dumps({"requestedBy": "someone", "requestedByDisplay": "某人",
                          "requestedAt": "2026-09-11T10:00:00",
                          "tiers": [{"order": 0, "approvers": [
                              {"username": approver, "display_name": approver}]}],
                          "currentTier": 0}, ensure_ascii=False), exp_id),
        )
        conn.commit()
    finally:
        conn.close()

    q = client.get("/api/approval-queue", headers=_auth(token))
    assert q.status_code == 200, q.text
    items = [it for g in q.json()["queue"] for it in g["items"] if it["type"] == "extra_expense"]
    assert len(items) == 1, f"額外支出應該出現在佇列，實際 {items}"
    it = items[0]
    assert it["extraExpenseId"] == exp_id
    assert it["linkedQuoteNo"] == "MQ-XQ-001"
    assert it["total"] == 2500
    assert it["projectName"] == "佇列測試用"
    assert it["tierCount"] == 1

    # 計數端點也要算進去，否則側欄徽章不會亮
    c = client.get("/api/approval-queue/count", headers=_auth(token))
    assert c.json()["count"] >= 1


def test_draft_expense_not_in_queue(client, make_user, seed_extra_expense):
    """草稿不該出現在佇列——還沒送審的東西不是別人要簽的。"""
    approver, approver_pw = make_user(username="xq_appr2", role="superadmin")
    token = _login(client, approver, approver_pw)
    _make_case("MQ-XQ-002")
    seed_extra_expense("MQ-XQ-002", total_cost=100, description="草稿", status="草稿")

    q = client.get("/api/approval-queue", headers=_auth(token))
    items = [it for g in q.json()["queue"] for it in g["items"] if it["type"] == "extra_expense"]
    assert items == []
