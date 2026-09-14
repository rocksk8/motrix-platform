"""全系統一致性稽核：模組串接、備份涵蓋、安全守門、組織邏輯（2026-09-14）。

**這支跟其他測試不一樣的地方**：它不驗證任何一個功能「做得對不對」，而是驗證
**跨層的對應關係有沒有漂掉**。這類缺陷的共同特徵是「每一邊單獨看都正確、
合起來才是錯的」，所以逐功能的測試永遠照不到：

  · 後端新增一個模組權限，但使用者管理頁沒有那個勾選項 → 那個權限永遠給不出去
  · 新增一張資料表，但沒人記得加進每日 JSON 備份 → 平常沒事，要用最後手段
    還原時才發現那張表從來沒被匯出過
  · 新增一支端點忘了呼叫守門函式 → 測試全綠，因為沒有人針對「它應該要擋」寫題

專案已經有一批 `tools/check_*.py`（端點沒有前端入口、Alpine 雙 init、正式機漂移、
高權限帳號稽查），但那些是**手動執行**的工具。這支刻意做成 pytest，跟著每次
測試跑，漂掉的當下就會紅。

---

**白名單的意義**：底下幾份「已知且刻意如此」的清單不是為了讓測試變綠，而是為了
**讓下一個新增的項目變紅**。清單裡每一筆都要有理由；看到紅燈時該做的是判斷
「這個新項目應該進清單，還是應該修程式」，不是無腦加進清單。

**寫這支測試的過程本身就證明了它的必要**：初稿用寫死的守門函式名稱掃描，
誤報了 5 支 T100 財務端點（它們有自己的 `_require_t100_admin`）；接著又誤判
`financial_view` 與 `project_approve_eng` 沒有後端檢查（前者有專屬的
`_require_financial_view()`、後者寫成 `"..." in modules` 的直接成員測試）。
三次誤判都是「人掃一遍」會犯的錯，也是為什麼這件事該交給會被執行的測試。
"""
import json
import pathlib
import re

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parent.parent
_FRONTEND = _BACKEND.parent / "frontend"


# ══════════════════════════════════════════════════════════════════════
# A. 備份涵蓋度
# ══════════════════════════════════════════════════════════════════════

# archive.py::_daily_backup() 匯出成 JSON 的那幾張表。
# 這裡不是複製一份清單，而是從原始碼解析出來——貼一份的話兩邊一樣會漂掉。
def _json_backup_tables() -> set:
    src = (_BACKEND / "archive.py").read_text(encoding="utf-8")
    m = re.search(r"tables = \{(.*?)\n        \}", src, re.S)
    assert m, "archive.py 的每日備份表格清單找不到了——這支測試的解析方式要跟著改"
    return set(re.findall(r"FROM\s+(\w+)", m.group(1)))


