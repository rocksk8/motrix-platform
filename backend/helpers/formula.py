# -*- coding: utf-8 -*-
"""安全的公式（CUSTOMIZATION-SPEC §1「積木式、不能寫程式」、§8.1 ②「公式語法檢查回傳錯誤位置」）。

語法（v1）：
- 數字、字串（'…' 或 "…"）、`true`／`false`／`null`
- 欄位引用：直接寫欄位 key（例：`qty * unit_price`）
- 四則運算 `+ - * /`、取餘數 `%`；比較 `== != < <= > >=`；`and`／`or`／`not`
- 函式：`if(條件, 是, 否)`、`round(x[, 位數])`、`round_half_up(x[, 位數])`、`min(…)`、`max(…)`、`sum(…)`、`abs(x)`、
  `coalesce(a, b, …)`（第一個不是空值的）、`days_between(起, 迄)`（日期字串 YYYY-MM-DD）
  **天數規則**：`迄 − 起`，**不含起算日**——同一天＝0、隔天＝1、迄早於起＝負數；只取字串前 10 碼（帶時間的 `2026-10-01T23:59` 也只看日期）；
  任一邊空白 ⇒ 空值；格式錯（`2026-02-30`、`昨天`）⇒ 公式錯誤。要「含頭含尾」（例：請假 10/1～10/3 算 3 天）寫 `days_between(起, 迄) + 1`。
- 明細表（W1 建構器第三輪，2026-09-30）：`total(表, "欄")` 加總、`avg(表, "欄")` 平均、`count(表)` 列數。
  第一個參數是明細表欄位的 key（不加引號），第二個是該表某個數值欄的 key（字串）；空值不算 0：
  沒有任何數字 ⇒ `total` 回 0、`avg` 回空值；`count` 是列數（含空白列）。

**`round` 與 `round_half_up` 現況（2026-09-30 查證）**：兩者**同一種算法**＝四捨五入（.5 一律進位，例 12562.5 → 12563），
不是 Python 內建 `round()` 的銀行家捨入；實作走 L1 `helpers.legal_params.round_half_up`（稽核 D C-M4，營業稅規定）。
`round_half_up` 是明確名稱的別名——稅額公式寫它，讀公式的人不必猜；`round` 的既有語意不變。

不允許：屬性（`a.b`）、索引（`a[0]`）、次方、lambda、推導式、任何其他函式——解析時就拒絕，不執行。

**空值不等於 0**：引用到沒填的欄位 ⇒ 空值；空值參與四則運算 ⇒ 結果是空值（不是 0）；
`coalesce(qty, 0)` 才把它當 0。除以 0 ⇒ 空值並回報，不丟到呼叫端。
"""
import ast
from datetime import date
from decimal import Decimal

from helpers.legal_params import round_half_up

MAX_LENGTH = 500
MAX_DEPTH = 30
FUNCTIONS = ("if", "round", "round_half_up", "min", "max", "sum", "abs", "coalesce", "days_between",
             "total", "avg", "count")
#: 第一個參數是明細表、第二個是欄 key 的函式
TABLE_FUNCTIONS = ("total", "avg", "count")
_LITERALS = {"true": True, "false": False, "null": None}
_BIN = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/", ast.Mod: "%"}
_CMP = {ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">="}


class FormulaError(ValueError):
    def __init__(self, message, pos=None):
        super().__init__(message)
        self.pos = pos


_IF = "iF"          # `if` 是 Python 關鍵字 ⇒ 解析前把字串外的 `if(` 換成等長的名字，錯誤位置不變


