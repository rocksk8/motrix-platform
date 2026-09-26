"""金額四捨五入：採購建議的預估成本（M03 端點）。

2026-09-26 自 `backend/tests/test_money_round_half_up_2026_09_26.py` 移入（PLAYBOOK §B-11：拿掉本模組時這些題跟著消失）。
"""


def test_purchase_suggestion_cost_rounds_half_up_to_cents(client, make_user):
    """採購建議預估金額：單價 0.0625 × 建議量 2 ＝ 0.125 ⇒ 0.13（舊：round(0.125, 2)＝0.12）。inventory L237、L250"""
    u, p = make_user(role="admin")
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    h = {"Authorization": "Bearer " + tok}
    r = client.post("/api/parts", headers=h, json={"partNo": "VAT-PS1", "name": "料", "category": "其他",
                                                   "safetyStock": 1, "cost": 0.0625})
    assert r.status_code == 201, r.text
    d = client.get("/api/inventory/purchase-suggestions", headers=h).json()
    it = next(x for x in d["items"] if x["part_no"] == "VAT-PS1")
    assert it["suggestedQty"] == 2, it                                                     # 前提
    assert it["estimatedCost"] == 0.13
    assert d["totalEstimatedCost"] == 0.13
