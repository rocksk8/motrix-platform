"""IP-13 `crm.quote_deleted` 取用方這一側（M01 刪報價單）：M02 不在時也要成立的題（M02 搬遷，2026-09-26）。

原本 M01 `modules/case/api/quotations.py` 直寫 `dev_cases`（table_write_exceptions 的 debt）⇒ 改由 M02 提供。
③ 反向控制：M02 不在 ⇒ 報價單照刪、案件不動、回應 notice 明說、記 WARNING
④ 產品碼除了 M02 與凍結 migration，沒有寫 dev_cases／dev_logs 的 SQL
提供方的登記與正對照在 `modules/crm/tests/test_crm_quote_deleted_provider.py`（隨模組搬走）。
"""
import logging
import re

import pytest

from core import registry
from core import source_tree  # noqa: E402

#: M01 ④(c)（主持裁示）：題目本身就是驗 M01（案件）的行為 ⇒ M01 不在的安裝包略過；理由逐題寫在 reason
def needs_case(reason):
    return pytest.mark.skipif(not source_tree.module_installed("modules/case/"),
                              reason="需要案件模組（M01）：" + reason)


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


@needs_case('刪報價單的端點屬 M01')
def test_without_crm_the_quote_is_deleted_and_the_user_is_told(client, make_user, monkeypatch, caplog):
    h = _login(client, make_user)
    _seed()
    orig = registry.providers
    monkeypatch.setattr(registry, "providers", lambda cap: {} if cap == "crm.quote_deleted" else orig(cap))
    from modules.case.api import quotations
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
