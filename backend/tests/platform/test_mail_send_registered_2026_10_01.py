"""A2-0 底層預留 #6：模組登記信件類型 ⇒ 自動進個人通知偏好；`email_notify.send_registered` 通用寄信入口。
① 模組（owner != core）`mail_types.register` 的新 key 自動出現在 EVENT_KEYS／「其他模組通知」組；core 的不自動（仍由固定清單＋守門管）
② `ensure_event` 冪等、不覆蓋已存在的 key
③ `send_registered`：事件收件人＋群組收件人去重、套退訂；沒有收件人 ⇒ False 不寄；主旨由登記表產生
④ 守門 test_mail_registry 的掃描認得 `send_registered`：字面 key 未登記 ⇒ 報錯
反向控制：`register` 拿掉自動併入 ⇒ ①必須紅。"""
import pytest

from helpers import email_notify as en
from helpers import mail_types as mt
from helpers import notification_prefs as np_


@pytest.fixture()
def clean_mail(monkeypatch):
    monkeypatch.setattr(mt, "_REGISTRY", dict(mt._REGISTRY))
    groups = [(label, list(items)) for label, items in np_.EVENT_GROUPS]
    keys = list(np_.EVENT_KEYS)
    yield
    np_.EVENT_GROUPS[:] = groups
    np_.EVENT_KEYS[:] = keys


def test_module_registered_type_joins_prefs_but_core_does_not(clean_mail):
    assert "zz_exp_pr" not in np_.EVENT_KEYS
    mt.register("zz_exp_pr", "請購單待簽", "approval", "none", "當層簽核人", "影響", "處理", owner="zz_mod")
    assert "zz_exp_pr" in np_.EVENT_KEYS
    grp = dict(np_.EVENT_GROUPS)[np_.MODULE_GROUP_LABEL]
    assert ("zz_exp_pr", "請購單待簽") in grp
    mt.register("zz_core_k", "核心類型", "approval", "none", "", "影響", "處理")             # owner=core ⇒ 不自動併入
    assert "zz_core_k" not in np_.EVENT_KEYS


def test_ensure_event_is_idempotent_and_keeps_existing(clean_mail):
    assert np_.ensure_event("approval_request", "別的說明") is False
    assert dict(dict(np_.EVENT_GROUPS)["簽核流程"])["approval_request"] == "報價單待審核通知（當層簽核人）"
    assert np_.ensure_event("zz_k1", "甲") is True and np_.ensure_event("zz_k1", "乙") is False
    assert np_.EVENT_KEYS.count("zz_k1") == 1 and np_.ensure_event("", "x") is False


def test_send_registered_recipients_subject_and_no_recipient(clean_mail, monkeypatch):
    mt.register("zz_exp_pr", "請購單待簽", "approval", "admins", "當層簽核人", "影響說明", "處理說明", owner="zz_mod")
    sent = []
    monkeypatch.setattr(en, "_async_send", lambda to, subject, html: sent.append((to, subject, html)))
    monkeypatch.setattr(en, "_lookup_emails", lambda u, k=None: ["a@x", "b@x"] if u else [])
    monkeypatch.setattr(en, "_group_emails", lambda k=None: ["b@x", "c@x"])
    assert en.send_registered("zz_exp_pr", title="請購單", rows=[("單號", "PR-1")], usernames=["u"], to_group=True,
                              reason="請購單待審核：PR-1", link="https://h/pages/x.html?id=1") is True
    to, subject, html = sent[0]
    assert to == ["a@x", "b@x", "c@x"]                                                   # 去重、保序
    assert subject == "【MOTRIX 系統通知】簽核－請購單待審核：PR-1"
    assert "影響說明" in html and "處理說明" in html and "https://h/pages/x.html?id=1" in html and "PR-1" in html
    sent.clear()
    monkeypatch.setattr(en, "_lookup_emails", lambda u, k=None: [])
    monkeypatch.setattr(en, "_group_emails", lambda k=None: [])
    assert en.send_registered("zz_exp_pr", title="t", rows=[], usernames=["u"], to_group=True) is False and sent == []


def test_static_guard_knows_send_registered():
    from tests.platform.test_mail_registry import scan
    ok = ('register("zz_ok", "甲", "business", "admins", "", "i", "a")\n'
          'def f():\n    send_registered("zz_ok", title="t", rows=[])\n')
    assert scan({"m.py": ok})[1] == []
    _reg, problems = scan({"m.py": ok.replace('send_registered("zz_ok"', 'send_registered("zz_nope"')})
    assert any("未登記" in p for p in problems), problems
