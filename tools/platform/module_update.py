"""P7 模組更新包：以單一模組為單位打包、檢查、套用、回滾（CUSTOMIZATION-SPEC §7）。

用法：
  python tools/platform/module_update.py build    --key tender_radar [--out DIR] [--commit HEAD]
  python tools/platform/module_update.py check    --pkg <更新包目錄>
  python tools/platform/module_update.py apply    --root <安裝根目錄> --pkg <更新包目錄> [--allow-downgrade]
  python tools/platform/module_update.py rollback --root <安裝根目錄> --key tender_radar [--backup <時間>]
  python tools/platform/module_update.py list     --root <安裝根目錄>

套用與回滾只動 `backend/modules/<key>/` 與該模組宣告的頁面，不動 L0／L1、其他模組與資料庫；**需重啟服務生效**。
"""
import argparse
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import product_select as PS  # noqa: E402

LOCK_NAME = "module-update.lock.json"
BACKUP_DIR = "module_backups"
_EXCLUDE_PARTS = ("tests", "__pycache__")
_EXCLUDE_NAMES = ("SPEC.md",)


class UpdateError(Exception):
    pass


# ── 小工具 ────────────────────────────────────────────────────────────────

def _git(*args, repo=REPO, binary=False):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if r.returncode != 0:
        raise UpdateError("git %s 失敗：%s" % (" ".join(args), r.stderr.decode("utf-8", "replace").strip()))
    return r.stdout if binary else r.stdout.decode("utf-8").strip()


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _rmtree(p):
    def _clear(func, path, _exc):
        os.chmod(path, stat.S_IWRITE)
        func(path)
    shutil.rmtree(str(p), onerror=_clear)


def _ver(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v or "0")))


def _core_version(backend):
    return PS.core_version(backend)


def _core_ok(spec, core_version):
    """模組的 core 範圍（">=1.0,<2.0"）對安裝目錄的 CORE_VERSION 是否成立；看不懂 ⇒ 不成立。"""
    sys.path.insert(0, str(REPO / "backend"))
    from core.loader import core_compatible
    try:
        return core_compatible(spec, core_version)
    except ValueError:
        return False


def _page_paths(manifest):
    return ["frontend/pages/%s" % p["path"] for p in manifest.get("pages", [])]


