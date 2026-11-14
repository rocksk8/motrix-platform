# -*- coding: utf-8 -*-
"""測試寫法掃描：測試讀「全域稽核表／失敗表」時，必須依自己建立的使用者或 request 篩選（T87 A2；T86 正式閘門 test_quote_put_fail_reason_codes 教訓）。

[單位] tools:audit_scope_scan   [層] 工具   [穩定度] 內部
[不變式]
  * 只讀不寫；純 AST 掃描。守門測試 `tests/platform/test_audit_reads_scoped_to_own_rows_2026_11_14.py` 與 author_gate --quick 共用這一份。
  * 掃的是測試檔裡的字串常數（含 f-string 的常數段）：同一個字串含 `FROM <全域表>`，卻沒有任何「自己的範圍」條件 ⇒ 命中。
      全域表：AUDIT_TABLES（目前 audit_log——失敗列與一般稽核列都在這裡）。
      自己的範圍：WHERE 內出現 username／user_id／actor／request_id／target／entity／object／quote_no／case_id／doc_no／ref_id 這類欄位，
                 或 `id >`／`rowid >`／`created_at >`（用查詢前的水位線只看自己這次新增的列）。
  * 為什麼：`SELECT * FROM audit_log WHERE result='fail'` 讀到的是整個資料庫的失敗列；單獨跑會綠，整包跑時別的測試留下的列讓
    `len(rows) == 1` 變成 `len(rows) == 3`（T86 正式閘門才抓到）。
  * 逃生口：字串所在的行加真正的註解 `# audit-scope-ok: <理由>`（理由 ≥8 字元且≥2 詞或中文≥4 字；例如這個測試用的是獨立資料庫）；使用數另有棘輪（基線 hatches）。
  * 棘輪：既有檔的命中數記在 `tests/platform/audit_scope_baseline.json`（只准減少）；新檔與有改動的檔超過基線＝紅。
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

import text_anchor_scan as TA  # noqa: E402  （棘輪 over_baseline／測試檔判定共用）

AUDIT_TABLES = ("audit_log",)
BASELINE = REPO / "backend" / "tests" / "platform" / "audit_scope_baseline.json"
_FROM = re.compile(r"\bFROM\s+(%s)\b" % "|".join(AUDIT_TABLES), re.I)
_SCOPE = re.compile(
    r"\b(username|user_id|user_name|actor|actor_id|actor_username|request_id|target|target_id|entity|entity_id|object_id|quote_no|case_id|doc_no|ref_id|"
    r"record_id|session_id)\b|\b(rowid|id|created_at|ts|at)\s*>\s*[?:\w]", re.I)
_STMT = re.compile(r"\s*(SELECT|WITH|DELETE|UPDATE)\b", re.I)                # 只認 SQL 敘述開頭的字串（說明文字、docstring 提到 FROM audit_log 不算）
_OK_REASON = re.compile(r"#\s*audit-scope-ok:\s*(.*)$")


def _strings(tree):
    """⇒ [(起始行, 完整字串)]；JoinedStr 取其常數段（變數段留空白）。巢在 JoinedStr 裡的常數不重複計。"""
    out, inside = [], set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for v in node.values:
                inside.add(id(v))
            out.append((node.lineno, "".join(v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else " " for v in node.values)))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in inside:
            out.append((node.lineno, node.value))
    return out


def hatch_lines(src):
    """⇒ {行號: 理由}：真正的註解 token 裡、理由合格（≥8 字元且≥2 詞或中文≥4 字）的 `# audit-scope-ok: …`。"""
    out = {}
    for ln, c in TA.comment_lines(src, "audit-scope-ok").items():
        m = _OK_REASON.search(c)
        if m and TA.valid_reason(m.group(1)):
            out[ln] = m.group(1).strip()
    return out


def _collect(src):
    """⇒ [(行號, 片段, 逃生口行號或 None)]。語法錯誤的檔 ⇒ []（別的守門會抓）。"""
    if not any(t in src for t in AUDIT_TABLES):
        return []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")                  # 被掃的檔裡的 SyntaxWarning（無效跳脫）不是這個守門的事
            tree = ast.parse(src)
    except SyntaxError:
        return []
    hatches = hatch_lines(src)
    hits = []
    for ln, s in _strings(tree):
        m = _FROM.search(s)
        if not m or not _STMT.match(s) or _SCOPE.search(s):
            continue
        h = next((n for n in range(ln, ln + s.count(chr(10)) + 1) if n in hatches), None)
        hits.append((ln, " ".join(s.split())[:60], h))
    return sorted(set(hits), key=lambda x: (x[0], x[1]))


def scan_source(src):
    """⇒ [(行號, 片段)]。有有效逃生口註解者略過。"""
    return [(ln, sn) for ln, sn, h in _collect(src) if h is None]


def hatch_uses(src):
    hatches = hatch_lines(src)
    return sorted((h, hatches[h]) for h in {h for _l, _s, h in _collect(src) if h is not None})


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


def hatches_in_tree(files, read):
    out = {}
    for f in files:
        src = read(f)
        u = hatch_uses(src) if src is not None else []
        if u:
            out[f] = len(u)
    return out


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
    hat = hatches_in_tree(paths, lambda f: (REPO / f).read_text(encoding="utf-8", errors="replace") if (REPO / f).is_file() else None)
    if write:
        old = load_baseline()
        if old.get("files") and not any(not a.startswith("--") for a in argv):
            up = over_baseline(cur, old["files"]) + [(f, n, old.get("hatches", {}).get(f, 0)) for f, n in hat.items() if n > old.get("hatches", {}).get(f, 0)]
            if up:
                for f, n, b in up[:10]:
                    print("拒絕：%s 現在 %d、基線 %d——基線只准往下寫" % (f, n, b))
                return 1
        BASELINE.write_text(json.dumps({"version": 2, "_doc": "audit_scope_scan 的既有命中（只准減少；新增與修改的測試超過這裡的數字＝紅）。不得為了讓新測試過關而調高。",
                                        "total": sum(cur.values()), "files": cur, "hatches": hat}, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print("基線：%d 檔、%d 處；逃生口 %d 處" % (len(cur), sum(cur.values()), sum(hat.values())))
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
