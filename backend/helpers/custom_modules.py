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
import os
import math
import re
from datetime import date, datetime

from core import paths as _paths
from helpers import custom_fields as _cf
from helpers import formula as _fx

KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
STATE_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,29}$")
PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9]{0,5}$")
#: 欄位型別目錄：自訂欄位的型別＋公式（唯讀、由公式算出）＋參照（指到其他資料）
FIELD_TYPES = _cf.MODULE_TYPES + ("formula", "ref", "table", "file", "image")
#: 明細表（`table`）的限制與可用欄型別（W1 建構器第三輪，2026-09-30）
TABLE_MAX_ROWS, TABLE_MAX_COLS = 200, 12
TABLE_COL_TYPES = ("text", "number", "date", "select", "checkbox", "formula")
#: 金流性質（附錄 B）：欄位 `finance.kind`；缺／none ＝不計
FINANCE_KINDS = ("income", "expense")
#: 預設值 token（伺服器在建立單據時決定，不信前端）：`{"$": "today"｜"now"｜"requester"}`
DEFAULT_TOKENS = ("today", "now", "requester")

#: 建構器的元件分組（`fieldElements[].group` 用它）
ELEMENT_GROUPS = [{"id": "basic", "label": "基礎元件"}, {"id": "layout", "label": "版面元件"}, {"id": "org", "label": "組織元件"}, {"id": "advanced", "label": "進階元件"}]
#: 元件列（建構器左欄）：一個元件＝一個型別＋預設屬性（preset）。型別本身一律要在 FIELD_TYPES 內。
FIELD_ELEMENTS = [
    {"id": "text", "type": "text", "label": "單行文字", "group": "basic", "preset": {}},
    {"id": "textarea", "type": "textarea", "label": "多行文字", "group": "basic", "preset": {}},
    {"id": "datetime", "type": "date", "label": "日期時間", "group": "basic", "preset": {"withTime": True}},
    {"id": "date", "type": "date", "label": "日期", "group": "basic", "preset": {}},
    {"id": "daterange", "type": "daterange", "label": "日期時間區間", "group": "basic", "preset": {"withTime": True}},
    {"id": "number", "type": "number", "label": "數字", "group": "basic", "preset": {}},
    {"id": "radio", "type": "radio", "label": "單選", "group": "basic", "preset": {"options": ["選項一", "選項二"]}},
    {"id": "checkboxes", "type": "checkboxes", "label": "複選", "group": "basic", "preset": {"options": ["選項一", "選項二"]}},
    {"id": "select", "type": "select", "label": "下拉單選", "group": "basic", "preset": {"options": ["選項一", "選項二"]}},
    {"id": "multiselect", "type": "multiselect", "label": "下拉複選", "group": "basic", "preset": {"options": ["選項一", "選項二"]}},
    {"id": "checkbox", "type": "checkbox", "label": "勾選（是／否）", "group": "basic", "preset": {}},
    {"id": "table", "type": "table", "label": "明細表", "group": "layout", "preset": {
        "minRows": 0, "maxRows": 200, "addLabel": "新增一列", "columns": [
            {"key": "item", "label": "項目", "type": "text"}, {"key": "qty", "label": "數量", "type": "number"},
            {"key": "price", "label": "單價", "type": "number"}, {"key": "amt", "label": "金額", "type": "formula", "formula": "qty * price"}]}},
    {"id": "formula", "type": "formula", "label": "公式（唯讀）", "group": "advanced", "preset": {}},
    {"id": "ref", "type": "ref", "label": "參照", "group": "advanced", "preset": {}},
    {"id": "file", "type": "file", "label": "附件（檔案）", "group": "advanced", "preset": {}},
    {"id": "image", "type": "image", "label": "圖片", "group": "advanced", "preset": {}},
    {"id": "user", "type": "ref", "label": "人員（單選）", "group": "org", "preset": {"target": "users"}},
    {"id": "users", "type": "ref", "label": "人員（複選）", "group": "org", "preset": {"target": "users", "multiple": True}},
    {"id": "dept", "type": "ref", "label": "部門（單選）", "group": "org", "preset": {"target": "departments"}},
    {"id": "depts", "type": "ref", "label": "部門（複選）", "group": "org", "preset": {"target": "departments", "multiple": True}},
]
#: 每個型別在屬性面板可設的屬性（面板依它產生；kind：text／int／number／bool／options／columns／exts）
FIELD_ATTRS = {
    "text": [("placeholder", "提示語", "text"), ("default", "預設值", "text"), ("maxLength", "最大長度", "int"), ("unique", "不可重複", "bool")],
    "textarea": [("placeholder", "提示語", "text"), ("maxLength", "最大長度", "int")],
    "number": [("placeholder", "提示語", "text"), ("min", "最小值", "number"), ("max", "最大值", "number"), ("unique", "不可重複", "bool")],
    "date": [("withTime", "包含時間", "bool")],
    "daterange": [("withTime", "包含時間", "bool")],
    "radio": [("options", "選項（一行一個）", "options"), ("allowOther", "允許「其他」自己輸入", "bool")],
    "checkboxes": [("options", "選項（一行一個）", "options"), ("allowOther", "允許「其他」自己輸入", "bool"),
                   ("minSelect", "至少選幾項", "int"), ("maxSelect", "最多選幾項", "int")],
    "select": [("options", "選項（一行一個）", "options"), ("allowOther", "允許「其他」自己輸入", "bool")],
    "multiselect": [("options", "選項（一行一個）", "options"), ("allowOther", "允許「其他」自己輸入", "bool"),
                    ("minSelect", "至少選幾項", "int"), ("maxSelect", "最多選幾項", "int")],
    "checkbox": [], "formula": [], "ref": [("multiple", "可複選", "bool")],
    "file": [("accept", "允許的檔案類型（不勾＝全部）", "exts"), ("maxFiles", "最多幾個檔", "int")],
    "image": [("maxFiles", "最多幾張圖", "int")],
    "table": [("columns", "欄位", "columns"), ("minRows", "最少列數", "int"), ("maxRows", "最多列數", "int"), ("addLabel", "新增列按鈕文字", "text")],
}


def field_type_specs() -> dict:
    """給建構器的型別規格：`{型別: {attrs: [{key, label, kind}]}}`（型別清單與屬性面板都由這裡產生，頁面不寫死）。"""
    return {t: {"attrs": [{"key": k, "label": l, "kind": kd} for k, l, kd in FIELD_ATTRS.get(t, [])]} for t in FIELD_TYPES}


# ── 範本（W1 建構器第三輪）：`helpers/form_templates/*.json`，程式出貨的資料；載入時驗證，壞的不列 ─────────────
_TEMPLATE_DIR = _paths.FORM_TEMPLATES_DIR


