# -*- coding: utf-8 -*-
"""測試寫法掃描：禁止新測試用「文字子字串」當計數或錨點（T87 A2；T86 fx33 教訓）。

[單位] tools:text_anchor_scan   [層] 工具   [穩定度] 內部
[不變式]
  * 只讀不寫；純 AST 掃描。守門測試 `tests/platform/test_no_text_anchor_in_tests_2026_11_14.py` 與 author_gate --quick 共用這一份。
  * 掃的是「對被測原始碼文字（頁面、js、python 檔內容）做字面子字串的 計數／定位」：
      count   `<任何>.count(標記)`、`str.count(text, 標記)`、`operator.countOf(text, 標記)`、`len(re.findall/finditer/split(標記, text))`
      anchor  `<任何>.index/rindex/find/rfind/partition/rpartition(標記)`、`<x>.split(標記)` 被取索引／拆包／取 len
    「標記」＝字串／bytes 常數、f-string、`"a" + "b"`、`"尚無%s" % n`、`"尚無{}".format(n)`、檔內任何位置（含類別層級、AnnAssign；同名多次賦值**每一個值都測**）的字串常數名稱、或走訪常數清單的迴圈變數；
    split／re.split／re.findall／re.finditer 的結果被取索引、拆包、len／sum、包 list() 後再數、放進 comprehension 再數、或**綁到名稱後在同一函式內**取索引／len 都算；
    長度 ≥2 且含 中文／`<>="'(){}[]:;/\\-@#` 與空白 其中之一（純英數單字與 `.`、`/` 單字元不算）。接收者是字串常數本身（`"a,b".count(",")`）不算。
  * 為什麼：T86 的 `fx33` 探針用文案字面值當定位與計數，文案一改（PM 要求用語中性化）整支探針紅；
    bp1_layout／module_startup 的錨點、motrix_format 的 needle 同一類。改用 data-testid、結構（AST／正規式抓結構）、行為比對。
  * **沒有逃生口**（T87 決定，h11 F1）：命中就改寫測試——用 data-testid、結構（AST）、行為比對；真的在數資料列，改成數 DOM／API 回傳的列，不要數文案字串。
    曾經的 `# text-anchor-ok` 註解現在不具任何效力（基線也不再記逃生口）。
  * 棘輪：基線在 `tests/platform/text_anchor_baseline.json`（只准減少；與 ratchet.py 的三道檢查共用：逐檔貼合、對照合併基準、不重複存上限）。
  * 已知限制：標記經由**輔助函式的參數**傳進去（`def _c(t, m): return t.count(m)`，呼叫端 `_c(t, "尚無資料")`）看不到；同檔「換一個錨點」總數不變看不出來——靠審查；切出來的結果綁名稱後再**換名字**（`other = parts; len(other)`）與 `len(t) - len(t.replace(標記, ""))` 也看不出來。
  * 掃描範圍：測試根（backend/tests、backend/core/tests、backend/modules/*/tests）底下**所有** .py（含 conftest.py 與非 test_ 開頭的輔助檔）。
"""
import ast
import warnings
import json
import re
import sys
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
BASELINE = REPO / "backend" / "tests" / "platform" / "text_anchor_baseline.json"
TEST_ROOT_RE = re.compile(r"^backend/(tests|core/tests|modules/[^/]+/tests)/.*\.py$")


def is_marker(s):
    """字串像『文案或標記』（要被當子字串錨點／計數用）嗎。"""
    if not isinstance(s, str) or len(s) < 2:
        return False
    if len(s) == 2 and not _CJK.search(s):
        return False                                       # 兩字元只認中文（`儲存`、`重啟`）；`ab`、`x-` 太常見
    return bool(_CJK.search(s) or _MARKUP.search(s))


