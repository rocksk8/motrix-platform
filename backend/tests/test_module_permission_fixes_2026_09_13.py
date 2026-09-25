"""模組權限稽核修正的行為測試（2026-09-13）。

全部是「畫面上看得到、API 卻不同意」或反過來的落差，細節見
`MODULE-AUDIT-2026-09-13.md`。分成八段：

1. **每案 IDOR**：`quote_no` 可列舉（MQ-YYYYMM-NNN），一批端點先前只要求登入，
   任何已登入帳號都能讀、甚至**覆寫**別人案件的成本精算。
2. **`reports`／`finance` 模組形同虛設**：目錄勾得到、側欄會顯示營運報表，但報表
   端點只認 `admin+` → 勾了進去整頁 403。
4. **`financial_view`** 從前端顯示偏好變成真的權限（viewer／engineer 看不到金額）。
5. **案件執行面** 認 `case_manage` 模組（為什麼不是純擁有者規則，見 `_guard_case()`）。
6. **16 個後端不讀的模組** 現在會擋，且**跨模組消費者不會被打死**。
7. **`/api/sales-orders`** 的兩道檢查。
8. **巡視補漏**：第一輪只掃了 `quotations.py`，再巡一次補上案件代辦、完工單、
   出貨單、三種憑證流、網路架構規劃書與全域搜尋。

`project_manage` 那項是「目錄有沒有這個 key」的結構問題，由
`test_module_keys_consistency_2026_09_13.py` 守著，不在這裡測。
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


def _make_case(quote_no, sales_person="", assigned=None):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, sales_person, assigned_user_ids) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測客", "測專", 100000, 95238,
             json.dumps({"dealTag": "已成案",
                         "settlement": {"status": "draft", "cost": 1000}}, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", sales_person,
             json.dumps(assigned or [])),
        )
        conn.commit()
    finally:
        conn.close()


def _assign(quote_no, user_id):
    """把某人加進案件的 assigned_user_ids（測試用）。"""
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT assigned_user_ids FROM quotations WHERE quote_no=?",
                           (quote_no,)).fetchone()
        ids = json.loads(row["assigned_user_ids"] or "[]")
        if user_id not in ids:
            ids.append(user_id)
        conn.execute("UPDATE quotations SET assigned_user_ids=? WHERE quote_no=?",
                     (json.dumps(ids), quote_no))
        conn.commit()
    finally:
        conn.close()


# ── 1. 精算 IDOR ──────────────────────────────────────────────────────────────

def test_outsider_cannot_read_settlement_of_someone_elses_case(client, make_user):
    """不是這張案件的業務、也沒被指派 → 讀不到別人的成本精算。"""
    owner_u, owner_p = make_user(username="s_owner", role="sales")
    other_u, other_p = make_user(username="s_outsider", role="sales")
    _make_case("MQ-IDOR-001", sales_person="s_owner")

    tok = _login(client, other_u, other_p)
    r = client.get("/api/quotations/MQ-IDOR-001/settlement", headers=_auth(tok))
    assert r.status_code == 403, f"外人讀得到別人的精算：{r.status_code} {r.text}"


def test_outsider_cannot_overwrite_settlement_of_someone_elses_case(client, make_user):
    """寫入路徑同理——這是修正前唯一的寫入缺口：任何登入者可覆寫任何案件的精算。"""
    make_user(username="s_owner2", role="sales")
    other_u, other_p = make_user(username="s_outsider2", role="viewer")
    _make_case("MQ-IDOR-002", sales_person="s_owner2")

    tok = _login(client, other_u, other_p)
    r = client.put("/api/quotations/MQ-IDOR-002/settlement",
                   json={"settlement": {"status": "draft", "cost": 999999}},
                   headers=_auth(tok))
    assert r.status_code == 403, f"外人改得動別人的精算：{r.status_code} {r.text}"

    # 觀測點刻意放在「成功才會被改到」的下游：資料本身沒被動到才算真的擋住
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT data_json FROM quotations WHERE quote_no='MQ-IDOR-002'").fetchone()
    finally:
        conn.close()
    assert json.loads(row["data_json"])["settlement"]["cost"] == 1000, "403 了但資料還是被改掉"


def test_owner_and_assignee_and_admin_can_still_use_settlement(client, make_user):
    """三種本來就該能用的人不可以被擋下來：案件業務、被指派的協作者、admin。"""
    owner_u, owner_p = make_user(username="s_owner3", role="sales")
    # 工程師這裡要帶 financial_view：擁有者規則放行他之後，還有第二道
    # 「財務金額可視」（見下面第 4 段）——這一題測的是擁有者規則，不要讓兩條
    # 規則混在一起判不出是哪一條在作用。
    eng_u, eng_p = make_user(username="s_eng3", role="engineer",
                             modules=["case_manage", "financial_view"])
    adm_u, adm_p = make_user(username="s_adm3", role="admin")
    _make_case("MQ-IDOR-003", sales_person="s_owner3", assigned=[_user_id(eng_u)])

    for u, p in ((owner_u, owner_p), (eng_u, eng_p), (adm_u, adm_p)):
        tok = _login(client, u, p)
        assert client.get("/api/quotations/MQ-IDOR-003/settlement",
                          headers=_auth(tok)).status_code == 200, f"{u} 讀不到"
        assert client.get("/api/quotations/MQ-IDOR-003/finance-summary",
                          headers=_auth(tok)).status_code == 200, f"{u} 看不到財務總覽"

    tok = _login(client, owner_u, owner_p)
    r = client.put("/api/quotations/MQ-IDOR-003/settlement",
                   json={"settlement": {"status": "draft", "cost": 2000}},
                   headers=_auth(tok))
    assert r.status_code == 200, r.text

    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT data_json FROM quotations WHERE quote_no='MQ-IDOR-003'").fetchone()
    finally:
        conn.close()
    assert json.loads(row["data_json"])["settlement"]["cost"] == 2000


def test_outsider_cannot_read_finance_summary(client, make_user):
    """`finance-summary` 回的是同一批錢（應收／應付／開票／請款），一起補上。"""
    make_user(username="s_owner4", role="sales")
    other_u, other_p = make_user(username="s_outsider4", role="engineer")
    _make_case("MQ-IDOR-004", sales_person="s_owner4")

    tok = _login(client, other_u, other_p)
    r = client.get("/api/quotations/MQ-IDOR-004/finance-summary", headers=_auth(tok))
    assert r.status_code == 403, f"外人看得到別人的應收應付：{r.status_code}"


# ── 2. reports 模組 ───────────────────────────────────────────────────────────


# ── 4. financial_view 成為真的權限（使用者裁示：viewer／engineer 不該看到金額）──

def test_engineer_without_financial_view_cannot_read_settlement(client, make_user):
    """工程師被指派到案件、碰得到執行面，但**看不到成本與毛利**。"""
    eng_u, eng_p = make_user(username="fv_eng", role="engineer",
                             modules=["case_manage", "work_log"])
    _make_case("MQ-FV-001", sales_person="fv_sales", assigned=[_user_id(eng_u)])
    tok = _login(client, eng_u, eng_p)

    assert client.get("/api/quotations/MQ-FV-001/settlement",
                      headers=_auth(tok)).status_code == 403
    assert client.get("/api/quotations/MQ-FV-001/finance-summary",
                      headers=_auth(tok)).status_code == 403
    # 寫入路徑同樣擋住，而且資料要真的沒被改到
    r = client.put("/api/quotations/MQ-FV-001/settlement",
                   json={"settlement": {"status": "draft", "cost": 555}}, headers=_auth(tok))
    assert r.status_code == 403
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT data_json FROM quotations WHERE quote_no='MQ-FV-001'").fetchone()
    finally:
        conn.close()
    assert json.loads(row["data_json"])["settlement"]["cost"] == 1000


def test_engineer_with_financial_view_can_read_settlement(client, make_user):
    """勾了「財務金額可視」就看得到——規則與前端 canSeeFinancial() 逐字相同。"""
    eng_u, eng_p = make_user(username="fv_eng2", role="engineer",
                             modules=["case_manage", "financial_view"])
    _make_case("MQ-FV-002", sales_person="fv_sales", assigned=[_user_id(eng_u)])
    tok = _login(client, eng_u, eng_p)
    assert client.get("/api/quotations/MQ-FV-002/settlement",
                      headers=_auth(tok)).status_code == 200


def test_sales_role_sees_financial_without_the_module(client, make_user):
    """sales 角色本來就在前端規則的白名單裡，不需要額外勾模組。"""
    u, p = make_user(username="fv_sales_role", role="sales", modules=["case_manage"])
    _make_case("MQ-FV-003", sales_person="fv_sales_role")
    tok = _login(client, u, p)
    assert client.get("/api/quotations/MQ-FV-003/settlement",
                      headers=_auth(tok)).status_code == 200


# ── 5. 案件執行面：case_manage 模組可存取，沒有模組的擋下 ────────────────────

def test_case_execution_face_allows_case_manage_module(client, make_user):
    """工程師不是業務、也沒被指派，但有 `case_manage` → 讀得到案件階段。

    ⚠️ 這條放行是實測後的決定，不是偷懶：開發機 26 張報價單裡
    `assigned_user_ids` 有值的是 **0 張**，純擁有者規則會讓 engineer 角色對
    全部案件的存取權變成 0（見 `_guard_case()` docstring）。
    """
    u, p = make_user(username="ce_eng", role="engineer", modules=["case_manage"])
    _make_case("MQ-CE-001", sales_person="someone_else")
    tok = _login(client, u, p)
    assert client.get("/api/quotations/MQ-CE-001/stages", headers=_auth(tok)).status_code == 200


def test_case_execution_face_blocks_account_without_the_module(client, make_user):
    """viewer／服務帳號（只有 dashboard）仍然擋住——這才是這一輪真正收掉的面。"""
    u, p = make_user(username="ce_viewer", role="viewer", modules=["dashboard"])
    _make_case("MQ-CE-002", sales_person="someone_else")
    tok = _login(client, u, p)
    assert client.get("/api/quotations/MQ-CE-002/stages", headers=_auth(tok)).status_code == 403
    assert client.get("/api/quotations/MQ-CE-002/updates", headers=_auth(tok)).status_code == 403


# ── 6. 16 個「後端不讀」的模組現在真的會擋 ──────────────────────────────────

def test_modules_without_backend_checks_now_block(client, make_user):
    """只有 `dashboard` 的帳號打不開料號／客戶／裝置。

    每日工作事項（/api/daily-tasks）那一項已由 M12 模組內的
    `test_daily_tasks_main_flow.py::test_without_the_module_permission_the_list_is_refused` 涵蓋，
    本題只刪不補（拿掉 M12 時端點不在 ⇒ 404，不是本題要驗的 403；AUDIT-D-A-M12-move §B-11）。"""
    u, p = make_user(username="mod_none", role="viewer", modules=["dashboard"])
    tok = _login(client, u, p)
    for path in ("/api/parts", "/api/parts/categories", "/api/customers"):   # /api/devices：modules/analytics/tests/test_module_permission_fixes_2026_09_13.py
        r = client.get(path, headers=_auth(tok))
        assert r.status_code == 403, f"{path} 沒有擋：{r.status_code}"


def test_cross_module_consumers_are_not_broken(client, make_user):
    """反向（這才是重點）：案件管理要叫料，所以 `case_manage` 也打得開料號與庫存。

    模組檢查收的是「該 API 所有消費頁面所屬模組的聯集」，不是單一模組——只認
    `procurement` 會把案件管理的叫料打死。
    """
    u, p = make_user(username="mod_case", role="engineer", modules=["case_manage"])
    tok = _login(client, u, p)
    assert client.get("/api/parts", headers=_auth(tok)).status_code == 200

    u2, p2 = make_user(username="mod_proc", role="sales", modules=["procurement"])
    tok2 = _login(client, u2, p2)
    assert client.get("/api/parts", headers=_auth(tok2)).status_code == 200
    # 庫存摘要（case_manage 叫料）與供應商（procurement）是 M03 的端點：
    # modules/supply/tests/test_supply_moved_guards.py::test_cross_module_consumers_reach_supply（PLAYBOOK §B-11）


# ── 7. /api/sales-orders ────────────────────────────────────────────────────

def test_sales_orders_requires_finance_module_and_financial_view(client, make_user):
    u, p = make_user(username="so_viewer", role="viewer", modules=["dashboard"])
    tok = _login(client, u, p)
    assert client.get("/api/sales-orders", headers=_auth(tok)).status_code == 403

    u2, p2 = make_user(username="so_fin", role="sales",
                       modules=["finance", "financial_view"])
    tok2 = _login(client, u2, p2)
    assert client.get("/api/sales-orders", headers=_auth(tok2)).status_code == 200


# ── 8. 巡視補漏（2026-09-13 第二次掃描）：其他 router 的同一種每案 IDOR ──────
#
# 第一輪只掃了 `quotations.py`。再巡一次發現同樣的形狀還散在案件代辦、完工單、
# 出貨單、三種憑證流與網路架構規劃書——它們都吃 quote_no，而 quote_no 可列舉。

def _outsider(client, make_user, name):
    u, p = make_user(username=name, role="viewer", modules=["dashboard"])
    return _login(client, u, p)


def test_case_action_items_not_readable_by_outsiders(client, make_user):
    _make_case("MQ-SWEEP-001", sales_person="sw_owner")
    tok = _outsider(client, make_user, "sw_v1")
    assert client.get("/api/quotations/MQ-SWEEP-001/action-items",
                      headers=_auth(tok)).status_code == 403
    r = client.post("/api/quotations/MQ-SWEEP-001/action-items",
                    json={"text": "路人"}, headers=_auth(tok))
    assert r.status_code == 403


def _case_document_bases():
    """帶 quote_no 讀案件單據的端點；出貨單在採購・庫存・出貨（M03）、承攬商付款在外包工班（M04），
    模組不在時不列（端點本來就不在，PLAYBOOK §B-11）。"""
    from core import source_tree
    bases = ["/api/completion-notes", "/api/invoice-vouchers", "/api/payment-requests"]
    if source_tree.module_installed("modules/supply/"):
        bases.append("/api/shipping-notes")
    if source_tree.module_installed("modules/subcontract/"):
        bases.append("/api/contractor-vouchers")
    return bases


def test_case_documents_not_listable_by_outsiders(client, make_user):
    """完工單／出貨單／開票／請款／承攬商付款：帶 quote_no 就是讀某張案件的單據。"""
    _make_case("MQ-SWEEP-002", sales_person="sw_owner")
    tok = _outsider(client, make_user, "sw_v2")
    for base in _case_document_bases():
        r = client.get(f"{base}?quote_no=MQ-SWEEP-002", headers=_auth(tok))
        assert r.status_code == 403, f"{base} 沒擋：{r.status_code}"
        # 不帶 quote_no 的跨案件總覽同樣要擋
        assert client.get(base, headers=_auth(tok)).status_code == 403, base


def test_case_manager_can_still_list_case_documents(client, make_user):
    """反向：具案件管理模組的人照常看得到（案件管理頁就是這樣載入這些單據的）。"""
    u, p = make_user(username="sw_cm", role="engineer", modules=["case_manage"])
    _make_case("MQ-SWEEP-003", sales_person="sw_owner")
    tok = _login(client, u, p)
    for base in _case_document_bases():
        assert client.get(f"{base}?quote_no=MQ-SWEEP-003",
                          headers=_auth(tok)).status_code == 200, base


def test_remaining_quota_endpoints_are_guarded(client, make_user):
    """`remaining` 回的是這張案件還能開多少票／請多少款，等同金額資訊。"""
    _make_case("MQ-SWEEP-004", sales_person="sw_owner")
    tok = _outsider(client, make_user, "sw_v4")
    assert client.get("/api/invoice-vouchers/remaining?quote_no=MQ-SWEEP-004",
                      headers=_auth(tok)).status_code == 403
    assert client.get("/api/payment-requests/remaining?quote_no=MQ-SWEEP-004",
                      headers=_auth(tok)).status_code == 403


# test_case_network_plan_lookup_is_guarded （2026-09-26 移到 modules/netplan/tests/test_netplan_moved_guards.py：拿掉 netplan 時那一項跟著消失，PLAYBOOK §B-11）


def test_global_search_does_not_bypass_module_checks(client, make_user):
    """全域搜尋是最容易被忘記的側門：它自己有一套查詢，不會經過各 router 的檢查。"""
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO customers (code, name) VALUES ('C-SW','搜尋測試客戶')")
        conn.execute("INSERT INTO parts (part_no, name, brand, active) VALUES ('P-SW','搜尋測試料號','X',1)")
        conn.commit()
    finally:
        conn.close()

    tok = _outsider(client, make_user, "sw_search")
    body = client.get("/api/search?q=搜尋測試", headers=_auth(tok)).json()
    assert body["customers"] == [], "沒有客戶模組卻搜得到客戶"
    assert body["parts"] == [], "沒有採購模組卻搜得到料號"

    u2, p2 = make_user(username="sw_search_ok", role="engineer", modules=["case_manage"])
    body2 = client.get("/api/search?q=搜尋測試", headers=_auth(_login(client, u2, p2))).json()
    assert len(body2["customers"]) == 1 and len(body2["parts"]) == 1, "有模組的人反而搜不到"


# ── 9. 憑證流與額外支出的金額可視（2026-09-13 第四輪）────────────────────────
#
# 使用者裁示「viewer／engineer 不該看到金額」時，稽核報告 §4 把三種憑證流與額外
# 支出列為「未做，因為那些端點上有非管理員的簽核人，直接套會把簽核人擋在門外」。
# 這一輪連同「單號可列舉」的 IDOR 一起收，規則是：**本單簽核人與填寫人例外**。

def _mk_invoice_voucher(voucher_no, quote_no, approver=None, created_by="someone"):
    import db
    appr = {"tiers": [{"approvers": [{"username": approver, "status": "pending"}]}],
            "currentTier": 0} if approver else {}
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO invoice_vouchers (voucher_no, quote_no, scope, payment_idx, status, "
            "snapshot_json, data_json, created_by, created_at, updated_at, amount) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (voucher_no, quote_no, "amount", 0, "待審核", "{}",
             json.dumps({"approval": appr}, ensure_ascii=False), created_by,
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", 50000),
        )
        conn.commit()
    finally:
        conn.close()


def test_voucher_detail_is_not_readable_by_outsiders(client, make_user):
    """單號是可預測的（前綴＋年月＋流水號），詳情端點先前只要求登入。"""
    _make_case("MQ-VCH-001", sales_person="vch_owner")
    _mk_invoice_voucher("IV-2026-001", "MQ-VCH-001")
    tok = _outsider(client, make_user, "vch_out")
    assert client.get("/api/invoice-vouchers/IV-2026-001",
                      headers=_auth(tok)).status_code == 403
    assert client.get("/api/invoice-vouchers/IV-2026-001/pdf-download",
                      headers=_auth(tok)).status_code == 403


def test_voucher_list_hides_amounts_from_non_financial_users(client, make_user):
    """沒有財務可視權的人，清單只剩「自己要簽的那幾張」，不是整支 403。

    整支 403 會讓非管理員的簽核人連簽核佇列都打不開——他們正是要在那裡看到待簽單據。
    """
    _make_case("MQ-VCH-002", sales_person="vch_owner")
    _mk_invoice_voucher("IV-2026-002", "MQ-VCH-002")                       # 與他無關
    _mk_invoice_voucher("IV-2026-003", "MQ-VCH-002", approver="vch_eng")   # 他要簽的

    u, p = make_user(username="vch_eng", role="engineer",
                     modules=["case_manage", "quotation"])
    tok = _login(client, u, p)
    nos = [v["voucherNo"] for v in
           client.get("/api/invoice-vouchers?quote_no=MQ-VCH-002", headers=_auth(tok)).json()]
    assert nos == ["IV-2026-003"], f"過濾結果不對：{nos}"

    # 有財務可視權就兩張都看得到
    u2, p2 = make_user(username="vch_fin", role="engineer",
                       modules=["case_manage", "financial_view"])
    nos2 = sorted(v["voucherNo"] for v in
                  client.get("/api/invoice-vouchers?quote_no=MQ-VCH-002",
                             headers=_auth(_login(client, u2, p2))).json())
    assert nos2 == ["IV-2026-002", "IV-2026-003"], nos2


def test_extra_expenses_visible_to_filer_even_without_financial_view(client, make_user):
    """額外支出：現場花錢的人看得到自己報的帳，看不到別人的。"""
    import db
    eng_u, eng_p = make_user(username="xe_eng", role="engineer", modules=["case_manage"])
    _make_case("MQ-XE-100", sales_person="xe_owner", assigned=[_user_id(eng_u)])
    conn = db.get_db()
    try:
        for desc, who in (("我報的帳", "xe_eng"), ("別人報的帳", "xe_other")):
            conn.execute(
                "INSERT INTO case_extra_expenses (quote_no, category, description, qty, unit, "
                "unit_cost, total_cost, note, expense_date, doc_no, files_json, created_by, "
                "created_by_name, created_by_inferred, payer_username, payer_name, created_at, "
                "updated_at, updated_by_name, status, approval_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,'[]',?,?,0,?,?,?,?,?,'草稿','{}')",
                ("MQ-XE-100", "其他", desc, 1, "式", 1000, 1000, "", "2026-09-01", "",
                 who, who, who, who, "2026-01-01T00:00:00", "2026-01-01T00:00:00", who),
            )
        conn.commit()
    finally:
        conn.close()

    body = client.get("/api/quotations/MQ-XE-100/extra-expenses",
                      headers=_auth(_login(client, eng_u, eng_p))).json()
    descs = [i["description"] for i in body["items"]]
    assert descs == ["我報的帳"], descs
    assert body["totalAmount"] == 1000, "合計要跟著只算看得到的那幾筆"

    # 有財務可視權（或 sales/admin）就看得到全部
    u2, p2 = make_user(username="xe_fin", role="engineer",
                       modules=["case_manage", "financial_view"])
    _assign(quote_no="MQ-XE-100", user_id=_user_id(u2))
    body2 = client.get("/api/quotations/MQ-XE-100/extra-expenses",
                       headers=_auth(_login(client, u2, p2))).json()
    assert len(body2["items"]) == 2 and body2["totalAmount"] == 2000


# ── 10. 解鎖（半解鎖）流程複查（2026-09-13）──────────────────────────────────
#
# 已結案案件「解鎖 → 上傳/修改 → superadmin 審核」這條路，在補完模組與擁有者
# 檢查之後重新走一次，確認三件事：擋得住外人、擋不住該擋的人、審核仍限 superadmin。

def _close_case(quote_no):
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE quotations SET deal_tag='已結案' WHERE quote_no=?", (quote_no,))
        conn.commit()
    finally:
        conn.close()


def test_anyone_can_unlock_but_every_change_needs_approval(client, make_user):
    """解鎖是**刻意全開**的（2026-08-26 使用者裁示，2026-09-13 再次確認）：
    「誰都可以改動，但都需要審核」——把關點在審核，不在入口。

    2026-09-13 的模組權限稽核曾一度把解鎖一起收成擁有者規則，複查時發現那推翻了
    使用者已經裁示過的設計，已還原。這一題就是釘住「不要再收第二次」。
    """
    _make_case("MQ-LOCK-001", sales_person="lock_owner")
    _close_case("MQ-LOCK-001")
    tok = _outsider(client, make_user, "lock_out")           # 只有 dashboard 的檢視者
    assert client.post("/api/quotations/MQ-LOCK-001/case-unlock",
                       headers=_auth(tok)).status_code == 200

    import db
    conn = db.get_db()
    try:
        row = conn.execute(
            "SELECT case_semi_unlocked FROM quotations WHERE quote_no='MQ-LOCK-001'").fetchone()
    finally:
        conn.close()
    assert row["case_semi_unlocked"], "回了 200 但案件其實沒被解鎖"

    # 但**未結案**的案件沒有那道審核，仍然擋外人（這是兩層規則的分界）
    _make_case("MQ-LOCK-001B", sales_person="lock_owner")
    r = client.post("/api/quotations/MQ-LOCK-001B/materials/0/files",
                    files={"files": ("x.jpg", bytes.fromhex("ffd8ffe0") + b"fake", "image/jpeg")},
                    headers=_auth(tok))
    assert r.status_code == 403, f"未結案的案件不該讓外人上傳：{r.status_code}"


def test_anyone_can_upload_to_a_semi_unlocked_case_but_it_queues(client, make_user):
    """「誰都可以改動，但都需要審核」的另一半：半解鎖期間外人也傳得了檔案，
    但東西不會直接生效，而是進待審核佇列等 superadmin 決定。

    觀測點放在下游——不是看回傳 200，而是看 `case_change_requests` 真的多一筆
    pending。只看狀態碼的話，「直接套用」跟「排進審核」兩種結果長得一模一樣。
    """
    import db
    _make_case("MQ-LOCK-005", sales_person="lock_owner5")
    _close_case("MQ-LOCK-005")
    # 這支端點要求料件索引存在，先種一筆叫料
    conn = db.get_db()
    try:
        row = conn.execute("SELECT data_json FROM quotations WHERE quote_no='MQ-LOCK-005'").fetchone()
        data = json.loads(row["data_json"])
        data.setdefault("caseRecord", {}).setdefault("materials", []).append({"name": "測試料件"})
        conn.execute("UPDATE quotations SET data_json=? WHERE quote_no='MQ-LOCK-005'",
                     (json.dumps(data, ensure_ascii=False),))
        conn.commit()
    finally:
        conn.close()
    tok = _outsider(client, make_user, "lock_out5")
    assert client.post("/api/quotations/MQ-LOCK-005/case-unlock",
                       headers=_auth(tok)).status_code == 200

    r = client.post("/api/quotations/MQ-LOCK-005/materials/0/files",
                    files={"files": ("photo.jpg", bytes.fromhex("ffd8ffe0") + b"fake", "image/jpeg")},
                    headers=_auth(tok))
    assert r.status_code in (200, 201), r.text
    assert r.json().get("pending") is True, r.json()

    conn = db.get_db()
    try:
        rows = conn.execute(
            "SELECT status FROM case_change_requests WHERE quote_no='MQ-LOCK-005'").fetchall()
    finally:
        conn.close()
    assert [r["status"] for r in rows] == ["pending"], "沒有排進審核佇列"


def test_case_manager_can_unlock_and_upload_during_semi_unlock(client, make_user):
    """反向：具「案件管理」模組的工程師照樣解得開、也傳得了叫料附件。

    這條是實務主線——現場的人補資料，補完再由 superadmin 審核。
    """
    u, p = make_user(username="lock_eng", role="engineer", modules=["case_manage"])
    _make_case("MQ-LOCK-002", sales_person="lock_owner")
    _close_case("MQ-LOCK-002")
    tok = _login(client, u, p)
    r = client.post("/api/quotations/MQ-LOCK-002/case-unlock", headers=_auth(tok))
    assert r.status_code == 200, r.text
    assert r.json()["caseSemiUnlocked"] is True
    assert client.post("/api/quotations/MQ-LOCK-002/case-lock",
                       headers=_auth(tok)).status_code == 200


def test_change_request_detail_is_not_enumerable(client, make_user):
    """`change_id` 是小整數流水號，比 quote_no 更好猜，而內容是整包案件變更。"""
    import db
    _make_case("MQ-LOCK-003", sales_person="lock_owner")
    _close_case("MQ-LOCK-003")
    conn = db.get_db()
    try:
        cur = conn.execute(
            "INSERT INTO case_change_requests (quote_no, action_type, summary, payload_json, "
            "staged_files_json, status, requested_by, requested_by_display, requested_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("MQ-LOCK-003", "case_record_update", "測試變更", "{}", "[]", "pending",
             "lock_owner", "lock_owner", "2026-09-13T00:00:00"),
        )
        change_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    tok = _outsider(client, make_user, "lock_out3")
    assert client.get(f"/api/case-changes/{change_id}", headers=_auth(tok)).status_code == 403

    # 提出申請的本人看得到自己送出的內容
    ru, rp = make_user(username="lock_owner", role="sales")
    assert client.get(f"/api/case-changes/{change_id}",
                      headers=_auth(_login(client, ru, rp))).status_code == 200


def test_change_request_approval_still_superadmin_only(client, make_user):
    """審核維持僅 superadmin——這一輪的權限調整不該鬆動它。"""
    import db
    _make_case("MQ-LOCK-004", sales_person="lock_owner4")
    _close_case("MQ-LOCK-004")
    conn = db.get_db()
    try:
        cur = conn.execute(
            "INSERT INTO case_change_requests (quote_no, action_type, summary, payload_json, "
            "staged_files_json, status, requested_by, requested_by_display, requested_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("MQ-LOCK-004", "case_record_update", "測試變更", "{}", "[]", "pending",
             "lock_owner4", "lock_owner4", "2026-09-13T00:00:00"),
        )
        change_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    au, ap = make_user(username="lock_admin", role="admin", modules=["case_manage"])
    assert client.post(f"/api/case-changes/{change_id}/approve",
                       headers=_auth(_login(client, au, ap))).status_code == 403


# ── 11. 完結案限最高管理者（2026-09-13 使用者裁示）──────────────────────────

def test_only_superadmin_can_close_a_case(client, make_user):
    """admin 也不能按完結案——結案是全系統最不可逆的動作，而且原本就只有
    superadmin 能把它降級回來（按得下去的人比按得回來的人多，本來就不對稱）。

    觀測點分兩段：admin 被擋下（403，且案件真的沒被結案），superadmin 在**同一張
    案件**上結得成（200，且 deal_tag 真的變成已結案）。少了後半段，這題就可能只是
    「大家都被擋」的假綠燈。
    """
    _make_case("MQ-CLOSE-001", sales_person="close_owner")
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE quotations SET deal_tag='已成案', status='已送出' "
                     "WHERE quote_no='MQ-CLOSE-001'")
        conn.execute("UPDATE quotations SET data_json=? WHERE quote_no='MQ-CLOSE-001'",
                     (json.dumps({"dealTag": "已成案"}, ensure_ascii=False),))
        conn.commit()
    finally:
        conn.close()

    au, ap = make_user(username="close_admin", role="admin", modules=["case_manage"])
    r = client.patch("/api/quotations/MQ-CLOSE-001/deal-tag",
                     json={"deal_tag": "已結案"}, headers=_auth(_login(client, au, ap)))
    assert r.status_code == 403, f"admin 竟然結得了案：{r.status_code} {r.text}"

    conn = db.get_db()
    try:
        tag = conn.execute("SELECT deal_tag FROM quotations WHERE quote_no='MQ-CLOSE-001'").fetchone()["deal_tag"]
    finally:
        conn.close()
    assert tag == "已成案", "403 了但案件其實被結案了"

    su, sp = make_user(username="close_super", role="superadmin")
    r2 = client.patch("/api/quotations/MQ-CLOSE-001/deal-tag",
                      json={"deal_tag": "已結案"}, headers=_auth(_login(client, su, sp)))
    assert r2.status_code == 200, f"superadmin 結不了案：{r2.status_code} {r2.text}"

    conn = db.get_db()
    try:
        tag2 = conn.execute("SELECT deal_tag FROM quotations WHERE quote_no='MQ-CLOSE-001'").fetchone()["deal_tag"]
    finally:
        conn.close()
    assert tag2 == "已結案", f"回了 200 但案件沒結成：{tag2}"


def test_admin_can_still_set_other_deal_tags(client, make_user):
    """反向：這次只鎖「已結案」，admin 標記已成案／未成案不受影響。"""
    _make_case("MQ-CLOSE-002", sales_person="close_owner2")
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE quotations SET deal_tag='', status='已送出', data_json=? "
                     "WHERE quote_no='MQ-CLOSE-002'", (json.dumps({}),))
        conn.commit()
    finally:
        conn.close()
    au, ap = make_user(username="close_admin2", role="admin", modules=["case_manage"])
    r = client.patch("/api/quotations/MQ-CLOSE-002/deal-tag",
                     json={"deal_tag": "已成案"}, headers=_auth(_login(client, au, ap)))
    assert r.status_code == 200, r.text


# ── 12. 完結案前置條件＋半解鎖變更的 superadmin 通知（2026-09-13 使用者裁示）──

def _seed_closeable_case(quote_no, settlement=None):
    """一張「其他條件都達成」的已成案案件，方便單獨測某一個前置條件。"""
    import db
    data = {"dealTag": "已成案"}
    if settlement is not None:
        data["settlement"] = settlement
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, sales_person, assigned_user_ids) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測客", "測專", 100000, 95238,
             json.dumps(data, ensure_ascii=False), "2026-01-01T00:00:00", "2026-01-01T00:00:00",
             "已成案", "", "[]"),
        )
        conn.commit()
    finally:
        conn.close()


def test_close_blocked_when_settlement_not_finalized(client, make_user):
    """精算還在草稿就結案，等於把一張永遠算不完的帳鎖進已結案。"""
    _seed_closeable_case("MQ-CLOSE-010", settlement={"status": "draft", "cost": 1000})
    su, sp = make_user(username="cl_su1", role="superadmin")
    r = client.patch("/api/quotations/MQ-CLOSE-010/deal-tag",
                     json={"deal_tag": "已結案"}, headers=_auth(_login(client, su, sp)))
    assert r.status_code == 400, r.text
    assert "精算" in r.text, r.text


def test_close_allowed_when_settlement_finalized(client, make_user):
    """反向控制：精算完結就不再擋（否則上一題可能只是「什麼都擋」）。"""
    _seed_closeable_case("MQ-CLOSE-011", settlement={"status": "finalized", "cost": 1000})
    su, sp = make_user(username="cl_su2", role="superadmin")
    r = client.patch("/api/quotations/MQ-CLOSE-011/deal-tag",
                     json={"deal_tag": "已結案"}, headers=_auth(_login(client, su, sp)))
    assert r.status_code == 200, r.text


def test_close_blocked_when_completion_note_pending(client, make_user):
    """完工單是 DB v77（2026-09-12）才有的模組，原本的前置條件清單沒有它。"""
    import db
    _seed_closeable_case("MQ-CLOSE-012")
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO completion_notes (note_no, quote_no, status, data_json, created_by, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            ("CN-TEST-001", "MQ-CLOSE-012", "待審核", "{}", "someone",
             "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()
    su, sp = make_user(username="cl_su3", role="superadmin")
    r = client.patch("/api/quotations/MQ-CLOSE-012/deal-tag",
                     json={"deal_tag": "已結案"}, headers=_auth(_login(client, su, sp)))
    assert r.status_code == 400, r.text
    assert "完工單" in r.text, r.text


def test_close_blocked_when_extra_expense_pending(client, make_user):
    """送審中的額外支出＝還沒定案的成本，結案後才核准會讓成本事後改變。"""
    import db
    _seed_closeable_case("MQ-CLOSE-013")
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO case_extra_expenses (quote_no, category, description, qty, unit, "
            "unit_cost, total_cost, note, expense_date, doc_no, files_json, created_by, "
            "created_by_name, created_by_inferred, payer_username, payer_name, created_at, "
            "updated_at, updated_by_name, status, approval_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,'[]',?,?,0,?,?,?,?,?,'待審核','{}')",
            ("MQ-CLOSE-013", "其他", "還在審的支出", 1, "式", 500, 500, "", "2026-09-01", "",
             "someone", "someone", "someone", "someone",
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "someone"),
        )
        conn.commit()
    finally:
        conn.close()
    su, sp = make_user(username="cl_su4", role="superadmin")
    r = client.patch("/api/quotations/MQ-CLOSE-013/deal-tag",
                     json={"deal_tag": "已結案"}, headers=_auth(_login(client, su, sp)))
    assert r.status_code == 400, r.text
    assert "額外支出" in r.text, r.text


def test_semi_unlock_change_emails_superadmin(client, make_user, monkeypatch):
    """半解鎖期間有人上傳／變更 → 除了排隊審核，還要寄信給最高管理者。

    兩個 monkeypatch 都是為了讓斷言**確定**：背景執行緒改成同步跑（不然測試會跟
    執行緒賽跑），寄信落在 `_send` 上攔截（不是攔上層函式——那樣連收件人算對了
    沒有都測不到）。
    """
    import db
    import helpers.email_notify as en
    import routers.quotations as q

    monkeypatch.setattr(q, "spawn_bg_thread", lambda fn, args=(), **kw: fn(*args))
    sent = []
    monkeypatch.setattr(en, "_send", lambda to, subject, html: sent.append((to, subject)))

    su, sp = make_user(username="mail_su", role="superadmin")
    conn = db.get_db()
    try:
        conn.execute("UPDATE users SET email='boss@example.com' WHERE username='mail_su'")
        conn.commit()
    finally:
        conn.close()

    _make_case("MQ-MAIL-001", sales_person="mail_owner")
    _close_case("MQ-MAIL-001")
    conn = db.get_db()
    try:
        row = conn.execute("SELECT data_json FROM quotations WHERE quote_no='MQ-MAIL-001'").fetchone()
        data = json.loads(row["data_json"])
        data.setdefault("caseRecord", {}).setdefault("materials", []).append({"name": "測試料件"})
        conn.execute("UPDATE quotations SET data_json=? WHERE quote_no='MQ-MAIL-001'",
                     (json.dumps(data, ensure_ascii=False),))
        conn.commit()
    finally:
        conn.close()

    tok = _outsider(client, make_user, "mail_uploader")
    assert client.post("/api/quotations/MQ-MAIL-001/case-unlock",
                       headers=_auth(tok)).status_code == 200
    sent.clear()
    r = client.post("/api/quotations/MQ-MAIL-001/materials/0/files",
                    files={"files": ("photo.jpg", bytes.fromhex("ffd8ffe0") + b"fake", "image/jpeg")},
                    headers=_auth(tok))
    assert r.status_code in (200, 201), r.text
    assert r.json().get("pending") is True

    recipients = [addr for to, _ in sent for addr in to]
    assert "boss@example.com" in recipients, f"沒有寄給最高管理者：{sent}"
    assert any("變更待審核" in subj for _, subj in sent), f"信件主旨不對：{sent}"