# 刻意不進「每日 JSON 匯出」的表，以及理由。
#
# ⚠️ 先講清楚整體風險，不要看到這份清單很長就以為資料沒被備份：
# 每日備份同時會複製**整個 SQLite 檔案**（雲端一份 + 本機 db_backups 一份），
# 所以這 60 幾張表的資料是有備份的。JSON 匯出是 §8.3「還原優先序」裡的
# **最後手段**（本機整庫 → 雲端整庫 → JSON 重建），它的價值在於「人看得懂、
# 可以部分挑出來」。真正的風險是：要走到最後手段那一步時，才發現能重建的
# 只有 8 張表。
_NOT_IN_JSON_BACKUP = {
    # ── 選型資料庫（七類導覽）：內容由 sync_*.py 腳本產生，git 裡有來源 ──
    "switch_categories", "switch_products", "switch_scenarios", "switch_fit",
    "monitor_categories", "monitor_products", "monitor_scenarios", "monitor_fit",
    "access_categories", "access_products", "access_scenarios", "access_fit",
    "gateway_categories", "gateway_products", "gateway_scenarios", "gateway_fit",
    "automation_categories", "automation_products", "automation_scenarios", "automation_fit",
    "netarch_families", "netarch_generations", "netarch_products",
    "env_guide_environments", "env_guide_links", "env_guide_recommendations",
    # ── 執行期狀態／快取，重建即可，備份沒有意義 ──
    "sessions", "login_rate_limit", "edit_presence", "schema_version",
    "quote_seq", "payslip_seq", "user_request_log", "user_activity_daily",
    "user_list_prefs",
    # ── 業務資料，但目前只靠「整庫複製」那一層保護（見下方 xfail 測試）──
    "dev_cases", "dev_logs",
    "case_stages", "case_stage_visits", "case_updates", "case_extra_expenses",
    "case_change_requests", "case_action_items",
    "shipping_notes", "payment_requests", "completion_notes",
    "invoice_vouchers", "contractor_payment_vouchers", "contractor_dispatches",
    "contractors", "vendor_contractors",
    "daily_tasks", "daily_task_completions", "daily_task_edit_log",
    "work_logs", "project_logs", "project_stages",
    "network_plans", "stock_items", "stock_batches",
    "payslips", "users", "departments", "divisions",
    "approval_delegates", "webauthn_credentials",
    "system_settings", "t100_export_confirmations",
}


def _all_tables(client) -> set:
    import db
    conn = db.get_db()
    try:
        return {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()}
    finally:
        conn.close()


def test_every_table_is_either_backed_up_or_explicitly_excluded(client):
    """新增資料表時，必須明確決定它要不要進每日 JSON 匯出。

    這一題會紅，代表有人加了新表卻沒有做這個決定——不是叫你把它加進排除清單，
    是叫你想一下：這張表的資料如果要靠 JSON 重建，重建得出來嗎？
    """
    tables = _all_tables(client)
    backed = _json_backup_tables()
    undecided = tables - backed - _NOT_IN_JSON_BACKUP
    assert not undecided, (
        "這些資料表既不在每日 JSON 備份裡，也不在本測試的排除清單裡：\n  "
        + "\n  ".join(sorted(undecided))
        + "\n\n請在 archive.py::_daily_backup() 的 tables 加上它，"
          "或在本檔 _NOT_IN_JSON_BACKUP 註明不需要的理由。"
    )


def test_backup_list_has_no_stale_entries(client):
    """反向控制：備份清單裡不該有已經不存在的表。

    少了這一題，上面那題可以靠「把整個資料庫都寫進排除清單」變綠。
    """
    tables = _all_tables(client)
    backed = _json_backup_tables()
    stale = backed - tables
    assert not stale, (
        f"archive.py 每日備份指名了不存在的資料表：{sorted(stale)}"
        "——每天的備份都會為它記一筆 error。")


@pytest.mark.xfail(reason="已知落差，非本輪要修：JSON 匯出只涵蓋 8/76 張表，"
                          "其中包含 system_settings、payslips、users 等關鍵資料。"
                          "整庫複製那層有保護到，但 §8.3 的最後手段實際上重建不出系統。",
                   strict=True)
def test_business_critical_tables_are_in_json_backup(client):
    """這一題**刻意是 xfail**：把「JSON 備份涵蓋度不足」這個已知落差變成
    看得見、會被追蹤的東西，而不是散落在某份文件裡的一句話。

    strict=True 的意思是：哪天有人把這些表補進每日匯出、這題意外變綠了，
    pytest 會報 XPASS 失敗提醒你回來把這個 xfail 拿掉。落差修好了，
    標記就該消失。

    `system_settings` 特別要緊：§0 已經記載過「正式機的 webauthn_rp_id /
    webauthn_origin 不在 git 裡，還原舊 db 時這兩個值會整個消失」。
    """
    backed = _json_backup_tables()
    critical = {"users", "system_settings", "payslips", "dev_cases", "dev_logs",
                "shipping_notes", "payment_requests", "completion_notes"}
    missing = critical - backed
    assert not missing, f"關鍵業務資料表不在每日 JSON 匯出裡：{sorted(missing)}"


