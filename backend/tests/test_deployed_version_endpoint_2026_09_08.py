"""GET /api/system/deployed-version（2026-09-08 新增，見 routers/auth.py）。
供本機部署儀表板工具（backend/tools/deploy_dashboard.py）查詢正式機目前
部署版本用，公開端點、無需登入。"""
import json


def test_returns_empty_object_when_marker_file_missing(client, tmp_path, monkeypatch):
    import routers.auth as auth_module
    monkeypatch.setattr(auth_module, "_DEPLOYED_MARKER_PATH", str(tmp_path / "does_not_exist.json"))

    r = client.get("/api/system/deployed-version")
    assert r.status_code == 200, r.text
    assert r.json() == {}


def test_returns_marker_file_content_when_present(client, tmp_path, monkeypatch):
    import routers.auth as auth_module
    marker_path = tmp_path / ".deployed_commit.json"
    payload = {
        "commit": "abc123def456",
        "commit_short": "abc123d",
        "branch": "master",
        "applied_at": "2026-09-08 12:00:00",
        "built_at": "2026-09-08 11:00:00",
    }
    marker_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(auth_module, "_DEPLOYED_MARKER_PATH", str(marker_path))

    r = client.get("/api/system/deployed-version")
    assert r.status_code == 200, r.text
    assert r.json() == payload
