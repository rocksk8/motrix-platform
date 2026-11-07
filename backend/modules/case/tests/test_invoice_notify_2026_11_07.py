# -*- coding: utf-8 -*-
"""案件發票上傳 → 通知財務＋最高管理者（2026-11-07；設計 docs/platform/plans/CASE-INVOICE-UPLOAD-NOTIFY-DESIGN.md）。

驗收（設計 §4）：①兩個端點直接上傳各寄一次（多檔也一次），內容含案件編號與檔案數、不含檔名；②半解鎖暫存不寄、核准套用後寄一次；
③到貨憑證附件／刪除不寄；④寄信丟例外 ⇒ 上傳仍 201、資料已存、稽核照寫；⑤收件人（財務＋超管收；admin／sales 不收；退訂不收；覆寫僅超管）。
"""
import io
import json

import pytest

from tests._requires import requires_module  # noqa: E402
pytestmark = requires_module("case", "本檔打 M01（案件）的上傳端點")

_MAKE_USER_DEFAULT_ROLE = "superadmin"


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


_PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
                     "de0000000c4944415478da6360000002000155a5e6ce0000000049454e44ae42"
                     "6082")
_SECRET_NAME = "invoice-NT99999-secret.png"


def _png(name=_SECRET_NAME):
    return (name, io.BytesIO(_PNG), "image/png")


def _make_quotation(no, deal_tag="已成案"):
    import db
    conn = db.get_db()
    try:
        data = {"customerName": "測試客戶", "projectName": "測試專案", "dealTag": deal_tag,
                "caseRecord": {"payment": {"items": [{"id": "p1", "label": "第一期款", "invoiceNo": ""}]},
                               "materials": [{"id": "m1", "name": "測試料件A", "files": [], "invoiceFiles": []}]}}
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)", (no, "已送出", "測試客戶", "測試專案", 100000, 95238, json.dumps(data),
                                                      "2026-01-01T00:00:00", "2026-01-01T00:00:00", deal_tag))
        if deal_tag == "已結案":
            conn.execute("INSERT INTO case_stages (quote_no, label, sort_order, done, done_at, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                         (no, "階段一", 0, 1, "2026-01-01T00:00:00", "2026-01-01T00:00:00", "2026-01-01T00:00:00"))
            # 完結案前置：款項已收
            d = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (no,)).fetchone()["data_json"])
            d["caseRecord"]["payment"]["items"][0].update({"received": True, "receivedAt": "2026-08-01"})
            conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), no))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def sent(monkeypatch):
    """攔 `send_registered`：只記呼叫，不真的寄。"""
    from helpers import email_notify as en
    calls = []

    def _fake(event_key, **kw):
        calls.append((event_key, kw))
        return True
    monkeypatch.setattr(en, "send_registered", _fake)
    return calls


def _rows(kw):
    return dict(kw["rows"])


# ── ① 直接上傳 ──────────────────────────────────────────────────────────────

def test_payment_invoice_upload_sends_one_mail_for_many_files(client, make_user, sent):
    u, p = make_user(username="up1")
    t = _login(client, u, p)
    _make_quotation("MQ-INV-001")
    r = client.post("/api/quotations/MQ-INV-001/payment/0/invoice-files", headers=_auth(t),
                    files=[("files", _png("a-NT111.png")), ("files", _png("b-NT222.png"))])
    assert r.status_code == 201, r.text
    assert len(sent) == 1, sent
    key, kw = sent[0]
    assert key == "case_invoice_uploaded" and kw["to_group"] is True and not kw.get("usernames")
    rows = _rows(kw)
    assert rows["案件編號"] == "MQ-INV-001" and rows["檔案數量"] == "2 個"
    assert rows["項目"] == "第一期款" and rows["上傳人"] == "up1" and "測試客戶" in rows["客戶／專案"]
    blob = json.dumps(kw, ensure_ascii=False)
    assert "NT111" not in blob and "NT222" not in blob, "信件不可含檔名（檔名常含金額）"
    assert "q=MQ-INV-001" in kw["link"]


