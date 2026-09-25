# -*- coding: utf-8 -*-
"""IP-5 `daily_task.external`（M12 → M01）與 IP-6 `calendar.writeback`（M01／M03／M05 → L1 行事曆）。

ROADMAP A11／DEPENDENCY-MAP §3.1：M01 不再直接寫 M12 的 daily_tasks／daily_task_completions；
L1 行事曆不再直接寫 5 張 L2 表。

⚙️ 反向控制：同一條流程先確認「提供者在 ⇒ 真的有寫」（正對照），再拿掉提供者 ⇒
主流程照常、只少那一項，而且明說。
"""
import ast
import json
from pathlib import Path

import pytest

from core import registry, source_tree

BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _inline_bg(monkeypatch):
    """端點的背景同步改成當場執行（斷言看得到結果；不留執行緒）。"""
    from routers import quotations as q
    monkeypatch.setattr(q, "spawn_bg_thread", lambda target, args=(), **kw: target(*args))


def _without(monkeypatch, capability, name):
    """拿掉一個提供者：未搬遷模組在 _LEGACY_PROVIDERS，已搬進 modules/ 的在已載入模組的 ModuleSpec.providers。"""
    key = (capability, name)
    if key in registry._LEGACY_PROVIDERS:
        monkeypatch.delitem(registry._LEGACY_PROVIDERS, key)
        return
    for lm in registry.loaded():
        if key in lm.spec.providers:
            monkeypatch.delitem(lm.spec.providers, key)
            return
    # 提供者本來就不在（例：模組資料夾被刪掉的反向控制）⇒ 已經是「沒有」的狀態
    assert key not in registry.providers(capability), key


def _login(client, make_user, name):
    u, p = make_user(name, "Conn-Pass-123", role="superadmin")[:2]
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return u, {"Authorization": "Bearer " + tok}


def _case(no):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
                     "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (no, "已送出", "串接客戶", "串接工程", 1000, 952, "{}",
                      "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"))
        conn.commit()
    finally:
        conn.close()


def _q(sql, *args):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


# ── IP-5 ────────────────────────────────────────────────────────────────



def _tick(client, h, no, done=True):
    sid = client.post(f"/api/quotations/{no}/stages", headers=h, json={"label": "客戶驗收"}).json()["id"]
    r = client.put(f"/api/quotations/{no}/stages/{sid}", headers=h, json={"done": done, "doneAt": "2026-09-11"})
    assert r.status_code == 200, r.text
    return sid, r.json()




def test_daily_task_connector_without_m12_stage_still_saves_and_says_so(client, make_user, monkeypatch):
    """反向控制：拿掉 M12 ⇒ 勾選照常存檔、零筆每日任務、回應明說原因。"""
    from helpers.case_stage_tasks import NOTICE_NO_DAILY_TASKS
    _without(monkeypatch, "daily_task.external", "daily_tasks")
    u, h = _login(client, make_user, "ip5_off")
    _case("MQ-IP5-OFF")
    sid, body = _tick(client, h, "MQ-IP5-OFF")
    assert body.get("done") in (True, 1)
    assert body.get("notice") == NOTICE_NO_DAILY_TASKS == "未建立每日任務：每日任務模組未安裝"
    assert _q("SELECT * FROM daily_tasks WHERE case_no=?", "MQ-IP5-OFF") == []
    assert _q("SELECT done, daily_task_id FROM case_stages WHERE id=?", sid)[0] == {"done": 1, "daily_task_id": 0}


def _stage_with_old_task(client, h, no, task_id=77):
    """M12 在的時候建立過任務（daily_task_id 有值）、之後 M12 被拿掉的狀態：直接寫 M01 自己的 case_stages。"""
    sid = client.post(f"/api/quotations/{no}/stages", headers=h, json={"label": "叫料出貨"}).json()["id"]
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE case_stages SET done=1, done_at='2026-09-11', daily_task_id=? WHERE id=?", (task_id, sid))
        conn.commit()
    finally:
        conn.close()
    return sid


def test_without_m12_uncheck_says_the_old_task_was_not_withdrawn(client, make_user, monkeypatch):
    """B-1（AUDIT-X-C-batch1）：M12 不在時取消勾選，原本有任務 ⇒ 明說「沒有收回」，不能說成「沒有建立」。

    任務 id 留著：M12 裝回來後再勾選／取消勾選，會收斂到同一筆任務（見 NOTICE_NOT_WITHDRAWN 註解）。"""
    from helpers.case_stage_tasks import NOTICE_NOT_WITHDRAWN
    _without(monkeypatch, "daily_task.external", "daily_tasks")
    u, h = _login(client, make_user, "ip5_unchk")
    _case("MQ-IP5-UNCHK")
    sid = _stage_with_old_task(client, h, "MQ-IP5-UNCHK")
    r = client.put(f"/api/quotations/MQ-IP5-UNCHK/stages/{sid}", headers=h, json={"done": False, "doneAt": ""})
    assert r.status_code == 200, r.text
    assert r.json().get("notice") == NOTICE_NOT_WITHDRAWN and "未收回" in NOTICE_NOT_WITHDRAWN
    assert _q("SELECT done, daily_task_id FROM case_stages WHERE id=?", sid)[0] == {"done": 0, "daily_task_id": 77}


