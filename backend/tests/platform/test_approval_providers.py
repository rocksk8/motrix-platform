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

BACKEND = Path(__file__).resolve().parents[2]
#: 別的模組的單據表（2026-09-26 前 M01 的三支端點逐表直寫的那些）
FOREIGN_TABLES = ("contractor_payment_vouchers", "invoice_vouchers", "payment_requests", "shipping_notes",
                  "vouchers_all", "voucher_lines", "bonus_awards", "bonus_case_awards")
M01_FUNCS = ("get_approval_queue", "get_approval_queue_count", "reassign_approval", "_queue_provider_items",
             "approval_queue_detail")


def _funcs(src, names):
    tree = ast.parse(src)
    return {n.name: ast.get_source_segment(src, n) for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name in names}


def test_m01_endpoints_do_not_touch_other_modules_tables():
    src = (BACKEND / "routers" / "quotations.py").read_text(encoding="utf-8")
    found = _funcs(src, M01_FUNCS)
    assert set(found) == set(M01_FUNCS), sorted(found)
    bad = {f: [t for t in FOREIGN_TABLES if t in body] for f, body in found.items()}
    bad = {f: ts for f, ts in bad.items() if ts}
    assert not bad, "M01 佇列／角標／轉簽仍直接碰其他模組的單據表 ⇒ 改由擁有模組提供（M01-PLAN §3-7）：%s" % bad


def _expected_reassign_types():
    out = {"quotation", "completion_note"}                                # M01 本身
    if source_tree.module_installed("modules/accounting/"):                  # M06（2026-09-26 搬進模組）
        out.add("voucher")
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


def test_every_foreign_detail_type_has_one_provider(client):
    """M01 自己的四種（報價單、完工單、額外支出、已結案變更）在端點內；其他模組的單據各有一個 `approval.detail`。"""
    want = set()
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
    assert _detail(client, _login(client, ou, op), "IV-AQP-5").status_code == 403


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

def test_m01_fills_case_names_only_when_missing(client, monkeypatch):
    import db
    from routers import quotations as q
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at) "
                     "VALUES ('MQ-AQP-9','成交','甲客戶','乙專案','{}','2026-09-26','2026-09-26')")
        conn.commit()
        items = [{"type": "t1", "linkedQuoteNo": "MQ-AQP-9"},
                 {"type": "t2", "linkedQuoteNo": "MQ-AQP-9", "customer": "", "projectName": "自己的"},
                 {"type": "t3", "linkedQuoteNo": "MQ-NONE"}]
        monkeypatch.setattr(registry, "providers",
                            lambda cap: {"x": lambda c: [dict(i) for i in items]} if cap == "approval.queue_items" else {})
        got = {it["type"]: it for it in q._queue_provider_items(conn)}
    finally:
        conn.close()
    assert (got["t1"]["customer"], got["t1"]["projectName"]) == ("甲客戶", "乙專案")
    assert (got["t2"]["customer"], got["t2"]["projectName"]) == ("", "自己的")
    assert (got["t3"]["customer"], got["t3"]["projectName"]) == ("", "")
