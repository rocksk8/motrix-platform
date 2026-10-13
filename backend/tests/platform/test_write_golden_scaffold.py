# -*- coding: utf-8 -*-
"""U0b-T2/T3 寫入金標骨架的自測（用小型 FastAPI app，不碰資料庫、不跑全站）。"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from tests.platform import _write_golden as WG


class Body(BaseModel):
    name: str


def _app(leak=False):
    app = FastAPI()

    @app.post("/api/things")
    def _create(b: Body):
        out = {"id": 1, "name": b.name, "created_at": "t"}
        if leak:
            out["owner_unit_id"] = 1
        return out

    @app.put("/api/things/1")
    def _upd(b: Body):
        return {"ok": True}
    return TestClient(app)


def test_valid_payload_records_success_keys():
    rec = WG.record_write(_app(), {}, "POST", "/api/things", {"name": "a"})
    assert rec["s"] == 200 and rec["k"] == ["created_at", "id", "name"]


def test_invalid_payload_is_rejected_not_recorded_as_baseline():     # 風險 #2：4xx 錯誤鍵集不得被記成金標
    with pytest.raises(WG.GoldenError):
        WG.record_write(_app(), {}, "POST", "/api/things", {"nope": 1})


def test_positive_control_internal_key_leak_is_detected():
    assert WG.leaked(WG.record_write(_app(leak=True), {}, "POST", "/api/things", {"name": "a"})) == ["owner_unit_id"]
    assert WG.leaked(WG.record_write(_app(), {}, "POST", "/api/things", {"name": "a"})) == []


def test_key_delta_reports_both_directions():
    d = WG.key_delta({"k": ["a", "b"]}, {"k": ["b", "c"]})
    assert d == {"removed": ["a"], "added": ["c"]}
    assert WG.key_delta({"k": []}, {"k": []}) == {"removed": [], "added": []}


def test_uncovered_lists_write_routes_without_case_or_waiver():
    inv = {"POST /api/a": {"w": True}, "PUT /api/b": {"w": True}, "GET /api/c": {"w": False}, "POST /x": {"w": True}}
    assert WG.uncovered(inv, ["POST /api/a"], []) == ["PUT /api/b"]
    assert WG.uncovered(inv, ["POST /api/a"], ["PUT /api/b"]) == []