def templates(include_gaps: bool = False):
    """⇒ `[{key, name, category, description, note, requires}]`（要整份內容用 `template_body`）。
    每個範本載入時用 `validate_module` 驗一次；驗不過或檔案壞掉 ⇒ 不列，`include_gaps=True` 時另回 `[{key, reason}]`。
    `requires`＝範本用到的欄位型別（含明細表欄型別）；有任何型別不在 `FIELD_TYPES` ⇒ 不列（型別就緒的才出現）。"""
    out, gaps = [], []
    for name in sorted(os.listdir(_TEMPLATE_DIR)) if os.path.isdir(_TEMPLATE_DIR) else []:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(_TEMPLATE_DIR, name), encoding="utf-8") as fh:
                t = json.load(fh)
            key, body = t["key"], t["body"]
        except (OSError, ValueError, KeyError, TypeError) as e:
            gaps.append({"key": name, "reason": "範本檔讀不出來：%s" % e})
            continue
        types = sorted({f.get("type") for f in body.get("fields", []) if isinstance(f, dict)} |
                       {c.get("type") for f in body.get("fields", []) if isinstance(f, dict) and f.get("type") == "table"
                        for c in f.get("columns", []) if isinstance(c, dict)})
        if any(x not in FIELD_TYPES + ("formula",) for x in types):
            gaps.append({"key": key, "reason": "用到還沒就緒的型別：%s" % "、".join(x for x in types if x not in FIELD_TYPES)})
            continue
        probs = validate_module(dict(body, permission="custom.%s" % key), key if KEY_RE.match(key) else "")
        if probs:
            gaps.append({"key": key, "reason": "驗證不過：%s" % probs[0]["message"]})
            continue
        out.append({"key": key, "name": t.get("name") or key, "category": t.get("category", ""), "description": t.get("description", ""),
                    "note": t.get("note", ""), "requires": types})
    return (out, gaps) if include_gaps else out


def template_body(key: str):
    """範本的整份定義（深拷貝）；不存在或沒通過載入驗證 ⇒ None。"""
    if not any(t["key"] == key for t in templates()):
        return None
    for name in sorted(os.listdir(_TEMPLATE_DIR)):
        if name.endswith(".json"):
            try:
                with open(os.path.join(_TEMPLATE_DIR, name), encoding="utf-8") as fh:
                    t = json.load(fh)
            except (OSError, ValueError):
                continue
            if isinstance(t, dict) and t.get("key") == key:
                return t["body"]
    return None
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


def register_ref_target(key: str, table: str, label_column: str, id_column: str = "id", modules=None) -> None:
    """`modules`：讀這個對象需要的模組權限（任一即可）；None ＝登入即可。參照選項端點照這個擋（被參照的對象也要有讀取權限）。"""
    _REF_TARGETS[key] = (table, label_column, id_column)
    _REF_TARGET_MODULES[key] = tuple(modules) if modules else None


#: 參照對象 → 讀取它需要的模組權限（None ＝登入即可）
_REF_TARGET_MODULES = {}


def ref_target_modules(target: str):
    """內建參照對象的讀取權限（任一）；None ＝登入即可。`custom:<模組>` 不在這裡（由呼叫端檢查該模組的權限）。"""
    return _REF_TARGET_MODULES.get(target)


def ref_targets() -> dict:
    return {k: {"table": t, "label": l} for k, (t, l, _i) in sorted(_REF_TARGETS.items())}


# 與 routers/customers.py 的讀取權限相同：不可以經參照欄讀到自己沒有權限看的客戶清單
register_ref_target("customers", "customers", "name", modules=("customer", "case_manage", "dev_crm", "procurement"))
register_ref_target("users", "users", "display_name", "username")
register_ref_target("departments", "departments", "name")      # 組織元件（部門）：登入即可讀部門名稱


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
    else:
        from helpers.module_registry import MODULE_KEYS
        if perm in MODULE_KEYS:
            # 稽核 D C-S4：設成內建 key（例 cashier）⇒ 擁有那個內建權限的人全部都能用這個自訂模組
            out.append(_p("permission", "權限 key 不可以用內建模組的 key：%s（建議 custom.%s）" % (perm, key or "<模組>")))
    out += _validate_numbering(body.get("numbering"))
    fields = body.get("fields")
    if not isinstance(fields, list) or not fields:
        out.append(_p("fields", "至少要有一個欄位"))
        fields = []
    out += _validate_fields(fields)
    keys = [f.get("key") for f in fields if isinstance(f, dict)]
    out += _validate_workflow(body.get("workflow"), keys)
    out += _validate_finance([f for f in fields if isinstance(f, dict)], body)
    from . import custom_builder_support as _S
    out += _S.access_problems(body)                       # 可見設定的形狀／角色／必填受限：隨時檢查（建構器即時標出卡片）
    if not out:
        out += _S.leaking_formulas(body)                  # 公式洩漏要公式解析得了才算 ⇒ 前面都對時
    if not out:
        out += _validate_by_sample(body)
    out += _validate_output(body)
    return out


def _validate_by_sample(body):
    """稽核 D C-S1：語法檢查看不出型別錯誤（例 `item > 5`，item 是文字）。用樣本資料實際算一次公式與簽核條件，
    出錯就在發布時指出位置；算出空值不算錯（執行時會照簽，見 _tier_applies）。"""
    out = []
    try:
        vals = sample_values(body)
    except Exception:                                        # noqa: BLE001 — 樣本本身組不出來就不做這一步
        return out
    for i, f in enumerate(body.get("fields", [])):
        if isinstance(f, dict) and f.get("type") == "formula":
            try:
                _fx.evaluate(f.get("formula"), vals)
            except _fx.FormulaError as e:
                out.append(_p("fields[%d].formula" % i, "用樣本資料試算失敗：%s" % e))
    for i, s in enumerate((body.get("workflow") or {}).get("states", [])):
        for j, t in enumerate(((s or {}).get("approval") or {}).get("tiers", []) if isinstance(s, dict) else []):
            if isinstance(t, dict) and t.get("when"):
                try:
                    _fx.evaluate(t["when"], vals)
                except _fx.FormulaError as e:
                    out.append(_p("workflow.states[%d].approval.tiers[%d].when" % (i, j), "用樣本資料試算失敗：%s" % e))
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


#: 欄位說明（`help`）的長度上限（2026-09-27 新增；CORE 1.57）
HELP_MAX = 300


