"""M06 會計傳票 不在時，別人那一側照常（M06-PLAN §1-C；IP-22 `voucher.by_case`）。

合成：拿掉提供者（`_without`）；真正拿掉模組的反向控制見 PLAYBOOK §B-11。
"""
from tests.platform.test_case_stage_connectors import _without

QNO = "MQ-ACC-CONN-1"


def _hdr(client, make_user):
    u, p = make_user(username="acc_conn", role="superadmin")
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _seed():
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, data_json, created_at, updated_at)"
                     " VALUES (?,?,?,?,?)", (QNO, "已送出", "{}", "2026-01-01", "2026-01-01"))
        conn.commit()
    finally:
        conn.close()


def test_case_bundle_without_m06(client, make_user, monkeypatch):
    """IP-22：傳票段 404 並說出原因；其他段照常。"""
    from routers import quotations as q
    h = _hdr(client, make_user)
    _seed()
    _without(monkeypatch, "voucher.by_case", "accounting")
    r = client.get("/api/quotations/%s/case-bundle" % QNO, headers=h)
    assert r.status_code == 200
    assert r.json()["parts"]["vouchers"] == {"ok": False, "status": 404, "detail": q.VOUCHERS_UNAVAILABLE}
    assert r.json()["parts"]["updates"]["ok"] is True


def test_case_bundle_with_m06_lists_vouchers(client, make_user):
    """正對照：M06 在 ⇒ 提供者一定在、傳票段 ok（空案件 ⇒ 空清單）。
    略過的判準是「模組在不在」，不是「提供者在不在」——後者正是要驗的東西（漏宣告時要紅，不是略過）。"""
    from core import source_tree
    if not source_tree.module_installed("modules/accounting/"):
        import pytest
        pytest.skip("M06 不在")
    h = _hdr(client, make_user)
    _seed()
    r = client.get("/api/quotations/%s/case-bundle" % QNO, headers=h)
    assert r.json()["parts"]["vouchers"] == {"ok": True, "data": {"vouchers": []}}
