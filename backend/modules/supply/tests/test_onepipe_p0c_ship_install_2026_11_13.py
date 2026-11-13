"""一條龍 P0c（旗標 onepipe.ship_install_ok）：同一案件先出貨、後登載設備，不再報序號衝突。

關＝與今天逐位元相同（仍衝突）；開＝同案 shipped→installed 合法，釋放回 shipped；他案出貨／已被認領仍衝突。
"""
from tests._requires import requires_module  # noqa: E402
needs_m01 = requires_module("case", "本題打 M01（案件）的案件記錄端點")

from tests.test_api_integration import _auth, _login, _make_quotation


def _flag(monkeypatch, on):
    from helpers import onepipe_flags
    monkeypatch.setattr(onepipe_flags, "flag_on", lambda field, conn=None: bool(on) and field == "ship_install_ok")


def _item(serial, status, quote_no="", note_no="", device_id=""):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO stock_items (part_no, serial_no, status, quote_no, shipping_note_no, case_device_id, created_at, updated_at) "
                     "VALUES (?,?,?,?,?,?,?,?)", ("NET-P0C", serial, status, quote_no, note_no, device_id, "2026-01-01T00:00:00", "2026-01-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _row(serial):
    import db
    conn = db.get_db()
    try:
        return dict(conn.execute("SELECT status, quote_no, shipping_note_no, case_device_id FROM stock_items WHERE serial_no=?", (serial,)).fetchone())
    finally:
        conn.close()


def _note(note_no, status, quote_no=""):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT OR REPLACE INTO shipping_notes (note_no, quote_no, status, customer_name, data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                     (note_no, quote_no, status, "客戶", "{}", "2026-01-01T00:00:00", "2026-01-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _save(client, token, quote_no, devices):
    r = client.patch("/api/quotations/%s/case-record" % quote_no, headers=_auth(token), json={"case_record": {"devices": devices}})
    assert r.status_code == 200, r.text
    return r.json()


@needs_m01
def test_flag_off_same_case_shipped_serial_is_still_a_conflict(client, make_user, monkeypatch):
    _flag(monkeypatch, False)
    u, p = make_user(role="admin")
    token = _login(client, u, p)
    _make_quotation("MQ-P0C-001")
    _item("SN-P0C-OFF", "shipped", quote_no="MQ-P0C-001", note_no="SH-1")
    out = _save(client, token, "MQ-P0C-001", [{"id": 1, "sn": "SN-P0C-OFF"}])
    assert [c["stockStatus"] for c in out["stockConflicts"]] == ["shipped"]
    assert _row("SN-P0C-OFF")["status"] == "shipped"


@needs_m01
def test_flag_on_same_case_shipped_then_install_then_release_goes_back_to_shipped(client, make_user, monkeypatch):
    _flag(monkeypatch, True)
    u, p = make_user(role="admin")
    token = _login(client, u, p)
    _make_quotation("MQ-P0C-002")
    _note("SH-2", "已核准", "MQ-P0C-002")
    _item("SN-P0C-ON", "shipped", quote_no="MQ-P0C-002", note_no="SH-2")
    out = _save(client, token, "MQ-P0C-002", [{"id": 7, "sn": "SN-P0C-ON"}])
    assert out["stockConflicts"] == []
    r = _row("SN-P0C-ON")
    assert (r["status"], r["quote_no"], r["shipping_note_no"], r["case_device_id"]) == ("installed", "MQ-P0C-002", "SH-2", "7")
    _save(client, token, "MQ-P0C-002", [{"id": 7, "sn": ""}])              # 設備拿掉序號 ⇒ 釋放
    r = _row("SN-P0C-ON")
    assert (r["status"], r["quote_no"], r["shipping_note_no"], r["case_device_id"]) == ("shipped", "MQ-P0C-002", "SH-2", "")


@needs_m01
def test_flag_on_other_case_shipped_or_already_installed_still_conflicts(client, make_user, monkeypatch):
    _flag(monkeypatch, True)
    u, p = make_user(role="admin")
    token = _login(client, u, p)
    _make_quotation("MQ-P0C-003")
    _item("SN-P0C-OTHER", "shipped", quote_no="MQ-P0C-OTHER", note_no="SH-3")
    _item("SN-P0C-TAKEN", "installed", quote_no="MQ-P0C-003", note_no="SH-3", device_id="99")
    _item("SN-P0C-NOQ", "shipped", quote_no="", note_no="SH-4")
    out = _save(client, token, "MQ-P0C-003", [{"id": 1, "sn": "SN-P0C-OTHER"}, {"id": 2, "sn": "SN-P0C-TAKEN"}, {"id": 3, "sn": "SN-P0C-NOQ"}])
    assert sorted(c["stockStatus"] for c in out["stockConflicts"]) == ["installed", "shipped", "shipped"]
    assert _row("SN-P0C-OTHER")["status"] == "shipped" and _row("SN-P0C-TAKEN")["case_device_id"] == "99" and _row("SN-P0C-NOQ")["status"] == "shipped"


@needs_m01
def test_flag_on_in_stock_path_is_unchanged(client, make_user, monkeypatch):
    _flag(monkeypatch, True)
    u, p = make_user(role="admin")
    token = _login(client, u, p)
    _make_quotation("MQ-P0C-004")
    _item("SN-P0C-STOCK", "in_stock")
    assert _save(client, token, "MQ-P0C-004", [{"id": 1, "sn": "SN-P0C-STOCK"}])["stockConflicts"] == []
    assert _row("SN-P0C-STOCK")["status"] == "installed"
    _save(client, token, "MQ-P0C-004", [{"id": 1, "sn": ""}])
    r = _row("SN-P0C-STOCK")
    assert (r["status"], r["quote_no"], r["shipping_note_no"]) == ("in_stock", "", "")


@needs_m01
def test_release_follows_the_data_not_the_flag_flag_on_claim_then_flag_off_release(client, make_user, monkeypatch):
    """M1（hichan-9 審查）：旗標開時認領、之後旗標關掉再釋放 ⇒ 仍回 shipped（出貨單還是已核准），不可被算成在庫。"""
    _note("SH-M1", "已核准", "MQ-P0C-M1")
    _flag(monkeypatch, True)
    u, p = make_user(role="admin")
    token = _login(client, u, p)
    _make_quotation("MQ-P0C-M1")
    _item("SN-P0C-M1", "shipped", quote_no="MQ-P0C-M1", note_no="SH-M1")
    assert _save(client, token, "MQ-P0C-M1", [{"id": 5, "sn": "SN-P0C-M1"}])["stockConflicts"] == []
    assert _row("SN-P0C-M1")["status"] == "installed"
    _flag(monkeypatch, False)
    _save(client, token, "MQ-P0C-M1", [{"id": 5, "sn": ""}])
    r = _row("SN-P0C-M1")
    assert (r["status"], r["quote_no"], r["shipping_note_no"], r["case_device_id"]) == ("shipped", "MQ-P0C-M1", "SH-M1", "")


@needs_m01
def test_release_when_the_note_is_no_longer_approved_goes_back_in_stock_and_clears_the_note(client, make_user, monkeypatch):
    """M2（PM 裁示）：出貨單已不是已核准 ⇒ 釋放回在庫並清掉出貨單號（否則永遠卡在 shipped 掛著草稿單）。"""
    _flag(monkeypatch, True)
    u, p = make_user(role="admin")
    token = _login(client, u, p)
    _make_quotation("MQ-P0C-M2")
    _note("SH-M2", "已核准", "MQ-P0C-M2")
    _item("SN-P0C-M2", "shipped", quote_no="MQ-P0C-M2", note_no="SH-M2")
    _save(client, token, "MQ-P0C-M2", [{"id": 6, "sn": "SN-P0C-M2"}])
    assert _row("SN-P0C-M2")["status"] == "installed"
    _note("SH-M2", "草稿", "MQ-P0C-M2")                                         # 單被退回草稿（例如舊資料／別條路徑）
    _save(client, token, "MQ-P0C-M2", [{"id": 6, "sn": ""}])
    r = _row("SN-P0C-M2")
    assert (r["status"], r["quote_no"], r["shipping_note_no"], r["case_device_id"]) == ("in_stock", "", "", "")


@needs_m01
def test_revoke_approval_is_blocked_while_a_serial_of_the_note_is_installed(client, make_user, monkeypatch):
    """M2（PM 裁示）：這張單的序號已登載成設備 ⇒ 撤回核准 409，講人話；移除設備後才可撤回，序號回在庫。"""
    _flag(monkeypatch, True)
    u, p = make_user(role="admin")
    token = _login(client, u, p)
    _make_quotation("MQ-P0C-RV")
    _note("SH-RV", "已核准", "MQ-P0C-RV")
    _item("SN-P0C-RV", "shipped", quote_no="MQ-P0C-RV", note_no="SH-RV")
    _save(client, token, "MQ-P0C-RV", [{"id": 8, "sn": "SN-P0C-RV"}])
    r = client.post("/api/shipping-notes/SH-RV/revoke-approval", headers=_auth(token), json={"note": "測試撤回"})
    assert r.status_code == 409 and "請先從案件移除設備再撤回" in r.json()["detail"], r.text
    assert _row("SN-P0C-RV")["status"] == "installed"
    _save(client, token, "MQ-P0C-RV", [{"id": 8, "sn": ""}])                       # 移除設備序號 ⇒ 回 shipped（單仍已核准）
    assert _row("SN-P0C-RV")["status"] == "shipped"
    r = client.post("/api/shipping-notes/SH-RV/revoke-approval", headers=_auth(token), json={"note": "測試撤回"})
    assert r.status_code == 200, r.text
    assert r.json()["stockReturned"] == 1 and _row("SN-P0C-RV")["status"] == "in_stock"
