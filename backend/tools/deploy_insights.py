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


# ── 正式機健康檢查（D1）──────────────────────────────────────────────────

#: 本機 DB 快照多久沒更新就算不健康（每日排程 02:00；給 6 小時緩衝）
BACKUP_MAX_AGE_HOURS = 30
MIN_FREE_GB = 10


def evaluate_health(facts: dict, now=None) -> dict:
    """把正式機回傳的事實（_dashboard_remote.ps1 -Action health）判成 {ok, problems, warnings}。
    problems 會擋部署；warnings 只提醒。事實缺漏 ⇒ 當成問題（拿不到 ≠ 沒問題）。"""
    from datetime import datetime
    now = now or datetime.now()
    problems, warnings = [], []
    if not isinstance(facts, dict) or not facts:
        return {"ok": False, "problems": ["正式機沒有回傳任何健康資訊"], "warnings": []}
    if facts.get("alertActive"):
        problems.append("正式機有未解除的備份告警：" + (facts.get("alertText") or "（內容空白）").splitlines()[0])
    lb = facts.get("latestDbBackup")
    if not lb or not lb.get("at"):
        problems.append("正式機找不到任何本機資料庫備份（backend/db_backups）")
    else:
        try:
            at = datetime.fromisoformat(lb["at"])
            # 稽核 C-1：`.done` 被重寫過會顯得很新 ⇒ 新鮮度不可以比「資料夾日期的隔天 0 點」更新
            try:
                from datetime import timedelta
                cap = datetime.fromisoformat(str(lb.get("name"))) + timedelta(days=1)
                at = min(at, cap)
            except (TypeError, ValueError):
                pass
            age = (now - at).total_seconds() / 3600
            if age > BACKUP_MAX_AGE_HOURS:
                problems.append(f"正式機最近一次本機資料庫備份是 {age:.0f} 小時前（{lb.get('name')}），超過 {BACKUP_MAX_AGE_HOURS} 小時")
        except ValueError:
            problems.append(f"正式機備份時間讀不懂：{lb.get('at')!r}")
    # 稽核 A-2：看「安裝目錄所在的磁碟」，不是寫死 C:；拿不到那一顆的空間 ⇒ 不放行（未知 ≠ 沒問題）
    disks = facts.get("disks") or []
    drive = (facts.get("installDrive") or "").upper()
    target = next((d for d in disks if str(d.get("name", "")).upper() == drive), None) if drive else None
    if not drive:
        problems.append("拿不到正式機安裝目錄所在的磁碟代號")
    elif target is None or target.get("freeGB") is None:
        problems.append(f"拿不到正式機 {drive}: 的剩餘空間（安裝目錄所在的磁碟）")
    elif target["freeGB"] < MIN_FREE_GB:
        problems.append(f"正式機 {drive}: 剩餘空間 {target['freeGB']} GB，低於 {MIN_FREE_GB} GB（部署前會做 DB 備份與程式快照）")
    if not facts.get("port666Listen"):
        problems.append("正式機 port 666 沒有服務在監聽（服務沒有在跑）")
    for m in facts.get("devMarkers") or []:
        problems.append(f"正式機安裝根目錄有開發機標記 {m}：會讓正式機{'停止寄信' if m == '.no_email_send' else '停止雲端備份'}，而且不會報錯")
    if not facts.get("piiFolders"):
        warnings.append("正式機看不到「系統存檔_個資」資料夾：新版上線後整庫雲端備份與勞報單鏡像會暫停並每天告警")
    fe = facts.get("factErrors") or []
    if isinstance(fe, str):
        fe = [fe]
    for e in (fe if isinstance(fe, list) else [])[:5]:
        warnings.append("正式機收集事實時出錯（該項可能不完整）：" + str(e)[:200])
    if "pythonVersion" in facts and not facts.get("pythonVersion"):
        warnings.append("沒有取得正式機的 Python 版本（開發機 venv 無法對齊）：" + str(facts.get("pythonError") or "原因不明"))
    mods = summarize_modules(facts.get("modules") if isinstance(facts.get("modules"), dict) else {})         if "modules" in facts else {"rows": [], "warnings": []}
    warnings.extend(mods["warnings"])
    return {"ok": not problems, "problems": problems, "warnings": warnings, "modules": mods["rows"]}


# ── 正式機模組狀態（D5）──────────────────────────────────────────────────

