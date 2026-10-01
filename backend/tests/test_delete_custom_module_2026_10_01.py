# -*- coding: utf-8 -*-
"""建構器「刪除模組」：無單據可直接刪；有單據 409；with_records 才連單據刪；已入帳一律拒絕；不影響其他模組。"""
from tests.test_custom_modules_engine_2026_09_25 import KEY, _new, loan  # noqa: F401  (loan 是 fixture)

URL = "/api/definitions/custom_module/%s" % KEY


def _keys(client, h):
    return [d["key"] for d in client.get("/api/definitions/custom_module", headers=h["super"]).json()]


def test_delete_module_without_records(loan):
    client, h = loan
    r = client.delete(URL, headers=h["super"])
    assert r.status_code == 200 and r.json()["versions"] >= 1 and r.json()["records"] == 0
    assert KEY not in _keys(client, h)
    assert client.get("/api/custom-modules", headers=h["super"]).json() == []


def test_delete_module_with_records_is_refused_then_forced(loan):
    client, h = loan
    _new(client, h)
    r = client.delete(URL, headers=h["super"])
    assert r.status_code == 409 and r.json()["records"] == 1
    assert KEY in _keys(client, h)
    r = client.delete(URL + "?with_records=1", headers=h["super"])
    assert r.status_code == 200 and r.json()["records"] == 1
    from db import get_db
    conn = get_db()
    try:
        assert conn.execute("SELECT COUNT(*) FROM custom_records WHERE module_key=?", (KEY,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM custom_record_values WHERE module_key=?", (KEY,)).fetchone()[0] == 0
    finally:
        conn.close()


def test_delete_module_with_finance_outbox_is_refused_even_forced(loan):
    client, h = loan
    rec = _new(client, h)
    from db import get_db
    conn = get_db()
    try:
        rid = conn.execute("SELECT id FROM custom_records WHERE module_key=?", (KEY,)).fetchone()[0]
        conn.execute("INSERT INTO custom_record_finance_outbox (dedupe_key, event, module_key, record_id, record_no) "
                     "VALUES ('t1','x',?,?,?)", (KEY, rid, rec["record_no"]))
        conn.commit()
    finally:
        conn.close()
    assert client.delete(URL + "?with_records=1", headers=h["super"]).status_code == 409
    assert KEY in _keys(client, h)


def test_delete_module_superadmin_only_and_missing(loan):
    client, h = loan
    assert client.delete(URL, headers=h["req"]).status_code in (401, 403)
    assert client.delete("/api/definitions/custom_module/no_such_mod", headers=h["super"]).status_code == 404
