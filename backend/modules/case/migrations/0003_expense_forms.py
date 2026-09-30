# -*- coding: utf-8 -*-
"""case v3（2026-10-01，費用單據 A2：請購／差旅／採購／零用金 擴充「新增請款」）：`case_extra_expenses` 一次加齊通用欄位。

為什麼一次加齊：之後再加欄就是第二次 migration（底層預留，使用者 2026-10-01「都要動到底層了，思考先行預留」）。
- kind：''＝舊版案件額外支出（行為不變）；其餘由費用單據定義（請購／差旅／採購／零用金…）決定
- doc_code：人看的單號（RQ-／TE-／PC-／PO-YYYYMM-NNN，由 `next_entity_code(…, code_col="doc_code")` 產生）；空字串不受唯一限制
- data_json／lines_json：超級管理員定義的欄位值與明細列（讀寫都不得丟未知鍵）；def_version：建立當下的欄位定義版本
- department_id：費用歸屬單位（無案件時的成本中心）
- payee_type／payee_name／payee_bank／payee_account：收款人（員工或廠商；銀行資料的權威來源是 payroll 的銀行資料表，這裡只留單據當下快照／手填）
- pay_terms／remit_date／pay_method／pay_account_code／paid_by：出納撥款（採購單：核准後出納填匯款日＋付款條件；付款方式決定總帳貸方）
- pretax／tax／currency：稅額拆分（沒有稅額欄的單據維持 0）；currency 目前只有 TWD
- void_reason／voided_by／voided_at：作廢（額外支出作廢路徑，第 29 班用；現在一起加，避免再一次 migration）
- 只新增欄位／索引、冪等；舊列全部維持原值；表不在 ⇒ 回原因字串＝未完成（下次啟動再補）；不自己 commit、不 import 會演進的程式碼。
"""

_COLS = (
    ("kind", "TEXT NOT NULL DEFAULT ''"),
    ("doc_code", "TEXT NOT NULL DEFAULT ''"),
    ("data_json", "TEXT NOT NULL DEFAULT '{}'"),
    ("lines_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("def_version", "INTEGER NOT NULL DEFAULT 0"),
    ("department_id", "INTEGER"),
    ("payee_type", "TEXT NOT NULL DEFAULT ''"),
    ("payee_name", "TEXT NOT NULL DEFAULT ''"),
    ("payee_bank", "TEXT NOT NULL DEFAULT ''"),
    ("payee_account", "TEXT NOT NULL DEFAULT ''"),
    ("pay_terms", "TEXT NOT NULL DEFAULT ''"),
    ("remit_date", "TEXT NOT NULL DEFAULT ''"),
    ("pay_method", "TEXT NOT NULL DEFAULT ''"),
    ("pay_account_code", "TEXT NOT NULL DEFAULT ''"),
    ("paid_by", "TEXT NOT NULL DEFAULT ''"),
    ("pretax", "REAL NOT NULL DEFAULT 0"),
    ("tax", "REAL NOT NULL DEFAULT 0"),
    ("currency", "TEXT NOT NULL DEFAULT 'TWD'"),
    ("void_reason", "TEXT NOT NULL DEFAULT ''"),
    ("voided_by", "TEXT NOT NULL DEFAULT ''"),
    ("voided_at", "TEXT NOT NULL DEFAULT ''"),
)


def up(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(case_extra_expenses)").fetchall()}
    if not cols:
        return "case_extra_expenses 表不存在，費用單據欄位這次不補、下次啟動再試"
    for name, ddl in _COLS:
        if name not in cols:
            conn.execute("ALTER TABLE case_extra_expenses ADD COLUMN %s %s" % (name, ddl))
    # doc_code 有值時必須唯一（舊列與 kind='' 是空字串，不受限）
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_case_extra_exp_doc_code ON case_extra_expenses(doc_code) WHERE doc_code <> ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_case_extra_exp_kind_status ON case_extra_expenses(kind, status)")
    return None
