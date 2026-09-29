# -*- coding: utf-8 -*-
"""更新標註：某一次更新（列車／出貨包）從上一個已部署 commit 到這一次，**動到哪些模組、版號怎麼變**。

用法：
  python tools/platform/update_annotation.py --to <SHA> [--from <SHA>] [--out <json>]
        [--render-runplan] [--render-stepfile] [--check-stepfile <步驟檔.md>]

為什麼（使用者 2026-09-29）：每次更新都標註動到哪些模組（含版號），目的是之後只重驗動到的模組。
以前這份資訊有三個各自手寫／各自重算的地方：RUN-PLAN 班次紀錄（手寫）、正式機步驟檔 3 的 #7「允許的版本變化」（手寫）、
稽核與演練（各自從 git 差異重算），彼此不對帳。這支把它變成**一份機器產出的清單**，四處共用：
  ① 發布包內 `backend/update_annotation.json`（建包端寫；被 package.sha256 涵蓋）　② RUN-PLAN 一行（--render-runplan）
  ③ 步驟檔 #7 的允許清單（--render-stepfile／--check-stepfile 對帳）　④ `modtest --annotation <json>` 依清單選題。

不新造判定：檔案分組沿用 `deploy_insights.module_changes`（modules.json），版號取兩端的 module.json、`CORE_VERSION` 取兩端的 core/registry.py。
--from 預設＝tests/_prod_baseline.py 的 BASELINE（正式機已部署的那一版，每次部署後由部署者更新）。

判不了的不猜：兩端 module.json 讀不到 ⇒ 該模組版號標 "unknown"、整份 complete=false。
動了程式檔卻沒升版號 ⇒ warnings（**警告不擋**，使用者裁定 2026-09-30）。
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "backend" / "tools"))

FORMAT = 1
#: 「只是文件／測試」的路徑：動了它們不算「動了程式」，所以不要求升版
_NON_CODE = re.compile(r"(^|/)(tests?|__pycache__)/|\.md$|CHANGELOG", re.I)


def _git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError("git %s 失敗：%s" % (" ".join(args), (r.stderr or r.stdout).strip()))
    return r.stdout


def _show(repo, ref, rel):
    r = subprocess.run(["git", "-C", str(repo), "show", "%s:%s" % (ref, rel)], capture_output=True)
    return r.stdout.decode("utf-8-sig", "replace") if r.returncode == 0 else None


def module_version(repo, ref, key):
    """⇒ 版號字串；該 ref 沒有這個模組 ⇒ None；有檔但讀不懂 ⇒ "unknown"。"""
    raw = _show(repo, ref, "backend/modules/%s/module.json" % key)
    if raw is None:
        return None
    try:
        return str(json.loads(raw).get("version") or "unknown")
    except ValueError:
        return "unknown"


def core_version(repo, ref):
    raw = _show(repo, ref, "backend/core/registry.py")
    m = re.search(r'^CORE_VERSION\s*=\s*"([^"]+)"', raw or "", re.M)
    return m.group(1) if m else "unknown"


def prod_baseline(repo=REPO):
    p = Path(repo) / "backend" / "tests" / "_prod_baseline.py"
    m = re.search(r'^BASELINE\s*=\s*"([0-9a-f]+)"', p.read_text(encoding="utf-8") if p.exists() else "", re.M)
    return m.group(1) if m else None


def build(repo, base, head):
    import deploy_insights as DI
    repo = Path(repo)
    full_base = _git(repo, "rev-parse", base).strip()
    full_head = _git(repo, "rev-parse", head).strip()
    modules_json = repo / "docs" / "platform" / "modules.json"
    reg = json.loads(modules_json.read_text(encoding="utf-8"))
    key_of = {gid: g["key"] for gid, g in reg.get("modules", {}).items() if g.get("key")}
    all_keys = sorted(key_of.values())
    ch = DI.module_changes(repo, full_base, full_head, modules_json)
    l1 = {"changed": False, "files": []}
    by_key, warnings, complete = {}, [], True
    for g in ch["groups"]:
        gid = g["id"]
        if gid == "L1":
            l1 = {"changed": True, "files": g["files"]}
            continue
        for f in g["files"]:
            # 模組資料夾內的檔一律依路徑歸屬（modules.json 的 units 沒登記到的新檔也不會掉進 OTHER 而被漏標）；
            # 模組宣告的頁面／js 走 modules.json 的組（gid → key）
            pm = re.match(r"backend/modules/([^/]+)/", f)
            k = pm.group(1) if pm else key_of.get(gid)
            if k:
                e = by_key.setdefault(k, {"files": [], "changelog": [], "name": ""})
                e["files"].append(f)
        if key_of.get(gid):
            e = by_key.setdefault(key_of[gid], {"files": [], "changelog": [], "name": ""})
            e["changelog"] = g["changelog"]
            e["name"] = g["name"]
    mods = []
    for key, e in by_key.items():
        vf, vt = module_version(repo, full_base, key), module_version(repo, full_head, key)
        if "unknown" in (vf, vt):
            complete = False
        code = [f for f in e["files"] if not _NON_CODE.search(f)]
        mods.append({"key": key, "name": e["name"], "from": vf, "to": vt, "files": sorted(e["files"]), "changelog": e["changelog"]})
        if code and vf == vt and vf not in (None, "unknown"):
            warnings.append("模組 %s 動了 %d 個程式檔（例如 %s）但版號沒升（%s）" % (key, len(code), sorted(code)[0], vf))
    cf, ct = core_version(repo, full_base), core_version(repo, full_head)
    if "unknown" in (cf, ct):
        complete = False
    if l1["changed"] and cf == ct and cf != "unknown":
        code = [f for f in l1["files"] if not _NON_CODE.search(f)]
        if code:
            warnings.append("共用核心（L1）動了 %d 個程式檔（例如 %s）但 CORE_VERSION 沒升（%s）" % (len(code), code[0], cf))
    changed_keys = set(by_key)
    return {"format": FORMAT, "from": full_base, "to": full_head, "complete": complete,
            "l1": {"changed": l1["changed"], "core_from": cf, "core_to": ct, "file_count": len(l1["files"]), "files": l1["files"],
                   "note": "共用核心有動：影響所有模組（驗證範圍沿用 modtest 的反向依賴擴大）" if l1["changed"] else ""},
            "modules": sorted(mods, key=lambda m: m["key"]),
            "unchanged_modules": [k for k in all_keys if k not in changed_keys],
            "warnings": warnings}


def render_runplan(a):
    parts = []
    for m in a["modules"]:
        parts.append("%s %s→%s" % (m["key"], m["from"] or "（新）", m["to"] or "（移除）") if m["from"] != m["to"]
                     else "%s %s（版號未變）" % (m["key"], m["to"]))
    core = ("；共用核心 %s→%s" % (a["l1"]["core_from"], a["l1"]["core_to"]) if a["l1"]["core_from"] != a["l1"]["core_to"]
            else ("；共用核心有動、版號 %s 未變" % a["l1"]["core_to"] if a["l1"]["changed"] else ""))
    warn = "；⚠ " + "；".join(a["warnings"]) if a["warnings"] else ""
    inc = "" if a["complete"] else "；⚠ 標註不完整（有版號讀不到）"
    return "動到的模組（%s→%s）：%s%s%s%s" % (a["from"][:8], a["to"][:8], "、".join(parts) or "無", core, warn, inc)


def allowed_changes(a):
    """步驟檔 3 #7 用：{key: 新版號}——版號真的變了的模組。"""
    return {m["key"]: m["to"] for m in a["modules"] if m["from"] != m["to"] and m["to"] not in (None, "unknown")}


