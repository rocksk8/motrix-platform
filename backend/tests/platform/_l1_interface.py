"""G1：L0／L1 公開介面快照（MODULE-GUIDE §2「底層穩定契約」）。

範圍：docs/platform/modules.json 的 L1 單位中，Python 單位（plat:／core:／helper:）的
  - 公開（不以 _ 開頭）的頂層函式與類別：參數簽章（名稱、有無預設值、*args、keyword-only、**kwargs）
  - 公開類別的公開方法簽章與 dataclass 欄位（有型別註記的類別屬性）
  - 全大寫的模組常數名稱（只記名稱，不記值）
⚠ 守不到：回傳形狀（靜態讀不出來）、L1 router 的 HTTP 端點、資料表欄位（MODULE-GUIDE 標「⚠ 未守門」）。

升版規則（`--update` 重產快照時強制）：
  只有新增 ⇒ CORE_VERSION 至少升次版號；有修改或刪除 ⇒ 升主版號；版號沒照規則升 ⇒ 拒絕重產。
用法：
  python backend/tests/platform/_l1_interface.py --diff      列出目前介面與快照的差異
  python backend/tests/platform/_l1_interface.py --update    依升版規則重產快照
"""
import ast
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
REPO = BACKEND.parent
MODULES_JSON = REPO / "docs" / "platform" / "modules.json"
SNAPSHOT = HERE / "l1_interface_snapshot.json"
REGISTRY = BACKEND / "core" / "registry.py"
CHANGELOG = BACKEND / "core" / "CHANGELOG.md"

_UPPER = re.compile(r"^[A-Z][A-Z0-9_]*$")


def unit_path(unit):
    kind, name = unit.split(":", 1)
    return {"plat": BACKEND / "core" / (name + ".py"),
            "core": BACKEND / (name + ".py"),
            "helper": BACKEND / "helpers" / (name + ".py")}.get(kind)


def l1_python_units(modules_json=MODULES_JSON):
    data = json.loads(Path(modules_json).read_text(encoding="utf-8"))
    return sorted(u for u in data["L1"]["units"] if u.split(":", 1)[0] in ("plat", "core", "helper"))


def _sig(args):
    out = []
    pos = list(args.posonlyargs) + list(args.args)
    first_default = len(pos) - len(args.defaults)
    for i, a in enumerate(pos):
        out.append(a.arg + ("=…" if i >= first_default else ""))
    if args.vararg:
        out.append("*" + args.vararg.arg)
    elif args.kwonlyargs:
        out.append("*")
    for a, d in zip(args.kwonlyargs, args.kw_defaults):
        out.append(a.arg + ("=…" if d is not None else ""))
    if args.kwarg:
        out.append("**" + args.kwarg.arg)
    return "(" + ", ".join(out) + ")"


def interface_of(source):
    """一個模組的公開介面 ⇒ {名稱: 描述字串}。"""
    tree = ast.parse(source)
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            out[node.name] = "def" + _sig(node.args)
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            out[node.name] = "class"
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and (not item.name.startswith("_") or item.name == "__init__"):
                    out["%s.%s" % (node.name, item.name)] = "def" + _sig(item.args)
                elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name) \
                        and not item.target.id.startswith("_"):
                    out["%s.%s" % (node.name, item.target.id)] = "field" + ("=…" if item.value is not None else "")
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name) and _UPPER.match(t.id):
                    out[t.id] = "const"
    return out


def current_interface(units=None):
    units = l1_python_units() if units is None else units
    res = {}
    for u in units:
        p = unit_path(u)
        if p is None or not p.is_file():
            res[u] = {"__missing__": "unit"}
            continue
        res[u] = interface_of(p.read_text(encoding="utf-8-sig"))
    return res


def _params(desc):
    m = __import__("re").match(r"^def\((.*)\)$", desc)
    if not m:
        return None
    return [p.strip() for p in m.group(1).split(",") if p.strip()]


def compatible_extension(old_desc, new_desc):
    """相容擴充：舊參數原樣、原順序保留在前面，新加的都有預設值（或是 *args／**kwargs／keyword-only 分隔）。"""
    o, n = _params(old_desc), _params(new_desc)
    if o is None or n is None or n[:len(o)] != o:
        return False
    return all(p.endswith("=…") or p.startswith("*") for p in n[len(o):])


def diff(old, new):
    """(added, changed, removed)：各為 ["unit::name", ...]。整個單位新增／刪除也算。
    簽章只在尾端加了有預設值的參數 ⇒ 算「新增」（相容擴充，升次版號即可）。"""
    added, changed, removed = [], [], []
    for u in sorted(set(old) | set(new)):
        o, n = old.get(u, {}), new.get(u, {})
        for k in sorted(set(o) | set(n)):
            key = "%s::%s" % (u, k)
            if k not in o:
                added.append(key)
            elif k not in n:
                removed.append(key)
            elif o[k] != n[k]:
                if compatible_extension(o[k], n[k]):
                    added.append("%s  %s → %s（相容擴充）" % (key, o[k], n[k]))
                else:
                    changed.append("%s  %s → %s" % (key, o[k], n[k]))
    return added, changed, removed


def parse_version(v):
    m = re.fullmatch(r"(\d+)\.(\d+)", str(v).strip())
    if not m:
        raise ValueError("CORE_VERSION 格式要是「主.次」：%r" % v)
    return int(m.group(1)), int(m.group(2))


def required_bump(added, changed, removed):
    """需要的升版等級：None／"minor"／"major"。"""
    if changed or removed:
        return "major"
    if added:
        return "minor"
    return None


def bump_ok(old_version, new_version, need):
    """新版號是否滿足需要的升版等級（等級不足或倒退都算不滿足）。"""
    o, n = parse_version(old_version), parse_version(new_version)
    if need is None:
        return n >= o
    if need == "major":
        return n[0] > o[0]
    return n > o


def core_version():
    m = re.search(r'^CORE_VERSION\s*=\s*"([^"]+)"', REGISTRY.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else None


def changelog_top_version():
    m = re.search(r"^##\s+(\d+\.\d+)\b", CHANGELOG.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else None


def load_snapshot():
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def main(argv):
    cur = current_interface()
    ver = core_version()
    if "--update" in argv:
        if SNAPSHOT.exists():
            snap = load_snapshot()
            a, c, r = diff(snap["interface"], cur)
            need = required_bump(a, c, r)
            if not bump_ok(snap["core_version"], ver, need):
                print("拒絕重產：介面差異需要 %s 升版，而 CORE_VERSION %s → %s 不足。"
                      % (need, snap["core_version"], ver))
                return 1
        SNAPSHOT.write_text(json.dumps({"core_version": ver, "interface": cur}, ensure_ascii=False,
                                       indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        print("已重產：CORE_VERSION %s，%d 個單位" % (ver, len(cur)))
        return 0
    snap = load_snapshot()
    a, c, r = diff(snap["interface"], cur)
    print("快照 %s／目前 %s；新增 %d、修改 %d、刪除 %d" % (snap["core_version"], ver, len(a), len(c), len(r)))
    for label, items in (("新增", a), ("修改", c), ("刪除", r)):
        for x in items:
            print("  %s  %s" % (label, x))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main(sys.argv[1:]))