def test_material_invoice_upload_sends_one_mail(client, make_user, sent):
    u, p = make_user(username="up2")
    t = _login(client, u, p)
    _make_quotation("MQ-INV-002")
    r = client.post("/api/quotations/MQ-INV-002/materials/0/invoice-files", headers=_auth(t), files={"files": _png()})
    assert r.status_code == 201, r.text
    assert len(sent) == 1
    rows = _rows(sent[0][1])
    assert rows["項目"] == "測試料件A" and rows["類別"] == "叫料發票" and rows["檔案數量"] == "1 個"
    assert _SECRET_NAME not in json.dumps(sent[0][1], ensure_ascii=False)


def test_uploader_who_is_superadmin_still_triggers_mail(client, make_user, sent):
    """Q2：上傳人自己是最高管理者（財務角色同理，收件人由群組決定、不特別排除）也照寄。"""
    u, p = make_user(username="up3", role="superadmin")
    t = _login(client, u, p)
    _make_quotation("MQ-INV-003")
    r = client.post("/api/quotations/MQ-INV-003/payment/0/invoice-files", headers=_auth(t), files={"files": _png()})
    assert r.status_code == 201, r.text
    assert len(sent) == 1 and sent[0][1].get("usernames") in (None, [])      # 不帶 usernames ⇒ 沒有「排除上傳人」的路徑


# ── ② 半解鎖暫存不寄、核准後寄 ───────────────────────────────────────────────

def _unlocked_closed_case(client, make_user, no):
    sa_u, sa_p = make_user(username="sa_" + no[-3:], role="superadmin")
    ed_u, ed_p = make_user(username="ed_" + no[-3:], role="superadmin")
    sa, ed = _login(client, sa_u, sa_p), _login(client, ed_u, ed_p)
    _make_quotation(no, deal_tag="已結案")
    r = client.post(f"/api/quotations/{no}/case-unlock", headers=_auth(ed))
    assert r.status_code == 200, r.text
    return sa, ed


@pytest.mark.parametrize("path,key,idx_url", [("payment", "payment_invoice_upload", "payment/0/invoice-files"),
                                              ("material", "material_invoice_upload", "materials/0/invoice-files")])
def test_semi_unlock_staged_upload_no_mail_until_approved(client, make_user, sent, path, key, idx_url):
    no = "MQ-INV-9%s" % ("1" if path == "payment" else "2")
    sa, ed = _unlocked_closed_case(client, make_user, no)
    r = client.post(f"/api/quotations/{no}/{idx_url}", headers=_auth(ed), files=[("files", _png()), ("files", _png("x.png"))])
    assert r.status_code == 201, r.text
    assert r.json()["pending"] is True
    assert sent == [], "暫存階段發票還沒進案件 ⇒ 不寄"
    cid = r.json()["changeRequestId"]
    ap = client.post(f"/api/case-changes/{cid}/approve", headers=_auth(sa))
    assert ap.status_code == 200, ap.text
    assert len(sent) == 1, sent
    rows = _rows(sent[0][1])
    assert rows["案件編號"] == no and rows["檔案數量"] == "2 個" and rows["上傳人"].startswith("ed_")
    assert rows["類別"] == ("款項發票" if path == "payment" else "叫料發票")


def test_semi_unlock_reject_sends_nothing(client, make_user, sent):
    no = "MQ-INV-930"
    sa, ed = _unlocked_closed_case(client, make_user, no)
    r = client.post(f"/api/quotations/{no}/payment/0/invoice-files", headers=_auth(ed), files={"files": _png()})
    cid = r.json()["changeRequestId"]
    rj = client.post(f"/api/case-changes/{cid}/reject", headers=_auth(sa), json={"reason": "x"})
    assert rj.status_code == 200, rj.text
    assert sent == []


# ── ③ 其他附件／刪除不寄 ─────────────────────────────────────────────────────

