# -*- coding: utf-8 -*-
"""33-S1：出貨單連動材料申請（契約 docs/platform/plans/SHIPPING-MATERIAL-LINK-CONTRACT-S1.md）。
- 提供者 `shipping.material_shipped`：reserved（待審核／簽核中）、shipped（已核准）；草稿、已退回不計；`exclude_note_no`
- 提供者 `material.shippable`（case）：只回已核准且已到貨者；到貨量全數
- 出貨單送審／核准檢查：超量 `ship_exceeds_arrived`、無效連結 `ship_link_invalid`、序號互斥、M01 不在 `ship_link_module_off`；核准時再檢（競態）
- 無 materialLink 的出貨單行為不變；E6 警示端點
- AST 守門：supply 不 import case
⚙️ 突變：拿掉核准時重檢／草稿也計占用／拿掉超量比較 ⇒ 紅。"""
import ast
import json
from pathlib import Path

import pytest

from tests._requires import requires_module

pytestmark = requires_module("case", "出貨連動需要 M01 的材料申請")

Q = "MQ-SL-001"
ITEM = "it1"
DOC = "MO-SL-1"


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def world(client, make_user, monkeypatch):
    from modules.supply.api import shipping_notes as _sn
    monkeypatch.setattr(_sn, "_setting_to_active_tiers", lambda setting, conn, username: [])      # 不設簽核層＝送審即核准；本檔驗的是連結檢查，不是簽核流程
    import db
    u, p = make_user(username="sl_super", role="superadmin")
    h = _login(client, u, p)
    c = db.get_db()
    try:
        data = {"caseRecord": {"materialOrders": [{"itemId": ITEM, "itemName": "電纜", "quantity": 10, "unit": "捲", "quoteItemId": "q1"},
                                                  {"itemId": "it2", "itemName": "螺絲", "quantity": 5, "unit": "盒"}]}}
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?)", (Q, "已送出", "客戶", "工程", 1000, 952, json.dumps(data), "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"))
        for iid, doc, status, rec in ((ITEM, DOC, "已核准", "2026-10-02"), ("it2", "MO-SL-2", "已核准", "")):
            c.execute("INSERT INTO case_material_approvals (quote_no, item_id, doc_code, status, received_on) VALUES (?,?,?,?,?)", (Q, iid, doc, status, rec))
        c.commit()
    finally:
        c.close()
    return client, h


def _note(client, h, items, status="草稿"):
    r = client.post("/api/shipping-notes", headers=h, json={"quote_no": Q, "items": items})
    assert r.status_code == 201, r.text
    no = r.json()["note_no"]
    if status != "草稿":
        _set(no, status=status)
    return no


def _set(no, status=None, items=None):
    import db
    c = db.get_db()
    try:
        if status is not None:
            c.execute("UPDATE shipping_notes SET status=? WHERE note_no=?", (status, no))
        if items is not None:
            c.execute("UPDATE shipping_notes SET items_json=? WHERE note_no=?", (json.dumps(items, ensure_ascii=False), no))
        c.commit()
    finally:
        c.close()


def _status(no):
    import db
    c = db.get_db()
    try:
        return c.execute("SELECT status FROM shipping_notes WHERE note_no=?", (no,)).fetchone()["status"]
    finally:
        c.close()


def L(qty, item=ITEM, doc=DOC, **extra):
    d = {"description": "電纜", "materialLink": {"materialItemId": item, "docCode": doc, "qty": qty}}
    d.update(extra)
    return d


def _providers():
    from core import registry
    import db
    c = db.get_db()
    return c, registry.providers("shipping.material_shipped")["supply"], registry.providers("material.shippable")["case"]


# ── 提供者 ────────────────────────────────────────────────────────────────

def test_material_shippable_returns_only_approved_and_received(world):
    c, _shipped, shippable = _providers()
    try:
        rows = shippable(c, Q)
    finally:
        c.close()
    assert [(r["materialItemId"], r["docCode"], r["appliedQty"], r["arrivedQty"], r["status"]) for r in rows] == [(ITEM, DOC, 10.0, 10.0, "已核准")]
    assert rows[0]["name"] == "電纜" and rows[0]["unit"] == "捲" and rows[0]["quoteItemId"] == "q1"


