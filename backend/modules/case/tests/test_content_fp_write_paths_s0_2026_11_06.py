# -*- coding: utf-8 -*-
"""S0（報價單簽核二擇一／內容指紋；規格 docs/platform/plans/QUOTE-APPROVE-EDIT-CHOICE-PROPOSAL.md §H）：
`quotations.data_json` 寫入點＋指紋排除清單的**靜態守門**。不實作指紋、不改任何現有行為。

守什麼（三件事，各有正對照證明掃描器抓得到）：
1. 直接寫 `quotations.data_json` 的 SQL（UPDATE／INSERT／REPLACE，含多行與分段字串）——每一處都要登記在 `DIRECT_WRITES`
   並寫明處置類別。新增一處＝測試紅，逼寫的人回答：它進不進指紋？要不要呼叫 reconcile？
2. 寫入漏斗 `save_quotation_json` 的真正呼叫點（AST 數，不是文字比對——註解／docstring／import 不算）。
3. 指紋排除清單（denylist）與「伺服器會寫的頂層鍵」的歸類：新增頂層鍵沒歸類＝測試紅（未知鍵預設算內容）。

⚠️ 已知盲點（不要當成全覆蓋）：
- SQL 組字串（`"UPDATE " + table`）只有 `helpers/approval_queue.py::DataJsonApproval.save` 一處，且守門確認沒人傳 "quotations" 給它。
- 頂層鍵掃描只認 `X["k"]=`、`X.setdefault/pop("k")`（X 為 d／data／q／qdata／_data2／_sd／dd）；`X.update({...})`、dict 字面值整份重組不在內。
- 純前端寫的鍵（用戶端送整份本文）看不到；那些走 `update_quotation`（PUT）整份取代，在 DIRECT_WRITES 登記為 CONTENT。
"""
import ast
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3]

# ── 處置類別 ───────────────────────────────────────────────────────────────────────────────
FUNNEL = "FUNNEL"                    # 唯一寫入漏斗本體（save_quotation_json）
NEW_ROW = "NEW_ROW"                  # INSERT 新單：沒有既存簽核，無需作廢
MIGRATION_ONCE = "MIGRATION_ONCE"    # 開機遷移／一次性工具／凍結遷移：不在簽核路徑上（已套用、冪等）；新增遷移仍要登記
BOOKKEEPING_ONLY = "BOOKKEEPING_ONLY"  # 只動排除清單內的鍵（指紋不變）→ 不需 reconcile
CONTENT_DIRECT = "CONTENT_DIRECT"    # 直接 UPDATE 且會改內容鍵、**繞過漏斗** → S3 的「寫後掛鉤」抓不到，需改走漏斗或手動呼叫 reconcile
LEAVES_APPROVAL = "LEAVES_APPROVAL"  # 同時清掉 approval／回草稿：離開簽核範圍，指紋不適用
CONTENT_FULL = "CONTENT_FULL"        # 整份本文取代（解鎖編輯 PUT）：既有「重建簽核」路徑，spec 明訂不動
POST_APPROVAL = "POST_APPROVAL"      # 僅 已成案／已結案 單據可達：不在「待審核／簽核中」範圍

