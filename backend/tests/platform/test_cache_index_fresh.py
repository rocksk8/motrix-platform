# -*- coding: utf-8 -*-
"""CACHE-INDEX.md 的摘要是快取（PLAYBOOK §G-瓶頸）：來源 commit 落後太多時**警告**（不擋合回）。

- 解析行：`- 來源檔：<路徑>｜來源 commit：<sha>`；每一行的來源檔要存在（不存在＝索引寫錯 ⇒ 紅，因為那是索引本身壞了，不是「過期」）。
- 過期判斷：`git rev-list --count <sha>..HEAD -- <來源檔>` > N（8）⇒ `warnings.warn`（列出檔名與落後幾個 commit）。
- 來源 commit 不在這個 repo（例如 rebase／squash 之後換了 SHA、shallow clone）⇒ 警告「無法判斷」，不紅。
- 純函式 `stale()` 用合成資料做正對照／反向控制。
"""
import re
import subprocess
import warnings
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
INDEX = REPO / "docs" / "platform" / "CACHE-INDEX.md"
N = 8
LINE = re.compile(r"^- 來源檔：(?P<path>[^｜\s]+)｜來源 commit：(?P<sha>[0-9a-f]{7,40})\s*$", re.M)


def entries():
    return [(m["path"], m["sha"]) for m in LINE.finditer(INDEX.read_text(encoding="utf-8"))]


def stale(behind: int, n: int = N) -> bool:
    return behind > n


def _behind(sha, path):
    r = subprocess.run(["git", "-C", str(REPO), "rev-list", "--count", "%s..HEAD" % sha, "--", path],
                       capture_output=True, text=True, encoding="utf-8")
    return int(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip().isdigit() else None


def test_index_lists_the_big_docs_and_every_source_file_exists():
    es = entries()
    paths = {p for p, _ in es}
    for must in ("docs/platform/CORE-SPEC.md", "MULTIWIN-PROTOCOL.md", "docs/platform/MODULE-GUIDE.md",
                 "docs/platform/PLAYBOOK.md"):
        assert must in paths, "CACHE-INDEX.md 少了 %s 的摘要段" % must
    missing = [p for p in paths if not (REPO / p).exists()]
    assert not missing, "索引指向不存在的來源檔：%s" % missing


def test_stale_summaries_are_reported_as_warnings_not_failures():
    late = []
    for path, sha in entries():
        b = _behind(sha, path)
        if b is None:
            warnings.warn("CACHE-INDEX：%s 的來源 commit %s 不在這個 repo，無法判斷是否過期" % (path, sha))
        elif stale(b):
            late.append("%s（來源 %s 之後又改了 %d 次）" % (path, sha, b))
    if late:
        warnings.warn("CACHE-INDEX 摘要可能過期（>%d 次改動）：%s；重讀原檔更新摘要與來源 commit" % (N, "；".join(late)))


def test_stale_predicate_positive_and_negative_control():
    assert stale(N + 1) and not stale(N) and not stale(0)
    assert LINE.findall("- 來源檔：a/b.md｜來源 commit：abcdef12\n") == [("a/b.md", "abcdef12")]
    assert LINE.findall("- 來源檔：a/b.md｜來源 commit：ZZZ\n") == []           # 亂寫的 sha 不算條目
