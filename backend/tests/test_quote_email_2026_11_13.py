"""報價用公司信箱（2026-11-13）：使用者設定 → 公司對外信箱 → 個人信箱；只有最高管理者能設；已開出的報價單不變；信件只加 Reply-To。"""
import json
from core.source_tree import page_file as _page_file
from pathlib import Path

import pytest

from helpers import quote_email as QE


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _uid(username):
    from db import get_db
    conn = get_db()
    r = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    conn.close()
    return r["id"]


def _set_personal(username, email):
    from db import get_db
    conn = get_db()
    conn.execute("UPDATE users SET email=? WHERE username=?", (email, username))
    conn.commit()
    conn.close()


@pytest.fixture
def su(client, make_user):
    u, p = make_user(username="qe_root", role="superadmin")
    return _login(client, u, p)


def _company(client, su, ext):
    r = client.put("/api/settings/company-profile", json={"external_email": ext}, headers=su)
    assert r.status_code == 200, r.text
    return r


# ── 純函式：三層優先 ──────────────────────────────────────────────────────────

def test_precedence_three_levels_pure():
    assert QE.resolve("me@corp.com", "sales@corp.com", "me@gmail.com") == {"email": "me@corp.com", "source": "user"}
    assert QE.resolve("", "sales@corp.com", "me@gmail.com") == {"email": "sales@corp.com", "source": "company"}
    assert QE.resolve("", "", "me@gmail.com") == {"email": "me@gmail.com", "source": "personal"}
    assert QE.resolve("", "", "") == {"email": "", "source": "none"}
    # 格式不合法視為沒填（不會被當成有效值帶進單據）
    assert QE.resolve("not-an-email", "x@@y", "me@gmail.com")["source"] == "personal"


def test_valid_and_domain_hint_never_blocks():
    assert QE.valid("a.b+c@corp.com.tw") and not QE.valid("a@b") and not QE.valid("a b@corp.com") and not QE.valid("")
    assert "私人信箱" in QE.domain_hint("me@gmail.com", "sales@corp.com")
    assert "不同" in QE.domain_hint("me@other.com", "sales@corp.com")
    assert QE.domain_hint("me@corp.com", "sales@corp.com") == "" and QE.domain_hint("", "x@corp.com") == ""


# ── API：三層優先（使用者列表／報價人聯絡／我的帳號）──────────────────────────────

def test_precedence_end_to_end_api(client, make_user, su):
    u, p = make_user(username="qe_sales", role="sales")
    _set_personal(u, "private@gmail.com")
    h = _login(client, u, p)
    uid = _uid(u)

    def mine():
        return next(x for x in client.get("/api/users", headers=h).json() if x["username"] == u)

    # ③只有個人信箱
    assert (mine()["quoteEmailEffective"], mine()["quoteEmailSource"]) == ("private@gmail.com", "personal")
    prof = client.get("/api/auth/profile", headers=h).json()
    assert prof["quoteEmailSource"] == "personal" and prof["quoteEmail"] == ""
    # ②公司對外信箱
    _company(client, su, "sales@corp.com")
    assert (mine()["quoteEmailEffective"], mine()["quoteEmailSource"]) == ("sales@corp.com", "company")
    # ①使用者自己的報價用信箱
    assert client.put(f"/api/users/{uid}", json={"quote_email": "rick@corp.com"}, headers=su).status_code == 200
    assert (mine()["quoteEmailEffective"], mine()["quoteEmailSource"]) == ("rick@corp.com", "user")
    assert client.get("/api/auth/profile", headers=h).json()["quoteEmailEffective"] == "rick@corp.com"
    sc = client.get("/api/users/sales-contact", params={"username": u}, headers=su).json()
    assert sc["quoteEmail"] == "rick@corp.com" and sc["quoteEmailSource"] == "user" and sc["email"] == "private@gmail.com"
    # 清掉 ⇒ 退回公司層；公司層也清掉 ⇒ 退回個人
    client.put(f"/api/users/{uid}", json={"quote_email": ""}, headers=su)
    assert mine()["quoteEmailSource"] == "company"
    _company(client, su, "")
    assert mine()["quoteEmailSource"] == "personal"


