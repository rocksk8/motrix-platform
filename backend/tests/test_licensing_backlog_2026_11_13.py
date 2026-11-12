# -*- coding: utf-8 -*-
"""T80 稽核殘留項（AUDIT-16 LG-S3／LG-S5、AUDIT-17 之外的 M9 測試缺口）的守門。2026-11-13。

conftest 的 autouse 固件已把 `LICENSE_PATH` 指到一把測試用的有效金鑰、`machine_fingerprint` 換成固定值，
所以這份檔案不碰硬體（見 conftest `license_test_key`）。
"""
import threading
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


# ── LG-S5：指紋探測 single-flight ───────────────────────────────────────────

N_THREADS = 6


def _run_concurrently(fn, n=N_THREADS):
    """n 條執行緒對齊後同時呼叫 fn；回 [(ok, value_or_exception)]。"""
    gate = threading.Barrier(n)
    out = [None] * n

    def work(i):
        gate.wait(10)
        try:
            out[i] = (True, fn())
        except Exception as exc:  # noqa: BLE001
            out[i] = (False, exc)
    ths = [threading.Thread(target=work, args=(i,)) for i in range(n)]
    for th in ths:
        th.start()
    for th in ths:
        th.join(30)
    assert all(o is not None for o in out), "有執行緒沒跑完（死鎖？）"
    return out


@pytest.fixture()
def slow_probe(monkeypatch):
    """可控的硬體探測：每次呼叫睡一下（讓並行的人有時間撞在一起）、記次數。回 (calls, set_result)。"""
    monkeypatch.setattr(lic, "_FINGERPRINT_CACHE", None)
    monkeypatch.setattr(lic, "_FP_PROBE_DELAY_S", 0)
    monkeypatch.setattr(lic, "_stable_machine_id", lambda: "")
    calls = []
    result = {"v": ("uuid-x", "mac-y")}

    def probe():
        calls.append(1)
        time.sleep(0.15)
        return result["v"]
    monkeypatch.setattr(lic, "_probe_hardware_once", probe)
    return calls, result


@pytest.mark.real_fingerprint
def test_lg_s5_concurrent_cold_callers_share_one_probe(slow_probe):
    calls, _ = slow_probe
    out = _run_concurrently(lic.machine_fingerprint)
    assert all(ok for ok, _ in out) and len({v for _, v in out}) == 1, out
    assert len(calls) == 1, "冷啟動時並行的 %d 個請求各自探了硬體：%d 次探測（要 1 次）" % (N_THREADS, len(calls))


@pytest.mark.real_fingerprint
def test_lg_s5_concurrent_callers_share_one_failure_when_hardware_is_persistently_unreadable(slow_probe):
    """持續讀不到：一輪探測＝_FP_PROBE_RETRIES 次呼叫。並行的人要共用這一輪的失敗，不是各跑一輪（或排隊輪流各跑一輪）。"""
    calls, result = slow_probe
    result["v"] = ("", "")
    out = _run_concurrently(lic.machine_fingerprint)
    assert all((not ok) and isinstance(v, RuntimeError) for ok, v in out), out
    assert len(calls) == lic._FP_PROBE_RETRIES, "並行請求沒有共用同一輪失敗：共 %d 次探測呼叫（一輪是 %d）" % (len(calls), lic._FP_PROBE_RETRIES)


@pytest.mark.real_fingerprint
def test_lg_s5_sequential_callers_are_not_held_back_by_an_old_failure(slow_probe):
    """反向：single-flight 只合併「並行」的人，不是加一個時間窗——硬體恢復後下一個請求馬上認得到。"""
    calls, result = slow_probe
    result["v"] = ("", "")
    with pytest.raises(RuntimeError):
        lic.machine_fingerprint()
    n_after_fail = len(calls)
    with pytest.raises(RuntimeError):
        lic.machine_fingerprint()
    assert len(calls) > n_after_fail, "循序的第二次呼叫沒有重新探測（被舊失敗擋住了）"
    result["v"] = ("uuid-x", "mac-y")
    assert len(lic.machine_fingerprint()) == 16, "硬體恢復後第一個請求就要認得到"


@pytest.mark.real_fingerprint
def test_lg_s5_concurrent_callers_when_a_partial_backoff_just_expired_share_one_reprobe(slow_probe, monkeypatch):
    """殘缺值的退避剛到期、並行請求同時進來：只重探一輪。"""
    calls, result = slow_probe
    result["v"] = ("uuid-only", "")
    first = lic.machine_fingerprint()
    cache = lic._FINGERPRINT_CACHE
    assert cache[1] is False
    del calls[:]
    monkeypatch.setattr(lic, "_FINGERPRINT_CACHE", (cache[0], cache[1], time.monotonic() - 61, cache[3]))
    out = _run_concurrently(lic.machine_fingerprint)
    assert all(ok and v == first for ok, v in out), out
    assert len(calls) == lic._FP_PROBE_RETRIES, "退避到期瞬間並行的請求各自重探了：%d 次探測呼叫（一輪是 %d）" % (len(calls), lic._FP_PROBE_RETRIES)


# ── M9：穩定指紋「快取到行程結束」這個性質本身 ───────────────────────────────

@pytest.mark.real_fingerprint
def test_m9_a_stable_fingerprint_is_never_reprobed_however_old_the_cache_is(monkeypatch):
    """T80 M9（測試缺口）：既有 `test_lgm1_all_empty_then_full_recovers…` 只驗「同一瞬間不會重探」。
    這題直接驗性質：穩定結果的 cached_at 往前撥 2 小時（比最長退避 3600 秒還久），仍然不重探；
    對照：同樣撥法對「殘缺」結果要重探（證明這題量得到差別，不是兩邊都不探）。"""
    monkeypatch.setattr(lic, "_FINGERPRINT_CACHE", None)
    monkeypatch.setattr(lic, "_FP_PROBE_DELAY_S", 0)
    monkeypatch.setattr(lic, "_probe_hardware_once", lambda: ("uuid-x", "mac-y"))
    digest = lic.machine_fingerprint()
    cache = lic._FINGERPRINT_CACHE
    assert cache[1] is True

    def boom():
        raise AssertionError("穩定結果被重新探測了")
    monkeypatch.setattr(lic, "_probe_hardware_once", boom)
    monkeypatch.setattr(lic, "_FINGERPRINT_CACHE", (cache[0], True, time.monotonic() - 7200, cache[3]))
    assert lic.machine_fingerprint() == digest

    # 對照組
    calls = []
    monkeypatch.setattr(lic, "_probe_hardware_once", lambda: calls.append(1) or ("uuid-only", ""))
    monkeypatch.setattr(lic, "_FINGERPRINT_CACHE", ("deadbeefdeadbeef", False, time.monotonic() - 7200, 0))
    lic.machine_fingerprint()
    assert calls, "對照組：殘缺值撥過 2 小時應該重探"