def _tree_hashes(root, key):
    """安裝目錄（或更新包）裡這個模組的檔案 ⇒ {相對路徑: sha256}。"""
    out = {}
    mdir = Path(root) / "backend" / "modules" / key
    if mdir.is_dir():
        for f in sorted(mdir.rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts:
                out[f.relative_to(root).as_posix()] = _sha(f)
    manifest_p = mdir / "module.json"
    if manifest_p.is_file():
        for rel in _page_paths(json.loads(manifest_p.read_text(encoding="utf-8"))):
            if (Path(root) / rel).is_file():
                out[rel] = _sha(Path(root) / rel)
    return out


# ── build ────────────────────────────────────────────────────────────────

def build(key, out_dir, commit="HEAD", repo=REPO):
    """從 git（已 commit 的內容）取出單一模組 ⇒ 更新包目錄。"""
    commit = _git("rev-parse", commit, repo=repo)
    mod_rel = "backend/modules/%s" % key
    manifest = json.loads(_git("show", "%s:%s/module.json" % (commit, mod_rel), repo=repo))
    pages = _page_paths(manifest)
    tar_bytes = _git("archive", "--format=tar", commit, mod_rel, *pages, repo=repo, binary=True)
    pkg = Path(out_dir) / ("%s_%s_%s_%s" % (time.strftime("%Y%m%d_%H%M%S"), key, manifest.get("version"), commit[:8]))
    pkg.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as t:
        members = [m for m in t.getmembers()
                   if not any(x in Path(m.name).parts for x in _EXCLUDE_PARTS) and Path(m.name).name not in _EXCLUDE_NAMES]
        t.extractall(pkg, members=members)
    missing = [p for p in pages if not (pkg / p).is_file()]
    if missing:
        _rmtree(pkg)
        raise UpdateError("module.json 宣告的頁面在 %s 裡找不到：%s" % (commit[:8], missing))
    lock = {
        "lock_version": PS.LOCK_VERSION, "kind": "module_update", "product": "update-%s" % key,
        "built_from": commit, "core_version": _core_version_at(commit, repo),
        "modules": {key: PS.module_entry(pkg / mod_rel)},
        "pages": {p: _sha(pkg / p) for p in pages},
    }
    (pkg / LOCK_NAME).write_text(json.dumps(lock, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return pkg


def _core_version_at(commit, repo):
    try:
        src = _git("show", "%s:backend/core/registry.py" % commit, repo=repo)
    except UpdateError:
        return None
    m = re.search(r'^CORE_VERSION\s*=\s*"([^"]+)"', src, re.M)
    return m.group(1) if m else None


# ── check ────────────────────────────────────────────────────────────────

def load_pkg(pkg):
    lp = Path(pkg) / LOCK_NAME
    if not lp.is_file():
        raise UpdateError("不是模組更新包：缺 %s" % LOCK_NAME)
    lock = json.loads(lp.read_text(encoding="utf-8"))
    if lock.get("lock_version") != PS.LOCK_VERSION or lock.get("kind") != "module_update":
        raise UpdateError("看不懂的 lock（lock_version=%r、kind=%r）⇒ 不猜" % (lock.get("lock_version"), lock.get("kind")))
    if len(lock.get("modules") or {}) != 1:
        raise UpdateError("模組更新包一次只能帶一個模組：%s" % sorted(lock.get("modules") or {}))
    return lock


def check(pkg):
    """更新包自身 ⇒ 問題清單。"""
    try:
        lock = load_pkg(pkg)
    except UpdateError as e:
        return [str(e)]
    (key, entry), = lock["modules"].items()
    problems = []
    mdir = Path(pkg) / "backend" / "modules" / key
    if not (mdir / "module.json").is_file():
        return ["包裡沒有 backend/modules/%s/module.json" % key]
    cur = PS.module_entry(mdir)
    if cur["version"] != entry.get("version") or cur["sha256"] != entry.get("sha256"):
        problems.append("模組 %s 的版本或內容雜湊與 lock 不符（打包後被改過）" % key)
    for rel, h in (lock.get("pages") or {}).items():
        if not (Path(pkg) / rel).is_file() or _sha(Path(pkg) / rel) != h:
            problems.append("頁面 %s 不存在或雜湊不符" % rel)
    return problems


# ── apply／rollback ──────────────────────────────────────────────────────

def preflight(root, pkg, allow_downgrade=False):
    """套用前檢查；回傳 (key, lock, installed_version)。任何一項不過 ⇒ UpdateError（什麼都還沒動）。"""
    problems = check(pkg)
    if problems:
        raise UpdateError("更新包檢查不過：" + "；".join(problems))
    lock = load_pkg(pkg)
    (key, entry), = lock["modules"].items()
    backend = Path(root) / "backend"
    inst_lock_p = backend / PS.LOCK_NAME
    if not inst_lock_p.is_file():
        raise UpdateError("安裝目錄沒有 backend/%s ⇒ 不是經過產品選配的安裝，不套用" % PS.LOCK_NAME)
    inst_core = _core_version(backend)
    if not _core_ok(entry.get("core"), inst_core):
        raise UpdateError("模組 %s 要求 core %s，安裝目錄是 %s ⇒ 不相容" % (key, entry.get("core"), inst_core))
    if (Path(pkg) / "backend" / "modules" / key / "migrations").is_dir():
        raise UpdateError("模組 %s 帶 migrations/：模組自有 migration 尚未實作（P7b）⇒ 不套用" % key)
    installed = json.loads(inst_lock_p.read_text(encoding="utf-8")).get("modules", {}).get(key)
    inst_ver = installed.get("version") if isinstance(installed, dict) else installed
    if inst_ver is not None and _ver(entry["version"]) <= _ver(inst_ver) and not allow_downgrade:
        raise UpdateError("模組 %s：更新包 %s 不高於已安裝 %s ⇒ 拒絕（降版或重裝請加 --allow-downgrade）"
                          % (key, entry["version"], inst_ver))
    return key, lock, inst_ver


def apply(root, pkg, allow_downgrade=False):
    key, lock, inst_ver = preflight(root, pkg, allow_downgrade)
    root = Path(root)
    backend = root / "backend"
    from datetime import datetime
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")   # 含微秒：同一秒內連續套用不可撞名
    bdir = root / BACKUP_DIR / key / stamp
    bdir.mkdir(parents=True)
    before = _tree_hashes(root, key)
    for rel in before:
        dst = bdir / "files" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / rel, dst)
    inst_lock_p = backend / PS.LOCK_NAME
    inst_lock = json.loads(inst_lock_p.read_text(encoding="utf-8"))
    record = {"key": key, "from_version": inst_ver, "to_version": lock["modules"][key]["version"],
              "built_from": lock.get("built_from"), "files_before": before,
              "lock_entry_before": (inst_lock.get("modules") or {}).get(key),
              "excluded_before": list(inst_lock.get("excluded", [])), "applied_at": stamp}
    # 替換：先刪舊模組與舊頁面，再放新的
    old_mdir = backend / "modules" / key
    if old_mdir.exists():
        _rmtree(old_mdir)
    for rel in before:
        if rel.startswith("frontend/") and (root / rel).is_file():
            (root / rel).unlink()
    shutil.copytree(Path(pkg) / "backend" / "modules" / key, old_mdir)
    for rel in lock.get("pages") or {}:
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(pkg) / rel, dst)
    inst_lock.setdefault("modules", {})[key] = lock["modules"][key]
    inst_lock["excluded"] = [k for k in inst_lock.get("excluded", []) if k != key]
    inst_lock_p.write_text(json.dumps(inst_lock, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    record["files_after"] = _tree_hashes(root, key)
    (bdir / "apply.json").write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return record, bdir


def backups(root, key):
    d = Path(root) / BACKUP_DIR / key
    return sorted(p.name for p in d.iterdir() if (p / "apply.json").is_file()) if d.is_dir() else []


def rollback(root, key, stamp=None):
    root = Path(root)
    avail = backups(root, key)
    if not avail:
        raise UpdateError("模組 %s 沒有任何套用備份 ⇒ 無從回滾" % key)
    stamp = stamp or avail[-1]
    if stamp not in avail:
        raise UpdateError("找不到備份 %s（有：%s）" % (stamp, avail))
    bdir = root / BACKUP_DIR / key / stamp
    rec = json.loads((bdir / "apply.json").read_text(encoding="utf-8"))
    backend = root / "backend"
    mdir = backend / "modules" / key
    # 移除套用後的檔（模組資料夾＋套用後宣告的頁面），再還原備份
    for rel in rec.get("files_after", {}):
        if rel.startswith("frontend/") and (root / rel).is_file():
            (root / rel).unlink()
    if mdir.exists():
        _rmtree(mdir)
    for rel, h in rec["files_before"].items():
        src = bdir / "files" / rel
        if _sha(src) != h:
            raise UpdateError("備份檔 %s 的雜湊與紀錄不符 ⇒ 備份已損壞，停止回滾" % rel)
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    inst_lock_p = backend / PS.LOCK_NAME
    inst_lock = json.loads(inst_lock_p.read_text(encoding="utf-8"))
    if rec.get("lock_entry_before") is None:
        inst_lock.get("modules", {}).pop(key, None)
    else:
        inst_lock.setdefault("modules", {})[key] = rec["lock_entry_before"]
    if "excluded_before" in rec:
        inst_lock["excluded"] = rec["excluded_before"]
    inst_lock_p.write_text(json.dumps(inst_lock, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    after = _tree_hashes(root, key)
    if after != rec["files_before"]:
        diff = sorted(set(after.items()) ^ set(rec["files_before"].items()))
        raise UpdateError("回滾後雜湊與套用前不一致：%s" % diff[:5])
    (bdir / "rollback.json").write_text(json.dumps({"rolled_back_at": time.strftime("%Y%m%d_%H%M%S")}) + "\n",
                                        encoding="utf-8")
    return rec, stamp


# ── CLI ──────────────────────────────────────────────────────────────────

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--key", required=True)
    b.add_argument("--out", default=str(REPO / "deploy_packages" / "module_updates"))
    b.add_argument("--commit", default="HEAD")
    c = sub.add_parser("check")
    c.add_argument("--pkg", required=True)
    a = sub.add_parser("apply")
    a.add_argument("--root", required=True)
    a.add_argument("--pkg", required=True)
    a.add_argument("--allow-downgrade", action="store_true")
    r = sub.add_parser("rollback")
    r.add_argument("--root", required=True)
    r.add_argument("--key", required=True)
    r.add_argument("--backup")
    lst = sub.add_parser("list")
    lst.add_argument("--root", required=True)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "build":
            if _git("status", "--porcelain", "--", "backend/modules/%s" % args.key):
                raise UpdateError("backend/modules/%s 有未 commit 的改動 ⇒ 先 commit（只打包已 commit 的內容）" % args.key)
            pkg = build(args.key, args.out, args.commit)
            print("✓ 模組更新包：%s" % pkg)
        elif args.cmd == "check":
            problems = check(args.pkg)
            if problems:
                print("✗ " + "\n✗ ".join(problems))
                return 1
            print("✓ 更新包一致")
        elif args.cmd == "apply":
            rec, bdir = apply(args.root, args.pkg, args.allow_downgrade)
            print("✓ 已套用 %s：%s → %s（備份 %s）。⚠ 需重啟服務才生效。"
                  % (rec["key"], rec["from_version"] or "（原本沒有）", rec["to_version"], bdir))
        elif args.cmd == "rollback":
            rec, stamp = rollback(args.root, args.key, args.backup)
            print("✓ 已回滾 %s 至套用前（備份 %s，雜湊逐一相等）。⚠ 需重啟服務才生效。" % (rec["key"], stamp))
        else:
            lock = json.loads((Path(args.root) / "backend" / PS.LOCK_NAME).read_text(encoding="utf-8"))
            for k, e in sorted((lock.get("modules") or {}).items()):
                print("%-20s %-10s 備份：%s" % (k, e.get("version") if isinstance(e, dict) else e,
                                              "、".join(backups(args.root, k)) or "無"))
    except UpdateError as e:
        print("✗ %s" % e)
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
