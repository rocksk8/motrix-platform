# -*- coding: utf-8 -*-
"""EM1（第三種形狀）：訊息引用一個 UI 名稱，畫面上有東西、但名字不一樣。

三種形狀並排（A §249）：
  第一種 地方不存在          => EM8 ①（em8_scan.py）已覆蓋
  第二種 動作沒有入口        => EM8 ②（em8_reverse.py）已覆蓋
  第三種 地方存在而名字對不上 => 這支

判準：後端訊息裡引用的 UI 名稱，**在前端找不到完全相同的字串**，
但前端存在一個**高相似度、看起來就是它**的標籤 => 印出來讓人判，尺不自己下結論。

## 已知限制（寫在輸出裡）
  L1 這是**近似比對**（difflib.SequenceMatcher），不是精確判定。ratio 只是排序依據，
     不是「超過某個數字就一定是它」——每一條都要人看過。
  L2 前端標籤目錄取自 <label>／class 含 title|head|label|eyebrow 的元素／<h1-4>／
     <button>／短 <span>（≤20 字）。不在這些形狀裡的畫面文字（例如純 <div> 包住的說明段落）
     不會進目錄，會讓真正的名字對不上案例被漏掉。
  L3 只挑「高相似度但不精確相等」的候選；相似度低於門檻的**不代表它是第一種形狀**，
     只代表這把尺沒有把握 —— 那類要靠 EM8 ① 或人工判斷。
  L4 範圍含 email_notify.py（信件）—— A 明確要求含進來，因為那是使用者看得到、
     最少被檢查的一類。
"""
import difflib
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


# ── ① 從後端訊息裡抽出「引用的 UI 名稱」候選 ─────────────────────
QUOTE_RX = re.compile(r"[『「]([^』」]{2,20})[』」]")
ARROW_RX = re.compile(r"([\u4e00-\u9fff]{2,10})\s*→\s*([\u4e00-\u9fff A-Za-z0-9_]{2,20})")
NOUN_RX = re.compile(r"請[至在到]([\u4e00-\u9fff]{2,16}?)(?:頁面|設定|欄位|按鈕|分頁|頁籤|區|選項|功能|畫面)")


def extract_candidates(text):
    out = set()
    for m in QUOTE_RX.finditer(text):
        out.add(m.group(1))
    for m in ARROW_RX.finditer(text):
        out.add(m.group(1))
        out.add(m.group(2))
    for m in NOUN_RX.finditer(text):
        out.add(m.group(1))
    # 去掉太短或不含中文的雜訊
    return {c for c in out if len(c) >= 2 and (CJK.search(c) or c[0].isalpha())}


def backend_messages():
    import ast
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


# ── ② 前端標籤目錄 ────────────────────────────────────────────
#: 🔴 修過一次：這裡原本用尾端裸 `<` 收尾，會**吃掉下一個標籤的 `<`**——
#: 巢狀空殼 div（例如 `<div class="ns-card-head">` 包住
#: `<div class="ns-card-head-title">文字</div>`）外層先匹配、把空白當內容抓走，
#: `finditer` 從被吃掉的 `<` 之後續掃 ⇒ **內層真正的標籤永遠比對不到**。
#: 這正是 `Edge 瀏覽器路徑`（正對照）第一次沒亮的成因。改用 `(?=<)` 零寬預查，
#: 並要求擷取內容**至少一個非空白字元**（`[^<\s][^<]{0,23}`），空殼不再被當成命中。
LABEL_TAG = re.compile(
    r"""<(label)[^>]*>([^<\s][^<]{0,23})</label>
       |<[a-zA-Z0-9]+\s+[^>]*class=["'][^"']*(?:title|head|label|eyebrow)[^"']*["'][^>]*>([^<\s][^<]{0,23})(?=<)
       |<h[1-4][^>]*>([^<\s][^<]{0,23})</h[1-4]>
       |<button[^>]*>([^<\s][^<]{0,23})</button>
    """, re.X)
SPAN_RX = re.compile(r"<span[^>]*>([^<]{1,20})</span>")


