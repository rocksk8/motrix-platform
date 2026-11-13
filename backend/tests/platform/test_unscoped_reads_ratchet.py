# -*- coding: utf-8 -*-
"""未經範圍讀取的 AST 棘輪（§14.10 #6）：目前的未經範圍讀取集合必須是基準的子集（只減不增）。

掃描器見 `_unscoped_reads.py`。新增讀取請改走 `filter_sql`／核准 helper；確實要登記才動基準檔，且總數上限 `MAX_ENTRIES` 只准手動調小。
已知假陰性（文件化，不是漏掉）：
  ①核准 helper 以『函式』為粒度——同函式內有一句走 helper，其餘讀取都視為已處理；
  ②完全由其他函式回傳的 SQL（`conn.execute(build())`）看不到文字，只在 `execute(<變數>)` 且變數非本函式／模組組裝時記為 dynamic；
  ③字串存在 dict／list／class 屬性後再取用的 SQL，只在被當作運算式出現的地方被掃到；
  ④不含 SELECT 的寫入（UPDATE／DELETE）不屬於本棘輪（輸入側見 test_u0a_sinks）；
  ⑤migrations 目錄與 core/migrations.py 不掃。
"""
from tests.platform import _unscoped_reads as U

#: 基準總筆數上限：只准手動調小（基準縮小後把這個數字一起降下來）
# 873 = 871 + 2（LINE 事件矩陣 2026-11-13：`routers/system.py::_audit_mark`／`_line_conflict_who` 只對最高管理者的 LINE 設定頁讀 `audit_log`：前者回最新一筆的編號（只有 id）、後者只在儲存衝突時找「誰在何時改了這些事件」（只回顯示名與時間，不回稽核列；僅 `settings.line_notify%` 動作）；audit_log 沒有逐列範圍可套）。PM 2026-11-13 核准：新功能必要（「復原這一批」要顯示衝突是誰造成的）、限最高管理者頁；整合時照規矩把各分支的增減相加
# 865 = 864 + 1（授權匯入 T83 2026-11-13：`license_manager.recent_activity` 讀 `audit_log` 最近幾筆 `license.import`／`license.import_rejected`——只回時間、操作者顯示名稱與白話結果（不含授權內容），端點只限最高管理者（GET /api/license/overview）；不得接其他使用者端點）
# 864 = 861 + 3（fix/excel-import-dataloss 2026-11-13：Excel 匯入的比對讀客戶／料號主檔——與同檔 list_customers／get_customer 同為全公司共用主檔、權限由模組檢查，沒有單位欄位可範圍化）
# 870 = 868 + 2（T83 整合 2026-11-13：備份與監控頁 `helpers/backup_monitor._audit_latest_map`／`_alerts_block` 讀 `audit_log` 的備份事件（`backup.*` 動作的最後時間、最近 N 筆警示）——只回時間與（過濾過路徑的）事件文字、不回個人資料，端點限最高管理者；audit_log 不是案件範圍資料，沒有 row_access 可套。feat/backup-monitor-page 分支當初漏登記）
# 880 = 879 + 1（S1d 設定變更通知 2026-11-13，PM 核准 +1：`settings_registry._notice_watermark` 只在 sqlite_sequence 查不到 notifications 的 seq 列這個罕見分支回退讀 `MAX(id)`——通知水位線、只讀 id、無業務資料；取不到回 None＝跳過去重）
# 874 = 873 + 1（T84 feat/upload-files-txn-2 2026-11-13：每日維護 `quotations.sweep_stale_staging` 讀 `case_change_requests` 找逾時的 staging 預留列——系統排程、沒有使用者；只讀 id、不回傳給任何人，只把這幾列標成 cancelled 並清掉它們的暫存檔）
MAX_ENTRIES = 881      # 879 + 1；上一行之前：856 + 5（T80c 外勤 S2 K審修 2026-11-12：列表 `list_field_cases` 改成「案件成員」口徑（CM14：業務／協作者／角色／階段負責人），SQL 只做 instr 粗篩（超集）、
                        # 最後在 Python 逐筆用 `_is_member` 判定（與單件同一支）——所以 quotations／case_stages／case_updates 的讀取不再走 row_access.filter_sql（它不認 roles／階段負責人，會讓現場工程師列表恆空）；
                        # 另 `_coarse_member_sql`／`_stage_assigned` 各讀 case_stages。每一筆回傳前都被 `_is_member` 擋過、只回白名單欄位（無金額）；測試 test_membership_equals_the_existing_case_member_rule_for_every_path 釘住與 `_is_case_member` 同義）
                        # 856 = 853 + 3（T80c 外勤 S2 2026-11-12：新端點 `GET /api/field/cases/{quote_no}` 的 `get_field_case` 讀 quotations／case_stages／case_updates 各一——一律先過 `_is_member`（案件成員，CM14；不再是 `_guard_case`＋`case_manage` 放行，見上一段 861 的說明）、只回白名單欄位（無金額），與 `GET /api/quotations/{no}/stages`、`/updates` 同型；（當時列表走 row_access.filter_sql 不新增；後來列表也改成員口徑，見上一段 +5））
                        # 853 = 852 + 1（T80c 外勤 S1 2026-11-12：新端點 `POST /api/quotations/{quote_no}/updates/{uid}/files` 補附件——`_add_case_update_files_impl` 讀 `case_updates` 那一列（作者比對＋拿鎖重讀追加），
                        # 之前一律已過 `_guard_case`（案件範圍）且只碰 URL 指名的那一則留言；與同檔 delete_case_update_file 同型。另兩筆是既有端點抽出 `_impl` 的改名，不增減）
                        # 852 = 851 + 1（簽核二擇一 S6 2026-11-07：content_fp.shadow_stats 唯讀聚合 `audit_log` 的 `quotation.reconfirm_shadow` 列，只供超管端點 `GET /api/quotations/reconfirm-shadow-stats`；
                        # audit_log 不是案件範圍資料（沒有 row_access 可套），回傳的是計數不是列；端點本身限 superadmin；不得接其他使用者端點）
                        # 851 = 850 + 1（簽核二擇一 S3b 2026-11-06：content_fp.reconcile_txn 在 reconfirm_mode≠off 時多讀一次 `SELECT status FROM quotations`（K 審 Q1 選項 A，漏斗不知道單據真實狀態）；
                        # 另 helpers/audit 的 `_notify` 抽出 `_notify_in_txn`，通知表的 NOT EXISTS 讀取跟著搬過去，不增減）
                        # 850 = 849 + 1（簽核二擇一 S1 2026-11-06：content_fp.rebaseline_fingerprint 以呼叫端明確給的單號讀 quotations，
                        # 供會碰簽核中單的開機遷移重設指紋基準；不是使用者請求路徑、不回傳資料給使用者，沒有 row_access 可套。K 審已通過，條件：**不得接使用者端點**（modules/case/tests/test_content_fp_s1_2026_11_06.py 有守門題）、保留可呼叫證明題與 S0 MIGRATION_ONCE 備註）
                        # 849 = 847 + 2（業務開發進度重設計 2026-11-04：舊 update_dev_case_progress 移除 −1，新增 add_dev_case_progress／_progress_extras／_check_dev_case_reply_overdue +3；
                        # 前者比對 user["id"]==assigned_to（不是 row_access 範圍查詢），_progress_extras 只對呼叫端已過 row_access 的案件列補進度，每日排程與 _check_dev_case_stale 同為系統身分）；
                        # 847 = 845 + 2（T73：assign_dev_case／update_dev_case_progress 讀 dev_cases 後自己在 Python 層判權限
                        # ——/assign 限管理員、/progress 比對 user["id"]==assigned_to，不是 row_access 範圍查詢；
                        # 兩輪獨立稽核都已確認這個判權限方式，見 AUDIT-hichan3-t73.md／AUDIT-pm-sub-t73.md 的驗收列）
                        # （併入）861 + 2（UX P1.5 2026-11-13：`helpers/login_greeting._last_audit_login` 以呼叫端的 user_id 讀自己最後一次 `auth.login`（舊帳號回填，只回時間、不回列）；
                        # `modules/case/api/dashboard_groups.new_quotes_since` 只回 COUNT(*)（登入問候語「離開期間新增 N 張報價單」，呼叫端只對最高管理者呼叫，IP-GR1，L1 不直接讀 quotations）。皆無 row_access 可套、不回傳資料列）
                        # 861 = 856 + 5（T80c 外勤 S2 K審修 2026-11-12：列表 `list_field_cases` 改成「案件成員」口徑（CM14：業務／協作者／角色／階段負責人），SQL 只做 instr 粗篩（超集）、
                        # （併入）861 + 1（估價單 2026-11-13：`modules/case/quotations.py::_estimate_prefixes` 只回「曾開過估價單的單號字首」的 DISTINCT 聚合（不含任何案件內容、不回列），
                        # 經串接點 IP-ESTQ1 給 L1 `helpers/doc_type`；沒有逐案範圍可套，也不接使用者端點）
                        # （併入）861 + 2（「開始使用」清單 2026-11-13：`getting_started._d_import` 數 `customers` 筆數、`_latest_audit_at` 讀 `audit_log` 最近一列的時間——
                        # 兩者都只回計數／時間字串、不回任何一筆資料，端點只限最高管理者（GET /api/getting-started）；不得接其他使用者端點）
                        # （併入）861 + 1（「開始使用」清單 2026-11-13：`getting_started._d_import` 數 `customers` 筆數——只回計數、不回任何一筆資料，端點只限最高管理者（GET /api/getting-started）；不得接其他使用者端點）
                        # （併入）861 + 4（一條龍 P0a／P0c／P1' 2026-11-13：①`email_notify.shipping_link` 與 `inventory._StockSerials.release` 各讀 `shipping_notes` 一次，只用單號查「存在／仍是已核准」（`release` 是案件存檔交易內、舊資料維持 in_stock 的判斷；`shipping_link` 是通知連結的查案號），不回傳資料給使用者；②`case/material_flow._purchase` 讀 `case_extra_expenses`，**端點先過 `require_case`（案件成員）**且只取單據代號／狀態／日期、沒有金額；③`supply/case_summary` 讀 `stock_items` 彙總該案台數，案件可見性由案件側先檢查、呼叫者另要有檢視庫存的模組權限。測試 modules/case/tests/test_onepipe_p1_timeline_2026_11_13.py）
                        # （併入）868 + 2；上一行之前：856 + 5（T80c 外勤 S2 K審修 2026-11-12：列表 `list_field_cases` 改成「案件成員」口徑（CM14：業務／協作者／角色／階段負責人），SQL 只做 instr 粗篩（超集）、
                        # （併入）872 + 1（txn-4 `_sweep_decided_staging_dirs` 讀 case_change_requests.status：每日維護清掃，系統排程、無使用者、只讀 status 判斷已決定與否、不回傳，比照 txn-2 的 sweep_stale_staging；h7 整合時提出）；上一行之前：868 + 2；再之前：856 + 5（T80c 外勤 S2 K審修 2026-11-12：列表 `list_field_cases` 改成「案件成員」口徑（CM14：業務／協作者／角色／階段負責人），SQL 只做 instr 粗篩（超集）、
                        # （併入）875 + 1（一條龍 P0d 2026-11-13：`modules/case/case_deadlines._closed_warranty_rows` 讀 `quotations`（已結案、有設備保固資料的案件），供保固到期通知排程使用——排程沒有登入者，與同檔 `_check_warranty_expiry` 讀同一張表同型（已登記）；只產生通知（案號／客戶名／到期日），不回傳給使用者；旗標 onepipe.warranty_closed_notify。測試 modules/case/tests 的 test_onepipe_warranty_closed_2026_11_13.py）
                        # 875 = 861 + 4（一條龍 P0a／P0c／P1' 2026-11-13：①`email_notify.shipping_link` 與 `inventory._StockSerials.release` 各讀 `shipping_notes` 一次，只用單號查「存在／仍是已核准」（`release` 是案件存檔交易內、舊資料維持 in_stock 的判斷；`shipping_link` 是通知連結的查案號），不回傳資料給使用者；②`case/material_flow._purchase` 讀 `case_extra_expenses`，**端點先過 `require_case`（案件成員）**且只取單據代號／狀態／日期、沒有金額；③`supply/case_summary` 讀 `stock_items` 彙總該案台數，案件可見性由案件側先檢查、呼叫者另要有檢視庫存的模組權限。測試 modules/case/tests/test_onepipe_p1_timeline_2026_11_13.py）
