# -*- coding: utf-8 -*-
"""EM4 v2：被吞掉的失敗（唯讀，只報不改）。

v1 判「錯」131 個，看內容發現**幾乎全是 `except: pass` 的清理型**（`conn.close()`、
刪暫存檔）—— 那些吞掉的東西**本來就沒有使用者要知道的事**，不是 EM4。
=> v2 把 `pass` 型再依「try 區塊在做什麼」分流，並把 🔴 收窄成 JV9 那個形狀：
   **回一個空值／預設值，而成功路徑也會回同一個值 ⇒ 無法區分。**

## 已知限制（寫在輸出裡）
  L1 「與成功路徑無法區分」＝比對同一函式其他 return 的字面值。成功路徑的空值若從變數回，
     比不出來 => 進「需要人看」。
  L2 **沒追呼叫端**。判「錯」＝「在這個函式裡它說不出來」，不是「全系統沒人知道」。
  L3 記錄型認 logger/log/logging/print/_audit/warn/error/exception/critical/info/debug
     ＋ append/add/extend/setdefault/insert/update ＋ execute（寫 DB）＋ raise。
     自製記錄函式會漏。
  L4 只掃 backend 的 .py（排除 tests/tools/rollback_snapshots/scripts/deploy_packages）。
     ⚠️ **前端的 try/catch 不在範圍內**，而靜默吞掉在那一側同樣存在。
  L5 「清理型」是看 try 區塊裡**只有**清理類呼叫（close/remove/unlink/rmtree/kill/
     terminate/shutdown/join/rollback/flush）。混在一起的算「需要人看」。
"""
import ast
import glob
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\hichan\Desktop\MOTRIX-ERP"
SKIP = ("tests", "tools", "rollback_snapshots", "scripts", "deploy_packages")
LOGN = ("logger", "log", "logging", "print", "_audit", "warn", "warning",
        "error", "exception", "critical", "info", "debug")
RECN = ("append", "add", "extend", "setdefault", "insert", "update")
CLEAN = ("close", "remove", "unlink", "rmtree", "kill", "terminate", "shutdown",
         "join", "rollback", "flush", "cleanup", "discard", "quit")
TELE = ("_audit", "_record_user_activity", "_record_request_trail", "record", "trail")
EMPTY = ("", 0, None, False)
rd = lambda p: io.open(p, encoding="utf-8", errors="replace").read()


def in_scope(p):
    return not any(s in os.path.relpath(p, ROOT).replace("\\", "/").split("/") for s in SKIP)


def says(h):
    out = []
    for n in ast.walk(h):
        if isinstance(n, ast.Raise):
            try:
                out.append("raise " + (ast.unparse(n.exc)[:80] if n.exc else "（原樣往外丟）"))
            except Exception:
                out.append("raise")
        elif isinstance(n, ast.Call):
            f = n.func
            nm = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
            if nm in LOGN:
                a = n.args[0].value[:70] if (n.args and isinstance(n.args[0], ast.Constant)
                                             and isinstance(n.args[0].value, str)) else ""
                out.append("%s(%r)" % (nm, a))
            elif nm in RECN:
                try:
                    out.append("記錄 " + ast.unparse(n)[:80])
                except Exception:
                    out.append("記錄 " + nm)
            elif nm == "execute":
                out.append("寫 DB")
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Subscript):
                    try:
                        out.append("寫欄位 " + ast.unparse(n)[:70])
                    except Exception:
                        pass
    return out


def try_body_kind(try_node):
    """try 區塊在做什麼：cleanup / telemetry / other"""
    calls = []
    for s in try_node.body:
        for n in ast.walk(s):
            if isinstance(n, ast.Call):
                f = n.func
                calls.append(f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "?"))
    if calls and all(c in CLEAN for c in calls):
        return "cleanup", ", ".join(sorted(set(calls)))
    if any(c in TELE for c in calls):
        return "telemetry", ", ".join(sorted(set(c for c in calls if c in TELE)))
    return "other", ", ".join(sorted(set(calls))[:5])


def ret_kind(h):
    rets = [n for n in ast.walk(h) if isinstance(n, ast.Return)]
    if not rets:
        body = [s for s in h.body if not isinstance(s, (ast.Pass,))]
        if not body:
            return "pass", "pass"
        if all(isinstance(s, (ast.Continue, ast.Break)) for s in body):
            return "pass", ast.unparse(body[0])
        return "fall", "沒有 return"
    txt, kinds = [], set()
    for r in rets:
        if r.value is None:
            kinds.add("empty"); txt.append("return（隱含 None）")
        elif isinstance(r.value, ast.Constant) and r.value.value in EMPTY:
            kinds.add("empty"); txt.append("return %r" % (r.value.value,))
        elif isinstance(r.value, (ast.List, ast.Dict, ast.Tuple)) and not (
                getattr(r.value, "elts", None) or getattr(r.value, "keys", None)):
            kinds.add("empty"); txt.append("return " + ast.unparse(r.value))
        else:
            kinds.add("other")
            try:
                txt.append("return " + ast.unparse(r.value)[:60])
            except Exception:
                txt.append("return ?")
    return ("empty" if kinds == {"empty"} else "other" if kinds == {"other"} else "mixed"), "；".join(txt)


def encl(tree, ln):
    best = None
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) \
           and n.lineno <= ln <= (getattr(n, "end_lineno", n.lineno) or n.lineno):
            if best is None or n.lineno > best.lineno:
                best = n
    return best


def same_as_success(fn, text):
    m = re.search(r"return (.+?)(?:；|$)", text)
    if not fn or not m:
        return None
    want = m.group(1).strip()
    if want.startswith("（"):
        want = "None"
    c = 0
    for n in ast.walk(fn):
        if isinstance(n, ast.Return):
            v = "None" if n.value is None else None
            if v is None:
                try:
                    v = ast.unparse(n.value).strip()
                except Exception:
                    continue
            if v == want:
                c += 1
    return c >= 2