def test_non_superadmin_cannot_set_quote_email(client, make_user, su):
    ua, pa = make_user(username="qe_adm", role="admin")
    us, ps = make_user(username="qe_s2", role="sales")
    ha, hs = _login(client, ua, pa), _login(client, us, ps)
    tgt = _uid(us)
    for h in (ha, hs):
        assert client.put(f"/api/users/{tgt}", json={"quote_email": "x@corp.com"}, headers=h).status_code in (401, 403)
    assert client.post("/api/users", json={"username": "qe_new", "password": "Zx9!kLm2#pQ", "quote_email": "x@corp.com"}, headers=ha).status_code in (401, 403)
    assert client.get("/api/auth/profile", headers=hs).json()["quoteEmail"] == ""
    # 公司對外信箱同樣只有最高管理者
    assert client.put("/api/settings/company-profile", json={"external_email": "x@corp.com"}, headers=ha).status_code in (401, 403)


def test_format_validated_domain_hint_does_not_block(client, make_user, su):
    u, _ = make_user(username="qe_v", role="sales")
    uid = _uid(u)
    assert client.put(f"/api/users/{uid}", json={"quote_email": "not-an-email"}, headers=su).status_code == 400
    assert client.put(f"/api/users/{uid}", json={"quote_email": "me@gmail.com"}, headers=su).status_code == 200   # 私人網域：只提醒，不擋
    assert client.put("/api/settings/company-profile", json={"external_email": "bad@@x"}, headers=su).status_code == 422
    r = _company(client, su, "me@gmail.com")
    assert "私人信箱" in r.json().get("emailHint", "")                                                       # 公司欄：回提醒文字、仍存檔
    assert client.get("/api/settings/company-profile", headers=su).json()["external_email"] == "me@gmail.com"


def test_other_users_quote_email_hidden_from_non_admin(client, make_user, su):
    ua, pa = make_user(username="qe_peer_a", role="sales")
    ub, _ = make_user(username="qe_peer_b", role="sales")
    client.put(f"/api/users/{_uid(ub)}", json={"quote_email": "b@corp.com"}, headers=su)
    rows = {x["username"]: x for x in client.get("/api/users", headers=_login(client, ua, pa)).json()}
    assert "quoteEmail" not in rows[ub] and "quoteEmailEffective" not in rows[ub]
    assert "quoteEmailEffective" in rows[ua]


# ── 已開出的報價單不被追溯 ─────────────────────────────────────────────────────

def test_issued_quote_snapshot_unchanged_when_settings_change(client, make_user, su):
    from db import get_db
    u, _ = make_user(username="qe_old", role="sales")
    snap = {"quoteNo": "QE-OLD-1", "salesPerson": "qe_old", "salesPersonUsername": u, "salesEmail": "old@gmail.com"}
    conn = get_db()
    conn.execute("INSERT INTO quotations (quote_no, status, data_json, created_at) VALUES (?,?,?,?)",
                 ("QE-OLD-1", "已核准", json.dumps(snap), "2026-01-01"))
    conn.commit()
    conn.close()
    client.put(f"/api/users/{_uid(u)}", json={"quote_email": "new@corp.com"}, headers=su)
    _company(client, su, "sales@corp.com")
    conn = get_db()
    row = conn.execute("SELECT data_json FROM quotations WHERE quote_no='QE-OLD-1'").fetchone()
    conn.close()
    assert json.loads(row["data_json"])["salesEmail"] == "old@gmail.com"      # 設定改了，舊單的快照不動
    assert QE.reply_to_for_quote("QE-OLD-1") == "old@gmail.com"               # 通知信的 Reply-To 也只取快照，不即時重算
    assert QE.reply_to_for_quote("QE-NO-SUCH") == ""


def test_pdf_reads_only_the_quote_snapshot():
    """PDF 的報價人 E-mail 只讀報價單快照 `q["salesEmail"]`，不會即時去查使用者或公司設定。"""
    src = (Path(__file__).resolve().parent.parent / "pdf_gen.py").read_text(encoding="utf-8")
    assert 'q.get("salesEmail","")' in src
    assert "quote_email" not in src


