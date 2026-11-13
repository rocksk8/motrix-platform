"""改字串前後，找出「還在斷言舊字串」的測試（T85 文字車用）。

用法（在 repo 根目錄、改完字串但尚未 commit 或已 commit 皆可）：
    python -I -X utf8 docs/platform/plans/TEXT-INVENTORY/find_asserting_tests.py <base-commit>
比較 <base-commit> 與工作樹在 frontend／backend/modules／helpers／routers／core 的差異，逐行逐字抽出被改掉的片段（含前後文各 6 字），
再看 backend/tests、backend/modules/*/tests、tests 裡有沒有同樣的片段。只印命中；0 命中＝沒有測試還在斷言舊字。
命中也可能是註解／docstring／別的區塊尚未改的同一句——逐筆讀過再決定。
"""
import subprocess, difflib, glob, re, os, sys, collections
base = sys.argv[1] if len(sys.argv) > 1 else "HEAD"
SRC = ["frontend", "backend/modules", "backend/helpers", "backend/routers", "backend/core"]
out = subprocess.check_output(["git", "diff", "-U0", "--no-color", base, "--"] + SRC, encoding="utf-8")
CJK = re.compile(r"[\u3400-\u9fff]")
tests = {}
for f in glob.glob("backend/tests/**/*", recursive=True) + glob.glob("backend/modules/*/tests/**/*", recursive=True) + glob.glob("tests/**/*", recursive=True):
    if os.path.isfile(f) and f.endswith((".py", ".json", ".js", ".html")):
        try:
            tests[f] = open(f, encoding="utf-8").read()
        except Exception:
            pass
cur = None
rem = []
add = []
hits = collections.defaultdict(set)   # (src, ctx) -> test files


def flush():
    global rem, add
    if cur and "/tests/" not in cur.replace("\\", "/") and (rem or add):
        for i, o in enumerate(rem):
            n = add[i] if len(rem) == len(add) else ""
            sm = difflib.SequenceMatcher(None, o, n, autojunk=False)
            for tag, i1, i2, j1, j2 in sm.get_opcodes():
                if tag not in ("replace", "delete"):
                    continue
                for ctx in (o[max(0, i1 - 6):i2], o[i1:i2 + 6]):
                    if len(CJK.findall(ctx)) < 2:
                        continue
                    for tf, tx in tests.items():
                        if ctx in tx:
                            hits[(cur, ctx)].add(tf)
    rem = []
    add = []


for l in out.split("\n"):
    if l.startswith("+++ b/"):
        flush()
        cur = l[6:]
    elif l.startswith("--- "):
        continue
    elif l.startswith("@@"):
        flush()
    elif l.startswith("-"):
        rem.append(l[1:])
    elif l.startswith("+"):
        add.append(l[1:])
flush()
for (src, ctx), tfs in sorted(hits.items()):
    print(f"{src} :: {ctx!r} -> {sorted(tfs)[:3]}{' +%d' % (len(tfs) - 3) if len(tfs) > 3 else ''}")
print("hits", len(hits))
