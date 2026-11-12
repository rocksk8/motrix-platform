# -*- coding: utf-8 -*-
r"""AUDIT-16 重現（pytest；要借 backend/conftest.py 的 client／live_server／make_user，所以要複製進 backend/tests 才跑得動）。

用法（Windows，測完把複製進去的檔刪掉，不要 commit）：
    copy docs\platform\audit\AUDIT-16-probes\test_zz_audit16_probe.py backend\tests\
    set MOTRIX_TRAIN=1 & set PYTHONUTF8=1 & set TMP=D:\Claude-pm\tmp & set TEMP=D:\Claude-pm\tmp
    cd backend & D:\MOTRIX-PLATFORM\.venv312\Scripts\python.exe -X utf8 -m pytest tests\test_zz_audit16_probe.py -s -q -p no:cacheprovider --basetemp=D:\Claude-pm\tmp\bt
    del tests\test_zz_audit16_probe.py
輸出找 `NONAPI`／`PATH`／`METHOD`／`COLD` 開頭的行。第三題（COLD）把 `licensing._run` 換成睡 3 秒的假指令——**不跑真的 PowerShell／WMI**。
"""
import pytest
from helpers import licensing as lic

def test_probe_routes(_app):
    from tests._routes import all_routes
    rs = all_routes(_app)
    for p, m, r in rs:
        if not p.startswith("/api/"):
            print("NONAPI", type(r).__name__, p, ",".join(sorted(m)))
    for r in _app.routes:
        if type(r).__name__ in ("Mount", "WebSocketRoute", "APIWebSocketRoute"):
            print("SPECIAL", type(r).__name__, getattr(r, "path", ""))
    print("TOTAL", len(rs))

def test_probe_blocked_paths(client, make_user, monkeypatch, tmp_path):
    username, password = make_user(role="admin")
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    tok = r.json()["token"]; hdr = {"Authorization": "Bearer " + tok}
    monkeypatch.setattr(lic, "LICENSE_PATH", str(tmp_path / "nokey" / "license.key"))
    paths = ["/api/customers", "/api/customers/", "//api/customers", "/api/./customers", "/api/x/../customers",
             "/API/customers", "/%61pi/customers", "/api/ping", "/api/ping/", "/api/system/version", "/api/system/branding",
             "/api/auth/me", "/api/license/status", "/api/uploads/x?pt=bad", "/api/line/callback",
             "/api/system/deployed-version", "/docs", "/openapi.json", "/redoc", "/", "/index.html", "/uploads/x", "/api"]
    for p in paths:
        a = client.get(p, follow_redirects=False)
        b = client.get(p, headers=hdr, follow_redirects=False)
        print("PATH", p, "anon=", a.status_code, "authed=", b.status_code, (b.text[:60] if b.status_code not in (200,) else ""))
    for m in ("HEAD", "OPTIONS"):
        print("METHOD", m, client.request(m, "/api/customers", headers=hdr).status_code)


def test_probe_cold_fingerprint_blocks_event_loop(live_server, client, make_user, license_test_key, monkeypatch, tmp_path):
    import hashlib, threading, time, json, urllib.request, urllib.error, datetime as dt
    from helpers import licensing as lic
    username, password = make_user(role="admin")
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    hdr = {"Authorization": "Bearer " + r.json()["token"]}

    import http.client
    host, port = live_server.replace("http://", "").split(":")
    def call(path, h=None):
        t = time.perf_counter()
        c = http.client.HTTPConnection(host, int(port), timeout=60)
        c.request("GET", path, headers=h or {})
        rr = c.getresponse(); rr.read(); c.close()
        return rr.status, round(time.perf_counter() - t, 2)

    # 真指紋函式＋假的外部指令（睡 3 秒＝PowerShell Get-CimInstance 慢的樣子；不碰真硬體）
    monkeypatch.setattr(lic, "machine_fingerprint", license_test_key["real_fingerprint"])
    monkeypatch.setattr(lic, "_FINGERPRINT_CACHE", None)
    def slow_run(cmd, timeout=30):
        time.sleep(3.0)
        return "UUID" + chr(9) + "uuid-x" + chr(10)
    monkeypatch.setattr(lic, "_run", slow_run)
    fp = hashlib.sha256(b"uuid=uuid-x").hexdigest()[:16]
    blob = lic.sign_license({"customer": "X", "tax_id": "1", "machine": fp, "modules": ["*"], "issued": "2026-01-01",
                             "expires": (dt.date.today() + dt.timedelta(days=30)).isoformat()}, license_test_key["priv_pem"])
    keyp = tmp_path / "k" / "license.key"; keyp.parent.mkdir(); keyp.write_text(blob, encoding="utf-8")
    monkeypatch.setattr(lic, "LICENSE_PATH", str(keyp))     # 新檔 ⇒ 快取鍵不同 ⇒ 下一個請求要重驗＋算指紋

    res = {}
    def a(): res["A"] = call("/api/customers", hdr)
    ta = threading.Thread(target=a); ta.start(); time.sleep(0.6)
    res["B"] = call("/api/ping")            # 公開端點、不需要授權，只是想走一般請求
    ta.join()
    print("COLD A (triggers fingerprint):", res["A"], " B (/api/ping started 0.6s later):", res["B"])
    assert res["A"][0] == 200
