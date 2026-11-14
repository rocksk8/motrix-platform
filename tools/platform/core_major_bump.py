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
  （`--root PATH` 指到別的樹；`--to N` 指定目標主版號，預設＝目前核心主版號＋1）

## 規則
- 只改 `module.json` 裡頂層的 `"core": "<範圍>"`；**不碰 `"version"`**（版號由列車 train_number 取）。只放寬**上限**到 `<(目標主版號+1).0`，下限不動
  ⇒ 放寬後的模組仍能裝在舊核心上（模組更新 `module_update._core_ok`／載入器 `core_compatible` 同一套比較）。
- 每個被改的模組 CHANGELOG 最上面加 `## (next)` 段落（版號由列車取）；核心 CHANGELOG 也加一段。
- **L1 相容檢查**：L1 介面相對快照被「修改或刪除」的名稱，若有模組程式（modules/*，不含 tests）還在 import／使用 ⇒ 拒絕（範圍放寬救不了呼叫端壞掉）。
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
HINT = "先預演 `python %s apply --dry-run`，確認後 `python %s apply`（會一次放寬所有 module.json 的 core 上限、寫 CHANGELOG）" % (TOOL, TOOL)

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

def guard_problems(core_ver, specs, major_pending):
    """純函式。specs＝{key: 範圍}。⇒ 問題清單（空＝可以）。
    ① 目前 CORE_VERSION 超出某模組範圍 ⇒ 該模組不會載入；② 核心要升主版號但範圍還沒接受下一個主版號。"""
    problems = []
    cur_major = major_of(core_ver)
    for key, spec in sorted(specs.items()):
        if not compatible(spec, core_ver):
            problems.append("模組 %s 的 core 範圍 %r 不接受目前核心 %s ⇒ 啟動時這個模組不會載入（路由 404）" % (key, spec, core_ver))
    if major_pending:
        target = "%d.0" % (cur_major + 1)
        for key, spec in sorted(specs.items()):
            if not compatible(spec, target):
                problems.append("核心這包要升主版號（%s）但模組 %s 的 core 範圍 %r 不接受 %s ⇒ 升了之後所有模組都載入失敗" % (target, key, spec, target))
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


def l1_diff(root, base=None):
    """⇒ (added, changed, removed) 或 None（沒有 L1 工具／讀不到快照）。base＝git ref：用該版快照當基準；沒給 ⇒ 用樹內目前的快照。"""
    G = _l1_module(root)
    if G is None:
        return None
    snap_text = _git(root, "show", "%s:%s" % (base, SNAPSHOT)) if base else (Path(root) / SNAPSHOT).read_text(encoding="utf-8") if (Path(root) / SNAPSHOT).is_file() else None
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


def scan_module_uses(modules_dir, breaking):
    """模組程式（不含 tests）裡還在用的、被修改／刪除的 L1 名稱。⇒ ["modules/<key>/x.py: helpers.foo.bar", …]"""
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
                        if a.name in by_mod[node.module]:
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
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases:
                mod = aliases[node.value.id]
                if node.attr in by_mod[mod]:
                    found.add("%s.%s" % (mod, node.attr))
        for h in sorted(found):
            hits.append("modules/%s: %s" % (rel.as_posix(), h))
    return hits


def l1_compat_problems(root, base=None):
    d = l1_diff(root, base)
    if d is None:
        return []
    a, c, r = d
    breaking = breaking_names(c, r)
    if not breaking:
        return []
    return ["L1 介面被修改／刪除的名稱，模組程式還在用：" + h for h in scan_module_uses(Path(root) / MODULES, breaking)]


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
        if new == spec:
            continue
        if not compatible(new, "%d.0" % target_major):
            manual.append((key, "放寬後 %r 仍不接受 %d.0" % (new, target_major)))
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


def apply(root, target_major=None, dry_run=False, skip_tests=False, base=None, today=None, runner=None, out=print):
    """⇒ exit code：0＝完成／不用改、1＝拒絕（L1 不相容、測試紅、要人工處理）、3＝dry-run 且有要改。"""
    root = Path(root)
    cur = core_version(root)
    target = target_major if target_major is not None else major_of(cur) + 1
    if target <= major_of(cur):
        out("目標主版號 %d 不比目前核心 %s 大 ⇒ 不做" % (target, cur))
        return 1
    today = today or date.today().isoformat()
    specs = module_specs(root)
    out("核心 %s ⇒ 目標主版號 %d；%d 個模組" % (cur, target, len(specs)))
    writes, rows, manual = plan_apply(root, target, today)
    for key, why in manual:
        out("  ✗ %s：%s（要人工處理）" % (key, why))
    if manual:
        return 1
    if not rows:
        out("所有模組的 core 範圍都已接受 %d.0 ⇒ 不用改" % target)
        return 0
    l1 = l1_compat_problems(root, base)
    for p in l1:
        out("  ✗ " + p)
    if l1:
        out("⇒ 拒絕：先修呼叫端（範圍放寬救不了已被刪除／修改的 L1 名稱）")
        return 1
    for key, old, new in rows:
        out("  %-14s %s  ⇒  %s" % (key, old, new))
    if not skip_tests:
        failures = (runner or run_module_tests)(root, sorted(specs))
        for key, tail in failures:
            out("  ✗ 模組 %s 測試未過：\n%s" % (key, tail))
        if failures:
            out("⇒ 拒絕：模組測試要全部過才放寬範圍；沒有改任何檔")
            return 1
    if dry_run:
        out("（預演：L1 相容檢查通過；模組測試%s；沒有寫任何檔）" % ("已跑且全過" if not skip_tests else "未跑（加 --with-tests 才跑）"))
        return 3
    for path, (text, bom) in writes.items():
        _write(path, text, bom)
    out("✔ 已改 %d 個模組的 core 範圍、寫了 %d 個 CHANGELOG（版號由列車 train_number assign 取）" % (len(rows), len(writes)))
    return 0


# ── CLI ─────────────────────────────────────────────────────────────────

def cmd_status(root, base):
    cur = core_version(root)
    specs = module_specs(root)
    pend, why = major_pending(root, base)
    print("核心 %s；下一個主版號 %d.0；核心要升主版號：%s" % (cur, major_of(cur) + 1, ("是（%s）" % why) if pend else "否"))
    nxt = "%d.0" % (major_of(cur) + 1)
    for key, (_, spec) in specs.items():
        print("  %-14s %-18s 接受目前 %s  接受 %s" % (key, spec, "✔" if compatible(spec, cur) else "✗", "✔" if compatible(spec, nxt) else "✗"))
    return 0


def cmd_check(root, base):
    cur = core_version(root)
    specs = {k: s for k, (_, s) in module_specs(root).items()}
    pend, why = major_pending(root, base)
    problems = guard_problems(cur, specs, pend)
    if pend and not problems:
        print("核心要升主版號（%s），所有模組範圍都已接受 %d.0 ⇒ OK" % (why, major_of(cur) + 1))
    for p in problems:
        print(p)
    return 1 if problems else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="核心大版本升級工具（見檔頭）")
    ap.add_argument("cmd", choices=["status", "check", "apply"])
    ap.add_argument("--root", default=str(REPO))
    ap.add_argument("--base", default=None, help="L1 快照的比較基準（git ref，例如 origin/platform）；沒給＝樹內目前的快照")
    ap.add_argument("--to", type=int, default=None, help="目標主版號（預設＝目前核心主版號＋1）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-tests", action="store_true")
    ap.add_argument("--with-tests", action="store_true", help="dry-run 時也跑各模組測試")
    a = ap.parse_args(argv)
    if a.cmd == "status":
        return cmd_status(a.root, a.base)
    if a.cmd == "check":
        return cmd_check(a.root, a.base)
    return apply(a.root, a.to, dry_run=a.dry_run, skip_tests=a.skip_tests or (a.dry_run and not a.with_tests), base=a.base)


if __name__ == "__main__":
    sys.exit(main())
