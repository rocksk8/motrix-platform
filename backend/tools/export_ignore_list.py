# -*- coding: utf-8 -*-
"""T22-2：建包時用 **git 本人**算好「不出貨清單」（`export-ignore` 屬性為 set 的已追蹤檔），寫進包內。

用法：python export_ignore_list.py --repo <repo 根> [--commit <SHA>] --out <輸出 json>

為什麼有這支：verify_package 4a（排除清單 ∩ MUST_EXIST）原本在驗包當下問 `git check-attr`。正式機的安裝目錄不是 git repo
⇒ 那一項在正式機必定失敗（第二十二班兩次被擋下）。判斷本身必須留著、而且**不可以自己重新實作 git 的比對語意**
（曾經自製 `_pattern_covers`，與 git 不一致，兩條目錄規則沒生效卻沒被抓到，見 verify_package._export_ignore_state 的說明）。
⇒ 在**有 git 的地方**（建包端）讓 git 算出結果，寫進包；驗包端沒有 .git 時讀這份清單比對。
清單在包內（`backend/export_ignore.json`）⇒ 被 package.sha256 的逐檔雜湊與簽章涵蓋，正式機驗得到。

輸出：{"format": 1, "commit": "<SHA>", "count": N, "paths": ["docs/x.md", ...]}（`/` 分隔、相對 repo 根、排序）
"""
import argparse
import json
import subprocess
import sys

FORMAT = 1


def _git(repo, *args, stdin=None):
    r = subprocess.run(["git", "-C", repo, *args], input=stdin, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError("git %s 失敗（exit %s）：%s" % (" ".join(args), r.returncode, r.stderr.decode("utf-8", "replace").strip()))
    return r.stdout


def build(repo, commit="HEAD"):
    """⇒ dict。`git ls-tree` 列出該 commit 的所有檔，`git check-attr --stdin -z` 問每一個的 export-ignore；只收值為 set 的。"""
    sha = _git(repo, "rev-parse", commit).decode("utf-8").strip()
    listing = _git(repo, "ls-tree", "-r", "-z", "--name-only", sha)
    names = [n for n in listing.split(b"\0") if n]
    if not names:
        raise RuntimeError("commit %s 沒有任何檔案，無法產生不出貨清單" % sha)
    # 屬性取自該 commit 的 .gitattributes（`git archive <commit>` 用的就是這一份）；--source 需要 git >= 2.40
    out = _git(repo, "check-attr", "--source", sha, "-z", "--stdin", "export-ignore", stdin=b"\0".join(names) + b"\0")
    parts = out.split(b"\0")
    ignored = []
    # -z 輸出：<path>\0<attr>\0<value>\0 重複
    for i in range(0, len(parts) - 2, 3):
        path, attr, value = parts[i], parts[i + 1], parts[i + 2]
        if attr == b"export-ignore" and value == b"set":
            ignored.append(path.decode("utf-8"))
    return {"format": FORMAT, "commit": sha, "count": len(ignored), "paths": sorted(ignored)}


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--commit", default="HEAD")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    try:
        d = build(a.repo, a.commit)
    except (RuntimeError, OSError) as e:
        print("EXPORT_IGNORE_FAIL %s" % e)
        return 1
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print("EXPORT_IGNORE_OK %d 個檔（commit %s）→ %s" % (d["count"], d["commit"][:8], a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
