# -*- coding: utf-8 -*-
"""T22-1：正式機步驟檔演練——照步驟檔的 powershell 區塊**逐行實跑**，安裝目錄是**非 git** 的複本。

用法：
  python backend/tools/stepfile_drill.py <步驟檔.md> [--work <工作目錄>] [--steps 1] [--keep]

為什麼有這支（第二十二班兩次被擋下，D §9）：
  ① 演練在 git 工作樹裡跑，正式機安裝目錄不是 git ⇒ 走 git 的檢查在正式機必定 FAIL，演練看不到。
  ② 演練呼叫的是 API／自己拼的路徑，步驟檔寫的是另一套（少了 `payload\\`）⇒ 演練綠、步驟檔紅。
🔑 所以：不自己拼指令，**從步驟檔抽出區塊、代入路徑、原樣執行**；並在執行前先靜態檢查每個路徑
   （`<ROOT>\\..\\motrix-staging\\<包>\\…`）在 stage 出來的目錄裡真的存在。

做什麼（全部在 <工作目錄>\\<時間>\\ 底下，不含 .git）：
  1. inst\\   ＝ `git archive HEAD` 的安裝複本（無 .git；.deployed_commit.json 寫舊版）；delivery.py 的公鑰換成演練金鑰。
  2. 交付\\   ＝ 用演練金鑰把 `git archive HEAD` 的包發布（deploy_manifest.json 由本工具寫）。
  3. 步驟檔的區塊：`<ROOT>`／交付資料夾／包名／包的 sha256 代入後，依序執行「步驟 --steps 指定的那幾節」的 powershell 區塊。
  4. 每個區塊：先靜態檢查路徑，再執行；報告 exit code 與輸出最後幾行。
⚠ 只演練「步驟 1（取包並驗證）」與其靜態路徑檢查；步驟 2 起會停服務、動安裝目錄，不在本工具範圍（--steps 只接受 1）。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import io
import tempfile
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

ROOT_TOKEN = "<ROOT>"
DELIVERY_ROOT_RE = re.compile(r"H:\\我的雲端硬碟\\MOTRIX-交付")
PKG_NAME_RE = re.compile(r"\d{8}_\d{6}_[0-9a-f]{8}_[a-z0-9-]+")
PKG_PLACEHOLDER = "<包名>"
BLOCK_RE = re.compile(r"```powershell\n(.*?)```", re.S)
SECTION_RE = re.compile(r"^## 步驟 (\d+)", re.M)
PATH_RE = re.compile(r"[^\s\"']*motrix-staging[^\s\"']*")


class DrillError(Exception):
    pass


def extract_blocks(md_text, steps=(1,)):
    """⇒ [(步驟號, 區塊文字)]，只取 `## 步驟 N` 節裡的 ```powershell 區塊，依文件順序。"""
    heads = [(m.start(), int(m.group(1))) for m in SECTION_RE.finditer(md_text)]
    out = []
    for i, (pos, n) in enumerate(heads):
        end = heads[i + 1][0] if i + 1 < len(heads) else len(md_text)
        if n in steps:
            out += [(n, b.strip("\n")) for b in BLOCK_RE.findall(md_text[pos:end])]
    return out


def substitute(block, root, delivery_root, pkg_name):
    b = block.replace(ROOT_TOKEN, root)
    b = DELIVERY_ROOT_RE.sub(lambda _m: delivery_root, b)
    return PKG_NAME_RE.sub(pkg_name, b)


def path_problems(command, staged_parent):
    """靜態：命令裡每個含 motrix-staging 的路徑，去掉萬用字元後的**目錄部分**必須存在（抓「少了 payload\\」這類）。
    ⇒ [問題字串]。staging 目錄本身（--staging 參數）與 .log 輸出檔不查。"""
    probs = []
    for tok in PATH_RE.findall(command):
        tok = tok.rstrip(",;")
        if tok.lower().endswith(".log") or "--staging" in tok:
            continue
        p = Path(re.split(r"[*?]", tok)[0])
        if p.name == "" or "*" in tok:
            p = Path(str(p).rstrip("\\/"))
        if not p.exists() and Path(str(staged_parent)) in p.parents:
            probs.append("路徑不存在：%s" % tok)
    return probs


def _git_archive(dest, subdir=None):
    dest.mkdir(parents=True)
    args = ["git", "-C", str(REPO), "archive", "--format=tar", "HEAD"] + ([subdir] if subdir else [])
    r = subprocess.run(args, capture_output=True, check=True)
    tarfile.open(fileobj=io.BytesIO(r.stdout)).extractall(dest)


def build_drill(base, write_ignore_list=True):
    """⇒ dict(inst, pkg_name, delivery_root, staging, sha256)"""
    import delivery as D
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    inst, pkg = base / "inst", base / "pkg"
    _git_archive(inst)
    _git_archive(pkg)
    sys.path.insert(0, str(REPO / "tools" / "platform"))
    import product_select as PS                  # 與 build_deploy_package 相同：選配 full、寫 modules.lock.json
    PS.apply(pkg, PS.load_product("full"))
    if write_ignore_list:      # 與 build_deploy_package.ps1 Step 5.55 相同：建包端讓 git 算好不出貨清單、寫進包
        import export_ignore_list as EI
        (pkg / "backend" / "export_ignore.json").write_text(
            json.dumps(EI.build(str(REPO), "HEAD"), ensure_ascii=False, indent=1), encoding="utf-8")
    (inst / "backend" / ".deployed_commit.json").write_text(json.dumps(
        {"commit": "0" * 40, "commit_short": "00000000", "built_at": "2000-01-01 00:00:00"}), encoding="utf-8")
    (pkg / "deploy_manifest.json").write_text(json.dumps(
        {"commit": head, "product": "full", "built_at": datetime.now().isoformat(timespec="seconds")}), encoding="utf-8")
    k = Ed25519PrivateKey.generate()
    priv = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    pub = k.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")
    # 演練安裝複本的 delivery.py 只換公鑰（正式機那份內建的是真公鑰；演練沒有那把私鑰）
    dp = inst / "backend" / "tools" / "delivery.py"
    src = dp.read_text(encoding="utf-8")
    new, n = re.subn(r"(DELIVERY_PUBKEY_PEM = \()(.*?)(\n\)|\n    \))", lambda m: m.group(1) + repr(pub.encode("ascii")) + m.group(3), src, count=1, flags=re.S)
    if n != 1:
        raise DrillError("找不到 DELIVERY_PUBKEY_PEM 的定義，無法換成演練公鑰")
    dp.write_text(new, encoding="utf-8")
    droot = base / "交付"
    droot.mkdir()
    name = D.publish(str(pkg), str(droot), priv, tools_dir=str(HERE))
    sha = (droot / "packages" / name / "package.sha256")
    import hashlib
    return {"inst": inst, "pkg_name": name, "delivery_root": str(droot), "staging": base / "motrix-staging",
            "sha256": hashlib.sha256(sha.read_bytes()).hexdigest().upper() if sha.exists() else None}


def run_block(command, cwd):
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(cwd), timeout=900)
    return r.returncode, (r.stdout + r.stderr)


def drill(step_file, work, steps=(1,), keep=False, write_ignore_list=True):
    """⇒ 報告 dict：{blocks:[{step,command,static,exit,tail}], ok, base}。"""
    md = Path(step_file).read_text(encoding="utf-8")
    blocks = extract_blocks(md, steps)
    if not blocks:
        raise DrillError("步驟檔裡找不到步驟 %s 的 powershell 區塊" % (steps,))
    base = Path(work) / time.strftime("%Y%m%d_%H%M%S")
    base.mkdir(parents=True)
    report = {"base": str(base), "blocks": [], "ok": True}
    try:
        d = build_drill(base, write_ignore_list)
        # 🔴 演練的前提是「安裝目錄不在任何 git repo 之內」——家目錄本身就是 repo 的機器上，放在 %TEMP% 會讓 git 檢查意外成功，
        #    演練綠、正式機紅（第二十二班的形狀）⇒ 前提不成立就拒絕，不是降級照跑。
        if subprocess.run(["git", "-C", str(d["inst"]), "rev-parse", "--git-dir"], capture_output=True).returncode == 0:
            raise DrillError("演練目錄 %s 在某個 git repo 之內：請用 --work 指到不在 repo 內的位置（例如 D:\開發測試檔\…）" % base)
        d["staging"].mkdir()
        for n, raw in blocks:
            cmd = substitute(raw, str(d["inst"]), d["delivery_root"], d["pkg_name"])
            # 步驟檔的 staging＝<ROOT>\..\motrix-staging ＝ base\motrix-staging（inst 的上一層）
            item = {"step": n, "command": cmd, "static": path_problems(cmd, d["staging"])}
            if item["static"]:
                item["exit"], item["tail"] = None, "（靜態路徑檢查未過，未執行）"
                report["ok"] = False
            else:
                code, out = run_block(cmd, base)
                item["exit"], item["tail"] = code, "\n".join(out.strip().splitlines()[-12:])
                if code != 0:
                    report["ok"] = False
            report["blocks"].append(item)
    finally:
        if not keep:
            shutil.rmtree(base, ignore_errors=True)
    return report


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step_file")
    ap.add_argument("--work", default=os.path.join(tempfile.gettempdir(), "motrix-stepdrill"))
    ap.add_argument("--steps", default="1", help="只接受 1")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args(argv)
    if a.steps != "1":
        print("🔴 --steps 只接受 1（步驟 2 起會停服務、動安裝目錄）")
        return 2
    rep = drill(a.step_file, a.work, (1,), a.keep)
    for it in rep["blocks"]:
        print("=" * 70)
        print(it["command"])
        for p in it["static"]:
            print("  🔴 靜態：%s" % p)
        print("  exit=%s\n%s" % (it["exit"], it["tail"]))
    print("=" * 70)
    print("STEPFILE_DRILL_%s" % ("OK" if rep["ok"] else "FAIL"))
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
