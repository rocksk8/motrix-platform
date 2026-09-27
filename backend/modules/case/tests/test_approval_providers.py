"""「待我簽核」與轉簽改由各單據模組提供（M01-PLAN §3-7；IP-10 `approval.queue_items`、IP-94 `approval.reassign`）。

① M01 的佇列、角標、轉簽三支端點不再直讀／直寫其他模組的單據表（只彙整提供者）
② 每種可轉簽的單據類型各有一個 `approval.reassign` 提供者（依安裝的模組）
③ 拿掉一個單據模組的提供者 ⇒ 那一類不列、角標跟著少、`reassignTypes` 不含、轉簽 400；正對照：提供者在時全部都有
④ 簽核資料讀不出來 ⇒ 轉簽 400（fail-closed），不是 500、也不是當成空鏈
⑤ 提供者沒給 `customer`／`projectName` ⇒ M01 依 `linkedQuoteNo` 補；給了（含空字串）不覆寫
⑥ 佇列詳情（`approval.detail`，c-approval-2）：其他模組單據的內容由擁有模組提供；拿掉 ⇒ 400「模組未安裝」；
   正對照：提供者在時 200、欄位與檔案來自提供者、案件抬頭由 M01 補
"""
import ast
import json
from pathlib import Path

import pytest

from core import registry, source_tree

BACKEND = Path(__file__).resolve().parents[3]   # M01 ④：隨模組搬進 modules/case/tests
#: 別的模組的單據表（2026-09-26 前 M01 的三支端點逐表直寫的那些）
FOREIGN_TABLES = ("contractor_payment_vouchers", "invoice_vouchers", "payment_requests", "shipping_notes",
                  "vouchers_all", "voucher_lines", "bonus_awards", "bonus_case_awards")
#: 佇列彙整（L1 routers/approval_queue.py，2026-09-27 自 M01 搬入）與 M01 自己的提供者
L1_FUNCS = ("get_approval_queue", "get_approval_queue_count", "_queue_provider_items", "reassign_approval",
            "approval_queue_detail")
M01_FUNCS = ("approval_queue_items", "detail_quotation", "detail_completion_note", "detail_extra_expense",
             "detail_case_change")


def _funcs(src, names):
    tree = ast.parse(src)
    return {n.name: ast.get_source_segment(src, n) for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name in names}


def test_case_endpoints_do_not_touch_other_modules_tables():
    found = {}
    for rel, names in ((("routers", "approval_queue.py"), L1_FUNCS),
                       (("modules", "case", "api", "quotations.py"), M01_FUNCS)):
        got = _funcs(BACKEND.joinpath(*rel).read_text(encoding="utf-8"), names)
        assert set(got) == set(names), (rel, sorted(got))
        found.update(got)
    bad = {f: [t for t in FOREIGN_TABLES if t in body] for f, body in found.items()}
    bad = {f: ts for f, ts in bad.items() if ts}
    assert not bad, "M01 佇列／角標／轉簽仍直接碰其他模組的單據表 ⇒ 改由擁有模組提供（M01-PLAN §3-7）：%s" % bad


def _expected_reassign_types():
    out = {"quotation", "completion_note", "voucher"}                     # M01 本身、仍在 routers/ 的 M06
    if source_tree.module_installed("modules/supply/"):
        out.add("shipping_note")
    if source_tree.module_installed("modules/subcontract/"):
        out.add("contractor_voucher")
    if source_tree.module_installed("modules/arap/"):
        out |= {"invoice_voucher", "payment_request"}
    return out


def test_every_reassign_type_has_one_provider(client):
    got = registry.providers("approval.reassign")
    assert set(got) == _expected_reassign_types(), sorted(got)
    for name, obj in got.items():
        assert callable(getattr(obj, "load", None)) and callable(getattr(obj, "save", None)), name


