# -*- coding: utf-8 -*-
"""S-X3 第一刀：報價單送審通知用語（`approval:submitted`）。

- 預設字＝今天寫死的字（站內訊息、信件主旨事由／標題／徽章／引言／按鈕）逐字相同；旗標關／沒有範本 ⇒ 呼叫端輸出逐位元相同
- 驗證：只收白名單占位符、無標記／網址／隱形字元／官方狀態字樣、必須包含 {單號}
- 信件：展開後逐字 HTML 逸出；主旨前綴與分類固定
- 比較函式：新增或改變＝放寬、拿掉＝收緊
"""
import inspect

import pytest

from helpers import email_notify as EN
from helpers import notify_templates as NT

KEY = "approval:submitted"
CTX = {"單號": "MQ-202610-001", "對象": "甲公司", "標記": "（退回改版）"}


def _tpl(monkeypatch, body):
    monkeypatch.setattr(NT, "resolve", lambda key, conn=None: body if key == KEY else None)


# ── 預設 = 今天寫死的字 ────────────────────────────────────────────────────
def test_default_template_is_valid_and_equals_the_old_hard_coded_strings():
    d = NT.default_template(KEY)
    assert NT.definition_problems(KEY, d) == []
    q = "MQ-202610-001"
    assert NT._expand(d["inapp"]["message"], CTX) == f"報價單 {q}（退回改版）（甲公司）需要您簽核"
    assert NT._expand(d["mail"]["reason"], CTX) == f"報價單待審核：{q}（甲公司）"
    src = inspect.getsource(EN.notify_approval_request)
    for f in ("title", "badge", "intro", "button"):
        assert NT.EVENTS[KEY]["fields"]["mail." + f]["default"] in src, f
    from modules.case.api import quotations as QA
    qs = inspect.getsource(QA._submitted_msg)
    assert "報價單 {quote_no}{label}（{cname}）需要您簽核" in qs


def test_off_or_unpublished_returns_none_everywhere(monkeypatch):
    _tpl(monkeypatch, None)
    assert NT.render_inapp(KEY, CTX) is None and NT.mail_fields(KEY, CTX) is None
    assert NT.resolve("no:such") is None


def test_quotation_submitted_msg_is_byte_identical_when_off(monkeypatch):
    from modules.case.api import quotations as QA
    _tpl(monkeypatch, None)
    assert QA._submitted_msg("MQ-1", "（解鎖改版）", "乙") == "報價單 MQ-1（解鎖改版）（乙）需要您簽核"
    assert QA._submitted_msg("MQ-1", "", "乙") == "報價單 MQ-1（乙）需要您簽核"
    _tpl(monkeypatch, {"version": 1, "inapp": {"message": "請盡快審核 {單號}{標記}（{對象}）"}})
    assert QA._submitted_msg("MQ-1", "", "乙") == "請盡快審核 MQ-1（乙）"


