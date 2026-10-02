# -*- coding: utf-8 -*-
"""自訂欄位命名空間（P4，CUSTOMIZATION-SPEC §3.6）。

內建模組的單據在自己的 JSON 資料裡預留 `customFields: {}`；核心欄位與計算不動。
欄位定義存在定義文件庫（core.definitions，kind＝custom_fields，key＝模組 key），有草稿與版本。
送審時單據記下 `customFieldsVersion`（凍結）。
"""
import math
import re
from datetime import date

KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
#: 欄位型別目錄（v1）。建構器與排版器只能從這裡挑。
TYPES = ("text", "number", "date", "select", "checkbox")
#: 建構器第三輪（W1，2026-09-30）新增的型別：**只給自訂模組**（`custom_modules`）用；P4 內建單據的 customFields 仍是上面 5 種。
#: textarea 多行文字、radio 單選、checkboxes 複選、multiselect 下拉複選、daterange 日期時間區間（`{from,to}`）。
EXT_TYPES = ("textarea", "radio", "checkboxes", "multiselect", "daterange")
MODULE_TYPES = TYPES + EXT_TYPES
#: 需要 `options` 的型別
OPTION_TYPES = ("select", "radio", "checkboxes", "multiselect")
DATA_CLASSES = ("T1", "F2")
MAX_TEXT = 2000
OTHER_MAX = 200


def validate_definition(body: dict, key: str = "", core_fields=(), types=TYPES) -> list:
    """定義驗證：回 `[{"path", "message"}]`（空＝通過）。`core_fields`＝該模組的核心欄位（不可同名）。
    `types`：可用型別（預設 P4 的 5 種；自訂模組傳 `MODULE_TYPES`）。"""
    problems = []
    fields = body.get("fields")
    if not isinstance(fields, list):
        return [{"path": "fields", "message": "fields 必須是清單"}]
    seen = set()
    core = set(core_fields or ())
    for i, f in enumerate(fields):
        p = "fields[%d]" % i
        if not isinstance(f, dict):
            problems.append({"path": p, "message": "欄位必須是物件"})
            continue
        k = f.get("key")
        if not isinstance(k, str) or not KEY_RE.match(k):
            problems.append({"path": p + ".key", "message": "key 只能用小寫英文、數字與底線，英文開頭，最長 40 字：%r" % (k,)})
        elif k in seen:
            problems.append({"path": p + ".key", "message": "key 重複：%s" % k})
        elif k in core:
            problems.append({"path": p + ".key", "message": "不可以與核心欄位同名：%s" % k})
        seen.add(k)
        if not str(f.get("label") or "").strip():
            problems.append({"path": p + ".label", "message": "必須有顯示名稱"})
        t = f.get("type")
        if t not in types:
            problems.append({"path": p + ".type", "message": "未知型別 %r（可用：%s）" % (t, "、".join(types))})
        if t in OPTION_TYPES:
            opts = f.get("options")
            if not isinstance(opts, list) or not opts or not all(isinstance(o, str) and o for o in opts) \
                    or len(set(opts)) != len(opts):
                problems.append({"path": p + ".options", "message": "下拉選單必須有至少一個選項" if t == "select" else "選項必須有至少一個（不可空白、不可重複）"})
        if t in ("text", "textarea") and f.get("maxLength") is not None:
            ml = f.get("maxLength")
            if isinstance(ml, bool) or not isinstance(ml, int) or not 1 <= ml <= MAX_TEXT:
                problems.append({"path": p + ".maxLength", "message": "最大長度必須是 1～%d 的整數" % MAX_TEXT})
        if t == "number":
            for bound in ("min", "max"):
                v = f.get(bound)
                if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)):
                    problems.append({"path": p + "." + bound, "message": "%s 必須是數字" % ("最小值" if bound == "min" else "最大值")})
            if isinstance(f.get("min"), (int, float)) and isinstance(f.get("max"), (int, float)) and f["min"] > f["max"]:
                problems.append({"path": p + ".min", "message": "最小值不可大於最大值"})
        if t == "checkboxes" or t == "multiselect":
            for bound in ("minSelect", "maxSelect"):
                v = f.get(bound)
                if v is not None and (isinstance(v, bool) or not isinstance(v, int) or v < 0):
                    problems.append({"path": p + "." + bound, "message": "必須是 0 以上的整數"})
        if f.get("dataClass", "T1") not in DATA_CLASSES:
            problems.append({"path": p + ".dataClass", "message": "資料分類只能是 T1 或 F2"})
        if "default" in f and t in TYPES:
            ok, _v, _msg = _coerce(f, f["default"])
            if not ok:
                problems.append({"path": p + ".default", "message": "預設值與型別不符"})
    return problems


