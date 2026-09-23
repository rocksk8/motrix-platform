# -*- coding: utf-8 -*-
"""EM4 v4：加一條判準 —— **回傳值裡有沒有帶著理由**。

B 對他自己那幾支跑同一把尺，8 處**全部誤報**：它們回的是 `(None, "原因")`／`None`，
而**那個原因字串本身就是區分訊號**。
🔑 掃描器只看得到形狀，看不到值裡有沒有答案。

v4 新增「帶理由」的認法：
  a) tuple 裡有非空字串字面值            return None, "讀不到設定"
  b) dict 有 error/reason/message/detail/warning/note 鍵
  c) 回一個 ALL_CAPS 具名常數（例如 LEGACY_SETTLEMENT_MESSAGE）
  d) f-string／字串相加裡含非空字面值
=> 判「說得出來」，從缺陷欄移出。⚠️ **那是分類修正，不是缺陷處置。**

⚙️ 正對照：a9e1119^ 的 voucher_pdf.py **仍然必須亮**（純 ''，沒有理由）
⚙️ 負對照：**自己造的合成輸入** return (None, "讀不到設定") **不可以亮**
   （不用 B 碼裡的真實案例當誘餌——他改掉之後對照組就失效）
"""
import ast
import glob
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SP = r"C:\Users\hichan\AppData\Local\Temp\claude\C--Users-hichan\c0588b23-65c8-4872-9062-09101ec9fdb3\scratchpad"
src = io.open(os.path.join(SP, "em4_scan2.py"), encoding="utf-8").read().replace("\nmain()\n", "\n")
G = {"__name__": "em4v2"}
exec(compile(src, "em4_scan2.py", "exec"), G)
ROOT = G["ROOT"]
EMPTY = G["EMPTY"]
REASON_KEYS = ("error", "reason", "message", "detail", "warning", "note", "msg", "why")
PRED = re.compile(r"^(_?is_|_?has_|_?can_|_?verify|_?check|_?accepts|_?allow|_?should)|_ok$|_exceeded$|_enabled$")


def has_reason(node):
    """這個 return 的值裡有沒有帶著「為什麼」。回 (bool, 說明)"""
    if node is None:
        return False, ""
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.strip():
            return True, "字串字面值 %r" % n.value[:50]
        if isinstance(n, ast.Dict):
            for k in n.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str) \
                   and k.value.lower() in REASON_KEYS:
                    return True, "dict 有 %r 鍵" % k.value
        if isinstance(n, ast.JoinedStr):
            return True, "f-string"
        if isinstance(n, ast.Name) and n.id.isupper() and len(n.id) > 3:
            return True, "具名常數 %s" % n.id
    return False, ""


def yields_empty(node, want):
    if node is None:
        return want is None
    if isinstance(node, ast.Constant) and node.value in EMPTY:
        return node.value == want or (node.value is None and want is None)
    if isinstance(node, (ast.List, ast.Dict, ast.Tuple)) and not (
            getattr(node, "elts", None) or getattr(node, "keys", None)):
        return isinstance(want, (list, dict, tuple))
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        return yields_empty(node.values[-1], want)
    return False


def want_of(h):
    for n in ast.walk(h):
        if isinstance(n, ast.Return):
            if n.value is None:
                return None, True
            if isinstance(n.value, ast.Constant) and n.value.value in EMPTY:
                return n.value.value, True
            if isinstance(n.value, (ast.List, ast.Dict, ast.Tuple)) and not (
                    getattr(n.value, "elts", None) or getattr(n.value, "keys", None)):
                return ([] if isinstance(n.value, ast.List) else {}), True
    return None, False


