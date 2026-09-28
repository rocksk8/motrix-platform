"""P7 模組更新包：以單一模組為單位打包、檢查、套用、回滾（CUSTOMIZATION-SPEC §7；上線設計 docs/platform/MODULE-UPDATE-DELIVERY.md）。

用法：
  python tools/platform/module_update.py build     --key tender_radar --prod-base <正式機 commit> [--out DIR] [--commit HEAD] [--overlay key=sha256 ...]
  python tools/platform/module_update.py check     --pkg <更新包目錄>
  python tools/platform/module_update.py preflight --root <安裝根目錄> --pkg <更新包目錄> [--require-base] [--json]
  python tools/platform/module_update.py apply     --root <安裝根目錄> --pkg <更新包目錄> [--allow-downgrade] [--json]
  python tools/platform/module_update.py rollback  --root <安裝根目錄> --key tender_radar [--backup <時間>] [--json]
  python tools/platform/module_update.py list      --root <安裝根目錄>

build＝出貨：先以 ship_tier 判定 P（正式機 commit）→X 只改這個模組（第②級，否則拒絕、必須完整包），
再跑第②級的題（該模組題＋tests/platform＋頁面 e2e＋提供者有改時的消費端題），全綠才打包。
套用與回滾只動 `backend/modules/<key>/`、該模組宣告的頁面、安裝目錄 lock 的該模組條目，以及三個狀態檔
（`.deployed_files.json` 的該模組片段、`.deployed_modules.json`、`version_manifest.json` 的該模組條目）；
不動 L0／L1、其他模組與資料庫；**需重啟服務生效**（正式機由 backend/tools/apply_module_update.ps1 負責停服、重啟、健檢、自動回滾）。
📌 本檔隨完整包出貨（根目錄 tools/ 一律進包：tools/platform/upgrade.py 同理），正式機的套用腳本呼叫的是**已安裝**的這一份。
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
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import product_select as PS  # noqa: E402

LOCK_NAME = "module-update.lock.json"
BACKUP_DIR = "module_backups"
BACKUP_KEEP = 5
_EXCLUDE_PARTS = ("tests", "__pycache__")
_EXCLUDE_NAMES = ("SPEC.md",)

#: 單模組套用會一併改動（並在回滾時整檔還原）的安裝目錄狀態檔（設計 §1.3 步驟 7、§3）
BASELINE_REL = "backend/.deployed_files.json"          # 完整包刪除計畫的基準（apply_plan.BASELINE_REL）
DEPLOYED_MODULES_REL = "backend/.deployed_modules.json"   # 模組覆蓋紀錄（core.upgrade.CONFIG_FILES）
MANIFEST_REL = "backend/version_manifest.json"
STATE_FILES = (BASELINE_REL, DEPLOYED_MODULES_REL, MANIFEST_REL)
DEPLOYED_COMMIT_REL = "backend/.deployed_commit.json"


class UpdateError(Exception):
    """code：機器可讀的原因（--json 輸出；apply_module_update.ps1 依它分流，例：backup_corrupt ⇒ 停用該模組再重啟，設計 §2 F13）。
    值域見 docs/platform/MODULE-UPDATE-DELIVERY.md §10。"""

    def __init__(self, msg, code="refused"):
        super().__init__(msg)
        self.code = code


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
    return ["%s/%s" % (_PAGES_DIR, p["path"]) for p in manifest.get("pages", [])]


_PAGES_DIR = "frontend/pages"
#: 稽核 D S4-S2：套用時會寫到 <ROOT>/<rel> ⇒ 只准頁面目錄底下、單層、.html；不准 ..、絕對路徑、子目錄
PAGE_REL_RE = re.compile("^" + re.escape(_PAGES_DIR) + r"/[A-Za-z0-9_\-]+(?:\.[A-Za-z0-9_\-]+)*\.html$")


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


def _read_json(p):
    """PS 5.1 的 Set-Content -Encoding UTF8 會帶 BOM ⇒ 一律 utf-8-sig。"""
    return json.loads(Path(p).read_text(encoding="utf-8-sig"))


def deployed_commit(root):
    p = Path(root) / DEPLOYED_COMMIT_REL
    if not p.is_file():
        return None
    try:
        return (_read_json(p) or {}).get("commit") or None
    except ValueError:
        return None


# ── build（低階：從 git 取出單一模組）───────────────────────────────────────────

def build(key, out_dir, commit="HEAD", repo=REPO):
    """從 git（已 commit 的內容）取出單一模組 ⇒ 更新包目錄。出貨請用 ship()（先判等級、跑題）。"""
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
    _write_lock(pkg, lock)
    return pkg


def _write_lock(pkg, lock):
    (Path(pkg) / LOCK_NAME).write_text(json.dumps(lock, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def _core_version_at(commit, repo):
    try:
        src = _git("show", "%s:backend/core/registry.py" % commit, repo=repo)
    except UpdateError:
        return None
    m = re.search(r'^CORE_VERSION\s*=\s*"([^"]+)"', src, re.M)
    return m.group(1) if m else None


# ── ship（出貨：判等級 → 第②級測試 → 打包）─────────────────────────────────────

def manifest_lines(prod_base, commit, key, repo=REPO):
    """X 的 version_manifest.json 裡、P 沒有、而且屬於 <key> 的條目 ⇒ 原始文字行（去掉行尾逗號；套用時以文字插入）。"""
    import ship_tier as ST
    old = json.loads(_git("show", "%s:%s" % (prod_base, MANIFEST_REL), repo=repo) or "[]")
    have = {(e.get("module"), e.get("version")) for e in old}
    man = json.loads(_git("show", "%s:backend/modules/%s/module.json" % (commit, key), repo=repo))
    names = {n for n in (man.get("name"), man.get("manifest_name"), key) if n}
    out = []
    for line in _git("show", "%s:%s" % (commit, MANIFEST_REL), repo=repo).splitlines():
        raw = line.strip().rstrip(",")
        if not raw.startswith("{"):
            continue
        try:
            e = json.loads(raw)
        except ValueError:
            raise UpdateError("version_manifest.json 不是一行一筆（不能以文字插入）：%s" % raw[:60])
        if (e.get("module"), e.get("version")) not in have and e.get("module") in names:
            out.append(raw)
    del ST
    return out


def ship_tests(key, tier_result, repo=REPO):
    """第②級的題（backend 相對路徑，給 pytest 在 backend/ 跑）：該模組題＋tests/platform＋宣告頁面與消費端經 modtest 選出的題。"""
    sel = {"backend/tests/platform"}
    mod_tests = Path(repo) / "backend" / "modules" / key / "tests"
    if mod_tests.is_dir():
        sel.add("backend/modules/%s/tests" % key)
    man = json.loads((Path(repo) / "backend" / "modules" / key / "module.json").read_text(encoding="utf-8"))
    extra = list(_page_paths(man))
    pc = tier_result.get("provider") or {}
    extra += list(pc.get("consumers") or [])
    if extra:
        r = subprocess.run([sys.executable, str(HERE / "modtest.py"), "--files", *extra, "--dry-run", "--json"],
                           cwd=str(repo), capture_output=True)
        if r.returncode not in (0, 3):
            raise UpdateError("modtest 選題失敗：%s" % r.stderr.decode("utf-8", "replace")[-400:])
        try:
            sel |= set(json.loads(r.stdout.decode("utf-8")).get("tests") or [])
        except ValueError:
            raise UpdateError("modtest 選題輸出看不懂（不猜：拒絕出貨）")
    return sorted(s[len("backend/"):] if s.startswith("backend/") else s for s in sel)


def run_ship_tests(tests, repo=REPO):
    """-n 2、低優先權、basetemp 用完刪（PLAYBOOK §C-13）；回 {"tests","passed","failed","errors","seconds","line"}。"""
    bt = Path(tempfile.gettempdir()) / ("motrix-pytest-ship-%s" % time.strftime("%Y%m%d_%H%M%S"))
    t0 = time.time()
    flags = 0x00004000 if os.name == "nt" else 0          # BELOW_NORMAL_PRIORITY_CLASS
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", *tests, "-n", "2", "-p", "no:cacheprovider", "-q",
                            "--basetemp=%s" % bt], cwd=str(Path(repo) / "backend"), capture_output=True,
                           creationflags=flags)
    finally:
        shutil.rmtree(bt, ignore_errors=True)
    out = r.stdout.decode("utf-8", "replace").splitlines()
    line = next((l for l in reversed(out) if re.search(r"\d+ (passed|failed|error)", l)), "")
    num = lambda w: int((re.search(r"(\d+) %s" % w, line) or [0, 0])[1])   # noqa: E731
    res = {"tests": tests, "passed": num("passed"), "failed": num("failed"), "errors": num("error"),
           "seconds": round(time.time() - t0, 1), "line": line.strip("= "), "exit": r.returncode}
    if r.returncode != 0 or res["failed"] or res["errors"] or not res["passed"]:
        raise UpdateError("第②級測試沒有全綠（exit %s）：%s" % (r.returncode, res["line"] or "沒有結果行"))
    return res


def ship(key, out_dir, prod_base, commit="HEAD", overlays=None, run_tests=True, repo=REPO):
    """出貨：ship_tier 判定 P→X＝第②級且就是 <key> ⇒ 跑第②級測試 ⇒ build ⇒ lock 補出貨資訊。"""
    import ship_tier as ST
    commit = _git("rev-parse", commit, repo=repo)
    res = ST.tier_for(prod_base, commit, overlays or {}, repo=repo)
    if res["tier"] != ST.TIER_MODULE or res["key"] != key:
        why = "\n  ".join("%s：%s" % o for o in res["offenders"]) or "（判定模組 %s）" % res["key"]
        raise UpdateError("P→X 不是只改模組 %s（等級 %s）⇒ 必須完整包：\n  %s" % (key, res["tier"], why))
    summary = {"skipped": "run_tests=False（僅限題目內呼叫）"}
    if run_tests:
        if _git("rev-parse", "HEAD", repo=repo) != commit or _git("status", "--porcelain", "--", "backend", "frontend", "tools", repo=repo):
            raise UpdateError("第②級測試要在 X 本身跑：工作樹必須是 %s 而且 backend／frontend／tools 沒有未 commit 的改動" % commit[:8])
        summary = run_ship_tests(ship_tests(key, res, repo), repo)
    pkg = build(key, out_dir, commit=commit, repo=repo)
    lock = load_pkg(pkg)
    lock.update({"prod_base_commit": _git("rev-parse", prod_base, repo=repo), "tier": "module", "tests": summary,
                 "manifest_lines": manifest_lines(prod_base, commit, key, repo),
                 "provider": {k: (res.get("provider") or {}).get(k) for k in ("provider_changed", "caps", "consumers")},
                 "overlays": dict(overlays or {})})
    _write_lock(pkg, lock)
    return pkg


# ── check ────────────────────────────────────────────────────────────────

def load_pkg(pkg):
    lp = Path(pkg) / LOCK_NAME
    if not lp.is_file():
        raise UpdateError("不是模組更新包：缺 %s" % LOCK_NAME, code="pkg_invalid")
    lock = json.loads(lp.read_text(encoding="utf-8"))
    if lock.get("lock_version") != PS.LOCK_VERSION or lock.get("kind") != "module_update":
        raise UpdateError("看不懂的 lock（lock_version=%r、kind=%r）⇒ 不猜" % (lock.get("lock_version"), lock.get("kind")), code="pkg_invalid")
    if len(lock.get("modules") or {}) != 1:
        raise UpdateError("模組更新包一次只能帶一個模組：%s" % sorted(lock.get("modules") or {}), code="pkg_invalid")
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
    for rel in (lock.get("pages") or {}):
        if not PAGE_REL_RE.match(str(rel)):
            problems.append("lock 的頁面路徑不合格（只准 %s/<檔名>.html）：%r" % (_PAGES_DIR, rel))
    if any(not PAGE_REL_RE.match(str(r)) for r in (lock.get("pages") or {})):
        return problems
    for rel, h in (lock.get("pages") or {}).items():
        if not (Path(pkg) / rel).is_file() or _sha(Path(pkg) / rel) != h:
            problems.append("頁面 %s 不存在或雜湊不符" % rel)
    for raw in lock.get("manifest_lines") or []:
        try:
            json.loads(raw)
        except ValueError:
            problems.append("lock 的 version_manifest 條目不是合法 JSON：%s" % raw[:60])
    return problems


# ── apply／rollback ──────────────────────────────────────────────────────

#: 測試注入點：(模組 manifest) -> (ok, 原因)。None ⇒ 用**安裝目錄**的 helpers.licensing 讀它的授權金鑰（與正式機啟動同一支判定）
_license_check = None


def _license_for(root):
    if _license_check is not None:
        return _license_check
    backend = Path(root) / "backend"
    if not (backend / "helpers" / "licensing.py").is_file():
        raise UpdateError("安裝目錄沒有 helpers/licensing.py ⇒ 授權判不了，不套用", code="license_unavailable")
    sys.path.insert(0, str(backend))
    try:
        from helpers import licensing as L
    except Exception as e:                              # noqa: BLE001  算不出來就不動（不猜）
        raise UpdateError("讀不到授權判定（helpers.licensing：%s），不套用" % e, code="license_unavailable")
    L.LICENSE_PATH = str(backend / "license.key")
    gate = L.LICENSE_GATE_ENABLED
    status = L.verify_license() if gate else {}
    return lambda manifest: L.module_licensed(manifest, status, gate)


def preflight(root, pkg, allow_downgrade=False, require_base=False):
    """套用前檢查；回傳 (key, lock, installed_version)。任何一項不過 ⇒ UpdateError（什麼都還沒動）。"""
    problems = check(pkg)
    if problems:
        raise UpdateError("更新包檢查不過：" + "；".join(problems), code="pkg_invalid")
    lock = load_pkg(pkg)
    (key, entry), = lock["modules"].items()
    backend = Path(root) / "backend"
    inst_lock_p = backend / PS.LOCK_NAME
    if not inst_lock_p.is_file():
        raise UpdateError("安裝目錄沒有 backend/%s ⇒ 不是經過產品選配的安裝，不套用" % PS.LOCK_NAME, code="no_install_lock")
    base = lock.get("prod_base_commit")
    if base or require_base:
        cur = deployed_commit(root)
        if not base:
            raise UpdateError("更新包沒有記正式機基準 commit（不是用 ship 出貨的包）⇒ 不套用", code="no_base")
        if cur is None:
            raise UpdateError("安裝目錄沒有 %s ⇒ 判不了這個包是不是對這一版做的，不套用" % DEPLOYED_COMMIT_REL, code="no_deployed_marker")
        if cur != base:
            raise UpdateError("這個包是對正式機 %s 做的，而安裝目錄是 %s ⇒ 不套用（請以目前版本重新出貨，或改用完整包）"
                              % (base[:8], cur[:8]), code="base_mismatch")
    pending = pending_interrupted_any(root)
    if pending:
        k, st = pending[-1]
        raise UpdateError("模組 %s 有中斷的套用（備份 %s）⇒ 先用套用腳本的回滾模式回到套用前（停服、還原、重啟、健檢；"
                          "見 docs/platform/MODULE-UPDATE-PROD-INSTRUCTIONS.md §5），再套用任何模組"
                          "（lock 與狀態檔是全安裝共用；稽核 D S3R-M1／P8）" % (k, st), code="interrupted_apply_pending")
    inst_core = _core_version(backend)
    if not _core_ok(entry.get("core"), inst_core):
        raise UpdateError("模組 %s 要求 core %s，安裝目錄是 %s ⇒ 不相容" % (key, entry.get("core"), inst_core), code="core_incompatible")
    manifest = json.loads((Path(pkg) / "backend" / "modules" / key / "module.json").read_text(encoding="utf-8"))
    ok, why = _license_for(root)(manifest)
    if not ok:
        raise UpdateError("模組 %s 不在這台機器的授權內（%s）⇒ 不套用" % (key, why), code="unlicensed")
    inst_lock = json.loads(inst_lock_p.read_text(encoding="utf-8"))
    installed = (inst_lock.get("modules") or {}).get(key)
    inst_ver = installed.get("version") if isinstance(installed, dict) else installed
    if isinstance(installed, dict) and installed.get("sha256") == entry.get("sha256"):
        raise UpdateError("模組 %s 已是這一版（內容雜湊相同）⇒ 不需套用" % key, code="already_installed")
    if inst_ver is not None and _ver(entry["version"]) <= _ver(inst_ver) and not allow_downgrade:
        raise UpdateError("模組 %s：更新包 %s 不高於已安裝 %s ⇒ 拒絕（降版或重裝請加 --allow-downgrade）"
                          % (key, entry["version"], inst_ver), code="not_higher")
    return key, lock, inst_ver


def _save_state(root, bdir):
    """三個狀態檔的套用前位元組（不存在就記下「本來沒有」）。"""
    absent = []
    for rel in STATE_FILES:
        src = Path(root) / rel
        if src.is_file():
            dst = bdir / "state_before" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        else:
            absent.append(rel)
    return absent


def _restore_state(root, bdir, absent):
    for rel in STATE_FILES:
        dst = Path(root) / rel
        if rel in absent:
            if dst.is_file():
                dst.unlink()
            continue
        src = bdir / "state_before" / rel
        if not src.is_file():
            raise UpdateError("備份裡缺狀態檔 %s ⇒ 備份已損壞，停止回滾" % rel, code="backup_corrupt")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _write_json_atomic(path, data, indent=1):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=indent) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))


def _update_baseline(root, key, before, after):
    """完整包刪除計畫的基準（.deployed_files.json）：換掉這個模組與它宣告頁面那一段（設計 §1.3 步驟 7／稽核 D DB-S6）。"""
    p = Path(root) / BASELINE_REL
    if not p.is_file():
        return False                                    # 沒有基準（新裝）⇒ 完整包那邊本來就只列不刪
    data = _read_json(p)
    files = [f for f in data.get("files", []) if f not in before]
    data["files"] = sorted(set(files) | set(after))
    data["module_updates"] = sorted(set(data.get("module_updates", [])) | {key})
    _write_json_atomic(p, data, indent=0)
    return True


def _insert_manifest(root, lines):
    """version_manifest.json：以**文字插入**（不整份重寫，〈共用 JSON 用文字插入〉）；同一 (module, version) 已在 ⇒ 略過。"""
    p = Path(root) / MANIFEST_REL
    if not lines or not p.is_file():
        return 0
    text = p.read_text(encoding="utf-8")
    have = {(e.get("module"), e.get("version")) for e in json.loads(text)}
    add = [raw for raw in lines if (json.loads(raw).get("module"), json.loads(raw).get("version")) not in have]
    if not add:
        return 0
    if not text.startswith("[\n"):
        raise UpdateError("version_manifest.json 開頭不是 '[' 換行 ⇒ 不能以文字插入")
    new = "[\n" + "".join("  %s,\n" % raw for raw in add) + text[2:]
    json.loads(new)                                      # 插完仍是合法 JSON 才寫
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(new, encoding="utf-8")
    os.replace(str(tmp), str(p))
    return len(add)


def _update_deployed_modules(root, key, lock, stamp):
    """模組覆蓋紀錄：只留 prod_base＝目前正式機 commit 的條目（完整包換了 commit ⇒ 舊條目過期，設計 §3），再記這一筆。"""
    p = Path(root) / DEPLOYED_MODULES_REL
    cur = deployed_commit(root)
    data = {}
    if p.is_file():
        try:
            data = _read_json(p) or {}
        except ValueError:
            data = {}
    data = {k: v for k, v in data.items() if isinstance(v, dict) and v.get("prod_base_commit") == cur}
    entry = lock["modules"][key]
    data[key] = {"version": entry.get("version"), "sha256": entry.get("sha256"), "built_from": lock.get("built_from"),
                 "prod_base_commit": lock.get("prod_base_commit") or cur, "applied_at": stamp}
    _write_json_atomic(p, data)


def overlays(root):
    """正式機已套用、而且仍然有效（base＝目前 commit）的模組覆蓋 ⇒ {key: sha256}（ship_tier 扣除用）。"""
    p = Path(root) / DEPLOYED_MODULES_REL
    if not p.is_file():
        return {}
    cur = deployed_commit(root)
    return {k: v.get("sha256") for k, v in (_read_json(p) or {}).items()
            if isinstance(v, dict) and v.get("prod_base_commit") == cur}


def _state_hashes(root):
    """lock＋三個狀態檔的現值雜湊（不存在 ⇒ None）：套用完成時記下，回滾前比對（稽核 D S3-M2）。"""
    out = {}
    for rel in ("backend/" + PS.LOCK_NAME,) + STATE_FILES:
        p = Path(root) / rel
        out[rel] = _sha(p) if p.is_file() else None
    return out


def _write_record(bdir, record):
    _write_json_atomic(Path(bdir) / "apply.json", record)


def _verify_backup(bdir, rec):
    for rel, h in rec["files_before"].items():
        src = Path(bdir) / "files" / rel
        if not src.is_file() or _sha(src) != h:
            raise UpdateError("備份檔 %s 的雜湊與紀錄不符 ⇒ 備份已損壞，停止回滾" % rel, code="backup_corrupt")
    # lock 與三個狀態檔的備份也要核對（它們是整檔還原：壞掉的備份會把壞內容寫回正式機）
    for rel, h in (rec.get("backup_hashes") or {}).items():
        src = Path(bdir) / rel
        if not src.is_file() or _sha(src) != h:
            raise UpdateError("備份檔 %s 不在或雜湊與紀錄不符 ⇒ 備份已損壞，停止回滾" % rel, code="backup_corrupt")
    if not (Path(bdir) / "lock_before.json").is_file() and "lock_entry_before" not in rec:
        raise UpdateError("備份裡沒有 lock_before.json ⇒ 備份已損壞，停止回滾", code="backup_corrupt")


def _restore_from(root, key, bdir, rec):
    """用一份備份把這個模組、宣告頁面、lock、三個狀態檔還原成套用前（apply 中途失敗與 rollback 共用）。
    先核對備份；對不上 ⇒ UpdateError，安裝目錄一個檔都不動。"""
    root, bdir = Path(root), Path(bdir)
    _verify_backup(bdir, rec)
    backend = root / "backend"
    mdir = backend / "modules" / key
    # 移除套用後（或套用到一半）的檔：模組資料夾＋套用前／套用後宣告的頁面
    pages = {r for r in rec.get("files_after", {}) if r.startswith("frontend/")}
    pages |= {r for r in rec.get("pages_after", []) if r.startswith("frontend/")}
    pages |= {r for r in rec["files_before"] if r.startswith("frontend/")}
    for rel in pages:
        if (root / rel).is_file():
            (root / rel).unlink()
    if mdir.exists():
        _rmtree(mdir)
    for rel in rec["files_before"]:
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bdir / "files" / rel, dst)
    inst_lock_p = backend / PS.LOCK_NAME
    if (bdir / "lock_before.json").is_file():
        shutil.copy2(bdir / "lock_before.json", inst_lock_p)       # 逐位元組還原
    else:                                                            # 舊版備份（沒有 lock_before）：照條目還原
        inst_lock = json.loads(inst_lock_p.read_text(encoding="utf-8"))
        if rec.get("lock_entry_before") is None:
            inst_lock.get("modules", {}).pop(key, None)
        else:
            inst_lock.setdefault("modules", {})[key] = rec["lock_entry_before"]
        if "excluded_before" in rec:
            inst_lock["excluded"] = rec["excluded_before"]
        inst_lock_p.write_text(json.dumps(inst_lock, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if "state_absent" in rec:
        _restore_state(root, bdir, rec["state_absent"])
    after = _tree_hashes(root, key)
    if after != rec["files_before"]:
        diff = sorted(set(after.items()) ^ set(rec["files_before"].items()))
        raise UpdateError("還原後雜湊與套用前不一致：%s" % diff[:5], code="restore_mismatch")


STAMP_RE = re.compile(r"^\d{8}_\d{6}(_\d{1,6})?$")


def apply(root, pkg, allow_downgrade=False, require_base=False, stamp=None):
    """stamp：呼叫端指定備份名（apply_module_update.ps1 開頭就定好，寫進 log 與結果檔，中途失敗時用它 rollback --backup）。"""
    if stamp is not None and not STAMP_RE.match(str(stamp)):
        raise UpdateError("--stamp 格式不對：%r（yyyyMMdd_HHmmss[_微秒]）" % stamp, code="bad_args")
    key, lock, inst_ver = preflight(root, pkg, allow_downgrade, require_base)
    root = Path(root)
    backend = root / "backend"
    from datetime import datetime
    if stamp is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")   # 含微秒：同一秒內連續套用不可撞名
    bdir = root / BACKUP_DIR / key / stamp
    if bdir.exists():
        raise UpdateError("備份 %s 已存在 ⇒ 不覆蓋（stamp 重複）" % bdir, code="bad_args")
    bdir.mkdir(parents=True)
    before = _tree_hashes(root, key)
    for rel in before:
        dst = bdir / "files" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / rel, dst)
    inst_lock_p = backend / PS.LOCK_NAME
    shutil.copy2(inst_lock_p, bdir / "lock_before.json")
    state_absent = _save_state(root, bdir)
    backup_hashes = {"lock_before.json": _sha(bdir / "lock_before.json")}
    for rel in STATE_FILES:
        if rel not in state_absent:
            backup_hashes["state_before/" + rel] = _sha(bdir / "state_before" / rel)
    inst_lock = json.loads(inst_lock_p.read_text(encoding="utf-8"))
    record = {"key": key, "status": "in_progress", "backup_hashes": backup_hashes, "from_version": inst_ver, "to_version": lock["modules"][key]["version"],
              "built_from": lock.get("built_from"), "prod_base_commit": lock.get("prod_base_commit"),
              "files_before": before, "pages_after": sorted(lock.get("pages") or {}),
              "lock_entry_before": (inst_lock.get("modules") or {}).get(key),
              "excluded_before": list(inst_lock.get("excluded", [])), "state_absent": state_absent,
              "applied_at": stamp}
    # 稽核 D S3-M1：**動檔之前**先寫紀錄（in_progress）——中途被砍掉（行程被殺、斷電）時 rollback 找得到這一份
    _write_record(bdir, record)
    try:
        # 替換＝鏡像（稽核 D DB-S6）：整個模組資料夾刪掉再放新的、舊版宣告的頁面刪掉再放新版宣告的
        # ⇒ 新版刪掉的檔不會留著被載入
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
        after = _tree_hashes(root, key)
        record["files_after"] = after
        record["baseline_updated"] = _update_baseline(root, key, set(before), set(after))
        record["manifest_inserted"] = _insert_manifest(root, lock.get("manifest_lines"))
        _update_deployed_modules(root, key, lock, stamp)
    except BaseException as e:                              # noqa: BLE001  任何中途失敗（含 Ctrl+C）：用本次備份還原（S3R-M1）
        try:
            _restore_from(root, key, bdir, record)
        except Exception as e2:                             # noqa: BLE001
            raise UpdateError("套用中途失敗（%s），而且用本次備份還原也失敗（%s）⇒ 安裝目錄是半套狀態；"
                              "備份 %s 仍在（rollback 會用它）" % (e, e2, bdir), code="apply_failed_half")
        _rmtree(bdir)                                       # S3-S1：還原成功 ⇒ 這一份失敗的備份沒有用了
        raise UpdateError("套用中途失敗（%s）⇒ 已用本次備份還原到套用前" % e, code="apply_failed_restored")
    # 稽核 D S3-M2：套用完成時的現值——回滾前比對，之後有任何寫入（別的模組包、完整包）⇒ 拒絕整檔還原
    record["status"] = "applied"
    record["state_after"] = _state_hashes(root)
    _write_record(bdir, record)
    _prune_backups(root, key)
    return record, bdir


def _prune_backups(root, key, keep=None):
    keep = BACKUP_KEEP if keep is None else keep
    d = Path(root) / BACKUP_DIR / key
    for name in _all_records(root, key)[:-keep]:
        if (_record(root, key, name) or {}).get("status") != "in_progress":
            _rmtree(d / name)


def _record(root, key, name):
    try:
        return json.loads((Path(root) / BACKUP_DIR / key / name / "apply.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _all_records(root, key):
    """這個模組的全部備份目錄名（有 apply.json 的），舊到新。"""
    d = Path(root) / BACKUP_DIR / key
    return sorted(p.name for p in d.iterdir() if (p / "apply.json").is_file()) if d.is_dir() else []


def pending_interrupted_any(root):
    """全安裝所有模組的中斷套用 ⇒ [(模組, 備份名)]，依備份名（時間）排序。"""
    d = Path(root) / BACKUP_DIR
    out = []
    for kd in (sorted(x for x in d.iterdir() if x.is_dir()) if d.is_dir() else []):
        out += [(kd.name, n) for n in pending_interrupted(root, kd.name)]
    return sorted(out, key=lambda t: t[1])


def newest_record_any(root):
    """全安裝所有模組最新的一份備份 ⇒ (模組, 備份名) 或 None。"""
    d = Path(root) / BACKUP_DIR
    best = None
    for kd in (sorted(x for x in d.iterdir() if x.is_dir()) if d.is_dir() else []):
        for n in _all_records(root, kd.name):
            if best is None or n > best[1]:
                best = (kd.name, n)
    return best


def pending_interrupted(root, key):
    """中斷的套用（status＝in_progress）⇒ 備份名清單（稽核 D S3R-M1）。"""
    # 稽核 D S5-S1（P9）：apply.json 讀不懂也算中斷（與 apply_plan.interrupted_module_applies 一致；不猜）
    return [n for n in _all_records(root, key)
            if _record(root, key, n) is None or _record(root, key, n).get("status") == "in_progress"]


def backups(root, key):
    """可回滾的備份：套用完成（applied）、中途被砍掉而留下的（in_progress）、舊版紀錄（沒有 status）；
    已回滾過的（rolled_back）不列。"""
    d = Path(root) / BACKUP_DIR / key
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.iterdir()):
        if not (p / "apply.json").is_file():
            continue
        rec = _record(root, key, p.name)
        if rec is None or rec.get("status", "applied") in ("applied", "in_progress"):
            out.append(p.name)
    return out


def rollback(root, key, stamp=None):
    root = Path(root)
    avail = backups(root, key)
    if not avail:
        raise UpdateError("模組 %s 沒有任何套用備份 ⇒ 無從回滾" % key, code="no_backup")
    stamp = stamp or avail[-1]
    if stamp not in avail:
        raise UpdateError("找不到備份 %s（有：%s）" % (stamp, avail), code="backup_not_found")
    bdir = root / BACKUP_DIR / key / stamp
    rec = _record(root, key, stamp)
    if rec is None:
        raise UpdateError("備份 %s 的 apply.json 讀不懂 ⇒ 備份已損壞，停止回滾" % stamp, code="backup_corrupt")
    if rec.get("status") == "in_progress":
        # 稽核 D S3R-M1：中斷的套用只准回滾「最新一份」——比它新的紀錄存在＝之後又動過，整檔還原會蓋掉它們
        newest = newest_record_any(root)
        if newest != (key, stamp):
            raise UpdateError("備份 %s 是中斷的套用，但全安裝之後還有 %s/%s ⇒ 不回滾到它（lock 與狀態檔是共用的，"
                              "整檔還原會蓋掉之後的套用；稽核 D P8）" % (stamp, newest[0], newest[1]),
                              code="interrupted_not_latest")
        base = rec.get("prod_base_commit")
        if base and deployed_commit(root) != base:
            raise UpdateError("正式機已換成另一個完整包（%s ≠ 套用時的 %s）⇒ 不回滾這個模組包"
                              % (str(deployed_commit(root))[:8], base[:8]), code="base_changed")
    else:
        # 稽核 D S3-M2：整檔還原只在「套用完成之後沒有任何其他寫入」時才安全
        if "files_after" in rec and _tree_hashes(root, key) != rec["files_after"]:
            raise UpdateError("模組 %s 在這次套用（%s）之後又被改過 ⇒ 不回滾到它之前（會蓋掉之後的改動）" % (key, stamp), code="module_changed")
        if "state_after" in rec:
            cur = _state_hashes(root)
            changed = sorted(r for r in rec["state_after"] if cur.get(r) != rec["state_after"][r])
            if changed:
                raise UpdateError("這次套用之後又有別的寫入（%s）⇒ 不回滾（整檔還原會蓋掉之後的套用）" % "、".join(changed), code="state_changed")
        base = rec.get("prod_base_commit")
        if base and deployed_commit(root) != base:
            raise UpdateError("正式機已換成另一個完整包（%s ≠ 套用時的 %s）⇒ 不回滾這個模組包"
                              % (str(deployed_commit(root))[:8], base[:8]), code="base_changed")
    _restore_from(root, key, bdir, rec)
    rec["status"] = "rolled_back"
    _write_record(bdir, rec)
    (bdir / "rollback.json").write_text(json.dumps({"rolled_back_at": time.strftime("%Y%m%d_%H%M%S")}) + "\n",
                                        encoding="utf-8")
    return rec, stamp


# ── CLI ──────────────────────────────────────────────────────────────────

def _emit(ok, **kw):
    """--json：給 apply_module_update.ps1 解析的一行（ASCII，傳輸不受主控台編碼影響）。"""
    print("MODULE_UPDATE_RESULT " + json.dumps(dict(ok=ok, **kw), ensure_ascii=True))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--key", required=True)
    b.add_argument("--prod-base", required=True, help="正式機目前的 commit（出貨判等級的起點）")
    b.add_argument("--out", default=str(REPO / "deploy_packages" / "module_updates"))
    b.add_argument("--commit", default="HEAD")
    b.add_argument("--overlay", action="append", default=[], help="正式機已套用的模組覆蓋 key=sha256")
    c = sub.add_parser("check")
    c.add_argument("--pkg", required=True)
    pf = sub.add_parser("preflight")
    pf.add_argument("--root", required=True)
    pf.add_argument("--pkg", required=True)
    pf.add_argument("--require-base", action="store_true")
    pf.add_argument("--json", action="store_true")
    a = sub.add_parser("apply")
    a.add_argument("--root", required=True)
    a.add_argument("--pkg", required=True)
    a.add_argument("--allow-downgrade", action="store_true")
    a.add_argument("--require-base", action="store_true")
    a.add_argument("--json", action="store_true")
    a.add_argument("--stamp", help="備份名（yyyyMMdd_HHmmss[_微秒]）；apply_module_update.ps1 開頭就定好")
    r = sub.add_parser("rollback")
    r.add_argument("--root", required=True)
    r.add_argument("--key", required=True)
    r.add_argument("--backup")
    r.add_argument("--json", action="store_true")
    lst = sub.add_parser("list")
    lst.add_argument("--root", required=True)
    lst.add_argument("--json", action="store_true", help="正式機可見性（主持裁示）：模組版本、備份、覆蓋紀錄、部署 commit")
    args = ap.parse_args(argv)
    as_json = getattr(args, "json", False)
    try:
        if args.cmd == "build":
            if _git("status", "--porcelain", "--", "backend/modules/%s" % args.key):
                raise UpdateError("backend/modules/%s 有未 commit 的改動 ⇒ 先 commit（只打包已 commit 的內容）" % args.key)
            pkg = ship(args.key, args.out, args.prod_base, args.commit, dict(o.split("=", 1) for o in args.overlay))
            print("✓ 模組更新包：%s" % pkg)
        elif args.cmd == "check":
            problems = check(args.pkg)
            if problems:
                print("✗ " + "\n✗ ".join(problems))
                return 1
            print("✓ 更新包一致")
        elif args.cmd == "preflight":
            key, lock, inst_ver = preflight(args.root, args.pkg, require_base=args.require_base)
            if as_json:
                _emit(True, key=key, from_version=inst_ver, to_version=lock["modules"][key]["version"],
                      has_migrations=(Path(args.pkg) / "backend" / "modules" / key / "migrations").is_dir())
            else:
                print("✓ 可以套用 %s：%s → %s" % (key, inst_ver or "（原本沒有）", lock["modules"][key]["version"]))
        elif args.cmd == "apply":
            rec, bdir = apply(args.root, args.pkg, args.allow_downgrade, args.require_base, args.stamp)
            if as_json:
                _emit(True, key=rec["key"], stamp=rec["applied_at"], from_version=rec["from_version"],
                      to_version=rec["to_version"], backup=str(bdir))
            else:
                print("✓ 已套用 %s：%s → %s（備份 %s）。⚠ 需重啟服務才生效。"
                      % (rec["key"], rec["from_version"] or "（原本沒有）", rec["to_version"], bdir))
        elif args.cmd == "rollback":
            rec, stamp = rollback(args.root, args.key, args.backup)
            if as_json:
                _emit(True, key=rec["key"], stamp=stamp, version=rec["from_version"])
            else:
                print("✓ 已回滾 %s 至套用前（備份 %s，雜湊逐一相等）。⚠ 需重啟服務才生效。" % (rec["key"], stamp))
        elif as_json:
            lock = json.loads((Path(args.root) / "backend" / PS.LOCK_NAME).read_text(encoding="utf-8"))
            _emit(True, deployed_commit=deployed_commit(args.root), overlays=overlays(args.root),
                  modules={k: {"version": e.get("version") if isinstance(e, dict) else e, "backups": backups(args.root, k)}
                           for k, e in sorted((lock.get("modules") or {}).items())})
        else:
            lock = json.loads((Path(args.root) / "backend" / PS.LOCK_NAME).read_text(encoding="utf-8"))
            for k, e in sorted((lock.get("modules") or {}).items()):
                print("%-20s %-10s 備份：%s" % (k, e.get("version") if isinstance(e, dict) else e,
                                              "、".join(backups(args.root, k)) or "無"))
    except UpdateError as e:
        if as_json:
            _emit(False, code=e.code, error=str(e), stamp=getattr(args, "stamp", None) or getattr(args, "backup", None))
        else:
            print("✗ %s" % e)
        return 2
    except Exception as e:                  # noqa: BLE001  §10：非預期例外也要印一行（ps1 視為 module_copy_failed 並用 stamp 回滾）
        if as_json:
            _emit(False, code="unexpected", error="%s: %s" % (type(e).__name__, e),
                  stamp=getattr(args, "stamp", None) or getattr(args, "backup", None))
            return 3
        raise
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
