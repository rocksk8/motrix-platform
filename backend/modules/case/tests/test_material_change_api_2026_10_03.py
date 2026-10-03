# -*- coding: utf-8 -*-
"""33-M2b：材料申請變更申請的端點、簽核佇列／詳情提供者、通知、`use_change_request` 守門。狀態機本身見 test_material_change_core_2026_10_03。"""
import json

import pytest

import db
from helpers import tiered_approval as TA
from modules.case import material_approval as MA
from modules.case import material_change as MC
from modules.case.api import material_changes as API
from modules.case.tests.test_material_change_core_2026_10_03 import (  # noqa: F401
    IID, LINE1, LINE2, NO, W, _cp, _flow, _one_tier, _order, _order_now, _setup, reg, ENG, BOSS)

BASE = "/api/quotations/%s/material-orders/%s" % (NO, IID)


@pytest.fixture
def fake_proposal(monkeypatch):
    """案件側提案（2e 的 change_proposal）以假函式代替：qty 3、小計 3000、涵蓋兩行。"""
    def fn(conn, quote_no, item_id, proposed):
        cp = _cp()
        if "quantity" in (proposed or {}):
            cp["after"]["quantity"] = float(proposed["quantity"])
            cp["after"]["totalPrice"] = 1000.0 * float(proposed["quantity"])
        if "notes" in (proposed or {}):
            cp["after"]["notes"] = proposed["notes"]
        return cp
    monkeypatch.setattr(MC, "PROPOSAL_FN", fn)
    return fn


def _post(c, h, path, body=None):
    return c.post(path, headers=h, json=body or {})


def test_create_list_submit_auto_approve_and_apply_over_http(W, reg, fake_proposal):
    c, h = W
    _flow([])
    _setup(received="2026-10-04")
    r = _post(c, h, BASE + "/changes", {"reason": "追加一台"})
    assert r.status_code == 200, r.text
    ch = r.json()["change"]
    assert ch["status"] == "草稿" and ch["docCode"].startswith("MC-") and [d["field"] for d in ch["diff"]] == ["quantity", "totalPrice", "poSnapshot"]
    assert _order_now(db.get_db())["quantity"] == 2                                              # 草稿：原版不動
    lst = c.get(BASE + "/changes", headers=h).json()["changes"]
    assert [x["id"] for x in lst] == [ch["id"]]
    s = _post(c, h, "/api/quotations/%s/material-changes/%d/submit" % (NO, ch["id"]))
    assert s.status_code == 200 and s.json()["autoApproved"] and s.json()["applied"], s.text
    cn = db.get_db()
    try:
        assert _order_now(cn)["quantity"] == 3.0 and MA.get(cn, NO, IID)["version"] == 2 and MA.get(cn, NO, IID)["received_on"] == "2026-10-04"
    finally:
        cn.close()
    assert c.get(BASE + "/changes", headers=h).json()["changes"][0]["status"] == "已核准"


def test_create_rejects_amount_fields_missing_reason_and_unavailable_proposal(W, reg, monkeypatch, fake_proposal):
    c, h = W
    _setup()
    for body, code in (({"reason": "x", "totalPrice": 1}, 400), ({"reason": "x", "unitPrice": 1}, 400), ({}, 400), ({"reason": "  "}, 400)):
        assert _post(c, h, BASE + "/changes", body).status_code == code, body
    assert db.get_db().execute("SELECT COUNT(*) FROM case_material_changes").fetchone()[0] == 0
    monkeypatch.setattr(MC, "PROPOSAL_FN", None)
    monkeypatch.setattr(MC, "_proposal_fn", lambda: None)
    r = _post(c, h, BASE + "/changes", {"reason": "x"})
    assert r.status_code == 501 and c.get(BASE + "/change-proposal", headers=h).status_code == 501


def test_preview_proposal_passes_quantity_and_notes_and_is_read_only(W, reg, fake_proposal):
    c, h = W
    _setup()
    r = c.get(BASE + "/change-proposal?quantity=5&notes=hi", headers=h)
    assert r.status_code == 200 and r.json()["after"]["quantity"] == 5.0 and r.json()["after"]["notes"] == "hi"
    assert db.get_db().execute("SELECT COUNT(*) FROM case_material_changes").fetchone()[0] == 0