def test_without_m12_uncheck_with_no_task_says_nothing(client, make_user, monkeypatch):
    """原本就沒有任務 ⇒ 沒有什麼沒收回，不出提示（提示只在真的少了一件事時出現）。"""
    _without(monkeypatch, "daily_task.external", "daily_tasks")
    u, h = _login(client, make_user, "ip5_unchk0")
    _case("MQ-IP5-UNCHK0")
    sid, _ = _tick(client, h, "MQ-IP5-UNCHK0")
    r = client.put(f"/api/quotations/MQ-IP5-UNCHK0/stages/{sid}", headers=h, json={"done": False, "doneAt": ""})
    assert r.status_code == 200 and "notice" not in r.json(), r.json()


def test_without_m12_deleting_a_stage_with_a_task_says_so(client, make_user, monkeypatch):
    from helpers.case_stage_tasks import NOTICE_NOT_WITHDRAWN
    _without(monkeypatch, "daily_task.external", "daily_tasks")
    u, h = _login(client, make_user, "ip5_del")
    _case("MQ-IP5-DEL")
    sid = _stage_with_old_task(client, h, "MQ-IP5-DEL")
    r = client.delete(f"/api/quotations/MQ-IP5-DEL/stages/{sid}", headers=h)
    assert r.status_code == 200 and r.json() == {"ok": True, "notice": NOTICE_NOT_WITHDRAWN}, r.text
    sid0, _ = _tick(client, h, "MQ-IP5-DEL")                       # 沒有任務的階段 ⇒ 不出提示
    assert client.delete(f"/api/quotations/MQ-IP5-DEL/stages/{sid0}", headers=h).json() == {"ok": True}


def _sql_writes(rel):
    """檔案裡字串常值中的 INSERT/UPDATE/DELETE 目標表。"""
    import re
    src = (BACKEND / rel).read_text(encoding="utf-8")
    out = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            for m in re.finditer(r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+([a-z_]+)", n.value, re.I):
                out.add(m.group(1).lower())
    return out


def test_m01_and_l1_no_longer_write_foreign_tables():
    assert not ({"daily_tasks", "daily_task_completions"} & _sql_writes("helpers/case_stage_tasks.py"))
    assert not ({"case_stages", "invoice_vouchers", "payment_requests", "shipping_notes", "quotations"}
                & _sql_writes("helpers/google_calendar.py"))


# ── IP-6 ────────────────────────────────────────────────────────────────

#: 各 kind 的提供方檔：已搬進 modules/ 的 kind 在模組不在時本來就不登記（PLAYBOOK §B-11）
IP6_OWNERS = {
    "invoice_voucher": "routers/invoice_vouchers.py",
    "payment_request": "routers/payment_requests.py",
    "shipping_note": "modules/supply/api/shipping_notes.py",
    "quotation": "routers/quotations.py",
    "case_stage": "routers/quotations.py",
}


def test_calendar_writeback_every_owner_registers_its_writeback(client):
    """client 夾具＝載入器掛好已安裝的模組（ModuleSpec.providers 在那時登記）。"""
    import routers.invoice_vouchers, routers.payment_requests, routers.quotations  # noqa: F401,E401
    want = {k for k, f in IP6_OWNERS.items() if source_tree.module_installed(f)}
    assert "quotation" in want and set(registry.providers("calendar.writeback")) == want


@pytest.fixture()
def fake_google(monkeypatch):
    from helpers import google_calendar as gc
    monkeypatch.setattr(gc, "_create_all_day_event", lambda s, d, dt: "evt-ip6")
    monkeypatch.setattr(gc, "_update_all_day_event", lambda eid, s, d, dt: eid)
    monkeypatch.setattr(gc, "_delete_event", lambda eid: None)
    return gc


def test_calendar_writeback_with_owner_event_id_is_written_back(client, make_user, fake_google):
    _case("MQ-IP6-ON")
    fake_google.push_event_for_quotation_won("MQ-IP6-ON")
    d = json.loads(_q("SELECT data_json FROM quotations WHERE quote_no=?", "MQ-IP6-ON")[0]["data_json"])
    assert d.get("googleCalendarEventId") == "evt-ip6"


@pytest.fixture()
def distinct_google(monkeypatch):
    """每一次建立事件都回**不同**的 id（X 稽核 A-3：同一個假值驗不出寫反）；`on_create` 可在建立期間插入動作。"""
    from helpers import google_calendar as gc
    made, hooks = [], []

    def _create(summary, desc, dt):
        for h in hooks:
            h()
        made.append("evt-%d" % (len(made) + 1))
        return made[-1]
    monkeypatch.setattr(gc, "_create_all_day_event", _create)
    monkeypatch.setattr(gc, "_update_all_day_event", lambda eid, s, d, dt: eid)
    monkeypatch.setattr(gc, "_delete_event", lambda eid: None)
    gc.made, gc.on_create = made, hooks
    return gc


def test_calendar_writeback_case_stage_slots_are_separate(client, make_user, distinct_google):
    u, h = _login(client, make_user, "ip6_stage")
    _case("MQ-IP6-STG")
    sid = client.post("/api/quotations/MQ-IP6-STG/stages", headers=h, json={"label": "驗收"}).json()["id"]
    import db
    conn = db.get_db()
    conn.execute("UPDATE case_stages SET due_date='2026-10-01', done=1, done_at='2026-09-30' WHERE id=?", (sid,))
    conn.commit()
    conn.close()
    distinct_google.push_event_for_case_stage_due(sid)
    due_id = distinct_google.made[-1]
    distinct_google.push_event_for_case_stage_done(sid)
    done_id = distinct_google.made[-1]
    assert due_id != done_id
    row = _q("SELECT google_calendar_event_id, google_calendar_done_event_id FROM case_stages WHERE id=?", sid)[0]
    assert row == {"google_calendar_event_id": due_id, "google_calendar_done_event_id": done_id}


#: 單號放在 data_json 的三種單據：(kind, 表, 單號欄, 觸發函式)
_IP6_DOC_KINDS = [
    ("invoice_voucher", "invoice_vouchers", "voucher_no", "push_event_for_invoice_voucher"),
    ("payment_request", "payment_requests", "request_no", "push_event_for_payment_request"),
]
# 出貨單（M03）那一列在 modules/supply/tests/test_supply_calendar_writeback.py（拿掉 M03 時跟著消失）


def _doc(table, col, no):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO %s (%s, quote_no, data_json) VALUES (?, ?, ?)" % (table, col),
                     (no, "MQ-IP6-DOC", json.dumps({"keep": "原本的值"})))
        conn.commit()
    finally:
        conn.close()


