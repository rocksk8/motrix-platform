# -*- coding: utf-8 -*-
"""apply_update.ps1 的「刪除／新增」計畫：platform 安裝套 platform 包的日常更新（UPGRADE-RUNBOOK §8）。

[單位] tool:apply_plan    [層] 部署工具（正式機由 apply_update.ps1 呼叫，跑的是**新包裡**這一份）
[公開介面] package_files, deletable, make_plan, interrupted_module_applies, execute, cleanup_added, not_in_snapshot, cleanup_not_in_snapshot,
    verify_snapshot, write_baseline
[不變式] 只刪程式目錄（backend 程式、frontend、tools、product）裡 classify==program 的檔；資料／DB／設定／
    uploads／PDF 一律不碰；刪除上限超過 ⇒ 不動任何檔（exit 3）；每一個要刪的檔在快照裡都要找得到
[契約題] tests/platform/test_apply_plan_2026_09_28.py
[注意] 分類用**新包的** core.upgrade.classify（與 V9→新版升級同一支判定）

為什麼需要它：apply_update.ps1 的 robocopy 只加不刪，而模組載入器看的是資料夾、不是 lock ⇒
包裡刪掉、改名或排除的模組資料夾與頁面會繼續被載入。刪除的依據（聯集）：
  baseline          上一次成功套用時寫下的 `backend/.deployed_files.json`（舊版包的程式檔清單）
                    有、而新包沒有的檔
  lock_excluded     新包 modules.lock.json 的 excluded：安裝目錄裡那個模組資料夾
  lock_removed_page 新包 modules.lock.json 的 removed_pages
  orphan_module     安裝目錄有 module.json、而新包沒有的模組資料夾（載入器會載它）
沒有 baseline（V9→新版轉換後的第一次）⇒ 其他「安裝目錄有、新包沒有」的程式檔**只列出不刪**
（no_baseline_candidates），成功後寫 baseline，下一次起就有依據。

子命令（exit：0 完成／2 拒絕或失敗／3 刪除清單超過上限）：
  plan            --root R --pkg P --out plan.json [--max N] [--log 文字檔]
  verify-snapshot --plan plan.json --snapshot <rollback_snapshots\\<ts>>
  execute         --root R --pkg P --plan plan.json
  cleanup-added   --root R --pkg P --plan plan.json        （自動回滾：刪掉這次新增的程式檔）
  baseline        --root R --plan plan.json                 （成功後寫 backend/.deployed_files.json）
  cleanup-snapshot --root R --pkg P --snapshot S [--dry-run] [--max N]
                  （回滾：安裝目錄有、快照沒有的程式檔一律刪——D 稽核 DM2：回滾到較舊的快照時，
                   之後幾次套用新增的模組只靠「那一次的 added」刪不乾淨；快照裡沒有的頂層目錄整個略過）
"""
import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime

#: 頁面目錄：「安裝包／安裝目錄」的相對路徑（不是執行中的原始碼樹，所以不走 core.source_tree；
#: test_page_paths_centralized 基線登記本檔 1 處，主持裁示 2026-09-28 第十四班）
PAGES_REL = "frontend/pages"
#: 刪除只准在這幾個目錄底下（相對安裝根目錄）
PROGRAM_SCOPES = ("backend/", "frontend/", "tools/", "product/")
#: 部署工具自己的狀態檔：不列進包清單、不刪
BASELINE_REL = "backend/.deployed_files.json"
#: .apply.lock（UPDATE-DELIVERY §9.2；D 稽核 DO1）：套用中一定存在，不可被列進候選、被快照寫回或被刪
STATE_FILES = (BASELINE_REL, "backend/.apply.lock")
#: 執行期狀態檔（檔名結尾）：停用清單快取 `<主庫>.modules_disabled.json`（core.paths.modules_disabled_cache）
STATE_SUFFIXES = (".modules_disabled.json",)
LOCK_REL = "backend/modules.lock.json"
_KEY_RE = re.compile(r"^[A-Za-z0-9_]+$")

_upgrade = None


class Refuse(Exception):
    pass


def load_classifier(pkg):
    """新包的 core.upgrade（classify／walk／PACKAGE_DEFAULT_CONFIG）。"""
    global _upgrade
    if _upgrade is None:
        sys.path.insert(0, os.path.join(pkg, "backend"))
        from core import upgrade as u
        _upgrade = u
    return _upgrade


def _fold(rel):
    """比對「是不是同一個檔」的鍵（AH-M1）：正式機是 Windows、檔案系統不分大小寫 ⇒ 一律 casefold。
    在分大小寫的檔案系統上會把兩個只差大小寫的檔當成同一個 ⇒ 少刪、不會多刪（保守方向）。"""
    return rel.casefold()


