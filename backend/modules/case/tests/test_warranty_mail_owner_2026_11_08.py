# -*- coding: utf-8 -*-
"""T78 R1：保固到期信要寄得到案件業務，而且先寄成功才記「已通知」。

舊作法：`quotations.sales_person`（顯示名）當 `username` 比對收件人 ⇒ 顯示名≠帳號時業務收不到；
又在寄信前就寫 guard_key ⇒ SMTP 暫時失敗就永遠不補寄。
新作法：`sales_person_id` 外鍵解出帳號（`helpers.case_access.case_owner_username`）＋`send_registered(wait=True)`，寄成功才寫記號。"""
import json
from datetime import date, timedelta

import pytest

from tests._requires import requires_module

pytestmark = requires_module("case", "本檔打 M01（案件）的每日保固檢查")

OWNER_EMAIL = "owner-sales@example.invalid"
ADMIN_EMAIL = "boss-admin@example.invalid"
QNO = "MQ-WR-001"


class _Handle:
    def __init__(self, outcome):
        self._o = outcome

    def wait(self, timeout=None):
        return self._o


def _mk_user(username, display, email, role="sales", active=1):
    import db
    c = db.get_db()
    try:
        cur = c.execute("INSERT INTO users (username, password_hash, display_name, role, modules, active, created_at, must_change_password, email) "
                        "VALUES (?,?,?,?,?,?,?,0,?)", (username, "x", display, role, "[]", active, "2026-01-01T00:00:00", email))
        c.commit()
        return cur.lastrowid
    finally:
        c.close()


def _mk_case(owner_id, owner_display, qno=QNO, n_devices=1):
    import db
    ws = (date.today() - timedelta(days=350)).isoformat()                       # 12 個月保固 ⇒ 約 15 天後到期（落在預設 30 天預警內）
    data = {"caseRecord": {"devices": [{"name": "NVR-%02d" % i, "sn": "SN%04d" % i, "warrantyStart": ws, "warrantyMonths": 12} for i in range(1, n_devices + 1)]}}
    c = db.get_db()
    try:
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, sales_person, sales_person_id) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (qno, "已送出", "保固客戶", "保固專案", 1000, 952, json.dumps(data, ensure_ascii=False),
                   "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", owner_display, owner_id))
        c.commit()
    finally:
        c.close()


def _guards():
    import db
    c = db.get_db()
    try:
        return [r["key"] for r in c.execute("SELECT key FROM system_settings WHERE key LIKE 'warranty_notif.%'").fetchall()]
    finally:
        c.close()


@pytest.fixture()
def mail(monkeypatch):
    """攔截寄送：記下收件人；結果由 `state["outcome"]` 決定（預設寄出）。"""
    from helpers import email_notify as en
    state = {"outcome": en.SEND_SENT, "sent": [], "html": []}

    def fake(to, subject, html):
        state["sent"].append(list(to))
        state["html"].append(html)
        return _Handle(state["outcome"])
    monkeypatch.setattr(en, "_async_send", fake)
    return state


def _run():
    import modules.case.case_deadlines as D
    D._check_warranty_expiry()


def test_owner_gets_the_mail_when_display_name_differs_from_username(client, mail):
    """顯示名「王小明」≠ 帳號 sales_wang：業務信箱仍要在收件人內（舊作法以顯示名比對 username，收不到）。"""
    uid = _mk_user("sales_wang", "王小明", OWNER_EMAIL)
    _mk_user("boss_adm", "管理者", ADMIN_EMAIL, role="superadmin")
    _mk_case(uid, "王小明")
    _run()
    assert mail["sent"], "沒有寄出任何信"
    assert OWNER_EMAIL in mail["sent"][0], mail["sent"]
    assert len(_guards()) == 1


def test_transient_failure_does_not_write_the_guard_and_retries_next_run(client, mail):
    from helpers import email_notify as en
    uid = _mk_user("sales_wang", "王小明", OWNER_EMAIL)
    _mk_case(uid, "王小明")
    mail["outcome"] = en.SEND_TRANSIENT_FAIL
    _run()
    assert len(mail["sent"]) == 1 and _guards() == [], "暫時失敗不可寫已通知記號"
    mail["outcome"] = en.SEND_SENT
    _run()
    assert len(mail["sent"]) == 2 and len(_guards()) == 1, "下一次檢查要補寄並寫記號"
    _run()
    assert len(mail["sent"]) == 2, "寫了記號之後不重寄"