def _capture_mail(monkeypatch):
    sent = {}
    monkeypatch.setattr(EN, "_lookup_emails", lambda names, key: ["a@example.com"])
    monkeypatch.setattr(EN, "_base_url", lambda: "https://x.example")
    monkeypatch.setattr(EN, "_async_send", lambda to, subject, html: sent.update(subject=subject, html=html))
    import datetime as _dt
    class _D(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return _dt.datetime(2026, 10, 14, 9, 0)
    monkeypatch.setattr(EN, "datetime", _D)
    return sent


def test_mail_is_byte_identical_when_no_template_and_changes_only_the_template_fields(monkeypatch):
    sent = _capture_mail(monkeypatch)
    _tpl(monkeypatch, None)
    EN.notify_approval_request("MQ-9", "丙公司", ["u"])
    off = dict(sent)
    assert off["subject"] == "【MOTRIX 系統通知】簽核－報價單待審核：MQ-9（丙公司）"
    assert "報價單簽核申請" in off["html"] and "待您審核" in off["html"] and "前往審核報價單" in off["html"]
    _tpl(monkeypatch, {"version": 1, "mail": {"reason": "請審核 {單號}", "intro": "有一張 {對象} 的單，麻煩您。", "badge": "請處理"}})
    EN.notify_approval_request("MQ-9", "丙公司", ["u"])
    assert sent["subject"] == "【MOTRIX 系統通知】簽核－請審核 MQ-9", "主旨前綴與分類固定，只換事由"
    assert "有一張 丙公司 的單，麻煩您。" in sent["html"] and "請處理" in sent["html"]
    assert "報價單簽核申請" in sent["html"] and "前往審核報價單" in sent["html"], "沒設定的欄位維持預設"


def test_mail_expansion_is_html_escaped(monkeypatch):
    sent = _capture_mail(monkeypatch)
    _tpl(monkeypatch, {"version": 1, "mail": {"intro": "客戶 {對象} 的單"}})
    EN.notify_approval_request("MQ-9", "<b>x</b>&\"公司", ["u"])
    assert "<b>x</b>" not in sent["html"].split("事由")[1].split("報價單號")[0]
    assert "&lt;b&gt;x&lt;/b&gt;&amp;&quot;公司" in sent["html"]


# ── 驗證 ──────────────────────────────────────────────────────────────────
def _bad(body):
    return {p["path"] for p in NT.definition_problems(KEY, body)}


def test_validator_whitelist_and_bans():
    ok = {"version": 1, "inapp": {"message": "請審核 {單號}"}}
    assert _bad(ok) == set()
    assert _bad({"version": 1}) == {""}, "至少一個欄位"
    assert "inapp.message" in _bad({"version": 1, "inapp": {"message": "請審核 {單號} {金額}"}}), "沒有金額占位符"
    assert "inapp.message" in _bad({"version": 1, "inapp": {"message": "請審核"}}), "必須含單號"
    assert "inapp.message" in _bad({"version": 1, "inapp": {"message": "<b>{單號}</b>"}})
    assert "inapp.message" in _bad({"version": 1, "inapp": {"message": "{單號} https://evil.example"}})
    assert "inapp.message" in _bad({"version": 1, "inapp": {"message": "{單號}​"}})
    assert "inapp.message" in _bad({"version": 1, "inapp": {"message": "{單號} 已 核 准"}}), "官方狀態字樣（插空白也擋）"
    assert "inapp.message" in _bad({"version": 1, "inapp": {"message": "{單號 }"}})
    assert "inapp.message" in _bad({"version": 1, "inapp": {"message": "{單號} {"}})
    assert "inapp.message" in _bad({"version": 1, "inapp": {"message": "{單號}" + "字" * 200}})
    assert "mail.reason" in _bad({"version": 1, "mail": {"reason": "{標記}{單號}"}}), "信件事由沒有 {標記}"
    assert "mail.nope" in _bad({"version": 1, "mail": {"nope": "x"}})
    assert "mail.title" in _bad({"version": 1, "mail": {"title": "   "}})
    assert "x" in _bad({"version": 1, "x": 1, "inapp": {"message": "{單號}"}})
    assert "version" in _bad({"version": 2, "inapp": {"message": "{單號}"}})
    assert NT.definition_problems("no:such", ok)


def test_money_text_in_inapp_is_masked_in_the_preview_for_non_finance(monkeypatch):
    _tpl(monkeypatch, None)
    body = {"version": 1, "inapp": {"message": "請審核 {單號}，金額約 1,200,000 元"}}
    pv = NT.preview(None, {"username": "u", "role": "superadmin"}, body, KEY)
    row = next(r for r in pv["rows"] if r["field"] == "inapp.message")
    assert "1,200,000 元" in row["draft"] and "1,200,000" not in row["draftNonFinance"] and "（金額略）" in row["draftNonFinance"]
    assert row["current"].startswith("報價單 MQ-202610-001")


def test_preview_rejects_invalid_drafts(monkeypatch):
    _tpl(monkeypatch, None)
    with pytest.raises(ValueError):
        NT.preview(None, {"username": "u", "role": "superadmin"}, {"version": 1, "inapp": {"message": "沒有單號"}}, KEY)
    with pytest.raises(LookupError):
        NT.preview(None, {"username": "u", "role": "superadmin"}, {}, "no:such")


# ── 治理 ──────────────────────────────────────────────────────────────────
def test_comparator_loosen_tighten_neutral():
    from routers.def_pipeline import classify, ACTIVE_KINDS
    assert "notify_template" in ACTIVE_KINDS
    a = {"version": 1, "inapp": {"message": "請審核 {單號}"}}
    b = {"version": 1, "inapp": {"message": "麻煩審核 {單號}"}}
    assert classify("notify_template", {}, a)[0] == "loosen"
    assert classify("notify_template", a, b)[0] == "loosen"
    assert classify("notify_template", a, a)[0] == "neutral"
    assert classify("notify_template", a, {"version": 1, "mail": {}})[0] == "tighten"
    assert classify("notify_template", a, {"version": 1, "inapp": "x"})[0] == "loosen"


def test_static_guards():
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    for rel in ("helpers/notify_templates.py", "routers/notify_templates.py"):
        assert not re.search(r"\(\*\*[a-z_]", (root / rel).read_text(encoding="utf-8")), rel
    sg = (root / "helpers" / "settings_groups.py").read_text(encoding="utf-8")
    assert '"builder_notify"' in sg
    main = (root / "main.py").read_text(encoding="utf-8")
    assert "notify_templates_router.router" in main
    # 惰性登記：模組 import 時不登記 kind
    from core import definitions as D
    assert NT.KIND not in D.kinds() or NT.enabled()


def test_client_status_and_preview_are_closed_when_off(client, make_user):
    u, pw = make_user(username="nt_sa", role="superadmin")[:2]
    t = client.post("/api/auth/login", json={"username": u, "password": pw}, headers={"X-Forwarded-For": "203.0.113.88"}).json()["token"]
    h = {"Authorization": "Bearer " + t}
    assert client.get("/api/notify-templates/%s/status" % KEY, headers=h).json() == {"enabled": False, "canEdit": False}
    assert client.post("/api/notify-templates/%s/preview" % KEY, headers=h, json={"template": {}}).status_code == 404
    assert client.get("/api/notify-templates/no:such/status", headers=h).status_code == 404
    kinds = [k["kind"] if isinstance(k, dict) else k for k in client.get("/api/definition-kinds", headers=h).json()["kinds"]]
    assert NT.KIND not in kinds, "旗標關 ⇒ kind 不出現（與今天相同）"


# ── 04 審查 M1／S1／S2／S3 ─────────────────────────────────────────────────
def test_m1_mail_subject_is_plain_text_and_body_is_escaped(monkeypatch):
    sent = _capture_mail(monkeypatch)
    _tpl(monkeypatch, {"version": 1, "mail": {"reason": "請審核 {單號}（{對象}）", "intro": "客戶 {對象} 的單"}})
    EN.notify_approval_request("MQ-9", "A&B <工程> 'x'\r\nBcc: z", ["u"])
    subj = sent["subject"]
    assert "A&B <工程> 'x' Bcc: z" in subj and "&amp;" not in subj and "&lt;" not in subj and "\n" not in subj and "\r" not in subj
    assert "A&amp;B &lt;工程&gt; &#x27;x&#x27;" in sent["html"], "內文欄位逐字逸出"
    assert "A&B <工程>" not in sent["html"].split("事由")[1].split("報價單號")[0]


def test_m1_subject_length_is_capped(monkeypatch):
    _tpl(monkeypatch, {"version": 1, "mail": {"reason": "審 {單號} {對象}"}})
    f = NT.mail_fields(KEY, {"單號": "M", "對象": "長" * 500})
    assert len(f["reason"]) <= NT.EVENTS_LIMIT_REASON


def test_s1_kind_gate_hides_the_kind_when_off(monkeypatch):
    from core import spine
    monkeypatch.setattr(NT, "enabled", lambda conn=None: False)
    assert spine.kind_info(NT.KIND, KEY)["status"] == "hidden"
    monkeypatch.setattr(NT, "enabled", lambda conn=None: True)
    assert spine.kind_info(NT.KIND, KEY)["status"] == "open"


@pytest.mark.parametrize("text", ["已通過", "通過審核", "批准", "審核通過", "簽核通過", "已簽核", "已批", "已生效", "签核完成", "审核通过", "通过", "已签核",
                                  "approve", "Approved", "PASSED", "Paid", "ａｐｐｒｏｖｅｄ", "final", "已 通 過", "void"])
def test_s2_more_official_words_are_banned(text):
    assert _bad({"version": 1, "mail": {"intro": "您好 " + text}}) == {"mail.intro"}


@pytest.mark.parametrize("text", ["finally", "unpaid", "avoid", "originality", "signedness", "passage", "approval"])
def test_s2_english_words_use_word_boundaries(text):
    assert _bad({"version": 1, "mail": {"intro": "您好 " + text}}) == set()


@pytest.mark.parametrize("text", ["bit.ly/x", "line.me/ti/p/abc", "example.com", "a.tw", "x.io", "a/b", "http://x", "www.x", "ｅｘａｍｐｌｅ．ｃｏｍ", "ｘ／ｙ"])
def test_s3_urls_and_slashes_are_banned(text):
    assert _bad({"version": 1, "mail": {"intro": "請見 " + text}}) == {"mail.intro"}


# ── 既有問題（旗標關也成立）：簽核類信件的使用者資料要逸出 ──────────────────────
def test_approval_mails_escape_user_data_even_with_no_template(monkeypatch):
    sent = _capture_mail(monkeypatch)
    _tpl(monkeypatch, None)
    EN.notify_approval_request("MQ-9", "<img src=x onerror=1>公司", ["u"])
    assert "<img" not in sent["html"] and "&lt;img src=x onerror=1&gt;公司" in sent["html"]
    assert sent["subject"].endswith("報價單待審核：MQ-9（<img src=x onerror=1>公司）"), "主旨是純文字，維持原樣"
    monkeypatch.setattr(EN, "_lookup_emails", lambda names, key: ["a@example.com"])
    EN.notify_returned("MQ-9", "MQ-9-R1", "甲<b>", "備註 <script>x</script>", "u")
    assert "<script>" not in sent["html"] and "&lt;script&gt;x&lt;/script&gt;" in sent["html"] and "<b>" not in sent["html"].split("報價單號")[0] + sent["html"].split("客戶名稱")[1]


def test_only_approval_category_is_escaped_other_builders_keep_their_deliberate_html(monkeypatch):
    monkeypatch.setattr(EN, "_base_url", lambda: "https://x.example")
    biz = EN._build_html("daily_task_completed", "標題", "徽章", "#000", [("修改後", "<strong>新</strong>")], "", "https://x.example", intro="內容")
    assert "<strong>新</strong>" in biz
    appr = EN._build_html("approval_request", "標題", "徽章", "#000", [("客戶名稱", "<strong>新</strong>")], "", "https://x.example", intro="內容")
    assert "<strong>新</strong>" not in appr and "&lt;strong&gt;新&lt;/strong&gt;" in appr


@pytest.mark.parametrize("text", ["аpproved", "ОК", "рaid", "Οk", "ｎ‌ｏ", "😀", "已通過", "—"])
def test_r3_character_allowlist_blocks_lookalikes_before_the_reserved_check(text):
    # 前四個含西里爾／希臘外觀相似字、後面是 emoji／破折號：都不在白名單
    probs = _bad({"version": 1, "mail": {"intro": "您好 " + text}})
    assert probs == {"mail.intro"}


def test_r3_defaults_and_normal_text_pass_the_allowlist():
    assert NT.definition_problems(KEY, NT.default_template(KEY)) == []
    assert _bad({"version": 1, "mail": {"intro": "您好，請於 2026-10-20 前處理（急件）：謝謝！"}}) == set()
