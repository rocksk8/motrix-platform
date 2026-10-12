# -*- coding: utf-8 -*-
"""完工單「從報價單帶入項目」核心（第 57 班；設計 COMPLETION-NOTE-QUOTE-ITEMS-T56）：
端點白名單、路由順序、狀態閘、累計、quoteSync 協議、超量政策、設定預設值、前端靜態守門。"""
import json
from pathlib import Path

import pytest

import db
from modules.case import completion_sync as CS

BASE = "/api/completion-notes"
QI = BASE + "/quote-items"
REPO = Path(__file__).resolve().parents[4]

ITEMS = [
    {"id": "it-1", "description": "攝影機", "brand": "某牌", "qty": 10, "unit": "台",
     "cost": 100, "margin": 30, "unitPrice": 150, "amount": 1500, "notes": "內部提醒：成本偏低", "secretKey": "x"},
    {"id": "hd-1", "type": "header", "description": "二、配線"},
    {"id": "it-2", "description": "線材", "qty": 5, "unit": "批", "unitPrice": 20, "amount": 100},
    {"description": "舊資料沒有編號", "qty": 2, "unit": "式"},
]


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _admin(client, make_user, name="qi_admin"):
    u, p = make_user(username=name, role="admin")
    return _login(client, u, p)


def _quote(no="MQ-QI-001", status="已送出", items=None, signed=1, extra=None):
    data = {"items": ITEMS if items is None else items, "deliveryAddress": "台中市西屯區 1 號",
            "contactName": "陳經理", "contactPhone": "04-0000"}
    data.update(extra or {})
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM quotations WHERE quote_no=?", (no,))
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, "
            "created_at, updated_at, deal_tag, is_signed) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (no, status, "測試客戶", "測試專案", 1, 1, json.dumps(data, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "", signed))
        conn.commit()
    finally:
        conn.close()
    return no


def _set_quote_data(no, items):
    conn = db.get_db()
    try:
        d = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (no,)).fetchone()[0])
        d["items"] = items
        conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), no))
        conn.commit()
    finally:
        conn.close()


