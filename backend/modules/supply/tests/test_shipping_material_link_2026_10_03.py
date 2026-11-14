# -*- coding: utf-8 -*-
"""33-S1：出貨單連動材料申請（契約 docs/platform/plans/SHIPPING-MATERIAL-LINK-CONTRACT-S1.md）。
- 提供者 `shipping.material_shipped`：reserved（待審核／簽核中）、shipped（已核准）；草稿、已退回不計；`exclude_note_no`
- 提供者 `material.shippable`（case）：只回已核准且已到貨者；到貨量全數
- 出貨單送審／核准檢查：超量 `ship_exceeds_arrived`、無效連結 `ship_link_invalid`、M01 不在 `ship_link_module_off`；核准時再檢（競態）
- T86：連結與序號同列並存（原互斥放寬）：序號筆數 ≤ 連結數量 `ship_link_serial_qty`、**逐個序號**須為這個案件這筆材料申請入庫的 `ship_link_serial_part`；只有連結／只有序號的列不變
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


# ── T86：連結與庫存序號同列並存（原 33-S1 互斥 `ship_link_serial_exclusive` 放寬；改成兩邊都要驗證一致）──────────────

def _stock(part, serials, item=ITEM, mode="stock", quote=Q):
    """直接寫一批入庫（序號在庫、批次記到這筆材料申請）；`mode='direct'` 只留批次表頭。"""
    import db
    c = db.get_db()
    try:
        c.execute("INSERT OR IGNORE INTO parts (part_no, name, active, cost, created_at, updated_at) VALUES (?,?,1,0,?,?)", (part, "料", "2026-01-01", "2026-01-01"))
        batch = "B-%s-%s-%s-%s" % (part, item, mode, quote)
        c.execute("INSERT INTO stock_batches (batch_no, part_no, created_by, created_at, updated_at, quote_no, po_doc_code, material_item_id, delivery_mode) VALUES (?,?,?,?,?,?,?,?,?)",
                  (batch, part, "t", "2026-01-01", "2026-01-01", quote, "", item, mode))
        for sn in serials:
            c.execute("INSERT INTO stock_items (part_no, serial_no, status, batch_no, created_by, created_at, updated_at, material_item_id) VALUES (?,?,'in_stock',?,?,?,?,?)",
                      (part, sn, batch, "t", "2026-01-01", "2026-01-01", item))
        c.commit()
    finally:
        c.close()


def _stock_status(part, sn):
    import db
    c = db.get_db()
    try:
        return c.execute("SELECT status FROM stock_items WHERE part_no=? AND serial_no=?", (part, sn)).fetchone()["status"]
    finally:
        c.close()


def test_link_and_serials_coexist_when_consistent_and_stock_is_deducted(world):
    client, h = world
    _stock("P1", ["S1", "S2", "S3"])
    no = _note(client, h, [L(2, part_no="P1", serials=["S1", "S2"])])                  # 存檔：只擋序號筆數 ≤ 連結數量
    r = client.post("/api/shipping-notes/%s/submit" % no, headers=h)
    assert r.status_code == 200, r.text
    r = client.post("/api/shipping-notes/%s/approve" % no, headers=h, json={})                # 核准才扣庫存（送審只檢查）
    assert r.status_code == 200, r.text
    assert _stock_status("P1", "S1") == "shipped" and _stock_status("P1", "S2") == "shipped" and _stock_status("P1", "S3") == "in_stock"
    c, shipped, _s = _providers()
    try:
        assert shipped(c, Q)[ITEM]["reserved"] + shipped(c, Q)[ITEM]["shipped"] == 2.0   # 連結數量照舊占用材料申請的到料量，序號不另外重複計
    finally:
        c.close()


def test_coexist_row_with_more_serials_than_link_qty_is_refused_at_save(world):
    client, h = world
    r = client.post("/api/shipping-notes", headers=h, json={"quote_no": Q, "items": [L(1, part_no="P1", serials=["S1", "S2"])]})
    assert r.status_code == 400 and r.json()["code"] == "ship_link_serial_qty"
    r = client.post("/api/shipping-notes", headers=h, json={"quote_no": Q, "items": [L(1, part_no="P1", serials="S1")]})
    assert r.status_code == 400 and r.json()["code"] == "ship_link_invalid"


def test_every_serial_must_be_received_for_that_material_request(world):
    client, h = world
    _stock("P1", ["S1"])
    _stock("PX", ["X1"], item="it2")                                                   # 另一筆材料申請入庫的料號
    no = _note(client, h, [L(1, part_no="PX", serials=["X1"])])
    r = client.post("/api/shipping-notes/%s/submit" % no, headers=h)
    assert r.status_code == 400 and r.json()["code"] == "ship_link_serial_part"
    assert _status(no) == "草稿" and _stock_status("PX", "X1") == "in_stock"
    none = _note(client, h, [L(1, part_no="PZ", serials=["Z1"])])                      # 這筆材料申請完全沒有入庫紀錄
    assert client.post("/api/shipping-notes/%s/submit" % none, headers=h).json()["code"] == "ship_link_serial_part"
    _stock("PD", ["D1"], mode="direct")                                                # 直送批次沒有序號，不算「入庫過的料號」
    d = _note(client, h, [L(1, part_no="PD", serials=["D1"])])
    assert client.post("/api/shipping-notes/%s/submit" % d, headers=h).json()["code"] == "ship_link_serial_part"


@pytest.mark.parametrize("other_item,other_quote", [("it2", Q), ("", ""), (ITEM, "MQ-OTHER")], ids=["other-material-request", "generic-stock", "other-case"])
def test_same_part_serial_from_elsewhere_cannot_hang_on_the_link(world, other_item, other_quote):
    client, h = world
    _stock("P1", ["S1"])                                                               # 為這筆材料申請入庫的（正確）
    _stock("P1", ["X1"], item=other_item, quote=other_quote)                           # 同料號、但是另一筆材料申請／一般庫存／別案的
    bad = _note(client, h, [L(2, part_no="P1", serials=["S1", "X1"])])
    r = client.post("/api/shipping-notes/%s/submit" % bad, headers=h)
    assert r.status_code == 400 and r.json()["code"] == "ship_link_serial_part" and "X1" in r.json()["detail"]
    assert _status(bad) == "草稿" and _stock_status("P1", "S1") == "in_stock" and _stock_status("P1", "X1") == "in_stock"
    _set(bad, status="待審核")                                                         # 核准時同樣擋
    r = client.post("/api/shipping-notes/%s/approve" % bad, headers=h, json={})
    assert r.status_code == 400 and r.json()["code"] == "ship_link_serial_part"
    assert _status(bad) == "待審核" and _stock_status("P1", "S1") == "in_stock"
    ok = _note(client, h, [L(1, part_no="P1", serials=["S1"])])                         # 只掛正確的序號 ⇒ 通過並扣庫
    assert client.post("/api/shipping-notes/%s/submit" % ok, headers=h).status_code == 200
    assert client.post("/api/shipping-notes/%s/approve" % ok, headers=h, json={}).status_code == 200
    assert _stock_status("P1", "S1") == "shipped" and _stock_status("P1", "X1") == "in_stock"


def test_approve_rechecks_coexist_part(world):
    client, h = world
    _stock("P1", ["S1"])
    no = _note(client, h, [L(1, part_no="P1", serials=["S1"])], status="待審核")
    import db
    c = db.get_db()
    c.execute("DELETE FROM stock_batches WHERE quote_no=? AND material_item_id=?", (Q, ITEM))   # 送審之後入庫紀錄被撤掉
    c.commit()
    c.close()
    r = client.post("/api/shipping-notes/%s/approve" % no, headers=h, json={})
    assert r.status_code == 400 and r.json()["code"] == "ship_link_serial_part"
    assert _status(no) == "待審核" and _stock_status("P1", "S1") == "in_stock"


def test_rows_with_only_a_link_or_only_serials_behave_as_before(world):
    client, h = world
    _stock("P1", ["S1"])
    no = _note(client, h, [L(2), {"description": "庫存品", "part_no": "P1", "serials": ["S1"], "qty": 1}])   # 兩個不同列：一列只有連結、一列只有序號
    assert client.post("/api/shipping-notes/%s/submit" % no, headers=h).status_code == 200
    assert client.post("/api/shipping-notes/%s/approve" % no, headers=h, json={}).status_code == 200
    assert _stock_status("P1", "S1") == "shipped"


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


# ── 34-S2：出貨單頁清單端點、簽核人詳情 ──────────────────────────────────────

def test_shippable_endpoint_lists_arrived_items_with_remaining_and_excludes_the_note_itself(world):
    client, h = world
    other = _note(client, h, [L(4)], status="待審核")                      # 別張單據占用 4
    mine = _note(client, h, [L(3)])                                         # 本張草稿（草稿不占用；排除自己也不影響）
    r = client.get("/api/shipping-notes/material-shippable", params={"quote_no": Q, "note_no": mine}, headers=h)
    assert r.status_code == 200, r.text
    it = r.json()["items"]
    assert [(x["materialItemId"], x["docCode"], x["arrivedQty"], x["reserved"], x["shipped"], x["remaining"]) for x in it] == [(ITEM, DOC, 10.0, 4.0, 0.0, 6.0)]
    assert it[0]["name"] == "電纜" and it[0]["unit"] == "捲"
    _set(other, status="已核准")
    again = client.get("/api/shipping-notes/material-shippable", params={"quote_no": Q}, headers=h).json()["items"][0]
    assert (again["reserved"], again["shipped"], again["remaining"]) == (0.0, 4.0, 6.0)


def test_shippable_endpoint_permissions(world, client, make_user):
    c, h = world
    u, p = make_user(username="sl_plain", role="sales", modules=["quotation"])
    h2 = _login(client, u, p)
    assert client.get("/api/shipping-notes/material-shippable", params={"quote_no": Q}, headers=h2).status_code in (403, 404)
    assert client.get("/api/shipping-notes/material-shippable", params={"quote_no": Q}).status_code in (401, 403)


def test_approver_detail_shows_the_linked_material_request(world):
    client, h = world
    _note(client, h, [L(4)], status="已核准")                                # 其他單據已出貨 4
    mine = _note(client, h, [L(3)], status="待審核")
    import db
    from modules.supply.api import shipping_notes as sn
    c = db.get_db()
    try:
        d = sn._queue_detail(c, mine)
        f = [x for x in d["fields"] if x["label"] == "對應材料申請"]
        assert len(f) == 1 and DOC in f[0]["value"] and "電纜" in f[0]["value"] and "本單 3捲" in f[0]["value"] and "累計 4" in f[0]["value"] and "已到料 10" in f[0]["value"], f
        plain = sn._queue_detail(c, _note(client, h, [{"description": "一般"}], status="待審核"))
        assert not [x for x in plain["fields"] if x["label"] == "對應材料申請"]       # 沒有連結的單據詳情不變
    finally:
        c.close()
