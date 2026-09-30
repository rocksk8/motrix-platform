"""列車取號：分支寫佔位，列車合完之後一次把號碼定下來（PLAYBOOK §G6；使用者 2026-09-30「撞號太多次了，想辦法解決」）。

用法（列車樹的根目錄，所有包都疊上去之後；Python 一律 D:\\MOTRIX-PLATFORM\\.venv312\\Scripts\\python.exe）：
  python tools/platform/train_number.py assign [--base origin/platform]   取號並改寫檔案（冪等：再跑一次不會再改）
  python tools/platform/train_number.py assign --dry-run                   只印會怎麼改（exit 3＝有要改、0＝不用改）
  python tools/platform/train_number.py --check                            CI／platform：還有佔位或撞號 ⇒ exit 1

取號規則（號碼一律從「正式機基準」與「目前檔案」兩者較大的往上）：
  模組      每個 modules/<key>/CHANGELOG.md：正式機基準（tests/_prod_baseline.py 的 BASELINE）那一版的 module.json version
            以上的段落是「這一包」。由下往上：已編號而且比下面大、沒重複 ⇒ 照舊；`(next)` ⇒ 下一個修正號
            （`(next:minor)`／`(next:major)` 照指定）；已編號卻撞號／沒遞增 ⇒ 重編並在標題尾註記。
            `--base` 那一版就有的段落（已在 platform、未出貨）優先保留號碼，分支帶來的段落排到它們上面。
            module.json version ＝ 最上面的版號。
  CORE      同上（兩段版號、`(next)` 預設次版號）；L1 介面相對 `--base` 的快照需要主版號 ⇒ 最下面那個佔位升主版號。
            registry.CORE_VERSION、G1 快照的 core_version ＝ 最上面的版號（快照的介面必須已是目前的介面，
            否則拒絕：先 `_l1_interface.py --update --pending`）。
  manifest  `"version": "next"` ⇒ 依 (date, time) 排序，取該日期已用過的最大字母的下一個（z 之後 aa）。
            同一模組這一包已有條目（未出貨）⇒ 佔位條目併進那一筆（VR3「一個模組一筆」）；
            未出貨條目撞號 ⇒ `--base` 就有的保留，其餘重編。已出貨的一律不動。
  migration backend/core/migrations.py 的 `register("core", NEXT, fn)` ⇒ 依檔案順序接在最大號後面；
            已編號撞號 ⇒ `--base` 就有的保留、其餘重編（⚠ 開發庫若已跑過舊號，要重建開發庫——報表會標出）。
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from merge_drivers import parse_manifest, render_manifest, split_sections   # noqa: E402

CORE_CHANGELOG = "backend/core/CHANGELOG.md"
REGISTRY = "backend/core/registry.py"
SNAPSHOT = "backend/tests/platform/l1_interface_snapshot.json"
MANIFEST = "backend/version_manifest.json"
MIGRATIONS = "backend/core/migrations.py"
BASELINE_PY = "backend/tests/_prod_baseline.py"

PLACEHOLDER_HEAD = re.compile(r"^(##[ \t]+)\(next(?::(patch|minor|major))?\)")
NUMBERED_HEAD = re.compile(r"^(##[ \t]+)(\d+(?:\.\d+)+)(?![\d.])")
MIG_LINE = re.compile(r"""^(register\(\s*["']core["']\s*,\s*)(\d+|NEXT)(\s*,\s*)([A-Za-z_]\w*)(\s*\))""", re.M)


# ── 版號 ────────────────────────────────────────────────────────────────

def parse_version(s, parts):
    t = tuple(int(x) for x in s.split("."))
    return t if len(t) == parts else None


def fmt(v):
    return ".".join(str(x) for x in v)


def bump(v, level, parts):
    if v is None:
        return (1, 0, 0)[:parts]
    if level == "major":
        return (v[0] + 1,) + (0,) * (parts - 1)
    if level == "minor" or parts == 2:
        return (v[0], v[1] + 1) + (0,) * (parts - 2)
    return v[:2] + (v[2] + 1,)


def implied_level(v):
    """已編號段落重編時保留它原本的幅度（x.0.0＝主、x.y.0＝次、其餘＝修正）。"""
    if all(x == 0 for x in v[1:]):
        return "major"
    if len(v) == 3 and v[2] == 0:
        return "minor"
    return "patch" if len(v) == 3 else "minor"


# ── CHANGELOG ───────────────────────────────────────────────────────────

def classify(section, parts):
    """⇒ ("next", 幅度或 None) ／ ("num", 版號) ／ ("other", None)。"""
    head = section.split("\n", 1)[0]
    m = PLACEHOLDER_HEAD.match(head)
    if m:
        return "next", m.group(2)
    m = NUMBERED_HEAD.match(head)
    if m:
        v = parse_version(m.group(2), parts)
        if v is not None:
            return "num", v
    return "other", None


def assign_changelog(text, floor, parts, pinned_heads=(), default_level="patch", need_major=False):
    """⇒ (新全文, 最上面的版號 tuple 或 None, [(舊, 新, 說明)])。

    floor：已出貨的版號（None＝從沒出貨）；它（含）以下的段落不動。pinned_heads：--base 那一版的標題行（優先保留號碼）。"""
    pre, secs = split_sections(text)
    kinds = [classify(s, parts) for s in secs]
    end = len(secs)
    for i, (k, v) in enumerate(kinds):
        if k == "num" and floor is not None and v <= floor:
            end = i
            break
    region = list(range(end))
    pinned = {i for i in region if secs[i].split("\n", 1)[0] in set(pinned_heads)}
    order = [i for i in region if i not in pinned] + [i for i in region if i in pinned]
    below = [v for k, v in kinds[end:] if k == "num"]
    last = floor if floor is not None else (max(below) if below else None)
    used = set(below)
    lowest_next = next((i for i in reversed(order) if kinds[i][0] == "next"), None)
    new_secs = {}
    changes = []
    for i in reversed(order):
        k, v = kinds[i]
        s = secs[i]
        head, nl, body = s.partition("\n")
        if k == "other":
            new_secs[i] = s
            continue
        if k == "num" and (last is None or v > last) and v not in used:
            new_secs[i] = s
            last = v
            used.add(v)
            continue
        if k == "next":
            level = "major" if (need_major and i == lowest_next) else (v or default_level)
        else:
            level = implied_level(v)
        nv = bump(last, level, parts)
        while nv in used:
            nv = bump(nv, "patch" if parts == 3 else "minor", parts)
        if k == "next":
            head = PLACEHOLDER_HEAD.sub(lambda m: m.group(1) + fmt(nv), head, count=1)
            changes.append(("(next%s)" % (":" + v if v else ""), fmt(nv), "佔位取號"))
        else:
            head = NUMBERED_HEAD.sub(lambda m: m.group(1) + fmt(nv), head, count=1) + \
                "〔train_number：%s → %s〕" % (fmt(v), fmt(nv))
            changes.append((fmt(v), fmt(nv), "撞號／未遞增 ⇒ 重編"))
        new_secs[i] = head + nl + body
        last = nv
        used.add(nv)
    out = pre + "".join(new_secs[i] for i in order) + "".join(secs[end:])
    top = None
    for s in split_sections(out)[1]:
        k, v = classify(s, parts)
        if k == "num":
            top = v
            break
    return out, top, changes


# ── manifest ────────────────────────────────────────────────────────────

_DAY = re.compile(r"^(\d{4}-\d{2}-\d{2})([a-z]*)$")


def _suffix_key(s):
    return (len(s), s)


def next_suffix(s):
    """"" ⇒ a；a ⇒ b；z ⇒ aa；az ⇒ ba；zz ⇒ aaa。"""
    if not s:
        return "a"
    chars = list(s)
    i = len(chars) - 1
    while i >= 0 and chars[i] == "z":
        chars[i] = "a"
        i -= 1
    if i < 0:
        return "a" * (len(s) + 1)
    chars[i] = chr(ord(chars[i]) + 1)
    return "".join(chars)


def _ekey(e):
    return json.dumps(e, sort_keys=True, ensure_ascii=False)


def assign_manifest(text, shipped, base_entries=()):
    """⇒ (新全文, [(模組, 舊, 新, 說明)])。shipped：已出貨的 (module, version) 集合；base_entries：--base 那一版的條目。"""
    spans = parse_manifest(text)
    if spans is None:
        raise SystemExit("version_manifest.json 的排版不是本 repo 的格式（`[\\n  {…},\\n  {…}\\n]\\n`）⇒ 不改，先整理格式")
    entries = [json.loads(s) for s in spans]
    base_keys = {_ekey(e) for e in base_entries}
    base_pairs = {(e.get("module"), e.get("version")) for e in base_entries}
    changes = []
    drop = set()
    new_spans = list(spans)

    def unshipped(e):
        return (e.get("module"), e.get("version")) not in shipped

    # ① 佔位條目併進同模組這一包已有的條目（VR3）
    by_mod = {}
    for i, e in enumerate(entries):
        if unshipped(e):
            by_mod.setdefault(e.get("module"), []).append(i)
    for mod, idx in by_mod.items():
        nexts = [i for i in idx if entries[i].get("version") == "next"]
        nums = [i for i in idx if entries[i].get("version") != "next"]
        if not nexts or len(idx) < 2:
            continue
        pinned_nums = [i for i in nums if (mod, entries[i].get("version")) in base_pairs]
        target = (pinned_nums or nums or nexts)[0]
        others = sorted((i for i in nexts if i != target),
                        key=lambda i: (entries[i].get("date") or "", entries[i].get("time") or "", i))
        t = dict(entries[target])
        for i in others:
            o = entries[i]
            t["content"] = (t.get("content") or "").rstrip() + "\n" + (o.get("content") or "").strip()
            if (o.get("date") or "", o.get("time") or "") > (t.get("date") or "", t.get("time") or "") and t.get("version") == "next":
                t["date"], t["time"] = o.get("date"), o.get("time")
            drop.add(i)
        entries[target] = t
        new_spans[target] = json.dumps(t, ensure_ascii=False)
        changes.append((mod, entries[target].get("version"), entries[target].get("version"),
                        "併入 %d 筆佔位（一個模組一筆）" % len(others)))

    # ② 要取號的：佔位＋未出貨而撞號的（--base 就有的保留）
    alive = [i for i in range(len(entries)) if i not in drop]
    used = {}
    for i in alive:
        v = entries[i].get("version")
        if v != "next":
            used.setdefault(v, []).append(i)
    todo = [i for i in alive if entries[i].get("version") == "next"]
    for v, idx in used.items():
        if len(idx) < 2:
            continue
        keep = [i for i in idx if not unshipped(entries[i])] or [i for i in idx if _ekey(entries[i]) in base_keys] or idx[-1:]
        todo += [i for i in idx if i not in keep and unshipped(entries[i])]
    todo = sorted(set(todo), key=lambda i: (entries[i].get("date") or "", entries[i].get("time") or "", i))
    max_suffix = {}
    for i in alive:
        m = _DAY.match(entries[i].get("version") or "")
        if m and i not in todo:
            d, s = m.groups()
            if d not in max_suffix or _suffix_key(s) > _suffix_key(max_suffix[d]):
                max_suffix[d] = s
    for i in todo:
        e = entries[i]
        d = e.get("date") or ""
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            raise SystemExit("manifest 條目缺 date（YYYY-MM-DD），無法取號：%s" % e.get("module"))
        s = next_suffix(max_suffix[d]) if d in max_suffix else "a"
        max_suffix[d] = s
        old = e.get("version")
        nv = d + s
        e = dict(e, version=nv)
        entries[i] = e
        if new_spans[i] == spans[i]:
            new_spans[i] = re.sub(r'("version"\s*:\s*")[^"]*(")', lambda m: m.group(1) + nv + m.group(2), spans[i], count=1)
        else:
            new_spans[i] = json.dumps(e, ensure_ascii=False)
        changes.append((e.get("module"), old, nv, "佔位取號" if old == "next" else "撞號 ⇒ 重編"))
    out = render_manifest([s for i, s in enumerate(new_spans) if i not in drop])
    json.loads(out)
    return out, changes


# ── core migration ──────────────────────────────────────────────────────

def assign_migrations(text, base_text=""):
    """⇒ (新全文, [(函式, 舊, 新, 說明)])。"""
    ms = list(MIG_LINE.finditer(text))
    base_lines = {m.group(0) for m in MIG_LINE.finditer(base_text)}
    nums = {}
    for m in ms:
        if m.group(2) != "NEXT":
            nums.setdefault(int(m.group(2)), []).append(m)
    renum = []
    for n, group in nums.items():
        if len(group) > 1:
            keep = next((m for m in group if m.group(0) in base_lines), group[0])
            renum += [m for m in group if m is not keep]
    top = max(nums) if nums else 0
    new_no = {}
    changes = []
    for m in ms:
        if m.group(2) == "NEXT" or m in renum:
            top += 1
            new_no[m.start()] = top
            changes.append((m.group(4), m.group(2), str(top),
                            "佔位取號" if m.group(2) == "NEXT" else "撞號 ⇒ 重編（⚠ 已跑過舊號的開發庫要重建）"))
    out = MIG_LINE.sub(lambda m: (m.group(1) + str(new_no[m.start()]) + m.group(3) + m.group(4) + m.group(5))
                       if m.start() in new_no else m.group(0), text)
    return out, changes


# ── git／檔案 ────────────────────────────────────────────────────────────

class Tree:
    def __init__(self, root, base):
        self.root = Path(root)
        self.base = base

    def git(self, *args):
        r = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True, encoding="utf-8")
        return r.stdout if r.returncode == 0 else None

    def show(self, ref, rel):
        return self.git("show", "%s:%s" % (ref, rel)) if ref else None

    def read(self, rel):
        p = self.root / rel
        return p.read_text(encoding="utf-8") if p.is_file() else None

    def write(self, rel, text):
        (self.root / rel).write_text(text, encoding="utf-8", newline="\n")

    def baseline(self):
        src = self.read(BASELINE_PY) or ""
        m = re.search(r'^BASELINE\s*=\s*"([0-9a-f]+)"', src, re.M)
        if not m:
            raise SystemExit("讀不到 %s 的 BASELINE" % BASELINE_PY)
        if self.git("rev-parse", "--verify", "%s^{commit}" % m.group(1)) is None:
            raise SystemExit("正式機基準 %s 不在這個 repo（先 git fetch --tags）" % m.group(1))
        return m.group(1)


def _heads(text):
    return [s.split("\n", 1)[0] for s in split_sections(text or "")[1]]


def _core_version_of(src):
    m = re.search(r'^CORE_VERSION\s*=\s*"([^"]*)"', src or "", re.M)
    return m.group(1) if m else None


def _need_major(tree):
    """L1 介面相對 --base 快照需要主版號？（只在列車根目錄＝本 repo 時算；synthetic 樹一律 False）"""
    if tree.root.resolve() != REPO.resolve():
        return False, None
    base_snap = tree.show(tree.base, SNAPSHOT)
    if base_snap is None:
        return False, None
    sys.path.insert(0, str(REPO / "backend" / "tests" / "platform"))
    sys.path.insert(0, str(REPO / "backend"))
    import _l1_interface as G   # noqa: E402
    cur = G.current_interface()
    a, c, r = G.diff(json.loads(base_snap)["interface"], cur)
    return G.required_bump(a, c, r) == "major", cur


def plan(tree):
    """⇒ ({相對路徑: 新全文}, [(類別, 對象, 舊, 新, 說明)], [錯誤])。"""
    writes, rows, errors = {}, [], []
    base_ref = tree.base
    bl = tree.baseline()

    # 模組
    for cl in sorted((tree.root / "backend" / "modules").glob("*/CHANGELOG.md")):
        key = cl.parent.name
        rel_cl = "backend/modules/%s/CHANGELOG.md" % key
        rel_mj = "backend/modules/%s/module.json" % key
        mj = tree.read(rel_mj)
        if mj is None:
            continue
        shipped = tree.show(bl, rel_mj)
        floor = parse_version(json.loads(shipped).get("version", "0.0.0"), 3) if shipped else None
        text = tree.read(rel_cl)
        new, top, ch = assign_changelog(text, floor, 3, _heads(tree.show(base_ref, rel_cl)), "patch")
        for old, nv, why in ch:
            rows.append(("模組", key, old, nv, why))
        if new != text:
            writes[rel_cl] = new
        cur_v = json.loads(mj).get("version")
        if top is not None and fmt(top) != cur_v:
            writes[rel_mj] = re.sub(r'("version"\s*:\s*")[^"]*(")', lambda m: m.group(1) + fmt(top) + m.group(2), mj, count=1)
            rows.append(("模組", key + "/module.json", cur_v, fmt(top), "version＝CHANGELOG 最上面"))

    # CORE
    text = tree.read(CORE_CHANGELOG)
    if text is not None:
        shipped = _core_version_of(tree.show(bl, REGISTRY))
        floor = parse_version(shipped, 2) if shipped else None
        has_next = any(classify(s, 2)[0] == "next" for s in split_sections(text)[1])
        need_major, cur_iface = _need_major(tree) if has_next else (False, None)
        new, top, ch = assign_changelog(text, floor, 2, _heads(tree.show(base_ref, CORE_CHANGELOG)), "minor", need_major)
        for old, nv, why in ch:
            rows.append(("CORE", "core/CHANGELOG", old, nv, why + ("（L1 介面需要主版號）" if need_major and old.startswith("(next") else "")))
        if new != text:
            writes[CORE_CHANGELOG] = new
        reg = tree.read(REGISTRY)
        if top is not None and reg is not None and _core_version_of(reg) != fmt(top):
            writes[REGISTRY] = re.sub(r'^(CORE_VERSION\s*=\s*")[^"]*(")', lambda m: m.group(1) + fmt(top) + m.group(2),
                                      reg, count=1, flags=re.M)
            rows.append(("CORE", "registry.CORE_VERSION", _core_version_of(reg), fmt(top), ""))
        snap_text = tree.read(SNAPSHOT)
        if top is not None and snap_text is not None:
            snap = json.loads(snap_text)
            if snap.get("core_version") != fmt(top):
                if cur_iface is not None and snap.get("interface") != cur_iface:
                    errors.append("G1 快照的介面不是目前的介面（合併後沒重產）⇒ 先跑 "
                                  "`python backend/tests/platform/_l1_interface.py --update --pending` 再取號")
                else:
                    rows.append(("CORE", "G1 快照 core_version", snap.get("core_version"), fmt(top), ""))
                    snap["core_version"] = fmt(top)
                    writes[SNAPSHOT] = json.dumps(snap, ensure_ascii=False, indent=1, sort_keys=True) + "\n"

    # manifest
    text = tree.read(MANIFEST)
    if text is not None:
        shipped = {(e.get("module"), e.get("version")) for e in json.loads(tree.show(bl, MANIFEST) or "[]")}
        base_entries = json.loads(tree.show(base_ref, MANIFEST) or "[]")
        new, ch = assign_manifest(text, shipped, base_entries)
        for mod, old, nv, why in ch:
            rows.append(("manifest", mod, old, nv, why))
        if new != text:
            writes[MANIFEST] = new

    # core migration
    text = tree.read(MIGRATIONS)
    if text is not None:
        new, ch = assign_migrations(text, tree.show(base_ref, MIGRATIONS) or "")
        for fn, old, nv, why in ch:
            rows.append(("migration", fn, old, nv, why))
        if new != text:
            writes[MIGRATIONS] = new
    return writes, rows, errors


def print_table(rows):
    if not rows:
        print("（沒有要取號或重編的項目）")
        return
    w = [max(len(str(r[i])) for r in rows + [("類別", "對象", "舊", "新", "說明")]) for i in range(5)]
    for r in [("類別", "對象", "舊", "新", "說明")] + rows:
        print("  ".join(str(x).ljust(w[i]) for i, x in enumerate(r)).rstrip())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", choices=("assign", "check"), default=None)
    ap.add_argument("--check", action="store_true", help="同 check：還有佔位或撞號 ⇒ exit 1，不改檔")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--base", default="origin/platform", help="已在 platform 的狀態（優先保留它的號碼）")
    ap.add_argument("--root", default=str(REPO))
    a = ap.parse_args(argv)
    check = a.check or a.cmd == "check"
    if not check and a.cmd != "assign":
        ap.error("要給 assign 或 --check")
    tree = Tree(a.root, a.base)
    if tree.git("rev-parse", "--verify", "%s^{commit}" % a.base) is None:
        print("找不到 --base %s" % a.base)
        return 2
    writes, rows, errors = plan(tree)
    print_table(rows)
    for e in errors:
        print("錯誤：" + e)
    if errors:
        return 1
    if check:
        print("檢查：%s" % ("有 %d 項要取號／重編 ⇒ 跑 train_number.py assign" % len(rows) if writes else "OK（沒有佔位、沒有撞號）"))
        return 1 if writes else 0
    if a.dry_run:
        print("會改 %d 個檔：%s" % (len(writes), "、".join(sorted(writes)) or "無"))
        return 3 if writes else 0
    for rel, text in writes.items():
        tree.write(rel, text)
    print("已寫入 %d 個檔：%s" % (len(writes), "、".join(sorted(writes)) or "無"))
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