def test_every_detail_type_has_one_provider(client):
    """每種單據各有一個 `approval.detail`（端點在 L1，2026-09-27）：M01 四種（報價單、完工單、額外支出、已結案變更）與其他模組的。"""
    want = {"quotation", "completion_note", "extra_expense", "case_change"}   # 本檔在 modules/case/tests ⇒ M01 在
    if source_tree.module_installed("modules/supply/"):
        want.add("shipping_note")
    if source_tree.module_installed("modules/subcontract/"):
        want.add("contractor_voucher")
    if source_tree.module_installed("modules/arap/"):
        want |= {"invoice_voucher", "payment_request"}
    got = registry.providers("approval.detail")
    assert set(got) == want and all(callable(f) for f in got.values()), sorted(got)


# ── 行為：以開票申請（M05）為例 ─────────────────────────────────────────────

def _login(client, u, p):
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _seed_iv(no, approver, data_json=None):
    import db
    appr = {"requestedBy": "aq_sales", "requestedByDisplay": "業務", "requestedAt": "2026-09-26T09:00:00",
            "currentTier": 0, "tiers": [{"approvers": [{"username": approver, "displayName": approver, "status": "pending"}]}]}
    conn = db.get_db()
    try:
        # 掛的案件要真的存在：孤兒單（案件已不存在）只列給簽核鏈上的人（c-approval-l1-4，§G5 #13）
        conn.execute("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, "
                     "updated_at) VALUES ('MQ-AQP-1','成交','客','案','{}','2026-09-26','2026-09-26')")
        conn.execute("INSERT INTO invoice_vouchers (voucher_no, quote_no, status, data_json, created_at, updated_at) "
                     "VALUES (?,?,?,?,?,?)",
                     (no, "MQ-AQP-1", "待審核", data_json if data_json is not None else json.dumps({"approval": appr}),
                      "2026-09-26T09:00:00", "2026-09-26T09:00:00"))
        conn.commit()
    finally:
        conn.close()


def _iv_approval(no):
    import db
    conn = db.get_db()
    try:
        return json.loads(conn.execute("SELECT data_json FROM invoice_vouchers WHERE voucher_no=?", (no,)).fetchone()[0])["approval"]
    finally:
        conn.close()


def _without(monkeypatch, name):
    orig = registry.providers

    def fake(cap):
        got = orig(cap)
        if cap in ("approval.queue_items", "approval.reassign", "approval.detail"):
            got = {k: v for k, v in got.items() if k != name}
        return got
    monkeypatch.setattr(registry, "providers", fake)


def _queue_nos(client, h):
    d = client.get("/api/approval-queue", headers=h).json()
    return {it["quoteNo"] for g in d["queue"] for it in g["items"]}, d["reassignTypes"]


def _count(client, h):
    return client.get("/api/approval-queue/count", headers=h).json()["count"]


@pytest.fixture
def iv_setup(client, make_user):
    if not source_tree.module_installed("modules/arap/"):
        pytest.skip("M05 不在這個安裝包 ⇒ 開票申請本來就不存在（PLAYBOOK §B-11）")
    su, sp = make_user("aqp_super", "Conn-Pass-123", role="superadmin")[:2]
    au, ap = make_user("aqp_old", "Conn-Pass-123", role="admin")[:2]
    make_user("aqp_new", "Conn-Pass-123", role="admin")
    return _login(client, su, sp), _login(client, au, ap)


def test_owner_present_lists_counts_and_reassigns(client, iv_setup):
    sh, ah = iv_setup
    _seed_iv("IV-AQP-1", "aqp_old")
    nos, types = _queue_nos(client, sh)
    assert "IV-AQP-1" in nos and "invoice_voucher" in types
    assert _count(client, ah) >= 1
    r = client.post("/api/approval-queue/reassign", headers=sh,
                    json={"type": "invoice_voucher", "id": "IV-AQP-1", "to_username": "aqp_new", "reason": "請假"})
    assert r.status_code == 200, r.text
    a = _iv_approval("IV-AQP-1")["tiers"][0]["approvers"][0]
    assert a["username"] == "aqp_new" and a["reassignedFrom"] == "aqp_old" and a["reassignReason"] == "請假"


