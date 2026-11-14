"""核心大版本升級工具（T86；PM「核心大版本升級會卡死」）：核心升主版號（1.x → 2.0）時，一次把所有模組的 core 相容範圍放寬到下一個主版號。

## 為什麼要有這支
`train_number.py assign` 只要看到 L1 介面「有修改或刪除」就把核心升成下一個主版號；可是每個 `module.json` 都宣告
`"core": ">=1.0,<2.0"`——核心一升到 2.0，**所有**模組載入器判「不相容」、全部不載入（路由 404）。
以前靠臨時繞過（stub）撐過去。這支工具把「升大版本」變成一個有檢查、可預演、可重複的步驟。

## 用法（列車樹根目錄；Python 一律 D:\\MOTRIX-PLATFORM\\.venv312\\Scripts\\python.exe）
  python tools/platform/core_major_bump.py status                      列出核心版本、下一個主版號，以及每個模組的 core 範圍是否已接受
  python tools/platform/core_major_bump.py check [--base REF]          守門：核心要升主版號（L1 介面相對 --base 快照需要主版號，或 CHANGELOG 最上面是 `(next:major)`），
                                                                       或目前 CORE_VERSION 超出某個模組的範圍，而模組範圍沒一起處理 ⇒ exit 1 並指到本工具
  python tools/platform/core_major_bump.py apply --dry-run             預演：做 L1 相容檢查、印出會怎麼改，不寫任何檔（exit 3＝有要改、0＝不用改）
  python tools/platform/core_major_bump.py apply [--skip-tests]        L1 相容檢查 → 各模組測試 → 全部過了才一次改寫所有 `module.json` 的 core 上限＋寫各模組與核心 CHANGELOG
                                                                       （這包不需要升主版號時要加 --force 才會真的改）
  （`--root PATH` 指到別的樹；`--to N` 指定目標主版號，預設＝目前核心主版號＋1；若已有模組不接受目前核心＝補救，目標取目前主版號）

## 規則
- 只改 `module.json` 裡頂層的 `"core": "<範圍>"`；**不碰 `"version"`**（版號由列車 train_number 取）。只放寬**上限**到 `<(目標主版號+1).0`，下限不動
  ⇒ 放寬後的模組仍能裝在舊核心上（模組更新 `module_update._core_ok`／載入器 `core_compatible` 同一套比較）。
- 每個被改的模組 CHANGELOG 最上面加 `## (next)` 段落（版號由列車取）；核心 CHANGELOG 也加一段。
- **L1 相容檢查**：L1 介面相對 `--base`（預設 origin/platform 的快照，與 train_number 同一基準）被「修改或刪除」的名稱，若有模組程式（modules/*，不含 tests）還在 import／使用 ⇒ 拒絕
  （範圍放寬救不了呼叫端壞掉）。找不到基準 ⇒ 明印「L1 相容檢查未做」，不默默當成通過。模組測試跑在**舊**範圍上，所以 L1 掃描才是相容性的證據。
- 結束碼：0＝完成／不用改／檢查通過；1＝拒絕或守門不過；3＝`apply --dry-run` 有要改（正常，不是失敗）。
- **模組測試**：依序跑每個有 tests 目錄的模組（`pytest backend/modules/<key>/tests`，serial，暫存放樹內 `.pt-core-major`，用完刪）；任何一個紅 ⇒ 拒絕、不改任何檔。
- 冪等：所有模組都已接受目標主版號 ⇒ 什麼都不做。
- 守門測試：backend/tests/platform/test_core_major_bump_2026_11_14.py。規則文件：docs/platform/MODULE-GUIDE.md §2「核心大版本升級」。
"""
import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REGISTRY = "backend/core/registry.py"
MODULES = "backend/modules"
CORE_CHANGELOG = "backend/core/CHANGELOG.md"
SNAPSHOT = "backend/tests/platform/l1_interface_snapshot.json"
TOOL = "tools/platform/core_major_bump.py"
PY = r"D:\MOTRIX-PLATFORM\.venv312\Scripts\python.exe"
HINT = "先預演 `%s %s apply --dry-run`，確認後 `%s %s apply`（會一次放寬所有 module.json 的 core 上限、寫 CHANGELOG）" % (PY, TOOL, PY, TOOL)