def _rename_if(body):
    out, i, quote = [], 0, None
    while i < len(body):
        ch = body[i]
        if quote:
            out.append(ch)
            if ch == "\\" and i + 1 < len(body):
                out.append(body[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            out.append(ch)
        elif body.startswith("if", i) and (i == 0 or not (body[i - 1].isalnum() or body[i - 1] == "_")):
            j = i + 2
            while j < len(body) and body[j] == " ":
                j += 1
            if j < len(body) and body[j] == "(":
                out.append(_IF)
                i += 2
                continue
            out.append(ch)
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _lead(expr):
    return len(expr) - len(expr.lstrip())


def _pos(expr, node):
    """ast 的 col_offset（UTF-8 位元組，針對去掉前導空白的字串）⇒ 原字串的字元位置（0 起算）。"""
    body = expr.lstrip()
    return _lead(expr) + len(body.encode("utf-8")[:node.col_offset].decode("utf-8", errors="ignore"))


def _parse(expr):
    """回 ast.Expression；不合法 ⇒ 回（不是丟）FormulaError，帶位置。公式只能一行。"""
    if not isinstance(expr, str) or not expr.strip():
        return FormulaError("公式是空的", 0)
    if len(expr) > MAX_LENGTH:
        return FormulaError("公式太長（最多 %d 字）" % MAX_LENGTH, MAX_LENGTH)
    for i, ch in enumerate(expr):
        if ch in ("\r", "\n"):
            return FormulaError("公式只能一行", i)
    try:
        return ast.parse(_rename_if(expr.lstrip()), mode="eval")
    except SyntaxError as e:
        return FormulaError("語法錯誤：%s" % (e.msg or "無法解析"), _lead(expr) + max((e.offset or 1) - 1, 0))


def check(expr, fields=None, tables=None) -> list:
    """回 `[{"pos": 字元位置, "message": …}]`（空＝通過）。`fields` 給了 ⇒ 引用不存在的欄位也列出。
    `tables`：`{明細表 key: [可加總的數值欄 key…]}`；給了 ⇒ `total／avg／count` 的第一個參數必須是其中的表、
    第二個必須是該表的數值欄，而明細表不可以直接參與運算（只能當上面三個函式的第一個參數）。"""
    tree = _parse_or_error(expr)
    if isinstance(tree, dict):
        return [tree]
    problems = []
    known = set(fields) if fields is not None else None
    table_keys = set(tables) if tables is not None else set()
    #: 當作明細表參數用的 Name 節點 id（這些不算「直接參與運算」）
    table_args = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in TABLE_FUNCTIONS and n.args \
                and isinstance(n.args[0], ast.Name):
            table_args.add(id(n.args[0]))

    def walk(node, depth):
        if depth > MAX_DEPTH:
            problems.append({"pos": _pos(expr, node), "message": "公式巢狀太深（最多 %d 層）" % MAX_DEPTH})
            return
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float, str)) or isinstance(node.value, bool):
                problems.append({"pos": _pos(expr, node), "message": "不支援的常數 %r" % (node.value,)})
        elif isinstance(node, ast.Name):
            if node.id in _LITERALS:
                return
            if known is not None and node.id not in known:
                problems.append({"pos": _pos(expr, node), "message": "引用不到欄位 %s" % node.id})
            elif node.id in table_keys and id(node) not in table_args:
                problems.append({"pos": _pos(expr, node), "message": "明細表 %s 不能直接運算，請用 total／avg／count" % node.id})
        elif isinstance(node, ast.BinOp):
            if type(node.op) not in _BIN:
                problems.append({"pos": _pos(expr, node), "message": "不支援的運算（只能用 + - * / %）"})
            walk(node.left, depth + 1)
            walk(node.right, depth + 1)
        elif isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, (ast.USub, ast.UAdd, ast.Not)):
                problems.append({"pos": _pos(expr, node), "message": "不支援的運算"})
            walk(node.operand, depth + 1)
        elif isinstance(node, ast.BoolOp):
            for v in node.values:
                walk(v, depth + 1)
        elif isinstance(node, ast.Compare):
            for op in node.ops:
                if type(op) not in _CMP:
                    problems.append({"pos": _pos(expr, node), "message": "不支援的比較（只能用 == != < <= > >=）"})
            walk(node.left, depth + 1)
            for c in node.comparators:
                walk(c, depth + 1)
        elif isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else None
            name = "if" if name == _IF else name
            if name not in FUNCTIONS:
                problems.append({"pos": _pos(expr, node), "message": "不支援的函式 %s（可用：%s）" % (name or "?", "、".join(FUNCTIONS))})
            elif node.keywords:
                problems.append({"pos": _pos(expr, node.keywords[0].value), "message": "函式不接受具名參數"})
            else:
                n = len(node.args)
                ok = {"if": n == 3, "round": n in (1, 2), "round_half_up": n in (1, 2), "abs": n == 1, "days_between": n == 2,
                      "total": n == 2, "avg": n == 2, "count": n == 1}.get(name, n >= 1)
                if not ok:
                    problems.append({"pos": _pos(expr, node), "message": "%s 的參數個數不對" % name})
                elif name in TABLE_FUNCTIONS:
                    problems.extend(_check_table_call(expr, node, name, tables))
            for i, a in enumerate(node.args):
                if name in TABLE_FUNCTIONS and i == 1:
                    continue                                   # 欄 key 是字串常數，不當公式常數檢查
                walk(a, depth + 1)
        else:
            problems.append({"pos": _pos(expr, node), "message": "不支援的寫法（%s）" % type(node).__name__})

    walk(tree.body, 0)
    return problems


