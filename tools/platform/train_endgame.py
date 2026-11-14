# -*- coding: utf-8 -*-
"""列車收尾一鍵（T87 A2）：把整合者在「合完分支之後」的手工步驟收成一個可重跑、遇到要人處理就停的流程。

[單位] tools:train_endgame    [層] 工具    [穩定度] 內部
[公開介面] STAGES, run_stages, changelog_order_problems, functional_files, manifest_new_entries, check_version_record, sync_bottom_layer,
           build_a1_expectations, step_facts, fill_step_file, package_check, main
[不變式]
  - 分支合併與衝突判斷仍由人做；本工具只處理「合完之後」的收尾。程式碼衝突、CHANGELOG 內文、步驟檔的「這一班有什麼」不代寫。
  - 每個會改檔的階段各自一個 commit（與手工做法相同）；沒有改動就不 commit。`plan` 完全唯讀。
  - 遇到第一個「要人處理」的階段就停（exit 1），輸出說明；修好再跑 `run`，已完成的階段會判定為「已完成」而略過（冪等）。
  - 檢查 ①（功能變更必須有版本紀錄）的逃生口 `--allow-no-version-record "PM 核准（YYYY-MM-DD）：原因"`：
    格式不符就拒絕；用了會寫進本機狀態檔，並由 `fill`／步驟檔階段寫進步驟檔「關卡紀錄」。
  - 不 push、不發布、不建包；`package_check` 只讀包資料夾。

階段（順序＝手工收尾順序）
  baselines     resolve_baselines（結構合併基準檔、重算衍生值；L1 介面快照在這裡更新）→ --check
  bottom_layer  scope_gate 掃到的全域測試補進 bottom_layer.json global_tests（只補，不自動移除；過期條目只警告）
  version_record 檢查 ①：base..HEAD 有功能變更卻沒有新增 version_manifest 條目 ⇒ 擋下
  a1_expectations 檢查 ②：產生 backend/a1_expectations.json（A1 自動套用的包專屬驗證項；進 repo、凍結前 commit）
  changelog     CHANGELOG 摺疊前檢查：`(next)` 在最上面、標題順序、有功能變更的模組／核心都有 CHANGELOG 段落
  l1_pre        L1 介面快照＝目前介面（取號前）
  assign        train_number assign（獨立 commit）→ --check；取號會升核心主版號而 core_major_bump 還沒處理 ⇒ 停
  regen         regen_all（獨立 commit）→ --check
  l1_post       L1 介面快照＝目前介面（取號、重產之後）
  step_file     步驟檔「事實區塊」（版號、commit／檔案數、關卡備註）；沒有步驟檔就由範本產生草稿
  pyc           追蹤中的 .pyc／__pycache__ ＝ 0

用法（列車樹根目錄；Python 用 D:\\MOTRIX-PLATFORM\\.venv312\\Scripts\\python.exe）：
  python tools/platform/train_endgame.py plan  --base origin/platform --label t87 [--step-file docs/platform/prod-tasks/…-apply.md]
  python tools/platform/train_endgame.py run   --base origin/platform --label t87 [--only <階段>] [--trailer "Co-Authored-By: …"]
  python tools/platform/train_endgame.py fill  --step-file <檔> --pkg-name <包名> --pkg-sha <sha> [--freeze <sha>]
  python tools/platform/train_endgame.py pkg-check <包資料夾>         包內 pyc／__pycache__ 數、檔案數、檔案清單 sha256
退出碼：0 全部完成；1 有階段要人處理（或 plan 發現尚有工作）；2 工具自己出錯。
"""
import argparse
import ast
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

MANIFEST = "backend/version_manifest.json"
BOTTOM = "tools/platform/bottom_layer.json"
A1_FILE = "backend/a1_expectations.json"
TEMPLATE = "docs/platform/prod-tasks/TEMPLATE-apply.md"
FACTS_BEGIN = "<!-- endgame:facts begin -->"
FACTS_END = "<!-- endgame:facts end -->"
ALLOW_RE = re.compile(r"PM 核准（(\d{4}-\d{2}-\d{2})）：(\S[^\r\n]{0,199})")     # 用 fullmatch；不准有換行
LABEL_RE = re.compile(r"[A-Za-z0-9._-]{1,40}")
PKG_NAME_RE = re.compile(r"\d{8}_\d{6}_[0-9a-f]{8}_full")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
FREEZE_RE = re.compile(r"[0-9a-f]{7,40}")
OVERRIDE_DIR = "docs/platform/train-overrides"
OVERRIDE_DAYS = 14                     # 核准日期距今最多幾天
LOCK_STALE_SECONDS = 2 * 3600          # 鎖檔超過這麼久只提示、不自動刪
LOG_FORBID_DEFAULT = ["ImportError", "no such column", "no such table"]
_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)

STAGES = ("baselines", "bottom_layer", "version_record", "a1_expectations", "changelog",
          "l1_pre", "assign", "regen", "l1_post", "step_file", "pyc")


# ── 結果與 git 小工具 ───────────────────────────────────────────────────────

DONE, WILL, BLOCK, WARN = "已完成", "待執行", "要人處理", "警告"


class Result:
    def __init__(self, stage, status, lines=(), commits=()):
        self.stage, self.status, self.lines, self.commits = stage, status, list(lines), list(commits)


def git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", creationflags=_NOWIN)
    if check and r.returncode != 0:
        raise RuntimeError("git %s 失敗：%s" % (" ".join(args), (r.stderr or r.stdout).strip()))
    return r.stdout


