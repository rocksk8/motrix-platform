# -*- coding: utf-8 -*-
"""內建畫面的自訂欄位（T61 S5；設計：docs/platform/plans/T61-S5-FIELD-CATALOG-DESIGN.md）。

[單位] helper:builtin_fields    [層] L1    [穩定度] 契約（改介面照 PLAYBOOK §C-7 升版）
[公開介面] ALLOWED_TYPES, MAX_FIELDS, RECORD_TYPES, definition_problems, enabled, gate, public_fields, usage_counts
[不變式] ①旗標 `builder_custom_fields.enabled` 關閉 ⇒ `gate()` 一律回舊值（不介入任何寫入）、`public_fields()` 回空；
    ②值只放在單據 JSON 的 `customFields` 命名空間，沒有值就**不寫這個鍵**；③型別只有文字／日期／單選／勾選（沒有金額、公式、參照、必填、預設值）；
    ④停用或已不在定義裡的欄位，其值**原樣保留**（用戶端送來的改動一律忽略）；⑤任何錯誤 ⇒ 回錯誤清單，不丟例外。
[契約題] backend/tests/test_builtin_custom_fields_2026_10_14.py

內建單據類型的欄位定義存在定義文件庫（kind＝`custom_fields`，key＝下面的單據類型鍵，scope＝company）。本檔只做三件事：
`definition_problems`（發布前的額外驗證，由 `custom_fields.validate_definition` 呼叫）、`gate`（每一條寫入路徑在存檔前呼叫）、
`public_fields`（頁面要畫哪些欄位）。值的型別檢查沿用 `custom_fields._coerce`（同一份規則）。
"""
import json

#: 第一版可用的型別（沒有數字：數字欄可能被拿去放金額，第一版先不給）
ALLOWED_TYPES = ("text", "date", "select", "checkbox")
MAX_FIELDS = 20
_MAX_LABEL = 30
_MAX_HELP = 100
_MAX_OPTIONS = 30
_MAX_OPTION_LEN = 40
_MAX_JSON_BYTES = 8192
_DEFAULT_TEXT = 200
#: 欄位定義裡認得的鍵（其餘＝問題；不靜默丟掉）
_FIELD_KEYS = {"key", "label", "type", "options", "maxLength", "disabled", "help", "dataClass"}

#: 單據類型登錄：鍵 ⇒ 標籤與核心欄位名（自訂欄位的 key 不可與之同名，避免畫面上冒充）。
#: 值放哪裡由各寫入路徑自己決定（案件資訊＝caseRecord.customFields；供應商＝data_json.customFields）。
RECORD_TYPES = {
    "case_info": {
        "label": "案件資訊",
        "table": "quotations", "path": ("caseRecord", "customFields"),          # 值放在哪（唯讀統計用）
        "core": ("deliveryAddress", "deliveryTerms", "contactPerson", "contactPhone", "contractNote", "startDate", "endDate",
                 "filler", "sales", "executor", "warrantyNote", "notes", "payment", "materials", "devices", "stages",
                 "contract", "roles", "projectTimeline", "materialOrders"),
    },
    "supplier": {
        "label": "供應商",
        "table": "suppliers", "path": ("customFields",),
        "core": ("code", "name", "nameEn", "alias", "tags", "taxId", "phone", "fax", "email", "website", "address", "category",
                 "currency", "paymentTerms", "leadTimeDays", "leadTime", "active", "contacts", "visits", "note"),
    },
}


def enabled(conn=None) -> bool:
    """旗標是否開啟。永不丟例外（讀不到 ⇒ 關閉＝今天的行為）。"""
    try:
        from helpers import settings_registry as _SR
        return bool(_SR.get("builder_custom_fields", "enabled", conn=conn))
    except Exception:                                                                    # noqa: BLE001
        return False


def _published(conn, record_type):
    """該單據類型最新發布的定義 body；沒有／讀不到 ⇒ None。"""
    try:
        from core import definitions as D
        r = D.get(conn, "custom_fields", record_type, "company")
        return (r or {}).get("body")
    except Exception:                                                                    # noqa: BLE001
        return None


def _open(conn):
    if conn is not None:
        return conn, False
    from db import get_db
    return get_db(), True


def _active_fields(body):
    out = []
    for f in (body or {}).get("fields", []) if isinstance(body, dict) else []:
        if isinstance(f, dict) and f.get("key") and f.get("type") in ALLOWED_TYPES and not f.get("disabled"):
            out.append(f)
    return out


