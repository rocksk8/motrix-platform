# -*- coding: utf-8 -*-
"""去識別化 S4：sale 包的剪裁與投影（SALE-PACKAGE-DEID.md §2.3）。只用標準庫；建包端（own 包不呼叫）。

  python tools/platform/deid_project.py prune   <包目錄> [--config product/sale_prune.json] [--overlay backend/version_manifest_sale_overlay.json]
  python tools/platform/deid_project.py verify  <包目錄> [--config ...]     # 包裡沒有被剪的路徑、沒有 OWN-ONLY 段、manifest 已投影
  python tools/platform/deid_project.py rebuild --commit <sha> --out <目錄> [--product full] [--repo <repo>]   # 從 git 重算出 sale 包的「內容樹」

做三件事（`git archive`＋`product_select` 之後、掃描之前）：
① 剪檔：`remove` 的 glob 減掉 `keep` 的 glob（不用 export-ignore：own 包仍需要這些檔，而 export-ignore 對兩種對象一體適用）。
② 剪段：`cuts`——原始碼裡以 `# >>> OWN-ONLY:<名>` ／ `# <<< OWN-ONLY:<名>` 圍起來的整段（含標記行），換成設定裡的替身文字。
   標記不是恰好一組 ⇒ 丟 ProjectError（不猜）。own 包不剪，程式碼照舊（標記只是註解）。
③ 客戶版文件：`replace` 用 `product/sale_docs/` 的檔取代 DEPLOY／DR-SOP／HTTPS 清單（來源隨後被剪掉）；`require_text` 是驗證用的標記。
④ 投影 `backend/version_manifest.json`：版本 ≤ `manifest_baseline` 的條目 `content` 換成固定字串（保留 module／version／date／time，
   `_sync_module_versions()` 與登入頁版號要用版本鍵）；之後的條目照原文，但 `version_manifest_sale_overlay.json` 有 `module|version` 就以覆蓋內文取代。
   **repo 裡的 version_manifest 一字不改**（已出貨條目不可改寫），投影只存在包裡。
重算：`rebuild` 由 commit＋設定＋overlay 產出相同的檔案樹，出貨前逐檔驗證「除投影檔外其餘等於 blob、被剪的檔不在、投影檔等於重算結果」。
"""
import argparse
import fnmatch
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DEFAULT_CONFIG = REPO / "product" / "sale_prune.json"
DEFAULT_OVERLAY = REPO / "backend" / "version_manifest_sale_overlay.json"
MANIFEST_REL = "backend/version_manifest.json"
GENERIC_CONTENT = "安裝基準之前的紀錄"
BEGIN_RE = "# >>> OWN-ONLY:%s"
END_RE = "# <<< OWN-ONLY:%s"


class ProjectError(Exception):
    pass


# ── 設定 ─────────────────────────────────────────────────────────────────────────

def load_config(path=DEFAULT_CONFIG):
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    if cfg.get("v") != 1:
        raise ProjectError("sale_prune.json 版本不是 1")
    for k in ("remove", "keep", "forbidden", "cuts", "manifest_baseline"):
        if k not in cfg:
            raise ProjectError("sale_prune.json 缺欄位：%s" % k)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}[a-z]*", str(cfg["manifest_baseline"])):
        raise ProjectError("manifest_baseline 格式不對：%r" % cfg["manifest_baseline"])
    return cfg


