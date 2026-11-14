"""T85 一條龍 P2a「入庫底層」（旗標 onepipe.receive_ledger；決策 D1＝A 入庫或直送、D9）。

關＝與今天逐位元相同（提供者回 DISABLED、不多欄位不多鍵不寫異動、對帳表 404）；開＝入庫與案件材料申請對應、逐列回報、直送只留表頭、
序號異動留紀錄、`stock.case_summary` 多回入庫台數、對帳表列出「案件已到貨而庫存沒有」的材料申請。
"""
import json

import pytest

from tests._requires import requires_module
pytestmark = requires_module("supply", "本檔測 M03（採購與庫存）的入庫底層")
needs_m01 = requires_module("case", "本題需要 M01（案件）的材料申請與案件頁")

from tests.test_api_integration import _auth, _login, _make_quotation

ADMIN = {"role": "admin", "username": "adm", "display_name": "管理員甲"}
STAFF = {"role": "sales", "username": "stf", "display_name": "一般同仁"}


@pytest.fixture(autouse=True)
def _shippable_provider(request, monkeypatch):
    """多數題的 materialItemId 只是標籤（沒有真的材料申請）：預設讓 `material.shippable` 提供者缺席（略過「材料申請屬於這個案件」檢查）；
    要測那項檢查的題目要求 `real_shippable` 夾具。"""
    from core import registry
    real = registry.single_provider
    use_real = "real_shippable" in request.fixturenames
    monkeypatch.setattr(registry, "single_provider", lambda cap: None if (cap == "material.shippable" and not use_real) else real(cap))


@pytest.fixture
def real_shippable():
    return True


def _flag(monkeypatch, on):
    from helpers import onepipe_flags
    monkeypatch.setattr(onepipe_flags, "flag_on", lambda field, conn=None: bool(on) and field == "receive_ledger")


