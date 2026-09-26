"""M01-PLAN §5 ④ 補題（稽核 D 兩項觀察，主持 2026-09-26 併入 ④）。本檔需要 M01（隨模組搬走，PLAYBOOK §B-11）。

(a) 佇列詳情的金額遮蔽「看 dataUrl」那一層：id 不是 passbook、但帶內嵌影像（dataUrl）的檔案，沒有財務權的人也拿不到；
    正對照：本單簽核人（同樣非財務）拿得到。
(b) 轉簽時簽核鏈讀不出來 ⇒ 400（fail-closed），不依賴 M05：用 M01 自己的完工單（`completion_note`），
    M05 不在的安裝也驗得到這條路。
"""
import json

from core import registry


def _login(client, u, p):
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _seed_case(no, sales):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at, "
                     "deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (no, "已送出", "客", "案", "{}", "2026-09-26", "2026-09-26", "已成案", sales, "[]"))
        conn.commit()
    finally:
        conn.close()


def test_detail_drops_any_inline_image_for_users_without_money_rights(client, make_user, monkeypatch):
    su, sp = make_user(username="edg_sales", role="viewer", modules=["dashboard"])[:2]
    au, ap = make_user(username="edg_appr", role="viewer", modules=["dashboard"])[:2]
    _seed_case("MQ-EDG-1", "edg_sales")
    raw = json.dumps({"approval": {"currentTier": 0, "tiers": [{"approvers": [{"username": "edg_appr", "status": "pending"}]}]}})

    def fake_detail(conn, doc_no):
        return {"quoteNo": "MQ-EDG-1", "approvalRaw": raw, "title": "合成單據",
                "fields": [{"label": "金額", "value": "1,000"}], "items": [],
                "files": [{"id": "not-passbook", "name": "內嵌影像", "kind": "image", "path": "",
                           "dataUrl": "data:image/png;base64,AAAA"},
                          {"id": "f1", "name": "一般檔", "kind": "pdf", "path": "uploads/x.pdf"}]}
    orig = registry.providers
    monkeypatch.setattr(registry, "providers",
                        lambda cap: dict(orig(cap), zz_edge=fake_detail) if cap == "approval.detail" else orig(cap))
    url = "/api/approval-queue/detail?type=zz_edge&id=ZZ-1"
    sales = client.get(url, headers=_login(client, su, sp))
    assert sales.status_code == 200, sales.text
    body = sales.json()
    assert body.get("moneyMasked") is True
    assert not [f for f in body["files"] if f.get("dataUrl")], body["files"]          # 看的是 dataUrl，不只 id
    assert [f["id"] for f in body["files"]] == ["f1"]                                  # 一般檔照給
    appr = client.get(url, headers=_login(client, au, ap)).json()
    assert [f for f in appr["files"] if f.get("dataUrl", "").startswith("data:image/")]  # 正對照：簽核人拿得到


def test_reassign_refuses_an_unreadable_chain_without_needing_m05(client, make_user):
    import db
    su, sp = make_user(username="edg_super", role="superadmin")[:2]
    make_user(username="edg_new", role="admin")
    _seed_case("MQ-EDG-2", "someone")
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO completion_notes (note_no, quote_no, status, data_json, created_by, created_at, updated_at, "
                     "site_address, work_summary, items_json, warranty_months) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     ("CN-EDG-2", "MQ-EDG-2", "待審核", "{not json", "x", "2026-09-26", "2026-09-26", "台中", "x", "[]", 12))
        conn.commit()
    finally:
        conn.close()
    r = client.post("/api/approval-queue/reassign", headers=_login(client, su, sp),
                    json={"type": "completion_note", "id": "CN-EDG-2", "to_username": "edg_new", "reason": "請假"})
    assert r.status_code == 400 and "格式不正確" in r.json()["detail"], r.text
