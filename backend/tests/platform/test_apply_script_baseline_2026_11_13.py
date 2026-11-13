# -*- coding: utf-8 -*-
"""已出貨腳本基準守門（T83，PM 派工）：apply_update.ps1／apply_module_update.ps1 的內容和「最近一次實際出貨」不同 ⇒ 版號必須嚴格變大。

起因：2026-11-13a 已隨 T81 出貨，授權匯入又改了 apply_update.ps1 的行為卻沒升版——AH-O7（test_apply_plan）只比「腳本 vs 登記檔」，
登記檔 sha256 照更新就綠，抓不到「版號等於已出貨版」。基準檔 docs/platform/prod-baseline/apply_scripts.json 由 `delivery.py publish`
成功之後寫（record_baseline）；這裡驗：①目前的腳本對基準 ②判斷函式（正反對照＋突變）③發布端擋下衝突、失敗不寫基準、成功才寫。
"""
import json
import os
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "backend" / "tools"))
import delivery as D  # noqa: E402

BASE_V, BASE_SHA = "2026-11-13a", "a" * 64
MOD_SHA = "b" * 64


def _baseline(v=BASE_V, sha=BASE_SHA):
    return {"apply_update": {"version": v, "sha256": sha, "shipped_in": "pkg_old", "commit": "c" * 40}}


# ── ① 目前的腳本 vs 基準檔（真的樹）─────────────────────────────────────────────

def test_baseline_file_is_present_and_well_formed():
    path = D.default_baseline_path()
    assert os.path.isfile(path), "基準檔不見了：%s（只有 delivery.py publish 成功後會寫它；不可刪）" % path
    b = D.read_baseline(path)
    assert set(b) >= set(D.BASELINE_SCRIPTS), "基準檔缺腳本：%s" % (set(D.BASELINE_SCRIPTS) - set(b))
    for name, e in b.items():
        assert re.match(r"^[0-9a-f]{64}$", e["sha256"]), name
        assert D.tool_version_key(e["version"]) is not None, (name, e["version"])
        assert e["shipped_in"] and re.match(r"^[0-9a-f]{40}$", str(e["commit"])), name


def test_current_scripts_are_consistent_with_the_shipped_baseline():
    """核心守門：腳本內容與已出貨不同而版號沒升 ⇒ 紅（訊息直接講要升到多少）。"""
    facts = D.script_facts(str(REPO))
    assert set(facts) == set(D.BASELINE_SCRIPTS), "原始碼樹缺腳本：%s" % (set(D.BASELINE_SCRIPTS) - set(facts))
    problems = D.baseline_problems(facts, D.read_baseline(D.default_baseline_path()))
    assert not problems, "\n".join(problems)


def test_version_registries_agree_with_what_the_guard_reads():
    """守門直接讀腳本，AH-O7 讀登記檔：兩邊的版號與雜湊必須一致，否則守門驗的不是 AH-O7 驗的那個東西。"""
    facts = D.script_facts(str(REPO))
    for name, (rel, _re) in D.BASELINE_SCRIPTS.items():
        reg = json.loads((REPO / Path(rel).with_suffix(".version.json")).read_text(encoding="utf-8"))
        assert (reg["version"], reg["sha256"]) == facts[name], name


# ── ② 判斷函式：正反對照 ────────────────────────────────────────────────────────

def test_same_content_same_version_is_green():
    assert D.baseline_problems({"apply_update": (BASE_V, BASE_SHA)}, _baseline()) == []


def test_changed_content_with_the_shipped_version_is_red_and_says_what_to_do():
    """這次要抓的事：內容變了、版號還是已出貨版。"""
    p = D.baseline_problems({"apply_update": (BASE_V, "d" * 64)}, _baseline())
    assert len(p) == 1 and "沒有升" in p[0] and BASE_V in p[0] and "pkg_old" in p[0], p


