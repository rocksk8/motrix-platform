# -*- coding: utf-8 -*-
"""內建頁面開放給自訂模組的「掛載點」（建構器方案 B；設計 docs/platform/plans/BUILDER-B-DESIGN.md）。

[單位] plat:mounts    [層] L0    [穩定度] 實驗（第 31 班骨架；出貨時升契約）
[公開介面] KINDS, MAX_TABS_PER_POINT, declared_points, point_id, validate_mount_points, visible_point
[不變式] 掛載點只來自已載入模組 module.json 的 `mount_points`；`page` 必須是同一份 `pages[].path`；perm 與選單項同一種格式、同一個判準
    （core.menu.visible）；格式錯誤 ⇒ 問題清單（loader 不載入該模組，同 customization）
[注意] 只用標準函式庫（loader 在 import 模組前驗 module.json）。「隱藏頁籤」不是存取控制——嵌入的自訂模組各端點仍各自驗權限。

`module.json`：
    "mount_points": [{"key": "daily-tasks", "page": "daily-tasks.html", "kind": "tab",
                      "label": "每日工作事項頁籤", "perm": "any", "context": []}]
全域識別＝`<模組key>.<key>`（例 `daily_tasks.daily-tasks`）。
"""
import re

KINDS = ("tab",)
#: 同一個掛載點最多幾個自訂模組頁籤（超過 ⇒ 建構器發布時拒絕；顯示端也只取前這麼多）
MAX_TABS_PER_POINT = 8

_KEY = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
_CTX = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")
_REQUIRED = ("key", "page", "kind", "label", "perm")
_OPTIONAL = ("context",)


def _p(path, message):
    return {"path": path, "message": message}


def point_id(module_key, key):
    return "%s.%s" % (module_key, key)


def _perm_valid(perm):
    # 與選單項同一個格式（core.menu._perm_ok）：任一模組權限的清單／"superadmin"／"any"
    from core import menu as _menu
    return _menu._perm_ok(perm)


def validate_mount_points(manifest) -> list:
    """`module.json` 的 `mount_points` ⇒ 問題清單 `[{path, message}]`（沒有這個鍵 ⇒ 空清單）。"""
    out = []
    if not isinstance(manifest, dict) or "mount_points" not in manifest:
        return out
    pts = manifest["mount_points"]
    if not isinstance(pts, list):
        return [_p("mount_points", "必須是清單")]
    pages = {pg.get("path") for pg in (manifest.get("pages") or []) if isinstance(pg, dict)}
    keys = []
    for i, p in enumerate(pts):
        pp = "mount_points[%d]" % i
        if not isinstance(p, dict):
            out.append(_p(pp, "必須是物件"))
            continue
        for k in _REQUIRED:
            if k not in p:
                out.append(_p(pp, "缺 %s" % k))
        for k in p:
            if k not in _REQUIRED and k not in _OPTIONAL:
                out.append(_p("%s.%s" % (pp, k), "不認得的鍵（可用：%s）" % "、".join(_REQUIRED + _OPTIONAL)))
        if "key" in p:
            if not isinstance(p["key"], str) or not _KEY.match(p["key"]):
                out.append(_p(pp + ".key", "key 必須符合 [a-z][a-z0-9-]{0,39}：%r" % (p["key"],)))
            else:
                keys.append(p["key"])
        if "page" in p and p["page"] not in pages:
            out.append(_p(pp + ".page", "頁面 %r 不在 module.json 的 pages[].path（掛載點只能開在本模組宣告的頁面）" % (p["page"],)))
        if "kind" in p and p["kind"] not in KINDS:
            out.append(_p(pp + ".kind", "kind 目前只有 %s：%r" % ("、".join(KINDS), p["kind"])))
        if "label" in p and (not isinstance(p["label"], str) or not p["label"].strip()):
            out.append(_p(pp + ".label", "label 必須是非空字串"))
        if "perm" in p and not _perm_valid(p["perm"]):
            out.append(_p(pp + ".perm", "perm 格式不對（模組權限清單、\"superadmin\" 或 \"any\"）：%r" % (p["perm"],)))
        ctx = p.get("context", [])
        if not isinstance(ctx, list) or not all(isinstance(c, str) and _CTX.match(c) for c in ctx) or len(set(ctx)) != len(ctx):
            out.append(_p(pp + ".context", "必須是不重複的鍵名清單（例 [\"case_no\"]）"))
    seen = set()
    for k in keys:
        if k in seen:
            out.append(_p("mount_points", "key 重複：%s" % k))
        seen.add(k)
    return out


def declared_points(manifests) -> dict:
    """{模組key: manifest}（**只含已載入模組**，由呼叫端保證）⇒ {點 id: {module, key, page, kind, label, perm, context}}。
    格式有問題的宣告不會到這裡（loader 已拒載）；仍防禦性略過不合格的列。"""
    out = {}
    for mkey in sorted(manifests or {}):
        m = manifests[mkey] or {}
        if validate_mount_points(m):
            continue
        for p in m.get("mount_points") or []:
            out[point_id(mkey, p["key"])] = {"module": mkey, "key": p["key"], "page": p["page"], "kind": p["kind"],
                                             "label": p["label"], "perm": p["perm"], "context": list(p.get("context") or [])}
    return out


def visible_point(point, modules, superadmin) -> bool:
    """這位使用者（模組權限集合、是否最高管理者）過得了該點自己的 perm 嗎？與選單項同一個判準（core.menu.visible）。"""
    from core import menu as _menu
    return _menu.visible(point["perm"], set(modules or []), superadmin)
