# -*- coding: utf-8 -*-
"""依客戶授權建包（CORE-SPEC「完整包與客戶加購模組」使用者裁示①；B，2026-09-28）。

`product_select apply --license <檔>`：驗章 ⇒ 授權的 modules 決定包的內容（"*"＝全部）；代號對應 module.json 的
license_key（沒寫 ⇒ 資料夾名）。lock 記 `license: {sha256, env}`（檔案指紋，不是內容）。
① 授權列 2 個代號（其中一個是 license_key 與資料夾名不同的模組）⇒ 包只含那 2 個模組＋L0／L1
② "*" ⇒ 全部
③ 拒絕：壞簽章、格式壞、非永久已到期、列了包裡沒有的代號、"*" 混個別代號、找不到檔
④ 照收：建包機不是客戶的機器（machine_mismatch）；永久授權過期
⑤ 反向控制：沒給 --license ⇒ 與現在相同（lock 沒有 license 鍵、內容與直接 apply 產品檔一致）；--product 與 --license 不可以同時給
簽章用測試當場產生的 Ed25519 金鑰（不讀真的私鑰），monkeypatch 開發公鑰。
"""
import datetime as _dt
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from tests.platform.test_product_select import _pkg

REPO = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("_product_select_lic", REPO / "tools" / "platform" / "product_select.py")
PS = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(PS)

TODAY = _dt.date.today()


@pytest.fixture()
def sign(monkeypatch):
    """回傳 sign(**overrides) ⇒ 授權 blob 字串。預設：別台機器、400 天後到期、年費。"""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from helpers import licensing as L
    priv = ed25519.Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption())
    pub_pem = priv.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    monkeypatch.setattr(L, "_PUBKEY_DEV", pub_pem)
    monkeypatch.setattr(L, "_PUBKEY_PROD", b"")

    def _sign(**overrides):
        payload = {"customer": "建包測試客戶", "tax_id": "12345678", "machine": "not-this-machine-0000",
                   "modules": ["alpha"], "issued": TODAY.isoformat(),
                   "expires": (TODAY + _dt.timedelta(days=400)).isoformat()}
        payload.update(overrides)
        return L.sign_license(payload, priv_pem)
    return _sign


def _three(tmp_path):
    """合成包：alpha、beta、gamma；gamma 的 license_key 是 g-sku（與資料夾名不同）。"""
    pkg, mj = _pkg(tmp_path, mods=("alpha", "beta", "gamma"))
    mf = pkg / "backend" / "modules" / "gamma" / "module.json"
    m = json.loads(mf.read_text(encoding="utf-8"))
    m["license_key"] = "g-sku"
    mf.write_text(json.dumps(m), encoding="utf-8")
    return pkg, mj


def _write(tmp_path, blob, name="license.key"):
    p = tmp_path / name
    p.write_text(blob if isinstance(blob, str) else blob.decode("utf-8"), encoding="utf-8")
    return p


def _apply_by_license(pkg, lic_path):
    prod, info = PS.product_from_license(lic_path, PS.module_dirs(pkg / "backend"))
    return PS.apply(pkg, prod, info)


def test_license_decides_the_modules_via_license_key(tmp_path, sign, monkeypatch):
    monkeypatch.setattr(PS, "REPO", REPO)
    pkg, mj = _three(tmp_path)
    lic = _write(tmp_path, sign(modules=["alpha", "g-sku"]))
    lock = _apply_by_license(pkg, lic)
    assert sorted(lock["modules"]) == ["alpha", "gamma"] and lock["excluded"] == ["beta"], lock
    assert sorted(PS.module_dirs(pkg / "backend")) == ["alpha", "gamma"]
    assert not (pkg / "frontend" / "pages" / "beta.html").exists()
    assert (pkg / "backend" / "main.py").exists() and (pkg / "backend" / "core" / "registry.py").exists(), "L0／L1 要在"
    assert lock["license"] == {"sha256": hashlib.sha256(lic.read_bytes()).hexdigest(), "env": "dev"}
    written = json.loads((pkg / "backend" / "modules.lock.json").read_text(encoding="utf-8"))
    assert written["license"]["sha256"] == lock["license"]["sha256"]
    assert "建包測試客戶" not in json.dumps(written, ensure_ascii=False), "lock 只記指紋，不記授權內容"
    monkeypatch.setattr(PS, "REPO", Path("Z:/__no_such_repo__"))    # check 只驗合成包自己宣告的 L1
    assert PS.check(pkg, mj) == []


