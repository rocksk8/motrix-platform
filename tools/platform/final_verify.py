# -*- coding: utf-8 -*-
"""最終系統驗證（W3；第 48/49 班）：一行指令對一棵 MOTRIX-PLATFORM 樹（或正式機套用後的狀態報告）逐項印出 PASS／FAIL。

[單位] tools:final_verify    [層] 工具（唯讀）    [穩定度] 內部
[公開介面] run_checks, render_markdown, main；各項檢查函式 check_*（純函式：吃 root 路徑，回 [Result]）
[不變式] 只讀：不寫專案檔、不連正式機資料（`--prod-report` 只讀報告資料夾的文字檔）；重的閘門（pytest 全量、e2e、建包）一律不在這裡跑。
    每一項回 PASS／FAIL／WARN／SKIP 與一句話原因；任何 FAIL ⇒ 結束碼 1（WARN 不擋，列在總結）。

用法（Python 用 D:\\MOTRIX-PLATFORM\\.venv312\\Scripts\\python.exe；樹裡跑 git，需要 git 在 PATH）：
  python tools/platform/final_verify.py --root <樹>                                 # 5 組檢查（版本／文件／端點／樹衛生）＋摘要
  python tools/platform/final_verify.py --root <樹> --prod-report "G:\\...\\正式機回報" --baseline-ref prod/e526a2ef
                                                                                     # 加第 5 組：正式機部署對照（最新一筆摘要.md／status\\latest.json）
  python tools/platform/final_verify.py --root <樹> --md docs/platform/plans/FINAL-VERIFY-T49.md   # 另存 markdown 總結（FINAL-VERIFY-T48.md 範本格式）
  python tools/platform/final_verify.py --root <樹> --only V1,V4 --skip V2.2          # 只跑／略過指定組別或項目
  python tools/platform/final_verify.py --root <樹> --json                            # 機器可讀
白名單檔：tools/platform/final_verify_allow.json（根目錄檔案、公開路由、前端呼叫的已知例外；改它要有理由，審查看得到）。
"""
import argparse
import ast
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ALLOW_FILE = HERE / "final_verify_allow.json"

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"


class Result:
    __slots__ = ("id", "item", "status", "detail")

    def __init__(self, id, item, status, detail=""):
        self.id, self.item, self.status, self.detail = id, item, status, detail

    def as_dict(self):
        return {"id": self.id, "item": self.item, "status": self.status, "detail": self.detail}


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def _git(root: Path, *args, check=False, input=None):
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", input=input)
    if check and r.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args), r.stderr.strip()))
    return r


def load_allow():
    try:
        return json.loads(_read(ALLOW_FILE))
    except (OSError, ValueError):
        return {}


def _short(items, n=12):
    items = list(items)
    s = "；".join(str(i) for i in items[:n])
    return s + ("…（共 %d）" % len(items) if len(items) > n else "")


# ═══════════════════════════ V1 版本一致 ═══════════════════════════════════════════════════════════════
_HEADING = re.compile(r"^##\s+(\(next[^)]*\)|\S+)", re.M)
_VER = re.compile(r"^\d+\.\d+(\.\d+)?$")


def top_heading_version(changelog_text: str):
    m = _HEADING.search(changelog_text)
    return m.group(1) if m else None


def latest_manifest_version(manifest):
    """manifest 是依提交順序追加的，不一定依日期排；最新＝版號字串（YYYY-MM-DD＋字母）最大的那筆。"""
    vs = [str(e.get("version")) for e in manifest if re.match(r"^\d{4}-\d{2}-\d{2}", str(e.get("version", "")))]
    return max(vs) if vs else None


