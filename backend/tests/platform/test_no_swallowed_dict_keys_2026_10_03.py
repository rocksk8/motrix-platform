# -*- coding: utf-8 -*-
"""字典項目中間不得有「吞掉後續鍵」的行內註解（第 32 班 M-1：`"diff": …,  # 說明 "fee": …, "paidAt": …` ——
整串 `"fee": …` 落在 `#` 之後變成註解，字典少了兩個鍵、語法仍然合法、沒有任何錯誤）。

規則（tokenize）：`backend/**/*.py`（含測試）的行內註解（`#` 前面有程式碼），若
  (a) 註解內含 `"鍵":` 或 `'鍵':` 的樣子，且 (b) `#` 前的程式碼以 `,` 結尾（還在字典／清單項目之間）
⇒ 紅。註解要放行首或項目結尾後（不再接 `"key":`）。正對照：合成 M-1 那一行必須被抓、正常註解必須放行。
"""
import io
import re
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]            # backend/
_KEY = re.compile(r"""["'][A-Za-z_]\w*["']\s*:\s""")
_SKIP = ("__pycache__", ".venv", "node_modules")
#: 已人工確認無害（註解只是在說明資料形狀，行內沒有被吞掉的程式碼）：「相對路徑:行號」。新增項目要附理由。
ALLOW = {"modules/accounting/api/accounting_export.py:93"}      # `"bankAccounts": [],   # [{"name": str, "acctCode": str}, ...]，設定頁維護…`


def suspicious(src):
    """⇒ [(行號, 註解前 60 字)]。"""
    out = []
    for t in tokenize.generate_tokens(io.StringIO(src).readline):
        if t.type != tokenize.COMMENT:
            continue
        code = t.line[:t.start[1]].rstrip()
        if code.strip() and code.endswith(",") and _KEY.search(t.string):
            out.append((t.start[0], code.strip()[-60:]))
    return out


def test_scanner_positive_control():
    m1 = '''d = {\n    "diff": max(0, x),          # 只有多付才有差額 "fee": float(f), "paidAt": p,\n    "paidBy": b,\n}\n'''
    assert [n for n, _ in suspicious(m1)] == [2]
    ok = '''d = {\n    # 只有多付才有差額\n    "diff": max(0, x), "fee": float(f),\n    "paidBy": b,   # 付款人\n}\nx = {}   # kind -> {"label": str}\n'''
    assert suspicious(ok) == []


def test_no_inline_comment_swallows_following_dict_keys():
    bad = []
    for p in sorted(ROOT.rglob("*.py")):
        if any(s in p.as_posix() for s in _SKIP):
            continue
        try:
            src = p.read_text(encoding="utf-8")
            hits = suspicious(src)
        except (UnicodeDecodeError, tokenize.TokenError, SyntaxError, IndentationError):
            continue
        rel = p.relative_to(ROOT).as_posix()
        bad += ["%s:%d  …%s" % (rel, n, c) for n, c in hits if "%s:%d" % (rel, n) not in ALLOW]
    assert not bad, "行內註解把後面的 \"key\": 吞成註解（字典少鍵、語法仍合法）：\n" + "\n".join(bad[:20])
