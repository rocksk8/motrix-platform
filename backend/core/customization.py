# -*- coding: utf-8 -*-
"""L0 模組描述：可自訂點（CUSTOMIZATION-SPEC P3；§8.2 排版器需求）。

模組在 `module.json` 的 `customization` 登記「排版器可以動的點」：列表欄位、表單區塊、按鈕、
選單（按鈕群組）、匯出按鈕、輸出版型；欄位分「核心」（不可移除、不可改名，只能移動位置）與
「可顯示」（可以隱藏、改標籤、移動）。排版器（P9）**只能**動這裡登記的點。

本檔只用標準函式庫（loader 是 L0，要在 import 模組之前驗 module.json）。三件事：

- `validate_manifest(manifest)`：格式驗證 ⇒ 問題清單 `[{path, message}]`；非空 ⇒ loader 不載入該模組。
  不認得的鍵一律是問題（寬鬆驗證會靜默丟掉欄位）；`schema` 看不懂 ⇒ 不猜。
- `points(manifest)`：把登記內容攤平成「點」清單（每個點帶 `id`、`kind`、允許的 `ops`），給能力目錄與排版器用。
- `check_layout(points, ops)`：排版操作只能指向登記過的點、只能做該點允許的操作
  （「程式沒有提供的選項不可以出現」的資料層守門；P5 的 layout 驗證器與 P9 都要呼叫它）。

與 STAGE-C（B）的 `pages[].menu` 的分工：側欄選單項**只在** `pages[].menu` 宣告（B 的格式），
本檔不重複宣告，只把有 `menu` 物件的頁面衍生成 `sidebar` 點；`customization.pages[].page`
必須是同一個 module.json `pages[].path` 裡的頁面。
"""
import re

#: 可自訂點描述的格式版本。loader 只認得這些；看不懂 ⇒ 模組不載入（不猜）。
SCHEMA_VERSIONS = (1,)

#: 每一頁必須逐項寫出的類別（沒有也要寫空清單＝有人決定過「這一頁沒有」）。
PAGE_KINDS = ("lists", "forms", "actions", "menus", "exports")

#: 各類點允許的排版操作（v1）。
OPS_CORE_FIELD = ("move",)
OPS_DISPLAY_FIELD = ("move", "hide", "show", "relabel")
OPS_BY_KIND = {
    "sidebar": ("move", "hide", "relabel"),
    "list": ("reorder",),
    "form": ("reorder", "add_section"),
    "section": ("move", "relabel"),
    "action": ("move", "hide", "relabel"),
    "menu": ("move", "hide", "relabel", "reorder"),
    "export": ("move", "hide", "relabel"),
    "output": ("select_template",),
}

EXPORT_FORMATS = ("xlsx", "csv", "pdf")

_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")
_ENDPOINT = re.compile(r"^(GET|POST|PUT|PATCH|DELETE) (/[^\s]*)$")


def _p(path, message):
    return {"path": path, "message": message}


def _check_keys(obj, required, optional, path, out):
    """必填鍵要在、不認得的鍵是問題。回傳物件是否為 dict。"""
    if not isinstance(obj, dict):
        out.append(_p(path, "必須是物件"))
        return False
    for k in required:
        if k not in obj:
            out.append(_p(path, "缺 %s" % k))
    for k in obj:
        if k not in required and k not in optional:
            out.append(_p("%s.%s" % (path, k), "不認得的鍵（可用：%s）" % "、".join(list(required) + list(optional))))
    return True


def _key_ok(v, path, out):
    if not isinstance(v, str) or not _KEY.match(v):
        out.append(_p(path, "key 必須符合 [A-Za-z][A-Za-z0-9_]{0,39}：%r" % (v,)))
        return False
    return True


def _label_ok(v, path, out):
    if not isinstance(v, str) or not v.strip():
        out.append(_p(path, "label 必須是非空字串"))


def _list_of(v, path, out, nonempty=False):
    if not isinstance(v, list):
        out.append(_p(path, "必須是清單"))
        return []
    if nonempty and not v:
        out.append(_p(path, "不可以是空清單"))
    return v


def _unique(keys, path, out, what):
    seen = set()
    for k in keys:
        if k in seen:
            out.append(_p(path, "%s 重複：%s" % (what, k)))
        seen.add(k)


