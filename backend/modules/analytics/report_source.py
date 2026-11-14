# -*- coding: utf-8 -*-
"""營運分析模組的自訂報表來源登記（T87 B2 D2）：應收帳款（receivable）。

[單位] analytics:report_source    [層] M08    [穩定度] 實驗
[公開介面] register
[不變式] ①**不另寫第二套口徑**：明細來自 `reports._ar_aging_core(..., detail=…)`——與 B1 應收帳齡（`/api/reports/ar-aging`、標準報表「應收帳齡」）
    是同一個迴圈、同一個金額（`payment_item_amounts`）、同一個帳齡區間（`_finance_params`）；自訂報表的「未收金額合計」與 B1 的未收合計恆相等（契約題比對）。
    ②一列＝一個款項項目（請款期別），含已收；「收款狀態」預設篩成「未收」（＝B1 的母體），使用者可改成全部或只看已收。
    ③進入條件＝B1 應收帳齡的閘門（`reports._require_reports_access`：財務角色／superadmin，或「營運報表」模組且 `money_visible`），以 `gate` 掛在來源上，
      與模組存取是「且」：沒有閘門的人在來源清單看不到、用 API 存取（預覽／匯出／存檔）一律 404。能力不取代這道閘門。
    ④金額欄（請款／已收／未收）天花板＝`financial_view`（`can_see_financial`：只有 superadmin 與財務角色）。通過閘門但看不到金額的人（例如營運報表＋出納模組）
      仍看得到非金額欄，金額欄由 report_runner 拿掉並回報「已隱藏 N 欄」；拿來篩選／分組／排序則 422。分享、匯出每次都用執行者自己的權限重算。
    ⑤列範圍＝`row_access` 的 `receivable`（scope=read；直通＝superadmin／admin 或持有 finance／reports 模組），**無條件**併入每一支查詢；
      未登錄（模組沒載入）⇒ 恆假。這是閘門之外的第二道鎖。
    ⑥帳齡區間欄存的是『位置代號』（1～4），白話名稱取自目前的帳齡切點設定（設定中心可調），所以切點改了，存好的報表不會失效。
    ⑦資料在執行時由擁有模組算進**自己建的記憶體資料庫**（來源規格的 `connect`），`report_runner.run_owned(plan, accept)` 以同一套唯讀＋授權器＋時間上限執行；
      沒有「執行任意 SQL」的入口，也不碰正式資料庫的其他表。
    ⑧「預計收款日」是款項項目上登記的預計收款日期（可為空）；帳齡不是從它算的（B1 的帳齡以報價日起算），欄位說明寫清楚，避免被當成帳齡基準。
[契約題] backend/tests/platform/test_custom_reports_receivable_t87.py
"""
import sqlite3

from fastapi import HTTPException

from helpers import report_catalog as _RC
from helpers import row_access as _RA

OWNER = "analytics"
SOURCE_ID = "receivable"
TABLE = "receivable_items"
MODULES = ("finance", "reports")

#: 擁有者規則：沒有擁有者欄位——可見與否只看「直通」（admin 或持有財務／營運報表模組）；其餘人一律看不到任何一列。
RECEIVABLE_ACCESS = _RA.OwnerRule(read_bypass_modules=MODULES, deny_message="無權限查看應收帳款")
_RA.register("receivable", RECEIVABLE_ACCESS)

_COLUMNS = (
    ("quote_no", "TEXT"), ("customer_name", "TEXT"), ("project_name", "TEXT"), ("owner_name", "TEXT"), ("stage", "TEXT"),
    ("pct", "REAL"), ("billed", "REAL"), ("received_amt", "REAL"), ("outstanding", "REAL"), ("status", "TEXT"),
    ("quote_date", "TEXT"), ("expected_date", "TEXT"), ("received_date", "TEXT"), ("days", "INTEGER"), ("band", "TEXT"),
)


def _gate(user) -> bool:
    """B1 應收帳齡的閘門（同一個函式；擋 ⇒ HTTPException）。任何例外 ⇒ 不放行。"""
    try:
        from modules.analytics.api import reports as _rp
        _rp._require_reports_access(user)
        return True
    except HTTPException:
        return False
    except Exception:                                    # noqa: BLE001 — fail-closed
        return False


def _band_options(conn=None):
    """帳齡區間的選項：值是位置代號，白話名稱取自目前的帳齡切點設定。"""
    from helpers import finance_params as _fp
    labels = _fp.aging_labels(_fp.aging_cuts())
    return [(str(k), labels[k]) for k in _fp.BAND_KEYS]