# {"相對路徑::函式限定名": (語句數, 處置類別, 備註)}——語句數＝該函式內寫 data_json 的 SQL 語句數
DIRECT_WRITES = {
    # —— 漏斗本體 ——
    "modules/case/quotations.py::save_quotation_json": (2, FUNNEL, "有／無 status 兩個分支"),
    # —— 新單 ——
    "modules/case/api/quotations.py::create_quotation._do_insert": (1, NEW_ROW, "新建；叫料過閘後插入"),
    "modules/case/api/quotations.py::create_historical_quotation": (1, NEW_ROW, "補登已成案（無簽核）"),
    # —— 簽核路徑上的直接 UPDATE ——
    "modules/case/api/quotations.py::create_quotation": (1, BOOKKEEPING_ONLY, "送審後只 patch `approval`（讀回現值再寫）"),
    "modules/case/api/quotations.py::update_quotation": (1, CONTENT_FULL, "PUT：解鎖編輯／草稿存檔，整份取代；解鎖編輯重建簽核（現狀，spec 明訂不動）"),
    "modules/case/api/quotations.py::update_status": (1, BOOKKEEPING_ONLY, "superadmin 直接改狀態；離開／回到草稿時只動 locationIdentity／clauseTitles（⚠ 白名單允許草稿→已送出，繞過分層簽核，既有行為）"),
    "modules/case/api/quotations.py::recall_quotation": (1, LEAVES_APPROVAL, "收回：pop approval＋快照，狀態回草稿"),
    "modules/case/api/quotations.py::reject_quotation": (1, LEAVES_APPROVAL, "退回改版：quoteNo 升版、pop approval，狀態回草稿"),
    # —— 已成案後 ——
    "modules/case/api/quotations.py::case_batch_assign": (1, POST_APPROVAL, "批次案件變更：只准 已成案；改 caseRecord.roles.executor"),
    "modules/case/api/quotations.py::_calendar_writeback_quotation": (1, BOOKKEEPING_ONLY, "只寫 googleCalendarEventId（提案排除清單未列，S0 盤點新增）"),
    # —— 繞過漏斗、會改內容鍵的路徑（S3 重點：寫後掛鉤抓不到，需改走漏斗或手動 reconcile）——
    "modules/case/material_change.py::_apply": (1, CONTENT_DIRECT, "材料申請投影進 caseRecord.materialOrders；不更新 updated_at／熱欄位"),
    "modules/case/material_payment.py::sync_order_paid": (1, CONTENT_DIRECT, "已付款狀態投影進 materialOrders；不更新 updated_at"),
    "modules/case/profit_guard.py::change_pct": (1, CONTENT_DIRECT, "改管銷比率：overheadPct／tot／net_margin_pct"),
    "modules/case/recycle_adapter.py::MaterialOrderAdapter.delete_in_tx": (1, CONTENT_DIRECT, "刪除材料申請：拿掉 materialOrders 一筆"),
    "modules/case/recycle_adapter.py::MaterialOrderAdapter.restore_in_tx": (1, CONTENT_DIRECT, "還原材料申請：放回 materialOrders 一筆"),
    "modules/case/alt_sign.py::sign": (1, CONTENT_DIRECT, "擇一回簽：altPicks／total／pretax；另改 is_signed 欄位"),
    "modules/case/alt_sign.py::clear_signed_selection": (1, CONTENT_DIRECT, "取消回簽：清 altPicks／altPickedAt／altPickedBy"),
    "modules/case/quotations.py::_record_doc_version": (1, BOOKKEEPING_ONLY, "只 append docVersions（PDF 版本紀錄；提案排除清單未列，S0 盤點新增）"),
    # —— 開機遷移／一次性工具 ——
    "db.py::_m052_fix_stage_json_ids": (1, MIGRATION_ONCE, "stages 作廢 id 修正寫進 caseRecord.stages"),
    "db.py::_m058_backfill_deal_won_at": (1, MIGRATION_ONCE, "補 dealWonAt（只 已成案／已結案）"),
    "db.py::_m059_fix_deal_won_at_from_audit_log": (2, MIGRATION_ONCE, "依稽核紀錄校正／移除 dealWonAt（只 已成案／已結案）"),
    "db.py::_m116_case_roles_username": (1, MIGRATION_ONCE, "caseRecord.roles 字串→物件；⚠ 不分狀態——這類遷移會讓簽核中的單指紋一次性翻動；已套用不追溯。之後凡可能碰待審核／簽核中單的遷移必須呼叫 `content_fp.rebaseline_fingerprint(conn, quote_no)`（K 審 §I5）"),
    "tools/backfill_location_identity_snapshot.py::main": (1, MIGRATION_ONCE, "補 locationIdentity 快照（排除鍵）"),
    "migrations_frozen/t48_overhead25/recalc.py::apply_plan": (1, MIGRATION_ONCE, "凍結：T48 管銷 25% 重算"),
    "migrations_frozen/t48_overhead25/recalc.py::apply_rollback": (1, MIGRATION_ONCE, "凍結：T48 還原"),
    "migrations_frozen/t52_charity/recalc.py::apply_plan": (1, MIGRATION_ONCE, "凍結：T52 公益 1% 重算"),
    "migrations_frozen/t52_charity/recalc.py::apply_rollback": (1, MIGRATION_ONCE, "凍結：T52 還原"),
}