_CORE_LINE = re.compile(r'^(?P<indent>[ \t]*)"core"\s*:\s*"(?P<spec>[^"]*)"(?P<tail>\s*,?)\s*$', re.M)
_UPPER = re.compile(r"^\s*(<=|<)\s*(\d+(?:\.\d+)*)\s*$")
_PENDING_MAJOR = re.compile(r"^##[ \t]+\(next:major\)", re.M)


# ── 版本與範圍 ──────────────────────────────────────────────────────────

def core_version(root):
    src = (Path(root) / REGISTRY).read_text(encoding="utf-8")
    m = re.search(r'^CORE_VERSION\s*=\s*"([^"]*)"', src, re.M)
    if not m:
        raise SystemExit("讀不到 %s 的 CORE_VERSION" % REGISTRY)
    return m.group(1)


def major_of(version):
    return int(str(version).split(".")[0])


def compatible(spec, version):
    """與載入器、模組更新同一套比較（core.loader.core_compatible）；看不懂 ⇒ False。"""
    sys.path.insert(0, str(REPO / "backend"))
    from core.loader import core_compatible
    try:
        return core_compatible(spec, version)
    except ValueError:
        return False


def relax_spec(spec, target_major):
    """把 spec 的上限放寬到 `<(target_major+1).0`。⇒ (新範圍, 說明)；不用改 ⇒ (spec, None)；不能自動改 ⇒ (spec, 原因)。
    只動上限：`<A.B`／`<=A.B` 且 A ≤ 目標主版號 ⇒ 換掉；沒有上限（`>=1.0`）⇒ 本來就接受；`==` 釘死 ⇒ 要人工處理。"""
    parts = [p.strip() for p in (spec or "").split(",") if p.strip()]
    if not parts:
        return spec, "範圍是空的"
    if compatible(spec, "%d.0" % target_major):
        return spec, None                                            # 本來就接受（例如 <2.5 對目標 2.0）
    new_upper = "<%d.0" % (target_major + 1)
    out, changed = [], False
    for p in parts:
        m = _UPPER.match(p)
        if m:
            top = int(m.group(2).split(".")[0])
            exclusive = m.group(1) == "<"
            limit = top if exclusive else top + 1                   # 這個上限實際擋掉的第一個主版號
            if limit <= target_major:
                out.append(new_upper)
                changed = True
                continue
        elif p.startswith("=="):
            return spec, "用 == 釘死版本，無法自動放寬"
        out.append(p)
    if not changed:
        return spec, None
    new = ",".join(out)
    return new, None


def module_specs(root):
    """{key: (module.json 路徑, core 範圍或 None)}"""
    res = {}
    for mj in sorted((Path(root) / MODULES).glob("*/module.json")):
        try:
            spec = json.loads(mj.read_text(encoding="utf-8-sig")).get("core")
        except ValueError:
            spec = None
        res[mj.parent.name] = (mj, spec)
    return res


# ── 守門 ────────────────────────────────────────────────────────────────

def _group_by_spec(specs, version):
    """{範圍: [不接受 version 的模組…]}（同一個範圍的模組併成一行，不要一個模組一行）。"""
    bad = {}
    for key, spec in sorted(specs.items()):
        if not compatible(spec, version):
            bad.setdefault(spec, []).append(key)
    return bad


