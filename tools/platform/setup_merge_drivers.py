"""登記 CHANGELOG／version_manifest 的 git 合併驅動（PLAYBOOK §G6；每個 clone 做一次，worktree 共用）。

用法（repo 或任何 worktree 內）：
  D:\\MOTRIX-PLATFORM\\.venv312\\Scripts\\python.exe tools/platform/setup_merge_drivers.py            登記／更新
  ... setup_merge_drivers.py --check     檢查已登記而且複本是最新（exit 0／1；列車長開車前跑）
  ... setup_merge_drivers.py --remove    移除登記（之後回到一般衝突）

做法：把 tools/platform/merge_drivers.py 複製到 `<git 共用目錄>/motrix/merge_drivers.py`（不隨 checkout 變動：
舊分支上沒有這支檔也照樣能跑），再寫 repo 本地 git config：
  merge.motrix-changelog.driver = "<python>" "<複本>" changelog %O %A %B %P
  merge.motrix-manifest.driver  = "<python>" "<複本>" manifest  %O %A %B %P
對應的 .gitattributes 已在 repo 裡。沒登記的機器：git 找不到驅動 ⇒ 一般三方合併（照常出衝突，不會靜默少東西）。
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "merge_drivers.py"
DRIVERS = {"motrix-changelog": "changelog", "motrix-manifest": "manifest"}


def _git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8")
    if check and r.returncode != 0:
        raise SystemExit("git %s 失敗：%s" % (" ".join(args), r.stderr.strip()))
    return r


def common_dir(repo):
    p = Path(_git(repo, "rev-parse", "--git-common-dir").stdout.strip())
    return (Path(repo) / p).resolve() if not p.is_absolute() else p


def _posix(p):
    return str(p).replace("\\", "/")


def expected(repo, python=None):
    """⇒ (複本路徑, {config 鍵: 值})。"""
    copy = common_dir(repo) / "motrix" / "merge_drivers.py"
    py = _posix(python or sys.executable)
    cfg = {}
    for name, kind in DRIVERS.items():
        cfg["merge.%s.name" % name] = "MOTRIX %s（兩邊的新增都留；看不懂就一般衝突）" % kind
        cfg["merge.%s.driver" % name] = '"%s" "%s" %s %%O %%A %%B %%P' % (py, _posix(copy), kind)
    return copy, cfg


def problems(repo):
    """⇒ [問題]；空＝已登記而且複本是最新。"""
    copy, cfg = expected(repo)
    out = []
    for k in cfg:
        if not k.endswith(".driver"):
            continue
        got = _git(repo, "config", "--get", k, check=False).stdout.strip()
        if not got:
            out.append("沒有登記 %s" % k)
        elif _posix(copy) not in got:
            out.append("%s 指向別的檔：%s" % (k, got))
    if not copy.is_file():
        out.append("複本不存在：%s" % copy)
    elif copy.read_bytes() != SOURCE.read_bytes():
        out.append("複本過期（tools/platform/merge_drivers.py 改過）：重跑 setup_merge_drivers.py")
    return out


def install(repo, python=None):
    copy, cfg = expected(repo, python)
    copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SOURCE, copy)
    for k, v in cfg.items():
        _git(repo, "config", k, v)
    return copy


def remove(repo):
    for name in DRIVERS:
        _git(repo, "config", "--remove-section", "merge.%s" % name, check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--remove", action="store_true")
    a = ap.parse_args(argv)
    if a.remove:
        remove(a.repo)
        print("已移除 motrix 合併驅動登記")
        return 0
    if a.check:
        bad = problems(a.repo)
        print("合併驅動：%s" % ("OK" if not bad else "；".join(bad)))
        return 1 if bad else 0
    copy = install(a.repo)
    print("已登記 motrix-changelog／motrix-manifest（複本 %s）" % copy)
    return 0


if __name__ == "__main__":
    try:                                                              # 背景執行不彈視窗（tools/platform/nowindow.py；MOTRIX_SHOW_WINDOWS=1 可關）
        import sys as _s, pathlib as _p
        _s.path.insert(0, str(_p.Path(__file__).resolve().parents[0]))
        import nowindow as _nw
        _nw.install()
    except ImportError:
        pass
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
