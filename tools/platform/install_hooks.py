# -*- coding: utf-8 -*-
"""安裝 pre-push hook（推送前自動跑 precheck；紅 ⇒ 擋推送）。每個 clone 做一次；worktree 共用 repo 本地設定，不必每棵樹各裝。

[單位] tools:install_hooks   [層] 工具   [穩定度] 內部
[公開介面] main
[不變式] 只設一個本地 git config（core.hooksPath=.githooks），不複製檔、不碰 .git/hooks；實際登記邏輯在 setup_prepush.py（同一份，不重寫）。

用法（repo 或任何 worktree 內）：
  python tools/platform/install_hooks.py            安裝並檢查（exit 0＝OK）
  python tools/platform/install_hooks.py --check    只檢查（每個視窗開工第一件事）
  python tools/platform/install_hooks.py --remove   移除登記
行為：一般分支 push ⇒ precheck --hook（FAIL 擋；INCOMPLETE 只警告）；train/*、platform ⇒ prepush_check 整合模式（只警告）。
逃生口 `git push --no-verify`：只給緊急（hook／基礎設施本身壞了）；**交件的 SHA 不得使用**（DEV-RULES-TOKEN 第 8 條），用了要在推送說明寫理由。
限制：舊分支沒有 `.githooks/` 或 precheck.py ⇒ hook 靜默略過（不擋），所以交件訊息仍要自己附 PRECHECK PASS 那一行。
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import setup_prepush as SP  # noqa: E402

REPO = HERE.parents[1]


def problems(repo=REPO):
    ps = list(SP.problems(repo))
    hook = Path(repo) / SP.HOOKS_DIR / "pre-push"
    if hook.is_file() and "precheck.py" not in hook.read_text(encoding="utf-8", errors="replace"):
        ps.append("pre-push hook 沒有呼叫 precheck.py（舊版 hook；從 train/t88-int 之後的分支更新 .githooks/）")
    if not (Path(repo) / "tools" / "platform" / "precheck.py").is_file():
        ps.append("找不到 tools/platform/precheck.py")
    return ps


def main(argv=None):
    ap = argparse.ArgumentParser(description="安裝 pre-push hook（推送前跑 precheck）")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--remove", action="store_true")
    a = ap.parse_args(argv)
    if a.remove:
        SP.remove(REPO)
        print("已移除 core.hooksPath")
        return 0
    if not a.check:
        SP.install(REPO)
    ps = problems(REPO)
    print("\n".join(ps) if ps else "OK：pre-push 會跑 precheck（紅 ⇒ 擋；--no-verify 只給緊急，交件不得用）")
    return 1 if ps else 0


if __name__ == "__main__":
    sys.exit(main())
