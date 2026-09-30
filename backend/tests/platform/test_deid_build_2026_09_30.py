# -*- coding: utf-8 -*-
"""去識別化 S6：`deid_build.py`（建包的 audience 邏輯）——own 一律要本公司資料檔；sale 剪裁＋驗證＋git 重算比對＋掃描必過。

用一個小的 git repo（合成檔）驅動：不依賴真實 repo 的殘留命中數，決定性。
"""
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
import deid_build as B  # noqa: E402
import deid_hashlist as HL  # noqa: E402
import deid_project as P  # noqa: E402
import deid_scan as S  # noqa: E402
import own_payload as OP  # noqa: E402

COMPANY = "示範資訊股份有限公司"
UPGRADE = ("import re\n# >>> OWN-ONLY:v9-company-defaults\nV9_COMPANY_DEFAULTS = {'tax_id': 'X'}\n# <<< OWN-ONLY:v9-company-defaults\n"
           "# >>> OWN-ONLY:is-our-install\ndef _is_our_install(profile):\n    return True\n# <<< OWN-ONLY:is-our-install\n")
ENTRIES = [{"module": "m", "version": "2026-09-01", "date": "d", "time": "t", "content": "舊紀錄"},
           {"module": "m", "version": "2026-09-30g", "date": "d", "time": "t", "content": "基準當天"}]


def _git(root, *a):
    subprocess.run(["git", "-C", str(root), "-c", "user.email=t@example.com", "-c", "user.name=t", *a], check=True, capture_output=True)


def _marked_files():
    """設定裡每個剪段的檔 ⇒ 每段用 OWN-ONLY 標記圍起一行原始內容（模擬 repo 裡的自用寫法）。"""
    files = {}
    for c in P.load_config()["cuts"]:
        files[c["path"]] = files.get(c["path"], "") + "# >>> OWN-ONLY:%s\nORIGINAL_%s = 1\n# <<< OWN-ONLY:%s\n" % (c["name"], c["name"].replace("-", "_"), c["name"])
    return files


