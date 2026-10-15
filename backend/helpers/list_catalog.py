# -*- coding: utf-8 -*-
"""清單目錄（T66 L0：只登記與驗證、不改行為）。設計：docs/platform/plans/T66-LIST-PREFS-DESIGN.md §1.1。

[單位] helper:list_catalog    [層] L1    [穩定度] 實驗（唯讀登記；沒有旗標、沒有路由、沒有資料表）
[公開介面] MAX_PAGE_SIZE_CEILING, SECTION_NAME, by_id, columns_of, is_money_column, list_problems, lists, money_column_ids, problems, register_list, restore, section_payload, snapshot
[不變式] ①擁有模組以 `register_list()` 登記一份清單；核心不寫死任何清單／欄位。②「金額欄」由欄位的 `catalogId` 對 `field_catalog` 的 `moneyClass != none` 衍生，
    不在這裡再宣告一份（單一來源）。③登記有問題 ⇒ 該清單**不登記**（fail closed）並記 warning，不丟例外（不讓一個模組的筆誤拖垮載入）；守門測試逐一確認先導清單無問題。
    ④回傳值一律是複本；目錄是登記資料，不含任何使用者資料。⑤同一個 `list_id` 只准同一個擁有者重複登記（重新匯入），不同擁有者搶 ⇒ ValueError。
    ⑥載入時向 `core.catalog` 登記區段 `listCatalog`（擁有者 `helpers.list_catalog`；不列入 `EXPECTED_SECTIONS`，所以沒載入時不算缺口）。
[契約題] backend/tests/platform/test_list_catalog_t66.py
"""
import copy
import logging
import re
import threading

from core import catalog as _catalog
from helpers import field_catalog as _FC

logger = logging.getLogger("motrix.list_catalog")

SECTION_NAME = "listCatalog"
MAX_PAGE_SIZE_CEILING = 500                  # 與各清單端點今天的 limit 上限一致（case 清單 200～500）
_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(:[a-z0-9][a-z0-9_\-]*)?$")
_COL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")
_DIRS = ("asc", "desc")

_LISTS = {}                                  # list_id -> {"owner": str, "spec": dict}
_lock = threading.Lock()


def list_problems(list_id, spec) -> list:
    """單一清單登記資料的問題（空＝合格）。"""
    out = []
    if not isinstance(list_id, str) or not _ID_RE.match(list_id):
        return ["清單代號不合法：%r" % (list_id,)]
    if not isinstance(spec, dict):
        return ["%s：登記內容必須是物件" % list_id]
    if not str(spec.get("label") or "").strip():
        out.append("%s：沒有白話名稱" % list_id)
    cols = spec.get("columns")
    if not isinstance(cols, (list, tuple)) or not cols:
        return out + ["%s：沒有欄位" % list_id]
    ids = []
    for c in cols:
        if not isinstance(c, dict) or not _COL_RE.match(str(c.get("id") or "")):
            out.append("%s：欄位 id 不合法：%r" % (list_id, c))
            continue
        cid = c["id"]
        if cid in ids:
            out.append("%s：欄位 id 重複：%s" % (list_id, cid))
        ids.append(cid)
        if not str(c.get("label") or "").strip():
            out.append("%s.%s：沒有白話名稱" % (list_id, cid))
        cat = c.get("catalogId")
        if cat is not None and _FC.by_id(cat) is None:
            out.append("%s.%s：catalogId 不在欄位目錄：%s" % (list_id, cid, cat))
    d = spec.get("defaults")
    if not isinstance(d, dict):
        return out + ["%s：沒有 defaults" % list_id]
    dcols = d.get("columns")
    if not isinstance(dcols, (list, tuple)) or not dcols or any(x not in ids for x in dcols) or len(set(dcols)) != len(dcols):
        out.append("%s：defaults.columns 必須是欄位的非空、不重複子集" % list_id)
    by = {c["id"]: c for c in cols if isinstance(c, dict) and "id" in c}
    for c in cols:
        if isinstance(c, dict) and c.get("required") and dcols and c.get("id") not in dcols:
            out.append("%s：必留欄位 %s 不在預設欄位內" % (list_id, c.get("id")))
    s = d.get("sort")
    if s is not None:
        if not isinstance(s, dict) or s.get("col") not in by or not by[s["col"]].get("sortable") or s.get("dir") not in _DIRS:
            out.append("%s：defaults.sort 必須指向可排序欄位、方向 asc／desc" % list_id)
        elif dcols and s["col"] not in dcols:
            out.append("%s：預設排序欄位 %s 不在預設欄位內（排序欄位必須看得到）" % (list_id, s["col"]))
    ceil_, menu = spec.get("pageSizeCeiling"), spec.get("pageSizeMenu")
    if not isinstance(ceil_, int) or isinstance(ceil_, bool) or not 1 <= ceil_ <= MAX_PAGE_SIZE_CEILING:
        out.append("%s：pageSizeCeiling 必須是 1～%d 的整數" % (list_id, MAX_PAGE_SIZE_CEILING))
    elif not isinstance(menu, (list, tuple)) or not menu or any(not isinstance(x, int) or isinstance(x, bool) or not 1 <= x <= ceil_ for x in menu) \
            or list(menu) != sorted(set(menu)):
        out.append("%s：pageSizeMenu 必須是遞增、不重複、不超過天花板的整數清單" % list_id)
    elif d.get("pageSize") not in menu:
        out.append("%s：defaults.pageSize 必須在 pageSizeMenu 內" % list_id)
    return out


