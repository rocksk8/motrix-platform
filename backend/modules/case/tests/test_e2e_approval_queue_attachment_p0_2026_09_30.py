"""瀏覽器層級（2026-09-30 P0）：簽核佇列裡，**不是案件的人**的簽核人仍看得到要簽的單據附件縮圖。

`/api/photo-token` 改為只簽給讀得到擁有單據的人之後，簽核人（常常不是案件的業務）單看路徑會被擋；
approval-queue 頁換簽章時帶目前詳情的 (type, id)，伺服器以詳情守門＋詳情列出的路徑放行。
稽核 S1：縮圖一次用批次端點換完（N 張圖＝1 次請求、1 次詳情守門），不再每張打一次單張端點。
觀測點：每張縮圖真的載出來（`naturalWidth > 0`）且 `/api/uploads/` 全 200；簽章請求＝批次 1 次、單張 0 次。
"""
import json
import os

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
       b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")
N = 3


@pytest.mark.e2e
def test_approver_not_on_case_sees_attachment_thumbnail(live_server, client, make_user, e2e_browser):
    import db
    import helpers.uploads as up
    u, p = make_user(username="aqp0_appr", role="sales", modules=["quotation"])
    quote_no = "MQ-AQP0-001"
    files = []
    for i in range(N):
        rel = f"quotations/{quote_no}/sign{i}.png"
        full = os.path.join(up.UPLOADS_ROOT, *rel.split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        open(full, "wb").write(PNG)
        files.append({"id": "s%d" % i, "filename": "sign%d.png" % i, "path": rel})
    data = {"quoteNo": quote_no, "approval": {
        "requestedBy": "someone_else", "requestedAt": "2026-09-30T09:00:00", "currentTier": 0,
        "tiers": [{"approvers": [{"username": "aqp0_appr", "displayName": "aqp0_appr", "status": "pending"}]}]}}
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, "
            "created_at, updated_at, deal_tag, sales_person, assigned_user_ids, signed_files_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "待審核", "客戶P0", "專案P0", 1000, 952, json.dumps(data, ensure_ascii=False),
             "2026-09-30T09:00:00", "2026-09-30T09:00:00", "", "別的業務", "[]", json.dumps(files)))
        conn.commit()
    finally:
        conn.close()

    # 前提：單看路徑，這個簽核人讀不到（不是案件的人）——否則下面的綠燈證明不了「帶情境」這件事
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    assert client.get("/api/photo-token", headers={"Authorization": "Bearer " + tok},
                      params={"path": files[0]["path"]}).status_code == 404

    seen, token_reqs = [], []
    page = e2e_browser.new_page()
    page.on("response", lambda r: seen.append((r.status, r.url)) if "/api/uploads/" in r.url else None)
    page.on("request", lambda r: token_reqs.append((r.method, r.url.split("?")[0]))
            if "/api/photo-token" in r.url else None)
    inject_login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/approval-queue.html")
    page.wait_for_selector(f"text={quote_no}", timeout=20000)
    page.click(f"text={quote_no}")
    sel = "img[src*='/api/uploads/']"
    page.wait_for_function("(n) => { const a = [...document.querySelectorAll(\"%s\")];"
                           " return a.length >= n && a.every(i => i.complete); }" % sel, arg=N, timeout=15000)
    widths = page.eval_on_selector_all(sel, "a => a.map(i => i.naturalWidth)")
    assert len(widths) == N and all(w > 0 for w in widths), f"簽核人看不到附件縮圖：{widths}；/api/uploads/ 回應：{seen}"
    assert len(seen) >= N and all(s == 200 for s, _ in seen), seen
    batch = [r for r in token_reqs if r[0] == "POST" and r[1].endswith("/api/photo-token/batch")]
    single = [r for r in token_reqs if r[0] == "GET"]
    assert len(batch) == 1 and not single, token_reqs      # S1：一次批次，不是每張一次
