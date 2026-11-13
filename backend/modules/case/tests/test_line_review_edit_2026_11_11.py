# -*- coding: utf-8 -*-
"""T79 候選：「報價單審核中被簽核人編輯」的通知，除了信件還要能同時發 LINE（驗收題）。

走真實端點（POST /review-edit）→ `review_edit_notify.fire_edited` → `email_notify.send_registered` → `line_notify`；
LINE 對外呼叫換成假的 `_http`（不連 LINE）。驗：
- 收件人＝信件最終寄出的那些帳號裡「已綁定 LINE」者；沒綁定、停用、一般管理員、個人已退訂者都不收；
- 類型沒勾選／LINE 沒啟用／開發機標記 ⇒ 一則都不發，信件照寄；
- 預設不帶連結（A 案）；兩個開關都開才帶白名單連結；
- LINE 失敗不影響編輯存檔與信件。
"""
import time

import pytest

from modules.case.tests.test_content_fp_s1_2026_11_06 import NO, _seed
from modules.case.tests.test_reconcile_txn_s3b_2026_11_06 import _fresh_mode_cache, _set_mode
from modules.case.tests.test_review_edit_chain_reset_2026_11_11 import _prep_recipients, _set_email
from modules.case.tests.test_review_edit_s4_2026_11_07 import _edit
from tests._requires import requires_module

pytestmark = requires_module("case", "打 M01 的報價單複查編輯端點")

_ = _fresh_mode_cache

TOKEN = "tok-line-e2e-0123456789"


def _uid(n):
    return "U" + ("%032x" % n)


class _FakeLine:
    def __init__(self):
        self.calls, self.status = [], 200

    def __call__(self, method, path, token, payload=None):
        self.calls.append({"path": path, "token": token, "payload": payload})
        return self.status, {}

    def wait(self, n=1, timeout=5.0):
        end = time.time() + timeout
        while len(self.calls) < n and time.time() < end:
            time.sleep(0.02)
        time.sleep(0.15)                      # 多等一下，確認沒有「多出來」的呼叫
        return self.calls

    @property
    def mails(self):
        """只含「報價單審核中被編輯」這類信的收件人（主旨含「在審核中被」）。同一個行程裡別的測試／背景執行緒可能在這個測試期間寄出別類的信
        （2026-11-14 T84 閘門整批並行時多了一封只寄 sa1／sa2 的信；單跑與整個 case 模組並行都重現不出來）；本檔驗「這個事件的收件人」，
        不是「全機只有這一封信」。全部的信在 `all_mails`（收件人, 主旨），比對失敗時印在訊息裡，雜信的來源一眼看得出。"""
        return [to for to, subj in self.all_mails if "在審核中被" in subj]

    def targets(self):
        out = []
        for c in self.calls:
            p = c["payload"]
            out += [p["to"]] if isinstance(p["to"], str) else list(p["to"])
        return sorted(out)

    def text(self):
        return self.calls[-1]["payload"]["messages"][0]["text"]


@pytest.fixture()
def line(client, monkeypatch):
    from helpers import line_notify as L
    from helpers import email_notify as EN
    from helpers.settings import _set_setting
    fake = _FakeLine()
    monkeypatch.setattr(L, "_http", fake)
    monkeypatch.setattr(EN, "email_send_policy", lambda env=None: (True, "測試允許"))
    sent = []
    monkeypatch.setattr(EN, "_async_send", lambda to, subject, html: sent.append((sorted(to), subject)))
    fake.all_mails = sent
    _set_setting("line_notify", {"enabled": True, "channel_access_token": TOKEN, "events": {"approval_review_edit": True}})
    return fake


def _scenario(client, make_user):
    hs, names = _seed(client, make_user, tiers=3)
    _prep_recipients(make_user)
    _set_mode(2)
    from helpers import line_notify as L
    for i, u in enumerate(("fp_req", "sa1", "bystander", "sa_off", "sa_noemail"), start=1):
        L.link_user(u, _uid(i))            # sa2 刻意不綁
    return hs


