# -*- coding: utf-8 -*-
"""onepipe P0d（2026-11-13）：保固到期通知納入已結案案件。旗標 `onepipe.warranty_closed_notify`（預設關）。

守的不變式：
  ① 旗標關＝和今天逐位元相同：已結案案件一封都不寄；進行中案件照舊寄；不寫任何 `onepipe.*` 記號。
  ② 旗標開的第一次每日檢查＝靜默建基準：當下已在提醒期間內的已結案設備只寫「已通知」記號、不寄信；進行中案件照常寄。
  ③ 基準之後：新進入提醒期間的已結案設備才寄（同天數、同收件人、同去重鍵，一台一個門檻只寄一次）；基準日前就過期的永遠不寄。
  ④ 關閉 ⇒ 基準作廢；再開 ⇒ 重新建基準（關閉期間錯過的不補寄）。
  ⑤ 補登的歷史案件（T70 靜音）即使結案也不寄；已結案這一段出任何錯都不影響進行中案件的通知。
"""
import json
from datetime import date, timedelta

import pytest

BASE = "onepipe.warranty_closed_baseline"


def _start_for(days_left: int) -> str:
    """保固起日：12 個月後剛好在 days_left 天後到期。"""
    from helpers.dates import _warranty_expiry
    target = date.today() + timedelta(days=days_left)
    s = target - timedelta(days=365)
    for _ in range(5):
        exp, _left = _warranty_expiry(s.isoformat(), 12)
        if exp == target:
            return s.isoformat()
        s += timedelta(days=1 if exp < target else -1)
    raise AssertionError("找不到保固起日")


def _dev(sn, days_left):
    return {"name": "設備" + sn, "sn": sn, "warrantyStart": _start_for(days_left), "warrantyMonths": 12}


def _quote(quote_no, tag, devices, *, column_tag=True, historical=False):
    import db
    data = {"quoteNo": quote_no, "dealTag": tag, "caseRecord": {"devices": devices}}
    if historical:
        data["approval"] = {"historical": True}
    c = db.get_db()
    try:
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, data_json, created_at, updated_at, deal_tag) "
                  "VALUES (?,?,?,?,?,?,?,?,?)",
                  (quote_no, "已核准", "客戶" + quote_no, "專案", 1000, json.dumps(data, ensure_ascii=False),
                   "2026-01-01T00:00:00", "2026-01-01T00:00:00", tag if column_tag else ""))
        c.commit()
    finally:
        c.close()


def _set_devices(quote_no, devices):
    import db
    c = db.get_db()
    try:
        d = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()["data_json"])
        d["caseRecord"]["devices"] = devices
        c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), quote_no))
        c.commit()
    finally:
        c.close()


def _set_flag(on):
    # P3（ship_device_warranty）把保固去重鍵加上到期日；本檔驗 P0d 的舊鍵格式，所以固定關掉 P3 的開關（P3 的鍵格式由 test_onepipe_p3_device_warranty 驗）
    import db
    from helpers import settings_groups  # noqa: F401
    from helpers import settings_registry as SR
    c = db.get_db()
    try:
        SR.publish("onepipe", {"warranty_closed_notify": 1 if on else 0, "ship_device_warranty": 0}, reason="測試", user="onepipe_p0d_test", conn=c)
        c.commit()
    finally:
        c.close()


def _settings(prefix):
    import db
    c = db.get_db()
    try:
        return {r[0]: r[1] for r in c.execute("SELECT key, value_json FROM system_settings WHERE key LIKE ?", (prefix + "%",)).fetchall()}
    finally:
        c.close()


@pytest.fixture()
def mails(client, monkeypatch):
    """乾淨起點＋攔截寄信：回傳 [(quote_no, device_name, days_left)]。"""
    import db
    from modules.case import case_deadlines as CD
    c = db.get_db()
    try:
        c.execute("DELETE FROM system_settings WHERE key LIKE 'warranty_notif.%' OR key=?", (BASE,))
        c.execute("DELETE FROM quotations WHERE quote_no LIKE 'MQ-P0D-%'")
        c.commit()
    finally:
        c.close()
    _set_flag(False)
    box = []

    def fake(device_name, customer, quote_no, days_left, expiry_iso, owner_username="", out=None, sn=""):
        box.append((quote_no, device_name, days_left))
        return True
    monkeypatch.setattr(CD._en, "_send_warranty_expiry", fake)
    yield box
    c = db.get_db()
    try:
        c.execute("DELETE FROM system_settings WHERE key LIKE 'warranty_notif.%' OR key=?", (BASE,))
        c.execute("DELETE FROM quotations WHERE quote_no LIKE 'MQ-P0D-%'")
        c.commit()
    finally:
        c.close()
    _set_flag(False)


