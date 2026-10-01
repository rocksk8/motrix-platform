# -*- coding: utf-8 -*-
"""費用單據的「類型定義」（A2-2）：請購單／採購單／差旅費用請款單／零用金支付單各是一份 `expense_type` 定義。

[單位] helper:expense_types    [層] L1    [穩定度] 契約（改介面照 PLAYBOOK §C-7 升版）
[公開介面] CODE_RE, DEFAULT_KINDS, KIND, MAX_LINES, MAX_TEXT, PREFIX_RE, RESERVED_KEYS, cashier_field_keys, get_type, list_types, normalize_lines, validate_expense_type, validate_values
[不變式] 明細金額與合計只在 `normalize_lines` 算一次（W1 §7.1；整數 TWD、每列 round_half_up）；`validate_values` 不丟任何未知的明細鍵
[契約題] tests/platform/test_expense_types_2026_10_01.py

定義本文與 API 契約：`D:\\開發測試檔\\plan-expense-a2.md` §7／§8。定義存在定義文件庫（`core.definitions`，kind＝`expense_type`，
key＝類型代碼）：有草稿、版本、差異、還原；沒有發布版時用程式預設（`helpers/expense_type_defs/<代碼>.json`，版本 0）。
單據建立時把 `def_version` 釘在列上，之後定義改了，舊單據仍依它自己的版本驗證與輸出。

驗證與轉型**重用**建構器那一份（`custom_modules._validate_fields`／`clean_values`）；這裡只加費用單據專屬的規則：
編號前綴、`payable`、`lines` 明細表的欄位規則、平台保留鍵的型別、`locked`（預填鎖定）與 `editableBy:"cashier"`。
"""
import copy
import json
import os
import re
from datetime import date

from core import definitions as D
from core import paths as _paths
from helpers.legal_params import round_half_up

KIND = "expense_type"
DEFAULT_KINDS = ("purchase_req", "purchase_order", "travel", "petty_cash")
_DEFS_DIR = _paths.backend("helpers", "expense_type_defs")
CODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9]{0,3}$")
#: 平台保留的 `data` 鍵 ⇒ (型別, 參照對象)；定義可以放，型別固定（plan §7.2）
RESERVED_KEYS = {"applicant": ("ref", "users"), "dept": ("ref", "departments"), "cost_dept": ("ref", "departments"),
                 "req_date": ("date", None), "pay_date": ("date", None), "urgency": ("select", None),
                 "pay_terms": ("text", None), "remit_date": ("date", None)}
_URGENCY = ["一般", "急件", "特急"]
MAX_LINES = 200
MAX_TEXT = 500


def _p(path, message):
    return {"path": path, "message": message}


# ── 程式預設 ────────────────────────────────────────────────────────────────

def _default_for(key):
    if key not in DEFAULT_KINDS:
        return None
    with open(os.path.join(_DEFS_DIR, key + ".json"), encoding="utf-8") as f:
        return json.load(f)


# ── 定義驗證 ────────────────────────────────────────────────────────────────

#: 明細欄的 key 是 camelCase（與既有額外支出明細一致，plan §7.1），而建構器的通用驗證只收小寫底線 key ⇒
#: 送進通用驗證前後互轉（只在這一個檔案內；不放寬建構器的 key 規則，避免影響其他 kind）
_SNAKE = {"unitCost": "unit_cost", "invoiceNo": "invoice_no"}
_CAMEL = {v: k for k, v in _SNAKE.items()}


def _snake_text(s):
    for c, sn in _SNAKE.items():
        s = re.sub(r"\b%s\b" % c, sn, s)
    return s


def _camel_text(s):
    for sn, c in _CAMEL.items():
        s = s.replace(sn, c)
    return s


def _generic(body):
    """費用單據專屬屬性拿掉、`optionsFrom` 的下拉當文字 ⇒ 交給建構器的通用驗證／轉型（類別是否有效由送審時的 `expense.categories` 查）。"""
    g = copy.deepcopy(body)
    for f in g.get("fields") or []:
        if not isinstance(f, dict):
            continue
        f.pop("locked", None)
        f.pop("editableBy", None)
        if f.get("type") == "table":
            f.pop("addLabel", None)
            for c in f.get("columns") or []:
                if not isinstance(c, dict):
                    continue
                if c.get("optionsFrom"):
                    c.pop("optionsFrom")
                    c["type"] = "text"
                if c.get("key") in _SNAKE:
                    c["key"] = _SNAKE[c["key"]]
                if isinstance(c.get("formula"), str):
                    c["formula"] = _snake_text(c["formula"])
    return g


