"""L1 案件存取守門（主持裁示 2026-09-26，DEPENDENCY-MAP §3 #2「案件可見性規則 → L1 權限」）。

原本在 M01 `helpers/quotations.py`；M01、M03 出貨、M04 外包、M05 開票／請款、M10 網路規劃都用它，
留在 M01 等於每個模組都依賴 M01。`helpers.quotations` 保留同名匯入，既有呼叫端不用改。

⚠ 已知例外（DEPENDENCY-MAP §3.2）：本檔讀 M01 的 `quotations` 表；L1 其他檔新增讀這張表會被
`tests/platform/test_case_access_l1.py` 擋下（既有的讀取列在基線、只准變少）。
M01 不在（案件表不存在）⇒ `guard_case_access` 一律 404、`case_access_allowed` 一律 False，不放行。
"""
import json
import sqlite3

from fastapi import HTTPException

from core import txn as _txn
from helpers import row_access


# ── 案件可見性：登錄到 L1 row_access（DEPENDENCY-MAP §0-5）─────────────────────
# 取代原 `_check_quotation_owner()`（單筆）與 routers/quotations.py `_visible_case_filter_sql()`
# （SQL）兩份各自實作；兩種形式現在由同一份宣告推導，等價由 tests/test_row_access_2026_09_25.py 守。
#   owner：admin+／本人業務（sales_person_id）／舊資料（id 為 NULL 比顯示名稱）／assigned_user_ids
#   read ：owner＋持 cashier 模組者（CM14b，2026-09-24 使用者裁示「讀得到，但只能改收款」）
# 🔑 這段在模組層：`helpers` 匯入即登錄（2026-09-26 起在 L1，M01 搬走時留在這裡）。
#    沒登錄時 row_access 一律 fail closed（只會少看到，不會多看到）。
CASE_ACCESS = row_access.OwnerRule(
    owner_id_col="sales_person_id",
    legacy_name_col="sales_person",
    id_list_cols=("assigned_user_ids",),
    lenient_json=False,
    read_bypass_modules=("cashier",),
    deny_message="無權限存取其他業務的報價單",
)
row_access.register("case", CASE_ACCESS)


def is_document_approver(data_json: str, user: dict, conn) -> bool:
    """這個人是否在這張單的簽核名單裡（任何一層），或本人就是送審申請人。

    含目前有效的簽核代理人——代理人在簽核路徑上處處被視同本人
    （`check_approve_permission()` 等），檢視權限沒有理由是例外。
    """
    from helpers.tiered_approval import active_tiers, active_delegators_for
    try:
        parsed = json.loads(data_json or "{}") or {}
    except Exception:
        return False
    # 兩種存法都吃：報價單／三種憑證流存成 `data_json.approval`；案件額外支出
    # 存成獨立欄位 `approval_json`（內容就是 approval 物件本身，沒有外層包裝）。
    appr = parsed.get("approval") if isinstance(parsed.get("approval"), dict) else parsed
    names = {a["username"] for tier in (active_tiers(appr) or [])
             for a in (tier.get("approvers") or []) if a.get("username")}
    if appr.get("requestedBy"):
        names.add(appr["requestedBy"])
    if user["username"] in names:
        return True
    try:
        return bool(set(active_delegators_for(conn, user["username"])) & names)
    except Exception:
        return False


def case_access_allowed(conn, q, user: dict, *, allow_approver: bool = False,
                        allow_module: str = None) -> bool:
    """單一案件列 `q`（需含 sales_person_id、sales_person、assigned_user_ids、data_json）准不准這個人動。
    規則只有這一份：row_access `case`／scope="owner"，否則 `allow_module`，否則（`allow_approver`）簽核人。
    `guard_case_access()` 與 `routers/quotations.py::_guard_case()` 都呼叫這一支（稽核 Y-5）。"""
    if row_access.visible("case", user, q, scope="owner"):
        return True
    from helpers.auth import user_has_module
    return bool((allow_module and user_has_module(user, allow_module))
                or (allow_approver and is_document_approver(q["data_json"], user, conn)))


def guard_case_access(conn, quote_no: str, user: dict, *, allow_approver: bool = False,
                      allow_module: str = None):
    """「用 quote_no 直接取單一案件」的共用守門（2026-09-13 模組權限稽核）。

    `quote_no` 可列舉（`MQ-YYYYMM-NNN`），少了這道就是 IDOR。規則是 `row_access`
    的 `case`／scope="owner"（見上方 `CASE_ACCESS`）：admin+ 直通，否則必須是該案業務或
    `assigned_user_ids` 裡的協作者。放在 helpers 而不是某支 router，是因為需要它的地方橫跨
    `quotations.py`／`case_action_items.py`／完工單／出貨單／三種憑證流／網路架構
    規劃書——2026-09-10 `_check_quotation_owner()` 從 router 搬到這裡的理由完全相同
    （當時是叫料 API 忘了加，把同一個 IDOR 又開了一次）。

    `allow_module`：案件執行面（階段、拜訪、動態、完工單／出貨單清單…）額外放行
    具該模組的人。⚠️ 這條不是偷懶——實測開發機 26 張報價單，`assigned_user_ids`
    有值的是 0 張，「指派協作者」實務上沒被使用過，純擁有者規則會讓 engineer 角色
    對全部案件的存取權變成 0。金額面（精算、應收應付）不放寬。

    `allow_approver`：簽核路徑上的人（含代理人）也放行，給單據 PDF 下載用。

    擋下來時順手把連線關掉：呼叫端清一色是「conn = get_db() → 操作 → close()」的
    直線寫法，沒有 try/finally。
    """
    try:
        q = conn.execute(
            "SELECT sales_person_id, sales_person, assigned_user_ids, data_json "
            "FROM quotations WHERE quote_no=?", (quote_no,)
        ).fetchone()
    except sqlite3.OperationalError:
        # 案件表不存在（M01 不在這個安裝裡）⇒ 與「查無此案」相同：404，一律不放行（主持裁示條件 3）
        q = None
    if not q:
        _txn.safe_close(conn)
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    if not case_access_allowed(conn, q, user, allow_approver=allow_approver, allow_module=allow_module):
        _txn.safe_close(conn)
        raise HTTPException(403, CASE_ACCESS.deny_message)
    return q
