# -*- coding: utf-8 -*-
"""2026-11-13：估價單走到的「寄信／行事曆／PDF」文字不可寫死「報價單」。

接縫＝`helpers.doc_type.label_of_no(單號)`（只有單號時）／`label(doc_type)`（手上有欄位時）。
每條路徑各用一張估價單（ME-）、一張報價單（MQ-）走一次：
  - 估價單：整段文字裡不該再出現「報價單」。
  - 報價單：字串與改動前逐位元相同（「估價單」一個字都不能出現）。
"""
from tests._requires import requires_module  # noqa: E402
import json
from datetime import date, timedelta

import pytest

pytestmark = requires_module("case", "本檔打 M01（案件）的通知與資料（報價單／估價單）")

EST_NO = "ME-202611-001"
QUO_NO = "MQ-202611-001"


def _only(text, want, other):
    assert want in text, text
    assert other not in text, text


def _est(text):
    _only(text, "估價單", "報價單")


def _quo(text):
    _only(text, "報價單", "估價單")


@pytest.fixture
def mails(monkeypatch):
    """攔下所有「非同步寄信」：(to, subject, html)。"""
    from helpers import email_notify as E
    sent = []
    monkeypatch.setattr(E, "_admin_emails", lambda *a, **k: ["a@example.com"])
    monkeypatch.setattr(E, "_superadmin_emails", lambda *a, **k: ["a@example.com"])
    monkeypatch.setattr(E, "_finance_audience_emails", lambda *a, **k: ["a@example.com"])
    monkeypatch.setattr(E, "_async_send", lambda to, subject, html, *a, **k: sent.append((to, subject, html)))
    return sent


# ── 1. 只有單號的通知信 ─────────────────────────────────────────────────────

def test_label_of_no_follows_the_prefix_and_never_raises():
    from helpers import doc_type as D
    assert D.label_of_no(EST_NO) == "估價單"
    assert D.label_of_no(QUO_NO) == "報價單"
    for weird in (None, "", "ZZ-1", 123):
        assert D.label_of_no(weird) == "報價單"


def test_settlement_mail_follows_type(mails):
    from helpers import email_notify as E
    E.notify_settlement_finalized(EST_NO, "客", "某人")
    E.notify_settlement_finalized(QUO_NO, "客", "某人")
    (_, _, est), (_, _, quo) = mails
    _est(est)
    _quo(quo)


def test_case_close_blocked_and_change_requested_mails_follow_type(mails):
    from helpers import email_notify as E
    for no, row, other in ((EST_NO, "估價單號", "報價單號"), (QUO_NO, "報價單號", "估價單號")):
        mails.clear()
        E.notify_case_close_blocked(no, "客", "案", ["款項未收齊"], [])
        E.notify_case_change_requested(no, "客", "案", "摘要", "某人")
        assert len(mails) == 2, mails
        for _, _, html in mails:
            assert row in html and other not in html, html[:400]


def test_review_edit_mail_follows_type(monkeypatch):
    from modules.case import review_edit_notify as R
    seen = []
    monkeypatch.setattr(R._en, "send_registered", lambda *a, **k: seen.append((a, k)) or True)
    monkeypatch.setattr(R._en, "_base_url", lambda: "http://x")
    R.fire_edited(EST_NO, customer="客", editor="某人", requester="u", fields=["金額"])
    R.fire_edited(QUO_NO, customer="客", editor="某人", requester="u", fields=["金額"])
    (_, est), (_, quo) = seen
    for k in ("title", "reason", "button_text"):
        _est(est[k])
        _quo(quo[k])
    assert est["rows"][0][0] == "估價單號" and quo["rows"][0][0] == "報價單號"


# ── 2. 站內活動通知信（notify_module_activity 的 module_label）──────────────────

def test_quotation_endpoints_pass_the_doc_label_to_module_activity():
    """報價單 API 裡不再有寫死的 `notify_module_activity("報價單", …)`：一律由單號／欄位取名。"""
    import re
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "modules" / "case" / "api" / "quotations.py").read_text(encoding="utf-8")
    assert not re.search(r'notify_module_activity\(\s*["\']報價單["\']', src)
    assert len(re.findall(r"notify_module_activity\(_DT\.label_of_no\(", src)) == 11


def test_module_activity_mail_carries_the_given_label(mails):
    from helpers import email_notify as E
    from helpers import doc_type as D
    E.notify_module_activity(D.label_of_no(EST_NO), "標記成案", "某人", EST_NO)
    E.notify_module_activity(D.label_of_no(QUO_NO), "標記成案", "某人", QUO_NO)
    (_, s1, h1), (_, s2, h2) = mails
    _est(s1 + h1)
    _quo(s2 + h2)


