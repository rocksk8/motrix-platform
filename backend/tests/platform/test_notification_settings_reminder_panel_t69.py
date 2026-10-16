# -*- coding: utf-8 -*-
"""T69 SO-S5：通知設定頁的「簽核提醒寄不出去的單據」唯讀面板。

面板只讀既有端點 `GET /api/settings/reminder-send-failures`（最高管理者限定），不新增端點。
① 頁面真的有接這個端點、有空清單文字、有補填 Email 的連結
② 頁面用的欄位名（docType／docNo／reason／attempts／at／key）＝後端真的寫出的欄位（防兩邊各寫各的）
③ 原因白話：兩種後端原因碼都有對應文字，頁面不直接顯示原因碼
④ 非最高管理者打端點 403（面板的「只有最高管理者可以查看」分支有依據）
⑤ 沒有破壞 AL1：init() 只有一個守衛、頁面沒有第二個 x-init
"""
import re
from pathlib import Path

PAGE = Path(__file__).resolve().parents[3] / "frontend" / "pages" / "notification-settings.html"


def _page():
    return PAGE.read_text(encoding="utf-8")


def test_page_reads_the_existing_endpoint_and_explains_empty_and_denied():
    s = _page()
    assert "/api/settings/reminder-send-failures" in s
    assert "目前沒有寄不出去的提醒" in s            # 空清單要有話說，不是一片空白
    assert "只有最高管理者可以查看" in s            # 403 分支
    assert 'href="users.html"' in s                  # 補填 Email 的出口


def test_page_field_names_are_the_ones_the_backend_writes(tmp_path, monkeypatch):
    from helpers import system_checks
    store = {}
    monkeypatch.setattr(system_checks, "_get_setting", lambda k, d=None: store.get(k, d))
    monkeypatch.setattr(system_checks, "_set_setting", lambda k, v: store.__setitem__(k, v))
    system_checks._record_reminder_failure("報價單", "MQ-202610-001", 3, "permanent_fail")
    row = system_checks.reminder_send_failures()[0]
    s = _page()
    for key in ("docType", "docNo", "reason", "attempts", "at", "key"):
        assert key in row, key                       # 後端沒寫這欄 ⇒ 面板會是空的
    for key in ("it.docType", "it.docNo", "it.reason", "it.attempts", "it.at", "it.key"):
        assert key in s, key


def test_reason_codes_are_shown_as_plain_words():
    from helpers import email_notify
    s = _page()
    for code in (email_notify.SEND_PERMANENT_FAIL, email_notify.SEND_UNKNOWN):
        assert "'%s'" % code in s                    # 對照表裡有這個後端原因碼
    assert "x-text=\"it.reason\"" not in s           # 不直接把原因碼印給使用者
    assert "收件人沒有 Email" in s and "不確定信有沒有寄出" in s


def test_endpoint_refuses_non_superadmin(client, make_user):
    name, pw = make_user(username="rfp_user", role="admin")
    tok = client.post("/api/auth/login", json={"username": name, "password": pw}).json()["token"]
    r = client.get("/api/settings/reminder-send-failures", headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 403, r.text


def test_panel_does_not_add_a_second_init():
    s = _page()
    assert len(re.findall(r"x-init=", s)) == 1
    assert s.count("_initDone") >= 2                 # 守衛仍在（宣告＋判斷）
