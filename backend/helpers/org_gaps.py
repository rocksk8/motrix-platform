# -*- coding: utf-8 -*-
"""組織設定缺口檢查（選單去工程師化 批次 5a，2026-11-13）：只讀，不改任何資料。

[單位] helper:org_gaps    [層] L1    [穩定度] 實驗
[公開介面] check, GAP_KEYS
[檢查項目] ①在職但沒有部門的人 ②有在職成員、卻沒有主管（或主管已停用）的部門 ③沒有任何人持有「財務」職務
[不變式] ①只讀（不寫、不 DELETE）；任何一項查不到資料表／欄位 ⇒ 該項視為「沒有缺口」並記 log，不丟 500（缺口檢查壞了不該擋住頁面）。
    ②「持有財務職務」走 `helpers.auth.finance_duty_person`（與實際權限同一條規則，旗標 off／on 都對）；最高管理者不算（他本來就全能，缺口是「日常沒人負責財務」）。
    ③沒有在職成員的空部門不算缺口（沒有人需要它的主管）。
    ④回傳的人名／部門名只給呼叫端（路由限管理者以上），單項最多列 `MAX_ITEMS` 筆，`count` 一律是完整數量。
    ⑤文字用白話、不含程式字眼；`fix.href` 指向實際能修的頁面（不新增頁面）。
"""
import logging

logger = logging.getLogger("motrix.org_gaps")

MAX_ITEMS = 20

#: 缺口代碼（前端／測試共用）
GAP_NO_DEPARTMENT = "no_department"
GAP_NO_MANAGER = "no_manager"
GAP_NO_FINANCE = "no_finance"
GAP_KEYS = (GAP_NO_DEPARTMENT, GAP_NO_MANAGER, GAP_NO_FINANCE)


def _label(row) -> str:
    return (row["display_name"] or row["username"] or "").strip() or ("#%s" % row["id"])


def _no_department(conn):
    rows = conn.execute(
        "SELECT id, username, display_name FROM users WHERE active=1 AND (department_id IS NULL OR department_id=0) ORDER BY id"
    ).fetchall()
    if not rows:
        return None
    return {
        "key": GAP_NO_DEPARTMENT, "severity": "warn", "count": len(rows),
        "title": "有 %d 位同仁還沒有歸屬部門" % len(rows),
        "detail": "沒有部門的人，簽核流程找不到他的部門主管，單據會卡住或改送給最高管理者。",
        "items": [{"id": r["id"], "name": _label(r)} for r in rows[:MAX_ITEMS]],
        "fix": {"label": "到使用者管理補上部門", "href": "users.html"},
    }


def _no_manager(conn):
    rows = conn.execute(
        """
        SELECT d.id, d.name, d.manager_user_id,
               (SELECT COUNT(*) FROM users u WHERE u.department_id = d.id AND u.active = 1) AS members,
               m.active AS manager_active
        FROM departments d LEFT JOIN users m ON m.id = d.manager_user_id
        ORDER BY d.id
        """
    ).fetchall()
    bad = [r for r in rows if r["members"] > 0 and (not r["manager_user_id"] or not r["manager_active"])]
    if not bad:
        return None
    return {
        "key": GAP_NO_MANAGER, "severity": "warn", "count": len(bad),
        "title": "有 %d 個部門沒有主管" % len(bad),
        "detail": "「部門主管簽核」會找不到人。請為這些部門指定一位在職的主管（主管離職停用後也要重新指定）。",
        "items": [{"id": r["id"], "name": r["name"], "note": ("主管已停用" if r["manager_user_id"] else "尚未指定")} for r in bad[:MAX_ITEMS]],
        "fix": {"label": "到組織架構指定主管", "href": "org-structure.html"},
    }


def _no_finance(conn):
    from helpers.auth import finance_duty_person
    rows = conn.execute("SELECT id, username, role, modules FROM users WHERE active=1").fetchall()
    for r in rows:
        if finance_duty_person({"id": r["id"], "username": r["username"], "role": r["role"], "modules": r["modules"]}):
            return None
    if not rows:
        return None                                  # 還沒有任何人員（全新安裝）：不提醒，免得開機第一眼就一堆紅字
    return {
        "key": GAP_NO_FINANCE, "severity": "warn", "count": 1,
        "title": "目前沒有人擔任「財務」職務",
        "detail": "請款、付款、對帳等財務動作目前只有最高管理者能做。請指定一位同仁擔任財務。",
        "items": [],
        "fix": {"label": "到使用者管理指定財務", "href": "users.html"},
    }


def check(conn=None) -> dict:
    """回 {ok, count, gaps:[{key, severity, title, detail, count, items, fix:{label, href}}]}；ok＝完全沒有缺口。"""
    own = conn is None
    if own:
        from db import get_db
        conn = get_db()
    gaps = []
    try:
        for fn in (_no_department, _no_manager, _no_finance):
            try:
                g = fn(conn)
            except Exception:  # noqa: BLE001 — 單項壞掉不影響其他項，也不擋頁面
                logger.warning("org_gaps.%s 失敗，略過這一項", fn.__name__, exc_info=True)
                g = None
            if g:
                gaps.append(g)
    finally:
        if own:
            conn.close()
    return {"ok": not gaps, "count": len(gaps), "gaps": gaps}
