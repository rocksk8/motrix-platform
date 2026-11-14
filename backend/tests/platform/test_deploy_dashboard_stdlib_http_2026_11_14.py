# -*- coding: utf-8 -*-
"""T87 A1 M1：儀表板與自動套用要在正式機（Python312，沒有 requests）上跑得起來。

正式機實測有的第三方套件：urllib3 2.7.0、fastapi 0.141.1、uvicorn 0.52.0、pydantic 2.13.4、websockets 17.0.1。
不在正式機另外裝套件（PM 裁示 2026-11-14）。
（檔名以 test_deploy_dashboard 開頭：HC1c 只准這種檔 import 儀表板。）
"""
import ast
import http.server
import importlib
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
TOOLS = BACKEND / "tools"
PLATFORM_TOOLS = BACKEND.parent / "tools" / "platform"        # 開發機才有的 repo 工具（例如 scope_gate，函式內延遲 import）
sys.path.insert(0, str(TOOLS))

# 正式機實測有的第三方套件（import 名稱）
PROD_VERIFIED = {"urllib3", "fastapi", "uvicorn", "pydantic", "websockets", "starlette"}   # starlette：fastapi 的相依
# import 名稱 → requirements.txt 裡的套件名（只列名稱不同的）
IMPORT_TO_DIST = {"PIL": "pillow", "multipart": "python-multipart", "webauthn": "webauthn"}
GUARDED_FILES = ("deploy_dashboard.py", "auto_apply.py")


def _requirement_names():
    names = set()
    for line in (BACKEND / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        for sep in ("[", ">", "<", "=", "!", "~", ";", " "):
            line = line.split(sep, 1)[0]
        names.add(line.strip().lower().replace("_", "-"))
    return names


def _third_party_imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    top = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            top.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            top.add(node.module.split(".")[0])
    out = set()
    for m in top:
        if m in sys.stdlib_module_names:
            continue
        if (TOOLS / (m + ".py")).exists() or (PLATFORM_TOOLS / (m + ".py")).exists() or (TOOLS / m).is_dir() or (BACKEND / (m + ".py")).exists() or (BACKEND / m).is_dir():
            continue                                         # 本專案自己的模組
        out.add(m)
    return out


def test_requirements_parser_sees_known_packages():
    names = _requirement_names()
    assert {"fastapi", "pydantic", "uvicorn", "pypdf"} <= names                 # 解析器本身要有正對照


@pytest.mark.parametrize("fname", GUARDED_FILES)
def test_third_party_imports_are_declared_or_verified_on_prod(fname):
    declared = _requirement_names()
    bad = []
    for m in sorted(_third_party_imports(TOOLS / fname)):
        dist = IMPORT_TO_DIST.get(m, m).lower().replace("_", "-")
        if m in PROD_VERIFIED or dist in declared:
            continue
        bad.append(m)
    assert not bad, "%s import 了不在 requirements.txt、也沒在正式機驗過的套件：%s" % (fname, bad)


def test_the_guard_would_catch_requests(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("import requests\nimport json\nimport fastapi\n", encoding="utf-8")
    assert _third_party_imports(f) == {"requests", "fastapi"}


@pytest.mark.parametrize("blocked", [("requests",), ("requests", "urllib3")])
def test_dashboard_imports_without_requests_installed(blocked):
    """在另一個乾淨行程裡把套件擋掉再 import（不污染本行程的 sys.modules）。"""
    code = (
        "import sys\n"
        + "".join("sys.modules[%r] = None\n" % b for b in blocked)
        + "sys.path.insert(0, %r)\n" % str(TOOLS)
        + "import deploy_dashboard as dd\n"
        + "assert hasattr(dd.requests, 'get') and hasattr(dd.requests, 'post') and issubclass(dd.requests.RequestException, Exception)\n"
        + "print('IMPORT_OK')\n"
    )
    r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert "IMPORT_OK" in r.stdout, r.stdout + r.stderr


def test_auto_apply_imports_without_requests_installed():
    code = (
        "import sys\nsys.modules['requests'] = None\nsys.modules['urllib3'] = None\n"
        "sys.path.insert(0, %r)\nimport auto_apply\nprint('IMPORT_OK')\n" % str(TOOLS)
    )
    r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert "IMPORT_OK" in r.stdout, r.stdout + r.stderr


# ── 小物件的行為（連本機臨時伺服器）──────────────────────────────────────────

class _H(http.server.BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        _H.seen.append(("GET", self.path, self.headers.get("Authorization")))
        if self.path == "/slow":
            import time
            time.sleep(3)
        if self.path == "/boom":
            return self._send(500, {"detail": "x"})
        self._send(200, {"ok": True})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        _H.seen.append(("POST", self.path, body, self.headers.get("Content-Type")))
        self._send(403 if self.path == "/deny" else 200, {"echo": body})


@pytest.fixture
def server():
    _H.seen = []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield "http://127.0.0.1:%d" % srv.server_address[1]
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def dd():
    return importlib.import_module("deploy_dashboard")


def test_get_and_post_roundtrip(dd, server):
    r = dd.requests.get(server + "/x", headers={"Authorization": "Bearer t"}, verify=False, timeout=5)
    assert r.ok and r.status_code == 200 and r.json() == {"ok": True}
    assert _H.seen[-1] == ("GET", "/x", "Bearer t")
    p = dd.requests.post(server + "/login", json={"username": "u", "password": "中文"}, verify=False, timeout=5)
    assert p.json()["echo"] == {"username": "u", "password": "中文"} and _H.seen[-1][3] == "application/json"


def test_http_error_statuses_are_responses_not_exceptions(dd, server):
    r = dd.requests.get(server + "/boom", verify=False, timeout=5)
    assert r.status_code == 500 and not r.ok and r.json() == {"detail": "x"}
    d = dd.requests.post(server + "/deny", json={}, verify=False, timeout=5)
    assert d.status_code == 403 and not d.ok


def test_connection_refused_and_timeout_raise_request_exception(dd, server):
    with pytest.raises(dd.requests.RequestException):
        dd.requests.get("http://127.0.0.1:9/", verify=False, timeout=2)
    with pytest.raises(dd.requests.RequestException):
        dd.requests.get(server + "/slow", verify=False, timeout=0.5)
    with pytest.raises(dd.requests.RequestException):
        dd.requests.get("not a url", verify=False, timeout=1)


def test_request_exception_is_its_own_class_not_a_catch_all(dd):
    assert dd.requests.RequestException is not OSError and not issubclass(RuntimeError, dd.requests.RequestException)


def test_https_verify_false_skips_certificate_check(dd, monkeypatch):
    """verify=False 要走「不驗憑證」的 context，verify=True 要驗（不連網，只看 context 設定）。"""
    seen = {}

    class FakeOpener:
        def open(self, req, timeout=None):
            raise OSError("stop here")

    def fake_https_handler(context=None):
        seen["ctx"] = context
        return object()

    monkeypatch.setattr(dd.urllib.request, "HTTPSHandler", fake_https_handler)
    monkeypatch.setattr(dd.urllib.request, "build_opener", lambda *h: FakeOpener())
    with pytest.raises(dd.requests.RequestException):
        dd.requests.get("https://example.invalid/", verify=False, timeout=1)
    assert seen["ctx"].verify_mode == dd.ssl.CERT_NONE and seen["ctx"].check_hostname is False
    with pytest.raises(dd.requests.RequestException):
        dd.requests.get("https://example.invalid/", timeout=1)
    assert seen["ctx"].verify_mode == dd.ssl.CERT_REQUIRED and seen["ctx"].check_hostname is True