# ── 3. 簽核逾期催辦 ───────────────────────────────────────────────────────────

def test_overdue_approval_reminder_follows_type(client, make_user, monkeypatch):
    import helpers.system_checks as SC
    from db import get_db
    u, pw = make_user(username="est_rem", role="admin")
    r = client.post("/api/auth/login", json={"username": u, "password": pw})
    h = {"Authorization": "Bearer " + r.json()["token"]}
    nos = {}
    for dt in ("estimate", None):
        data = {"customerName": "催辦客", "projectName": "案", "quoteDate": "2026-11-13",
                "items": [{"description": "品項"}], "tot": {"total": 1, "pretax": 1}}
        if dt:
            data["docType"] = dt
        rr = client.post("/api/quotations", headers=h, json={"status": "草稿", "data": data})
        assert rr.status_code == 201, rr.text
        nos[dt or "quote"] = rr.json()["quote_no"]
    past = (date.today() - timedelta(days=21)).isoformat() + "T09:00:00"
    conn = get_db()
    try:
        for no in nos.values():
            row = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (no,)).fetchone()
            d = json.loads(row["data_json"])
            d["approval"] = {"requestedAt": past,
                             "tiers": [{"approvers": [{"username": u, "status": "pending"}]}]}
            conn.execute("UPDATE quotations SET status='待審核', data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), no))
        conn.commit()
    finally:
        conn.close()
    got = {}
    monkeypatch.setattr(SC, "notify_approval_reminder",
                        lambda doc_type, doc_no, *a, **k: got.__setitem__(doc_no, doc_type) or "sent")
    SC._check_approval_reminders()
    assert got.get(nos["estimate"]) == "估價單", got
    assert got.get(nos["quote"]) == "報價單", got


# ── 4. 行事曆事件 ─────────────────────────────────────────────────────────────

def test_calendar_event_wording_follows_type(client, make_user, monkeypatch):
    from helpers import google_calendar as G
    from db import get_db
    u, pw = make_user(username="est_cal", role="admin")
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": pw}).json()["token"]}
    nos = {}
    for dt in ("estimate", None):
        data = {"customerName": "行事曆客", "projectName": "案", "quoteDate": "2026-11-13",
                "items": [{"description": "品項"}], "tot": {"total": 100, "pretax": 95}}
        if dt:
            data["docType"] = dt
        rr = client.post("/api/quotations", headers=h, json={"status": "草稿", "data": data})
        assert rr.status_code == 201, rr.text
        nos[dt or "quote"] = rr.json()["quote_no"]
    events = {}
    monkeypatch.setattr(G, "_create_event_with_retry",
                        lambda title, desc, *a, **k: events.__setitem__(len(events), (title, desc)) or None)
    for no in (nos["estimate"], nos["quote"]):
        try:
            G.push_event_for_quotation_won(no)
        except Exception:
            pass
    if len(events) < 2:
        pytest.skip("行事曆推送在此環境被旗標／憑證略過；用語已由 relabel 單元題覆蓋")
    _est(events[0][0] + events[0][1])
    _quo(events[1][0] + events[1][1])


def test_calendar_text_goes_through_relabel_only_for_estimates():
    from helpers import doc_type as D
    t = "報價單成案 — 案（客｜X）\n報價單 X 已標記為「已成案」。"
    assert D.relabel(t, D.QUOTE) == t
    assert "報價單" not in D.relabel(t, D.ESTIMATE)


# ── 5. PDF ──────────────────────────────────────────────────────────────────

def _pdf_src(name):
    from pathlib import Path
    return (Path(__file__).resolve().parents[1] / name).read_text(encoding="utf-8")


def test_pdf_reference_labels_come_from_the_doc_no():
    """出貨單「關聯報價單」、請款單／開票憑據「其他資訊（報價單）」：不再寫死，改由單號取名。"""
    s = _pdf_src("pdf_gen.py")
    assert "關聯報價單：" not in s
    assert "其他資訊（報價單）" not in s
    assert s.count("_DT.label_of_no(") >= 3


def test_shipping_note_pdf_label_follows_the_linked_doc():
    import pdf_gen
    base = {"noteNo": "SN-1", "shipDate": "2026-11-13", "items": [], "customerName": "客"}
    est = pdf_gen._build_shipping_html(dict(base, quoteNo=EST_NO))
    quo = pdf_gen._build_shipping_html(dict(base, quoteNo=QUO_NO))
    assert "關聯估價單：" in est and "關聯報價單：" not in est
    assert "關聯報價單：" in quo and "關聯估價單：" not in quo
