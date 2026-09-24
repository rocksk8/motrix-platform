"""建包：同一份 tree 已全綠就沿用測試結果（PLAN-TEST-PERF §3.1）。由 build_deploy_package.ps1 呼叫。

用法：
  python build_test_reuse.py fingerprint                         → {"fingerprint": "...", "components": {...}}（工作樹不乾淨 ⇒ fingerprint 為 null）
  python build_test_reuse.py lookup --records F --fp X           → 可沿用的那一筆（JSON），或 null
  python build_test_reuse.py record --records F --fp X --green 1 --commit C

🔑 指紋＝整棵 tracked tree（`HEAD^{tree}`）＋執行環境。文件不排除：測試會讀 docs/（見
   tests/test_build_test_reuse_2026_09_25.py 的說明）。
🔑 沿用條件：同指紋、**嚴格全綠**（兩段 exit 0，逾時放行不算）、**同一天**、12 小時內；
   同指紋的最新一筆若是紅的，不沿用更早的綠。
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

MAX_HOURS = 12
#: 影響測試結果的 MOTRIX_* 以外的前綴不列；鎖／暫存相關的不影響結果，排除以免每輪指紋都不同。
_ENV_IGNORE = {"MOTRIX_PYTEST_LOCK", "MOTRIX_PYTEST_LOCK_WAIT", "MOTRIX_PYTEST_LOCK_POLL", "MOTRIX_PYTEST_SLOTS",
               "MOTRIX_PYTEST_EXCLUSIVE", "MOTRIX_PYTEST_EXCLUSIVE_OWNER", "MOTRIX_PYTEST_KEEP_BASETEMP"}


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


def current_env():
    """執行環境的組成（會影響測試結果的）。"""
    freeze = subprocess.run([sys.executable, "-m", "pip", "freeze"], capture_output=True, text=True).stdout
    try:
        from importlib.metadata import version
        pw = version("playwright")
    except Exception:  # noqa: BLE001 — 沒裝就記成 None，指紋照樣算
        pw = None
    root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright")
    browsers = sorted(p.name for p in root.iterdir()) if root.is_dir() else []
    return {
        "python": sys.version,
        "pip_freeze": "\n".join(sorted(freeze.splitlines())),
        "playwright": pw,
        "browsers": browsers,
        "motrix_env": {k: v for k, v in sorted(os.environ.items()) if k.startswith("MOTRIX_") and k not in _ENV_IGNORE},
    }


def fingerprint(repo, env=None):
    """工作樹不乾淨（含未追蹤檔）⇒ None（不沿用）。"""
    if _git(repo, "status", "--porcelain").strip():
        return None
    tree = _git(repo, "rev-parse", "HEAD^{tree}").strip()
    env = current_env() if env is None else env
    blob = json.dumps({"tree": tree, "env": env}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def find_reusable(records, fp, now, max_hours=MAX_HOURS):
    """同指紋的**最新一筆**：嚴格全綠、同一天、max_hours 內 ⇒ 回它；否則 None。純函式。"""
    if not fp:
        return None
    same = [r for r in records if r.get("fingerprint") == fp]
    if not same:
        return None
    last = same[-1]          # 紀錄依時間附加 ⇒ 檔案順序就是先後（同一秒寫兩筆時比時間戳分不出來）
    try:
        t = datetime.strptime(last["tested_at"], "%Y-%m-%d %H:%M:%S")
    except (KeyError, ValueError):
        return None
    if last.get("green") is not True or t.date() != now.date():
        return None
    if (now - t).total_seconds() > max_hours * 3600 or t > now:
        return None
    return last


def _read(records):
    p = Path(records)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def lookup(records, fp, now=None):
    return find_reusable(_read(records), fp, now or datetime.now())


def record(records, fp, green, commit):
    p = Path(records)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = {"fingerprint": fp, "tested_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "green": bool(green), "commit": commit}
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fingerprint")
    lk = sub.add_parser("lookup")
    lk.add_argument("--records", required=True)
    lk.add_argument("--fp", required=True)
    rc = sub.add_parser("record")
    rc.add_argument("--records", required=True)
    rc.add_argument("--fp", required=True)
    rc.add_argument("--green", required=True)
    rc.add_argument("--commit", default="")
    a = ap.parse_args(argv)
    repo = _git(Path(__file__).resolve().parent, "rev-parse", "--show-toplevel").strip()
    if a.cmd == "fingerprint":
        print(json.dumps({"fingerprint": fingerprint(repo)}))
    elif a.cmd == "lookup":
        print(json.dumps(lookup(a.records, a.fp), ensure_ascii=False))
    else:
        record(a.records, a.fp, a.green == "1", a.commit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
