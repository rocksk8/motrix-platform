"""LG-O1（T80 稽核 hichan-16）：正式公鑰一填入，出貨包就不可以再帶開發公鑰 `_PUBKEY_DEV`。

背景：`helpers/licensing.py` 同時內嵌兩把公鑰、兩把都受信，而它會進每一個出貨包；開發私鑰沒有受控保管，
握有它的人可以簽出 `env=dev` 的授權，`license_gate_middleware` 不會擋。修法＝**包裡沒有那把公鑰**：
建包時（`tools/platform/pubkey_policy.py strip`）把包內 `_PUBKEY_DEV` 改寫成 `b""`，再用同一個判定 `check`／`verify_package` 驗一次。

這支測試守六件事（每一件都有「拿掉那段邏輯就紅」的對照）：
1. 判定本身：兩把都非空才有問題；任何看不懂的寫法都算問題（fail-closed）。
2. 改寫只動 `_PUBKEY_DEV` 那一個賦值，其餘逐位元相同（含 `_PUBKEY_PROD`）；正式公鑰為空時不動；冪等；保留換行風格。
3. **行為**：改寫後的 licensing.py，開發私鑰簽的授權在正式環境驗不過（`bad_signature`），正式私鑰簽的照樣有效；
   對照組：沒改寫的版本，開發私鑰簽的授權是有效的（`env=dev`）——證明「驗不過」是改寫造成的，不是金鑰壞掉。
4. CLI 的結束碼（`strip`／`check`，缺檔回非 0 而不是安靜成功）。
5. `verify_package.check_dev_pubkey`：未改寫的包被擋、改寫後的包過、缺檔被擋（不是 PASS）。
6. 接線：建包腳本在 `export_ignore.json` 之前呼叫 `strip` 再 `check`；`verify_package.main` 有呼叫 `check_dev_pubkey`
   （建包腳本本身無法在單元測試裡整支跑，所以用靜態守門釘住，拿掉任何一個呼叫都會紅）。
"""
import importlib.util
import io
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

REPO = Path(__file__).resolve().parents[2]
POLICY = REPO / "tools" / "platform" / "pubkey_policy.py"
LICENSING = REPO / "backend" / "helpers" / "licensing.py"
BUILD_PS1 = REPO / "backend" / "tools" / "build_deploy_package.ps1"
VERIFY_PY = REPO / "backend" / "tools" / "verify_package.py"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def pp():
    return _load(POLICY, "_pubkey_policy_under_test")


def _read(path):
    with io.open(path, encoding="utf-8", newline="") as f:
        return f.read()


def _keypair():
    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption())
    pub_pem = priv.public_key().public_bytes(serialization.Encoding.PEM,
                                             serialization.PublicFormat.SubjectPublicKeyInfo)
    return priv_pem, pub_pem


def _src(dev=b"-----BEGIN PUBLIC KEY-----\nAAAA\n-----END PUBLIC KEY-----\n",
         prod=b"-----BEGIN PUBLIC KEY-----\nBBBB\n-----END PUBLIC KEY-----\n", extra="", nl="\n"):
    text = ('x = 1\n_PUBKEY_DEV = (\n    %r\n)\n\n# 正式公鑰\n_PUBKEY_PROD = (\n    %r\n)\n%s\ny = 2\n' % (dev, prod, extra))
    return text.replace("\n", nl)


# ── 1. 判定 ──────────────────────────────────────────────────────────────────────────────

def test_real_licensing_py_has_both_keys_and_is_flagged(pp):
    """真檔的現況：兩把都在（repo 的常態）⇒ 判定必須報問題（這是 verify_package 的正對照依據）。"""
    dev, prod, node, probs = pp.inspect_source(_read(LICENSING))
    assert probs == [] and node is not None
    assert dev and dev.strip(), "開發公鑰讀不到（解析壞了？）"
    assert prod and prod.strip(), "正式公鑰讀不到（本班已填入；空的話這題的前提就變了，請回 STATE §4 第 1 項）"
    assert pp.policy_problems(_read(LICENSING)), "兩把公鑰都在卻沒被判成問題 ⇒ 判定壞了"


@pytest.mark.parametrize("dev,prod,expect_problem", [
    (b"D", b"P", True),            # 兩把都在 ⇒ LG-O1
    (b"D", b"", False),            # 正式公鑰為空（開發階段）⇒ 開發公鑰是唯一受信公鑰，不可動
    (b"D", b"  \n", False),        # 只有空白也算空
    (b"", b"P", False),            # 已改寫過
    (b" \n", b"P", False),
    (b"", b"", False),
])
def test_policy_truth_table(pp, dev, prod, expect_problem):
    assert bool(pp.policy_problems(_src(dev=dev, prod=prod))) is expect_problem


