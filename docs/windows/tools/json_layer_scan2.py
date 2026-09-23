# -*- coding: utf-8 -*-
"""JSON 層掃描 v2：補上 v1 的兩個盲區。

v1 判「產品有沒有寫這個鍵」只看 **Python 的 dict 字面值／下標賦值**，於是 4 個候選全是假陽性：
  盲區A  鍵其實是**資料表欄位** ⇒ 產品 dict(row) 就有這個鍵，沒有任何 dict 字面值
         （total_cost／unit_cost 是 case_extra_expenses 的欄位）
  盲區B  鍵是由**前端**寫的 ⇒ 我只掃 Python 就看不到
         （directMarginPct／netProfit 寫在 quotation-form.html 的物件字面值裡）

⇒ v2 的「產品可以寫進這個鍵」＝ Python 寫入 ∪ **DB 欄位名** ∪ **前端寫入位置**。
"""
import ast
import collections
import glob
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\hichan\Desktop\MOTRIX-ERP"
SQL_W = re.compile(r"\b(INSERT\s+(?:OR\s+\w+\s+)?INTO|UPDATE)\b", re.I)


def rd(p):
    return io.open(p, encoding="utf-8", errors="replace").read()


def parse(p):
    try:
        return ast.parse(rd(p))
    except SyntaxError:
        return None


def dict_keys(node, prefix=""):
    out = []
    if isinstance(node, ast.Dict):
        for k, v in zip(node.keys, node.values):
            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                p = prefix + "." + k.value if prefix else k.value
                out.append((p, k.value))
                out += dict_keys(v, p)
    elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        for e in node.elts:
            out += dict_keys(e, prefix + "[]")
    elif isinstance(node, ast.Call):
        for a in list(node.args) + [kw.value for kw in node.keywords]:
            out += dict_keys(a, prefix)
    return out


def is_sql_write(call):
    if not (isinstance(call.func, ast.Attribute)
            and call.func.attr in ("execute", "executemany")) or not call.args:
        return False
    a0 = call.args[0]
    if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
        return bool(SQL_W.search(a0.value))
    if isinstance(a0, (ast.BinOp, ast.JoinedStr)):
        try:
            return bool(SQL_W.search(ast.unparse(a0)))
        except Exception:
            return False
    return False


def test_side(paths):
    keys = collections.defaultdict(list)
    unres = []
    for f in paths:
        tree = parse(f)
        if tree is None:
            continue
        env = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign) and isinstance(n.value, (ast.Dict, ast.List)):
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        env[t.id] = n.value
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and is_sql_write(node)):
                continue
            for d in [x for x in ast.walk(node)
                      if isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute)
                      and x.func.attr == "dumps" and x.args]:
                arg = d.args[0]
                tgt = env.get(arg.id) if isinstance(arg, ast.Name) else arg
                if tgt is None:
                    unres.append((f, node.lineno, arg.id))
                    continue
                for path, k in dict_keys(tgt):
                    keys[k].append((f, node.lineno, path))
    return keys, unres


def py_side(paths):
    w, r = collections.defaultdict(list), collections.defaultdict(list)
    for f in paths:
        tree = parse(f)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for st in node.body:
                    if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                        w[st.target.id].append((f, st.lineno, "model-field"))
            if isinstance(node, ast.Dict):
                for k in node.keys:
                    if isinstance(k, ast.Constant) and isinstance(k.value, str):
                        w[k.value].append((f, node.lineno, "py dict-literal"))
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant) \
                       and isinstance(t.slice.value, str):
                        w[t.slice.value].append((f, node.lineno, "py subscript-assign"))
            elif isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Attribute) and node.args \
                   and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    if fn.attr == "setdefault":
                        w[node.args[0].value].append((f, node.lineno, "py setdefault"))
                    elif fn.attr == "get":
                        r[node.args[0].value].append((f, node.lineno, "py get"))
            elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
                    and isinstance(node.slice.value, str):
                r[node.slice.value].append((f, node.lineno, "py subscript-read"))
    return w, r


def db_columns():
    """盲區A：資料表欄位名 —— 產品 dict(row) 之後這些就是 JSON 鍵。"""
    s = rd(os.path.join(ROOT, "backend", "db.py"))
    cols = collections.defaultdict(list)
    for m in re.finditer(r"CREATE TABLE IF NOT EXISTS\s+(\w+)\s*\((.*?)\n\s*\)", s, re.S):
        for line in m.group(2).split("\n"):
            t = line.strip()
            if not t or t.startswith(("--", "#", "FOREIGN", "UNIQUE", "PRIMARY", "CHECK")):
                continue
            c = t.split()[0].strip('",')
            if re.fullmatch(r"[A-Za-z_]\w*", c):
                cols[c].append(("db.py", 0, "column of " + m.group(1)))
    for m in re.finditer(r"ADD COLUMN\s+(\w+)", s):
        cols[m.group(1)].append(("db.py", 0, "ALTER ADD COLUMN"))
    # INSERT 的欄位清單也算
    for m in re.finditer(r"INSERT\s+(?:OR\s+\w+\s+)?INTO\s+\w+\s*\(([^)]*)\)", s, re.I | re.S):
        for c in m.group(1).split(","):
            c = c.strip().strip('"')
            if re.fullmatch(r"[A-Za-z_]\w*", c):
                cols[c].append(("db.py", 0, "insert column"))
    return cols


