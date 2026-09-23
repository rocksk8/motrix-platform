# -*- coding: utf-8 -*-
"""量「指路說法」的縫：em8_scan.py（請至/請在/請到）與 em1_mismatch.py 的觸發詞
之外，還有多少「指路」的說法兩把尺都收不到。唯讀，只報不改。

產出不是「又找到幾個缺陷」，是**一份觸發詞的收斂清單**——目標是讓下一次掃描
不必再發明觸發詞。

## 做法
  ① 候選新觸發詞：請透過／可在／需至／請於／前往／開啟／點選／按下／
     到…頁面／在…設定裡
  ② 每個詞都跑：先印「前端查得到」的（母體，證明這個詞真的會指路），
     再印「前端查不到」的（縫）—— 不要一開始就只看查不到那堆
  ③ 正對照：「修改連結」必須出現在「查不到」那堆
  ④ 負對照：舊詞（請至/在/到）的候選**不可以**被這份清單重複列出
     （用「已被 em8_scan.py 收過的目標詞」白名單排除）

## 已知限制（寫在輸出裡）
  L1 每個觸發詞的擷取規則不同（見 TRIGGERS），比 em8_scan.py 的單一規則粗糙；
     「開啟」「前往」「按下」等常用詞大量出現在非 UI 指路的語境（開啟某功能開關、
     前往下一步、按下 Enter），**擷取後仍需人工過濾**，這份報告不自動下結論。
  L2 只掃 backend 的 .py 訊息字面值（同 em8_scan.py 範圍）。
  L3 目標是否存在只用**子字串**判斷（不含 em1 的近似比對），所以「查不到」不等於
     「第一種形狀」，可能只是這把粗尺沒找到，見 em1_mismatch.py 再查一次。
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

# 每個觸發詞一條擷取規則：詞在前 or 詞在後，都抓「詞旁邊的 CJK/英數片段」
TRIGGERS = [
    ("請透過", re.compile(r"請透過[「『]?([\u4e00-\u9fffA-Za-z0-9_]{2,16})[」』]?")),
    ("可在",   re.compile(r"可在[「『]?([\u4e00-\u9fffA-Za-z0-9_]{2,16})[」』]?(?:頁面|設定|裡|中|查看|填寫)?")),
    ("請於",   re.compile(r"請於[「『]?([\u4e00-\u9fffA-Za-z0-9_]{2,16})[」』]?")),
    ("前往",   re.compile(r"前往[「『]?([\u4e00-\u9fffA-Za-z0-9_]{2,16})[」』]?")),
    ("開啟",   re.compile(r"開啟[「『]?([\u4e00-\u9fffA-Za-z0-9_]{2,16})[」』]?(?:頁面|功能|設定)?")),
    ("點選",   re.compile(r"點選[「『]?([\u4e00-\u9fffA-Za-z0-9_]{2,16})[」』]?")),
    ("按下",   re.compile(r"按下[「『]?([\u4e00-\u9fffA-Za-z0-9_]{2,16})[」』]?")),
    ("到…頁面", re.compile(r"到([\u4e00-\u9fffA-Za-z0-9_]{2,16})頁面")),
    ("在…設定裡", re.compile(r"在([\u4e00-\u9fffA-Za-z0-9_]{2,16})設定(?:裡|中)")),
]

OLD_TRIGGER = re.compile(r"請[至在到]")


def rd(p):
    return io.open(p, encoding="utf-8", errors="replace").read()


def in_scope(p):
    return not any(s in os.path.relpath(p, ROOT).replace("\\", "/").split("/") for s in SKIP)


def backend_messages():
    files = [p for p in glob.glob(os.path.join(ROOT, "backend", "**", "*.py"), recursive=True)
             if in_scope(p)]
    rows = []
    for f in files:
        try:
            tree = ast.parse(rd(f))
        except SyntaxError:
            continue
        rel = os.path.relpath(f, ROOT).replace("\\", "/")
        doc_ids = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                b = getattr(node, "body", [])
                if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant) \
                   and isinstance(b[0].value.value, str):
                    doc_ids.add(id(b[0].value))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
               and id(node) not in doc_ids and CJK.search(node.value):
                rows.append((rel, node.lineno, node.value))
            elif isinstance(node, ast.JoinedStr):
                parts = []
                for v in node.values:
                    if isinstance(v, ast.Constant) and isinstance(v.value, str):
                        parts.append(v.value)
                    elif isinstance(v, ast.FormattedValue):
                        parts.append("%s")
                joined = "".join(parts)
                if CJK.search(joined):
                    rows.append((rel, node.lineno, joined))
    return rows


FRONTEND_TEXT = None


def frontend_blob():
    global FRONTEND_TEXT
    if FRONTEND_TEXT is None:
        parts = []
        for f in glob.glob(os.path.join(ROOT, "frontend", "**", "*"), recursive=True):
            if f.endswith((".html", ".js")) and "vendor" not in f.replace("\\", "/"):
                parts.append(rd(f))
        FRONTEND_TEXT = "\n".join(parts)
    return FRONTEND_TEXT


def main():
    msgs = backend_messages()
    print("=== 母體：含中文的訊息字串 %d 處 ===" % len(msgs))

    fe = frontend_blob()
    already_em8 = set()
    for rel, ln, text in msgs:
        if OLD_TRIGGER.search(text):
            for m in re.finditer(r"[『「]([^』」]{1,20})[』」]", text):
                already_em8.add(m.group(1))

    got, gap = [], []
    for word, rx in TRIGGERS:
        for rel, ln, text in msgs:
            for m in rx.finditer(text):
                target = m.group(1).strip()
                if not target or not CJK.search(target):
                    continue
                clean = re.sub(r"\s+", " ", text).strip()
                rec = (word, target, rel, ln, clean)
                if target in fe:
                    got.append(rec)
                else:
                    gap.append(rec)

    print()
    print("=== ① 先印「前端查得到」的（母體，證明這個詞真的會指路）===")
    per_word_got = {}
    for word, target, rel, ln, text in got:
        per_word_got.setdefault(word, []).append((target, rel, ln))
    for word, _ in TRIGGERS:
        rows = per_word_got.get(word, [])
        print("  【%s】查得到 %d 處" % (word, len(rows)))
        for target, rel, ln in rows[:3]:
            print("       %r  %s:%d" % (target, rel, ln))

    print()
    print("=== ② 「前端查不到」的（縫，全部列出，去重）===")
    seen = set()
    per_word_gap = {}
    for word, target, rel, ln, text in gap:
        key = (word, target)
        if key in seen:
            continue
        seen.add(key)
        per_word_gap.setdefault(word, []).append((target, rel, ln, text))
    total_gap = sum(len(v) for v in per_word_gap.values())
    print("  去重後 %d 處" % total_gap)
    for word, _ in TRIGGERS:
        rows = per_word_gap.get(word, [])
        if not rows:
            continue
        print("  【%s】%d 處" % (word, len(rows)))
        for target, rel, ln, text in rows:
            print("       %r  %s:%d" % (target, rel, ln))
            print("           %s" % text[:100])

    print()
    print("=== ⚙️ 正對照：「修改連結」必須出現在②（縫）===")
    hit = [r for r in gap if r[1] == "修改連結" or "修改連結" in r[1]]
    print("  命中 %d 處 %s" % (len(hit), "✅" if hit else "🔴 沒抓到"))
    for word, target, rel, ln, text in hit:
        print("     觸發詞【%s】 %r  %s:%d" % (word, target, rel, ln))

    print()
    print("=== ⚙️ 負對照：舊詞（請至/在/到）候選不可以被這份清單重複列出 ===")
    overlap = seen & already_em8
    print("  em8_scan.py 已收過的目標詞 %d 個 ／ 與這份清單重複的 = %d %s"
          % (len(already_em8), len(overlap), "✅ 無重複" if not overlap else "🔴 重複: %s" % overlap))

    print()
    print("=== ⇒ 觸發詞收斂清單（給下一次掃描直接用，不必重新發明）===")
    for word, _ in TRIGGERS:
        n_got = len(per_word_got.get(word, []))
        n_gap = len(per_word_gap.get(word, []))
        verdict = "有效，納入下次" if n_got + n_gap > 0 else "本專案沒有這個寫法，不必收錄"
        print("  %-10s 查得到 %2d／查不到 %2d  => %s" % (word, n_got, n_gap, verdict))

    print()
    print(__doc__.split("## 已知限制")[1].rstrip())


main()