# 真正呼叫 `save_quotation_json(...)` 的點（AST 數；S0 實測 25（不是提案寫的「約31」），S1 加 content_fp.rebaseline_fingerprint 一處＝26——31 含註解／docstring／def／import）
FUNNEL_CALLS = {
    "modules/case/content_fp.py": 1,      # S1 rebaseline_fingerprint（走漏斗、不動 updated_at）
    "modules/case/api/material_orders.py": 2,
    "modules/case/api/quotations.py": 22,
    "modules/case/api/settlement_api.py": 1,
}

# ── 指紋排除清單（提案 §H1 的 denylist；**未知鍵一律算內容**）─────────────────────────────────
#: 提案原列
EXCLUDED_SPEC = frozenset({
    "approval", "statusLog", "editHistory", "returnInfo", "clauseTitles", "locationIdentity", "status",
})
#: 時間戳類：提案寫「updatedAt 類時間戳」。目前頂層實際只見 `updatedAt`（寫入時被 `_DIFF_IGNORE_KEYS` 也忽略）
EXCLUDED_TIMESTAMPS = frozenset({"updatedAt"})
#: S0 盤點新增、K 審（提案 §I4）定案的純伺服器簿記
EXCLUDED_PROPOSED = frozenset({
    "docVersions",             # _record_doc_version：PDF 版本紀錄，伺服器自己 append
    "googleCalendarEventId",   # _calendar_writeback_quotation：日曆事件回寫
    "altPickedAt",             # 回簽時間戳（與 altPicks 成對寫；altPicks 本身維持內容）
    "altPickedBy",             # 回簽人
    "dealWonAt",               # 成案時間戳（由 dealTag 轉換產生）
})
#: 請求暫存欄位：寫入前 `q.pop(...)`，不會進 data_json；列在這裡只是讓掃描器的歸類表完整
TRANSIENT_REQUEST_ONLY = frozenset({"_expectedUpdatedAt", "_isUnlockEdit"})
EXCLUDED_KEYS = EXCLUDED_SPEC | EXCLUDED_TIMESTAMPS | EXCLUDED_PROPOSED

#: 伺服器會寫、且**判定為內容**的頂層鍵（排除清單之外的一律如此；這裡只是明示歸類）
CONTENT_KEYS = frozenset({
    "caseRecord", "customFields", "items", "tot", "overheadPct", "quoteNo", "quoteDate", "locationId",
    "settlement", "taxBasis", "historical", "altPicks", "altTexts",
})
#: K 審（§I4）裁定**維持從嚴算內容**：`rejection` 只在離開簽核範圍時寫；`dealTag` 先這樣，等影子模式（§H6-1④）一週的
#: 「來源區塊」統計，若佔比高再改列排除（改清單要同步改 `content_fp.EXCLUDED_KEYS` 與本檔）
CONTENT_PENDING_K = frozenset({"dealTag", "rejection"})

# 頂層鍵掃描的範圍＝會寫報價單 data_json 的檔（db.py 排除：遷移裡 d[...] 多為巢狀欄位，非頂層）
KEY_SCAN_FILES = (
    "modules/case/api/quotations.py", "modules/case/api/material_orders.py", "modules/case/api/settlement_api.py",
    "modules/case/quotations.py", "modules/case/alt_sign.py", "modules/case/profit_guard.py",
    "modules/case/material_change.py", "modules/case/material_payment.py", "modules/case/recycle_adapter.py",
    "modules/case/material_guard.py", "helpers/clause_titles.py", "helpers/company_identity.py",
)
KEY_VARS = frozenset({"d", "data", "q", "qdata", "_data2", "_sd", "dd"})
#: 變數鍵（`d[k]=`／`d[SNAPSHOT_KEY]=`）：SNAPSHOT_KEY＝locationIdentity；`profit_guard` 的 `d[k]` 迴圈是 ALT_SERVER_KEYS
VARIABLE_KEY_ALIASES = {"SNAPSHOT_KEY": "locationIdentity", "k": None}   # None＝迴圈變數，鍵集合由 ALT_SERVER_KEYS 另守


