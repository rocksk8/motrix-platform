# -*- coding: utf-8 -*-
"""清單偏好的公司政策（T66 L1）：定義種類 `list_pref_policy`＋寬嚴比較＋讀取。設計：docs/platform/plans/T66-LIST-PREFS-DESIGN.md §1.2。

[單位] helper:list_pref_policy    [層] L1    [穩定度] 實驗（旗標 `list_prefs.enabled` 預設關；沒有路由、沒有資料表）
[公開介面] DEFAULT_ALLOW_USER_PREFS, FIELD, GLOBAL_KEY, GROUP, KIND, OFF_REASON, compare, definition_problems, enabled, ensure_kind, policy_for
[不變式] ①旗標關（或沒開『建構器治理』）⇒ 不登記 kind（`/api/definition-kinds` 與今天相同）、`policy_for()` 回 None（＝沒有政策＝今天的行為）。
    ②key＝已登記的清單代號，或 `*`（全域預設，只能設 `allowUserPrefs` 與 `pageSize`）；政策只能在清單目錄的範圍內縮小，不能超出（欄位、排序欄位、筆數選單）。
    ③政策只存範圍與預設，不存任何使用者資料；金額欄可以出現在 `allowed`（只是上限），能不能看見仍由欄位可見政策（F7）在讀取時交集——政策永遠不能讓人看到 F7 看不到的欄位。
    ④寬嚴：放寬（允許更多欄位／排序／筆數、開放個人設定、預設顯示更多、拿掉固定欄位、預設筆數變大、看不懂的內容）＝需第二位最高管理者核准；收緊立即生效；其餘中性。
    ⑤`policy_for()` 永不丟例外：讀不到、壞掉、清單已不存在 ⇒ None。
[契約題] backend/tests/platform/test_list_pref_policy_t66.py
"""
import logging

from core import definitions as D
from helpers import list_catalog as LC

logger = logging.getLogger("motrix.list_pref_policy")

KIND = "list_pref_policy"
GROUP = "list_prefs"
FIELD = "enabled"
GLOBAL_KEY = "*"
DEFAULT_ALLOW_USER_PREFS = True            # 設計 §9-4：沒有政策列的清單預設允許個人設定（旗標本身預設關）
OFF_REASON = "清單偏好尚未開放：請先在設定中心開啟「清單個人偏好」與「建構器治理」。"
_TOP = {"version", "allowUserPrefs", "columns", "sort", "pageSize"}
_COLS = {"allowed", "pinned", "defaultHidden"}
_SORT = {"allowed", "default"}
_PS = {"allowed", "default"}


def enabled(conn=None) -> bool:
    """fail-closed：讀不到設定 ⇒ 關。必須同時開啟『建構器治理』（改動要走版本帳本與發布前預覽）。"""
    try:
        from helpers import settings_registry as SR
        if not bool(int(SR.get(GROUP, FIELD, conn=conn))):
            return False
        return int(SR.get("builder_governance", "enabled", conn=conn)) == 1
    except Exception:                                        # noqa: BLE001
        return False


def _p(path, msg):
    return {"path": path, "message": msg}


def _int_list(v):
    return isinstance(v, list) and all(isinstance(x, int) and not isinstance(x, bool) for x in v)


def _str_list(v):
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def definition_problems(key, body) -> list:
    """⇒ `[{path, message}]`（空＝合格）。"""
    if not isinstance(body, dict):
        return [_p("", "內容必須是物件")]
    out = [_p(k, "不認得的設定：%s" % k) for k in sorted(set(body) - _TOP)]
    if body.get("version") != 1:
        out.append(_p("version", "version 必須是 1"))
    if "allowUserPrefs" in body and not isinstance(body["allowUserPrefs"], bool):
        out.append(_p("allowUserPrefs", "必須是 true／false"))
    spec = None
    if key == GLOBAL_KEY:
        if "columns" in body or "sort" in body:
            out.append(_p("columns", "全域預設（*）只能設定 allowUserPrefs 與 pageSize；欄位與排序要指定清單"))
    else:
        spec = LC.by_id(key)
        if spec is None:
            return out + [_p("", "沒有這份清單：%s" % key)]
    if spec and "columns" in body:
        out += _check_columns(body["columns"], spec)
    if spec and "sort" in body:
        out += _check_sort(body, spec)
    if "pageSize" in body:
        out += _check_page_size(body["pageSize"], spec)
    if spec and not out:
        out += _check_cross(body, spec)
    return out