def _check_table_call(expr, node, name, tables):
    """`total(表, "欄")`／`avg(表, "欄")`／`count(表)` 的引數檢查。`tables` 是 None ⇒ 只檢查形狀。"""
    out = []
    first = node.args[0]
    if not isinstance(first, ast.Name):
        return [{"pos": _pos(expr, first), "message": "%s 的第一個參數必須是明細表欄位" % name}]
    if name != "count":
        col = node.args[1]
        if not (isinstance(col, ast.Constant) and isinstance(col.value, str)):
            return [{"pos": _pos(expr, col), "message": "%s 的第二個參數必須是欄位 key（加引號的文字）" % name}]
        if tables is not None and first.id in tables and col.value not in tables[first.id]:
            out.append({"pos": _pos(expr, col), "message": "明細表 %s 沒有可加總的數值欄 %s" % (first.id, col.value)})
    if tables is not None and first.id not in tables:
        out.append({"pos": _pos(expr, first), "message": "%s 不是明細表" % first.id})
    return out


def _parse_or_error(expr):
    r = _parse(expr)
    if isinstance(r, FormulaError):
        return {"pos": r.pos, "message": str(r)}
    return r


def references(expr) -> set:
    """公式引用到的欄位 key（語法錯誤 ⇒ 空集合；先 check 再用）。"""
    tree = _parse_or_error(expr)
    if isinstance(tree, dict):
        return set()
    funcs = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id not in _LITERALS and id(n) not in funcs}