def check_versions(root: Path):
    out = []
    reg = _read(root / "backend/core/registry.py")
    m = re.search(r'^CORE_VERSION\s*=\s*"([^"]+)"', reg, re.M)
    core = m.group(1) if m else None
    if not core or not _VER.match(core):
        out.append(Result("V1.1", "CORE_VERSION 是正式版號", FAIL, "registry.CORE_VERSION=%r" % core))
    else:
        top = top_heading_version(_read(root / "backend/core/CHANGELOG.md"))
        try:
            snap = json.loads(_read(root / "backend/tests/platform/l1_interface_snapshot.json")).get("core_version")
        except (OSError, ValueError):
            snap = None
        bad = []
        if top != core:
            bad.append("core/CHANGELOG 最上面是 %r" % top)
        if snap != core:
            bad.append("G1 快照 core_version=%r" % snap)
        out.append(Result("V1.1", "CORE_VERSION ＝ core CHANGELOG 最上面 ＝ G1 快照", FAIL if bad else PASS,
                          "；".join(bad) or "CORE_VERSION=%s" % core))
    bad, n = [], 0
    for mj in sorted((root / "backend/modules").glob("*/module.json")):
        try:
            ver = json.loads(_read(mj)).get("version")
        except ValueError:
            bad.append("%s: module.json 壞掉" % mj.parent.name)
            continue
        n += 1
        cl = mj.parent / "CHANGELOG.md"
        top = top_heading_version(_read(cl)) if cl.exists() else None
        if ver != top:
            bad.append("%s: module.json=%s ≠ CHANGELOG 最上面 %s" % (mj.parent.name, ver, top))
    out.append(Result("V1.2", "每個模組 module.json version ＝ CHANGELOG 最上面版號（%d 個模組）" % n, FAIL if bad else PASS, _short(bad) or "一致"))
    try:
        manifest = json.loads(_read(root / "backend/version_manifest.json"))
    except (OSError, ValueError) as e:
        out.append(Result("V1.3", "version_manifest 可讀", FAIL, str(e)))
        manifest = []
    else:
        nxt = [e for e in manifest if str(e.get("version", "")).startswith("next")]
        malformed = [e.get("version") for e in manifest if not re.match(r"^\d{4}-\d{2}-\d{2}[a-z0-9]{0,3}$", str(e.get("version", "")))
                     and not str(e.get("version", "")).startswith("next")]
        dup = {}
        for e in manifest:
            dup.setdefault((e.get("module"), e.get("version")), 0)
            dup[(e.get("module"), e.get("version"))] += 1
        dups = [k for k, v in dup.items() if v > 1]
        bad = (["%d 筆 version=next" % len(nxt)] if nxt else []) + (["格式不對：%s" % _short(malformed, 5)] if malformed else []) + \
              (["重複 (模組,版號)：%s" % _short(dups, 5)] if dups else [])
        out.append(Result("V1.3", "version_manifest：沒有 next 佔位、版號格式、無重複", FAIL if bad else PASS,
                          "；".join(bad) or "%d 筆；最新 %s" % (len(manifest), latest_manifest_version(manifest) or "—")))
    db = _read(root / "backend/db.py")
    up = _read(root / "backend/core/upgrade.py")
    cur = re.search(r"^CURRENT_VERSION\s*=\s*(\d+)", db, re.M)
    b1 = re.search(r"^V9_BASELINE\s*=\s*(\d+)", db, re.M)
    b2 = re.search(r"^V9_BASELINE\s*=\s*(\d+)", up, re.M)
    if not (cur and b1 and b2):
        out.append(Result("V1.4", "CURRENT_VERSION／V9_BASELINE", FAIL, "找不到常數（db.CURRENT_VERSION=%s db.V9_BASELINE=%s upgrade.V9_BASELINE=%s）" % (cur and cur.group(1), b1 and b1.group(1), b2 and b2.group(1))))
    else:
        c, x, y = int(cur.group(1)), int(b1.group(1)), int(b2.group(1))
        bad = [] if x == y else ["db.V9_BASELINE=%d ≠ upgrade.V9_BASELINE=%d" % (x, y)]
        if x > c:
            bad.append("V9_BASELINE %d > CURRENT_VERSION %d" % (x, c))
        out.append(Result("V1.4", "CURRENT_VERSION ≥ V9_BASELINE 且 db／upgrade 兩處基準一致", FAIL if bad else PASS,
                          "；".join(bad) or "CURRENT_VERSION=%d V9_BASELINE=%d" % (c, x)))
    left = []
    for cl in [root / "backend/core/CHANGELOG.md", *sorted((root / "backend/modules").glob("*/CHANGELOG.md"))]:
        if cl.exists() and re.search(r"^##\s+\(next", _read(cl), re.M):
            left.append(str(cl.relative_to(root)).replace("\\", "/"))
    for mj in sorted((root / "backend/modules").glob("*/module.json")):
        if re.search(r'"version"\s*:\s*"next', _read(mj)):
            left.append(str(mj.relative_to(root)).replace("\\", "/"))
    snap_t = _read(root / "backend/tests/platform/l1_interface_snapshot.json")
    if re.search(r'"core_version"\s*:\s*"next"', snap_t):
        left.append("backend/tests/platform/l1_interface_snapshot.json")
    out.append(Result("V1.5", "沒有殘留的 (next)／next 佔位", FAIL if left else PASS, _short(left) or "乾淨"))
    return out


# ═══════════════════════════ V2 文件 ═══════════════════════════════════════════════════════════════════
_CI_LINE = re.compile(r"^- 來源檔：(?P<path>[^｜\s]+)｜來源 commit：(?P<sha>[0-9a-f]{7,40})\s*$", re.M)