def guard_problems(core_ver, specs, major_pending):
    """純函式。specs＝{key: 範圍}。⇒ 問題清單（空＝可以；同範圍的模組併成一行，最後一行是怎麼修）。
    ① 目前 CORE_VERSION 超出某模組範圍 ⇒ 該模組不相容、啟動時不會載入；② 核心要升主版號但範圍還沒接受下一個主版號。"""
    problems = []
    for spec, keys in _group_by_spec(specs, core_ver).items():
        problems.append("%d 個模組的 core 範圍 %r 與目前核心 %s 不相容 ⇒ 啟動時這些模組不會載入（路由 404）：%s"
                        % (len(keys), spec, core_ver, "、".join(keys)))
    if major_pending:
        target = "%d.0" % (major_of(core_ver) + 1)
        for spec, keys in _group_by_spec(specs, target).items():
            problems.append("核心這包要升主版號（%s），但 %d 個模組的 core 範圍 %r 與 %s 不相容 ⇒ 升了之後這些模組全部載入失敗：%s"
                            % (target, len(keys), spec, target, "、".join(keys)))
    if problems:
        problems.append("⇒ " + HINT)
    return problems


def _git(root, *args):
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8")
    return r.stdout if r.returncode == 0 else None


def _l1_module(root):
    """載入該樹自己的 _l1_interface（沒有 ⇒ None；合成樹／沒有 L1 時略過 L1 判斷）。"""
    d = Path(root) / "backend" / "tests" / "platform"
    if not (d / "_l1_interface.py").is_file():
        return None
    for p in (str(d), str(Path(root) / "backend")):
        if p not in sys.path:
            sys.path.insert(0, p)
    import importlib
    sys.modules.pop("_l1_interface", None)
    return importlib.import_module("_l1_interface")


DEFAULT_BASE = "origin/platform"


def resolve_base(root, base=None):
    """L1 比較基準的 git ref：給了就用給的（解析不到 ⇒ ValueError）；沒給 ⇒ 預設 origin/platform（與 train_number 同一個基準），
    解析不到就回 None（呼叫端要明說「L1 相容檢查未做」，不可以默默當成通過）。"""
    if base:
        if _git(root, "rev-parse", "--verify", "%s^{commit}" % base) is None:
            raise ValueError("找不到 --base %s" % base)
        return base
    return DEFAULT_BASE if _git(root, "rev-parse", "--verify", "%s^{commit}" % DEFAULT_BASE) is not None else None


def l1_diff(root, base=None):
    """⇒ (added, changed, removed) 或 None（沒有 L1 工具、讀不到 base 的快照、或沒有 base）。
    ⚠ 不用樹內快照當基準：列車規則要求樹內快照永遠已是目前的介面，拿它比只會得到空差異（檢查形同虛設）。"""
    G = _l1_module(root)
    if G is None or not base:
        return None
    snap_text = _git(root, "show", "%s:%s" % (base, SNAPSHOT))
    if snap_text is None:
        return None
    return G.diff(json.loads(snap_text)["interface"], G.current_interface())


def major_pending(root, base=None):
    """⇒ (要升主版號?, 原因)。依據：L1 介面相對快照需要主版號（同 train_number 的判斷），或核心 CHANGELOG 最上面的佔位指定 `(next:major)`。"""
    cl = Path(root) / CORE_CHANGELOG
    if cl.is_file():
        text = cl.read_text(encoding="utf-8")
        first = re.search(r"^##[ \t]+(?!\(next)", text, re.M)
        head = text[:first.start()] if first else text
        if _PENDING_MAJOR.search(head):
            return True, "核心 CHANGELOG 有 `(next:major)`"
    d = l1_diff(root, base)
    if d is not None:
        a, c, r = d
        if c or r:
            return True, "L1 介面有 %d 項修改／%d 項刪除（需要主版號）" % (len(c), len(r))
    return False, ""


# ── L1 相容檢查 ─────────────────────────────────────────────────────────

def _unit_module_names(unit):
    """G1 單位名 ⇒ import 路徑（helper:x → helpers.x、plat:x → core.x、core:x → x）。"""
    kind, _, name = unit.partition(":")
    return {"helper": "helpers." + name, "plat": "core." + name, "core": name}.get(kind)