def test_material_shipped_counts_reserved_and_shipped_but_not_draft_or_returned(world):
    client, h = world
    for st, q in (("草稿", 1), ("待審核", 2), ("簽核中", 3), ("已核准", 4), ("已退回", 8)):
        _note(client, h, [L(q)], status=st)
    c, shipped, _s = _providers()
    try:
        r = shipped(c, Q)
        assert r[ITEM]["reserved"] == 5.0 and r[ITEM]["shipped"] == 4.0 and len(r[ITEM]["notes"]) == 3
        first = r[ITEM]["notes"][0]
        r2 = shipped(c, Q, exclude_note_no=first)
        assert r2[ITEM]["reserved"] + r2[ITEM]["shipped"] < r[ITEM]["reserved"] + r[ITEM]["shipped"]
        assert shipped(c, "NO-SUCH") == {}
    finally:
        c.close()


def test_material_shipped_qty_is_reserved_plus_shipped(world):
    from core import registry
    client, h = world
    for st, q in (("草稿", 1), ("待審核", 2), ("簽核中", 3), ("已核准", 4), ("已退回", 8)):
        _note(client, h, [L(q)], status=st)
    import db
    fn = registry.providers("shipping.material_shipped_qty")["supply"]
    c = db.get_db()
    try:
        assert fn(c, Q, ITEM) == 9.0                                           # 2＋3＋4；草稿與已退回不計
        assert fn(c, Q, "it2") == 0.0 and fn(c, "NO-SUCH", ITEM) == 0.0 and isinstance(fn(c, Q, ITEM), float)
    finally:
        c.close()


# ── 送審檢查 ──────────────────────────────────────────────────────────────

def test_submit_within_arrived_ok_and_over_is_400_with_code(world):
    client, h = world
    ok = _note(client, h, [L(10)])
    assert client.post("/api/shipping-notes/%s/submit" % ok, headers=h).status_code == 200
    over = _note(client, h, [L(1)])                                       # 已被另一單占用 10 ⇒ 再 1 就超量
    r = client.post("/api/shipping-notes/%s/submit" % over, headers=h)
    assert r.status_code == 400 and r.json()["code"] == "ship_exceeds_arrived" and "電纜" in r.json()["detail"]
    assert _status(over) == "草稿"


def test_same_note_lines_are_summed(world):
    client, h = world
    no = _note(client, h, [L(6), L(5)])
    r = client.post("/api/shipping-notes/%s/submit" % no, headers=h)
    assert r.status_code == 400 and r.json()["code"] == "ship_exceeds_arrived"


def test_returned_notes_release_the_quantity(world):
    client, h = world
    a = _note(client, h, [L(10)])
    assert client.post("/api/shipping-notes/%s/submit" % a, headers=h).status_code == 200
    _set(a, status="已退回")                                               # 退回核准＝釋放
    b = _note(client, h, [L(10)])
    assert client.post("/api/shipping-notes/%s/submit" % b, headers=h).status_code == 200


@pytest.mark.parametrize("item,doc", [("it2", "MO-SL-2"), ("nope", "X"), (ITEM, "WRONG-DOC")])
def test_link_to_unreceived_unknown_or_mismatched_doc_is_invalid(world, item, doc):
    client, h = world
    no = _note(client, h, [L(1, item=item, doc=doc)])
    r = client.post("/api/shipping-notes/%s/submit" % no, headers=h)
    assert r.status_code == 400 and r.json()["code"] == "ship_link_invalid"


def test_cancelled_approval_cannot_be_linked(world):
    client, h = world
    import db
    c = db.get_db()
    c.execute("UPDATE case_material_approvals SET status='已取消' WHERE quote_no=? AND item_id=?", (Q, ITEM))
    c.commit()
    c.close()
    no = _note(client, h, [L(1)])
    assert client.post("/api/shipping-notes/%s/submit" % no, headers=h).json()["code"] == "ship_link_invalid"


def test_serials_and_link_on_the_same_row_are_refused_at_save(world):
    client, h = world
    r = client.post("/api/shipping-notes", headers=h, json={"quote_no": Q, "items": [L(1, part_no="P1", serials=["S1"])]})
    assert r.status_code == 400 and r.json()["code"] == "ship_link_serial_exclusive"