def summarize_modules(mfacts: dict) -> dict:
    """把 _prod_health_facts.ps1 的 `modules` 事實整理成一張表＋警示。只提醒、不擋部署。
    狀態取自最近一次啟動的 log（「模組 X 版本 已載入」／「模組 X 未載入：原因」）；沒有 log 就是「不明」，不猜。"""
    import json as _json
    import re
    mfacts = mfacts or {}
    warnings = []
    # 稽核 D-2：每一種事實各自容錯。值來自正式機的檔案與 DB，型別不可信；
    # 任何一項讀不懂都只轉成警示，不可以讓整個健康檢查 500（那會讓上一次的「通過」繼續有效）
    inst_raw = mfacts.get("installed") or []
    if isinstance(inst_raw, dict):                      # ConvertTo-Json 把單元素陣列拆開
        inst_raw = [inst_raw]
    installed = {}
    if isinstance(inst_raw, list):
        installed = {m.get("key"): m for m in inst_raw if isinstance(m, dict) and m.get("key")}
    else:
        warnings.append("正式機已安裝模組清單讀不懂")
    lock, lock_mods = None, {}
    if mfacts.get("lockRaw"):
        try:
            lock = _json.loads(mfacts["lockRaw"])
            lock_mods = lock.get("modules") if isinstance(lock, dict) else None
            if not isinstance(lock_mods, dict) or not all(isinstance(v, dict) for v in lock_mods.values()):
                raise ValueError
        except (ValueError, TypeError):
            lock, lock_mods = None, {}
            warnings.append("正式機的 modules.lock.json 讀不懂")
    else:
        warnings.append("正式機沒有 modules.lock.json（V9 或舊版部署包沒有這個檔）")
    disabled = None
    raw = mfacts.get("disabledRaw")
    err = mfacts.get("disabledError")
    if err is not None:
        last = str(err).strip().splitlines()[-1][:200] if str(err).strip() else "（沒有訊息）"
        warnings.append("讀不到正式機的停用清單：" + last)
    elif mfacts.get("dbMissing"):
        warnings.append("正式機找不到 motrix_erp.db，停用清單無法確認")
    elif raw:
        try:
            val = _json.loads(raw)
            if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
                raise ValueError
            disabled = set(val)
        except (ValueError, TypeError):
            warnings.append("正式機的停用清單讀不懂")
    elif raw == "":
        disabled = set()
    else:
        # 稽核 D-6：讀不到≠沒有停用
        warnings.append("沒有取得正式機的停用清單（原因不明）")
    state = {}
    lines = mfacts.get("logLines") or []
    if isinstance(lines, str):
        lines = [lines]
    for line in lines if isinstance(lines, list) else []:
        line = str(line)
        m = re.search(r"模組 (\S+) (?:(\S+) )?已載入", line)
        if m:
            state[m.group(1)] = ("已載入", "")
            continue
        # 稽核 D-3：loader 的格式是「未載入（未授權）：原因」，括號段可有可無
        m = re.search(r"模組 (\S+) 未載入(?:（([^）]*)）)?[：:]\s*(.*)$", line)
        if m:
            tag, why = (m.group(2) or ""), m.group(3).strip()
            state[m.group(1)] = ("未授權" if tag == "未授權" else "未載入", why)
    rows = []
    for key in sorted(set(installed) | set(lock_mods)):
        inst, lk = installed.get(key), lock_mods.get(key) or {}
        st, why = state.get(key, ("不明（沒有啟動紀錄）", ""))
        if disabled is not None and key in disabled:
            why = (why + "；" if why else "") + "停用清單內"
        rows.append({"key": key, "installedVersion": inst.get("version") if inst else None,
                     "lockVersion": lk.get("version"), "state": st, "reason": why})
        if inst is None:
            warnings.append(f"模組 {key} 在 lock 裡、卻沒有安裝")
        elif lock is not None and not lk:
            warnings.append(f"模組 {key} 已安裝、卻不在 lock 裡")
        elif lk and inst.get("version") != lk.get("version"):
            warnings.append(f"模組 {key} 的版本與 lock 不一致（安裝 {inst.get('version')}，lock {lk.get('version')}）")
        if st == "未載入" and "停用" not in why:
            warnings.append(f"模組 {key} 載入失敗：{why}")
    return {"rows": rows, "warnings": warnings}


# ── 分支上游 ─────────────────────────────────────────────────────────────

def upstream_ahead(root):
    """回傳 (上游名稱, 領先數)；沒有上游 ⇒ (None, None)，不猜 origin/master。"""
    try:
        up = _git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}").strip()
        n = int(_git(root, "rev-list", "--count", f"{up}..HEAD").strip())
        return up, n
    except (RuntimeError, ValueError):
        return None, None