def breaking_names(changed, removed):
    """changed／removed（"unit::name  …"）⇒ {單位: {頂層名稱}}。成員（Class.method）算到 Class。"""
    res = {}
    for item in list(changed) + list(removed):
        key = item.split("  ")[0]
        unit, _, name = key.partition("::")
        res.setdefault(unit, set()).add(name.split(".")[0])
    return res


def _dotted(node):
    """Name／Attribute 鏈 ⇒ "a.b.c"；其他 ⇒ None。"""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def scan_module_uses(modules_dir, breaking):
    """模組程式（不含 tests）裡還在用的、被修改／刪除的 L1 名稱。⇒ ["modules/<key>/x.py: helpers.foo.bar", …]
    認得：from X import name（含 `import *`）、import X [as a] 之後的 a.name／X.name、from helpers import 子模組 [as a]、`import helpers` 後的 helpers.name。
    不認得（模組現況沒有用到）：動態 import／getattr、相對 import。"""
    by_mod = {}
    for unit, names in breaking.items():
        m = _unit_module_names(unit)
        if m:
            by_mod[m] = names
    helper_all = {}
    for unit, names in breaking.items():
        if unit.startswith("helper:"):
            for n in names:
                helper_all.setdefault(n, []).append(unit)
    hits = []
    for f in sorted(Path(modules_dir).rglob("*.py")):
        rel = f.relative_to(Path(modules_dir))
        if "tests" in rel.parts or f.name.startswith("test_") or f.name == "conftest.py":
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8-sig"))
        except (SyntaxError, ValueError):
            continue
        aliases = {}
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                if node.module in by_mod:
                    for a in node.names:
                        if a.name == "*":
                            found.add("%s.*（import *）" % node.module)
                        elif a.name in by_mod[node.module]:
                            found.add("%s.%s" % (node.module, a.name))
                elif node.module == "helpers":
                    for a in node.names:
                        if a.name in helper_all:                      # from helpers import name（helpers/__init__ 轉出的名稱）
                            found.add("helpers.%s" % a.name)
                        if "helpers." + a.name in by_mod:             # from helpers import <子模組>
                            aliases[a.asname or a.name] = "helpers." + a.name
                elif node.module == "core":
                    for a in node.names:
                        if "core." + a.name in by_mod:
                            aliases[a.asname or a.name] = "core." + a.name
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name in by_mod:
                        aliases[a.asname or a.name] = a.name
                    elif a.name == "helpers" and not a.asname:
                        aliases["helpers"] = "helpers"
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                d = _dotted(node.value)
                mod = aliases.get(d) if d else None
                if mod == "helpers":
                    if node.attr in helper_all:
                        found.add("helpers.%s" % node.attr)
                elif mod and node.attr in by_mod.get(mod, ()):
                    found.add("%s.%s" % (mod, node.attr))
        for h in sorted(found):
            hits.append("modules/%s: %s" % (rel.as_posix(), h))
    return hits


def unknown_units(breaking):
    """快照裡認不得的單位種類（工具不會掃它們的使用處）⇒ 要明說，不可以安靜略過。"""
    return sorted(u for u in breaking if _unit_module_names(u) is None)


def l1_compat_problems(root, base=None):
    """⇒ (問題清單, 說明清單)。說明＝這次 L1 相容檢查沒做完整的地方（沒有 base、單位種類不認得）；不是問題但一定要印出來。"""
    d = l1_diff(root, base)
    if d is None:
        why = ("沒有可比較的基準：找不到 %s，也沒給 --base" % DEFAULT_BASE) if not base else ("讀不到 %s 的 L1 快照、或這棵樹沒有 L1 工具" % base)
        return [], ["L1 相容檢查未做（%s）⇒ 被修改／刪除的 L1 名稱是否還有模組在用，這次沒有驗證" % why]
    a, c, r = d
    breaking = breaking_names(c, r)
    notes = []
    if not breaking:
        return [], notes
    unk = unknown_units(breaking)
    if unk:
        notes.append("L1 相容檢查略過了認不得的單位種類（沒掃它們的使用處）：" + "、".join(unk))
    return ["L1 介面被修改／刪除的名稱，模組程式還在用：" + h for h in scan_module_uses(Path(root) / MODULES, breaking)], notes


