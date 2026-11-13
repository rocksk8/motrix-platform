# -*- coding: utf-8 -*-
"""組織設定缺口檢查（選單去工程師化 批次 5a，2026-11-13）：只讀，不改任何資料。

檢查項目（說明，不是單位卡欄位）：①在職但沒有部門的人 ②有在職成員、卻沒有主管（或主管已停用）的部門 ③沒有任何人持有「財務」職務

[單位] helper:org_gaps    [層] L1    [穩定度] 實驗
[公開介面] check, GAP_KEYS, GAP_NO_DEPARTMENT, GAP_NO_FINANCE, GAP_NO_MANAGER, MAX_ITEMS, finance_holder_exists
[契約題] tests/test_org_gaps_5a_2026_11_13.py
[不變式] ①只讀（不寫、不 DELETE）；任何一項查不到資料表／欄位 ⇒ 該項視為「沒有缺口」並記 log，不丟 500（缺口檢查壞了不該擋住頁面）。
    ②「持有財務職務」與 `helpers.auth.finance_duty_person` 同一條規則（旗標 off／shadow／on 都對；測試逐一比對），但**一次查詢、不逐人呼叫**
      （逐人呼叫在旗標 `on` 時每人開一條連線，300 人約 2 秒；`shadow` 時還會寫稽核）⇒ 本檔任何旗標模式都不寫入任何東西。最高管理者不算（他本來就全能，缺口是「日常沒人負責財務」）。
    ③沒有在職成員的空部門不算缺口（沒有人需要它的主管）。最高管理者不算「沒有部門」（主要是簽核、不是送審）；全新安裝（沒有任何在職的非最高管理者）整個檢查不出任何缺口。
    ④回傳的人名／部門名只給呼叫端（路由限管理者以上），單項最多列 `MAX_ITEMS` 筆，`count` 一律是完整數量。
    ⑤文字用白話、不含程式字眼；`fix.href` 指向實際能修的頁面（不新增頁面）。
"""
import json
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
        "SELECT id, username, display_name FROM users WHERE active=1 AND role!='superadmin' AND (department_id IS NULL OR department_id=0) ORDER BY id"
    ).fetchall()
    if not rows:
        return None
    return {
        "key": GAP_NO_DEPARTMENT, "severity": "warn", "count": len(rows),
        "title": "有 %d 位同仁還沒有歸屬部門" % len(rows),
        "detail": "沒有部門的人，送審時會被擋下（系統找不到他的部門主管），要先補上部門才能送審。最高管理者若要送審，仍然需要歸屬部門。",
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


def _finance_mode(conn) -> str:
    """旗標 `finance_via_effective`（off／shadow／on），直接讀、不走快取、不寫入；讀不到＝off（與 helpers.auth 的預設一致）。"""
    from helpers.auth import FINANCE_FLAG_KEY
    try:
        row = conn.execute("SELECT value_json FROM system_settings WHERE key=?", (FINANCE_FLAG_KEY,)).fetchone()
        v = json.loads(row[0]) if row else "off"
    except Exception:  # noqa: BLE001 — 讀不到／壞掉＝off（較嚴的角色規則），不讓整個檢查靜默消失
        logger.warning("org_gaps 讀不到財務旗標，當作 off", exc_info=True)
        v = "off"
    return v if v in ("shadow", "on") else "off"


def finance_holder_exists(conn) -> bool:
    """是否有任何在職、非最高管理者的人擔任「財務」職務。與 `helpers.auth.finance_duty_person` 同一條規則，但一次查完、完全唯讀：
    `off`／`shadow`＝角色是 finance；`on`＝（角色是 finance ∪ 已啟用職責角色給的 `finance` 鍵）− 個人扣項。
    新規則查不到（表不存在等）⇒ 退回角色規則（與 helpers.auth 的退路相同）。一致性由測試逐模式比對。"""
    from helpers.auth import FINANCE_ROLE
    rows = conn.execute("SELECT id, role FROM users WHERE active=1 AND role!='superadmin'").fetchall()
    base = {r["id"] for r in rows if r["role"] == FINANCE_ROLE}
    if _finance_mode(conn) != "on":
        return bool(base)
    try:
        granted = set()
        for r in conn.execute("SELECT b.user_id, r.permissions FROM user_duty_roles b JOIN duty_roles r ON r.id=b.role_id WHERE r.active=1").fetchall():
            try:
                if "finance" in (json.loads(r["permissions"] or "[]") or []):
                    granted.add(r["user_id"])
            except (TypeError, ValueError):
                pass
        subs = {r["user_id"] for r in conn.execute("SELECT user_id FROM user_perm_subtracts WHERE perm_key='finance'").fetchall()}
    except Exception:  # noqa: BLE001 — 與 helpers.auth 相同：新規則算不出來就用角色規則
        return bool(base)
    active = {r["id"] for r in rows}
    return bool(((base | granted) & active) - subs)


def _has_regular_staff(conn) -> bool:
    return conn.execute("SELECT 1 FROM users WHERE active=1 AND role!='superadmin' LIMIT 1").fetchone() is not None


def _no_finance(conn):
    if not _has_regular_staff(conn):
        return None                                  # 還沒有任何一般同仁（全新安裝）：不提醒，免得開機第一眼就一堆紅字
    if finance_holder_exists(conn):
        return None
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
        try:
            if not _has_regular_staff(conn):         # 全新安裝：只有最高管理者（或沒有人）⇒ 三項都不提醒
                return {"ok": True, "count": 0, "gaps": []}
        except Exception:  # noqa: BLE001
            logger.warning("org_gaps 判斷是否全新安裝失敗，照常檢查", exc_info=True)
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