def test_owner_absent_hides_the_type_everywhere(client, iv_setup, monkeypatch):
    sh, ah = iv_setup
    _seed_iv("IV-AQP-2", "aqp_old")
    before = _count(client, ah)
    _without(monkeypatch, "invoice_voucher")
    nos, types = _queue_nos(client, sh)
    assert "IV-AQP-2" not in nos and "invoice_voucher" not in types
    assert _count(client, ah) == before - 1
    r = client.post("/api/approval-queue/reassign", headers=sh,
                    json={"type": "invoice_voucher", "id": "IV-AQP-2", "to_username": "aqp_new", "reason": "請假"})
    assert r.status_code == 400 and "未安裝" in r.json()["detail"], r.text
    assert _iv_approval("IV-AQP-2")["tiers"][0]["approvers"][0]["username"] == "aqp_old"


def _detail(client, h, no):
    return client.get("/api/approval-queue/detail?type=invoice_voucher&id=" + no, headers=h)


def test_detail_comes_from_the_owner_and_says_when_it_is_absent(client, iv_setup, monkeypatch):
    import db
    sh, _ah = iv_setup
    conn = db.get_db()
    try:                                                   # 詳情的每案權限要案件存在（M01 `_guard_queue_detail`，行為同前）
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at, "
                     "assigned_user_ids) VALUES ('MQ-AQP-1','成交','甲客戶','乙專案','{}','2026-09-26','2026-09-26','[]')")
        conn.commit()
    finally:
        conn.close()
    _seed_iv("IV-AQP-4", "aqp_old")
    ok = _detail(client, sh, "IV-AQP-4")
    assert ok.status_code == 200, ok.text
    d = ok.json()
    assert d["case"]["customerName"] == "甲客戶" and any(f["label"] == "建立時間" for f in d["fields"])
    assert _detail(client, sh, "IV-NONE").status_code == 404
    _without(monkeypatch, "invoice_voucher")
    r = _detail(client, sh, "IV-AQP-4")
    assert r.status_code == 400 and "未安裝" in r.json()["detail"], r.text


def test_detail_keeps_m01_access_and_money_rules_for_provider_types(client, iv_setup, make_user):
    """每案權限與金額遮蔽仍由 M01 判斷，依據是提供者給的 `approvalRaw`：鏈上的一般使用者（非該案、無財務權）看得到內容與金額；
    不在鏈上的外人 403。"""
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at, "
                     "assigned_user_ids) VALUES ('MQ-AQP-1','成交','甲客戶','乙專案','{}','2026-09-26','2026-09-26','[]')")
        conn.commit()
    finally:
        conn.close()
    au, ap = make_user(username="aqp_chain", role="viewer", modules=["dashboard"])[:2]
    ou, op = make_user(username="aqp_outsider", role="viewer", modules=["dashboard"])[:2]
    _seed_iv("IV-AQP-5", "aqp_chain")
    r = _detail(client, _login(client, au, ap), "IV-AQP-5")
    assert r.status_code == 200, r.text
    assert not r.json().get("moneyMasked") and any(f["label"] == "金額" and f["value"] != "（無財務檢視權限）"
                                                   for f in r.json()["fields"])
    assert _detail(client, _login(client, ou, op), "IV-AQP-5").status_code == 404   # M01-O1：看不到＝不存在（同一個 404）