# ── 信件：只加 Reply-To，寄件者不變 ────────────────────────────────────────────

def _capture_send(monkeypatch):
    import helpers.email_notify as EN
    sent = {}

    class FakeSMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def ehlo(self):
            pass

        def starttls(self):
            pass

        def login(self, *a):
            pass

        def sendmail(self, frm, to, body):
            sent.update(frm=frm, to=to, body=body)

    monkeypatch.setattr(EN, "_cfg", lambda: {"enabled": True, "smtp_user": "sys@mail.test", "smtp_password": "x", "from_name": "MOTRIX"})
    monkeypatch.setattr(EN, "_smtp_send_blocked", lambda s: False)
    monkeypatch.setattr(EN.smtplib, "SMTP", FakeSMTP)
    return EN, sent


def test_reply_to_added_and_from_unchanged(monkeypatch):
    EN, sent = _capture_send(monkeypatch)
    assert EN._send(["boss@corp.com"], "報價單待審核", "<p>x</p>", "rick@corp.com") == EN.SEND_SENT
    body = sent["body"]
    assert "Reply-To: rick@corp.com" in body and "<sys@mail.test>" in body and sent["frm"] == "sys@mail.test"


def test_no_or_bad_reply_to_means_no_header(monkeypatch):
    EN, sent = _capture_send(monkeypatch)
    EN._send(["boss@corp.com"], "s", "<p>x</p>")
    assert "Reply-To" not in sent["body"]
    EN._send(["boss@corp.com"], "s", "<p>x</p>", "evil@x.com\r\nBcc: z@z.com")
    assert "Reply-To" not in sent["body"] and "Bcc" not in sent["body"]


def test_approval_request_uses_quote_snapshot_as_reply_to(monkeypatch, client, make_user, su):
    from db import get_db
    EN, _ = _capture_send(monkeypatch)
    u, _p = make_user(username="qe_appr", role="admin")
    _set_personal(u, "appr@corp.com")
    snap = {"quoteNo": "QE-RT-1", "salesEmail": "rick@corp.com"}
    conn = get_db()
    conn.execute("INSERT INTO quotations (quote_no, status, data_json, created_at) VALUES (?,?,?,?)",
                 ("QE-RT-1", "簽核中", json.dumps(snap), "2026-01-01"))
    conn.commit()
    conn.close()
    calls = []
    monkeypatch.setattr(EN, "_async_send", lambda *a: calls.append(a))
    EN.notify_approval_request("QE-RT-1", "客戶甲", [u])
    assert calls and len(calls[0]) == 4 and calls[0][3] == "rick@corp.com"
    calls.clear()
    EN.notify_approval_request("QE-NONE", "客戶甲", [u])        # 找不到報價單 ⇒ 不加 Reply-To，呼叫形狀與舊版相同
    assert calls and len(calls[0]) == 3


# ── 畫面接線（靜態守門）：三個地方都走同一個解析結果 ─────────────────────────────

def test_pages_are_wired_to_the_resolved_quote_email():
    from core import source_tree
    form = source_tree.page_file("quotation-form.html").read_text(encoding="utf-8")
    assert form.count("quoteEmailEffective") >= 3 and "quoteEmailSource" in form        # 本人帶入、改選報價人、舊單補填
    assert "尚未設定公司信箱" in form
    users = source_tree.page_file("users.html").read_text(encoding="utf-8")
    assert "quote_email" in users and 'data-testid="quote-email-input"' in users and ':disabled="!isSuperAdmin"' in users
    comp = source_tree.page_file("company-profile-settings.html").read_text(encoding="utf-8")
    assert "external_email" in comp and "公司對外信箱" in comp


# ── hichan-3 審查修正（L1／L2／L4／L5）──────────────────────────────────────────

@pytest.mark.parametrize("bad", ["é@corp.com", "a　b@corp.com", "a​b@corp.com", "ａ@corp.com", "名字@corp.com", "a b@corp.com"])
def test_valid_is_ascii_printable_only(bad):
    assert not QE.valid(bad)
    assert QE.valid("a.b+c@corp.com")