def _doc_data(table, col, no):
    return json.loads(_q("SELECT data_json FROM %s WHERE %s=?" % (table, col), no)[0]["data_json"])


@pytest.mark.parametrize("kind,table,col,push", _IP6_DOC_KINDS)
def test_calendar_writeback_document_kinds_write_their_own_row(client, distinct_google, kind, table, col, push):
    """X 稽核 A-3：三支回寫原本沒有任何題目執行過。每一種都要把**這一次**建出來的 id 寫進**自己那一列**，其他欄位不動。"""
    _doc(table, col, "IP6-%s-A" % kind)
    _doc(table, col, "IP6-%s-B" % kind)
    getattr(distinct_google, push)("IP6-%s-A" % kind)
    a = _doc_data(table, col, "IP6-%s-A" % kind)
    assert a == {"keep": "原本的值", "googleCalendarEventId": distinct_google.made[-1]}
    assert "googleCalendarEventId" not in _doc_data(table, col, "IP6-%s-B" % kind)


@pytest.mark.parametrize("kind,table,col,push", _IP6_DOC_KINDS)
def test_calendar_writeback_document_kinds_do_not_overwrite_concurrent_edits(client, distinct_google, kind, table, col, push):
    """lost-update：建立事件（網路請求）期間別人改了單據 ⇒ 回寫只加 event id，不把舊的 data_json 蓋回去。"""
    no = "IP6-%s-LU" % kind
    _doc(table, col, no)

    def _someone_edits():
        import db
        conn = db.get_db()
        conn.execute("UPDATE %s SET data_json=? WHERE %s=?" % (table, col),
                     (json.dumps({"keep": "別人剛改的"}, ensure_ascii=False), no))
        conn.commit()
        conn.close()
    distinct_google.on_create.append(_someone_edits)
    getattr(distinct_google, push)(no)
    assert _doc_data(table, col, no) == {"keep": "別人剛改的", "googleCalendarEventId": distinct_google.made[-1]}


def test_calendar_writeback_without_owner_event_is_created_but_nothing_is_written(client, make_user, fake_google, monkeypatch, caplog):
    """反向控制：拿掉 M01 的回寫 ⇒ 不丟例外、不寫任何東西、記 WARNING 說明原因。"""
    import logging
    _without(monkeypatch, "calendar.writeback", "quotation")
    _case("MQ-IP6-OFF")
    with caplog.at_level(logging.WARNING, logger=fake_google.logger.name):
        fake_google.push_event_for_quotation_won("MQ-IP6-OFF")
    d = json.loads(_q("SELECT data_json FROM quotations WHERE quote_no=?", "MQ-IP6-OFF")[0]["data_json"])
    assert "googleCalendarEventId" not in d
    assert "擁有模組未安裝" in caplog.text


def test_calendar_writeback_unknown_stage_slot_is_refused():
    import routers.quotations  # noqa: F401
    fn = registry.providers("calendar.writeback")["case_stage"]
    with pytest.raises(KeyError):
        fn(1, "evt", "guessed_slot")
