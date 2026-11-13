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
# 864 = 861 + 3（fix/excel-import-dataloss 2026-11-13：Excel 匯入的比對讀客戶／料號主檔——與同檔 list_customers／get_customer 同為全公司共用主檔、權限由模組檢查，沒有單位欄位可範圍化）
MAX_ENTRIES = 871      # 861 + 4（一條龍 P0a／P0c／P1' 2026-11-13：①`email_notify.shipping_link` 與 `inventory._StockSerials.release` 各讀 `shipping_notes` 一次，只用單號查「存在／仍是已核准」（`release` 是案件存檔交易內、舊資料維持 in_stock 的判斷；`shipping_link` 是通知連結的查案號），不回傳資料給使用者；②`case/material_flow._purchase` 讀 `case_extra_expenses`，**端點先過 `require_case`（案件成員）**且只取單據代號／狀態／日期、沒有金額；③`supply/case_summary` 讀 `stock_items` 彙總該案台數，案件可見性由案件側先檢查、呼叫者另要有檢視庫存的模組權限。測試 modules/case/tests/test_onepipe_p1_timeline_2026_11_13.py）
                        # 861 = 856 + 5（T80c 外勤 S2 K審修 2026-11-12：列表 `list_field_cases` 改成「案件成員」口徑（CM14：業務／協作者／角色／階段負責人），SQL 只做 instr 粗篩（超集）、
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
                        # （併入）861 + 1（估價單 2026-11-13：`modules/case/quotations.py::_estimate_prefixes` 只回「曾開過估價單的單號字首」的 DISTINCT 聚合（不含任何案件內容、不回列），
                        # 經串接點 IP-ESTQ1 給 L1 `helpers/doc_type`；沒有逐案範圍可套，也不接使用者端點）
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
