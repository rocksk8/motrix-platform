# -*- coding: utf-8 -*-
"""自訂模組引擎（P8，CUSTOMIZATION-SPEC §1／§3.1／§8.1）：定義是資料，不是程式。

- 定義存在定義文件庫（`core.definitions`，kind＝`custom_module`，key＝模組 key），有草稿、版本、差異、還原。
- 單據是**文件式**：每筆一份 JSON（`custom_records.data_json`），欄位值另寫一份索引（`custom_record_values`）
  給查詢與排序用 ⇒ 建立或修改模組**不用改資料庫結構**。
- 單據建立時**凍結在當時的定義版本**（`def_version`）；之後定義改了，舊單據仍依它自己的版本運作與輸出。
- 流程：狀態＋轉換；狀態可以掛分層簽核（沿用 `helpers.tiered_approval`，同一套規則），層可以帶條件公式；
  進入狀態可以通知；每次狀態改變發事件 `custom_module.transitioned`（P6）。
- 只從目錄挑：欄位型別（`FIELD_TYPES`）、公式函式（`helpers.formula`）、參照對象（`register_ref_target`）、
  輸出積木（`helpers.doc_template`）。

本檔不碰 FastAPI；HTTP 由 `routers/custom_records.py` 包。寫入的函式吃呼叫端的連線、自己 commit。
"""
import json
import re
from datetime import date, datetime

from helpers import custom_fields as _cf
from helpers import formula as _fx

KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
STATE_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,29}$")
PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9]{0,5}$")
#: 欄位型別目錄：自訂欄位的型別＋公式（唯讀、由公式算出）＋參照（指到其他資料）
FIELD_TYPES = _cf.TYPES + ("formula", "ref")
DATE_FORMATS = {"YYYYMMDD": "%Y%m%d", "YYYYMM": "%Y%m", "": ""}
EVENT_TRANSITIONED = "custom_module.transitioned"

#: 參照對象目錄：key ⇒ (表, 顯示欄位, 主鍵欄位)。內建模組把自己公開的資料登記進來；`custom:<key>` 另外處理。
_REF_TARGETS = {}


class CustomModuleError(ValueError):
    def __init__(self, message, problems=None, status=400):
        super().__init__(message)
        self.problems = problems or []
        self.status = status


#: 簽核人的來源目錄（同 helpers.tiered_approval）：建構器的簽核層編輯器只能從這裡挑
APPROVER_SOURCES = [
    {"sourceType": "", "label": "指定帳號", "params": ["username"]},
    {"sourceType": "department_manager", "label": "部門主管", "params": ["departmentId"]},
    {"sourceType": "division_manager", "label": "處主管", "params": ["divisionId"]},
    {"sourceType": "submitter_manager", "label": "申請人的主管", "params": []},
]


def register_ref_target(key: str, table: str, label_column: str, id_column: str = "id") -> None:
    _REF_TARGETS[key] = (table, label_column, id_column)


def ref_targets() -> dict:
    return {k: {"table": t, "label": l} for k, (t, l, _i) in sorted(_REF_TARGETS.items())}


register_ref_target("customers", "customers", "name")
register_ref_target("users", "users", "display_name", "username")


# ── 定義驗證（每一項帶位置）────────────────────────────────────────────────

def _p(path, message):
    return {"path": path, "message": message}


def validate_module(body: dict, key: str = "") -> list:
    """自訂模組定義 ⇒ `[{"path", "message"}]`（空＝可以發布）。建構器依 `path` 標出錯在哪。"""
    if not isinstance(body, dict):
        return [_p("", "定義必須是 JSON 物件")]
    out = []
    if key and not KEY_RE.match(key):
        out.append(_p("", "模組 key 只能用小寫英文、數字與底線（2～40 字）：%r" % key))
    if not str(body.get("name") or "").strip():
        out.append(_p("name", "必須有模組名稱"))
    perm = body.get("permission", "custom.%s" % key)
    if not isinstance(perm, str) or not re.match(r"^[a-z][a-z0-9_.]{1,60}$", perm):
        out.append(_p("permission", "權限 key 格式不對：%r" % (perm,)))
    out += _validate_numbering(body.get("numbering"))
    fields = body.get("fields")
    if not isinstance(fields, list) or not fields:
        out.append(_p("fields", "至少要有一個欄位"))
        fields = []
    out += _validate_fields(fields)
    keys = [f.get("key") for f in fields if isinstance(f, dict)]
    out += _validate_workflow(body.get("workflow"), keys)
    out += _validate_output(body)
    return out


def _validate_numbering(n):
    if not isinstance(n, dict):
        return [_p("numbering", "必須有編號規則（前綴、日期、流水號位數）")]
    out = []
    if not PREFIX_RE.match(str(n.get("prefix") or "")):
        out.append(_p("numbering.prefix", "前綴只能用大寫英文與數字、英文開頭，最長 6 字"))
    if n.get("date", "YYYYMMDD") not in DATE_FORMATS:
        out.append(_p("numbering.date", "日期格式只能是 YYYYMMDD、YYYYMM 或空白"))
    d = n.get("digits", 4)
    if not isinstance(d, int) or isinstance(d, bool) or not 3 <= d <= 8:
        out.append(_p("numbering.digits", "流水號位數必須是 3～8"))
    return out


