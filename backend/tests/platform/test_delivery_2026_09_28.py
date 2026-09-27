# -*- coding: utf-8 -*-
"""更新交付（UPDATE-DELIVERY §2／§3；A，2026-09-28）：開發機發布、正式機偵測／staging／驗證。

全部在 tmp 目錄模擬交付資料夾與安裝目錄——不碰真的雲端資料夾、不碰正式機。
正對照：好的包全部通過（驗得過，才證明下面的「驗不過」是被驗出來的）。
反向控制：改一個檔、多一個檔、少一個檔、改 delivery.json、換一把私鑰、沒有公鑰、同步中、重複版、腳本版本不一致——各自不通過，
而且訊息指到那一項。
"""
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "backend" / "tools"))
import delivery as D  # noqa: E402

COMMIT = "0123abcd" + "e" * 32
PS1 = '# apply\r\n$ApplyScriptVersion = "2026-09-28a"\r\nWrite-Host "x"\r\n'


def _keys():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    k = Ed25519PrivateKey.generate()
    priv = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    pub = k.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return priv, pub


def _pkg(tmp, commit=COMMIT, built_at="2026-09-28 01:00:00", ps1=PS1, reg_version=None, reg_digest=None):
    p = tmp / ("pkg_" + commit[:8] + built_at[-2:])
    (p / "backend" / "tools").mkdir(parents=True)
    (p / "frontend").mkdir()
    (p / "deploy_manifest.json").write_text(json.dumps({"commit": commit, "product": "full", "built_at": built_at}),
                                            encoding="utf-8")
    (p / "backend" / "tools" / "apply_update.ps1").write_bytes(ps1.encode("utf-8"))
    (p / "backend" / "tools" / "apply_update.version.json").write_text(json.dumps({
        "version": reg_version or "2026-09-28a", "sha256": reg_digest or D.ps1_digest(ps1.encode("utf-8"))}), encoding="utf-8")
    (p / "backend" / "main.py").write_text("print('app')\n", encoding="utf-8")
    (p / "frontend" / "index.html").write_text("<html></html>\n", encoding="utf-8")
    return p


def _install(tmp, commit="f" * 40, built_at="2026-09-27 22:01:36"):
    root = tmp / "install"
    (root / "backend").mkdir(parents=True)
    (root / "backend" / ".deployed_commit.json").write_text(json.dumps({"commit": commit, "built_at": built_at}), encoding="utf-8")
    (root / "backend" / "db.py").write_text("CURRENT_VERSION = 116\n", encoding="utf-8")
    return root


@pytest.fixture()
def env(tmp_path):
    root = tmp_path / "交付"
    root.mkdir()
    priv, pub = _keys()
    return {"tmp": tmp_path, "root": root, "priv": priv, "pub": pub, "staging": tmp_path / "staging",
            "install": _install(tmp_path)}


def _publish_and_stage(env, **kw):
    name = D.publish(str(_pkg(env["tmp"], **kw)), str(env["root"]), env["priv"], now=datetime(2026, 9, 28, 2, 0, 0))
    env["staging"].mkdir(exist_ok=True)
    return name, D.stage(str(env["root"]), name, str(env["staging"]))


def _verify(env, staged, pub=None):
    return D.verify_staged(staged, str(env["install"]), pubkey_pem=env["pub"] if pub is None else pub,
                           run_verify_package=False)


# ── 正對照 ───────────────────────────────────────────────────────────────────

def test_a_good_package_publishes_scans_stages_and_verifies(env):
    name, staged = _publish_and_stage(env)
    assert name == "20260928_020000_0123abcd_full"
    assert not (env["root"] / "incoming" / (name + ".partial")).exists(), "發布完成後不留 .partial"
    assert [s["name"] for s in D.scan(str(env["root"]))] == [name]
    r = _verify(env, staged)
    assert r["ok"] and r["problems"] == [], r
    assert r["meta"]["apply_script_version"] == "2026-09-28a" and r["meta"]["files"] == 5


