"""持 cashier 模組的非成員：讀得到任何案件，只能改收款（CM14b，2026-09-24 使用者裁示「讀得到，但只能改收款」）。

- 清單可見性（_visible_case_filter_sql）與單筆 GET：cashier 放行；地圖案件圖層（MP6）走同一個判準。
- 單筆 GET 回 `cashierReadOnly: true`（不是案件成員、靠 cashier 例外讀到的）⇒ 案件頁除收款外全唯讀。
- 寫入面不變：CM14 已擋（只放行 payment 分段）；報價單、叫料等仍走擁有者檢查。
- 沒有 cashier 的非成員：照舊看不到（403／清單沒有）。
"""
import json

import pytest

from tests.test_mp6_map_case_locations_2026_09_24 import (  # noqa: F401（_geo 是 fixture）
    CASE_A, CASE_ASSIGNED, CASE_B, CASE_QUOTE_ONLY, _cases, _geo, _seed as _mp6_seed, _uid,
)

NO = "MQ-CASHRD-001"


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _seed(roles=None):
    import db
    cr = {"payment": {"items": [{"id": 1, "type": "訂金款", "pct": 100, "amount": 100, "received": False,
                                 "note": ""}]},
          "materials": [{"id": 1, "name": "原料", "qty": 1}], "roles": roles or {}}
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (NO, "已送出", "客", "案", 100, 95, json.dumps({"dealTag": "已成案", "caseRecord": cr}, ensure_ascii=False),
             now, now, "已成案"))
        conn.commit()
    finally:
        conn.close()


def _listed(client, h):
    r = client.get("/api/quotations?deal_tag=已成案", headers=h)
    assert r.status_code == 200, r.text
    return NO in [it["quote_no"] for it in r.json()["items"]]


def test_non_member_cashier_reads_case_and_is_marked_read_only(client, make_user):
    u = make_user(username="crd_cash", role="engineer", modules=["case_manage", "cashier"])
    _seed()
    h = _login(client, *u)
    assert _listed(client, h)
    r = client.get(f"/api/quotations/{NO}", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["cashierReadOnly"] is True
    gm = client.get("/api/quotations/gate-matrix", headers=h).json()["items"]
    assert NO in [it["quoteNo"] for it in gm]


def test_member_cashier_is_not_read_only(client, make_user):
    u = make_user(username="crd_mem", role="engineer", modules=["case_manage", "cashier"])
    _seed(roles={"executor": "crd_mem"})
    r = client.get(f"/api/quotations/{NO}", headers=_login(client, *u))
    assert r.status_code == 200, r.text
    assert r.json()["cashierReadOnly"] is False


def test_non_member_without_cashier_still_cannot_read(client, make_user):
    u = make_user(username="crd_eng", role="engineer", modules=["case_manage"])
    _seed()
    h = _login(client, *u)
    assert not _listed(client, h)
    assert client.get(f"/api/quotations/{NO}", headers=h).status_code == 403


def test_reading_does_not_open_other_writes(client, make_user):
    """讀得到 ≠ 寫得到：報價單 PUT、叫料 PATCH 仍走擁有者檢查。"""
    import db
    u = make_user(username="crd_w", role="engineer", modules=["case_manage", "cashier", "project_manage"])
    _seed()
    conn = db.get_db()
    try:
        conn.execute("UPDATE quotations SET status='草稿' WHERE quote_no=?", (NO,))
        conn.commit()
    finally:
        conn.close()
    h = _login(client, *u)
    assert client.put(f"/api/quotations/{NO}", headers=h, json={"data": {"items": []}}).status_code == 403
    assert client.patch(f"/api/quotations/{NO}/material-orders", headers=h,
                        json={"materialOrders": []}).status_code == 403


def test_map_case_layer_matches_list_visibility_for_cashier(client, make_user, _geo):
    a = make_user(username="crd_mp_a", role="user", modules=["case_manage"])
    b = make_user(username="crd_mp_b", role="user", modules=["case_manage"])
    _mp6_seed(_uid(a[0]), _uid(b[0]))
    c = make_user(username="crd_mp_cash", role="user", modules=["case_manage", "cashier"])
    got, _, _ = _cases(client, _login(client, *c))
    assert got == sorted([CASE_A, CASE_B, CASE_ASSIGNED, CASE_QUOTE_ONLY]), got