def _part(part_no="NET-P2A", cost=100):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT OR IGNORE INTO parts (part_no, name, active, cost, created_at, updated_at) VALUES (?,?,1,?,?,?)",
                     (part_no, "測試交換器", cost, "2026-01-01T00:00:00", "2026-01-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _receive(lines, caller=ADMIN, quote_no="MQ-P2A-001"):
    """提供者吃呼叫端的連線、不 commit：測試扮演呼叫端（拿寫鎖、呼叫、commit）。"""
    import db
    from core.txn import begin_write
    from modules.supply import receive as R
    conn = db.get_db()
    try:
        begin_write(conn)
        out = R.receive(conn, quote_no, lines, caller)
        conn.commit()
        return out
    finally:
        conn.close()


def _q(sql, *args):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def _line(serials, **kw):
    base = {"partNo": "NET-P2A", "materialItemId": "m1", "poDocCode": "PO-1", "mode": "stock", "serials": [{"serialNo": s} for s in serials]}
    base.update(kw)
    return base


# ── migration ───────────────────────────────────────────────────────────────

def test_migration_adds_ledger_columns_and_event_table(client):
    import db
    conn = db.get_db()
    try:
        bcols = {r[1] for r in conn.execute("PRAGMA table_info(stock_batches)").fetchall()}
        icols = {r[1] for r in conn.execute("PRAGMA table_info(stock_items)").fetchall()}
        ecols = {r[1] for r in conn.execute("PRAGMA table_info(stock_item_events)").fetchall()}
    finally:
        conn.close()
    assert {"quote_no", "po_doc_code", "material_item_id", "delivery_mode"} <= bcols
    assert "material_item_id" in icols
    assert {"stock_item_id", "part_no", "serial_no", "event", "from_status", "to_status", "quote_no", "ref", "reason", "actor", "created_at"} <= ecols


def test_migration_is_idempotent(client):
    import importlib
    import db
    m = importlib.import_module("modules.supply.migrations.0001_receive_ledger")
    conn = db.get_db()
    try:
        m.up(conn)
        m.up(conn)
    finally:
        conn.close()


# ── stock.receive ───────────────────────────────────────────────────────────

def test_flag_off_receive_does_nothing(client, monkeypatch):
    _flag(monkeypatch, False)
    _part()
    out = _receive([_line(["SN-OFF-1"])])
    assert out == {"ok": False, "reason": "DISABLED"}
    assert _q("SELECT 1 FROM stock_items WHERE serial_no='SN-OFF-1'") == []
    assert _q("SELECT 1 FROM stock_batches WHERE quote_no='MQ-P2A-001'") == []


def test_receive_writes_batch_items_and_events_in_caller_transaction(client, monkeypatch):
    _flag(monkeypatch, True)
    _part()
    out = _receive([_line(["SN-A", "SN-B"], cost=250, invoiceNo="INV-9")])
    assert out["ok"] and out["written"] == 2 and out["rejected"] == 0
    b = out["batches"][0]
    assert b["batchNo"].startswith("PO-") and [r["status"] for r in b["rows"]] == ["written", "written"]
    hdr = _q("SELECT quote_no, po_doc_code, material_item_id, delivery_mode, invoice_no FROM stock_batches WHERE batch_no=?", b["batchNo"])[0]
    assert hdr == {"quote_no": "MQ-P2A-001", "po_doc_code": "PO-1", "material_item_id": "m1", "delivery_mode": "stock", "invoice_no": "INV-9"}
    items = _q("SELECT serial_no, status, material_item_id, cost, quote_no FROM stock_items WHERE batch_no=? ORDER BY serial_no", b["batchNo"])
    assert items == [{"serial_no": "SN-A", "status": "in_stock", "material_item_id": "m1", "cost": 250, "quote_no": ""},
                     {"serial_no": "SN-B", "status": "in_stock", "material_item_id": "m1", "cost": 250, "quote_no": ""}]      # 入庫不等於被案件認領：stock_items.quote_no 仍空
    ev = _q("SELECT event, to_status, quote_no, ref, actor FROM stock_item_events ORDER BY id")
    assert [(e["event"], e["to_status"], e["quote_no"], e["ref"], e["actor"]) for e in ev] == [("receive", "in_stock", "MQ-P2A-001", b["batchNo"], "管理員甲")] * 2


def test_receive_uses_the_callers_transaction_rollback_leaves_nothing(client, monkeypatch):
    _flag(monkeypatch, True)
    _part()
    import db
    from core.txn import begin_write
    from modules.supply import receive as R
    conn = db.get_db()
    try:
        begin_write(conn)
        assert R.receive(conn, "MQ-P2A-001", [_line(["SN-RB"])], ADMIN)["written"] == 1
        conn.rollback()                                   # 案件那一半失敗 ⇒ 呼叫端撤回，庫存這一半一起沒有
    finally:
        conn.close()
    assert _q("SELECT 1 FROM stock_items WHERE serial_no='SN-RB'") == []
    assert _q("SELECT 1 FROM stock_batches WHERE quote_no='MQ-P2A-001'") == []
    assert _q("SELECT 1 FROM stock_item_events") == []


def test_receive_reports_each_row_and_writes_the_rest(client, monkeypatch):
    _flag(monkeypatch, True)
    _part()
    _receive([_line(["SN-EXIST"], materialItemId="m0")])
    out = _receive([_line(["SN-NEW", "SN-NEW", "", "SN-EXIST", "SN-NEW2"])], quote_no="MQ-P2A-002")
    rows = out["batches"][0]["rows"]
    by = {(r["serialNo"], r["status"], r["reason"]) for r in rows}
    assert ("SN-NEW", "written", "") in by and ("SN-NEW2", "written", "") in by
    assert ("SN-NEW", "rejected", "重複（同一次貼上）") in by
    assert ("", "rejected", "序號空白") in by
    assert ("SN-EXIST", "rejected", "序號已存在於庫存") in by
    assert out["written"] == 2 and out["rejected"] == 3
    assert [r["status"] for r in _q("SELECT status FROM stock_items WHERE serial_no='SN-EXIST'")] == ["in_stock"]
    assert len(_q("SELECT 1 FROM stock_items WHERE serial_no IN ('SN-NEW','SN-NEW2')")) == 2


def test_receive_more_than_50_serials_in_a_line_writes_nothing_for_that_line(client, monkeypatch):
    _flag(monkeypatch, True)
    _part()
    out = _receive([_line(["S%03d" % i for i in range(51)]), _line(["SN-OK"], materialItemId="m2")])
    assert out["batches"][0]["written"] == 0 and {r["reason"] for r in out["batches"][0]["rows"]} == {"一次最多 50 筆序號"}
    assert out["batches"][1]["written"] == 1                                         # 別列照寫
    assert len(_q("SELECT 1 FROM stock_items")) == 1
    assert len(_q("SELECT 1 FROM stock_batches")) == 1                                # 整列拒收 ⇒ 不留空批次


def test_receive_unknown_part_is_rejected_per_row(client, monkeypatch):
    _flag(monkeypatch, True)
    out = _receive([_line(["SN-X"], partNo="NO-SUCH-PART")])
    assert out["written"] == 0 and out["batches"][0]["rows"] == [{"serialNo": "SN-X", "status": "rejected", "reason": "料號不存在"}]
    assert _q("SELECT 1 FROM stock_batches") == []


def test_receive_without_permission_writes_no_stock(client, monkeypatch):
    _flag(monkeypatch, True)
    _part()
    out = _receive([_line(["SN-NP"])], caller=STAFF)
    assert out == {"ok": False, "reason": "NO_PERMISSION"}
    assert _q("SELECT 1 FROM stock_items") == [] and _q("SELECT 1 FROM stock_batches") == [] and _q("SELECT 1 FROM stock_item_events") == []


def test_receive_direct_mode_keeps_only_a_header(client, monkeypatch):
    _flag(monkeypatch, True)
    _part()
    out = _receive([_line([], mode="direct", materialItemId="m-dr")])
    b = out["batches"][0]
    assert b["batchNo"].startswith("DR-") and b["mode"] == "direct" and out["written"] == 0
    assert _q("SELECT quote_no, material_item_id, delivery_mode FROM stock_batches WHERE batch_no=?", b["batchNo"]) == [
        {"quote_no": "MQ-P2A-001", "material_item_id": "m-dr", "delivery_mode": "direct"}]
    assert _q("SELECT 1 FROM stock_items") == []
    # 直送批次沒有序號列 ⇒ 既有的批次清單（由序號列群組）不會多出它（與今天相同）
    assert _q("SELECT 1 FROM stock_items WHERE batch_no=?", b["batchNo"]) == []


def test_receive_rejects_unknown_mode_and_missing_case(client, monkeypatch):
    _flag(monkeypatch, True)
    _part()
    out = _receive([_line(["SN-M"], mode="teleport")])
    assert out["written"] == 0 and out["batches"][0]["rows"][0]["reason"] == "不支援的到貨方式"
    assert _receive([_line(["SN-M"])], quote_no="") == {"ok": False, "reason": "NO_CASE"}


# ── 序號異動紀錄 ─────────────────────────────────────────────────────────────

def test_events_for_install_release_and_adjust_only_when_flag_on(client, make_user, monkeypatch):
    from modules.supply.api.inventory import _StockSerials as S
    import db
    for on in (False, True):
        _flag(monkeypatch, on)
        _part()
        sn = "SN-EV-%d" % on
        conn = db.get_db()
        try:
            conn.execute("INSERT INTO stock_items (part_no, serial_no, status, created_at, updated_at) VALUES ('NET-P2A',?, 'in_stock','2026-01-01','2026-01-01')", (sn,))
            assert S.claim(conn, sn, quote_no="MQ-P2A-001", device_id="d1", actor="甲", now="2026-02-01T00:00:00") == "in_stock"
            S.release(conn, sn, device_id="d1", now="2026-02-02T00:00:00")
            conn.commit()
        finally:
            conn.close()
        evs = _q("SELECT event, from_status, to_status FROM stock_item_events WHERE serial_no=? ORDER BY id", sn)
        if on:
            assert [(e["event"], e["from_status"], e["to_status"]) for e in evs] == [("install", "in_stock", "installed"), ("release", "installed", "in_stock")]
        else:
            assert evs == []                                                          # 旗標關：不多一列資料


def test_history_returns_events_oldest_first(client, monkeypatch):
    _flag(monkeypatch, True)
    _part()
    _receive([_line(["SN-H"])])
    import db
    from modules.supply import stock_events as E
    conn = db.get_db()
    try:
        E.record(conn, event="void", part_no="NET-P2A", serial_no="SN-H", from_status="in_stock", to_status="void", reason="遺失", actor="甲")
        conn.commit()
        h = E.history(conn, "NET-P2A", "SN-H")
    finally:
        conn.close()
    assert [x["event"] for x in h] == ["receive", "void"] and h[1]["reason"] == "遺失"


def test_event_write_failure_never_breaks_the_caller(client, monkeypatch):
    _flag(monkeypatch, True)
    import db
    from modules.supply import stock_events as E
    conn = db.get_db()
    try:
        conn.execute("ALTER TABLE stock_item_events RENAME TO stock_item_events_gone")
        assert E.record(conn, event="x", part_no="P", serial_no="S") is False          # 表不見也不丟例外
        conn.rollback()
    finally:
        conn.close()


# ── case_summary（IP-117）──────────────────────────────────────────────────

def test_case_summary_adds_received_keys_only_when_flag_on(client, monkeypatch):
    import db
    from modules.supply import case_summary as CS
    _part()
    _flag(monkeypatch, True)
    _receive([_line(["SN-C1", "SN-C2"]), _line([], mode="direct", materialItemId="m-dr")])
    conn = db.get_db()
    try:
        s = CS.case_summary(conn, "MQ-P2A-001")
        assert s["receivedInStock"] == 2 and s["directBatches"] == 1
        assert s["parts"] == [{"partNo": "NET-P2A", "installed": 0, "shipped": 0, "inStock": 2}]
        _flag(monkeypatch, False)
        off = CS.case_summary(conn, "MQ-P2A-001")
    finally:
        conn.close()
    assert set(off) == {"installed", "shipped", "void", "parts"} and off["parts"] == []         # 關＝與今天相同的鍵


def test_case_summary_in_stock_count_drops_after_install(client, monkeypatch):
    import db
    from modules.supply import case_summary as CS
    from modules.supply.api.inventory import _StockSerials as S
    _part()
    _flag(monkeypatch, True)
    _receive([_line(["SN-D1", "SN-D2"])])
    conn = db.get_db()
    try:
        S.claim(conn, "SN-D1", quote_no="MQ-P2A-001", device_id="d1", actor="甲", now="2026-02-01T00:00:00")
        conn.commit()
        s = CS.case_summary(conn, "MQ-P2A-001")
    finally:
        conn.close()
    assert (s["receivedInStock"], s["installed"]) == (1, 1)


# ── 讀取回應：旗標關不帶新欄位 ────────────────────────────────────────────────

def test_batch_and_item_reads_hide_new_columns_when_flag_off(client, make_user, monkeypatch):
    u, p = make_user(role="admin")
    token = _login(client, u, p)
    _part()
    _flag(monkeypatch, True)
    out = _receive([_line(["SN-R1"])])
    bn = out["batches"][0]["batchNo"]
    on = client.get("/api/inventory/batches/%s" % bn, headers=_auth(token)).json()
    assert on["header"]["quote_no"] == "MQ-P2A-001" and on["items"][0]["material_item_id"] == "m1"
    _flag(monkeypatch, False)
    off = client.get("/api/inventory/batches/%s" % bn, headers=_auth(token)).json()
    assert not ({"quote_no", "po_doc_code", "material_item_id", "delivery_mode"} & set(off["header"]))
    assert "material_item_id" not in off["items"][0]
    lst = client.get("/api/inventory/stock-items", headers=_auth(token)).json()["items"]
    assert lst and all("material_item_id" not in i for i in lst)


# ── 對帳表 ──────────────────────────────────────────────────────────────────

def _received_case(quote_no, item_id, name="交換器 24 埠", qty=4, day="2026-11-10"):
    import db
    conn = db.get_db()
    try:
        data = {"caseRecord": {"materialOrders": [{"itemId": item_id, "itemName": name, "unit": "台", "quantity": qty}]}}
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                     (quote_no, "已成案", "客戶", "專案", json.dumps(data, ensure_ascii=False), "2026-01-01T00:00:00", "2026-01-01T00:00:00"))
        conn.execute("INSERT INTO case_material_approvals (quote_no, item_id, doc_code, status, received_on, received_by) VALUES (?,?,?,?,?,?)",
                     (quote_no, item_id, "MR-" + quote_no[-3:] + item_id, "已核准", day, "pm"))
        conn.commit()
    finally:
        conn.close()