def _tiny_repo(tmp_path):
    r = tmp_path / "repo"
    files = {
        "product/sale_prune.json": (REPO / "product" / "sale_prune.json").read_text(encoding="utf-8"),
        **_marked_files(),
        "backend/autostart.bat": "cd /d C:\\srv\\erp\\backend\r\nset MOTRIX_GEO=1\r\n",
        "product/sale_files/autostart.bat": (REPO / "product" / "sale_files" / "autostart.bat").read_text(encoding="utf-8"),
        **{it["registry"]: '{"version": "v", "sha256": "0"}' for it in P.load_config().get("rehash", [])},
        "backend/version_manifest.json": json.dumps(ENTRIES, ensure_ascii=False),
        "backend/main.py": "print('hi')\n",
        "DEPLOY.md": "原檔（內部）\n", "DR-SOP.md": "原檔（內部）\n", "HTTPS-DEPLOY-CHECKLIST.md": "原檔（內部）\n",
        "product/sale_docs/DEPLOY.md": "客戶版 <安裝目錄>\n", "product/sale_docs/DR-SOP.md": "客戶版 <安裝目錄>\n",
        "product/sale_docs/HTTPS-DEPLOY-CHECKLIST.md": "客戶版 <安裝目錄>\n",
        "docs/platform/PLAYBOOK.md": "內部\n", "tools/platform/modtest.py": "x\n", "tools/platform/upgrade.py": "y\n",
        "backend/version_manifest_sale_overlay.json": "{}\n",
    }
    for rel, text in files.items():
        p = r / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    _git(r.parent, "init", "-q", str(r)) if False else subprocess.run(["git", "init", "-q", str(r)], check=True, capture_output=True)
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "c")
    commit = subprocess.run(["git", "-C", str(r), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    return r, commit


def _pkg(tmp_path, repo, commit, name="pkg"):
    """模擬建包：git archive（不做產品選配）＋建包才產生的檔。"""
    pkg = tmp_path / name
    tar = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", commit], capture_output=True, check=True).stdout
    pkg.mkdir()
    import io
    import tarfile
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        t.extractall(pkg)
    (pkg / "backend").mkdir(exist_ok=True)
    (pkg / "backend" / ".build_commit").write_text(commit, encoding="ascii")
    (pkg / "backend" / "export_ignore.json").write_text("[]", encoding="utf-8")
    return pkg


def _key(tmp_path):
    k = tmp_path / "hmac.key"
    HL.main(["keygen", "--out", str(k)])
    return k


def _hashlist(tmp_path, key, created=None, values=None, name="list.json"):
    vals = {"company": {COMPANY}} if values is None else values
    data = HL.build(vals, S.load_key(key), created=created or dt.datetime.now())
    p = tmp_path / name
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def _payload(tmp_path, good=True):
    d = {"v": 1, "source_blob": OP.PINNED_BLOB, "m008": {"correct": "a", "email": "b"}, "m106": {"company_name_en": "c"}}
    if good:
        d["auth"] = {"source_blob": OP.PINNED_AUTH_BLOB, "legacy_weak_passwords": ["Fict-x-1"]}
        d["network"] = {"source_blob": OP.PINNED_NET_BLOB, "server_ip": "192.0.2.9"}
    p = tmp_path / "own_payload.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    return p


# ── own ────────────────────────────────────────────────────────────────────────────────

def test_own_build_requires_the_payload_and_copies_it_into_the_package(tmp_path, monkeypatch):
    monkeypatch.delenv("MOTRIX_OWN_PAYLOAD", raising=False)
    repo, commit = _tiny_repo(tmp_path)
    pkg = _pkg(tmp_path, repo, commit)
    with pytest.raises(B.BuildError, match="本公司資料檔"):
        B.apply(pkg, "own", commit, "", repo)                                             # 沒給
    with pytest.raises(B.BuildError, match="auth"):
        B.apply(pkg, "own", commit, "", repo, own_payload=str(_payload(tmp_path, good=False)))   # 缺 auth 區段
    assert not (pkg / B.PAYLOAD_REL).exists(), "失敗時不可留下半成品"
    blk = B.apply(pkg, "own", commit, "", repo, own_payload=str(_payload(tmp_path)))
    assert blk["audience"] == "own" and blk["own_payload"] is True and blk["hits"] is None and (pkg / B.PAYLOAD_REL).is_file()
    assert (pkg / "docs/platform/PLAYBOOK.md").exists(), "own 包不剪"


def test_own_build_takes_the_payload_from_the_environment(tmp_path, monkeypatch):
    repo, commit = _tiny_repo(tmp_path)
    pkg = _pkg(tmp_path, repo, commit)
    monkeypatch.setenv("MOTRIX_OWN_PAYLOAD", str(_payload(tmp_path)))
    assert B.apply(pkg, "own", commit, "", repo)["own_payload"] is True


def test_own_build_records_hit_counts_when_it_has_a_list_but_never_blocks(tmp_path):
    repo, commit = _tiny_repo(tmp_path)
    pkg = _pkg(tmp_path, repo, commit)
    (pkg / "note.txt").write_text("客戶是 %s\n" % COMPANY, encoding="utf-8")
    key = _key(tmp_path)
    blk = B.apply(pkg, "own", commit, "", repo, own_payload=str(_payload(tmp_path)), key=str(key), hashlist=str(_hashlist(tmp_path, key)))
    assert blk["hits"] >= 1 and blk["key_id"] and blk["canary"] is True


# ── sale ───────────────────────────────────────────────────────────────────────────────

def _sale(tmp_path, **over):
    repo, commit = _tiny_repo(tmp_path)
    pkg = _pkg(tmp_path, repo, commit)
    key = _key(tmp_path)
    kw = dict(key=str(key), hashlist=str(_hashlist(tmp_path, key)))
    kw.update(over)
    return repo, commit, pkg, kw


def test_sale_happy_path_prunes_projects_verifies_rebuild_and_scans_clean(tmp_path):
    repo, commit, pkg, kw = _sale(tmp_path)
    blk = B.apply(pkg, "sale", commit, "", repo, **kw)
    assert blk["audience"] == "sale" and blk["hits"] == 0 and blk["canary"] is True and blk["own_payload"] is False
    assert blk["prune"]["removed"] >= 3 and blk["prune"]["manifest_projected"] == 2 and len(blk["prune"]["replaced"]) == 4
    assert all(blk["projection_inputs"][k] for k in ("sale_prune_blob", "overlay_blob"))
    assert blk["projection_inputs"]["manifest_baseline"] == P.load_config()["manifest_baseline"]
    assert str(tmp_path) not in json.dumps(blk, ensure_ascii=False), "sale 的 deid 區塊不可含開發機路徑"
    assert not (pkg / "docs").exists() and (pkg / "DEPLOY.md").read_text(encoding="utf-8").startswith("客戶版")
    assert "V9_COMPANY_DEFAULTS = {}" in (pkg / "backend/core/upgrade.py").read_text(encoding="utf-8")
    assert "ORIGINAL_" not in (pkg / "backend/tools/apply_update.ps1").read_text(encoding="utf-8"), "自用寫法要被剪掉"


def test_sale_refuses_without_key_or_list(tmp_path):
    repo, commit, pkg, kw = _sale(tmp_path)
    with pytest.raises(B.BuildError, match="必須做雜湊層掃描"):
        B.apply(pkg, "sale", commit, "", repo)


def test_sale_refuses_an_expired_list_a_wrong_key_and_a_list_without_the_canary(tmp_path):
    repo, commit, pkg, kw = _sale(tmp_path)
    old = _hashlist(tmp_path, kw["key"], created=dt.datetime.now() - dt.timedelta(days=60), name="old.json")
    with pytest.raises(B.BuildError, match="過期"):
        B.apply(_pkg(tmp_path, repo, commit, "p1"), "sale", commit, "", repo, key=kw["key"], hashlist=str(old))
    other = tmp_path / "other.key"
    HL.main(["keygen", "--out", str(other)])
    with pytest.raises(B.BuildError, match="金鑰"):
        B.apply(_pkg(tmp_path, repo, commit, "p2"), "sale", commit, "", repo, key=str(other), hashlist=kw["hashlist"])
    data = json.loads(Path(kw["hashlist"]).read_text(encoding="utf-8"))
    data["hashes"] = {h: k for h, k in data["hashes"].items() if k != "canary"}
    nocanary = tmp_path / "nocanary.json"
    nocanary.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(B.BuildError, match="金絲雀"):
        B.apply(_pkg(tmp_path, repo, commit, "p3"), "sale", commit, "", repo, key=kw["key"], hashlist=str(nocanary))


def test_sale_scan_hit_blocks_the_build_and_the_message_has_codes_not_plaintext(tmp_path):
    repo, commit, pkg, kw = _sale(tmp_path)
    (pkg / "backend" / "main.py").write_text("print('hi')\n# 客戶：%s\n" % COMPANY, encoding="utf-8")
    with pytest.raises(B.BuildError) as ei:
        B.apply(pkg, "sale", commit, "", repo, **kw)
    msg = str(ei.value)
    assert ("掃描有" in msg or "不一致" in msg) and COMPANY not in msg


def test_sale_scan_hit_in_a_committed_file_is_caught_by_the_scanner_not_only_by_the_rebuild(tmp_path):
    """植入的識別值放在 git 裡（重算也一致）⇒ 只有掃描能擋——證明掃描這道關是獨立有效的。"""
    repo, commit = _tiny_repo(tmp_path)
    (repo / "backend" / "main.py").write_text("print('hi')\n# 客戶：%s\n" % COMPANY, encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "plant")
    commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    pkg = _pkg(tmp_path, repo, commit)
    key = _key(tmp_path)
    with pytest.raises(B.BuildError) as ei:
        B.apply(pkg, "sale", commit, "", repo, key=str(key), hashlist=str(_hashlist(tmp_path, key)))
    msg = str(ei.value)
    assert "backend/main.py:2:company:" in msg and "掃描有" in msg and COMPANY not in msg          # 雜湊層（company）＋樣式層（company_pattern）各一筆


def test_sale_refuses_a_package_that_contains_the_own_payload(tmp_path):
    repo, commit, pkg, kw = _sale(tmp_path)
    (pkg / B.PAYLOAD_REL).parent.mkdir(parents=True, exist_ok=True)
    (pkg / B.PAYLOAD_REL).write_text("{}", encoding="utf-8")
    with pytest.raises(B.BuildError, match="本公司資料檔"):
        B.apply(pkg, "sale", commit, "", repo, **kw)


def test_sale_refuses_a_package_that_differs_from_the_git_rebuild(tmp_path):
    repo, commit, pkg, kw = _sale(tmp_path)
    (pkg / "backend" / "main.py").write_text("print('changed after archive')\n", encoding="utf-8")
    with pytest.raises(B.BuildError, match="與 git 重算不一致"):
        B.apply(pkg, "sale", commit, "", repo, **kw)


def test_sale_refuses_a_forbidden_path_that_slipped_in(tmp_path):
    repo, commit, pkg, kw = _sale(tmp_path)
    (pkg / "docs" / "windows").mkdir(parents=True)
    (pkg / "docs" / "windows" / "STATE.md").write_text("x\n", encoding="utf-8")
    (pkg / "NEXT-SESSION.md").write_text("x\n", encoding="utf-8")
    # docs/** 會被剪掉，但根目錄的 NEXT-SESSION.md 不在 remove ⇒ verify 擋
    with pytest.raises(B.BuildError, match="NEXT-SESSION.md"):
        B.apply(pkg, "sale", commit, "", repo, **kw)


def test_unknown_audience_is_refused(tmp_path):
    repo, commit, pkg, kw = _sale(tmp_path)
    with pytest.raises(B.BuildError):
        B.apply(pkg, "both", commit, "", repo, **kw)


def test_cli_writes_the_json_and_returns_nonzero_on_failure(tmp_path, capsys):
    repo, commit, pkg, kw = _sale(tmp_path)
    out = tmp_path / "deid.json"
    assert B.main(["apply", "--pkg", str(pkg), "--audience", "sale", "--commit", commit, "--product", "", "--repo", str(repo),
                   "--key", kw["key"], "--hashlist", kw["hashlist"], "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["audience"] == "sale" and "DEID_BUILD_OK" in capsys.readouterr().out
    repo2, commit2 = _tiny_repo(tmp_path / "again")
    pkg2 = _pkg(tmp_path / "again", repo2, commit2)
    assert B.main(["apply", "--pkg", str(pkg2), "--audience", "own", "--commit", commit2, "--product", "", "--repo", str(repo2), "--out", str(tmp_path / "o.json")]) == 1
    assert "DEID_BUILD_FAIL" in capsys.readouterr().out


# ── 建包腳本接線（原始碼層；整支建包要跑全量測試，不在這裡實跑）──────────────────────────────────

def test_build_script_wires_the_audience_step_before_the_manifest_is_written():
    src = (REPO / "backend" / "tools" / "build_deploy_package.ps1").read_text(encoding="utf-8-sig")
    assert '[ValidateSet("own", "sale")]' in src and '[string]$Audience = "own"' in src
    for p in ("$OwnPayload", "$DeidKey", "$DeidHashlist"):
        assert "[string]%s" % p in src
    call, manifest = src.index("deid_build.py"), src.index("$manifest = [ordered]@{")
    assert call < manifest, "去識別化必須在 deploy_manifest 寫出之前跑完（失敗要中止建包）"
    assert "& $pyExe @deidArgs" in src and "去識別化（-Audience $Audience）失敗" in src
    assert "audience             = $Audience" in src and "deid                 = $deidBlock" in src
    assert 'python     = $(if ($Audience -eq "sale") { "" } else { $pyEnv })' in src, "sale 的 manifest 不可記開發機直譯器路徑"
    assert 'Audience -eq "sale" -and $License' in src, "sale 不支援 -License 要明確擋"