def public_fields(record_type, conn=None) -> list:
    """頁面要畫的欄位（已發布、未停用）：`[{key,label,type,options?,maxLength?,help?}]`；旗標關閉或沒有定義 ⇒ []。"""
    if record_type not in RECORD_TYPES or not enabled(conn):
        return []
    c, own = _open(conn)
    try:
        fields = _active_fields(_published(c, record_type))
    finally:
        if own:
            c.close()
    return [{k: v for k, v in f.items() if k in ("key", "label", "type", "options", "maxLength", "help")} for f in fields]


def definition_problems(key, body) -> list:
    """內建單據類型的欄位定義額外驗證（由 `custom_fields.validate_definition` 在 key 屬於 RECORD_TYPES 時呼叫）。
    ⇒ `[{path, message}]`。已發布的欄位不可改型別（要改請停用再新增）。"""
    if key not in RECORD_TYPES:
        return []
    out = []
    fields = (body or {}).get("fields") if isinstance(body, dict) else None
    if not isinstance(fields, list):
        return out
    if len(fields) > MAX_FIELDS:
        out.append({"path": "fields", "message": "最多 %d 個欄位（含停用的）" % MAX_FIELDS})
    core = set(RECORD_TYPES[key]["core"])
    labels = {}
    prev = {}
    try:                                                                                 # 已發布版的型別（不可改）
        c, own = _open(None)
        try:
            prev = {f.get("key"): f.get("type") for f in ((_published(c, key) or {}).get("fields") or []) if isinstance(f, dict)}
        finally:
            if own:
                c.close()
    except Exception:                                                                    # noqa: BLE001
        prev = {}
    for i, f in enumerate(fields):
        p = "fields[%d]" % i
        if not isinstance(f, dict):
            continue
        for k in f:
            if k not in _FIELD_KEYS:
                out.append({"path": "%s.%s" % (p, k), "message": "不認得的設定：%s（第一版沒有必填、預設值、公式、金額）" % k})
        if f.get("type") not in ALLOWED_TYPES:
            out.append({"path": p + ".type", "message": "第一版只能用：文字、日期、單選、勾選"})
        if f.get("dataClass", "T1") != "T1":
            out.append({"path": p + ".dataClass", "message": "第一版只收一般資料（T1）；個人資料請用既有的個資欄位"})
        if f.get("key") in core:
            out.append({"path": p + ".key", "message": "不可以與既有欄位同名：%s" % f.get("key")})
        lab = str(f.get("label") or "").strip()
        if not 1 <= len(lab) <= _MAX_LABEL:
            out.append({"path": p + ".label", "message": "顯示名稱要 1～%d 字" % _MAX_LABEL})
        elif lab in labels:
            out.append({"path": p + ".label", "message": "顯示名稱重複：%s" % lab})
        labels[lab] = i
        if f.get("help") is not None and (not isinstance(f.get("help"), str) or len(f["help"]) > _MAX_HELP):
            out.append({"path": p + ".help", "message": "說明最多 %d 字的文字" % _MAX_HELP})
        if f.get("disabled") is not None and not isinstance(f.get("disabled"), bool):
            out.append({"path": p + ".disabled", "message": "停用必須是 true／false"})
        if f.get("type") == "select":
            opts = f.get("options")
            if isinstance(opts, list):
                if len(opts) > _MAX_OPTIONS:
                    out.append({"path": p + ".options", "message": "選項最多 %d 個" % _MAX_OPTIONS})
                if any(isinstance(o, str) and len(o) > _MAX_OPTION_LEN for o in opts):
                    out.append({"path": p + ".options", "message": "每個選項最多 %d 字" % _MAX_OPTION_LEN})
        elif f.get("options") is not None:
            out.append({"path": p + ".options", "message": "只有單選可以設定選項"})
        if f.get("type") != "text" and f.get("maxLength") is not None:
            out.append({"path": p + ".maxLength", "message": "只有文字可以設定最大長度"})
        if f.get("key") in prev and prev[f.get("key")] != f.get("type"):
            out.append({"path": p + ".type", "message": "已發布的欄位不能改型別；請停用它，再新增一個新欄位"})
    return out