@pytest.mark.parametrize("label,source", [
    ("語法錯誤", "def broken(:\n"),
    ("缺開發公鑰", '_PUBKEY_PROD = b"P"\n'),
    ("缺正式公鑰", '_PUBKEY_DEV = b"D"\n'),
    ("非字面值（呼叫）", '_PUBKEY_DEV = bytes(3)\n_PUBKEY_PROD = b"P"\n'),
    ("非 bytes（str）", '_PUBKEY_DEV = "D"\n_PUBKEY_PROD = b"P"\n'),
    ("重複賦值", '_PUBKEY_DEV = b"D"\n_PUBKEY_DEV = b"E"\n_PUBKEY_PROD = b"P"\n'),
    ("型別註記", '_PUBKEY_DEV: bytes = b"D"\n_PUBKEY_PROD = b"P"\n'),
    ("增量賦值", '_PUBKEY_DEV = b""\n_PUBKEY_DEV += b"D"\n_PUBKEY_PROD = b"P"\n'),
    ("函式內 global 重新賦值", '_PUBKEY_DEV = b""\n_PUBKEY_PROD = b"P"\ndef f():\n    global _PUBKEY_DEV\n    _PUBKEY_DEV = b"D"\n'),
    ("海象", '_PUBKEY_DEV = b""\n_PUBKEY_PROD = b"P"\nif (_PUBKEY_DEV := b"D"):\n    pass\n'),
    ("多目標賦值", '_PUBKEY_DEV = _OTHER = b"D"\n_PUBKEY_PROD = b"P"\n'),
    ("縮排在 if 裡（非模組層級）", 'if True:\n    _PUBKEY_DEV = b"D"\n_PUBKEY_PROD = b"P"\n'),
])
def test_unrecognised_shapes_fail_closed(pp, label, source):
    """看不懂 ⇒ 有問題，而且 strip 拒絕改寫（絕不「猜一個」）。"""
    assert pp.policy_problems(source), "%s：沒被判成問題（fail-open）" % label
    with pytest.raises(ValueError):
        pp.strip_source(source)


# ── 2. 改寫 ──────────────────────────────────────────────────────────────────────────────

def test_strip_only_touches_the_dev_assignment(pp):
    src = _src()
    new, changed = pp.strip_source(src)
    assert changed
    assert not pp.policy_problems(new)
    dev, prod, _n, probs = pp.inspect_source(new)
    assert probs == [] and dev == b"" and prod == b"-----BEGIN PUBLIC KEY-----\nBBBB\n-----END PUBLIC KEY-----\n"
    old_lines, new_lines = src.splitlines(), new.splitlines()
    # 前後各段逐行相同：只有 _PUBKEY_DEV 那四行（賦值開頭到括號結束）被換成一行
    assert old_lines[0] == new_lines[0] == "x = 1"
    assert new_lines[1].startswith('_PUBKEY_DEV = b""')
    assert old_lines[4:] == new_lines[2:], "改寫動到了 _PUBKEY_DEV 以外的行"


def test_strip_on_the_real_file_keeps_everything_else_byte_for_byte(pp):
    src = _read(LICENSING)
    new, changed = pp.strip_source(src)
    assert changed
    assert not pp.policy_problems(new)
    start = src.index("_PUBKEY_DEV = (")
    end = src.index(")\n", start) + 2
    assert new == src[:start] + pp.STRIPPED_LINE + "\n" + src[end:]
    _dev, prod, _n, _p = pp.inspect_source(new)
    assert prod == pp.inspect_source(src)[1], "正式公鑰被動到"


def test_strip_is_a_noop_when_prod_is_empty_or_dev_already_empty(pp):
    for dev, prod in ((b"D", b""), (b"", b"P"), (b"", b"")):
        src = _src(dev=dev, prod=prod)
        new, changed = pp.strip_source(src)
        assert (new, changed) == (src, False)


def test_strip_is_idempotent_and_preserves_crlf(pp):
    src = _src(nl="\r\n")
    new, changed = pp.strip_source(src)
    assert changed and "\r\n" in new and "\n" not in new.replace("\r\n", "")
    again, changed2 = pp.strip_source(new)
    assert (again, changed2) == (new, False)


# ── 3. 行為：改寫後開發私鑰簽的授權在正式環境驗不過 ───────────────────────────────────────

def _payload(machine):
    return {"customer": "測試客戶", "tax_id": "12345678", "machine": machine, "modules": ["*"],
            "issued": date.today().isoformat(), "expires": "2099-12-31"}


def _licensing_module(tmp_path, source, name):
    p = tmp_path / ("%s.py" % name)
    p.write_text(source, encoding="utf-8", newline="")
    return _load(p, name)


