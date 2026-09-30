# -*- coding: utf-8 -*-
"""去識別化：部署／維運腳本裡的伺服器 IP 與內網網段（https_setup.ps1、firewall_setup.bat）——自用原樣、sale 由剪段換成參數。

- 自用：只加了 OWN-ONLY 標記行；去掉標記後與加標記之前的版本逐字相同（行為不變）。
- sale：剪段後不含任何 172.16.x；https_setup 的 -Host2 變必填、firewall_setup 的網段改由第一個參數帶入（沒給就用法說明後結束）。
- sale 包不含 fetch_root_ca.ps1、setup_passkey_client.ps1（本公司的遠端取 CA／指紋）。
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
import deid_project as P  # noqa: E402

CFG = P.load_config()
PS = shutil.which("powershell.exe") or shutil.which("powershell")
FILES = ["backend/tools/https_setup.ps1", "firewall_setup.bat"]
BASE = "0a6fc468"          # 加標記之前的提交（wip/w3-prodroot）


def _cut_copy(tmp_path, rel):
    root = tmp_path / "pkg"
    dst = root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REPO / rel, dst)
    P.apply_cuts(root, [c for c in CFG["cuts"] if c["path"] == rel])
    return dst


def _strip(text):
    return "\n".join(ln for ln in text.replace("\r\n", "\n").split("\n") if "OWN-ONLY" not in ln)


@pytest.mark.parametrize("rel", FILES)
def test_own_files_equal_the_pre_marker_blob_once_markers_are_stripped(rel):
    r = subprocess.run(["git", "-C", str(REPO), "show", "%s:%s" % (BASE, rel)], capture_output=True)
    if r.returncode != 0:
        pytest.skip("這棵樹沒有基準提交 %s" % BASE)
    old = r.stdout.decode("utf-8-sig").replace("\r\n", "\n")
    now = (REPO / rel).read_bytes().decode("utf-8-sig").replace("\r\n", "\n")
    assert _strip(now) == old, rel


@pytest.mark.parametrize("rel", FILES)
def test_every_marker_in_these_files_has_a_cut(rel):
    text = (REPO / rel).read_text(encoding="utf-8-sig")
    names = re.findall(r">>> OWN-ONLY:(\S+)", text)
    keys = {(c["path"], c["name"]) for c in CFG["cuts"]}
    assert names and all((rel, n) in keys for n in names), (rel, names)


@pytest.mark.parametrize("rel", FILES)
def test_sale_variant_has_no_internal_network_addresses(tmp_path, rel):
    dst = _cut_copy(tmp_path, rel)
    text = dst.read_text(encoding="utf-8-sig")
    assert "OWN-ONLY" not in text and not re.search(r"172\.16\.\d", text), rel


@pytest.mark.skipif(not PS, reason="需要 Windows PowerShell")
def test_sale_https_setup_parses_and_host2_is_mandatory(tmp_path):
    dst = _cut_copy(tmp_path, "backend/tools/https_setup.ps1")
    r = subprocess.run([PS, "-NoProfile", "-Command",
                        "$e=$null;$t=$null;$a=[System.Management.Automation.Language.Parser]::ParseFile('%s',[ref]$t,[ref]$e);"
                        "$p=$a.ParamBlock.Parameters | Where-Object { $_.Name.VariablePath.UserPath -eq 'Host2' };"
                        "$m=($p.Attributes | ForEach-Object { $_.Extent.Text }) -join ';';"
                        "Write-Output ('ERR=' + $e.Count); Write-Output ('ATTR=' + $m); Write-Output ('DEFAULT=' + [string]($p.DefaultValue -ne $null))" % dst],
                       capture_output=True, timeout=120)
    out = r.stdout.decode("utf-8", "replace")
    assert "ERR=0" in out and "Mandatory" in out and "DEFAULT=False" in out, out


@pytest.mark.skipif(not PS, reason="需要 Windows PowerShell")
def test_own_https_setup_still_parses_with_its_default_host():
    r = subprocess.run([PS, "-NoProfile", "-Command",
                        "$e=$null;$t=$null;[void][System.Management.Automation.Language.Parser]::ParseFile('%s',[ref]$t,[ref]$e);Write-Output ('ERR=' + $e.Count)"
                        % (REPO / "backend/tools/https_setup.ps1")], capture_output=True, timeout=120)
    assert "ERR=0" in r.stdout.decode("utf-8", "replace")


def test_sale_firewall_bat_takes_the_network_from_the_first_argument(tmp_path):
    text = _cut_copy(tmp_path, "firewall_setup.bat").read_text(encoding="utf-8-sig")
    assert 'set "REMOTE=%~1"' in text and "remoteip=%REMOTE%" in text and "exit /b 1" in text
    assert "\r\n" in (tmp_path / "pkg" / "firewall_setup.bat").read_bytes().decode("utf-8"), "批次檔要保持 CRLF"


@pytest.mark.parametrize("script", ["backend/tools/fetch_root_ca.ps1", "backend/tools/setup_passkey_client.ps1"])
def test_own_only_ops_scripts_are_removed_from_sale(script):
    assert P.plan_remove([script], CFG) == [script] and P.matches(script, CFG["forbidden"])


def test_customer_https_doc_does_not_name_a_removed_script():
    doc = (REPO / "product" / "sale_docs" / "HTTPS-DEPLOY-CHECKLIST.md").read_text(encoding="utf-8")
    assert "fetch_root_ca" not in doc and "setup_passkey_client" not in doc