def _validate_fields(fields):
    out, seen = [], set()
    keys = [f.get("key") for f in fields if isinstance(f, dict)]
    for i, f in enumerate(fields):
        p = "fields[%d]" % i
        if not isinstance(f, dict):
            out.append(_p(p, "欄位必須是物件"))
            continue
        k, t = f.get("key"), f.get("type")
        # 欄位選填說明（使用者 2026-09-27；只新增、選填）：文字、最長 HELP_MAX 字
        if "help" in f and f["help"] is not None and (not isinstance(f["help"], str) or len(f["help"]) > HELP_MAX):
            out.append(_p(p + ".help", "說明必須是文字，最長 %d 字" % HELP_MAX))
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
            for prob in _fx.check(f.get("formula"), [x for x in keys if x != k], table_columns(fields)):
                out.append(_p(p + ".formula", "第 %d 字：%s" % (prob["pos"] + 1, prob["message"])))
        elif t == "ref":
            if not _cf.KEY_RE.match(str(k or "")):
                out.append(_p(p + ".key", "key 只能用小寫英文、數字與底線，英文開頭，最長 40 字：%r" % (k,)))
            if not str(f.get("label") or "").strip():
                out.append(_p(p + ".label", "必須有顯示名稱"))
            target = str(f.get("target") or "")
            if not (target in _REF_TARGETS or (target.startswith("custom:") and KEY_RE.match(target[7:]))):
                out.append(_p(p + ".target", "不認得的參照對象 %r（可用：%s、custom:<模組>）" % (target, "、".join(sorted(_REF_TARGETS)))))
            if "multiple" in f and not isinstance(f["multiple"], bool):
                out.append(_p(p + ".multiple", "multiple 要是 true／false"))
        elif t == "table":
            out += _validate_table(p, f)
        elif t in ("file", "image"):
            out += _validate_file_field(p, f)
        else:
            tok = _default_token(f)
            if tok is not None:
                out += _validate_token(p, f, tok)
                f = {k: v for k, v in f.items() if k != "default"}       # token 由伺服器決定，型別驗證不看它
            for prob in _cf.validate_definition({"fields": [f]}, types=_cf.MODULE_TYPES):
                out.append(_p(prob["path"].replace("fields[0]", p, 1), prob["message"]))
    formulas = {f["key"]: f.get("formula") for f in fields if isinstance(f, dict) and f.get("type") == "formula" and f.get("key")}
    try:
        _fx.evaluation_order(formulas)
    except _fx.FormulaError as e:
        out.append(_p("fields", str(e)))
    return out


def _validate_file_field(p, f):
    """附件欄：key／label；`accept` 只能是白名單（jpg／png／pdf）的子集（image 型別只有 jpg／png）；`maxFiles` 1～50。"""
    from . import custom_files as _cfiles
    out = []
    if not _cf.KEY_RE.match(str(f.get("key") or "")):
        out.append(_p(p + ".key", "key 只能用小寫英文、數字與底線，英文開頭，最長 40 字：%r" % (f.get("key"),)))
    if not str(f.get("label") or "").strip():
        out.append(_p(p + ".label", "必須有顯示名稱"))
    acc = f.get("accept")
    if acc is not None:
        base = _cfiles.IMAGE_EXTS if f.get("type") == "image" else _cfiles.ALLOWED_EXTS
        if not isinstance(acc, list) or any(not isinstance(x, str) for x in acc):
            out.append(_p(p + ".accept", "accept 要是副檔名清單"))
        else:
            bad = [x for x in acc if x.strip().lower().lstrip(".") not in base and x.strip()]
            if bad:
                out.append(_p(p + ".accept", "不允許的副檔名：%s（可用：%s）" % ("、".join(bad), "、".join(sorted(set(e for e in base if e != "jpeg"))))))
    mx = f.get("maxFiles")
    if mx is not None and (isinstance(mx, bool) or not isinstance(mx, int) or not 1 <= mx <= 50):
        out.append(_p(p + ".maxFiles", "最多檔數要是 1～50 的整數"))
    if f.get("default") is not None:
        out.append(_p(p + ".default", "附件欄不能設預設值"))
    return out


def _default_token(f):
    """欄位的 `default` 是 `{"$": token}` ⇒ token 字串（可能不合法）；不是 ⇒ None。"""
    d = f.get("default")
    return d.get("$", "") if isinstance(d, dict) else None


def _validate_token(p, f, tok):
    """token 只准用在對應型別：today→date、now→date（含時間）、requester→ref(users)。"""
    ok = {"today": f.get("type") == "date", "now": f.get("type") == "date" and bool(f.get("withTime")),
          "requester": f.get("type") == "ref" and f.get("target") == "users"}.get(tok)
    if tok not in DEFAULT_TOKENS:
        return [_p(p + ".default", "預設值只認得 %s：%r" % ("、".join(DEFAULT_TOKENS), tok))]
    if not ok:
        return [_p(p + ".default", "預設值「%s」不能用在這個型別的欄位" % tok)]
    return []


def _with_default_tokens(body, values, user):
    """建立單據時，把沒填的欄位的 token 預設值換成伺服器當下的值（不信前端）。"""
    values = dict(values) if isinstance(values, dict) else {}
    now = datetime.now()
    for f in body.get("fields", []):
        tok = _default_token(f) if isinstance(f, dict) else None
        if tok is None or values.get(f["key"]) not in (None, ""):
            continue
        if tok == "today":
            values[f["key"]] = now.strftime("%Y-%m-%dT%H:%M") if f.get("withTime") else now.date().isoformat()
        elif tok == "now":
            values[f["key"]] = now.strftime("%Y-%m-%dT%H:%M")
        elif tok == "requester":
            values[f["key"]] = user.get("username")
    return values


def table_columns(fields) -> dict:
    """`{明細表 key: [可加總的數值欄 key…]}`（number 欄與列內公式欄；供公式檢查用）。"""
    out = {}
    for f in fields or []:
        if isinstance(f, dict) and f.get("type") == "table" and f.get("key"):
            out[f["key"]] = [c.get("key") for c in (f.get("columns") or [])
                             if isinstance(c, dict) and c.get("type") in ("number", "formula") and c.get("key")]
    return out