def endpoint_parts(spec):
    """"POST /api/x" ⇒ ("POST", "/api/x")；格式不對 ⇒ None。"""
    m = _ENDPOINT.match(spec or "") if isinstance(spec, str) else None
    return (m.group(1), m.group(2)) if m else None


def validate_manifest(manifest) -> list:
    """`module.json` 的 `customization` ⇒ 問題清單（空＝合格）。沒有 `customization` 鍵 ⇒ 空清單
    （載入器不擋；「每個模組都要登記」由 G2 守門在 repo 層擋，不在客戶現場擋啟動）。"""
    out = []
    if not isinstance(manifest, dict) or "customization" not in manifest:
        return out
    c = manifest["customization"]
    root = "customization"
    if not _check_keys(c, ("schema", "fields", "pages", "outputs"), (), root, out):
        return out
    if c.get("schema") not in SCHEMA_VERSIONS or isinstance(c.get("schema"), bool):
        out.append(_p(root + ".schema", "看不懂的格式版本 %r（認得：%s）" % (c.get("schema"), SCHEMA_VERSIONS)))
        return out
    perms = manifest.get("permissions") or []

    # 欄位：{entity: [{key, label, core}]}
    entity_fields = {}
    fields = c.get("fields")
    if not isinstance(fields, dict):
        out.append(_p(root + ".fields", "必須是物件 {實體: [欄位]}"))
        fields = {}
    for ent, flist in fields.items():
        ep = "%s.fields.%s" % (root, ent)
        _key_ok(ent, ep, out)
        keys = []
        for i, f in enumerate(_list_of(flist, ep, out, nonempty=True)):
            fp = "%s[%d]" % (ep, i)
            if not _check_keys(f, ("key", "label", "core"), (), fp, out):
                continue
            if _key_ok(f.get("key"), fp + ".key", out):
                keys.append(f["key"])
            _label_ok(f.get("label"), fp + ".label", out)
            if "core" in f and not isinstance(f["core"], bool):
                out.append(_p(fp + ".core", "core 必須是 true／false（核心欄位不可改；可顯示欄位可隱藏、改標籤）"))
        _unique(keys, ep, out, "欄位 key")
        entity_fields[ent] = set(keys)

    # 頁面
    declared_pages = {pg.get("path") for pg in (manifest.get("pages") or []) if isinstance(pg, dict)}
    page_names = []
    for i, pg in enumerate(_list_of(c.get("pages"), root + ".pages", out)):
        pp = "%s.pages[%d]" % (root, i)
        if not _check_keys(pg, ("page",) + PAGE_KINDS, (), pp, out):
            continue
        name = pg.get("page")
        page_names.append(name)
        if name not in declared_pages:
            out.append(_p(pp + ".page", "頁面 %r 不在 module.json 的 pages[].path（可自訂點只能掛在本模組宣告的頁面）" % (name,)))
        _validate_page(pg, pp, entity_fields, perms, out)
    _unique(page_names, root + ".pages", out, "頁面")

    # 輸出版型
    okeys = []
    for i, o in enumerate(_list_of(c.get("outputs"), root + ".outputs", out)):
        op = "%s.outputs[%d]" % (root, i)
        if not _check_keys(o, ("key", "label", "template"), (), op, out):
            continue
        if _key_ok(o.get("key"), op + ".key", out):
            okeys.append(o["key"])
        _label_ok(o.get("label"), op + ".label", out)
        if not isinstance(o.get("template"), str) or not o.get("template"):
            out.append(_p(op + ".template", "template 必須是預設版型的 key（helpers/output_templates/<key>.json）"))
    _unique(okeys, root + ".outputs", out, "輸出 key")
    return out


