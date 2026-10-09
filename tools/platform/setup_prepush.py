# -*- coding: utf-8 -*-
"""登記推送前檢查的 git hook（SPEEDUP-PREPUSH-T50；每個 clone 做一次，worktree 共用 repo 本地設定）。

用法（repo 或任何 worktree 內；Python＝主工作樹 .venv312）：
  python tools/platform/setup_prepush.py            登記：git config --local core.hooksPath .githooks
  python tools/platform/setup_prepush.py --check    檢查已登記而且 hook 檔都在（exit 0／1；每個視窗開工第一件事）
  python tools/platform/setup_prepush.py --remove   移除登記（之後回到沒有 hook）

做法：只設一個本地 git config（不複製任何檔、不碰 .git/hooks 既有內容）。`.githooks/` 在 repo 裡（追蹤）：
  pre-push   → tools/platform/prepush_check.py（紅 ⇒ 擋；整合分支只警告）
  post-commit→ 只在 train/* 分支排一次背景檢查（tools/platform/integ_watch.py；只寫狀態檔）
沒登記的機器：什麼都不會發生（不會靜默少東西，只是沒有提前檢查）。
"""
import argparse
import subprocess
import sys
from pathlib import Path

HOOKS_DIR = ".githooks"
NEEDED = ("pre-push", "post-commit")


def _git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, r.stdout.strip()


def install(repo):
    rc, out = _git(repo, "config", "--local", "core.hooksPath", HOOKS_DIR)
    if rc != 0:
        raise SystemExit("git config 失敗：%s" % out)


def remove(repo):
    _git(repo, "config", "--local", "--unset", "core.hooksPath")


def problems(repo):
    """⇒ 問題清單（空＝已登記且 hook 檔都在）。"""
    repo = Path(repo)
    out = []
    rc, val = _git(repo, "config", "--local", "--get", "core.hooksPath")
    if val != HOOKS_DIR:
        out.append("core.hooksPath 是 %r，應為 %r（執行 setup_prepush.py）" % (val, HOOKS_DIR))
    rc, top = _git(repo, "rev-parse", "--show-toplevel")
    root = Path(top) if top else repo
    for n in NEEDED:
        if not (root / HOOKS_DIR / n).is_file():
            out.append("缺 %s/%s" % (HOOKS_DIR, n))
    rc, common = _git(repo, "rev-parse", "--git-common-dir")
    old = (Path(repo) / common / "hooks") if common else None
    if old and old.is_dir():
        extra = [p.name for p in old.iterdir() if p.is_file() and not p.name.endswith(".sample") and p.name in NEEDED]
        if extra:
            out.append("%s 內另有既有 hook %s；core.hooksPath 設定後它們不會再被呼叫（確認不需要）" % (old, extra))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--remove", action="store_true")
    a = ap.parse_args(argv)
    repo = Path(__file__).resolve().parents[2]
    if a.remove:
        remove(repo)
        print("已移除 core.hooksPath")
        return 0
    if a.check:
        ps = problems(repo)
        print("\n".join(ps) if ps else "OK：推送前檢查 hook 已登記")
        return 1 if ps else 0
    install(repo)
    ps = problems(repo)
    print("已登記 core.hooksPath=%s" % HOOKS_DIR + (("\n" + "\n".join(ps)) if ps else ""))
    return 1 if ps else 0


if __name__ == "__main__":
    sys.exit(main())
