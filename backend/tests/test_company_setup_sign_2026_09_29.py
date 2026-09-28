# -*- coding: utf-8 -*-
"""本公司資料設定閘門 §6.2 第 2 步：開發機以交付私鑰簽開發者正式機的確認檔（company_setup_cli.py sign）。

私鑰只以路徑傳入：輸出不含私鑰內容；簽完用內嵌公鑰自驗，驗不過（不是交付金鑰）就不寫檔；
只簽開發者身分；輸出檔已存在不覆蓋。以行程內呼叫 main()，測試金鑰與開發者指紋用 monkeypatch 換掉。
"""
import importlib.util
import json
from pathlib import Path

import pytest

from helpers import company_setup as cs
from tests.test_company_setup_core_2026_09_28 import GOOD, UBN_A, UBN_B, _db, _root

pytestmark = pytest.mark.company_gate

_CLI = Path(__file__).resolve().parents[1] / "tools" / "company_setup_cli.py"
_spec = importlib.util.spec_from_file_location("company_setup_cli_sign", _CLI)
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)


def _key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    k = Ed25519PrivateKey.generate()
    priv = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    pub = k.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return priv, pub


@pytest.fixture()
def dev(monkeypatch, tmp_path):
    priv, pub = _key()
    monkeypatch.setattr(cs, "DEVELOPER_IDENTITY_FP", frozenset({cs.identity_fp("tax", UBN_A)}))
    monkeypatch.setattr(cs, "PUBKEYS", (pub,))
    kp = tmp_path / "keys" / "delivery_private.pem"
    kp.parent.mkdir()
    kp.write_bytes(priv)
    return kp, priv


def _run(capsys, *args):
    code = cli.main(["sign", *args])
    out = capsys.readouterr().out
    return code, json.loads([l for l in out.splitlines() if l.startswith("{")][-1]), out


def test_sign_writes_a_file_the_server_accepts(tmp_path, dev, capsys):
    kp, priv = dev
    root = _root(tmp_path)
    _ok, ih = cs.ensure_install_id(root)
    out_file = tmp_path / "company_confirmation.sig"
    code, res, raw = _run(capsys, "--private-key", str(kp), "--install", ih, "--tax", UBN_A, "--out", str(out_file))
    assert code == 0 and res["ok"] is True and res["install"] == ih
    assert "PRIVATE" not in raw and priv.decode("ascii").splitlines()[1] not in raw        # 私鑰內容不出現在輸出
    # 放到安裝目錄 backend/ ⇒ 伺服器判定 valid（端到端：簽的就是伺服器要的格式）
    (Path(root) / "backend" / "company_confirmation.sig").write_bytes(out_file.read_bytes())
    profile = dict(GOOD, tax_id=UBN_A)
    assert cs.signed_file_state(profile, root) == "valid"
    from datetime import date
    assert (date.fromisoformat(res["expires"]) - date.fromisoformat(res["issued"])).days == 365      # 不帶 --days ⇒ 365
    conn = _db(tmp_path, profile)
    assert cs.backfill_once(conn, root) == "backfilled" and cs.status(conn, root)["configured"] is True


@pytest.mark.parametrize("case", ["not_developer", "bad_install", "days", "exists", "wrong_key"])
def test_sign_refusals_write_nothing(tmp_path, dev, capsys, case):
    kp, _priv = dev
    ih = "a" * 64
    out_file = tmp_path / "out.sig"
    args = {"--private-key": str(kp), "--install": ih, "--tax": UBN_A, "--out": str(out_file)}
    if case == "not_developer":
        args["--tax"] = UBN_B
    elif case == "bad_install":
        args["--install"] = "xyz"
    elif case == "days":
        args["--days"] = "366"                                                  # 授權上限 365（D SG-M1）
    elif case == "exists":
        out_file.write_text("old", encoding="utf-8")
    elif case == "wrong_key":
        other, _pub = _key()
        kp2 = tmp_path / "other.pem"
        kp2.write_bytes(other)
        args["--private-key"] = str(kp2)
    flat = [x for kv in args.items() for x in kv]
    code, res, raw = _run(capsys, *flat)
    assert code == cli.EXIT_ERROR and res["ok"] is False, res
    if case == "exists":
        assert out_file.read_text(encoding="utf-8") == "old"
    else:
        assert not out_file.exists() and not Path(str(out_file) + ".tmp").exists()
    assert "PRIVATE" not in raw


def test_missing_key_file_does_not_leak_a_traceback(tmp_path, dev, capsys):
    code, res, raw = _run(capsys, "--private-key", str(tmp_path / "nope.pem"), "--install", "b" * 64,
                          "--tax", UBN_A, "--out", str(tmp_path / "o.sig"))
    assert code == cli.EXIT_ERROR and "FileNotFoundError" in res["error"] and "Traceback" not in raw
