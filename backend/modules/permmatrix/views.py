# -*- coding: utf-8 -*-
"""權限矩陣的唯讀檢視（T67 PM-S2）：角色×能力格、某人的有效權限與理由。純讀取、不寫任何表。

能力清單一律來自模組宣告（`core.capabilities.all_caps()`）：沒有宣告就沒有格子，這裡不寫死任何模組或動作內容（框架先行）。
文字只給白話名稱與一句話說明；呼叫端（頁面）不顯示能力鍵，鍵只用於回傳寫入請求。
"""
from core import capabilities as CAP
from helpers import perm as P
from helpers import perm_text as T
from modules.permmatrix import service as S


def _cap_row(c):
    return {"key": c.key, "unit": c.unit, "unitLabel": T.module_label(c.unit), "obj": c.obj, "action": c.action, "actionLabel": T.action_label(c.action),
            "label": c.label, "desc": c.desc, "impact": c.impact, "risk": c.risk, "delegable": c.delegable,
            "wired": not c.reserved}              # 「未接入」＝已登錄但還沒有任何端點使用（頁面不可勾）


def matrix_view(conn):
    """角色×能力：每格 {granted, seeded, changed}；`changed`＝與種子（今天的行為）不同。回應不含個資。"""
    caps = CAP.all_caps()
    seed = P.seed_from_legacy(caps)
    eff = S._build_matrix(conn, seed)
    roles = S._roles()
    rows = []
    for key in sorted(caps):
        c = caps[key]
        cells = {}
        for r in roles:
            seeded = key in seed.role_grants.get(r, ())
            granted = key in eff.role_grants.get(r, ())
            cells[r] = {"granted": granted, "seeded": seeded, "changed": granted != seeded}
        rows.append({**_cap_row(c), "cells": cells})
    return {"roles": [{"role": r, "label": T.role_label(r)} for r in roles],
            "actions": [{"action": a, "label": CAP.ACTION_INFO[a][0], "desc": CAP.ACTION_INFO[a][1], "highRisk": a in CAP.HIGH_RISK_ACTIONS} for a in CAP.ACTIONS],
            "caps": rows, "signature": CAP.signature()}


def user_effective(conn, user_id):
    """某人的有效權限與每格理由（白話一句）。找不到或已停用 ⇒ PermError 404。"""
    r = conn.execute("SELECT username FROM users WHERE id=? AND active=1", (int(user_id),)).fetchone()
    u = P.load_user(r["username"]) if r else None
    if u is None:
        raise S.PermError("找不到該使用者或帳號已停用", 404)
    out = []
    for key, c in sorted(CAP.all_caps().items()):
        e = P.explain(u, key)
        out.append({**_cap_row(c), "allowed": bool(e.get("allowed")), "via": e.get("via"), "why": T.explain_text(u, key)})
    return {"user": {"id": u["id"], "name": T.user_label(u), "roleLabel": T.role_label(u["role"])}, "caps": out}


def users_view(conn):
    """個人覆寫分頁的人選與現有覆寫（不含最高管理者：不受覆寫影響）。"""
    ov = {}
    for r in conn.execute("SELECT user_id, cap, effect, set_by, set_at, reason FROM perm_user_overrides ORDER BY user_id, cap").fetchall():
        c = CAP.get(r["cap"])
        ov.setdefault(r["user_id"], []).append({"key": r["cap"], "label": c.label if c else "（未命名）", "effect": r["effect"], "setBy": r["set_by"], "setAt": r["set_at"], "reason": r["reason"]})
    users = [{"id": r["id"], "name": r["display_name"] or r["username"], "roleLabel": T.role_label(r["role"]), "overrides": ov.get(r["id"], [])}
             for r in conn.execute("SELECT id, username, display_name, role FROM users WHERE active=1 AND role!='superadmin' ORDER BY id").fetchall()]
    return {"users": users}