def _in_scope(rel):
    return rel.startswith(PROGRAM_SCOPES) and ".." not in rel.split("/")


def deletable(rel, u):
    """只有程式目錄裡、分類為 program、不是設定預設檔、不是工具狀態檔的才准刪。"""
    return (_in_scope(rel) and rel not in STATE_FILES and not rel.endswith(STATE_SUFFIXES)
            and rel not in u.PACKAGE_DEFAULT_CONFIG and u.classify(rel) == "program")


def package_files(pkg, u):
    return sorted(rel for rel, _ in u.walk(pkg) if deletable(rel, u))


def _read_json(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def _module_dirs(backend):
    d = os.path.join(backend, "modules")
    if not os.path.isdir(d):
        return {}
    return {n: os.path.join(d, n) for n in sorted(os.listdir(d))
            if os.path.isfile(os.path.join(d, n, "module.json"))}


def _files_under(root, rel_dir, u):
    base = os.path.join(root, rel_dir)
    out = []
    for rel, _ in u.walk(base):
        out.append(rel_dir.rstrip("/") + "/" + rel)
    return out


#: 測試注入點：(manifest) -> (ok, reason)。None ⇒ 用新包的 helpers.licensing 讀安裝目錄的授權金鑰（與正式機啟動同一支判定）
_license_check = None


def _license_check_for(root, pkg):
    load_classifier(pkg)                                        # 新包的 backend 已在 sys.path
    try:
        from helpers import licensing as L
    except Exception as e:                                      # 算不出來就不動（不猜）
        raise Refuse("讀不到授權判定（helpers.licensing：%s），不處理模組資料夾" % e)
    L.LICENSE_PATH = os.path.join(root, "backend", "license.key")
    gate = L.LICENSE_GATE_ENABLED
    status = L.verify_license() if gate else {}
    return lambda manifest: L.module_licensed(manifest, status, gate)


#: 單模組套用的備份目錄（tools/platform/module_update.BACKUP_DIR；安裝根目錄底下，不在 PROGRAM_SCOPES）
MODULE_BACKUP_DIR = "module_backups"


def interrupted_module_applies(root):
    """<ROOT>/module_backups/<模組>/<備份>/apply.json 的 status＝in_progress ⇒ [(模組, 備份)]。讀不懂的紀錄也算（不猜）。"""
    d = os.path.join(root, MODULE_BACKUP_DIR)
    out = []
    for key in (sorted(os.listdir(d)) if os.path.isdir(d) else []):
        kd = os.path.join(d, key)
        for st in (sorted(os.listdir(kd)) if os.path.isdir(kd) else []):
            rec_p = os.path.join(kd, st, "apply.json")
            if not os.path.isfile(rec_p):
                continue
            try:
                status = (_read_json(rec_p) or {}).get("status", "applied")
            except ValueError:
                status = "in_progress"
            if status == "in_progress":
                out.append((key, st))
    return out


def make_plan(root, pkg, max_files):
    u = load_classifier(pkg)
    root, pkg = os.path.abspath(root), os.path.abspath(pkg)
    new = package_files(pkg, u)
    new_set = set(new)
    new_fold = {_fold(r) for r in new}      # AH-M1：Windows 不分大小寫，只差大小寫的改名＝同一個檔
    lock_path = os.path.join(pkg, LOCK_REL)
    lock = _read_json(lock_path) if os.path.isfile(lock_path) else None
    if lock is not None and lock.get("kind") != "full_package":
        raise Refuse("部署包的 modules.lock.json kind=%r：apply_update 只套完整包（full_package）" % lock.get("kind"))
    pending = interrupted_module_applies(root)
    if pending:
        raise Refuse("安裝目錄有中斷的單模組套用（%s）：先用套用腳本的回滾模式回到套用前——使用者同意後執行 "
                     "`powershell -ExecutionPolicy Bypass -File <ROOT>\\backend\\tools\\apply_module_update.ps1 "
                     "-Rollback -ModuleKey <模組> -Backup <備份> -Yes`（模組／備份即上面的 <模組>/<備份>；新增了 migration 會被拒，"
                     "要連資料庫還原須使用者同意後再加 -IncludeDatabase -ConfirmDatabaseOverwrite；"
                     "見 docs/platform/MODULE-UPDATE-PROD-INSTRUCTIONS.md §5），再套完整包（B55／稽核 D P8：lock 與狀態檔是全安裝共用）"
                     % "、".join("%s/%s" % kv for kv in pending))
    base_path = os.path.join(root, BASELINE_REL)
    baseline = _read_json(base_path) if os.path.isfile(base_path) else None
    if baseline is not None and not isinstance(baseline.get("files"), list):
        raise Refuse("%s 格式不對（缺 files 清單）" % base_path)

    delete = {}
    kept_non_program = []
    module_dirs = []          # 2026-09-28 起一律空：完整包套用不刪模組資料夾（使用者裁示，CORE-SPEC「完整包與客戶加購模組」）

    # ── 模組：安裝目錄有、新包沒有 ⇒ 依授權決定（D 稽核 DO3／A 稽核 AH-S1；使用者裁示 2026-09-28）──
    #   授權有 ⇒ 拒絕套用（完整包要依授權帶齊；絕不靜默刪掉客戶付費的模組）；授權閘門關閉視為全部有授權
    #   授權沒有（到期／未授權）⇒ 只停用不刪：資料夾與它的頁面都保留（載入器依授權不載入，續約立刻恢復）
    #   ⇒ 這些模組的檔案不會經任何刪除來源（baseline、lock、候選）被刪
    pkg_mods = _module_dirs(os.path.join(pkg, "backend"))
    inst_mods = _module_dirs(os.path.join(root, "backend"))
    targets = {}
    if lock is not None:
        for key in lock.get("excluded") or []:
            if not _KEY_RE.match(str(key)):
                raise Refuse("modules.lock.json excluded 有不合法的模組名：%r" % key)
            if key in inst_mods and key not in pkg_mods:
                targets[key] = "lock_excluded"
    for key in inst_mods:
        if key not in pkg_mods and key not in targets:
            targets[key] = "orphan_module"
    refuse, kept_modules, protected, protected_pages = [], [], [], set()
    if targets:
        check = _license_check or _license_check_for(root, pkg)
        for key, why in sorted(targets.items()):
            try:
                manifest = _read_json(os.path.join(inst_mods[key], "module.json"))
            except Exception:
                manifest = {}
            if not isinstance(manifest, dict):
                manifest = {}
            manifest.setdefault("key", key)
            ok, reason = check(manifest)
            if ok:
                refuse.append("%s（%s）" % (key, reason or "授權有"))
            else:
                kept_modules.append({"key": key, "why": why, "license": reason})
            protected.append("backend/modules/%s/" % key)
            for page in manifest.get("pages") or []:
                protected_pages.add(PAGES_REL + "/" + str(page).replace("\\", "/").split("/")[-1])
    if refuse:
        raise Refuse("以下模組安裝目錄有、授權有，而新包沒有 ⇒ 拒絕套用（完整包要依客戶授權帶齊模組）：%s"
                     % "、".join(refuse))

    def guarded(rel):
        return rel.startswith(tuple(protected)) or rel in protected_pages

    def add(rel, reason):
        if rel in new_set or _fold(rel) in new_fold or rel in delete:
            return
        if not os.path.isfile(os.path.join(root, rel)):
            return
        if guarded(rel):
            return
        if deletable(rel, u):
            delete[rel] = reason
        else:
            kept_non_program.append(rel)

    if baseline is not None:
        for rel in sorted(set(baseline["files"]) - new_set):
            if _in_scope(rel):
                add(rel, "baseline")

    if lock is not None:
        for page in lock.get("removed_pages") or []:
            page = str(page).replace("\\", "/")
            if not page.startswith(PAGES_REL + "/") or ".." in page.split("/"):
                raise Refuse("modules.lock.json removed_pages 有不合法的路徑：%r" % page)
            add(page, "lock_removed_page")

    candidates = []
    if baseline is None:
        for rel, _ in u.walk(root):
            if _in_scope(rel) and _fold(rel) not in new_fold and rel not in delete and deletable(rel, u) \
                    and not guarded(rel):
                candidates.append(rel)

    added = [rel for rel in new if not os.path.isfile(os.path.join(root, rel))]
    manifest_path = os.path.join(pkg, "deploy_manifest.json")
    commit = _read_json(manifest_path).get("commit") if os.path.isfile(manifest_path) else None
    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "root": root, "pkg": pkg, "commit": commit,
        "baseline_present": baseline is not None,
        "baseline_commit": baseline.get("commit") if baseline else None,
        "lock_present": lock is not None,
        "max": max_files,
        "over_limit": len(delete) > max_files,
        "delete": [{"rel": r, "reason": delete[r]} for r in sorted(delete)],
        "module_dirs": sorted(module_dirs),
        "kept_modules": kept_modules,
        "kept_non_program": sorted(set(kept_non_program)),
        "no_baseline_candidates": sorted(candidates),
        "added": added,
        "package_files": new,
    }