def _check_columns(c, spec):
    if not isinstance(c, dict):
        return [_p("columns", "必須是物件")]
    out = [_p("columns." + k, "不認得的設定：%s" % k) for k in sorted(set(c) - _COLS)]
    ids = {x["id"] for x in spec["columns"]}
    for k in ("allowed", "pinned", "defaultHidden"):
        if k in c:
            v = c[k]
            if not _str_list(v) or len(set(v)) != len(v):
                out.append(_p("columns." + k, "必須是不重複的欄位 id 清單"))
            else:
                out += [_p("columns." + k, "清單沒有這個欄位：%s" % x) for x in v if x not in ids]
    if out:
        return out
    allowed = set(c["allowed"]) if "allowed" in c else ids
    pinned, hidden = set(c.get("pinned", [])), set(c.get("defaultHidden", []))
    req = {x["id"] for x in spec["columns"] if x.get("required")}
    if not req <= allowed:
        out.append(_p("columns.allowed", "必留欄位不可拿掉：%s" % "、".join(sorted(req - allowed))))
    if not pinned <= allowed:
        out.append(_p("columns.pinned", "固定欄位必須在允許欄位內"))
    if hidden & (pinned | req):
        out.append(_p("columns.defaultHidden", "固定／必留欄位不可預設隱藏"))
    if not hidden <= allowed:
        out.append(_p("columns.defaultHidden", "預設隱藏的欄位必須在允許欄位內"))
    if not allowed - hidden:
        out.append(_p("columns", "預設至少要有一個顯示的欄位"))
    return out


def _check_sort(body, spec):
    s = body["sort"]
    if not isinstance(s, dict):
        return [_p("sort", "必須是物件")]
    out = [_p("sort." + k, "不認得的設定：%s" % k) for k in sorted(set(s) - _SORT)]
    sortable = {x["id"] for x in spec["columns"] if x.get("sortable")}
    c = body.get("columns") if isinstance(body.get("columns"), dict) else {}
    allowed_cols = set(c["allowed"]) if isinstance(c.get("allowed"), list) else {x["id"] for x in spec["columns"]}
    if "allowed" in s:
        if not _str_list(s["allowed"]) or len(set(s["allowed"])) != len(s["allowed"]):
            out.append(_p("sort.allowed", "必須是不重複的欄位 id 清單"))
        else:
            for x in s["allowed"]:
                if x not in sortable:
                    out.append(_p("sort.allowed", "這個欄位不能排序：%s" % x))
                elif x not in allowed_cols:
                    out.append(_p("sort.allowed", "排序欄位必須在允許欄位內：%s" % x))
    if "default" in s:
        d = s["default"]
        allowed_sort = set(s["allowed"]) if _str_list(s.get("allowed")) else (sortable & allowed_cols)
        if not isinstance(d, dict) or set(d) != {"col", "dir"} or d.get("dir") not in ("asc", "desc"):
            out.append(_p("sort.default", "必須是 {col, dir}，dir 為 asc／desc"))
        elif d["col"] not in allowed_sort:
            out.append(_p("sort.default", "預設排序欄位必須是允許排序的欄位"))
    return out


def _check_page_size(ps, spec):
    if not isinstance(ps, dict):
        return [_p("pageSize", "必須是物件")]
    out = [_p("pageSize." + k, "不認得的設定：%s" % k) for k in sorted(set(ps) - _PS)]
    menu = list(spec["pageSizeMenu"]) if spec else list(range(1, LC.MAX_PAGE_SIZE_CEILING + 1))
    if "allowed" in ps:
        a = ps["allowed"]
        if not _int_list(a) or not a or len(set(a)) != len(a):
            out.append(_p("pageSize.allowed", "必須是不重複的整數清單"))
        elif any(x not in menu for x in a):
            out.append(_p("pageSize.allowed", "筆數必須在允許範圍內：%s" % ("、".join(str(x) for x in menu) if spec else "1～%d" % LC.MAX_PAGE_SIZE_CEILING)))
    if "default" in ps:
        d = ps["default"]
        allowed = ps["allowed"] if _int_list(ps.get("allowed")) and ps.get("allowed") else menu
        if not isinstance(d, int) or isinstance(d, bool) or d not in allowed:
            out.append(_p("pageSize.default", "預設筆數必須在允許的筆數內"))
    return out


def _check_cross(body, spec):
    """預設排序欄位必須是預設就看得到的欄位（排序欄位必須看得到）。"""
    d = (body.get("sort") or {}).get("default")
    if not d:
        return []
    c = body.get("columns") or {}
    allowed = set(c["allowed"]) if "allowed" in c else {x["id"] for x in spec["columns"]}
    if d["col"] in set(c.get("defaultHidden", [])) or d["col"] not in allowed:
        return [_p("sort.default", "預設排序欄位不可是預設隱藏的欄位")]
    return []


def _kind_validator(body, key):
    if not enabled():
        return [{"path": "", "message": OFF_REASON}]
    return definition_problems(key, body)


