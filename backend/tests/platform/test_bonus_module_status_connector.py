"""IP-16 `bonus.module_status`（M07 → L1 `/api/system/bonus-module-status`，2026-09-26 M07 搬遷前置，DEPENDENCY-MAP #27）。

L1 system 原本直接 import M07 的 `modules.payroll.bonus.bonus_module_on`。
① 正對照：M07 在 ⇒ 回的是 M07 的開關（`BONUS_MODULE_ENABLED=0` 關、預設開）
② 反向控制：M07 不在（拿掉提供者）⇒ 200、`enabled: false`、`notice` 明說；不是 500
③ L1 system 不再 import modules.payroll.bonus
"""
from core import registry, source_tree


def _hdr(client, make_user):
    u, p = make_user("ip16_user", "Conn-Pass-123", role="user")[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def test_status_follows_the_payroll_switch(client, make_user, monkeypatch):
    h = _hdr(client, make_user)
    monkeypatch.delenv("BONUS_MODULE_ENABLED", raising=False)
    assert client.get("/api/system/bonus-module-status", headers=h).json()["enabled"] is True
    monkeypatch.setenv("BONUS_MODULE_ENABLED", "0")
    assert client.get("/api/system/bonus-module-status", headers=h).json() == {"enabled": False}


def test_without_payroll_it_is_off_and_says_why(client, make_user, monkeypatch):
    from routers import system
    h = _hdr(client, make_user)
    orig = registry.providers
    monkeypatch.setattr(registry, "providers", lambda cap: {} if cap == "bonus.module_status" else orig(cap))
    r = client.get("/api/system/bonus-module-status", headers=h)
    assert r.status_code == 200 and r.json() == {"enabled": False, "notice": system.BONUS_MODULE_ABSENT}


def test_system_does_not_import_the_payroll_helper():
    src = (source_tree.BACKEND / "routers" / "system.py").read_text(encoding="utf-8")
    assert "from helpers import bonus" not in src and "modules.payroll.bonus" not in src