def render_stepfile(a):
    ch = allowed_changes(a)
    if not ch:
        return "唯一允許的版本變化：無（所有模組版本都不變）"
    return "唯一允許的版本變化：" + "、".join("`%s`→`%s`" % (k, v) for k, v in sorted(ch.items())) + "，其餘模組版本不變"


_STEP_RE = re.compile(r"唯一允許的版本變化：([^\n；;]*)")


def check_stepfile(a, text):
    """步驟檔手寫的「唯一允許的版本變化」與標註不一致 ⇒ 問題清單（空＝一致）。找不到那一句 ⇒ 也是問題。"""
    m = _STEP_RE.search(text)
    if not m:
        return ["步驟檔裡找不到「唯一允許的版本變化：…」這一句"]
    written = dict(re.findall(r"`([a-z0-9_]+)`\s*→\s*`([^`]+)`", m.group(1)))
    want = allowed_changes(a)
    probs = []
    for k in sorted(set(want) | set(written)):
        if written.get(k) != want.get(k):
            probs.append("模組 %s：步驟檔寫 %s，標註是 %s" % (k, written.get(k, "（沒寫）"), want.get(k, "（沒有版號變化）")))
    return probs


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--to", required=True)
    ap.add_argument("--from", dest="base")
    ap.add_argument("--repo", default=str(REPO))
    ap.add_argument("--out")
    ap.add_argument("--render-runplan", action="store_true")
    ap.add_argument("--render-stepfile", action="store_true")
    ap.add_argument("--check-stepfile", metavar="MD")
    x = ap.parse_args(argv)
    base = x.base or prod_baseline(x.repo)
    if not base:
        print("ANNOTATION_FAIL 沒有 --from，也讀不到 tests/_prod_baseline.py 的 BASELINE")
        return 1
    try:
        a = build(x.repo, base, x.to)
    except (RuntimeError, OSError, ValueError, KeyError) as e:
        print("ANNOTATION_FAIL %s" % e)
        return 1
    if x.out:
        Path(x.out).write_text(json.dumps(a, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if x.render_runplan:
        print(render_runplan(a))
    if x.render_stepfile:
        print(render_stepfile(a))
    rc = 0
    if x.check_stepfile:
        probs = check_stepfile(a, Path(x.check_stepfile).read_text(encoding="utf-8"))
        for p in probs:
            print("STEPFILE_MISMATCH %s" % p)
        rc = 1 if probs else 0
    for w in a["warnings"]:
        print("ANNOTATION_WARN %s" % w)
    print("ANNOTATION_OK %s→%s 模組 %d 個%s%s" % (a["from"][:8], a["to"][:8], len(a["modules"]),
                                               "" if a["complete"] else "（不完整）", "，警告 %d" % len(a["warnings"]) if a["warnings"] else ""))
    return rc


if __name__ == "__main__":
    sys.exit(main())
