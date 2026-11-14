# -*- coding: utf-8 -*-
"""T87 A1 M1：儀表板第一次裝到正式機上跑時，prod-status 的健康檢查要對兩種位置都對。

開發機：連正式機的對外位址（照舊）。正式機自己：**不連自己的對外 IP**，改連本機 ERP；本機 ERP 位址不是本機就什麼都不連。
（檔名以 test_deploy_dashboard 開頭：HC1c 只准這種檔 import 儀表板。）
"""
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import deploy_dashboard as dd  # noqa: E402

PROD_IP = "172.16.10.177"


class _R:
    ok = True

    def __init__(self, body=None):
        self._b = body or {}

    def json(self):
        return self._b


@pytest.fixture
def seen(monkeypatch):
    urls = []
    monkeypatch.setattr(dd.requests, "get", lambda url, **kw: urls.append(url) or _R())
    monkeypatch.setattr(dd, "_delivered_status", lambda: {"configured": False})
    monkeypatch.delenv("MOTRIX_DELIVERY_ERP_URL", raising=False)
    return urls


def test_on_the_dev_machine_the_prod_address_is_used_as_before(seen, monkeypatch):
    monkeypatch.setattr(dd, "_is_this_machine", lambda host: False)
    st = dd._check_prod_status()
    assert seen and all(u.startswith("https://%s:666/" % PROD_IP) for u in seen)
    assert st["healthy"] is True


def test_on_the_prod_machine_it_never_connects_to_its_own_external_address(seen, monkeypatch):
    monkeypatch.setattr(dd, "_is_this_machine", lambda host: host == PROD_IP)          # 正式機：對外位址是自己的
    st = dd._check_prod_status()
    assert seen, "應該改連本機 ERP"
    for u in seen:
        assert PROD_IP not in u and u.split("/")[2] == "127.0.0.1:666", u
    assert st["healthy"] is True


def test_on_the_prod_machine_with_a_non_local_erp_url_nothing_is_contacted(seen, monkeypatch):
    monkeypatch.setattr(dd, "_is_this_machine", lambda host: host == PROD_IP)
    monkeypatch.setenv("MOTRIX_DELIVERY_ERP_URL", "http://10.1.1.1:666")
    st = dd._check_prod_status()
    assert seen == [] and st["healthy"] is None and st["deployed"] == {}


def test_a_loopback_prod_base_url_is_used_as_is_the_drill_dead_end(seen, monkeypatch):
    monkeypatch.setattr(dd, "PROD_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(dd, "_is_this_machine", lambda host: pytest.fail("loopback 不需要判斷"))
    dd._check_prod_status()
    assert seen and all(u.startswith("http://127.0.0.1:9/") for u in seen)


def test_a_configured_delivery_root_still_contacts_nothing(monkeypatch):
    monkeypatch.setattr(dd.requests, "get", lambda *a, **k: pytest.fail("不該連線"))
    monkeypatch.setattr(dd, "_delivered_status", lambda: {"configured": True, "available": False})
    assert dd._check_prod_status()["healthy"] is None


def test_is_this_machine_uses_bind_only_and_sends_nothing(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("不該送封包／連線")
    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.setattr(socket.socket, "sendto", boom)
    assert dd._is_this_machine("127.0.0.1") is True
    assert dd._is_this_machine("203.0.113.9") is False        # TEST-NET-3：不會是任何機器的位址
    assert dd._is_this_machine("") is False                  # 垃圾輸入不丟例外，也不當成本機（空字串 bind 會變 INADDR_ANY）
    assert dd._is_this_machine("not a host") is False


def test_prod_host_lines_keep_the_exact_shape_the_drill_rewrite_expects():
    src = Path(dd.__file__).read_text(encoding="utf-8")
    assert 'PROD_HOST = "172.16.10.177"' in src and 'PROD_BASE_URL = f"https://{PROD_HOST}:666"' in src