def test_wrong_quote_wrong_change_and_withdraw_over_http(W, reg, fake_proposal):
    c, h = W
    _one_tier()
    _setup()
    ch = _post(c, h, BASE + "/changes", {"reason": "追加"}).json()["change"]
    assert _post(c, h, "/api/quotations/NOPE/material-changes/%d/submit" % ch["id"]).status_code == 404
    assert _post(c, h, "/api/quotations/%s/material-changes/9999/submit" % NO).status_code == 404
    assert _post(c, h, "/api/quotations/%s/material-changes/%d/withdraw" % (NO, ch["id"])).json()["status"] == "已撤回"
    r = _post(c, h, "/api/quotations/%s/material-changes/%d/approve" % (NO, ch["id"]))
    assert r.status_code == 409                                                                  # 已撤回不能核准


def test_queue_items_and_detail_provider_show_the_diff(W, reg, fake_proposal):
    c, h = W
    _one_tier()
    _setup()
    ch = _post(c, h, BASE + "/changes", {"reason": "追加一台"}).json()["change"]
    assert API.queue_items(db.get_db()) == []                                                    # 草稿不進佇列
    assert _post(c, h, "/api/quotations/%s/material-changes/%d/submit" % (NO, ch["id"])).json()["status"] == "待審核"
    cn = db.get_db()
    try:
        items = API.queue_items(cn)
        assert len(items) == 1
        it = items[0]
        assert it["type"] == "material_change" and it["docCode"] == ch["docCode"] and it["typeLabel"] == "材料申請變更"
        assert it["approveUrl"].endswith("/material-changes/%d/approve" % ch["id"]) and it["rejectField"] == "reason" and "原 2.0 → 變更後 3.0" in it["projectName"]
        d = API.detail(cn, ch["docCode"])
        vals = {f["label"]: f["value"] for f in d["fields"]}
        assert vals["數量"] == "2 台 → 3 台" and vals["小計"] == "2,000 → 3,000" and "PO-2 #1" in vals["涵蓋採購單行"] and vals["變更原因"] == "追加一台"
        with pytest.raises(Exception):
            API.detail(cn, "MC-NOPE")
    finally:
        cn.close()


def test_view_hides_money_for_users_without_finance_view():
    row = {"id": 1, "doc_code": "MC-1", "quote_no": NO, "item_id": IID, "status": "草稿", "base_version": 1, "reason": "x", "created_by": "u", "created_at": "", "submitted_at": "",
           "approved_at": "", "applied_at": "", "approval_json": "{}",
           "diff_json": json.dumps([{"field": "quantity", "old": 2, "new": 3, "money": False}, {"field": "totalPrice", "old": 2000, "new": 3000, "money": True}]),
           "proposal_json": json.dumps({"quantity": 3, "unitPrice": 1000, "totalPrice": 3000, "poSnapshot": [{"poDocCode": "PO-1", "line": 1, "qty": 3, "amount": 3000}]}),
           "base_json": json.dumps({"quantity": 2, "unitPrice": 1000, "totalPrice": 2000, "poSnapshot": []})}
    v = API._view(row, False)
    assert v["diff"][0]["new"] == 3 and v["diff"][1]["new"] is None and v["diff"][1]["hidden"]
    assert "totalPrice" not in v["proposal"] and "amount" not in v["proposal"]["poSnapshot"][0] and v["proposal"]["quantity"] == 3
    assert API._view(row, True)["proposal"]["totalPrice"] == 3000


def test_notifications_fire_for_every_event_without_raising(W, reg, monkeypatch):
    sent = []
    from helpers import email_notify as EN
    monkeypatch.setattr(EN, "send_registered", lambda key, **k: sent.append(key) or True)
    from modules.case import material_notify as MN
    info = {"docCode": "MC-1", "quoteNo": NO, "itemName": "交換器"}
    for ev, kw in (("submitted", {"approvers": ["a"]}), ("next_tier", {"approvers": ["a"], "tier_no": 2, "total_tiers": 3}),
                   ("approved", {"requester": "r"}), ("returned", {"requester": "r", "reason": "不對"})):
        assert MN.fire_change(ev, info, **kw)
    assert sent == ["material_change_submitted", "material_change_next_tier", "material_change_approved", "material_change_returned"]