def _lines_problems(f, p):
    out = []
    cols = [c for c in (f.get("columns") or []) if isinstance(c, dict)]
    keys = {c.get("key") for c in cols}
    for need in ("category", "summary", "amount"):
        if need not in keys:
            out.append(_p(p + ".columns", "明細必須有欄位 %s" % need))
    if ("qty" in keys) != ("unitCost" in keys):
        out.append(_p(p + ".columns", "數量（qty）與單價（unitCost）必須一起出現"))
    for c in cols:
        if c.get("key") == "amount" and c.get("type") not in ("number", "formula"):
            out.append(_p(p + ".columns", "amount 欄必須是 number 或 formula"))
        if c.get("key") in ("qty", "unitCost") and c.get("type") != "number":
            out.append(_p(p + ".columns", "%s 欄必須是 number" % c.get("key")))
    if not isinstance(f.get("minRows", 1), int) or f.get("minRows", 1) < 1:
        out.append(_p(p + ".minRows", "明細至少要 1 列（minRows ≥ 1）"))
    return out


def _field_problems(fields):
    out, lines_seen = [], 0
    for i, f in enumerate(fields):
        if not isinstance(f, dict):
            continue
        p, k = "fields[%d]" % i, f.get("key")
        if "locked" in f and not isinstance(f["locked"], bool):
            out.append(_p(p + ".locked", "locked 要是 true／false"))
        if f.get("editableBy") not in (None, "cashier"):
            out.append(_p(p + ".editableBy", "editableBy 目前只認得 cashier"))
        if k in RESERVED_KEYS:
            typ, target = RESERVED_KEYS[k]
            if f.get("type") != typ or (target and f.get("target") != target):
                out.append(_p(p, "保留鍵 %s 的型別必須是 %s%s" % (k, typ, "（參照 %s）" % target if target else "")))
            if k == "urgency" and f.get("type") == "select" and list(f.get("options") or []) != _URGENCY:
                out.append(_p(p + ".options", "urgency 的選項必須是：%s" % "、".join(_URGENCY)))
        if f.get("editableBy") == "cashier" and k not in ("pay_terms", "remit_date", "pay_date"):
            out.append(_p(p + ".editableBy", "只有 pay_terms／remit_date／pay_date 可以設成出納填寫"))
        if k == "lines":
            lines_seen += 1
            if f.get("type") != "table":
                out.append(_p(p + ".type", "lines 必須是明細表（table）"))
            else:
                out += _lines_problems(f, p)
        elif f.get("type") == "table":
            out.append(_p(p, "費用單據只能有一個明細表，key 必須是 lines"))
    if not lines_seen:
        out.append(_p("fields", "必須有一個 key 為 lines 的明細表"))
    return out


def validate_expense_type(body, key: str = "") -> list:
    """類型定義 ⇒ `[{"path","message"}]`（空＝可以發布）。形狀同建構器的驗證結果。"""
    from helpers import custom_modules as CM
    from helpers.tiered_approval import APPROVAL_DOC_TYPES
    if not isinstance(body, dict):
        return [_p("", "定義必須是 JSON 物件")]
    out = []
    if key and not CODE_RE.match(key):
        out.append(_p("", "類型代碼只能用小寫英文、數字與底線（2～40 字）：%r" % key))
    if not str(body.get("name") or "").strip():
        out.append(_p("name", "必須有類型名稱"))
    num = body.get("numbering")
    if not isinstance(num, dict) or not PREFIX_RE.match(str(num.get("prefix") or "")):
        out.append(_p("numbering.prefix", "必須有單號前綴：大寫英文開頭、英數、最長 4 字"))
    elif num.get("date", "YYYYMMDD") != "YYYYMMDD" or num.get("digits", 4) != 4:
        out.append(_p("numbering", "單號格式固定為 {前綴}-YYYYMMDD-NNNN（date／digits 不可改）"))
    else:
        for other in DEFAULT_KINDS:
            if other != key:
                od = _default_for(other)
                if od and (od.get("numbering") or {}).get("prefix") == num["prefix"]:
                    out.append(_p("numbering.prefix", "前綴 %s 已被「%s」使用" % (num["prefix"], od["name"])))
    if not isinstance(body.get("payable"), bool):
        out.append(_p("payable", "必須指定 payable（true＝核准後進出納；false＝只是核准文件）"))
    if "enabled" in body and not isinstance(body["enabled"], bool):
        out.append(_p("enabled", "enabled 要是 true／false"))
    dt = body.get("docType", "extra_expense")
    if dt not in APPROVAL_DOC_TYPES:
        out.append(_p("docType", "簽核單據類型未登記：%r" % (dt,)))
    fields = body.get("fields")
    if not isinstance(fields, list) or not fields:
        return out + [_p("fields", "至少要有一個欄位")]
    g = _generic(body)
    out += [_p(x["path"], _camel_text(x["message"])) for x in CM._validate_fields(g["fields"])]
    out += _field_problems(fields)
    keys = {f.get("key") for f in fields if isinstance(f, dict)}
    ui = body.get("ui")
    if ui is not None:
        groups = ((ui or {}).get("form") or {}).get("groups") if isinstance(ui, dict) else None
        if not isinstance(ui, dict) or (groups is not None and not isinstance(groups, list)):
            out.append(_p("ui", "ui 形狀不對"))
        else:
            for gi, grp in enumerate(groups or []):
                bad = [x for x in ((grp or {}).get("fields") or []) if x not in keys]
                if bad:
                    out.append(_p("ui.form.groups[%d].fields" % gi, "引用不到的欄位：%s" % "、".join(map(str, bad))))
    if not out:
        out += [_p(x["path"], _camel_text(x["message"])) for x in CM._validate_output(g)]
    return out


