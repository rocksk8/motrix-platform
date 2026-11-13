# -*- coding: utf-8 -*-
"""UX 守門報告（P0；UX-PRINCIPLES §11）：**只出報告、不擋 CI**。

[單位] tool:ux_audit    [層] L2（唯讀工具）    [依賴] 只用標準庫；不 import 後端模組、不連資料庫
[做什麼]
  ①掃 frontend 的 .html／.js：舊用語（deprecated_terms）、禁用詞（forbidden_terms，含白名單）——分「畫面文字」與「JS 字串」兩欄；
    JS 字串內的『待審核』多半是**資料鍵**（不改），所以只當參考，不計入 ratchet。
  ②每頁度量：行內樣式、`toLocaleString(`、`<th` 欄數、H1 數、頁頭 `.pg__a` 內的 `.btn-primary`。
  ③狀態詞彙一致性：`status-chip.js` 的 MAP 鍵 vs `status_display.py` 的 STATUS_KEYS。
  ④ratchet：`--baseline` 比對「只許降不許升」的指標；`--check` 有升高才以 1 結束（**不接進 CI**，PM 之後決定）。
[用法] python backend/tools/ux_audit.py [--root <repo>] [--md 輸出.md] [--json 輸出.json] [--baseline 基準.json] [--write-baseline 基準.json] [--check]
[設定] backend/tools/ux_audit_config.json（詞彙與白名單；改它不需要改程式）
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "ux_audit_config.json")
SKIP_DIRS = {"node_modules", "vendor", "lib", ".git", "fonts", "__pycache__"}


def load_config(path=CONFIG_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ───────────────────────── 文字抽取 ─────────────────────────

_RE_COMMENT = re.compile(r"<!--.*?-->", re.S)
_RE_SCRIPT = re.compile(r"<script\b[^>]*>(.*?)</script>", re.S | re.I)
_RE_STYLE = re.compile(r"<style\b[^>]*>.*?</style>", re.S | re.I)
_RE_TAG = re.compile(r"<[^>]+>", re.S)
_RE_ATTR = re.compile(r"""\b(?:placeholder|title|aria-label|alt|label)\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.I)
_RE_XTEXT = re.compile(r"""\bx-text\s*=\s*"([^"]*)"|\bx-text\s*=\s*'([^']*)'""", re.I)
_RE_STR = re.compile(r"""'((?:[^'\\\n]|\\.)*)'|"((?:[^"\\\n]|\\.)*)"|`((?:[^`\\]|\\.)*)`""", re.S)
_CJK = re.compile(r"[一-鿿]")


def _strip_comments(html):
    return _RE_COMMENT.sub(" ", html)


def extract_html(html):
    """回傳 (visible_text, js_strings)。visible_text＝標籤外文字＋placeholder/title/aria-label/alt/label 屬性值＋x-text 內的字串字面。"""
    html = _strip_comments(html)
    scripts = _RE_SCRIPT.findall(html)
    body = _RE_STYLE.sub(" ", _RE_SCRIPT.sub(" ", html))
    attrs = [a or b for a, b in _RE_ATTR.findall(body)]
    xtexts = []
    for a, b in _RE_XTEXT.findall(body):
        for m in _RE_STR.finditer(a or b):
            xtexts.append(m.group(1) or m.group(2) or m.group(3) or "")
    text = _RE_TAG.sub(" ", body)
    visible = [text] + attrs + xtexts
    js = []
    for sc in scripts:
        js.extend(js_strings(sc))
    return "\n".join(visible), js


def js_strings(code):
    code = re.sub(r"/\*.*?\*/", " ", code, flags=re.S)
    code = re.sub(r"(?m)(^|\s)//.*$", " ", code)
    out = []
    for m in _RE_STR.finditer(code):
        v = m.group(1) or m.group(2) or m.group(3) or ""
        if _CJK.search(v) or re.search(r"[A-Za-z]{4,}", v):
            out.append(v)
    return out


# ───────────────────────── 度量 ─────────────────────────

def _count(pattern, text):
    return len(re.findall(pattern, text))