# ── 掃描器 ─────────────────────────────────────────────────────────────────────────────────
_SQL_START = re.compile(r"""(UPDATE|INSERT\s+(?:OR\s+\w+\s+)?INTO|REPLACE\s+INTO)\s+["`]?quotations["`]?\b""", re.I)
_ASSIGNS_DATA_JSON = re.compile(r"(?<![\w(.$'])data_json\s*=(?!=)", re.I)
_STMT_END = re.compile(r"\bWHERE\b|\bVALUES\b|\bSELECT\b|\n\s*\n", re.I)


def _is_test_path(rel: str) -> bool:
    return "/tests/" in "/" + rel or rel.startswith("tests/")


def _iter_sources():
    for f in sorted(BACKEND.rglob("*.py")):
        rel = f.relative_to(BACKEND).as_posix()
        if _is_test_path(rel) or "/.venv/" in "/" + rel or "/node_modules/" in "/" + rel:
            continue
        yield rel, f.read_text(encoding="utf-8", errors="replace")


def _enclosing_qualnames(tree):
    """line → 最內層函式限定名；回傳 callable(lineno)。"""
    spans = []

    def walk(node, prefix):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                q = prefix + ch.name
                spans.append((ch.lineno, ch.end_lineno, q))
                walk(ch, q + ".")
            elif isinstance(ch, ast.ClassDef):
                walk(ch, prefix + ch.name + ".")
            else:
                walk(ch, prefix)
    walk(tree, "")

    def at(lineno):
        best = None
        for a, b, q in spans:
            if a <= lineno <= b and (best is None or a >= best[0]):
                best = (a, q)
        return best[1] if best else "<module>"
    return at


def find_data_json_writes(rel: str, src: str):
    """回傳 [(行號, 限定名)]：該檔內每一句『UPDATE／INSERT／REPLACE quotations …且寫到 data_json』。"""
    out = []
    tree = None
    for m in _SQL_START.finditer(src):
        tail = src[m.start(): m.start() + 1200]
        end = _STMT_END.search(tail, m.end() - m.start())
        head = tail[: end.start()] if end else tail
        line_start = src.rfind("\n", 0, m.start()) + 1
        if src[line_start: m.start()].lstrip().startswith("#"):
            continue                           # 註解裡提到 SQL 字樣不是寫入
        if m.group(1).upper().startswith("UPDATE"):
            # SET 子句裡 `data_json =` 才算寫入；`deal_tag = COALESCE(json_extract(data_json, …))` 只是讀
            writes = bool(_ASSIGNS_DATA_JSON.search(head))
        else:                                  # INSERT／REPLACE：欄位清單在 VALUES 之前
            writes = "data_json" in head
        if not writes:
            continue
        if tree is None:
            tree = _enclosing_qualnames(ast.parse(src))
        ln = src.count("\n", 0, m.start()) + 1
        out.append((ln, tree(ln)))
    return out


def _registry_from_source():
    got = {}
    for rel, src in _iter_sources():
        for _ln, q in find_data_json_writes(rel, src):
            k = f"{rel}::{q}"
            got[k] = got.get(k, 0) + 1
    return got


# ── 1. 直接寫 data_json 的 SQL ────────────────────────────────────────────────────────────
def test_every_direct_data_json_write_is_registered_with_a_disposition():
    got = _registry_from_source()
    want = {k: v[0] for k, v in DIRECT_WRITES.items()}
    new = {k: v for k, v in got.items() if want.get(k) != v}
    gone = {k: v for k, v in want.items() if got.get(k) != v}
    assert not new and not gone, (
        "寫 quotations.data_json 的 SQL 與登記表不一致。\n"
        f"  新增／數量變了（請在 DIRECT_WRITES 登記並選處置類別，回答『進不進指紋、要不要 reconcile』）：{new}\n"
        f"  登記了但找不到（搬走／改名？）：{gone}")