def _validate_fields(fields):
    out, seen = [], set()
    keys = [f.get("key") for f in fields if isinstance(f, dict)]
    for i, f in enumerate(fields):
        p = "fields[%d]" % i
        if not isinstance(f, dict):
            out.append(_p(p, "欄位必須是物件"))
            continue
        k, t = f.get("key"), f.get("type")
        if k in seen:
            out.append(_p(p + ".key", "key 重複：%s" % k))
        seen.add(k)
        if f.get("dataClass") == "F2":
            # 🔴 自訂模組的單據是整份 JSON；個資欄位的分流（MODULE-GUIDE §3）還沒有接到自訂模組 ⇒ 先拒絕，不讓它靜默進一般備份
            out.append(_p(p + ".dataClass", "自訂模組暫不支援個資（F2）欄位：個資分流尚未接上"))
        if t == "formula":
            if not _cf.KEY_RE.match(str(k or "")):
                out.append(_p(p + ".key", "key 只能用小寫英文、數字與底線，英文開頭，最長 40 字：%r" % (k,)))
            if not str(f.get("label") or "").strip():
                out.append(_p(p + ".label", "必須有顯示名稱"))
            for prob in _fx.check(f.get("formula"), [x for x in keys if x != k]):
                out.append(_p(p + ".formula", "第 %d 字：%s" % (prob["pos"] + 1, prob["message"])))
        elif t == "ref":
            if not _cf.KEY_RE.match(str(k or "")):
                out.append(_p(p + ".key", "key 只能用小寫英文、數字與底線，英文開頭，最長 40 字：%r" % (k,)))
            if not str(f.get("label") or "").strip():
                out.append(_p(p + ".label", "必須有顯示名稱"))
            target = str(f.get("target") or "")
            if not (target in _REF_TARGETS or (target.startswith("custom:") and KEY_RE.match(target[7:]))):
                out.append(_p(p + ".target", "不認得的參照對象 %r（可用：%s、custom:<模組>）" % (target, "、".join(sorted(_REF_TARGETS)))))
        else:
            for prob in _cf.validate_definition({"fields": [f]}):
                out.append(_p(prob["path"].replace("fields[0]", p, 1), prob["message"]))
    formulas = {f["key"]: f.get("formula") for f in fields if isinstance(f, dict) and f.get("type") == "formula" and f.get("key")}
    try:
        _fx.evaluation_order(formulas)
    except _fx.FormulaError as e:
        out.append(_p("fields", str(e)))
    return out