# ── use_change_request 守門 ───────────────────────────────────────────

def test_direct_edit_of_an_approved_post_rule_request_is_refused_but_non_substantive_edits_pass(W, reg):
    c, h = W
    _setup()
    f = json.dumps(_order_now(db.get_db()), sort_keys=True)
    r = c.patch("/api/quotations/%s/material-orders" % NO, headers=h, json={"materialOrders": [_order(quantity=3, totalPrice=3000)]})
    assert r.status_code == 200 and [x["code"] for x in r.json()["rejected"]] == ["use_change_request"]
    assert json.dumps(_order_now(db.get_db()), sort_keys=True) == f and MA.status_of(db.get_db(), NO, IID) == "已核准"      # 資料不變、狀態不變（沒有被打回草稿）
    r = c.patch("/api/quotations/%s/material-orders" % NO, headers=h, json={"materialOrders": [_order(notes="只是備註")]})
    assert r.status_code == 200 and not r.json().get("rejected") and _order_now(db.get_db())["notes"] == "只是備註"


def test_grandfathered_and_pre_rule_approved_requests_still_fall_back_to_draft_on_edit(W, reg):
    c, h = W
    for kw in ({"grandfathered": True}, {"created_at": "2026-09-20T00:00:00"}):
        _setup(**kw)
        r = c.patch("/api/quotations/%s/material-orders" % NO, headers=h, json={"materialOrders": [_order(quantity=3, totalPrice=3000)]})
        assert r.status_code == 200 and not r.json().get("rejected"), (kw, r.text)
        assert MA.status_of(db.get_db(), NO, IID) == "草稿" and _order_now(db.get_db())["quantity"] == 3     # 舊行為不變（改了回草稿）


def test_doc_type_is_registered_with_the_case_package_and_follows_the_unified_flow():
    assert MC.DOC_TYPE in TA.APPROVAL_DOC_TYPES and MC.DOC_TYPE in TA.DEFAULT_UNIFIED_DOC_TYPES and TA.APPROVAL_DOC_TYPE_LABELS[MC.DOC_TYPE] == "材料申請變更"


# ── 出貨連動接線（c7 的契約：dict 版 `shipping.material_shipped`、float 版 `shipping.material_shipped_qty`）────────────

def _fake_registry(monkeypatch, table):
    from core import registry
    monkeypatch.setattr(registry, "providers", lambda cap: table.get(cap, {}))


def test_shipped_provider_resolution_order_and_dict_wrapper(W, reg, monkeypatch, fake_proposal):
    c, h = W
    _setup()
    monkeypatch.setattr(MC, "SHIPPED_PROVIDER", None)
    _fake_registry(monkeypatch, {})
    assert MC._shipped_fn() is None                                                                    # 沒有任何提供者
    d = {"shipping.material_shipped": {"supply": lambda conn, qn: {IID: {"reserved": 1.0, "shipped": 3.0, "notes": ["SN-1"]}, "other": {"shipped": 99}}}}
    _fake_registry(monkeypatch, d)
    f = MC._shipped_fn()
    assert f(None, NO, IID) == 4.0 and f(None, NO, "none") == 0.0                                      # 保留＋已出貨；沒資料＝0
    r = _post(c, h, BASE + "/changes", {"reason": "追加"})                                              # 新數量 3 < 4 ⇒ 擋
    assert r.status_code == 409 and r.json()["detail"].startswith("新的數量低於已出貨")
    d["shipping.material_shipped"]["supply"] = lambda conn, qn: {IID: {"reserved": 0, "shipped": 2.0}}
    assert _post(c, h, BASE + "/changes", {"reason": "追加"}).status_code == 200                       # 2 ≤ 3 ⇒ 過
    qty = {"shipping.material_shipped_qty": {"supply": lambda conn, qn, item: 9.0}, **d}
    _fake_registry(monkeypatch, qty)
    assert MC._shipped_fn()(None, NO, IID) == 9.0                                                      # float 版優先於 dict 版
    monkeypatch.setattr(MC, "SHIPPED_PROVIDER", lambda conn, qn, item: 1.0)
    assert MC._shipped_fn()(None, NO, IID) == 1.0                                                      # 測試覆寫最優先