def scan(files):
    B = {"ok": [], "em4": [], "cleanup": [], "tele": [], "human": []}
    tot = 0
    for f in files:
        try:
            tree = ast.parse(rd(f))
        except SyntaxError:
            continue
        rel = os.path.relpath(f, ROOT).replace("\\", "/") if f.startswith(ROOT) else os.path.basename(f)
        for t in ast.walk(tree):
            if not isinstance(t, ast.Try):
                continue
            tk, tdesc = try_body_kind(t)
            for h in t.handlers:
                tot += 1
                said = says(h)
                rk, rtext = ret_kind(h)
                fn = encl(tree, h.lineno)
                fname = fn.name if fn else "(模組層)"
                rec = [rel, h.lineno, fname, rtext, said, tk, tdesc, None]
                if said:
                    B["ok"].append(rec)
                elif rk == "pass":
                    if tk == "cleanup":
                        B["cleanup"].append(rec)
                    elif tk == "telemetry":
                        B["tele"].append(rec)
                    else:
                        B["human"].append(rec)
                elif rk == "empty":
                    s = same_as_success(fn, rtext)
                    rec[7] = s
                    (B["em4"] if s else B["human"]).append(rec)
                else:
                    B["human"].append(rec)
    return tot, B


def main():
    FILES = [p for p in glob.glob(os.path.join(ROOT, "backend", "**", "*.py"), recursive=True)
             if in_scope(p)]
    tot, B = scan(FILES)
    print("=== EM4 母體（現役）===")
    print("  %d 支 .py ／ except handler **%d** 個" % (len(FILES), tot))
    print("  ✅ 說得出來（有 log／紀錄／raise）      %d" % len(B["ok"]))
    print("  🔴 **EM4：回空值且成功路徑同值 ⇒ 無法區分**  %d" % len(B["em4"]))
    print("  ⚙️ 清理型 pass（try 裡只有 close/remove 之類）%d  ← 不是 EM4" % len(B["cleanup"]))
    print("  ⚙️ 記錄型 pass（吞掉的是 audit/telemetry 本身）%d  ← 另一族" % len(B["tele"]))
    print("  ❓ 需要人看                             %d" % len(B["human"]))
    s = sum(len(v) for v in B.values())
    print("  收斂 %d = %d  -> %s" % (tot, s, "OK" if s == tot else "MISMATCH"))

    print()
    print("=== 🔴 EM4（全部列出：位置／函式／吞掉之後回什麼／依據）===")
    for rel, ln, fname, rtext, said, tk, tdesc, s2 in B["em4"]:
        print("  %s:%d  %s" % (rel, ln, fname))
        print("      吞掉之後：%s" % rtext[:80])
        print("      依據：handler 裡沒有 log／紀錄／raise，且**同一函式的成功路徑也回同一個值**")
        print("      try 裡在做：%s" % tdesc[:90])

    print()
    print("=== ⚙️ 清理型（抽 8 個，說明為什麼不算 EM4）===")
    for rel, ln, fname, rtext, said, tk, tdesc, s2 in B["cleanup"][:8]:
        print("  %s:%d %-30s try 裡只有：%s" % (rel, ln, fname, tdesc[:60]))

    print()
    print("=== ⚙️ 記錄型（吞掉的是記錄本身，全部列出）===")
    for rel, ln, fname, rtext, said, tk, tdesc, s2 in B["tele"]:
        print("  %s:%d %-30s try 裡：%s" % (rel, ln, fname, tdesc[:60]))

    print()
    print("=== ✅ 判「對」的樣本：寫出它說了什麼（抽 8）===")
    for rel, ln, fname, rtext, said, tk, tdesc, s2 in B["ok"][:8]:
        print("  %s:%d %s" % (rel, ln, fname))
        print("      它說了：%s" % "；".join(said)[:130])

    print()
    print("=== ⚙️ 正對照：a9e1119^ 的 voucher_pdf.py（舊版必須亮）===")
    CTRL = r"C:\Users\hichan\AppData\Local\Temp\claude\C--Users-hichan\c0588b23-65c8-4872-9062-09101ec9fdb3\scratchpad\ctrl_voucher_pdf_old.py"
    ctot, CB = scan([CTRL])
    print("  舊版 handler %d 個 => EM4 %d／清理 %d／記錄 %d／說得出來 %d／需人看 %d"
          % (ctot, len(CB["em4"]), len(CB["cleanup"]), len(CB["tele"]), len(CB["ok"]), len(CB["human"])))
    for rel, ln, fname, rtext, said, tk, tdesc, s2 in CB["em4"]:
        print("     🔴 %s:%d %s => %s" % (rel, ln, fname, rtext[:60]))
    print("  正對照結論：%s" % ("✅ 亮了" if CB["em4"] else "🔴 沒亮 —— 這把尺無效"))
    print()
    print("=== ⚙️ 負對照：split_attachments 那個 append 不可以被判成 EM4 ===")
    neg = [x for x in CB["em4"] + CB["human"] if "split" in x[2]]
    pos = [x for x in CB["ok"] if "split" in x[2]]
    print("  落在 EM4／需人看 = %d %s" % (len(neg), "🔴" if neg else "✅"))
    for rel, ln, fname, rtext, said, tk, tdesc, s2 in pos:
        print("     ✅ 落在「說得出來」：%s:%d %s => %s" % (rel, ln, fname, "；".join(said)[:90]))

    print()
    print("=== 已知限制 ===")
    print(__doc__.split("## 已知限制")[1].rstrip())


main()
