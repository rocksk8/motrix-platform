# -*- coding: utf-8 -*-
"""T85 文字車：盤點「給人看的中文字串」並標出不合準則的地方（靜態；只讀原始碼，不執行任何專案程式）。

用法（repo 根目錄）：python -I -X utf8 docs/platform/plans/TEXT-INVENTORY/scan_text.py [--out docs/platform/plans/TEXT-INVENTORY]
產出：strings.csv（每個含中文的字串一列：區塊、檔、行、情境、問題代碼、原文）、summary.md（每區塊／每檔計數）。
範圍：frontend/pages、frontend/index.html、frontend/static/*.js（不含 vendor）、frontend/js、backend 非測試 .py 的字串常數（不含 docstring）、
  backend/modules/*/pages|js。docstring、註解、測試不在範圍。報價單／估價單 PDF／匯出／列印相關檔另標 frozen?＝需人確認、預設不動。
問題代碼：
  C1 口語／網路用語   C2 「你」（應為「您」）   C3 出現 ERP   C4 大陸用語（應為台灣正體）   C5 驚嘆號／表情符號
  C6 半形標點緊貼中文（, . : ; ? ( )）   C7 中英／中數緊貼沒有空格（現行慣例＝之間加半形空格，約 92%，緊貼為離群）   C8 三個點（...）應為「…」
  C10 口語句式（好像／其實／有沒有／弄／搞…；需人判斷）
  C9 版面功能符號（✓ ✗ ⚠ ● → 等）：不是表情符號，預設保留，只計數
"""
import argparse
import ast
import csv
import json
import re
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
CJK = re.compile(r"[㐀-鿿]")
COLLOQ = re.compile(r"搞定|喔|啦|囉|超(?=[快好大強棒讚猛便宜簡單輕鬆])|爆(?=[量炸滿棚])|GG|嘿|哈哈|哇|耶|欸|蛤|讚|酷|爽|搞砸|掛了|炸了|小心點|別擔心|放心|不用怕")
NI = re.compile(r"(?<!您)你(?!好嗎)")
ERP = re.compile(r"(?<![A-Za-z])ERP(?![A-Za-z])", re.I)
MAINLAND = re.compile(r"賬號|賬戶|賬|設置|數據|信息(?!化)|默認|服務器|用戶|軟件|硬件|文件夾|網絡|打印|質量|視頻|激活|緩存|鼠標|屏幕|菜單|(?<!存)內存(?!在)")
EMOJI = re.compile("[\U0001F300-\U0001FAFF⭐⭕✅❌❗❓❤✨]")      # 圖形表情符號（🔒🎉⭐✅❌…）
MARK = re.compile("[✓✔✗✘⚠●○★☆→←]")        # 版面功能符號（✓ ✗ ⚠ ● → 等）：不是表情符號，預設保留，只計數
BANG = re.compile(r"[!！]")
HALF = re.compile(r"[㐀-鿿][,;:?](?!\d)|[㐀-鿿]\([^)]*[㐀-鿿]|[㐀-鿿]\.(?![\w/.])|[,;:?!]\s?[㐀-鿿]")
SPACE = re.compile(r"[㐀-鿿](?<![㐀-鿿])[A-Za-z0-9]|[A-Za-z0-9][㐀-鿿]")     # C7＝中英數緊貼（現行慣例是「之間加半形空格」，約 92%；緊貼的是少數離群）
INFORMAL = re.compile(r"好像|應該會|大概|其實|蠻|有沒有|是不是|會不會|夠不夠|弄|搞|整個|一下|沒事|別忘|幫您|幫你|讓您|不用擔心|大家|我們幫")   # C10 口語句式（需人判斷）
DOTS = re.compile(r"\.{3}")

FROZEN_FILES = re.compile(r"(quote.*(pdf|print|export)|pdf|export|print_|_print|xlsx|csv|output_templates|form_templates)", re.I)   # 報價單／估價單 PDF、匯出、列印：只標示，由人確認


def issues(s):
    out = []
    for code, rx in (("C1", COLLOQ), ("C2", NI), ("C3", ERP), ("C4", MAINLAND), ("C6", HALF), ("C7", SPACE), ("C8", DOTS), ("C9", MARK), ("C10", INFORMAL)):
        if rx.search(s):
            out.append(code)
    if EMOJI.search(s) or BANG.search(s):
        out.append("C5")            # 驚嘆號或圖形表情符號
    return sorted(out)