def test_material_file_upload_and_deletes_do_not_mail(client, make_user, sent):
    u, p = make_user(username="up4")
    t = _login(client, u, p)
    _make_quotation("MQ-INV-004")
    r = client.post("/api/quotations/MQ-INV-004/materials/0/files", headers=_auth(t),
                    files={"files": ("t.pdf", b"%PDF-1.4 fake", "application/pdf")})
    assert r.status_code == 201, r.text
    assert sent == [], "到貨憑證等一般附件不寄"
    up = client.post("/api/quotations/MQ-INV-004/payment/0/invoice-files", headers=_auth(t), files={"files": _png()})
    assert up.status_code == 201 and len(sent) == 1
    fid = up.json()["files"][0]["id"]
    d = client.delete(f"/api/quotations/MQ-INV-004/payment/0/invoice-files/{fid}", headers=_auth(t))
    assert d.status_code == 200, d.text
    assert len(sent) == 1, "刪除不寄"


# ── ④ 寄信失敗不擋上傳 ───────────────────────────────────────────────────────

def test_mail_failure_never_breaks_upload(client, make_user, monkeypatch):
    from helpers import email_notify as en

    def _boom(*a, **k):
        raise RuntimeError("smtp down")
    monkeypatch.setattr(en, "send_registered", _boom)
    u, p = make_user(username="up5")
    t = _login(client, u, p)
    _make_quotation("MQ-INV-005")
    r = client.post("/api/quotations/MQ-INV-005/payment/0/invoice-files", headers=_auth(t), files={"files": _png()})
    assert r.status_code == 201, r.text
    assert r.json()["added"] == 1
    cr = client.get("/api/quotations/MQ-INV-005", headers=_auth(t)).json()["data"]["caseRecord"]
    assert len(cr["payment"]["items"][0]["invoiceFiles"]) == 1, "資料已存"
    import db
    conn = db.get_db()
    try:
        n = conn.execute("SELECT COUNT(*) AS c FROM audit_log WHERE action='payment.upload_invoice_files' AND target_id='MQ-INV-005'").fetchone()["c"]
    finally:
        conn.close()
    assert n == 1, "稽核照寫"


def test_fire_uploaded_never_raises_and_logs_reason(monkeypatch, caplog):
    from helpers import email_notify as en
    from modules.case import invoice_notify as IN

    def _boom(*a, **k):
        raise ValueError("原因-XYZ")
    monkeypatch.setattr(en, "send_registered", _boom)
    with caplog.at_level("ERROR"):
        assert IN.fire_uploaded("MQ-X", kind="payment", item_label="第一期", uploader="u", file_count=1) is False
    assert "原因-XYZ" in caplog.text and "MQ-X" in caplog.text, "失敗原因要進 log"
    IN.fire_uploaded(None, kind="zzz", item_label=None, uploader=None, file_count=None)           # 欄位缺值也不丟例外


def test_notice_tolerates_bad_data():
    from modules.case import invoice_notify as IN
    assert IN.notice("MQ-1", None, kind="payment", item_label="x", uploader="u", file_count=1)["customer"] == ""
    assert IN.notice("MQ-1", [1], kind="payment", item_label="x", uploader="u", file_count=1)["project"] == ""


def test_notice_never_raises_and_send_notice_tolerates_none(caplog):
    """組裝（notice）丟例外不可往外冒：回 None＋記 log；send_notice(None) ⇒ False（K 審建議修）。"""
    from modules.case import invoice_notify as IN

    class _BadDict(dict):
        def get(self, *a, **k):
            raise RuntimeError("壞資料-ABC")
    with caplog.at_level("ERROR"):
        assert IN.notice("MQ-BAD", _BadDict(), kind="payment", item_label="x", uploader="u", file_count=1) is None
    assert "壞資料-ABC" in caplog.text and "MQ-BAD" in caplog.text
    assert IN.send_notice(None) is False and IN.send_notice({}) is False