#: 掃描器自己的下限：掃到的筆數太少 ⇒ 掃描壞了（假綠）
SCAN_FLOOR = 100


def test_current_unscoped_reads_are_subset_of_baseline():
    cur, base = U.scan_all(), U.load_baseline()
    assert len(cur) >= SCAN_FLOOR, "掃描器只掃到 %d 筆：疑似壞掉" % len(cur)
    new = {k: v for k, v in cur.items() if k not in base}
    assert new == {}, "新增未經範圍的讀取（請改走 filter_sql／核准 helper，或有理由才登記基準）：\n" + "\n".join("  %s  [%s]" % kv for kv in sorted(new.items()))
    changed = {k: (base[k], v) for k, v in cur.items() if k in base and base[k] != v}
    assert changed == {}, "類別改變：%s" % changed
    assert len(base) <= MAX_ENTRIES, "基準 %d 筆超過上限 %d" % (len(base), MAX_ENTRIES)


def test_baseline_file_is_sorted_one_entry_per_line_and_known_categories():
    raw = U.BASELINE_PATH.read_text(encoding="utf-8")
    base = U.load_baseline()
    assert raw == U.dump(base), "基準檔格式不是 dump() 的輸出（需排序、一筆一行）"
    assert set(base.values()) <= {"unscoped", "dynamic"}


