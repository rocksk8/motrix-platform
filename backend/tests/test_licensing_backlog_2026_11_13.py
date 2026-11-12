# -*- coding: utf-8 -*-
"""T80 稽核殘留項（AUDIT-16 LG-S3／LG-S5、AUDIT-17 之外的 M9 測試缺口）的守門。2026-11-13。

conftest 的 autouse 固件已把 `LICENSE_PATH` 指到一把測試用的有效金鑰、`machine_fingerprint` 換成固定值，
所以這份檔案不碰硬體（見 conftest `license_test_key`）。
"""
import time

import pytest

from helpers import licensing as lic


@pytest.fixture(autouse=True)
def _no_external_commands(monkeypatch):
    def _boom(*a, **kw):
        pytest.fail("不該跑外部指令：%r" % (a,))
    monkeypatch.setattr(lic, "_run", _boom)
    monkeypatch.setattr(lic, "_LICENSE_FILE_CACHE", None)
    monkeypatch.setattr(lic, "_EMERGENCY_CACHE", None)


# ── LG-S3：快取回傳值是深拷貝 ────────────────────────────────────────────────

def test_lg_s3_mutating_the_returned_modules_does_not_pollute_the_license_cache():
    first = lic.verify_license()                  # 冷：驗章後存快取、回傳
    assert first["valid"] is True and first["modules"] == ["*"]
    first["modules"].append("INJECTED")           # 呼叫端對剛拿到的回傳值動手
    second = lic.verify_license()                 # 熱：從快取來
    assert second["modules"] == ["*"], "冷路徑回傳的清單與快取共用同一個物件：改它會污染下一個請求"
    second["modules"].clear()                     # 熱路徑回傳的也不可以是快取本體
    third = lic.verify_license()
    assert third["modules"] == ["*"], "熱路徑回傳的清單就是快取本體：改它會污染下一個請求"


def test_lg_s3_mutating_the_returned_emergency_info_does_not_pollute_its_cache(monkeypatch):
    info = {"active": True, "until": "2099-01-01", "note": "n", "env": "prod", "tags": ["a"]}
    monkeypatch.setattr(lic, "emergency_status", lambda status: info)
    status = {"reason": "machine_mismatch"}
    first = lic.emergency_pass(status)
    assert first is not None
    first["tags"].append("INJECTED")
    second = lic.emergency_pass(status)
    assert second["tags"] == ["a"], "冷路徑回傳值與快取共用清單"
    second["tags"].append("INJECTED2")
    third = lic.emergency_pass(status)
    assert third["tags"] == ["a"], "熱路徑回傳值就是快取本體"


def test_lg_s3_copy_status_keeps_scalars_and_copies_containers():
    src = {"a": 1, "m": ["x", {"k": [1]}], "d": {"q": [2]}}
    out = lic._copy_status(src)
    assert out == src and out is not src
    out["m"][1]["k"].append(9)
    out["d"]["q"].append(9)
    assert src == {"a": 1, "m": ["x", {"k": [1]}], "d": {"q": [2]}}