def _validate_table(p, f):
    """明細表欄位：key／label、欄（型別白名單、key 唯一、列內公式只能引用同表的欄）、列數範圍。"""
    out = []
    if not _cf.KEY_RE.match(str(f.get("key") or "")):
        out.append(_p(p + ".key", "key 只能用小寫英文、數字與底線，英文開頭，最長 40 字：%r" % (f.get("key"),)))
    if not str(f.get("label") or "").strip():
        out.append(_p(p + ".label", "必須有顯示名稱"))
    cols = f.get("columns")
    if not isinstance(cols, list) or not cols:
        return out + [_p(p + ".columns", "明細表至少要有一欄")]
    if len(cols) > TABLE_MAX_COLS:
        out.append(_p(p + ".columns", "明細表最多 %d 欄" % TABLE_MAX_COLS))
    seen, ckeys = set(), [c.get("key") for c in cols if isinstance(c, dict)]
    for j, c in enumerate(cols):
        cp = "%s.columns[%d]" % (p, j)
        if not isinstance(c, dict):
            out.append(_p(cp, "欄必須是物件"))
            continue
        ck, ct = c.get("key"), c.get("type")
        if not _cf.KEY_RE.match(str(ck or "")):
            out.append(_p(cp + ".key", "key 只能用小寫英文、數字與底線，英文開頭，最長 40 字：%r" % (ck,)))
        elif ck in seen:
            out.append(_p(cp + ".key", "欄 key 重複：%s" % ck))
        seen.add(ck)
        if not str(c.get("label") or "").strip():
            out.append(_p(cp + ".label", "必須有顯示名稱"))
        if ct not in TABLE_COL_TYPES:
            out.append(_p(cp + ".type", "明細表的欄只能是：%s" % "、".join(TABLE_COL_TYPES)))
        elif ct == "formula":
            for prob in _fx.check(c.get("formula"), [x for x in ckeys if x != ck]):
                out.append(_p(cp + ".formula", "第 %d 字：%s" % (prob["pos"] + 1, prob["message"])))
        else:
            for prob in _cf.validate_definition({"fields": [c]}, types=TABLE_COL_TYPES):
                out.append(_p(prob["path"].replace("fields[0]", cp, 1), prob["message"]))
    forms = {c["key"]: c.get("formula") for c in cols if isinstance(c, dict) and c.get("type") == "formula" and c.get("key")}
    try:
        _fx.evaluation_order(forms)
    except _fx.FormulaError as e:
        out.append(_p(p + ".columns", str(e)))
    for bound, dflt in (("minRows", 0), ("maxRows", TABLE_MAX_ROWS)):
        v = f.get(bound, dflt)
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= TABLE_MAX_ROWS:
            out.append(_p(p + "." + bound, "列數必須是 0～%d 的整數" % TABLE_MAX_ROWS))
    if isinstance(f.get("minRows"), int) and isinstance(f.get("maxRows"), int) and f["minRows"] > f["maxRows"]:
        out.append(_p(p + ".minRows", "最少列數不可大於最多列數"))
    return out


def _validate_finance(fields, body):
    """金流性質（附錄 B）：`finance.kind` 只能掛在 number／formula；日期欄引用 date；案件欄引用 text／ref；要有入帳狀態。"""
    out = []
    by_key = {f.get("key"): f for f in fields if isinstance(f, dict)}
    any_finance = False
    for i, f in enumerate(fields):
        fin = f.get("finance") if isinstance(f, dict) else None
        if fin is None or (isinstance(fin, dict) and fin.get("kind") in (None, "", "none")):
            continue
        p = "fields[%d].finance" % i
        if not isinstance(fin, dict) or fin.get("kind") not in FINANCE_KINDS:
            out.append(_p(p + ".kind", "金流性質只能是 %s 或不計" % "、".join(FINANCE_KINDS)))
            continue
        any_finance = True
        if f.get("type") not in ("number", "formula"):
            out.append(_p(p, "只有數字或公式欄位可以設金流性質"))
        for name, types in (("dateField", ("date",)), ("cashDateField", ("date",)), ("caseField", ("text", "ref")),
                            ("cashAmountField", ("number", "formula"))):
            ref = fin.get(name)
            if ref in (None, ""):
                continue
            tgt = by_key.get(ref)
            if tgt is None or tgt.get("type") not in types:
                out.append(_p(p + "." + name, "%s 必須是%s欄位：%r" % (
                    {"dateField": "歸屬日期", "cashDateField": "現金日期", "caseField": "關聯案件", "cashAmountField": "現金口徑金額"}[name],
                    "日期" if types == ("date",) else ("數字或公式" if name == "cashAmountField" else "文字或參照"), ref)))
    if any_finance:
        states = {s.get("key") for s in (body.get("workflow") or {}).get("states", []) if isinstance(s, dict)}
        ps = (body.get("finance") or {}).get("postStates")
        if ps is not None and (not isinstance(ps, list) or not ps or not set(ps) <= states):
            out.append(_p("finance.postStates", "入帳狀態必須是流程裡存在的狀態"))
        elif ps is None and not _derive_post_states(body):
            out.append(_p("finance.postStates", "有金流欄位，但流程沒有簽核核准後的終態可推導入帳狀態：請指定入帳狀態"))
    return out


def _derive_post_states(body):
    """入帳狀態的預設推導：簽核 `on_approved` 指向的狀態（沒有簽核的模組 ⇒ 空，需指定）。"""
    return sorted({(s.get("approval") or {}).get("on_approved") for s in (body.get("workflow") or {}).get("states", [])
                   if isinstance(s, dict) and (s.get("approval") or {}).get("on_approved")})


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
    # 稽核 D C-S3：起始狀態掛簽核不會生效（單據以起始狀態建立，不會展開簽核）⇒ 發布時擋下
    if initial in by_key and by_key[initial][1].get("approval"):
        out.append(_p("workflow.states[%d].approval" % by_key[initial][0], "起始狀態不可以掛簽核（建立單據時不會展開）；請另設一個送審後的狀態"))
    # 稽核 D C-M3：簽核狀態的 on_approved 互相指向 ⇒ 條件都不成立時會一直自動通過（原本 RecursionError 500）
    nxt = {k: (s.get("approval") or {}).get("on_approved") for k, (_i, s) in by_key.items() if s.get("approval")}
    for start in sorted(nxt):
        path, cur = [start], nxt[start]
        while cur in nxt and cur not in path:
            path.append(cur)
            cur = nxt[cur]
        if cur == start:
            out.append(_p("workflow.states[%d].approval.on_approved" % by_key[start][0],
                          "簽核狀態互相指向，形成循環：%s" % " → ".join(path + [start])))
            break
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


def unique_errors(conn, module_key, body, vals, exclude_id=None) -> list:
    """欄位屬性 `unique`（不可重複）：同一模組其他單據已有相同的值 ⇒ 錯誤。只比 text／number，靠欄位索引。"""
    out = []
    for f in body.get("fields", []):
        if not (isinstance(f, dict) and f.get("unique") and f.get("type") in ("text", "number")):
            continue
        v = vals.get(f["key"])
        if v is None:
            continue
        row = conn.execute("SELECT 1 FROM custom_record_values WHERE module_key=? AND field=? AND value_text=? AND record_id != ? LIMIT 1",
                           (module_key, f["key"], v if isinstance(v, str) else json.dumps(v, ensure_ascii=False),
                            exclude_id if exclude_id is not None else -1)).fetchone()
        if row:
            out.append({"key": f["key"], "message": "%s：已有其他單據使用「%s」" % (f.get("label") or f["key"], v)})
    return out


