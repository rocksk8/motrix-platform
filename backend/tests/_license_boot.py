# -*- coding: utf-8 -*-
"""子行程用的測試授權（T80：授權閘門預設開）。

測試主行程由 `conftest.py::license_test_key` 提供自簽金鑰；**子行程沒有 conftest**，而 `import main` 時閘門是開的：
沒有金鑰 ⇒ 模組載入器一個模組都不載、業務 API 全回 402（標案雷達的 S5／S6／啟動 log／reset 端點題就是這樣紅的）。

這裡做同一件事（只換公鑰／金鑰路徑／機器指紋，驗章走真路徑，產品程式沒有任何略過開關）：
子行程腳本在 `import main` 之前呼叫 `install_test_license()`。與 conftest 的差別：金鑰寫在自己的暫存目錄、行程結束時刪。
"""
import atexit
import os
import shutil
import tempfile

MACHINE = "a1b2c3d4e5f60718"          # 與 conftest.TEST_LICENSE_MACHINE 同值（沒有任何東西依賴它們相等，只是少一個要記的數字）


def install_test_license():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from helpers import licensing as lic

    def _pem_pub(k):
        return k.public_key().public_bytes(encoding=serialization.Encoding.PEM,
                                           format=serialization.PublicFormat.SubjectPublicKeyInfo)

    priv = ed25519.Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(encoding=serialization.Encoding.PEM, format=serialization.PrivateFormat.PKCS8,
                                  encryption_algorithm=serialization.NoEncryption())
    d = tempfile.mkdtemp(prefix="motrix-childlic-")
    atexit.register(shutil.rmtree, d, True)
    path = os.path.join(d, "license.key")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(lic.sign_license({"customer": "測試用公司", "tax_id": "00000000", "machine": MACHINE, "modules": ["*"],
                                   "issued": "2026-01-01", "expires": "2099-12-31",
                                   "kind": lic.LICENSE_KIND_SUBSCRIPTION}, priv_pem))
    lic._PUBKEY_PROD = _pem_pub(priv)                                     # 當成正式金鑰（env=prod）：不帶 dev_key 橫幅
    lic._PUBKEY_DEV = _pem_pub(ed25519.Ed25519PrivateKey.generate())      # 拋棄式，沒人持有私鑰
    lic.LICENSE_PATH = path
    lic.machine_fingerprint = lambda: MACHINE
    return path