# ── 讀取（任何模組 in-process 呼叫）────────────────────────────────────────────

def get_type(conn, code: str, version=None):
    """`{code, version, body}`；查無 ⇒ None。`version=None`＝目前生效的（公司發布版，沒有就是程式預設、版本 0）；
    `version=N`＝單據釘住的版本（0＝程式預設）。"""
    if not isinstance(code, str) or not CODE_RE.match(code):
        return None
    if version is None:
        body, src = D.resolve(conn, KIND, code)
        if body is None:
            return None
        row = D.get(conn, KIND, code, "company")
        return {"code": code, "version": row["version"] if row else 0, "body": body}
    if version == 0:
        body = _default_for(code)
        return {"code": code, "version": 0, "body": body} if body is not None else None
    row = D.get(conn, KIND, code, "company", version)
    return {"code": code, "version": row["version"], "body": row["body"]} if row else None


def list_types(conn) -> list:
    """`[{code,name,prefix,payable,docType,defVersion}]`：已啟用的類型（預設四種＋公司另外發布的）。"""
    codes = list(DEFAULT_KINDS)
    for r in D.list_definitions(conn, KIND):
        if r["key"] not in codes:
            codes.append(r["key"])
    out = []
    for c in codes:
        t = get_type(conn, c)
        if not t or t["body"].get("enabled", True) is False:
            continue
        b = t["body"]
        out.append({"code": c, "name": b.get("name", c), "prefix": (b.get("numbering") or {}).get("prefix", ""),
                    "payable": bool(b.get("payable")), "docType": b.get("docType", "extra_expense"), "defVersion": t["version"]})
    return out


def cashier_field_keys(body) -> list:
    """定義裡標 `editableBy:"cashier"` 的欄位 key（核准後僅出納可改、不走變更申請）。"""
    return [f["key"] for f in (body.get("fields") or []) if isinstance(f, dict) and f.get("editableBy") == "cashier"]


# ── 明細金額（唯一實作；W2 的 normalize_lines 改成委派）────────────────────────────

def _num(v, label):
    if v is None or v == "":
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError("%s必須是數字" % label)
    if v != v or v in (float("inf"), float("-inf")):
        raise ValueError("%s必須是有限的數字" % label)
    return v