def clean_table(f: dict, raw) -> tuple:
    """明細表的值 ⇒ `(rows, errors)`。逐列逐欄用同一套 `_coerce`；列內公式在欄位清理後、依引用順序算；
    整列全空的列丟掉；錯誤帶路徑 key（`tbl[3].col`）。"""
    cols = [c for c in f.get("columns") or [] if isinstance(c, dict)]
    label = f.get("label") or f["key"]
    if raw is None or raw == "":
        raw = []
    if not isinstance(raw, list):
        return None, [{"key": f["key"], "message": "%s：必須是列的清單" % label}]
    errors, rows = [], []
    forms = {c["key"]: c["formula"] for c in cols if c.get("type") == "formula"}
    order = _fx.evaluation_order(forms) if forms else []
    for i, r in enumerate(raw):
        if not isinstance(r, dict):
            errors.append({"key": "%s[%d]" % (f["key"], i), "message": "%s 第 %d 列：必須是物件" % (label, i + 1)})
            continue
        row = {}
        for c in cols:
            if c.get("type") == "formula":
                continue
            v = r.get(c["key"])
            if (v is None or v == "") and "default" in c:
                v = c["default"]
            ok, val, msg = _cf._coerce(c, v)
            if not ok:
                errors.append({"key": "%s[%d].%s" % (f["key"], i, c["key"]),
                               "message": "%s 第 %d 列 %s：%s" % (label, i + 1, c.get("label") or c["key"], msg)})
            elif val is None:
                if c.get("required") and any(x not in (None, "") for x in r.values()):
                    errors.append({"key": "%s[%d].%s" % (f["key"], i, c["key"]),
                                   "message": "%s 第 %d 列 %s：必填" % (label, i + 1, c.get("label") or c["key"])})
            else:
                row[c["key"]] = val
        if not row:
            continue                                             # 整列空白 ⇒ 不收
        for k in order:
            try:
                row[k] = _fx.evaluate(forms[k], row)
                if isinstance(row[k], float) and not math.isfinite(row[k]):
                    raise _fx.FormulaError("結果不是有限的數字")
            except _fx.FormulaError as e:
                row[k] = None
                errors.append({"key": "%s[%d].%s" % (f["key"], i, k),
                               "message": "%s 第 %d 列：公式無法計算（%s）" % (label, i + 1, e)})
        rows.append(row)
    mx = f.get("maxRows", TABLE_MAX_ROWS)
    mn = f.get("minRows", 0) or (1 if f.get("required") else 0)
    if len(rows) > mx:
        errors.append({"key": f["key"], "message": "%s：最多 %d 列" % (label, mx)})
    if len(rows) < mn:
        errors.append({"key": f["key"], "message": "%s：至少 %d 列" % (label, mn)})
    return rows, errors


def clean_values(conn, body: dict, values) -> tuple:
    """回 `(乾淨的值（含公式結果）, 錯誤, 丟掉的鍵)`。公式欄位不收輸入（送了也丟掉並回報）。"""
    values = values if isinstance(values, dict) else {}
    tables = [f for f in _input_fields(body) if f.get("type") == "table"]
    multi_refs = [f for f in _input_fields(body) if f.get("type") == "ref" and f.get("multiple")]
    file_fields = [f for f in _input_fields(body) if f.get("type") in ("file", "image")]
    plain = [dict(f, type="text") if f.get("type") == "ref" else f for f in _input_fields(body)
             if f.get("type") not in ("table", "file", "image") and not (f.get("type") == "ref" and f.get("multiple"))]
    plain = [{k: v for k, v in f.items() if not (k == "default" and isinstance(v, dict))} for f in plain]      # token 預設在 create_record 換掉
    out, errors, dropped = _cf.clean(values, {"fields": plain})
    dropped = [k for k in dropped if k not in {t["key"] for t in tables}]
    for t in tables:
        rows, terr = clean_table(t, values.get(t["key"]))
        errors += terr
        if rows:
            out[t["key"]] = rows
    from . import custom_files as _cfiles
    for f in file_fields:
        ids, ferrs = _cfiles.clean_ids(f, values.get(f["key"]))
        errors += ferrs
        if ids:
            out[f["key"]] = ids
    for f in multi_refs:
        picked, rerrs = _clean_multi_ref(conn, f, values.get(f["key"]))
        errors += rerrs
        if picked:
            out[f["key"]] = picked
    for f in _input_fields(body):
        if f.get("type") == "ref" and not f.get("multiple") and out.get(f["key"]) is not None:
            if not _ref_exists(conn, f["target"], out[f["key"]]):
                errors.append({"key": f["key"], "message": "%s：參照不到 %s" % (f.get("label") or f["key"], out[f["key"]])})
    computed, ferrors = compute(body, out)
    return computed, errors + ferrors, dropped


def _clean_multi_ref(conn, f, raw):
    """複選參照（人員／部門）⇒ (去重後的代號清單, 錯誤)。每一個都要參照得到；必填＝至少一個；不是清單 ⇒ 錯。"""
    label = f.get("label") or f["key"]
    if raw is None or raw == "" or raw == []:
        return [], ([{"key": f["key"], "message": "%s：必填" % label}] if f.get("required") else [])
    if not isinstance(raw, list) or any(isinstance(x, (dict, list, bool)) or x is None for x in raw):
        return [], [{"key": f["key"], "message": "%s：要是代號清單" % label}]
    seen, picked = set(), []
    for x in raw:
        s = str(x).strip()
        if s and s not in seen:
            seen.add(s)
            picked.append(s)
    errors = [{"key": f["key"], "message": "%s：參照不到 %s" % (label, s)} for s in picked if not _ref_exists(conn, f["target"], s)]
    return picked, errors


def ref_labels(conn, body: dict, data: dict) -> dict:
    """單據裡參照欄的顯示名稱 `{欄位: 名稱或名稱清單}`（單據檢視用；查不到的代號原樣保留）。"""
    out = {}
    for f in body.get("fields", []):
        if not isinstance(f, dict) or f.get("type") != "ref" or data.get(f["key"]) in (None, "", []):
            continue
        v = data[f["key"]]
        one = lambda x, t=f["target"]: _ref_label(conn, t, x)
        out[f["key"]] = [one(x) for x in v] if isinstance(v, list) else one(v)
    return out


def _ref_label(conn, target, value):
    if target.startswith("custom:") or target not in _REF_TARGETS:
        return str(value)
    table, label, idc = _REF_TARGETS[target]
    r = conn.execute("SELECT %s AS l FROM %s WHERE %s=?" % (label, table, idc), (value,)).fetchone()
    return (r["l"] if r and r["l"] else str(value))


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
            if isinstance(out[k], float) and not math.isfinite(out[k]):
                raise _fx.FormulaError("結果不是有限的數字")
        except _fx.FormulaError as e:
            out[k] = None
            errors.append({"key": k, "message": "%s：公式無法計算（%s）" % (formulas[k].get("label") or k, e)})
    return out, errors


_SAMPLES = {"text": "範例文字", "textarea": "範例文字", "number": 1, "date": "2026-09-25", "checkbox": True}


def _sample_of(f):
    t = f.get("type")
    if t in ("select", "radio"):
        return (f.get("options") or ["選項"])[0]
    if t in ("checkboxes", "multiselect"):
        return [(f.get("options") or ["選項"])[0]]
    if t == "daterange":
        return {"from": "2026-09-25T09:00" if f.get("withTime") else "2026-09-25",
                "to": "2026-09-26T18:00" if f.get("withTime") else "2026-09-26"}
    if t == "date" and f.get("withTime"):
        return "2026-09-25T09:00"
    if t == "ref" and f.get("multiple"):
        return ["範例"]
    if t in ("file", "image"):
        return []
    return _SAMPLES.get(t, "範例")


