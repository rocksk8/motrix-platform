"""共用的 tiers 依序簽核純邏輯（2026-08-22）。

報價單／出貨單／承攬商匯款申請／開票申請憑據四個 router 原本各自複製一份
幾乎逐字相同的版本——這裡只抽出「沒有副作用、判斷用」的部分集中維護，
真正的 side effect（DB 寫入、通知、PDF 產生、庫存扣減、行事曆推送等）仍留在
各自 router 裡，這個模組不碰 FastAPI（不拋 HTTPException），呼叫端自己決定
要怎麼包裝錯誤訊息。

這次抽出的直接理由：架構檢查時發現 shipping_notes.py 沒套用到稍早在
contractor_vouchers.py／invoice_vouchers.py 修好的兩個簽核漏洞（見
MOTRIX-ERP-QUICK.md 2026-08-22 changelog）——邏輯重複四份、改一個地方
其餘三個要記得改，這次就是真的漏掉一個地方，證實了共用的必要性。

⚠️ 未來開發保留：目前 tiers 完全是「逐一手動挑選簽核人員」，尚未整合
`routers/org_structure.py` 的處/部門組織架構。`divisions.manager_user_id`／
`departments.manager_user_id` 已經是刻意為此保留的欄位（2026-08-22/
2026-08-22e），未來若要支援「依部門/處自動列入主管簽核」，應該在這個模組
新增對應的純函式（例如把某部門主管展開成一個 tier 的 approver），維持
「這裡不碰 FastAPI、不做 side effect」的既有分工，不要把組織架構查詢邏輯
直接寫進四個 router 裡。
"""
from typing import Optional


def active_tiers(appr: dict) -> list:
    return appr.get("tiers") or []


def current_tier_idx(appr: dict) -> int:
    return appr.get("currentTier") or 0


class UnresolvedManagerError(Exception):
    """部門主管自動簽核層在送審當下無法解析（部門不存在／未設主管／主管已停用）。
    呼叫端（各 router 的送審端點）自己 catch 並包成 HTTPException(400, str(e))，
    這個模組維持不碰 FastAPI 的既有分工。"""


def resolve_department_manager(conn, department_id: int) -> Optional[dict]:
    """查某部門目前的主管，回傳 {userId, username, displayName} 或 None
    （部門不存在／未設主管／主管帳號已停用時皆回傳 None，呼叫端自行決定
    要不要當錯誤處理——這裡本身不拋例外）。"""
    row = conn.execute("""
        SELECT u.id, u.username, u.display_name
        FROM departments d
        JOIN users u ON u.id = d.manager_user_id
        WHERE d.id=? AND u.active=1
    """, (department_id,)).fetchone()
    if not row:
        return None
    return {"userId": row["id"], "username": row["username"], "displayName": row["display_name"] or row["username"]}


def resolve_division_manager(conn, division_id: int) -> Optional[dict]:
    """查某處目前的主管，回傳 {userId, username, displayName} 或 None
    （處不存在／未設主管／主管帳號已停用時皆回傳 None）。跟
    resolve_department_manager() 對稱，2026-08-22h 新增。"""
    row = conn.execute("""
        SELECT u.id, u.username, u.display_name
        FROM divisions v
        JOIN users u ON u.id = v.manager_user_id
        WHERE v.id=? AND u.active=1
    """, (division_id,)).fetchone()
    if not row:
        return None
    return {"userId": row["id"], "username": row["username"], "displayName": row["display_name"] or row["username"]}


def resolve_submitter_manager_chain(conn, requester_username: str) -> dict:
    """申請人部門主管自動簽核鏈（2026-08-22i）：先查申請人自己的部門主管；
    若主管就是申請人自己（申請人身兼部門主管），改查該部門所屬處的主管；
    若處主管也是申請人自己（申請人身兼處主管），改查其他在職的超級管理員
    （逃生條款，比照 check_no_tier_self_approval 的既有寫法，避免永久卡死）。
    任一步驟解析不出來就 raise UnresolvedManagerError，訊息說明具體原因。"""
    req = conn.execute(
        "SELECT id, username, department_id FROM users WHERE username=? AND active=1",
        (requester_username,)
    ).fetchone()
    if not req or not req["department_id"]:
        raise UnresolvedManagerError("申請人尚未歸屬任何部門，請聯絡管理員設定部門後才能送審")

    dept = conn.execute("SELECT id, name, division_id FROM departments WHERE id=?", (req["department_id"],)).fetchone()
    if not dept:
        raise UnresolvedManagerError("申請人所屬部門已不存在，請聯絡管理員確認組織架構設定")

    mgr = resolve_department_manager(conn, dept["id"])
    if not mgr:
        raise UnresolvedManagerError(f"「{dept['name']}」尚未指定主管（或主管帳號已停用），請聯絡管理員先設定部門主管")
    if mgr["username"] != requester_username:
        return mgr

    # 申請人自己就是部門主管 → 改由處主管簽核
    div_mgr = resolve_division_manager(conn, dept["division_id"]) if dept["division_id"] else None
    if not div_mgr:
        raise UnresolvedManagerError(f"申請人是「{dept['name']}」主管，需改由處主管簽核，但該處尚未指定主管（或主管帳號已停用）")
    if div_mgr["username"] != requester_username:
        return div_mgr

    # 申請人自己就是處主管 → 改由其他在職超級管理員簽核
    other_admin = conn.execute(
        "SELECT id, username, display_name FROM users WHERE role='superadmin' AND active=1 AND username!=? LIMIT 1",
        (requester_username,)
    ).fetchone()
    if not other_admin:
        raise UnresolvedManagerError("申請人是處主管，需改由超級管理員簽核，但找不到其他在職的超級管理員")
    return {"userId": other_admin["id"], "username": other_admin["username"],
            "displayName": other_admin["display_name"] or other_admin["username"]}


