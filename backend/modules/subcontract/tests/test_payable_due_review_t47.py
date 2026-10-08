# -*- coding: utf-8 -*-
"""第 47 班 paydate-l1 獨立稽核（ab）跟進 S1～S4 的回歸題：

S1 `run_scan` 遇到 SEND_UNKNOWN 停止寄信後，其餘筆仍補站內通知（只有「寄信日＝今天」的候選，錯過就永遠沒有）；信件語意不變（沒寄出就不寫信件 guard）。
S2 承攬商匯款核准／撤銷核准／退回：行事曆對齊（`_PD.fire`）在 commit 之後、通知之前，通知出錯也不漏。
S3 出納端點在 commit 之後呼叫的串接點出錯，只記 log，不讓已完成的改期回 500。
S4 同一筆的兩次對齊（讀現況→寫事件）序列化：後讀到的現況不會被先讀到的舊現況覆蓋。
"""
import threading
import time
from datetime import date

import pytest

from modules.subcontract.tests.test_voucher_payable_due_t45 import (  # noqa: F401  fixture／輔助
    TODAY, _login, _voucher, _x, world)
from tests import _fake_gcal
from tests._requires import requires_module

pytestmark = [requires_module("case", "用案件編號建派發／匯款單"), requires_module("arap", "出納端點在 M05"),
              requires_module("subcontract", "承攬商匯款")]


def _notes(username):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute("SELECT * FROM notifications WHERE username=? AND type LIKE ?", (username, "payable_due_%"))]
    finally:
        c.close()


def _guards(prefix):
    import db
    c = db.get_db()
    try:
        return [r["key"] for r in c.execute("SELECT key FROM system_settings WHERE key LIKE ?", (prefix + "%",))]
    finally:
        c.close()


def test_audit_s1_in_app_notice_still_written_for_items_after_a_send_unknown(client, world, monkeypatch):
    from helpers import payable_due_core as C
    items = [{"guard_id": "s1a", "planned": TODAY.isoformat(), "ident": "S1甲", "rows": [], "source": "x", "key": "s1a"},
             {"guard_id": "s1b", "planned": TODAY.isoformat(), "ident": "S1乙", "rows": [], "source": "x", "key": "s1b"},
             {"guard_id": "s1c", "planned": TODAY.isoformat(), "ident": "S1丙", "rows": [], "source": "x", "key": "s1c"}]
    called = []

    def send(kind, rows, link, ident, out=None):
        called.append(ident)
        out["outcome"] = C._en.SEND_UNKNOWN                 # 第一封就逾時
        return False

    C.run_scan(items, TODAY, is_wd=lambda d: d.weekday() < 5, send=send)
    assert called == ["S1甲"], "SMTP 無回應 ⇒ 只試第一封，不再逐封卡住"
    msgs = " ".join(n["message"] for n in _notes("vpd_fin"))
    for ident in ("S1甲", "S1乙", "S1丙"):
        assert ident in msgs, "%s 的站內通知要補寫（錯過今天就永遠沒有）" % ident
    assert _guards("payable_due_notif.s1") == [], "信件沒寄出 ⇒ 不寫信件 guard（語意不變，下次重試）"
    assert len(_guards("payable_due_inapp.s1")) >= 3, "站內通知 guard 各寫一次"


def test_audit_s1_wait_limit_also_still_writes_in_app_notices(client, world):
    from helpers import payable_due_core as C
    items = [{"guard_id": "s1w%d" % i, "planned": TODAY.isoformat(), "ident": "S1W%d" % i, "rows": [], "source": "x", "key": "s1w%d" % i}
             for i in range(3)]
    ticks = iter([0, 0, 999, 999, 999, 999, 999, 999])        # 第一筆之後就超過等待上限

    def send(kind, rows, link, ident, out=None):
        out["outcome"] = C._en.SEND_SENT
        return True

    C.run_scan(items, TODAY, is_wd=lambda d: d.weekday() < 5, send=send, monotonic=lambda: next(ticks), max_wait=10)
    msgs = " ".join(n["message"] for n in _notes("vpd_fin"))
    assert all(("S1W%d" % i) in msgs for i in range(3)), "超過等待上限的筆也補站內通知"