@needs_m01
def test_case_provider_lists_only_approved_and_received(client):
    import db
    from modules.case import material_received as MR
    _received_case("MQ-P2A-010", "i1")
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO case_material_approvals (quote_no, item_id, doc_code, status, received_on) VALUES ('MQ-P2A-010','i2','MR-2','已核准','')")
        conn.execute("INSERT INTO case_material_approvals (quote_no, item_id, doc_code, status, received_on) VALUES ('MQ-P2A-010','i3','MR-3','草稿','2026-11-11')")
        conn.commit()
        got = MR.received_items(conn)
        since = MR.received_items(conn, since="2026-11-11")
    finally:
        conn.close()
    assert got == [{"quoteNo": "MQ-P2A-010", "itemId": "i1", "docCode": "MR-010i1", "name": "交換器 24 埠", "unit": "台", "appliedQty": 4, "receivedOn": "2026-11-10", "receivedBy": "pm"}]
    assert since == []


@needs_m01
def test_reconcile_flag_off_is_404_and_non_admin_is_403(client, make_user, monkeypatch):
    admin = _login(client, *make_user(role="admin"))
    _flag(monkeypatch, False)
    assert client.get("/api/inventory/reconcile", headers=_auth(admin)).status_code == 404
    _flag(monkeypatch, True)
    staff = _login(client, *make_user(username="inv_staff", role="sales", modules=["inventory"]))
    assert client.get("/api/inventory/reconcile", headers=_auth(staff)).status_code == 403


