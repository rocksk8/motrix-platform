# -*- coding: utf-8 -*-
"""T80 稽核 hichan-16（AUDIT-16-license-gate.md）must-fix 修法的關閉題。

對應稽核報告 §5.4 關閉條件：
1. LG-M1／LG-M1b（licensing.py::machine_fingerprint）
2. LG-M2（main.py::license_gate_middleware、licensing.py::emergency_pass 快取）
3. IP-M1／LG-S7 的 /64 聚合與 IPv4-mapped 展開已在 test_trusted_client_ip_2026_11_11.py 補題，這裡不重複。

每題都對應稽核 §5.3 列出的一個突變（M1／M2／M4／M5），還原修法要讓對應那題紅。
"""
import asyncio
import time

import pytest

from helpers import licensing as lic


# ── LG-M1／LG-M1b：machine_fingerprint() 的重試與退避 ──────────────────────────

@pytest.mark.real_fingerprint
def test_lgm1b_three_partial_probes_are_not_cached_permanently(monkeypatch):
    """三次探測都只讀到一半（殘缺）：重試要剛好跑 3 次（突變 M2：改成 1 次重試，這裡會紅）；
    結果要存成「不穩定」，退避期內沿用同一個殘缺值，不會每次呼叫都重新探測硬體。"""
    monkeypatch.setattr(lic, "_FINGERPRINT_CACHE", None)
    monkeypatch.setattr(lic, "_FP_PROBE_DELAY_S", 0)  # 不要真的睡，測試要快
    calls = []

    def always_partial():
        calls.append(1)
        return ("uuid-only-never-complete", "")  # 永遠只有一半

    monkeypatch.setattr(lic, "_probe_hardware_once", always_partial)

    first = lic.machine_fingerprint()
    assert len(calls) == 3, "殘缺時應該重試到 _FP_PROBE_RETRIES（3）次才定案：%r" % calls

    # 退避期內（還在 60 秒內）：不重新探測，沿用同一個值。
    second = lic.machine_fingerprint()
    assert second == first
    assert len(calls) == 3, "退避期內又跑去探測硬體了，退避沒生效：%r" % calls


@pytest.mark.real_fingerprint
def test_lgm1b_strikes_escalate_the_backoff_instead_of_caching_forever(monkeypatch):
    """hichan-16複驗抓到的題目缺口：原本的題目分不清「永久快取」與「退避」（兩者在第二次呼叫
    回的值都一樣），也沒有走真正的 machine_fingerprint() 去累積 strikes。這題走完整流程：

    1. 殘缺×3 ⇒ `_FINGERPRINT_CACHE` 要是 unstable、strikes=0。
    2. 退避（60s）到期、硬體仍殘缺 ⇒ 重探一次、strikes 要變成 1（退避升級到下一檔 300s）。
    3. 只倒回 61 秒（上一檔的退避值，不夠蓋過新的 300s 退避）、硬體這次其實已經完整了，
       也不該重探——證明退避真的升級了，不是永遠 60 秒（否則這裡就會錯誤地重探、變穩定）。
    4. 倒回 301 秒（蓋過 300s 退避）⇒ 這次才重探，讀到完整結果，升級成穩定值。

    突變 M6（is_stable 永遠 True，等於 LG-M1b 整個退回「殘缺也永久快取」）與 M8（退避永遠
    60s、不升級）都會在步驟 2／3 紅。"""
    monkeypatch.setattr(lic, "_FINGERPRINT_CACHE", None)
    monkeypatch.setattr(lic, "_FP_PROBE_DELAY_S", 0)
    calls = []

    def always_partial():
        calls.append(1)
        return ("uuid-only-never-complete", "")

    # 步驟 1：殘缺 ×3
    monkeypatch.setattr(lic, "_probe_hardware_once", always_partial)
    first = lic.machine_fingerprint()
    cache = lic._FINGERPRINT_CACHE
    assert cache[1] is False, "殘缺結果被標成穩定了（M6）：%r" % (cache,)
    assert cache[3] == 0, "第一次殘缺不該就有 strike：%r" % (cache,)

    # 步驟 2：倒回剛好超過第 0 檔退避（60s），硬體仍殘缺 ⇒ 重探、strikes 要變成 1
    monkeypatch.setattr(lic, "_FINGERPRINT_CACHE", (cache[0], cache[1], time.monotonic() - 61, cache[3]))
    calls_before = len(calls)
    second = lic.machine_fingerprint()
    assert len(calls) > calls_before, "退避到期了卻沒有重探"
    assert second == first  # 硬體還是殘缺，算出同一個值
    cache = lic._FINGERPRINT_CACHE
    assert cache[3] == 1, "退避到期重探後，strikes 應該要累加（否則永遠停在第 0 檔退避，M8）：%r" % (cache,)

    # 步驟 3：只倒回 61 秒——這不夠蓋過「升級後」的第 1 檔退避（300s）。硬體這次其實已經
    # 完整了，但退避沒到期就不該去看；能撐住代表退避真的升級了，不是永遠 60s（M8）。
    monkeypatch.setattr(lic, "_probe_hardware_once", lambda: ("uuid-full", "mac-full"))
    monkeypatch.setattr(lic, "_FINGERPRINT_CACHE", (cache[0], cache[1], time.monotonic() - 61, cache[3]))
    calls_before = len(calls)
    third = lic.machine_fingerprint()
    assert len(calls) == calls_before, "退避還沒到期（只過了61秒，第1檔要300秒）卻重探了，退避沒升級（M8）"
    assert third == first, "退避期內理當沿用舊值"

    # 步驟 4：倒回 301 秒，蓋過第 1 檔退避 ⇒ 這次重探，硬體完整 ⇒ 升級成穩定值。
    monkeypatch.setattr(lic, "_FINGERPRINT_CACHE", (cache[0], cache[1], time.monotonic() - 301, cache[3]))
    fourth = lic.machine_fingerprint()
    assert fourth != first, "退避到期、硬體已完整，應該升級成新的穩定值"
    cache = lic._FINGERPRINT_CACHE
    assert cache[1] is True, "硬體完整之後應該標成穩定（M6）：%r" % (cache,)

    def boom():
        raise AssertionError("穩定之後不該再探測硬體")
    monkeypatch.setattr(lic, "_probe_hardware_once", boom)
    assert lic.machine_fingerprint() == fourth


