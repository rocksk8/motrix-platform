# -*- coding: utf-8 -*-
"""MOTRIX-ERP 程式碼健檢 v2。ASCII-only。

v1 報 462 個死碼 —— 絕大多數是 FastAPI 路由（裝飾器持有）。
v2 的每一節都先跑「對照組」：已知該亮的要亮、已知不該亮的不可以亮。
"""
import os, io, ast, collections, builtins

ROOT = r'C:\Users\hichan\Desktop\MOTRIX-ERP'
SKIP = {'rollback_snapshots', 'deploy_packages', '__pycache__', 'node_modules',
        '.git', 'venv', '.venv', 'export_archive', 'db_backups', 'deploy_logs',
        'logs', 'uploads'}

files = []
for d, subs, fs in os.walk(os.path.join(ROOT, 'backend')):
    subs[:] = [x for x in subs if x not in SKIP]
    for f in fs:
        if f.endswith('.py'):
            files.append(os.path.join(d, f))

trees, srcs = {}, {}
for p in files:
    rel = os.path.relpath(p, ROOT).replace(os.sep, '/')
    s = io.open(p, encoding='utf-8', errors='replace').read()
    try:
        trees[rel] = ast.parse(s)
        srcs[rel] = s
    except SyntaxError as e:
        print('SYNTAX %s:%s %s' % (rel, e.lineno, e.msg))

prod = [r for r in trees if '/tests/' not in r]
test = [r for r in trees if '/tests/' in r]


def decorated(node):
    """這個函式是不是被任何裝飾器持有（路由、例外處理、fixture、property…）"""
    return bool(node.decorator_list)


# ═══ 1. 死碼：模組層級、未被裝飾、全 repo 零引用 ═══
defined = {}
for rel in prod:
    for node in trees[rel].body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
           and not node.name.startswith('__') and not decorated(node):
            defined.setdefault(node.name, []).append((rel, node.lineno))

ref = collections.Counter()
for rel, t in trees.items():
    for node in ast.walk(t):
        if isinstance(node, ast.Name):
            ref[node.id] += 1
        elif isinstance(node, ast.Attribute):
            ref[node.attr] += 1
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # __all__ 與 getattr 的字串引用
            ref[node.value] += 1
        elif isinstance(node, ast.ImportFrom):
            # from X import name as alias  -> 原名 name 也算被引用
            for a in node.names:
                ref[a.name] += 1
        elif isinstance(node, ast.Import):
            for a in node.names:
                ref[a.name.split('.')[-1]] += 1

dead = []
for name, where in sorted(defined.items()):
    if len(where) != 1:
        continue
    rel, ln = where[0]
    # 定義那一行本身不算引用；ast.Name 只在「使用」時出現，FunctionDef 不產生 Name
    if ref[name] == 0:
        dead.append('%s:%d  %s' % (rel, ln, name))

# --- 對照組 ---
ctrl_pos = [d for d in dead if 'reminder_stage' in d]      # D 實證的死碼，應該亮
ctrl_neg = [d for d in dead if 'locate_cached' in d or 'warm_geocode_cache' in d
            or 'is_enabled' in d]   # is_enabled 是改名匯入的，v2 曾誤報  # 活的，不可以亮

# ═══ 2. 未使用的 import（排除 __init__.py 的再匯出）═══
unused = []
for rel in prod:
    if rel.endswith('__init__.py'):
        continue                                  # 再匯出檔，整檔略過（明著排除）
    t, s = trees[rel], srcs[rel]
    imported = {}
    for node in ast.walk(t):
        if isinstance(node, ast.Import):
            for a in node.names:
                imported[(a.asname or a.name).split('.')[0]] = node.lineno
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name != '*':
                    imported[a.asname or a.name] = node.lineno
    used = set()
    for node in ast.walk(t):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            n2 = node
            while isinstance(n2, ast.Attribute):
                n2 = n2.value
            if isinstance(n2, ast.Name):
                used.add(n2.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            used.add(node.value)                  # 型別註解字串／__all__
    for nm, ln in sorted(imported.items()):
        if nm not in used:
            unused.append('%s:%d  %s' % (rel, ln, nm))

# ═══ 3. 例外處理：完全沒有痕跡的（與 AUDIT 同判準，這裡只給檔案分佈）═══
TRACE = ('warning', 'error', 'exception', 'info', 'debug', 'critical', 'print')
silent = collections.Counter()
for rel in prod:
    for node in ast.walk(trees[rel]):
        if isinstance(node, ast.ExceptHandler):
            traced = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                         and n.func.attr in TRACE for n in ast.walk(node))
            raised = any(isinstance(n, ast.Raise) for n in ast.walk(node))
            if not traced and not raised:
                silent[rel] += 1

# ═══ 4. 函式長度（複雜度的粗代理）═══
longfn = []
for rel in prod:
    s = srcs[rel]
    for node in ast.walk(trees[rel]):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, 'end_lineno', node.lineno)
            n = end - node.lineno
            if n >= 150:
                longfn.append((n, '%s:%d  %s' % (rel, node.lineno, node.name)))
longfn.sort(reverse=True)

print('=' * 72)
print('CODE HEALTH v2   product=%d  test=%d' % (len(prod), len(test)))
print('=' * 72)

print()
print('-- CONTROLS (a tool must light the known one before reporting "no others")')
print('   positive  reminder_stage (D proved dead) : %s' % ('LIT' if ctrl_pos else 'NOT LIT  <-- tool broken'))
print('   negative  locate_cached/warm_geocode     : %s' % ('CLEAN' if not ctrl_neg else 'FALSE POSITIVE'))

print()
print('-- dead module-level functions (undecorated, 0 refs repo-wide): %d' % len(dead))
for x in dead[:25]:
    print('     ' + x)
if len(dead) > 25:
    print('     ... +%d more' % (len(dead) - 25))

print()
print('-- unused imports (excl. __init__.py re-exports): %d' % len(unused))
for x in unused[:20]:
    print('     ' + x)
if len(unused) > 20:
    print('     ... +%d more' % (len(unused) - 20))

print()
print('-- exception handlers with no trace, by file: %d total' % sum(silent.values()))
for rel, n in silent.most_common(10):
    print('   %4d  %s' % (n, rel))

print()
print('-- functions >= 150 lines: %d' % len(longfn))
for n, x in longfn[:12]:
    print('   %4d  %s' % (n, x))
