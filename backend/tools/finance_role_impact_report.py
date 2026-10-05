"""第42班「財務角色」上線前後影響報表（唯讀；只做 SELECT，不寫任何資料）。

使用者 2026-10-05 裁示：財務／出納能力只屬於「財務」角色與 superadmin；admin 直通與 sales 的財務金額直通拿掉；
既有帳號 `users.modules` 裡的 cashier／finance／financial_view 勾選保留在資料庫、但程式不再認（惰性，回滾即還原）。

這支列出**上線當下會失去財務／出納能力的帳號**（給正式機視窗上線前後讓使用者看），並檢查有沒有人接手：
- 會失去的：非 superadmin、非 finance 的在職帳號，且（角色是 admin／sales〔原本的角色直通〕，或 modules 持有 cashier／finance／financial_view）
- 保有的：superadmin（不變式：全功能）與 finance 角色
- ⚠️ 沒有任何在職「財務」角色帳號 ⇒ 警告（上線後只有 superadmin 能處理財務／出納）；沒有在職 superadmin ⇒ 錯誤

用法（在 backend 目錄）：
    python tools/finance_role_impact_report.py            # 文字報告
    python tools/finance_role_impact_report.py --json     # JSON
結束碼：0 正常；1 有警告（沒有財務角色帳號）；2 錯誤（沒有 superadmin）。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

FINANCE_KEYS = ("cashier", "finance", "financial_view")
#: 舊規則下「靠角色直通」就有財務能力的角色（與 helpers/auth.py 舊 can_see_financial／各處 role in (...) 對應）
LEGACY_PASSTHROUGH_ROLES = ("admin", "sales")


def _mods(raw):
    try:
        v = json.loads(raw or "[]")
        return v if isinstance(v, list) else []
    except Exception:
        return []


def build_report(conn) -> dict:
    rows = conn.execute(
        "SELECT id, username, display_name, role, modules, email FROM users WHERE active = 1 ORDER BY role, username"
    ).fetchall()
    lose, keep_super, keep_finance = [], [], []
    for r in rows:
        mods = _mods(r["modules"])
        flags = [k for k in FINANCE_KEYS if k in mods]
        item = {"username": r["username"], "displayName": r["display_name"] or "", "role": r["role"],
                "heldFlags": flags, "legacyRolePassthrough": r["role"] in LEGACY_PASSTHROUGH_ROLES,
                "hasEmail": bool((r["email"] or "").strip())}
        if r["role"] == "superadmin":
            keep_super.append(item)
        elif r["role"] == "finance":
            keep_finance.append(item)
        elif flags or r["role"] in LEGACY_PASSTHROUGH_ROLES:
            reasons = []
            if r["role"] in LEGACY_PASSTHROUGH_ROLES:
                reasons.append("角色直通（%s）" % r["role"])
            if flags:
                reasons.append("勾選 " + "／".join(flags))
            item["loses"] = reasons
            lose.append(item)
    problems = []
    if not keep_super:
        problems.append({"level": "error", "message": "沒有任何在職 superadmin 帳號"})
    if not keep_finance:
        problems.append({"level": "warn", "message": "尚無在職「財務」角色帳號：上線後只有 superadmin 能處理財務／出納；"
                                                     "請先到使用者管理把負責人的角色改為「財務」"})
    elif not any(i["hasEmail"] for i in keep_finance + keep_super):
        problems.append({"level": "warn", "message": "財務角色與 superadmin 都沒有設定 Email：付款／匯款通知會寄不出去"})
    return {"loseAccess": lose, "keepSuperadmin": keep_super, "keepFinance": keep_finance, "problems": problems}


def exit_code(rep: dict) -> int:
    if any(p["level"] == "error" for p in rep["problems"]):
        return 2
    return 1 if rep["problems"] else 0


def format_text(rep: dict) -> str:
    out = ["# 財務角色上線影響報表（唯讀）", ""]
    out.append("## 會失去財務／出納能力的帳號（%d）" % len(rep["loseAccess"]))
    for i in rep["loseAccess"]:
        out.append("- %s（%s，%s）：%s" % (i["username"], i["displayName"] or "—", i["role"], "；".join(i["loses"])))
    if not rep["loseAccess"]:
        out.append("（無）")
    out += ["", "## 保有（superadmin，不變式：全功能）（%d）" % len(rep["keepSuperadmin"])]
    out += ["- %s（%s）" % (i["username"], i["displayName"] or "—") for i in rep["keepSuperadmin"]] or ["（無）"]
    out += ["", "## 保有（財務角色）（%d）" % len(rep["keepFinance"])]
    out += ["- %s（%s）" % (i["username"], i["displayName"] or "—") for i in rep["keepFinance"]] or ["（無）"]
    out += ["", "## 檢查"]
    out += ["- [%s] %s" % (p["level"].upper(), p["message"]) for p in rep["problems"]] or ["- OK：有人接手"]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    import db
    conn = db.get_db()
    try:
        rep = build_report(conn)
    finally:
        conn.close()
    print(json.dumps(rep, ensure_ascii=False, indent=2) if args.json else format_text(rep))
    sys.exit(exit_code(rep))


if __name__ == "__main__":
    main()