_STATUS = (("未收", "未收"), ("已收", "已收"))


def _materialize():
    """把應收明細（與 B1 同一個計算）放進記憶體資料庫的 `receivable_items`。回傳尚未設唯讀的連線，由 run_owned 負責設唯讀與關閉。"""
    from modules.analytics.api import reports as _rp
    detail = []
    _rp._ar_aging_core(None, None, None, with_owner=True, detail=detail)
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE %s (id INTEGER PRIMARY KEY, %s)" % (TABLE, ", ".join("%s %s" % c for c in _COLUMNS)))   # id＝rowid 別名（編譯的 ORDER BY rowid 與授權器都靠它）
    rows = []
    for d in detail:
        amt = float(d["amount"] or 0)
        rcv = bool(d["received"])
        rows.append((d["quoteNo"], d["customer"], d["project"], d["owner"], d["stage"], float(d["pct"] or 0),
                     amt, amt if rcv else 0.0, 0.0 if rcv else amt, "已收" if rcv else "未收",
                     d["quoteDate"] or None, d["expectedDate"] or None, d["receivedDate"] or None,
                     d["days"], (str(d["band"]) if d["band"] is not None else None)))
    conn.executemany("INSERT INTO %s (%s) VALUES (%s)" % (TABLE, ", ".join(c[0] for c in _COLUMNS), ", ".join("?" * len(_COLUMNS))), rows)
    conn.commit()
    return conn


def _execute(plan):
    """擁有模組的執行回呼（D6）：只接受 `compile()` 產生、且來源是自己的計畫；資料經 `connect`（`_materialize()`，與 B1 同一個計算）。"""
    from helpers import report_runner as RR
    return RR.run_owned(plan, (SOURCE_ID,))


def _f(fid, label, typ, **kw):
    d = {"id": fid, "label": label, "type": typ, "kind": "column", "column": fid, "select": True, "filter": False,
         "group": False, "aggregate": (), "sort": False}
    d.update(kw)
    return d


def register() -> list:
    """由 `modules/analytics/__init__.py` 在模組載入時呼叫。回傳問題清單（空＝已登記）。"""
    money = ("count", "sum", "avg", "min", "max")
    fields = [
        _f("quote_no", "案件號", "text", filter=True, sort=True),
        _f("customer_name", "客戶", "text", filter=True, group=True, sort=True),
        _f("project_name", "案件名稱", "text", filter=True),
        _f("owner_name", "業務", "text", filter=True, group=True),
        _f("stage", "期別", "text", filter=True, group=True),
        _f("pct", "請款比例（%）", "number", filter=True, sort=True),
        _f("billed", "請款金額", "money", catalogId="receivable.billed", filter=True, sort=True, aggregate=money),
        _f("received_amt", "已收金額", "money", catalogId="receivable.received", filter=True, sort=True, aggregate=money),
        _f("outstanding", "未收金額", "money", catalogId="receivable.outstanding", filter=True, sort=True, aggregate=money),
        _f("status", "收款狀態", "enum", filter=True, group=True, enum=_STATUS),
        _f("quote_date", "報價日（帳齡起算日）", "date", filter=True, group=True, sort=True, bucket=("month", "quarter", "year")),
        _f("expected_date", "預計收款日", "date", filter=True, group=True, sort=True, bucket=("month", "quarter", "year")),
        _f("received_date", "收款日", "date", filter=True, sort=True),
        _f("days", "帳齡天數", "number", filter=True, sort=True, aggregate=("count", "avg", "min", "max")),
        _f("band", "帳齡區間", "enum", filter=True, group=True, enum=_band_options),
    ]
    return _RC.register_source(SOURCE_ID, OWNER, {
        "label": "應收帳款", "table": TABLE, "modules": list(MODULES), "gate": _gate, "connect": _materialize, "execute": _execute,
        "desc": "與營運報表的應收帳齡同一份資料：每一個請款期別一列（含已收）；帳齡以報價日起算，已收的沒有帳齡。",
        "rowAccess": {"kind": "receivable", "scope": "read"}, "exprs": (), "fields": fields,
        "defaultFilters": [{"field": "status", "op": "eq", "value": "未收"}],
        "defaults": {"columns": ["quote_no", "customer_name", "stage", "outstanding", "days", "band"],
                     "sort": {"field": "days", "dir": "desc"}},
    })
