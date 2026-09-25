# -*- coding: utf-8 -*-
"""部署儀表板的閘門（CORE-SPEC §9e D2／D6）。絕不觸發真的打包或對正式機連線。"""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import deploy_dashboard as dd  # noqa: E402


@pytest.fixture
def client(monkeypatch, tmp_path):
    started = []
    # 🔴 打包 job 換成記錄器：測試永遠不可以真的跑 build_deploy_package.ps1
    monkeypatch.setattr(dd, "_run_job", lambda *a, **kw: started.append(a))
    monkeypatch.setattr(dd, "LAST_FULL_PATH", tmp_path / ".last_full.json")
    monkeypatch.setattr(dd, "HISTORY_PATH", tmp_path / "history.json")   # 不寫真的歷史檔
    monkeypatch.setattr(dd, "_head_full_sha", lambda: "a" * 40)
    # 正式機查詢一律換掉：不連線
    monkeypatch.setattr(dd, "_check_prod_status", lambda: {"healthy": None, "deployed": {}})
    c = TestClient(dd.app, client=("127.0.0.1", 1))
    c.started = started
    c.lf = tmp_path / ".last_full.json"
    return c


def _wait(c):
    import time
    for _ in range(50):
        if c.started:
            return
        time.sleep(0.02)


def test_build_is_blocked_without_green_full(client):
    r = client.post("/api/build", json={})
    assert r.status_code == 409 and r.json()["gate"]["state"] == "missing"
    assert client.started == []


def test_build_blocked_when_full_is_for_another_commit(client):
    client.lf.write_text(json.dumps({"commit": "b" * 40, "ok": True}), encoding="utf-8")
    r = client.post("/api/build", json={})
    assert r.status_code == 409 and r.json()["gate"]["state"] == "other_commit"


def test_build_allowed_with_green_full(client):
    client.lf.write_text(json.dumps({"commit": "a" * 40, "ok": True}), encoding="utf-8")
    r = client.post("/api/build", json={})
    assert r.status_code == 200 and "jobId" in r.json()
    _wait(client)
    assert len(client.started) == 1


def test_override_without_reason_is_refused(client):
    r = client.post("/api/build", json={"overrideTestGate": True, "overrideReason": " "})
    assert r.status_code == 400 and client.started == []


def test_override_with_reason_builds_and_leaves_a_trace(client, tmp_path):
    r = client.post("/api/build", json={"overrideTestGate": True, "overrideReason": "緊急修補正式機登入錯誤"})
    assert r.status_code == 200
    _wait(client)
    assert len(client.started) == 1
    hist = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
    assert "略過測試閘門" in hist[0]["action"] and "緊急修補正式機登入錯誤" in hist[0]["action"]
    assert hist[0]["success"] is False       # 在歷史上顯示成紅，不可以看起來像一般成功的動作


def test_gate_endpoint_reports_state(client):
    assert client.get("/api/build-gate").json()["state"] == "missing"


def test_module_changes_without_prod_base_says_why(client):
    r = client.get("/api/module-changes", params={"head": "a" * 40})
    assert r.status_code == 400 and "正式機已部署版本查不到" in r.json()["detail"]


def test_module_changes_rejects_non_commit_input(client):
    r = client.get("/api/module-changes", params={"base": "HEAD~1", "head": "a" * 40})
    assert r.status_code == 400 and "不是 commit" in r.json()["detail"]


def test_module_changes_rejects_path_like_package(client):
    r = client.get("/api/module-changes", params={"package": "..\\x"})
    assert r.status_code == 400
