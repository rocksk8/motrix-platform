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