def _all_str_consts(tree):
    """檔內任何位置（模組、類別、函式）的 `NAME = "…"` 與 `NAME: str = "…"` ⇒ {名稱: [值…]}（同名多次賦值**全部**保留：後面的同名常數蓋掉前面無害的那個，也要測）。"""
    out = {}
    for node in ast.walk(tree):
        targets, value = [], None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        if value is None:
            continue
        vals = _const_strs(value, {})
        if not vals:
            continue
        for t in targets:
            if isinstance(t, ast.Name):
                lst = out.setdefault(t.id, [])
                lst.extend(v for v in vals if v not in lst)
    return out


def _const_strs(node, consts):
    """字串常數／bytes／f-string 的常數段／`"a" + "b"`／`"尚無%s" % n`／`"尚無{}".format(n)`／常數名 ⇒ 可能的字串清單；其他 ⇒ []。"""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return [node.value]
        if isinstance(node.value, bytes):
            return [node.value.decode("utf-8", "replace")]
        return []
    if isinstance(node, ast.JoinedStr):
        parts = [v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)]
        return ["".join(parts)] if parts else []
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        a, b = _const_strs(node.left, consts), _const_strs(node.right, consts)
        if a and b:
            return [x + y for x in a[:4] for y in b[:4]]
        return a or b
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        return _const_strs(node.left, consts)                     # "尚無%s" % n：格式字串的常數段就是標記
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
        return _const_strs(node.func.value, consts)               # "尚無{}".format(n)
    if isinstance(node, ast.Name):
        return list(consts.get(node.id, []))
    return []


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
                vals = [v for e in it.elts for v in _const_strs(e, consts)]
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
    """引數 ⇒ 標記字串清單（可能多個：迴圈變數、同名多次賦值的常數）；不是標記 ⇒ []。"""
    if isinstance(arg, ast.Name) and arg.id in loops:
        cands = loops[arg.id]
    elif isinstance(arg, ast.Attribute) and arg.attr in consts:               # self.MARK／cls.MARK／Klass.MARK
        cands = consts[arg.attr]
    else:
        cands = _const_strs(arg, consts)
    return [m for m in cands if is_marker(m)]


_WRAPPERS = frozenset({"list", "tuple", "sorted", "set", "iter", "reversed"})


def _scope_of(node, parents):
    n = parents.get(id(node))
    while n is not None and not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
        n = parents.get(id(n))
    return n


def _name_is_counted_or_indexed(name, scope):
    for n in ast.walk(scope):
        if isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id == name:
            return True
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("len", "sum") and any(isinstance(a, ast.Name) and a.id == name for a in n.args):
            return True
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Name) and n.value.id == name and any(isinstance(t, (ast.Tuple, ast.List)) for t in n.targets):
            return True
    return False


def _used_as_count_or_index(node, parents):
    """切／找的結果有沒有被取索引、拆包、數長度：直接；包 list()／sorted() 等；放進 comprehension 再 sum／len；或綁到名稱後在同一函式（模組）內取索引／len／拆包。"""
    cur = node
    while True:
        par = parents.get(id(cur))
        if par is None:
            return False
        if isinstance(par, ast.Subscript) and par.value is cur:
            return True
        if isinstance(par, ast.Assign):
            if any(isinstance(t, (ast.Tuple, ast.List)) for t in par.targets):
                return True
            names = [t.id for t in par.targets if isinstance(t, ast.Name)]
            scope = _scope_of(par, parents)
            return bool(scope is not None and any(_name_is_counted_or_indexed(n, scope) for n in names))
        if isinstance(par, ast.Call) and isinstance(par.func, ast.Name):
            if par.func.id in ("len", "sum"):
                return True
            if par.func.id in _WRAPPERS:
                cur = par
                continue
            return False
        if isinstance(par, (ast.comprehension, ast.GeneratorExp, ast.ListComp, ast.SetComp)):
            cur = par
            continue
        return False