def _create_quote(client, h, data):
    r = client.post("/api/quotations", headers=h, json={"data": data, "status": "草稿"})
    assert r.status_code in (200, 201), r.text
    return r.json().get("quote_no") or r.json().get("quoteNo") or data.get("quoteNo")


def _snap(qno):
    from db import get_db
    conn = get_db()
    try:
        return json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (qno,)).fetchone()["data_json"])
    finally:
        conn.close()


def test_server_overrides_forged_sales_email_on_create(client, make_user, su):
    u, p = make_user(username="qe_forge", role="sales")
    _set_personal(u, "forge@corp.com")
    h = _login(client, u, p)
    qno = _create_quote(client, h, {"customerName": "甲", "items": [], "tot": {}, "salesPerson": u, "salesPersonUsername": u, "salesEmail": "attacker@evil.example"})
    assert _snap(qno)["salesEmail"] == "forge@corp.com"            # 偽造值被解析結果覆寫
    assert QE.reply_to_for_quote(qno) == "forge@corp.com"


def test_server_keeps_a_legitimate_value_and_fills_a_blank_one(client, make_user, su):
    u, p = make_user(username="qe_legit", role="sales")
    _set_personal(u, "legit@corp.com")
    client.put(f"/api/users/{_uid(u)}", json={"quote_email": "quote@corp.com"}, headers=su)
    h = _login(client, u, p)
    q1 = _create_quote(client, h, {"customerName": "甲", "items": [], "tot": {}, "salesPerson": u, "salesPersonUsername": u, "salesEmail": "legit@corp.com"})
    assert _snap(q1)["salesEmail"] == "legit@corp.com"             # 個人信箱也是三層之一 ⇒ 合法值保留
    q2 = _create_quote(client, h, {"customerName": "乙", "items": [], "tot": {}, "salesPerson": u, "salesPersonUsername": u, "salesEmail": ""})
    assert _snap(q2)["salesEmail"] == "quote@corp.com"             # 空白 ⇒ 填入解析值（報價用信箱優先）


def test_update_forged_email_is_overridden_but_an_untouched_old_value_stays(client, make_user, su):
    u, p = make_user(username="qe_upd", role="sales")
    _set_personal(u, "upd@corp.com")
    h = _login(client, u, p)
    qno = _create_quote(client, h, {"customerName": "甲", "items": [], "tot": {}, "salesPerson": u, "salesPersonUsername": u})
    from db import get_db
    conn = get_db()
    d = _snap(qno)
    d["salesEmail"] = "stale@old.example"                          # 舊單：快照是已不在三層裡的舊信箱
    conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), qno))
    conn.commit()
    conn.close()
    body = {**_snap(qno)}
    r = client.put(f"/api/quotations/{qno}", headers=h, json={"data": body, "status": "草稿"})
    assert r.status_code == 200, r.text
    assert _snap(qno)["salesEmail"] == "stale@old.example"         # 沒改 ⇒ 舊單維持原樣
    body["salesEmail"] = "attacker@evil.example"
    r = client.put(f"/api/quotations/{qno}", headers=h, json={"data": body, "status": "草稿"})
    assert r.status_code == 200, r.text
    assert _snap(qno)["salesEmail"] == "upd@corp.com"              # 改成不合法的值 ⇒ 覆寫成解析值


def test_other_quote_mails_also_carry_reply_to(client, monkeypatch):
    """next_tier／approved／returned／resubmit_requester 與 approval_request 一致：有快照才加 Reply-To，沒有就維持舊呼叫形狀。"""
    from db import get_db
    from helpers import email_notify as EN
    conn = get_db()
    conn.execute("INSERT INTO quotations (quote_no, status, data_json, created_at) VALUES (?,?,?,?)",
                 ("QE-RT-2", "簽核中", json.dumps({"salesEmail": "rick@corp.com"}), "2026-01-01"))
    conn.commit()
    conn.close()
    monkeypatch.setattr(EN, "_lookup_emails", lambda users, key: ["x@corp.com"])
    monkeypatch.setattr(EN, "_admin_emails", lambda key=None: [])
    calls = []
    monkeypatch.setattr(EN, "_async_send", lambda *a: calls.append(a))
    EN.notify_next_tier("QE-RT-2", "客戶", 2, 3, ["a"])
    EN.notify_approved("QE-RT-2", "客戶", "boss", "a")
    EN.notify_returned("QE-NONE", "QE-RT-2", "客戶", "備註", "a")
    EN.notify_resubmit_requester("QE-RT-2", "QE-NONE", "客戶", "a", ["b"])
    assert len(calls) == 4 and all(len(c) == 4 and c[3] == "rick@corp.com" for c in calls), [len(c) for c in calls]
    calls.clear()
    EN.notify_next_tier("QE-NONE", "客戶", 2, 3, ["a"])
    assert len(calls) == 1 and len(calls[0]) == 3                  # 沒有快照 ⇒ 舊呼叫形狀


