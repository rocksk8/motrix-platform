# -*- coding: utf-8 -*-
"""P6 事件匯流排的契約（CUSTOMIZATION-SPEC §6）。"""
import pytest

from core import events


@pytest.fixture(autouse=True)
def isolated():
    saved = events.snapshot()
    events.restore(({}, {}, []))
    yield
    events.restore(saved)


def test_publish_without_subscribers_is_normal():
    events.declare("t.happened", "m_a", 1, ["id"])
    assert events.publish("t.happened", {"id": 1}) == 0
    assert events.recent_failures() == []


def test_subscribers_run_in_order_and_get_a_copy():
    events.declare("t.x", "m_a", 1, ["id"])
    seen = []

    def first(p):
        seen.append(("first", p["id"]))
        p["id"] = 999                               # 改副本不可以影響下一個訂閱者

    events.subscribe("t.x", first, subscriber="m_b")
    events.subscribe("t.x", lambda p: seen.append(("second", p["id"])), subscriber="m_c")
    assert events.publish("t.x", {"id": 7}) == 2
    assert seen == [("first", 7), ("second", 7)]


def test_failing_subscriber_is_isolated_and_recorded():
    events.declare("t.y", "m_a", 1, ["id"])
    got = []

    def boom(_p):
        raise RuntimeError("壞掉")

    events.subscribe("t.y", boom, subscriber="m_bad")
    events.subscribe("t.y", lambda p: got.append(p["id"]), subscriber="m_good")
    assert events.publish("t.y", {"id": 3}) == 1            # 發佈方不收到例外
    assert got == [3]                                       # 後面的訂閱者照樣收到
    f = events.recent_failures()
    assert len(f) == 1 and f[0]["subscriber"] == "m_bad" and "壞掉" in f[0]["error"]


def test_duplicate_subscription_does_not_double_deliver():
    events.declare("t.z", "m_a", 1, [])
    n = []
    h = lambda p: n.append(1)                               # noqa: E731
    events.subscribe("t.z", h, subscriber="m_b")
    events.subscribe("t.z", h, subscriber="m_b")
    events.publish("t.z", {})
    assert n == [1]


def test_conflicting_declarations_are_refused():
    events.declare("t.c", "m_a", 1, ["id"])
    events.declare("t.c", "m_a", 1, ["id"])                 # 完全相同 ⇒ 可以
    with pytest.raises(ValueError):
        events.declare("t.c", "m_other", 1, ["id"])


def test_contract_violations_raise_in_strict_mode(monkeypatch):
    monkeypatch.setenv("MOTRIX_STRICT_DB_GUARDS", "1")
    with pytest.raises(ValueError, match="沒有宣告"):
        events.publish("t.undeclared", {})
    events.declare("t.v", "m_a", 1, ["id", "amount"])
    with pytest.raises(ValueError, match="amount"):
        events.publish("t.v", {"id": 1})


def test_contract_violations_log_and_still_deliver_in_product(monkeypatch, caplog):
    """產品環境：守門記 ERROR 照送，不可以因為契約檢查擋掉業務（守門預設照寫）。"""
    monkeypatch.delenv("MOTRIX_STRICT_DB_GUARDS", raising=False)
    got = []
    events.subscribe("t.loose", lambda p: got.append(p), subscriber="m_b")
    with caplog.at_level("ERROR", logger="motrix.events"):
        assert events.publish("t.loose", {"id": 1}) == 1
    assert got and any("沒有宣告" in r.message for r in caplog.records)


def test_subscribing_before_the_owner_is_loaded_is_allowed():
    """宣告方模組還沒載入（或沒裝）時也可以先訂閱；它不發佈就只是沒有反應。"""
    got = []
    events.subscribe("t.later", lambda p: got.append(p), subscriber="m_b")
    assert events.subscribers("t.later") == ["m_b"]
    events.declare("t.later", "m_a", 1, ["id"])
    events.publish("t.later", {"id": 2})
    assert got == [{"id": 2}]


