# -*- coding: utf-8 -*-
"""文字前後對照表產生器（T87；T85／T86「正式＋中性」用語改寫的對照表格式）。

比對 --base..--head 之間「中文顯示字串」的修改，產出三欄表格（改前｜改後｜位置），照 T85 的格式：
  - 開頭寫範圍與比對區間；按「後端訊息／通知」「前端畫面」「說明文件」分節；
  - 只收「修改」（同一處的舊行與新行配成一對）；純新增、純刪除是新功能或移除，不算改寫；
  - 相同的「改前／改後」只列一次，位置寫第一個檔名，多處時寫「檔名 等 N 處」；
  - 改動處前後各留一小段上下文，超出的用「…」截掉。

不收：測試檔、tools/、migrations_frozen、各種 CHANGELOG、version_manifest；PDF／匯出／列印相關檔（--exclude-re，預設見下）；
註解行（# // /* * <!--）與 Python 行尾註解。**這是機械比對，抽查用**：Python 的 docstring 與 JS 字串裡的註解無法區分，可能有少量雜訊。

用法（列車樹根目錄；Python 用 D:\\MOTRIX-PLATFORM\\.venv312\\Scripts\\python.exe）：
  python tools/platform/text_diff_table.py --base c21e502d6 --head 1580c8c1b --out docs/platform/plans/TEXT-DIFF-TABLE-T86.md --title T86
  （--root 指到別的樹；--context 上下文字數，預設 12；--exclude-re 排除檔名規則）
退出碼：0 完成；2 工具錯誤（git 失敗等）。
測試：backend/tests/platform/test_text_diff_table_2026_11_14.py。
"""
import argparse
import difflib
import re
import subprocess
import sys
from pathlib import Path

CJK = re.compile(r"[\u3400-\u9fff\uff00-\uffef\u3000-\u303f]")
HAN = re.compile(r"[\u3400-\u9fff]")
DEFAULT_EXCLUDE = r"pdf|print|export|xlsx|excel"
SECTIONS = ("後端訊息／通知", "前端畫面", "說明文件")
MERGE_GAP = 6          # 兩處改動之間相隔不超過這麼多字就併成一列
MIN_RATIO = 0.5        # 舊行與新行相似度低於此值＝整句重寫（不是用語修改），不收
_PY_COMMENT = re.compile(r"\s+#\s")
_COMMENT_START = {".py": ("#",), ".js": ("//", "/*", "*"), ".html": ("//", "/*", "*", "<!--"), ".md": ()}


def classify(path, exclude_re=DEFAULT_EXCLUDE):
    """⇒ 節名或 None（不收）。"""
    p = path.replace("\\", "/")
    low = p.lower()
    name = low.rsplit("/", 1)[-1]
    if "/tests/" in "/" + low or name.startswith("test_") or name.startswith("conftest"):
        return None
    if low.startswith(("tools/", "backend/tools/")) or "migrations_frozen" in low or "changelog" in name or name == "version_manifest.json":
        return None
    if exclude_re and re.search(exclude_re, name):
        return None
    ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    if low.startswith("docs/"):
        # 說明文件＝給使用者看的指南（docs/**/guides/*.md）；工程文件與產生檔（UNIT-INDEX、RUN-PLAN、plans…）不收
        return SECTIONS[2] if ext == ".md" and "/guides/" in low else None
    if low.startswith("frontend/"):
        return SECTIONS[1] if ext in (".html", ".js") else None
    if low.startswith("backend/"):
        if ext == ".py" or name == "module.json":
            return SECTIONS[0]
        return None
    return None


def _strip_comment(line, ext):
    s = line.strip()
    if any(s.startswith(t) for t in _COMMENT_START.get(ext, ())):
        return ""
    if ext == ".py":
        m = _PY_COMMENT.search(line)
        if m:
            head = line[:m.start()]
            if head.count('"') % 2 == 0 and head.count("'") % 2 == 0:
                return head
    return line


def parse_diff(text):
    """git diff -U0 的輸出 ⇒ [(檔案, [(舊行…), (新行…)] 區塊…)]。只認 modify 區塊（同時有刪有加）。"""
    files, cur, old, new, in_hunk = [], None, [], [], False

    def flush():
        nonlocal old, new
        if cur is not None and old and new:
            cur[1].append((old, new))
        old, new = [], []

    for ln in text.splitlines():
        if ln.startswith("diff --git "):
            flush()
            m = re.match(r"diff --git a/(.*) b/(.*)$", ln)
            cur = (m.group(2), []) if m else None
            if cur:
                files.append(cur)
            in_hunk = False
        elif ln.startswith("@@"):
            flush()
            in_hunk = True
        elif in_hunk and ln.startswith("-") and not ln.startswith("---"):
            old.append(ln[1:])
        elif in_hunk and ln.startswith("+") and not ln.startswith("+++"):
            new.append(ln[1:])
    flush()
    return files