def test_star_license_keeps_everything(tmp_path, sign):
    pkg, _ = _three(tmp_path)
    lock = _apply_by_license(pkg, _write(tmp_path, sign(modules=["*"])))
    assert sorted(lock["modules"]) == ["alpha", "beta", "gamma"] and lock["excluded"] == []


@pytest.mark.parametrize("case", ["bad_signature", "malformed", "expired", "unknown_key", "star_mixed", "not_list", "missing_file"])
def test_bad_licenses_refuse_to_build(tmp_path, sign, case):
    pkg, _ = _three(tmp_path)
    if case == "bad_signature":
        blob = sign(modules=["alpha"])
        payload = json.loads(__import__("base64").b64decode(blob) if not blob.strip().startswith("{") else blob)
        payload["modules"] = ["alpha", "beta"]                                   # 簽完之後竄改
        text = json.dumps(payload, ensure_ascii=False)
        lic = _write(tmp_path, text if blob.strip().startswith("{")
                     else __import__("base64").b64encode(text.encode("utf-8")).decode("ascii"))
    elif case == "malformed":
        lic = _write(tmp_path, "這不是授權檔")
    elif case == "expired":
        lic = _write(tmp_path, sign(expires=(TODAY - _dt.timedelta(days=1)).isoformat()))
    elif case == "unknown_key":
        lic = _write(tmp_path, sign(modules=["alpha", "no-such-sku"]))
    elif case == "star_mixed":
        lic = _write(tmp_path, sign(modules=["*", "alpha"]))
    elif case == "not_list":
        lic = _write(tmp_path, sign(modules="alpha"))
    else:
        lic = tmp_path / "nope.key"
    before = sorted(PS.module_dirs(pkg / "backend"))
    with pytest.raises(PS.SelectError):
        _apply_by_license(pkg, lic)
    assert sorted(PS.module_dirs(pkg / "backend")) == before, "拒絕時包不可以被動過"
    assert not (pkg / "backend" / "modules.lock.json").exists()


def test_perpetual_expired_and_other_machine_are_accepted(tmp_path, sign):
    """④：建包機不是客戶的機器（每一題都是 machine_mismatch）；永久授權過期過的是維護期，照建。"""
    pkg, _ = _three(tmp_path)
    lock = _apply_by_license(pkg, _write(tmp_path, sign(kind="perpetual",
                                                        expires=(TODAY - _dt.timedelta(days=30)).isoformat())))
    assert sorted(lock["modules"]) == ["alpha"]


def test_reverse_control_without_license_nothing_changes(tmp_path):
    """⑤：沒給 --license ⇒ 與直接 apply 產品檔相同，lock 沒有 license 鍵。"""
    pkg_a, _ = _three(tmp_path / "a")
    pkg_b, _ = _three(tmp_path / "b")
    prod = tmp_path / "sub.json"
    prod.write_text(json.dumps({"name": "sub", "modules": ["beta"]}), encoding="utf-8")
    direct = PS.apply(pkg_a, PS.load_product(str(prod)))
    PS.main(["apply", "--pkg", str(pkg_b), "--product", str(prod)])
    via_cli = json.loads((pkg_b / "backend" / "modules.lock.json").read_text(encoding="utf-8"))
    assert "license" not in direct and "license" not in via_cli
    assert {k: v for k, v in via_cli.items()} == {k: v for k, v in direct.items()}


def test_cli_license_path_writes_the_fingerprint_and_both_flags_are_refused(tmp_path, sign):
    pkg, _ = _three(tmp_path)
    lic = _write(tmp_path, sign(modules=["g-sku"]))
    PS.main(["apply", "--pkg", str(pkg), "--license", str(lic)])
    lock = json.loads((pkg / "backend" / "modules.lock.json").read_text(encoding="utf-8"))
    assert sorted(lock["modules"]) == ["gamma"] and lock["license"]["sha256"] == hashlib.sha256(lic.read_bytes()).hexdigest()
    with pytest.raises(SystemExit):
        PS.main(["apply", "--pkg", str(pkg), "--product", "full", "--license", str(lic)])
    bad = _write(tmp_path, "壞掉的授權", name="bad.key")
    pkg2, _ = _three(tmp_path / "c")
    assert PS.main(["apply", "--pkg", str(pkg2), "--license", str(bad)]) == 2
