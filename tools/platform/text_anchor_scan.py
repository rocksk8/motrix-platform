# -*- coding: utf-8 -*-
"""測試寫法掃描：禁止新測試用「文字子字串」當計數或錨點（T87 A2；T86 fx33 教訓）。

[單位] tools:text_anchor_scan   [層] 工具   [穩定度] 內部
[不變式]
  * 只讀不寫；純 AST 掃描。守門測試 `tests/platform/test_no_text_anchor_in_tests_2026_11_14.py` 與 author_gate --quick 共用這一份。
  * 掃的是「對被測原始碼文字（頁面、js、python 檔內容）做字面子字串的 計數／定位」：
      count   `<任何>.count(標記)`、`str.count(text, 標記)`、`operator.countOf(text, 標記)`、`len(re.findall/finditer/split(標記, text))`
      anchor  `<任何>.index/rindex/find/rfind/partition/rpartition(標記)`、`<x>.split(標記)` 被取索引／拆包／取 len
    「標記」＝字串常數、f-string、`"a" + "b"`、檔內任何位置（含類別層級、AnnAssign）的字串常數名稱、或走訪常數清單的迴圈變數；
    長度 ≥2 且含 中文／`<>="'(){}[]:;/\\-@#` 與空白 其中之一（純英數單字與 `.`、`/` 單字元不算）。接收者是字串常數本身（`"a,b".count(",")`）不算。
  * 為什麼：T86 的 `fx33` 探針用文案字面值當定位與計數，文案一改（PM 要求用語中性化）整支探針紅；
    bp1_layout／module_startup 的錨點、motrix_format 的 needle 同一類。改用 data-testid、結構（AST／正規式抓結構）、行為比對。
  * 逃生口（真的在數資料列、不是在數文案）：呼叫所在的行（或其跨行範圍）有**真正的註解** `# text-anchor-ok: <理由>`，理由 ≥8 字元且（≥2 個詞或中文 ≥4 字）。
    逃生口的使用數另有棘輪（基線 `hatches`，只准減少），測試輸出會列出所有使用處讓審查看得到。
  * 棘輪：基線在 `tests/platform/text_anchor_baseline.json`（只准減少；與 ratchet.py 的三道檢查共用：逐檔貼合、對照合併基準、不重複存上限）。
  * 掃描範圍：測試根（backend/tests、backend/core/tests、backend/modules/*/tests）底下**所有** .py（含 conftest.py 與非 test_ 開頭的輔助檔）。
"""
import ast
import warnings
import io
import json
import re
import sys
import tokenize
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

COUNT_METHODS = frozenset({"count"})
ANCHOR_METHODS = frozenset({"index", "rindex", "find", "rfind", "partition", "rpartition"})
RE_FUNCS = frozenset({"findall", "finditer", "split"})
_CJK = re.compile(r"[㐀-鿿＀-￯]")
_MARKUP = re.compile(r"""[<>="'(){}\[\]:;/\\\s\-@#]""")
_PREFILTER = re.compile(r"\.(count|index|rindex|find|rfind|partition|rpartition|split|rsplit|countOf|findall|finditer)\(")      # 沒有這些呼叫的檔不必解析
_OK_REASON = re.compile(r"#\s*text-anchor-ok:\s*(.*)$")
BASELINE = REPO / "backend" / "tests" / "platform" / "text_anchor_baseline.json"
TEST_ROOT_RE = re.compile(r"^backend/(tests|core/tests|modules/[^/]+/tests)/.*\.py$")


def is_marker(s):
    """字串像『文案或標記』（要被當子字串錨點／計數用）嗎。"""
    if not isinstance(s, str) or len(s) < 2:
        return False
    if len(s) == 2 and not _CJK.search(s):
        return False                                       # 兩字元只認中文（`儲存`、`重啟`）；`ab`、`x-` 太常見
    return bool(_CJK.search(s) or _MARKUP.search(s))


def valid_reason(text):
    """逃生口理由：≥8 字元，且（≥2 個詞，或中文 ≥4 字）；單一英數字、`x`、`ok` 不算。"""
    t = (text or "").strip()
    return len(t) >= 8 and (len(t.split()) >= 2 or len(_CJK.findall(t)) >= 4)


def comment_lines(src, marker="text-anchor-ok"):
    """⇒ {行號: 註解文字}（只算真正的註解 token，字串裡的 `# text-anchor-ok:` 不算）。"""
    out = {}
    if marker not in src:
        return out
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                out[tok.start[0]] = tok.string
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return out