def _validate_page(pg, pp, entity_fields, perms, out):
    def fields_of(entity, path):
        if entity not in entity_fields:
            out.append(_p(path, "實體 %r 沒有在 customization.fields 宣告" % (entity,)))
            return None
        return entity_fields[entity]

    # 列表
    lkeys = []
    for i, lst in enumerate(_list_of(pg.get("lists"), pp + ".lists", out)):
        lp = "%s.lists[%d]" % (pp, i)
        if not _check_keys(lst, ("key", "label", "entity", "columns"), (), lp, out):
            continue
        if _key_ok(lst.get("key"), lp + ".key", out):
            lkeys.append(lst["key"])
        _label_ok(lst.get("label"), lp + ".label", out)
        known = fields_of(lst.get("entity"), lp + ".entity")
        cols = []
        for j, col in enumerate(_list_of(lst.get("columns"), lp + ".columns", out, nonempty=True)):
            cp = "%s.columns[%d]" % (lp, j)
            if not _check_keys(col, ("field", "visible"), (), cp, out):
                continue
            cols.append(col.get("field"))
            if known is not None and col.get("field") not in known:
                out.append(_p(cp + ".field", "欄位 %r 不在實體 %r 的欄位清單" % (col.get("field"), lst.get("entity"))))
            if not isinstance(col.get("visible"), bool):
                out.append(_p(cp + ".visible", "visible 必須是 true／false（預設是否顯示）"))
        _unique(cols, lp + ".columns", out, "欄位")
    _unique(lkeys, pp + ".lists", out, "列表 key")

    # 表單
    fkeys = []
    for i, frm in enumerate(_list_of(pg.get("forms"), pp + ".forms", out)):
        fp = "%s.forms[%d]" % (pp, i)
        if not _check_keys(frm, ("key", "label", "entity", "sections"), (), fp, out):
            continue
        if _key_ok(frm.get("key"), fp + ".key", out):
            fkeys.append(frm["key"])
        _label_ok(frm.get("label"), fp + ".label", out)
        known = fields_of(frm.get("entity"), fp + ".entity")
        skeys, used = [], []
        for j, sec in enumerate(_list_of(frm.get("sections"), fp + ".sections", out, nonempty=True)):
            sp = "%s.sections[%d]" % (fp, j)
            if not _check_keys(sec, ("key", "label", "fields"), (), sp, out):
                continue
            if _key_ok(sec.get("key"), sp + ".key", out):
                skeys.append(sec["key"])
            _label_ok(sec.get("label"), sp + ".label", out)
            for k, fld in enumerate(_list_of(sec.get("fields"), sp + ".fields", out, nonempty=True)):
                used.append(fld)
                if known is not None and fld not in known:
                    out.append(_p("%s.fields[%d]" % (sp, k), "欄位 %r 不在實體 %r 的欄位清單" % (fld, frm.get("entity"))))
        _unique(skeys, fp + ".sections", out, "區塊 key")
        _unique(used, fp + ".sections", out, "欄位（同一欄位只能放在一個區塊）")
    _unique(fkeys, pp + ".forms", out, "表單 key")

    # 按鈕
    akeys = []
    for i, act in enumerate(_list_of(pg.get("actions"), pp + ".actions", out)):
        ap = "%s.actions[%d]" % (pp, i)
        if not _check_keys(act, ("key", "label"), ("endpoint", "perm"), ap, out):
            continue
        if _key_ok(act.get("key"), ap + ".key", out):
            akeys.append(act["key"])
        _label_ok(act.get("label"), ap + ".label", out)
        if "endpoint" in act and endpoint_parts(act["endpoint"]) is None:
            out.append(_p(ap + ".endpoint", "endpoint 格式必須是「METHOD /path」：%r" % (act["endpoint"],)))
        if "perm" in act and act["perm"] not in perms:
            out.append(_p(ap + ".perm", "perm %r 不在 module.json 的 permissions" % (act["perm"],)))
    _unique(akeys, pp + ".actions", out, "按鈕 key")

    # 選單（一組按鈕：下拉選單或列操作群組）；項目只能是本頁登記的按鈕
    mkeys = []
    for i, mn in enumerate(_list_of(pg.get("menus"), pp + ".menus", out)):
        mp = "%s.menus[%d]" % (pp, i)
        if not _check_keys(mn, ("key", "label", "items"), (), mp, out):
            continue
        if _key_ok(mn.get("key"), mp + ".key", out):
            mkeys.append(mn["key"])
        _label_ok(mn.get("label"), mp + ".label", out)
        items = _list_of(mn.get("items"), mp + ".items", out, nonempty=True)
        for k, it in enumerate(items):
            if it not in akeys:
                out.append(_p("%s.items[%d]" % (mp, k), "選單項目 %r 不是本頁登記的按鈕" % (it,)))
        _unique(items, mp + ".items", out, "選單項目")
    _unique(mkeys, pp + ".menus", out, "選單 key")

    # 匯出按鈕：一定要有端點（匯出是程式提供的能力）
    xkeys = []
    for i, ex in enumerate(_list_of(pg.get("exports"), pp + ".exports", out)):
        xp = "%s.exports[%d]" % (pp, i)
        if not _check_keys(ex, ("key", "label", "endpoint", "format"), ("perm",), xp, out):
            continue
        if _key_ok(ex.get("key"), xp + ".key", out):
            xkeys.append(ex["key"])
        _label_ok(ex.get("label"), xp + ".label", out)
        if endpoint_parts(ex.get("endpoint")) is None:
            out.append(_p(xp + ".endpoint", "endpoint 格式必須是「METHOD /path」：%r" % (ex.get("endpoint"),)))
        if ex.get("format") not in EXPORT_FORMATS:
            out.append(_p(xp + ".format", "format 必須是 %s 之一" % "／".join(EXPORT_FORMATS)))
        if "perm" in ex and ex["perm"] not in perms:
            out.append(_p(xp + ".perm", "perm %r 不在 module.json 的 permissions" % (ex["perm"],)))
    _unique(xkeys, pp + ".exports", out, "匯出 key")


