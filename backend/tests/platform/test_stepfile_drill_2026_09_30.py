"""T22-1：stepfile_drill——步驟檔逐行演練（非 git 安裝目錄）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import stepfile_drill as SD  # noqa: E402

FENCE = "```"
NAME = "20260929_161131_b6182dbf_full"
STAGE = (r'python <ROOT>\backend\tools\delivery.py stage --root "H:\我的雲端硬碟\MOTRIX-交付" --name ' + NAME +
         r' --staging <ROOT>\..\motrix-staging')


def _verify_pkg(expect):
    return (r'python <ROOT>\backend\tools\verify_package.py <ROOT>\..\motrix-staging' + "\\" + NAME +
            r'\payload --expect-db-version %d' % expect)


def _current_db_version():
    """期望值跟著這棵樹的 db.CURRENT_VERSION（基準由 V9 凍結；第 46 班 116→118 時這裡曾是寫死的 116 而紅）。"""
    import re
    src = (Path(__file__).resolve().parents[2] / "db.py").read_text(encoding="utf-8")
    return int(re.search(r"^CURRENT_VERSION\s*=\s*(\d+)", src, re.M).group(1))


VERIFY_PKG = _verify_pkg(_current_db_version())


def _md(*step1_blocks):
    parts = ["# x\n## 步驟 0：前置\n%spowershell\necho zero\n%s\n## 步驟 1：取包並驗證\n" % (FENCE, FENCE)]
    parts += ["%spowershell\n%s\n%s\n" % (FENCE, b, FENCE) for b in step1_blocks]
    parts.append("## 步驟 2：套用\n%spowershell\necho two\n%s\n" % (FENCE, FENCE))
    return "".join(parts)


def test_extract_only_requested_step():
    md = _md(STAGE)
    assert [n for n, _ in SD.extract_blocks(md, (1,))] == [1]
    assert len(SD.extract_blocks(md, (0, 2))) == 2


def test_substitute_fills_root_delivery_and_name():
    _n, b = SD.extract_blocks(_md(STAGE), (1,))[0]
    out = SD.substitute(b, r"D:\i", r"D:\deliver", "20260930_000000_aaaaaaaa_full")
    assert r"D:\i\backend" in out and r'"D:\deliver"' in out and "20260930_000000_aaaaaaaa_full" in out
    assert "<ROOT>" not in out and "H:" not in out


def test_static_path_check_catches_missing_payload(tmp_path):
    """正對照：步驟檔少寫 payload\\（第二十二班第二次擋下的原因）必須被抓到；寫對的不報。"""
    stg = tmp_path / "motrix-staging"
    (stg / "pkg" / "payload" / "backend" / "tools").mkdir(parents=True)
    good = r'Copy-Item "%s\pkg\payload\backend\tools\*" x' % stg
    bad = r'Copy-Item "%s\pkg\backend\tools\*" x' % stg
    assert SD.path_problems(good, stg) == []
    assert SD.path_problems(bad, stg)


def test_drill_refuses_inside_a_git_repo(tmp_path):
    """演練目錄在 git repo 內 ⇒ 拒絕（否則 git 檢查意外成功，演練綠、正式機紅）。"""
    import subprocess
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    step = tmp_path / "s.md"
    step.write_text(_md(STAGE), encoding="utf-8")
    import pytest
    with pytest.raises(SD.DrillError):
        SD.drill(str(step), str(tmp_path / "w"), (1,))
    assert not list((tmp_path / "w").iterdir())


def _run(tmp_path, monkeypatch, verify=None, **kw):
    """%TEMP% 在家目錄 repo 之內 ⇒ 用 GIT_CEILING_DIRECTORIES 讓 git 不往上找（等同正式機「上面沒有 repo」）。"""
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    step = tmp_path / "s.md"
    step.write_text(_md(STAGE, verify or VERIFY_PKG), encoding="utf-8")
    work = tmp_path / "w"
    rep = SD.drill(str(step), str(work), (1,), **kw)
    assert not list(work.iterdir())                                     # 用完清掉
    return rep


def test_drill_nongit_install_passes_verify_package_with_the_package_list(tmp_path, monkeypatch):
    """T22-2：非 git 安裝目錄＋包內不出貨清單 ⇒ 第二十二班步驟 1 的 stage／verify／verify_package 全部 exit 0（原本 2 項 FAIL）。"""
    rep = _run(tmp_path, monkeypatch)
    tails = " | ".join(b["tail"] for b in rep["blocks"])
    assert rep["blocks"][0]["exit"] == 0, tails
    assert not rep["blocks"][1]["static"], rep["blocks"][1]["static"]
    assert rep["blocks"][1]["exit"] == 0, tails
    assert rep["ok"] is True


def test_drill_nongit_install_without_the_list_still_fails(tmp_path, monkeypatch):
    """反向控制：包內沒有清單 ⇒ verify_package 紅（不是略過）。"""
    rep = _run(tmp_path, monkeypatch, write_ignore_list=False)
    assert rep["blocks"][1]["exit"] != 0
    assert "export_ignore" in rep["blocks"][1]["tail"] or rep["ok"] is False


def test_drill_wrong_expected_db_version_still_fails_verify_package(tmp_path, monkeypatch):
    """檢查要保持有意義：期望值給錯（少 1）⇒ verify_package 必須失敗，且訊息點出版本不符。"""
    rep = _run(tmp_path, monkeypatch, verify=_verify_pkg(_current_db_version() - 1))
    assert rep["blocks"][1]["exit"] != 0
    assert "db 版本" in rep["blocks"][1]["tail"]
