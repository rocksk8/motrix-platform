# -*- coding: utf-8 -*-
"""選單建構器（BP-1）：側欄項改名、換到另一個既有群組、整份選單的發布前預覽。

[單位] helper:menu_builder    [層] L1    [穩定度] 實作
[公開介面] OFF_REASON, enabled, is_builder_op, redact_ops, ops_hash, preview, sidebar_ops_of_all
[不變式] 設定 `builder_menu.enabled`（預設 0＝關）關著時：relabel／move.to 不被接受（發布驗證擋）、不被套用（core.menu.apply_layout builder=False），預覽端點 404；
    其餘（hide／show／群組內 move）與今天逐字相同。改名與換群組**只是顯示**：href、perm、`denied` 不變，使用者沒有權限的項目永遠不出現在選單或預覽。
[注意] 只用既有的版面定義（kind=layout，key=module:<模組>）發布，不新增 kind、不碰 core/definitions.py
"""
import hashlib
import json

from core import catalog, registry
from core import menu as core_menu

GROUP = "builder_menu"
FIELD = "enabled"
MAX_OPS = 200
OFF_REASON = "選單建構器未開啟（設定：builder_menu.enabled）"


def enabled(conn=None) -> bool:
    """fail-closed：讀不到設定 ⇒ 關。"""
    try:
        from helpers import settings_registry as SR
        return bool(int(SR.get(GROUP, FIELD, conn=conn)))
    except Exception:                                        # noqa: BLE001
        return False


def is_builder_op(op) -> bool:
    """BP-1 新增的兩種操作：側欄改名、側欄換群組。"""
    if not isinstance(op, dict) or not str(op.get("target", "")).endswith("/sidebar"):
        return False
    return op.get("op") == "relabel" or (op.get("op") == "move" and "to" in op)


def redact_ops(items):
    """/api/platform/menu 回給非最高管理者的 applied／skipped／dropped：拿掉操作原文（含管理者取的名稱、看不到的目標），只留操作種類與理由。"""
    out = []
    for x in items or []:
        op = x.get("op") if isinstance(x, dict) else None
        kind = op.get("op") if isinstance(op, dict) else (op if isinstance(op, str) else None)
        if isinstance(op, str):                              # applied：每筆本身就是操作
            out.append({"op": kind})
        else:                                                # skipped／dropped：{op, reason|message}
            out.append({"op": {"op": kind}, **({"reason": x["reason"]} if isinstance(x, dict) and "reason" in x else {})})
    return out


def ops_hash(ops) -> str:
    return hashlib.sha256(json.dumps(ops, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def sidebar_ops_of_all(conn, role, mod_items):
    """每個有側欄點的已載入模組各 resolve 一次（與 /api/platform/menu 同一份 catalog.effective_layout_ops）⇒ 側欄 ops。"""
    ops = []
    for key in sorted({it["module"] for it in mod_items if it.get("module")}):
        eff = catalog.effective_layout_ops(conn, key, role)
        ops += [op for op in eff["ops"] if str((op or {}).get("target", "")).endswith("/sidebar")]
    return ops


def _problems(ops):
    """草稿 ops 逐模組過 catalog.check_layout；⇒ [{path, message}]（path 以整份 ops 為根）。"""
    out = []
    if not isinstance(ops, list):
        return [{"path": "ops", "message": "ops 必須是清單"}]
    if len(ops) > MAX_OPS:
        return [{"path": "ops", "message": "操作太多（上限 %d）" % MAX_OPS}]
    for i, op in enumerate(ops):
        tgt = (op or {}).get("target") if isinstance(op, dict) else None
        if not isinstance(tgt, str) or not tgt.endswith("/sidebar") or ":" not in tgt:
            out.append({"path": "ops[%d].target" % i, "message": "預覽只接受側欄項的操作"})
            continue
        mod = tgt.split(":", 1)[0]
        if not registry.is_loaded(mod):
            out.append({"path": "ops[%d].target" % i, "message": "模組 %s 未載入" % mod})
            continue
        out += [{"path": "ops[%d]%s" % (i, p["path"].replace("[0]", "", 1)), "message": p["message"]} for p in catalog.check_layout(mod, [op])]
    return out


def preview(conn, caller, body):
    """整份選單的預覽（唯讀、不寫任何資料）：以某位使用者（預設＝呼叫者）的權限算出『目前已發布』與『套上草稿 ops 之後』兩份。
    草稿 ops＝整份側欄操作（取代已發布的側欄操作做比較）。使用者沒有權限的項目兩份都不會出現（先過 core.menu.build）。
    ⇒ {"user","role","current","preview","skipped","opsHash"}；ops 不合法 ⇒ 丟 ValueError(problems)。"""
    from helpers.auth import effective_modules
    ops = (body or {}).get("ops", [])
    probs = _problems(ops)
    if probs:
        raise ValueError(probs)
    who = (body or {}).get("user")
    if who:
        row = conn.execute("SELECT id, username, role, modules FROM users WHERE username=? AND active=1", (str(who),)).fetchone()
        if not row:
            raise LookupError("找不到這位使用者")
        uid, uname, role, mods = row["id"], row["username"], row["role"], row["modules"]
    else:
        uid, uname, role, mods = caller.get("id"), caller["username"], caller["role"], caller.get("modules")
    modules = effective_modules(role, mods, user_id=uid, conn=conn)
    mod_items = core_menu.module_items({m.key: m.manifest for m in registry.loaded()})
    sa = role == "superadmin"
    groups = core_menu.build(core_menu.load_l1(), mod_items, modules, sa)
    current, _a, _s = core_menu.apply_layout_ex(groups, sidebar_ops_of_all(conn, role, mod_items), builder=True)
    new, _a, skipped = core_menu.apply_layout_ex(groups, ops, builder=True)
    return {"user": uname, "role": role, "current": current, "preview": new, "skipped": skipped, "opsHash": ops_hash(ops)}