def _validate_workflow(wf, field_keys):
    if not isinstance(wf, dict):
        return [_p("workflow", "必須有流程（狀態與轉換）")]
    out = []
    states = wf.get("states") if isinstance(wf.get("states"), list) else []
    if not states:
        out.append(_p("workflow.states", "至少要有一個狀態"))
    by_key = {}
    for i, s in enumerate(states):
        p = "workflow.states[%d]" % i
        k = s.get("key") if isinstance(s, dict) else None
        if not isinstance(k, str) or not STATE_KEY_RE.match(k):
            out.append(_p(p + ".key", "狀態 key 只能用小寫英文、數字與底線：%r" % (k,)))
            continue
        if k in by_key:
            out.append(_p(p + ".key", "狀態重複：%s" % k))
        by_key[k] = (i, s)
        if not str(s.get("label") or "").strip():
            out.append(_p(p + ".label", "狀態必須有顯示名稱"))
    initial = wf.get("initial")
    if initial not in by_key:
        out.append(_p("workflow.initial", "起始狀態 %r 不在狀態清單裡" % (initial,)))
    finals = {k for k, (_i, s) in by_key.items() if s.get("final")}
    if by_key and not finals:
        out.append(_p("workflow.states", "沒有終點狀態（至少一個狀態要標 final）"))
    edges = {k: set() for k in by_key}
    trans = wf.get("transitions") if isinstance(wf.get("transitions"), list) else []
    tkeys = set()
    for i, t in enumerate(trans):
        p = "workflow.transitions[%d]" % i
        if not isinstance(t, dict):
            out.append(_p(p, "轉換必須是物件"))
            continue
        if not STATE_KEY_RE.match(str(t.get("key") or "")):
            out.append(_p(p + ".key", "轉換 key 只能用小寫英文、數字與底線：%r" % (t.get("key"),)))
        elif t["key"] in tkeys:
            out.append(_p(p + ".key", "轉換重複：%s" % t["key"]))
        tkeys.add(t.get("key"))
        if not str(t.get("label") or "").strip():
            out.append(_p(p + ".label", "轉換必須有按鈕名稱"))
        fr, to = t.get("from"), t.get("to")
        frs = fr if isinstance(fr, list) else [fr]
        for f_ in frs:
            if f_ not in by_key:
                out.append(_p(p + ".from", "來源狀態 %r 不存在" % (f_,)))
            elif f_ in finals:
                out.append(_p(p + ".from", "終點狀態 %s 不可以再往外轉換" % f_))
            elif to in by_key:
                edges[f_].add(to)
        if to not in by_key:
            out.append(_p(p + ".to", "目標狀態 %r 不存在" % (to,)))
    for k, (i, s) in by_key.items():
        appr = s.get("approval")
        if appr is None:
            continue
        p = "workflow.states[%d].approval" % i
        for side in ("on_approved", "on_rejected"):
            tgt = appr.get(side) if isinstance(appr, dict) else None
            if tgt not in by_key:
                out.append(_p(p + "." + side, "簽核%s後要去的狀態 %r 不存在" % ("通過" if side == "on_approved" else "退回", tgt)))
            else:
                edges[k].add(tgt)
        tiers = appr.get("tiers") if isinstance(appr, dict) else None
        if not isinstance(tiers, list) or not tiers:
            out.append(_p(p + ".tiers", "簽核至少要有一層"))
            tiers = []
        for j, tier in enumerate(tiers):
            tp = "%s.tiers[%d]" % (p, j)
            approvers = tier.get("approvers") if isinstance(tier, dict) else None
            if not isinstance(approvers, list) or not approvers:
                out.append(_p(tp + ".approvers", "這一層沒有簽核人"))
            else:
                for a_i, a in enumerate(approvers):
                    if not isinstance(a, dict) or not (a.get("username") or a.get("sourceType")):
                        out.append(_p("%s.approvers[%d]" % (tp, a_i), "簽核人要指定帳號，或部門主管／處主管／申請人主管"))
            if isinstance(tier, dict) and tier.get("when"):
                for prob in _fx.check(tier["when"], field_keys):
                    out.append(_p(tp + ".when", "第 %d 字：%s" % (prob["pos"] + 1, prob["message"])))
    # 可達性：從起始狀態走得到每一個狀態；非終點狀態都要有出路
    if initial in by_key:
        seen, stack = {initial}, [initial]
        while stack:
            for n in edges[stack.pop()]:
                if n not in seen:
                    seen.add(n)
                    stack.append(n)
        for k, (i, _s) in by_key.items():
            if k not in seen:
                out.append(_p("workflow.states[%d]" % i, "狀態 %s 從起始狀態走不到（孤立狀態）" % k))
            elif k not in finals and not edges[k]:
                out.append(_p("workflow.states[%d]" % i, "狀態 %s 不是終點卻沒有出路（單據會卡住）" % k))
    return out


def _validate_output(body):
    tpl = (body.get("output") or {}).get("template") if isinstance(body.get("output"), dict) else None
    if tpl is None:
        return []
    from helpers import doc_template as dt
    if not isinstance(tpl, dict):
        return [_p("output.template", "輸出版型必須是 JSON 物件")]
    return [_p("output.template." + p["path"] if p.get("path") else "output.template", p["message"])
            for p in dt.problems(tpl, sample_view(body))]


# ── 編號 ─────────────────────────────────────────────────────────────────

def format_number(numbering: dict, day: date, seq: int) -> str:
    fmt = DATE_FORMATS.get(numbering.get("date", "YYYYMMDD"), "%Y%m%d")
    parts = [numbering["prefix"]] + ([day.strftime(fmt)] if fmt else []) + [str(seq).zfill(numbering.get("digits", 4))]
    return "-".join(parts)


def next_number(conn, module_key: str, numbering: dict, day: date = None) -> str:
    """依期間（日期格式決定：每日／每月／不分期）遞增流水號。呼叫端在寫入交易內呼叫。"""
    day = day or date.today()
    fmt = DATE_FORMATS.get(numbering.get("date", "YYYYMMDD"), "%Y%m%d")
    period = day.strftime(fmt) if fmt else ""
    row = conn.execute("SELECT seq FROM custom_record_counters WHERE module=? AND period=?", (module_key, period)).fetchone()
    seq = (row[0] if row else 0) + 1
    conn.execute("INSERT INTO custom_record_counters (module, period, seq) VALUES (?,?,?) "
                 "ON CONFLICT(module, period) DO UPDATE SET seq=excluded.seq", (module_key, period, seq))
    return format_number(numbering, day, seq)


# ── 值：清理、公式、樣本 ─────────────────────────────────────────────────────

def _input_fields(body):
    return [f for f in body.get("fields", []) if f.get("type") not in ("formula",)]


def clean_values(conn, body: dict, values) -> tuple:
    """回 `(乾淨的值（含公式結果）, 錯誤, 丟掉的鍵)`。公式欄位不收輸入（送了也丟掉並回報）。"""
    values = values if isinstance(values, dict) else {}
    plain = [dict(f, type="text") if f.get("type") == "ref" else f for f in _input_fields(body)]
    out, errors, dropped = _cf.clean(values, {"fields": plain})
    for f in _input_fields(body):
        if f.get("type") == "ref" and out.get(f["key"]) is not None:
            if not _ref_exists(conn, f["target"], out[f["key"]]):
                errors.append({"key": f["key"], "message": "%s：參照不到 %s" % (f.get("label") or f["key"], out[f["key"]])})
    computed, ferrors = compute(body, out)
    return computed, errors + ferrors, dropped