def test_case_sales_without_money_rights_gets_no_passbook(client, make_user):
    """稽核 D AP-M2：該案業務（非財務、非簽核人）打得開承攬商匯款申請的詳情，但拿不到存簿封面（沒有 passbook、沒有任何 dataUrl）；
    正對照：本單簽核人（同樣非財務）看得到。"""
    import db
    if not source_tree.module_installed("modules/subcontract/"):
        pytest.skip("M04 不在這個安裝包 ⇒ 承攬商匯款申請本來就不存在（PLAYBOOK §B-11）")
    su, sp = make_user(username="apm2_sales", role="viewer", modules=["dashboard"])[:2]
    au, ap = make_user(username="apm2_appr", role="viewer", modules=["dashboard"])[:2]
    snap = {"grandTotal": 5000, "vendorName": "測試承攬商", "bankPassbookImage": "data:image/png;base64,AAAA"}
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at, "
                     "deal_tag, sales_person, assigned_user_ids) VALUES ('MQ-APM2-1','已送出','客','案','{}','2026-09-26',"
                     "'2026-09-26','已成案','apm2_sales','[]')")
        conn.execute("INSERT INTO contractor_dispatches (id, quote_no, dispatch_date, scope, items_json, personnel_json, "
                     "total_amount, tax_rate, status, notes, created_by, created_at, updated_at, files_json, invoice_files_json) "
                     "VALUES (99102,'MQ-APM2-1','2026-09-01','x','[]','[]',5000,0,'已完成','','x','2026-09-26','2026-09-26','[]','[]')")
        conn.execute("INSERT INTO contractor_payment_vouchers (voucher_no, quote_no, dispatch_id, status, snapshot_json, data_json, "
                     "created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                     ("CV-APM2-1", "MQ-APM2-1", 99102, "待審核", json.dumps(snap),
                      json.dumps({"approval": {"currentTier": 0, "tiers": [{"approvers": [{"username": "apm2_appr", "status": "pending"}]}]}}),
                      "x", "2026-09-26", "2026-09-26"))
        conn.commit()
    finally:
        conn.close()
    url = "/api/approval-queue/detail?type=contractor_voucher&id=CV-APM2-1"
    sales = client.get(url, headers=_login(client, su, sp))
    assert sales.status_code == 200, sales.text
    assert sales.json().get("moneyMasked") is True
    assert not [f for f in sales.json()["files"] if f.get("id") == "passbook" or f.get("dataUrl")], sales.json()["files"]
    appr = client.get(url, headers=_login(client, au, ap)).json()
    assert [f for f in appr["files"] if f.get("id") == "passbook" and f.get("dataUrl", "").startswith("data:image/")]


def test_unreadable_chain_is_refused(client, iv_setup):
    sh, _ah = iv_setup
    _seed_iv("IV-AQP-3", "aqp_old", data_json="{not json")
    r = client.post("/api/approval-queue/reassign", headers=sh,
                    json={"type": "invoice_voucher", "id": "IV-AQP-3", "to_username": "aqp_new", "reason": "請假"})
    assert r.status_code == 400 and "格式不正確" in r.json()["detail"], r.text


# ── ⑤ M01 補案件名稱 ─────────────────────────────────────────────────────────

def test_case_names_are_filled_only_when_missing(client, monkeypatch):
    import db
    import routers.approval_queue as q          # 彙整在 L1；名稱經 case.summary（M01 提供）
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at) "
                     "VALUES ('MQ-AQP-9','成交','甲客戶','乙專案','{}','2026-09-26','2026-09-26')")
        conn.commit()
        items = [{"type": "t1", "linkedQuoteNo": "MQ-AQP-9"},
                 {"type": "t2", "linkedQuoteNo": "MQ-AQP-9", "customer": "", "projectName": "自己的"},
                 {"type": "t3", "linkedQuoteNo": "MQ-NONE"}]
        real = registry.providers
        monkeypatch.setattr(registry, "providers",
                            lambda cap: {"x": lambda c: [dict(i) for i in items]} if cap == "approval.queue_items" else real(cap))
        got = {it["type"]: it for it in q._queue_provider_items(conn)}
    finally:
        conn.close()
    assert (got["t1"]["customer"], got["t1"]["projectName"]) == ("甲客戶", "乙專案")
    assert (got["t2"]["customer"], got["t2"]["projectName"]) == ("", "自己的")
    assert (got["t3"]["customer"], got["t3"]["projectName"]) == ("", "")


# ── ⑦ 佇列在 L1、M01 是提供者（c-approval-l1，主持裁示 2026-09-27）────────────