def js_strings(src, base_line=1):
    """JS／行內腳本：抓 '..' ".." `..` 字串（含跳脫），略過 // 與 /* */ 註解。回 [(行, 字串)]。"""
    out, i, n, line = [], 0, len(src), base_line
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            line += src.count("\n", i, j)
            i = j
            continue
        if c in "'\"`":
            q, j, buf, l0 = c, i + 1, [], line
            while j < n:
                d = src[j]
                if d == "\\" and j + 1 < n:
                    buf.append(src[j + 1])
                    j += 2
                    continue
                if d == "\n":
                    line += 1
                    if q != "`":
                        break
                if d == q:
                    break
                buf.append(d)
                j += 1
            s = "".join(buf)
            if CJK.search(s):
                out.append((l0, s))
            i = j + 1
            continue
        i += 1
    return out


class Html(HTMLParser):
    SKIP_ATTR = {"class", "id", "href", "src", "name", "type", "for", "data-testid", "style", "lang", "charset", "rel", "action", "method"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.stack = [], []

    def handle_starttag(self, tag, attrs):
        self.stack.append(tag)
        ln = self.getpos()[0]
        for k, v in attrs:
            if not v or k in self.SKIP_ATTR or not CJK.search(v):
                continue
            if k.startswith(("x-", "@", ":", "v-", "on")):
                for l, s in js_strings(v, ln):
                    self.rows.append((l, "attr:" + k, s))
            else:
                self.rows.append((ln, "attr:" + k, v))

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()

    def handle_data(self, data):
        if not CJK.search(data):
            return
        ln = self.getpos()[0]
        top = self.stack[-1] if self.stack else ""
        if top == "script":
            for l, s in js_strings(data, ln):
                self.rows.append((l, "script", s))
        elif top == "style":
            return
        else:
            t = re.sub(r"\s+", " ", data).strip()
            if t:
                self.rows.append((ln, "text", t))


def scan_html(path):
    p = Html()
    try:
        p.feed(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:  # noqa: BLE001
        return [(0, "parse-error", repr(e))]
    return p.rows


def scan_json(path):
    """JSON 資料檔（選單／頁面標題／設定說明／module.json／單據範本）：只掃字串「值」，鍵名不算。context＝最後一層鍵。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as e:  # noqa: BLE001
        return [(0, "parse-error", repr(e))]
    rows = []

    def walk(o, key):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, str(k))
        elif isinstance(o, list):
            for v in o:
                walk(v, key)
        elif isinstance(o, str) and CJK.search(o):
            rows.append((0, "json:" + key, o))
    walk(data, "")
    return rows


def scan_js(path):
    return [(l, "js", s) for l, s in js_strings(path.read_text(encoding="utf-8", errors="replace"))]


def ctx_of(node, parent):
    """Python 字串的情境。"""
    cur = node
    p = parent.get(id(cur))
    while p is not None and isinstance(p, (ast.JoinedStr, ast.FormattedValue, ast.BinOp)):
        cur = p
        p = parent.get(id(cur))
    if isinstance(p, ast.keyword):
        return "kw:" + (p.arg or "")
    if isinstance(p, ast.Call):
        f = p.func
        return "call:" + (getattr(f, "id", None) or getattr(f, "attr", None) or "")
    if isinstance(p, ast.Dict):
        for k, v in zip(p.keys, p.values):
            if v is cur and isinstance(k, ast.Constant):
                return "dict:" + str(k.value)
        return "dict"
    if isinstance(p, ast.Assign):
        return "assign"
    return type(p).__name__ if p is not None else "?"


LOGCALLS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log", "print"}


def scan_py(path):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:  # noqa: BLE001
        return [(0, "parse-error", repr(e))]
    parent, doc = {}, set()
    for n in ast.walk(tree):
        for ch in ast.iter_child_nodes(n):
            parent[id(ch)] = n
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body \
                and isinstance(n.body[0], ast.Expr) and isinstance(getattr(n.body[0], "value", None), ast.Constant):
            doc.add(id(n.body[0].value))
    rows = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc and CJK.search(n.value):
            c = ctx_of(n, parent)
            if c.startswith("call:") and c[5:] in LOGCALLS:
                c = "log"                       # 開發者看的 log／print：不在範圍
            rows.append((n.lineno, c, n.value))
    return rows


def block_of(rel):
    if rel.endswith(".json"):
        return "J1-json"
    if rel.startswith("frontend/pages/") or rel == "frontend/index.html":
        return "F1-pages"
    if rel.startswith(("frontend/static/", "frontend/js/")):
        return "F2-static-js"
    if rel.startswith("backend/modules/"):
        return "B3-module-" + rel.split("/")[2]
    if rel.startswith("backend/routers/"):
        return "B1-routers"
    if rel.startswith("backend/helpers/settings"):
        return "B2-settings"
    if rel.startswith("backend/helpers/"):
        return "B4-helpers"
    if rel.startswith("backend/core/"):
        return "B5-core"
    return "B6-other"


def collect(root):
    files = []
    for pat in ("frontend/pages/*.html", "frontend/index.html", "frontend/static/*.js", "frontend/js/*.js",
                "backend/modules/*/pages/*.html", "backend/modules/*/js/*.js",
                "backend/version_manifest.json", "backend/core/*.json", "backend/modules/*/module.json", "frontend/static/*.json",
                "backend/helpers/form_templates/*.json", "backend/helpers/output_templates/*.json", "backend/helpers/expense_type_defs/*.json"):
        files += sorted(root.glob(pat))
    for p in sorted((root / "backend").rglob("*.py")):
        r = p.relative_to(root).as_posix()
        if any(x in r for x in ("/tests/", "/tools/", "/db_backups/", "__pycache__", "/rollback_snapshots/", "/migrations/")) \
                or p.name.startswith("test_") or p.name == "conftest.py":
            continue
        files.append(p)
    return files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs/platform/plans/TEXT-INVENTORY"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows_all, per_file, per_block = [], {}, defaultdict(Counter)
    for f in collect(ROOT):
        rel = f.relative_to(ROOT).as_posix()
        rs = scan_html(f) if rel.endswith(".html") else scan_js(f) if rel.endswith(".js") else scan_json(f) if rel.endswith(".json") else scan_py(f)
        blk = block_of(rel)
        frozen = bool(FROZEN_FILES.search(rel))
        c = Counter()
        for ln, ctx, s in rs:
            iss = issues(s)
            rows_all.append([blk, rel, ln, ctx, "frozen?" if frozen else "", ",".join(iss), s.replace("\n", "\\n")[:300]])
            c["strings"] += 1
            if len(CJK.findall(s)) >= 25 and ctx != "log":
                c["long"] += 1
            if ctx == "log":
                c["log"] += 1
            real = [i for i in iss if i != "C9"]
            if iss and ctx != "log":
                for i in iss:
                    c[i] += 1
                if real:
                    c["flagged"] += 1
        per_file[rel] = c
        for k, v in c.items():
            per_block[blk][k] += v
        per_block[blk]["files"] += 1
    with open(out / "strings.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["block", "file", "line", "context", "frozen", "issues", "text"])
        w.writerows(rows_all)
    cols = ["strings", "flagged", "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10", "long", "log"]
    lines = ["# 文字盤點彙總（scan_text.py 產生）", "", "| 區塊 | 檔數 | " + " | ".join(cols) + " |", "|---|---|" + "---|" * len(cols)]
    for b in sorted(per_block):
        c = per_block[b]
        lines.append("| %s | %d | %s |" % (b, c["files"], " | ".join(str(c[k]) for k in cols)))
    tot = Counter()
    for c in per_block.values():
        tot.update(c)
    lines.append("| **合計** | %d | %s |" % (tot["files"], " | ".join(str(tot[k]) for k in cols)))
    lines += ["", "（flagged＝含 C1～C8、C10 的字串數；C9（✓✗⚠ 等版面符號）只計數；long＝25 字以上的長說明句（需通篇人讀，規則掃不出口語語氣）；log＝開發者看的 log／print，不計入。）", "",
              "## 每檔（含問題的前 60 檔，依 flagged 排序）", "", "| 檔 | strings | flagged | " + " | ".join(cols[2:13]) + " |", "|---|---|---|" + "---|" * 11]
    for rel, c in sorted(per_file.items(), key=lambda kv: -kv[1]["flagged"])[:60]:
        if not c["flagged"]:
            break
        lines.append("| %s | %d | %d | %s |" % (rel, c["strings"], c["flagged"], " | ".join(str(c[k]) for k in cols[2:13])))
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("rows", len(rows_all), "files", len(per_file), "flagged", tot["flagged"])


if __name__ == "__main__":
    main()
