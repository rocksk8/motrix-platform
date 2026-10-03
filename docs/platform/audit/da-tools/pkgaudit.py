# -*- coding: utf-8 -*-
r"""da 包完整性唯讀稽核。用法：
  python pkgaudit.py --pkg <G:\...\packages\NAME> --commit <SHA> [--prev <前一包目錄> --prev-commit <SHA>] [--deploy <deploy_packages\NAME>] [--repo D:\MOTRIX-PLATFORM] [--expect-db 116]
全程唯讀（只讀 git／檔案；暫存放 %TEMP%\da-pkgaudit，用完刪）。輸出 PASS／FAIL 逐項。"""
import argparse, base64, hashlib, json, os, re, shutil, subprocess, sys, tempfile, zipfile, io

ap = argparse.ArgumentParser()
ap.add_argument("--pkg", required=True); ap.add_argument("--commit", required=True)
ap.add_argument("--prev"); ap.add_argument("--prev-commit")
ap.add_argument("--deploy"); ap.add_argument("--repo", default=r"D:\MOTRIX-PLATFORM"); ap.add_argument("--expect-db", type=int, default=116)
a = ap.parse_args()
sys.path.insert(0, os.path.join(a.repo, "backend", "tools"))
import delivery as D  # noqa

R = []
def rep(name, ok, detail=""):
    R.append((name, ok, detail)); print(("PASS " if ok else "FAIL ") + name + ((" — " + str(detail)[:600]) if detail else ""))

def sh(*cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, creationflags=0x08000000)

pk = a.pkg; payload = os.path.join(pk, "payload")
meta_b = open(os.path.join(pk, "delivery.json"), "rb").read(); sha_b = open(os.path.join(pk, "package.sha256"), "rb").read()
sig = open(os.path.join(pk, "package.sha256.sig"), "r").read().strip()
meta = json.loads(meta_b)
print("package.sha256 SHA256 =", hashlib.sha256(sha_b).hexdigest().upper())
# 1 檔數／bytes／雜湊
ents = D.payload_entries(payload); listed = D.parse_sha_list(sha_b.decode("utf-8"))
bad = [r for r, s, n in ents if listed.get(r) != s]
rep("1 檔數／雜湊", len(ents) == len(listed) == meta["files"] and not bad and {r for r, _s, _n in ents} == set(listed),
    {"payload": len(ents), "sha_lines": len(listed), "meta_files": meta["files"], "mismatch": bad[:5], "bytes": (sum(n for _r, _s, n in ents), meta["bytes"])})
rep("1b bytes 與 meta", sum(n for _r, _s, n in ents) == meta["bytes"])
rep("1c meta 欄位", meta.get("format") == 1 and meta.get("kind") == "full" and meta.get("product") == "full" and meta.get("commit", "").startswith(a.commit), {k: meta.get(k) for k in ("format", "kind", "product", "commit", "name")})
# 2 簽章＋反向控制
pub = D.DELIVERY_PUBKEY_PEM
sb = D.signed_bytes(meta_b, sha_b)
ok_real = D.verify_signature(sb, sig, pub)
def flip(b): return bytes([b[0] ^ 1]) + b[1:] if b else b
neg = [D.verify_signature(D.signed_bytes(meta_b, flip(sha_b)), sig, pub), D.verify_signature(D.signed_bytes(flip(meta_b), sha_b), sig, pub)]
sg = bytearray(base64.b64decode(sig)); sg[0] ^= 1
neg.append(D.verify_signature(sb, base64.b64encode(bytes(sg)).decode(), pub))
rep("2 簽章（真實 True＋三項反向控制 False）", ok_real and not any(neg), {"real": ok_real, "flip_sha/meta/sig": neg})
# 3 與前一包 diff
SPECIAL = {"backend/.build_commit", "backend/export_ignore.json", "backend/modules.lock.json", "deploy_manifest.json", "backend/version_manifest.json"}
def tree_hashes(root): return {r: s for r, s, _n in D.payload_entries(root)}
if a.prev:
    ph = tree_hashes(os.path.join(a.prev, "payload")); nh = {r: s for r, s, _n in ents}
    add = sorted(set(nh) - set(ph)); rem = sorted(set(ph) - set(nh)); chg = sorted(r for r in nh if r in ph and nh[r] != ph[r])
    gd = set(sh("git", "-c", "core.quotepath=false", "diff", "--name-only", "-z", a.prev_commit, a.commit, cwd=a.repo).stdout.decode("utf-8", "replace").split("\0")) - {""}
    unexplained = [r for r in add + chg if r not in gd and r not in SPECIAL]
    rep("3 與前一包 diff（每個差異檔都在 git diff 內）", not unexplained, {"added": len(add), "removed": len(rem), "changed": len(chg), "removed_list": rem[:10], "unexplained": unexplained[:10]})
    open(os.path.join(tempfile.gettempdir(), "da_pkg_diff.txt"), "w", encoding="utf-8").write("ADDED\n" + "\n".join(add) + "\nREMOVED\n" + "\n".join(rem) + "\nCHANGED\n" + "\n".join(chg))