def frontend_labels():
    labels = []
    for f in glob.glob(os.path.join(ROOT, "frontend", "**", "*.html"), recursive=True):
        if "vendor" in f.replace("\\", "/"):
            continue
        rel = os.path.relpath(f, ROOT).replace("\\", "/")
        s = rd(f)
        for m in LABEL_TAG.finditer(s):
            text = next((g for g in m.groups() if g), None)
            if text and CJK.search(text):
                ln = s.count("\n", 0, m.start()) + 1
                labels.append((rel, ln, text.strip()))
        for m in SPAN_RX.finditer(s):
            t = m.group(1).strip()
            if t and CJK.search(t) and len(t) <= 20:
                ln = s.count("\n", 0, m.start()) + 1
                labels.append((rel, ln, t))
    return labels


def main():
    msgs = backend_messages()
    print("=== 母體 ===")
    print("  含中文的訊息字串 %d 處（含 email_notify.py，L4）" % len(msgs))

    cand = []  # (file, line, message, candidate)
    for rel, ln, text in msgs:
        for c in extract_candidates(text):
            cand.append((rel, ln, text, c))
    seen_c = {c for *_, c in cand}
    print("  抽出的 UI 名稱候選 %d 個（去重）" % len(seen_c))

    labels = frontend_labels()
    label_texts = {t for *_, t in labels}
    print("  前端標籤目錄 %d 條（去重 %d）" % (len(labels), len(label_texts)))

    print()
    print("=== ⚙️ 正對照：Edge 執行檔路徑 必須亮 ===")
    print("  精確命中 = %s" % ("Edge 執行檔路徑" in "".join(t for _, _, t in labels)))
    best = difflib.get_close_matches("Edge 執行檔路徑", label_texts, n=1, cutoff=0.3)
    print("  最接近的前端標籤 = %s" % best)

    print()
    print("=== ⚙️ 負對照：使用者管理 不可以亮（精確命中即可，不進候選）===")
    exact = "使用者管理" in label_texts or any("使用者管理" in t for t in label_texts)
    print("  精確命中前端標籤 = %s => %s" % (exact, "✅ 不會進候選" if exact else "🔴"))

    print()
    print("=== 逐條判定：候選 vs 前端目錄 ===")
    label_index = {}
    for rel, ln, t in labels:
        label_index.setdefault(t, []).append((rel, ln))

    report = []
    for c in sorted(seen_c):
        exact_hit = c in label_index
        if exact_hit:
            continue  # 精確存在，不是第三種形狀（可能是第一種或沒問題，EM8①已覆蓋）
        close = difflib.get_close_matches(c, label_texts, n=3, cutoff=0.45)
        if close:
            report.append((c, close))

    print("  候選 %d 個 => 前端精確存在（跳過）%d ／ **近似但不相等 %d**"
          % (len(seen_c), len(seen_c) - len(report) - sum(1 for c in seen_c if c not in label_index and not difflib.get_close_matches(c, label_texts, n=1, cutoff=0.45)),
             len(report)))

    print()
    print("── 🔴 近似但不相等（全部列出：訊息名稱 → 最接近的畫面標籤 → 相似度，人看再判）──")
    for c, close in sorted(report, key=lambda x: -difflib.SequenceMatcher(None, x[0], x[1][0]).ratio()):
        locs = [(rel, ln) for rel, ln in label_index.get(close[0], [])][:2]
        ratio = difflib.SequenceMatcher(None, c, close[0]).ratio()
        # 找出這個候選字是從哪則訊息來的（抓第一個）
        src = next(((rel, ln, text) for rel, ln, text, cc in cand if cc == c), None)
        print("  訊息名稱 %r  =>  畫面標籤 %r（相似度 %.2f）  位置 %s"
              % (c, close[0], ratio, locs))
        if src:
            srel, sln, stext = src
            clean = re.sub(r"\s+", " ", stext).strip()
            print("      來源訊息 %s:%d  %s" % (srel, sln, clean[:110]))

    print()
    print(__doc__.split("## 已知限制")[1].rstrip())


main()