def classify(files_or_src, is_src=False):
    B = {"ok": [], "reason": [], "value": [], "pred": [], "cleanup": [], "human": []}
    tot = 0
    items = [("<合成>", files_or_src)] if is_src else [(f, None) for f in files_or_src]
    for f, s in items:
        try:
            tree = ast.parse(s if is_src else G["rd"](f))
        except SyntaxError:
            continue
        rel = "<合成輸入>" if is_src else (
            os.path.relpath(f, ROOT).replace("\\", "/") if f.startswith(ROOT) else os.path.basename(f))
        for t in ast.walk(tree):
            if not isinstance(t, ast.Try):
                continue
            tk, tdesc = G["try_body_kind"](t)
            for h in t.handlers:
                tot += 1
                said = G["says"](h)
                rk, rtext = G["ret_kind"](h)
                fn = G["encl"](tree, h.lineno)
                fname = fn.name if fn else "(模組層)"
                # 🔴 新判準：回傳值裡有沒有理由（對所有 return 型都問）
                rsn, rwhy = False, ""
                for n in ast.walk(h):
                    if isinstance(n, ast.Return):
                        rsn, rwhy = has_reason(n.value)
                        if rsn:
                            break
                rec = [rel, h.lineno, fname, rtext, said, tdesc, None, rwhy]
                if said:
                    B["ok"].append(rec)
                elif rsn:
                    B["reason"].append(rec)
                elif rk == "pass":
                    (B["cleanup"] if tk == "cleanup" else B["human"]).append(rec)
                elif rk == "empty":
                    want, okw = want_of(h)
                    same = False
                    if fn and okw:
                        same = sum(1 for n in ast.walk(fn)
                                   if isinstance(n, ast.Return) and yields_empty(n.value, want)) >= 2
                    rec[6] = same
                    (B["pred"] if PRED.search(fname) else B["value"]).append(rec)
                else:
                    B["human"].append(rec)
    return tot, B


SYNTH = '''
def read_setting():
    try:
        return load()
    except Exception:
        return (None, "讀不到設定")        # 合成負對照：理由在值裡


def read_plain():
    try:
        return load()
    except Exception:
        return ""                          # 合成正對照：純空值，沒有理由
'''


def main():
    print("=== ⚙️ 對照組先跑 ===")
    st, SB = classify(SYNTH, is_src=True)
    print("  合成輸入 %d 個 handler" % st)
    print("    帶理由那個 => 落在 %s %s"
          % ("『說得出來』" if any("讀不到設定" in x[7] for x in SB["reason"]) else "其他欄",
             "✅ 不算缺陷" if SB["reason"] else "🔴"))
    print("    純空值那個 => 落在缺陷欄 = %s %s"
          % (bool(SB["value"]), "✅" if SB["value"] else "🔴 負對照壞了"))
    ct, CB = classify([os.path.join(SP, "ctrl_voucher_pdf_old.py")])
    print("  正對照 a9e1119^ voucher_pdf.py => 缺陷欄 %d 個 %s"
          % (len(CB["value"]), "✅ 仍然亮" if CB["value"] else "🔴 不亮了"))
    for r in CB["value"]:
        print("     🔴 %s:%d %s => %s" % (r[0], r[1], r[2], r[3]))

    FILES = [p for p in glob.glob(os.path.join(ROOT, "backend", "**", "*.py"), recursive=True)
             if G["in_scope"](p)]
    tot, B = classify(FILES)
    print()
    print("=== 現役（v4）===")
    print("  handler %d" % tot)
    print("    ✅ 說得出來（log／紀錄／raise）      %d" % len(B["ok"]))
    print("    ✅ **回傳值裡帶著理由**（v4 新增）    %d" % len(B["reason"]))
    print("    🔴 取值型（純空值，沒有理由）        %d" % len(B["value"]))
    print("    ⚙️ 謂詞型                          %d" % len(B["pred"]))
    print("    ⚙️ 清理型 pass                      %d" % len(B["cleanup"]))
    print("    ❓ 需要人看                         %d" % len(B["human"]))
    s = sum(len(v) for v in B.values())
    print("  收斂 %d = %d -> %s" % (tot, s, "OK" if s == tot else "MISMATCH"))

    print()
    print("=== ✅ v4 從缺陷欄／需人看欄移出來的（帶理由）—— 抽 14 個，寫出理由在哪 ===")
    for r in B["reason"][:14]:
        print("  %s:%d %-32s %s" % (r[0], r[1], r[2], r[3][:38]))
        print("        理由在值裡：%s" % r[7])

    print()
    print("=== 🔴 剩下的取值型（純空值）全部列出 ===")
    for r in sorted(B["value"], key=lambda x: (not x[6], x[0])):
        print("  %s%s:%d %-34s %s%s"
              % ("☠️ " if r[6] else "   ", r[0], r[1], r[2], r[3][:30],
                 "   （函式內無法區分）" if r[6] else ""))


main()
