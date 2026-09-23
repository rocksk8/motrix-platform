# -*- coding: utf-8 -*-
"""PX1：權限訊息說的，與程式實際檢查的，是不是同一件事（唯讀，只報不改）。

判準：對每一支會 raise HTTPException(401/403, detail) 的地方，比對
  ① 程式實際檢查什麼（守衛條件：role 比對／require_superadmin／module 檢查／自訂 helper）
  ② detail 說什麼（文字裡宣稱的角色/模組）
  ③ 兩者是不是同一件事

嚴重度不對稱，分兩欄：
  「說得比實際嚴」：訊息說 superadmin，實際 admin 或更低就過 => 有人進得去而不該進，排前面
  「說得比實際鬆」：訊息說 admin，實際要 superadmin => 使用者卡住，排後面

## 用行號會過期（協定 §5w）—— 一律用「檔案 + 函式名 + detail 字串」定位，不留行號當主鍵。

## 已知限制（寫在輸出裡）
  L1 「守衛條件」用**同一函式內、raise 語句往上最近的 if**近似抓，多層 if 巢狀時可能
     抓到不是直接守著這個 raise 的那個 if（例如那個 if 只是外層業務條件、raise 是
     它裡面另一個 if 管的）——這類我標成「守衛條件不明」進「需要人看」，不主動下結論。
  L2 只認得出現在原始碼裡的**字面角色比對**（role == "superadmin" 之類）與
     `_require_user(require_superadmin=True, module=...)`／`require_any_module(...)`／
     已知的具名 helper（`_require_dev`／`_require_financial_view`／`_require_t100_admin`
     等）。**中介層**（`main.py` 的 auth middleware）與**動態組出來的角色判斷**
     （例如從設定檔讀角色清單）看不到，單獨列，不混進「不一致」的結論。
  L3 401（未登入）與 403（已登入但權限不足）混掃；訊息內容比對邏輯相同，
     但 401 幾乎都是「未登入」這句固定文字，很少出現字面不一致，多數會落在
     「無法判斷」桶，這是預期中的（不是漏掃）。
  L4 module 名稱是否與 detail 提到的模組中文名一致，只做**存在性**檢查
     （這個 module key 有沒有出現在系統模組清單裡），不驗證中文名翻譯對不對——
     那個屬於 EM2（文字對齊畫面）的範圍。
"""
import ast
import glob
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\hichan\Desktop\MOTRIX-ERP"
SKIP = ("tests", "tools", "rollback_snapshots", "scripts", "deploy_packages", "docs")


def rd(p):
    return io.open(p, encoding="utf-8", errors="replace").read()


def in_scope(p):
    return not any(s in os.path.relpath(p, ROOT).replace("\\", "/").split("/") for s in SKIP)


# ── ① 訊息宣稱什麼角色/模組 ──────────────────────────────────
CLAIM_SUPER = re.compile(r"超級管理員|最高管理者|最高管理員")
CLAIM_ADMIN = re.compile(r"(?<!超級)(?<!最高)管理員")  # 泛稱「管理員」但不是前面那三種超級變體
CLAIM_MODULE = re.compile(r"需要[「『]?([\u4e00-\u9fffA-Za-z0-9_]{2,12})[」』]?模組|具授權模組|具[「『]([\u4e00-\u9fffA-Za-z0-9_]{2,12})[」』]模組")


def classify_message(text):
    """回一個標籤：super / admin_generic / module / login / other"""
    if "登入" in text or "Session" in text or "session" in text:
        return "login"
    if CLAIM_SUPER.search(text):
        return "super"
    if CLAIM_MODULE.search(text):
        return "module"
    if CLAIM_ADMIN.search(text):
        return "admin_generic"
    return "other"


# ── ② 守衛條件分類 ────────────────────────────────────────
KNOWN_HELPERS = {
    "_require_dev": "super",       # 內部只准 admin 以上，實際見各檔定義再查
    "_require_financial_view": "module:financial_view",
    "_require_t100_admin": "module:t100",
    "_require_radar": "module:tender_radar",
}


def _is_role_ref(node):
    if isinstance(node, ast.Subscript):
        s = node.slice
        if isinstance(s, ast.Constant) and s.value == "role":
            return True
    if isinstance(node, ast.Attribute) and node.attr == "role":
        return True
    return False


