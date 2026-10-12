# -*- coding: utf-8 -*-
"""脊柱 E-b3：字面掃描器（設計 SPINE-ENGINE-DESIGN-T57 §3.5）。

只抓**精確字面**，不做啟發式、不掃散文：
- `<任何>.register("<key>", <名稱>, "<business|approval|system>", …)` ＝ 信件類型登記（`mail_types.register`）；
- `register_group("<group>", …)` ＝ 設定群組登記。
範圍：`backend/modules/**`（非 tests／migrations）。程式出現而 `module.json` 的 `features[].mail`／`settings.groups` 沒宣告、也不在白名單 ⇒ 違規。
白名單 `spine_scan_allowlist.json`：每筆 {kind, file, keys, reason, owner, expires}；**必須仍對得上實際出現**（失效、已改為宣告、過期 ⇒ 紅），不累積殭屍。
限制（誠實）：變數鍵（迴圈裡 `register(_k, …)`）掃不到；core 的 `mail_types.py` 不在範圍。
"""
import ast
import json
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ALLOWLIST = HERE / "spine_scan_allowlist.json"
CATEGORIES = {"business", "approval", "system"}


def scan_source(src):
    """原始碼 → [(kind, key, lineno)]；kind ∈ mail_register｜settings_group。"""
    out = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        name = getattr(n.func, "attr", None) or getattr(n.func, "id", None)
        a = n.args
        if not a or not (isinstance(a[0], ast.Constant) and isinstance(a[0].value, str)):
            continue
        if name == "register" and len(a) >= 3 and isinstance(a[2], ast.Constant) and a[2].value in CATEGORIES:
            out.append(("mail_register", a[0].value, n.lineno))
        elif name == "register_group":
            out.append(("settings_group", a[0].value, n.lineno))
    return out


def declared(manifest):
    """module.json → ({信件鍵}, {設定群組代號})。"""
    mails, groups = set(), set()
    for f in (manifest.get("features") or []):
        if isinstance(f, dict):
            mails.update(m for m in (f.get("mail") or []) if isinstance(m, str))
    groups.update(((manifest.get("settings") or {}).get("groups")) or [])
    for f in (manifest.get("features") or []):
        g = ((f or {}).get("settings") or {}).get("group") if isinstance(f, dict) else None
        if isinstance(g, str):
            groups.add(g)
    return mails, groups


def scan_tree(root=None):
    """`modules/<m>/**.py` 的字面登記 ⇒ {(相對路徑, kind, key)}（含行號 dict 供訊息）。"""
    root = Path(root) if root else BACKEND / "modules"
    found = {}
    for f in sorted(root.rglob("*.py")):
        parts = f.relative_to(root).parts
        if "tests" in parts or "migrations" in parts:
            continue
        for kind, key, ln in scan_source(f.read_text(encoding="utf-8")):
            found[("/".join(("modules",) + parts), kind, key)] = ln
    return found


def manifests(root=None):
    root = Path(root) if root else BACKEND / "modules"
    out = {}
    for m in sorted(root.glob("*/module.json")):
        try:
            out[m.parent.name] = json.loads(m.read_text(encoding="utf-8"))
        except ValueError:
            out[m.parent.name] = {}
    return out


def allowlist_entries(path=None):
    p = Path(path) if path else ALLOWLIST
    return json.loads(p.read_text(encoding="utf-8")).get("entries", []) if p.exists() else []


def problems(found, mans, entries, today=None):
    """違規與白名單失效的描述清單（空＝通過）。"""
    today = today or date.today()
    out = []
    allowed = {}
    for e in entries:
        for k in e.get("keys", []):
            allowed[(e["file"], e["kind"], k)] = e
        for fld in ("reason", "owner", "expires"):
            if not str(e.get(fld) or "").strip():
                out.append("白名單項目缺 %s：%s" % (fld, e.get("file")))
        try:
            if date.fromisoformat(e.get("expires", "")) < today:
                out.append("白名單項目已過期（%s）：%s" % (e.get("expires"), e.get("file")))
        except ValueError:
            out.append("白名單 expires 格式不對（YYYY-MM-DD）：%s" % e.get("file"))
    for (file, kind, key), ln in sorted(found.items()):
        mod = file.split("/")[1]
        mails, groups = declared(mans.get(mod, {}))
        ok = key in (mails if kind == "mail_register" else groups)
        if (file, kind, key) in allowed:
            if ok:
                out.append("白名單項目已不需要（已在 module.json 宣告）：%s %s %s" % (file, kind, key))
            continue
        if not ok:
            out.append("%s:%d 字面登記 %s %r，但 %s/module.json 的 features[].%s 沒有宣告（補宣告，或附理由加進白名單）" % (
                file, ln, kind, key, mod, "mail" if kind == "mail_register" else "settings.group／settings.groups"))
    for k in sorted(allowed):
        if k not in found:
            out.append("白名單項目對不上實際程式（已移除或改名？請刪掉）：%s %s %s" % k)
    return out
