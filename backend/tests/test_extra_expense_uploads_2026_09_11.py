"""額外支出的發票／收據附件上傳（2026-09-11，改版第四段）。

**取代 `test_settlement_extra_uploads_2026_08_31.py`**（同日移除）。舊的那組端點是
`/api/quotations/{no}/settlement/extra/{idx}/files`，用**陣列索引**定位 data_json 裡的
`settlement.extraItems[idx]`。額外支出搬到 `case_extra_expenses` 表（DB v75）之後，
端點改成用**資料列 id** 定位：索引會因為新增/刪除/重排而指到別筆去，id 不會。

**兩個刻意改掉的行為，不是漏測**：

1. 附件在「已核准」之後**上鎖**（2026-09-11 第二輪交辦）。這一條在同一天內翻過兩次：
   舊版「精算完結後一律擋下」→ 第一輪改成「核准後仍可補傳憑證」（理由是補憑證是
   會計常態）→ 使用者推翻，改回上鎖。**推翻的理由**：核准當下簽核人看到的憑證，
   跟事後被換掉的憑證不是同一份，等於簽核簽了一個會變的東西。補憑證的路徑改走
   「變更申請」——新檔案先存成待核准附件，簽核通過才併進正式清單
   （見 `test_xe_change_request_2026_09_11.py`）。
2. 舊版「索引超出範圍回 400」→ **新版不存在的 id 回 404**，語意更準確。

附件的實體檔案分類也從 `quotation_settlement_extra` 改成 `case_extra_expense`。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import io
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_case(quote_no="MQ-XEF-001"):
    import db
    import json
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測客", "測專", 100000, 95238,
             json.dumps({"dealTag": "已成案"}, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"),
        )
        conn.commit()
    finally:
        conn.close()


def _files_url(exp_id, quote_no="MQ-XEF-001"):
    return f"/api/quotations/{quote_no}/extra-expenses/{exp_id}/files"


def _upload(client, token, exp_id, names=("receipt.pdf",), quote_no="MQ-XEF-001"):
    files = [("files", (n, io.BytesIO(b"%PDF-1.4 test"), "application/pdf")) for n in names]
    return client.post(_files_url(exp_id, quote_no), headers=_auth(token), files=files)


def test_upload_and_delete(client, make_user, seed_extra_expense):
    username, password = make_user(username="xef1", role="admin")
    token = _login(client, username, password)
    _make_case()
    exp_id = seed_extra_expense("MQ-XEF-001", total_cost=1000, description="有附件的",
                                status="草稿")

    r = _upload(client, token, exp_id)
    assert r.status_code == 201, r.text
    assert r.json()["added"] == 1
    file_id = r.json()["files"][0]["id"]

    items = client.get("/api/quotations/MQ-XEF-001/extra-expenses",
                       headers=_auth(token)).json()["items"]
    assert len(items[0]["files"]) == 1
    assert items[0]["files"][0]["filename"] == "receipt.pdf"

    r2 = client.delete(f"{_files_url(exp_id)}/{file_id}", headers=_auth(token))
    assert r2.status_code == 200, r2.text
    items = client.get("/api/quotations/MQ-XEF-001/extra-expenses",
                       headers=_auth(token)).json()["items"]
    assert items[0]["files"] == []


def test_upload_multiple_files_at_once(client, make_user, seed_extra_expense):
    username, password = make_user(username="xef2", role="admin")
    token = _login(client, username, password)
    _make_case()
    # fixture 的 status 預設是「已核准」，而已核准之後附件已上鎖（見模組 docstring
    # 第 1 點），所以這裡要明確種成草稿才測得到「一次傳多檔」本身
    exp_id = seed_extra_expense("MQ-XEF-001", total_cost=1000, description="多檔",
                                status="草稿")

    r = _upload(client, token, exp_id, names=("a.pdf", "b.pdf", "c.pdf"))
    assert r.status_code == 201, r.text
    assert r.json()["added"] == 3


def test_unknown_id_returns_404_not_400(client, make_user):
    """舊版用陣列索引、超出範圍回 400；改用資料列 id 之後，不存在就是 404。"""
    username, password = make_user(username="xef3", role="admin")
    token = _login(client, username, password)
    _make_case()
    r = _upload(client, token, 999999)
    assert r.status_code == 404, r.text


def test_upload_locked_after_approval(client, make_user, seed_extra_expense):
    """**刻意的行為改變（2026-09-11 第二輪，翻掉同日第一輪的決定）**：已核准之後
    附件跟金額一起上鎖。

    第一輪開放核准後補傳憑證，理由是「補憑證是會計常態」。使用者推翻了它——核准
    當下簽核人看到的憑證，跟事後被換掉的憑證不是同一份。補憑證改走變更申請
    （`test_xe_change_request_2026_09_11.py::test_pending_change_files_are_not_visible_until_approved`）。
    """
    username, password = make_user(username="xef4", role="admin")
    token = _login(client, username, password)
    _make_case()
    exp_id = seed_extra_expense("MQ-XEF-001", total_cost=1000, description="已核准的",
                                status="已核准")

    r = _upload(client, token, exp_id)
    assert r.status_code == 409, "已核准的項目不可再上傳附件"
    assert "上鎖" in r.json()["detail"], "訊息要指出改走變更申請，不能只說不可修改"

    # 刪除既有附件同樣上鎖——只擋上傳等於還是能把憑證弄不見
    r_del = client.delete(f"{_files_url(exp_id)}/anything", headers=_auth(token))
    assert r_del.status_code == 409, "已核准的附件也不可刪除"

    # 金額當然仍然不能改
    r2 = client.patch(f"/api/quotations/MQ-XEF-001/extra-expenses/{exp_id}",
                      headers=_auth(token),
                      json={"description": "偷改", "qty": 1, "unitCost": 99999})
    assert r2.status_code == 409, "已核准的金額仍然不可修改"


def test_upload_requires_case_access(client, make_user, seed_extra_expense):
    """擁有者檢查不能省——quote_no 可列舉。"""
    owner, _ = make_user(username="xef_owner", role="admin")
    outsider, outsider_pw = make_user(username="xef_out", role="engineer")
    _make_case()
    exp_id = seed_extra_expense("MQ-XEF-001", total_cost=100, description="別人的案件")

    token = _login(client, outsider, outsider_pw)
    r = _upload(client, token, exp_id)
    assert r.status_code == 404, r.text   # M01-O1：看不到＝不存在（同一個 404）
