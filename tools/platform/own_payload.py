# -*- coding: utf-8 -*-
"""去識別化段 1：本公司資料檔（own payload）——由**固定的舊版 db.py（git 歷史）**取出，產物放程式庫之外。

使用者裁示（2026-09-28 19:32，CORE-SPEC「去識別化：本公司資料的存放」）：本公司資料**不進程式庫，建包時產生**。
db.py 的凍結 migration 原本把三類值寫成字面值：
  A 類  註解／docstring            ⇒ 直接改寫成不含值（不需要資料檔）
  B 類  比較條件（哪些列要改）      ⇒ 改比 sha256（`db._frozen_sha256`），行為等價（本工具 `hashes` 印出要貼進 db.py 的雜湊）
  C 類  要寫進去的值（顯示名、email、英文公司名）⇒ 讀這份資料檔；缺檔或版本不符 ⇒ `db._FrozenOwnPayloadError`
這支工具就是產生／驗證 C 類資料檔的地方。**值不印到畫面、不寫 log、不進 commit。**

用法：
  python tools/platform/own_payload.py generate --out D:\\MOTRIX-KEYS\\deid\\own_payload.json [--copy-to backend/migrations_frozen/own_payload.json]
  python tools/platform/own_payload.py hashes        # 印 B 類雜湊常數（只有雜湊，可貼進 db.py）
  python tools/platform/own_payload.py verify <檔>   # 只驗版本綁定與欄位齊全，不印值

資料檔格式：{"v": 1, "source_blob": "<固定舊版 db.py 的 git blob id>", "m008": {"correct": ..., "email": ...}, "m106": {"company_name_en": ...}}
`source_blob` 綁定「取自哪一版」——db.py 載入時比對，不符就拒絕（不會用錯版本的值）。
"""
import argparse
import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
#: 固定的舊版 db.py（train/0930 7a443897 的 backend/db.py，含全部字面值）。git 歷史裡永遠取得到；內容雜湊一併釘住。
PINNED_BLOB = "cb3d1c27f5dfb30527b3554b9a272abaaffa99b4"
PINNED_SHA256 = "3341bf242e694981b18af4092e01cdfc2db95e0110b07f692aa82acd432b6f00"
FORMAT = 1


def pinned_source(repo=REPO):
    r = subprocess.run(["git", "-C", str(repo), "cat-file", "blob", PINNED_BLOB], capture_output=True)
    if r.returncode != 0:
        raise SystemExit("取不到固定的舊版 db.py（blob %s）：%s" % (PINNED_BLOB, r.stderr.decode("utf-8", "replace").strip()))
    if hashlib.sha256(r.stdout).hexdigest() != PINNED_SHA256:
        raise SystemExit("固定的舊版 db.py 內容雜湊不符（blob %s）" % PINNED_BLOB)
    return r.stdout.decode("utf-8")


def _func(tree, name):
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n
    raise SystemExit("舊版 db.py 找不到 %s" % name)


def _const_str(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def extract(text):
    """⇒ (payload dict（含明文，只給寫檔用）, hashes dict（只有雜湊）, values dict（明文，**只給契約題在記憶體內造夾具用**，不寫檔不印））。"""
    tree = ast.parse(text)
    f8 = _func(tree, "_m008_fix_legacy_owner_names")
    old_names, correct, email, owner_user = None, None, None, None
    for n in ast.walk(f8):
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            if n.targets[0].id == "old_names" and isinstance(n.value, ast.Tuple):
                old_names = [_const_str(e) for e in n.value.elts]
            if n.targets[0].id == "correct":
                correct = _const_str(n.value)
    import re
    for n in ast.walk(f8):
        s = _const_str(n)
        if s and s.startswith("UPDATE users SET email="):
            m = re.match(r"UPDATE users SET email='([^']*)' WHERE username='([^']*)'", s)
            if m:
                email, owner_user = m.group(1), m.group(2)
    f106 = _func(tree, "_m106_company_profile_identity_backfill")
    taxid, name_en = None, None
    for n in ast.walk(f106):
        if isinstance(n, ast.Compare) and isinstance(n.ops[0], ast.NotEq) and _const_str(n.comparators[0]):
            taxid = _const_str(n.comparators[0])
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_backfill" and len(n.args) == 2 and _const_str(n.args[0]) == "company_name_en":
            name_en = _const_str(n.args[1])
    if not (old_names and all(old_names) and correct and email and owner_user and taxid and name_en):
        raise SystemExit("舊版 db.py 的結構與預期不同，抽不出全部值（不印細節，避免洩漏）")
    h = lambda v: hashlib.sha256(v.encode("utf-8", "surrogatepass")).hexdigest()
    payload = {"v": FORMAT, "source_blob": PINNED_BLOB, "m008": {"correct": correct, "email": email}, "m106": {"company_name_en": name_en}}
    hashes = {"m008_old_names": sorted(h(v) for v in old_names), "m008_username": h(owner_user), "m106_tax_id": h(taxid)}
    values = {"old_names": old_names, "username": owner_user, "tax_id": taxid}
    return payload, hashes, values


def verify_payload(d):
    """⇒ 問題清單（空＝可用）。不印值。"""
    if not isinstance(d, dict) or d.get("v") != FORMAT:
        return ["格式版本不符"]
    if d.get("source_blob") != PINNED_BLOB:
        return ["來源版本（source_blob）與固定的舊版 db.py 不符"]
    probs = []
    for sec, keys in (("m008", ("correct", "email")), ("m106", ("company_name_en",))):
        s = d.get(sec)
        for k in keys:
            if not isinstance(s, dict) or not isinstance(s.get(k), str) or not s[k]:
                probs.append("缺欄位 %s.%s" % (sec, k))
    return probs


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--out", required=True)
    g.add_argument("--copy-to")
    sub.add_parser("hashes")
    v = sub.add_parser("verify")
    v.add_argument("file")
    a = ap.parse_args(argv)
    if a.cmd == "verify":
        try:
            d = json.load(open(a.file, encoding="utf-8-sig"))
        except (OSError, ValueError) as e:
            print("OWN_PAYLOAD_INVALID 讀不懂：%s" % type(e).__name__)
            return 1
        probs = verify_payload(d)
        for p in probs:
            print("OWN_PAYLOAD_INVALID %s" % p)
        print("OWN_PAYLOAD_%s" % ("OK" if not probs else "BAD"))
        return 0 if not probs else 1
    payload, hashes, _values = extract(pinned_source())
    if a.cmd == "hashes":
        print(json.dumps(hashes, indent=1))
        return 0
    for path in [a.out] + ([a.copy_to] if a.copy_to else []):
        p = Path(path)
        if p.exists():
            print("OWN_PAYLOAD_REFUSED 已存在：%s（不覆蓋）" % p)
            return 1
    for path in [a.out] + ([a.copy_to] if a.copy_to else []):
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "x", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
            f.write("\n")
        print("OWN_PAYLOAD_OK %s（%d 個欄位，值不顯示）" % (p, sum(len(v) for k, v in payload.items() if isinstance(v, dict))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
