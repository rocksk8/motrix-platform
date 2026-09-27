# -*- coding: utf-8 -*-
"""部署儀表板：正式機「套用更新」與開發機 prod-status 讀交付結果（UPDATE-DELIVERY §3／§4；A，2026-09-28）。

TestClient 打儀表板 API；不起 PowerShell（delivery._run_powershell 換成假執行器，照 §9.2 寫 result.json、印 ::RESULT::）、
不連正式機（prod-status 的 requests 換掉）、不碰真的雲端資料夾（交付資料夾、安裝目錄、staging 都是 tmp）。
帳密驗證（_verify_superadmin 打本機 ERP）在這裡換掉；e2e 那一題打真的 ERP（live_server）。
"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))
import delivery as D  # noqa: E402
import deploy_dashboard as dd  # noqa: E402

COMMIT = "0123abcd" + "e" * 32
PS1 = '# apply\r\n$ApplyScriptVersion = "2026-09-28a"\r\nWrite-Host "x"\r\n'


def _keys():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    k = Ed25519PrivateKey.generate()
    return (k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()),
            k.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))


def make_package(tmp, manifest_entries=()):
    p = tmp / "pkg"
    (p / "backend" / "tools").mkdir(parents=True)
    (p / "deploy_manifest.json").write_text(json.dumps({"commit": COMMIT, "product": "full", "built_at": "2026-09-28 01:00:00"}),
                                            encoding="utf-8")
    (p / "backend" / "tools" / "apply_update.ps1").write_bytes(PS1.encode("utf-8"))
    (p / "backend" / "tools" / "apply_update.version.json").write_text(
        json.dumps({"version": "2026-09-28a", "sha256": D.ps1_digest(PS1.encode("utf-8"))}), encoding="utf-8")
    (p / "backend" / "version_manifest.json").write_text(json.dumps(list(manifest_entries), ensure_ascii=False), encoding="utf-8")
    return p


def make_install(tmp):
    root = tmp / "install"
    (root / "backend" / "tools").mkdir(parents=True)
    (root / "backend" / ".deployed_commit.json").write_text(json.dumps({"commit": "f" * 40, "built_at": "2026-09-27 22:00:00"}),
                                                            encoding="utf-8")
    (root / "backend" / "db.py").write_text("CURRENT_VERSION = 116\n", encoding="utf-8")
    (root / "backend" / "version_manifest.json").write_text(json.dumps([{"module": "舊", "version": "2026-09-27a"}]),
                                                            encoding="utf-8")
    return root


def fake_run(install, status="success", rolled_back="applied", service="up", code=0):
    def run(cmd):
        logs = install / "backend" / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "apply_update_20260928_031500.result.json").write_text(json.dumps({
            "protocol": 2, "status": status, "rolled_back": rolled_back, "service": service, "exit": code,
            "script": "apply_update", "script_version": "2026-09-28a", "timestamp": "20260928_031500",
            "package": cmd[-2], "commit": COMMIT, "started_at": "2026-09-28 03:15:00", "finished_at": "2026-09-28 03:16:00"}),
            encoding="utf-8")
        return code, "::PROTOCOL:: v=2\n::RESULT:: v=2 status=%s rolled_back=%s service=%s exit=%d\n" % (
            status, rolled_back, service, code)
    return run


@pytest.fixture()
def env(tmp_path, monkeypatch):
    priv, pub = _keys()
    root = tmp_path / "交付"
    root.mkdir()
    install = make_install(tmp_path)
    monkeypatch.setattr(D, "DELIVERY_PUBKEY_PEM", pub)
    monkeypatch.setattr(D, "_default_resolver", lambda: str(root))
    monkeypatch.setattr(D, "verify_package_cmd", lambda *a: [sys.executable, "-c", "pass"])   # 已安裝的 verify_package：這裡只驗接線
    monkeypatch.setattr(D, "_run_powershell", fake_run(install))
    monkeypatch.setattr(dd, "DELIVERY_INSTALL_ROOT", install)
    monkeypatch.setattr(dd, "DELIVERY_STAGING_ROOT", tmp_path / "staging")
    monkeypatch.setattr(dd, "_delivery_state", {"prepared": {}, "running": False, "last": None})
    monkeypatch.setattr(dd, "_verify_superadmin", lambda u, p, t="": u if (u, p) == ("boss", "right") else
                        (_ for _ in ()).throw(ValueError("帳號或密碼不正確")))
    name = D.publish(str(make_package(tmp_path, [{"module": "系統設定/儲存位置", "version": "2026-09-28a", "content": "新頁"},
                                                  {"module": "舊", "version": "2026-09-27a", "content": "已裝"}])),
                     str(root), priv, now=datetime(2026, 9, 28, 3, 0, 0))
    c = TestClient(dd.app, client=("127.0.0.1", 1))
    return {"c": c, "root": root, "install": install, "name": name, "priv": priv, "tmp": tmp_path}


def _apply_and_wait(env, **over):
    body = {"name": env["name"], "username": "boss", "password": "right", "confirm": True}
    body.update(over)
    r = env["c"].post("/api/delivery/apply", json=body)
    if r.status_code != 200:
        return r, None
    for _ in range(100):
        s = env["c"].get("/api/delivery/status").json()
        if not s["running"] and s["last"]:
            return r, s
        time.sleep(0.05)
    raise AssertionError("套用沒有在 5 秒內結束")


def test_overview_lists_packages_and_says_when_not_configured(env, monkeypatch):
    d = env["c"].get("/api/delivery/overview").json()
    assert d["available"] and [p["name"] for p in d["packages"]] == [env["name"]] and d["lock"] is None
    monkeypatch.setattr(D, "_default_resolver", lambda: "")
    d = env["c"].get("/api/delivery/overview").json()
    assert not d["available"] and "尚未設定更新交付資料夾" in d["notice"] and d["packages"] == []


def test_prepare_verifies_and_summarises(env):
    d = env["c"].post("/api/delivery/prepare", json={"name": env["name"]}).json()
    assert d["ok"] and d["commit"] == COMMIT, d
    assert [c["module"] for c in d["changes"]] == ["系統設定/儲存位置"], "只列包裡有、安裝版沒有的版本紀錄"
    assert d["deleteCount"] is None and any("刪除計畫試算失敗" in n for n in d["notes"]), "包裡沒有 apply_plan ⇒ 明說無法試算"
    assert (env["tmp"] / "staging" / env["name"] / D.PAYLOAD).is_dir() and not str(env["tmp"] / "staging").startswith(str(env["install"]))


def test_rc_tampered_package_is_not_offered(env):
    (env["root"] / "packages" / env["name"] / D.PAYLOAD / "backend" / "tools" / "apply_update.ps1").write_text("evil", encoding="utf-8")
    d = env["c"].post("/api/delivery/prepare", json={"name": env["name"]}).json()
    assert not d["ok"] and any("雜湊不符" in p or "apply_update" in p for p in d["problems"]), d


def test_apply_guards_confirm_prepare_credentials(env):
    c = env["c"]
    assert c.post("/api/delivery/apply", json={"name": env["name"], "username": "boss", "password": "right"}).status_code == 400
    r = c.post("/api/delivery/apply", json={"name": env["name"], "username": "boss", "password": "right", "confirm": True})
    assert r.status_code == 409 and "準備" in r.json()["detail"]
    c.post("/api/delivery/prepare", json={"name": env["name"]})
    r = c.post("/api/delivery/apply", json={"name": env["name"], "username": "boss", "password": "wrong", "confirm": True})
    assert r.status_code == 403 and "密碼" in r.json()["detail"]
    assert not list((env["install"] / "backend" / "logs").glob("*")) if (env["install"] / "backend" / "logs").exists() else True


def test_rc_staging_changed_after_prepare_is_refused(env):
    env["c"].post("/api/delivery/prepare", json={"name": env["name"]})
    staged = env["tmp"] / "staging" / env["name"] / D.PAYLOAD / "deploy_manifest.json"
    staged.write_text("{}", encoding="utf-8")
    r, _ = _apply_and_wait(env)
    assert r.status_code == 409 and "被改過" in r.json()["detail"]


def test_apply_runs_writes_back_and_status_survives(env):
    env["c"].post("/api/delivery/prepare", json={"name": env["name"]})
    r, s = _apply_and_wait(env)
    assert r.status_code == 200 and r.json()["by"] == "boss"
    assert s["last"]["outcome"] == "succeeded" and s["last"]["result"]["status"] == "success"
    assert s["rolledBackText"], "rolled_back 經 describe_rolled_back 給畫面文字"
    back = json.loads((env["root"] / "results" / (env["name"] + ".result.json")).read_text(encoding="utf-8"))
    assert back["outcome"] == "succeeded" and back["commit"] == COMMIT and "package" not in back
    assert (env["install"] / "backend" / "tools" / "apply_update.ps1").read_bytes() == PS1.encode("utf-8"), "AH-M2：先換上包裡的 tools"
    # 重開儀表板（記憶體狀態清空）⇒ 從結果檔讀上一次
    dd._delivery_state.update({"prepared": {}, "running": False, "last": None})
    d = env["c"].get("/api/delivery/overview").json()
    assert d["last"]["status"] == "success"


def test_prod_status_reads_delivery_results_and_never_calls_prod(env, monkeypatch):
    called = []
    monkeypatch.setattr(dd.requests, "get", lambda *a, **k: called.append(a) or (_ for _ in ()).throw(RuntimeError("不可以連正式機")))
    d = env["c"].get("/api/prod-status").json()
    assert d["healthy"] is None and d["deployed"] == {} and d["delivered"]["configured"] and not d["delivered"]["available"]
    assert "還沒有任何成功" in d["delivered"]["notice"]
    D.write_back(str(env["root"]), env["name"], {"commit": COMMIT, "finished_at": "2026-09-28 03:16:00"}, "succeeded")
    d = env["c"].get("/api/prod-status").json()
    assert d["deployed"]["source"] == "delivery" and d["deployed"]["commit"] == COMMIT and called == []


def test_rc_prod_status_without_delivery_folder_keeps_the_old_path(env, monkeypatch):
    """反向控制：沒設交付資料夾 ⇒ 照舊連正式機（這裡換成失敗的 requests）⇒ healthy False，不是 None。"""
    monkeypatch.setattr(D, "_default_resolver", lambda: "")
    calls = []

    def boom(*a, **k):
        calls.append(a)
        raise RuntimeError("offline")
    monkeypatch.setattr(dd.requests, "get", boom)
    d = env["c"].get("/api/prod-status").json()
    assert d["healthy"] is False and calls and d["delivered"]["configured"] is False
