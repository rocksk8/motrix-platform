# -*- coding: utf-8 -*-
"""去識別化 S2：清單產生器（SALE-PACKAGE-DEID.md §2.2 (a)）——**在正式機上執行**，讀每日備份的複本（不開正式庫），**只輸出雜湊**。

用法：
  python deid_hashlist.py keygen --out <金鑰檔>                       # 32 bytes 隨機；已存在就拒絕；只印路徑與 key_id
  python deid_hashlist.py export --db <備份複本> --key <金鑰檔> --out <清單.json> [--extra <補充檔.json>]

## 金鑰（H2-S2）
32 bytes，離線存放（開發機 D:\\MOTRIX-KEYS\\deid\\hmac.key＋隨身碟）；正式機執行 export 時由隨身碟提供、**不留在正式機**。
**不印金鑰、不寫 log；輸出只有 key_id（HMAC(key,"motrix-deid-keycheck") 前 8 bytes）**。Claude 不讀金鑰內容。

## 清單內容
`{"v":1, "key_id", "created", "source_counts":{kind:n}, "lengths":{kind:[長度]}, "anchors":{8hex:[長度]}, "hashes":{32hex:kind}}`
- 雜湊：`HMAC-SHA256(key, kind + "|" + normalize(value))` 取前 16 bytes（要金鑰，不是公開鹽：統編 8 碼、電話 10 碼空間小，公開鹽會被窮舉）。
- 數字型（taxid／phone／account）：值正規化後取連續數字串（≥ 8 碼）；文字型：正規化後 ≥ 3 字，另存前 3 字的 anchor。
- **金絲雀**：一律加進清單（kind=canary），掃描器要能掃到它（證明清單／金鑰／掃描器接得起來）。
- 人工補充檔 `--extra`：`[{"kind":"company","value":"…"}, {"kind":"company","value":"兩字簡稱","adjacent":["整合","公司"]}]`
  兩字簡稱不進雜湊層（誤判太多）；有 `adjacent` ⇒ 展開成「簡稱＋鄰接字」的完整字串各自雜湊。補充檔是明文識別資訊，**只放隨身碟，不進 repo**。
- 資料庫只以唯讀（`mode=ro`）開；表或欄不存在就略過（`source_counts` 記 0，不猜）。
"""
import argparse
import hashlib
import hmac
import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deid_scan as S  # noqa: E402

#: (表, 欄, kind)。company_profile 是 system_settings 裡的 JSON（見 _profile_values）。
SOURCES = (
    ("customers", "name", "customer"), ("customers", "tax_id", "taxid"), ("customers", "phone", "phone"),
    ("suppliers", "name", "supplier"), ("suppliers", "tax_id", "taxid"), ("suppliers", "phone", "phone"),
    ("vendor_contractors", "name", "supplier"), ("vendor_contractors", "tax_id", "taxid"), ("vendor_contractors", "contact_name", "person"),
    ("vendor_contractors", "phone", "phone"), ("vendor_contractors", "email", "email"), ("vendor_contractors", "address", "address"),
    ("contractors", "name", "person"), ("contractors", "phone", "phone"), ("contractors", "email", "email"), ("contractors", "address", "address"),
    ("contractors", "bank_account_number", "account"), ("contractors", "bank_account_name", "person"),
    ("users", "display_name", "person"), ("users", "email", "email"), ("users", "phone", "phone"),
    ("quotations", "customer_name", "customer"), ("dev_cases", "customer_name", "customer"),
)
#: company_profile（system_settings.key）JSON 內的欄位 ⇒ kind
PROFILE_FIELDS = (("name", "company"), ("company_name", "company"), ("company_name_en", "company"), ("tax_id", "taxid"), ("phone", "phone"),
                  ("email", "email"), ("address", "address"), ("contact_info", "company"))


def open_readonly(db_path):
    p = Path(db_path).resolve()
    if not p.is_file():
        raise SystemExit("找不到資料庫複本：%s" % p)
    return sqlite3.connect("file:%s?mode=ro" % str(p).replace("\\", "/"), uri=True, timeout=30)


def _table_cols(conn, table):
    return {r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)}


