"""相依套件已知弱點掃描（2026-09-07，B5 優化事項）。

正式機長期不重建 Python 環境，requirements.txt 只寫 `>=` 下限、實際安裝的版本
可能停在有已知 CVE 的舊版上都沒人發現。這支工具跑 `pip-audit` 對照 PyPI 的
弱點資料庫（PyPA Advisory Database），分別掃 requirements.txt（正式機服務
實際需要的）與 requirements-dev.txt（開發/測試專用，不影響正式機）。

用法：
    pip install pip-audit   # 只需要裝一次
    python tools/check_dependencies.py
    python tools/check_dependencies.py --dev-only     # 只掃 requirements-dev.txt
    python tools/check_dependencies.py --prod-only    # 只掃 requirements.txt

不是排程工具，沒有自動跑的機制——建議之後每次升級套件版本、或間隔性（例如每季）
手動跑一次即可，比照 check_guide_sync.py 這類「需要時才手動執行」的既有工具慣例。
"""
import argparse
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_HERE)


def _run_audit(requirements_file: str, label: str) -> int:
    path = os.path.join(_BACKEND_DIR, requirements_file)
    print(f"\n=== {label} ===")
    if not os.path.exists(path):
        print(f"（找不到 {path}，略過）")
        return 0
    sys.stdout.flush()  # 避免跟子行程自己的輸出交錯（尤其輸出被導向檔案/管線時）
    result = subprocess.run(
        [sys.executable, "-m", "pip_audit", "-r", path],
        cwd=_BACKEND_DIR,
    )
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dev-only", action="store_true", help="只掃 requirements-dev.txt")
    parser.add_argument("--prod-only", action="store_true", help="只掃 requirements.txt")
    args = parser.parse_args()

    try:
        import pip_audit  # noqa: F401
    except ImportError:
        print("找不到 pip-audit，請先執行：pip install pip-audit")
        return 1

    exit_code = 0
    if not args.dev_only:
        exit_code |= _run_audit("requirements.txt", "正式機服務相依（requirements.txt）")
    if not args.prod_only:
        exit_code |= _run_audit("requirements-dev.txt", "開發/測試專用相依（requirements-dev.txt）")

    print()
    if exit_code:
        print("⚠ 發現已知弱點，見上方明細；Fix Versions 欄位是建議升級到的版本。")
    else:
        print("✓ 沒有發現已知弱點。")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
