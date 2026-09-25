"""core-only 反向控制：把 backend/modules/ 底下的 L2 模組**全部**拿掉，跑 tests/platform，允許清單以外必須全綠。

為什麼要有：守門的結果不可以隨「裝了哪些模組」而改變（例：G1 快照原本依「L2 有沒有在用」決定 L1 公開介面，
拿掉 M04 就報「刪除、要升主版號」）。每搬一個模組才在它的反向控制裡抓到一題太慢——這支一次把整類擋掉。
PLAYBOOK §G3：每一班列車跑一次（對列車 HEAD）。

用法（repo 根目錄）：
  python tools/platform/core_only_rc.py [--commit <SHA>] [--workers 2] [--keep] [--window X]
做法：
  1. `git worktree add --detach` 一棵拋棄式樹（%TEMP%\\motrix-coreonly-<sha>），不碰任何人的工作樹
  2. 刪掉 backend/modules/<key>/（有 module.json 的資料夾；modules/__init__.py 保留）
  3. 低優先權跑 `pytest tests/platform -n <workers> --continue-on-collection-errors`（收集錯誤也算不過，PLAYBOOK §B-11）
  4. 失敗（含收集錯誤）扣掉 ALLOWED ⇒ 非空 ⇒ exit 1
輸出：stdout 最後一行一份 JSON（commit、removed、failed、allowed_hit、unexpected、ok）。
清理：工作樹與 basetemp 一律刪（--keep 保留工作樹，basetemp 照刪）。
"""
import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: PLAYBOOK §B-11 允許紅的產生檔一致性題：拿掉模組之後它們反映實際的樹，紅是預期的
ALLOWED = frozenset({
    "tests/platform/test_module_boundaries.py::test_modules_json_lists_only_existing_units",
    "tests/platform/test_unit_cards.py::test_unit_index_is_current",
})

BELOW_NORMAL = 0x00004000   # Windows BELOW_NORMAL_PRIORITY_CLASS（PLAYBOOK §C-13 低優先權）


def _git(*args, cwd=REPO):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout.strip()


def _rmtree(p):
    def _clear(func, path, _exc):
        os.chmod(path, stat.S_IWRITE)
        func(path)
    if Path(p).exists():
        shutil.rmtree(p, onerror=_clear)


def module_dirs(backend):
    root = Path(backend) / "modules"
    return sorted(d for d in root.iterdir() if (d / "module.json").is_file()) if root.is_dir() else []


def failed_ids(junit_path, backend_rel="backend"):
    """junit xml ⇒ 失敗／錯誤的 node id 集合（`tests/platform/x.py::test_y`，參數化保留 [..]）。
    收集錯誤（整檔 import 失敗）以檔案路徑本身表示。"""
    out = set()
    root = ET.parse(str(junit_path)).getroot()
    for case in root.iter("testcase"):
        if case.find("failure") is None and case.find("error") is None:
            continue
        cls, name = case.get("classname", ""), case.get("name", "")
        if not cls:                                   # 收集錯誤：classname 空、name＝模組點路徑
            out.add(name.replace(".", "/") + ".py")
            continue
        f = case.get("file")
        if not f:
            parts = cls.split(".")
            # classname＝tests.platform.test_x（或 ….TestClass）
            mod = [p for p in parts if not p[:1].isupper()]
            f = "/".join(mod) + ".py"
        f = f.replace("\\", "/")
        if f.startswith(backend_rel + "/"):
            f = f[len(backend_rel) + 1:]
        klass = [p for p in cls.split(".") if p[:1].isupper()]
        out.add(f + "::" + "::".join(klass + [name]) if name else f)
    return out


def classify(failed, allowed=ALLOWED):
    """(允許清單命中, 允許清單以外的失敗)。"""
    failed = set(failed)
    return sorted(failed & allowed), sorted(failed - allowed)


def run(commit="HEAD", workers=2, keep=False, window="coreonly"):
    sha = _git("rev-parse", "--short=8", commit)
    tree = Path(tempfile.gettempdir()) / ("motrix-coreonly-%s" % sha)
    basetemp = Path(tempfile.gettempdir()) / ("motrix-pytest-%s-%s" % (window, sha))
    out = {"commit": sha, "tree": str(tree)}
    if tree.exists():
        raise SystemExit("拋棄式樹已存在（上一輪沒清掉？）：%s ⇒ 確認沒人在用後手動刪除" % tree)
    _git("worktree", "add", "--detach", str(tree), sha)
    try:
        backend = tree / "backend"
        removed = [d.name for d in module_dirs(backend)]
        for d in module_dirs(backend):
            _rmtree(d)
        out["removed"] = removed
        assert not module_dirs(backend), "模組沒刪乾淨"
        junit = tree / "coreonly-junit.xml"
        cmd = [sys.executable, "-X", "utf8", "-m", "pytest", "tests/platform", "-q", "-p", "no:cacheprovider",
               "-n", str(workers), "--basetemp=%s" % basetemp, "--continue-on-collection-errors",
               "--junitxml=%s" % junit]
        kw = {"creationflags": BELOW_NORMAL} if os.name == "nt" else {}
        proc = subprocess.run(cmd, cwd=str(backend), capture_output=True, text=True, encoding="utf-8",
                              errors="replace", **kw)
        out["pytest_exit"] = proc.returncode
        out["summary"] = (proc.stdout.strip().splitlines() or [""])[-1]
        if not junit.is_file():
            out.update(ok=False, error="pytest 沒有產生 junit（被中斷？）", tail=proc.stdout[-2000:] + proc.stderr[-1000:])
            return out
        failed = failed_ids(junit)
        hit, unexpected = classify(failed)
        out.update(failed=len(failed), allowed_hit=hit, unexpected=unexpected, ok=not unexpected)
        return out
    finally:
        _rmtree(basetemp)
        if not keep:
            subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=str(REPO),
                           capture_output=True, text=True)
            _rmtree(tree)
            subprocess.run(["git", "worktree", "prune"], cwd=str(REPO), capture_output=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--commit", default="HEAD")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--window", default="coreonly")
    a = ap.parse_args(argv)
    res = run(a.commit, a.workers, a.keep, a.window)
    for x in res.get("unexpected", []):
        print("  非預期紅：%s" % x)
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