def _coerce(f: dict, v):
    """回 (ok, 正規化後的值, 錯誤訊息)。空值（None／""）一律視為「沒填」。"""
    t = f.get("type")
    if v is None or v == "":
        return True, None, ""
    if t in ("text", "textarea"):
        if not (isinstance(v, (str, int, float)) and not isinstance(v, bool)):
            return False, None, "必須是文字"
        s = str(v)
        ml = f.get("maxLength")
        if isinstance(ml, int) and not isinstance(ml, bool) and len(s) > ml:
            return False, None, "最多 %d 字" % ml
        return True, s, ""
    if t == "number":
        if isinstance(v, bool):
            return False, None, "必須是數字"
        try:
            n = float(v)
        except (TypeError, ValueError, OverflowError):
            return False, None, "必須是數字"
        if not math.isfinite(n):
            # 稽核 D C-M5："nan"／"inf" 會被 float() 收下 ⇒ 寫進資料庫之後整個列表都 500（JSON 不能序列化 NaN）
            return False, None, "必須是有限的數字（不接受 NaN／無限大）"
        if isinstance(f.get("min"), (int, float)) and not isinstance(f.get("min"), bool) and n < f["min"]:
            return False, None, "不可小於 %s" % f["min"]
        if isinstance(f.get("max"), (int, float)) and not isinstance(f.get("max"), bool) and n > f["max"]:
            return False, None, "不可大於 %s" % f["max"]
        return True, (int(n) if n.is_integer() else n), ""
    if t == "date":
        return _coerce_date(f, v)
    if t in ("select", "radio"):
        if v in (f.get("options") or []):
            return True, v, ""
        if f.get("allowOther") and isinstance(v, str) and 0 < len(v.strip()) <= OTHER_MAX:
            return True, v.strip(), ""                       # 「其他＋自己打」（單位、原因等）
        return False, None, "不在選項內"
    if t in ("checkboxes", "multiselect"):
        if isinstance(v, str):
            v = [v]
        if not isinstance(v, list):
            return False, None, "必須是選項清單"
        out = []
        for x in v:
            if x not in (f.get("options") or []):
                if f.get("allowOther") and isinstance(x, str) and 0 < len(x.strip()) <= OTHER_MAX:
                    x = x.strip()
                else:
                    return False, None, "有選項不在清單內：%s" % (x,)
            if x not in out:
                out.append(x)
        lo, hi = f.get("minSelect"), f.get("maxSelect")
        if isinstance(lo, int) and not isinstance(lo, bool) and len(out) < lo:
            return False, None, "至少選 %d 項" % lo
        if isinstance(hi, int) and not isinstance(hi, bool) and len(out) > hi:
            return False, None, "最多選 %d 項" % hi
        return (True, out, "") if out else (True, None, "")
    if t == "daterange":
        if not isinstance(v, dict):
            return False, None, "必須是起訖（from／to）"
        a, b = v.get("from"), v.get("to")
        if a in (None, "") and b in (None, ""):
            return True, None, ""
        ok1, x, m1 = _coerce_date(f, a)
        ok2, y, m2 = _coerce_date(f, b)
        if not ok1 or not ok2 or x is None or y is None:
            return False, None, "起訖都要填，且必須是日期%s" % ("時間" if f.get("withTime") else "")
        if x > y:
            return False, None, "起不可晚於迄"
        return True, {"from": x, "to": y}, ""
    if t == "checkbox":
        return (True, v, "") if isinstance(v, bool) else (False, None, "必須是勾選（true／false）")
    return False, None, "未知型別"


def _coerce_date(f, v):
    """`withTime`＝日期時間（`YYYY-MM-DDTHH:MM`）；否則只取日期（`YYYY-MM-DD`）。空值視為沒填。"""
    if v is None or v == "":
        return True, None, ""
    s = str(v).strip()
    if f.get("withTime"):
        m = re.match(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2})", s)
        if not m:
            return False, None, "必須是日期時間（YYYY-MM-DD HH:MM）"
        try:
            date.fromisoformat(m.group(1))
        except ValueError:
            return False, None, "必須是日期時間（YYYY-MM-DD HH:MM）"
        if int(m.group(2)) > 23 or int(m.group(3)) > 59:
            return False, None, "時間不正確"
        return True, "%sT%s:%s" % (m.group(1), m.group(2), m.group(3)), ""
    try:
        return True, date.fromisoformat(s[:10]).isoformat(), ""
    except ValueError:
        return False, None, "必須是日期（YYYY-MM-DD）"


def clean(values, definition: dict) -> tuple:
    """回 `(乾淨的值, 錯誤清單, 丟掉的鍵)`。錯誤清單非空 ⇒ 呼叫端回 400 並指出是哪一欄。

    - 未定義的鍵：丟掉並回報（不默默保留，也不默默吃掉而不說）。
    - 型別不符、必填沒填：列入錯誤，每一項 `{"key", "message"}`。
    - 沒填且有預設值：填入預設值。
    """
    values = values if isinstance(values, dict) else {}
    fields = {f["key"]: f for f in (definition or {}).get("fields", []) if isinstance(f, dict) and "key" in f}
    out, errors = {}, []
    dropped = sorted(k for k in values if k not in fields)
    for k, f in fields.items():
        raw = values.get(k, None)
        if (raw is None or raw == "") and "default" in f:
            raw = f["default"]
        ok, v, msg = _coerce(f, raw)
        if not ok:
            errors.append({"key": k, "message": "%s：%s" % (f.get("label") or k, msg)})
            continue
        if v is None:
            if f.get("required"):
                errors.append({"key": k, "message": "%s：必填" % (f.get("label") or k)})
            continue
        out[k] = v
    return out, errors, dropped