def _note(client, h, no, items, **over):
    body = {"quote_no": no, "items": items, "completion_date": "2026-09-10"}
    body.update(over)
    r = client.post(BASE, headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()["note_no"]


def _set_status(note_no, status):
    conn = db.get_db()
    try:
        conn.execute("UPDATE completion_notes SET status=? WHERE note_no=?", (status, note_no))
        conn.commit()
    finally:
        conn.close()


def _row(qid, qty, status="完成", **kw):
    d = {"description": "x", "qty": qty, "unit": "台", "status": status, "quoteItemId": qid}
    d.update(kw)
    return d


def _qi(client, h, no="MQ-QI-001", **params):
    return client.get(QI, params=dict(quote_no=no, **params), headers=h)


# ── 白名單（金額永遠不出）──────────────────────────────────────────────────────

def test_response_keys_are_the_non_money_allowlist_only(client, make_user):
    h = _admin(client, make_user)
    no = _quote()
    r = _qi(client, h, no)
    assert r.status_code == 200, r.text
    allowed = set(CS.SAFE_ITEM_KEYS) | {"alreadyCompleted", "remaining", "tracked"}
    for it in r.json()["items"]:
        assert set(it) <= allowed, it
    txt = json.dumps(r.json(), ensure_ascii=False)
    for needle in ("cost", "margin", "unitPrice", "amount", "內部提醒", "secretKey", "1500"):
        assert needle not in txt, needle


def test_safe_keys_exclude_money_even_if_someone_adds_a_money_key_to_the_allowlist():
    from helpers.financial_mask import ITEM_MONEY_KEYS
    assert not set(CS.SAFE_ITEM_KEYS) & set(ITEM_MONEY_KEYS)
    mutated = tuple(k for k in CS.ALLOWED_ITEM_KEYS + ("unitPrice", "amount") if k not in ITEM_MONEY_KEYS)
    assert mutated == CS.SAFE_ITEM_KEYS


def test_source_items_ignore_unknown_and_money_keys():
    out = CS.source_items({"items": ITEMS})
    for it in out:
        assert set(it) <= set(CS.SAFE_ITEM_KEYS)
    assert [i["description"] for i in out] == ["攝影機", "二、配線", "線材", "舊資料沒有編號"]
    assert out[3]["id"] == ""                              # 舊資料沒有編號 ⇒ 無法追蹤


def test_header_block_comes_from_quotation(client, make_user):
    h = _admin(client, make_user)
    j = _qi(client, h, _quote()).json()
    assert j["header"] == {"customerName": "測試客戶", "projectName": "測試專案", "siteAddress": "台中市西屯區 1 號",
                           "recipient": "陳經理", "contactPhone": "04-0000"}
    assert j["sourceState"] == "signed" and j["warnings"] == []


# ── 路由順序與權限 ─────────────────────────────────────────────────────────────

def test_static_route_is_not_swallowed_by_note_no(client, make_user):
    h = _admin(client, make_user)
    r = _qi(client, h, _quote())
    assert r.status_code == 200 and "items" in r.json()                 # 不是「完工單不存在」
    assert client.get(QI, headers=h).status_code == 422                 # 缺 quote_no ⇒ 驗證錯誤，仍是這支端點


def test_route_registered_before_note_no_route():
    import modules.case as C
    paths = []
    for r in C.MODULE.routers:
        paths += [x.path for x in r.routes if x.path.startswith(BASE)]
    assert paths.index(QI) < paths.index(BASE + "/{note_no}")


def test_non_admin_and_anonymous_are_refused(client, make_user):
    no = _quote()
    assert client.get(QI, params={"quote_no": no}).status_code in (401, 403)
    u, p = make_user(username="qi_eng", role="engineer", modules=["case_manage"])
    assert _qi(client, _login(client, u, p), no).status_code == 403
    u2, p2 = make_user(username="qi_sales", role="sales")
    assert _qi(client, _login(client, u2, p2), no).status_code == 403          # 放寬給業務屬另案權限審查


def test_unknown_quote_is_404_with_the_neutral_sentence(client, make_user):
    h = _admin(client, make_user)
    r = _qi(client, h, "MQ-NOPE-999")
    assert r.status_code == 404 and r.json()["detail"] == "找不到可帶入的報價單"


# ── 狀態閘 ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status", ["草稿", "待審核", "簽核中", "已取消", "已拒絕"])
def test_status_gate_refuses_non_sent_quotes(client, make_user, status):
    h = _admin(client, make_user)
    r = _qi(client, h, _quote(status=status))
    assert r.status_code == 409 and r.json()["detail"]


def test_status_gate_allows_sent_and_warns_when_unsigned(client, make_user):
    h = _admin(client, make_user)
    r = _qi(client, h, _quote(signed=0))
    assert r.status_code == 200 and r.json()["sourceState"] == "unsigned" and r.json()["warnings"]


def test_unsigned_can_be_refused_by_setting(client, make_user, monkeypatch):
    from modules.case.api import completion_notes as CN
    h = _admin(client, make_user)
    no = _quote(signed=0)
    real = CN._opt
    monkeypatch.setattr(CN, "_opt", lambda k: 0 if k == "prefill_unsigned" else real(k))
    assert _qi(client, h, no).status_code == 409
    assert _qi(client, h, _quote("MQ-QI-002", signed=1)).status_code == 200


# ── 累計 ───────────────────────────────────────────────────────────────────────

def test_cumulative_counts_only_counted_statuses_and_sums_duplicates(client, make_user):
    h = _admin(client, make_user)
    no = _quote()
    n1 = _note(client, h, no, [_row("it-1", 3), _row("it-1", 1, "部分完成"), _row("it-2", 2, "未施作"),
                               {"type": "header", "description": "h", "quoteItemId": "hd-1"}])
    n2 = _note(client, h, no, [_row("it-1", 4)])
    n3 = _note(client, h, no, [_row("it-1", 9)])                       # 保持草稿 ⇒ 不計
    _set_status(n1, "已核准"); _set_status(n2, "待審核")
    conn = db.get_db()
    try:
        assert CS.completed_qty_by_item(conn, no) == {"it-1": 8.0}
        assert CS.completed_qty_by_item(conn, no, exclude_note=n2) == {"it-1": 4.0}
    finally:
        conn.close()
    items = {i["id"]: i for i in _qi(client, h, no).json()["items"] if i["type"] != "header"}
    assert items["it-1"]["alreadyCompleted"] == 8 and items["it-1"]["remaining"] == 2
    assert items["it-2"]["alreadyCompleted"] == 0 and items["it-2"]["remaining"] == 5
    mine = {i["id"]: i for i in _qi(client, h, no, exclude_note=n2).json()["items"] if i["type"] != "header"}
    assert mine["it-1"]["alreadyCompleted"] == 4
    _set_status(n1, "草稿")                                              # 撤銷核准 ⇒ 累計即時縮小
    assert {i["id"]: i for i in _qi(client, h, no).json()["items"] if i["type"] != "header"}["it-1"]["alreadyCompleted"] == 4
    assert n3


def test_bad_quantities_count_as_zero_and_untracked_rows_are_ignored(client, make_user):
    h = _admin(client, make_user)
    no = _quote()
    n = _note(client, h, no, [_row("it-1", -5), _row("it-1", "abc"), _row("it-1", 2),
                              {"description": "手動", "qty": 7, "unit": "式", "status": "完成"}])
    _set_status(n, "已核准")
    conn = db.get_db()
    try:
        assert CS.completed_qty_by_item(conn, no) == {"it-1": 2.0}
    finally:
        conn.close()
    assert CS.num(float("inf")) == 0 and CS.num(None) == 0 and CS.num("3") == 3.0


def test_untracked_legacy_item_is_marked_and_not_accumulated(client, make_user):
    h = _admin(client, make_user)
    items = _qi(client, h, _quote()).json()["items"]
    legacy = [i for i in items if i["description"] == "舊資料沒有編號"][0]
    assert legacy["tracked"] is False and legacy["remaining"] == 2


# ── 指紋與 quoteSync ───────────────────────────────────────────────────────────

def test_fingerprint_ignores_money_and_follows_qty_and_name(client, make_user):
    h = _admin(client, make_user)
    no = _quote()
    fp0 = _qi(client, h, no).json()["fingerprint"]
    changed_money = json.loads(json.dumps(ITEMS)); changed_money[0]["unitPrice"] = 999; changed_money[0]["cost"] = 1
    _set_quote_data(no, changed_money)
    assert _qi(client, h, no).json()["fingerprint"] == fp0
    changed_qty = json.loads(json.dumps(ITEMS)); changed_qty[0]["qty"] = 11
    _set_quote_data(no, changed_qty)
    assert _qi(client, h, no).json()["fingerprint"] != fp0


def _stored_sync(note_no):
    conn = db.get_db()
    try:
        return json.loads(conn.execute("SELECT data_json FROM completion_notes WHERE note_no=?", (note_no,)).fetchone()[0]).get("quoteSync")
    finally:
        conn.close()


def test_quote_sync_accepted_only_when_fingerprint_matches_now(client, make_user):
    h = _admin(client, make_user)
    no = _quote()
    fp = _qi(client, h, no).json()["fingerprint"]
    r = client.post(BASE, headers=h, json={"quote_no": no, "items": [_row("it-1", 1)], "quote_sync": {"fingerprint": "forged"}})
    assert r.status_code == 409
    n = _note(client, h, no, [_row("it-1", 1)], quote_sync={"fingerprint": fp})
    st = _stored_sync(n)
    assert st["itemsFingerprint"] == fp and st["syncedAt"]
    assert client.get(f"{BASE}/{n}", headers=h).json()["quoteSync"]["itemsFingerprint"] == fp
    # 載入到存檔之間報價單被改 ⇒ 送回舊指紋 ⇒ 409，儲存值不變
    chg = json.loads(json.dumps(ITEMS)); chg[2]["qty"] = 50
    _set_quote_data(no, chg)
    r = client.put(f"{BASE}/{n}", headers=h, json={"quote_no": no, "items": [_row("it-1", 1)], "quote_sync": {"fingerprint": fp}})
    assert r.status_code == 409 and "重新帶入" in r.json()["detail"]
    assert _stored_sync(n)["itemsFingerprint"] == fp


def test_plain_update_keeps_quote_sync_untouched(client, make_user):
    h = _admin(client, make_user)
    no = _quote()
    fp = _qi(client, h, no).json()["fingerprint"]
    n = _note(client, h, no, [_row("it-1", 1)], quote_sync={"fingerprint": fp})
    before = _stored_sync(n)
    chg = json.loads(json.dumps(ITEMS)); chg[0]["qty"] = 99
    _set_quote_data(no, chg)                                           # 報價單已更動：一般存檔不得悄悄清掉或刷新同步戳記
    r = client.put(f"{BASE}/{n}", headers=h, json={"quote_no": no, "items": [_row("it-1", 2)], "notes": "改備註"})
    assert r.status_code == 200, r.text
    assert _stored_sync(n) == before


def test_update_uses_stored_quote_no_not_the_body(client, make_user):
    h = _admin(client, make_user)
    a = _quote("MQ-QI-A"); b = _quote("MQ-QI-B", items=[{"id": "b-1", "description": "B", "qty": 1, "unit": "式"}])
    fp_b = _qi(client, h, b).json()["fingerprint"]
    n = _note(client, h, a, [_row("it-1", 1)])
    r = client.put(f"{BASE}/{n}", headers=h, json={"quote_no": b, "items": [_row("it-1", 1)], "quote_sync": {"fingerprint": fp_b}})
    assert r.status_code == 409                                         # 以庫內的 A 重算指紋，B 的指紋不被接受
    conn = db.get_db()
    try:
        assert conn.execute("SELECT quote_no FROM completion_notes WHERE note_no=?", (n,)).fetchone()[0] == a
    finally:
        conn.close()


def test_approval_state_survives_quote_sync_write(client, make_user):
    h = _admin(client, make_user)
    no = _quote()
    fp = _qi(client, h, no).json()["fingerprint"]
    n = _note(client, h, no, [_row("it-1", 1)], quote_sync={"fingerprint": fp})
    conn = db.get_db()
    try:
        d = json.loads(conn.execute("SELECT data_json FROM completion_notes WHERE note_no=?", (n,)).fetchone()[0])
        d["approval"] = {"history": [{"x": 1}]}
        conn.execute("UPDATE completion_notes SET data_json=? WHERE note_no=?", (json.dumps(d), n)); conn.commit()
    finally:
        conn.close()
    assert client.put(f"{BASE}/{n}", headers=h, json={"quote_no": no, "items": [_row("it-1", 1)], "quote_sync": {"fingerprint": fp}}).status_code == 200
    assert _stored_sync(n)["itemsFingerprint"] == fp
    conn = db.get_db()
    try:
        assert json.loads(conn.execute("SELECT data_json FROM completion_notes WHERE note_no=?", (n,)).fetchone()[0])["approval"] == {"history": [{"x": 1}]}
    finally:
        conn.close()


# ── 驗證與超量政策 ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [123, "", "x" * 65, ["a"]])
def test_quote_item_id_must_be_a_short_string(client, make_user, bad):
    h = _admin(client, make_user)
    r = client.post(BASE, headers=h, json={"quote_no": _quote(), "items": [_row(bad, 1)]})
    assert r.status_code == 400


def test_quote_qty_must_be_a_finite_number(client, make_user):
    h = _admin(client, make_user)
    r = client.post(BASE, headers=h, json={"quote_no": _quote(), "items": [_row("it-1", 1, quoteQty="9")]})
    assert r.status_code == 400
    assert client.post(BASE, headers=h, json={"quote_no": "MQ-QI-001", "items": [_row("it-1", 1, quoteQty=10)]}).status_code == 201


def test_over_quantity_warns_by_default_and_blocks_by_setting(client, make_user, monkeypatch):
    from modules.case.api import completion_notes as CN
    h = _admin(client, make_user)
    no = _quote()
    n1 = _note(client, h, no, [_row("it-1", 8)]); _set_status(n1, "已核准")
    assert client.post(BASE, headers=h, json={"quote_no": no, "items": [_row("it-1", 5)]}).status_code == 201     # 預設警告不擋
    real = CN._opt
    monkeypatch.setattr(CN, "_opt", lambda k: 1 if k == "over_qty" else real(k))
    r = client.post(BASE, headers=h, json={"quote_no": no, "items": [_row("it-1", 5)]})
    assert r.status_code == 400 and "超過報價數量" in r.json()["detail"]
    assert client.post(BASE, headers=h, json={"quote_no": no, "items": [_row("it-1", 2)]}).status_code == 201


# ── 設定中心（預設＝使用者 10-12 裁示）────────────────────────────────────────────

def test_settings_group_defaults_are_the_user_decisions():
    from helpers import settings_registry as R
    g = R.groups()["completion_note"]
    got = {f["key"]: f["default"] for f in g["fields"]}
    assert got == {"auto_prefill": 1, "prefill_unsigned": 1, "qty_mode": 0, "default_status": 0,
                   "include_headers": 1, "brand_prefix": 1, "over_qty": 0}
    for f in g["fields"]:
        assert f["question"] and f["label"] and f["help"] and f["impact"] and f["choices"]
        assert f["recommended"] == f["default"]
        for c in f["choices"]:
            assert c["label"] and c["impact"]
    assert R.get("completion_note", "over_qty") == 0
    assert {f["key"]: f["loosen"] for f in g["fields"]}["prefill_unsigned"] is None          # 便利性選項：不走雙人核准


def test_options_in_response_follow_the_registry(client, make_user):
    h = _admin(client, make_user)
    o = _qi(client, h, _quote()).json()["options"]
    assert o == {"autoPrefill": True, "qtyMode": "remaining", "defaultStatus": "完成", "brandPrefix": True, "overQty": "warn"}


# ── 前端靜態守門 ───────────────────────────────────────────────────────────────

def test_form_no_longer_loads_the_whole_quotation_and_shows_no_price_columns():
    src = (REPO / "frontend/pages/completion-note-form.html").read_text(encoding="utf-8")
    assert "/api/quotations/" not in src
    assert "/api/completion-notes/quote-items" in src
    for word in ("單價", "金額", "unitPrice", "價格"):
        assert word not in src, word


# ── 補強（0d 稽核 S1–S4）────────────────────────────────────────────────────────

def test_source_fails_closed_when_counted_items_exists_but_raises(client, make_user, monkeypatch):
    from modules.case import profit_guard as PG

    def boom(data):
        raise RuntimeError("alt calc broke")
    monkeypatch.setattr(PG, "counted_items", boom, raising=False)
    with pytest.raises(CS.SourceUnavailable):
        CS.source_items({"items": ITEMS})
    h = _admin(client, make_user)
    r = _qi(client, h, _quote())
    assert r.status_code == 409 and "無法判定計入項目" in r.json()["detail"]


def test_source_degrades_to_all_items_only_when_the_function_is_absent(monkeypatch):
    from modules.case import profit_guard as PG
    monkeypatch.delattr(PG, "counted_items", raising=False)
    assert len(CS.source_items({"items": ITEMS})) == 4
    monkeypatch.setattr(PG, "counted_items", lambda data: [ITEMS[0]], raising=False)
    assert [i["id"] for i in CS.source_items({"items": ITEMS})] == ["it-1"]               # 存在就用它的結果


def test_fingerprint_follows_brand(client, make_user):
    h = _admin(client, make_user)
    no = _quote()
    fp0 = _qi(client, h, no).json()["fingerprint"]
    chg = json.loads(json.dumps(ITEMS)); chg[0]["brand"] = "另一牌"
    _set_quote_data(no, chg)
    assert _qi(client, h, no).json()["fingerprint"] != fp0


def test_put_over_quantity_is_blocked_by_setting_and_excludes_itself(client, make_user, monkeypatch):
    from modules.case.api import completion_notes as CN
    h = _admin(client, make_user)
    no = _quote()
    n1 = _note(client, h, no, [_row("it-1", 8)]); _set_status(n1, "已核准")
    mine = _note(client, h, no, [_row("it-1", 2)])
    real = CN._opt
    monkeypatch.setattr(CN, "_opt", lambda k: 1 if k == "over_qty" else real(k))
    r = client.put(f"{BASE}/{mine}", headers=h, json={"quote_no": no, "items": [_row("it-1", 5)]})
    assert r.status_code == 400 and "超過報價數量" in r.json()["detail"]
    assert client.put(f"{BASE}/{mine}", headers=h, json={"quote_no": no, "items": [_row("it-1", 2)]}).status_code == 200   # 自己不算進他單


@pytest.mark.parametrize("status", ["草稿", "已取消"])
def test_put_with_quote_sync_is_409_when_the_quote_went_back_or_was_cancelled(client, make_user, status):
    h = _admin(client, make_user)
    no = _quote()
    fp = _qi(client, h, no).json()["fingerprint"]
    n = _note(client, h, no, [_row("it-1", 1)], quote_sync={"fingerprint": fp})
    before = _stored_sync(n)
    conn = db.get_db()
    try:
        conn.execute("UPDATE quotations SET status=? WHERE quote_no=?", (status, no)); conn.commit()
    finally:
        conn.close()
    r = client.put(f"{BASE}/{n}", headers=h, json={"quote_no": no, "items": [_row("it-1", 1)], "quote_sync": {"fingerprint": fp}})
    assert r.status_code == 409 and "報價單目前無法同步" in r.json()["detail"]
    assert _stored_sync(n) == before
    assert client.put(f"{BASE}/{n}", headers=h, json={"quote_no": no, "items": [_row("it-1", 2)]}).status_code == 200      # 不帶同步戳記的一般存檔不受影響


def test_unreadable_and_missing_quotes_give_the_identical_404(client, make_user, monkeypatch):
    from fastapi import HTTPException
    from modules.case.api import completion_notes as CN
    no = _quote()
    conn = db.get_db()
    try:
        admin = {"username": "x", "role": "admin", "id": 1}
        monkeypatch.setattr(CN, "case_page_readable", lambda c, q, u: False)
        with pytest.raises(HTTPException) as hidden:
            CN._quote_source(conn, no, admin)
        with pytest.raises(HTTPException) as missing:
            CN._quote_source(conn, "MQ-NOPE-000", admin)
    finally:
        conn.close()
    assert (hidden.value.status_code, hidden.value.detail) == (missing.value.status_code, missing.value.detail) == (404, "找不到可帶入的報價單")


def test_create_and_update_take_the_write_lock_before_checking():
    import inspect
    from modules.case.api import completion_notes as CN
    for fn in (CN.create_completion_note, CN.update_completion_note):
        src = inspect.getsource(fn)
        assert src.index("begin_write(conn)") < src.index("_enforce_over_qty(") < src.index("conn.commit()"), fn.__name__


@pytest.mark.skip(reason="TODO(M3 整合)：擇一方案併入後補——①counted_items 只回客戶選定品項 ⇒ 完工單只帶選定方案；②未選定組別 ⇒ sourceState=alt_unselected 與 unselected_group 設定；"
                         "③取消回簽清除選定 ⇒ 指紋改變、完工單顯示橫幅（§8b 選項 a）；④counted_items 簽章變更時 completion_sync 是唯一接點")
def test_alt_quote_integration_todo():
    raise AssertionError("placeholder")