# ── 模組測試 ────────────────────────────────────────────────────────────

def run_module_tests(root, keys):
    """依序跑每個有 tests 目錄的模組。⇒ 失敗模組清單 [(key, 輸出尾段)]。"""
    failures = []
    root = Path(root)
    tmp = root / ".pt-core-major"
    try:
        for key in keys:
            tdir = root / MODULES / key / "tests"
            if not tdir.is_dir():
                continue
            print("  測試 %s …" % key, flush=True)
            r = subprocess.run([sys.executable, "-m", "pytest", "modules/%s/tests" % key, "-q", "-x", "-p", "no:cacheprovider",
                                "-W", "ignore", "--basetemp=%s" % tmp],
                               cwd=str(root / "backend"), capture_output=True, text=True, encoding="utf-8", errors="replace")
            if r.returncode != 0:
                failures.append((key, (r.stdout or "")[-1500:]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return failures


# ── 改寫 ────────────────────────────────────────────────────────────────

def _read(path):
    data = Path(path).read_bytes()
    return data.decode("utf-8-sig") if data.startswith(b"\xef\xbb\xbf") else data.decode("utf-8"), data.startswith(b"\xef\xbb\xbf")


def _write(path, text, bom):
    Path(path).write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))


def _nl(text):
    return "\r\n" if "\r\n" in text else "\n"


def rewrite_module_json(text, new_spec):
    """只換頂層 `"core": "…"` 那一行的值，其餘（含 version、換行、縮排）逐字保留。"""
    ms = [m for m in _CORE_LINE.finditer(text) if re.search(r"\d", m.group("spec"))]
    if len(ms) != 1:
        raise ValueError("module.json 找不到唯一的頂層 core 範圍行")
    m = ms[0]
    return text[:m.start("spec")] + new_spec + text[m.end("spec"):]


def add_changelog_section(text, body_lines, head):
    """在檔頭標題後插入新的 `## (next)` 段落；沿用檔案原本的換行。"""
    nl = _nl(text)
    block = nl.join([head] + body_lines) + nl + nl
    m = re.search(r"^##[ \t]", text, re.M)
    if m:
        return text[:m.start()] + block + text[m.start():]
    return text.rstrip("\r\n") + nl + nl + block


def plan_apply(root, target_major, today):
    """⇒ (writes {路徑: (新文字, bom)}, rows [(key, 舊, 新)], manual [(key, 原因)])。不寫檔。"""
    root = Path(root)
    writes, rows, manual = {}, [], []
    new_upper = "<%d.0" % (target_major + 1)
    for key, (mj, spec) in module_specs(root).items():
        if spec is None:
            manual.append((key, "module.json 沒有 core 範圍"))
            continue
        new, why = relax_spec(spec, target_major)
        if why:
            manual.append((key, why))
            continue
        if not compatible(new, "%d.0" % target_major):
            manual.append((key, "範圍 %r 不接受 %d.0，而且無法只放寬上限（下限高於目標、或看不懂）" % (new, target_major)))
            continue
        if new == spec:
            continue
        text, bom = _read(mj)
        writes[str(mj)] = (rewrite_module_json(text, new), bom)
        rows.append((key, spec, new))
        cl = mj.parent / "CHANGELOG.md"
        ctext, cbom = _read(cl) if cl.is_file() else ("# %s 更新紀錄\n\n" % key, False)
        head = "## (next) — %s（core-major-bump；為核心 %d.0 預備；版號由列車取）" % (today, target_major)
        body = ["- 相容範圍（`module.json` 的 `core`）：由 `%s` 放寬為 `%s`（只放寬上限、下限不變；程式、資料、API 不變）。工具：`%s`。" % (spec, new, TOOL)]
        writes[str(cl)] = (add_changelog_section(ctext, body, head), cbom)
    if rows:
        cl = root / CORE_CHANGELOG
        if cl.is_file():
            ctext, cbom = _read(cl)
            head = "## (next) — %s（core-major-bump；核心大版本升級的模組相容範圍；版號由列車取）" % today
            body = ["- 工具：`%s apply`——%d 個模組的 `module.json` core 範圍上限放寬為 `%s`（為核心 %d.0 預備；下限不變）。"
                    "沒有改任何程式、資料表、API、權限；核心本身的版號仍由列車 `train_number.py assign` 依 L1 介面定。" % (TOOL, len(rows), new_upper, target_major)]
            writes[str(cl)] = (add_changelog_section(ctext, body, head), cbom)
    return writes, rows, manual