def check_cache_index(root: Path, n=8):
    idx = root / "docs/platform/CACHE-INDEX.md"
    if not idx.exists():
        return [Result("V2.1", "CACHE-INDEX 新鮮", FAIL, "docs/platform/CACHE-INDEX.md 不存在")]
    es = [(m["path"], m["sha"]) for m in _CI_LINE.finditer(_read(idx))]
    missing = [p for p, _ in es if not (root / p).exists()]
    stale, unknown = [], []
    for p, sha in es:
        if p in missing:
            continue
        r = _git(root, "rev-list", "--count", "%s..HEAD" % sha, "--", p)
        if r.returncode != 0 or not r.stdout.strip().isdigit():
            unknown.append(p)
        elif int(r.stdout.strip()) > n:
            stale.append("%s 落後 %s 個 commit" % (p, r.stdout.strip()))
    if missing or not es:
        return [Result("V2.1", "CACHE-INDEX 新鮮", FAIL, ("來源檔不存在：" + _short(missing)) if missing else "沒有解析到任何摘要段")]
    if stale or unknown:
        return [Result("V2.1", "CACHE-INDEX 新鮮（來源 commit 落後 ≤ %d）" % n, WARN, _short(stale + ["無法判斷：" + p for p in unknown]))]
    return [Result("V2.1", "CACHE-INDEX 新鮮（來源 commit 落後 ≤ %d）" % n, PASS, "%d 段都新鮮" % len(es))]


