import re, os, sys, json, ast
from pathlib import Path
B = Path(".")
pats = [re.compile(p) for p in (
    r'role["\']?\s*\)?\s*(?:in|==)\s*[\(\[\{]?\s*["\'](?:superadmin|admin)',
    r'\[\s*["\']superadmin["\']\s*,\s*["\']admin["\']\s*\]', r'\(\s*["\']superadmin["\']\s*,\s*["\']admin["\']\s*\)', r'\{\s*["\']superadmin["\']\s*,\s*["\']admin["\']\s*\}',
    r'["\']role["\']\]?\s*==\s*["\']admin["\']', r'_require_admin\(', r'require_admin\(', r'is_admin\(', r'_is_admin', r'role\s*==\s*["\']admin["\']', r'in\s*\(\s*["\']admin["\']')]
DOM = re.compile(r'(cashier|arap|payroll|salary|wage|payslip|voucher|remit|bank|account|bonus|withhold|ledger|financ|settle|money|amount|price|cost|profit|margin|expense|report|invoice|payable|receivable|pay_|payment|labor|tax|gl_|export|pdf|csv|xlsx)', re.I)
hits = []
for p in B.rglob("*.py"):
    s = str(p).replace("\\", "/")
    if "/tests/" in s or "test_" in p.name or ".venv" in s or "__pycache__" in s or "/tools/" in s and "check" in s: continue
    try: lines = p.read_text(encoding="utf-8-sig").split("\n")
    except Exception: continue
    # function map
    try: tree = ast.parse("\n".join(lines))
    except Exception: tree = None
    funcs = []
    if tree:
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)): funcs.append((n.lineno, getattr(n, "end_lineno", n.lineno), n.name))
    for i, l in enumerate(lines, 1):
        if l.lstrip().startswith("#"): continue
        if any(pt.search(l) for pt in pats):
            fn = next((nm for a, b, nm in sorted(funcs, key=lambda x: x[1]-x[0]) if a <= i <= b), "")
            hits.append({"file": s, "line": i, "func": fn, "text": l.strip()[:150], "dom": bool(DOM.search(s) or DOM.search(fn) or DOM.search(l))})
json.dump(hits, open(os.path.join(os.environ["TEMP"], "da_admin_hits.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(len(hits), sum(h["dom"] for h in hits))
from collections import Counter
c = Counter(h["file"] for h in hits if h["dom"]); print(c.most_common(40))
