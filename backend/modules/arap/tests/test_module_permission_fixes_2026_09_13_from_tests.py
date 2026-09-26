"""需要應收應付（M05）的題：刪掉 modules/arap 時隨模組消失（PLAYBOOK §B-11）。

（2026-09-26 自 tests/test_module_permission_fixes_2026_09_13.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
模組權限稽核修正的行為測試（2026-09-13）。

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
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


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


# ── 2. reports 模組 ───────────────────────────────────────────────────────────


# ── 4. financial_view 成為真的權限（使用者裁示：viewer／engineer 不該看到金額）──


# ── 5. 案件執行面：case_manage 模組可存取，沒有模組的擋下 ────────────────────


# ── 6. 16 個「後端不讀」的模組現在真的會擋 ──────────────────────────────────


# ── 7. /api/sales-orders ────────────────────────────────────────────────────


# ── 8. 巡視補漏（2026-09-13 第二次掃描）：其他 router 的同一種每案 IDOR ──────
#
# 第一輪只掃了 `quotations.py`。再巡一次發現同樣的形狀還散在案件代辦、完工單、
# 出貨單、三種憑證流與網路架構規劃書——它們都吃 quote_no，而 quote_no 可列舉。

def _outsider(client, make_user, name):
    u, p = make_user(username=name, role="viewer", modules=["dashboard"])
    return _login(client, u, p)


def _case_document_bases():
    """帶 quote_no 讀案件單據的端點；承攬商付款在外包工班（M04），模組不在時不列（PLAYBOOK §B-11）。"""
    from core import source_tree
    bases = ["/api/completion-notes", "/api/shipping-notes", "/api/invoice-vouchers", "/api/payment-requests"]
    if source_tree.module_installed("modules/subcontract/"):
        bases.append("/api/contractor-vouchers")
    return bases


def test_remaining_quota_endpoints_are_guarded(client, make_user):
    """`remaining` 回的是這張案件還能開多少票／請多少款，等同金額資訊。"""
    _make_case("MQ-SWEEP-004", sales_person="sw_owner")
    tok = _outsider(client, make_user, "sw_v4")
    assert client.get("/api/invoice-vouchers/remaining?quote_no=MQ-SWEEP-004",
                      headers=_auth(tok)).status_code == 404   # M01-O1：看不到＝不存在（同一個 404）
    assert client.get("/api/payment-requests/remaining?quote_no=MQ-SWEEP-004",
                      headers=_auth(tok)).status_code == 404   # M01-O1：看不到＝不存在（同一個 404）


# test_case_network_plan_lookup_is_guarded （2026-09-26 移到 modules/netplan/tests/test_netplan_moved_guards.py：拿掉 netplan 時那一項跟著消失，PLAYBOOK §B-11）


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
                      headers=_auth(tok)).status_code == 404   # M01-O1：看不到＝不存在（同一個 404）
    assert client.get("/api/invoice-vouchers/IV-2026-001/pdf-download",
                      headers=_auth(tok)).status_code == 404   # M01-O1：看不到＝不存在（同一個 404）


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


# ── 11. 完結案限最高管理者（2026-09-13 使用者裁示）──────────────────────────


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
