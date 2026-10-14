# -*- coding: utf-8 -*-
"""選項清單（census #4）：管理者決定下拉選單有哪些選項、顯示名稱與順序；新增／改名／重排／停用，不能刪除已發布的選項。

[單位] helper:option_lists    [層] L1    [穩定度] 實作
[公開介面] BUILTIN, FIELD, GROUP, KIND, LABEL_MAX, MAX_VALUES, OFF_REASON, definition_problems, effective, enabled, ensure_kind, lists_for_menu, preview, registered
[不變式] 設定 `builder_option_lists.enabled`（預設 0＝關）**且** `builder_governance.enabled`=1 才生效；關著 ⇒ `effective()` 回程式預設（與今天寫死的清單逐項相同）、
    選單回應不帶 `optionLists`、頁面不多任何請求。清單裡的 `value` 是**存進資料裡的字**（客戶類型 VIP、料件分類 網通設備…）：發布後不可刪除、不可改字，
    只能「停用」（停用＝新資料不能再選，舊資料照常顯示）或改 `label`（顯示名稱；`relabel:false` 的清單不允許改 label，因為該欄位的值同時被報表／科目對照拿來比對）。
    第一版發布必須包含程式預設的每一個選項（預設選項只能停用，不能少）。
    選項文字是純文字：無占位符、無控制／雙向／隱形字元、不以 = + - @ 開頭（會進匯出檔）。
[契約題] tests/platform/test_option_lists_t62.py
[注意] 新增一個 kind `option_list`（key＝清單代號，scope＝company），惰性登記（旗標關＝不登記）；版本／差異／還原／帳本／發布前預覽雜湊全部沿用定義文件庫與治理層。
    本版**不統計各選項被多少筆資料使用**（客戶／供應商／料號都是單位表，統計需要走各自的範圍化讀取，另案）；預覽只列『哪些畫面用這份清單』並標出被停用的選項。
"""
import re
import unicodedata

from core import definitions as D

GROUP = "builder_option_lists"
FIELD = "enabled"
KIND = "option_list"
OFF_REASON = "選項清單尚未開放（設定中心：自訂選項清單）"
MAX_VALUES = 40
LABEL_MAX = 20
_TOP_KEYS = {"version", "values"}
_ITEM_KEYS = {"value", "label", "disabled", "prefix"}
_BAD = re.compile("[<>&\"'`\\\\{}\x00-\x1f\x7f​-‏‪-‮⁦-⁩﻿]")
_FILLERS = frozenset("ᅟᅠㅤﾠ⠀᠎͏؜឴឵­⁠")
_TRIGGERS = ("=", "+", "-", "@")
_PREFIX_RE = re.compile(r"^[A-Z]{2,5}$")


def _b(value, label=None, prefix=None):
    d = {"value": value, "label": label if label is not None else value}
    if prefix is not None:
        d["prefix"] = prefix
    return d


#: 程式預設（＝今天寫死在畫面／程式裡的清單；`used_by` 是白話說明，預覽時顯示）。
BUILTIN = {
    "customer_type": {
        "label": "客戶類型", "relabel": True, "prefix": False,
        "used_by": ["客戶管理頁：新增／編輯客戶的「客戶類型」下拉", "客戶管理頁：上方的類型篩選標籤"],
        "defaults": [_b("一般", "一般客戶"), _b("VIP", "VIP 客戶"), _b("潛在", "潛在客戶")]},
    "supplier_category": {
        "label": "供應商類型", "relabel": True, "prefix": False,
        "used_by": ["供應商管理頁：新增／編輯供應商的「供應商類型」下拉", "供應商管理頁：上方的類型篩選標籤"],
        "defaults": [_b(v) for v in ("原廠", "代理商", "製造商", "服務商", "其他")]},
    "part_category": {
        "label": "料件分類", "relabel": False, "prefix": True,
        "used_by": ["料號管理頁：分類下拉與自動產生料號的前綴", "進貨／庫存的分類篩選",
                    "會計匯出的「存貨費用科目」對照（新分類要到會計設定補科目）", "營運報表的設備／材料分桶（新分類預設算材料）"],
        "defaults": [_b("網通設備", prefix="NET"), _b("監控設備", prefix="CCTV"), _b("交換器", prefix="SW"),
                     _b("伺服器/工控", prefix="SVR"), _b("線材配件", prefix="CAB"), _b("其他", prefix="OTH")]},
    "part_unit": {
        "label": "料件單位", "relabel": False, "prefix": False,
        "used_by": ["料號管理頁：新增料號時的預設單位（清單第一個未停用的）與單位的建議選項"],
        "defaults": [_b("台")]},
}