def pair_lines(old, new):
    """同一區塊的舊行與新行配對：行數相同逐行配；不同就逐一找最像的（上限 200×200）。"""
    if len(old) == len(new):
        return list(zip(old, new))
    if len(old) > 200 or len(new) > 200:
        return []
    pairs, used = [], set()
    for n in new:
        best, bi = 0.0, None
        for i, o in enumerate(old):
            if i in used:
                continue
            sm = difflib.SequenceMatcher(None, o, n, autojunk=False)
            if sm.real_quick_ratio() < MIN_RATIO or sm.quick_ratio() < MIN_RATIO:
                continue
            r = sm.ratio()
            if r > best:
                best, bi = r, i
        if bi is not None and best >= MIN_RATIO:
            used.add(bi)
            pairs.append((old[bi], n))
    return pairs


def line_changes(o, n, ctx=12):
    """一對舊行／新行 ⇒ [(改前片段, 改後片段)…]；沒有中文改動 ⇒ []。"""
    if o == n or not (CJK.search(o) or CJK.search(n)):
        return []
    if "".join(CJK.findall(o)) == "".join(CJK.findall(n)):
        return []                                     # 去掉中文以外的字元後相同＝只動了標點、括號、程式碼，中文沒變
    sm = difflib.SequenceMatcher(None, o, n, autojunk=False)
    if sm.ratio() < MIN_RATIO:
        return []
    ops = [op for op in sm.get_opcodes() if op[0] != "equal"]
    merged = []
    for op in ops:
        if merged and op[1] - merged[-1][1] <= MERGE_GAP:
            m = merged[-1]
            merged[-1] = (m[0], op[2], m[2], op[4])
        else:
            merged.append((op[1], op[2], op[3], op[4]))
    out = []
    for i1, i2, j1, j2 in merged:
        if not (o[i1:i2] + n[j1:j2]).strip():
            continue
        a = "…" + o[max(0, i1 - ctx):i2 + ctx] + "…"
        b = "…" + n[max(0, j1 - ctx):j2 + ctx] + "…"
        out.append((a, b))
    return out


def collect(diff_text, ctx=12, exclude_re=DEFAULT_EXCLUDE):
    """⇒ ({節: {(改前, 改後): [檔名…]}}, 被排除的檔案數)。"""
    result = {s: {} for s in SECTIONS}
    excluded = 0
    for path, blocks in parse_diff(diff_text):
        sec = classify(path, exclude_re)
        if sec is None:
            if re.search(exclude_re or "$^", path.lower().rsplit("/", 1)[-1]) and blocks:
                excluded += 1
            continue
        ext = "." + path.rsplit(".", 1)[-1] if "." in path else ""
        for old, new in blocks:
            old2 = [_strip_comment(l, ext) for l in old]
            new2 = [_strip_comment(l, ext) for l in new]
            for o, n in pair_lines(old2, new2):
                for a, b in line_changes(o, n, ctx):
                    result[sec].setdefault((a, b), []).append(path.rsplit("/", 1)[-1])
    return result, excluded


def _cell(s):
    return s.replace("|", "\\|").replace("\r", "").replace("\n", "\\n")


def render(result, title, base, head, exclude_re=DEFAULT_EXCLUDE):
    total = sum(len(v) for v in result.values())
    lines = ["# %s 文字專業化——前後對照表" % title, "",
             "範圍：中文顯示字串的修改（畫面文字、通知文字、說明文件；測試檔不收；PDF、匯出、列印相關檔不在範圍）。比對區間：`%s..%s`。" % (base, head), "",
             "共 %d 組不同的改動（相同的改前／改後只列一次）。" % total, ""]
    for sec in SECTIONS:
        rows = result[sec]
        lines += ["## %s（%d 組）" % (sec, len(rows)), ""]
        if not rows:
            lines += ["本區間無此類改動。", ""]
            continue
        lines += ["| 改前 | 改後 | 位置 |", "|---|---|---|"]
        for (a, b), where in rows.items():
            loc = where[0] if len(where) == 1 else "%s 等 %d 處" % (where[0], len(where))
            lines.append("| %s | %s | %s |" % (_cell(a), _cell(b), loc))
        lines.append("")
    return "\n".join(lines)


def git_diff(root, base, head):
    r = subprocess.run(["git", "-C", str(root), "-c", "core.quotepath=off", "diff", "-U0", "--no-color", "--no-ext-diff", "--no-renames",
                        "%s..%s" % (base, head)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit("git diff 失敗：" + r.stderr.strip()[:300])
    return r.stdout


def main(argv=None):
    ap = argparse.ArgumentParser(description="文字前後對照表產生器（見檔頭）")
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument("--context", type=int, default=12)
    ap.add_argument("--exclude-re", default=DEFAULT_EXCLUDE)
    a = ap.parse_args(argv)
    try:
        result, excluded = collect(git_diff(a.root, a.base, a.head), a.context, a.exclude_re)
    except SystemExit as e:
        print(e, file=sys.stderr)
        return 2
    text = render(result, a.title or "本班", a.base, a.head, a.exclude_re)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8", newline="\n")
    print("已寫 %s：%s；因 PDF／匯出／列印規則略過 %d 個檔。" % (out, "、".join("%s %d 組" % (s, len(result[s])) for s in SECTIONS), excluded))
    return 0


if __name__ == "__main__":
    sys.exit(main())
