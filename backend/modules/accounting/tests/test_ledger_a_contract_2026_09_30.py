# -*- coding: utf-8 -*-
"""總帳 A · `gl.events` 契約 v1（proposal-gl/02-events-engine.md §2）：事件驗證、內容雜湊、向多提供者收集並明說缺席。

守門的核心：**缺席與壞掉都要說出來，不可與「0 筆」長得一樣**；一個提供者壞了不拖垮其他來源；無效事件被列出、不消失。
正對照：合格事件必出現且帶 content_hash。反向控制：拿掉提供者／塞壞事件／提供者丟例外，各自產生對應的說明。
"""
import copy

import pytest

from core import registry
from modules.accounting.ledger import contract as C

GOOD = {
    "source_type": "quotation_invoice", "source_key": "Q1::AB12345678", "event_code": "E01", "event_date": "2026-10-05",
    "doc_no": "AB12345678", "case_no": "Q1", "party": {"key": "12345678", "name": "甲"}, "tax_code": "OUT-5",
    "lines": [{"role": "AR", "side": "D", "amount": 10500}, {"role": "REV_SALES", "side": "C", "amount": 10000},
              {"role": "OUTPUT_TAX", "side": "C", "amount": 500}],
}


def _ev(**kw):
    e = copy.deepcopy(GOOD)
    e.update(kw)
    return e


@pytest.fixture
def prov(monkeypatch):
    """乾淨的提供者登記（只保留本題登記的）。"""
    monkeypatch.setattr(registry, "_LEGACY_PROVIDERS", {})
    monkeypatch.setattr(registry, "_LOADED", {})

    def add(name, fn):
        registry._LEGACY_PROVIDERS[(C.CAPABILITY, name)] = fn
    return add


# ── 驗證 ─────────────────────────────────────────────────────────────────

def test_good_event_passes():
    assert C.validate_event(GOOD) == []


@pytest.mark.parametrize("mutate,expect", [
    (lambda e: e.pop("source_key"), "source_key"),
    (lambda e: e.update(event_date="2026-13-01"), "event_date"),
    (lambda e: e.update(event_date="2026/10/05"), "event_date"),
    (lambda e: e.update(mode="weird"), "mode"),
    (lambda e: e.update(lines=[]), "lines"),
    (lambda e: e["lines"][0].update(role="NO_SUCH"), "未登記"),
    (lambda e: e["lines"][0].update(side="X"), "side"),
    (lambda e: e["lines"][0].update(amount=10500.5), "非負整數"),
    (lambda e: e["lines"][0].update(amount="10500"), "非負整數"),
    (lambda e: e["lines"][0].update(amount=-1), "非負整數"),
    (lambda e: e["lines"][0].update(amount=True), "非負整數"),
    (lambda e: e["lines"][0].update(amount=10400), "借貸不相等"),
])
def test_bad_events_are_rejected_with_a_reason(mutate, expect):
    e = copy.deepcopy(GOOD)
    mutate(e)
    probs = C.validate_event(e)
    assert probs and any(expect in p for p in probs), probs


def test_non_object_and_all_zero_events_are_rejected():
    assert C.validate_event("x") and C.validate_event(None)
    z = _ev(lines=[{"role": "AR", "side": "D", "amount": 0}, {"role": "REV_SALES", "side": "C", "amount": 0}])
    assert any("全部是 0" in p for p in C.validate_event(z))


# ── 內容雜湊 ─────────────────────────────────────────────────────────────

def test_hash_ignores_meta_order_and_memo_but_not_content():
    h = C.canonical_hash(GOOD)
    shuffled = _ev(lines=list(reversed(GOOD["lines"])), meta={"note": "診斷"})
    shuffled["lines"][0]["memo"] = "說明文字不算內容"
    assert C.canonical_hash(shuffled) == h
    for change in (_ev(event_date="2026-10-06"), _ev(case_no="Q2"), _ev(tax_code="OUT-0"),
                   _ev(party={"key": "99999999"})):
        assert C.canonical_hash(change) != h
    amt = copy.deepcopy(GOOD)
    amt["lines"][1]["amount"] = 10001
    amt["lines"][0]["amount"] = 10501
    assert C.canonical_hash(amt) != h                      # 金額變了＝內容變了（drift 偵測的根據）


# ── 收集 ─────────────────────────────────────────────────────────────────