def test_case_level_list_returns_all_items_changes_newest_first_with_item_name(W, reg, fake_proposal):
    c, h = W
    _flow([])
    _setup()
    first = _post(c, h, BASE + "/changes", {"reason": "第一張"}).json()["change"]
    _post(c, h, "/api/quotations/%s/material-changes/%d/withdraw" % (NO, first["id"]))
    second = _post(c, h, BASE + "/changes", {"reason": "第二張"}).json()["change"]
    r = c.get("/api/quotations/%s/material-changes" % NO, headers=h)
    assert r.status_code == 200
    got = r.json()["changes"]
    assert [x["id"] for x in got] == [second["id"], first["id"]] and got[0]["itemName"] == "交換器" and got[1]["status"] == "已撤回"
    assert c.get("/api/quotations/NOPE/material-changes", headers=h).status_code == 404


# ── 真實的案件側提案（2e 的 material_coverage.change_proposal，不用假函式）─────────────────────────────

def test_real_change_proposal_end_to_end_create_apply_and_no_change_afterwards(W, reg, monkeypatch):
    from modules.case.tests.test_material_coverage_2026_10_03 import _approved_po, _line, _ln, _put_materials, _row
    monkeypatch.setattr(MC, "PROPOSAL_FN", None)                                                    # 真提案：走 material_coverage.change_proposal
    c, h = W
    _flow([])
    po1 = _approved_po(c, h, [_ln("a", 3, unitCost=1000, unit="台")])
    _put_materials([{"itemId": IID, "itemName": "交換器", "quantity": 3, "unit": "台", "unitPrice": 1000, "totalPrice": 3000, "quoteItemId": "a", "notes": "",
                     "paidStatus": "pending", "paidAmount": 0, "paidDate": "", "supplierId": 1, "poDocCode": po1["docCode"], "poLine": 1}], {IID: "已核准"})
    _row(IID, snapshot=[_line(po1["docCode"], 1, 3.0, 3000.0)], doc="MO-20261005-0001")
    assert _post(c, h, BASE + "/changes", {"reason": "x"}).status_code == 400                       # 還沒有新的採購單行 ⇒ 沒有變更
    po2 = _approved_po(c, h, [_ln("a", 2, unitCost=1000, unit="台")])
    pv = c.get(BASE + "/change-proposal", headers=h).json()
    assert pv["problems"] == [] and pv["after"]["quantity"] == 5.0 and pv["after"]["totalPrice"] == 5000.0 and [l["poDocCode"] for l in pv["uncoveredLines"]] == [po2["docCode"]]
    ch = _post(c, h, BASE + "/changes", {"reason": "追加 2 台"}).json()["change"]
    assert [d["field"] for d in ch["diff"]] == ["quantity", "totalPrice", "poSnapshot"]
    s = _post(c, h, "/api/quotations/%s/material-changes/%d/submit" % (NO, ch["id"]))
    assert s.status_code == 200 and s.json()["applied"], s.text
    cn = db.get_db()
    try:
        o = _order_now(cn)
        assert (o["quantity"], o["totalPrice"]) == (5.0, 5000.0)
        snap = json.loads(MA.get(cn, NO, IID)["approval_json"])["snapshot"]["poSnapshot"]
        assert [x["poDocCode"] for x in snap] == [po1["docCode"], po2["docCode"]]
    finally:
        cn.close()
    again = _post(c, h, BASE + "/changes", {"reason": "再來一次"})
    assert again.status_code == 400 and "沒有任何變更" in again.json()["detail"]                       # 套用後涵蓋已齊，不能再提空變更


