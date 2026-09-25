# -*- coding: utf-8 -*-
"""升級精靈（CORE-SPEC §9e D4）的 API 閘門。不連正式機、不起 PowerShell。"""
import json
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import deploy_dashboard as dd  # noqa: E402


@pytest.fixture
def client(monkeypatch, tmp_path):
    runs = []
    monkeypatch.setattr(dd, "_run_upgrade_job", lambda *a, **kw: runs.append(a))   # 🔴 不真的執行
    monkeypatch.setattr(dd, "HISTORY_PATH", tmp_path / "history.json")
    monkeypatch.setattr(dd, "DEPLOY_PACKAGES_DIR", tmp_path / "pkgs")
    (tmp_path / "pkgs" / "20260925_new").mkdir(parents=True)
    monkeypatch.setattr(dd, "_last_health", {"at": 0.0, "ok": False})
    monkeypatch.setattr(dd, "_active_job_id", None)
    c = TestClient(dd.app, client=("127.0.0.1", 1))
    c.runs = runs
    c.tmp = tmp_path
    return c


def _body(**over):
    b = {"step": "preflight", "package": "20260925_new", "backupStamp": "20260925_2000",
         "username": "Motrix", "password": "x", "confirm": True}
    b.update(over)
    return b


def _wait(c, n=1):
    for _ in range(50):
        if len(c.runs) >= n:
            return
        time.sleep(0.02)


def test_unknown_step_refused(client):
    assert client.post("/api/upgrade/step", json=_body(step="rm -rf")).status_code == 400


def test_confirm_required(client):
    assert client.post("/api/upgrade/step", json=_body(confirm=False)).status_code == 400


@pytest.mark.parametrize("field,value", [("package", "..\\x"), ("backupStamp", "a b"), ("backupStamp", "../x")])
def test_unsafe_names_refused(client, field, value):
    assert client.post("/api/upgrade/step", json=_body(**{field: value})).status_code == 400
    assert client.runs == []


def test_preflight_runs_with_fixed_step_name(client):
    r = client.post("/api/upgrade/step", json=_body())
    assert r.status_code == 200
    _wait(client)
    job_id, action, cmd, stdin = client.runs[0]
    joined = " ".join(cmd)
    assert action == "upgrade-preflight" and "-Step 'preflight'" in joined and "-Action 'upgrade'" in joined
    assert stdin == "x\n" and "'x'" not in joined          # 密碼只走 stdin，不進指令列


def test_rollback_full_needs_typed_full(client):
    assert client.post("/api/upgrade/step", json=_body(step="rollback-full")).status_code == 400
    assert client.post("/api/upgrade/step", json=_body(step="rollback-full", confirmText="full")).status_code == 400
    assert client.runs == []
    assert client.post("/api/upgrade/step", json=_body(step="rollback-full", confirmText="FULL")).status_code == 200


def test_stop_services_needs_health_or_ack(client):
    r = client.post("/api/upgrade/step", json=_body(step="stop-services"))
    assert r.status_code == 409 and client.runs == []
    r = client.post("/api/upgrade/step", json=_body(step="stop-services", healthAck=True))
    assert r.status_code == 200
    hist = json.loads((client.tmp / "history.json").read_text(encoding="utf-8"))
    assert "升級停服務" in hist[0]["action"] and hist[0]["success"] is False


def test_job_lock_shared_with_deploy(client, monkeypatch):
    monkeypatch.setattr(dd, "_active_job_id", "someone-else")
    assert client.post("/api/upgrade/step", json=_body()).status_code == 409


def test_remote_script_knows_every_step():
    """儀表板的步驟清單與遠端腳本的 ValidateSet 必須一致（少一個 ⇒ 按了必失敗；多一個 ⇒ 沒有人擋）。"""
    src = (Path(dd.TOOLS_DIR) / "_dashboard_remote.ps1").read_text(encoding="utf-8-sig")
    import re
    m = re.search(r'ValidateSet\(""((?:,\s*"[^"]+")+)\)\]\s*\[string\]\$Step', src)
    assert m, "找不到 -Step 的 ValidateSet"
    remote = set(re.findall(r'"([^"]+)"', m.group(1)))
    assert remote == set(dd.UPGRADE_STEPS)
