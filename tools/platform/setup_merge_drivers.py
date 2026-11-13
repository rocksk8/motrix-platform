"""登記 CHANGELOG／version_manifest／基準 JSON／MAX_ENTRIES 的 git 合併驅動（PLAYBOOK §G6；每個 clone 做一次，worktree 共用）。

用法（repo 或任何 worktree 內）：
  D:\\MOTRIX-PLATFORM\\.venv312\\Scripts\\python.exe tools/platform/setup_merge_drivers.py            登記／更新
  ... setup_merge_drivers.py --check     檢查已登記而且複本是最新（exit 0／1；列車長開車前跑）
  ... setup_merge_drivers.py --remove    移除登記（之後回到一般衝突）

直譯器：只接受完整路徑在 `D:\\MOTRIX-PLATFORM\\.venv312` 底下的 python（登記進共用 .git/config，所有 worktree 都會用它跑驅動）；--check 也會比對已登記的直譯器。
做法：把 tools/platform/merge_drivers.py 複製到 `<git 共用目錄>/motrix/merge_drivers.py`（不隨 checkout 變動：
舊分支上沒有這支檔也照樣能跑），再寫 repo 本地 git config：
  merge.motrix-changelog.driver = "<python>" "<複本>" changelog %O %A %B %P
  merge.motrix-manifest.driver  = "<python>" "<複本>" manifest  %O %A %B %P
  merge.motrix-json.driver      = "<python>" "<複本>" json      %O %A %B %P      （基準 JSON：結構合併）
  merge.motrix-maxentries.driver = "<python>" "<複本>" maxentries %O %A %B %P    （test_unscoped_reads_ratchet.py 的 MAX_ENTRIES）
對應的 .gitattributes 已在 repo 裡。沒登記的機器：git 找不到驅動 ⇒ 一般三方合併（照常出衝突，不會靜默少東西）。
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "merge_drivers.py"
#: 驅動會被 git 以「登記時的直譯器」執行（寫進共用的 .git/config、所有 worktree 都吃）⇒ 只准專案固定的 venv，
#: 不收「剛好是誰在跑這支腳本」的 sys.executable（使用者自己的 python、release runner 的暫時環境…）
REQUIRED_VENV = r"D:\MOTRIX-PLATFORM\.venv312"
DRIVERS = {"motrix-changelog": "changelog", "motrix-manifest": "manifest", "motrix-json": "json", "motrix-maxentries": "maxentries"}


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


def python_ok(python):
    """⇒ 錯誤說明或 None：直譯器的完整路徑要在 REQUIRED_VENV（D:\\MOTRIX-PLATFORM\\.venv312）底下（大小寫、斜線方向不拘；`..` 先正規化）。
    只比路徑中間有沒有 `.venv312` 這個字，任何人的 `C:\\x\\.venv312\\python.exe` 都會過——所以改比完整路徑。"""
    got = os.path.normcase(os.path.abspath(str(python)))
    root = os.path.normcase(os.path.abspath(REQUIRED_VENV))
    if got == root or got.startswith(root + os.sep):
        return None
    return "直譯器不在 %s 之下：%s（請用 %s\\Scripts\\python.exe 執行本腳本）" % (REQUIRED_VENV, python, REQUIRED_VENV)


def expected(repo, python=None):
    """⇒ (複本路徑, {config 鍵: 值})。"""
    copy = common_dir(repo) / "motrix" / "merge_drivers.py"
    py = _posix(python or sys.executable)
    cfg = {}
    for name, kind in DRIVERS.items():
        cfg["merge.%s.name" % name] = "MOTRIX %s（兩邊的新增都留；看不懂就一般衝突）" % kind
        cfg["merge.%s.driver" % name] = '"%s" "%s" %s %%O %%A %%B %%P' % (py, _posix(copy), kind)
    return copy, cfg


def registered_python(got):
    """從 `"<python>" "<複本>" kind %O …` 取出 <python>。"""
    m = re.match(r'^"([^"]+)"', got or "")
    return m.group(1) if m else None


def problems(repo, strict=True):
    """⇒ [問題]；空＝已登記而且複本是最新（strict：登記的直譯器也必須在 REQUIRED_VENV 之下）。"""
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
        elif strict:
            bad = python_ok(registered_python(got) or "")
            if bad:
                out.append("%s：%s" % (k, bad))
    if not copy.is_file():
        out.append("複本不存在：%s" % copy)
    elif copy.read_bytes() != SOURCE.read_bytes():
        out.append("複本過期（tools/platform/merge_drivers.py 改過）：重跑 setup_merge_drivers.py")
    return out


def install(repo, python=None, strict=True):
    if strict:
        bad = python_ok(python or sys.executable)
        if bad:
            raise SystemExit("拒絕登記：" + bad)
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
    print("已登記 %s（複本 %s）" % ("／".join(DRIVERS), copy))
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