def enabled(conn=None) -> bool:
    """fail-closed：讀不到設定 ⇒ 關。必須同時開啟『建構器治理』（改動要走版本帳本與發布前預覽雜湊）。"""
    try:
        from helpers import settings_registry as SR
        if not bool(int(SR.get(GROUP, FIELD, conn=conn))):
            return False
        return int(SR.get("builder_governance", "enabled", conn=conn)) == 1
    except Exception:                                        # noqa: BLE001
        return False


def registered() -> dict:
    return {k: {"label": v["label"], "relabel": v["relabel"], "prefix": v["prefix"], "usedBy": list(v["used_by"]),
                "defaults": [dict(x) for x in v["defaults"]]} for k, v in BUILTIN.items()}


def _text_problem(v, what):
    if not isinstance(v, str) or not v.strip():
        return "%s必須是不空白的文字" % what
    if v != v.strip():
        return "%s前後不可有空白" % what
    if len(v) > LABEL_MAX:
        return "%s最多 %d 字" % (what, LABEL_MAX)
    if any(unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp", "Co", "Cs") or c in _FILLERS for c in v):
        return "%s不可含控制、隱形、雙向或私用字元" % what
    if _BAD.search(v):
        return "%s不可含 < > & 引號、反斜線、花括號" % what
    if v[:1] in _TRIGGERS:
        return "%s不可以 = + - @ 開頭" % what
    return ""


def _live_values(key):
    """已發布版本的選項（⇒ {value: item}）；讀不到 ⇒ {}。"""
    try:
        from db import get_db
        c = get_db()
        try:
            r = D.get(c, KIND, key, "company")
        finally:
            c.close()
        return {x["value"]: x for x in ((r or {}).get("body") or {}).get("values", []) if isinstance(x, dict) and "value" in x}
    except Exception:                                        # noqa: BLE001
        return {}


def definition_problems(key, body, live=None) -> list:
    """⇒ `[{path, message}]`（空＝通過）。`live`＝已發布版本 `{value: item}`（None ⇒ 自己讀）。不看旗標。"""
    spec = BUILTIN.get(key)
    if spec is None:
        return [{"path": "", "message": "不是已登記的清單：%r" % (key,)}]
    if not isinstance(body, dict):
        return [{"path": "", "message": "清單必須是物件"}]
    out = [{"path": k, "message": "不認得的鍵：%s" % k} for k in body if k not in _TOP_KEYS]
    if body.get("version") != 1 or isinstance(body.get("version"), bool):
        out.append({"path": "version", "message": "version 必須是 1"})
    vals = body.get("values")
    if not isinstance(vals, list) or not vals:
        return out + [{"path": "values", "message": "values 必須是不空的清單"}]
    if len(vals) > MAX_VALUES:
        out.append({"path": "values", "message": "最多 %d 個選項" % MAX_VALUES})
    seen, labels, prefixes = set(), set(), set()
    _fold = lambda x: unicodedata.normalize("NFKC", x).casefold()          # 全形／大小寫不同的同一個字也算重複（ＶＩＰ、vip、VIP）
    for i, it in enumerate(vals):
        p = "values[%d]" % i
        if not isinstance(it, dict):
            out.append({"path": p, "message": "選項必須是物件"})
            continue
        allowed = _ITEM_KEYS if spec["prefix"] else _ITEM_KEYS - {"prefix"}
        out.extend({"path": "%s.%s" % (p, k), "message": "不認得的鍵：%s" % k} for k in it if k not in allowed)
        m = _text_problem(it.get("value"), "選項")
        if m:
            out.append({"path": p + ".value", "message": m})
        elif _fold(it["value"]) in seen:
            out.append({"path": p + ".value", "message": "選項重複（全形、半形、大小寫不同也算重複）：%s" % it["value"]})
        else:
            seen.add(_fold(it["value"]))
        m = _text_problem(it.get("label"), "顯示名稱")
        if m:
            out.append({"path": p + ".label", "message": m})
        elif _fold(it["label"]) in labels:
            out.append({"path": p + ".label", "message": "顯示名稱重複：%s" % it["label"]})
        else:
            labels.add(_fold(it["label"]))
        if not spec["relabel"] and isinstance(it.get("value"), str) and it.get("label") != it.get("value"):
            out.append({"path": p + ".label", "message": "這份清單不能改顯示名稱（這個欄位的值同時被報表或科目對照拿來比對）"})
        if "disabled" in it and not isinstance(it["disabled"], bool):
            out.append({"path": p + ".disabled", "message": "disabled 必須是 true／false"})
        if spec["prefix"]:
            pf = it.get("prefix")
            if not isinstance(pf, str) or not _PREFIX_RE.match(pf):
                out.append({"path": p + ".prefix", "message": "料號前綴必須是 2～5 個大寫英文字母"})
            elif pf in prefixes:
                out.append({"path": p + ".prefix", "message": "料號前綴重複：%s" % pf})
            else:
                prefixes.add(pf)
    if all(isinstance(it, dict) and it.get("disabled") for it in vals):
        out.append({"path": "values", "message": "至少要有一個未停用的選項"})
    # 與程式預設、已發布版本的關係（不可刪除、不可改前綴）
    have = {it.get("value"): it for it in vals if isinstance(it, dict)}
    for d in spec["defaults"]:
        if d["value"] not in have:
            out.append({"path": "values", "message": "程式預設的選項「%s」不能少（要隱藏請改成停用）" % d["value"]})
        elif spec["prefix"] and have[d["value"]].get("prefix") != d.get("prefix"):
            out.append({"path": "values", "message": "選項「%s」的料號前綴不能改（已經有料號在用）" % d["value"]})
    prev = _live_values(key) if live is None else live
    for v, old in prev.items():
        if v not in have:
            out.append({"path": "values", "message": "已發布的選項「%s」不能刪除（要隱藏請改成停用）" % v})
        elif spec["prefix"] and have[v].get("prefix") != old.get("prefix"):
            out.append({"path": "values", "message": "選項「%s」的料號前綴不能改" % v})
    return out


def _kind_validator(body, key):
    if not enabled():
        return [{"path": "", "message": OFF_REASON}]
    return definition_problems(key, body)


def ensure_kind():
    """惰性登記 kind（旗標關＝不登記，`/api/definition-kinds` 與今天相同）。"""
    if KIND not in D.kinds() and enabled():
        try:
            D.register_kind(KIND, label="選項清單", validator=_kind_validator)
        except ValueError:                                   # 並行登記 ⇒ 已存在
            pass
    return KIND in D.kinds()


def effective(list_id, conn=None) -> list:
    """⇒ `[{value, label, disabled, prefix?}]`：旗標開且有已發布的合法版本 ⇒ 該版；否則程式預設（逐項＝今天寫死的清單，disabled 一律 False）。"""
    spec = BUILTIN[list_id]
    base = [dict(d, disabled=False) for d in spec["defaults"]]
    if not enabled(conn):
        return base
    try:
        from db import get_db
        own = conn is None
        c = conn if conn is not None else get_db()
        try:
            r = D.get(c, KIND, list_id, "company")
        finally:
            if own:
                c.close()
        body = (r or {}).get("body")
        if not body or definition_problems(list_id, body, live={}):
            return base
        return [dict(x, disabled=bool(x.get("disabled"))) for x in body["values"]]
    except Exception:                                        # noqa: BLE001
        return base


def lists_for_menu(conn=None):
    """給 /api/platform/menu 的 `optionLists`：只含『已有發布版本』的清單 ⇒ `{id: [{value,label,disabled}]}`；旗標關或都沒發布 ⇒ None（不帶這個鍵）。"""
    if not enabled(conn):
        return None
    out = {}
    for k in BUILTIN:
        eff = effective(k, conn)
        if eff != [dict(d, disabled=False) for d in BUILTIN[k]["defaults"]]:
            out[k] = [{"value": x["value"], "label": x["label"], "disabled": x["disabled"]} for x in eff]
    return out or None


def _preview_item(x, with_prefix):
    d = {"value": x["value"], "label": x["label"], "disabled": bool(x.get("disabled"))}
    if with_prefix:
        d["prefix"] = x["prefix"]
    return d


def preview(list_id, body):
    """草稿預覽（唯讀）：合併後的清單、哪些畫面用它、被停用的選項（既有資料仍會顯示、新資料不能選）、新增的選項。
    不合法 ⇒ ValueError(problems)；不認得的清單 ⇒ LookupError。"""
    if list_id not in BUILTIN:
        raise LookupError("不是已登記的清單")
    probs = definition_problems(list_id, body)
    if probs:
        raise ValueError(probs)
    spec = BUILTIN[list_id]
    dflt = {d["value"] for d in spec["defaults"]}
    live = _live_values(list_id) or {d["value"]: d for d in spec["defaults"]}
    items = body["values"]
    return {"id": list_id, "label": spec["label"], "usedBy": list(spec["used_by"]),
            "values": [_preview_item(x, spec["prefix"]) for x in items],
            "added": [x["value"] for x in items if x["value"] not in live and x["value"] not in dflt],
            "disabled": [x["value"] for x in items if x.get("disabled")],
            "warnings": (["停用的選項：既有資料仍會顯示這些值，只是新增／編輯時不能再選。"] if any(x.get("disabled") for x in items) else [])
                        + ["本版不統計各選項被多少筆資料使用。"]}
