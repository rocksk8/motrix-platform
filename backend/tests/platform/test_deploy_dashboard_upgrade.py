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
    monkeypatch.setattr(dd, "UPGRADE_SESSION_PATH", tmp_path / "upgrade_session.json")
    # 進行中的一輪升級（S-U06：時間戳由伺服器保存）
    (tmp_path / "upgrade_session.json").write_text(json.dumps(
        {"stamp": "20260925_2000", "package": "20260925_new", "steps": {}, "closedAt": None}), encoding="utf-8")
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
    job_id, action, cmd, stdin, stamp = client.runs[0]
    assert stamp == "20260925_2000"
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


# ── S-U06：這一輪升級的紀錄在伺服器端 ─────────────────────────────────────

def test_step_with_a_stamp_not_in_the_current_session_is_refused(client):
    r = client.post("/api/upgrade/step", json=_body(backupStamp="20260101_0000"))
    assert r.status_code == 409 and client.runs == []


def test_step_without_any_session_is_refused(client):
    (client.tmp / "upgrade_session.json").unlink()
    assert client.post("/api/upgrade/step", json=_body()).status_code == 409


def test_corrupt_session_file_is_not_treated_as_none(client):
    (client.tmp / "upgrade_session.json").write_text("{bad", encoding="utf-8")
    assert client.post("/api/upgrade/step", json=_body()).status_code == 409
    assert client.post("/api/upgrade/session", json={"package": "20260925_new"}).status_code == 409


def test_session_survives_reload_and_only_one_at_a_time(client):
    assert client.get("/api/upgrade/session").json()["stamp"] == "20260925_2000"
    r = client.post("/api/upgrade/session", json={"package": "20260925_new"})
    assert r.status_code == 409 and r.json()["session"]["stamp"] == "20260925_2000"


def test_close_needs_reason_then_new_session_gets_server_stamp(client):
    assert client.post("/api/upgrade/session/close", json={"reason": ""}).status_code == 400
    assert client.post("/api/upgrade/session/close", json={"reason": "演練結束，正式日另開"}).status_code == 200
    s = client.post("/api/upgrade/session", json={"package": "20260925_new"}).json()
    assert s["stamp"] != "20260925_2000" and s["closedAt"] is None


def test_step_results_are_recorded_in_the_session(client):
    dd._record_step("20260925_2000", "backup", True)
    assert client.get("/api/upgrade/session").json()["steps"]["backup"]["ok"] is True
    dd._record_step("OTHER", "convert", True)          # 別一輪的結果不可以寫進這一輪
    assert "convert" not in client.get("/api/upgrade/session").json()["steps"]


def test_remote_script_knows_every_step():
    """儀表板的步驟清單與遠端腳本的 ValidateSet 必須一致（少一個 ⇒ 按了必失敗；多一個 ⇒ 沒有人擋）。"""
    src = (Path(dd.TOOLS_DIR) / "_dashboard_remote.ps1").read_text(encoding="utf-8-sig")
    import re
    m = re.search(r'ValidateSet\(""((?:,\s*"[^"]+")+)\)\]\s*\[string\]\$Step', src)
    assert m, "找不到 -Step 的 ValidateSet"
    remote = set(re.findall(r'"([^"]+)"', m.group(1)))
    assert remote == set(dd.UPGRADE_STEPS)