def git_show(repo, rev, rel):
    r = subprocess.run(["git", "-C", str(repo), "show", "%s:%s" % (rev, rel)], capture_output=True, creationflags=_NOWIN)
    return r.stdout.decode("utf-8-sig", errors="replace") if r.returncode == 0 else None


def run_py(repo, script, *args):
    env = dict(os.environ, PYTHONUTF8="1")
    r = subprocess.run([sys.executable, "-X", "utf8", str(Path(repo) / script), *args], cwd=str(repo), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=env, creationflags=_NOWIN)
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


def changed_files(repo, base):
    out = git(repo, "diff", "--name-only", "%s...HEAD" % base)
    return [l.strip() for l in out.splitlines() if l.strip()]


def porcelain_paths(repo):
    """工作樹目前有改動的路徑（含未追蹤、已 staged、改名的新舊路徑）。"""
    out = git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    parts, paths, i = out.split("\0"), [], 0
    while i < len(parts):
        e = parts[i]
        i += 1
        if len(e) < 4:
            continue
        xy, p = e[:2], e[3:]
        paths.append(p)
        if ("R" in xy or "C" in xy) and i < len(parts):
            paths.append(parts[i])
            i += 1
    return sorted(set(paths))


def _commit_only(repo, paths, message, trailer=""):
    """paths 加入並只 commit 這些路徑（不帶走 index 裡別的東西）；沒有改動 ⇒ None。"""
    paths = list(paths)
    if not paths:
        return None
    git(repo, "add", "-A", "--", *paths)
    if not git(repo, "diff", "--cached", "--name-only", "--", *paths).strip():
        return None
    git(repo, "commit", "-q", "-m", message + (("\n\n" + trailer) if trailer else ""), "--", *paths)
    return git(repo, "rev-parse", "--short", "HEAD").strip()


def commit_paths(repo, paths, message, trailer=""):
    """明確指定的路徑 add＋commit；沒有改動 ⇒ 回傳 None。"""
    return _commit_only(repo, paths, message, trailer)


def commit_tool_changes(repo, before, message, trailer=""):
    """階段跑完後，只 commit「階段開始之後新出現」的改動路徑（before＝開始時的 porcelain_paths）。
    不用 `add -A .`：工作樹裡原本就有的其他檔不會被帶進這個 commit。"""
    seen = set(before)
    return _commit_only(repo, [p for p in porcelain_paths(repo) if p not in seen], message, trailer)


# ── 逃生口紀錄（綁班次與 base，進版控）──────────────────────────────────────

def parse_allow(text):
    """「PM 核准（YYYY-MM-DD）：原因」⇒ (日期, 原因)；格式錯、含換行、日期不存在或超過 OVERRIDE_DAYS 天 ⇒ ValueError。"""
    m = ALLOW_RE.fullmatch(text or "")
    if not m:
        raise ValueError("--allow-no-version-record 必須寫成「PM 核准（YYYY-MM-DD）：原因」（單行、原因 1–200 字）")
    try:
        d = datetime.date.fromisoformat(m.group(1))
    except ValueError:
        raise ValueError("核准日期不存在：%s" % m.group(1))
    today = datetime.date.today()
    if d > today or (today - d).days > OVERRIDE_DAYS:
        raise ValueError("核准日期 %s 必須在最近 %d 天內（且不是未來）" % (d, OVERRIDE_DAYS))
    return d, m.group(2)


def override_rel(label):
    return "%s/%s.json" % (OVERRIDE_DIR, label)


def load_override(repo, label, base_sha):
    """⇒ (紀錄 或 None, 說明 或 None)。檔案屬於別班或別的 base ⇒ 不採用，並說明。"""
    p = Path(repo) / override_rel(label)
    if not p.is_file():
        return None, None
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
        parse_shape = ALLOW_RE.fullmatch(rec["text"])
    except (OSError, ValueError, KeyError, TypeError):
        return None, "放行紀錄 %s 讀不懂，不採用。" % override_rel(label)
    if rec.get("label") != label or rec.get("base_sha") != base_sha or not parse_shape:
        return None, "放行紀錄 %s 綁的是別班／別的 base（label %s、base %s），不採用。" % (
            override_rel(label), rec.get("label"), str(rec.get("base_sha"))[:12])
    return rec, None


def write_override(repo, label, base_sha, text):
    """寫放行紀錄；內容沒變 ⇒ 回傳 False。"""
    d, reason = parse_allow(text)
    rec = {"kind": "no_version_record", "label": label, "base_sha": base_sha, "approved_date": d.isoformat(), "reason": reason, "text": text}
    new = json.dumps(rec, ensure_ascii=False, indent=1) + "\n"
    p = Path(repo) / override_rel(label)
    if p.is_file() and p.read_text(encoding="utf-8") == new:
        return False
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(new, encoding="utf-8", newline="\n")
    return True


# ── 執行鎖 ─────────────────────────────────────────────────────────────────

def lock_path(repo):
    gd = Path(git(repo, "rev-parse", "--git-dir").strip())
    return (gd if gd.is_absolute() else Path(repo) / gd) / "train_endgame.lock"


