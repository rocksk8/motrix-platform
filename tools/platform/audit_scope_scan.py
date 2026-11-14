# -*- coding: utf-8 -*-
"""測試寫法掃描：測試讀「全域稽核表／失敗表」時，必須依自己建立的使用者或 request 篩選（T87 A2；T86 正式閘門 test_quote_put_fail_reason_codes 教訓）。

[單位] tools:audit_scope_scan   [層] 工具   [穩定度] 內部
[不變式]
  * 只讀不寫；純 AST 掃描。守門測試 `tests/platform/test_audit_reads_scoped_to_own_rows_2026_11_14.py` 與 author_gate --quick 共用這一份。
  * 掃的是測試檔裡「SQL 敘述開頭」（SELECT／WITH／DELETE／UPDATE）的字串（含 f-string 的常數段、`"a" + "b"` 拼接）：含 `FROM <全域表>`（AUDIT_TABLES，目前 audit_log）時，
    **只看第一個 WHERE 之後、ORDER BY／GROUP BY／LIMIT 之前的條件**；沒有 WHERE ⇒ 命中；WHERE 裡沒有「自己的範圍」條件 ⇒ 命中。
      自己的範圍＝範圍欄位（username／user_id／actor／request_id／target／entity／object_id／quote_no／case_id／doc_no／ref_id…）與值比較（= != <> IN LIKE），
      或水位線 `id >`／`rowid >`／`created_at >`／`ts >`（**右邊不能是數字常數**：`id > 0` 等於沒篩）。
      只出現在 SELECT 欄位清單或 ORDER BY 的欄位名不算。
  * 為什麼：`SELECT * FROM audit_log WHERE result='fail'` 讀到的是整個資料庫的失敗列；單獨跑會綠，整包跑時別的測試留下的列讓
    `len(rows) == 1` 變成 `len(rows) == 3`（T86 正式閘門才抓到）。
  * **沒有逃生口**（T87 決定，h11 F1）：命中就改寫測試（WHERE 加上自己建立的使用者／request_id／target，或先記下 max(id) 再用 `id > ?` 只看新增的列）。
  * 棘輪：既有檔的命中數記在 `tests/platform/audit_scope_baseline.json`（只准減少；與 ratchet.py 的三道檢查共用）；新檔與有改動的檔超過基線＝紅。
  * 已知限制：只認 AUDIT_TABLES 的表名與 SQL 敘述開頭的字串；動態拼出表名、ORM 讀取、別的全域表（failure 表）看不到——要擴就在 AUDIT_TABLES 加表名；
    子查詢裡的 WHERE 會被當成同一個條件區。
"""
import ast
import json
import re
import sys
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

import text_anchor_scan as TA  # noqa: E402  （棘輪 over_baseline／測試檔判定共用）

AUDIT_TABLES = ("audit_log",)
BASELINE = REPO / "backend" / "tests" / "platform" / "audit_scope_baseline.json"
_FROM = re.compile(r"\bFROM\s+(%s)\b" % "|".join(AUDIT_TABLES), re.I)
_STMT = re.compile(r"\s*(SELECT|WITH|DELETE|UPDATE)\b", re.I)                # 只認 SQL 敘述開頭的字串（說明文字、docstring 提到 FROM audit_log 不算）
_WHERE = re.compile(r"\bWHERE\b", re.I)
_WHERE_END = re.compile(r"\b(ORDER\s+BY|GROUP\s+BY|LIMIT|HAVING)\b", re.I)
_SCOPE_COLS = ("username|user_id|user_name|actor|actor_id|actor_username|request_id|target|target_id|entity|entity_id|object_id|quote_no|case_id|doc_no|ref_id|"
               "record_id|session_id")
_SCOPE_EQ = re.compile(r"\b(?:%s)\b\s*(?:=|!=|<>|\bIN\b|\bLIKE\b)\s*(?:\S|$)" % _SCOPE_COLS, re.I)
_WATERMARK = re.compile(r"\b(?:rowid|id|created_at|ts)\b\s*>=?\s*(?!['\"]?\d)(?:\S|$)", re.I)