# ══════════════════════════════════════════════════════════════════════
# B. 安全：每一支路由都要有守門
# ══════════════════════════════════════════════════════════════════════

_ROUTE_DEC = re.compile(r'^@router\.(get|post|put|patch|delete)\(\s*["\']([^"\']+)["\']', re.M)
# 偵測**任何**守門呼叫，不寫死名稱——各 router 有自己的守門函式
# （accounting_export.py 的 _require_t100_admin、quotations.py 的
# _require_financial_view / _guard_case…），寫死名單會誤報。
# ⚠️ 反過來說，新的守門函式請沿用 `require_*` / `_require_*` / `_guard_*` 命名。
# 取成 check_admin() 這種名字不會讓測試變紅——會讓那支端點被判定成「沒有守門」
# 而變紅（假警報，你會想把它加進白名單，那才是真正的危險）。
_GUARD_CALL = re.compile(r'\b(_?require_?\w*|_guard_\w*)\s*\(')

# 刻意不需要守門的端點，以及理由。**新增第 17 支就會讓測試紅**，那正是重點。
_PUBLIC_ROUTES = {
    # 登入流程本身：還沒有身分，不可能要求身分
    ("auth.py", "POST", "/api/auth/login/totp"),
    ("auth.py", "GET", "/api/auth/login/qr-info"),
    ("auth.py", "POST", "/api/auth/login/qr-approve"),
    ("auth.py", "GET", "/api/auth/login/qr-status"),
    ("auth.py", "POST", "/api/auth/webauthn/login/begin"),
    ("auth.py", "POST", "/api/auth/webauthn/login/complete"),
    # 登出／查自己：以 token 本身為身分，函式內直接解 token
    ("auth.py", "POST", "/api/auth/logout"),
    ("auth.py", "GET", "/api/auth/me"),
    ("auth.py", "PATCH", "/api/auth/change-password"),
    # 健康檢查與版本：heartbeat_job.py 與部署面板要在沒有 session 的情況下打
    ("auth.py", "GET", "/api/ping"),
    ("auth.py", "GET", "/api/system/version"),
    ("auth.py", "GET", "/api/system/deployed-version"),
    ("system.py", "GET", "/api/system/webauthn-config-status"),
    # 伺服器時間：前端對時用，不含任何公司資料
    ("dashboard.py", "GET", "/api/now"),
    # 政府開放資料代理（統編查公司名），不觸及本系統資料
    ("dashboard.py", "GET", "/api/company/tax/{tax_id}"),
    ("dashboard.py", "GET", "/api/company/search"),
}


def _scan_routes():
    for f in sorted((_BACKEND / "routers").glob("*.py")):
        src = f.read_text(encoding="utf-8")
        marks = [(m.start(), m.group(1).upper(), m.group(2)) for m in _ROUTE_DEC.finditer(src)]
        for i, (pos, method, path) in enumerate(marks):
            end = marks[i + 1][0] if i + 1 < len(marks) else len(src)
            yield f.name, method, path, src[pos:end]


def test_every_route_has_a_guard_or_is_a_known_public_endpoint():
    """新增端點忘了呼叫守門函式，是這套系統踩過好幾次的缺陷類型
    （見 §12 2026-09-13 的「模組權限盤點：七項對接斷點」）。

    這一題不檢查「擋得對不對」——那是各功能測試的事；它只檢查
    「有沒有想過要擋」。
    """
    unguarded = [
        (fname, method, path)
        for fname, method, path, body in _scan_routes()
        if not _GUARD_CALL.search(body)
    ]
    unexpected = [r for r in unguarded if r not in _PUBLIC_ROUTES]
    assert not unexpected, (
        "這些端點沒有呼叫任何守門函式，也不在已知的公開端點清單裡：\n  "
        + "\n  ".join(f"{f}  {m} {p}" for f, m, p in unexpected)
        + "\n\n請加上 _require_user()／require_any_module()／該模組自己的守門函式，"
          "或在本檔 _PUBLIC_ROUTES 註明為什麼它可以公開。"
    )