def test_audit_s2_calendar_sync_fires_even_when_the_notification_raises(client, world, monkeypatch):
    import modules.subcontract.api.contractor_vouchers as CV
    fired = []
    monkeypatch.setattr(CV._PD, "fire", lambda no: fired.append(no))
    monkeypatch.setattr(CV, "_notify", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("notify boom")))
    no = _voucher(client, world["sa"], "2031-07-15")
    _x("UPDATE contractor_payment_vouchers SET status='已核准', data_json=? WHERE voucher_no=?",
       ('{"approval": {"requestedBy": "vpd_sa"}}', no))                  # 有申請人才會走通知那一段
    with pytest.raises(Exception):
        client.post("/api/contractor-vouchers/%s/revoke-approval" % no, headers=world["sa"],
                    json={"note": "撤銷原因：測試用，說明文字夠長"})
    assert fired == [no], "撤銷核准：通知出錯時，對齊仍已觸發（commit 之後、通知之前）"


def test_s3_hook_failure_after_commit_does_not_turn_a_done_change_into_500(client, world, monkeypatch):
    from core import registry
    real = registry.single_provider

    def single_provider(name, *a, **k):
        if name == "contractor_voucher.planned_changed":
            return lambda voucher_no: (_ for _ in ()).throw(RuntimeError("hook boom"))
        return real(name, *a, **k)

    monkeypatch.setattr(registry, "single_provider", single_provider)
    no = _voucher(client, world["sa"], "2031-07-15")
    r = client.patch("/api/cashier/payable-queue/%s/planned-pay-date" % no, headers=world["fin"], json={"plannedPayDate": "2031-07-20"})
    assert r.status_code == 200 and r.json().get("plannedPayDate") == "2031-07-20", r.text


def test_audit_s4_two_quick_syncs_for_one_key_do_not_interleave_read_and_write(client, world, monkeypatch):
    """同一筆的兩次對齊：「讀現況→寫事件」整段序列化。沒有鎖時第二個執行緒會在第一個還沒寫完時就讀現況，
    之後兩邊的寫入先後不定 ⇒ 事件可能停在舊狀態。這裡記下讀與寫完成的順序，要求：讀A、寫A完、讀B、寫B完。"""
    from helpers import payable_due_core as C
    from modules.subcontract import payable_due as PD
    cal = _fake_gcal.install(monkeypatch)
    _fake_gcal.set_events(events={"payable_due": True})
    no = _voucher(client, world["sa"], "2031-07-15")
    log = []
    real_sync_event, real_event_tuple = C.sync_event, PD.event_tuple
    gate, second_started = threading.Event(), threading.Event()
    first = {"done": False}

    def event_tuple(row):
        log.append(("read", threading.current_thread().name))
        return real_event_tuple(row)

    def slow_first(source, key, item=None):
        if not first["done"]:
            first["done"] = True
            gate.set()                                      # 第一個執行緒已讀完現況、準備寫
            second_started.wait(10)
            time.sleep(1.0)                                 # 給第二個執行緒機會（沒有鎖時它會在這段時間讀現況）
        r = real_sync_event(source, key, item)
        log.append(("write_done", threading.current_thread().name))
        return r

    monkeypatch.setattr(PD, "event_tuple", event_tuple)
    monkeypatch.setattr(C, "sync_event", slow_first)
    t1 = threading.Thread(target=PD.sync, args=(no,), name="A")
    t1.start()
    assert gate.wait(5)
    _x("UPDATE contractor_payment_vouchers SET is_paid=1 WHERE voucher_no=?", (no,))     # 現況變了：已匯款 ⇒ 應收回
    t2 = threading.Thread(target=PD.sync, args=(no,), name="B")
    t2.start()
    second_started.set()
    t1.join(15)
    t2.join(15)
    assert log == [("read", "A"), ("write_done", "A"), ("read", "B"), ("write_done", "B")], log
    assert cal.events == {}, "最後的現況（已匯款）要贏：事件已收回"