def require_valid(manifest) -> None:
    """loader 的呼叫點：格式錯誤 ⇒ ValueError（loader 記成「載入失敗」並顯示原因；前三項＋總數）。"""
    problems = validate_manifest(manifest)
    if problems:
        head = "；".join("%s：%s" % (p["path"], p["message"]) for p in problems[:3])
        more = "（另有 %d 項）" % (len(problems) - 3) if len(problems) > 3 else ""
        raise ValueError("module.json customization 格式錯誤：" + head + more)


# ── 攤平成點 ─────────────────────────────────────────────────────────────────

def points(manifest) -> list:
    """登記內容 ⇒ 點清單。只對**已通過** validate_manifest 的 manifest 呼叫。

    每個點：`{id, kind, label, ops, ...}`；id 形如 `<module>:<page>/list:<key>/column:<field>`。
    沒有 `customization` ⇒ 只有 sidebar 點（若 pages[].menu 有宣告）。"""
    key = manifest.get("key") or ""
    out = []
    for pg in manifest.get("pages") or []:
        if isinstance(pg, dict) and isinstance(pg.get("menu"), dict):
            out.append({"id": "%s:%s/sidebar" % (key, pg.get("path")), "kind": "sidebar",
                        "label": pg["menu"].get("label") or pg.get("path"), "page": pg.get("path"),
                        "menu": dict(pg["menu"]), "ops": list(OPS_BY_KIND["sidebar"])})
    c = manifest.get("customization")
    if not isinstance(c, dict):
        return out
    fields = {ent: {f["key"]: f for f in flist} for ent, flist in (c.get("fields") or {}).items()}

    def field_point(pid, ent, fkey, extra):
        f = fields[ent][fkey]
        core = bool(f["core"])
        d = {"id": pid, "kind": "field", "entity": ent, "field": fkey, "label": f["label"], "core": core,
             "ops": list(OPS_CORE_FIELD if core else OPS_DISPLAY_FIELD)}
        d.update(extra)
        return d

    for pg in c.get("pages") or []:
        base = "%s:%s" % (key, pg["page"])
        for lst in pg["lists"]:
            lid = "%s/list:%s" % (base, lst["key"])
            out.append({"id": lid, "kind": "list", "label": lst["label"], "entity": lst["entity"],
                        "ops": list(OPS_BY_KIND["list"])})
            for col in lst["columns"]:
                out.append(field_point("%s/column:%s" % (lid, col["field"]), lst["entity"], col["field"],
                                       {"parent": lid, "visible": col["visible"]}))
        for frm in pg["forms"]:
            fid = "%s/form:%s" % (base, frm["key"])
            out.append({"id": fid, "kind": "form", "label": frm["label"], "entity": frm["entity"],
                        "ops": list(OPS_BY_KIND["form"])})
            for sec in frm["sections"]:
                sid = "%s/section:%s" % (fid, sec["key"])
                out.append({"id": sid, "kind": "section", "label": sec["label"], "parent": fid,
                            "ops": list(OPS_BY_KIND["section"])})
                for fld in sec["fields"]:
                    out.append(field_point("%s/field:%s" % (fid, fld), frm["entity"], fld, {"parent": sid}))
        for act in pg["actions"]:
            d = {"id": "%s/action:%s" % (base, act["key"]), "kind": "action", "label": act["label"],
                 "ops": list(OPS_BY_KIND["action"])}
            for k in ("endpoint", "perm"):
                if k in act:
                    d[k] = act[k]
            out.append(d)
        for mn in pg["menus"]:
            out.append({"id": "%s/menu:%s" % (base, mn["key"]), "kind": "menu", "label": mn["label"],
                        "items": ["%s/action:%s" % (base, it) for it in mn["items"]],
                        "ops": list(OPS_BY_KIND["menu"])})
        for ex in pg["exports"]:
            d = {"id": "%s/export:%s" % (base, ex["key"]), "kind": "export", "label": ex["label"],
                 "endpoint": ex["endpoint"], "format": ex["format"], "ops": list(OPS_BY_KIND["export"])}
            if "perm" in ex:
                d["perm"] = ex["perm"]
            out.append(d)
    for o in c.get("outputs") or []:
        out.append({"id": "%s:output:%s" % (key, o["key"]), "kind": "output", "label": o["label"],
                    "template": o["template"], "ops": list(OPS_BY_KIND["output"])})
    return out