def normalize_lines(lines) -> tuple:
    """明細列 ⇒ `(乾淨的列, total_cost)`；不合法 ⇒ ValueError（訊息可直接給使用者）。
    金額權威（plan §7.1）：`qty` 與 `unitCost` 都是數字 ⇒ `amount = round_half_up(qty × unitCost)`；否則 `amount` 為權威（≥0）。
    `total_cost = Σ amount`（整數 TWD）。**未知的鍵原樣保留**（categoryCode／accountCode／files／定義自訂欄）。"""
    if lines is None:
        lines = []
    if not isinstance(lines, list):
        raise ValueError("明細必須是陣列")
    if len(lines) > MAX_LINES:
        raise ValueError("明細最多 %d 列" % MAX_LINES)
    out, total = [], 0
    for i, raw in enumerate(lines, 1):
        if not isinstance(raw, dict):
            raise ValueError("第 %d 列格式不對" % i)
        row = dict(raw)
        for k in ("category", "accountCode", "summary", "invoiceNo"):
            if row.get(k) is not None:
                if not isinstance(row[k], str):
                    raise ValueError("第 %d 列 %s 必須是文字" % (i, k))
                row[k] = row[k].strip()
                if len(row[k]) > MAX_TEXT:
                    raise ValueError("第 %d 列 %s 太長（上限 %d 字）" % (i, k, MAX_TEXT))
        qty, unit = _num(row.get("qty"), "第 %d 列數量" % i), _num(row.get("unitCost"), "第 %d 列單價" % i)
        if qty is not None and unit is not None:
            if qty < 0 or unit < 0:
                raise ValueError("第 %d 列數量與單價不能為負" % i)
            amount = round_half_up(qty * unit)
        else:
            amt = _num(row.get("amount"), "第 %d 列金額" % i)
            if amt is None:
                raise ValueError("第 %d 列金額必須是數字" % i)
            if amt < 0:
                raise ValueError("第 %d 列金額不能為負" % i)
            amount = round_half_up(amt)
        row["amount"] = amount
        total += amount
        out.append(row)
    return out, total


# ── 值驗證（建立／更新／送審時呼叫）────────────────────────────────────────────────

def _is_cashier(viewer) -> bool:
    if (viewer or {}).get("role") == "superadmin":
        return True
    mods = (viewer or {}).get("modules") or []
    if isinstance(mods, str):
        try:
            mods = json.loads(mods)
        except ValueError:
            mods = []
    return "cashier" in mods


def validate_values(conn, defn: dict, data, lines, *, viewer: dict) -> tuple:
    """`(clean_data, clean_lines, total_cost, problems)`；`problems`＝`[{"key","message"}]`（空＝通過）。
    - 預設值 token（requester／today）由伺服器換；`locked` 的欄位一律以伺服器預填為準（前端送什麼都不採用）
    - `editableBy:"cashier"` 的欄位：不是出納／超級管理員送來的值 ⇒ 丟掉並回報
    - 定義沒有的鍵 ⇒ 回報（不靜默丟）；欄位型別／必填／公式／參照沿用建構器（`custom_modules.clean_values`）
    - 明細：逐列逐欄驗證（必填、型別、列數），儲存用的列由 `normalize_lines` 算（保留所有未知鍵）；`total_cost` 是唯一來源
    - `clean_data` 含公式欄位的結果（例 `total`），不含 `lines`"""
    from helpers import custom_modules as CM
    data = dict(data) if isinstance(data, dict) else {}
    data.pop("lines", None)
    g = _generic(defn)
    problems = []
    fields = [f for f in defn.get("fields") or [] if isinstance(f, dict)]
    known = {f["key"] for f in fields if f.get("key")}
    for k in sorted(set(data) - known):
        problems.append({"key": k, "message": "欄位 %s 不在這個類型的定義裡" % k})
        data.pop(k)
    if not _is_cashier(viewer):
        for k in cashier_field_keys(defn):
            if data.pop(k, None) not in (None, ""):
                problems.append({"key": k, "message": "這個欄位只有出納可以填寫"})
    # 預填與鎖定：locked 的欄位用伺服器值蓋掉
    filled = CM._with_default_tokens(g, {k: v for k, v in data.items()}, viewer or {})
    for f in fields:
        if f.get("locked") and f.get("key") and CM._default_token(f) is not None:
            tok_vals = CM._with_default_tokens(g, {}, viewer or {})
            filled[f["key"]] = tok_vals.get(f["key"])
    try:
        clean_lines, total = normalize_lines(lines)
    except ValueError as e:
        return {}, [], 0, problems + [{"key": "lines", "message": str(e)}]
    values = dict(filled)
    values["lines"] = [{_SNAKE.get(k, k): v for k, v in r.items()} if isinstance(r, dict) else r for r in lines] if isinstance(lines, list) else []
    computed, errors, _dropped = CM.clean_values(conn, g, values)
    problems += [{"key": _camel_text(e["key"]), "message": _camel_text(e["message"])} for e in errors]
    clean = {k: v for k, v in computed.items() if k != "lines"}
    return clean, clean_lines, total, problems


# ── 登記成定義種類（A2-0 #3）──────────────────────────────────────────────────────

if KIND not in D.kinds():
    D.register_kind(KIND, label="費用單據類型", validator=validate_expense_type, default=_default_for)