def primary_in_header(html):
    """頁頭 `.pg__a` 區塊內的 `.btn-primary` 數（以 div 巢狀深度找區塊結尾）。"""
    html = _strip_comments(html)
    total = 0
    for m in re.finditer(r"""<div\b[^>]*class\s*=\s*["'][^"']*\bpg__a\b[^"']*["'][^>]*>""", html):
        depth, i = 1, m.end()
        while depth and i < len(html):
            nxt = re.search(r"<(/?)div\b", html[i:])
            if not nxt:
                break
            depth += -1 if nxt.group(1) else 1
            i += nxt.end()
        block = html[m.end():i]
        total += _count(r"\bbtn-primary\b", block)
    return total


def page_metrics(html):
    h = _strip_comments(html)
    body = _RE_SCRIPT.sub(" ", h)
    prim_hdr = primary_in_header(h)
    return {
        "lines": html.count("\n") + 1,
        "inline_styles": _count(r'\bstyle\s*=\s*"', body),
        "to_locale_string": _count(r"toLocaleString\(", html),
        "th_count": _count(r"<th\b", body),
        "h1_count": _count(r"<h1\b", body),
        "has_pg_header": bool(re.search(r"""class\s*=\s*["'][^"']*\bpg\b""", body)),
        "btn_primary_total": _count(r"\bbtn-primary\b", body),
        "primary_in_header": prim_hdr,
        "primary_in_header_over1": max(0, prim_hdr - 1),
    }


def term_hits(visible, js, terms):
    out = {}
    for t in terms:
        term = t["term"]
        flags = re.I if t.get("ci") else 0
        v = len(re.findall(re.escape(term), visible, flags))
        j = len(re.findall(re.escape(term), "\n".join(js), flags))
        if v or j:
            out[term] = {"text": v, "js": j}
    return out


# ───────────────────────── 掃描 ─────────────────────────

def iter_frontend(root):
    """frontend 底下的 .html／.js，加上各模組自己的頁面（backend/modules/<key>/pages/，頁面搬進模組後不會被安靜地少掃）。"""
    roots = [os.path.join(root, "frontend")]
    mods = os.path.join(root, "backend", "modules")
    if os.path.isdir(mods):
        roots += [os.path.join(mods, m, "pages") for m in sorted(os.listdir(mods)) if os.path.isdir(os.path.join(mods, m, "pages"))]
    for top in roots:
        for dirpath, dirnames, filenames in os.walk(top):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                if fn.endswith((".html", ".js")):
                    yield os.path.join(dirpath, fn)