def ensure_kind():
    """惰性登記 kind（旗標關＝不登記，`/api/definition-kinds` 與今天相同）。"""
    if KIND not in D.kinds() and enabled():
        try:
            D.register_kind(KIND, label="清單個人偏好政策", validator=_kind_validator)
        except ValueError:                                   # 並行登記 ⇒ 已存在
            pass
    return KIND in D.kinds()


# ── 寬嚴比較：old_body → new_body ⇒ (class, reasons)；集合 None＝不限（清單目錄全部） ─────────────────────────
def _names(s):
    return "、".join(sorted(str(x) for x in s))


def _setcmp(o, n, what, loosen, tighten, more_is_loose=True):
    """o／n 是集合或 None（不限）。`more_is_loose`：集合變大算放寬（允許清單）；False＝變大算收緊（固定／預設隱藏清單）。"""
    if o == n:
        return
    grow, shrink = (loosen, tighten) if more_is_loose else (tighten, loosen)
    if o is None:
        tighten.append("%s改為限定範圍" % what)
    elif n is None:
        loosen.append("%s改為不限" % what)
    else:
        if n - o:
            grow.append("%s新增：%s" % (what, _names(n - o)))
        if o - n:
            shrink.append("%s拿掉：%s" % (what, _names(o - n)))


def _as_set(v):
    return None if v is None else set(v)


def compare(old, new):
    """⇒ (loosen｜tighten｜neutral, 白話原因)。看不懂的結構或多出來的屬性＝放寬。"""
    old = old if isinstance(old, dict) else {}
    if not isinstance(new, dict):
        return "loosen", ["無法解析政策內容，視為放寬"]
    loosen, tighten = [], []
    loosen += ["看不懂的設定 %s（視為放寬）" % k for k in sorted((set(old) | set(new)) - _TOP)]
    a_o, a_n = old.get("allowUserPrefs", DEFAULT_ALLOW_USER_PREFS), new.get("allowUserPrefs", DEFAULT_ALLOW_USER_PREFS)
    if a_o != a_n:
        (loosen if a_n else tighten).append("個人設定改為%s" % ("開放" if a_n else "不開放"))
    oc, nc = old.get("columns") or {}, new.get("columns") or {}
    _setcmp(_as_set(oc.get("allowed")), _as_set(nc.get("allowed")), "允許的欄位", loosen, tighten)
    _setcmp(set(oc.get("pinned", [])), set(nc.get("pinned", [])), "固定欄位", loosen, tighten, more_is_loose=False)
    _setcmp(set(oc.get("defaultHidden", [])), set(nc.get("defaultHidden", [])), "預設隱藏的欄位", loosen, tighten, more_is_loose=False)
    so, sn = old.get("sort") or {}, new.get("sort") or {}
    _setcmp(_as_set(so.get("allowed")), _as_set(sn.get("allowed")), "允許的排序欄位", loosen, tighten)
    po, pn = old.get("pageSize") or {}, new.get("pageSize") or {}
    _setcmp(_as_set(po.get("allowed")), _as_set(pn.get("allowed")), "允許的每頁筆數", loosen, tighten)
    do, dn = po.get("default"), pn.get("default")
    if do != dn:
        if isinstance(dn, int) and (not isinstance(do, int) or dn > do):
            loosen.append("預設每頁筆數加大為 %s" % dn)
        else:
            tighten.append("預設每頁筆數改為 %s" % dn if dn is not None else "預設每頁筆數回到清單預設")
    if loosen:
        return "loosen", loosen + tighten
    return ("tighten", tighten) if tighten else ("neutral", [])


def policy_for(conn, list_id, role=None):
    """⇒ 這份清單目前有效的政策 body（清單專屬 ＞ `*`），或 None（＝沒有政策＝今天的行為）。旗標關、讀不到、壞掉 ⇒ None。永不丟例外。
    兩者並存時清單專屬的欄位優先、缺的用 `*` 補（pageSize 逐項合併）。"""
    try:
        if not enabled(conn) or LC.by_id(list_id) is None:
            return None
        own, _s1 = D.resolve(conn, KIND, list_id, role)
        glob, _s2 = D.resolve(conn, KIND, GLOBAL_KEY, role)
        for b in (own, glob):
            if b is not None and (not isinstance(b, dict) or b.get("version") != 1):
                return None
        if own is None and glob is None:
            return None
        out = dict(glob or {})
        out.update(own or {})
        if "pageSize" in (glob or {}) and "pageSize" in (own or {}):
            out["pageSize"] = {**glob["pageSize"], **own["pageSize"]}
        return out
    except Exception:                                        # noqa: BLE001
        logger.warning("讀取清單偏好政策失敗：%s", list_id, exc_info=True)
        return None