@needs_m01
def test_reconcile_lists_received_items_without_stock_and_drops_them_after_receive(client, make_user, monkeypatch, real_shippable):
    admin = _login(client, *make_user(role="admin"))
    _flag(monkeypatch, True)
    _part()
    _received_case("MQ-P2A-020", "ia")
    _received_case("MQ-P2A-021", "ib", name="攝影機")
    r = client.get("/api/inventory/reconcile", headers=_auth(admin)).json()
    assert r["caseAvailable"] is True and {(i["quoteNo"], i["itemId"]) for i in r["items"]} == {("MQ-P2A-020", "ia"), ("MQ-P2A-021", "ib")}
    assert not any("cost" in k or "price" in k.lower() or "amount" in k.lower() for i in r["items"] for k in i)         # 沒有金額欄位
    _receive([_line(["SN-RC1"], materialItemId="ia")], quote_no="MQ-P2A-020")                         # 入庫處理 ia
    _receive([_line([], mode="direct", materialItemId="ib")], quote_no="MQ-P2A-021")                  # 直送處理 ib
    assert client.get("/api/inventory/reconcile", headers=_auth(admin)).json()["items"] == []
    r2 = client.get("/api/inventory/reconcile?since=2026-12-01", headers=_auth(admin)).json()
    assert r2["items"] == []


