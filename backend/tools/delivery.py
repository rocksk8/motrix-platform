# -*- coding: utf-8 -*-
"""更新交付：開發機把完整包發布到 <交付資料夾>；正式機偵測、複製到 staging、驗證（UPDATE-DELIVERY.md §2、§3）。

[單位] tool:delivery    [層] 部署工具（開發機與正式機各跑**自己安裝的**這一份）
[公開介面] keygen, publish, scan, stage, verify_staged, sign, verify_signature, signed_bytes
[不變式] 發布以「整個目錄改名」收尾（incoming\\<包>.partial → packages\\<包>）；正式機只看 packages\\。
         驗證用**正式機已安裝版本**內建的公鑰（`DELIVERY_PUBKEY_PEM`），不用包自己帶的——新包不能替自己背書。
         簽章涵蓋 delivery.json＋package.sha256（`signed_bytes`）⇒ 改任何一個都驗不過。
         staging 逐檔雜湊與清單完全相同（不多不少）才算通過。任何一項判不出來 ⇒ 不通過（不猜）。
[契約題] tests/platform/test_delivery_2026_09_28.py
[注意] 不碰正式機的程式與資料：staging 放在安裝目錄**外**（呼叫端給路徑）；本檔不呼叫 apply_update（一鍵套用另做）。
       <交付資料夾> 由使用者自建（U-1＝我的雲端硬碟\\MOTRIX-交付），程式**不自動建**：根目錄不存在 ⇒ 拒絕。

交付資料夾結構：
  <交付資料夾>\\incoming\\<包名>.partial\\   發布中（正式機不看）
  <交付資料夾>\\packages\\<包名>\\           已發布：payload\\（完整包）＋delivery.json＋package.sha256＋package.sha256.sig
  <交付資料夾>\\results\\<包名>.result.json  正式機寫回的結果（(d) 另做；本檔只讀它來決定能不能清舊包）

子命令（exit：0 通過／1 不通過或拒絕）：
  keygen   --private-out <路徑>                 產生 Ed25519 金鑰：私鑰寫到檔（已存在就拒絕），公鑰印出（貼進 DELIVERY_PUBKEY_PEM）
  publish  --pkg <完整包> --root <交付資料夾> --private-key <私鑰檔> [--keep 3]
  scan     --root <交付資料夾>
  stage    --root <交付資料夾> --name <包名> --staging <staging 根>
  verify   --staged <staging\\包名> --install-root <安裝根目錄> [--skip-verify-package]
"""
import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime

#: 正式機驗章用的公鑰（PEM）。U-4：私鑰放開發機本機檔＋使用者離線備份；公鑰由 `keygen` 印出後貼在這裡、隨版本出貨。
#: 空的 ⇒ verify 一律拒絕（「尚未設定交付公鑰」），不會退回「不驗章」。
DELIVERY_PUBKEY_PEM = b""

FORMAT = 1
KEEP_DEFAULT = 3                     # U-5
PAYLOAD = "payload"
META_JSON = "delivery.json"
SHA_LIST = "package.sha256"
SIG = "package.sha256.sig"
NAME_RE = re.compile(r"^\d{8}_\d{6}_[0-9a-f]{8}_[a-z0-9_-]+$")
_PS1 = "backend/tools/apply_update.ps1"
_PS1_REG = "backend/tools/apply_update.version.json"
_PS1_VER_RE = re.compile(r'^\$ApplyScriptVersion = "([^"]+)"', re.M)


class DeliveryError(Exception):
    pass


# ── 雜湊、簽章 ────────────────────────────────────────────────────────────────

def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def payload_entries(payload):
    """[(相對路徑 posix, sha256, 位元組)]，依路徑排序；payload 裡的每一個檔都算（不略過任何東西）。"""
    out = []
    for dp, _dns, fns in os.walk(payload):
        for fn in fns:
            full = os.path.join(dp, fn)
            rel = os.path.relpath(full, payload).replace("\\", "/")
            out.append((rel, _sha256_file(full), os.path.getsize(full)))
    return sorted(out)


