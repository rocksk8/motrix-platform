"""報價單預覽改用伺服器版面（2026-09-24，裁示 P1～P4）。

原本「預覽」是 quotation-form.html 另畫的一份版面、「PDF」是 pdf_gen._build_quote_html()，
兩份各自維護，檢視報告列出 9 處可見差異（預覽寫死公司抬頭、項次編號不同…）。
現在預覽走 POST /api/quotations/preview-html，回傳與 PDF 同一支 builder 產生的 HTML。

這支題釘住：
- 同一張單，預覽 HTML 與 PDF 交給 Edge 的 HTML 逐字相同（只差預覽回報高度的那段 script）
- 挑 4 處原報告的差異驗證：公司抬頭、項次編號、毛利率小數位、NT$ 前綴
- 權限與 pdf-download 一致（這份 HTML 在 internal=true 時含成本，不能比它寬）
"""
import json

import pytest


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


QUOTE_NO = "MQ-202609-081"
DATA = {
    "quoteNo": QUOTE_NO, "customerName": "預覽客戶", "projectName": "預覽專案", "status": "已送出",
    "items": [
        {"id": 1, "type": "header", "description": "網路設備"},
        {"id": 2, "description": "交換器", "brand": "X", "qty": 2, "unit": "台",
         "cost": 5000, "margin": 0.355, "unitPrice": 12345, "amount": 24690},
        {"id": 3, "type": "header", "description": "伺服器"},
        {"id": 4, "description": "主機", "brand": "Y", "qty": 1, "unit": "台",
         "cost": 30000, "margin": 0.3, "unitPrice": 45000, "amount": 45000},
    ],
    "tot": {"total": 73174, "pretax": 69690, "directMarginPct": 0, "netMarginPct": 0},
}


def _seed(quote_no=QUOTE_NO, sales_person_id=None):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date, sales_person_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "預覽客戶", "預覽專案", 73174, 69690,
             json.dumps(dict(DATA, quoteNo=quote_no), ensure_ascii=False),
             "2026-09-01T00:00:00", "2026-09-01T00:00:00", "已成案", "2026-09-01", sales_person_id),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def captured_pdf_html(monkeypatch):
    """攔下 Edge：記下 PDF 那份 HTML，回一個假的 PDF。"""
    import pdf_gen
    seen = []

    def _fake_run(args, *a, **k):
        url = args[-1]
        path = url[len("file:///"):]
        seen.append(open(path, encoding="utf-8").read())
        out = next(x for x in args if x.startswith("--print-to-pdf=")).split("=", 1)[1]
        open(out, "wb").write(b"%PDF-1.4 fake")
    monkeypatch.setattr(pdf_gen, "run_edge_pdf", _fake_run)
    monkeypatch.setattr(pdf_gen, "_get_edge_path", lambda: "edge")
    return seen


@pytest.fixture
def custom_identity(monkeypatch):
    import pdf_gen
    ident = dict(pdf_gen.DEFAULT_IDENTITY)
    ident.update(company_name="測試抬頭有限公司", company_name_en="Test Header Co.",
                 tax_id="12345678", phone="02-1234-5678", email="t@example.com")
    monkeypatch.setattr(pdf_gen, "location_identity", lambda *_a, **_k: dict(ident))
    return ident


def _strip_report(html):
    i = html.find('<script>window.addEventListener("load",function(){setTimeout(function(){var r=')
    if i < 0:
        return html
    j = html.index("</script>", i) + len("</script>")
    return html[:i] + html[j:]


def _preview(client, token, internal=False, quote_no=QUOTE_NO, data=None):
    return client.post("/api/quotations/preview-html", headers=_auth(token),
                       json={"quoteNo": quote_no, "data": data or dict(DATA, quoteNo=quote_no),
                             "internal": internal})


