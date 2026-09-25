# -*- coding: utf-8 -*-
"""部署前健康檢查（CORE-SPEC §9e D1）：判斷規則與部署閘門。不連正式機、不觸發部署。"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import deploy_dashboard as dd  # noqa: E402
import deploy_insights as di  # noqa: E402

NOW = datetime(2026, 9, 25, 20, 0, 0)


def _facts(**over):
    f = {"alertActive": False, "alertText": "", "latestDbBackup": {"name": "x.db", "at": (NOW - timedelta(hours=18)).isoformat()},
         "disks": [{"name": "C", "freeGB": 120}], "installDrive": "C", "port666Listen": 1, "devMarkers": [], "piiFolders": ["H:\\我的雲端硬碟\\系統存檔_個資"]}
    f.update(over)
    return f


def test_healthy():
    v = di.evaluate_health(_facts(), NOW)
    assert v["ok"] and v["problems"] == [] and v["warnings"] == []


@pytest.mark.parametrize("over,needle", [
    ({"alertActive": True, "alertText": "雲端路徑不存在"}, "備份告警"),
    ({"latestDbBackup": None}, "找不到任何本機資料庫備份"),
    ({"latestDbBackup": {"name": "x", "at": (NOW - timedelta(hours=31)).isoformat()}}, "31 小時前"),
    ({"latestDbBackup": {"name": "x", "at": "昨天"}}, "讀不懂"),
    ({"disks": [{"name": "C", "freeGB": 3}]}, "低於 10 GB"),
    ({"disks": []}, "拿不到正式機 C: 的剩餘空間"),
    ({"port666Listen": 0}, "沒有服務在監聽"),
    ({"devMarkers": [".no_email_send"]}, "停止寄信"),
    ({"devMarkers": [".no_cloud_archive"]}, "停止雲端備份"),
])
def test_each_problem_blocks(over, needle):
    v = di.evaluate_health(_facts(**over), NOW)
    assert not v["ok"] and any(needle in p for p in v["problems"]), v


def test_disk_check_follows_the_install_drive_not_c():
    """稽核 A-2：裝在 D: 而 D: 快滿，原本只看 C: ⇒ 放行（實測 D: 0.1 GB 仍 ok）。"""
    v = di.evaluate_health(_facts(installDrive="D", disks=[{"name": "C", "freeGB": 500}, {"name": "D", "freeGB": 0.1}]), NOW)
    assert not v["ok"] and any("D: 剩餘空間 0.1 GB" in p for p in v["problems"])


def test_install_drive_missing_from_disk_list_blocks():
    v = di.evaluate_health(_facts(installDrive="D", disks=[{"name": "C", "freeGB": 500}]), NOW)
    assert not v["ok"] and any("拿不到正式機 D:" in p for p in v["problems"])


def test_unknown_install_drive_blocks():
    v = di.evaluate_health(_facts(installDrive=None), NOW)
    assert not v["ok"] and any("磁碟代號" in p for p in v["problems"])


def test_rewritten_done_cannot_make_an_old_snapshot_look_fresh():
    """稽核 C-1：舊日期資料夾的 .done 被重寫成今天，新鮮度仍以資料夾日期為上限。"""
    lb = {"name": "2026-09-20", "at": (NOW - timedelta(hours=1)).isoformat()}
    v = di.evaluate_health(_facts(latestDbBackup=lb), NOW)
    assert not v["ok"] and any("小時前" in p for p in v["problems"])


def test_missing_pii_folder_only_warns():
    v = di.evaluate_health(_facts(piiFolders=[]), NOW)
    assert v["ok"] and any("系統存檔_個資" in w for w in v["warnings"])


def test_empty_facts_is_not_healthy():
    assert di.evaluate_health({}, NOW)["ok"] is False


@pytest.fixture
def client(monkeypatch, tmp_path):
    started = []
    monkeypatch.setattr(dd, "_run_job", lambda *a, **kw: started.append(a))       # 🔴 不真的部署
    monkeypatch.setattr(dd, "HISTORY_PATH", tmp_path / "history.json")
    monkeypatch.setattr(dd, "DEPLOY_PACKAGES_DIR", tmp_path / "pkgs")
    (tmp_path / "pkgs" / "20260925_x").mkdir(parents=True)
    monkeypatch.setattr(dd, "_last_health", {"at": 0.0, "ok": False})
    monkeypatch.setattr(dd, "_active_job_id", None)
    c = TestClient(dd.app, client=("127.0.0.1", 1))
    c.started = started
    return c


BODY = {"package": "20260925_x", "username": "Motrix", "password": "x", "confirm": True}


def test_deploy_blocked_without_recent_passing_health(client):
    r = client.post("/api/deploy", json=BODY)
    assert r.status_code == 409 and "健康檢查" in r.json()["detail"]
    assert client.started == []


def test_health_endpoint_then_deploy_allowed(client, monkeypatch):
    monkeypatch.setattr(dd, "_run_remote_json", lambda *a, **kw: (_facts(latestDbBackup={"name": "x", "at": datetime.now().isoformat()}), None))
    h = client.post("/api/prod-health", json={"username": "Motrix", "password": "x"})
    assert h.status_code == 200 and h.json()["ok"] is True
    r = client.post("/api/deploy", json=BODY)
    assert r.status_code == 200


def test_failed_health_still_blocks(client, monkeypatch):
    monkeypatch.setattr(dd, "_run_remote_json", lambda *a, **kw: (_facts(port666Listen=0), None))
    assert client.post("/api/prod-health", json={"username": "M", "password": "x"}).json()["ok"] is False
    assert client.post("/api/deploy", json=BODY).status_code == 409


def test_ack_allows_and_leaves_trace(client, tmp_path):
    import json
    r = client.post("/api/deploy", json={**BODY, "healthAck": True})
    assert r.status_code == 200
    hist = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
    assert "未通過健康檢查但已人工確認" in hist[0]["action"] and hist[0]["success"] is False


def test_stale_health_expires(client, monkeypatch):
    import time
    monkeypatch.setattr(dd, "_last_health", {"at": time.time() - dd.HEALTH_VALID_SECONDS - 5, "ok": True})
    assert client.post("/api/deploy", json=BODY).status_code == 409