def _ref_exists(conn, target, value) -> bool:
    if target.startswith("custom:"):
        return conn.execute("SELECT 1 FROM custom_records WHERE module_key=? AND record_no=?",
                            (target[7:], str(value))).fetchone() is not None
    table, _label, idc = _REF_TARGETS[target]
    return conn.execute("SELECT 1 FROM %s WHERE %s=?" % (table, idc), (value,)).fetchone() is not None


def ref_options(conn, target: str, q: str = "", limit: int = 50) -> list:
    """參照欄的選項 `[{value, label}]`。內建對象依登記的表與欄位；`custom:<模組>` ⇒ 該模組的單號（標籤＝單號＋第一個文字欄）。"""
    like = "%" + (q or "") + "%"
    if target.startswith("custom:"):
        rows = conn.execute("SELECT record_no, data_json FROM custom_records WHERE module_key=? AND record_no LIKE ? "
                            "ORDER BY id DESC LIMIT ?", (target[7:], like, limit)).fetchall()
        out = []
        for r in rows:
            data = json.loads(r["data_json"] or "{}")
            first = next((v for v in data.values() if isinstance(v, str) and v), "")
            out.append({"value": r["record_no"], "label": (r["record_no"] + " " + first).strip()})
        return out
    if target not in _REF_TARGETS:
        raise CustomModuleError("不認得的參照對象 %r" % target, status=404)
    table, label, idc = _REF_TARGETS[target]
    extra = " AND active=1" if table == "users" else ""
    sql = ("SELECT {i} AS v, {l} AS l FROM {t} WHERE ({l} LIKE ? OR CAST({i} AS TEXT) LIKE ?){x} ORDER BY {l} LIMIT ?"
           .format(i=idc, l=label, t=table, x=extra))
    rows = conn.execute(sql, (like, like, limit)).fetchall()
    return [{"value": r["v"], "label": r["l"] or str(r["v"])} for r in rows]


def compute(body: dict, values: dict) -> tuple:
    """依引用順序算出公式欄位。公式出錯（除以 0 等）⇒ 那一欄是空值，並回報是哪一欄。"""
    out = dict(values)
    errors = []
    formulas = {f["key"]: f for f in body.get("fields", []) if f.get("type") == "formula"}
    for k in _fx.evaluation_order({k: f["formula"] for k, f in formulas.items()}):
        try:
            out[k] = _fx.evaluate(formulas[k]["formula"], out)
        except _fx.FormulaError as e:
            out[k] = None
            errors.append({"key": k, "message": "%s：公式無法計算（%s）" % (formulas[k].get("label") or k, e)})
    return out, errors


_SAMPLES = {"text": "範例文字", "number": 1, "date": "2026-09-25", "checkbox": True}


def sample_view(body: dict) -> dict:
    """給輸出預覽與版型驗證用的樣本視圖（與 record_view 同形）。"""
    vals = {}
    for f in _input_fields(body):
        t = f.get("type")
        vals[f["key"]] = (f.get("options") or ["選項"])[0] if t == "select" else _SAMPLES.get(t, "範例")
    vals, _e = compute(body, vals)
    numbering = body.get("numbering") or {"prefix": "X"}
    try:
        no = format_number(numbering, date(2026, 9, 25), 1)
    except (KeyError, TypeError, ValueError):
        no = "X-0001"
    wf = body.get("workflow") or {}
    return _view(body, {"record_no": no, "status": wf.get("initial") or "", "created_by": "範例使用者",
                        "created_at": "2026-09-25T09:00:00", "approval": {}}, vals)


def _view(body, rec, vals):
    labels = {s.get("key"): s.get("label") for s in (body.get("workflow") or {}).get("states", []) if isinstance(s, dict)}
    return {"recordNo": rec["record_no"], "status": rec["status"], "statusLabel": labels.get(rec["status"], rec["status"]),
            "createdBy": rec.get("created_by", ""), "createdAt": rec.get("created_at", ""), "moduleName": body.get("name", ""),
            "fields": vals, "approval": rec.get("approval") or {}, **vals}


# ── 單據 ────────────────────────────────────────────────────────────────

def _load_def(conn, module_key, version=None):
    from core import definitions as D
    d = D.get(conn, "custom_module", module_key, "company", version)
    if d is None or d.get("status") != "published":
        raise CustomModuleError("自訂模組 %s 沒有已發布的定義%s" % (module_key, "（第 %s 版）" % version if version else ""), status=404)
    return d


def published_modules(conn) -> list:
    rows = conn.execute("SELECT key, MAX(version) AS v FROM ui_definitions WHERE kind='custom_module' AND scope='company' "
                        "AND status='published' GROUP BY key ORDER BY key").fetchall()
    out = []
    for r in rows:
        d = _load_def(conn, r["key"], r["v"])
        out.append({"key": r["key"], "version": d["version"], "name": d["body"].get("name"),
                    "icon": d["body"].get("icon", ""), "menu": d["body"].get("menu") or {},
                    "permission": permission_of(r["key"], d["body"])})
    return out