def test_dispositions_are_valid_and_every_content_bypass_is_listed_for_s3():
    valid = {FUNNEL, NEW_ROW, MIGRATION_ONCE, BOOKKEEPING_ONLY, CONTENT_DIRECT, LEAVES_APPROVAL, CONTENT_FULL, POST_APPROVAL}
    assert all(v[1] in valid for v in DIRECT_WRITES.values())
    assert all(v[2].strip() for v in DIRECT_WRITES.values()), "每一筆都要有備註"
    # 釘住 S3 要處理的『繞過漏斗＋會改內容鍵』清單：新增／移除都要讓人意識到（改走漏斗＝從這裡拿掉）
    direct = sorted(k for k, v in DIRECT_WRITES.items() if v[1] == CONTENT_DIRECT)
    assert direct == sorted([
        "modules/case/alt_sign.py::sign",
        "modules/case/alt_sign.py::clear_signed_selection",
        "modules/case/material_change.py::_apply",
        "modules/case/material_payment.py::sync_order_paid",
        "modules/case/profit_guard.py::change_pct",
        "modules/case/recycle_adapter.py::MaterialOrderAdapter.delete_in_tx",
        "modules/case/recycle_adapter.py::MaterialOrderAdapter.restore_in_tx",
    ])


def test_scanner_positive_and_negative_controls():
    """正對照：掃描器要抓得到各種寫法；負對照：不能把無關語句算進來（否則登記表會被雜訊淹沒）。"""
    pos = {
        "one-line": 'def f(c):\n    c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (1, 2))\n',
        "multi-line triple quote": 'def f(c):\n    c.execute("""\n        UPDATE quotations SET\n          status=?, data_json=?, updated_at=?\n        WHERE quote_no=?\n    """, ())\n',
        "split literals": 'def f(c):\n    c.execute("UPDATE quotations "\n              "SET deal_tag=?, data_json=? "\n              "WHERE quote_no=?", ())\n',
        "insert": 'def f(c):\n    c.execute("""INSERT INTO quotations (quote_no, status, data_json) VALUES (?,?,?)""", ())\n',
        "insert or replace": 'def f(c):\n    c.execute("INSERT OR REPLACE INTO quotations (quote_no, data_json) VALUES (?,?)", ())\n',
        "replace into": 'def f(c):\n    c.execute("REPLACE INTO quotations (quote_no, data_json) VALUES (?,?)", ())\n',
        "json_set": 'def f(c):\n    c.execute("UPDATE quotations SET data_json=json_set(data_json, \'$.x\', 1) WHERE quote_no=?", ())\n',
        "lowercase": 'def f(c):\n    c.execute("update quotations set data_json=? where quote_no=?", ())\n',
        "quoted table": 'def f(c):\n    c.execute(\'UPDATE "quotations" SET data_json=? WHERE 1\', ())\n',
    }
    for name, src in pos.items():
        assert [q for _l, q in find_data_json_writes("x.py", src)] == ["f"], f"掃描器漏抓：{name}"
    neg = {
        "other column": 'def f(c):\n    c.execute("UPDATE quotations SET deal_tag=? WHERE quote_no=?", ())\n',
        "other table": 'def f(c):\n    c.execute("UPDATE payment_requests SET data_json=? WHERE request_no=?", ())\n',
        "select": 'def f(c):\n    c.execute("SELECT data_json FROM quotations WHERE quote_no=?", ())\n',
        "reads data_json inside a SET expression": 'def f(c):\n    c.execute("UPDATE quotations SET deal_tag = COALESCE(json_extract(data_json, \'$.dealTag\'), \'\') WHERE 1", ())\n',
        "mentioned in a comment": 'def f(c):\n    # 一句獨立的 UPDATE quotations SET status=?, data_json=? WHERE 1\n    pass\n',
        "reads data_json in WHERE only": 'def f(c):\n    c.execute("UPDATE quotations SET deal_tag=\'x\' WHERE json_extract(data_json,\'$.a\')=1", ())\n',
    }
    for name, src in neg.items():
        assert find_data_json_writes("x.py", src) == [], f"掃描器誤抓：{name}"
    # 限定名用最內層函式／類別方法
    nested = 'class A:\n    def m(self, c):\n        def inner():\n            c.execute("UPDATE quotations SET data_json=? WHERE 1", ())\n'
    assert [q for _l, q in find_data_json_writes("x.py", nested)] == ["A.m.inner"]