def test_m01_quotation_reaches_the_l1_queue_through_its_provider(client, make_user):
    """M01 的報價單經 `approval.queue_items`（名稱 case，ModuleSpec 宣告）進 L1 佇列與角標。
    突變：拿掉 ModuleSpec 那一行 ⇒ 本題紅（佇列裡沒有報價單、角標 0）。"""
    import db
    from modules.case.api import quotations as q
    assert registry.providers("approval.queue_items").get("case") is q.approval_queue_items
    su, sp = make_user("aqp_l1_super", "Conn-Pass-123", role="superadmin")[:2]
    au, ap = make_user("aqp_l1_appr", "Conn-Pass-123", role="admin")[:2]
    appr = {"requestedBy": "aqp_l1_sales", "requestedByDisplay": "業務", "requestedAt": "2026-09-27T09:00:00",
            "currentTier": 0, "tiers": [{"approvers": [{"username": au, "displayName": au, "status": "pending"}]}]}
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at) "
                     "VALUES ('MQ-AQP-L1','待審核','甲客戶','乙專案',?,'2026-09-27','2026-09-27')",
                     (json.dumps({"approval": appr}),))
        conn.commit()
    finally:
        conn.close()
    sh, ah = _login(client, su, sp), _login(client, au, ap)
    d = client.get("/api/approval-queue", headers=sh).json()
    got = {it["quoteNo"]: it for g in d["queue"] for it in g["items"]}
    assert got["MQ-AQP-L1"]["type"] == "quotation" and got["MQ-AQP-L1"]["customer"] == "甲客戶", sorted(got)
    assert _count(client, ah) == 1
    r = client.get("/api/approval-queue/detail", params={"type": "quotation", "id": "MQ-AQP-L1"}, headers=ah)
    assert r.status_code == 200, r.text
    assert r.json()["case"] == {"quoteNo": "MQ-AQP-L1", "customerName": "甲客戶", "projectName": "乙專案", "dealTag": ""}


# ── ⑧ 已結案變更的 selfViewBy（稽核 D AL-M1）與查無／看不到同一句（AL-S1）──────────
#
# 兩個人都**沒有案件權限**（非 admin、沒有 case_manage、不是業務也不是協作者）才分得出來：
# 有權限的人不靠 selfViewBy 也看得到，拿掉它的突變就不會紅。

def _no_case_user(make_user, name):
    return make_user(name, "Conn-Pass-123", role="sales", modules=["quotation"])[:2]


def _seed_ccr(requested_by):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, sales_person, data_json, "
                     "created_at, updated_at, assigned_user_ids) VALUES ('MQ-AQP-CCR','成交','丙客戶','丁專案','別人','{}',"
                     "'2026-09-27','2026-09-27','[]')")
        cur = conn.execute("INSERT INTO case_change_requests (quote_no, action_type, summary, requested_by, requested_by_display, "
                           "requested_at) VALUES ('MQ-AQP-CCR','case_record_update','改備註',?,?,'2026-09-27T10:00:00')",
                           (requested_by, requested_by))
        conn.commit()
        return str(cur.lastrowid)
    finally:
        conn.close()


def test_case_change_detail_requester_without_case_access_sees_it(client, make_user):
    """申請人本人（沒有案件權限）看得到自己的已結案變更。突變「selfViewBy 不生效」⇒ 404 ⇒ 紅。"""
    ru, rp = _no_case_user(make_user, "aqp_ccr_req")
    cid = _seed_ccr(ru)
    r = client.get("/api/approval-queue/detail", params={"type": "case_change", "id": cid}, headers=_login(client, ru, rp))
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "已結案案件變更 #" + cid


def test_case_change_detail_outsider_gets_the_not_found_404(client, make_user):
    """外人（同樣沒有案件權限）打別人的已結案變更 ⇒ 404，與查無同一句、不帶案件單號。
    突變「不比對是不是本人」⇒ 200 ⇒ 紅。"""
    from routers.approval_queue import detail_not_found_message
    ru, _rp = _no_case_user(make_user, "aqp_ccr_req2")
    ou, op = _no_case_user(make_user, "aqp_ccr_out")
    cid = _seed_ccr(ru)
    oh = _login(client, ou, op)
    r = client.get("/api/approval-queue/detail", params={"type": "case_change", "id": cid}, headers=oh)
    assert r.status_code == 404 and r.json() == {"detail": detail_not_found_message(cid)}, r.text
    assert "MQ-AQP-CCR" not in r.text and "丙客戶" not in r.text
    missing = client.get("/api/approval-queue/detail", params={"type": "case_change", "id": "999999"}, headers=oh)
    assert missing.status_code == 404 and missing.json() == {"detail": detail_not_found_message("999999")}


