"""IP-11 `crm.quote_deleted`：刪報價單時解除業務開發案件的轉建連結（M02 搬遷，2026-09-26）。

原本 M01 `routers/quotations.py` 直寫 `dev_cases`（table_write_exceptions 的 debt）⇒ 改由 M02 提供。
① 提供者已登記（模組載入時）
② 正對照：刪草稿報價單 ⇒ 連到它的案件連結清空、退回「洽談中」，別張單的案件不動；稽核照寫
③ 反向控制：M02 不在 ⇒ 報價單照刪、案件不動、回應 notice 明說、記 WARNING
④ 產品碼除了 M02 與凍結 migration，沒有寫 dev_cases／dev_logs 的 SQL
"""
import logging
import re

import pytest

from core import registry

QNO, OTHER = "MQ-IP11-0926", "MQ-IP11-OTHER"


def _login(client, make_user):
    u, p = make_user("ip11_super", "Conn-Pass-123", role="superadmin")[:2]
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _seed():
    import db
    conn = db.get_db()
    try:
        now = "2026-09-26T00:00:00"
        for q in (QNO, OTHER):
            conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
                         "data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                         (q, "草稿", "客", "案", 0, 0, "{}", now, now))
        for name, q in (("連到要刪的", QNO), ("連到別張", OTHER)):
            conn.execute("INSERT INTO dev_cases (case_name, customer_name, status, converted_quote_no, created_by, "
                         "created_at, updated_at) VALUES (?,?,?,?,?,?,?)", (name, "客", "成案", q, 1, now, now))
        conn.commit()
    finally:
        conn.close()


def _cases():
    import db
    conn = db.get_db()
    try:
        return {r["case_name"]: (r["converted_quote_no"], r["status"])
                for r in conn.execute("SELECT case_name, converted_quote_no, status FROM dev_cases")}
    finally:
        conn.close()


def test_provider_is_registered(client):
    assert set(registry.providers("crm.quote_deleted")) == {"crm"}


def test_deleting_a_quote_unlinks_only_its_dev_cases(client, make_user):
    h = _login(client, make_user)
    _seed()
    r = client.delete("/api/quotations/%s" % QNO, headers=h)
    assert r.status_code == 200 and r.json() == {"ok": True}, r.text
    assert _cases() == {"連到要刪的": ("", "洽談中"), "連到別張": (OTHER, "成案")}
    import db
    conn = db.get_db()
    try:
        assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='dev_case.unlink_deleted_quote'").fetchone()[0] == 1
    finally:
        conn.close()


def test_without_crm_the_quote_is_deleted_and_the_user_is_told(client, make_user, monkeypatch, caplog):
    h = _login(client, make_user)
    _seed()
    orig = registry.providers
    monkeypatch.setattr(registry, "providers", lambda cap: {} if cap == "crm.quote_deleted" else orig(cap))
    from routers import quotations
    with caplog.at_level(logging.WARNING):
        r = client.delete("/api/quotations/%s" % QNO, headers=h)
    assert r.status_code == 200 and r.json() == {"ok": True, "notice": quotations.QUOTE_DELETED_CRM_ABSENT}
    assert _cases() == {"連到要刪的": (QNO, "成案"), "連到別張": (OTHER, "成案")}
    assert any("業務開發模組未安裝" in rec.getMessage() for rec in caplog.records)
    assert client.get("/api/quotations/%s" % QNO, headers=h).status_code == 404


def test_no_writes_to_dev_cases_outside_crm():
    from core import source_tree
    pat = re.compile(r"(UPDATE|INSERT\s+INTO|DELETE\s+FROM)\s+dev_(cases|logs)\b", re.I)
    hits, scanned = [], 0
    for p in source_tree.product_files():
        rel = source_tree.rel(p)
        if rel.startswith("modules/crm/") or rel == "db.py":        # 擁有者；db.py 是凍結 migration（CORE-SPEC §6）
            continue
        scanned += 1
        hits += ["%s: %s" % (rel, m.group(0)) for m in pat.finditer(p.read_text(encoding="utf-8"))]
    assert scanned > 100 and not hits, hits
