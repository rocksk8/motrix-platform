"""`PX1` · 權限訊息說的角色，與程式實際檢查的角色，要是同一件事（`STATE.md` 總表 `PX1`）。

```
說得比實際嚴  訊息說「只有最高管理員」，而 admin 也放行  ⇒ 有人進得去而不該進（安全缺陷，不會報錯）
說得比實際鬆  訊息泛稱「管理員」，而只有 superadmin 放行  ⇒ admin 被誤導、卡住
```
量尺照 `docs/windows/tools/px1_scan.py`（`STATE §267／§269` 盤點過：0 處不一致）搬進 pytest，
讓「0」從一次性的盤點變成**會擋下一次**的守門。

⚙️ 規格要求「必須先找到一個確定不一致的當正對照，找不到就明著說沒有」——
   產品碼裡**沒有**（§269）⇒ 正對照用**合成誘餌**（兩個方向各一支），不用產品碼的真實案例
   （真實案例修好的那天，正對照就跟著消失）。
⚠️ 量尺只認得 `if <role 比較>: raise HTTPException(401/403, 字面)` 這個形狀（px1_scan 的 L1／L2）；
   守衛條件判不出來的不下結論 —— 這一題守的是**判得出來的那一群**，範圍比「所有權限訊息」小。
"""
import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
_SKIP = {"tests", "tools", "rollback_snapshots", "scripts"}

CLAIM_SUPER = re.compile(r"超級管理員|最高管理者|最高管理員")
CLAIM_ADMIN = re.compile(r"(?<!超級)(?<!最高)管理員")
CLAIM_MODULE = re.compile(r"模組")


def _claim(text):
    if "登入" in text or "session" in text.lower():
        return "login"
    if CLAIM_SUPER.search(text):
        return "super"
    if CLAIM_MODULE.search(text):
        return "module"
    if CLAIM_ADMIN.search(text):
        return "admin"
    return "other"


def _is_role_ref(node):
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
            and node.slice.value == "role":
        return True
    return isinstance(node, ast.Attribute) and node.attr == "role"


def _strs(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return {e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    return set()


def _allowed(test):
    """`role != x`／`role not in (…)` 為真才 raise ⇒ 通過的角色集合。判不出來回 None。"""
    for n in ast.walk(test):
        if isinstance(n, ast.Compare) and len(n.ops) == 1 and _is_role_ref(n.left):
            vals = _strs(n.comparators[0])
            if vals and isinstance(n.ops[0], (ast.NotEq, ast.NotIn)):
                return frozenset(vals)
    return None


def scan_source(src, where="<src>"):
    """回 `(一致, 說得比實際嚴, 說得比實際鬆)` 三張清單。"""
    ok, tighter, looser = [], [], []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.If):
            continue
        allowed = _allowed(node.test)
        if allowed is None:
            continue
        for st in node.body:
            if not (isinstance(st, ast.Raise) and isinstance(st.exc, ast.Call)
                    and getattr(st.exc.func, "id", None) == "HTTPException"
                    and len(st.exc.args) >= 2
                    and isinstance(st.exc.args[0], ast.Constant)
                    and st.exc.args[0].value in (401, 403)
                    and isinstance(st.exc.args[1], ast.Constant)
                    and isinstance(st.exc.args[1].value, str)):
                continue
            text = st.exc.args[1].value
            claim = _claim(text)
            row = (where, st.lineno, text, sorted(allowed))
            if claim == "super":
                (ok if allowed == {"superadmin"} else
                 tighter if {"admin", "superadmin"} <= allowed else ok).append(row)
            elif claim == "admin":
                (looser if allowed == {"superadmin"} else ok).append(row)
    return ok, tighter, looser


def _product_files():
    for p in sorted((ROOT / "backend").rglob("*.py")):
        rel = p.relative_to(ROOT / "backend")
        if rel.parts[0] in _SKIP or "__pycache__" in rel.parts:
            continue
        yield p


def test_px1_no_permission_message_disagrees_with_its_role_guard():
    ok_all, tighter_all, looser_all = [], [], []
    for p in _product_files():
        ok, tighter, looser = scan_source(p.read_text(encoding="utf-8"), p.relative_to(ROOT).as_posix())
        ok_all += ok
        tighter_all += tighter
        looser_all += looser
    assert ok_all, "量尺一個一致的案例都沒掃到 —— 掃描器壞了，下面的「0 不一致」是空綠"
    assert not tighter_all, (
        "權限訊息說「只有最高管理員」，而程式讓 admin 也過（有人進得去而不該進）：\n  "
        + "\n  ".join("%s:%d %r 允許 %s" % r for r in tighter_all))
    assert not looser_all, (
        "權限訊息泛稱「管理員」，而程式只放 superadmin（admin 會被誤導）：\n  "
        + "\n  ".join("%s:%d %r 允許 %s" % r for r in looser_all))


_DECOY_TIGHTER = '''
def f(user):
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "僅最高管理員可以執行這個動作")
'''
_DECOY_LOOSER = '''
def g(user):
    if user["role"] != "superadmin":
        raise HTTPException(403, "僅管理員可以執行這個動作")
'''
_CONTROL_OK = '''
def h(user):
    if user["role"] != "superadmin":
        raise HTTPException(403, "僅最高管理員可以執行這個動作")
'''


def test_px1_the_scanner_catches_both_directions_on_synthetic_decoys():
    assert scan_source(_DECOY_TIGHTER)[1], "誘餌（說得比實際嚴）沒被抓到 —— 量尺壞了"
    assert scan_source(_DECOY_LOOSER)[2], "誘餌（說得比實際鬆）沒被抓到 —— 量尺壞了"
    ok, tighter, looser = scan_source(_CONTROL_OK)
    assert ok and not tighter and not looser, "對照組（一致）被誤報"
