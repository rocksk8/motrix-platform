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


def test_every_category_escapes_plain_text_and_only_safe_fragments_pass_through(monkeypatch):
    # 原名 test_only_approval_category_is_escaped_other_builders_keep_their_deliberate_html：mail-escape-r2（04 稽核）之後 `_build_html` 對**所有**類別
    # 預設逸出純文字；呼叫端刻意傳入的 HTML 必須包成 `_safe()`（其中的使用者資料自己 `_esc()`）。所以：純文字 <strong> 一律被逸出，包了 _safe 的才原樣放行。
    monkeypatch.setattr(EN, "_base_url", lambda: "https://x.example")
    for cat in ("daily_task_completed", "approval_request"):
        plain = EN._build_html(cat, "標題", "徽章", "#000", [("修改後", "<strong>新</strong>")], "", "https://x.example", intro="內容")
        assert "<strong>新</strong>" not in plain and "&lt;strong&gt;新&lt;/strong&gt;" in plain, cat
    deliberate = EN._build_html("daily_task_completed", "標題", "徽章", "#000", [("修改後", EN._safe("<strong>新</strong>"))], "", "https://x.example", intro="內容")
    assert "<strong>新</strong>" in deliberate


@pytest.mark.parametrize("text", ["аpproved", "ОК", "рaid", "Οk", "ｎ‌ｏ", "😀", "已通過", "—"])
def test_r3_character_allowlist_blocks_lookalikes_before_the_reserved_check(text):
    # 前四個含西里爾／希臘外觀相似字、後面是 emoji／破折號：都不在白名單
    probs = _bad({"version": 1, "mail": {"intro": "您好 " + text}})
    assert probs == {"mail.intro"}


def test_r3_defaults_and_normal_text_pass_the_allowlist():
    assert NT.definition_problems(KEY, NT.default_template(KEY)) == []
    assert _bad({"version": 1, "mail": {"intro": "您好，請於 2026-10-20 前處理（急件）：謝謝！"}}) == set()


# ── N 刀：輪到下一層／核准／退回（報價單家族）──────────────────────────────────────────
NT_CTX = {"單號": "MQ-9", "對象": "丙公司", "標記": "", "層": 2, "總層": 3, "最終審核人": "王經理", "原單號": "MQ-9", "新單號": "MQ-9-R1"}


def test_all_events_defaults_are_valid_and_exempt_from_the_character_rules():
    for k in NT.EVENTS:
        assert NT.definition_problems(k, NT.default_template(k)) == [], k
    assert "/" in NT.EVENTS["approval:next_tier"]["fields"]["inapp.message"]["default"], "預設字含斜線，仍要放行"
    assert _bad_for("approval:next_tier", {"version": 1, "inapp": {"message": "輪到您 {單號} 第 {層}/{總層} 層"}}) == {"inapp.message"}


def _bad_for(key, body):
    return {p["path"] for p in NT.definition_problems(key, body)}


def test_allow_status_only_on_the_approved_event():
    assert _bad_for("approval:approved", {"version": 1, "mail": {"badge": "已核准", "intro": "全數通過 批准 approved"}}) == set()
    assert _bad_for("approval:approved", {"version": 1, "mail": {"badge": "аpproved"}}) == {"mail.badge"}, "外觀相似字仍擋"
    for k in ("approval:submitted", "approval:next_tier", "approval:returned"):
        assert _bad_for(k, {"version": 1, "mail": {"badge": "已核准"}}) == {"mail.badge"}, k