def test_review_edit_also_pushes_line_to_linked_recipients_only(client, make_user, line):
    """2026-11-12：LINE 獨立於 Email——收件人＝業務收件人（送審人＋全部在職超管）∩ 已綁定；沒有 Email 的超管（sa_noemail）也收得到。"""
    hs = _scenario(client, make_user)
    r = _edit(client, hs[0], qty=9)
    assert r.status_code == 200, r.text
    line.wait(1)
    assert line.mails == [sorted(["req@example.test", "sa1@example.test", "sa2@example.test"])], "信件收件人不變：%r" % (line.all_mails,)
    # LINE：業務收件人 ∩ 已綁定＝送審人、sa1、**沒有 Email 的 sa_noemail**。sa2 沒綁；bystander（一般管理員）不是收件人、停用的 sa_off 兩個通道都不發，即使綁了也不收
    assert len(line.calls) == 1 and line.calls[0]["path"] == "/v2/bot/message/multicast"
    assert line.targets() == sorted([_uid(1), _uid(2), _uid(5)])
    assert line.calls[0]["token"] == TOKEN
    t = line.text()
    assert "報價單審核中被編輯" in t and NO in t and "編輯人" in t
    assert "http" not in t, "A 案：預設不帶連結"
    assert "變動項目" in t and "：9" not in t and "數量：" not in t, "只有欄位名稱，不帶新舊值"


def test_event_not_ticked_or_line_disabled_sends_nothing_but_mail_still_goes(client, make_user, line):
    from helpers.settings import _set_setting
    hs = _scenario(client, make_user)
    _set_setting("line_notify", {"enabled": True, "channel_access_token": TOKEN, "events": {}})          # 沒勾選
    assert _edit(client, hs[0], qty=9).status_code == 200
    assert line.wait(1, timeout=0.6) == [] and len(line.mails) == 1
    _set_setting("line_notify", {"enabled": False, "channel_access_token": TOKEN, "events": {"approval_review_edit": True}})   # 整個沒啟用
    assert _edit(client, hs[0], qty=8).status_code == 200
    assert line.wait(1, timeout=0.6) == [] and len(line.mails) == 2


def test_email_unsubscribed_user_still_gets_line(client, make_user, line):
    """使用者管理的「Email 通知偏好」只管信件；LINE 另有自己的個人勾選（line_prefs），Email 退訂不影響 LINE。"""
    import db
    hs = _scenario(client, make_user)
    c = db.get_db()
    c.execute("UPDATE users SET notification_muted=? WHERE username='sa1'", ('["approval_review_edit"]',))
    c.commit()
    c.close()
    assert _edit(client, hs[0], qty=9).status_code == 200
    line.wait(1)
    assert line.targets() == sorted([_uid(1), _uid(2), _uid(5)]), "sa1 退訂的是 Email；LINE 照發"
    assert line.mails == [sorted(["req@example.test", "sa2@example.test"])], "信件這邊 sa1 確實沒收到"


def test_company_mail_off_stops_mail_but_not_line(client, make_user, line):
    """「信件與通知收件設定」把這種信關掉只影響信件；LINE 有自己的公司開關與事件勾選。"""
    from helpers import mail_types as mt
    from helpers.settings import _set_setting
    hs = _scenario(client, make_user)
    _set_setting(mt.OVERRIDES_KEY, {"approval_review_edit": {"mode": "default", "users": [], "roles": [], "off": True}})
    assert _edit(client, hs[0], qty=9).status_code == 200
    line.wait(1)
    assert line.mails == [] and line.targets() == sorted([_uid(1), _uid(2), _uid(5)])


def test_dev_machine_marker_blocks_line_but_not_the_edit(client, make_user, line, monkeypatch):
    from helpers import email_notify as EN
    monkeypatch.setattr(EN, "email_send_policy", lambda env=None: (False, "測試：開發機標記"))
    hs = _scenario(client, make_user)
    assert _edit(client, hs[0], qty=9).status_code == 200
    assert line.wait(1, timeout=0.6) == []


def test_line_failure_never_breaks_the_edit_or_the_mail(client, make_user, line):
    line.status = 500
    hs = _scenario(client, make_user)
    r = _edit(client, hs[0], qty=9)
    assert r.status_code == 200, r.text
    line.wait(1)
    assert len(line.calls) == 1 and len(line.mails) == 1


def test_links_only_with_both_switches_and_only_the_whitelisted_page(client, make_user, line):
    from helpers.settings import _set_setting
    hs = _scenario(client, make_user)
    base = {"enabled": True, "channel_access_token": TOKEN, "events": {"approval_review_edit": True}}
    _set_setting("line_notify", {**base, "public_base_url": "https://line.example.com"})                   # 只有網域（A 案上線狀態）
    assert _edit(client, hs[0], qty=9).status_code == 200
    line.wait(1)
    assert "http" not in line.text()
    line.calls.clear()
    _set_setting("line_notify", {**base, "public_base_url": "https://line.example.com", "include_links": True})
    assert _edit(client, hs[0], qty=8).status_code == 200
    line.wait(1)
    t = line.text()
    assert "https://line.example.com/pages/quotation-form.html?no=%s" % NO in t
    assert "172.16" not in t and "https://line.example.com/pages/" in t
