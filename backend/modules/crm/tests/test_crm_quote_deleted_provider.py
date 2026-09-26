"""IP-13 `crm.quote_deleted` 提供方這一側（M02）：登記與正對照。拿掉本模組時這一檔跟著消失。

① 提供者已登記（模組載入時）
② 正對照：刪草稿報價單 ⇒ 連到它的案件連結清空、退回「洽談中」，別張單的案件不動；稽核照寫
反向控制（本模組不在）在 L1 側：`tests/platform/test_crm_quote_deleted_connector.py`。
"""


from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
from core import registry
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')

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