def apply(root, target_major=None, dry_run=False, skip_tests=False, base=None, today=None, runner=None, out=print, force=False):
    """⇒ exit code：0＝完成／不用改、1＝拒絕（L1 不相容、測試紅、要人工處理、這包不需要升主版號又沒給 --force）、3＝dry-run 且有要改（正常，不是失敗）。
    目標主版號預設＝目前核心主版號＋1；若已有模組不接受**目前**核心（例如核心已是 2.0 才發現），預設改成目前主版號（直接補救，不要跳過一個主版號）。"""
    root = Path(root)
    cur = core_version(root)
    cm = major_of(cur)
    specs = module_specs(root)
    rejecting = sorted(k for k, (_, sp) in specs.items() if not compatible(sp, cur))
    target = target_major if target_major is not None else (cm if rejecting else cm + 1)
    if target < cm or (target == cm and not rejecting):
        out("目標主版號 %d.0 不比目前核心 %s 大，而且所有模組的範圍都接受目前核心 ⇒ 不做" % (target, cur))
        return 1
    today = today or date.today().isoformat()
    try:
        base = resolve_base(root, base)
    except ValueError as e:
        out(str(e))
        return 1
    pend, why = major_pending(root, base)
    out("核心 %s；這包%s升主版號%s" % (cur, "要" if pend else "不需要", "（%s）" % why if pend else ""))
    out("目標：模組的 core 範圍接受 %d.0；共 %d 個模組" % (target, len(specs)))
    if rejecting:
        out("⚠ 目前核心 %s 已有 %d 個模組不相容（%s）⇒ 目標取目前主版號 %d.0，直接補救" % (cur, len(rejecting), "、".join(rejecting), target))
    writes, rows, manual = plan_apply(root, target, today)
    for key, why_ in manual:
        out("  ✗ %s：%s（要人工處理）" % (key, why_))
    if manual:
        return 1
    if not rows:
        out("所有模組的 core 範圍都已接受 %d.0 ⇒ 不用改" % target)
        return 0
    if not rejecting and not pend:
        out("⚠ 核心這包目前不需要升主版號（判斷依據：L1 介面相對%s、核心 CHANGELOG 沒有 `(next:major)`）；"
            "現在放寬只是預備%s" % ("快照 " + base if base else "基準（找不到 %s，也沒給 --base ⇒ 看不出介面差異）" % DEFAULT_BASE,
                                    "" if dry_run else "，要做請加 --force"))
        if not dry_run and not force:
            return 1
    l1, l1_notes = l1_compat_problems(root, base)
    for n in l1_notes:
        out("  ⚠ " + n)
    for p in l1:
        out("  ✗ " + p)
    if l1:
        out("⇒ 拒絕：先修呼叫端（範圍放寬救不了已被刪除／修改的 L1 名稱），修好再重跑 `apply --dry-run`")
        return 1
    for key, old, new in rows:
        out("  %-14s %s  ⇒  %s" % (key, old, new))
    if not skip_tests:
        failures = (runner or run_module_tests)(root, sorted(specs))
        for key, tail in failures:
            out("  ✗ 模組 %s 測試未過：\n%s" % (key, tail))
        if failures:
            out("⇒ 拒絕：模組測試要全部過才放寬範圍；沒有改任何檔。修好該模組後重跑")
            return 1
    if dry_run:
        nxt = "確認後執行 `apply`" if (rejecting or pend) else "這包不需要升主版號：真的執行要加 --force"
        out("（預演：有 %d 個模組要改，結束碼 3 是正常的、不是失敗；L1 相容檢查%s，模組測試%s；沒有寫任何檔。%s）"
            % (len(rows), "未做（見上面的 ⚠）" if l1_notes and base is None else ("通過（有略過項，見上面的 ⚠）" if l1_notes else "通過"), "已跑且全過" if not skip_tests else "未跑（加 --with-tests 才跑）", nxt))
        return 3
    for path, (text, bom) in writes.items():
        _write(path, text, bom)
    out("✔ 已改 %d 個模組的 core 範圍、寫了 %d 個 CHANGELOG（版號由列車 train_number assign 取）" % (len(rows), len(writes)))
    return 0