def test_tests_in_the_tree_are_really_excluded_but_the_scan_reaches_real_sources():
    srcs = dict(_iter_sources())
    assert "modules/case/quotations.py" in srcs and "db.py" in srcs
    assert not any(_is_test_path(r) for r in srcs)
    assert "migrations_frozen/t52_charity/recalc.py" in srcs   # 凍結遷移也在掃描範圍（登記為 MIGRATION_ONCE）


# ── 2. 寫入漏斗的呼叫點 ───────────────────────────────────────────────────────────────────
def _funnel_call_counts():
    got = {}
    for rel, src in _iter_sources():
        if "save_quotation_json" not in src:
            continue
        n = 0
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None
                n += name == "save_quotation_json"
        if n:
            got[rel] = n
    return got


def test_save_quotation_json_call_sites_are_pinned():
    assert _funnel_call_counts() == FUNNEL_CALLS, (
        "save_quotation_json 呼叫點變了：新增呼叫端走漏斗＝安全（S3 的寫後掛鉤會涵蓋），但請更新 FUNNEL_CALLS；"
        "若是想繞過它另寫 UPDATE，請改到 DIRECT_WRITES 登記並說明理由")
    assert sum(FUNNEL_CALLS.values()) == 26


def test_the_funnel_is_the_only_place_with_a_plain_data_json_update_in_quotations_module():
    """漏斗本體（modules/case/quotations.py::save_quotation_json）的兩句 UPDATE 不能被拆散到別的函式。"""
    src = (BACKEND / "modules/case/quotations.py").read_text(encoding="utf-8")
    quals = [q for _l, q in find_data_json_writes("modules/case/quotations.py", src)]
    assert quals.count("save_quotation_json") == 2
    assert [q for q in quals if q != "save_quotation_json"] == ["_record_doc_version"]


# ── 3. 動態表名的 data_json 寫入（唯一一處）──────────────────────────────────────────────
def test_dynamic_table_data_json_writer_is_pinned_and_never_pointed_at_quotations():
    dyn = re.compile(r"""["']UPDATE\s*["']\s*\+|f["']UPDATE\s+\{""")
    hits = {}
    for rel, src in _iter_sources():
        for m in dyn.finditer(src):
            if "data_json" in src[m.start(): m.start() + 200]:
                hits[rel] = hits.get(rel, 0) + 1
    assert hits == {"helpers/approval_queue.py": 1}, f"出現新的『動態表名＋data_json』寫入：{hits}"
    for rel, src in _iter_sources():
        for m in re.finditer(r"DataJsonApproval\(\s*[\"']([^\"']+)[\"']", src):
            assert m.group(1) != "quotations", f"{rel}: DataJsonApproval 指到 quotations——會繞過漏斗，改走 save_quotation_json"


# ── 4. 排除清單 ───────────────────────────────────────────────────────────────────────────
def test_exclusion_list_is_locked():
    assert EXCLUDED_SPEC == {"approval", "statusLog", "editHistory", "returnInfo", "clauseTitles", "locationIdentity", "status"}
    assert EXCLUDED_KEYS == EXCLUDED_SPEC | {"updatedAt", "docVersions", "googleCalendarEventId", "altPickedAt", "altPickedBy", "dealWonAt"}
    from modules.case import content_fp            # S1 起排除清單有了 production 常數：兩邊必須逐字相等
    assert content_fp.EXCLUDED_KEYS == EXCLUDED_KEYS
    # 排除清單與內容清單不得重疊；內容清單裡的核心鍵一個都不能被排除（突變：把它們搬進排除清單，這裡必須翻紅）
    assert not (EXCLUDED_KEYS & (CONTENT_KEYS | CONTENT_PENDING_K))
    for core in ("items", "tot", "caseRecord", "customFields", "overheadPct", "settlement", "altPicks", "dealTag"):
        assert core not in EXCLUDED_KEYS, f"{core} 是內容，不能進排除清單"