def test_baseline_ids_have_no_line_numbers_and_tables_exist():
    for k, v in U.load_baseline().items():
        f, fn, tail = k.split("::")[0], "::".join(k.split("::")[1:-1]), k.split("::")[-1]
        assert f.endswith(".py") and fn, k
        if v == "unscoped":
            assert tail in U.UNIT_TABLES, k
        else:
            assert tail.startswith("<") and tail.endswith(">"), k


# ── 正對照：掃描器本身不能假綠 ───────────────────────────────────────────────────────────
def _scan(src):
    return U.scan_source("x.py", src)


def test_control_unscoped_read_is_flagged():
    got = _scan('def f(conn):\n    return conn.execute("SELECT * FROM quotations WHERE id=?", (1,)).fetchall()\n')
    assert got == {"x.py::f::quotations": "unscoped"}


def test_control_all_string_shapes_flagged():
    for body in ('conn.execute(f"SELECT * FROM quotations WHERE {w}")',
                 'conn.execute("SELECT * FROM quotations WHERE " + w)',
                 'conn.execute("SELECT * FROM quotations WHERE %s" % w)',
                 'conn.execute("SELECT * FROM quotations WHERE {}".format(w))',
                 'q = "SELECT a FROM customers c JOIN quotations q ON 1"\n    conn.execute(q)',
                 'conn.execute("SELECT a FROM suppliers, quotations")'):
        got = _scan("def f(conn, w):\n    " + body + "\n")
        assert "x.py::f::quotations" in got, body