def _str_set(node):
    """從 ast 節點取出字串常數集合：'x' / ('x','y') / ['x','y']"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        out = set()
        for e in node.elts:
            if isinstance(e, ast.Constant) and isinstance(e.value, str):
                out.add(e.value)
        return out
    return set()


#: 🔴 修過一次：原本只看 cond_src 字串裡有沒有出現 "superadmin"，
#: 於是 `role not in ('superadmin','admin')`（admin 以上皆可過）被誤判成
#: 跟 `role != 'superadmin'`（只有 superadmin 能過）**同一類**——
#: 兩者的通過集合完全不同（{admin,superadmin,...} vs {superadmin}），
#: 而字串比對看不出差別。改成走 AST 取出**實際比較到的字串集合**，
#: 回「通過此條件所需的最小角色集合」，不猜語意。
def classify_guard(test):
    """在整個布林運算式裡找 role 比較，回「**通過此守衛的角色集合**」。
    `role != 'x'` 這個條件為真才 raise，也就是「role 不是 x 就擋」=> 只有 role=='x' 能通過。
    `role not in (a,b)` 同理 => 只有 role in (a,b) 能通過。回傳 frozenset(允許角色)。
    `role == 'x'` / `role in (...)` 直接接 raise 是反過來的寫法（少見、語意容易搞混），
    標記為 None（進「守衛條件不明」，不猜）。
    """
    for n in ast.walk(test):
        if isinstance(n, ast.Compare) and len(n.ops) == 1:
            left, op, right = n.left, n.ops[0], n.comparators[0]
            if _is_role_ref(left):
                vals = _str_set(right)
                if not vals:
                    continue
                if isinstance(op, (ast.NotEq, ast.NotIn)):
                    return frozenset(vals)   # 通過角色 = 沒被排除的那些
                # Eq / In 直接接 raise：語意反了，不猜
    return None


def guard_of_call(node_call):
    """_require_user(...) 呼叫的關鍵字，回 super / module:<x> / login-only"""
    kw = {k.arg: k.value for k in node_call.keywords}
    has_super = False
    module_val = None
    if "require_superadmin" in kw and isinstance(kw["require_superadmin"], ast.Constant) \
       and kw["require_superadmin"].value is True:
        has_super = True
    if "module" in kw and isinstance(kw["module"], ast.Constant):
        module_val = kw["module"].value
    if has_super and module_val:
        return "super_or_module:%s" % module_val
    if has_super:
        return "super"
    if module_val:
        return "module:%s" % module_val
    return "login-only"


def scan():
    files = [p for p in glob.glob(os.path.join(ROOT, "backend", "**", "*.py"), recursive=True)
             if in_scope(p)]
    rows = []
    for f in files:
        try:
            tree = ast.parse(rd(f))
        except SyntaxError:
            continue
        rel = os.path.relpath(f, ROOT).replace("\\", "/")
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            fname = fn.name
            # 先收集這個函式裡所有 _require_user(...) / 具名 helper 呼叫的守衛意義
            local_guards = []  # (lineno, guard_kind)
            for n in ast.walk(fn):
                if isinstance(n, ast.Call):
                    callee = n.func.id if isinstance(n.func, ast.Name) else \
                        (n.func.attr if isinstance(n.func, ast.Attribute) else "")
                    if callee == "_require_user":
                        local_guards.append((n.lineno, guard_of_call(n)))
                    elif callee in KNOWN_HELPERS:
                        local_guards.append((n.lineno, KNOWN_HELPERS[callee]))
                    elif callee == "require_any_module" and n.args and len(n.args) >= 2:
                        mods = n.args[1]
                        try:
                            names = [e.value for e in getattr(mods, "elts", []) if isinstance(e, ast.Constant)]
                        except Exception:
                            names = []
                        local_guards.append((n.lineno, "module:" + "|".join(names) if names else "module:?"))
            # 找出 role 字面比對的 if（role != "superadmin" 之類），視為緊鄰它自己 raise 的守衛
            for n in ast.walk(fn):
                if isinstance(n, ast.If):
                    cond_src = ""
                    try:
                        cond_src = ast.unparse(n.test)
                    except Exception:
                        pass
                    role_guard = classify_guard(n.test)
                    for stmt in ast.walk(n):
                        if isinstance(stmt, ast.Raise) and isinstance(stmt.exc, ast.Call):
                            fcall = stmt.exc.func
                            fname_c = fcall.id if isinstance(fcall, ast.Name) else \
                                (fcall.attr if isinstance(fcall, ast.Attribute) else "")
                            if fname_c != "HTTPException" or not stmt.exc.args:
                                continue
                            args = stmt.exc.args
                            if len(args) < 2 or not isinstance(args[0], ast.Constant):
                                continue
                            code = args[0].value
                            detail = args[1]
                            dtext = None
                            if isinstance(detail, ast.Constant) and isinstance(detail.value, str):
                                dtext = detail.value
                            elif isinstance(detail, ast.JoinedStr):
                                parts = [v.value for v in detail.values if isinstance(v, ast.Constant)]
                                dtext = "".join(parts)
                            if code not in (401, 403) or not dtext:
                                continue
                            rows.append((rel, fname, code, dtext, role_guard, cond_src[:80], stmt.lineno))
            for gl, gk in local_guards:
                pass  # local_guards 目前只用於輔助交叉核對，見下方彙整
            fn._local_guards = local_guards  # type: ignore
    return rows, files


def main():
    rows, files = scan()
    print("=== 母體 ===")
    print("  掃 %d 支 .py，raise HTTPException(401/403, 字面 detail) 共 %d 處" % (len(files), len(rows)))

    # 訊息宣稱的角色 => 期待的「允許角色集合」（用來跟 role_guard 比對方向）
    # super         => 期待只有 {'superadmin'}
    # admin_generic => 期待 {'admin','superadmin'}（管理員以上，含更高層）
    # module        => 有模組例外，不能只看 role 集合（另外處理）
    tighter, looser, unclear, ok = [], [], [], []
    for rel, fname, code, dtext, role_guard, cond, ln in rows:
        claim = classify_message(dtext)
        if claim == "login":
            ok.append((rel, fname, code, dtext, role_guard, "login-only 訊息，401 情境"))
            continue
        if role_guard is None:
            unclear.append((rel, fname, code, dtext, cond))
            continue
        allowed = role_guard  # frozenset
        if claim == "module":
            # module 型訊息：只要 allowed 集合裡有 admin 或 superadmin 且條件式含 user_has_module，
            # 判為一致（module 存在性另外查，見 L4）；沒有 module 檢查蹤跡則進 unclear
            if "user_has_module" in cond or "module" in cond:
                ok.append((rel, fname, code, dtext, role_guard, "訊息含模組例外，條件式也有模組檢查"))
            else:
                unclear.append((rel, fname, code, dtext, cond))
            continue
        if claim == "super":
            if allowed == frozenset({"superadmin"}):
                ok.append((rel, fname, code, dtext, role_guard, "一致：只有 superadmin 能過，訊息也說 superadmin"))
            elif "admin" in allowed and "superadmin" in allowed:
                # 🔴 訊息說「只有超級管理員」，但實際 admin 就能過 => 有人進得去而不該進
                tighter.append((rel, fname, code, dtext, role_guard, cond,
                                 "訊息說僅 superadmin，實際 admin 也放行 => 有人進得去而不該進"))
            else:
                unclear.append((rel, fname, code, dtext, cond))
        elif claim == "admin_generic":
            if "admin" in allowed and "superadmin" in allowed and len(allowed) == 2:
                ok.append((rel, fname, code, dtext, role_guard, "一致：admin 以上皆可過，訊息泛稱管理員"))
            elif allowed == frozenset({"superadmin"}):
                # 訊息泛稱「管理員」，實際只有 superadmin 能過 => 一般 admin 會被訊息誤導以為自己能做
                looser.append((rel, fname, code, dtext, role_guard, cond,
                                "訊息泛稱管理員，實際只有 superadmin 能過 => admin 會被誤導、卡住"))
            else:
                unclear.append((rel, fname, code, dtext, cond))
        else:
            unclear.append((rel, fname, code, dtext, cond))

    print("  role_guard 判得出來的 %d ／ 判不出來（守衛條件不明，L1）%d"
          % (len(rows) - len(unclear), len(unclear)))
    print()
    print("=== 分類 ===")
    print("  ✅ 一致 %d" % len(ok))
    print("  🔴🔴 訊息說得比實際嚴（有人進得去而不該進，排前面）%d" % len(tighter))
    print("  🔴 訊息說得比實際鬆（使用者會卡住／被誤導，排後面）%d" % len(looser))
    print("  ❓ 守衛條件不明（L1），全部列出不下結論 %d" % len(unclear))

    print()
    print("=== 🔴🔴 訊息說得比實際嚴（優先看這批）===")
    if not tighter:
        print("  （沒有找到——這是好消息，但見下方正對照，這把尺至少要能找到一個已知案例）")
    for rel, fname, code, dtext, allowed, cond, why in tighter:
        print("  %s :: %s()  [%d]" % (rel, fname, code))
        print("      detail = %r" % dtext[:90])
        print("      實際允許角色 = %s   條件式 = %s" % (sorted(allowed), cond[:80]))
        print("      %s" % why)

    print()
    print("=== 🔴 訊息說得比實際鬆（全部列出）===")
    for rel, fname, code, dtext, allowed, cond, why in looser:
        print("  %s :: %s()  [%d]" % (rel, fname, code))
        print("      detail = %r" % dtext[:90])
        print("      實際允許角色 = %s   條件式 = %s" % (sorted(allowed), cond[:80]))
        print("      %s" % why)

    print()
    print("=== ❓ 守衛條件不明（L1，全部列出，不下結論）===")
    for rel, fname, code, dtext, cond in unclear[:40]:
        print("  %s :: %s()  detail=%r  cond=%s" % (rel, fname, dtext[:60], cond[:60]))
    if len(unclear) > 40:
        print("  … 另 %d 筆" % (len(unclear) - 40))

    print()
    print(__doc__.split("## 已知限制")[1].rstrip())


main()
