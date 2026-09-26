"""core-only 反向控制：把 backend/modules/ 底下的 L2 模組**全部**拿掉，跑 tests/platform，允許清單以外必須全綠。

為什麼要有：守門的結果不可以隨「裝了哪些模組」而改變（例：G1 快照原本依「L2 有沒有在用」決定 L1 公開介面，
拿掉 M04 就報「刪除、要升主版號」）。每搬一個模組才在它的反向控制裡抓到一題太慢——這支一次把整類擋掉。
PLAYBOOK §G3：每一班列車跑一次（對列車 HEAD）。

用法（repo 根目錄）：
  python tools/platform/core_only_rc.py [--commit <SHA>] [--workers 2] [--keep] [--window X]
做法：
  1. `git worktree add --no-checkout --detach` 一棵拋棄式樹（%TEMP%\\motrix-coreonly-<sha>），不碰任何人的工作樹
  2. `git sparse-checkout set --no-cone '/*' '!/backend/modules/<key>/' …`（該 commit 裡每個有 module.json 的模組各一條），再 `git checkout`
     ⇒ 模組資料夾從一開始就不存在，**不刪任何檔**（刪資料夾會被權限規則擋下，稽核 ⑰ 與 C 都被擋過；主持 2026-09-26 裁示），也不會留 __pycache__
  3. 低優先權跑 `pytest tests/platform -n <workers> --continue-on-collection-errors`（收集錯誤也算不過，PLAYBOOK §B-11）
  4. 判定（judge）：有跑到題、紅燈 ⊆ ALLOWED ∪ 已知紅清單（tools/platform/core_only_known_red.json）、清單上沒有已轉綠的 ⇒ ok
輸出：stdout 最後一行一份 JSON（commit、removed、failed、allowed_hit、known_hit、unexpected、stale_known、ok、reasons）。
清理：`git worktree remove --force` 只移除自己建的那棵樹；basetemp 一律刪（--keep 保留工作樹）。
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


def module_keys_at(sha):
    """該 commit 裡 backend/modules/ 底下有 module.json 的資料夾名（讀 git，不讀工作樹）。"""
    out = []
    for name in _git("ls-tree", "-d", "--name-only", sha, "backend/modules/").splitlines():
        key = name.rstrip("/").split("/")[-1]
        if _git("ls-tree", "--name-only", sha, "backend/modules/%s/module.json" % key):
            out.append(key)
    return sorted(out)


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


#: 已知紅清單（AUDIT-D-B-G1 G-M1）：repo 內的相對位置；判定時讀「被測那一版」樹裡的這個檔
KNOWN_RED_REL = "tools/platform/core_only_known_red.json"


def load_known(path):
    """已知紅清單 ⇒ {題: 那一筆}。檔案不在 ⇒ 空（沒有已知紅）。"""
    p = Path(path)
    if not p.is_file():
        return {}
    return {e["test"]: e for e in json.loads(p.read_text(encoding="utf-8"))["entries"]}


KNOWN_FIELDS = ("test", "owner", "fix_branch", "registered_at", "ruling")


def validate_known(entries, runplan_text, backend):
    """已知紅清單的每一筆 ⇒ 問題清單（空＝合格）。
    - 欄位齊（題名、擁有者、預計修復分支、登記時間、裁示錨點）、題名不重複
    - 題真的存在（檔案在、函式有定義）——題改名或刪掉還留在清單上 ⇒ 報
    - **裁示**：RUN-PLAN 裡有一行同時寫著錨點與題的函式名（新增一筆＝先有主持裁示；清單不可以自己長）"""
    import re
    problems, seen = [], set()
    lines = runplan_text.splitlines()
    for e in entries:
        miss = [k for k in KNOWN_FIELDS if not str(e.get(k) or "").strip()]
        if miss:
            problems.append("%s：缺欄位 %s" % (e.get("test"), miss))
            continue
        t = e["test"]
        if t in seen:
            problems.append("%s：重複" % t)
        seen.add(t)
        f, _, name = t.partition("::")
        func = name.split("::")[-1].split("[")[0]
        src = Path(backend) / f
        if not src.is_file() or not re.search(r"^\s*(async\s+)?def %s\(" % re.escape(func),
                                              src.read_text(encoding="utf-8"), re.M):
            problems.append("%s：題不存在（檔案或函式找不到）" % t)
        if not any(e["ruling"] in l and func in l for l in lines):
            problems.append("%s：RUN-PLAN 找不到同時寫著「%s」與題名的裁示行" % (t, e["ruling"]))
    return problems


def total_cases(junit_path):
    return sum(1 for _ in ET.parse(str(junit_path)).getroot().iter("testcase"))


def judge(failed, total, pytest_exit, known, allowed=ALLOWED):
    """列車判定 ⇒ dict。ok＝有跑到題、紅燈 ⊆ 允許 ∪ 已知紅、已知紅沒有一筆已轉綠。
    - 一題都沒跑（exit 5 或 0 題）⇒ 不算過（G-S1：「沒有紅」不等於「驗過了」）
    - 清單上的題已經綠了還留著 ⇒ 不算過（stale；清單不可以退化成「全寫進去就變綠」）"""
    failed = set(failed)
    known = set(known)
    res = {"total": total,
           "allowed_hit": sorted(failed & allowed),
           "known_hit": sorted(failed & known - allowed),
           "unexpected": sorted(failed - allowed - known),
           "stale_known": sorted(known - failed)}
    reasons = []
    if pytest_exit == 5 or total == 0:
        reasons.append("一題都沒跑（exit %s、%d 題）" % (pytest_exit, total))
    if res["unexpected"]:
        reasons.append("非預期紅 %d 題" % len(res["unexpected"]))
    if res["stale_known"]:
        reasons.append("已知紅清單有 %d 筆已轉綠，要從清單刪掉" % len(res["stale_known"]))
    res["ok"] = not reasons
    res["reasons"] = reasons
    return res


def run(commit="HEAD", workers=2, keep=False, window="coreonly"):
    sha = _git("rev-parse", "--short=8", commit)
    tree = Path(tempfile.gettempdir()) / ("motrix-coreonly-%s" % sha)
    basetemp = Path(tempfile.gettempdir()) / ("motrix-pytest-%s-%s" % (window, sha))
    out = {"commit": sha, "tree": str(tree)}
    if tree.exists():
        raise SystemExit("拋棄式樹已存在（上一輪沒清掉？）：%s ⇒ 確認沒人在用後手動刪除" % tree)
    removed = module_keys_at(sha)
    _git("worktree", "add", "--no-checkout", "--detach", str(tree), sha)
    try:
        patterns = ["/*"] + ["!/backend/modules/%s/" % k for k in removed]
        _git("sparse-checkout", "set", "--no-cone", *patterns, cwd=tree)
        _git("checkout", cwd=tree)
        backend = tree / "backend"
        out["removed"] = removed
        assert (backend / "main.py").is_file(), "sparse checkout 沒有把 L1 取出來"
        assert not module_dirs(backend), "模組資料夾還在：%s" % [d.name for d in module_dirs(backend)]
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
        out["failed"] = len(failed)
        out.update(judge(failed, total_cases(junit), proc.returncode, load_known(tree / KNOWN_RED_REL)))
        return out
    finally:
        _rmtree(basetemp)
        if not keep:
            # 只移除自己建的那棵樹（git 自己的移除；不另外遞迴刪資料夾）
            r = subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=str(REPO),
                               capture_output=True, text=True, encoding="utf-8")
            if r.returncode:
                out["cleanup_error"] = "git worktree remove 失敗（請手動確認後移除 %s）：%s" % (tree, r.stderr.strip())


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
    for x in res.get("stale_known", []):
        print("  已知紅已轉綠（要從清單刪掉）：%s" % x)
    for x in res.get("reasons", []):
        print("  不過：%s" % x)
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