def permission_of(module_key, body) -> str:
    return body.get("permission") or "custom.%s" % module_key


def _row(conn, module_key, record_no):
    r = conn.execute("SELECT * FROM custom_records WHERE module_key=? AND record_no=?", (module_key, record_no)).fetchone()
    if r is None:
        raise CustomModuleError("找不到單據 %s" % record_no, status=404)
    d = dict(r)
    d["data"] = json.loads(d.pop("data_json") or "{}")
    d["approval"] = json.loads(d.pop("approval_json") or "{}")
    return d


def _write_index(conn, rec_id, module_key, vals):
    conn.execute("DELETE FROM custom_record_values WHERE record_id=?", (rec_id,))
    for k, v in vals.items():
        if v is None:
            continue
        num = v if isinstance(v, (int, float)) and not isinstance(v, bool) else None
        conn.execute("INSERT INTO custom_record_values (record_id, module_key, field, value_text, value_num) VALUES (?,?,?,?,?)",
                     (rec_id, module_key, k, v if isinstance(v, str) else json.dumps(v, ensure_ascii=False), num))


def rebuild_index(conn) -> int:
    """從 `custom_records.data_json` 重建整張欄位索引（從每日 JSON 還原單據之後執行；索引本身不匯出）。回重建的單據數。"""
    from core.txn import write_txn
    with write_txn(conn):
        conn.execute("DELETE FROM custom_record_values")
        rows = conn.execute("SELECT id, module_key, data_json FROM custom_records").fetchall()
        for r in rows:
            _write_index(conn, r["id"], r["module_key"], json.loads(r["data_json"] or "{}"))
        conn.commit()
    return len(rows)


def _log(conn, rec_id, action, from_state, to_state, user, note=""):
    conn.execute("INSERT INTO custom_record_log (record_id, action, from_state, to_state, by_user, note, at) "
                 "VALUES (?,?,?,?,?,?,?)", (rec_id, action, from_state, to_state, user, note or "",
                                            datetime.now().isoformat(timespec="seconds")))


def get_record(conn, module_key, record_no) -> dict:
    rec = _row(conn, module_key, record_no)
    d = _load_def(conn, module_key, rec["def_version"])
    rec["view"] = _view(d["body"], rec, rec["data"])
    # 單據凍結在建立時的定義版本 ⇒ 畫面的標籤、欄位與按鈕要用這一版，不是最新版
    rec["definition"] = d["body"]
    rec["log"] = [dict(r) for r in conn.execute("SELECT action, from_state, to_state, by_user, note, at FROM custom_record_log "
                                                 "WHERE record_id=? ORDER BY id", (rec["id"],)).fetchall()]
    return rec


def list_records(conn, module_key, status=None, field=None, value=None, limit=200) -> list:
    sql = "SELECT r.record_no, r.status, r.def_version, r.created_by, r.created_at, r.updated_at, r.data_json FROM custom_records r"
    args, where = [], ["r.module_key=?"]
    args.append(module_key)
    if field:
        sql += " JOIN custom_record_values v ON v.record_id=r.id AND v.field=?"
        args.insert(0, field)
        if value is not None:
            where.append("v.value_text=?")
            args.append(str(value))
    if status:
        where.append("r.status=?")
        args.append(status)
    sql += " WHERE " + " AND ".join(where) + " ORDER BY r.id DESC LIMIT ?"
    args.append(int(limit))
    out = []
    for r in conn.execute(sql, args).fetchall():
        d = dict(r)
        d["data"] = json.loads(d.pop("data_json") or "{}")
        out.append(d)
    return out


def create_record(conn, module_key, values, user) -> dict:
    from core.txn import write_txn
    d = _load_def(conn, module_key)
    body = d["body"]
    vals, errors, dropped = clean_values(conn, body, values)
    if errors:
        raise CustomModuleError("有 %d 個欄位不對" % len(errors), errors)
    now = datetime.now().isoformat(timespec="seconds")
    with write_txn(conn):
        no = next_number(conn, module_key, body["numbering"])
        cur = conn.execute("INSERT INTO custom_records (module_key, record_no, def_version, status, data_json, approval_json, "
                           "created_by, created_at, updated_by, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                           (module_key, no, d["version"], body["workflow"]["initial"], json.dumps(vals, ensure_ascii=False),
                            "{}", user["username"], now, user["username"], now))
        _write_index(conn, cur.lastrowid, module_key, vals)
        _log(conn, cur.lastrowid, "create", "", body["workflow"]["initial"], user["username"])
        conn.commit()
    rec = get_record(conn, module_key, no)
    rec["dropped"] = dropped
    return rec


