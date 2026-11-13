# -*- coding: utf-8 -*-
"""列出設定登錄表相關原始碼中含「禁用詞」的位置（S1c 禁用詞原文修正用）。

用法（repo 根目錄下）：
    python -I -X utf8 docs/platform/plans/SETTINGS-MATRIX-ROLLOUT/h12/scan_banned_words.py [--csv out.csv]

分類（kind）：
  ui    ＝程式裡的字串常數（使用者看得到：question/help/impact/risk_text/choices/警告句…）→ **必改**
  doc   ＝docstring（開發者看，不是使用者）                                        → 建議順手改
  cmt   ＝# 註解                                                                    → 可不改（守門測試不掃）
掃描範圍：backend/helpers/settings_groups*.py、settings_registry.py、routers/settings_center.py
禁用詞：確認期間、影子、閘門、true/false（獨立單字，字串內）。
建議改寫：確認期間 → 「要等 N 天才生效」（N 由呼叫端帶入）；影子 → 「只記錄、不生效」；閘門 → 「檢查／關卡以外的白話」。
"""
import ast, io, re, sys, tokenize, pathlib, csv

BANNED = [('確認期間', re.compile('確認期間')), ('影子', re.compile('影子')),
          ('閘門', re.compile('閘門')), ('true/false', re.compile(r'(?<![A-Za-z_])(true|false)(?![A-Za-z_])', re.I))]
FILES = ['backend/helpers/settings_registry.py', 'backend/routers/settings_center.py']


def files(root):
    out = [root / f for f in FILES]
    out += sorted((root / 'backend/helpers').glob('settings_groups*.py'))
    return [p for p in out if p.exists()]


def scan(path, root):
    src = path.read_text(encoding='utf-8')
    rel = path.relative_to(root).as_posix()
    rows = []
    tree = ast.parse(src)
    doc_nodes = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body \
                and isinstance(n.body[0], ast.Expr) and isinstance(getattr(n.body[0], 'value', None), ast.Constant) \
                and isinstance(n.body[0].value.value, str):
            doc_nodes.add(id(n.body[0].value))
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            kind = 'doc' if id(n) in doc_nodes else 'ui'
            for name, rx in BANNED:
                if rx.search(n.value):
                    rows.append((rel, n.lineno, kind, name, re.sub(r'\s+', ' ', n.value)[:140]))
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            for name, rx in BANNED:
                if rx.search(tok.string):
                    rows.append((rel, tok.start[0], 'cmt', name, tok.string[:140]))
    return rows


def main():
    root = pathlib.Path.cwd()
    rows = []
    for p in files(root):
        rows += scan(p, root)
    rows.sort(key=lambda r: (r[2] != 'ui', r[0], r[1]))
    for r in rows:
        print('%-4s %-11s %s:%d  %s' % (r[2], r[3], r[0], r[1], r[4][:80]))
    from collections import Counter
    c = Counter((r[2], r[3]) for r in rows)
    print('\n-- 統計 --')
    for k, v in sorted(c.items()):
        print(k, v)
    if '--csv' in sys.argv:
        out = sys.argv[sys.argv.index('--csv') + 1]
        with open(out, 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.writer(f, lineterminator='\r\n')
            w.writerow(['kind', '禁用詞', '檔案', '行', '字串節錄'])
            for r in rows:
                w.writerow([r[2], r[3], r[0], r[1], r[4]])


if __name__ == '__main__':
    main()
