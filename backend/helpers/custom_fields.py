# -*- coding: utf-8 -*-
"""自訂欄位命名空間（P4，CUSTOMIZATION-SPEC §3.6）。

內建模組的單據在自己的 JSON 資料裡預留 `customFields: {}`；核心欄位與計算不動。
欄位定義存在定義文件庫（core.definitions，kind＝custom_fields，key＝模組 key），有草稿與版本。
送審時單據記下 `customFieldsVersion`（凍結）。
"""
import re
from datetime import date

KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
#: 欄位型別目錄（v1）。建構器與排版器只能從這裡挑。
TYPES = ("text", "number", "date", "select", "checkbox")
DATA_CLASSES = ("T1", "F2")


def validate_definition(body: dict, key: str = "", core_fields=()) -> list:
    """定義驗證：回 `[{"path", "message"}]`（空＝通過）。`core_fields`＝該模組的核心欄位（不可同名）。"""
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
        if t not in TYPES:
            problems.append({"path": p + ".type", "message": "未知型別 %r（可用：%s）" % (t, "、".join(TYPES))})
        if t == "select":
            opts = f.get("options")
            if not isinstance(opts, list) or not opts or not all(isinstance(o, str) and o for o in opts):
                problems.append({"path": p + ".options", "message": "下拉選單必須有至少一個選項"})
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
    if t == "text":
        return (True, str(v), "") if isinstance(v, (str, int, float)) and not isinstance(v, bool) else (False, None, "必須是文字")
    if t == "number":
        if isinstance(v, bool):
            return False, None, "必須是數字"
        try:
            n = float(v)
        except (TypeError, ValueError):
            return False, None, "必須是數字"
        return True, (int(n) if n.is_integer() else n), ""
    if t == "date":
        try:
            return True, date.fromisoformat(str(v)[:10]).isoformat(), ""
        except ValueError:
            return False, None, "必須是日期（YYYY-MM-DD）"
    if t == "select":
        return (True, v, "") if v in (f.get("options") or []) else (False, None, "不在選項內")
    if t == "checkbox":
        return (True, v, "") if isinstance(v, bool) else (False, None, "必須是勾選（true／false）")
    return False, None, "未知型別"


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
