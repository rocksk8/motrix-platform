# -*- coding: utf-8 -*-
"""EM8：訊息指向畫面上不存在的東西（唯讀，只報不改）。

判準：後端字串裡出現「請至／請在／請到」等指路詞＋一個地點／設定名，
而那個地點／設定名在前端**完全查不到**（不是子字串誤判，是逐一驗證）。

## 兩個正對照（A-2 撞到的）
  dashboard.py:108   「請在系統設定修改 gcis_daily_limit」 => frontend 對 gcis_daily_limit 命中 0
  inventory.py:614   action 名 edit_note                    => frontend 對 edit_note 命中 0

## 已知限制（寫在輸出裡）
  L1 「地點／設定名」用正則從訊息裡截取，截取規則見 EXTRACT_RX；截取失敗的進「需要人看」。
  L2 前端比對用**子字串**，會有假陰性（前端用駝峰/底線混寫、或用變數組出來的字串）；
     所以「前端查不到」不是「前端一定沒有」，是「字串比對查不到」——回報時附上換了幾種寫法查過。
  L3 只掃 backend 的 .py 訊息字串（f-string／%／.format／字面值），不掃 log 訊息（那是給維護者看的）。
  L4 反向（②）用「前端呼叫的 API 路徑」比對「後端已註冊的路徑」，字串串接組出來的路徑取不到。
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
CJK = re.compile(r"[\u4e00-\u9fff]")


def rd(p):
    return io.open(p, encoding="utf-8", errors="replace").read()


def in_scope(p):
    return not any(s in os.path.relpath(p, ROOT).replace("\\", "/").split("/") for s in SKIP)


# ── ① 抽出「請至／請在／請到」附近的目標詞 ──────────────────────
# 目標形狀：中文詞組（畫面名／功能名）或英文識別字（設定鍵名）
POINTER_RX = re.compile(r"請[至在到](?:.{0,4}?『([^』]{1,20})』|.{0,4}?「([^」]{1,20})」|.{0,10}?([A-Za-z_][A-Za-z0-9_]{2,40}))")


def extract_targets(text):
    out = []
    for m in POINTER_RX.finditer(text):
        for g in m.groups():
            if g:
                out.append(g.strip())
    return out


def string_literals(tree):
    """回傳所有含中文的字串字面值（f-string 的常數段也算），排除 docstring。"""
    doc_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            b = getattr(node, "body", [])
            if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant) \
               and isinstance(b[0].value.value, str):
                doc_ids.add(id(b[0].value))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in doc_ids:
            if CJK.search(node.value):
                out.append((node.lineno, node.value))
        elif isinstance(node, ast.JoinedStr):
            parts = []
            for v in node.values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    parts.append(v.value)
                elif isinstance(v, ast.FormattedValue):
                    parts.append("%s")
            joined = "".join(parts)
            if CJK.search(joined):
                out.append((node.lineno, joined))
    return out


FRONTEND_FILES = None


def load_frontend():
    global FRONTEND_FILES
    if FRONTEND_FILES is None:
        FRONTEND_FILES = []
        for f in glob.glob(os.path.join(ROOT, "frontend", "**", "*"), recursive=True):
            if f.endswith((".html", ".js")) and "vendor" not in f.replace("\\", "/"):
                FRONTEND_FILES.append((os.path.relpath(f, ROOT).replace("\\", "/"), rd(f)))
    return FRONTEND_FILES


def frontend_hits(needle):
    hits = []
    for rel, s in load_frontend():
        if needle in s:
            hits.append((rel, s.count("\n", 0, s.index(needle)) + 1))
    return hits


def widen_variants(needle):
    """換幾種寫法再查一次（L2）：駝峰<->底線、去空白、大小寫。"""
    variants = {needle}
    # snake_case -> camelCase
    if "_" in needle:
        parts = needle.split("_")
        variants.add(parts[0] + "".join(p.capitalize() for p in parts[1:]))
    # camelCase -> snake_case
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", needle).lower()
    variants.add(snake)
    variants.add(needle.replace(" ", ""))
    variants.add(needle.lower())
    return variants


def scan_pointers():
    files = [p for p in glob.glob(os.path.join(ROOT, "backend", "**", "*.py"), recursive=True)
             if in_scope(p)]
    rows = []
    unresolved = []
    for f in files:
        try:
            tree = ast.parse(rd(f))
        except SyntaxError:
            continue
        rel = os.path.relpath(f, ROOT).replace("\\", "/")
        for ln, text in string_literals(tree):
            if not re.search(r"請[至在到]", text):
                continue
            targets = extract_targets(text)
            if not targets:
                unresolved.append((rel, ln, text[:80]))
                continue
            for t in targets:
                rows.append((rel, ln, text, t))
    return rows, unresolved


def main():
    print("=== EM8 ① 訊息指路，目標在前端查不到 ===")
    rows, unresolved = scan_pointers()
    print("  含「請至/請在/請到」的訊息字串共 %d 處" % len(rows))
    print("  抽不出目標詞的（進『需要人看』）= %d" % len(unresolved))

    print()
    print("=== ⚙️ 正對照：兩條必須亮 ===")
    for needle in ("gcis_daily_limit", "edit_note"):
        h = frontend_hits(needle)
        print("  %-20s frontend 命中 %d %s" % (needle, len(h), "✅ 沒有 => 該亮" if not h else "🔴 有命中，正對照失效"))

    print()
    print("=== ⚙️ 負對照：一條指向真實存在的地方，不可以亮 ===")
    neg_needle = "使用者管理"
    h = frontend_hits(neg_needle)
    print("  %-20s frontend 命中 %d %s" % (neg_needle, len(h), "✅ 有命中，不會被判成缺陷" if h else "🔴 沒命中，負對照失效"))

    print()
    print("=== 逐條判定（全部列出）===")
    missing, present, human = [], [], []
    seen = set()
    for rel, ln, text, target in rows:
        key = (rel, ln, target)
        if key in seen:
            continue
        seen.add(key)
        direct = frontend_hits(target)
        if direct:
            present.append((rel, ln, text, target, direct))
            continue
        # 換寫法再查
        found_variant = None
        for v in widen_variants(target):
            if v == target:
                continue
            h = frontend_hits(v)
            if h:
                found_variant = (v, h)
                break
        if found_variant:
            present.append((rel, ln, text, target, found_variant[1]))
        else:
            missing.append((rel, ln, text, target))

    print("  訊息目標 %d 個（去重）=> 前端找得到 %d ／ **前端查不到 %d**"
          % (len(seen), len(present), len(missing)))
    print()
    print("── 🔴 前端查不到（全部列出，含試過的變體）──")
    for rel, ln, text, target in missing:
        variants = widen_variants(target)
        clean = re.sub(r"\s+", " ", text).strip()
        print("  %s:%d" % (rel, ln))
        print("      訊息：%s" % clean[:130])
        print("      目標：%r  已試變體：%s" % (target, sorted(variants)))

    print()
    print("── ✅ 前端找得到的樣本（抽 6 個）──")
    for rel, ln, text, target, hits in present[:6]:
        print("  %s:%d 目標 %r => 前端 %s" % (rel, ln, target, hits[:2]))

    print()
    print("── ❓ 抽不出目標詞（全部列出）──")
    for rel, ln, text in unresolved:
        print("  %s:%d  %s" % (rel, ln, text))

    print()
    print(__doc__.split("## 已知限制")[1].rstrip())


main()