def test_sales_contact_new_field_name_and_old_name_kept(client, make_user, su):
    u, _ = make_user(username="qe_sc", role="sales")
    _set_personal(u, "sc@corp.com")
    sc = client.get("/api/users/sales-contact", params={"username": u}, headers=su).json()
    assert sc["quoteEmailEffective"] == "sc@corp.com" and sc["quoteEmail"] == sc["quoteEmailEffective"] and sc["quoteEmailSource"] == "personal"


def test_profile_copy_distinguishes_personal_email_from_quote_email():
    import pathlib
    html = _page_file("my-account.html").read_text(encoding="utf-8")
    assert "報價單與報價相關信件上帶的信箱，是下方的「報價用信箱」" in html
    assert "profile-quote-email-none" in html and "尚未設定：目前報價單上不會有你的信箱" in html
    assert "（尚未設定）" in html


# ── hichan-3 審查 B：補登歷史案件也要驗證；換業務員時舊信箱要重驗 ─────────────────────────────
def test_historical_backfill_also_overrides_forged_sales_email(client, make_user, su):
    import db
    from helpers import settings_registry as SR
    conn = db.get_db()
    try:
        SR.publish("quote_backfill", {"enabled": 1}, reason="測試", user="qe_hist", conn=conn)
        conn.commit()
        SR.invalidate("quote_backfill")
    finally:
        conn.close()
    try:
        u, _p = make_user(username="qe_hist_sales", role="sales")
        _set_personal(u, "hist@corp.com")
        body = {"data": {"customerName": "補登客戶", "projectName": "歷史案件", "quoteDate": "2026-07-15", "items": [],
                         "salesPerson": u, "salesPersonUsername": u, "salesEmail": "attacker@evil.example"},
                "reason": "補登 7 月舊案件，紙本單據遺失重建"}
        r = client.post("/api/quotations/historical", headers=su, json=body)
        assert r.status_code == 201, r.text
        assert _snap(r.json()["quote_no"])["salesEmail"] == "hist@corp.com"       # 偽造值被解析結果覆寫（PDF 會印出來）
    finally:
        conn = db.get_db()
        try:
            SR.publish("quote_backfill", {"enabled": 0}, reason="測試", user="qe_hist", conn=conn)
            conn.commit()
            SR.invalidate("quote_backfill")
        finally:
            conn.close()


def test_changing_the_salesperson_revalidates_an_unchanged_old_email(client, make_user, su):
    ua, pa = make_user(username="qe_swap_a", role="sales")
    ub, _pb = make_user(username="qe_swap_b", role="sales")
    _set_personal(ua, "a@corp.com")
    _set_personal(ub, "b@corp.com")
    h = _login(client, ua, pa)
    qno = _create_quote(client, h, {"customerName": "甲", "items": [], "tot": {}, "salesPerson": ua, "salesPersonUsername": ua})
    assert _snap(qno)["salesEmail"] == "a@corp.com"
    body = {**_snap(qno), "salesPerson": ub, "salesPersonUsername": ub}               # 換成 B，信箱欄位還是 A 的舊值
    r = client.put(f"/api/quotations/{qno}", headers=su, json={"data": body, "status": "草稿"})
    assert r.status_code == 200, r.text
    assert _snap(qno)["salesEmail"] == "b@corp.com"                                    # 不是沿用前一位業務員的信箱