def check_regen(root: Path, python=None):
    py = python or sys.executable
    r = subprocess.run([py, "tools/platform/regen_all.py", "--check"], cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1"))
    stale = [l.strip() for l in r.stdout.splitlines() if l.strip()]
    if r.returncode == 0:
        return [Result("V2.2", "產生檔（dep_graph／UNIT-INDEX／test_map）是最新（regen_all --check）", PASS, "三份都最新")]
    if r.returncode == 1:
        return [Result("V2.2", "產生檔是最新（regen_all --check）", FAIL, "過期：" + _short(stale) + "（重產：python tools/platform/regen_all.py）")]
    return [Result("V2.2", "產生檔是最新（regen_all --check）", FAIL, "工具出錯 exit=%d：%s" % (r.returncode, (r.stderr or r.stdout).strip()[-200:]))]


_MD_LINK = re.compile(r"(?<!!)\[[^\]\n]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_TICK_PATH = re.compile(r"`((?:docs|backend|frontend|tools)/[A-Za-z0-9_./\-]+\.[A-Za-z0-9]{1,5})`")
_LINK_SKIP_DIRS = {"archive", "windows", "audit", "node_modules", ".git"}


def _doc_files(root: Path):
    out = list(root.glob("*.md"))
    for sub in ("docs/quick", "docs/platform"):
        base = root / sub
        if base.is_dir():
            for p in base.rglob("*.md"):
                if not (set(p.relative_to(root).parts) & _LINK_SKIP_DIRS):
                    out.append(p)
    return sorted(set(out))


def find_dangling_links(root: Path, files=None):
    """⇒ (markdown 連結壞了 [(檔, 連結)], 反引號路徑不存在 [(檔, 路徑)])。純函式。"""
    broken, ticks = [], []
    for f in (files if files is not None else _doc_files(root)):
        text = _read(f)
        text = re.sub(r"```.*?```", "", text, flags=re.S)
        for m in _MD_LINK.finditer(text):
            t = m.group(1)
            if re.match(r"^(https?:|mailto:|#|tel:)", t) or "<" in t or "{" in t:
                continue
            target = t.split("#")[0].split("?")[0]
            if not target:
                continue
            p = (root / target.lstrip("/")) if target.startswith("/") else (f.parent / target)
            if not p.exists():
                broken.append((str(f.relative_to(root)).replace("\\", "/"), t))
        for m in _TICK_PATH.finditer(text):
            t = m.group(1)
            if any(c in t for c in "*<>{}") or not (root / t).exists() and not list(root.glob(t)):
                if not any(c in t for c in "*<>{}"):
                    ticks.append((str(f.relative_to(root)).replace("\\", "/"), t))
    return broken, ticks


def check_links(root: Path):
    broken, ticks = find_dangling_links(root)
    allow = set(load_allow().get("dangling_ticks", []))
    ticks = [(f, p) for f, p in ticks if "%s::%s" % (f, p) not in allow and p not in allow
             and not any(re.search(rx, p) for rx in load_allow().get("dangling_tick_patterns", []))]
    lok = set(load_allow().get("dangling_links_ok", []))
    broken = [(f, t) for f, t in broken if "%s::%s" % (f, t) not in lok]
    out = [Result("V2.3a", "docs 的 markdown 相對連結沒有指向不存在的檔（KEEP 文件；archive／windows／audit 不查）", FAIL if broken else PASS,
                  _short("%s → %s" % b for b in broken) or "沒有壞連結")]
    out.append(Result("V2.3b", "docs 反引號寫的 repo 路徑都存在", WARN if ticks else PASS,
                      _short("%s → %s" % t for t in ticks) or "都存在"))
    return out


def check_export_ignore(root: Path):
    out = []
    for sub in ("docs/windows", "docs/platform/archive"):
        ls = _git(root, "ls-files", "--", sub)
        files = [l for l in ls.stdout.splitlines() if l.strip()]
        if not files:
            out.append(Result("V2.4", ".gitattributes export-ignore：%s" % sub, SKIP, "此樹沒有追蹤的檔"))
            continue
        ca = _git(root, "check-attr", "export-ignore", "--stdin", "-z", input="\0".join(files) + "\0")
        # 輸出格式（-z）：path\0attr\0value\0
        parts = ca.stdout.split("\0")
        bad = []
        for i in range(0, len(parts) - 2, 3):
            if parts[i + 2] != "set":
                bad.append(parts[i])
        out.append(Result("V2.4", ".gitattributes export-ignore 涵蓋 %s（%d 檔）" % (sub, len(files)), FAIL if bad else PASS,
                          ("沒涵蓋：" + _short(bad)) if bad else "全部 export-ignore"))
    return out


# ═══════════════════════════ V3 端點 ═══════════════════════════════════════════════════════════════════
_DEC_NAMES = {"get", "post", "put", "patch", "delete", "options", "head"}


def _str_const(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def collect_routes(root: Path):
    """靜態掃出後端路由 ⇒ [{method, path, file, func, authed(bool), has_prefix}]。
    認得 `@router.get("/x")`／`@app.get(...)`；router 的 `APIRouter(prefix=…)` 前綴補上；handler 內有授權檢查
    （呼叫 *require*／*_guard*／讀 authorization／Depends）才算 authed。"""
    out = []
    bases = [root / "backend/routers", root / "backend/modules", root / "backend/main.py"]
    files = []
    for b in bases:
        if b.is_file():
            files.append(b)
        elif b.is_dir():
            for p in b.rglob("*.py"):
                parts = set(p.relative_to(root).parts)
                if parts & {"tests", "migrations", "__pycache__"}:
                    continue
                files.append(p)
    for p in sorted(files):
        try:
            tree = ast.parse(_read(p))
        except SyntaxError:
            continue
        prefix = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and getattr(node.value.func, "id", getattr(node.value.func, "attr", "")) == "APIRouter":
                pfx = ""
                for kw in node.value.keywords:
                    if kw.arg == "prefix":
                        pfx = _str_const(kw.value) or ""
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        prefix[t.id] = pfx
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for d in node.decorator_list:
                if not (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in _DEC_NAMES and d.args):
                    continue
                path = _str_const(d.args[0])
                if path is None:
                    continue
                owner = d.func.value.id if isinstance(d.func.value, ast.Name) else ""
                seg = ast.get_source_segment(_read(p), node) or ""
                authed = bool(re.search(r"_require_user|require_\w+|_guard\w*|check_\w*_permission|Depends\(|current_user|\bauthorization\b[^=:]*\)|authorization\s*\)", seg.split(":", 1)[-1] if False else seg)) \
                    or len(re.findall(r"\bauthorization\b", seg)) > 1
                out.append({"method": d.func.attr.upper(), "path": prefix.get(owner, "") + path, "file": str(p.relative_to(root)).replace("\\", "/"),
                            "func": node.name, "authed": authed})
    return out


def public_api_paths(root: Path):
    s = _read(root / "backend/main.py")
    m = re.search(r"_PUBLIC_API_PATHS\s*=\s*\{(.*?)\n\}", s, re.S)
    return set(re.findall(r'"(/api/[^"]*)"', m.group(1))) if m else set()


def _path_regex(path):
    return re.compile("^" + re.sub(r"\\{[^}]+\\}", "[^/]+", re.escape(path)) + "$")


def check_route_auth(root: Path, routes=None):
    """三層：① main.py 的 auth_middleware 對所有 /api/ 路徑（公開白名單除外）要求登入；② 公開白名單 ⊆ 已登記的基準（新增公開路徑必須明確加進
    final_verify_allow.json 的 public_ok）且每個都對得到路由；③ handler 自己沒有授權檢查的路由（只靠 ① 的全站閘）——列出數量（WARN，
    已知例外在 auth_ok）。"""
    routes = routes if routes is not None else collect_routes(root)
    allow = load_allow()
    main_src = _read(root / "backend/main.py")
    gate = re.search(r"async def auth_middleware\(.*?\n(?=@app\.middleware|\Z)", main_src, re.S)
    gate_ok = bool(gate) and 'path in _PUBLIC_API_PATHS' in gate.group(0) and 'startswith("/api/")' in gate.group(0)
    out = [Result("V3.2a", "main.py auth_middleware：除公開白名單外 /api/ 一律要登入", PASS if gate_ok else FAIL,
                  "閘門在" if gate_ok else "找不到 auth_middleware 的 /api/ 放行條件")]
    pub = public_api_paths(root)
    api = [r for r in routes if r["path"].startswith("/api")]
    new_pub = sorted(p for p in pub if p not in set(allow.get("public_ok", [])))
    rx = [_path_regex(r["path"]) for r in api]
    orphan = sorted(p for p in pub if not any(x.match(p) for x in rx))
    bad = (["新增公開路徑（未登記）：" + _short(new_pub)] if new_pub else []) + (["公開路徑沒有對應的路由：" + _short(orphan)] if orphan else [])
    out.append(Result("V3.2b", "公開 API 白名單（%d 條）只含已登記的路徑且都對得到路由" % len(pub), FAIL if bad else PASS, "；".join(bad) or "與基準一致"))
    ok_set = set(allow.get("auth_ok", []))
    weak = [r for r in api if not r["authed"] and not any(_path_regex(r["path"]).match(p) for p in pub) and "%s %s" % (r["method"], r["path"]) not in ok_set
            and r["path"] not in ok_set]
    out.append(Result("V3.2c", "每條 /api 路由 handler 自己有授權檢查（%d 條）；沒有的只靠全站閘門" % len(api), WARN if weak else PASS,
                      _short("%s %s" % (r["method"], r["path"]) for r in weak) or "全部 handler 都有檢查"))
    return out


def check_modules_routes(root: Path, python=None):
    py = python or sys.executable
    r = subprocess.run([py, "tools/platform/dep_scan.py", "--check-modules"], cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1"))
    tail = (r.stdout + r.stderr).strip().splitlines()
    ok = r.returncode == 0
    return [Result("V3.1", "路由歸屬／module.json api_prefixes ↔ modules.json（dep_scan --check-modules）", PASS if ok else FAIL,
                   "歸屬一致" if ok else _short(tail[-8:], 8))]


def _frontend_calls(root: Path):
    call = re.compile(r"""[`'"](/api/[A-Za-z0-9_\-./{}$:]*(?:\$\{[^}]*\}[A-Za-z0-9_\-./]*)*)""")
    out = []
    base = root / "frontend"
    for p in sorted(base.rglob("*")) if base.is_dir() else []:
        if p.suffix in (".html", ".js") and "vendor" not in p.parts:
            s = _read(p)
            for m in call.finditer(s):
                out.append((m.group(1), str(p.relative_to(root)).replace("\\", "/")))
    return out


def find_dangling_frontend_calls(root: Path, routes=None):
    """前端字面的 /api/... 呼叫對不到任何後端路由 ⇒ {呼叫路徑: [檔]}。`${…}`、{x} 都當單一路徑段；
    結尾還接著動態內容（`${…` 沒關、字串拼接）時，只比對前面完整的路徑段（前綴比對）。"""
    routes = routes if routes is not None else collect_routes(root)
    full = [r["path"] for r in routes if r["path"].startswith("/api")]
    segs = [p.strip("/").split("/") for p in full]
    miss = {}

    def seg_match(rs, cs):
        return (rs.startswith("{") and rs.endswith("}")) or rs == cs or cs == "X"
    for c, f in _frontend_calls(root):
        if "..." in c:                                                   # 註解／說明文字裡的示意路徑（/api/vouchers/{voucher_id}/...）不是呼叫
            continue
        dyn_tail = bool(re.search(r"\$\{[^}]*$|\$\{[^}]*\}[^/]*\$\{[^}]*$", c)) or c.endswith("/") or             bool(re.search(r"/(?:\$\{[^}]*\})+(?:\?|$)", c))            # 最後一段整段是動態內容（可能含多段路徑）⇒ 只比對前面完整的段
        c2 = re.sub(r"(?:\$\{[^}]*\})+", "X", c)
        if "${" in c2:
            c2 = c2[:c2.index("${")]
            c2 = c2.rsplit("/", 1)[0] if not c2.endswith("/") else c2
            dyn_tail = True
        c2 = c2.split("?")[0].rstrip("/")
        if not c2 or c2 == "/api":
            continue
        cs = c2.strip("/").split("/")
        ok = False
        for rs in segs:
            if dyn_tail:
                if len(rs) >= len(cs) and all(seg_match(rs[i], cs[i]) for i in range(len(cs))):
                    ok = True
                    break
            else:
                if len(rs) == len(cs) and all(seg_match(rs[i], cs[i]) for i in range(len(cs))):
                    ok = True
                    break
                if len(rs) == len(cs) + 1 and rs[-1].startswith("{") and all(seg_match(rs[i], cs[i]) for i in range(len(cs))):
                    ok = True                                               # "/api/foo/" + id 拼接
                    break
        if not ok:
            miss.setdefault(c2, set()).add(f)
    return {k: sorted(v) for k, v in miss.items()}


def check_frontend_calls(root: Path, routes=None):
    miss = find_dangling_frontend_calls(root, routes)
    allow = set(load_allow().get("frontend_calls_ok", []))
    bad = {k: v for k, v in miss.items() if k not in allow}
    return [Result("V3.3", "前端 /api 呼叫都對得到後端路由（%d 個呼叫路徑不重複）" % len({c for c, _ in _frontend_calls(root)}), FAIL if bad else PASS,
                   _short("%s（%s）" % (k, v[0]) for k, v in sorted(bad.items())) or "沒有懸空呼叫")]


def check_ip_registry(root: Path):
    """提供者名稱的一致性：程式裡被消費的提供者名稱（registry.providers／single_provider／provider("x")）都有人宣告
    （ModuleSpec.providers／registry.provide／L1 provide），且宣告的名稱在 INTEGRATION-POINTS.md 找得到。"""
    cons, prov = {}, {}
    consumer = re.compile(r"""registry\.(?:single_provider|providers|provider)\(\s*["']([a-z][a-z0-9_.\-]*)["']""")
    declare_tuple = re.compile(r"""\(\s*["']([a-z][a-z0-9_.\-]*\.[a-z0-9_.\-]+)["']\s*,\s*["'][a-z0-9_\-]+["']\s*\)\s*:""")
    declare_call = re.compile(r"""\bprovide\(\s*["']([a-z][a-z0-9_.\-]*)["']""")
    for p in sorted((root / "backend").rglob("*.py")):
        parts = set(p.relative_to(root).parts)
        if parts & {"tests", "__pycache__", "migrations"}:
            continue
        s = _read(p)
        rel = str(p.relative_to(root)).replace("\\", "/")
        for m in consumer.finditer(s):
            cons.setdefault(m.group(1), set()).add(rel)
        for rx in (declare_tuple, declare_call):
            for m in rx.finditer(s):
                prov.setdefault(m.group(1), set()).add(rel)
    doc = _read(root / "docs/platform/INTEGRATION-POINTS.md") if (root / "docs/platform/INTEGRATION-POINTS.md").exists() else ""
    allow = set(load_allow().get("ip_ok", []))
    no_decl = sorted(n for n in cons if n not in prov and n not in allow)
    undocumented = sorted(n for n in prov if n not in doc and n not in allow)
    out = [Result("V3.4a", "被消費的提供者都有人宣告（%d 個名稱）" % len(cons), FAIL if no_decl else PASS,
                  _short("%s（%s）" % (n, sorted(cons[n])[0]) for n in no_decl) or "都有宣告")]
    out.append(Result("V3.4b", "宣告的提供者名稱都寫在 INTEGRATION-POINTS.md（%d 個）" % len(prov), WARN if undocumented else PASS,
                      _short(undocumented) or "都有文件"))
    return out


def check_probes(root: Path, routes=None):
    routes = routes if routes is not None else collect_routes(root)
    paths = [r["path"] for r in routes]
    bad = []
    n = 0
    for mj in sorted((root / "backend/modules").glob("*/module.json")):
        try:
            d = json.loads(_read(mj))
        except ValueError:
            continue
        prov = d.get("provides") or {}
        pre = prov.get("api_prefixes") or d.get("api_prefixes") or []
        for pr in prov.get("probes") or d.get("probes") or []:
            n += 1
            if not any(pr == p or pr.startswith(p.split("{")[0].rstrip("/") + "/") or p.startswith(pr.rstrip("/") + "/") or p.split("{")[0].rstrip("/") == pr for p in paths):
                bad.append("%s: probe %s 沒有對應的路由" % (mj.parent.name, pr))
            if pre and not any(pr == x or pr.startswith(x.rstrip("/") + "/") for x in pre):
                bad.append("%s: probe %s 不在 api_prefixes" % (mj.parent.name, pr))
    return [Result("V3.5", "module.json probes 都對得到路由且在 api_prefixes 內（%d 個）" % n, FAIL if bad else PASS, _short(bad) or "一致")]


# ═══════════════════════════ V4 追蹤樹衛生 ═══════════════════════════════════════════════════════════════
_HYGIENE = re.compile(r"(\.db(-wal|-shm)?$|\.sqlite3?$|\.pyc$|(^|/)__pycache__/|\.log$|\.bak$|\.tmp$|\.orig$|\.rej$|\.swp$|~$|(^|/)\.DS_Store$|(^|/)Thumbs\.db$|\.pre_overhead_)", re.I)


def check_tree_hygiene(root: Path):
    ls = _git(root, "ls-files", "-z")
    files = [f for f in ls.stdout.split("\0") if f]
    allow = load_allow()
    ok_files = set(allow.get("tracked_ok", []))
    bad = [f for f in files if _HYGIENE.search(f) and f not in ok_files]
    out = [Result("V4.1", "沒有追蹤資料庫／pyc／__pycache__／log／備份暫存檔（%d 個追蹤檔）" % len(files), FAIL if bad else PASS, _short(bad) or "乾淨")]
    root_files = sorted(f for f in files if "/" not in f)
    allowed_root = set(allow.get("root_files", []))
    stray = [f for f in root_files if f not in allowed_root]
    out.append(Result("V4.2", "根目錄沒有計畫外的追蹤檔（%d 個在白名單）" % len(allowed_root), FAIL if stray else PASS,
                      _short(stray) or "根目錄 %d 個檔都在白名單" % len(root_files)))
    return out


# ═══════════════════════════ V5 正式機部署對照 ═══════════════════════════════════════════════════════
def latest_report(folder: Path):
    """最新一筆正式機回報（資料夾名以時間戳開頭：YYYYMMDD_HHMMSS_<sha>_<狀態>）⇒ 摘要.md 路徑或 None。"""
    dirs = sorted((d for d in folder.iterdir() if d.is_dir() and re.match(r"^\d{8}_\d{6}_", d.name)), key=lambda d: d.name)
    for d in reversed(dirs):
        f = d / "摘要.md"
        if f.exists():
            return f
    return None


def parse_summary(text: str):
    d = {}
    m = re.search(r"::RESULT::\s*(.*)", text)
    if m:
        d.update(dict(kv.split("=", 1) for kv in m.group(1).split() if "=" in kv))
    m = re.search(r"前後 commit：([0-9a-f]{7,40})\s*[→\->]+\s*([0-9a-f]{7,40})", text)
    if m:
        d["old_commit"], d["new_commit"] = m.group(1), m.group(2)
    m = re.search(r"api_version[^0-9]*(\d{4}-\d{2}-\d{2}[a-z]{0,2})", text)
    if m:
        d["api_version"] = m.group(1)
    return d


def check_deployed(root: Path, prod_report: Path, baseline_ref="origin/platform"):
    if not prod_report or not Path(prod_report).is_dir():
        return [Result("V5.1", "正式機部署對照", SKIP, "沒有給 --prod-report（或資料夾不存在）")]
    f = latest_report(Path(prod_report))
    if f is None:
        return [Result("V5.1", "正式機部署對照", FAIL, "報告資料夾裡找不到任何『摘要.md』")]
    s = parse_summary(_read(f))
    out = []
    ok_run = s.get("status") == "success" and s.get("service") == "up" and s.get("exit") == "0"
    out.append(Result("V5.1", "最新套用結果成功且服務在（%s）" % f.parent.name, PASS if ok_run else FAIL,
                      "status=%s service=%s exit=%s rolled_back=%s" % (s.get("status"), s.get("service"), s.get("exit"), s.get("rolled_back"))))
    new = s.get("new_commit", "")
    r = _git(root, "rev-parse", "--verify", baseline_ref + "^{commit}")
    base = r.stdout.strip() if r.returncode == 0 else ""
    if not new or not base:
        out.append(Result("V5.2", "部署的 commit ＝ 基準 %s" % baseline_ref, FAIL, "部署 commit=%r；基準解析=%r（%s）" % (new, base, r.stderr.strip()[:80])))
    else:
        same = base.startswith(new) or new.startswith(base)
        out.append(Result("V5.2", "部署的 commit ＝ 基準 %s" % baseline_ref, PASS if same else FAIL, "部署 %s；基準 %s" % (new[:12], base[:12])))
    try:
        manifest = json.loads(_read(root / "backend/version_manifest.json"))
        latest = latest_manifest_version(manifest)
    except (OSError, ValueError, KeyError):
        latest = None
    api = s.get("api_version")
    out.append(Result("V5.3", "部署的 api_version ＝ 樹的 manifest 最新版號", PASS if (api and api == latest) else FAIL, "部署 %s；樹 %s" % (api, latest)))
    latest_json = Path(prod_report) / "status" / "latest.json"
    if latest_json.exists():
        try:
            j = json.loads(_read(latest_json))
            dc = str(j.get("deployed_commit", ""))
            same = bool(dc) and bool(new) and (new.startswith(dc.rstrip("…")) or dc.startswith(new))
            errs = j.get("errors")
            out.append(Result("V5.4", "status\\latest.json 與摘要一致且 errors 為空", PASS if (same and not errs) else FAIL,
                              "deployed_commit=%s errors=%s" % (dc[:12], errs)))
        except ValueError as e:
            out.append(Result("V5.4", "status\\latest.json 可讀", FAIL, str(e)))
    else:
        out.append(Result("V5.4", "status\\latest.json", SKIP, "沒有 status\\latest.json"))
    return out


# ═══════════════════════════ 組裝／輸出 ═══════════════════════════════════════════════════════════════
GROUPS = [
    ("V1", "版本一致", lambda c: check_versions(c["root"])),
    ("V2.1", "文件：CACHE-INDEX", lambda c: check_cache_index(c["root"])),
    ("V2.2", "文件：產生檔", lambda c: check_regen(c["root"], c["python"])),
    ("V2.3", "文件：連結", lambda c: check_links(c["root"])),
    ("V2.4", "文件：export-ignore", lambda c: check_export_ignore(c["root"])),
    ("V3.1", "端點：歸屬", lambda c: check_modules_routes(c["root"], c["python"])),
    ("V3.2", "端點：授權", lambda c: check_route_auth(c["root"], c["routes"]())),
    ("V3.3", "端點：前端呼叫", lambda c: check_frontend_calls(c["root"], c["routes"]())),
    ("V3.4", "端點：提供者登錄", lambda c: check_ip_registry(c["root"])),
    ("V3.5", "端點：probes", lambda c: check_probes(c["root"], c["routes"]())),
    ("V4", "樹衛生", lambda c: check_tree_hygiene(c["root"])),
    ("V5", "正式機部署對照", lambda c: check_deployed(c["root"], c["prod_report"], c["baseline_ref"])),
]


def _match(rid, spec):
    """結果編號是否屬於 spec（V2.3 涵蓋 V2.3a／V2.3b；V1 涵蓋 V1.x；V1 不涵蓋 V10）。"""
    return rid == spec or (rid.startswith(spec) and not rid[len(spec)].isdigit())


def _selected(gid, only, skip):
    """這一組要不要跑：沒指定 only 或與任一 only 有重疊；且沒有被 skip 的祖先／同名項目整組略過。"""
    if only and not any(_match(gid, s) or _match(s, gid) for s in only):
        return False
    return not any(_match(gid, s) for s in skip)


def run_checks(root, python=None, prod_report=None, baseline_ref="origin/platform", only=(), skip=()):
    root = Path(root).resolve()
    cache = {}

    def routes():
        if "r" not in cache:
            cache["r"] = collect_routes(root)
        return cache["r"]
    ctx = {"root": root, "python": python, "prod_report": prod_report, "baseline_ref": baseline_ref, "routes": routes}
    results = []
    for gid, title, fn in GROUPS:
        if not _selected(gid, only, skip):
            continue
        try:
            rs = [r for r in fn(ctx) if (not only or any(_match(r.id, x) or _match(x, r.id) for x in only)) and not any(_match(r.id, x) for x in skip)]
        except Exception as e:                                     # noqa: BLE001 — 一組檢查自己壞掉也要回報成 FAIL，不能讓整份報告消失
            rs = [Result(gid, title, FAIL, "檢查本身出錯：%s: %s" % (type(e).__name__, e))]
        results.extend(rs)
    return results


def verdict(results):
    return FAIL if any(r.status == FAIL for r in results) else PASS


def render_text(results):
    lines = []
    for r in results:
        lines.append("[%-4s] %-6s %s" % (r.status, r.id, r.item) + (("\n         " + r.detail) if r.detail and r.status != PASS else ""))
    n = {k: sum(1 for r in results if r.status == k) for k in (PASS, FAIL, WARN, SKIP)}
    lines.append("")
    lines.append("結論：%s（PASS %d／FAIL %d／WARN %d／SKIP %d）" % (verdict(results), n[PASS], n[FAIL], n[WARN], n[SKIP]))
    return "\n".join(lines)


def render_markdown(results, root, tag=""):
    n = {k: sum(1 for r in results if r.status == k) for k in (PASS, FAIL, WARN, SKIP)}
    head = _git(Path(root), "rev-parse", "--short", "HEAD").stdout.strip()
    lines = ["# 最終系統驗證 %s" % tag, "",
             "> `tools/platform/final_verify.py` 產生；樹：`%s`（HEAD `%s`）；時間：%s" % (root, head, datetime.now().strftime("%Y-%m-%d %H:%M")), "",
             "**結論：%s**（PASS %d／FAIL %d／WARN %d／SKIP %d）" % (verdict(results), n[PASS], n[FAIL], n[WARN], n[SKIP]), "",
             "| 項目 | 結果 | 說明 |", "|---|---|---|"]
    for r in results:
        lines.append("| %s %s | %s | %s |" % (r.id, r.item.replace("|", "／"), r.status, (r.detail or "").replace("|", "／").replace("\n", " ")))
    lines += ["", "## 需要人判斷的項目", ""]
    todo = [r for r in results if r.status in (FAIL, WARN)]
    lines += (["- **%s %s**（%s）：%s" % (r.id, r.item, r.status, r.detail) for r in todo] or ["（無）"])
    return "\n".join(lines) + "\n"


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                                # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=str(HERE.parents[1]), help="要驗證的 MOTRIX-PLATFORM 樹（預設＝本工具所在的樹）")
    ap.add_argument("--python", default=None, help="子工具用的 Python（預設＝目前這個）")
    ap.add_argument("--prod-report", default="", help="正式機回報資料夾（只讀；給了才跑 V5）")
    ap.add_argument("--baseline-ref", default="origin/platform", help="V5 對照的基準（分支、tag 或 commit）")
    ap.add_argument("--only", default="", help="只跑這些組別／項目，逗號分隔（例：V1,V3.2）")
    ap.add_argument("--skip", default="", help="略過這些組別／項目")
    ap.add_argument("--md", default="", help="另存 markdown 總結到這個檔")
    ap.add_argument("--tag", default="", help="markdown 標題註記（例：T49）")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    only = [s for s in a.only.split(",") if s]
    skip = [s for s in a.skip.split(",") if s]
    res = run_checks(a.root, a.python, Path(a.prod_report) if a.prod_report else None, a.baseline_ref, only, skip)
    if a.md:
        Path(a.md).write_text(render_markdown(res, a.root, a.tag), encoding="utf-8", newline="\n")
    if a.json:
        print(json.dumps({"verdict": verdict(res), "results": [r.as_dict() for r in res]}, ensure_ascii=False, indent=1))
    else:
        print(render_text(res))
    return 1 if verdict(res) == FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