def test_control_scoped_read_stays_green():
    for helper in ("filter_sql('case', user)", "row_access.filter_sql('case', user)", "guard_case_access(conn, q, user)"):
        src = "def f(conn, user, q):\n    frag, a = %s\n    return conn.execute('SELECT * FROM quotations WHERE 1' + frag, a)\n" % helper
        assert _scan(src) == {}, helper
    # 外層函式走 helper ⇒ 內層也算
    assert _scan("def f(conn, user):\n    filter_sql('case', user)\n    def g():\n        conn.execute('SELECT * FROM quotations')\n") == {}


def test_control_non_unit_tables_and_non_select_ignored():
    assert _scan('def f(conn):\n    conn.execute("SELECT * FROM users")\n') == {}
    assert _scan('def f(conn):\n    conn.execute("DELETE FROM quotations WHERE id=1")\n') == {}
    assert _scan('def f():\n    """SELECT * FROM quotations"""\n    return 1\n') == {}


def test_control_dynamic_sql_lands_in_dynamic_not_silent():
    assert _scan('def f(conn, t):\n    conn.execute(f"SELECT * FROM {t}")\n') == {"x.py::f::<from>": "dynamic"}
    assert _scan('def f(conn, sql):\n    conn.execute(sql)\n') == {"x.py::f::<arg:sql>": "dynamic"}
    assert _scan('def f(conn, rest):\n    conn.execute("SELECT a " + rest)\n') == {"x.py::f::<from>": "dynamic"}
    # 本函式內組好的 SQL 變數不算 dynamic
    assert _scan('def f(conn):\n    sql = "SELECT 1"\n    conn.execute(sql)\n') == {}


def test_control_ratchet_fails_when_entry_not_in_baseline():
    base = {"x.py::f::quotations": "unscoped"}
    cur = _scan('def f(conn):\n    conn.execute("SELECT * FROM quotations")\n') | _scan('def g(conn):\n    conn.execute("SELECT * FROM customers")\n')
    assert {k for k in cur if k not in base} == {"x.py::g::customers"}      # 新增一筆 ⇒ 棘輪會紅
    assert {k for k in _scan('def f(conn):\n    conn.execute("SELECT * FROM quotations")\n') if k not in base} == set()   # 縮小／不變 ⇒ 綠


def test_control_ids_do_not_depend_on_line_numbers():
    a = _scan('def f(conn):\n    conn.execute("SELECT * FROM quotations")\n')
    b = _scan('\n\n# 註解\ndef f(conn):\n\n    conn.execute("SELECT * FROM quotations")\n')
    assert a == b