def _flatten_add(node):
    """`"a" + x + "b"` ⇒ 字串（非字串的項以一個空白代替）；項目裡完全沒有字串常數 ⇒ None。"""
    parts, has_str = [], False

    def walk(n):
        nonlocal has_str
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
            walk(n.left)
            walk(n.right)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            has_str = True
            parts.append(n.value)
        elif isinstance(n, ast.JoinedStr):
            has_str = True
            parts.append("".join(v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else " " for v in n.values))
        else:
            parts.append(" ")
    walk(node)
    return "".join(parts) if has_str else None


def _strings(tree):
    """⇒ [(起始行, 完整字串)]；JoinedStr 取其常數段（變數段留空白）；`"a" + "b"` 拼接成一個字串。巢在別的字串運算式裡的常數不重複計。"""
    out, inside = [], set()
    for node in ast.walk(tree):
        if id(node) in inside:
            continue
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            s = _flatten_add(node)
            if s is not None:
                out.append((node.lineno, s))
                inside.update(id(n) for n in ast.walk(node))
        elif isinstance(node, ast.JoinedStr):
            out.append((node.lineno, "".join(v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else " " for v in node.values)))
            inside.update(id(n) for n in ast.walk(node))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append((node.lineno, node.value))
    return out


def is_scoped(sql):
    """這段 SQL 讀 audit_log 時，WHERE 內有沒有自己的範圍條件。"""
    m = _WHERE.search(sql)
    if not m:
        return False
    where = sql[m.end():]
    e = _WHERE_END.search(where)
    if e:
        where = where[:e.start()]
    return bool(_SCOPE_EQ.search(where) or _WATERMARK.search(where))


def _collect(src):
    """⇒ [(行號, 片段)]。語法錯誤的檔 ⇒ []（別的守門會抓）。沒有逃生口。"""
    if not any(t in src for t in AUDIT_TABLES):
        return []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")                  # 被掃的檔裡的 SyntaxWarning（無效跳脫）不是這個守門的事
            tree = ast.parse(src)
    except SyntaxError:
        return []
    hits = []
    for ln, s in _strings(tree):
        if _FROM.search(s) and _STMT.match(s) and not is_scoped(s):
            hits.append((ln, " ".join(s.split())[:60]))
    return sorted(set(hits))


def scan_source(src):
    """⇒ [(行號, 片段)]。"""
    return _collect(src)


def scan_tree(files, read):
    out = {}
    for f in files:
        src = read(f)
        if src is None:
            continue
        n = len(scan_source(src))
        if n:
            out[f] = n
    return out


load_baseline = lambda path=BASELINE: TA.load_baseline(path)       # noqa: E731
over_baseline = TA.over_baseline
test_files = TA.test_files


def main(argv=None):
    """python tools/platform/audit_scope_scan.py [--write-baseline] [檔…]：沒給檔 ⇒ 掃整個 repo 的測試檔。"""
    argv = list(sys.argv[1:] if argv is None else argv)
    write = "--write-baseline" in argv
    paths = [a for a in argv if not a.startswith("--")]
    import subprocess
    if not paths:
        out = subprocess.run(["git", "-C", str(REPO), "ls-files", "backend"], capture_output=True, text=True, encoding="utf-8").stdout.splitlines()
        paths = test_files(out)
    cur = scan_tree(paths, lambda f: (REPO / f).read_text(encoding="utf-8", errors="replace") if (REPO / f).is_file() else None)
    if write:
        old = load_baseline()
        if old.get("files") and not any(not a.startswith("--") for a in argv):
            up = over_baseline(cur, old["files"])
            if up:
                for f, n, b in up[:10]:
                    print("拒絕：%s 現在 %d、基線 %d——基線只准往下寫" % (f, n, b))
                return 1
        BASELINE.write_text(json.dumps({"version": 3, "_doc": "audit_scope_scan 的既有命中（只准減少；新增與修改的測試超過這裡的數字＝紅）。不得為了讓新測試過關而調高；沒有逃生口。",
                                        "total": sum(cur.values()), "files": cur}, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print("基線：%d 檔、%d 處" % (len(cur), sum(cur.values())))
        return 0
    base = load_baseline().get("files", {})
    bad = over_baseline(cur, base)
    for f, n, b in bad:
        print("%s：%d 處（基線 %d）" % (f, n, b))
        for ln, snip in scan_source((REPO / f).read_text(encoding="utf-8", errors="replace")):
            print("    %d %s" % (ln, snip))
    print("audit_scope：%d 檔超出基線" % len(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