def test_unknown_and_permanent_outcomes_keep_the_guard_to_avoid_double_send(client, mail):
    from helpers import email_notify as en
    uid = _mk_user("sales_wang", "王小明", OWNER_EMAIL)
    _mk_case(uid, "王小明")
    mail["outcome"] = en.SEND_UNKNOWN
    _run()
    assert len(_guards()) == 1
    _run()
    assert len(mail["sent"]) == 1


def test_inactive_owner_still_notifies_group_recipients_only(client, mail):
    uid = _mk_user("sales_gone", "離職業務", OWNER_EMAIL, active=0)
    _mk_user("boss_adm", "管理者", ADMIN_EMAIL, role="superadmin")
    _mk_case(uid, "離職業務")
    _run()
    assert mail["sent"], "群組收件人（管理員）仍要收到"
    assert OWNER_EMAIL not in mail["sent"][0]


def test_no_recipient_does_not_write_the_guard(client, mail, monkeypatch):
    from helpers import email_notify as en
    uid = _mk_user("sales_nomail", "無信箱", "")
    _mk_case(uid, "無信箱")
    monkeypatch.setattr(en, "_group_emails", lambda *a, **k: [])
    _run()
    assert mail["sent"] == [] and _guards() == []


def test_one_failing_device_does_not_stop_the_scan(client, mail, monkeypatch):
    """寄送丟例外也只是這一台不記錄，掃描繼續。"""
    from helpers import email_notify as en
    uid = _mk_user("sales_wang", "王小明", OWNER_EMAIL)
    _mk_case(uid, "王小明")
    monkeypatch.setattr(en, "send_registered", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    _run()                                                      # 不丟例外
    assert _guards() == []


def test_button_link_points_at_the_case_not_the_site_home(client, mail, monkeypatch):
    """K 審必修：信件按鈕連到 quotation-form.html?no=<單號>（與舊信相同），不是退成站台首頁。"""
    import re
    from helpers import email_notify as en
    monkeypatch.setattr(en, "_base_url", lambda: "https://erp.example.test")      # 新安裝（資料庫沒有通知設定）網址為空 ⇒ 連結退成「#」（menu-ux b0）；要驗的是「有網址時連到該案」
    uid = _mk_user("sales_wang", "王小明", OWNER_EMAIL)
    _mk_case(uid, "王小明")
    _run()
    hrefs = re.findall(r'<a href="([^"]+)" class="btn"', mail["html"][0])
    assert hrefs == ["%s/pages/quotation-form.html?no=%s" % (en._base_url(), QNO)], hrefs


def test_transient_failure_stops_the_rest_of_this_run(client, mail):
    """K 審建議：SMTP 暫時失敗就別逐台各等一次——本輪只試第一台，全部不寫記號；下一輪恢復後補齊。"""
    from helpers import email_notify as en
    uid = _mk_user("sales_wang", "王小明", OWNER_EMAIL)
    _mk_case(uid, "王小明", n_devices=2)
    _mk_case(uid, "王小明", qno="MQ-WR-002", n_devices=2)                 # 兩張案件：停止要跨案件生效，不只跳出內層迴圈
    mail["outcome"] = en.SEND_TRANSIENT_FAIL
    _run()
    assert len(mail["sent"]) == 1 and _guards() == []
    mail["outcome"] = en.SEND_SENT
    _run()
    assert len(mail["sent"]) == 5 and len(_guards()) == 4        # 第二輪四台都補寄（第一輪已試過 1 台）


def test_no_recipient_does_not_halt_the_scan(client, mail, monkeypatch):
    """沒有收件人只是這一台沒人可寄，不代表 SMTP 壞了：後面的設備照掃（各自都沒收件人 ⇒ 都不寫記號）。"""
    from helpers import email_notify as en
    uid = _mk_user("sales_nomail", "無信箱", "")
    _mk_case(uid, "無信箱", n_devices=3)
    monkeypatch.setattr(en, "_group_emails", lambda *a, **k: [])
    seen = []
    real = en.send_registered
    monkeypatch.setattr(en, "send_registered", lambda *a, **k: (seen.append(1), real(*a, **k))[1])
    _run()
    assert len(seen) == 3 and _guards() == []