# ── 反向控制：內容被改 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("tamper, needle", [
    (lambda p: (p / "backend" / "main.py").write_text("print('evil')\n", encoding="utf-8"), "雜湊不符"),
    (lambda p: (p / "backend" / "extra.py").write_text("x\n", encoding="utf-8"), "清單外多出的檔"),
    (lambda p: (p / "frontend" / "index.html").unlink(), "缺檔"),
])
def test_rc_changed_payload_is_rejected(env, tamper, needle):
    _name, staged = _publish_and_stage(env)
    tamper(Path(staged) / D.PAYLOAD)
    r = _verify(env, staged)
    assert not r["ok"] and any(needle in p for p in r["problems"]), r["problems"]


def test_rc_edited_delivery_json_breaks_the_signature(env):
    """delivery.json 沒有另外簽——它在簽章涵蓋範圍內（signed_bytes）：只改 commit 顯示也驗不過。"""
    _name, staged = _publish_and_stage(env)
    mp = Path(staged) / D.META_JSON
    meta = json.loads(mp.read_text(encoding="utf-8"))
    meta["commit"] = "9" * 40
    mp.write_text(json.dumps(meta, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    r = _verify(env, staged)
    assert not r["ok"] and any("簽章不符" in p for p in r["problems"]), r["problems"]


def test_rc_a_package_signed_by_another_key_is_rejected(env):
    _name, staged = _publish_and_stage(env)
    _other_priv, other_pub = _keys()
    r = _verify(env, staged, pub=other_pub)
    assert not r["ok"] and any("簽章不符" in p for p in r["problems"]), r["problems"]


def test_rc_without_a_configured_public_key_nothing_passes(env):
    """DELIVERY_PUBKEY_PEM 空的 ⇒ 拒絕，不退回「不驗章」。"""
    _name, staged = _publish_and_stage(env)
    r = D.verify_staged(staged, str(env["install"]), pubkey_pem=b"", run_verify_package=False)
    assert not r["ok"] and any("尚未設定交付公鑰" in p for p in r["problems"]), r["problems"]
    assert D.DELIVERY_PUBKEY_PEM == b"", "公鑰由使用者產生後才貼（U-4）；題目不應該看到一把寫死的測試公鑰"


def test_signature_helpers_reject_garbage():
    priv, pub = _keys()
    sig = D.sign(b"abc", priv)
    assert D.verify_signature(b"abc", sig, pub) and not D.verify_signature(b"abd", sig, pub)
    assert not D.verify_signature(b"abc", "not base64!!", pub)
    assert not D.verify_signature(b"abc", sig, b"-----BEGIN PUBLIC KEY-----\nxx\n-----END PUBLIC KEY-----\n")


# ── 反向控制：版本 ────────────────────────────────────────────────────────────

def test_rc_same_commit_as_installed_is_rejected_and_older_is_a_note(env):
    env["install"] = _install(env["tmp"] / "i1", commit=COMMIT)
    _name, staged = _publish_and_stage(env)
    r = _verify(env, staged)
    assert not r["ok"] and any("已是這一版" in p for p in r["problems"]), r
    env["install"] = _install(env["tmp"] / "i2", built_at="2026-09-29 00:00:00")
    r = _verify(env, staged)
    assert r["ok"] and any("退版" in n for n in r["notes"]), r


def test_rc_script_version_mismatch_is_not_published(env):
    """AH-O7：apply_update.ps1 的內容雜湊與登記不同 ⇒ 開發機就不發布；已發布的包被換腳本 ⇒ 正式機雜湊不符。"""
    bad = _pkg(env["tmp"], reg_digest="0" * 64)
    with pytest.raises(D.DeliveryError, match="升版決定"):
        D.publish(str(bad), str(env["root"]), env["priv"])
    assert not list((env["root"] / "packages").glob("*")) if (env["root"] / "packages").exists() else True
    assert not list((env["root"] / "incoming").glob("*")), "拒絕發布時不留 .partial"
    ver, problems = D.script_version(str(_pkg(env["tmp"] / "x", reg_version="2026-09-27z")))
    assert ver is None and any("登記的" in p for p in problems), problems


# ── 發布與偵測的邊界 ──────────────────────────────────────────────────────────

def test_partial_is_invisible_and_bad_names_are_ignored(env):
    (env["root"] / "incoming" / "20260928_020000_0123abcd_full.partial").mkdir(parents=True)
    (env["root"] / "packages" / "not-a-package").mkdir(parents=True)
    (env["root"] / "packages" / "20260928_020000_0123abcd_full").mkdir()      # 沒有 delivery.json（同步中）
    assert D.scan(str(env["root"])) == []


def test_missing_delivery_root_is_refused_not_created(tmp_path):
    root = tmp_path / "沒有這個資料夾"
    with pytest.raises(D.DeliveryError, match="不自動建"):
        D.scan(str(root))
    priv, _pub = _keys()
    with pytest.raises(D.DeliveryError, match="不自動建"):
        D.publish(str(_pkg(tmp_path)), str(root), priv)
    assert not root.exists()


def test_publishing_the_same_name_twice_is_refused(env):
    pkg = _pkg(env["tmp"])
    D.publish(str(pkg), str(env["root"]), env["priv"], now=datetime(2026, 9, 28, 2, 0, 0))
    with pytest.raises(D.DeliveryError, match="已經發布過"):
        D.publish(str(pkg), str(env["root"]), env["priv"], now=datetime(2026, 9, 28, 2, 0, 0))


def test_stage_detects_sync_in_progress_and_leaves_nothing(env):
    name = D.publish(str(_pkg(env["tmp"])), str(env["root"]), env["priv"], now=datetime(2026, 9, 28, 2, 0, 0))
    (env["root"] / "packages" / name / D.PAYLOAD / "frontend" / "index.html").unlink()     # 雲端還沒同步到的檔
    env["staging"].mkdir()
    with pytest.raises(D.DeliveryError, match="同步中"):
        D.stage(str(env["root"]), name, str(env["staging"]))
    assert list(env["staging"].iterdir()) == [], "同步中不留半份 staging"


def test_prune_keeps_three_and_never_deletes_one_without_a_result(env):
    names = [D.publish(str(_pkg(env["tmp"] / str(i), built_at="2026-09-28 01:0%d:00" % i)), str(env["root"]), env["priv"],
                       keep=99, now=datetime(2026, 9, 28, 2, i, 0)) for i in range(5)]
    (env["root"] / "results").mkdir()
    (env["root"] / "results" / (names[0] + ".result.json")).write_text("{}", encoding="utf-8")   # 只有最舊那份有結果
    removed, kept = D.prune(str(env["root"]), keep=3)
    assert removed == [names[0]] and kept == [names[1]], (removed, kept)
    assert sorted(p.name for p in (env["root"] / "packages").iterdir()) == names[1:]


def test_verify_package_runs_the_installed_copy_with_the_installed_db_version(env):
    """結構檢查用**正式機已安裝版本**的 verify_package.py，期望的 db 版本取自已安裝的 db.py（獨立訊號，不取自包）。"""
    cmd = D.verify_package_cmd(str(env["install"]), "STAGED", D.installed_db_version(str(env["install"])))
    assert cmd[1] == os.path.join(str(env["install"]), "backend", "tools", "verify_package.py")
    assert cmd[2:] == ["STAGED", "--expect-db-version", "116"]
    assert D.installed_db_version(str(env["tmp"] / "nowhere")) is None


def test_ps1_digest_matches_the_h12_rule():
    """與 tests/platform/test_apply_plan 的 _ps1_digest 同規則：去 BOM、CRLF→LF。"""
    assert D.ps1_digest(b"\xef\xbb\xbfa\r\nb") == D.ps1_digest(b"a\nb") == hashlib.sha256(b"a\nb").hexdigest()
    assert D.ps1_digest(b"a\nb") != D.ps1_digest(b"a\nc")