# 4 禁入掃描＋正對照
FORB_NAME = re.compile(r"(\.db$|\.sqlite3?$|\.db-wal$|\.db-shm$|(^|/)__pycache__(/|$)|\.pyc$|(^|/)\.env($|\.)|\.pem$|\.key$|(^|/)venv|\.venv)", re.I)
FORB_BODY = [re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"), re.compile(rb"MOTRIX-KEYS")]
def scan(root):
    hits = []
    for dp, _d, fns in os.walk(root):
        for fn in fns:
            full = os.path.join(dp, fn); rel = os.path.relpath(full, root).replace("\\", "/")
            if FORB_NAME.search(rel): hits.append((rel, "name"))
            try:
                if os.path.getsize(full) < 5_000_000:
                    b = open(full, "rb").read()
                    for p in FORB_BODY:
                        if p.search(b): hits.append((rel, p.pattern[:20].decode())) ; break
            except OSError: pass
    return hits
tmp = os.path.join(tempfile.gettempdir(), "da-pkgaudit"); shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp)
pc = os.path.join(tmp, "control"); os.makedirs(os.path.join(pc, "x", "__pycache__"))
open(os.path.join(pc, "a.db"), "wb").write(b"x"); open(os.path.join(pc, "x", "__pycache__", "m.pyc"), "wb").write(b"x"); open(os.path.join(pc, ".env"), "w").write("K=1")
open(os.path.join(pc, "doc.md"), "w").write(r"see D:\MOTRIX-KEYS\delivery"); open(os.path.join(pc, "k.txt"), "w").write("-----BEGIN PRIVATE KEY-----\nabc")
ctrl = scan(pc); rep("4a 禁入掃描正對照（5 個植入物須全中）", len({h[0] for h in ctrl}) >= 5, sorted({h[0] for h in ctrl}))
hits = scan(payload)
base = [h for h in hits if h[1] == "MOTRIX-KEYS"]; other = [h for h in hits if h[1] != "MOTRIX-KEYS"]
rep("4b 包內禁入（排除 MOTRIX-KEYS 路徑字串基線）", not other, {"other": other[:10], "motrix_keys_path_mentions": [h[0] for h in base]})
# 5 export_ignore＋git archive 逐檔
arc = os.path.join(tmp, "archive")
r = subprocess.run("git archive %s | tar -x -C %s" % (a.commit, arc.replace("\\", "/")), shell=True, cwd=a.repo, capture_output=True) if os.makedirs(arc, exist_ok=True) is None else None
ah = tree_hashes(arc); nh = {r_: s for r_, s, _n in ents}
only_pk = sorted(set(nh) - set(ah)); only_ar = sorted(set(ah) - set(nh)); diff_c = sorted(k for k in nh if k in ah and nh[k] != ah[k])
def crlf_only(rel):
    pa, pb = open(os.path.join(payload, rel), "rb").read(), open(os.path.join(arc, rel), "rb").read()
    return pa.replace(b"\r\n", b"\n") == pb.replace(b"\r\n", b"\n")