def sha_list_text(entries):
    return "".join("%s  %s\n" % (sha, rel) for rel, sha, _n in entries)


def parse_sha_list(text):
    out = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        m = re.match(r"^([0-9a-f]{64})  (.+)$", line)
        if not m:
            raise DeliveryError("package.sha256 格式不對：%r" % line[:80])
        if m.group(2) in out:
            raise DeliveryError("package.sha256 同一個檔出現兩次：%s" % m.group(2))
        out[m.group(2)] = m.group(1)
    return out


def signed_bytes(meta_bytes, sha_bytes):
    """簽章涵蓋的內容：delivery.json 與 package.sha256 的原始位元組（中間隔 NUL）。"""
    return meta_bytes + b"\0" + sha_bytes


def sign(data, private_pem):
    from cryptography.hazmat.primitives import serialization
    key = serialization.load_pem_private_key(private_pem, password=None)
    return base64.b64encode(key.sign(data)).decode("ascii")


def verify_signature(data, sig_b64, public_pem):
    """True／False；公鑰或簽章格式壞掉 ⇒ False（不丟例外、不當成通過）。"""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        key = serialization.load_pem_public_key(public_pem)
        if not isinstance(key, Ed25519PublicKey):
            return False
        key.verify(base64.b64decode(sig_b64, validate=True), data)
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def keygen(private_out):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    if os.path.exists(private_out):
        raise DeliveryError("私鑰檔已存在，不覆蓋：%s" % private_out)
    key = Ed25519PrivateKey.generate()
    priv = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    pub = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    fd = os.open(private_out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(priv)
    return pub


# ── 腳本版本（AH-O7）──────────────────────────────────────────────────────────

def ps1_digest(raw):
    """與 tests/platform/test_apply_plan：去 BOM、CRLF→LF 後的 sha256。"""
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    return hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()


def script_version(payload):
    """⇒ (版本或 None, 問題清單)。apply_update.ps1 的 $ApplyScriptVersion、apply_update.version.json 的 version 與內容雜湊三者一致才回版本。"""
    ps1 = os.path.join(payload, *_PS1.split("/"))
    reg = os.path.join(payload, *_PS1_REG.split("/"))
    if not os.path.isfile(ps1) or not os.path.isfile(reg):
        return None, ["包裡沒有 %s 或 %s（本分支之前建的包不走雲端交付）" % (_PS1, _PS1_REG)]
    raw = open(ps1, "rb").read()
    m = _PS1_VER_RE.search(raw.decode("utf-8-sig", "replace"))
    try:
        r = json.load(open(reg, encoding="utf-8-sig"))
    except ValueError:
        return None, ["%s 不是合法的 JSON" % _PS1_REG]
    problems = []
    if not m:
        problems.append("apply_update.ps1 沒有 $ApplyScriptVersion")
    elif m.group(1) != r.get("version"):
        problems.append("apply_update.ps1 的版本 %s 與 %s 登記的 %s 不同" % (m.group(1), _PS1_REG, r.get("version")))
    if ps1_digest(raw) != r.get("sha256"):
        problems.append("apply_update.ps1 的內容雜湊與 %s 登記的不同（改了腳本沒有做升版決定）" % _PS1_REG)
    return (m.group(1) if m and not problems else None), problems


# ── 開發機：發布 ──────────────────────────────────────────────────────────────

def _require_root(root):
    if not os.path.isdir(root):
        raise DeliveryError("交付資料夾不存在：%s（由使用者自建，程式不自動建）" % root)


def package_name(pkg, now=None):
    m = json.load(open(os.path.join(pkg, "deploy_manifest.json"), encoding="utf-8-sig"))
    commit, product = str(m.get("commit") or ""), str(m.get("product") or "")
    if not re.match(r"^[0-9a-f]{8,40}$", commit) or not re.match(r"^[a-z0-9_-]+$", product):
        raise DeliveryError("deploy_manifest.json 的 commit／product 不合格：%r／%r" % (commit, product))
    return "%s_%s_%s" % ((now or datetime.now()).strftime("%Y%m%d_%H%M%S"), commit[:8], product), m


def publish(pkg, root, private_pem, keep=KEEP_DEFAULT, now=None):
    """發布一份完整包 ⇒ 包名。步驟：複製到 incoming\\<包>.partial\\payload → 寫 delivery.json、清單、簽章 → 改名成 packages\\<包>。"""
    _require_root(root)
    name, manifest = package_name(pkg, now)
    final = os.path.join(root, "packages", name)
    if os.path.exists(final):
        raise DeliveryError("已經發布過同名的包：%s" % final)
    partial = os.path.join(root, "incoming", name + ".partial")
    if os.path.exists(partial):
        shutil.rmtree(partial)                       # 上一次發布到一半留下的（只刪自己的 .partial）
    shutil.copytree(pkg, os.path.join(partial, PAYLOAD))
    payload = os.path.join(partial, PAYLOAD)
    ver, problems = script_version(payload)
    if problems:
        shutil.rmtree(partial)
        raise DeliveryError("包的 apply_update 版本不一致，不發布：" + "；".join(problems))
    entries = payload_entries(payload)
    sha_bytes = sha_list_text(entries).encode("utf-8")
    meta = {"format": FORMAT, "name": name, "commit": manifest.get("commit"), "product": manifest.get("product"),
            "built_at": manifest.get("built_at"), "files": len(entries), "bytes": sum(n for _r, _s, n in entries),
            "apply_script_version": ver, "published_at": (now or datetime.now()).isoformat(timespec="seconds")}
    meta_bytes = json.dumps(meta, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")
    with open(os.path.join(partial, SHA_LIST), "wb") as f:
        f.write(sha_bytes)
    with open(os.path.join(partial, META_JSON), "wb") as f:
        f.write(meta_bytes)
    with open(os.path.join(partial, SIG), "w", encoding="ascii") as f:
        f.write(sign(signed_bytes(meta_bytes, sha_bytes), private_pem))
    os.makedirs(os.path.dirname(final), exist_ok=True)
    os.replace(partial, final)                       # 發布＝這一步
    prune(root, keep)
    return name


def prune(root, keep=KEEP_DEFAULT):
    """packages\\ 只留最近 keep 份；更舊的只刪「已有結果檔」的（正式機還沒回報的不刪）。⇒ (刪掉的, 因為沒有結果而保留的)。"""
    pk = os.path.join(root, "packages")
    names = sorted(n for n in (os.listdir(pk) if os.path.isdir(pk) else []) if NAME_RE.match(n))
    removed, kept = [], []
    for n in names[:-keep] if keep > 0 else names:
        if os.path.isfile(os.path.join(root, "results", n + ".result.json")):
            shutil.rmtree(os.path.join(pk, n))
            removed.append(n)
        else:
            kept.append(n)
    return removed, kept


# ── 正式機：偵測、staging、驗證 ────────────────────────────────────────────────

def _read_meta(path):
    try:
        with open(path, "rb") as f:
            raw = f.read()
        return raw, json.loads(raw.decode("utf-8"))
    except (OSError, ValueError):
        return None, None


def scan(root):
    """packages\\ 底下名稱合格、有 delivery.json 的 ⇒ [{name, commit, product, built_at, files, bytes}]，新的在前。incoming\\ 不看。"""
    _require_root(root)
    pk = os.path.join(root, "packages")
    out = []
    for n in sorted(os.listdir(pk) if os.path.isdir(pk) else [], reverse=True):
        if not NAME_RE.match(n):
            continue
        _raw, meta = _read_meta(os.path.join(pk, n, META_JSON))
        if not isinstance(meta, dict) or meta.get("name") != n:
            continue
        out.append({k: meta.get(k) for k in ("name", "commit", "product", "built_at", "files", "bytes")})
    return out


def stage(root, name, staging_root):
    """整份複製到 staging_root\\<包名>（安裝目錄外）。複製前後 delivery.json 不同、或檔數對不上 ⇒ 判「同步中」、不留半份。
    ⇒ staging 目錄。"""
    if not NAME_RE.match(name or ""):
        raise DeliveryError("包名不合格：%r" % name)
    src = os.path.join(root, "packages", name)
    before, meta = _read_meta(os.path.join(src, META_JSON))
    if meta is None:
        raise DeliveryError("同步中：還讀不到 delivery.json")
    tmp = os.path.join(staging_root, name + ".tmp")
    dest = os.path.join(staging_root, name)
    if os.path.exists(tmp):
        shutil.rmtree(tmp)
    shutil.copytree(src, tmp)
    after, _m = _read_meta(os.path.join(src, META_JSON))
    staged_meta, _m2 = _read_meta(os.path.join(tmp, META_JSON))
    n_files = sum(len(fns) for _dp, _dns, fns in os.walk(os.path.join(tmp, PAYLOAD)))
    if before != after or before != staged_meta or n_files != meta.get("files"):
        shutil.rmtree(tmp)
        raise DeliveryError("同步中：已到 %d／%s 檔，或 delivery.json 在複製期間改變" % (n_files, meta.get("files")))
    if os.path.exists(dest):
        shutil.rmtree(dest)
    os.replace(tmp, dest)
    return dest


def installed_db_version(install_root):
    """已安裝版本 db.py 的 CURRENT_VERSION（verify_package --expect-db-version 的獨立來源：V9 基準凍結）。"""
    try:
        src = open(os.path.join(install_root, "backend", "db.py"), encoding="utf-8").read()
    except OSError:
        return None
    m = re.search(r"^CURRENT_VERSION\s*=\s*(\d+)", src, re.M)
    return int(m.group(1)) if m else None


def verify_package_cmd(install_root, payload, db_version):
    """用**已安裝版本**的 verify_package.py 檢查 staging 的包（受信任的是正式機上的程式，不是包裡的）。"""
    return [sys.executable, os.path.join(install_root, "backend", "tools", "verify_package.py"), payload,
            "--expect-db-version", str(db_version)]


def _installed_deployed(install_root):
    try:
        return json.load(open(os.path.join(install_root, "backend", ".deployed_commit.json"), encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def verify_staged(staged, install_root, pubkey_pem=None, run_verify_package=True):
    """⇒ {ok, problems, notes, meta}。problems 非空 ⇒ 不可以套用；notes 是要給人看、但不擋的（例：退版要確認）。"""
    problems, notes = [], []
    pub = DELIVERY_PUBKEY_PEM if pubkey_pem is None else pubkey_pem
    meta_bytes, meta = _read_meta(os.path.join(staged, META_JSON))
    try:
        sha_bytes = open(os.path.join(staged, SHA_LIST), "rb").read()
        sig = open(os.path.join(staged, SIG), encoding="ascii").read().strip()
    except OSError as e:
        return {"ok": False, "problems": ["交付檔不完整：%s" % e], "notes": [], "meta": meta}
    if meta is None:
        return {"ok": False, "problems": ["delivery.json 讀不到或不是 JSON"], "notes": [], "meta": None}
    # 1. 簽章
    if not pub:
        problems.append("尚未設定交付公鑰（DELIVERY_PUBKEY_PEM，U-4）：不驗章就不套用")
    elif not verify_signature(signed_bytes(meta_bytes, sha_bytes), sig, pub):
        problems.append("簽章不符：這個包不是由開發機發布的，或 delivery.json／清單被改過")
    # 2. 逐檔雜湊（不多不少）
    payload = os.path.join(staged, PAYLOAD)
    try:
        listed = parse_sha_list(sha_bytes.decode("utf-8"))
    except (DeliveryError, UnicodeDecodeError) as e:
        listed = None
        problems.append(str(e))
    actual = {rel: sha for rel, sha, _n in payload_entries(payload)} if os.path.isdir(payload) else {}
    if listed is not None:
        missing = sorted(set(listed) - set(actual))
        extra = sorted(set(actual) - set(listed))
        bad = sorted(r for r in set(listed) & set(actual) if listed[r] != actual[r])
        for label, items in (("缺檔", missing), ("清單外多出的檔", extra), ("雜湊不符", bad)):
            if items:
                problems.append("%s %d 個：%s" % (label, len(items), "、".join(items[:10])))
        if meta.get("files") != len(listed):
            problems.append("delivery.json 的檔數 %s 與清單 %d 不同" % (meta.get("files"), len(listed)))
    # 3. 腳本版本（AH-O7）
    ver, sv_problems = script_version(payload)
    problems += sv_problems
    if ver is not None and ver != meta.get("apply_script_version"):
        problems.append("delivery.json 記的腳本版本 %s 與包裡的 %s 不同" % (meta.get("apply_script_version"), ver))
    # 4. 版本（重複／退版）
    dep = _installed_deployed(install_root)
    if dep and dep.get("commit") and dep.get("commit") == meta.get("commit"):
        problems.append("已是這一版（commit %s）" % str(meta.get("commit"))[:8])
    elif dep and dep.get("built_at") and meta.get("built_at") and str(meta["built_at"]) < str(dep["built_at"]):
        notes.append("退版：這個包建於 %s，比目前安裝的 %s 舊（套用前要再確認，U-3）" % (meta["built_at"], dep["built_at"]))
    elif not dep:
        notes.append("讀不到目前安裝的部署紀錄（.deployed_commit.json）：無法判斷重複或退版")
    # 5. 結構（verify_package，已安裝版本的那一支）
    if run_verify_package and not problems:
        dbv = installed_db_version(install_root)
        if dbv is None:
            problems.append("讀不到已安裝版本 db.py 的 CURRENT_VERSION：無法執行 verify_package")
        else:
            r = subprocess.run(verify_package_cmd(install_root, payload, dbv), capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=600)
            if r.returncode != 0:
                problems.append("verify_package 不通過（exit %s）：%s" % (r.returncode, (r.stdout + r.stderr)[-600:]))
    return {"ok": not problems, "problems": problems, "notes": notes, "meta": meta}


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors="backslashreplace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keygen"); k.add_argument("--private-out", required=True)
    p = sub.add_parser("publish"); p.add_argument("--pkg", required=True); p.add_argument("--root", required=True)
    p.add_argument("--private-key", required=True); p.add_argument("--keep", type=int, default=KEEP_DEFAULT)
    s = sub.add_parser("scan"); s.add_argument("--root", required=True)
    st = sub.add_parser("stage"); st.add_argument("--root", required=True); st.add_argument("--name", required=True)
    st.add_argument("--staging", required=True)
    v = sub.add_parser("verify"); v.add_argument("--staged", required=True); v.add_argument("--install-root", required=True)
    v.add_argument("--skip-verify-package", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "keygen":
            print(keygen(a.private_out).decode("ascii"))
            print("DELIVERY_KEYGEN_OK（私鑰：%s；公鑰貼進 backend/tools/delivery.py 的 DELIVERY_PUBKEY_PEM）" % a.private_out)
        elif a.cmd == "publish":
            name = publish(a.pkg, a.root, open(a.private_key, "rb").read(), a.keep)
            print("DELIVERY_PUBLISH_OK %s" % name)
        elif a.cmd == "scan":
            print(json.dumps(scan(a.root), ensure_ascii=False, indent=1))
        elif a.cmd == "stage":
            print("DELIVERY_STAGE_OK %s" % stage(a.root, a.name, a.staging))
        else:
            r = verify_staged(a.staged, a.install_root, run_verify_package=not a.skip_verify_package)
            print(json.dumps(r, ensure_ascii=False, indent=1))
            print("DELIVERY_VERIFY_%s" % ("OK" if r["ok"] else "FAIL"))
            return 0 if r["ok"] else 1
        return 0
    except DeliveryError as e:
        print("DELIVERY_REFUSED %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