def sample_values(body: dict) -> dict:
    """每個輸入欄位一個樣本值（依型別）＋公式算出的值。明細表給一列樣本（列內公式也算）。"""
    vals = {}
    for f in _input_fields(body):
        if f.get("type") == "table":
            row = {c["key"]: _sample_of(c) for c in f.get("columns") or [] if isinstance(c, dict) and c.get("type") != "formula"}
            rows, _e = clean_table(dict(f, required=False, minRows=0), [row])
            vals[f["key"]] = rows or []
        else:
            vals[f["key"]] = _sample_of(f)
    vals, _e = compute(body, vals)
    return vals


def sample_view(body: dict) -> dict:
    """給輸出預覽與版型驗證用的樣本視圖（與 record_view 同形）。"""
    return _sample_view_of(body, sample_values(body))


def _sample_view_of(body, vals):
    """樣本視圖：給定欄位值，其餘（編號、狀態、建立者、時間）用固定的樣本。"""
    numbering = body.get("numbering") or {"prefix": "X"}
    try:
        no = format_number(numbering, date(2026, 9, 25), 1)
    except (KeyError, TypeError, ValueError):
        no = "X-0001"
    wf = body.get("workflow") or {}
    return _view(body, {"record_no": no, "status": wf.get("initial") or "", "created_by": "範例使用者",
                        "created_at": "2026-09-25T09:00:00", "approval": {}}, vals)


_FIELD_PROBLEM_RE = re.compile(r"^fields\[(\d+)\]")


def preview_output(body: dict) -> tuple:
    """建構器即時預覽（BUILDER-UX §3.4）：編到一半的草稿也要畫得出來 ⇒ 回 `(html, 未完成清單)`。

    - 輸出一律走正式匯出的 `render_view`（同一個 renderer、同一份版型）——不另寫預覽版。
    - 未完成的欄位（沒有 key、公式空白或錯誤、選單沒有選項、型別不認得…）換成文字佔位「〈名稱〉尚未完成」照畫，
      並列進未完成清單；編號規則未完成 ⇒ 用樣本編號照畫。
    - 連一個完成的欄位都沒有 ⇒ CustomModuleError（422）；版型本身結構錯（未知積木／主題）同樣 422（版型編輯器要看到錯在哪）。
    """
    fields = body.get("fields") if isinstance(body.get("fields"), list) else []
    probs = _validate_fields(fields)
    by_idx = {}
    for p in probs:
        m = _FIELD_PROBLEM_RE.match(p["path"])
        if m:
            by_idx.setdefault(int(m.group(1)), p["message"])
        elif p["path"] == "fields":                              # 公式互相引用成環 ⇒ 所有公式欄都算不出來
            for i, f in enumerate(fields):
                if isinstance(f, dict) and f.get("type") == "formula":
                    by_idx.setdefault(i, p["message"])
    shown, placeholders, used = [], {}, set()
    for i, f in enumerate(fields):
        label = str((f.get("label") if isinstance(f, dict) else "") or "").strip() or "第 %d 個欄位" % (i + 1)
        k = f.get("key") if isinstance(f, dict) else None
        ok_key = isinstance(k, str) and KEY_RE.match(k) and k not in used
        if i in by_idx:
            k = k if ok_key else "_incomplete_%d" % (i + 1)
            placeholders[k] = (i, label, by_idx[i])
            shown.append({"key": k, "label": label, "type": "text"})
        else:
            shown.append(f)
        used.add(k)
    if len(placeholders) == len(shown):
        raise CustomModuleError("還沒有可以預覽的欄位" if not shown else "所有欄位都尚未完成",
                                problems=[{"path": "fields[%d]" % i, "message": msg} for i, _l, msg in placeholders.values()] or
                                [{"path": "fields", "message": "至少要有一個欄位"}], status=422)
    wf = body.get("workflow") if isinstance(body.get("workflow"), dict) else {}
    out = body.get("output")
    if out is not None and not isinstance(out, dict):             # 輸出設定壞了 ⇒ 用通用版型照畫、列進清單
        out = None
    rb = dict(body, fields=shown, name=str(body.get("name") or ""), output=out,
              numbering=body.get("numbering") if isinstance(body.get("numbering"), dict) else {"prefix": "X"},
              workflow=dict(wf, states=[s for s in (wf.get("states") if isinstance(wf.get("states"), list) else []) if isinstance(s, dict)]))
    vals = {}
    for f in _input_fields(rb):
        t = f.get("type")
        vals[f["key"]] = (f.get("options") or ["選項"])[0] if t == "select" else _SAMPLES.get(t, "範例")
    vals, errors = compute(rb, vals)
    for e in errors:                                             # 語法對、用樣本算不出來（型別不合、除以 0…）
        i = next(j for j, f in enumerate(shown) if f.get("key") == e["key"])
        placeholders[e["key"]] = (i, shown[i].get("label") or e["key"], e["message"])
    for k, (_i, label, _m) in placeholders.items():
        vals[k] = "〈%s〉尚未完成" % label
    incomplete = [{"path": "fields[%d]" % i, "field": k if not k.startswith("_incomplete_") else None, "label": label, "message": msg}
                  for k, (i, label, msg) in sorted(placeholders.items(), key=lambda kv: kv[1][0])]
    incomplete += [{"path": p["path"], "message": p["message"]} for p in _validate_numbering(body.get("numbering"))]
    if body.get("output") is not None and out is None:
        incomplete.append({"path": "output", "message": "輸出設定必須是物件：暫以通用版型顯示"})
    view = _sample_view_of(rb, vals)
    tpl = (rb.get("output") or {}).get("template") if isinstance(rb.get("output"), dict) else None
    if tpl is not None:
        from helpers import doc_template as dt
        if not isinstance(tpl, dict):
            raise CustomModuleError("輸出版型有問題", problems=[_p("output.template", "輸出版型必須是 JSON 物件")], status=422)
        tp = dt.problems(tpl, view)
        broken = [p for p in tp if p["path"].endswith(".type") or p["path"] == "theme"]
        if broken:
            raise CustomModuleError("輸出版型有問題", problems=[_p("output.template." + p["path"], p["message"]) for p in broken], status=422)
        incomplete += [{"path": "output.template." + p["path"], "message": p["message"]} for p in tp]
    return render_view(rb, view), incomplete