def test_real_supply_provider_blocks_lowering_below_shipped_without_overriding_the_hook(W, reg, monkeypatch, fake_proposal):
    """da：不覆寫 `MC.SHIPPED_PROVIDER`，走真正的註冊表取 c7 的出貨連動提供者（modules/supply/material_link.py）：
    已核准的出貨單占用／已出貨 4 台，提案把數量降到 3 ⇒ 409 `change_below_shipped`；已出貨 ≤ 新數量就過。"""
    from core import registry
    if registry.providers("shipping.material_shipped_qty").get("supply") is None and registry.providers("shipping.material_shipped").get("supply") is None:
        pytest.skip("出貨連動提供者（shipping.material_shipped／_qty）不在這個安裝包")
    monkeypatch.setattr(MC, "SHIPPED_PROVIDER", None)                                                  # 明確不覆寫：驗註冊表那條路
    c, h = W
    _flow([])
    _setup(received="2026-10-04")
    r = c.post("/api/shipping-notes", headers=h, json={"quote_no": NO, "items": [{"description": "交換器", "materialLink": {"materialItemId": IID, "docCode": "MO-20261005-0001", "qty": 1}}]})
    assert r.status_code == 201, r.text
    note = r.json()["note_no"]
    cn = db.get_db()
    try:
        cn.execute("UPDATE shipping_notes SET status='已核准', items_json=? WHERE note_no=?",
                   (json.dumps([{"description": "交換器", "materialLink": {"materialItemId": IID, "docCode": "MO-20261005-0001", "qty": 4.0}}], ensure_ascii=False), note))
        cn.commit()
        assert MC._shipped_fn()(cn, NO, IID) == 4.0                                                    # 真提供者：已出貨 4（已核准的出貨單）
    finally:
        cn.close()
    r = _post(c, h, BASE + "/changes", {"reason": "追加"})                                              # 新數量 3 < 4
    assert r.status_code == 409 and "已出貨" in r.json()["detail"], r.text
    assert db.get_db().execute("SELECT COUNT(*) FROM case_material_changes").fetchone()[0] == 0
    cn = db.get_db()
    try:
        cn.execute("UPDATE shipping_notes SET items_json=? WHERE note_no=?",
                   (json.dumps([{"description": "交換器", "materialLink": {"materialItemId": IID, "docCode": "MO-20261005-0001", "qty": 3.0}}], ensure_ascii=False), note))
        cn.commit()
    finally:
        cn.close()
    assert _post(c, h, BASE + "/changes", {"reason": "追加"}).status_code == 200                       # 已出貨 3 ≤ 新數量 3 ⇒ 過



def test_audit_rows_really_land_after_commit_for_every_action(W, reg, fake_proposal):
    """稽核寫在自己的交易裡（不另開連線）：commit 之後另一條連線讀得到每個動作的 material_changes.* 稽核（create／submit／approve／apply／reject／withdraw／revise）。"""
    c, h = W
    _one_tier()
    _setup()
    ch = _post(c, h, BASE + "/changes", {"reason": "追加"}).json()["change"]
    _post(c, h, "/api/quotations/%s/material-changes/%d/revise" % (NO, ch["id"]), {"reason": "追加（改）"})
    _post(c, h, "/api/quotations/%s/material-changes/%d/submit" % (NO, ch["id"]))
    _post(c, h, "/api/quotations/%s/material-changes/%d/withdraw" % (NO, ch["id"]))
    _flow([])
    ch2 = _post(c, h, BASE + "/changes", {"reason": "再追加"}).json()["change"]
    assert _post(c, h, "/api/quotations/%s/material-changes/%d/submit" % (NO, ch2["id"])).json()["applied"]
    cn = db.get_db()                                                                                      # 全新連線：只看得到已 commit 的
    try:
        acts = {r[0] for r in cn.execute("SELECT action FROM audit_log WHERE action LIKE 'material_changes.%'")}
    finally:
        cn.close()
    assert {"material_changes.create", "material_changes.revise", "material_changes.submit", "material_changes.withdraw", "material_changes.apply"} <= acts, acts


def _walk_keys(v, acc):
    if isinstance(v, dict):
        for k, x in v.items():
            acc.add(k)
            _walk_keys(x, acc)
    elif isinstance(v, list):
        for x in v:
            _walk_keys(x, acc)
    return acc


