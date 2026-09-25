# -*- coding: utf-8 -*-
"""部署儀表板的唯讀分析（CORE-SPEC §9e D2／D6／D7）——純函式，不碰正式機。

- module_changes()：兩個 commit 之間，改動檔依 docs/platform/modules.json 分組，
  並列出各模組 CHANGELOG 在這段區間新增的行（「這一包會改到哪些模組」）。
- last_full()：讀 modtest --full 寫出的 tools/platform/.last_full.json，判斷
  「這個 commit 有沒有全綠的全量」。沒有檔 ≠ 跑過而失敗，兩者要分得開。
- upstream_ahead()：目前分支相對上游領先幾個 commit（取代寫死的 origin/master）。
"""
import json
import os
import subprocess
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _git(root, *args):
    r = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=30,
                       creationflags=CREATE_NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip() or f"git {' '.join(args)} failed")
    return r.stdout


# ── 檔案 → 單位 → 模組 ───────────────────────────────────────────────────

def unit_of(path: str):
    """repo 相對路徑 → dep_graph 單位名（對不到回 None）。"""
    p = path.replace("\\", "/")
    parts = p.split("/")
    if p.startswith("backend/modules/") and len(parts) >= 4:
        key = parts[2]
        if len(parts) == 4 and p.endswith(".py"):
            return f"mod:{key}/{Path(parts[3]).stem}"
        return f"moddir:{key}"                       # 模組資料夾內其他檔（tests、README、CHANGELOG…）
    if p.startswith("backend/core/") and len(parts) == 3 and p.endswith(".py"):
        return f"plat:{Path(parts[2]).stem}"
    if p.startswith("backend/core/"):
        return "platdir"                              # 底層資料夾內其他檔（CHANGELOG 等）⇒ L1
    if p.startswith("backend/routers/") and len(parts) == 3 and p.endswith(".py"):
        return f"router:{Path(parts[2]).stem}"
    if p.startswith("backend/helpers/") and len(parts) == 3 and p.endswith(".py"):
        return f"helper:{Path(parts[2]).stem}"
    if p.startswith("backend/") and len(parts) == 2 and p.endswith(".py"):
        return f"core:{Path(parts[1]).stem}"
    if p.startswith("frontend/pages/") and p.endswith(".html"):
        return "page:" + p[len("frontend/"):]
    if p.startswith("frontend/js/") and p.endswith(".js"):
        return "js:" + p[len("frontend/"):]
    return None


def load_groups(modules_json: Path) -> dict:
    """{單位名: 組代號}；模組資料夾以 moddir:<key> 對到其組。"""
    data = json.loads(Path(modules_json).read_text(encoding="utf-8"))
    out = {u: "L1" for u in data.get("L1", {}).get("units", [])}
    out["platdir"] = "L1"
    for gid, g in data.get("modules", {}).items():
        for u in g.get("units", []):
            out[u] = gid
        if g.get("key"):
            out[f"moddir:{g['key']}"] = gid
    return out, {gid: g.get("name", gid) for gid, g in data.get("modules", {}).items()}


def _changelog_added(root, base, head, path):
    try:
        diff = _git(root, "diff", "--unified=0", f"{base}..{head}", "--", path)
    except RuntimeError:
        return []
    return [l[1:] for l in diff.splitlines()
            if l.startswith("+") and not l.startswith("+++") and l[1:].strip()]


def module_changes(root, base: str, head: str, modules_json=None) -> dict:
    """base..head 的改動依模組分組。base／head 必須是這個 repo 認得的 commit，否則丟 RuntimeError。"""
    root = Path(root)
    modules_json = Path(modules_json or root / "docs" / "platform" / "modules.json")
    for c in (base, head):
        _git(root, "cat-file", "-e", f"{c}^{{commit}}")      # 不認得就讓呼叫端明說，不猜
    files = [f for f in _git(root, "diff", "--name-only", "--no-renames", f"{base}..{head}").splitlines() if f]
    groups, names = load_groups(modules_json)
    by = {}
    for f in files:
        u = unit_of(f)
        gid = groups.get(u) if u else None
        if gid is None:
            gid = "OTHER"
        by.setdefault(gid, {"files": [], "changelog": []})["files"].append(f)
    # 各模組 CHANGELOG 在區間內新增的行
    for gid, g in list(by.items()):
        key = None
        for u, gg in groups.items():
            if gg == gid and u.startswith("moddir:"):
                key = u.split(":", 1)[1]
        if key:
            by[gid]["changelog"] = _changelog_added(root, base, head, f"backend/modules/{key}/CHANGELOG.md")
    core_log = _changelog_added(root, base, head, "backend/core/CHANGELOG.md")
    if core_log:
        by.setdefault("L1", {"files": [], "changelog": []})["changelog"] = core_log
    order = sorted(by, key=lambda k: (k == "OTHER", k != "L1", k))
    return {
        "base": base, "head": head, "fileCount": len(files),
        "groups": [{"id": k, "name": ("共用核心" if k == "L1" else "其他（文件／工具／測試）" if k == "OTHER" else names.get(k, k)),
                    "files": by[k]["files"], "changelog": by[k]["changelog"]} for k in order],
    }


# ── 測試閘門 ─────────────────────────────────────────────────────────────

def last_full(path: Path, commit_full_sha: str) -> dict:
    """回傳 {state, detail, record}；state ∈ missing／unreadable／other_commit／dirty／failed／ok。"""
    path = Path(path)
    if not path.exists():
        return {"state": "missing", "detail": "沒有全量紀錄（從未跑過，或結果檔不在主工作樹）", "record": None}
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"state": "unreadable", "detail": f"全量紀錄讀不出來：{e}", "record": None}
    if (rec.get("commit") or "") != commit_full_sha:
        return {"state": "other_commit",
                "detail": f"最近一次全量是 {str(rec.get('commit'))[:8]}，不是目前要打包的 {commit_full_sha[:8]}", "record": rec}
    if rec.get("dirty"):
        return {"state": "dirty", "detail": "那次全量跑的時候工作樹有未 commit 的改動，結果不代表這個 commit", "record": rec}
    if rec.get("ok") is not True:
        return {"state": "failed", "detail": "這個 commit 的全量沒有全綠", "record": rec}
    return {"state": "ok", "detail": "這個 commit 的全量全綠", "record": rec}


# ── 分支上游 ─────────────────────────────────────────────────────────────

def upstream_ahead(root):
    """回傳 (上游名稱, 領先數)；沒有上游 ⇒ (None, None)，不猜 origin/master。"""
    try:
        up = _git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}").strip()
        n = int(_git(root, "rev-list", "--count", f"{up}..HEAD").strip())
        return up, n
    except (RuntimeError, ValueError):
        return None, None