def update_record(conn, module_key, record_no, values, user) -> dict:
    """只有在起始狀態（草稿）才能改；送出之後內容凍結。"""
    from core.txn import write_txn
    with write_txn(conn):
        rec = _row(conn, module_key, record_no)
        body = _load_def(conn, module_key, rec["def_version"])["body"]
        if rec["status"] != body["workflow"]["initial"]:
            raise CustomModuleError("單據已送出（%s），不能再修改內容" % rec["status"], status=409)
        vals, errors, dropped = clean_values(conn, body, values)
        if errors:
            raise CustomModuleError("有 %d 個欄位不對" % len(errors), errors)
        now = datetime.now().isoformat(timespec="seconds")
        conn.execute("UPDATE custom_records SET data_json=?, updated_by=?, updated_at=? WHERE id=?",
                     (json.dumps(vals, ensure_ascii=False), user["username"], now, rec["id"]))
        _write_index(conn, rec["id"], module_key, vals)
        _log(conn, rec["id"], "update", rec["status"], rec["status"], user["username"])
        conn.commit()
    out = get_record(conn, module_key, record_no)
    out["dropped"] = dropped
    return out


def _state(body, key):
    return next((s for s in body["workflow"]["states"] if s["key"] == key), {})


class _Effects:
    """交易內只收集、commit 之後才送：通知與事件的處理者會另開連線寫 DB，在寫入交易內做會 `database is locked`
    （而 `_notify` 把它吞成 WARNING ⇒ 通知靜默消失）。"""

    def __init__(self):
        self.notices, self.later = [], []

    def append(self, message):
        self.notices.append(message)

    def notify(self, username, type_, ref_id, ref_label, message):
        """站內通知：記下來，commit 之後才寫（`helpers.audit._notify` 自己開連線）。"""
        def _send():
            from helpers.audit import _notify
            _notify(username, type_, ref_id, ref_label, message)
        self.later.append(_send)

    def flush(self):
        import logging
        for fn in self.later:
            try:
                fn()
            except Exception:                              # noqa: BLE001 — 通知失敗不可以讓已 commit 的狀態回報失敗
                logging.getLogger(__name__).exception("自訂模組：交易後的通知／事件失敗")


def _tier_applies(tier, data, notices) -> bool:
    """這一層要不要簽。**只有條件明確不成立才跳過**（False 或數字 0）；
    算出空值（引用的欄位沒填）或公式執行時出錯（例：除以 0）⇒ **照簽**（fail-safe），並在回應裡說明。
    原本：空值被當成不成立而跳過（fail-open）、出錯直接 500（稽核 D 事前提示，2026-09-26）。"""
    cond = tier.get("when")
    if not cond:
        return True
    try:
        v = _fx.evaluate(cond, data)
    except _fx.FormulaError as e:
        notices.append("簽核條件「%s」無法計算（%s）⇒ 這一層照簽" % (cond, e))
        return True
    if v is None:
        notices.append("簽核條件「%s」算不出來（有欄位沒填）⇒ 這一層照簽" % cond)
        return True
    return not (v is False or (isinstance(v, (int, float)) and not isinstance(v, bool) and v == 0))


def _enter_state(conn, body, rec, to_state, user, action, note, notices):
    """改狀態：寫紀錄、進入有簽核的狀態就展開簽核層；所有層的條件都不成立 ⇒ 直接當作通過。"""
    from helpers import tiered_approval as ta
    frm = rec["status"]
    st = _state(body, to_state)
    # 沒有簽核的狀態：保留上一次的簽核紀錄（核准後的輸出要印得出誰簽過）；進入有簽核的狀態才換成新的一輪
    approval = rec.get("approval") or {}
    if st.get("approval"):
        cfg = st["approval"]
        tiers = [t for t in cfg.get("tiers", []) if _tier_applies(t, rec["data"], notices)]
        try:
            active = ta.setting_to_active_tiers({"includeSubmitterManagerTier": bool(cfg.get("includeSubmitterManagerTier")),
                                                 "tiers": tiers}, conn, rec["created_by"])
        except ta.UnresolvedManagerError as e:
            raise CustomModuleError(str(e))
        if not active:
            notices.append("簽核條件都不成立 ⇒ 直接視為通過")
            conn.execute("UPDATE custom_records SET status=? WHERE id=?", (to_state, rec["id"]))
            _log(conn, rec["id"], action, frm, to_state, user["username"], note)
            rec["status"] = to_state
            _published(body, rec, frm, to_state, action, user, notices)
            return _enter_state(conn, body, rec, cfg["on_approved"], user, "auto_approve", "", notices)
        approval = {"state": to_state, "tiers": active, "currentTier": 0, "requestedBy": rec["created_by"],
                    "requestedByDisplay": ta._display_name(conn, rec["created_by"]),
                    "requestedAt": datetime.now().isoformat(timespec="seconds")}
    conn.execute("UPDATE custom_records SET status=?, approval_json=?, updated_by=?, updated_at=? WHERE id=?",
                 (to_state, json.dumps(approval, ensure_ascii=False), user["username"],
                  datetime.now().isoformat(timespec="seconds"), rec["id"]))
    _log(conn, rec["id"], action, frm, to_state, user["username"], note)
    rec["status"], rec["approval"] = to_state, approval
    _published(body, rec, frm, to_state, action, user, notices)
    _notify_state(body, rec, st, approval if st.get("approval") else {}, notices)   # 保留的舊紀錄不再通知簽核人
    return rec