def resolve_tier_approvers(conn, tier_setting: dict, requester_username: str = None) -> list:
    """展開一個 tier 設定的 approvers。同一層可以放多筆（依陣列順序輪流簽，
    跟多層簽核同一套規則，可混合手動挑人／部門主管／處主管／申請人部門主管
    動態帶入，也可以跨部門）。手動挑人的項目（沒有 sourceType）沿用既有邏輯；
    sourceType=='department_manager'/'division_manager' 的項目在送審當下即時
    查詢該部門/處目前的主管；'submitter_manager' 則走動態鏈解析——查不到
    （單位被刪、沒設主管、主管已停用）就 raise UnresolvedManagerError，讓呼叫端
    擋下送審並提示管理員先設定主管，而不是靜默跳過整層（那樣會讓一道簽核關卡
    無聲消失）。"""
    resolved = []
    for a in (tier_setting.get("approvers") or []):
        source = a.get("sourceType")
        if source == "submitter_manager":
            mgr = resolve_submitter_manager_chain(conn, requester_username)
            resolved.append({**mgr, "status": "pending", "approvedAt": None})
        elif source == "department_manager":
            dept_id = a.get("departmentId")
            dept_row = conn.execute("SELECT name FROM departments WHERE id=?", (dept_id,)).fetchone()
            dept_name = dept_row["name"] if dept_row else f"#{dept_id}"
            mgr = resolve_department_manager(conn, dept_id) if dept_row else None
            if not mgr:
                raise UnresolvedManagerError(
                    f"此層設定為「{dept_name}」主管自動簽核，但目前該部門未指定主管"
                    f"（或主管帳號已停用），請聯絡管理員先設定部門主管"
                )
            # 申請人剛好就是這個部門的主管時跳過，不加入這層——比照
            # _exclude_requester()／submitter_manager 鏈的既有原則：申請人不得
            # 需要簽核自己的申請（2026-08-24 安全審查修正）。該層若因此變空，
            # setting_to_active_tiers() 的空層過濾會自然跳過整層。
            if mgr["username"] != requester_username:
                resolved.append({**mgr, "status": "pending", "approvedAt": None})
        elif source == "division_manager":
            div_id = a.get("divisionId")
            div_row = conn.execute("SELECT name FROM divisions WHERE id=?", (div_id,)).fetchone()
            div_name = div_row["name"] if div_row else f"#{div_id}"
            mgr = resolve_division_manager(conn, div_id) if div_row else None
            if not mgr:
                raise UnresolvedManagerError(
                    f"此層設定為「{div_name}」處主管自動簽核，但目前該處未指定主管"
                    f"（或主管帳號已停用），請聯絡管理員先設定處主管"
                )
            if mgr["username"] != requester_username:
                resolved.append({**mgr, "status": "pending", "approvedAt": None})
        else:
            resolved.append({
                "userId":      a.get("userId"),
                "username":    a["username"],
                "displayName": a.get("displayName", a["username"]),
                "status":      "pending",
                "approvedAt":  None,
            })
    return resolved