@needs_m01
def test_reconcile_without_case_module_returns_empty(client, make_user, monkeypatch):
    from core import registry
    admin = _login(client, *make_user(role="admin"))
    _flag(monkeypatch, True)
    real = registry.single_provider
    monkeypatch.setattr(registry, "single_provider", lambda cap: None if cap == "material.received_list" else real(cap))
    assert client.get("/api/inventory/reconcile", headers=_auth(admin)).json() == {"items": [], "total": 0, "caseAvailable": False}


# ── 時間軸入庫格 ─────────────────────────────────────────────────────────────

@needs_m01
def test_timeline_stock_cell_shows_received_counts_when_flag_on(client, make_user, monkeypatch):
    import db
    from modules.case import material_flow as MF
    from modules.supply import case_summary as CS
    _part()
    _flag(monkeypatch, True)
    _receive([_line(["SN-T1", "SN-T2"])], quote_no="MQ-P2A-030")
    conn = db.get_db()
    try:
        cell = MF._stock(conn, "MQ-P2A-030", None)
    finally:
        conn.close()
    assert cell["state"] == "inprogress" and cell["summary"].startswith("已入庫尚未認領 2 台、已安裝 0 台、已出貨 0 台")
    _flag(monkeypatch, False)
    conn = db.get_db()
    try:
        off = MF._stock(conn, "MQ-P2A-030", None)
    finally:
        conn.close()
    assert off["summary"].startswith("尚無這個案件的序號")                                    # 關＝與今天相同的文字


