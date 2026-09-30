# -*- coding: utf-8 -*-
"""去識別化：伺服器 IP 移出程式碼，改放 own 資料檔的 `network` 區段（helpers/own_values.py）。

契約：本公司環境（有資料檔）的 CORS 預設與通知信系統網址預設和舊版逐字相同；客戶環境（沒有）只有本機四筆、系統網址留空；
資料檔壞掉／版本不符都退回客戶行為，不丟例外。值只在記憶體裡出現（取自 git 歷史的固定舊版 main.py）。
"""
import ast
import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
sys.path.insert(0, str(REPO / "tools" / "platform"))
import own_payload as OP  # noqa: E402

FICT_IP = "192.0.2.77"          # RFC 5737 文件用網段
DB_BLOB = OP.PINNED_BLOB


@pytest.fixture()
def OV():
    sys.path.insert(0, str(BACKEND))
    from helpers import own_values
    return own_values


def _payload(tmp_path, network, monkeypatch):
    d = {"v": 1, "source_blob": DB_BLOB, "m008": {"correct": "a", "email": "b"}, "m106": {"company_name_en": "c"}}
    if network is not None:
        d["network"] = network
    p = tmp_path / "p.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    monkeypatch.setenv("MOTRIX_OWN_PAYLOAD", str(p))


def test_blob_constants_agree_between_the_tool_and_the_runtime_module(OV):
    assert OV.NETWORK_SOURCE_BLOB == OP.PINNED_NET_BLOB


def test_with_a_valid_network_section_the_defaults_carry_the_ip_in_the_old_order(tmp_path, monkeypatch, OV):
    _payload(tmp_path, {"source_blob": OV.NETWORK_SOURCE_BLOB, "server_ip": FICT_IP}, monkeypatch)
    assert OV.server_ip() == FICT_IP
    assert OV.default_cors_origins() == ["http://localhost:666", "http://127.0.0.1:666", "http://%s:666" % FICT_IP,
                                         "https://localhost:666", "https://127.0.0.1:666", "https://%s:666" % FICT_IP]
    assert OV.default_base_url() == "https://%s:666" % FICT_IP


@pytest.mark.parametrize("case", ["missing_file", "no_section", "wrong_blob", "not_an_ip", "not_a_string", "ipv6", "broken_json"])
def test_customer_environment_gets_local_only_and_an_empty_base_url_and_never_raises(tmp_path, monkeypatch, OV, case):
    if case == "missing_file":
        monkeypatch.setenv("MOTRIX_OWN_PAYLOAD", str(tmp_path / "nope.json"))
    elif case == "broken_json":
        (tmp_path / "b.json").write_text("{nope", encoding="utf-8")
        monkeypatch.setenv("MOTRIX_OWN_PAYLOAD", str(tmp_path / "b.json"))
    else:
        net = {"no_section": None,
               "wrong_blob": {"source_blob": "0" * 40, "server_ip": FICT_IP},
               "not_an_ip": {"source_blob": OV.NETWORK_SOURCE_BLOB, "server_ip": "erp.example.com"},
               "not_a_string": {"source_blob": OV.NETWORK_SOURCE_BLOB, "server_ip": 12345},
               "ipv6": {"source_blob": OV.NETWORK_SOURCE_BLOB, "server_ip": "::1"}}[case]
        _payload(tmp_path, net, monkeypatch)
    assert OV.server_ip() == ""
    assert OV.default_cors_origins() == ["http://localhost:666", "http://127.0.0.1:666", "https://localhost:666", "https://127.0.0.1:666"]
    assert OV.default_base_url() == ""


def test_extract_network_needs_exactly_one_non_local_ip():
    ok = OP.extract_network('X = ["http://localhost:666", "http://127.0.0.1:666", "http://10.9.8.7:666", "https://10.9.8.7:666"]')
    assert ok["server_ip"] == "10.9.8.7" and ok["source_blob"] == OP.PINNED_NET_BLOB
    for bad in ('X = ["http://localhost:666"]', 'X = ["http://10.0.0.1:666", "http://10.0.0.2:666"]'):
        with pytest.raises(SystemExit):
            OP.extract_network(bad)


def test_verify_payload_requires_the_network_section():
    ok = {"v": 1, "source_blob": OP.PINNED_BLOB, "m008": {"correct": "a", "email": "b"}, "m106": {"company_name_en": "c"},
          "auth": {"source_blob": OP.PINNED_AUTH_BLOB, "legacy_weak_passwords": ["x1"]},
          "network": {"source_blob": OP.PINNED_NET_BLOB, "server_ip": "10.1.1.1"}}
    assert OP.verify_payload(ok) == []
    assert any("network" in p for p in OP.verify_payload({k: v for k, v in ok.items() if k != "network"}))
    assert any("network" in p for p in OP.verify_payload(dict(ok, network={"source_blob": "0" * 40, "server_ip": "10.1.1.1"})))
    assert any("network" in p for p in OP.verify_payload(dict(ok, network={"source_blob": OP.PINNED_NET_BLOB, "server_ip": ""})))


def test_add_auth_now_patches_both_sections_and_is_idempotent(tmp_path):
    old = {"v": 1, "source_blob": OP.PINNED_BLOB, "m008": {"correct": "a", "email": "b"}, "m106": {"company_name_en": "c"}}
    p = tmp_path / "p.json"
    p.write_text(json.dumps(old), encoding="utf-8")
    assert OP.add_auth(p).startswith("OWN_PAYLOAD_UPDATED")
    d = json.loads(p.read_text(encoding="utf-8"))
    assert OP.verify_payload(d) == [] and "network" in d and "auth" in d
    assert OP.add_auth(p).startswith("OWN_PAYLOAD_UNCHANGED")


def test_no_product_source_file_contains_the_server_ip():
    """程式庫的 .py／.html／.js（backend、frontend；含 tests）不得含伺服器 IP。值取自固定舊版 main.py，只在記憶體比對。
    例外（另案處理中，逐檔登記）：部署／維運腳本與部署儀表板。"""
    ip = OP.extract_network(OP.pinned_net_source())["server_ip"]
    allowed = {"backend/tools/deploy_dashboard.py", "backend/tools/deploy_dashboard.html", "backend/tools/deploy_insights.py",
               "backend/tests/platform/test_deploy_dashboard_health.py", "backend/tests/test_deploy_dashboard_local_only_2026_09_22.py",
               "backend/version_manifest.json"}
    hits = []
    for base in ("backend", "frontend"):
        for p in (REPO / base).rglob("*"):
            if not p.is_file() or p.suffix.lower() not in (".py", ".html", ".js") or "__pycache__" in p.parts or "node_modules" in p.parts:
                continue
            rel = p.relative_to(REPO).as_posix()
            if rel in allowed or "/vendor/" in rel:
                continue
            try:
                if ip in p.read_text(encoding="utf-8-sig", errors="ignore"):
                    hits.append(rel)
            except OSError:
                pass
    assert hits == [], hits


@pytest.mark.needs_own_payload
def test_own_environment_defaults_equal_the_pre_change_values(OV, monkeypatch):
    monkeypatch.delenv("MOTRIX_OWN_PAYLOAD", raising=False)
    tree = ast.parse(OP.pinned_net_source())
    old = None
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "_DEFAULT_CORS_ORIGINS":
            old = [e.value for e in n.value.elts]
    assert old and len(old) == 6
    assert OV.default_cors_origins() == old
    assert OV.default_base_url() == "https://%s:666" % OV.server_ip() and OV.server_ip()