@pytest.mark.real_fingerprint
def test_lgm1_all_empty_then_full_recovers_within_the_retry_window(monkeypatch):
    """第一次探測空的，重試時讀到完整 ⇒ 當次就要拿到完整、穩定的結果（不是永遠殘缺）。"""
    monkeypatch.setattr(lic, "_FINGERPRINT_CACHE", None)
    monkeypatch.setattr(lic, "_FP_PROBE_DELAY_S", 0)
    responses = iter([("", ""), ("uuid-x", "mac-y")])

    def flaky_then_ok():
        return next(responses)

    monkeypatch.setattr(lic, "_probe_hardware_once", flaky_then_ok)
    digest = lic.machine_fingerprint()
    assert len(digest) == 16

    # 穩定結果快取到行程結束：即使硬體探測之後開始失敗，也不會被重新觸發。
    def boom():
        raise AssertionError("穩定結果不該再探測硬體")

    monkeypatch.setattr(lic, "_probe_hardware_once", boom)
    assert lic.machine_fingerprint() == digest


def test_lgm1_machine_mismatch_is_cached_only_for_a_short_ttl(monkeypatch, tmp_path):
    """_verify_license_file() 的 machine_mismatch 只能快取 60 秒（稽核 LG-M1，§5.1 情境 C）：
    硬體「恢復」後，不需要碰檔案／跨日／重啟，TTL 過了就要自動變成 ok（突變 M1 會讓這裡卡死、紅）。"""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    import datetime as _dt

    priv = ed25519.Ed25519PrivateKey.generate()
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo)
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM, format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption())
    monkeypatch.setattr(lic, "_PUBKEY_DEV", pub_pem)
    monkeypatch.setattr(lic, "_PUBKEY_PROD", b"")

    real_machine = "the-real-machine-fingerprint"
    license_path = tmp_path / "license.key"
    payload = {
        "customer": "測試客戶", "tax_id": "11112222", "machine": real_machine,
        "modules": ["*"], "issued": _dt.date.today().isoformat(),
        "expires": (_dt.date.today() + _dt.timedelta(days=100)).isoformat(),
    }
    license_path.write_text(lic.sign_license(payload, priv_pem), encoding="utf-8")
    monkeypatch.setattr(lic, "LICENSE_PATH", str(license_path))
    monkeypatch.setattr(lic, "_LICENSE_FILE_CACHE", None)

    # 硬體一開始讀不到（算不出指紋）⇒ machine_mismatch
    def fails():
        raise RuntimeError("no hardware")
    monkeypatch.setattr(lic, "machine_fingerprint", fails)
    st = lic.verify_license()
    assert st["reason"] == "machine_mismatch"

    # 硬體「恢復」了，回真正相符的指紋——但如果還在 TTL 內，快取仍然沿用舊的 mismatch
    monkeypatch.setattr(lic, "machine_fingerprint", lambda: real_machine)
    st2 = lic.verify_license()
    assert st2["reason"] == "machine_mismatch", "TTL 內應該還是沿用快取的 mismatch"

    # 把快取的時間戳往前撥到 TTL 之外（不碰檔案、不跨日、不重啟）
    key, status, _cached_at = lic._LICENSE_FILE_CACHE
    monkeypatch.setattr(lic, "_LICENSE_FILE_CACHE", (key, status, time.monotonic() - 999))
    st3 = lic.verify_license()
    assert st3["reason"] == "ok", "TTL 過期後應該自動重判，硬體已經恢復了"