def _collect(src):
    """⇒ [(行號, 種類, 片段)]：所有命中。語法錯誤的檔 ⇒ []（別的守門會抓）。**沒有逃生口**：命中就要改寫測試（T87 決定：逃生口關閉）。"""
    if not _PREFILTER.search(src):
        return []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")                  # 被掃的檔裡的 SyntaxWarning（無效跳脫）不是這個守門的事
            tree = ast.parse(src)
    except SyntaxError:
        return []
    consts = _all_str_consts(tree)
    loops = _loop_markers(tree, consts)
    hits = []

    def add(node, kind, name, markers):
        if markers:
            hits.append((node.lineno, kind, "%s(%r)" % (name, markers[0][:30])))

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
            # re.findall/finditer/split(標記, text)：結果被數長度（含包 list／sum 與綁名稱後再 len）或取索引、拆包
            if isinstance(recv, ast.Name) and recv.id == "re" and attr in RE_FUNCS:
                if _used_as_count_or_index(node, parents):
                    add(node, "anchor" if attr == "split" else "count", "re." + attr, _markers_of(node.args[0], consts, loops))
                continue
            if recv_is_const:
                continue
            if attr in COUNT_METHODS:
                add(node, "count", attr, _markers_of(node.args[0], consts, loops))
            elif attr in ANCHOR_METHODS:
                add(node, "anchor", attr, _markers_of(node.args[0], consts, loops))
            elif attr in ("split", "rsplit"):                  # <x>.split(標記)：結果被取索引、拆包、取 len（含綁名稱後再用）＝用文案切出一段當錨點／數段數
                if _used_as_count_or_index(node, parents):
                    add(node, "anchor", attr, _markers_of(node.args[0], consts, loops))
    return sorted(set(hits), key=lambda h: (h[0], h[1], h[2]))


def scan_source(src):
    """⇒ [(行號, 種類 'count'|'anchor', 片段)]；語法錯誤的檔 ⇒ []（別的守門會抓）。"""
    return _collect(src)


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
    """測試根底下所有 .py（含 conftest.py 與非 test_ 開頭的輔助檔）。"""
    return sorted(f for f in tree_files if TEST_ROOT_RE.match(f))


def load_baseline(path=BASELINE):
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"files": {}, "total": 0}
    return d


def over_baseline(current, baseline_files):
    """⇒ [(檔, 現在, 基線)]：命中數大於基線（新檔基線＝0）。"""
    return [(f, n, baseline_files.get(f, 0)) for f, n in sorted(current.items()) if n > baseline_files.get(f, 0)]


def main(argv=None):
    """python tools/platform/text_anchor_scan.py [--write-baseline] [檔…]：沒給檔 ⇒ 掃整個 repo 的測試檔。
    --write-baseline 只准把基線往下寫：任何一檔比現有基線高就拒絕（除非基線檔不存在＝第一次建立）。"""
    argv = list(sys.argv[1:] if argv is None else argv)
    write = "--write-baseline" in argv
    paths = [a for a in argv if not a.startswith("--")]
    import subprocess
    if not paths:
        out = subprocess.run(["git", "-C", str(REPO), "ls-files", "backend"], capture_output=True, text=True, encoding="utf-8").stdout.splitlines()
        paths = test_files(out)
    rd = lambda f: (REPO / f).read_text(encoding="utf-8", errors="replace") if (REPO / f).is_file() else None      # noqa: E731
    cur = scan_tree(paths, rd)
    if write:
        old = load_baseline()
        if old.get("files") and not paths_given(argv):
            up = over_baseline(cur, old["files"])
            if up:
                for f, n, b in up[:10]:
                    print("拒絕：%s 現在 %d、基線 %d——基線只准往下寫" % (f, n, b))
                return 1
        BASELINE.write_text(json.dumps({"version": 2, "_doc": "text_anchor_scan 的既有命中（只准減少；新增與修改的測試超過這裡的數字＝紅）。不得為了讓新測試過關而調高。",
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


def paths_given(argv):
    return any(not a.startswith("--") for a in argv)


if __name__ == "__main__":
    sys.exit(main())
