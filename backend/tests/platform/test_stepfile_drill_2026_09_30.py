"""T22-1：stepfile_drill——步驟檔逐行演練（非 git 安裝目錄）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import stepfile_drill as SD  # noqa: E402

FENCE = "```"
NAME = "20260929_161131_b6182dbf_full"
STAGE = (r'python <ROOT>\backend\tools\delivery.py stage --root "H:\我的雲端硬碟\MOTRIX-交付" --name ' + NAME +
         r' --staging <ROOT>\..\motrix-staging')
VERIFY_PKG = (r'python <ROOT>\backend\tools\verify_package.py <ROOT>\..\motrix-staging' + "\\" + NAME +
              r'\payload --expect-db-version 116')


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


def test_drill_reproduces_prod_nongit_failure(tmp_path, monkeypatch):
    """演練安裝目錄非 git ⇒ verify_package 4a 的 git check-attr 失敗，與正式機第二十二班相同（不在演練裡被吞掉）。
    %TEMP% 在家目錄 repo 之內 ⇒ 用 GIT_CEILING_DIRECTORIES 讓 git 不往上找（等同正式機「上面沒有 repo」）。"""
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    step = tmp_path / "s.md"
    step.write_text(_md(STAGE, VERIFY_PKG), encoding="utf-8")
    work = tmp_path / "w"
    rep = SD.drill(str(step), str(work), (1,))
    tails = " | ".join(b["tail"] for b in rep["blocks"])
    assert rep["blocks"][0]["exit"] == 0, tails
    assert not rep["blocks"][1]["static"], rep["blocks"][1]["static"]
    assert rep["blocks"][1]["exit"] != 0, tails
    assert not list(work.iterdir())                                     # 用完清掉