def _is_unapproved(body, status) -> bool:
    """單據是否「尚未核可」（輸出紅色警示用）：模組有簽核狀態，而單據的目前狀態不在「簽核通過後可到達」的狀態集合裡
    （草稿、簽核中、被退回都算未核可；核可後的狀態與其後續狀態不算）。沒有任何簽核的模組 ⇒ False。"""
    wf = body.get("workflow") or {}
    states = [s for s in wf.get("states", []) if isinstance(s, dict)]
    approved = {(s.get("approval") or {}).get("on_approved") for s in states if s.get("approval")} - {None}
    if not approved:
        return False
    nxt = {}
    for t in wf.get("transitions", []):
        if isinstance(t, dict):
            nxt.setdefault(t.get("from"), set()).add(t.get("to"))
    seen, todo = set(), list(approved)
    while todo:
        k = todo.pop()
        if k in seen:
            continue
        seen.add(k)
        todo.extend(nxt.get(k, ()))
    return status not in seen


def _view(body, rec, vals):
    labels = {s.get("key"): s.get("label") for s in (body.get("workflow") or {}).get("states", []) if isinstance(s, dict)}
    return {"recordNo": rec["record_no"], "status": rec["status"], "statusLabel": labels.get(rec["status"], rec["status"]),
            "createdBy": rec.get("created_by", ""), "createdAt": rec.get("created_at", ""), "moduleName": body.get("name", ""),
            "fields": vals, "approval": rec.get("approval") or {}, **vals,
            "unapproved": _is_unapproved(body, rec["status"])}


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


def visible_to(mods, user) -> list:
    """published_modules() 的結果 ⇒ 這位使用者看得到的（最高管理者全部；其他人要有該模組的 permission）。
    唯一一份：`GET /api/custom-modules` 與 `GET /api/platform/menu`（C4 選單）共用。"""
    if user.get("role") == "superadmin":
        return list(mods)
    from .custom_builder_support import can_see_menu       # menu.visibleTo（角色／帳號，後端強制）
    try:
        mine = set(json.loads(user.get("modules") or "[]"))
    except (TypeError, ValueError):
        mine = set()
    return [m for m in mods if m.get("permission") in mine and can_see_menu(m.get("menu"), user)]


def permission_of(module_key, body) -> str:
    return body.get("permission") or "custom.%s" % module_key


def _dump_values(vals) -> str:
    """寫入 data_json：非有限數字一律拒絕（稽核 D C-M5 第二道防線；第一道是 custom_fields._coerce）。
    json.dumps 預設會寫出非標準的 NaN ⇒ 之後讀單與整個列表都 500；在交易內擋下 ⇒ 什麼都不寫。"""
    try:
        return json.dumps(vals, ensure_ascii=False, allow_nan=False)
    except ValueError:
        raise CustomModuleError("欄位值不可以是 NaN 或無限大",
                                [{"key": k, "message": "不可以是 NaN 或無限大"} for k, v in vals.items()
                                 if isinstance(v, float) and not math.isfinite(v)])


def _finite(v):
    """讀出時把非有限的數字換成空值（修正前可能已寫進 NaN／inf；JSON 不能序列化它們）。"""
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if isinstance(v, dict):
        return {k: _finite(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_finite(x) for x in v]
    return v


def _row(conn, module_key, record_no):
    r = conn.execute("SELECT * FROM custom_records WHERE module_key=? AND record_no=?", (module_key, record_no)).fetchone()
    if r is None:
        raise CustomModuleError("找不到單據 %s" % record_no, status=404)
    d = dict(r)
    d["data"] = _finite(json.loads(d.pop("data_json") or "{}"))
    d["approval"] = json.loads(d.pop("approval_json") or "{}")
    return d


def _write_index(conn, rec_id, module_key, vals):
    conn.execute("DELETE FROM custom_record_values WHERE record_id=?", (rec_id,))
    for k, v in vals.items():
        if v is None:
            continue
        num = v if isinstance(v, (int, float)) and not isinstance(v, bool) else None
        text = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
        if isinstance(v, list) and v and isinstance(v[0], dict):     # 明細表：索引只記列數，不把整份 JSON 放進 value_text
            num, text = len(v), "%d 筆" % len(v)
        conn.execute("INSERT INTO custom_record_values (record_id, module_key, field, value_text, value_num) VALUES (?,?,?,?,?)",
                     (rec_id, module_key, k, text, num))


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


def compute_preview(conn, module_key, values, version=None) -> dict:
    """填單時即時算：同一套 `clean_values`（所以與存檔算出來的一定一樣），但**不存檔、不查必填**。
    回 `{computed: {公式欄: 值}, tables: {明細表: 算好列內公式的列}, errors: [公式相關錯誤]}`；
    公式無法算（缺欄位、除以 0）⇒ 該欄為空並回報，不丟例外。"""
    body = _load_def(conn, module_key, version)["body"]
    vals, errors, _dropped = clean_values(conn, body, values)
    formulas = {f["key"] for f in body.get("fields", []) if isinstance(f, dict) and f.get("type") == "formula"}
    tables = {f["key"] for f in body.get("fields", []) if isinstance(f, dict) and f.get("type") == "table"}
    return {"computed": {k: vals.get(k) for k in formulas}, "tables": {k: vals.get(k) or [] for k in tables},
            "errors": [e for e in errors if "公式" in e["message"]]}


def get_record(conn, module_key, record_no) -> dict:
    rec = _row(conn, module_key, record_no)
    d = _load_def(conn, module_key, rec["def_version"])
    rec["view"] = _view(d["body"], rec, rec["data"])
    # 單據凍結在建立時的定義版本 ⇒ 畫面的標籤、欄位與按鈕要用這一版，不是最新版
    rec["definition"] = d["body"]
    rec["refLabels"] = ref_labels(conn, d["body"], rec["data"])
    from . import custom_history as _hist
    rec["displayNo"] = _hist.display_no(rec)
    if rec["displayNo"] != rec["record_no"]:                   # 輸出／視圖的單號帶 -R<n>（record_no 本身不變）
        rec["view"] = dict(rec["view"], recordNo=rec["displayNo"], baseRecordNo=rec["record_no"])
    from . import custom_files as _cfiles
    rec["fileMeta"] = _cfiles.files_of_field(conn, module_key, d["body"], rec["data"])
    if rec["fileMeta"]:                              # 輸出／視圖只放檔名（不放路徑與連結）
        names = _cfiles.view_names(d["body"], rec["fileMeta"])
        vf = dict(rec["view"]["fields"])
        vf.update(names)
        v = dict(rec["view"])
        v["fields"] = vf
        v.update(names)
        rec["view"] = v
    rec["log"] = [dict(r) for r in conn.execute("SELECT action, from_state, to_state, by_user, note, at FROM custom_record_log "
                                                 "WHERE record_id=? ORDER BY id", (rec["id"],)).fetchall()]
    return rec


def list_records(conn, module_key, status=None, field=None, value=None, limit=200) -> list:
    sql = "SELECT r.record_no, r.status, r.def_version, r.created_by, r.created_at, r.updated_at, r.data_json, r.revision FROM custom_records r"
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
        d["data"] = _finite(json.loads(d.pop("data_json") or "{}"))
        d["displayNo"] = d["record_no"] + ("-R%d" % d["revision"] if d.get("revision") else "")
        out.append(d)
    return out


def create_record(conn, module_key, values, user) -> dict:
    from core.txn import write_txn
    d = _load_def(conn, module_key)
    body = d["body"]
    values = _with_default_tokens(body, values, user)
    vals, errors, dropped = clean_values(conn, body, values)
    errors = errors + unique_errors(conn, module_key, body, vals)
    from . import custom_files as _cfiles
    errors = errors + _cfiles.check_files(conn, module_key, body, vals, user["username"])
    if errors:
        raise CustomModuleError("有 %d 個欄位不對" % len(errors), errors)
    now = datetime.now().isoformat(timespec="seconds")
    with write_txn(conn):
        no = next_number(conn, module_key, body["numbering"])
        cur = conn.execute("INSERT INTO custom_records (module_key, record_no, def_version, status, data_json, approval_json, "
                           "created_by, created_at, updated_by, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                           (module_key, no, d["version"], body["workflow"]["initial"], _dump_values(vals),
                            "{}", user["username"], now, user["username"], now))
        _write_index(conn, cur.lastrowid, module_key, vals)
        _cfiles.bind_files(conn, module_key, body, vals, cur.lastrowid)
        _log(conn, cur.lastrowid, "create", "", body["workflow"]["initial"], user["username"])
        conn.commit()
    rec = get_record(conn, module_key, no)
    rec["dropped"] = dropped
    return rec