def test_behaviour_stripped_package_rejects_dev_signed_license_but_accepts_prod(pp, tmp_path):
    dev_priv, dev_pub = _keypair()
    prod_priv, prod_pub = _keypair()
    real = _read(LICENSING)

    def build(strip):
        src = real
        # 用測試自產的金鑰取代兩把公鑰常數，再決定要不要改寫——驗的是『改寫這件事』，不依賴真的私鑰
        for name, pub in (("_PUBKEY_DEV", dev_pub), ("_PUBKEY_PROD", prod_pub)):
            m = re.search(r"^%s = \(\n(?:    b\".*\"\n)+\)\n" % name, src, flags=re.M)
            assert m, "找不到 %s 的賦值區塊（licensing.py 的排版變了？本題的取代規則要跟著改）" % name
            src = src[:m.start()] + "%s = (\n    %r\n)\n" % (name, pub) + src[m.end():]
        if strip:
            src, changed = pp.strip_source(src)
            assert changed
        mod = _licensing_module(tmp_path, src, "_lic_strip" if strip else "_lic_keep")
        mod.machine_fingerprint = lambda: "machine-x"
        return mod

    kept, stripped = build(False), build(True)
    dev_blob = kept.sign_license(_payload("machine-x"), dev_priv)
    prod_blob = kept.sign_license(_payload("machine-x"), prod_priv)

    # 對照組：沒改寫 ⇒ 開發私鑰簽的授權有效（env=dev）；正式私鑰簽的有效（env=prod）
    st = kept.verify_license(dev_blob)
    assert st["valid"] is True and st["env"] == "dev", st
    st = kept.verify_license(prod_blob)
    assert st["valid"] is True and st["env"] == "prod", st
    # 改寫後 ⇒ 開發私鑰簽的授權被拒；正式私鑰簽的不受影響
    st = stripped.verify_license(dev_blob)
    assert st["valid"] is False and st["reason"] == "bad_signature", st
    st = stripped.verify_license(prod_blob)
    assert st["valid"] is True and st["env"] == "prod", st


# ── 4. CLI ───────────────────────────────────────────────────────────────────────────────

def _fake_pkg(tmp_path, source):
    pkg = tmp_path / "pkg"
    f = pkg / "backend" / "helpers" / "licensing.py"
    f.parent.mkdir(parents=True)
    f.write_text(source, encoding="utf-8", newline="")
    return pkg, f


def _run(*args):
    r = subprocess.run([sys.executable, "-I", str(POLICY), *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, r.stdout + r.stderr


def test_cli_check_strip_check_roundtrip(tmp_path):
    pkg, f = _fake_pkg(tmp_path, _src())
    rc, out = _run("check", "--pkg", str(pkg))
    assert rc == 1 and "LG-O1" in out, out
    rc, out = _run("strip", "--pkg", str(pkg))
    assert rc == 0, out
    rc, out = _run("check", "--pkg", str(pkg))
    assert rc == 0, out
    assert '_PUBKEY_DEV = b""' in f.read_text(encoding="utf-8")


def test_cli_missing_file_and_unreadable_source_are_nonzero_not_success(tmp_path):
    empty = tmp_path / "nopkg"
    empty.mkdir()
    assert _run("check", "--pkg", str(empty))[0] == 2
    assert _run("strip", "--pkg", str(empty))[0] == 2
    pkg, _f = _fake_pkg(tmp_path, "def broken(:\n")
    assert _run("check", "--pkg", str(pkg))[0] == 1
    assert _run("strip", "--pkg", str(pkg))[0] == 1


# ── 5. verify_package ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def vp():
    mod = _load(VERIFY_PY, "_verify_package_lgo1")
    mod.R.fails.clear()
    mod.R.voided = False
    yield mod
    mod.R.fails.clear()
    mod.R.voided = False


def test_verify_package_blocks_unstripped_and_passes_stripped(vp, pp, tmp_path):
    pkg, f = _fake_pkg(tmp_path, _src())
    vp.check_dev_pubkey(str(pkg))
    assert any(g == "開發公鑰" for g, _d in vp.R.fails), "兩把公鑰都在的包沒被擋"
    vp.R.fails.clear()
    f.write_text(pp.strip_source(_src())[0], encoding="utf-8", newline="")
    vp.check_dev_pubkey(str(pkg))
    assert vp.R.fails == [] and vp.R.voided is False, vp.R.fails


def test_verify_package_missing_file_is_a_failure_not_a_pass(vp, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    vp.check_dev_pubkey(str(empty))
    assert any(g == "開發公鑰" for g, _d in vp.R.fails)


# ── 6. 接線（靜態守門）──────────────────────────────────────────────────────────────────

def test_build_script_calls_strip_then_check_before_export_ignore():
    ps1 = _read(BUILD_PS1)
    i_strip = ps1.index("pubkey_policy.py")
    s = ps1.index("$pubkeyPolicy strip --pkg $pkgDir")
    c = ps1.index("$pubkeyPolicy check --pkg $pkgDir")
    e = ps1.index("export_ignore_list.py")
    assert i_strip < s < c < e, "建包腳本的 LG-O1 步驟順序不對（要 strip → check → 才寫 export_ignore／manifest）"
    # 兩個呼叫之後都要檢查結束碼並中止
    for call in ("$pubkeyPolicy strip --pkg $pkgDir", "$pubkeyPolicy check --pkg $pkgDir"):
        tail = ps1[ps1.index(call):ps1.index(call) + 200]
        assert "$LASTEXITCODE -ne 0" in tail and "Fail " in ps1[ps1.index(call):ps1.index(call) + 400]


def test_verify_package_main_runs_the_gate():
    src = _read(VERIFY_PY)
    assert re.search(r"^\s+check_dev_pubkey\(pkg\)\s*$", src, flags=re.M), "verify_package.main 沒有呼叫 check_dev_pubkey"
