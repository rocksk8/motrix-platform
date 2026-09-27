"""建包挑 Python（IMPROVEMENT-REPORT §6 第 3 項；2026-09-27）。

D7 建包挑到 PATH 第一支 hermes-agent 的 venv（別的工具的環境，import 得到所有依賴）。改成：
① 專案 venv（主工作樹的 .venv312；MOTRIX_PROJECT_VENV 可換）優先；
② 合格＝import 得到＋滿足 requirements.txt＋requirements-dev.txt 的版本規格（backend/tools/check_py_deps.py，含 httpx2）。
乾跑入口 `build_deploy_package.ps1 -WhichPython`：只挑直譯器、印 `WHICH_PYTHON=<路徑>`，不動 git、不打包。
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
BUILD = BACKEND / "tools" / "build_deploy_package.ps1"
sys.path.insert(0, str(BACKEND / "tools"))
import check_py_deps as C  # noqa: E402


def _reqs(*lines):
    return [("req.txt:%d" % i, l) for i, l in enumerate(lines, 1)]


def test_spec_check_reports_missing_old_and_accepts_satisfied():
    got = C.problems(_reqs("fastapi>=0.111.0", "httpx2>=2.0", "pytest>=8.0", "Pillow>=10"),
                     {"fastapi": "0.110.0", "pytest": "9.1.1", "pillow": "10.4.0"})
    assert got == ["req.txt:1 fastapi: installed 0.110.0, need >=0.111.0",
                   "req.txt:2 httpx2: not installed (need >=2.0)"]


def test_spec_check_skips_markers_that_do_not_apply_and_rejects_unparseable_versions():
    assert C.problems(_reqs('pywin32>=300; sys_platform == "nonexistent-os"'), {}) == []
    assert C.problems(_reqs("foo>=1.0"), {"foo": "not-a-version"}) == ["req.txt:1 foo: installed not-a-version, need >=1.0"]
    assert C.problems(_reqs("foo"), {"foo": "0.0.1"}) == []


def test_default_files_include_the_dev_key_package():
    names = [l.split(">")[0].split("=")[0].strip().lower() for _w, l in C.read_requirements(C.DEFAULT_FILES)]
    assert "httpx2" in names and "fastapi" in names and "pytest-xdist" in names


def test_cli_exit_codes(tmp_path):
    bad = tmp_path / "r.txt"
    bad.write_text("httpx2>=999\n", encoding="utf-8")
    r = subprocess.run([sys.executable, "-B", str(BACKEND / "tools" / "check_py_deps.py"), str(bad)],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 1 and "httpx2" in r.stdout and "need >=999" in r.stdout, r.stdout
    r = subprocess.run([sys.executable, "-B", str(BACKEND / "tools" / "check_py_deps.py"), str(tmp_path / "missing.txt")],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 2 and "cannot check" in r.stdout, r.stdout


def test_step_2_5_uses_the_shared_selection():
    src = BUILD.read_text(encoding="utf-8-sig")
    assert src.count("function Select-MotrixPython") == 1 and "$sel = Select-MotrixPython" in src
    i = src.index("function Select-MotrixPython")
    body = src[i:src.index("\n}", i)]
    assert body.index("Get-ProjectVenvPython") < body.index("Get-Command python -All"), "專案 venv 要排在 PATH 之前"
    assert "check_py_deps.py" in body and "httpx2" in body
    assert src.count("Get-Command python -All") == 1, "Step 2.5 不可以再有自己的一份挑選迴圈"


def _project_venv():
    sys.path.insert(0, str(REPO / "tools" / "platform"))
    import project_env
    return project_env.venv_python()


def _which(env_extra=None):
    env = dict(os.environ, **(env_extra or {}))
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                        "[Console]::OutputEncoding = [Text.Encoding]::UTF8; & '%s' -WhichPython; exit $LASTEXITCODE" % BUILD],
                       capture_output=True, text=True, encoding="utf-8", cwd=str(REPO), env=env, timeout=300)
    line = next((l for l in r.stdout.splitlines() if l.startswith("WHICH_PYTHON=")), None)
    assert line is not None, (r.returncode, r.stdout[-1500:], r.stderr[-1500:])
    return line.split("=", 1)[1].strip(), r.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="部署腳本只在 Windows 上跑")
def test_dry_run_picks_the_project_venv_first():
    proj = _project_venv()
    if proj is None:
        pytest.skip("這台沒有專案 venv（tools/platform/project_env.py create）")
    got, out = _which({"MOTRIX_PROJECT_VENV": ""})
    assert Path(got) == Path(proj), out[-1500:]


@pytest.mark.skipif(sys.platform != "win32", reason="部署腳本只在 Windows 上跑")
def test_dry_run_rejects_every_interpreter_that_fails_the_version_spec():
    """反向控制：多一條沒有人滿足的需求（httpx2>=999）⇒ import 得到也不採用（[版本]），全部不合格 ⇒ 挑不到、exit 2。"""
    env = dict(os.environ, MOTRIX_DEPS_EXTRA_REQUIREMENT="httpx2>=999")
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                        "[Console]::OutputEncoding = [Text.Encoding]::UTF8; & '%s' -WhichPython; exit $LASTEXITCODE" % BUILD],
                       capture_output=True, text=True, encoding="utf-8", cwd=str(REPO), env=env, timeout=300)
    assert r.returncode == 2 and "WHICH_PYTHON=\n" in r.stdout.replace("\r", "") and "[版本]" in r.stdout, r.stdout[-1500:]


@pytest.mark.skipif(sys.platform != "win32", reason="部署腳本只在 Windows 上跑")
def test_dry_run_without_a_project_venv_falls_back_and_says_so():
    """反向控制：指到不存在的專案 venv ⇒ 不是挑它、輸出寫明「專案 venv：沒有」（挑選邏輯真的看專案 venv，不是剛好 PATH 第一支）。"""
    got, out = _which({"MOTRIX_PROJECT_VENV": ".venv-does-not-exist-xyz"})
    assert "專案 venv：沒有" in out, out[-1500:]
    proj = _project_venv()
    assert proj is None or Path(got) != Path(proj)