def _published(body, rec, frm, to, action, user, effects):
    from core import events
    payload = {"module": rec["module_key"], "recordNo": rec["record_no"], "from": frm, "to": to,
               "action": action, "by": user["username"]}
    effects.later.append(lambda: events.publish(EVENT_TRANSITIONED, payload))


def _notify_state(body, rec, st, approval, notices):
    label = "%s %s" % (body.get("name", ""), rec["record_no"])
    targets = set()
    n = st.get("notify") or {}
    if n.get("requester"):
        targets.add(rec["created_by"])
    targets.update(u for u in n.get("users", []) if isinstance(u, str))
    if approval:
        tier = approval["tiers"][0]
        fp = next((a for a in tier["approvers"] if a.get("status") != "approved"), None)
        if fp:
            notices.notify(fp["username"], "approval", notify_ref(rec), label, "%s 待您簽核" % label)
            notices.append("已通知 %s 簽核" % fp.get("displayName", fp["username"]))
    for u in sorted(targets):
        msg = "%s 狀態：%s" % (label, st.get("label", st.get("key")))
        notices.notify(u, "info", notify_ref(rec), label, msg)


def transition(conn, module_key, record_no, tkey, user, note="") -> dict:
    """使用者按下轉換按鈕。目前狀態不在該轉換的來源 ⇒ 409；簽核中的狀態不可以用轉換跳過簽核。"""
    from core.txn import write_txn
    notices = _Effects()
    with write_txn(conn):
        rec = _row(conn, module_key, record_no)
        body = _load_def(conn, module_key, rec["def_version"])["body"]
        t = next((x for x in body["workflow"].get("transitions", []) if x.get("key") == tkey), None)
        if t is None:
            raise CustomModuleError("沒有這個動作：%s" % tkey, status=404)
        frs = t["from"] if isinstance(t["from"], list) else [t["from"]]
        if rec["status"] not in frs:
            raise CustomModuleError("目前狀態 %s 不能執行「%s」" % (rec["status"], t.get("label", tkey)), status=409)
        if rec["approval"] and _state(body, rec["status"]).get("approval"):
            raise CustomModuleError("簽核進行中，請用核准／退回", status=409)
        if t.get("requester_only") and user["username"] != rec["created_by"] and user["role"] != "superadmin":
            raise CustomModuleError("只有申請人可以執行「%s」" % t.get("label", tkey), status=403)
        _enter_state(conn, body, rec, t["to"], user, tkey, note, notices)
        conn.commit()
    notices.flush()
    out = get_record(conn, module_key, record_no)
    out["notices"] = notices.notices
    return out


def decide(conn, module_key, record_no, user, approve: bool, note="") -> dict:
    """簽核：沿用 tiered_approval 的規則（依序、代理人、當層任一人可退回）。"""
    from core.txn import write_txn
    from helpers import tiered_approval as ta
    notices = _Effects()
    with write_txn(conn):
        rec = _row(conn, module_key, record_no)
        body = _load_def(conn, module_key, rec["def_version"])["body"]
        cfg = _state(body, rec["status"]).get("approval")
        appr = rec["approval"]
        if not cfg or not appr:
            raise CustomModuleError("這張單據目前不在簽核中", status=409)
        tiers, idx = ta.active_tiers(appr), ta.current_tier_idx(appr)
        now = datetime.now().isoformat(timespec="seconds")
        if approve:
            ok, code, msg = ta.check_approve_permission(tiers, idx, user["username"], conn)
            if not ok:
                raise CustomModuleError(msg, status=code)
            if ta.sign_first_pending(tiers[idx], user, now, conn):
                appr["currentTier"] = idx + 1
            if appr["currentTier"] >= len(tiers):
                conn.execute("UPDATE custom_records SET approval_json=? WHERE id=?",
                             (json.dumps(appr, ensure_ascii=False), rec["id"]))
                rec["approval"] = appr
                _enter_state(conn, body, rec, cfg["on_approved"], user, "approve", note, notices)
            else:
                conn.execute("UPDATE custom_records SET approval_json=?, updated_at=? WHERE id=?",
                             (json.dumps(appr, ensure_ascii=False), now, rec["id"]))
                _log(conn, rec["id"], "approve_tier", rec["status"], rec["status"], user["username"], note)
                nxt = ta.first_pending_approver(tiers[appr["currentTier"]])
                if nxt:
                    label = "%s %s" % (body.get("name", ""), rec["record_no"])
                    notices.notify(nxt["username"], "approval", notify_ref(rec), label, "%s 待您簽核" % label)
        else:
            ok, code, msg = ta.check_reject_permission(tiers, idx, user, conn)
            if not ok:
                raise CustomModuleError(msg, status=code)
            _enter_state(conn, body, rec, cfg["on_rejected"], user, "reject", note, notices)
        conn.commit()
    notices.flush()
    out = get_record(conn, module_key, record_no)
    out["notices"] = notices.notices
    return out