def acquire_lock(repo):
    """獨佔鎖（O_EXCL）。已被持有 ⇒ ValueError（快速失敗）；過期的鎖只提示，不自動刪。"""
    p = lock_path(repo)
    try:
        fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            age = time.time() - p.stat().st_mtime
            who = p.read_text(encoding="utf-8").strip()
        except OSError:
            age, who = 0, "?"
        raise ValueError("另一個 train_endgame run 正在進行（鎖檔 %s，%s，已 %d 分鐘）。%s" % (
            p, who, age // 60, "鎖檔已超過 %d 小時，確認沒人在跑後手動刪除。" % (LOCK_STALE_SECONDS // 3600) if age > LOCK_STALE_SECONDS else "等它結束。"))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("pid %d @ %s" % (os.getpid(), datetime.datetime.now().isoformat(timespec="seconds")))
    return p


def release_lock(path):
    try:
        Path(path).unlink()
    except OSError:
        pass


# ── 檢查 ①：功能變更必須有版本紀錄 ─────────────────────────────────────────

_NOT_FUNCTIONAL_NAMES = {"CHANGELOG.md", "version_manifest.json", "_prod_baseline.py", "module.json", "a1_expectations.json"}


def functional_files(changed):
    """變動檔中「使用者可感受的功能變更」：backend/ 與 frontend/ 底下，扣掉測試、說明檔、版本簿記、部署工具。"""
    out = []
    for f in changed:
        f = f.replace("\\", "/")
        if not (f.startswith("backend/") or f.startswith("frontend/")):
            continue
        parts = f.split("/")
        if "tests" in parts or f.startswith("backend/tools/") or f.startswith("backend/migrations_frozen/"):
            continue
        if parts[-1] in _NOT_FUNCTIONAL_NAMES or f.endswith(".md"):
            continue
        out.append(f)
    return out


def _entries(text):
    try:
        data = json.loads(text) if text else []
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def manifest_new_entries(repo, base):
    """HEAD 的 version_manifest 相對 base 新增的條目（以 (module, version) 判定；version＝next 的佔位也算新增）。"""
    old = {(e.get("module"), e.get("version")) for e in _entries(git_show(repo, base, MANIFEST))}
    head = _entries(git_show(repo, "HEAD", MANIFEST))
    return [e for e in head if (e.get("module"), e.get("version")) not in old]


def touched_units(fn):
    """功能變更檔涉及的單位：backend/modules/<m>、core、frontend。"""
    return sorted({f.split("/")[2] for f in fn if f.startswith("backend/modules/")}
                  | ({"core"} if any(f.startswith("backend/core/") for f in fn) else set())
                  | ({"frontend"} if any(f.startswith("frontend/") for f in fn) else set()))


def check_version_record(repo, base, allow=None):
    changed = changed_files(repo, base)
    fn = functional_files(changed)
    new = manifest_new_entries(repo, base)
    if not fn:
        return Result("version_record", DONE, ["本車沒有功能變更檔，不需要新的版本紀錄。"])
    units = touched_units(fn)
    if new:
        lines = ["功能變更檔 %d 個；version_manifest 新增 %d 筆。" % (len(fn), len(new))]
        if len(units) > len(new):
            # manifest 的 module 欄是自由中文標籤，沒有和程式單位的對應表 ⇒ 不能機械判定「每個單位都有紀錄」，只能請人核對
            return Result("version_record", WARN, lines + [
                "涉及 %d 個單位（%s），只新增 %d 筆：請人核對每個單位的變更都被某一筆涵蓋。" % (len(units), "、".join(units), len(new)),
                "新增條目的 module：" + "；".join(str(e.get("module")) for e in new[:12])])
        return Result("version_record", DONE, lines)
    if allow:
        return Result("version_record", WARN, ["功能變更檔 %d 個、沒有新增版本紀錄；已用 --allow-no-version-record：%s" % (len(fn), allow)])
    mods = units
    return Result("version_record", BLOCK, [
        "功能變更檔 %d 個（涉及：%s），但 %s 沒有新增任何條目。" % (len(fn), "、".join(mods) or "—", MANIFEST),
        "處理：補寫版本紀錄（`\"version\": \"next\"` 佔位，取號時代入），或由 PM 核准後用 "
        "--allow-no-version-record \"PM 核准（YYYY-MM-DD）：原因\" 放行（寫成 %s/<班次>.json 進版控，綁班次與 base，並寫進步驟檔）。" % OVERRIDE_DIR,
        "前 5 個功能變更檔：" + "；".join(fn[:5]),
    ])


# ── bottom_layer 登記 ───────────────────────────────────────────────────────

def bottom_layer_gap(repo):
    import scope_gate
    cands = set(scope_gate.global_test_candidates(repo))
    listed = json.loads((Path(repo) / BOTTOM).read_text(encoding="utf-8"))["global_tests"]
    return sorted(cands - set(listed)), sorted(set(listed) - cands)


def sync_bottom_layer(repo, write=True):
    """補登缺的全域測試（文字插入，不重排檔案）。回傳 (新增清單, 過期清單)。"""
    missing, stale = bottom_layer_gap(repo)
    if missing and write:
        p = Path(repo) / BOTTOM
        raw = p.read_bytes().decode("utf-8")
        nl = "\r\n" if "\r\n" in raw else "\n"
        m = re.search(r'("global_tests"\s*:\s*\[)(.*?)(\n\s*\])', raw, re.S)
        if not m:
            raise RuntimeError("bottom_layer.json 找不到 global_tests 陣列")
        body = m.group(2).rstrip()
        indent = re.search(r"\n(\s*)\"", m.group(2))
        pad = indent.group(1) if indent else "  "
        add = ("," if body.strip() else "") + "".join('%s%s"%s"%s' % (nl, pad, p_, ",") for p_ in missing).rstrip(",")
        raw = raw[:m.end(2)].rstrip() + add + raw[m.start(3):]
        p.write_bytes(raw.encode("utf-8"))
        json.loads(raw)                                    # 寫壞就丟例外
    return missing, stale


# ── 檢查 ②：a1_expectations.json ───────────────────────────────────────────

def public_api_paths(repo):
    """main.py 的 _PUBLIC_API_PATHS（集合字面值）；讀不到 ⇒ None（呼叫端不產 auth_required，不猜）。"""
    try:
        tree = ast.parse((Path(repo) / "backend" / "main.py").read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_PUBLIC_API_PATHS" for t in node.targets):
            try:
                return set(ast.literal_eval(node.value))
            except (ValueError, TypeError):
                return None
    return None


def _route_keys(repo, rev):
    text = git_show(repo, rev, "backend/tests/platform/route_inventory.json")
    try:
        return set(json.loads(text)["endpoints"]) if text else set()
    except (ValueError, KeyError):
        return set()


def build_a1_expectations(repo, base):
    changed = changed_files(repo, base)
    out, notes = {}, []
    pages = []
    if (Path(repo) / "frontend" / "index.html").exists():
        pages.append("/")
    for f in changed:
        m = re.match(r"^frontend/pages/([A-Za-z0-9_\-]+\.html)$", f.replace("\\", "/"))
        if m and (Path(repo) / f).exists():
            pages.append("/pages/" + m.group(1))
    if pages:
        out["pages"] = sorted(set(pages))[:40]
    public = public_api_paths(repo)
    new_routes = sorted(_route_keys(repo, "HEAD") - _route_keys(repo, base))
    if public is None:
        notes.append("讀不到 _PUBLIC_API_PATHS，不產生 auth_required（避免把免登入端點寫成必須 401）")
    else:
        req = []
        for k in new_routes:
            method, _, path = k.partition(" ")
            if method not in ("GET", "POST", "HEAD", "OPTIONS") or not path.startswith("/api/") or path in public:
                continue
            req.append({"method": method, "path": path})
        if req:
            out["auth_required"] = req[:60]
    mods = sorted({f.split("/")[2] for f in functional_files(changed) if f.startswith("backend/modules/")})
    files = ["backend/modules/%s/module.json" % k for k in mods if (Path(repo) / "backend" / "modules" / k / "module.json").exists()]
    if files:
        out["files"] = files
    out["log_forbid"] = list(LOG_FORBID_DEFAULT)
    return out, notes


def render_json(obj):
    return json.dumps(obj, ensure_ascii=False, indent=1) + "\n"


# ── 步驟檔事實區塊 ─────────────────────────────────────────────────────────

def prod_baseline(repo):
    try:
        m = re.search(r'BASELINE\s*=\s*["\']([0-9a-f]{7,40})["\']', (Path(repo) / "backend/tests/_prod_baseline.py").read_text(encoding="utf-8"))
        return m.group(1) if m else None
    except OSError:
        return None


def disk_versions(repo):
    out = {}
    reg = (Path(repo) / "backend/core/registry.py").read_text(encoding="utf-8")
    m = re.search(r'CORE_VERSION\s*=\s*"([^"]+)"', reg)
    out["core"] = m.group(1) if m else "?"
    for p in sorted((Path(repo) / "backend" / "modules").glob("*/module.json")):
        try:
            out[p.parent.name] = json.loads(p.read_text(encoding="utf-8-sig")).get("version", "?")
        except ValueError:
            out[p.parent.name] = "?"
    return out


def step_facts(repo, base, prod=None, allow=None, label=None):
    prod = prod or prod_baseline(repo)
    head = git(repo, "rev-parse", "HEAD").strip()
    lines = [FACTS_BEGIN, "<!-- 本區塊由 tools/platform/train_endgame.py 產生；手改會在下次執行時被覆蓋 -->", "",
             "- 正式機基準：`%s`；凍結：`%s`" % (prod or "?", head),
             "- 組成：相對基準 %s 個 commit、%s 個檔案" % (
                 git(repo, "rev-list", "--count", "%s..HEAD" % prod).strip() if prod else "?",
                 len([l for l in git(repo, "diff", "--name-only", prod, "HEAD").splitlines() if l.strip()]) if prod else "?"),
             "- 版號（磁碟實際值）：" + "；".join("%s %s" % kv for kv in disk_versions(repo).items()),
             "- manifest 條目：%d 筆（本車新增 %d）" % (len(_entries(git_show(repo, "HEAD", MANIFEST))), len(manifest_new_entries(repo, base)))]
    if allow:
        lines.append("- 備註：本包未新增版本紀錄；%s（放行紀錄：%s，綁定班次與 base）" % (allow, override_rel(label) if label else OVERRIDE_DIR))
    lines += ["", FACTS_END]
    return "\n".join(lines)


def write_step_file(repo, base, rel, label, allow=None):
    p = Path(repo) / rel
    facts = step_facts(repo, base, allow=allow, label=label)
    if p.exists():
        raw = p.read_bytes().decode("utf-8")
        nl = "\r\n" if "\r\n" in raw else "\n"
        text = raw.replace("\r\n", "\n")
        if FACTS_BEGIN in text and FACTS_END in text:
            a, b = text.index(FACTS_BEGIN), text.index(FACTS_END) + len(FACTS_END)
            new = text[:a] + facts + text[b:]
        else:
            new = text.rstrip("\n") + "\n\n## 事實區塊（自動產生）\n\n" + facts + "\n"
    else:
        tpl = (Path(repo) / TEMPLATE).read_text(encoding="utf-8").replace("\r\n", "\n")
        new = tpl.replace("# 給正式機 Claude：第 N 班更新步驟", "# 給正式機 Claude：%s 更新步驟" % label, 1)
        new += "\n\n## 事實區塊（自動產生）\n\n" + facts + "\n"
        nl = "\n"
    new = new.replace("\n", nl)
    if p.exists() and new == raw:
        return False
    p.write_bytes(new.encode("utf-8"))
    return True


def _fill_problems(pkg_name, pkg_sha, freeze, pkg_dir, repo):
    probs = []
    if pkg_name is not None and not PKG_NAME_RE.fullmatch(pkg_name):
        probs.append("包名格式不對（要 YYYYMMDD_HHMMSS_<8 碼 hex>_full）：%r" % pkg_name[:80])
    if pkg_sha is not None and not SHA256_RE.fullmatch(pkg_sha):
        probs.append("sha256 必須是 64 碼小寫 hex：%r" % pkg_sha[:80])
    if freeze is not None and not FREEZE_RE.fullmatch(freeze):
        probs.append("凍結 sha 必須是 7–40 碼小寫 hex：%r" % freeze[:80])
    if pkg_name is not None or pkg_sha is not None:
        if not pkg_dir:
            probs.append("給了 --pkg-name／--pkg-sha 就必須同時給 --pkg-dir（包資料夾），才能和 package.sha256 實際內容比對。")
        else:
            d = Path(pkg_dir)
            f = d / "package.sha256"
            if pkg_name is not None and d.name != pkg_name:
                probs.append("包資料夾名 %r 與 --pkg-name %r 不符" % (d.name, pkg_name))
            if not f.is_file():
                probs.append("包資料夾裡沒有 package.sha256：%s" % d)
            elif pkg_sha is not None and hashlib.sha256(f.read_bytes()).hexdigest() != pkg_sha:
                probs.append("--pkg-sha 與 package.sha256 的實際 sha256 不符")
    if freeze is not None and FREEZE_RE.fullmatch(freeze):
        r = subprocess.run(["git", "-C", str(repo), "cat-file", "-e", freeze + "^{commit}"], capture_output=True, creationflags=_NOWIN)
        if r.returncode != 0:
            probs.append("凍結 sha %s 不在這個 repo" % freeze)
    return probs


_PLACEHOLDER_RE = re.compile(r"<(?:PKG|FREEZE)_[A-Z0-9_]*>")


def unfilled_placeholders(path):
    return sorted(set(_PLACEHOLDER_RE.findall(Path(path).read_bytes().decode("utf-8"))))


def fill_step_file(path, pkg_name=None, pkg_sha=None, freeze=None, pkg_dir=None, repo=None):
    """包發布後代入佔位欄位；先驗證格式並與 package.sha256 比對，不符就丟 ValueError、什麼都不寫。回傳實際代入的欄位名。"""
    probs = _fill_problems(pkg_name, pkg_sha, freeze, pkg_dir, repo or REPO)
    if probs:
        raise ValueError("fill 的輸入不合格，未寫入任何東西：\n  " + "\n  ".join(probs))
    p = Path(path)
    raw = p.read_bytes().decode("utf-8")
    done = []
    for key, val in (("<PKG_NAME>", pkg_name), ("<PKG_SHA256>", pkg_sha), ("<FREEZE_SHA>", freeze),
                     ("<FREEZE_8>", freeze[:8] if freeze else None)):
        if val and key in raw:
            raw = raw.replace(key, val)
            done.append(key)
    p.write_bytes(raw.encode("utf-8"))
    return done


# ── 包檢查（發布前給 PM 核對）──────────────────────────────────────────────

def package_check(pkg_dir):
    pkg = Path(pkg_dir)
    rows, pyc, cache = [], 0, 0
    for d, dirs, files in os.walk(pkg):
        cache += sum(1 for x in dirs if x == "__pycache__")
        for f in files:
            fp = Path(d) / f
            if f.endswith((".pyc", ".pyo")):
                pyc += 1
            rows.append((fp.relative_to(pkg).as_posix(), hashlib.sha256(fp.read_bytes()).hexdigest()))
    rows.sort()
    txt = "".join("%s  %s\n" % (h, r) for r, h in rows)
    return {"files": len(rows), "pyc": pyc, "pycache": cache, "filelist_sha256": hashlib.sha256(txt.encode()).hexdigest(), "filelist": txt}


def tracked_pyc(repo):
    return [f for f in git(repo, "ls-files").splitlines() if f.endswith((".pyc", ".pyo")) or "/__pycache__/" in f or f.startswith("__pycache__/")]


# ── 階段 ───────────────────────────────────────────────────────────────────

def _tail(text, n=8):
    return text.splitlines()[-n:]


class Ctx:
    def __init__(self, repo, base, label, step_file, allow, trailer, dry):
        self.repo, self.base, self.label, self.step_file, self.allow, self.trailer, self.dry = repo, base, label, step_file, allow, trailer, dry


def st_baselines(c):
    rc, out = run_py(c.repo, "tools/platform/resolve_baselines.py", "--check")
    if rc == 0:
        return Result("baselines", DONE, ["基準檔都已處理。"])
    if c.dry:
        return Result("baselines", WILL, ["resolve_baselines --check 回報有東西要處理。"] + _tail(out))
    before = porcelain_paths(c.repo)
    run_py(c.repo, "tools/platform/resolve_baselines.py")
    sha = commit_tool_changes(c.repo, before, "chore(%s): resolve_baselines" % c.label, c.trailer)
    rc2, out2 = run_py(c.repo, "tools/platform/resolve_baselines.py", "--check")
    if rc2 != 0:
        return Result("baselines", BLOCK, ["resolve_baselines 之後仍有要人處理的項目："] + _tail(out2, 15), [sha] if sha else [])
    return Result("baselines", DONE, ["已重算基準檔。"], [sha] if sha else [])


def st_bottom_layer(c):
    missing, stale = bottom_layer_gap(c.repo)
    lines = ["全域測試待補登：%d 個" % len(missing)] + ["  + " + m for m in missing]
    if stale:
        lines += ["登記了但已不是全域測試（只警告，請人確認後移除）："] + ["  - " + s for s in stale]
    if not missing:
        return Result("bottom_layer", WARN if stale else DONE, lines)
    if c.dry:
        return Result("bottom_layer", WILL, lines)
    sync_bottom_layer(c.repo)
    sha = commit_paths(c.repo, [BOTTOM], "chore(%s): bottom_layer.json 補登全域測試 %d 個" % (c.label, len(missing)), c.trailer)
    return Result("bottom_layer", WARN if stale else DONE, lines, [sha] if sha else [])


def st_version_record(c):
    return check_version_record(c.repo, c.base, c.allow)


def st_a1(c):
    obj, notes = build_a1_expectations(c.repo, c.base)
    new = render_json(obj)
    p = Path(c.repo) / A1_FILE
    cur = p.read_text(encoding="utf-8") if p.exists() else None
    lines = ["pages %d、auth_required %d、files %d" % (len(obj.get("pages", [])), len(obj.get("auth_required", [])), len(obj.get("files", [])))] + notes
    if cur == new:
        return Result("a1_expectations", DONE, lines)
    if c.dry:
        return Result("a1_expectations", WILL, lines)
    p.write_text(new, encoding="utf-8", newline="\n")
    sha = commit_paths(c.repo, [A1_FILE], "chore(%s): a1_expectations.json（A1 包專屬驗證項，自動產生）" % c.label, c.trailer)
    return Result("a1_expectations", DONE, lines, [sha] if sha else [])


_GUARD_REL = "backend/tests/platform/test_module_changelog_follows_code.py"


def changelog_order_problems(repo):
    """沿用守門 test_module_changelog_follows_code 自己的 check_module（不重寫規則）：
    CHANGELOG 最上面的條目必須寫在該模組「最後一次程式改動」之後。回傳 {模組: [問題]}。"""
    import importlib.util
    repo = Path(repo)
    guard = repo / _GUARD_REL if (repo / _GUARD_REL).exists() else REPO / _GUARD_REL
    sys.path.insert(0, str(repo / "backend" if (repo / "backend" / "core").exists() else REPO / "backend"))
    try:
        spec = importlib.util.spec_from_file_location("_endgame_changelog_guard", str(guard))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        bad = {}
        for d in sorted((repo / "backend" / "modules").glob("*/module.json")):
            rel = d.parent.relative_to(repo).as_posix()
            probs = mod.check_module(repo, rel)
            if probs:
                bad[d.parent.name] = probs
        return bad
    finally:
        sys.path.pop(0)


def st_changelog(c):
    import train_preflight
    findings = [f for f in train_preflight.check_changelogs(c.repo)]
    changed = changed_files(c.repo, c.base)
    fn = functional_files(changed)
    need = {"backend/core/CHANGELOG.md"} if any(f.startswith("backend/core/") for f in fn) else set()
    need |= {"backend/modules/%s/CHANGELOG.md" % f.split("/")[2] for f in fn if f.startswith("backend/modules/")}
    miss = sorted(x for x in need if (Path(c.repo) / x).exists() and x not in changed)
    lines = ["%s：%s" % (f.where, f.msg) for f in findings] + ["有功能變更但 CHANGELOG 沒有新段落：%s" % x for x in miss]
    for k, probs in changelog_order_problems(c.repo).items():
        lines += ["%s：%s" % (k, "；".join(probs))]
    if lines:
        return Result("changelog", BLOCK, lines + ["處理：把 `## (next)` 段落放最上面並寫內文；CHANGELOG 要在最後一次程式改動『之後』提交。內文由人寫，本工具不代寫。"])
    return Result("changelog", DONE, ["CHANGELOG 標題順序正確，有功能變更的模組／核心都有段落，且都寫在最後一次程式改動之後。"])


def st_l1(name):
    def f(c):
        rc, out = run_py(c.repo, "backend/tests/platform/_l1_interface.py", "--check")
        if rc == 0:
            return Result(name, DONE, _tail(out, 2))
        return Result(name, BLOCK, _tail(out, 8) + ["處理：`python backend/tests/platform/_l1_interface.py --update --pending`（CHANGELOG 最上面須是 (next)），再重跑。"])
    return f


def core_major_gap(repo, base):
    """取號會把核心升到新主版號、而 core_major_bump 還沒處理 ⇒ 回傳問題清單；沒有這個情況 ⇒ []。
    「處理過」的證據＝所有 module.json 的 core 範圍已接受下一個主版號（core_major_bump apply 的結果；T86 的 CORE 2.0 事故就是缺這一步）。
    判斷本體沿用 core_major_bump（major_pending／guard_problems），不另寫一套。"""
    import core_major_bump as CMB
    pending, why = CMB.major_pending(repo, base)
    if not pending:
        return []
    specs = {k: spec for k, (_p, spec) in CMB.module_specs(repo).items()}
    probs = CMB.guard_problems(CMB.core_version(repo), specs, True)
    if not probs:
        return []
    return ["取號會把核心升到新主版號（%s），而 core_major_bump 還沒處理：" % why] + probs


def st_assign(c):
    rc, out = run_py(c.repo, "tools/platform/train_number.py", "assign", "--dry-run", "--base", c.base)
    if rc not in (0, 3):
        return Result("assign", BLOCK, ["train_number assign --dry-run 失敗（exit %d）：" % rc] + _tail(out, 12))
    if rc == 0:
        rc2, out2 = run_py(c.repo, "tools/platform/train_number.py", "--check", "--base", c.base)
        return Result("assign", DONE if rc2 == 0 else BLOCK, _tail(out2, 4))
    gap = core_major_gap(c.repo, c.base)
    if gap:
        return Result("assign", BLOCK, gap + ["這是核心大版本升級，不是一般取號：先照上面的指令跑 core_major_bump，再重跑本工具。"])
    if c.dry:
        return Result("assign", WILL, ["有佔位要取號。"] + _tail(out, 8))
    before = porcelain_paths(c.repo)
    rc, out = run_py(c.repo, "tools/platform/train_number.py", "assign", "--base", c.base)
    if rc != 0:
        return Result("assign", BLOCK, _tail(out, 12))
    sha = commit_tool_changes(c.repo, before, "chore(%s): train_number assign" % c.label, c.trailer)
    rc2, out2 = run_py(c.repo, "tools/platform/train_number.py", "--check", "--base", c.base)
    return Result("assign", DONE if rc2 == 0 else BLOCK, _tail(out2, 4), [sha] if sha else [])


def st_regen(c):
    rc, out = run_py(c.repo, "tools/platform/regen_all.py", "--check")
    if rc == 0:
        return Result("regen", DONE, ["產生檔都是最新。"])
    if c.dry:
        return Result("regen", WILL, ["有產生檔過期：" + "；".join(l for l in out.splitlines() if l.strip().startswith(("docs/", "backend/")))[:300]])
    before = porcelain_paths(c.repo)
    rc, out = run_py(c.repo, "tools/platform/regen_all.py")
    if rc != 0:
        return Result("regen", BLOCK, ["regen_all 失敗："] + _tail(out, 10))
    sha = commit_tool_changes(c.repo, before, "chore(%s): regen_all after assign" % c.label, c.trailer)
    rc2, out2 = run_py(c.repo, "tools/platform/regen_all.py", "--check")
    return Result("regen", DONE if rc2 == 0 else BLOCK, _tail(out2, 4), [sha] if sha else [])


def st_step_file(c):
    if not c.step_file:
        return Result("step_file", WARN, ["未指定 --step-file，略過（指定後會產生／更新事實區塊）。"])
    if c.dry:
        p = Path(c.repo) / c.step_file
        return Result("step_file", WILL, ["步驟檔%s；將寫入事實區塊。" % ("已存在" if p.exists() else "不存在，將由範本產生草稿")])
    changed = write_step_file(c.repo, c.base, c.step_file, c.label, c.allow)
    sha = commit_paths(c.repo, [c.step_file], "docs(%s): 步驟檔事實區塊（自動產生）" % c.label, c.trailer) if changed else None
    return Result("step_file", DONE, ["步驟檔事實區塊已%s。" % ("更新" if changed else "是最新")], [sha] if sha else [])


def st_pyc(c):
    bad = tracked_pyc(c.repo)
    if bad:
        return Result("pyc", BLOCK, ["追蹤中的 pyc／__pycache__ 有 %d 個：" % len(bad)] + bad[:5])
    return Result("pyc", DONE, ["追蹤中的 .pyc／__pycache__ ＝ 0。（建包後請再跑 `pkg-check <包資料夾>`）"])


IMPL = {"baselines": st_baselines, "bottom_layer": st_bottom_layer, "version_record": st_version_record,
        "a1_expectations": st_a1, "changelog": st_changelog, "l1_pre": st_l1("l1_pre"), "assign": st_assign,
        "regen": st_regen, "l1_post": st_l1("l1_post"), "step_file": st_step_file, "pyc": st_pyc}
assert tuple(IMPL) == STAGES


def preflight(repo, base, dry):
    """前置檢查：base 解析得到且是 HEAD 的祖先、base..HEAD 有差異（否則所有「沒有功能變更」都是假綠燈）、工作樹乾淨。
    ⇒ (Result, base 的完整 sha 或 None)。報告最上面一定印 base 與 HEAD 的 sha。"""
    head = git(repo, "rev-parse", "HEAD").strip()
    try:
        base_sha = git(repo, "rev-parse", "--verify", "%s^{commit}" % base).strip()
    except RuntimeError:
        return Result("preflight", BLOCK, ["base %r 解析不到（先 git fetch，或檢查 --base）；HEAD %s" % (base, head[:12])]), None
    lines = ["base %s ＝ %s；HEAD ＝ %s" % (base, base_sha[:12], head[:12])]
    blocks = []
    anc = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", base_sha, head], capture_output=True, creationflags=_NOWIN)
    if anc.returncode != 0:
        blocks.append("base 不是 HEAD 的祖先（分支錯了？）——相對它的比對沒有意義。")
    elif base_sha == head:
        blocks.append("base 就是 HEAD：base..HEAD 是空的，所有「沒有功能變更」的結論都會是假的。")
    elif not changed_files(repo, base):
        blocks.append("base..HEAD 沒有任何檔案差異，不是正常的一班車。")
    dirty = porcelain_paths(repo)
    if dirty:
        msg = "工作樹不乾淨（%d 個路徑）：%s%s" % (len(dirty), "；".join(dirty[:10]), "…" if len(dirty) > 10 else "")
        (lines if dry else blocks).append(msg + ("" if dry else "。先 commit 或移走，工具只 commit 自己改的檔。"))
    if blocks:
        return Result("preflight", BLOCK, lines + blocks), base_sha
    return Result("preflight", WARN if dry and dirty else DONE, lines), base_sha


def run_stages(repo, base, label, step_file=None, allow=None, trailer="", dry=True, only=None):
    """依序跑階段；run 模式遇 BLOCK 就停。plan 模式（dry）每個階段都評估（但取號之後的階段依賴前面，標註）。
    run 模式：工作樹必須乾淨（每個階段開始時也檢查）、持有執行鎖、每個階段只 commit 自己改的檔。"""
    if not LABEL_RE.fullmatch(label or ""):
        raise ValueError("--label 只能是英數與 . _ -（1–40 字）：%r" % (label or "")[:60])
    if allow is not None:
        parse_allow(allow)                                                 # 格式／日期不對 ⇒ ValueError
    pre, base_sha = preflight(repo, base, dry)
    results = [pre]
    if pre.status == BLOCK:
        return results
    lock = None
    if not dry:
        try:
            lock = acquire_lock(repo)
        except ValueError as e:
            return results + [Result("lock", BLOCK, [str(e)])]
    try:
        stage_allow, notes, commits = None, [], []
        rec, why = load_override(repo, label, base_sha)
        if why:
            notes.append(why)
        if rec:
            stage_allow = rec["text"]
            notes.append("採用既有放行紀錄 %s（綁 label %s、base %s）。" % (override_rel(label), label, base_sha[:12]))
        if allow:
            stage_allow = allow
            if dry:
                notes.append("（plan）run 時會把放行寫成 %s 並 commit。" % override_rel(label))
            else:
                changed = write_override(repo, label, base_sha, allow)
                sha = commit_paths(repo, [override_rel(label)], "chore(%s): 無版本紀錄放行紀錄（%s）" % (label, allow), trailer) if changed else None
                notes.append("放行紀錄已寫入 %s（綁 label %s、base %s）。" % (override_rel(label), label, base_sha[:12]))
                commits = [sha] if sha else []
        if stage_allow or notes:
            results.append(Result("override", WARN, ([stage_allow] if stage_allow else []) + notes, commits))
        c = Ctx(repo, base, label, step_file, stage_allow, trailer, dry)
        for name in STAGES:
            if only and name != only:
                continue
            if not dry:
                dirty = porcelain_paths(repo)
                if dirty:
                    results.append(Result(name, BLOCK, ["階段開始時工作樹不乾淨：" + "；".join(dirty[:10])]))
                    break
            try:
                r = IMPL[name](c)
            except Exception as e:                                         # noqa: BLE001
                r = Result(name, BLOCK, ["階段出錯（%s: %s）" % (type(e).__name__, e)])
                results.append(r)
                if not dry:
                    break
                continue
            results.append(r)
            if not dry and r.status == BLOCK:
                break
        return results
    finally:
        if lock:
            release_lock(lock)


_DEPENDENT = ("regen", "l1_post", "step_file")


def format_report(results, dry, base="origin/platform", label="train"):
    out = ["列車收尾一鍵（%s）" % ("plan：唯讀" if dry else "run")]
    for r in results:
        out.append("[%s] %s%s" % (r.status, r.stage, "（結果依賴前面階段先完成）" if dry and r.stage in _DEPENDENT and r.status == WILL else ""))
        out += ["    " + l for l in r.lines]
        if r.commits:
            out.append("    commit：" + "、".join(r.commits))
    todo = [r.stage for r in results if r.status in (WILL, BLOCK)]
    out.append("")
    out.append("結果：" + ("全部完成。" if not todo else "尚有 %d 個階段：%s" % (len(todo), "、".join(todo))))
    if dry:
        out.append("（選用）文字對照表（本班有用語改寫時）：python tools/platform/text_diff_table.py --base %s --head HEAD --title %s --out docs/platform/plans/TEXT-DIFF-TABLE-%s.md"
                   % (base, label.upper(), label.upper()))
    return "\n".join(out)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                                      # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("plan", "run"):
        sp = sub.add_parser(n)
        sp.add_argument("--base", default="origin/platform")
        sp.add_argument("--label", default="train")
        sp.add_argument("--step-file")
        sp.add_argument("--only", choices=STAGES)
        sp.add_argument("--allow-no-version-record")
        sp.add_argument("--trailer", default="")
    sp = sub.add_parser("fill")
    sp.add_argument("--step-file", required=True)
    sp.add_argument("--pkg-name")
    sp.add_argument("--pkg-sha")
    sp.add_argument("--freeze")
    sp.add_argument("--pkg-dir", help="包資料夾（用來和 package.sha256 實際內容比對；給 --pkg-name／--pkg-sha 時必填）")
    sp = sub.add_parser("pkg-check")
    sp.add_argument("package")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "fill":
            done = fill_step_file(a.step_file, a.pkg_name, a.pkg_sha, a.freeze, a.pkg_dir)
            print("已代入：" + ("、".join(done) or "（沒有可代入的佔位）"))
            left = unfilled_placeholders(a.step_file)
            if left:
                print("步驟檔還有佔位沒代入：%s（半填的步驟檔不能出貨）" % "、".join(left))
                return 1
            return 0
        if a.cmd == "pkg-check":
            r = package_check(a.package)
            print("檔案 %d；pyc %d；__pycache__ %d；檔案清單 sha256＝%s" % (r["files"], r["pyc"], r["pycache"], r["filelist_sha256"]))
            return 0 if r["pyc"] == 0 and r["pycache"] == 0 else 1
        dry = a.cmd == "plan"
        res = run_stages(REPO, a.base, a.label, a.step_file, a.allow_no_version_record, a.trailer, dry, a.only)
        print(format_report(res, dry, a.base, a.label))
        return 1 if any(r.status in (WILL, BLOCK) for r in res) else 0
    except ValueError as e:
        print("錯誤：%s" % e, file=sys.stderr)
        return 2
    except Exception as e:                                                 # noqa: BLE001
        print("工具出錯：%s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