def test_changed_content_with_a_lower_version_is_red():
    assert D.baseline_problems({"apply_update": ("2026-09-28k", "d" * 64)}, _baseline())


def test_changed_content_with_a_higher_version_is_green_even_if_only_comment_changed():
    """同意的口徑：不判斷是不是只改註解，內容變＋版號升＝綠。"""
    for v in ("2026-11-13b", "2026-11-14a", "2027-01-01a"):
        assert D.baseline_problems({"apply_update": (v, "d" * 64)}, _baseline()) == [], v


def test_same_content_but_a_different_version_is_red():
    assert D.baseline_problems({"apply_update": ("2026-11-13b", BASE_SHA)}, _baseline())


def test_version_is_compared_as_a_version_not_as_a_string():
    """字串比的陷阱：'2026-11-13a' < '2026-11-13b' 沒事，但 '2026-9-3x' 這類格式不對的要直接紅，而不是剛好比得過。"""
    assert D.baseline_problems({"apply_update": ("2026-9-3z", "d" * 64)}, _baseline())
    assert D.baseline_problems({"apply_update": ("2026-11-13", "d" * 64)}, _baseline()), "沒字母的 '2026-11-13' 與基準 13a 比＝較小"
    assert D.baseline_problems({"apply_update": (None, "d" * 64)}, _baseline())


def test_missing_or_malformed_baseline_entries_are_problems_not_passes():
    assert D.baseline_problems({"apply_update": (BASE_V, BASE_SHA)}, {})
    assert D.baseline_problems({"apply_update": (BASE_V, BASE_SHA)}, None)
    assert D.baseline_problems({"apply_update": (BASE_V, BASE_SHA)}, _baseline(sha="xyz"))
    assert D.baseline_problems({"apply_update": (BASE_V, BASE_SHA)}, _baseline(v="garbage"))


# ── ② 突變：對真的腳本動一個字，守門要紅；升版後轉綠 ─────────────────────────────────