def core_fields(manifest) -> dict:
    """{實體: [核心欄位 key]}——P4 自訂欄位不可以與它們同名（CUSTOMIZATION-SPEC §3.6）。"""
    c = manifest.get("customization") if isinstance(manifest, dict) else None
    if not isinstance(c, dict):
        return {}
    return {ent: [f["key"] for f in flist if f.get("core") is True] for ent, flist in (c.get("fields") or {}).items()}


# ── 排版操作的守門 ───────────────────────────────────────────────────────────

def check_layout(pts, ops) -> list:
    """排版操作清單 `[{op, target, ...}]` ⇒ 問題清單。

    - target 不在登記的點裡 ⇒ 擋（程式沒有提供的選項不可以出現）
    - op 不在該點允許的 ops ⇒ 擋（例：隱藏或改名核心欄位）
    - `move` 的 `to`（有給時）必須是同一種容器裡登記過的點：欄位只能在同一個表單的區塊之間移動、
      列表欄位只能留在原本的列表
    """
    by_id = {p["id"]: p for p in pts}
    out = []
    if not isinstance(ops, list):
        return [_p("", "排版操作必須是清單")]
    for i, o in enumerate(ops):
        path = "[%d]" % i
        if not isinstance(o, dict):
            out.append(_p(path, "必須是物件"))
            continue
        target = o.get("target")
        p = by_id.get(target)
        if p is None:
            out.append(_p(path + ".target", "不是登記過的可自訂點：%r" % (target,)))
            continue
        if o.get("op") not in p["ops"]:
            out.append(_p(path + ".op", "點 %s 不允許 %r（允許：%s）" % (target, o.get("op"), "、".join(p["ops"]))))
            continue
        if o.get("op") == "move" and "to" in o:
            dest = by_id.get(o["to"])
            if dest is None:
                out.append(_p(path + ".to", "目的地不是登記過的可自訂點：%r" % (o["to"],)))
            elif p["kind"] == "field" and not _same_container(p, dest):
                out.append(_p(path + ".to", "欄位只能在原本的列表或同一個表單的區塊之間移動：%s ⇒ %s" % (target, o["to"])))
        if o.get("op") == "relabel" and (not isinstance(o.get("label"), str) or not o["label"].strip()):
            out.append(_p(path + ".label", "relabel 要給非空的 label"))
    return out


def _same_container(field_pt, dest):
    parent = field_pt.get("parent") or ""
    if "/list:" in parent and "/section:" not in parent:
        return dest.get("id") == parent
    if dest.get("kind") != "section":
        return False
    form_of = lambda sid: sid.split("/section:")[0]  # noqa: E731
    return form_of(dest["id"]) == form_of(parent)