def _glob_re(pat):
    """`**` 跨目錄、`*`／`?` 不跨目錄；斜線一律 `/`。"""
    out, i = [], 0
    while i < len(pat):
        if pat.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pat.startswith("**", i):
            out.append(".*")
            i += 2
        elif pat[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pat[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pat[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def matches(rel, patterns):
    return any(_glob_re(p).match(rel) for p in patterns)


def list_files(root):
    root = Path(root)
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def plan_remove(files, cfg):
    return [f for f in files if matches(f, cfg["remove"]) and not matches(f, cfg["keep"])]


# ── 剪段 ─────────────────────────────────────────────────────────────────────────

def cut_text(text, name, stub, rel="?"):
    b, e = BEGIN_RE % name, END_RE % name
    if text.count(b) != 1 or text.count(e) != 1:
        raise ProjectError("%s：OWN-ONLY:%s 標記不是恰好一組（begin=%d end=%d）" % (rel, name, text.count(b), text.count(e)))
    i = text.index(b)
    i = text.rfind("\n", 0, i) + 1                                    # 行首
    j = text.index(e, i)
    j = text.find("\n", j)
    j = len(text) if j < 0 else j + 1
    if not (i < j):
        raise ProjectError("%s：OWN-ONLY:%s 的結束標記在開始標記之前" % (rel, name))
    if not stub.endswith("\n"):
        stub += "\n"
    return text[:i] + stub + text[j:]


def apply_cuts(root, cuts):
    done = []
    for c in cuts:
        p = Path(root) / c["path"]
        if not p.is_file():
            raise ProjectError("剪段的檔不存在：%s" % c["path"])
        raw = p.read_bytes()
        crlf = b"\r\n" in raw
        text = raw.decode("utf-8").replace("\r\n", "\n")
        text = cut_text(text, c["name"], c["stub"], c["path"])
        p.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
        done.append(c["path"] + "#" + c["name"])
    return done


# ── manifest 投影 ─────────────────────────────────────────────────────────────────

def version_sort_key(version):
    """與 helpers.startup.version_sort_key 相同（本工具不 import app；測試比對兩份）。"""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})([a-z]*)$", (version or "").strip())
    return (m.group(1), len(m.group(2)), m.group(2)) if m else ("", 0, "")


def project_entries(entries, baseline, overlay):
    """⇒ 新的 entries（不改輸入）。"""
    out, base = [], version_sort_key(baseline)
    for e in entries:
        e = dict(e)
        if version_sort_key(e.get("version")) <= base:
            e["content"] = GENERIC_CONTENT
        else:
            k = "%s|%s" % (e.get("module"), e.get("version"))
            if k in overlay:
                e["content"] = overlay[k]
        out.append(e)
    return out


def dump_manifest(entries):
    """一行一筆（與 repo 內 version_manifest.json 同格式，方便 diff）。"""
    return "[\n" + ",\n".join("  " + json.dumps(e, ensure_ascii=False) for e in entries) + "\n]\n"


def project_manifest(root, cfg, overlay):
    p = Path(root) / MANIFEST_REL
    entries = json.loads(p.read_text(encoding="utf-8"))
    new = project_entries(entries, cfg["manifest_baseline"], overlay or {})
    p.write_text(dump_manifest(new), encoding="utf-8", newline="\n")
    return sum(1 for a, b in zip(entries, new) if a != b)


def load_overlay(path=DEFAULT_OVERLAY):
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


# ── 主流程 ────────────────────────────────────────────────────────────────────────

def apply_replacements(root, replace):
    """`replace`：{包內路徑: 包內來源路徑}。用客戶版文件覆蓋原檔（來源本身之後由 remove 清掉）。來源不存在 ⇒ 丟例外（不猜）。"""
    done = []
    for dst, src in sorted((replace or {}).items()):
        sp, dp = Path(root) / src, Path(root) / dst
        if not sp.is_file():
            raise ProjectError("客戶版文件來源不存在：%s（要取代 %s）" % (src, dst))
        dp.parent.mkdir(parents=True, exist_ok=True)
        dp.write_bytes(sp.read_bytes())
        done.append(dst)
    return done


def prune_tree(root, cfg=None, overlay=None):
    cfg = cfg or load_config()
    root = Path(root)
    replaced = apply_replacements(root, cfg.get("replace"))
    rm = plan_remove(list_files(root), cfg)
    for rel in rm:
        (root / rel).unlink()
    for d in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
        try:
            d.rmdir()                                                    # 只刪空的
        except OSError:
            pass
    cuts = apply_cuts(root, cfg["cuts"])
    changed = project_manifest(root, cfg, overlay if overlay is not None else load_overlay())
    return {"removed": len(rm), "cuts": cuts, "manifest_projected": changed, "replaced": replaced}


def verify_tree(root, cfg=None):
    """⇒ [問題]。sale 包不得有：被剪／禁止的路徑、OWN-ONLY 標記或替身以外的殘留、未投影的 manifest。"""
    cfg = cfg or load_config()
    root = Path(root)
    probs = []
    files = list_files(root)
    for f in files:
        if matches(f, cfg["forbidden"]):
            probs.append("sale 包內不得有：%s" % f)
    for rel, token in sorted((cfg.get("require_text") or {}).items()):
        p = root / rel
        if not p.is_file():
            probs.append("客戶版文件不存在：%s" % rel)
        elif token not in p.read_text(encoding="utf-8"):
            probs.append("%s 不是客戶版（找不到標記 %s）——原檔沒被取代？" % (rel, token))
    for c in cfg["cuts"]:
        p = root / c["path"]
        if not p.is_file():
            probs.append("剪段的檔不存在：%s" % c["path"])
            continue
        t = p.read_text(encoding="utf-8")
        if "OWN-ONLY" in t:
            probs.append("%s 還有 OWN-ONLY 標記（該段沒剪掉）" % c["path"])
        if c["stub"].strip().splitlines()[0] not in t:
            probs.append("%s 找不到替身文字（剪段沒套用？）" % c["path"])
    mp = root / MANIFEST_REL
    if mp.is_file():
        base = version_sort_key(cfg["manifest_baseline"])
        for e in json.loads(mp.read_text(encoding="utf-8")):
            if version_sort_key(e.get("version")) <= base and e.get("content") != GENERIC_CONTENT:
                probs.append("version_manifest 基準前的條目未投影：%s %s" % (e.get("module"), e.get("version")))
                break
    return probs


def rebuild(commit, out, product="full", repo=REPO, cfg=None, overlay=None):
    """git archive ＋ product_select ＋ prune ＋ project ⇒ out。回 prune 報告。"""
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise ProjectError("輸出目錄不是空的：%s" % out)
    out.mkdir(parents=True, exist_ok=True)
    tar = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", commit], capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        t.extractall(out)
    sys.path.insert(0, str(HERE))
    import product_select as PS
    PS.apply(out, PS.load_product(product))
    return prune_tree(out, cfg, overlay)


def tree_digest(root, ignore=()):
    h = {}
    for f in list_files(root):
        if "__pycache__/" not in f and not matches(f, ignore):
            h[f] = hashlib.sha256((Path(root) / f).read_bytes()).hexdigest()
    return h


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("prune", "verify"):
        s = sub.add_parser(name)
        s.add_argument("pkg")
        s.add_argument("--config", default=str(DEFAULT_CONFIG))
        s.add_argument("--overlay", default=str(DEFAULT_OVERLAY))
    r = sub.add_parser("rebuild")
    r.add_argument("--commit", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--product", default="full")
    r.add_argument("--repo", default=str(REPO))
    r.add_argument("--config", default=str(DEFAULT_CONFIG))
    r.add_argument("--overlay", default=str(DEFAULT_OVERLAY))
    a = ap.parse_args(argv)
    try:
        cfg = load_config(a.config)
        if a.cmd == "prune":
            print("DEID_PRUNE_OK", json.dumps(prune_tree(a.pkg, cfg, load_overlay(a.overlay)), ensure_ascii=False))
            return 0
        if a.cmd == "verify":
            probs = verify_tree(a.pkg, cfg)
            for p in probs:
                print("DEID_PRUNE_PROBLEM " + p)
            print("DEID_PRUNE_VERIFY_%s" % ("FAIL" if probs else "OK"))
            return 1 if probs else 0
        rep = rebuild(a.commit, a.out, a.product, a.repo, cfg, load_overlay(a.overlay))
        print("DEID_REBUILD_OK", json.dumps(rep, ensure_ascii=False))
        return 0
    except ProjectError as e:
        print("DEID_PROJECT_ERROR %s" % e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