def test_public_route_allowlist_has_no_stale_entries():
    """反向控制：白名單裡不該有已經不存在或已經補上守門的端點。

    少了這一題，白名單會一路長大、沒有人回頭清，最後變成「全部都在白名單裡」。
    """
    actual_unguarded = {
        (fname, method, path)
        for fname, method, path, body in _scan_routes()
        if not _GUARD_CALL.search(body)
    }
    stale = _PUBLIC_ROUTES - actual_unguarded
    assert not stale, (
        f"這些端點已經不需要留在公開白名單裡（已補守門或已移除）：{sorted(stale)}")


# 以「擁有者」或「資料狀態」把關、而不是以角色把關的刪除端點。
# 每一筆都逐一讀過原始碼確認過，不是為了讓測試變綠才加進來的。
_DELETE_OWNERSHIP_VERIFIED = {
    # 刪自己的 passkey：token 本身就是身分，刪得掉的一定是自己那張
    ("auth.py", "/api/auth/webauthn/credentials/{cred_id}"),
    # 釋放自己的編輯鎖（edit_presence）
    ("system.py", "/api/edit-presence"),
    # 報價單刪除走**狀態**把關而不是角色——§5.1「僅草稿可刪；其他狀態回 403」
    ("quotations.py", "/api/quotations/{quote_no}"),
}


def test_destructive_routes_check_role_or_ownership():
    """DELETE 端點必須檢查角色或擁有者，不能只有「有登入就好」。

    `_require_user(authorization)` 單獨出現代表只驗證了身分，沒有驗證權限。
    """
    weak = []
    for fname, method, path, body in _scan_routes():
        if method != "DELETE":
            continue
        if (fname, path) in _DELETE_OWNERSHIP_VERIFIED:
            continue
        has_role = re.search(r'role.{0,40}(superadmin|admin)|_is_admin|require_superadmin'
                             r'|require_any_module|_guard_|_require_(?!user\b)\w+', body)
        if not has_role:
            weak.append(f"{fname}  {method} {path}")
    assert not weak, (
        "這些刪除端點只驗證了身分、沒有驗證權限：\n  " + "\n  ".join(weak)
        + "\n\n刪除是不可逆的，至少要檢查角色、模組或資料擁有者。"
    )


# ══════════════════════════════════════════════════════════════════════
# C. 模組串接 — 刻意不在這裡重做
# ══════════════════════════════════════════════════════════════════════
#
# 這一塊已經由 `test_module_keys_consistency_2026_09_13.py` 完整覆蓋，而且比
# 這裡原本寫的更周全——除了「目錄／後端／側欄三邊的 key 要對得起來」，它還守著
# 模組檢查最危險的失敗模式：**擋錯人**（某個模組的頁面呼叫到一支不接受該模組的
# API，畫面一片 403，而後端測試全綠，因為測試多半用 admin 帳號、admin 直通）。
#
# 寫這支稽核時我一度在這裡另外寫了三題，其中一題斷言
# `_SUPERADMIN_MODULES` 應該等於 users.html 的 **allModules**，並照著去「修」了
# helpers/auth.py——結果打破了既有測試守著的真正不變量：那份樣板要等於前端的
# **superadmin 角色樣板**，不是全部可授予模組的集合。改動已還原。
#
# 記在這裡是因為這個教訓比那三題有價值：**動手改之前先確認有沒有既有測試在守
# 同一件事**，既有的那份通常比臨時想出來的斷言更清楚為什麼要這樣。

# ══════════════════════════════════════════════════════════════════════
# D. 組織邏輯
# ══════════════════════════════════════════════════════════════════════

_KNOWN_ROLES = {"superadmin", "admin", "sales", "engineer", "viewer"}