def _copy_scripts(tmp_path):
    root = tmp_path / "tree"
    for rel, _re in D.BASELINE_SCRIPTS.values():
        dst = root / Path(rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes((REPO / rel).read_bytes())
    return root


def test_mutation_on_the_real_script_turns_the_guard_red_then_a_version_bump_turns_it_green(tmp_path):
    base = D.read_baseline(D.default_baseline_path())
    root = _copy_scripts(tmp_path)
    ps1 = root / "backend" / "tools" / "apply_update.ps1"
    ver = D.script_facts(str(root))["apply_update"][0]
    # 先把「目前」還原成已出貨內容與版號：此時必須綠（正對照；不依賴目前樹是否剛好升過版）
    raw = ps1.read_bytes().decode("utf-8")
    shipped_like = re.sub(r'^\$ApplyScriptVersion = "[^"]+"', '$ApplyScriptVersion = "%s"' % base["apply_update"]["version"], raw, flags=re.M)
    ps1.write_bytes(shipped_like.encode("utf-8"))
    mutated = shipped_like + "\n# mutation: 行為改了但版號沒升\n"
    ps1.write_bytes(mutated.encode("utf-8"))
    red = D.baseline_problems(D.script_facts(str(root)), base)
    assert any("[apply_update]" in p and "沒有升" in p for p in red), red
    bumped = re.sub(r'^\$ApplyScriptVersion = "[^"]+"', '$ApplyScriptVersion = "2099-01-01a"', mutated, flags=re.M)
    ps1.write_bytes(bumped.encode("utf-8"))
    assert not [p for p in D.baseline_problems(D.script_facts(str(root)), base) if "[apply_update]" in p]
    assert ver  # 版號正則在真腳本上讀得到


# ── ③ 發布端 ────────────────────────────────────────────────────────────────

PS1_TMPL = '# apply\r\n$ApplyScriptVersion = "%s"\r\nWrite-Host "%s"\r\n'


def _keys(tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    k = Ed25519PrivateKey.generate()
    priv = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    pub = k.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    f = tmp_path / "priv.pem"
    f.write_bytes(priv)
    return priv, str(f), pub


def _pkg(tmp_path, version, body="x", commit="0123abcd" + "e" * 32, built_at="2026-11-13 10:00:00", tag="a"):
    p = tmp_path / ("pkg_" + tag)
    (p / "backend" / "tools").mkdir(parents=True)
    (p / "frontend").mkdir()
    (p / "deploy_manifest.json").write_text(json.dumps({"commit": commit, "product": "full", "built_at": built_at}), encoding="utf-8")
    ps1 = (PS1_TMPL % (version, body)).encode("utf-8")
    (p / "backend" / "tools" / "apply_update.ps1").write_bytes(ps1)
    (p / "backend" / "tools" / "apply_update.version.json").write_text(json.dumps({"version": version, "sha256": D.ps1_digest(ps1)}), encoding="utf-8")
    (p / "backend" / "main.py").write_text("print('app')\n", encoding="utf-8")
    (p / "frontend" / "index.html").write_text("<html></html>\n", encoding="utf-8")
    return p, D.ps1_digest(ps1)


@pytest.fixture()
def delivery_root(tmp_path):
    root = tmp_path / "交付"
    root.mkdir()
    return root


def _write_baseline(tmp_path, v="2026-11-13a", sha=None):
    bp = tmp_path / "prod-baseline" / "apply_scripts.json"
    bp.parent.mkdir()
    bp.write_text(json.dumps({"scripts": {"apply_update": {"version": v, "sha256": sha or ("a" * 64), "shipped_in": "pkg_old", "commit": "c" * 40}}}), encoding="utf-8")
    return bp


def test_publish_refuses_changed_content_with_the_shipped_version_and_leaves_nothing_behind(tmp_path, delivery_root):
    priv, _f, pub = _keys(tmp_path)
    pkg, _sha = _pkg(tmp_path, "2026-11-13a", body="behavior changed")
    bp = _write_baseline(tmp_path)
    before = bp.read_bytes()
    with pytest.raises(D.DeliveryError) as ei:
        D.publish(str(pkg), str(delivery_root), priv, baseline_path=str(bp))
    assert "基準" in str(ei.value) and "沒有升" in str(ei.value)
    assert not (delivery_root / "packages").exists() or not list((delivery_root / "packages").iterdir())
    assert not (delivery_root / "incoming").exists() or not list((delivery_root / "incoming").iterdir()), "不該留 .partial"
    assert bp.read_bytes() == before


def test_publish_without_a_baseline_argument_does_not_check(tmp_path, delivery_root):
    """單元層不帶基準＝不查（既有 publish 測試與非原始碼樹的用法不受影響）；CLI 預設會帶。"""
    priv, _f, pub = _keys(tmp_path)
    pkg, _ = _pkg(tmp_path, "2026-11-13a", body="whatever")
    assert D.publish(str(pkg), str(delivery_root), priv)


def test_cli_failed_publish_does_not_touch_the_baseline(tmp_path, delivery_root, capsys):
    _p, keyfile, pub = _keys(tmp_path)
    pkg, _ = _pkg(tmp_path, "2026-11-13a", body="behavior changed")
    bp = _write_baseline(tmp_path)
    before = bp.read_bytes()
    rc = D.main(["publish", "--pkg", str(pkg), "--root", str(delivery_root), "--private-key", keyfile, "--baseline", str(bp)])
    out = capsys.readouterr().out
    assert rc == 1 and "DELIVERY_REFUSED" in out and "DELIVERY_PUBLISH_OK" not in out and "BASELINE_UPDATED" not in out
    assert bp.read_bytes() == before, "失敗的發布不得寫基準"


def test_cli_successful_publish_writes_the_baseline_after_the_ok_line(tmp_path, delivery_root, capsys, monkeypatch):
    _p, keyfile, pub = _keys(tmp_path)
    monkeypatch.setattr(D, "DELIVERY_PUBKEY_PEM", pub)
    pkg, sha = _pkg(tmp_path, "2026-11-13b", body="behavior changed", tag="b")
    bp = _write_baseline(tmp_path)
    rc = D.main(["publish", "--pkg", str(pkg), "--root", str(delivery_root), "--private-key", keyfile, "--baseline", str(bp)])
    out = capsys.readouterr().out
    assert rc == 0 and out.index("DELIVERY_PUBLISH_OK") < out.index("DELIVERY_BASELINE_UPDATED"), out
    e = json.loads(bp.read_text(encoding="utf-8"))["scripts"]["apply_update"]
    name = re.search(r"DELIVERY_PUBLISH_OK (\S+)", out).group(1)
    assert (e["version"], e["sha256"], e["shipped_in"], e["commit"]) == ("2026-11-13b", sha, name, "0123abcd" + "e" * 32)
    # 新基準立刻生效：同一份內容再用 13a 發布會被擋；同版號同內容可以再發
    pkg2, _ = _pkg(tmp_path, "2026-11-13a", body="behavior changed", tag="c", built_at="2026-11-13 11:00:00")
    assert D.main(["publish", "--pkg", str(pkg2), "--root", str(delivery_root), "--private-key", keyfile, "--baseline", str(bp)]) == 1


def test_cli_baseline_write_failure_is_loud_but_does_not_undo_the_published_package(tmp_path, delivery_root, capsys, monkeypatch):
    _p, keyfile, pub = _keys(tmp_path)
    pkg, _ = _pkg(tmp_path, "2026-11-13b", body="x", tag="d")
    bp = _write_baseline(tmp_path)

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(D, "record_baseline", boom)
    rc = D.main(["publish", "--pkg", str(pkg), "--root", str(delivery_root), "--private-key", keyfile, "--baseline", str(bp)])
    out = capsys.readouterr().out
    assert rc == 0 and "DELIVERY_PUBLISH_OK" in out and "DELIVERY_BASELINE_FAILED" in out and "baseline-record" in out, out


def test_record_baseline_never_rewinds_the_version(tmp_path, delivery_root):
    priv, _f, pub = _keys(tmp_path)
    pkg, _ = _pkg(tmp_path, "2026-11-13a", body="old shape", tag="e")
    name = D.publish(str(pkg), str(delivery_root), priv)           # 不帶基準：先讓它發布出去
    bp = _write_baseline(tmp_path, v="2026-11-14a", sha="f" * 64)   # 基準已經比這個包新
    with pytest.raises(D.DeliveryError):
        D.record_baseline(str(delivery_root), name, str(bp), pubkey_pem=pub)
    assert json.loads(bp.read_text(encoding="utf-8"))["scripts"]["apply_update"]["version"] == "2026-11-14a"


def test_record_baseline_first_time_writes_every_script_present_in_the_package(tmp_path, delivery_root):
    priv, _f, pub = _keys(tmp_path)
    pkg, sha = _pkg(tmp_path, "2026-11-13a", body="first", tag="f")
    mod = pkg / "backend" / "tools" / "apply_module_update.ps1"
    mod.write_bytes(b'# m\r\n$ApplyModuleScriptVersion = "2026-09-29a"\r\n')
    name = D.publish(str(pkg), str(delivery_root), priv)
    bp = tmp_path / "fresh" / "apply_scripts.json"
    D.record_baseline(str(delivery_root), name, str(bp), pubkey_pem=pub)
    s = json.loads(bp.read_text(encoding="utf-8"))["scripts"]
    assert s["apply_update"]["sha256"] == sha and s["apply_module_update"]["version"] == "2026-09-29a"
    assert bp.read_bytes().endswith(b"\n") and b"\r\n" not in bp.read_bytes()


# ── 審查補強（hichan-10：M1／L1～L4）──────────────────────────────────────────────

def _published(tmp_path, delivery_root, version="2026-11-13b", tag="p"):
    priv, keyfile, pub = _keys(tmp_path)
    pkg, sha = _pkg(tmp_path, version, body="shipped", tag=tag)
    return D.publish(str(pkg), str(delivery_root), priv), priv, keyfile, pub, sha


def test_m1_cli_module_package_skips_the_baseline_step_with_a_neutral_line(tmp_path, delivery_root, capsys, monkeypatch):
    """M1：單模組包 ⇒ 不驗、不寫基準，印中性的 NOT_APPLICABLE，不是假的 FAILED（那個補救指令也會再失敗）。"""
    from tests.platform.test_delivery_module_2026_09_28 import _mod_pkg
    _p, keyfile, pub = _keys(tmp_path)
    monkeypatch.setattr(D, "DELIVERY_PUBKEY_PEM", pub)
    bp = _write_baseline(tmp_path)
    before = bp.read_bytes()
    rc = D.main(["publish", "--pkg", str(_mod_pkg(tmp_path)), "--root", str(delivery_root), "--private-key", keyfile, "--baseline", str(bp)])
    out = capsys.readouterr().out
    assert rc == 0 and "DELIVERY_PUBLISH_OK" in out and "DELIVERY_BASELINE_NOT_APPLICABLE" in out, out
    assert "BASELINE_FAILED" not in out and "BASELINE_UPDATED" not in out
    assert bp.read_bytes() == before


def test_m1_module_package_publish_works_even_when_the_baseline_file_is_missing(tmp_path, delivery_root, capsys, monkeypatch):
    from tests.platform.test_delivery_module_2026_09_28 import _mod_pkg
    _p, keyfile, pub = _keys(tmp_path)
    rc = D.main(["publish", "--pkg", str(_mod_pkg(tmp_path)), "--root", str(delivery_root), "--private-key", keyfile,
                 "--baseline", str(tmp_path / "nope.json")])
    out = capsys.readouterr().out
    assert rc == 0 and "DELIVERY_BASELINE_NOT_APPLICABLE" in out, out


def test_l1_record_baseline_rejects_bad_names_and_path_traversal(tmp_path, delivery_root):
    name, _priv, _kf, pub, _sha = _published(tmp_path, delivery_root)
    bp = tmp_path / "b.json"
    for bad in ("..", "../" + name, "..\\" + name, name + "/..", "x", "", None, os.path.join(str(delivery_root), "packages", name)):
        with pytest.raises(D.DeliveryError):
            D.record_baseline(str(delivery_root), bad, str(bp), pubkey_pem=pub)
    assert not bp.exists()


def test_l1_record_baseline_rejects_a_fake_unsigned_directory(tmp_path, delivery_root):
    """假目錄：名稱合格、有 payload 和 delivery.json，但沒有簽章 ⇒ 拒絕。"""
    name, _priv, _kf, pub, _sha = _published(tmp_path, delivery_root)
    fake = "20261113_235959_deadbeef_full"
    src = delivery_root / "packages" / name
    import shutil
    shutil.copytree(src, delivery_root / "packages" / fake)
    (delivery_root / "packages" / fake / "package.sha256.sig").unlink()
    bp = tmp_path / "b.json"
    with pytest.raises(D.DeliveryError):
        D.record_baseline(str(delivery_root), fake, str(bp), pubkey_pem=pub)
    assert not bp.exists()


def test_l1_record_baseline_rejects_meta_name_mismatch_wrong_key_and_tampered_script(tmp_path, delivery_root):
    import shutil
    name, _priv, _kf, pub, _sha = _published(tmp_path, delivery_root)
    bp = tmp_path / "b.json"
    # 資料夾名與 delivery.json 的 name 不同（改名複製）：簽章本身是對的，但 name 對不上
    other = "20261113_235958_0123abcd_full"
    shutil.copytree(delivery_root / "packages" / name, delivery_root / "packages" / other)
    with pytest.raises(D.DeliveryError):
        D.record_baseline(str(delivery_root), other, str(bp), pubkey_pem=pub)
    # 公鑰不是發布者的
    _p2, _f2, pub2 = _keys(tmp_path)
    with pytest.raises(D.DeliveryError):
        D.record_baseline(str(delivery_root), name, str(bp), pubkey_pem=pub2)
    # 發布後腳本被換掉（簽章驗得過、但腳本雜湊對不上清單）
    ps1 = delivery_root / "packages" / name / "payload" / "backend" / "tools" / "apply_update.ps1"
    ps1.write_bytes(ps1.read_bytes() + b"# tampered\r\n")
    with pytest.raises(D.DeliveryError):
        D.record_baseline(str(delivery_root), name, str(bp), pubkey_pem=pub)
    assert not bp.exists()


def test_l2_cli_refuses_to_publish_when_the_baseline_file_is_missing_unless_no_baseline(tmp_path, delivery_root, capsys):
    _p, keyfile, pub = _keys(tmp_path)
    pkg, _ = _pkg(tmp_path, "2026-11-13b", body="x", tag="m")
    missing = str(tmp_path / "gone" / "apply_scripts.json")
    rc = D.main(["publish", "--pkg", str(pkg), "--root", str(delivery_root), "--private-key", keyfile, "--baseline", missing])
    out = capsys.readouterr().out
    assert rc == 1 and "DELIVERY_REFUSED" in out and "--no-baseline" in out and "DELIVERY_PUBLISH_OK" not in out, out
    assert not (delivery_root / "packages").exists() or not list((delivery_root / "packages").iterdir())
    rc = D.main(["publish", "--pkg", str(pkg), "--root", str(delivery_root), "--private-key", keyfile, "--no-baseline"])
    out = capsys.readouterr().out
    assert rc == 0 and "DELIVERY_PUBLISH_OK" in out and "DELIVERY_BASELINE_SKIPPED" in out and "BASELINE_UPDATED" not in out, out


def test_l2_default_baseline_path_missing_also_refuses(tmp_path, delivery_root, capsys, monkeypatch):
    _p, keyfile, pub = _keys(tmp_path)
    pkg, _ = _pkg(tmp_path, "2026-11-13b", body="x", tag="n")
    monkeypatch.setattr(D, "default_baseline_path", lambda: str(tmp_path / "no-default.json"))
    rc = D.main(["publish", "--pkg", str(pkg), "--root", str(delivery_root), "--private-key", keyfile])
    assert rc == 1 and "DELIVERY_REFUSED" in capsys.readouterr().out


def test_l3_non_default_baseline_path_is_printed(tmp_path, delivery_root, capsys, monkeypatch):
    _p, keyfile, pub = _keys(tmp_path)
    monkeypatch.setattr(D, "DELIVERY_PUBKEY_PEM", pub)
    pkg, _ = _pkg(tmp_path, "2026-11-13b", body="x", tag="o")
    bp = _write_baseline(tmp_path)
    rc = D.main(["publish", "--pkg", str(pkg), "--root", str(delivery_root), "--private-key", keyfile, "--baseline", str(bp)])
    out = capsys.readouterr().out
    assert rc == 0 and "DELIVERY_BASELINE_FILE" in out and str(bp) in out, out


def test_l4_no_stray_tmp_file_is_left_when_the_atomic_replace_fails(tmp_path, delivery_root, monkeypatch):
    name, _priv, _kf, pub, _sha = _published(tmp_path, delivery_root, tag="q")
    bp = tmp_path / "out" / "apply_scripts.json"

    def boom(*a, **k):
        raise OSError("replace failed")
    monkeypatch.setattr(D.os, "replace", boom)
    with pytest.raises(OSError):
        D.record_baseline(str(delivery_root), name, str(bp), pubkey_pem=pub)
    assert not bp.exists() and not (tmp_path / "out" / "apply_scripts.json.tmp").exists()
