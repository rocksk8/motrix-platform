# -*- coding: utf-8 -*-
"""AUDIT-16 重現腳本（純 Python，不開伺服器、不碰硬體、不碰資料庫）。

用法（Windows）：
    set TMP=D:\\Claude-pm\\tmp & set TEMP=D:\\Claude-pm\\tmp
    D:\\MOTRIX-PLATFORM\\.venv312\\Scripts\\python.exe -X utf8 docs\\platform\\audit\\AUDIT-16-probes\\probe_pure.py

所有「外部指令」（PowerShell 讀硬體）都換成假的；金鑰是臨時產的 Ed25519，寫在 tempfile 目錄、結束時刪。
輸出的標籤（A1、B2、C4…）對應 AUDIT-16-license-gate.md 的發現。
"""
import datetime as dt
import hashlib
import os
import shutil
import sys
import tempfile
import time
import unittest.mock as mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "backend"))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from helpers import licensing as L  # noqa: E402
from helpers.client_ip import client_ip  # noqa: E402

priv = Ed25519PrivateKey.generate()
priv_pem = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                              serialization.NoEncryption())
pub_pem = priv.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
base = tempfile.mkdtemp(prefix="audit16_")
L._PUBKEY_DEV = pub_pem
L._PUBKEY_PROD = b""
L.LICENSE_PATH = os.path.join(base, "license.key")
EMERG = os.path.join(base, "license_emergency.key")
FP = "a1b2c3d4e5f60718"
today = dt.date.today()


def mk(machine, exp_days=365, **kw):
    p = {"customer": "X", "tax_id": "123", "machine": machine, "modules": ["*"], "issued": "2026-01-01",
         "expires": (today + dt.timedelta(days=exp_days)).isoformat(), "kind": "subscription"}
    p.update(kw)
    return L.sign_license(p, priv_pem)


def put(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


try:
    # ── A：正常路徑成本（快取命中）──────────────────────────────────────────
    put(L.LICENSE_PATH, mk(FP))
    L._FINGERPRINT_CACHE = FP
    L.verify_license()
    n = 20000
    t = time.perf_counter()
    for _ in range(n):
        L.verify_license()
    print("A1 valid, cache hit: verify_license us/call =", round((time.perf_counter() - t) / n * 1e6, 1))

    # ── B：被擋時每個請求都付的成本（main.py:580-582 在 exempt 判斷之前就呼叫 emergency_pass）──
    L._FINGERPRINT_CACHE = "ffffffffffffffff"            # 這台機器的指紋 ≠ 金鑰上的 machine
    put(L.LICENSE_PATH, mk(FP))
    st = L.verify_license()
    print("B0 status.reason =", st["reason"])
    put(EMERG, L.sign_license({"purpose": "emergency_pass", "tax_id": "123", "machine": FP,
                               "issued": today.isoformat(), "expires": (today + dt.timedelta(days=7)).isoformat(),
                               "reason": "audit"}, priv_pem))
    print("B1 emergency_pass active =", bool(L.emergency_pass(st)))
    n = 300
    t = time.perf_counter()
    for _ in range(n):
        L.emergency_pass(st)
    print("B2 blocked + valid pass: emergency_pass us/call =", round((time.perf_counter() - t) / n * 1e6, 1))
    os.remove(EMERG)
    n = 20000
    t = time.perf_counter()
    for _ in range(n):
        L.emergency_pass(st)
    print("B3 blocked, no pass file: us/call =", round((time.perf_counter() - t) / n * 1e6, 1))
    put(EMERG, "A" * 8000)
    n = 2000
    t = time.perf_counter()
    for _ in range(n):
        L.emergency_pass(st)
    print("B4 blocked, 8KB junk pass file: us/call =", round((time.perf_counter() - t) / n * 1e6, 1))
    os.remove(EMERG)

    # ── C：指紋暫時讀不到 ⇒ machine_mismatch 被快取，硬體恢復後同一個檔仍判不符 ──────────────
    def hw_fail():
        return "", ""
    L._FINGERPRINT_CACHE = None
    L._windows_hardware = hw_fail
    L._posix_hardware = hw_fail
    L._stable_machine_id = lambda: ""
    fp_full = hashlib.sha256(b"uuid=uuid-x|mac=aabbccddeeff").hexdigest()[:16]
    put(L.LICENSE_PATH, mk(fp_full))                     # 這把金鑰是發給「硬體讀得到時」的這台機器的
    L._LICENSE_FILE_CACHE = None
    print("C1 hardware unreadable at first call ->", L.verify_license()["reason"])
    L._windows_hardware = lambda: ("uuid-x", "aabbccddeeff")
    L._posix_hardware = L._windows_hardware
    print("C2 hardware recovered, SAME license file, same day ->", L.verify_license()["reason"],
          "(預期 ok；machine_fingerprint() 現在回", L.machine_fingerprint(), "，金鑰要的是", fp_full, ")")

    # ── D：只讀到一半（UUID 空、MAC 有）⇒ 殘缺指紋被快取到行程結束 ────────────────────────
    L._FINGERPRINT_CACHE = None
    L._windows_hardware = lambda: ("", "aabbccddeeff")
    L._posix_hardware = L._windows_hardware
    partial = L.machine_fingerprint()
    L._windows_hardware = lambda: ("uuid-x", "aabbccddeeff")
    L._posix_hardware = L._windows_hardware
    print("D1 partial =", partial, " later (hardware fully readable) =", L.machine_fingerprint(), " expected =", fp_full)

    # ── E：其他 ──────────────────────────────────────────────────────────────
    L._FINGERPRINT_CACHE = FP
    put(L.LICENSE_PATH, mk(FP, modules=["case"]))
    L._LICENSE_FILE_CACHE = None
    s = L.verify_license()
    s["modules"].append("*")
    print("E1 caller mutates returned modules list; next verify_license()['modules'] =", L.verify_license()["modules"])

    class _R:
        def __init__(self, cf):
            self.client = type("C", (), {"host": "127.0.0.1"})
            self.headers = {"CF-Connecting-IP": cf}
    for i in (1, 2, 3):
        print("E2 same /64, key used by login lockout =", client_ip(_R("2001:db8:1:2::%x" % i)))

    real_date = dt.date

    class _Fake(real_date):
        @classmethod
        def today(cls):
            return real_date(2020, 1, 1)
    with mock.patch.object(L, "date", _Fake):
        L._LICENSE_FILE_CACHE = None
        put(L.LICENSE_PATH, mk(FP, exp_days=0, expires="2026-01-02"))
        print("E3 license expired 2026-01-02, OS clock set to 2020-01-01 ->", L.verify_license()["reason"])
finally:
    shutil.rmtree(base, ignore_errors=True)
