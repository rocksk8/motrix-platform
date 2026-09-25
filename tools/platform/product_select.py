"""9c① 匯出選配：依產品設定檔決定部署包裡有哪些 L2 模組（CORE-SPEC §9c）。

產品設定檔：repo 根目錄 `product/<名稱>.json`
  {"name": "full", "description": "...", "modules": ["*"]}        ← "*"＝包裡現有的全部模組
  {"name": "core-only", "description": "...", "modules": []}      ← 只有 L0／L1
  列出的 key 在包裡找不到 ⇒ 拒絕（不猜、不默默略過）。

用法（build_deploy_package.ps1 在解出快照之後呼叫；也可單獨跑）：
  python tools/platform/product_select.py apply --pkg <部署包目錄> --product full
  python tools/platform/product_select.py check --pkg <部署包目錄>        ← verify_package 用同一套判定

apply：沒選到的 `backend/modules/<key>/` 整個資料夾刪掉，連同它 module.json 宣告的前端頁面
       （`pages[].path`，位於 frontend/pages/）；寫 `backend/modules.lock.json`。
lock 檔結構（lock_version 1；預留 P7「模組更新包」：kind＝module_update 時只含被更新的模組）：
  {"lock_version": 1, "kind": "full_package", "product": "full", "core_version": "1.2",
   "modules": {"<key>": {"version": "1.0.0", "core": ">=1.0,<2.0", "sha256": "<模組資料夾內容雜湊>"}},
   "excluded": [...], "removed_pages": [...]}
check：lock 檔必須存在、列出的模組＝包內實際的模組資料夾（full_package；module_update 只核對它列的）、
       版本＝各自 module.json、內容雜湊一致；
       L0／L1 必要檔（docs/platform/modules.json 的 L1 Python 單位與 backend/core/*.py）一個都不能缺；
       tools/platform/upgrade.py 也必須在包裡（升級精靈用）。
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PRODUCT_DIR = REPO / "product"
MODULES_JSON = REPO / "docs" / "platform" / "modules.json"
LOCK_NAME = "modules.lock.json"
#: 包根目錄底下一定要有的檔（相對部署包根）。tools/ 刻意進包：升級精靈與 UPGRADE-RUNBOOK 在正式機執行
#: <NEW>\\tools\\platform\\upgrade.py（主持 2026-09-25 裁示；不可加 export-ignore）。
REQUIRED_PKG_FILES = ("tools/platform/upgrade.py",)


class SelectError(Exception):
    pass


def load_product(name_or_path):
    p = Path(name_or_path)
    if not p.suffix:
        p = PRODUCT_DIR / (name_or_path + ".json")
    if not p.is_file():
        raise SelectError("找不到產品設定檔：%s（可用：%s）" % (p, ", ".join(sorted(x.stem for x in PRODUCT_DIR.glob("*.json")))))
    prod = json.loads(p.read_text(encoding="utf-8"))
    mods = prod.get("modules")
    if not isinstance(mods, list) or not all(isinstance(m, str) for m in mods):
        raise SelectError("%s：modules 必須是字串清單（\"*\"＝全部）" % p.name)
    prod.setdefault("name", p.stem)
    return prod


def module_dirs(backend):
    root = Path(backend) / "modules"
    if not root.is_dir():
        return {}
    return {d.name: d for d in sorted(root.iterdir()) if d.is_dir() and (d / "module.json").is_file()}


def _manifest(d):
    return json.loads((Path(d) / "module.json").read_text(encoding="utf-8"))


def resolve(prod, available):
    """(要留的 key, 要刪的 key)。列了不存在的 key ⇒ SelectError。"""
    wanted = prod["modules"]
    if "*" in wanted:
        extra = [m for m in wanted if m != "*"]
        if extra:
            raise SelectError("modules 用了 \"*\" 就不要再列個別模組：%s" % extra)
        keep = sorted(available)
    else:
        unknown = sorted(set(wanted) - set(available))
        if unknown:
            raise SelectError("產品 %s 列了包裡沒有的模組：%s（包裡有：%s）" % (prod["name"], unknown, sorted(available)))
        keep = sorted(set(wanted))
    return keep, sorted(set(available) - set(keep))


LOCK_VERSION = 1
KINDS = ("full_package", "module_update")


def module_digest(d):
    """模組資料夾的內容雜湊（相對路徑＋位元組，排序後串接；略過 __pycache__）。P7 用它核對單一模組更新包。"""
    h = hashlib.sha256()
    d = Path(d)
    for f in sorted(p for p in d.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        h.update(f.relative_to(d).as_posix().encode("utf-8") + b"\0")
        h.update(f.read_bytes() + b"\0")
    return h.hexdigest()


def module_entry(d):
    m = _manifest(d)
    return {"version": m.get("version"), "core": m.get("core"), "sha256": module_digest(d)}


def _rmtree(p):
    def _clear_readonly(func, path, _exc):
        os.chmod(path, stat.S_IWRITE)
        func(path)
    shutil.rmtree(str(p), onerror=_clear_readonly)


def core_version(backend):
    reg = Path(backend) / "core" / "registry.py"
    m = re.search(r'^CORE_VERSION\s*=\s*"([^"]+)"', reg.read_text(encoding="utf-8"), re.M) if reg.is_file() else None
    return m.group(1) if m else None


def apply(pkg, prod):
    backend = Path(pkg) / "backend"
    available = module_dirs(backend)
    keep, drop = resolve(prod, available)
    removed_pages = []
    for key in drop:
        for page in _manifest(available[key]).get("pages", []):
            f = Path(pkg) / "frontend" / "pages" / page["path"]
            if f.is_file():
                f.unlink()
                removed_pages.append("frontend/pages/" + page["path"])
        _rmtree(available[key])
    lock = {
        "lock_version": LOCK_VERSION,
        "kind": "full_package",
        "product": prod["name"],
        "core_version": core_version(backend),
        "modules": {k: module_entry(available[k]) for k in keep},
        "excluded": drop,
        "removed_pages": removed_pages,
    }
    (backend / LOCK_NAME).write_text(json.dumps(lock, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return lock


def _core_files_at(pkg):
    """包打包時那個 commit 的 backend/core/*.py（依包內 .build_commit 從 git 列）；取不到 ⇒ None。"""
    import subprocess
    bc = Path(pkg) / "backend" / ".build_commit"
    if not bc.is_file():
        return None
    try:
        out = subprocess.run(["git", "-C", str(REPO), "ls-tree", "--name-only", bc.read_text(encoding="ascii").strip(),
                              "backend/core/"], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return sorted("core/" + Path(l).name for l in out.splitlines() if l.endswith(".py"))


def required_l1_files(modules_json=MODULES_JSON, core_files=None):
    """包裡一定要有的 L0／L1 檔（相對 backend/）。

    🔴 2026-09-25（B）：以**包自己的 commit** 為準（包內 docs/platform/modules.json＋.build_commit 的 core/）。
       初版用「目前 repo」的清單 ⇒ 拿去驗較早打的包時，把包打好之後才新增的 L1 檔算成缺檔
       （verify 一個 a870fa44 的包，報缺 core/events.py、helpers/module_switches.py）。"""
    data = json.loads(Path(modules_json).read_text(encoding="utf-8"))
    req = set()
    for u in data["L1"]["units"]:
        kind, name = u.split(":", 1)
        if kind == "plat":
            req.add("core/%s.py" % name)
        elif kind == "core":
            req.add("%s.py" % name)
        elif kind == "helper":
            req.add("helpers/%s.py" % name)
        elif kind == "router":
            req.add("routers/%s.py" % name)
    if core_files is None:
        core_files = ["core/%s" % p.name for p in (REPO / "backend" / "core").glob("*.py")]
    req.update(core_files)
    return sorted(req)


def check(pkg, modules_json=None):
    """部署包 ⇒ 問題清單（空＝通過）。modules_json 預設用包內那一份（同一個 commit）。"""
    backend = Path(pkg) / "backend"
    problems = []
    core_files = None
    if modules_json is None:
        own = Path(pkg) / "docs" / "platform" / "modules.json"
        modules_json = own if own.is_file() else MODULES_JSON
        core_files = _core_files_at(pkg)
    lock_p = backend / LOCK_NAME
    if not lock_p.is_file():
        return ["缺 backend/%s（沒有經過產品選配，或選配失敗）" % LOCK_NAME]
    lock = json.loads(lock_p.read_text(encoding="utf-8"))
    if lock.get("lock_version") != LOCK_VERSION:
        return ["lock_version %r 看不懂（這版只認 %d）⇒ 不猜" % (lock.get("lock_version"), LOCK_VERSION)]
    kind = lock.get("kind")
    if kind not in KINDS:
        return ["lock 的 kind %r 不認得（%s）" % (kind, "／".join(KINDS))]
    actual = module_dirs(backend)
    listed = lock.get("modules") or {}
    if kind == "full_package" and set(listed) != set(actual):
        problems.append("lock 列的模組 %s ≠ 包內實際 %s" % (sorted(listed), sorted(actual)))
    if kind == "module_update" and set(listed) - set(actual):
        problems.append("更新包 lock 列的模組不在包裡：%s" % sorted(set(listed) - set(actual)))
    for k in sorted(set(listed) & set(actual)):
        cur = module_entry(actual[k])
        if listed[k].get("version") != cur["version"]:
            problems.append("模組 %s：lock 版本 %s ≠ module.json %s" % (k, listed[k].get("version"), cur["version"]))
        if listed[k].get("sha256") != cur["sha256"]:
            problems.append("模組 %s：內容雜湊與 lock 不符（打包後被改過）" % k)
    if kind == "module_update":
        return problems             # 更新包只帶模組本身，不驗 L0／L1（P7 會另訂套用前檢查）
    for rel in required_l1_files(modules_json, core_files):
        if not (backend / rel).is_file():
            problems.append("缺 L0／L1 必要檔 backend/%s" % rel)
    for rel in REQUIRED_PKG_FILES:
        if not (Path(pkg) / rel).is_file():
            problems.append("缺部署包必要檔 %s（升級精靈在正式機執行它）" % rel)
    if lock.get("core_version") != core_version(backend):
        problems.append("lock 的 core_version %s ≠ 包內 CORE_VERSION %s" % (lock.get("core_version"), core_version(backend)))
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a1 = sub.add_parser("apply")
    a1.add_argument("--pkg", required=True)
    a1.add_argument("--product", required=True)
    a2 = sub.add_parser("check")
    a2.add_argument("--pkg", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "apply":
            lock = apply(a.pkg, load_product(a.product))
            print("[選配] 產品 %s：包含 %s；排除 %s；移除頁面 %s"
                  % (lock["product"], sorted(lock["modules"]) or "（無 L2）", lock["excluded"] or "無",
                     lock["removed_pages"] or "無"))
            problems = check(a.pkg)
        else:
            problems = check(a.pkg)
    except SelectError as e:
        print("[選配] ✗ %s" % e)
        return 2
    if problems:
        print("[選配] ✗ 驗證失敗：\n  " + "\n  ".join(problems))
        return 1
    print("[選配] ✓ modules.lock.json 與包內一致，L0／L1 必要檔齊全")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