def setting_to_active_tiers(setting: dict, conn, requester_username: str = None) -> list:
    """system_settings 裡存的簽核流程設定（tiers: [{order, approvers:[...]}]，
    每個 approver 是手動挑選的使用者或 sourceType='department_manager'／
    'division_manager'／'submitter_manager' 的自動簽核項目）轉成送審當下要
    寫進 approval.tiers 的「執行期」格式。跳過展開後沒有簽核人的層，避免卡在
    一個永遠不會有人簽的空層——但主管解析失敗會直接 raise UnresolvedManagerError
    （不會走到「跳過」這條路），因為那代表設定本身有問題，應該擋下送審而不是
    悄悄少一層。

    「申請人部門主管自動簽核」（2026-08-22i）是系統內建、預設一律套用的第一層——
    setting.get("includeSubmitterManagerTier", True) 沒有這個 key 時視為 True，
    管理員要在簽核設定頁明確關掉才會存 False，符合「內建但可移除」的需求。

    ⚠️ 2026-08-28 修正：先前的過濾條件檢查的是「設定裡這層有沒有 approver 項目」
    （恆真——department_manager/division_manager 項目本身一定有 1 筆），而不是
    「展開後這層實際解析出幾位簽核人」。當管理員手動指定的部門/處主管層，剛好
    解析到的主管就是申請人自己時，resolve_tier_approvers() 會把該筆靜默排除
    （避免自簽），但這層仍會以「approvers: []」的空層之姿留在回傳結果裡——
    check_approve_permission() 對空層永遠回傳「無待簽核人員」，任何人（含
    superadmin）都無法通過，等同卡死。改成依「展開後」的結果過濾，讓這層照
    docstring 原意直接跳過，並重新編號 order 讓陣列保持連續。"""
    tiers = list(setting.get("tiers") or [])
    if setting.get("includeSubmitterManagerTier", True):
        tiers = [{"approvers": [{"sourceType": "submitter_manager"}]}] + tiers
    result = []
    for t in tiers:
        if not (t.get("approvers") or []):
            continue
        resolved = resolve_tier_approvers(conn, t, requester_username)
        if resolved:
            result.append({"order": len(result), "approvers": resolved})
    return result


def first_pending_approver(tier: dict) -> Optional[dict]:
    return next((a for a in (tier.get("approvers") or []) if a.get("status") != "approved"), None)


def check_approve_permission(tiers: list, ct_idx: int, username: str):
    """approve 用的嚴格版：必須是當層「排序最前面的未簽核人」才能動作。
    回傳 (ok, status_code, error_message)：ok=True 時後兩者為 None；ok=False 時
    呼叫端直接拿 status_code/error_message 去包 HTTPException(status_code, error_message) 即可
    （狀態碼跟訊息逐一比照四個 router 原本各自的寫法，不引入新的行為差異）。"""
    if ct_idx >= len(tiers):
        return False, 400, "所有層已完成"
    tier = tiers[ct_idx]
    approvers = tier.get("approvers") or []
    is_in_tier = any(a["username"] == username for a in approvers)
    if not is_in_tier:
        pending_names = "、".join(
            a.get("displayName") or a["username"] for a in approvers if a.get("status") != "approved"
        ) or "（無待簽核人員）"
        return False, 403, f"此層需由以下人員簽核：{pending_names}"
    fp = first_pending_approver(tier)
    if not fp:
        return False, 400, "此層所有簽核人員已完成"
    if fp["username"] != username:
        next_name = fp.get("displayName") or fp["username"]
        return False, 403, f"請等待 {next_name} 先完成簽核（簽核順序固定）"
    return True, None, None


def check_reject_permission(tiers: list, ct_idx: int, user: dict):
    """reject 用的寬鬆版：當層任一簽核人或 superadmin 皆可退回（不要求排序，
    退回不像核准需要嚴格依序，任何一個當層相關人員發現問題都該能先擋下來）。
    回傳 (ok, status_code, error_message)，同上約定。"""
    if tiers:
        tier = tiers[ct_idx] if ct_idx < len(tiers) else {}
        approvers = tier.get("approvers") or []
        is_in_tier = any(a["username"] == user["username"] for a in approvers)
        if not is_in_tier and user["role"] != "superadmin":
            return False, 403, "無退回權限（非當層簽核人員）"
        return True, None, None
    if user["role"] != "superadmin":
        return False, 403, "僅超級管理員可執行此操作"
    return True, None, None


def check_no_tier_self_approval(conn, appr: dict, user: dict) -> Optional[str]:
    """無簽核層設定（superadmin fallback）情境下，檢查申請人是否想自行審核
    自己的申請。回傳 None 表示可以放行；回傳字串表示應該擋下（訊息內容即為
    錯誤訊息）。逃生條款：申請人是目前唯一在職的最高管理者時允許自簽，
    否則會永久卡死無人可簽。"""
    if appr.get("requestedBy") != user["username"]:
        return None
    other_admin = conn.execute(
        "SELECT 1 FROM users WHERE role='superadmin' AND active=1 AND username!=? LIMIT 1",
        (user["username"],),
    ).fetchone()
    if other_admin:
        return "申請人不得自行審核，請由其他最高管理者審核"
    return None