def test_existing_diff_ignore_keys_stay_within_known_classification():
    """既有 `_DIFF_IGNORE_KEYS`（editHistory 差異摘要用）是另一個清單，但每一個鍵都該在這裡有歸類；兩者不一致要讓人看到。"""
    src = (BACKEND / "modules/case/api/quotations.py").read_text(encoding="utf-8")
    m = re.search(r"_DIFF_IGNORE_KEYS\s*=\s*\{([^}]*)\}", src)
    assert m, "找不到 _DIFF_IGNORE_KEYS"
    keys = set(re.findall(r"""["']([^"']+)["']""", m.group(1)))
    assert keys <= (EXCLUDED_KEYS | TRANSIENT_REQUEST_ONLY), f"_DIFF_IGNORE_KEYS 出現未歸類的鍵：{keys - EXCLUDED_KEYS - TRANSIENT_REQUEST_ONLY}"


def test_the_snapshot_key_is_location_identity():
    src = (BACKEND / "helpers/company_identity.py").read_text(encoding="utf-8")
    assert re.search(r'^SNAPSHOT_KEY\s*=\s*"locationIdentity"\s*$', src, re.M)


def test_alt_server_keys_are_pinned():
    src = (BACKEND / "modules/case/profit_guard.py").read_text(encoding="utf-8")
    m = re.search(r"^ALT_SERVER_KEYS\s*=\s*\(([^)]*)\)", src, re.M)
    assert set(re.findall(r"""["']([^"']+)["']""", m.group(1))) == {"altPicks", "altPickedAt", "altPickedBy"}


# ── 5. 伺服器寫的頂層鍵必須歸類 ─────────────────────────────────────────────────────────────
def _server_written_top_level_keys():
    keys = {}
    for rel in KEY_SCAN_FILES:
        tree = ast.parse((BACKEND / rel).read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            k = None
            if isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Store) and isinstance(n.value, ast.Name) and n.value.id in KEY_VARS:
                s = n.slice
                if isinstance(s, ast.Constant) and isinstance(s.value, str):
                    k = s.value
                elif isinstance(s, ast.Name):
                    k = "<%s>" % s.id
            elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("setdefault", "pop")
                  and isinstance(n.func.value, ast.Name) and n.func.value.id in KEY_VARS
                  and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)):
                k = n.args[0].value
            if k:
                keys.setdefault(k, set()).add(rel)
    return keys


def test_every_server_written_top_level_key_is_classified():
    classified = EXCLUDED_KEYS | TRANSIENT_REQUEST_ONLY | CONTENT_KEYS | CONTENT_PENDING_K
    unknown = {}
    for k, files in _server_written_top_level_keys().items():
        if k.startswith("<"):
            name = k[1:-1]
            assert name in VARIABLE_KEY_ALIASES, f"變數鍵 d[{name}]=… 出現在 {sorted(files)}：請在 VARIABLE_KEY_ALIASES 說明它代表哪些鍵"
            real = VARIABLE_KEY_ALIASES[name]
            if real is None or real in classified:
                continue
            unknown[real] = files
        elif k not in classified:
            unknown[k] = files
    assert not unknown, (
        "伺服器新寫了未歸類的頂層鍵（預設會被算成『內容』＝動它就讓已簽的簽核作廢）。請判斷：\n"
        "  純簿記（伺服器自己維護、簽核人不需審視）→ 加進 EXCLUDED_PROPOSED 並經 K 審；\n"
        "  內容 → 加進 CONTENT_KEYS。\n" + "\n".join(f"  {k}: {sorted(v)}" for k, v in sorted(unknown.items())))


def test_key_scanner_positive_control():
    src = 'def f(d, q):\n    d["newKey"] = 1\n    q.setdefault("another", {})\n    q.pop("gone", None)\n    z["notScanned"] = 1\n'
    tree = ast.parse(src)
    got = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Store) and isinstance(n.value, ast.Name) and n.value.id in KEY_VARS:
            got.add(n.slice.value)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("setdefault", "pop") and n.func.value.id in KEY_VARS:
            got.add(n.args[0].value)
    assert got == {"newKey", "another", "gone"}
    # 並且真實掃描至少抓得到已知的幾個鍵（防止掃描範圍／變數名單默默失效而全綠）
    real = _server_written_top_level_keys()
    for must in ("approval", "statusLog", "editHistory", "docVersions", "googleCalendarEventId", "caseRecord", "altPicks"):
        assert must in real, f"頂層鍵掃描沒抓到已知的 {must}——掃描範圍或變數名單失效"
