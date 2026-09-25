"""2026-09-10：案件「專案期間」超期通知（f8198e9 上線，同日補測試）。

這批功能上線時沒有任何測試。這裡釘住三件事：
  1. 超期才寄、未超期不寄
  2. 同一個 7 天區間只寄一次，跨區間才會再寄
  3. guard key 會被收斂——原本只寫不刪，案件結案/改期之後舊 key 永遠留著，
     一個超期兩年的案件自己就會累積約 104 列 system_settings。這個專案已經
     為同一種模式付過代價（module_versions 曾長到 626,725 列 / 270MB）。
"""
import json
from datetime import date, timedelta

import pytest


def _make_case(quote_no, end_date, deal_tag="已成案"):
    import db
    conn = db.get_db()
    try:
        data = {"caseRecord": {"projectTimeline": {
            "startDate": "2026-01-01", "endDate": end_date, "status": "on_track"}}}
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, "
            "total, pretax, data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "超期測試專案", 1000, 952,
             json.dumps(data, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", deal_tag))
        conn.commit()
    finally:
        conn.close()


def _guard_keys():
    import db
    conn = db.get_db()
    try:
        return sorted(r["key"] for r in conn.execute(
            "SELECT key FROM system_settings WHERE key LIKE 'caseproj_notif.%'").fetchall())
    finally:
        conn.close()


@pytest.fixture()
def sent(monkeypatch):
    """攔截寄信，只記錄呼叫參數——這裡測的是排程判斷邏輯，不是郵件內容。"""
    calls = []
    import helpers.case_deadlines as dt  # 2026-09-26 自 routers/daily_tasks 搬出（M12 搬遷前置）
    monkeypatch.setattr(dt, "notify_case_project_overdue",
                        lambda *a, **kw: calls.append(a))
    return calls


def _run():
    import helpers.case_deadlines as dt  # 2026-09-26 自 routers/daily_tasks 搬出（M12 搬遷前置）
    dt._check_case_project_timeline_deadline()


def test_not_overdue_is_not_notified(client, sent):
    _make_case("MQ-OD-001", (date.today() + timedelta(days=5)).isoformat())
    _run()
    assert sent == []
    assert _guard_keys() == []


def test_overdue_notifies_once_per_bucket(client, sent):
    _make_case("MQ-OD-002", (date.today() - timedelta(days=3)).isoformat())
    _run()
    assert len(sent) == 1, "超期當天應寄一次"
    assert sent[0][0] == "MQ-OD-002"
    assert sent[0][4] == 3, "days_overdue 應為 3"
    keys = _guard_keys()
    assert keys == ["caseproj_notif.MQ-OD-002.0"], keys

    _run()
    assert len(sent) == 1, "同一個 7 天區間內重跑不應重複寄"


def test_next_bucket_notifies_again(client, sent):
    """超期第 8 天落在 bucket 1，應該再寄一次。"""
    _make_case("MQ-OD-003", (date.today() - timedelta(days=8)).isoformat())
    _run()
    assert len(sent) == 1
    assert _guard_keys() == ["caseproj_notif.MQ-OD-003.1"], "bucket 應為 1（8 // 7）"


def test_closed_case_is_skipped_and_guard_keys_pruned(client, sent):
    """案件結案後不再寄，且先前留下的 guard key 會被收斂掉。"""
    import db
    _make_case("MQ-OD-004", (date.today() - timedelta(days=2)).isoformat())
    _run()
    assert len(sent) == 1
    assert _guard_keys() == ["caseproj_notif.MQ-OD-004.0"]

    conn = db.get_db()
    try:
        conn.execute("UPDATE quotations SET deal_tag='已結案' WHERE quote_no=?", ("MQ-OD-004",))
        conn.commit()
    finally:
        conn.close()

    _run()
    assert len(sent) == 1, "已結案不應再寄"
    assert _guard_keys() == [], "結案後舊 guard key 應被清掉，不該無限累積"


def test_stale_buckets_are_pruned_for_still_overdue_case(client, sent):
    """仍在超期的案件也只留當前區間那一列，更早的區間永遠不會再被查詢。"""
    import db
    from helpers.settings import _set_setting
    _make_case("MQ-OD-005", (date.today() - timedelta(days=20)).isoformat())
    for old_bucket in (0, 1):
        _set_setting(f"caseproj_notif.MQ-OD-005.{old_bucket}", "2026-01-01")

    _run()
    assert _guard_keys() == ["caseproj_notif.MQ-OD-005.2"], "只該留 bucket 2（20 // 7）"
