# -*- coding: utf-8 -*-
"""更新交付：開發機把完整包發布到 <交付資料夾>；正式機偵測、複製到 staging、驗證（UPDATE-DELIVERY.md §2、§3）。

[單位] tool:delivery    [層] 部署工具（開發機與正式機各跑**自己安裝的**這一份）
[公開介面] keygen, publish, scan, stage, verify_staged, sign, verify_signature, signed_bytes,
           apply_staged, find_result, latest_result, write_back, read_results, latest_prod_commit,
           package_kind, module_package_meta, module_script_version, module_preflight_cmd, module_overlays（B55 單模組包）
[不變式] 發布以「整個目錄改名」收尾（incoming\\<包>.partial → packages\\<包>）；正式機只看 packages\\。
         驗證用**正式機已安裝版本**內建的公鑰（`DELIVERY_PUBKEY_PEM`），不用包自己帶的——新包不能替自己背書。
         簽章涵蓋 delivery.json＋package.sha256（`signed_bytes`）⇒ 改任何一個都驗不過。
         staging 逐檔雜湊與清單完全相同（不多不少）才算通過。任何一項判不出來 ⇒ 不通過（不猜）。
[契約題] tests/platform/test_delivery_2026_09_28.py
[注意] staging 放在安裝目錄**外**（呼叫端給路徑）。一鍵套用（apply_staged）只做三件事：看鎖、把包裡的 backend\\tools
       複製進安裝目錄（AH-M2）、呼叫 apply_update.ps1；結果一律讀它寫的 result.json（UPDATE-DELIVERY §9.2），
       判定重用 deploy_dashboard.decide_outcome／parse_result_line（由儀表板傳入 judge；本檔不 import 儀表板，HC1c）。
       <交付資料夾> 由使用者自建（U-1＝我的雲端硬碟\\MOTRIX-交付），程式**不自動建**：根目錄不存在 ⇒ 拒絕。

交付資料夾結構：
  <交付資料夾>\\incoming\\<包名>.partial\\   發布中（正式機不看）
  <交付資料夾>\\packages\\<包名>\\           已發布：payload\\（完整包）＋delivery.json＋package.sha256＋package.sha256.sig
  <交付資料夾>\\results\\<包名>.result.json  正式機寫回的結果（write_back；只帶結果欄位，不帶 log）

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
# 2026-09-28 使用者授權主持產生（私鑰只在開發機 D:\MOTRIX-KEYS\delivery，另有本機備份；不上雲）。換金鑰＝換這個常數並隨版本出貨。
DELIVERY_PUBKEY_PEM = (
    b"-----BEGIN PUBLIC KEY-----\n"
    b"MCowBQYDK2VwAyEAmq8vwzNR4dJwhycE4bPdw/ecx4tpspqXPAKWO81QUho=\n"
    b"-----END PUBLIC KEY-----\n"
)

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

#: 包型別（B55，設計 docs/platform/MODULE-UPDATE-DELIVERY.md §1.1／§1.2）。delivery.json 的 kind 在簽章範圍內。
#: kind 缺席 ⇒ full（本欄位之前發布的包）；不認得 ⇒ 拒絕。
KIND_FULL, KIND_MODULE = "full", "module"
KINDS = (KIND_FULL, KIND_MODULE)
MODULE_LOCK = "module-update.lock.json"               # tools/platform/module_update.LOCK_NAME
_MOD_PS1 = "backend/tools/apply_module_update.ps1"
_MOD_PS1_REG = "backend/tools/apply_module_update.version.json"
_MOD_TOOL = "tools/platform/module_update.py"        # 正式機用**已安裝**的這一份做 preflight


def package_kind(meta):
    kind = (meta or {}).get("kind") or KIND_FULL
    if kind not in KINDS:
        raise DeliveryError("看不懂的包型別 kind=%r（認得：%s）⇒ 不猜" % (kind, "／".join(KINDS)))
    return kind


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


_TOOL_VER_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})([a-z]?)$")


def tool_version_key(v):
    """套用工具版本（同 $ApplyScriptVersion 的格式：YYYY-MM-DD 加一個小寫字母，例 2026-09-28g）⇒ 可比較的 tuple；
    格式不對 ⇒ None（稽核 D S4-S1：不用字串比——'2026-09-28' 與 '2026-09-28a'、'2026-9-3' 之類會比錯）。"""
    m = _TOOL_VER_RE.match(str(v or ""))
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)) if m else None


def module_script_version(tools_dir):
    """apply_module_update.version.json 的 version（套用工具的版本）；讀不到 ⇒ None。tools_dir＝某一份安裝的 backend/tools。"""
    try:
        return json.load(open(os.path.join(tools_dir, os.path.basename(_MOD_PS1_REG)), encoding="utf-8-sig")).get("version")
    except (OSError, ValueError):
        return None


def module_package_meta(pkg, tools_dir=None):
    """單模組包（module_update.ship 產生）⇒ (包名尾段, delivery.json 的模組欄位)。不是用 ship 出貨的（沒有正式機基準、
    沒跑第②級題）⇒ 拒絕發布。"""
    try:
        lock = json.load(open(os.path.join(pkg, MODULE_LOCK), encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise DeliveryError("讀不到 %s：%s" % (MODULE_LOCK, e))
    mods = lock.get("modules") or {}
    if lock.get("kind") != "module_update" or len(mods) != 1:
        raise DeliveryError("%s 不是單一模組更新包的 lock" % MODULE_LOCK)
    (key, entry), = mods.items()
    if not re.match(r"^[a-z0-9_]+$", key):
        raise DeliveryError("模組代號不合格：%r" % key)
    if not lock.get("prod_base_commit") or lock.get("tier") != "module":
        raise DeliveryError("這個包沒有正式機基準 commit 或不是第②級出貨（請用 module_update.py build --prod-base 出貨）")
    tests = lock.get("tests") or {}
    if not tests.get("passed") or tests.get("failed") or tests.get("errors") or "skipped" in tests:
        raise DeliveryError("這個包沒有第②級測試全綠的紀錄 ⇒ 不發布")
    ver = module_script_version(tools_dir or os.path.dirname(os.path.abspath(__file__)))
    if not ver:
        raise DeliveryError("開發機沒有 %s ⇒ 算不出正式機需要的套用工具版本，不發布" % _MOD_PS1_REG)
    return "mod-%s" % key.replace("_", "-"), {
        "commit": lock.get("built_from"), "product": "mod-" + key.replace("_", "-"),
        "module": {"key": key, "version": entry.get("version"), "core": entry.get("core"),
                   "built_from": lock.get("built_from"), "prod_base_commit": lock.get("prod_base_commit"),
                   "tests": {k: tests.get(k) for k in ("passed", "seconds", "line")},
                   "provider": lock.get("provider")},
        "min_apply_module_script": ver}


def publish(pkg, root, private_pem, keep=KEEP_DEFAULT, now=None, tools_dir=None):
    """發布一份包（完整包或單模組包）⇒ 包名。步驟：複製到 incoming\\<包>.partial\\payload → 寫 delivery.json、清單、簽章 → 改名成 packages\\<包>。
    包裡有 module-update.lock.json ⇒ kind＝module（只含該模組與宣告頁面；不帶 tools，不要求 apply_update.ps1）。"""
    _require_root(root)
    if os.path.isfile(os.path.join(pkg, MODULE_LOCK)):
        return _publish_module(pkg, root, private_pem, keep, now, tools_dir)
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
    meta = {"format": FORMAT, "name": name, "kind": KIND_FULL, "commit": manifest.get("commit"),
            "product": manifest.get("product"),
            "built_at": manifest.get("built_at"), "files": len(entries), "bytes": sum(n for _r, _s, n in entries),
            "apply_script_version": ver, "published_at": (now or datetime.now()).isoformat(timespec="seconds")}
    return _finish_publish(root, name, partial, final, meta, entries, private_pem, keep)


def _publish_module(pkg, root, private_pem, keep, now, tools_dir):
    tail, mod = module_package_meta(pkg, tools_dir)
    commit = str(mod["commit"] or "")
    if not re.match(r"^[0-9a-f]{8,40}$", commit):
        raise DeliveryError("模組包的 built_from 不合格：%r" % commit)
    name = "%s_%s_%s" % ((now or datetime.now()).strftime("%Y%m%d_%H%M%S"), commit[:8], tail)
    final = os.path.join(root, "packages", name)
    if os.path.exists(final):
        raise DeliveryError("已經發布過同名的包：%s" % final)
    partial = os.path.join(root, "incoming", name + ".partial")
    if os.path.exists(partial):
        shutil.rmtree(partial)
    shutil.copytree(pkg, os.path.join(partial, PAYLOAD))
    entries = payload_entries(os.path.join(partial, PAYLOAD))
    meta = {"format": FORMAT, "name": name, "kind": KIND_MODULE, "commit": commit, "product": mod["product"],
            "built_at": (now or datetime.now()).isoformat(timespec="seconds"),
            "files": len(entries), "bytes": sum(n for _r, _s, n in entries), "module": mod["module"],
            "min_apply_module_script": mod["min_apply_module_script"],
            "published_at": (now or datetime.now()).isoformat(timespec="seconds")}
    return _finish_publish(root, name, partial, final, meta, entries, private_pem, keep)


def _finish_publish(root, name, partial, final, meta, entries, private_pem, keep):
    sha_bytes = sha_list_text(entries).encode("utf-8")
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
        row = {k: meta.get(k) for k in ("name", "commit", "product", "built_at", "files", "bytes")}
        row["kind"] = meta.get("kind") or KIND_FULL
        if row["kind"] == KIND_MODULE:
            row["module"] = {k: (meta.get("module") or {}).get(k) for k in ("key", "version", "prod_base_commit")}
        out.append(row)
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


def module_preflight_cmd(install_root, payload):
    """用**已安裝版本**的 module_update.py 做單模組包的套用前檢查（只讀）。"""
    return [sys.executable, os.path.join(install_root, *_MOD_TOOL.split("/")), "preflight", "--root", install_root,
            "--pkg", payload, "--require-base", "--json"]


def _run_cmd(cmd, timeout=600):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return r.returncode, r.stdout + r.stderr


def _verify_module(meta, payload, install_root, notes, runner=None):
    """kind＝module 的驗證（簽章與逐檔雜湊已由呼叫端做完）⇒ 問題清單。設計 §1.2。"""
    problems = []
    mod = meta.get("module") or {}
    if not mod.get("key") or not mod.get("prod_base_commit"):
        return ["delivery.json 缺模組代號或正式機基準 commit"]
    need = meta.get("min_apply_module_script")
    have = module_script_version(os.path.join(install_root, "backend", "tools"))
    if not have:
        problems.append("正式機沒有單模組套用工具（%s）⇒ 請先套用帶新工具的完整包" % _MOD_PS1_REG)
    elif tool_version_key(have) is None or tool_version_key(need) is None:
        problems.append("套用工具版本格式不認得（正式機 %r、包需要 %r；格式 YYYY-MM-DD[a-z]）⇒ 不猜" % (have, need))
    elif tool_version_key(have) < tool_version_key(need):
        problems.append("正式機的單模組套用工具 %s 比這個包需要的 %s 舊 ⇒ 請先套用完整包" % (have, need))
    if not os.path.isfile(os.path.join(install_root, *_MOD_TOOL.split("/"))):
        problems.append("正式機沒有 %s ⇒ 請先套用完整包" % _MOD_TOOL)
    dep = _installed_deployed(install_root)
    if not dep or not dep.get("commit"):
        problems.append("讀不到目前安裝的部署紀錄（.deployed_commit.json）⇒ 判不了這個包是不是對這一版做的")
    elif dep.get("commit") != mod.get("prod_base_commit"):
        problems.append("這個包是對正式機 %s 做的，而目前安裝的是 %s ⇒ 不套用（請以目前版本重新出貨或改用完整包）"
                        % (str(mod.get("prod_base_commit"))[:8], str(dep.get("commit"))[:8]))
    if problems:
        return problems
    rc, out = (runner or _run_cmd)(module_preflight_cmd(install_root, payload))
    line = next((l for l in reversed(out.splitlines()) if l.startswith("MODULE_UPDATE_RESULT ")), None)
    try:
        res = json.loads(line.split(" ", 1)[1]) if line else None
    except ValueError:
        res = None
    if res is None:
        return ["單模組套用前檢查沒有結果行（exit %s）：%s" % (rc, out[-400:])]
    if not res.get("ok") or rc != 0:
        return ["單模組套用前檢查不通過：%s" % res.get("error")]
    notes.append("單模組更新：%s %s → %s%s" % (res.get("key"), res.get("from_version") or "（原本沒有）",
                                              res.get("to_version"), "（帶 migration，套用時先乾跑）" if res.get("has_migrations") else ""))
    return []


def verify_staged(staged, install_root, pubkey_pem=None, run_verify_package=True, module_runner=None):
    """⇒ {ok, problems, notes, meta, kind}。problems 非空 ⇒ 不可以套用；notes 是要給人看、但不擋的（例：退版要確認）。
    kind＝module：不驗 apply_update 腳本版本與 verify_package（不適用），改驗正式機的單模組套用工具版本、基準 commit、
    與已安裝 module_update.py 的 preflight（module_runner：題目注入點）。"""
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
    try:
        kind = package_kind(meta)
    except DeliveryError as e:
        return {"ok": False, "problems": problems + [str(e)], "notes": notes, "meta": meta, "kind": None}
    if kind == KIND_MODULE:
        if not problems:                               # 簽章或雜湊不過就不往下跑（不在不信任的包上執行 preflight）
            problems += _verify_module(meta, payload, install_root, notes, module_runner)
        return {"ok": not problems, "problems": problems, "notes": notes, "meta": meta, "kind": kind}
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
    return {"ok": not problems, "problems": problems, "notes": notes, "meta": meta, "kind": kind}


# ── 正式機：一鍵套用 (c) ──────────────────────────────────────────────────────

LOCK_REL = os.path.join("backend", ".apply.lock")
#: result.json 與 ::RESULT:: 同源的欄位：(result.json 的鍵, deploy_dashboard.parse_result_line 的鍵)
RESULT_CORE = (("status", "status"), ("rolled_back", "rolledBack"), ("service", "service"), ("exit", "exit"))
#: 寫回雲端的欄位（白名單：不帶 package 路徑以外的本機資訊、不帶 log）
WRITE_BACK_FIELDS = ("protocol", "status", "rolled_back", "service", "exit", "script", "script_version", "timestamp",
                     "commit", "started_at", "finished_at",
                     # B55 單模組包（apply_module_update.ps1 的 result.json 才有；完整包 ⇒ None）
                     "kind", "module_key", "from_version", "to_version", "prod_base_commit")


def read_lock(install_root):
    """鎖檔內容（dict）；沒有鎖 ⇒ None；有鎖但讀不懂 ⇒ {"unreadable": True}。只讀，**不刪**（殘留鎖由人確認後刪）。"""
    p = os.path.join(install_root, LOCK_REL)
    if not os.path.exists(p):
        return None
    try:
        return json.load(open(p, encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {"unreadable": True}


def apply_cmd(install_root, payload, script="apply_update"):
    """script＝apply_update（完整包）或 apply_module_update（單模組包）；一律跑**已安裝**的那一份。"""
    return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            os.path.join(install_root, "backend", "tools", script + ".ps1"), "-PackagePath", payload, "-Yes"]


def _run_powershell(cmd, timeout=None):
    """逾時：完整包 45 分；單模組包 20 分（由腳本名決定，呼叫端不必知道）。逾時不自動中止（沿用原則）——由 subprocess 丟例外。"""
    if timeout is None:
        timeout = 20 * 60 if any(str(c).endswith("apply_module_update.ps1") for c in cmd) else 45 * 60
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return r.returncode, r.stdout + r.stderr


def find_result(install_root, script="apply_update", since=None):
    """logs\\<script>_<yyyyMMdd_HHmmss>.result.json 裡最新的那一份（since：只看這個時間之後寫的；epoch 秒）。⇒ dict 或 None。"""
    logs = os.path.join(install_root, "backend", "logs")
    rx = re.compile(r"^%s_\d{8}_\d{6}\.result\.json$" % re.escape(script))
    best = None
    for n in (os.listdir(logs) if os.path.isdir(logs) else []):
        full = os.path.join(logs, n)
        if not rx.match(n) or (since is not None and os.path.getmtime(full) < since):
            continue
        if best is None or n > best:
            best = n
    if best is None:
        return None
    try:
        return json.load(open(os.path.join(logs, best), encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {"unreadable": best}


def latest_result(install_root, script="apply_update"):
    """儀表板重開後顯示「上一次套用的結果」（§5-6）：-CheckOnly 的結果不算套用、跳過。"""
    logs = os.path.join(install_root, "backend", "logs")
    rx = re.compile(r"^%s_\d{8}_\d{6}\.result\.json$" % re.escape(script))
    for n in sorted((n for n in (os.listdir(logs) if os.path.isdir(logs) else []) if rx.match(n)), reverse=True):
        try:
            r = json.load(open(os.path.join(logs, n), encoding="utf-8-sig"))
        except (OSError, ValueError):
            return {"unreadable": n}
        if not str(r.get("status") or "").startswith("checkonly"):
            return r
    return None


def apply_staged(staged, install_root, verified, judge, run=None, clock=None):
    """一鍵套用。verified＝**剛剛**對同一個 staging 跑的 verify_staged 結果（ok 才准）。
    judge＝(decide_outcome, parse_result_line)：由呼叫端（部署儀表板）傳入它自己的判定函式——判定的唯一來源在儀表板，
    而儀表板不准被別的程式 import（HC1c：它的路由只能掛在有「只限本機」middleware 的那個 app）。
    ⇒ {started, outcome, result, problems, lock}。outcome：succeeded／failed（fail-closed）；沒開始 ⇒ started False。"""
    import time
    clock = clock or time.time
    if not (verified or {}).get("ok"):
        raise DeliveryError("驗證沒有通過，不套用：%s" % "；".join((verified or {}).get("problems") or ["沒有驗證結果"]))
    lock = read_lock(install_root)
    if lock is not None:
        return {"started": False, "outcome": "failed", "result": None, "lock": lock,
                "problems": ["另一個套用或回滾正在執行，或有殘留的鎖檔（不自動清；確認後由人刪除 backend\\.apply.lock）"]}
    payload = os.path.join(staged, PAYLOAD)
    kind = verified.get("kind") or KIND_FULL
    if kind == KIND_MODULE:
        # 單模組包不帶 tools（設計 §0）：跑正式機**已安裝**的 apply_module_update.ps1；不複製任何工具
        script = "apply_module_update"
    else:
        tools_src = os.path.join(payload, "backend", "tools")
        if not os.path.isdir(tools_src):
            raise DeliveryError("包裡沒有 backend\\tools：不能先換上新的套用腳本（AH-M2），不套用")
        shutil.copytree(tools_src, os.path.join(install_root, "backend", "tools"), dirs_exist_ok=True)   # AH-M2
        script = "apply_update"
    started = clock()
    rc, out = (run or _run_powershell)(apply_cmd(install_root, payload, script))
    decide, parse = judge
    res = find_result(install_root, script, since=started - 2)
    problems = []
    outcome = decide(rc, out, "deploy")
    stdout_res = parse(out)
    if res is None or "unreadable" in res:
        problems.append("找不到這一次的結果檔（backend\\logs\\%s_*.result.json）或讀不懂" % script)
        outcome = "failed"
    elif stdout_res is not None:
        mism = [rk for rk, sk in RESULT_CORE if str(res.get(rk)) != str(stdout_res.get(sk))]
        if mism:
            problems.append("結果檔與 ::RESULT:: 不一致：%s" % "、".join(mism))
            outcome = "failed"
    return {"started": True, "outcome": outcome, "result": res, "problems": problems, "lock": None, "returncode": rc}


# ── 結果寫回 (d) ──────────────────────────────────────────────────────────────

def outcome_from_result(res):
    """沒有儀表板時（CLI writeback）的判定：**只有** status＝success 而且 exit＝0 才算成功；其他一律 failed（fail-closed）。
    儀表板在時仍用它自己的 decide_outcome（值域在儀表板，HC1c）；這裡刻意只認一個成功值，不抄儀表板的值域。"""
    if not isinstance(res, dict) or "unreadable" in res:
        return "failed"
    return "succeeded" if res.get("status") == "success" and str(res.get("exit")) == "0" else "failed"


def write_back(root, name, result, outcome, host=None):
    """正式機把結果寫到 <交付資料夾>\\results\\<包名>.result.json（先 .tmp 再改名）。只帶 WRITE_BACK_FIELDS＋name／outcome／host。"""
    _require_root(root)
    if not NAME_RE.match(name or ""):
        raise DeliveryError("包名不合格：%r" % name)
    if outcome not in ("succeeded", "failed"):
        raise DeliveryError("outcome 只能是 succeeded／failed：%r" % outcome)
    rec = {k: (result or {}).get(k) for k in WRITE_BACK_FIELDS}
    rec.update(name=name, outcome=outcome, host=host or os.environ.get("COMPUTERNAME", ""))
    d = os.path.join(root, "results")
    os.makedirs(d, exist_ok=True)
    final = os.path.join(d, name + ".result.json")
    tmp = final + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, final)
    return final


def read_results(root):
    """開發機：{包名: 結果}（讀不懂的略過並列在 "_unreadable"）。"""
    _require_root(root)
    d = os.path.join(root, "results")
    out, bad = {}, []
    for n in sorted(os.listdir(d) if os.path.isdir(d) else []):
        if not n.endswith(".result.json") or not NAME_RE.match(n[:-len(".result.json")]):
            continue
        try:
            out[n[:-len(".result.json")]] = json.load(open(os.path.join(d, n), encoding="utf-8-sig"))
        except (OSError, ValueError):
            bad.append(n)
    if bad:
        out["_unreadable"] = bad
    return out


def latest_prod_commit(root):
    """開發機 /api/prod-status 用：最近一次 outcome=succeeded 的**完整包** {commit, finished_at, name}；沒有 ⇒ None（不猜）。
    單模組包（kind＝module）不算：它不改變正式機的 commit，只是在那個 commit 之上覆蓋一個模組（見 module_overlays）。"""
    best = None
    for name, r in read_results(root).items():
        if name == "_unreadable" or r.get("outcome") != "succeeded" or not r.get("commit"):
            continue
        if (r.get("kind") or KIND_FULL) != KIND_FULL:
            continue
        key = (str(r.get("finished_at") or ""), name)
        if best is None or key > best[0]:
            best = (key, {"commit": r["commit"], "finished_at": r.get("finished_at"), "name": name})
    return best[1] if best else None


def module_overlays(root):
    """開發機：正式機在「最近一次完整包」之上成功套用的單模組包 ⇒ {模組: {version, finished_at, name}}（同一模組取最新）。
    只算 prod_base_commit＝那個完整包 commit 的（換了完整包 ⇒ 舊覆蓋過期，設計 §3）。沒有完整包紀錄 ⇒ {}（不猜）。"""
    base = latest_prod_commit(root)
    if not base:
        return {}
    out = {}
    for name, r in read_results(root).items():
        if name == "_unreadable" or r.get("outcome") != "succeeded" or r.get("kind") != KIND_MODULE:
            continue
        if r.get("prod_base_commit") != base["commit"] or not r.get("module_key"):
            continue
        cur = out.get(r["module_key"])
        if cur is None or str(r.get("finished_at") or "") > str(cur["finished_at"] or ""):
            out[r["module_key"]] = {"version": r.get("to_version"), "finished_at": r.get("finished_at"), "name": name}
    return out


def _default_resolver():
    """這台機器的「更新交付資料夾」設定（系統設定→儲存位置；helpers.storage_locations 是唯一解析處）。
    跑的是**這支檔案所在的那一份安裝**（backend/tools 的上一層）的設定與主庫。"""
    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend not in sys.path:
        sys.path.insert(0, backend)
    try:
        from helpers import storage_locations
    except ImportError:
        raise DeliveryError("這一版沒有「儲存位置」設定（helpers.storage_locations）：請用 --root 指定交付資料夾")
    return storage_locations.path("delivery_root")


def configured_root(resolver=None):
    """交付資料夾：沒有用 --root 指定時讀設定。沒設定 ⇒ 拒絕（不猜、不掃磁碟、不自動建）。"""
    root = (resolver or _default_resolver)()
    if not root:
        raise DeliveryError("尚未設定更新交付資料夾（系統設定→儲存位置），也沒有用 --root 指定")
    return root


def main(argv=None, resolver=None):
    try:
        sys.stdout.reconfigure(errors="backslashreplace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keygen"); k.add_argument("--private-out", required=True)
    #: --root 省略 ⇒ 讀「系統設定→儲存位置」的更新交付資料夾（configured_root）
    p = sub.add_parser("publish"); p.add_argument("--pkg", required=True); p.add_argument("--root")
    p.add_argument("--private-key", required=True); p.add_argument("--keep", type=int, default=KEEP_DEFAULT)
    s = sub.add_parser("scan"); s.add_argument("--root")
    st = sub.add_parser("stage"); st.add_argument("--root"); st.add_argument("--name", required=True)
    st.add_argument("--staging", required=True)
    v = sub.add_parser("verify"); v.add_argument("--staged", required=True); v.add_argument("--install-root", required=True)
    v.add_argument("--skip-verify-package", action="store_true")
    #: B55：正式機沒有本機儀表板（主持裁示）⇒ 正式機 Claude 套用完用這個把結果寫回交付資料夾（開發機 prod-status 讀它）
    w = sub.add_parser("writeback"); w.add_argument("--root"); w.add_argument("--name", required=True)
    w.add_argument("--install-root", required=True)
    w.add_argument("--script", default="apply_module_update", choices=("apply_update", "apply_module_update"))
    w.add_argument("--since", type=float, help="只看這個 epoch 秒之後寫的結果檔（套用開始的時間）")
    a = ap.parse_args(argv)
    try:
        if a.cmd in ("publish", "scan", "stage", "writeback") and not a.root:
            a.root = configured_root(resolver)
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
        elif a.cmd == "writeback":
            res = find_result(a.install_root, a.script, since=a.since)
            outcome = outcome_from_result(res)
            path = write_back(a.root, a.name, res if isinstance(res, dict) and "unreadable" not in res else {}, outcome)
            print("DELIVERY_WRITEBACK_OK %s %s" % (outcome, path))
            return 0 if outcome == "succeeded" else 1
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
