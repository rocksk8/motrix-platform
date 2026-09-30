# -*- coding: utf-8 -*-
"""去識別化 S3：虛構值登記檔 `deid_fiction.json`（SALE-PACKAGE-DEID.md §2.1）——工具與驗證。只用標準庫。

登記檔是 list：`[{"kind","value","value_id","reason","added", ...}]`。`value_id` ＝ `deid_scan.value_code(kind, value)`（樣式層代碼，
sha256 前 8 hex）；掃描器命中的樣式值代碼在登記內 ⇒ 歸為「虛構」、不擋。**登記檔內是明文的虛構值**（所以不能登記真實值），
因此每一筆都要過取值規則（§2.1），`problems()` 不過就紅：

  taxid    檢查碼正確且**已以 GCIS 查詢確認查無登記**（要有 `gcis_checked: YYYY-MM-DD`）；保留值 `00000000` 免查詢
  phone    只准未核配號段：`02-0000-0000`～`02-0000-9999`、`0900-000-000`
  email    只准 example.com／.org／.net／*.test／*.invalid（RFC 2606）；另收公開的格式提示 `xxxxx@group.calendar.google.com`
  company  名稱要帶「範例／示範／測試／演練」
  address  以「範例」開頭
  docno    單據編號範例：流水號只准 `001`／`0001`（格式示意），不准像真實案件的號碼
  其他類別  不收（要收先改本檔的規則，不是臨時放行）

用法：
  python tools/platform/deid_fiction.py check [--file tools/platform/deid_fiction.json]
  python tools/platform/deid_fiction.py add --kind company --value 範例科技股份有限公司 --reason "登記頁範例" [--gcis-checked 2026-09-30]
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deid_scan as S  # noqa: E402

DEFAULT_FILE = Path(__file__).resolve().parent / "deid_fiction.json"
RESERVED_TAXID = "00000000"
FICTION_WORDS = ("範例", "示範", "測試", "演練")
EXAMPLE_DOMAINS = ("example.com", "example.org", "example.net")
#: 公開的固定格式提示（Google 行事曆 ID 的格式說明），不是任何人的信箱：只准這一個完整字串
PUBLIC_FORMAT_EMAILS = ("xxxxx@group.calendar.google.com",)
KINDS = ("taxid_pattern", "phone_pattern", "email", "company_pattern", "address_pattern", "docno_pattern")
PHONE_OK = (re.compile(r"^02-?0000-?\d{4}$"), re.compile(r"^0900-?000-?000$"))
DOCNO_RE = re.compile(r"^[A-Z]{2,3}-20\d{4}-(?:001|0001)(?:-R\d+)?$")


def value_problem(kind, value, entry=None):
    """⇒ 不合規則的原因（空字串＝合規）。"""
    entry = entry or {}
    v = str(value or "")
    if kind not in KINDS:
        return "類別 %s 不收虛構登記（收：%s）" % (kind, "、".join(KINDS))
    if kind == "taxid_pattern":
        if v == RESERVED_TAXID:
            return ""
        if not S.tw_tax_id_valid(v):
            return "統編檢查碼不對（不對的值掃描器本來就不會命中，不必登記）"
        chk = str(entry.get("gcis_checked") or "")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", chk):
            return "統編要記 GCIS 查詢日期 gcis_checked（確認查無登記）；保留值 00000000 免"
        return ""
    if kind == "phone_pattern":
        n = re.sub(r"^\+886[\s-]?", "0", v.replace(" ", ""))
        return "" if any(p.match(n) for p in PHONE_OK) else "電話只准 02-0000-0000～9999、0900-000-000（未核配號段）"
    if kind == "email":
        if v in PUBLIC_FORMAT_EMAILS:
            return ""
        dom = v.rsplit("@", 1)[-1].lower()
        ok = dom in EXAMPLE_DOMAINS or dom.endswith((".test", ".invalid", ".example", ".localhost"))
        return "" if ok else "email 只准 example.com／.org／.net／*.test／*.invalid"
    if kind == "company_pattern":
        return "" if any(w in v for w in FICTION_WORDS) else "公司名要帶「範例／示範／測試／演練」"
    if kind == "address_pattern":
        return "" if v.startswith("範例") else "地址要以「範例」開頭"
    if kind == "docno_pattern":
        return "" if DOCNO_RE.match(v) else "單據編號範例的流水號只准 001／0001（格式示意）"
    return "未知類別"


def make_entry(kind, value, reason, gcis_checked=None, added=None):
    e = {"kind": kind, "value": value, "value_id": S.value_code(kind, value), "reason": reason, "added": added or date.today().isoformat()}
    if gcis_checked:
        e["gcis_checked"] = gcis_checked
    return e


def problems(entries):
    """⇒ [問題字串]。每筆：類別／取值規則／value_id 與明文一致／有理由；整份：value_id 不重複。"""
    out, seen = [], {}
    for i, e in enumerate(entries):
        tag = "第 %d 筆（%s）" % (i + 1, e.get("kind"))
        if not str(e.get("reason") or "").strip():
            out.append("%s 沒有理由" % tag)
        why = value_problem(e.get("kind"), e.get("value"), e)
        if why:
            out.append("%s %s" % (tag, why))
        elif e.get("value_id") != S.value_code(e["kind"], e["value"]):
            out.append("%s value_id 與明文對不上（登記檔被手改？）" % tag)
        vid = e.get("value_id")
        if vid in seen:
            out.append("%s value_id 重複（與第 %d 筆）" % (tag, seen[vid] + 1))
        seen.setdefault(vid, i)
    return out


def load(path=DEFAULT_FILE):
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else []


def save(entries, path=DEFAULT_FILE):
    Path(path).write_text(json.dumps(entries, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", default=str(DEFAULT_FILE))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    a = sub.add_parser("add")
    a.add_argument("--kind", required=True)
    a.add_argument("--value", required=True)
    a.add_argument("--reason", required=True)
    a.add_argument("--gcis-checked")
    args = ap.parse_args(argv)
    entries = load(args.file)
    if args.cmd == "check":
        probs = problems(entries)
        for p in probs:
            print("DEID_FICTION_PROBLEM " + p)
        print("DEID_FICTION_%s %d 筆" % ("FAIL" if probs else "OK", len(entries)))
        return 1 if probs else 0
    e = make_entry(args.kind, args.value, args.reason, args.gcis_checked)
    probs = problems(entries + [e])
    if probs:
        for p in probs:
            print("DEID_FICTION_REFUSED " + p)
        return 1
    save(entries + [e], args.file)
    print("DEID_FICTION_ADDED %s %s" % (e["kind"], e["value_id"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
