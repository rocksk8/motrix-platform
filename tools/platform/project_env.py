"""專案專用 Python 環境（主工作樹的 .venv）：建立、定位、與正式機環境比對。

用法：
  python tools/platform/project_env.py create [--python 3.13]   建 <主工作樹>/.venv，照 requirements.txt＋requirements-dev.txt 安裝
  python tools/platform/project_env.py check                    比對 .venv 與 backend/tools/prod_env.json（正式機環境）
  python tools/platform/project_env.py where                    印出專案 python 的路徑（沒有就非 0）

為什麼：這台機器的 `python` 是別人的 venv（hermes-agent），測試一直跑在一個「剛好什麼都有」的環境裡；
正式機照 requirements.txt 安裝，而我們從沒在那樣的環境裡驗證過（2026-09-25 A 觀察、B 建立）。
版本可換：正式機的 Python 版本確定後（prod_env.json），用 --python 重建即可。
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[2]
import os

#: 專案環境的資料夾名（主工作樹底下）；可用環境變數 MOTRIX_PROJECT_VENV 指定別的受測版本（例：.venv313）。
#: 2026-09-25 使用者裁示「Python 版本不綁定」：.venv312 只是其中一個受測版本，不是規格。
VENV_DIR = os.environ.get("MOTRIX_PROJECT_VENV") or ".venv312"
#: 支援的 Python 下限（只設下限、不設上限；已實測 3.11／3.12／3.13）。同一個數字寫在 backend/requirements.txt 註解。
PYTHON_MIN = (3, 11)
#: 比對時一定要看的套件（產品執行期）
KEY_PACKAGES = ("fastapi", "starlette", "uvicorn", "pydantic", "pydantic-core", "cryptography", "webauthn",
                "openpyxl", "pypdf", "pillow", "boto3", "pyotp", "qrcode", "python-multipart")


def main_worktree_root():
    """主工作樹（.venv 只建一份，worktree 共用）。"""
    try:
        common = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                capture_output=True, text=True, check=True).stdout.strip()
        return Path(common).parent
    except (OSError, subprocess.CalledProcessError):
        return REPO


def venv_python():
    p = main_worktree_root() / VENV_DIR / "Scripts" / "python.exe"
    if not p.is_file():
        p2 = main_worktree_root() / VENV_DIR / "bin" / "python"
        return p2 if p2.is_file() else None
    return p


def _norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def venv_facts(py):
    code = ("import sys,json,importlib.metadata as m;"
            "print(json.dumps({'python':sys.version.split()[0],"
            "'packages':{d.metadata['Name']:d.version for d in m.distributions()}}))")
    out = subprocess.run([str(py), "-c", code], capture_output=True, text=True, check=True).stdout
    facts = json.loads(out)
    facts["packages"] = {_norm(k): v for k, v in facts["packages"].items()}
    return facts


def parse_prod_env(data):
    """prod_env.json ⇒ {"python": "3.x.y", "packages": {name: version}}。接受 pip freeze 文字或 dict。"""
    py = str(data.get("pythonVersion") or data.get("python") or "").replace("Python", "").strip()
    pk = data.get("pipFreeze") or data.get("pip_freeze") or data.get("packages") or {}
    if isinstance(pk, str):
        pk = pk.splitlines()
    if isinstance(pk, list):
        d = {}
        for line in pk:
            m = re.match(r"^\s*([A-Za-z0-9_.\-]+)==([^\s;]+)", line)
            if m:
                d[_norm(m.group(1))] = m.group(2)
        pk = d
    return {"python": py, "packages": {_norm(k): v for k, v in pk.items()}}


def in_supported_range(version):
    """版本字串是否 ≥ PYTHON_MIN（沒有上限）；讀不懂 ⇒ False。"""
    nums = [int(x) for x in re.findall(r"\d+", version or "")[:2]]
    return len(nums) == 2 and tuple(nums) >= PYTHON_MIN


def compare(venv, prod):
    """提示清單（空＝沒有要提示的）。**只提示、不擋**（使用者裁示：不綁 Python 版本）：
    正式機版本不在支援範圍 ⇒ 警告；在範圍內 ⇒ 不比 Python 版本，只列關鍵套件版本差異。"""
    diffs = []
    if not in_supported_range(prod["python"]):
        diffs.append("⚠ 正式機 Python %s 不在支援範圍（≥%d.%d）" % (prod["python"] or "（未知）", *PYTHON_MIN))
    for k in KEY_PACKAGES:
        a, b = venv["packages"].get(k), prod["packages"].get(k)
        if a != b:
            diffs.append("%s：專案 %s ≠ 正式機 %s" % (k, a or "（沒裝）", b or "（沒裝）"))
    return diffs


def cmd_check():
    py = venv_python()
    if py is None:
        print("⚠ 找不到專案環境（%s）⇒ 先跑 project_env.py create" % (main_worktree_root() / VENV_DIR))
        return 2
    prod_file = REPO / "backend" / "tools" / "prod_env.json"
    if not prod_file.is_file():
        prod_file = main_worktree_root() / "backend" / "tools" / "prod_env.json"
    if not prod_file.is_file():
        print("提示：還沒取得正式機環境（backend/tools/prod_env.json 不存在；使用者在儀表板按一次「部署前健康檢查」即產生）"
              "\n  ⇒ 目前的測試結果代表專案環境 %s（Python %s）。" % (VENV_DIR, venv_facts(py)["python"]))
        return 0
    facts = venv_facts(py)
    prod = parse_prod_env(json.loads(prod_file.read_text(encoding="utf-8-sig")))
    diffs = compare(facts, prod)
    print("專案 %s（Python %s）／正式機 Python %s" % (VENV_DIR, facts["python"], prod["python"] or "（未知）"))
    if diffs:
        print("提示（不擋）：\n  " + "\n  ".join(diffs))
    else:
        print("✓ 正式機在支援範圍內；%d 個關鍵套件版本相同" % len(KEY_PACKAGES))
    return 0


def cmd_create(pyver):
    root = main_worktree_root()
    venv = root / VENV_DIR
    subprocess.run(["py", "-%s" % pyver, "-m", "venv", str(venv)], check=True)
    py = venv_python()
    subprocess.run([str(py), "-m", "pip", "install", "-q", "--upgrade", "pip"], check=True)
    subprocess.run([str(py), "-m", "pip", "install", "-q", "-r", str(REPO / "backend" / "requirements.txt"),
                    "-r", str(REPO / "backend" / "requirements-dev.txt")], check=True)
    # playwright 的瀏覽器版本跟著套件版本走：新裝的 playwright 要自己的 chromium build，否則 e2e 全部啟動失敗
    subprocess.run([str(py), "-m", "playwright", "install", "chromium"], check=True)
    print("✓ %s（%s）" % (py, venv_facts(py)["python"]))
    return cmd_check()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("--python", default="3.12", help="正式機是 3.12（autostart.bat 用 Python312/Scripts/uvicorn.exe，主持 2026-09-25 查證）")
    sub.add_parser("check")
    sub.add_parser("where")
    a = ap.parse_args(argv)
    if a.cmd == "create":
        return cmd_create(a.python)
    if a.cmd == "check":
        return cmd_check()
    py = venv_python()
    print(py or "（沒有專案 .venv）")
    return 0 if py else 2


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