@pytest.mark.parametrize("internal", [False, True])
def test_preview_html_is_the_same_as_pdf_html(client, make_user, captured_pdf_html,
                                              custom_identity, internal):
    u, p = make_user(username="pv_sa", role="superadmin")
    tok = _login(client, u, p)
    _seed()
    r = client.get(f"/api/quotations/{QUOTE_NO}/pdf-download" + ("?internal=true" if internal else ""),
                   headers=_auth(tok))
    assert r.status_code == 200, r.text
    assert len(captured_pdf_html) == 1
    pv = _preview(client, tok, internal=internal)
    assert pv.status_code == 200, pv.text
    html = pv.json()["html"]
    assert "motrixPreviewHeight" in html, "預覽要回報高度給主頁"
    assert _strip_report(html) == captured_pdf_html[0], "預覽與 PDF 必須是同一份版面"


def test_four_reported_differences_now_follow_the_server_layout(client, make_user, custom_identity):
    u, p = make_user(username="pv_sa2", role="superadmin")
    tok = _login(client, u, p)
    _seed()
    html = _preview(client, tok, internal=True).json()["html"]
    # ① 公司抬頭：跟著據點設定，不是寫死的公司名稱
    assert "測試抬頭有限公司" in html
    assert "允 碩 整 合" not in html and "60575481" not in html
    # ② 項次編號：區段標題不佔號，品項 1、2 連號
    assert "<td>1</td><td>交換器</td>" in html and "<td>2</td><td>主機</td>" in html
    # ③ 毛利率小數位：一位小數
    assert "35.5%" in html and "30.0%" in html
    # ④ NT$ 前綴與千分位
    assert "NT$ 12,345" in html and "NT$ 45,000" in html


def test_preview_uses_unsaved_edits(client, make_user):
    """預覽要反映畫面上還沒存的修改，不是資料庫裡的版本。"""
    u, p = make_user(username="pv_sa3", role="superadmin")
    tok = _login(client, u, p)
    _seed()
    edited = json.loads(json.dumps(DATA))
    edited["items"][1]["description"] = "還沒存的品名"
    html = _preview(client, tok, data=edited).json()["html"]
    assert "還沒存的品名" in html


# ── 權限：與 pdf-download 一致 ─────────────────────────────────────────────

@pytest.mark.parametrize("internal", [False, True])
def test_permission_matches_pdf_download_for_existing_quote(client, make_user, captured_pdf_html, internal):
    owner, op = make_user(username="pv_owner", role="sales")
    other, xp = make_user(username="pv_other", role="sales")
    import db
    conn = db.get_db()
    try:
        oid = conn.execute("SELECT id FROM users WHERE username=?", (owner,)).fetchone()["id"]
    finally:
        conn.close()
    _seed(sales_person_id=oid)
    qs = "?internal=true" if internal else ""
    for user, pw in ((owner, op), (other, xp)):
        tok = _login(client, user, pw)
        pdf = client.get(f"/api/quotations/{QUOTE_NO}/pdf-download{qs}", headers=_auth(tok)).status_code
        pv = _preview(client, tok, internal=internal).status_code
        assert pv == pdf, (user, internal, pv, pdf)
    assert _preview(client, _login(client, other, xp), internal=internal).status_code == 403, \
        "不是這張單的人不可以看到預覽（內部版含成本）"


def test_new_quote_requires_quotation_module(client, make_user):
    u1, p1 = make_user(username="pv_nomod", role="sales", modules=[])
    u2, p2 = make_user(username="pv_mod", role="sales", modules=["quotation"])
    body = dict(DATA, quoteNo="")
    r1 = client.post("/api/quotations/preview-html", headers=_auth(_login(client, u1, p1)),
                     json={"quoteNo": "", "data": body, "internal": False})
    r2 = client.post("/api/quotations/preview-html", headers=_auth(_login(client, u2, p2)),
                     json={"quoteNo": "", "data": body, "internal": False})
    assert r1.status_code == 403, r1.text
    assert r2.status_code == 200, r2.text


def test_watermark_rule_shared_with_pdf():
    """浮水印規則抽成一支，PDF 與預覽共用。"""
    import pdf_gen
    kw = pdf_gen._quote_watermark_kwargs("草稿", "")
    assert kw["show_watermark"] is True and "預覽稿" in kw["watermark_text"]
    kw = pdf_gen._quote_watermark_kwargs("已送出", "已成案")
    assert kw["show_watermark"] is False
    kw = pdf_gen._quote_watermark_kwargs("已送出", "未成案")
    assert kw["show_watermark"] is True and kw["show_notice"] is True