def test_assembly_failure_in_apply_path_does_not_fail_approval(client, make_user, monkeypatch, sent):
    """半解鎖套用路徑：notice 組裝在 commit 之前、交易內——它出錯也不可讓核准失敗（稽核與套用照常）。"""
    from modules.case import invoice_notify as IN
    no = "MQ-INV-940"
    sa, ed = _unlocked_closed_case(client, make_user, no)
    r = client.post(f"/api/quotations/{no}/payment/0/invoice-files", headers=_auth(ed), files={"files": _png()})
    assert r.status_code == 201 and r.json()["pending"] is True
    cid = r.json()["changeRequestId"]

    def _boom(*a, **k):
        raise RuntimeError("assemble boom")
    monkeypatch.setattr(IN, "notice", _boom)
    ap = client.post(f"/api/case-changes/{cid}/approve", headers=_auth(sa))
    assert ap.status_code == 200, ap.text
    assert sent == []
    cr = client.get(f"/api/quotations/{no}", headers=_auth(sa)).json()["data"]["caseRecord"]
    assert len(cr["payment"]["items"][0]["invoiceFiles"]) == 1, "發票已套用"


# ── ⑤ 收件人（走真的 send_registered，只攔 _async_send）─────────────────────

def _set_user(username, email=None, muted=None, active=1):
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE users SET email=?, notification_muted=?, active=? WHERE username=?",
                     (email, json.dumps(muted or []), active, username))
        conn.commit()
    finally:
        conn.close()


def _capture_mail(monkeypatch):
    from helpers import email_notify as en
    out = []

    class _H:
        def wait(self, *a, **k):
            return en.SEND_SENT
    monkeypatch.setattr(en, "_async_send", lambda to, subject, html: (out.append((list(to), subject, html)), _H())[1])
    monkeypatch.setattr(en, "_mail_off", lambda *a, **k: False, raising=False)
    return out


def test_recipients_finance_and_superadmin_only(client, make_user, monkeypatch):
    out = _capture_mail(monkeypatch)
    for name, role, mail in [("r_sa", "superadmin", "sa@x.test"), ("r_fin", "finance", "fin@x.test"), ("r_fin2", "finance", "fin2@x.test"),
                             ("r_adm", "admin", "adm@x.test"), ("r_sales", "sales", "sales@x.test"), ("r_view", "viewer", "view@x.test"),
                             ("r_off", "finance", "off@x.test"), ("r_gone", "finance", "gone@x.test")]:
        make_user(username=name, role=role)
    for name, mail, muted, active in [("r_sa", "sa@x.test", [], 1), ("r_fin", "fin@x.test", ["module_activity"], 1),     # 退訂別的類型 ⇒ 不影響本類型
                                      ("r_fin2", "fin2@x.test", ["case_invoice_uploaded"], 1),                         # 退訂本類型 ⇒ 不收
                                      ("r_adm", "adm@x.test", [], 1), ("r_sales", "sales@x.test", [], 1), ("r_view", "view@x.test", [], 1),
                                      ("r_off", None, [], 1), ("r_gone", "gone@x.test", [], 0)]:
        _set_user(name, mail, muted, active)
    u, p = make_user(username="r_up")
    t = _login(client, u, p)
    _make_quotation("MQ-INV-006")
    r = client.post("/api/quotations/MQ-INV-006/payment/0/invoice-files", headers=_auth(t), files={"files": _png()})
    assert r.status_code == 201, r.text
    mails = [m for m in out if "發票" in m[1]]
    assert len(mails) == 1, out
    to = set(mails[0][0])
    assert {"sa@x.test", "fin@x.test"} <= to
    assert not ({"fin2@x.test", "adm@x.test", "sales@x.test", "view@x.test", "off@x.test", "gone@x.test"} & to), to
    assert "MQ-INV-006" in mails[0][1]            # 主旨寫結果（含案件編號）
    assert _SECRET_NAME not in mails[0][2] and "NT99999" not in mails[0][2]


def test_registered_as_finance_group_and_case_owned():
    from helpers import mail_types as mt
    import modules.case  # noqa: F401  載入時登記
    t = mt.get("case_invoice_uploaded")
    assert t is not None and t.group == "finance" and t.category == "business"