def hatch_lines(src):
    """⇒ {行號: 理由}：有效的逃生口註解（理由合格）。"""
    out = {}
    for ln, c in comment_lines(src).items():
        m = _OK_REASON.search(c)
        if m and valid_reason(m.group(1)):
            out[ln] = m.group(1).strip()
    return out


def _all_str_consts(tree):
    """檔內任何位置（模組、類別、函式）的 `NAME = "…"` 與 `NAME: str = "…"` ⇒ {名稱: 值}（同名多次取第一個）。"""
    out = {}
    for node in ast.walk(tree):
        targets, value = [], None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        if value is None:
            continue
        v = _const_str(value, {})
        if v is None:
            continue
        for t in targets:
            if isinstance(t, ast.Name):
                out.setdefault(t.id, v)
    return out


def _const_str(node, consts):
    """字串常數／f-string 的常數段／`"a" + "b"`／常數名 ⇒ 字串；其他 ⇒ None。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = [v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)]
        return "".join(parts) if parts else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        a, b = _const_str(node.left, consts), _const_str(node.right, consts)
        if a is not None and b is not None:
            return a + b
        return a if a is not None else b
    if isinstance(node, ast.Name) and node.id in consts:
        return consts[node.id]
    return None


def _loop_markers(tree, consts):
    """`for m in ("a", "b"):` / `for m in MARKERS:` ⇒ {迴圈變數名: [字串…]}。"""
    out = {}
    seqs = _seq_consts(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            it = node.iter
            if isinstance(it, ast.Name):
                it = seqs.get(it.id, it)
            if isinstance(it, (ast.List, ast.Tuple, ast.Set)):
                vals = [_const_str(e, consts) for e in it.elts]
                vals = [v for v in vals if v is not None]
                if vals:
                    out.setdefault(node.target.id, []).extend(vals)
    return out


def _seq_consts(tree):
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out.setdefault(t.id, node.value)
    return out


def _markers_of(arg, consts, loops):
    """引數 ⇒ 標記字串清單（可能多個：迴圈變數）；不是標記 ⇒ []。"""
    if isinstance(arg, ast.Name) and arg.id in loops:
        return [m for m in loops[arg.id] if is_marker(m)]
    if isinstance(arg, ast.Attribute) and arg.attr in consts:                 # self.MARK／cls.MARK／Klass.MARK
        return [consts[arg.attr]] if is_marker(consts[arg.attr]) else []
    v = _const_str(arg, consts)
    return [v] if v is not None and is_marker(v) else []


def _collect(src):
    """⇒ [(行號, 種類, 片段, 逃生口行號或 None)]：所有命中；有有效逃生口的帶著它的行號。"""
    if not _PREFILTER.search(src):
        return []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")                  # 被掃的檔裡的 SyntaxWarning（無效跳脫）不是這個守門的事
            tree = ast.parse(src)
    except SyntaxError:
        return []
    hatches = hatch_lines(src)
    consts = _all_str_consts(tree)
    loops = _loop_markers(tree, consts)
    hits = []

    def hatch_of(node):
        end = getattr(node, "end_lineno", node.lineno) or node.lineno
        return next((n for n in range(node.lineno, end + 1) if n in hatches), None)

    def add(node, kind, name, markers):
        if markers:
            hits.append((node.lineno, kind, "%s(%r)" % (name, markers[0][:30]), hatch_of(node)))

    parents = {}
    for node in ast.walk(tree):
        for ch in ast.iter_child_nodes(node):
            parents[id(ch)] = node

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute) and node.args:
            attr, recv = f.attr, f.value
            recv_is_const = isinstance(recv, ast.Constant)
            # str.count(text, "x") / operator.countOf(text, "x")
            if isinstance(recv, ast.Name) and ((recv.id == "str" and attr in COUNT_METHODS | ANCHOR_METHODS) or (recv.id == "operator" and attr == "countOf")) and len(node.args) >= 2:
                add(node, "count" if attr in COUNT_METHODS or attr == "countOf" else "anchor", attr, _markers_of(node.args[1], consts, loops))
                continue
            # re.findall/finditer/split(標記, text) 被 len() 包住 ⇒ 計數
            if isinstance(recv, ast.Name) and recv.id == "re" and attr in RE_FUNCS:
                par = parents.get(id(node))
                counted = isinstance(par, ast.Call) and isinstance(par.func, ast.Name) and par.func.id == "len"
                subscripted = isinstance(par, ast.Subscript) and attr == "split"
                if counted or subscripted:
                    add(node, "count" if counted else "anchor", "re." + attr, _markers_of(node.args[0], consts, loops))
                continue
            if recv_is_const:
                continue
            if attr in COUNT_METHODS:
                add(node, "count", attr, _markers_of(node.args[0], consts, loops))
            elif attr in ANCHOR_METHODS:
                add(node, "anchor", attr, _markers_of(node.args[0], consts, loops))
            elif attr in ("split", "rsplit"):                  # <x>.split(標記)：被取索引、拆包、或取 len ＝用文案切出一段當錨點／數段數
                par = parents.get(id(node))
                used = isinstance(par, ast.Subscript) or (isinstance(par, ast.Assign) and any(isinstance(t, (ast.Tuple, ast.List)) for t in par.targets)) \
                    or (isinstance(par, ast.Call) and isinstance(par.func, ast.Name) and par.func.id == "len")
                if used:
                    add(node, "anchor", attr, _markers_of(node.args[0], consts, loops))
    return sorted(set(hits), key=lambda h: (h[0], h[1], h[2]))


def scan_source(src):
    """⇒ [(行號, 種類 'count'|'anchor', 片段)]；語法錯誤的檔 ⇒ []（別的守門會抓）。呼叫跨行範圍內有有效逃生口註解者略過。"""
    return [(ln, k, sn) for ln, k, sn, h in _collect(src) if h is None]


def hatch_uses(src):
    """⇒ [(逃生口行號, 理由)]：真的蓋住一個命中的逃生口（只貼著沒有命中的呼叫的註解不計）。"""
    hatches = hatch_lines(src)
    used = {h for _ln, _k, _sn, h in _collect(src) if h is not None}
    return sorted((h, hatches[h]) for h in used)


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


def hatches_in_tree(files, read):
    out = {}
    for f in files:
        src = read(f)
        if src is None:
            continue
        u = hatch_uses(src)
        if u:
            out[f] = len(u)
    return out


def test_files(tree_files):
    """測試根底下所有 .py（含 conftest.py 與非 test_ 開頭的輔助檔）。"""
    return sorted(f for f in tree_files if TEST_ROOT_RE.match(f))


def load_baseline(path=BASELINE):
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"files": {}, "total": 0, "hatches": {}}
    return d


def over_baseline(current, baseline_files):
    """⇒ [(檔, 現在, 基線)]：命中數大於基線（新檔基線＝0）。"""
    return [(f, n, baseline_files.get(f, 0)) for f, n in sorted(current.items()) if n > baseline_files.get(f, 0)]


def main(argv=None):
    """python tools/platform/text_anchor_scan.py [--write-baseline] [檔…]：沒給檔 ⇒ 掃整個 repo 的測試檔。
    --write-baseline 只准把基線往下寫：任何一檔（或逃生口數）比現有基線高就拒絕（除非基線檔不存在＝第一次建立）。"""
    argv = list(sys.argv[1:] if argv is None else argv)
    write = "--write-baseline" in argv
    paths = [a for a in argv if not a.startswith("--")]
    import subprocess
    if not paths:
        out = subprocess.run(["git", "-C", str(REPO), "ls-files", "backend"], capture_output=True, text=True, encoding="utf-8").stdout.splitlines()
        paths = test_files(out)
    rd = lambda f: (REPO / f).read_text(encoding="utf-8", errors="replace") if (REPO / f).is_file() else None      # noqa: E731
    cur = scan_tree(paths, rd)
    hat = hatches_in_tree(paths, rd)
    if write:
        old = load_baseline()
        if old.get("files") and not paths_given(argv):
            up = over_baseline(cur, old["files"]) + [(f, n, old.get("hatches", {}).get(f, 0)) for f, n in hat.items() if n > old.get("hatches", {}).get(f, 0)]
            if up:
                for f, n, b in up[:10]:
                    print("拒絕：%s 現在 %d、基線 %d——基線只准往下寫" % (f, n, b))
                return 1
        BASELINE.write_text(json.dumps({"version": 2, "_doc": "text_anchor_scan 的既有命中（只准減少；新增與修改的測試超過這裡的數字＝紅）。不得為了讓新測試過關而調高。",
                                        "total": sum(cur.values()), "files": cur, "hatches": hat}, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print("基線：%d 檔、%d 處；逃生口 %d 處" % (len(cur), sum(cur.values()), sum(hat.values())))
        return 0
    base = load_baseline().get("files", {})
    bad = over_baseline(cur, base)
    for f, n, b in bad:
        print("%s：%d 處（基線 %d）" % (f, n, b))
        for ln, kind, snip in scan_source((REPO / f).read_text(encoding="utf-8", errors="replace")):
            print("    %d [%s] %s" % (ln, kind, snip))
    print("text_anchor：%d 檔超出基線" % len(bad))
    return 1 if bad else 0


def paths_given(argv):
    return any(not a.startswith("--") for a in argv)


if __name__ == "__main__":
    sys.exit(main())