def collect(conn):
    """⇒ {kind: set(明文值)}，以及 source_counts。明文只在記憶體內，不輸出。"""
    vals, counts = {}, {}
    for table, col, kind in SOURCES:
        try:
            if col not in _table_cols(conn, table):
                counts["%s.%s" % (table, col)] = 0
                continue
            rows = [r[0] for r in conn.execute("SELECT DISTINCT %s FROM %s WHERE %s IS NOT NULL AND %s <> ''" % (col, table, col, col))]
        except sqlite3.Error:
            counts["%s.%s" % (table, col)] = 0
            continue
        rows = [str(v) for v in rows if str(v).strip()]
        vals.setdefault(kind, set()).update(rows)
        counts["%s.%s" % (table, col)] = len(rows)
    try:
        row = conn.execute("SELECT value_json FROM system_settings WHERE key='company_profile'").fetchone()
        prof = json.loads(row[0]) if row and row[0] else {}
    except (sqlite3.Error, ValueError, TypeError):
        prof = {}
    n = 0
    for f, kind in PROFILE_FIELDS:
        v = prof.get(f) if isinstance(prof, dict) else None
        if isinstance(v, str) and v.strip():
            vals.setdefault(kind, set()).add(v)
            n += 1
    counts["company_profile"] = n
    return vals, counts


def expand_extra(extra):
    """補充檔 ⇒ {kind: set(值)}。有 adjacent ⇒「簡稱＋鄰接字」展開；沒有 adjacent 的短值原樣進（長度不足的下面會被略過並計入 skipped_short）。"""
    out = {}
    for e in extra or []:
        kind, v = e.get("kind"), e.get("value")
        if not kind or not isinstance(v, str) or not v.strip():
            continue
        adj = e.get("adjacent") or []
        if adj:
            for a in adj:
                out.setdefault(kind, set()).add(v + a)
                out.setdefault(kind, set()).add(a + v)
        else:
            out.setdefault(kind, set()).add(v)
    return out


def build(vals, key, created=None):
    """⇒ 清單 dict。長度不足（數字 <8、文字 <3）的略過並計數。"""
    hashes, lengths, anchors, kept, skipped = {}, {}, {}, {}, 0
    vals = {k: set(v) for k, v in vals.items()}
    vals.setdefault("canary", set()).add(S.CANARY)
    for kind, values in sorted(vals.items()):
        numeric = kind in S.NUMERIC_KINDS
        for v in sorted(values):
            n = S.normalize(v)
            if numeric:
                n = "".join(re.findall(r"\d+", n)) if re.search(r"\d", n) else ""
                ok = len(n) >= S.MIN_DIGITS
            else:
                ok = len(n) >= S.MIN_TEXT
            if not ok:
                skipped += 1
                continue
            hashes[S._hmac_norm(key, kind, n)] = kind
            lengths.setdefault(kind, set()).add(len(n))
            kept[kind] = kept.get(kind, 0) + 1
            if not numeric:
                a = S.anchor_id(key, n[:S.MIN_TEXT])
                anchors.setdefault(a, set()).add(len(n))
    return {"v": 1, "key_id": S.key_id(key), "created": (created or datetime.now()).isoformat(timespec="seconds"),
            "source_counts": kept, "skipped_short": skipped,
            "lengths": {k: sorted(v) for k, v in sorted(lengths.items())},
            "anchors": {a: sorted(v) for a, v in sorted(anchors.items())}, "hashes": dict(sorted(hashes.items()))}


def cmd_keygen(a):
    p = Path(a.out)
    if p.exists():
        print("DEID_KEYGEN_REFUSED 已存在：%s" % p)
        return 1
    p.parent.mkdir(parents=True, exist_ok=True)
    key = os.urandom(32)
    with open(p, "xb") as f:
        f.write(key)
    print("DEID_KEYGEN_OK path=%s key_id=%s size=32" % (p, S.key_id(key)))
    return 0


def cmd_export(a):
    key = S.load_key(a.key)
    conn = open_readonly(a.db)
    try:
        vals, counts = collect(conn)
    finally:
        conn.close()
    extra = []
    if a.extra:
        extra = json.loads(Path(a.extra).read_text(encoding="utf-8-sig"))
    for kind, values in expand_extra(extra).items():
        vals.setdefault(kind, set()).update(values)
    data = build(vals, key)
    data["source_columns"] = counts
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".%d.tmp" % os.getpid())
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, out)
    print("DEID_EXPORT_OK key_id=%s created=%s kinds=%s skipped_short=%d → %s" % (
        data["key_id"], data["created"], json.dumps(data["source_counts"], ensure_ascii=False), data["skipped_short"], out))
    return 0


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keygen")
    k.add_argument("--out", required=True)
    e = sub.add_parser("export")
    e.add_argument("--db", required=True)
    e.add_argument("--key", required=True)
    e.add_argument("--out", required=True)
    e.add_argument("--extra")
    a = ap.parse_args(argv)
    return cmd_keygen(a) if a.cmd == "keygen" else cmd_export(a)


if __name__ == "__main__":
    sys.exit(main())