def plan_text(plan):
    lines = ["apply_plan %s  commit=%s" % (plan["created_at"], plan["commit"]),
             "root=%s" % plan["root"], "pkg=%s" % plan["pkg"],
             "baseline=%s（commit %s）  lock=%s" % (plan["baseline_present"], plan["baseline_commit"], plan["lock_present"]),
             "DELETE %d 檔（上限 %d）：" % (len(plan["delete"]), plan["max"])]
    lines += ["  - [%s] %s" % (d["reason"], d["rel"]) for d in plan["delete"]]
    lines.append("模組資料夾（整個移除）：%s" % (", ".join(plan["module_dirs"]) or "無"))
    for m in plan.get("kept_modules") or []:
        lines.append("  保留（未授權，只停用不刪）：%s（%s；%s）" % (m["key"], m["why"], m["license"]))
    if plan["kept_non_program"]:
        lines.append("保留（不是程式檔，不刪）%d 檔：" % len(plan["kept_non_program"]))
        lines += ["  = %s" % r for r in plan["kept_non_program"]]
    if not plan["baseline_present"]:
        lines.append("沒有 baseline：以下 %d 個「安裝目錄有、新包沒有」的程式檔只列出、不刪（成功後寫 baseline）："
                     % len(plan["no_baseline_candidates"]))
        lines += ["  ? %s" % r for r in plan["no_baseline_candidates"]]
    lines.append("ADDED %d 檔（自動回滾時刪除）" % len(plan["added"]))
    return "\n".join(lines)