def can_edit_draft(rec, body, user) -> bool:
    """U14（使用者 2026-09-26 裁示）：草稿（起始狀態）只有建立者與超級管理員可以修改、送出；同權限的其他人只能看。"""
    if rec["status"] != body["workflow"]["initial"]:
        return False
    return user.get("role") == "superadmin" or user.get("username") == rec.get("created_by")


def _require_draft_owner(rec, body, user):
    if rec["status"] == body["workflow"]["initial"] and not can_edit_draft(rec, body, user):
        raise CustomModuleError("這張草稿只有建立者（%s）或超級管理員可以修改、送出" % rec.get("created_by"), status=403)


def update_record(conn, module_key, record_no, values, user) -> dict:
    """只有在起始狀態（草稿）才能改；送出之後內容凍結。"""
    from core.txn import write_txn
    with write_txn(conn):
        rec = _row(conn, module_key, record_no)
        body = _load_def(conn, module_key, rec["def_version"])["body"]
        if rec["status"] != body["workflow"]["initial"]:
            raise CustomModuleError("單據已送出（%s），不能再修改內容" % rec["status"], status=409)
        _require_draft_owner(rec, body, user)
        vals, errors, dropped = clean_values(conn, body, values)
        errors = errors + unique_errors(conn, module_key, body, vals, exclude_id=rec["id"])
        from . import custom_files as _cfiles
        errors = errors + _cfiles.check_files(conn, module_key, body, vals, user["username"], rec["id"])
        if errors:
            raise CustomModuleError("有 %d 個欄位不對" % len(errors), errors)
        now = datetime.now().isoformat(timespec="seconds")
        conn.execute("UPDATE custom_records SET data_json=?, updated_by=?, updated_at=? WHERE id=?",
                     (_dump_values(vals), user["username"], now, rec["id"]))
        _write_index(conn, rec["id"], module_key, vals)
        doomed = _cfiles.bind_files(conn, module_key, body, vals, rec["id"], previous=rec["data"])
        _log(conn, rec["id"], "update", rec["status"], rec["status"], user["username"])
        conn.commit()
    _cfiles.remove_files(doomed)
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


#: 一次動作裡「自動通過」最多連跳幾個狀態（稽核 D C-M3：互相指向 ⇒ 無限遞迴 500）
_MAX_AUTO_HOPS = 20


def _enter_state(conn, body, rec, to_state, user, action, note, notices, _hops=0):
    """改狀態：寫紀錄、進入有簽核的狀態就展開簽核層；所有層的條件都不成立 ⇒ 直接當作通過。"""
    from helpers import tiered_approval as ta
    from . import custom_history as _hist
    frm = rec["status"]
    st = _state(body, to_state)
    if action in ("approve", "reject", "auto_approve") and _state(body, frm).get("approval"):
        _hist.on_decided(conn, rec, "rejected" if action == "reject" else "approved", user, note)      # 送簽修訂紀錄：回填這次送簽的決定
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
            _finance_hook(conn, body, rec, frm, to_state)
            if _hops >= _MAX_AUTO_HOPS:
                raise CustomModuleError("流程設定有循環：簽核條件都不成立的狀態互相自動通過（超過 %d 次），請修正流程定義"
                                        % _MAX_AUTO_HOPS, status=409)
            return _enter_state(conn, body, rec, cfg["on_approved"], user, "auto_approve", "", notices, _hops + 1)
        approval = {"state": to_state, "tiers": active, "currentTier": 0, "requestedBy": rec["created_by"],
                    "requestedByDisplay": ta._display_name(conn, rec["created_by"]),
                    "requestedAt": datetime.now().isoformat(timespec="seconds")}
    conn.execute("UPDATE custom_records SET status=?, approval_json=?, updated_by=?, updated_at=? WHERE id=?",
                 (to_state, json.dumps(approval, ensure_ascii=False), user["username"],
                  datetime.now().isoformat(timespec="seconds"), rec["id"]))
    _log(conn, rec["id"], action, frm, to_state, user["username"], note)
    rec["status"], rec["approval"] = to_state, approval
    if st.get("approval") and approval.get("tiers"):
        _hist.on_submitted(conn, rec, user)                    # 送簽：寫快照、修訂號＝已送簽次數−1（首次不帶 -R）
    _published(body, rec, frm, to_state, action, user, notices)
    _finance_hook(conn, body, rec, frm, to_state)
    _notify_state(body, rec, st, approval if st.get("approval") else {}, notices)   # 保留的舊紀錄不再通知簽核人
    return rec


def _finance_hook(conn, body, rec, frm, to):
    """金流事件（outbox）：進入／離開入帳狀態時，與狀態變更同一個交易寫入（helpers.custom_finance）。"""
    from . import custom_finance as _cfin
    _cfin.on_transition(conn, body, rec, frm, to)


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
        _require_draft_owner(rec, body, user)
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
    html = dt.render(tpl, view, parts)
    # 核可狀態由程式決定、不由版型決定：單據目前停在「需要簽核」的狀態 ⇒ 紅色警示（冪等）
    return dt.inject_unapproved(html, view.get("statusLabel") or view.get("status"), "此單據尚未核可") if view.get("unapproved") else html


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
        from helpers.approval_queue import approval_raw_of
        raw = approval_raw_of(r["approval_json"], "custom_record", r["record_no"])   # 壞一筆只跳過那一筆（QJ-M1）
        if raw is None:
            continue
        appr = json.loads(raw)
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
