# -*- coding: utf-8 -*-
"""儀表板取用的 delivery 模組必須是已安裝的那一份（稽核 D US2；B，2026-09-28）。

驗章用的是「執行中那一份」delivery.py 的公鑰；若儀表板從 staging（新包）或別處 import 到 delivery，
等於包替自己驗章，信任鏈失效——而且不會有任何題紅。⇒ deploy_dashboard._trusted_delivery 比對 `__file__` 的 realpath，
不是儀表板自己所在 tools 目錄的 delivery.py ⇒ 拒絕（prepare／apply 回 409，背景套用記失敗），什麼都不動。

- 正對照：正常路徑（tools 目錄那一份）⇒ 取得的就是它、prepare 照常通過
- 反向控制：staging 放一份**內容相同**的 delivery.py，並讓 sys.path 先找到它 ⇒ 拒絕
  （內容相同 ⇒ 證明擋下來的原因是「位置」不是「內容」）
"""
import shutil
import sys

from tests.platform.test_deploy_dashboard_delivery_2026_09_28 import D, dd, env  # noqa: F401  （env 是 fixture）


def test_positive_control_the_installed_copy_is_used_and_prepare_passes(env):
    assert dd._trusted_delivery() is D
    d = env["c"].post("/api/delivery/prepare", json={"name": env["name"]}).json()
    assert d["ok"], d


def _shadow_with_a_staging_copy(env, monkeypatch):
    """staging 目錄放一份與已安裝版本逐位元組相同的 delivery.py，讓 `import delivery` 先找到它。"""
    shadow = env["tmp"] / "staging_shadow"
    shadow.mkdir()
    shutil.copyfile(dd.TOOLS_DIR / "delivery.py", shadow / "delivery.py")
    monkeypatch.delitem(sys.modules, "delivery")               # teardown 還原成已安裝的那一份
    monkeypatch.syspath_prepend(str(shadow))
    return shadow


def test_reverse_control_a_delivery_module_imported_from_staging_is_refused(env, monkeypatch):
    shadow = _shadow_with_a_staging_copy(env, monkeypatch)
    c = env["c"]
    r = c.post("/api/delivery/prepare", json={"name": env["name"]})
    assert r.status_code == 409 and "不是已安裝的那一份" in r.json()["detail"], r.text
    assert str(shadow) in r.json()["detail"] or str(shadow).lower() in r.json()["detail"].lower()
    assert not (env["tmp"] / "staging" / env["name"]).exists(), "拒絕時不可以先複製到 staging"
    assert dd._delivery_state["prepared"] == {}
    r = c.post("/api/delivery/apply", json={"name": env["name"], "username": "boss", "password": "right", "confirm": True})
    assert r.status_code == 409 and "不是已安裝的那一份" in r.json()["detail"], r.text
    assert dd._delivery_state["running"] is False


def test_the_background_apply_also_refuses_an_untrusted_module(env, monkeypatch):
    """背景執行緒自己也要再確認一次（端點檢查之後、真正套用之前換掉 sys.path 的情況）。"""
    _shadow_with_a_staging_copy(env, monkeypatch)
    dd._delivery_state["running"] = True
    dd._delivery_run(env["name"], str(env["tmp"] / "nowhere"), {"ok": True}, str(env["root"]))
    last = dd._delivery_state["last"]
    assert last["outcome"] == "failed" and last["started"] is False
    assert any("不是已安裝的那一份" in p for p in last["problems"]), last
    assert dd._delivery_state["running"] is False
    assert not (env["install"] / "backend" / "logs").exists(), "沒有執行任何套用"