def _run():
    from modules.case import case_deadlines as CD
    CD._check_warranty_expiry()


# ── ① 旗標關＝今天 ───────────────────────────────────────────────
def test_flag_is_registered_as_a_0_1_switch(client):
    from helpers import settings_groups  # noqa: F401
    from helpers import settings_registry as SR
    assert int(SR.get("onepipe", "warranty_closed_notify")) in (0, 1)   # 不釘預設值（預設開關由一條龍統一遷移決定）


def test_flag_off_closed_cases_never_mail_and_open_cases_do(client, mails):
    _quote("MQ-P0D-OPEN", "已成案", [_dev("O1", 20)])
    _quote("MQ-P0D-CLOSED", "已結案", [_dev("C1", 20)])
    _run()
    assert mails == [("MQ-P0D-OPEN", "設備O1", 20)]
    _run()                                                              # 冪等
    assert len(mails) == 1
    assert _settings("onepipe.") == {}, "旗標關不寫任何 onepipe 記號"
    assert set(_settings("warranty_notif.")) == {"warranty_notif.MQ-P0D-OPEN_O1_30"}


# ── ② 首次＝靜默建基準 ───────────────────────────────────────────
def test_first_run_with_flag_on_is_silent_for_closed_but_normal_for_open(client, mails):
    _quote("MQ-P0D-OPEN", "已成案", [_dev("O1", 20)])
    _quote("MQ-P0D-C20", "已結案", [_dev("C20", 20)])
    _quote("MQ-P0D-C3", "已結案", [_dev("C3", 3)])
    _set_flag(True)
    _run()
    assert mails == [("MQ-P0D-OPEN", "設備O1", 20)], "已結案的一封都不寄；進行中的照寄"
    keys = set(_settings("warranty_notif."))
    assert {"warranty_notif.MQ-P0D-C20_C20_30", "warranty_notif.MQ-P0D-C3_C3_7"} <= keys, "靜默記號有寫（與正式寄信同一把去重鍵）"
    b = json.loads(_settings("onepipe.")[BASE])
    assert b["date"] == date.today().isoformat() and b["silenced"] == 2
    _run()
    assert len(mails) == 1, "第二次也不補寄"


# ── ③ 基準之後 ──────────────────────────────────────────────────
def test_after_baseline_only_new_crossings_mail_once(client, mails):
    _quote("MQ-P0D-CLOSED", "已結案", [_dev("A", 20), _dev("B", 90)])        # A 已在期間內（會被靜默）、B 還早
    _set_flag(True)
    _run()
    assert mails == []
    _set_devices("MQ-P0D-CLOSED", [_dev("A", 20), _dev("B", 25)])           # B 進入 30 天提醒期間
    _run()
    assert mails == [("MQ-P0D-CLOSED", "設備B", 25)]
    _run()
    assert len(mails) == 1, "同一台同一門檻只寄一次"
    _set_devices("MQ-P0D-CLOSED", [_dev("A", 20), _dev("B", 5)])            # B 再進 7 天門檻 ⇒ 是另一個門檻，寄一次
    _run()
    assert mails[-1] == ("MQ-P0D-CLOSED", "設備B", 5) and len(mails) == 2


def test_closed_device_already_expired_never_mails(client, mails):
    _quote("MQ-P0D-OLD", "已結案", [_dev("X", -40)])
    _set_flag(True)
    _run()                                                              # 建基準（過期的不記、也不寄）
    _run()
    assert mails == []
    assert not [k for k in _settings("warranty_notif.") if "MQ-P0D-OLD" in k]
    _quote("MQ-P0D-OLD2", "已結案", [_dev("Y", -2)])                          # 基準之後才出現的舊資料：到期日早於基準日 ⇒ 仍不寄
    _run()
    assert mails == []