def scan(root, config=None):
    config = config or load_config()
    wl = {k: set(v) for k, v in config.get("whitelist", {}).items() if not k.startswith("_")}
    files = {}
    pages = 0
    for path in sorted(iter_frontend(root)):
        rel = os.path.relpath(path, root).replace("\\", "/")
        try:
            src = open(path, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        base = os.path.basename(path)
        if path.endswith(".html"):
            visible, js = extract_html(src)
            pages += 1
            entry = {"kind": "html", **page_metrics(src)}
        else:
            visible, js = "", js_strings(src)
            entry = {"kind": "js", "to_locale_string": _count(r"toLocaleString\(", src)}
        dep = term_hits(visible, js, config["deprecated_terms"])
        forb_all = term_hits(visible, js, config["forbidden_terms"])
        allowed = wl.get(base, set())
        forb = {k: v for k, v in forb_all.items() if k not in allowed and (v["text"] or v["js"])}
        entry["deprecated"] = dep
        entry["forbidden"] = forb
        # 禁用詞只在『畫面文字』計入 ratchet；JS 字串常是程式識別字（例：token 變數），只當參考
        entry["forbidden_hits"] = sum(v["text"] for v in forb.values())
        files[rel] = entry
    return {"files": files, "html_files": pages}


def status_vocab(root):
    """status-chip.js MAP 鍵 vs status_display.py STATUS_KEYS（靜態解析，不 import）。"""
    out = {"js_map_keys": [], "table_keys": [], "only_in_js": [], "only_in_table": [], "error": None}
    try:
        js = open(os.path.join(root, "frontend", "static", "status-chip.js"), encoding="utf-8").read()
        m = re.search(r"var MAP = \{(.*?)\n  \}", js, re.S)
        keys = re.findall(r"'([^']+)'\s*:", m.group(1)) if m else []
        py = open(os.path.join(root, "backend", "helpers", "status_display.py"), encoding="utf-8").read()
        m2 = re.search(r"_RAW = \((.*?)\n\)\n", py, re.S)
        tkeys = re.findall(r'\(\s*"([^"]+)"\s*,\s*"[a-z]+"\s*,\s*"[a-z]+"\s*,\s*"[a-z]+"\s*\)', m2.group(1)) if m2 else []
        out["js_map_keys"], out["table_keys"] = keys, tkeys
        out["only_in_js"] = sorted(set(keys) - set(tkeys))
        out["only_in_table"] = sorted(set(tkeys) - set(keys))
    except Exception as e:  # noqa: BLE001 —— 報告工具不得因單一來源失敗而中止
        out["error"] = "%s: %s" % (type(e).__name__, e)
    return out


def summarize(report, config):
    files = report["files"]
    totals = {"inline_styles": 0, "to_locale_string": 0, "forbidden_hits": 0, "primary_in_header_over1": 0, "th_count": 0}
    dep_totals = {}
    for e in files.values():
        for k in totals:
            totals[k] += e.get(k, 0)
        for term, c in e["deprecated"].items():
            d = dep_totals.setdefault(term, {"text": 0, "js": 0, "files": 0})
            d["text"] += c["text"]
            d["js"] += c["js"]
            d["files"] += 1
    report["totals"] = totals
    report["deprecated_totals"] = dep_totals
    return report


def run(root, config=None):
    config = config or load_config()
    rep = scan(root, config)
    rep["status_vocab"] = status_vocab(root)
    return summarize(rep, config)


# ───────────────────────── ratchet ─────────────────────────

def baseline_view(report, config):
    """基準只存 ratchet 指標（每檔）與『畫面文字』的舊用語計數。"""
    metrics = config.get("ratchet_metrics", [])
    out = {"files": {}, "deprecated_text": {}}
    for rel, e in report["files"].items():
        row = {m: e[m] for m in metrics if m in e and e[m]}
        if row:
            out["files"][rel] = row
    for term, c in report["deprecated_totals"].items():
        out["deprecated_text"][term] = c["text"]
    return out


def compare(report, baseline, config):
    """回傳 [(說明, 基準, 現在)]：現在 > 基準＝倒退。基準沒有的檔／詞，基準視為 0。"""
    cur = baseline_view(report, config)
    problems = []
    for rel, row in cur["files"].items():
        base_row = baseline.get("files", {}).get(rel, {})
        for m, v in row.items():
            if v > base_row.get(m, 0):
                problems.append(("%s：%s" % (rel, m), base_row.get(m, 0), v))
    for term, v in cur["deprecated_text"].items():
        if v > baseline.get("deprecated_text", {}).get(term, 0):
            problems.append(("舊用語『%s』畫面文字" % term, baseline.get("deprecated_text", {}).get(term, 0), v))
    return problems


# ───────────────────────── 輸出 ─────────────────────────

def to_markdown(report, config, baseline_problems=None):
    t = report["totals"]
    L = ["# UX 守門報告（P0，只出報告、不擋 CI）", "",
         "- 掃描：%d 個 HTML、%d 個檔案（含 JS）。產生工具：`backend/tools/ux_audit.py`；詞彙與白名單：`backend/tools/ux_audit_config.json`。" % (report["html_files"], len(report["files"])),
         "- 判讀：**『畫面文字』欄是真正會被使用者看到的；『JS 字串』欄多半是資料鍵或程式識別字（例：資料鍵『待審核』不改），只當參考。**", "",
         "## 1. 總計（ratchet 指標，之後只許降不許升）", "",
         "| 指標 | 現況 |", "|---|---|",
         "| 行內樣式 `style=\"` | %d |" % t["inline_styles"],
         "| 直接呼叫 `toLocaleString(`（應改走 `MotrixFormat`） | %d |" % t["to_locale_string"],
         "| 頁頭 `.pg__a` 內 `.btn-primary` 超過 1 顆的總超出數 | %d |" % t["primary_in_header_over1"],
         "| 禁用詞（畫面文字、扣除白名單） | %d |" % t["forbidden_hits"],
         "| `<th>` 欄標題總數 | %d |" % t["th_count"], ""]
    L += ["## 2. 舊用語（使用者已裁示要改的詞；先看『畫面文字』）", "", "| 舊用語 | 改成 | 畫面文字 | JS 字串 | 檔案數 | 備註 |", "|---|---|---|---|---|---|"]
    for d in config["deprecated_terms"]:
        c = report["deprecated_totals"].get(d["term"], {"text": 0, "js": 0, "files": 0})
        L.append("| %s | %s | %d | %d | %d | %s |" % (d["term"], d["use"], c["text"], c["js"], c["files"], d.get("note", "")))
    L += ["", "### 各檔『畫面文字』舊用語（前 40）", "", "| 檔案 | 詞 | 次數 |", "|---|---|---|"]
    rows = []
    for rel, e in report["files"].items():
        for term, c in e["deprecated"].items():
            if c["text"]:
                rows.append((c["text"], rel, term))
    for n, rel, term in sorted(rows, reverse=True)[:40]:
        L.append("| `%s` | %s | %d |" % (rel, term, n))
    L += ["", "## 3. 禁用詞（扣除白名單後）", "", "| 檔案 | 詞 | 畫面文字 | JS 字串 |", "|---|---|---|---|"]
    n = 0
    for rel, e in sorted(report["files"].items()):
        for term, c in e["forbidden"].items():
            if c["text"]:
                L.append("| `%s` | %s | %d | %d |" % (rel, term, c["text"], c["js"]))
                n += 1
    if not n:
        L.append("| （無） | | | |")
    L += ["", "## 4. 各頁頁頭與主按鈕（HTML 頁，只列有問題者）", "", "| 檔案 | H1 | 有 `.pg` 頁頭 | 頁頭內主按鈕 | 全頁 `.btn-primary` | 行內樣式 | `toLocaleString(` |", "|---|---|---|---|---|---|---|"]
    for rel, e in sorted(report["files"].items()):
        if e.get("kind") == "html" and "/pages/" in rel and (e["primary_in_header"] > 1 or e["h1_count"] != 1):
            L.append("| `%s` | %d | %s | %d | %d | %d | %d |" % (rel, e["h1_count"], "是" if e["has_pg_header"] else "否", e["primary_in_header"], e["btn_primary_total"], e["inline_styles"], e["to_locale_string"]))
    sv = report["status_vocab"]
    L += ["", "## 5. 狀態詞彙一致性（`status-chip.js` MAP vs `status_display.py` STATUS_KEYS）", ""]
    if sv.get("error"):
        L.append("- 解析失敗：%s" % sv["error"])
    else:
        L += ["- MAP 鍵 %d 個、顯示名稱表鍵 %d 個。" % (len(sv["js_map_keys"]), len(sv["table_keys"])),
              "- 只在 `status-chip.js`：%s" % ("、".join(sv["only_in_js"]) or "（無）"),
              "- 只在顯示名稱表：%s（這些鍵沒有色調對照，畫面會是中性色；多數是 deal／devcase 群組，屬預期）" % ("、".join(sv["only_in_table"]) or "（無）")]
    if baseline_problems is not None:
        L += ["", "## 6. 與基準比對（ratchet；**不擋 CI**）", ""]
        if not baseline_problems:
            L.append("- 沒有倒退。")
        else:
            L += ["| 項目 | 基準 | 現在 |", "|---|---|---|"] + ["| %s | %d | %d |" % p for p in baseline_problems]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=os.path.abspath(os.path.join(HERE, "..", "..")))
    ap.add_argument("--md")
    ap.add_argument("--json")
    ap.add_argument("--baseline")
    ap.add_argument("--write-baseline")
    ap.add_argument("--check", action="store_true", help="基準有倒退就以 1 結束（不接 CI）")
    a = ap.parse_args(argv)
    config = load_config()
    rep = run(a.root, config)
    problems = None
    if a.baseline and os.path.exists(a.baseline):
        problems = compare(rep, json.load(open(a.baseline, encoding="utf-8")), config)
    if a.write_baseline:
        with open(a.write_baseline, "w", encoding="utf-8", newline="\n") as f:
            json.dump(baseline_view(rep, config), f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write("\n")
    md = to_markdown(rep, config, problems)
    if a.md:
        with open(a.md, "w", encoding="utf-8", newline="\n") as f:
            f.write(md)
    if a.json:
        with open(a.json, "w", encoding="utf-8", newline="\n") as f:
            json.dump(rep, f, ensure_ascii=False, indent=1, sort_keys=True)
    if not a.md and not a.json:
        sys.stdout.reconfigure(encoding="utf-8")
        print(md)
    if a.check and problems:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
