# -*- coding: utf-8 -*-
"""棘輪基線的三道檢查（text_anchor_scan、audit_scope_scan 共用；T87 A2，h11 審查 M2）。

[單位] tools:ratchet   [層] 工具   [穩定度] 內部
[不變式]
  * 基線 JSON 形狀：{"total": N, "files": {檔: 命中數}, "hatches": {檔: 逃生口數}（可省略）}。
  * 為什麼要三道：只比「現場命中 vs 基線」擋不住 (i) 上限常數不跟著下降、重寫基線偷渡新增；(ii) 這個檔 +3、那個檔 −3，總數不變；
    (iii) 檔案變乾淨後基線還留著空位，之後的修改把空位補滿。
      1. slack：基線的每個數字都必須貼合現場（基線 > 現場＝要重寫基線，而且只准往下寫）。
      2. vs_base：基線本身與合併基準上的基線比，任何一檔變多（新檔、改名後變多都算；改名用 git rename 偵測對回舊名）或總數變多＝紅。
      3. 不另存上限常數：上限就是合併基準上的基線（常數會過期、又是第二個要審的數字）。
  * 抓不到合併基準（沒有 git、沒有 origin 分支）⇒ 回報 status="no_base" 與原因，呼叫端必須把它印成「未跑」，不能當通過。
"""
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BASE_CANDIDATES = ("origin/master", "origin/main", "master", "main")


def _git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, r.stdout


def slack(current, base_files):
    """⇒ [(檔, 現場, 基線)]：基線高於現場（可以、也必須往下重寫）。"""
    return [(f, current.get(f, 0), n) for f, n in sorted(base_files.items()) if n > current.get(f, 0)]


def vs_base(new_files, old_files, renames=None):
    """⇒ [(檔, 新基線, 舊基線)]：新基線的某檔高於合併基準的基線（改名檔以舊名的數字為準）。"""
    renames = renames or {}
    return [(f, n, old_files.get(renames.get(f, f), 0)) for f, n in sorted(new_files.items()) if n > old_files.get(renames.get(f, f), 0)]


def merge_base(repo=REPO, head="HEAD", env_base=None):
    """⇒ (sha 或 None, 說明)。env_base（例如環境變數 MOTRIX_RATCHET_BASE）優先；否則 merge-base HEAD 與第一個存在的主線分支。"""
    if env_base:
        rc, out = _git(repo, "rev-parse", "--verify", "--quiet", env_base + "^{commit}")
        return (out.strip(), "env") if rc == 0 and out.strip() else (None, "指定的基準 %s 不存在" % env_base)
    for cand in BASE_CANDIDATES:
        rc, out = _git(repo, "merge-base", head, cand)
        if rc == 0 and out.strip():
            return out.strip(), cand
    return None, "找不到主線分支（%s）的 merge-base" % "、".join(BASE_CANDIDATES)


def git_show_json(rel, ref, repo=REPO):
    rc, out = _git(repo, "show", "%s:%s" % (ref, rel))
    if rc != 0:
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


def git_renames(base, repo=REPO, head="HEAD"):
    """⇒ {新路徑: 舊路徑}（git 的改名偵測；內容相近才算）。"""
    rc, out = _git(repo, "diff", "-M", "--name-status", "--diff-filter=R", base, head)
    ren = {}
    for ln in out.splitlines():
        parts = ln.split("\t")
        if len(parts) >= 3 and parts[0].startswith("R"):
            ren[parts[2]] = parts[1]
    return ren


def check_against_base(rel_baseline, new_baseline, repo=REPO, env_base=None):
    """⇒ {"status": "ok"|"violation"|"no_base", "violations": [...], "note": str, "base": sha}。
    new_baseline＝現場讀到的基線 dict。基準上沒有這份基線檔（第一次建立）⇒ status=ok、note 說明。"""
    base, why = merge_base(repo, env_base=env_base)
    if base is None:
        return {"status": "no_base", "violations": [], "note": why, "base": None}
    old = git_show_json(rel_baseline, base, repo)
    if old is None:
        return {"status": "ok", "violations": [], "note": "合併基準 %s 上沒有 %s（第一次建立這份基線）" % (base[:9], rel_baseline), "base": base}
    ren = git_renames(base, repo)
    bad = vs_base(new_baseline.get("files", {}), old.get("files", {}), ren)
    bad += [("%s [逃生口]" % f, n, o) for f, n, o in vs_base(new_baseline.get("hatches", {}), old.get("hatches", {}), ren)]
    if sum(new_baseline.get("files", {}).values()) > sum(old.get("files", {}).values()):
        bad.append(("<總數>", sum(new_baseline["files"].values()), sum(old["files"].values())))
    return {"status": "violation" if bad else "ok", "violations": bad, "note": "對照合併基準 %s（%s）" % (base[:9], why), "base": base}
