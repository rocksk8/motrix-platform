"""`EM6` · 讀不到機器識別時，機器綁定**不可以靜默降級**。

規格（`STATE.md` 總表 `EM6`）：`helpers/licensing.py` 的 `_stable_machine_id -> ''` ⇒
機器綁定靜默降級，而它是商業模式的地基。`STATE §301` 實查結論：現況**不會**降級 ——
三個硬體來源都讀不到時 `machine_fingerprint()` 丟 `RuntimeError`，`_verify_blob()` 接住後
回 `machine_mismatch`（拒絕），不是放行。

⇒ 這一題把那個結論**釘成可執行的**：一把**正常簽出來、機器欄就是本機**的金鑰，
   在「三個來源全部讀不到」的那一刻必須被拒絕。
⚠️ 金鑰刻意簽給本機：若簽給別台，擋下它的會是「機器不符」而不是「讀不到」，
   這一題就量不到要量的那一格。
"""
import datetime as _dt

import pytest

from helpers import licensing as lic


@pytest.fixture()
def signed_for_this_machine(monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    priv = ed25519.Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(serialization.Encoding.PEM,
                                  serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption())
    pub_pem = priv.public_key().public_bytes(serialization.Encoding.PEM,
                                             serialization.PublicFormat.SubjectPublicKeyInfo)
    monkeypatch.setattr(lic, "_PUBKEY_DEV", pub_pem)
    monkeypatch.setattr(lic, "_PUBKEY_PROD", b"")
    today = _dt.date.today()
    blob = lic.sign_license({
        "customer": "EM6 測試", "tax_id": "12345678",
        "machine": lic.machine_fingerprint(),        # 讀得到的時候先算好：簽給本機
        "modules": ["quotation"],
        "issued": today.isoformat(),
        "expires": (today + _dt.timedelta(days=400)).isoformat(),
    }, priv_pem)
    return blob


def _hardware_unreadable(monkeypatch):
    monkeypatch.setattr(lic, "_FINGERPRINT_CACHE", None)
    monkeypatch.setattr(lic, "_windows_hardware", lambda: (None, None))
    monkeypatch.setattr(lic, "_posix_hardware", lambda: (None, None))
    monkeypatch.setattr(lic, "_stable_machine_id", lambda: "")


def test_em6_a_valid_license_is_accepted_while_the_machine_id_is_readable(signed_for_this_machine):
    """正對照：同一把金鑰在讀得到識別時是有效的 —— 否則下一題的拒絕可能來自別的檢查。"""
    st = lic.verify_license(signed_for_this_machine)
    assert st["valid"] is True, st


def test_em6_unreadable_machine_id_is_refused_not_silently_accepted(signed_for_this_machine,
                                                                     monkeypatch):
    _hardware_unreadable(monkeypatch)
    with pytest.raises(RuntimeError):
        lic.machine_fingerprint()        # 量尺：三個來源真的都讀不到了
    monkeypatch.setattr(lic, "_FINGERPRINT_CACHE", None)
    st = lic.verify_license(signed_for_this_machine)
    assert st["valid"] is False and st["reason"] == "machine_mismatch", (
        "讀不到任何硬體識別時，一把簽給本機的金鑰回 %r。\n" % (st,)
        + "☠️ 放行 ＝ 機器綁定靜默降級：拷到任何一台讀不到識別的機器都能用。")