def _inside(path, root):
    path, root = os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.realpath(root))
    return path.startswith(root + os.sep)


def _prune(root, rel_dirs, stop_at):
    """rel_dirs 由深到淺：只剩 __pycache__ 的目錄連同 __pycache__ 刪掉；空目錄刪掉。不越過 stop_at。"""
    seen = set()
    todo = sorted({d for d in rel_dirs}, key=lambda d: -d.count("/"))
    while todo:
        rel = todo.pop(0)
        if rel in seen or rel.rstrip("/") in stop_at or not _in_scope(rel + "/"):
            continue
        seen.add(rel)
        full = os.path.join(root, rel)
        if not os.path.isdir(full) or not _inside(full, root):
            continue
        names = os.listdir(full)
        if all(n == "__pycache__" and os.path.isdir(os.path.join(full, n)) for n in names):
            for n in names:
                shutil.rmtree(os.path.join(full, n))
            os.rmdir(full)
            parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
            if parent:
                todo.append(parent)
                todo.sort(key=lambda d: -d.count("/"))


_STOP_AT = ("backend", "frontend", "tools", "product", "backend/modules", PAGES_REL)


def _remove_listed(root, rels, u):
    removed, errors = [], []
    for rel in rels:
        full = os.path.join(root, rel)
        if not deletable(rel, u) or not _inside(full, root):
            errors.append("%s：不在可刪範圍（拒絕）" % rel)
            continue
        if not os.path.isfile(full):
            continue
        try:
            os.remove(full)
            removed.append(rel)
        except OSError as e:
            errors.append("%s：%s" % (rel, e))
    return removed, errors


def execute(root, pkg, plan):
    u = load_classifier(pkg)
    new_fold = {_fold(r) for r in plan["package_files"]}
    rels = [d["rel"] for d in plan["delete"] if _fold(d["rel"]) not in new_fold]
    removed, errors = _remove_listed(root, rels, u)
    for rel_dir in plan["module_dirs"]:          # 被移除模組的編譯快取一併清掉（資料檔若有則留著）
        full = os.path.join(root, rel_dir)
        if os.path.isdir(full) and _inside(full, root) and _in_scope(rel_dir + "/"):
            for dp, dns, _fns in os.walk(full, topdown=False):
                for d in dns:
                    if d == "__pycache__":
                        shutil.rmtree(os.path.join(dp, d), ignore_errors=True)
    dirs = set(plan["module_dirs"]) | {r.rsplit("/", 1)[0] for r in removed}
    _prune(root, dirs, _STOP_AT)
    return removed, errors


def cleanup_added(root, pkg, plan):
    u = load_classifier(pkg)
    removed, errors = _remove_listed(root, plan["added"], u)
    _prune(root, {r.rsplit("/", 1)[0] for r in removed}, _STOP_AT)
    return removed, errors