def render_output(conn, module_key, record_no) -> str:
    """單據輸出（HTML；PDF 由呼叫端轉）。用單據凍結的那一版定義的版型；沒有版型 ⇒ 通用的欄位表。"""
    from helpers import doc_template as dt
    rec = get_record(conn, module_key, record_no)
    body = _load_def(conn, module_key, rec["def_version"])["body"]
    return render_view(body, rec["view"])


def render_view(body, view) -> str:
    """版型＋視圖 ⇒ HTML。抬頭／頁尾用公司身分（總公司據點），簽核欄用與財務單據相同的共用元件。"""
    from helpers import doc_template as dt
    import pdf_gen
    ident = pdf_gen.apply_snapshot(pdf_gen.location_identity(pdf_gen._location_of({})), {})
    parts = {"identity_head": lambda: pdf_gen._identity_head(ident),
             "identity_foot": lambda: pdf_gen._identity_foot(ident),
             "approval_sign": lambda: pdf_gen._voucher_sign_html(view.get("approval") or {})}
    tpl = (body.get("output") or {}).get("template") or default_template(body)
    return dt.render(tpl, view, parts)


def default_template(body) -> dict:
    """沒有指定版型時的通用輸出：標題＋編號／狀態＋每個欄位一列。"""
    fmt = {"date": "date10", "number": "str", "formula": "str", "checkbox": "str"}
    fields = [{"label": f.get("label") or f["key"], "path": "fields." + f["key"], "format": fmt.get(f.get("type"), "text")}
              for f in body.get("fields", [])]
    return {"key": "custom_default", "version": 1, "theme": "voucher_standard", "title": {"path": "recordNo", "suffix": " " + body.get("name", "")},
            "blocks": [{"type": "identity_header", "title": body.get("name", "")},
                       {"type": "meta", "fields": [{"label": "編號", "path": "recordNo"}, {"label": "狀態", "path": "statusLabel"},
                                                   {"label": "建立者", "path": "createdBy"}, {"label": "建立時間", "path": "createdAt", "format": "date10"}] + fields},
                       {"type": "approval_sign"}, {"type": "identity_footer"}]}


def notify_ref(rec) -> str:
    """站內通知的 ref_id：`custom:<模組 key>:<單號>`（前端據此開 `module-record` 頁；單號本身不帶模組）。"""
    return "custom:%s:%s" % (rec["module_key"], rec["record_no"])


def queue_items(conn) -> list:
    """IP-10 `approval.queue_items`：簽核中的自訂模組單據，形狀同「待我簽核」佇列的其他類型（`type`＝`custom_record`）。
    只列「目前狀態有簽核、而且還沒簽完」的；誰看得到由佇列那一端的 `_queue_visible_to` 決定。"""
    out, defs = [], {}
    rows = conn.execute("SELECT module_key, record_no, def_version, status, approval_json, created_by, created_at "
                        "FROM custom_records WHERE approval_json != '{}'").fetchall()
    for r in rows:
        key = (r["module_key"], r["def_version"])
        if key not in defs:
            try:
                defs[key] = _load_def(conn, *key)["body"]
            except CustomModuleError:
                defs[key] = None
        body = defs[key]
        if body is None or not _state(body, r["status"]).get("approval"):
            continue
        appr = json.loads(r["approval_json"] or "{}")
        tiers, ct = appr.get("tiers") or [], appr.get("currentTier") or 0
        if ct >= len(tiers):
            continue
        out.append({
            "type": "custom_record", "moduleKey": r["module_key"], "moduleName": body.get("name", ""),
            "quoteNo": r["record_no"], "customer": "", "projectName": body.get("name", ""), "total": 0,
            "quoteDate": (r["created_at"] or "")[:10], "salesPerson": "",
            "requestedBy": appr.get("requestedBy") or r["created_by"],
            "requestedByDisplay": appr.get("requestedByDisplay") or appr.get("requestedBy") or r["created_by"],
            "requestedAt": appr.get("requestedAt") or "", "tiers": tiers, "currentTier": ct, "tierCount": len(tiers),
            "currentApprovers": tiers[ct].get("approvers") or [],
            "statusLabel": _state(body, r["status"]).get("label", r["status"]),
        })
    return out


def _permission_keys() -> list:
    """給權限目錄（helpers.module_registry）：已發布的自訂模組各一個權限 key。定義表還沒建 ⇒ 沒有。"""
    import sqlite3
    from db import get_db
    conn = get_db()
    try:
        return [(m["permission"], m["name"] or m["key"], "自訂模組") for m in published_modules(conn)]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def declare_events():
    from core import events
    events.declare(EVENT_TRANSITIONED, "L1:custom_modules", 1, ("module", "recordNo", "from", "to", "action", "by"),
                   "自訂模組的單據狀態改變（建立以外的每一次轉換、簽核通過／退回）")


declare_events()

from helpers import module_registry as _module_registry  # noqa: E402
_module_registry.register_key_source(_permission_keys)

from core import registry as _registry  # noqa: E402
_registry.provide("approval.queue_items", "custom_modules", queue_items)