# ── LG-M2(a)：verify_license()／emergency_pass() 不可以阻塞事件迴圈 ─────────────

def _asgi_get(app, path):
    async def run():
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
                  "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
                  "root_path": "", "headers": [(b"host", b"test")],
                  "client": ("203.0.113.5", 1), "server": ("test", 80)}
        sent = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(m):
            sent.append(m)

        t0 = time.monotonic()
        await app(scope, receive, send)
        return next(m["status"] for m in sent if m["type"] == "http.response.start"), time.monotonic() - t0

    return run()


def test_lgm2a_cold_license_check_does_not_block_the_event_loop(client, monkeypatch):
    """授權判定冷啟動（模擬硬體探測很慢）時，同一個事件迴圈的心跳不可以被卡住
    （突變 M5：把 run_in_threadpool 還原成同步呼叫，這裡會紅，比照 T80 R6 的
    test_async_middleware_writes_do_not_block_the_event_loop 同一手法）。

    ⚠️ hichan-16複驗抓到：這題原本沒要 `client` 固件就 `import main`，會讓 main.py
    在整合測試固件（換 DB／LICENSE_PATH 等檔案路徑）有機會接手之前就被 import 進
    sys.modules，污染同一個 pytest 行程裡**後面**的 client 類測試。一定要先經過
    `client` 固件再 import main。"""
    import main

    monkeypatch.setattr(main.license_core, "LICENSE_GATE_ENABLED", True)

    def slow_verify(blob=None):
        time.sleep(1.0)  # 模擬 machine_fingerprint() 冷啟動跑 PowerShell 的那幾百毫秒到數秒
        return {"valid": False, "reason": "missing", "env": None, "customer": None,
                "modules": None, "expires": None, "days_left": None}

    monkeypatch.setattr(main.license_core, "verify_license", slow_verify)

    async def scenario():
        gaps = []
        stop = asyncio.Event()

        async def heartbeat():
            last = time.monotonic()
            while not stop.is_set():
                await asyncio.sleep(0.05)
                now = time.monotonic()
                gaps.append(now - last)
                last = now

        hb = asyncio.create_task(heartbeat())
        await asyncio.sleep(0.1)
        status, took = await _asgi_get(main.app, "/api/ping")
        stop.set()
        await hb
        return status, took, max(gaps)

    status, took, worst = asyncio.run(scenario())
    assert status == 200, status
    assert took > 0.9, "請求沒有被模擬的慢速判定卡到，這題沒量到東西：%.2f" % took
    assert worst < 0.6, "事件迴圈被卡住 %.2f 秒：verify_license() 又變回同步呼叫了" % worst


# ── LG-M2(b)：emergency_pass() 的快取鍵要包含會改變判定結果的每一樣東西 ──────────

def test_lgm2b_emergency_pass_cache_recomputes_when_status_reason_changes(monkeypatch, tmp_path):
    """同一個通行證檔／授權金鑰檔／日期，`status.reason` 不同（例如 machine_mismatch
    vs expired）理論上都要照各自的規則判——快取鍵若漏了 status.reason（突變 M4），
    第二次呼叫會錯誤沿用第一次的結果。這裡用一個更直接的手法驗證鍵真的有分開："""
    monkeypatch.setattr(lic, "_EMERGENCY_CACHE", None)
    calls = []
    orig_judge = lic.emergency_status

    def counting_judge(status):
        calls.append(status.get("reason") if status else None)
        return orig_judge(status)

    monkeypatch.setattr(lic, "emergency_status", counting_judge)

    # 沒有通行證檔：兩種不同 reason 的 status 都要各自觸發一次真正的判定（不能互相沿用快取）。
    lic.emergency_pass({"reason": "machine_mismatch"})
    lic.emergency_pass({"reason": "expired"})
    assert calls == ["machine_mismatch", "expired"], (
        "兩個不同 status.reason 的呼叫沒有各自重算，快取鍵漏了 status.reason：%r" % calls)

    # 緊接著再打一次「跟上一次一樣」的 status（expired）：要直接命中快取，不會再呼叫判定函式。
    # （換回第一次的 machine_mismatch 不能用來測快取命中——單一快取格只留「最近一次」的鍵，
    #  中間那次 expired 已經把它蓋掉，回去是合法的 miss，不是 bug。）
    lic.emergency_pass({"reason": "expired"})
    assert calls == ["machine_mismatch", "expired"], "同樣的 status 應該命中快取，不該再重算：%r" % calls