def not_in_snapshot(root, snapshot, u):
    """安裝目錄有、快照沒有的可刪程式檔（排序）。快照裡沒有的頂層程式目錄（舊快照沒有 tools／product）整個略過。"""
    out = []
    for top in PROGRAM_SCOPES:
        top = top.rstrip("/")
        if not os.path.isdir(os.path.join(snapshot, top)) or not os.path.isdir(os.path.join(root, top)):
            continue
        for rel in _files_under(root, top, u):
            if deletable(rel, u) and not os.path.isfile(os.path.join(snapshot, rel)):
                out.append(rel)
    return sorted(out)


def cleanup_not_in_snapshot(root, pkg, snapshot, max_files=500, dry_run=False):
    """回 (清單, removed, errors, over_limit)。超過上限或 dry_run ⇒ 不刪。"""
    u = load_classifier(pkg)
    rels = not_in_snapshot(root, snapshot, u)
    if dry_run or len(rels) > max_files:
        return rels, [], [], len(rels) > max_files
    removed, errors = _remove_listed(root, rels, u)
    _prune(root, {r.rsplit("/", 1)[0] for r in removed}, _STOP_AT)
    return rels, removed, errors, False


def verify_snapshot(plan, snapshot):
    """每一個要刪的檔在快照裡都要有（回滾靠它還原）。回缺的清單。"""
    return [d["rel"] for d in plan["delete"] if not os.path.isfile(os.path.join(snapshot, d["rel"]))]


def write_baseline(root, plan):
    path = os.path.join(root, BASELINE_REL)
    data = {"commit": plan["commit"], "written_at": datetime.now().isoformat(timespec="seconds"),
            "files": plan["package_files"]}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=0)
    os.replace(tmp, path)
    return path


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors="backslashreplace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("plan", "verify-snapshot", "execute", "cleanup-added", "baseline",
                                    "cleanup-snapshot"))
    ap.add_argument("--root")
    ap.add_argument("--pkg")
    ap.add_argument("--out")
    ap.add_argument("--plan")
    ap.add_argument("--snapshot")
    ap.add_argument("--log")
    ap.add_argument("--max", type=int, default=200)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "cleanup-snapshot":
            limit = a.max if a.max != 200 else 500
            rels, removed, errors, over = cleanup_not_in_snapshot(a.root, a.pkg, a.snapshot, limit, a.dry_run)
            for r in (removed if not (a.dry_run or over) else rels):
                print("  %s %s" % ("removed" if not (a.dry_run or over) else "would-remove", r))
            for e in errors:
                print("  ERROR %s" % e)
            if over:
                print("APPLY_SNAPCLEAN_OVER_LIMIT %d > %d" % (len(rels), limit))
                return 3
            if errors:
                return 2
            print("APPLY_SNAPCLEAN_%s %d" % ("PLAN" if a.dry_run else "OK", len(rels) if a.dry_run else len(removed)))
            return 0
        if a.cmd == "plan":
            plan = make_plan(a.root, a.pkg, a.max)
            with open(a.out, "w", encoding="utf-8") as f:
                json.dump(plan, f, ensure_ascii=False, indent=1)
            text = plan_text(plan)
            if a.log:
                os.makedirs(os.path.dirname(os.path.abspath(a.log)), exist_ok=True)
                with open(a.log, "w", encoding="utf-8") as f:
                    f.write(text + "\n")
            print(text)
            if plan["over_limit"]:
                print("APPLY_PLAN_OVER_LIMIT %d > %d" % (len(plan["delete"]), a.max))
                return 3
            print("APPLY_PLAN_OK delete=%d added=%d" % (len(plan["delete"]), len(plan["added"])))
            return 0
        plan = _read_json(a.plan)
        if a.cmd == "verify-snapshot":
            missing = verify_snapshot(plan, a.snapshot)
            for r in missing:
                print("  快照裡沒有：%s" % r)
            if missing:
                return 2
            print("APPLY_SNAPSHOT_OK %d" % len(plan["delete"]))
            return 0
        if a.cmd == "baseline":
            print("APPLY_BASELINE_OK %s" % write_baseline(a.root, plan))
            return 0
        fn = execute if a.cmd == "execute" else cleanup_added
        removed, errors = fn(a.root, a.pkg, plan)
        for r in removed:
            print("  removed %s" % r)
        for e in errors:
            print("  ERROR %s" % e)
        if errors:
            return 2
        print("APPLY_%s_OK %d" % ("DELETE" if a.cmd == "execute" else "CLEANUP", len(removed)))
        return 0
    except Refuse as e:
        print("APPLY_PLAN_REFUSED %s" % e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