# ── 審查補強（h9）：直送防重複、材料申請歸屬、對帳表分頁與 since、刪除事件 ────────────────

@needs_m01
def test_direct_receive_rejects_duplicate_unless_additional(client, monkeypatch, real_shippable):
    _flag(monkeypatch, True)
    _part()
    _received_case("MQ-P2A-030", "d1")
    ln = lambda **kw: _line([], mode="direct", materialItemId="d1", **kw)           # noqa: E731
    first = _receive([ln()], quote_no="MQ-P2A-030")
    assert first["batches"][0]["batchNo"].startswith("DR-") and "error" not in first["batches"][0]
    again = _receive([ln()], quote_no="MQ-P2A-030")
    assert again["batches"][0]["batchNo"] == "" and "重複" in again["batches"][0]["error"]
    assert len(_q("SELECT 1 FROM stock_batches WHERE material_item_id='d1'")) == 1
    more = _receive([ln(additional=True)], quote_no="MQ-P2A-030")                  # 分批到貨：呼叫端明確帶 additional
    assert more["batches"][0]["batchNo"].startswith("DR-")
    assert len(_q("SELECT 1 FROM stock_batches WHERE material_item_id='d1'")) == 2


@needs_m01
def test_receive_rejects_material_item_of_another_case_or_not_received(client, monkeypatch, real_shippable):
    _flag(monkeypatch, True)
    _part()
    _received_case("MQ-P2A-031", "x1")
    _received_case("MQ-P2A-032", "x2")
    out = _receive([_line(["SN-X1"], materialItemId="x2")], quote_no="MQ-P2A-031")           # x2 是別案的材料申請
    b = out["batches"][0]
    assert out["written"] == 0 and b["rows"][0]["status"] == "rejected" and "不屬於這個案件" in b["error"]
    assert _q("SELECT 1 FROM stock_items") == []
    ok = _receive([_line(["SN-X1"], materialItemId="x1")], quote_no="MQ-P2A-031")
    assert ok["written"] == 1


@needs_m01
def test_reconcile_pages_past_handled_items_and_validates_since(client, make_user, monkeypatch):
    admin = _login(client, *make_user(role="admin"))
    _flag(monkeypatch, True)
    _part()
    import db
    conn = db.get_db()
    try:
        rows = [("MQ-BIG", "n%03d" % i, "MR-BIG-%03d" % i, "已核准", "2026-11-01" if i < 520 else "2026-10-01", "pm") for i in range(600)]
        conn.executemany("INSERT INTO case_material_approvals (quote_no, item_id, doc_code, status, received_on, received_by) VALUES (?,?,?,?,?,?)", rows)
        conn.commit()
    finally:
        conn.close()
    _receive([_line([], mode="direct", materialItemId="n%03d" % i) for i in range(520)], quote_no="MQ-BIG")     # 最新的 520 筆都已處理
    r = client.get("/api/inventory/reconcile", headers=_auth(admin)).json()
    assert r["total"] == 80 and {i["itemId"] for i in r["items"]} == {"n%03d" % i for i in range(520, 600)}       # 較舊、未處理的沒被擠掉
    assert client.get("/api/inventory/reconcile?since=2026-10-15", headers=_auth(admin)).json()["total"] == 0
    assert client.get("/api/inventory/reconcile?since=yesterday", headers=_auth(admin)).status_code == 400


def test_delete_in_stock_item_leaves_a_delete_event(client, make_user, monkeypatch):
    admin = _login(client, *make_user(role="admin"))
    _flag(monkeypatch, True)
    _part()
    _receive([_line(["SN-DEL"])])
    sid = _q("SELECT id FROM stock_items WHERE serial_no='SN-DEL'")[0]["id"]
    assert client.delete("/api/inventory/stock-items/%d" % sid, headers=_auth(admin)).status_code == 200
    ev = _q("SELECT event, from_status, to_status FROM stock_item_events WHERE serial_no='SN-DEL' ORDER BY id")
    assert [e["event"] for e in ev] == ["receive", "delete"] and ev[1]["from_status"] == "in_stock"

