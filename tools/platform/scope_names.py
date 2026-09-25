"""名稱層級選題（PLAYBOOK §C-11a ③）：被改的單位只有某幾個頂層名稱變了 ⇒ 只選「用到這些名稱」的直接使用者。

解決「寬扇出」：一個 helper 被幾十個單位直接 import（email_notify 26、auth 46、db 56），只看直接依賴仍有 70～90%。

兩個純函式，都以 AST 判斷、**判斷不了一律回 ALL**（保守＝回到直接依賴全選）：
  changed_names(舊原始碼, 新原始碼) ⇒ 內容有變的頂層名稱集合，或 ALL（模組層級的其他敘述有變、解析失敗）
  used_names(使用者原始碼, 目標模組點名, 再匯出表) ⇒ 使用者用到目標的哪些名稱，或 ALL，或 set()（找不到 import）
"""
import ast

ALL = None      # 「全部名稱」；以 None 表示，呼叫端用 `is ALL` 判斷


def _defs(tree):
    """頂層定義 ⇒ {名稱: ast.dump}；其餘模組層級敘述 ⇒ 另一份 dump 清單（有變 ⇒ ALL）。"""
    names, rest = {}, []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names[node.name] = ast.dump(node, include_attributes=False)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and all(
                isinstance(t, ast.Name) for t in (node.targets if isinstance(node, ast.Assign) else [node.target])):
            for t in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                names[t.id] = ast.dump(node, include_attributes=False)
        elif isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant) \
                and isinstance(node.value.value, str):
            continue                                     # docstring
        else:
            rest.append(ast.dump(node, include_attributes=False))
    return names, rest


def changed_names(old_src, new_src):
    try:
        (on, orest), (nn, nrest) = _defs(ast.parse(old_src)), _defs(ast.parse(new_src))
    except SyntaxError:
        return ALL
    if orest != nrest:
        return ALL              # import、if、try 等模組層級程式有變 ⇒ 影響範圍看不出來
    return {k for k in set(on) | set(nn) if on.get(k) != nn.get(k)}


def used_names(src, target, reexp=None):
    """target：目標的點名（`helpers.email_notify`、`db`、`core.events`、`modules.tender_radar.api`）。
    reexp：`helpers/__init__` 的再匯出 {名稱: 來源模組葉名}（`from helpers import f` 對回 email_notify）。"""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return ALL
    parent, _, leaf = target.rpartition(".")
    names, aliases = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level == 0 and mod == target:
                for a in node.names:
                    if a.name == "*":
                        return ALL
                    names.add(a.name)
            elif node.level == 0 and parent and mod == parent:
                for a in node.names:
                    if a.name == leaf:
                        aliases.add(a.asname or a.name)             # from helpers import email_notify
                    elif reexp and reexp.get(a.name) == leaf:
                        names.add(a.name)                           # from helpers import send_x（再匯出）
            elif node.level == 1 and parent and mod == leaf:
                names |= {a.name for a in node.names}               # 同套件：from .email_notify import f
            elif node.level == 1 and parent and not mod:
                aliases |= {(a.asname or a.name) for a in node.names if a.name == leaf}
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name == target:
                    if a.asname or "." not in target:
                        aliases.add(a.asname or target)             # import db／import helpers.x as m
                    else:
                        return ALL                                  # import helpers.x ⇒ helpers.x.f(…) 鏈太長，保守
    if aliases:
        attr_nodes = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases:
                names.add(node.attr)
                attr_nodes.add(id(node.value))
            # setattr／getattr／delattr／monkeypatch.setattr(m, "NAME", …)：第二個參數指明了名稱 ⇒ 不算整個模組被傳出去
            elif isinstance(node, ast.Call) and len(node.args) >= 2 and isinstance(node.args[0], ast.Name) \
                    and node.args[0].id in aliases and isinstance(node.args[1], ast.Constant) \
                    and isinstance(node.args[1].value, str) \
                    and ((isinstance(node.func, ast.Name) and node.func.id in ("setattr", "getattr", "delattr", "hasattr"))
                         or (isinstance(node.func, ast.Attribute) and node.func.attr in ("setattr", "delattr"))):
                names.add(node.args[1].value)
                attr_nodes.add(id(node.args[0]))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in aliases and id(node) not in attr_nodes \
                    and isinstance(node.ctx, ast.Load):
                return ALL                                          # 模組物件被整個傳出去
    return names


def _def_names(node):
    """一個模組層級敘述定義了哪些名稱（def／class／簡單指派）。"""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    if isinstance(node, ast.Assign):
        return {t.id for t in node.targets if isinstance(t, ast.Name)}
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return {node.target.id}
    return set()


def name_tables(sources, names, known):
    """只看 names 這幾個頂層定義（新舊兩版都看：刪掉的 SQL 也算）讀寫的資料表，格式同 dep_graph 單位欄位。
    規則與 dep_scan 相同（string_chunks＋sql_tables＋表名字串）。解析失敗 ⇒ None（呼叫端退回整個單位的資料表）。"""
    from dep_scan import sql_tables, string_chunks
    r, w, ddl, named, dyn = set(), set(), set(), set(), False
    for src in sources:
        try:
            tree = ast.parse(src)
        except SyntaxError:
            return None
        for node in tree.body:
            if not (_def_names(node) & set(names)):
                continue
            a, b, c, d = sql_tables(string_chunks(node), known)
            r |= a
            w |= b
            ddl |= c
            dyn = dyn or d
            named |= {n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and n.value in known}
    return {"tables_r": sorted(r - w), "tables_w": sorted(w), "tables_ddl": sorted(ddl),
            "tables_named": sorted(named - w - ddl), "dynamic_sql": dyn}


def dotted(unit_path):
    """`backend/helpers/email_notify.py` ⇒ `helpers.email_notify`；`backend/db.py` ⇒ `db`。"""
    p = unit_path[len("backend/"):] if unit_path.startswith("backend/") else unit_path
    p = p[:-3] if p.endswith(".py") else p
    parts = p.split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)
