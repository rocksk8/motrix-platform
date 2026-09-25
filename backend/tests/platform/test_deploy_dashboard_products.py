# -*- coding: utf-8 -*-
"""儀表板 D3：選配打包（CORE-SPEC §9e、§9c①）。不真的打包。"""
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
    started = []
    monkeypatch.setattr(dd, "_run_job", lambda *a, **kw: started.append(a))       # 🔴 不真的打包
    monkeypatch.setattr(dd, "HISTORY_PATH", tmp_path / "history.json")
    lf = tmp_path / ".last_full.json"
    lf.write_text(json.dumps({"commit": "a" * 40, "ok": True}), encoding="utf-8")
    monkeypatch.setattr(dd, "LAST_FULL_PATH", lf)
    monkeypatch.setattr(dd, "_head_full_sha", lambda: "a" * 40)
    c = TestClient(dd.app, client=("127.0.0.1", 1))
    c.started = started
    c.tmp = tmp_path
    return c


def _wait(c):
    for _ in range(50):
        if c.started:
            return
        time.sleep(0.02)


def test_products_come_from_the_real_product_folder(client):
    names = {p["name"] for p in client.get("/api/products").json()}
    assert {"full", "core-only"} <= names


@pytest.mark.parametrize("product", ["full", "core-only"])
def test_build_passes_the_chosen_product(client, product):
    assert client.post("/api/build", json={"product": product}).status_code == 200
    _wait(client)
    cmd = " ".join(client.started[0][2])
    assert f"-Product '{product}'" in cmd


def test_default_product_is_full(client):
    assert client.post("/api/build", json={}).status_code == 200
    _wait(client)
    assert "-Product 'full'" in " ".join(client.started[0][2])


@pytest.mark.parametrize("bad", ["nope", "..\\full", "full; rm"])
def test_unknown_or_unsafe_product_is_refused(client, bad):
    r = client.post("/api/build", json={"product": bad})
    assert r.status_code == 400 and client.started == []


def _product_select():
    import importlib.util
    src = Path(dd.PROJECT_ROOT) / "tools" / "platform" / "product_select.py"
    spec = importlib.util.spec_from_file_location("_ps_for_test", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_packages_show_their_module_lock(client, monkeypatch):
    # 稽核 D-1：lock 由打包端（product_select.apply）真的寫出來，不自己擺檔——位置錯了這題才會紅
    ps = _product_select()
    pk = client.tmp / "pkgs"
    full = pk / "20260925_full"
    mdir = full / "backend" / "modules" / "some_mod"
    mdir.mkdir(parents=True)
    (mdir / "module.json").write_text(json.dumps({"key": "some_mod", "version": "1.0.1"}), encoding="utf-8")
    (full / "deploy_manifest.json").write_text('{"commit_short": "abc"}', encoding="utf-8")
    ps.apply(full, {"name": "full", "modules": ["*"]})
    (pk / "20260925_old").mkdir()
    (pk / "20260925_old" / "deploy_manifest.json").write_text('{"commit_short": "def"}', encoding="utf-8")
    monkeypatch.setattr(dd, "DEPLOY_PACKAGES_DIR", pk)
    got = {p["folder"]: p for p in client.get("/api/packages").json()}
    assert got["20260925_full"]["lock"] == {"product": "full", "kind": "full_package", "modules": {"some_mod": "1.0.1"}}
    assert got["20260925_old"]["lock"] is None                  # 舊包沒有 lock：明確是 None，不當成「全部」


def test_lock_name_is_shared_with_the_packager():
    assert dd._LOCK_NAME == _product_select().LOCK_NAME