def test_declarations_are_listed_for_the_capability_catalog():
    events.declare("t.b", "m_a", 2, ["id"], "B 事件")
    events.declare("t.a", "m_a", 1, [])
    assert [(d.name, d.version) for d in events.declarations()] == [("t.a", 1), ("t.b", 2)]


def test_nested_payload_is_not_shared_between_subscribers_or_with_the_publisher():
    # 稽核 D H-M1：dict(payload) 是淺拷貝，巢狀資料會被第一個訂閱者改掉
    events.declare("t.nested", "m_a", 1, ["items"])
    seen = []

    def first(p):
        p["items"].append("被第一個訂閱者加的")
        p["items"][0] = "被改掉"

    events.subscribe("t.nested", first, subscriber="m_b")
    events.subscribe("t.nested", lambda p: seen.append(list(p["items"])), subscriber="m_c")
    original = {"items": ["原本"]}
    events.publish("t.nested", original)
    assert seen == [["原本"]]
    assert original == {"items": ["原本"]}                 # 發佈方手上的物件也不可以被改


def test_publishing_inside_an_open_write_transaction_is_refused(monkeypatch, tmp_path):
    # 稽核 D H-S1：規格「發佈在 commit 之後」要有守門
    import sqlite3
    from core import txn
    monkeypatch.setenv("MOTRIX_STRICT_DB_GUARDS", "1")
    events.declare("t.tx", "m_a", 1, ["id"])
    conn = sqlite3.connect(tmp_path / "x.db")
    conn.execute("CREATE TABLE t (a)")
    txn.begin_write(conn)
    with pytest.raises(ValueError, match="commit 之後"):
        events.publish("t.tx", {"id": 1})
    conn.commit()
    assert events.publish("t.tx", {"id": 1}) == 0            # commit 之後照常
    conn.close()


def test_publishing_in_another_threads_transaction_is_not_blocked(monkeypatch, tmp_path):
    # 反向控制：別條執行緒開著交易，不影響這條執行緒發佈
    import sqlite3
    import threading
    from core import txn
    monkeypatch.setenv("MOTRIX_STRICT_DB_GUARDS", "1")
    events.declare("t.tx2", "m_a", 1, ["id"])
    conn = sqlite3.connect(tmp_path / "y.db", check_same_thread=False)
    conn.execute("CREATE TABLE t (a)")
    t = threading.Thread(target=txn.begin_write, args=(conn,))
    t.start(); t.join()
    assert events.publish("t.tx2", {"id": 1}) == 0
    conn.rollback(); conn.close()


def test_non_json_payload_violates_the_contract(monkeypatch):
    monkeypatch.setenv("MOTRIX_STRICT_DB_GUARDS", "1")
    events.declare("t.obj", "m_a", 1, ["id"])
    with pytest.raises(ValueError, match="JSON"):
        events.publish("t.obj", {"id": object()})


def test_slow_subscriber_is_logged(caplog, monkeypatch):
    # 稽核 D H-S2：訂閱者同步執行，慢的要看得到
    monkeypatch.setattr(events, "_SLOW_SUBSCRIBER_SECONDS", 0.01)
    import time as _t
    events.declare("t.slow", "m_a", 1, ["id"])
    events.subscribe("t.slow", lambda p: _t.sleep(0.05), subscriber="m_slow")
    with caplog.at_level("WARNING", logger="motrix.events"):
        events.publish("t.slow", {"id": 1})
    assert any("m_slow" in r.getMessage() and "秒" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("payload", [{"id": (1, 2)}, {"id": {1: "a"}}])
def test_values_that_change_in_a_json_round_trip_violate_the_contract(monkeypatch, payload):
    # 稽核 D N-2：tuple→list、{1:..}→{"1":..} 不報錯卻改了內容
    monkeypatch.setenv("MOTRIX_STRICT_DB_GUARDS", "1")
    events.declare("t.rt", "m_a", 1, ["id"])
    with pytest.raises(ValueError, match="JSON 來回"):
        events.publish("t.rt", payload)