def _bytes(values) -> int:
    try:
        return len(json.dumps(values, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        return _MAX_JSON_BYTES + 1


def gate(record_type, new_values, old_values, conn=None):
    """每一條寫入路徑在存檔前呼叫。⇒ `(要存的值 或 None, 錯誤清單, 被忽略的鍵)`；回 None ＝「不要有這個鍵」。

    - 旗標關閉／單據類型不認得／沒有已發布定義：**回舊值**（用戶端送來的 customFields 一律不存）。
    - 旗標開啟：有效欄位（已發布且未停用）依型別驗證（錯 ⇒ 錯誤清單，指名是哪一欄）；空值或沒有送＝移除該欄位的值；
      不在定義裡或已停用的欄位，**保留舊值**（用戶端送來的改動忽略，列在被忽略的鍵）。
    - 結果空 ⇒ None（單據不寫 `customFields` 鍵）；序列化後超過 8 KB ⇒ 錯誤。
    - 不補預設值、不改寫值（除了型別正規化：日期＝YYYY-MM-DD、單選必須在選項內）——用戶端送什麼、存什麼，
      免得『存檔後的值與畫面的基準不同』讓下一次存檔誤判成別人改過。"""
    old = old_values if isinstance(old_values, dict) else {}
    if record_type not in RECORD_TYPES or not enabled(conn):
        return (old or None), [], sorted(k for k in (new_values or {}) if isinstance(new_values, dict))
    c, own = _open(conn)
    try:
        fields = {f["key"]: f for f in _active_fields(_published(c, record_type))}
    finally:
        if own:
            c.close()
    if not isinstance(new_values, dict):
        new_values = {}
    from helpers import custom_fields as _cf
    out, errors, ignored = {}, [], []
    for k, v in old.items():                                                             # 不在有效欄位內的舊值：原樣保留
        if k not in fields:
            out[k] = v
    for k in sorted(new_values):
        if k not in fields:
            if new_values[k] != old.get(k):
                ignored.append(k)
    for k, f in fields.items():
        if k not in new_values:
            continue                                                                       # 用戶端送來的物件是這些欄位的全部：沒有 ＝ 清掉
        raw = new_values[k]
        spec = dict(f)
        if f.get("type") == "text" and not isinstance(spec.get("maxLength"), int):
            spec["maxLength"] = _DEFAULT_TEXT
        if f.get("type") == "select" and raw == old.get(k) and raw not in (f.get("options") or []):
            out[k] = raw                                                                  # 選項被改掉之後，舊值原樣保留（不強迫改）
            continue
        ok, val, msg = _cf._coerce(spec, raw)                                             # noqa: SLF001 同一份型別規則
        if not ok:
            errors.append({"key": k, "message": "%s：%s" % (f.get("label") or k, msg)})
            continue
        if val is None:
            continue                                                                       # 空值＝沒有這個欄位的值
        out[k] = val
    if not errors and _bytes(out) > _MAX_JSON_BYTES:
        errors.append({"key": "", "message": "自訂欄位的內容太大（上限 %d KB）" % (_MAX_JSON_BYTES // 1024)})
    return (out or None), errors, ignored


def usage_counts(record_type, conn=None) -> dict:
    """唯讀統計：每個欄位 key 有幾筆單據填了值 ⇒ `{"counts": {key: n}, "records": 有任何自訂欄位值的單據數}`。
    給編輯器在停用欄位前顯示『已有幾筆單據填了這個欄位』。不寫任何資料；只掃 JSON 裡出現 `"customFields"` 的列（LIKE 先濾，
    不用 json_extract）；旗標關閉或單據類型不認得 ⇒ 空。永不丟例外。"""
    out = {"counts": {}, "records": 0}
    spec = RECORD_TYPES.get(record_type)
    if not spec or not enabled(conn):
        return out
    c, own = _open(conn)
    try:
        # 表名來自上面的登錄（程式內常數），不是使用者輸入
        rows = c.execute("SELECT data_json FROM %s WHERE data_json LIKE '%%\"customFields\"%%'" % spec["table"]).fetchall()
        for r in rows:
            try:
                node = json.loads(r[0] or "{}")
                for k in spec["path"]:
                    node = node.get(k) if isinstance(node, dict) else None
            except (TypeError, ValueError):
                continue
            if isinstance(node, dict) and node:
                out["records"] += 1
                for k in node:
                    out["counts"][k] = out["counts"].get(k, 0) + 1
    except Exception:                                                                    # noqa: BLE001
        return {"counts": {}, "records": 0}
    finally:
        if own:
            c.close()
    return out