def test_no_unknown_role_strings_in_backend():
    """程式裡比對的角色字串一定要是已知角色。

    `role == 'superadmn'` 這種拼錯不會有任何錯誤訊息，只會**永遠不成立**
    ——也就是那道權限檢查靜悄悄地永遠放行或永遠擋下。
    """
    bad = {}
    pat = re.compile(r"role.{0,20}?['\"]([a-z_]{3,20})['\"]")
    for f in list((_BACKEND / "routers").glob("*.py")) + list((_BACKEND / "helpers").glob("*.py")):
        src = f.read_text(encoding="utf-8")
        for m in pat.finditer(src):
            token = m.group(1)
            # 只看真的在跟角色比對的位置，排除欄位名／訊息文字
            if token in _KNOWN_ROLES or "_" in token:
                continue
            ctx = src[max(0, m.start() - 60):m.end() + 20]
            if re.search(r"role\s*(==|!=|in\b|not in\b)", ctx):
                bad.setdefault(f.name, set()).add(token)
    assert not bad, (
        f"疑似拼錯或未知的角色字串：{ {k: sorted(v) for k, v in bad.items()} }\n"
        f"已知角色：{sorted(_KNOWN_ROLES)}")


def test_user_role_column_only_holds_known_roles(client, make_user):
    """資料庫裡實際存在的角色值也要在已知集合內。

    靜態掃描看的是程式碼，這一題看的是資料——兩者都可能單獨漂掉。
    """
    make_user(username="audit_role_probe", role="sales")
    import db
    conn = db.get_db()
    try:
        roles = {r["role"] for r in conn.execute(
            "SELECT DISTINCT role FROM users WHERE role IS NOT NULL AND role != ''").fetchall()}
    finally:
        conn.close()
    assert not (roles - _KNOWN_ROLES), (
        f"users.role 出現未知角色值：{sorted(roles - _KNOWN_ROLES)}\n"
        "——權限檢查全都是拿字串比對，資料庫裡存了不認得的值等於那個人不屬於任何角色。")


def test_department_and_division_references_are_valid(client, make_user):
    """組織階層的外鍵完整性：使用者掛的部門／處必須存在。

    §7 的部門篩選（dashboard、stage-board 的 department_id）是拿
    users.department_id 去比對的——指向不存在的部門會讓那個人從所有
    部門篩選中默默消失，而不是報錯。
    """
    make_user(username="audit_org_probe", role="sales")
    import db
    conn = db.get_db()
    try:
        dept_ids = {r["id"] for r in conn.execute("SELECT id FROM departments").fetchall()}
        div_ids = {r["id"] for r in conn.execute("SELECT id FROM divisions").fetchall()}
        user_ids = {r["id"] for r in conn.execute("SELECT id FROM users").fetchall()}
        users = conn.execute("SELECT username, department_id FROM users").fetchall()
        depts = conn.execute(
            "SELECT id, name, division_id, manager_user_id FROM departments").fetchall()
    finally:
        conn.close()

    # users **沒有** division_id 欄位——處是透過 departments.division_id 連的，
    # 所以組織是 users → departments → divisions 兩段，兩段都要驗，
    # 外加部門主管指向的使用者也要存在（主管簽核會去找那個人）。
    orphans = [
        f"使用者 {r['username']} → 不存在的部門 id={r['department_id']}"
        for r in users if r["department_id"] and r["department_id"] not in dept_ids
    ] + [
        f"部門 {r['name']}(id={r['id']}) → 不存在的處 id={r['division_id']}"
        for r in depts if r["division_id"] and r["division_id"] not in div_ids
    ] + [
        f"部門 {r['name']}(id={r['id']}) 的主管指向不存在的使用者 id={r['manager_user_id']}"
        for r in depts if r["manager_user_id"] and r["manager_user_id"] not in user_ids
    ]
    assert not orphans, (
        "組織階層有指向不存在對象的參照：\n  " + "\n  ".join(orphans)
        + "\n——部門篩選會讓這些人默默消失、主管簽核會找不到人，而不是報錯。")
