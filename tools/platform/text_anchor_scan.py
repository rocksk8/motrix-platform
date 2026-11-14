# -*- coding: utf-8 -*-
"""測試寫法掃描：禁止新測試用「文字子字串」當計數或錨點（T87 A2；T86 fx33 教訓）。

[單位] tools:text_anchor_scan   [層] 工具   [穩定度] 內部
[不變式]
  * 只讀不寫；純 AST 掃描。守門測試 `tests/platform/test_no_text_anchor_in_tests_2026_11_14.py` 與 author_gate --quick 共用這一份。
  * 掃的是「對被測原始碼文字（頁面、js、python 檔內容）做字面子字串的 計數／定位」：
      count   `<任何>.count("標記")`            例：`visible.count("尚無待簽核")`、`html.count("<template x-for")`
      anchor  `<任何>.index/rindex/find/rfind/partition/rpartition("標記")`，以及 `<任何>.split("標記")[n]`
    「標記」＝字串常數（或同檔頂層的字串常數名稱）且 長度≥3，並含 中文／`<>="'(){}[]:;/\\`／空白 其中之一；
    純英數單字（`s.count("ab")`）不算。接收者是字串常數本身（`"a,b".count(",")`）不算。
  * 為什麼：T86 的 `fx33` 探針用文案字面值當定位與計數，文案一改（PM 要求用語中性化）整支探針紅；
    bp1_layout／module_startup 的錨點、motrix_format 的 needle 同一類。改用 data-testid、結構（AST／正規式抓結構）、行為比對。
  * 逃生口（真的在數資料列、不是在數文案）：同一行加 `# text-anchor-ok: <理由>`（理由必填，空的不算）。
  * 棘輪：既有檔的命中數記在 `tests/platform/text_anchor_baseline.json`（只准減少）；新檔與有改動的檔，命中數超過基線＝紅。
"""
import ast
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

import guard_patterns as GP  # noqa: E402

COUNT_METHODS = frozenset({"count"})
ANCHOR_METHODS = frozenset({"index", "rindex", "find", "rfind", "partition", "rpartition"})
_CJK = re.compile(r"[㐀-鿿＀-￯]")
_MARKUP = re.compile(r"""[<>="'(){}\[\]:;/\\\s]""")
_OK = re.compile(r"#\s*text-anchor-ok:\s*\S")
BASELINE = REPO / "backend" / "tests" / "platform" / "text_anchor_baseline.json"


def is_marker(s):
    """字串像『文案或標記』（要被當子字串錨點／計數用）嗎。"""
    if not isinstance(s, str) or len(s) < 3:
        return False
    return bool(_CJK.search(s) or _MARKUP.search(s))


def _module_str_consts(tree):
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = node.value.value
    return out


def _marker_arg(arg, consts):
    if isinstance(arg, ast.Constant):
        return arg.value if is_marker(arg.value) else None
    if isinstance(arg, ast.Name) and arg.id in consts:
        return consts[arg.id] if is_marker(consts[arg.id]) else None
    return None


def scan_source(src):
    """⇒ [(行號, 種類 'count'|'anchor', 片段)]；語法錯誤的檔 ⇒ []（別的守門會抓）。同一行有 text-anchor-ok（含理由）者略過。"""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    lines = src.splitlines()
    consts = _module_str_consts(tree)
    hits = []

    def ok_line(n):
        return 0 < n <= len(lines) and bool(_OK.search(lines[n - 1]))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or not node.args:
            continue
        attr = node.func.attr
        recv = node.func.value
        if isinstance(recv, ast.Constant):
            continue
        kind = "count" if attr in COUNT_METHODS else "anchor" if attr in ANCHOR_METHODS else None
        if kind is None:
            continue
        m = _marker_arg(node.args[0], consts)
        if m is None or ok_line(node.lineno):
            continue
        hits.append((node.lineno, kind, "%s(%r)" % (attr, m[:30])))
    for node in ast.walk(tree):                      # <x>.split("標記")[n]：用文案切出一段當錨點
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute) \
                and node.value.func.attr in ("split", "rsplit") and node.value.args and not isinstance(node.value.func.value, ast.Constant):
            m = _marker_arg(node.value.args[0], consts)
            if m is not None and not ok_line(node.lineno):
                hits.append((node.lineno, "anchor", "%s(%r)[…]" % (node.value.func.attr, m[:30])))
    return sorted(set(hits))


def scan_tree(files, read):
    """files＝repo 相對檔、read(path)→文字或 None ⇒ {檔: 命中數}（只列有命中的）。"""
    out = {}
    for f in files:
        src = read(f)
        if src is None:
            continue
        n = len(scan_source(src))
        if n:
            out[f] = n
    return out


def test_files(tree_files):
    return sorted(f for f in tree_files if GP.is_test_file(f) and f.endswith(".py"))


def load_baseline(path=BASELINE):
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"files": {}, "total": 0}
    return d


def over_baseline(current, baseline_files):
    """⇒ [(檔, 現在, 基線)]：命中數大於基線（新檔基線＝0）。只准減少，不准增加。"""
    return [(f, n, baseline_files.get(f, 0)) for f, n in sorted(current.items()) if n > baseline_files.get(f, 0)]


def main(argv=None):
    """python tools/platform/text_anchor_scan.py [--write-baseline] [檔…]：沒給檔 ⇒ 掃整個 repo 的測試檔。"""
    argv = list(sys.argv[1:] if argv is None else argv)
    write = "--write-baseline" in argv
    paths = [a for a in argv if not a.startswith("--")]
    import subprocess
    if not paths:
        out = subprocess.run(["git", "-C", str(REPO), "ls-files", "backend"], capture_output=True, text=True, encoding="utf-8").stdout.splitlines()
        paths = test_files(out)
    cur = scan_tree(paths, lambda f: (REPO / f).read_text(encoding="utf-8", errors="replace") if (REPO / f).is_file() else None)
    if write:
        BASELINE.write_text(json.dumps({"version": 1, "_doc": "text_anchor_scan 的既有命中（只准減少；新增與修改的測試超過這裡的數字＝紅）。不得為了讓新測試過關而調高。",
                                        "total": sum(cur.values()), "files": cur}, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print("基線：%d 檔、%d 處" % (len(cur), sum(cur.values())))
        return 0
    base = load_baseline().get("files", {})
    bad = over_baseline(cur, base)
    for f, n, b in bad:
        print("%s：%d 處（基線 %d）" % (f, n, b))
        for ln, kind, snip in scan_source((REPO / f).read_text(encoding="utf-8", errors="replace")):
            print("    %d [%s] %s" % (ln, kind, snip))
    print("text_anchor：%d 檔超出基線" % len(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