def test_positive_control_valid_event_is_collected_with_hash(prov):
    prov("arap", lambda s, e, changed_since="": {"events": [GOOD]})
    r = C.collect("2026-10-01", "2026-10-31")
    assert r["sources"]["arap"] == "ok" and len(r["events"]) == 1
    ev = r["events"][0]
    assert ev["source_module"] == "arap" and ev["mode"] == "snapshot" and len(ev["content_hash"]) == 64
    assert not r["invalid"]


def test_absent_sources_are_named_not_silent(prov, monkeypatch):
    r = C.collect("2026-10-01", "2026-10-31")
    assert r["events"] == [] and r["notices"], "沒有任何提供者時要有說明，不可只是空清單"
    assert all(v == "not_installed" for v in r["sources"].values())
    assert any("arap 模組未安裝" in n for n in r["notices"])
    # 模組已載入但還沒提供 gl.events ＝「尚未接入」，措辭不同
    monkeypatch.setattr(registry, "is_loaded", lambda k: k == "supply")
    r = C.collect("2026-10-01", "2026-10-31")
    assert r["sources"]["supply"] == "not_connected" and any("supply 尚未接入" in n for n in r["notices"])
    assert r["sources"]["arap"] == "not_installed"


def test_a_failing_provider_does_not_take_down_the_others(prov):
    def boom(s, e, changed_since=""):
        raise RuntimeError("壞了")
    prov("arap", boom)
    prov("supply", lambda s, e, changed_since="": {"events": [_ev(source_key="S1", source_type="stock_batch")]})
    r = C.collect("2026-10-01", "2026-10-31")
    assert r["sources"]["arap"] == "error" and r["sources"]["supply"] == "ok"
    assert len(r["events"]) == 1
    assert any("arap" in n and "RuntimeError" in n for n in r["notices"])


def test_invalid_events_are_listed_not_dropped_and_do_not_block_good_ones(prov):
    bad = _ev(source_key="BAD")
    bad["lines"][0]["amount"] = 1
    prov("arap", lambda s, e, changed_since="": {"events": [GOOD, bad, "垃圾"]})
    r = C.collect("2026-10-01", "2026-10-31")
    assert len(r["events"]) == 1 and len(r["invalid"]) == 2
    assert {i["source"] for i in r["invalid"]} == {"arap"} and all(i["problems"] for i in r["invalid"])


def test_duplicate_source_events_are_flagged(prov):
    prov("arap", lambda s, e, changed_since="": {"events": [GOOD, _ev()]})
    r = C.collect("2026-10-01", "2026-10-31")
    assert len(r["events"]) == 1 and any("重複" in "".join(i["problems"]) for i in r["invalid"])


def test_provider_notice_is_passed_through(prov):
    prov("arap", lambda s, e, changed_since="": {"events": [], "notice": "案件模組未安裝：不含收款"})
    r = C.collect("2026-10-01", "2026-10-31")
    assert any("arap：案件模組未安裝" in n for n in r["notices"])


def test_changed_since_is_passed_to_providers(prov):
    seen = {}

    def fn(s, e, changed_since=""):
        seen["cs"] = changed_since
        return {"events": []}
    prov("arap", fn)
    C.collect("2026-10-01", "2026-10-31", changed_since="2026-10-15T00:00:00")
    assert seen["cs"] == "2026-10-15T00:00:00"


def test_every_default_role_can_be_used_by_a_source():
    assert C.known_roles() and "AR" in C.known_roles() and "OUTPUT_TAX" in C.known_roles()


# ── API ─────────────────────────────────────────────────────────────────

def test_api_preview_reports_source_status_and_permissions(client, make_user):
    u, p = make_user(username="gl_a_events", role="superadmin", modules=["finance"])
    hdr = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}
    n, q = make_user(username="gl_a_events_none", role="staff", modules=[])
    none = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": n, "password": q}).json()["token"]}
    url = "/api/ledger/events/preview?start=2026-10-01&end=2026-10-31"
    assert client.get(url, headers=none).status_code == 403
    r = client.get(url, headers=hdr)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["contract_version"] == 1 and body["count"] == 0 and body["notices"], "A 階段所有來源都還沒接入：必須明說，不可只回空清單"
    assert set(body["sources"]) == set(C.SOURCES)
    assert client.get("/api/ledger/events/preview?start=2026-10-31&end=2026-10-01", headers=hdr).status_code == 400
    assert client.get("/api/ledger/events/preview?start=x&end=y", headers=hdr).status_code == 400
