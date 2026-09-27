# -*- coding: utf-8 -*-
"""稽核必修的關閉紀錄掃描（PLAYBOOK §E-6；D 的 d_scan_mustfix.py 移植，2026-09-28）。

  python tools/platform/mustfix_scan.py [--audit-dir docs/platform/audit] [--register docs/platform/mustfix_open.json]

掃 `docs/platform/audit/*.md` 宣告的必修，列出**沒有關閉紀錄**的，並與「登記中的未關必修」（register）比對：
兩邊必須完全相同——沒關又沒登記＝被忘了；登記了卻已經關了＝登記過期。不同 ⇒ exit 1。

宣告（D 的判準，不改）：`**ID（必修` / `**ID （必修`、表格列 `| ID | … 必修`、或 `### 必修` 段落內以 `**ID　` 開頭的行。
關閉（D 的判準，不改）：提到 ID 的行，ID 之後 60 字內、同一格裡有 ✅／關閉／已關（或表格列以 ID 開頭且有關閉字樣），
  而且那一行沒有 ⏳／未關／仍開／待驗／才在／不關閉／（必修。跨檔的關閉只在「ID 只在一份檔宣告、另一份檔沒有 `**ID`」時採信。
**標準關閉寫法**（D 建議、本工具新增）：單行 `✅ <編號> 關閉（<commit>）`。它在任何一份稽核檔裡都算數（不受跨檔限制），
  因為它寫明了哪一個 commit 關的——這一行就是「有人做過決定」的紀錄。新的關閉一律用這個寫法。

D 的判準認不得的四類寫法（2026-09-28 的 13 筆假陽性）：①關閉寫在另一份檔或並列句 ②改號延續、關閉記在新編號
③表格的 ID 加粗或寫在描述格 ④寫成「成立／通過」。處置：在宣告的那份檔補一行標準關閉寫法，不放寬判準
（放寬會讓真的沒關的也被當成關了）、也不設排除清單（排除清單可以靠全部寫進去而變綠）。
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
AUDIT_DIR = REPO / "docs" / "platform" / "audit"
REGISTER = REPO / "docs" / "platform" / "mustfix_open.json"
#: 凍結的舊 ID 清單（D 稽核 MS-M1，2026-09-28）：只有這些 ID 的關閉可以沿用舊的寬鬆判準（散文、表格裡的「關閉」）；
#: 清單以外（含之後宣告的）一律只認標準單行 CANON——一句「前提是 X 關閉」不會再把 X 從未關清單裡弄不見。
LEGACY = REPO / "docs" / "platform" / "mustfix_legacy_closures.json"

ID = r"[A-Z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*"
DECL = [re.compile(r"\*\*(" + ID + r")\s*（必修"), re.compile(r"^\|\s*(" + ID + r")\s*\|.*必修")]
CLOSE = re.compile(r"✅|關閉(?!才)|已關")
NEG = re.compile(r"⏳|未關|仍開|待驗|才在|不關閉|（必修")
#: 標準關閉寫法：`✅ <編號> 關閉（<commit>）`（commit 7～40 位十六進位）
CANON = re.compile(r"✅\s*(" + ID + r")\s*關閉（([0-9a-f]{7,40})）")

#: 登記中的未關必修上限：登記表是「已知、有人在修」的清單，不是把紅燈藏起來的地方（反向控制見題目）。
#: 10＝一輪稽核同時開著的必修實際最多約 5～6 筆（2026-09-26～27：M4 系列 3＋M06 2＋SM 1）再留餘裕
MAX_OPEN = 10
REGISTER_FIELDS = ("audit", "owner", "fix", "state")


def load_texts(audit_dir=AUDIT_DIR) -> dict:
    """{檔名: [行]}（只看 *.md）。"""
    return {p.name: p.read_text(encoding="utf-8-sig").splitlines() for p in sorted(Path(audit_dir).glob("*.md"))}


def declared(texts: dict) -> list:
    """⇒ [(檔名, ID)]：每份檔宣告的必修（ID 必須含數字，排除「B」「必修」之類的字）。"""
    out = []
    for f, lines in texts.items():
        ds = set()
        for line in lines:
            for p in DECL:
                ds.update(m.group(1) for m in p.finditer(line))
        for i, line in enumerate(lines):
            if re.match(r"^#+\s*必修", line):
                for l2 in lines[i + 1:]:
                    if re.match(r"^#", l2):
                        break
                    ds.update(m.group(1) for m in re.finditer(r"^\*\*(" + ID + r")[　 ]", l2))
        out += [(f, d) for d in sorted(ds) if re.search(r"\d", d)]
    return out


def canonical_closures(texts: dict) -> dict:
    """⇒ {ID: [(檔名, commit)]}：標準關閉寫法（該行沒有否定字樣）。"""
    out = {}
    for f, lines in texts.items():
        for line in lines:
            if NEG.search(line):
                continue
            for m in CANON.finditer(line):
                out.setdefault(m.group(1), []).append((f, m.group(2)))
    return out


def load_legacy(path=LEGACY) -> dict:
    """{ID: 宣告它的檔名}：可以沿用舊寬鬆判準的凍結清單。檔不在或讀不懂 ⇒ 例外（不當成空清單：那會把 80 幾筆舊關閉全變成未關）。"""
    with open(path, encoding="utf-8-sig") as f:
        return dict(json.load(f)["ids"])


def closure_hits(d: str, home: str, texts: dict, ndecl: Counter, canon=None, legacy=None) -> list:
    """ID `d`（宣告於 `home`）的關閉紀錄出現在哪幾份檔。空 ⇒ 沒有關閉紀錄。
    標準單行（CANON）一律算；舊的寬鬆判準只給凍結清單 `legacy` 裡的 ID（MS-M1）。"""
    canon = canonical_closures(texts) if canon is None else canon
    if d in canon:
        return [f for f, _sha in canon[d]]
    if d not in (legacy or {}):
        return []
    return loose_hits(d, home, texts, ndecl)


def loose_hits(d: str, home: str, texts: dict, ndecl: Counter) -> list:
    """舊的寬鬆判準（D 原腳本）：提到 ID 的行，ID 之後 60 字內同一格有 ✅／關閉／已關、該行沒有否定字樣。
    ⚠ 會把「前提是 X 關閉」這種散文也算成關閉（MS-M1）⇒ 只給凍結清單用。"""
    pat = re.compile(r"(?<![A-Za-z0-9-])" + re.escape(d) + r"(?![0-9a-z])")
    own_def = re.compile(r"\*\*" + re.escape(d) + r"(?![0-9a-z])")
    hits = []
    for f, lines in texts.items():
        if f != home and (ndecl[d] > 1 or own_def.search("\n".join(lines))):
            continue
        for line in lines:
            m = pat.search(line)
            if not m or NEG.search(line):
                continue
            c = CLOSE.search(line[m.start():])
            same_cell = c is not None and "|" not in line[m.start():m.start() + c.start()]
            if line.lstrip().startswith("| " + d + " ") and CLOSE.search(line) or (c and c.start() < 60 and same_cell):
                hits.append(f)
    return hits


def open_items(texts: dict, legacy=None) -> list:
    """⇒ [(檔名, ID)]：宣告了、沒有關閉紀錄的必修。legacy 省略 ⇒ 讀凍結清單檔。"""
    legacy = load_legacy() if legacy is None else legacy
    decl = declared(texts)
    ndecl = Counter(d for _f, d in decl)
    canon = canonical_closures(texts)
    return [(f, d) for f, d in decl if not closure_hits(d, f, texts, ndecl, canon, legacy)]


def legacy_problems(texts: dict, path=LEGACY) -> list:
    """凍結清單本身的檢查：筆數不可以超過凍結當下的數目；每一筆都要真的還在用舊判準
    （宣告它的檔還宣告它、沒有標準單行、舊判準確實找得到關閉）——否則過期，要從清單拿掉（清單只准減少）。"""
    with open(path, encoding="utf-8-sig") as f:
        data = json.load(f)
    ids, frozen = dict(data["ids"]), int(data["frozen_count"])
    problems = []
    if len(ids) > frozen:
        problems.append("凍結清單 %d 筆，超過凍結當下的 %d 筆：新的必修只認標準單行「✅ <編號> 關閉（<commit>）」，不可以加進清單" % (len(ids), frozen))
    decl = declared(texts)
    ndecl = Counter(d for _f, d in decl)
    canon = canonical_closures(texts)
    homes = {}
    for f, d in decl:
        homes.setdefault(d, set()).add(f)
    for d, f in sorted(ids.items()):
        if f not in homes.get(d, set()):
            problems.append("凍結清單的 %s 過期：%s 已經不宣告它 ⇒ 從清單拿掉" % (d, f))
        elif d in canon:
            problems.append("凍結清單的 %s 過期：已有標準單行 ⇒ 從清單拿掉" % d)
        elif not loose_hits(d, f, texts, ndecl):
            problems.append("凍結清單的 %s 找不到舊寫法的關閉 ⇒ 它其實沒關：寫標準單行或登記 mustfix_open.json，並從清單拿掉" % d)
    return problems


def load_register(path=REGISTER) -> dict:
    with open(path, encoding="utf-8-sig") as f:
        data = json.load(f)
    return data.get("open") or {}


def check(open_list: list, register: dict) -> list:
    """未關清單與登記表比對 ⇒ 問題清單（空＝一致）。"""
    problems = []
    open_ids = {d for _f, d in open_list}
    for f, d in open_list:
        if d not in register:
            problems.append("%s（%s）沒有關閉紀錄、也沒有登記在 mustfix_open.json ⇒ 被忘了：修好後由稽核者寫"
                            "「✅ %s 關閉（<commit>）」，還在修就登記（audit／owner／fix／state）" % (d, f, d))
    for d, e in sorted(register.items()):
        if d not in open_ids:
            problems.append("%s 登記過期：登記為未關，但稽核檔已有關閉紀錄（或沒有這個必修）⇒ 從 mustfix_open.json 移除" % d)
            continue
        miss = [k for k in REGISTER_FIELDS if not str((e or {}).get(k) or "").strip()]
        if miss:
            problems.append("%s 的登記缺欄位：%s（登記要寫明在哪一份稽核、誰在修、修在哪、目前狀態）" % (d, "、".join(miss)))
        elif e["audit"] not in {f for f, dd in open_list if dd == d}:
            problems.append("%s 登記的 audit=%s 與宣告它的稽核檔不符" % (d, e["audit"]))
    if len(register) > MAX_OPEN:
        problems.append("登記中的未關必修 %d 筆，超過上限 %d ⇒ 先把已修好的請稽核關閉，不要用登記表累積紅燈"
                        % (len(register), MAX_OPEN))
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--audit-dir", default=str(AUDIT_DIR))
    ap.add_argument("--register", default=str(REGISTER))
    ap.add_argument("--legacy", default=str(LEGACY))
    a = ap.parse_args(argv)
    texts = load_texts(a.audit_dir)
    decl, opened = declared(texts), open_items(texts, load_legacy(a.legacy))
    print("宣告的必修：%d｜沒有關閉紀錄：%d" % (len(decl), len(opened)))
    for f, d in opened:
        print("  %s %s" % (f, d))
    problems = check(opened, load_register(a.register)) + legacy_problems(texts, a.legacy)
    for p in problems:
        print("✗ " + p)
    print("✓ 與登記表一致" if not problems else "✗ %d 項" % len(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
