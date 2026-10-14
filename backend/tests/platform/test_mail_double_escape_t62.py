# -*- coding: utf-8 -*-
"""簽核類信件的內文只逸出一次（04 稽核）：`email_notify._build_html` 對簽核類信件統一逸出，呼叫端不可再逸出（否則 A&B 變 A&amp;amp;B）。

涵蓋兩個過去自己逸出的呼叫端：獎金分潤層外核准、勞報單層外代核。
"""

from helpers import email_notify as EN

EVIL_ACTOR = "A&B <x> 'q'"
EVIL_REASON = "因為 <b>急件</b> & \"特急\""


def _capture(monkeypatch):
    sent = []
    monkeypatch.setattr(EN, "_lookup_emails", lambda names, key: ["a@example.com"])
    monkeypatch.setattr(EN, "_base_url", lambda: "https://x.example")

    def cap(to, subject, html, *rest):
        sent.append((subject, html))

        class _H:
            def wait(self, timeout=None):
                return EN.SEND_SENT
        return _H()
    monkeypatch.setattr(EN, "_async_send", cap)
    return sent


def _assert_single_escape(html):
    assert "A&amp;B &lt;x&gt; &#x27;q&#x27;" in html, "核准人逸出一次"
    assert "&amp;amp;" not in html and "&amp;lt;" not in html and "&amp;#x27;" not in html, "不可雙重逸出"
    assert "&lt;b&gt;急件&lt;/b&gt; &amp; &quot;特急&quot;" in html, "原因逸出一次"
    assert "<b>急件</b>" not in html


def test_bonus_bypass_mail_is_escaped_exactly_once(monkeypatch):
    from modules.payroll import bonus_notify as BN
    sent = _capture(monkeypatch)
    monkeypatch.setattr(BN, "_notice_in_app", lambda *a, **k: None)
    assert BN.fire_bypass("Q-1", "客戶", EVIL_ACTOR, "原簽核人", EVIL_REASON, ["u1"]) is True
    _assert_single_escape(sent[-1][1])


def test_payslip_bypass_mail_is_escaped_exactly_once(monkeypatch):
    from modules.payroll import payslip_notify as PN
    sent = _capture(monkeypatch)
    monkeypatch.setattr(PN, "_inapp", lambda *a, **k: None)
    assert PN.fire_bypass("S-1", "2026-10-14", EVIL_ACTOR, "原簽核人", EVIL_REASON, ["u1"]) is True
    _assert_single_escape(sent[-1][1])


def test_no_local_html_escaping_remains_in_senders_of_approval_mails():
    """守門：用 `_build_html`／`send_registered` 寄簽核類信件的呼叫端不得自己 `html.escape`（共用的建構器負責）。"""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    offenders = []
    for p in list((root / "modules").rglob("*notify*.py")) + [root / "archive.py", root / "helpers" / "company_setup.py", root / "helpers" / "geo.py"]:
        if "tests" in p.parts:
            continue
        src = p.read_text(encoding="utf-8")
        if ("send_registered" in src or "_build_html" in src) and re.search(r"html\.escape|saxutils|markupsafe|&amp;|&lt;", src):
            offenders.append(str(p.relative_to(root)))
    assert offenders == [], "這些呼叫端自己逸出了（會雙重逸出）：%s" % offenders