@pytest.mark.parametrize("bad", [{"materialItemId": "", "docCode": DOC, "qty": 1}, {"materialItemId": ITEM, "docCode": DOC, "qty": 0},
                                 {"materialItemId": ITEM, "docCode": DOC, "qty": "3"}, {"materialItemId": ITEM, "docCode": DOC, "qty": True}, "x"])
def test_malformed_link_is_refused_at_save(world, bad):
    client, h = world
    r = client.post("/api/shipping-notes", headers=h, json={"quote_no": Q, "items": [{"description": "x", "materialLink": bad}]})
    assert r.status_code == 400 and r.json()["code"] == "ship_link_invalid"


def test_module_off_when_case_provider_absent(world, monkeypatch):
    client, h = world
    from core import registry
    real = registry.single_provider
    monkeypatch.setattr(registry, "single_provider", lambda cap: None if cap == "material.shippable" else real(cap))
    no = _note(client, h, [L(1)])
    r = client.post("/api/shipping-notes/%s/submit" % no, headers=h)
    assert r.status_code == 400 and r.json()["code"] == "ship_link_module_off"


# ── 核准時再檢查（競態）──────────────────────────────────────────────────

def test_approve_rechecks_and_refuses_when_another_note_took_the_quantity(world):
    client, h = world
    a = _note(client, h, [L(8)])
    assert client.post("/api/shipping-notes/%s/submit" % a, headers=h).status_code == 200
    b = _note(client, h, [L(1)])
    assert client.post("/api/shipping-notes/%s/submit" % b, headers=h).status_code == 200
    # 競態：送審之後，另一張單據把量占掉（直接寫入模擬另一個請求）；b 先退回草稿再回待審核模擬「b 在排隊簽核」
    _note(client, h, [L(5)], status="待審核")
    _set(b, status="待審核")
    r = client.post("/api/shipping-notes/%s/approve" % b, headers=h, json={})
    assert r.status_code == 400 and r.json()["code"] == "ship_exceeds_arrived"
    assert _status(b) == "待審核"


# ── 不變：沒有連結的出貨單；E6 警示 ────────────────────────────────────────

def test_notes_without_links_behave_exactly_as_before(world):
    client, h = world
    no = _note(client, h, [{"description": "一般品項"}])
    r = client.post("/api/shipping-notes/%s/submit" % no, headers=h)
    assert r.status_code == 200, r.text


def test_unlinked_warning_lists_received_items_with_remaining_quantity(world):
    client, h = world
    no = _note(client, h, [{"description": "一般品項"}])
    r = client.get("/api/shipping-notes/%s/material-link-check" % no, headers=h)
    assert r.status_code == 200 and [(x["materialItemId"], x["remaining"]) for x in r.json()["unlinked"]] == [(ITEM, 10.0)]
    _set(no, items=[L(4)])
    assert client.get("/api/shipping-notes/%s/material-link-check" % no, headers=h).json()["unlinked"] == []        # 已連結
    _note(client, h, [L(10)], status="已核准")                                                                       # 被別單用光 ⇒ 不再警示
    _set(no, items=[{"description": "一般品項"}])
    assert client.get("/api/shipping-notes/%s/material-link-check" % no, headers=h).json()["unlinked"] == []


def test_warning_endpoint_hides_notes_you_cannot_read(world, client, make_user):
    c, h = world
    no = _note(c, h, [{"description": "x"}])
    u, p = make_user(username="sl_out", role="sales", modules=["quotation"])
    r = client.get("/api/shipping-notes/%s/material-link-check" % no, headers=_login(client, u, p))
    assert r.status_code == 404


def test_supply_does_not_import_case():
    root = Path(__file__).resolve().parents[1]
    bad = []
    for f in root.rglob("*.py"):
        if "tests" in f.parts:
            continue
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            mods = [n.module] if isinstance(n, ast.ImportFrom) and n.module else [a.name for a in n.names] if isinstance(n, ast.Import) else []
            bad += [(f.name, m) for m in mods if m.startswith("modules.case")]
    assert not bad, bad