def test_account_with_case_access_but_no_finance_view_gets_no_money_from_any_change_endpoint(W, reg, fake_proposal, make_user, client, monkeypatch):
    """da must-fix：有案件存取、沒有財務檢視權的帳號打三支讀取端點，回應任何地方（含差異的涵蓋行、uncoveredLines）都不可有 amount／unitPrice／totalPrice。"""
    c, h = W
    _flow([])
    _setup()
    base_fn = MC.PROPOSAL_FN

    def with_uncovered(conn, q, i, proposed):                                                           # 假提案補上 uncoveredLines（含行金額）與帶已付金額的 below_paid 問題
        cp = base_fn(conn, q, i, proposed)
        cp["uncoveredLines"] = [dict(LINE2)]
        cp["problems"] = [{"code": "below_paid", "message": "變更後小計低於已付金額 1500"}]
        return cp
    monkeypatch.setattr(MC, "PROPOSAL_FN", with_uncovered)
    u, p = make_user(username="mc_eng_nomoney", role="engineer", modules=["case_manage"])
    cn = db.get_db()
    try:
        uid = cn.execute("SELECT id FROM users WHERE username='mc_eng_nomoney'").fetchone()["id"]
        cn.execute("UPDATE quotations SET assigned_user_ids=? WHERE quote_no=?", (json.dumps([uid]), NO))
        cn.commit()
    finally:
        cn.close()
    monkeypatch.setattr(MC, "PROPOSAL_FN", base_fn)                                                     # 建立用無問題的提案
    ch = _post(c, h, BASE + "/changes", {"reason": "追加"}).json()["change"]
    monkeypatch.setattr(MC, "PROPOSAL_FN", with_uncovered)
    assert any(l.get("amount") for d in ch["diff"] if d["field"] == "poSnapshot" for l in d["new"])        # 有財務檢視權者看得到金額（對照）
    pv = c.get(BASE + "/change-proposal", headers=h).json()
    assert pv["uncoveredLines"][0]["amount"] == 1000.0 and "1500" in pv["problems"][0]["message"]         # 對照：財務檢視者看得到金額與已付數字
    lg = c.post("/api/auth/login", json={"username": u, "password": p})
    assert lg.status_code == 200, lg.text
    eh = {"Authorization": "Bearer " + lg.json()["token"]}
    got = {}
    for name, url in (("item", BASE + "/changes"), ("case", "/api/quotations/%s/material-changes" % NO), ("proposal", BASE + "/change-proposal")):
        r = c.get(url, headers=eh)
        assert r.status_code == 200, (name, r.text)
        got[name] = r.json()
        keys = _walk_keys(r.json(), set())
        assert not (keys & {"amount", "unitPrice", "totalPrice"}), (name, keys & {"amount", "unitPrice", "totalPrice"})
        assert "3000" not in r.text and "2000" not in r.text and "1500" not in r.text and "1000.0" not in r.text, (name, r.text[:300])      # 數值本身也不在（涵蓋行金額、已付）
    assert got["proposal"]["uncoveredLines"] and all("amount" not in x for x in got["proposal"]["uncoveredLines"])
    assert [d["field"] for d in got["item"]["changes"][0]["diff"]] == ["quantity", "totalPrice", "poSnapshot"]    # 數量與涵蓋行仍看得到，只有金額被遮


def test_history_comment_and_audit_label_of_an_applied_change_carry_no_money_numbers(W, reg, fake_proposal):
    """da 輸出面掃描：核准套用寫進審核歷程（approval_json）與稽核的差異摘要，金額欄位只寫「已變更」，不帶單價／小計的數字。"""
    c, h = W
    _flow([])
    _setup()
    ch = _post(c, h, BASE + "/changes", {"reason": "追加"}).json()["change"]
    assert _post(c, h, "/api/quotations/%s/material-changes/%d/submit" % (NO, ch["id"])).json()["applied"]
    cn = db.get_db()
    try:
        hist = json.loads(MA.get(cn, NO, IID)["approval_json"])["history"][-1]["comment"]
        labels = [r[0] for r in cn.execute("SELECT target_label FROM audit_log WHERE action='material_changes.apply'")]
        details = [r[0] for r in cn.execute("SELECT detail FROM audit_log WHERE action LIKE 'material_changes.%'")]
    finally:
        cn.close()
    for text in [hist] + labels + details:
        assert "3000" not in text and "2000" not in text and "1000" not in text, text
    assert "totalPrice 已變更" in hist and "quantity 2.0→3.0" in hist and "poSnapshot 1 行→2 行" in hist, hist
