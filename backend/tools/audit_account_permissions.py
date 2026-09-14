"""高權限帳號（role=admin/superadmin）定期稽查工具（2026-08-28，資安優化）。

緣由：2026-08-24 全系統安全審查抓到 `claude` 自動化帳號 role=admin，但實際只需要
幾個選型資料庫 `*_guide_edit` 模組——role=admin 讓它在全系統 15+ 個「只檢查
role、不看 modules」的端點上，實際能存取稽核記錄/財務儀表板/承攬商財稅資料等
遠超預期的範圍（見 MOTRIX-ERP-QUICK.md §12「2026-08-24」條目、db.py migration 註解）。
問題根因是「role 決定要不要通過 `role in ('superadmin','admin')` 這類檢查，
modules 則是另一套獨立的細粒度授權」，兩者原本設計上該互補，但很多端點只檢查
前者，導致「role 開太高」本身就是實質風險，跟 modules 給了什麼無關。

這支工具找不出「哪些端點只檢查 role」（那需要靜態掃描程式碼，見下方 §2），
但至少能快速抓出「role 開得比 modules 用量高」這個最明顯的訊號模式，供
superadmin 定期人工複核——不是自動判定誰是自動化帳號，只是把可疑名單排到前面，
最終判斷仍需要人看。

用法：
    python audit_account_permissions.py              # 完整報告
    python audit_account_permissions.py --json        # 輸出 JSON（供其他工具串接）

§2：如果要延伸做「哪些端點只檢查 role 沒檢查 module」的靜態掃描，可以
grep routers/*.py 裡 `role not in (` / `role !=` 附近沒有 `module=` 關鍵字的
呼叫點，這次先不做，範圍留給下次真的要動這塊時再展開。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.stdout.reconfigure(encoding="utf-8")

import db  # noqa: E402

# 模組數量 <= 此值視為「範圍很窄」，role 若同時是 admin/superadmin 就特別可疑
_SPARSE_MODULE_THRESHOLD = 3

# 已知的自動化/工具帳號命名慣例（不是自動判定依據，只用來在報告中標註提醒——
# 就算不在這份清單裡，一樣可能是自動化帳號，仍要靠 module 數量訊號判斷）
_KNOWN_AUTOMATION_USERNAMES = {"claude", "automation", "bot", "api", "system"}


def _audit() -> list:
    conn = db.get_db()
    try:
        rows = conn.execute("""
            SELECT id, username, display_name, role, modules, active, created_at
            FROM users
            WHERE role IN ('superadmin', 'admin') AND active = 1
            ORDER BY role, username
        """).fetchall()
    finally:
        conn.close()

    out = []
    for r in rows:
        try:
            mods = json.loads(r["modules"] or "[]")
        except Exception:
            mods = []
        is_known_automation_name = r["username"].lower() in _KNOWN_AUTOMATION_USERNAMES
        is_sparse = len(mods) <= _SPARSE_MODULE_THRESHOLD
        out.append({
            "username":      r["username"],
            "displayName":   r["display_name"] or "",
            "role":          r["role"],
            "moduleCount":   len(mods),
            "modules":       mods,
            "createdAt":     r["created_at"] or "",
            "flagAutomationName": is_known_automation_name,
            "flagSparseModules":  is_sparse,
            # role=admin/superadmin 但 modules 幾乎沒用到——role 本身在做絕大多數
            # 授權工作，是最值得優先複核的組合
            "priority": 2 if (is_sparse and is_known_automation_name) else (1 if is_sparse else 0),
        })
    out.sort(key=lambda x: -x["priority"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="輸出 JSON 而非文字報告")
    args = ap.parse_args()

    results = _audit()

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    print("=" * 70)
    print("高權限帳號（admin/superadmin）稽查報告")
    print(f"門檻：modules <= {_SPARSE_MODULE_THRESHOLD} 個視為「範圍很窄」")
    print("=" * 70)

    if not results:
        print("目前沒有啟用中的 admin/superadmin 帳號。")
        return

    flagged = [r for r in results if r["priority"] > 0]
    if flagged:
        print(f"\n⚠️  建議優先複核（{len(flagged)} 筆）——role 權限可能高於實際需求：\n")
        for r in flagged:
            tag = "🤖 命名疑似自動化" if r["flagAutomationName"] else ""
            print(f"  [{r['role']:10s}] {r['username']:16s} {r['displayName']:12s} "
                  f"modules={r['moduleCount']:2d} {tag}")
            if r["modules"]:
                print(f"      → {', '.join(r['modules'])}")
            else:
                print("      → （完全沒有 modules，role 本身承擔全部授權）")
        print()

    others = [r for r in results if r["priority"] == 0]
    if others:
        print(f"其餘 {len(others)} 筆（modules 數量看起來與 role 相稱，未特別標註）：\n")
        for r in others:
            print(f"  [{r['role']:10s}] {r['username']:16s} {r['displayName']:12s} modules={r['moduleCount']}")

    print("\n提醒：這份報告只是找出「role 可能開太高」的訊號，不是自動判定——")
    print("人類使用者（如業務主管）modules 用量本來就可能不多，是否需要調整仍要人工判斷。")


if __name__ == "__main__":
    main()