def test_completion_note_not_found_and_denied_same_message(client, make_user):
    """M01 自己的查無訊息（「完工單不存在」）與看不到（原本回「報價單 MQ-X 不存在」，洩漏掛在哪一案）⇒ 同一句。"""
    import db
    from routers.approval_queue import detail_not_found_message
    ou, op = _no_case_user(make_user, "aqp_cn_out")
    conn = db.get_db()
    try:
        conn.execute("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, sales_person, data_json, "
                     "created_at, updated_at, assigned_user_ids) VALUES ('MQ-AQP-CN','成交','客','案','別人','{}',"
                     "'2026-09-27','2026-09-27','[]')")
        conn.execute("INSERT INTO completion_notes (note_no, quote_no, status, data_json, items_json, created_at, updated_at) "
                     "VALUES ('CN-AQP-1','MQ-AQP-CN','待審核','{}','[]','2026-09-27','2026-09-27')")
        conn.commit()
    finally:
        conn.close()
    oh = _login(client, ou, op)
    denied = client.get("/api/approval-queue/detail", params={"type": "completion_note", "id": "CN-AQP-1"}, headers=oh)
    missing = client.get("/api/approval-queue/detail", params={"type": "completion_note", "id": "CN-AQP-NOPE"}, headers=oh)
    assert denied.status_code == missing.status_code == 404
    assert denied.json() == {"detail": detail_not_found_message("CN-AQP-1")}, denied.text
    assert missing.json() == {"detail": detail_not_found_message("CN-AQP-NOPE")}, missing.text
    assert "MQ-AQP-CN" not in denied.text


# ── ⑨ 簽核 JSON 壞掉的報價單（稽核 D AL-O4：舊版整支佇列 500）────────────────────

def test_quotation_with_malformed_approval_json_does_not_break_the_queue(client, make_user, caplog):
    """壞 JSON 的報價單：佇列 200、**這一筆跳過並記 ERROR（寫單號）**、角標不算它；同一個提供者的其他報價單照列
    （壞一筆不可以讓整類消失）。〔更正〕~~列出它（沒有簽核層 ⇒ 任一 superadmin 可簽）、角標對 superadmin 計 1~~：
    c-queue-json 改成跳過（主持指派 2026-09-27）。理由：列出了也簽不了（核准端點讀這張單的 JSON 會丟 JSONDecodeError ⇒ 500、狀態不變；D 實測）。
    〔更正〕~~那是降級（簽核鏈讀不出來變成任一 superadmin 可簽）~~——D 實測核准端點 500、狀態不變，不是降級。
    能解析、沒有簽核層的報價單（沒有設定流程）照列：見 MQ-AQP-NOFLOW。"""
    import logging
    import db
    caplog.set_level(logging.ERROR)
    su, sp = make_user("aqp_bad_super", "Conn-Pass-123", role="superadmin")[:2]
    sh = _login(client, su, sp)
    before = _count(client, sh)
    ok_appr = {"requestedBy": "aqp_bad_sales", "requestedAt": "2026-09-27T09:00:00", "currentTier": 0,
               "tiers": [{"approvers": [{"username": "someone", "displayName": "someone", "status": "pending"}]}]}
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at) "
                     "VALUES ('MQ-AQP-BAD','待審核','客','案','{not json','2026-09-27','2026-09-27')")
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at) "
                     "VALUES ('MQ-AQP-OK','待審核','客','案',?,'2026-09-27','2026-09-27')", (json.dumps({"approval": ok_appr}),))
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at) "
                     "VALUES ('MQ-AQP-NOFLOW','待審核','客','案','{\"items\": []}','2026-09-27','2026-09-27')")
        conn.commit()
    finally:
        conn.close()
    r = client.get("/api/approval-queue", headers=sh)
    assert r.status_code == 200, r.text
    got = {it["quoteNo"]: it for g in r.json()["queue"] for it in g["items"]}
    assert "MQ-AQP-OK" in got and "MQ-AQP-BAD" not in got, sorted(got)
    assert "MQ-AQP-NOFLOW" in got and got["MQ-AQP-NOFLOW"]["tiers"] == [], "能解析、沒有流程的單要照列"
    assert any(r.levelno >= logging.ERROR and "MQ-AQP-BAD" in r.getMessage() for r in caplog.records)
    assert _count(client, sh) == before + 1        # 壞的那張不列也不算；OK 那張不是我簽；沒有流程的那張 ⇒ 任一 superadmin