def frontend_side():
    """盲區B：前端寫入位置 —— 物件字面值的 key、.key = 、["key"] = 。"""
    w = collections.defaultdict(list)
    files = glob.glob(os.path.join(ROOT, "frontend", "**", "*.js"), recursive=True) \
        + glob.glob(os.path.join(ROOT, "frontend", "**", "*.html"), recursive=True)
    OBJ = re.compile(r"(?m)(?:^|[\{,]\s*)([A-Za-z_$][\w$]*)\s*:")
    DOT = re.compile(r"\.([A-Za-z_$][\w$]*)\s*=(?!=)")
    SUB = re.compile(r"""\[\s*['"]([A-Za-z_$][\w$]*)['"]\s*\]\s*=(?!=)""")
    for f in files:
        if "vendor" in f.replace("\\", "/"):
            continue
        s = rd(f)
        rel = os.path.relpath(f, ROOT).replace("\\", "/")
        for rx, how in ((OBJ, "js obj-key"), (DOT, "js .key="), (SUB, "js [key]=")):
            for m in rx.finditer(s):
                w[m.group(1)].append((rel, s.count("\n", 0, m.start()) + 1, how))
    return w


def main():
    os.chdir(os.path.join(ROOT, "backend"))
    TESTS = sorted(glob.glob("tests/*.py"))
    PROD = [p for p in glob.glob("**/*.py", recursive=True)
            if not p.replace("\\", "/").startswith(("tests/", "tools/", "rollback_snapshots/"))]
    tk, unres = test_side(TESTS)
    pw, pr = py_side(PROD)
    cols = db_columns()
    fw = frontend_side()

    def written(k):
        for src, label in ((pw, "Python"), (cols, "DB 欄位"), (fw, "前端")):
            if k in src:
                return label, src[k][0]
        return None, None

    print("=== 母體 ===")
    print("  測試側（直接 SQL ＋ json.dumps）的鍵 = %d 種" % len(tk))
    print("  產品可寫來源：Python %d 種 ／ DB 欄位 %d 種 ／ 前端 %d 種"
          % (len(pw), len(cols), len(fw)))
    print("  ⚠️ 仍有的盲區：dumps(變數) 解析不到 = %d 處" % len(unres))

    guard, noise, ok = [], [], []
    for k in tk:
        label, _ = written(k)
        if label:
            ok.append((k, label))
        elif k in pr:
            guard.append(k)
        else:
            noise.append(k)
    print()
    print("=== 判定 ===")
    print("  產品可寫（不是問題）          %d 種" % len(ok))
    print("  **產品讀得到、寫不進去 ⇒ §196  %d 種**" % len(guard))
    print("  產品既不寫也不讀（fixture 雜訊） %d 種" % len(noise))
    print("  ✅ 收斂 %d = %d + %d + %d" % (len(tk), len(ok), len(guard), len(noise)))

    print()
    print("=== §196 候選（全部列出＋命中內容）===")
    if not guard:
        print("  （無）")
    for k in sorted(guard):
        f, ln, path = tk[k][0]
        rf, rl, how = pr[k][0]
        print("  %-24s 測試 %s:%d 路徑 %s ／ 產品讀 %s:%d (%s)"
              % (repr(k), os.path.basename(f), ln, path, rf, rl, how))

    print()
    print("=== ⚙️ 負對照：畫面改得動的鍵**不可以**被報出來 ===")
    for k in ("invoiceFiles", "materials", "description", "category", "netProfit",
              "directMarginPct", "total_cost", "unit_cost"):
        label, loc = written(k)
        status = "✅ 判成可寫（%s）" % label if label else ("🔴 被報成 §196" if k in pr else "－ 不在測試側")
        print("  %-18s %s %s" % (k, status, ("← " + str(loc)) if loc else ""))

    print()
    print("=== ⚙️ 正對照：合成一個「產品只讀不寫」的鍵，它必須亮 ===")
    synth = [k for k in pr if not written(k)[0]]
    print("  產品有讀而三個來源都沒寫的鍵共 %d 種；取前 3 個當合成測試輸入：" % len(synth))
    for k in sorted(synth)[:3]:
        rf, rl, how = pr[k][0]
        cls = "✅ 會被判成 §196" if (k not in [x[0] for x in ok]) else "🔴"
        print("     %-24s %s   （產品讀 %s:%d %s）" % (repr(k), cls, rf, rl, how))


main()