def register_list(list_id, owner, spec) -> list:
    """擁有者登記一份清單。回傳問題清單；有問題就不登記（記 warning）。不同擁有者搶同一代號 ⇒ ValueError。"""
    probs = list_problems(list_id, spec)
    if probs:
        logger.warning("清單目錄登記被拒：%s", "; ".join(probs))
        return probs
    with _lock:
        old = _LISTS.get(list_id)
        if old is not None and old["owner"] != owner:
            raise ValueError("清單 %s 已由 %s 登記，%s 不可以再登記一份" % (list_id, old["owner"], owner))
        _LISTS[list_id] = {"owner": owner, "spec": copy.deepcopy(spec)}
    return []


def lists() -> list:
    """全部清單（複本；依代號排序）。每欄附衍生的 `money`。"""
    with _lock:
        ids = sorted(_LISTS)
    return [x for x in (by_id(i) for i in ids) if x]


def by_id(list_id):
    with _lock:
        e = _LISTS.get(list_id)
        spec = copy.deepcopy(e["spec"]) if e else None
        owner = e["owner"] if e else None
    if spec is None:
        return None
    for c in spec["columns"]:
        c.setdefault("catalogId", None)
        c.setdefault("sortable", False)
        c.setdefault("required", False)
        c["money"] = is_money_column(c)
    spec["id"], spec["owner"] = list_id, owner
    return spec


def is_money_column(col) -> bool:
    """金額欄＝有 `catalogId` 且該欄位在欄位目錄的 `moneyClass != none`（衍生，不另宣告）。未知 catalogId 一律當金額欄（保守）。"""
    cat = (col or {}).get("catalogId")
    if cat is None:
        return False
    f = _FC.by_id(cat)
    return f is None or f.get("moneyClass") != "none"


def columns_of(list_id) -> list:
    e = by_id(list_id)
    return e["columns"] if e else []


def money_column_ids(list_id) -> tuple:
    return tuple(c["id"] for c in columns_of(list_id) if c["money"])


def problems() -> list:
    """目前登記的清單再驗一次（欄位目錄在登記之後才變動時抓得到）。"""
    out = []
    with _lock:
        items = [(i, copy.deepcopy(e["spec"])) for i, e in _LISTS.items()]
    for i, spec in sorted(items):
        out += list_problems(i, spec)
    return out


def section_payload() -> dict:
    """給能力目錄區段 `listCatalog` 用的內容。"""
    return {"lists": lists()}


def snapshot():
    with _lock:
        return copy.deepcopy(_LISTS)


def restore(state):
    with _lock:
        _LISTS.clear()
        _LISTS.update(copy.deepcopy(state))


_catalog.register_section(SECTION_NAME, "helpers.list_catalog", section_payload)