# ── ④ 關了再開＝重新建基準 ────────────────────────────────────────
def test_turning_off_voids_baseline_and_turning_on_again_rebaselines_silently(client, mails):
    _quote("MQ-P0D-CLOSED", "已結案", [_dev("A", 50)])
    _set_flag(True)
    _run()
    assert BASE in _settings("onepipe.")
    _set_flag(False)
    _set_devices("MQ-P0D-CLOSED", [_dev("A", 50), _dev("NEW", 10)])           # 關閉期間：新設備進入提醒期間
    _run()
    assert json.loads(_settings("onepipe.")[BASE]) == {}, "旗標關 ⇒ 基準作廢"
    assert mails == []
    _set_flag(True)
    _run()
    assert mails == [], "再開 ⇒ 重新靜默建基準，關閉期間錯過的不補寄"
    assert "warranty_notif.MQ-P0D-CLOSED_NEW_30" in _settings("warranty_notif.") or "warranty_notif.MQ-P0D-CLOSED_NEW_7" in _settings("warranty_notif.")


# ── ⑤ 歷史補登、錯誤隔離、判斷來源 ─────────────────────────────────
def test_historical_backfilled_closed_case_is_excluded(client, mails):
    _quote("MQ-P0D-HIST", "已結案", [_dev("H", 90)], historical=True)
    _quote("MQ-P0D-REAL", "已結案", [_dev("R", 90)])
    _set_flag(True)
    _run()
    _set_devices("MQ-P0D-HIST", [_dev("H", 10)])
    _set_devices("MQ-P0D-REAL", [_dev("R", 10)])
    _run()
    assert mails == [("MQ-P0D-REAL", "設備R", 10)]


def test_deal_tag_falls_back_to_data_json_when_column_empty(client, mails):
    _quote("MQ-P0D-COLEMPTY", "已結案", [_dev("Z", 90)], column_tag=False)
    _set_flag(True)
    _run()
    _set_devices("MQ-P0D-COLEMPTY", [_dev("Z", 10)])
    _run()
    assert mails == [("MQ-P0D-COLEMPTY", "設備Z", 10)]


def test_closed_section_failure_does_not_stop_open_case_notices(client, mails, monkeypatch):
    from modules.case import case_deadlines as CD
    _quote("MQ-P0D-OPEN", "已成案", [_dev("O1", 20)])
    _set_flag(True)
    monkeypatch.setattr(CD, "_closed_warranty_rows", lambda conn: (_ for _ in ()).throw(RuntimeError("壞了")))
    _run()
    assert mails == [("MQ-P0D-OPEN", "設備O1", 20)]
    assert BASE not in _settings("onepipe."), "失敗時不留基準（下次重做）"


def test_transient_mail_failure_on_closed_case_leaves_no_mark_and_retries(client, mails, monkeypatch):
    from modules.case import case_deadlines as CD
    _quote("MQ-P0D-CLOSED", "已結案", [_dev("A", 90)])
    _set_flag(True)
    _run()
    _set_devices("MQ-P0D-CLOSED", [_dev("A", 10)])

    def fail(device_name, customer, quote_no, days_left, expiry_iso, owner_username="", out=None, sn=""):
        out["outcome"] = CD._en.SEND_TRANSIENT_FAIL
        return False
    monkeypatch.setattr(CD._en, "_send_warranty_expiry", fail)
    _run()
    assert not [k for k in _settings("warranty_notif.") if "MQ-P0D-CLOSED" in k and k.endswith("_7")]
    monkeypatch.setattr(CD._en, "_send_warranty_expiry", lambda *a, **k: mails.append((a[2], a[0], a[3])) or True)
    _run()
    assert mails == [("MQ-P0D-CLOSED", "設備A", 10)]


def test_calendar_sync_and_open_query_are_untouched():
    """行事曆對帳與進行中案件的查詢不受旗標影響（只多了已結案那一段）。"""
    import inspect
    from modules.case import case_deadlines as CD
    assert "warranty_closed" not in inspect.getsource(CD._sync_warranty_calendar)
    assert "onepipe" not in inspect.getsource(CD._sync_warranty_calendar)