# ── CLI ─────────────────────────────────────────────────────────────────

def cmd_status(root, base):
    base = resolve_base(root, base)
    cur = core_version(root)
    specs = module_specs(root)
    pend, why = major_pending(root, base)
    nxt = "%d.0" % (major_of(cur) + 1)
    print("核心 %s；下一個主版號 %s；核心這包%s升主版號" % (cur, nxt, ("要（%s）" % why) if pend else "不需要"))
    print("  %-14s %-16s %-8s %s" % ("模組", "core 範圍", "目前核心 " + cur, "下一個主版號 " + nxt))
    for key, (_, spec) in specs.items():
        print("  %-14s %-16s %-14s %s" % (key, spec, "相容" if compatible(spec, cur) else "不相容", "相容" if compatible(spec, nxt) else "不相容"))
    bad_now = sorted(k for k, (_, s) in specs.items() if not compatible(s, cur))
    if bad_now:
        print("✗ %d 個模組不接受目前核心 %s（啟動時不會載入）：%s ⇒ 用 apply 補救（見 check 的說明）" % (len(bad_now), cur, "、".join(bad_now)))
    print("說明：「不相容」＝載入器會拒絕載入該模組。核心升到 %s 之前，下一欄要全部是「相容」（用 apply 放寬）。" % nxt)
    return 0


def cmd_check(root, base):
    base = resolve_base(root, base)
    cur = core_version(root)
    specs = {k: s for k, (_, s) in module_specs(root).items()}
    pend, why = major_pending(root, base)
    problems = guard_problems(cur, specs, pend)
    for p in problems:
        print(p)
    if not problems:
        if pend:
            print("OK：核心這包要升主版號（%s），所有模組的範圍都已接受 %d.0" % (why, major_of(cur) + 1))
        else:
            print("OK：核心 %s，所有模組的範圍都接受目前核心；這包沒有要升主版號" % cur)
    return 1 if problems else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="核心大版本升級工具（見檔頭）")
    ap.add_argument("cmd", choices=["status", "check", "apply"])
    ap.add_argument("--root", default=str(REPO))
    ap.add_argument("--base", default=None, help="L1 快照的比較基準（git ref）；預設 origin/platform（與 train_number 同一個基準；找不到就印「L1 相容檢查未做」）")
    ap.add_argument("--to", type=int, default=None, help="目標主版號（預設＝目前核心主版號＋1；已有模組不接受目前核心時＝目前主版號）")
    ap.add_argument("--force", action="store_true", help="核心這包不需要升主版號時，仍要預備性放寬（預設拒絕）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-tests", action="store_true")
    ap.add_argument("--with-tests", action="store_true", help="dry-run 時也跑各模組測試")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "status":
            return cmd_status(a.root, a.base)
        if a.cmd == "check":
            return cmd_check(a.root, a.base)
    except ValueError as e:
        print(e)
        return 1
    return apply(a.root, a.to, dry_run=a.dry_run, skip_tests=a.skip_tests or (a.dry_run and not a.with_tests), base=a.base, force=a.force)


if __name__ == "__main__":
    sys.exit(main())
