"""產生 TEXT-DIFF-TABLE.md：T85 文字車的「改前／改後」對照表（給使用者看）。

用法（repo 根目錄）：
    python -I -X utf8 docs/platform/plans/TEXT-INVENTORY/make_diff_table.py <base> [<head>] > docs/platform/plans/TEXT-DIFF-TABLE.md

逐行比對 base..head 在程式碼與畫面檔的變動，把「被改掉的那一段」連同前後文（各約 10 字）列成表。
只列有中文的變動；測試檔、golden、文件不列（不是使用者看得到的文字）。
同一段（改前＋改後相同）只列一次，後面標「另有 N 處」。
"""
import collections
import difflib
import re
import subprocess
import sys

base = sys.argv[1]
head = sys.argv[2] if len(sys.argv) > 2 else "HEAD"
CJK = re.compile(r"[㐀-鿿]")
SRC = ["frontend", "backend"]
out = subprocess.check_output(["git", "diff", "-U0", "--no-color", base, head, "--"] + SRC, encoding="utf-8")

LAYER = [
    ("frontend/pages/", "畫面（頁面）"),
    ("frontend/static/", "畫面（共用元件）"),
    ("frontend/js/", "畫面（頁面腳本）"),
    ("frontend/", "畫面（其他）"),
    ("backend/core/", "設定說明／選單"),
    ("backend/", "後端訊息／通知"),
]


def layer(path):
    for pre, name in LAYER:
        if path.startswith(pre):
            return name
    return "其他"


def skip(path):
    p = path.replace("\\", "/")
    return "/tests/" in p or p.startswith("backend/tests") or "golden" in p


def clean(s):
    s = re.sub(r"\s+", " ", s)
    return s.replace("|", "\\|").strip()


rows = collections.OrderedDict()  # (layer, before, after) -> [files]
cur = None
rem = []
add = []


def flush():
    global rem, add
    if cur and not skip(cur) and (rem or add):
        for i, o in enumerate(rem):
            n = add[i] if len(rem) == len(add) else ""
            if not n:
                continue
            sm = difflib.SequenceMatcher(None, o, n, autojunk=False)
            ops = [op for op in sm.get_opcodes() if op[0] != "equal"]
            # 合併相鄰（間距 < 4 字）的變動，讓一句話的多處修改顯示在同一列
            groups = []
            for op in ops:
                if groups and op[1] - groups[-1][-1][2] < 4:
                    groups[-1].append(op)
                else:
                    groups.append([op])
            for g in groups:
                i1, i2 = g[0][1], g[-1][2]
                j1, j2 = g[0][3], g[-1][4]
                a = o[max(0, i1 - 10):i2 + 10]
                b = n[max(0, j1 - 10):j2 + 10]
                if not (CJK.search(a) or CJK.search(b)):
                    continue
                key = (layer(cur), clean(a), clean(b))
                rows.setdefault(key, []).append(cur)
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

by_layer = collections.OrderedDict()
for (lay, a, b), files in rows.items():
    by_layer.setdefault(lay, []).append((a, b, files))

print("# T85 文字專業化——前後對照表\n")
print(f"範圍：畫面文字、通知文字、說明文件（報價單／估價單 PDF、匯出報表、列印格式不在範圍，除輸出內「MOTRIX ERP」系統名稱已改為「MOTRIX PLATFORM」）。比對區間：`{base[:9]}..{head[:9] if head != 'HEAD' else 'HEAD'}`。\n")
total = sum(len(v) for v in by_layer.values())
print(f"共 {total} 組不同的改動（相同的改前／改後只列一次）。\n")
for lay, items in by_layer.items():
    print(f"## {lay}（{len(items)} 組）\n")
    print("| 改前 | 改後 | 位置 |")
    print("|---|---|---|")
    for a, b, files in items:
        uniq = sorted(set(f.split("/")[-1] for f in files))
        loc = "、".join(uniq[:3]) + (f" 等 {len(files)} 處" if len(files) > 1 else "")
        print(f"| …{a}… | …{b}… | {loc} |")
    print()