true_diff = [k for k in diff_c if not crlf_only(k)]
rep("5a git archive 對照（只在包＝建包產生檔、無缺檔、內容差異僅 version_manifest）",
    set(only_pk) <= SPECIAL and not only_ar and set(true_diff) <= SPECIAL,
    {"only_in_package": only_pk, "only_in_archive": only_ar[:10], "crlf_only": len(diff_c) - len(true_diff), "content_diff": true_diff})
ei = json.load(open(os.path.join(payload, "backend", "export_ignore.json"), encoding="utf-8")) if os.path.exists(os.path.join(payload, "backend", "export_ignore.json")) else {}
lst = ei.get("paths") or []
tree = set(sh("git", "-c", "core.quotepath=false", "ls-tree", "-r", "--name-only", "-z", a.commit, cwd=a.repo).stdout.decode("utf-8", "replace").split("\0")) - {""}
rep("5b export_ignore＝ls-tree−archive 且清單內無檔出現在 payload", set(lst) == (tree - set(ah)) and not (set(lst) & set(nh)) if lst else False,
    {"registered": len(lst), "expected": len(tree - set(ah)), "commit": ei.get("commit"), "commit_matches": str(ei.get("commit","")).startswith(a.commit)})
bc = open(os.path.join(payload, "backend", ".build_commit"), "r", encoding="utf-8").read().strip()
rep("5c .build_commit", bc.startswith(a.commit) or a.commit.startswith(bc[:8]), bc)
# 6 verify_package
if a.deploy:
    r = subprocess.run([sys.executable, os.path.join(a.repo, "backend", "tools", "verify_package.py"), a.deploy, "--expect-db-version", str(a.expect_db)], capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=0x08000000)
    out = (r.stdout or "") + (r.stderr or "")
    m = re.search(r"（(\d+) 項 FAIL）", out)
    rep("6 verify_package --expect-db-version %d" % a.expect_db, r.returncode == 0 and m is not None and m.group(1) == "0", "FAIL count=%s rc=%s" % (m.group(1) if m else None, r.returncode))
    # 6b deploy_packages 與 G: payload 逐檔
    dh = tree_hashes(a.deploy); only_d = sorted(set(dh) - set(nh)); only_g = sorted(set(nh) - set(dh)); dd = sorted(k for k in nh if k in dh and nh[k] != dh[k])
    rep("6b deploy_packages 與 G: payload 逐檔相同（允許 deploy 僅多 product/ 等建包輔助）", not dd and not only_g, {"only_deploy": only_d[:8], "only_G": only_g[:8], "diff": dd[:8]})

# 7 版號：module.json 版號皆為數字（無 next 佔位）、CHANGELOG 最上面條目＝module.json 版號、core 版號
import glob as _g
badv = []
for mj in sorted(_g.glob(os.path.join(payload, "backend", "modules", "*", "module.json"))):
    m = json.load(open(mj, encoding="utf-8-sig")); v = str(m.get("version"))
    cl = os.path.join(os.path.dirname(mj), "CHANGELOG.md")
    top = None
    if os.path.exists(cl):
        mm = re.search(r"^##[ 	]+(\S+)", open(cl, encoding="utf-8").read(), re.M); top = mm.group(1) if mm else None
    if not re.fullmatch(r"\d+\.\d+\.\d+", v) or (top is not None and top != v):
        badv.append((m.get("key"), v, top))
rep("7 module.json 版號為數字且＝CHANGELOG 最上條目", not badv, badv)
ccl = os.path.join(payload, "backend", "core", "CHANGELOG.md")
if os.path.exists(ccl):
    mm = re.search(r"^##[ 	]+(\S+)", open(ccl, encoding="utf-8").read(), re.M)
    rep("7b core CHANGELOG 最上條目非 (next)", bool(mm) and "next" not in mm.group(1), mm.group(1) if mm else None)
shutil.rmtree(tmp, ignore_errors=True)
fails = [n for n, ok, _d in R if not ok]
print("\nSUMMARY: %d 項，FAIL %d %s" % (len(R), len(fails), fails))
sys.exit(1 if fails else 0)