def evaluate(expr, values: dict):
    """算出公式的值。語法或寫法不允許 ⇒ FormulaError（帶位置）；除以 0、型別不合 ⇒ FormulaError。"""
    problems = check(expr)
    if problems:
        raise FormulaError(problems[0]["message"], problems[0]["pos"])
    tree = _parse(expr)                                   # check 通過 ⇒ 一定是 ast.Expression
    values = values or {}

    def num(v, node):
        if v is None:
            return None
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise FormulaError("需要數字，得到 %r" % (v,), _pos(expr, node))
        return v

    def ev(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return _LITERALS[node.id] if node.id in _LITERALS else values.get(node.id)
        if isinstance(node, ast.UnaryOp):
            v = ev(node.operand)
            if isinstance(node.op, ast.Not):
                return not v
            v = num(v, node)
            return None if v is None else (-v if isinstance(node.op, ast.USub) else v)
        if isinstance(node, ast.BinOp):
            a, b = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Add) and isinstance(a, str) and isinstance(b, str):
                return a + b
            a, b = num(a, node.left), num(b, node.right)
            if a is None or b is None:
                return None
            if isinstance(node.op, (ast.Div, ast.Mod)) and b == 0:
                raise FormulaError("除以 0", _pos(expr, node))
            r = {ast.Add: lambda: a + b, ast.Sub: lambda: a - b, ast.Mult: lambda: a * b,
                 ast.Div: lambda: a / b, ast.Mod: lambda: a % b}[type(node.op)]()
            return int(r) if isinstance(r, float) and r.is_integer() and not isinstance(node.op, ast.Div) else r
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                r = True
                for v in node.values:
                    r = ev(v)
                    if not r:
                        return r
                return r
            r = False
            for v in node.values:
                r = ev(v)
                if r:
                    return r
            return r
        if isinstance(node, ast.Compare):
            left = ev(node.left)
            for op, c in zip(node.ops, node.comparators):
                right = ev(c)
                if type(op) in (ast.Eq, ast.NotEq):
                    ok = (left == right) if isinstance(op, ast.Eq) else (left != right)
                else:
                    if left is None or right is None:
                        return None
                    try:
                        ok = {ast.Lt: left < right, ast.LtE: left <= right, ast.Gt: left > right, ast.GtE: left >= right}[type(op)]
                    except TypeError:
                        raise FormulaError("無法比較 %r 與 %r" % (left, right), _pos(expr, node))
                if not ok:
                    return False
                left = right
            return True
        if isinstance(node, ast.Call):
            name = "if" if node.func.id == _IF else node.func.id
            if name == "if":
                return ev(node.args[1]) if ev(node.args[0]) else ev(node.args[2])
            if name in TABLE_FUNCTIONS:
                return _table_call(name, node, values, expr)
            args = [ev(a) for a in node.args]
            if name == "coalesce":
                return next((a for a in args if a is not None and a != ""), None)
            if name == "days_between":
                try:
                    d1, d2 = (date.fromisoformat(str(a)[:10]) if a else None for a in args)
                except ValueError:
                    raise FormulaError("days_between 需要日期（YYYY-MM-DD）", _pos(expr, node))
                return None if d1 is None or d2 is None else (d2 - d1).days
            nums = [num(a, node) for a in args]
            if any(a is None for a in nums):
                return None
            if name in ("round", "round_half_up"):
                # 四捨五入（稽核 D C-M4）：內建 round 是銀行家捨入（2.5 ⇒ 2），1.005 還會因浮點變 1.0。
                # 用 L1 法規參數那一支（主持裁示不另寫一份）：乘上 10^位數、四捨五入到整數、再除回來。
                digits = int(nums[1]) if len(nums) == 2 else 0
                scale = Decimal(10) ** digits
                n = round_half_up(nums[0], scale)
                if digits <= 0:
                    return int(Decimal(n) / scale)
                return float(Decimal(n) / scale)
            return {"min": lambda: min(nums), "max": lambda: max(nums), "sum": lambda: sum(nums),
                    "abs": lambda: abs(nums[0])}[name]()
        raise FormulaError("不支援的寫法", _pos(expr, node))           # check 已擋，理論上到不了

    return ev(tree.body)


def _table_call(name, node, values, expr):
    """`total／avg／count`：表值是 `[{欄: 值}]`。空值不算 0：`total` 沒有數字回 0、`avg` 沒有數字回空值。"""
    rows = values.get(node.args[0].id)
    rows = rows if isinstance(rows, list) else []
    if name == "count":
        return len(rows)
    col = node.args[1].value
    nums = []
    for r in rows:
        v = r.get(col) if isinstance(r, dict) else None
        if v is None or v == "":
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise FormulaError("明細表 %s 的 %s 欄有不是數字的值 %r" % (node.args[0].id, col, v), _pos(expr, node))
        nums.append(v)
    if name == "total":
        t = sum(nums) if nums else 0
        return int(t) if isinstance(t, float) and t.is_integer() else t
    if not nums:
        return None
    a = sum(nums) / len(nums)
    return int(a) if isinstance(a, float) and a.is_integer() else a


def evaluation_order(formulas: dict) -> list:
    """`{欄位: 公式}` ⇒ 計算順序（依引用關係）。有循環引用 ⇒ FormulaError，訊息列出循環。"""
    deps = {k: references(v) & set(formulas) for k, v in formulas.items()}
    order, state = [], {}

    def visit(k, path):
        if state.get(k) == "done":
            return
        if state.get(k) == "visiting":
            cycle = path[path.index(k):] + [k]
            raise FormulaError("公式循環引用：%s" % " → ".join(cycle))
        state[k] = "visiting"
        for d in sorted(deps[k]):
            visit(d, path + [k])
        state[k] = "done"
        order.append(k)

    for k in sorted(formulas):
        visit(k, [])
    return order