def test_quote_family_inapp_helpers_are_byte_identical_when_off_and_use_the_template_when_published(monkeypatch):
    from modules.case.api import quotations as QA
    _tpl_ev(monkeypatch, {})
    assert QA._tier_msg("MQ-1", "（退回改版）", "乙", 2, 3) == "報價單 MQ-1（退回改版）（乙）輪到您簽核（第 2 層 / 共 3 層）"
    assert QA._tier_msg("MQ-1", "", "乙", 2, 3) == "報價單 MQ-1（乙）輪到您簽核（第 2 層 / 共 3 層）"
    assert QA._approved_msg("MQ-1", "乙", "王") == "報價單 MQ-1（乙）已核准"
    assert QA._returned_msg("MQ-1-R1", "MQ-1", "乙") == "報價單 MQ-1-R1（原 MQ-1，乙）已退回修改，請確認後重新送審"
    _tpl_ev(monkeypatch, {"approval:next_tier": {"version": 1, "inapp": {"message": "輪到您 {單號} 第 {層} 層"}},
                          "approval:approved": {"version": 1, "inapp": {"message": "{單號} 已核准完成"}},
                          "approval:returned": {"version": 1, "inapp": {"message": "{新單號} 請修改"}}})
    assert QA._tier_msg("MQ-1", "", "乙", 2, 3) == "輪到您 MQ-1 第 2 層"
    assert QA._approved_msg("MQ-1", "乙", "王") == "MQ-1 已核准完成"
    assert QA._returned_msg("MQ-1-R1", "MQ-1", "乙") == "MQ-1-R1 請修改"


def _tpl_ev(monkeypatch, by_event):
    monkeypatch.setattr(NT, "resolve", lambda key, conn=None: by_event.get(key))


def test_quote_family_mails_are_byte_identical_when_off_and_change_only_the_template_fields(monkeypatch):
    sent = _capture_mail(monkeypatch)
    calls = [lambda: EN.notify_next_tier("MQ-9", "丙公司", 2, 3, ["u"]),
             lambda: EN.notify_approved("MQ-9", "丙公司", "王經理", "u"),
             lambda: EN.notify_returned("MQ-9", "MQ-9-R1", "丙公司", "請補資料", "u")]
    monkeypatch.setattr(EN, "_admin_emails", lambda k=None: [])
    _tpl_ev(monkeypatch, {})
    off = []
    for c in calls:
        c()
        off.append((sent["subject"], sent["html"]))
    assert off[0][0] == "【MOTRIX 系統通知】簽核－報價單審核通知（第 2/3 層）：MQ-9（丙公司）"
    assert off[1][0] == "【MOTRIX 系統通知】簽核－報價單審核完成：MQ-9（丙公司）"
    assert off[2][0] == "【MOTRIX 系統通知】簽核－報價單退回修改：MQ-9（丙公司）"
    # 發布範本但沒有任何欄位對上 ⇒ 仍與關閉時相同（沒設定的欄位維持預設）
    _tpl_ev(monkeypatch, {"approval:next_tier": {"version": 1, "mail": {}}, "approval:approved": {"version": 1, "mail": {}}, "approval:returned": {"version": 1, "mail": {}}})
    for c, (subj, html) in zip(calls, off):
        c()
        assert (sent["subject"], sent["html"]) == (subj, html)
    _tpl_ev(monkeypatch, {"approval:next_tier": {"version": 1, "mail": {"reason": "輪到您 {單號}", "badge": "請處理", "intro": "第 {層} 層"}},
                          "approval:approved": {"version": 1, "mail": {"badge": "已核准", "reason": "完成 {單號} {最終審核人}"}},
                          "approval:returned": {"version": 1, "mail": {"reason": "退回 {原單號} {新單號}", "button": "去修改"}}})
    calls[0]()
    assert sent["subject"] == "【MOTRIX 系統通知】簽核－輪到您 MQ-9" and "請處理" in sent["html"] and "第 2 層" in sent["html"] and "報價單簽核流程通知" in sent["html"]
    calls[1]()
    assert sent["subject"] == "【MOTRIX 系統通知】簽核－完成 MQ-9 王經理" and "已核准" in sent["html"]
    calls[2]()
    assert sent["subject"] == "【MOTRIX 系統通知】簽核－退回 MQ-9 MQ-9-R1" and "去修改" in sent["html"] and "請補資料" in sent["html"]


def test_defaults_in_the_senders_equal_the_event_defaults():
    import inspect
    for fn, key in ((EN.notify_next_tier, "approval:next_tier"), (EN.notify_approved, "approval:approved"), (EN.notify_returned, "approval:returned")):
        src = inspect.getsource(fn)
        for f in ("title", "badge", "button"):
            assert NT.EVENTS[key]["fields"]["mail." + f]["default"] in src, (key, f)
