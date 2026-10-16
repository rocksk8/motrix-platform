# -*- coding: utf-8 -*-
"""小模組的狀態／單位／用語顯示名稱（C7）：網路規劃狀態、採購建議狀態、住宿計價單位與管道。**只改『看到的字』，狀態值（資料庫值）永遠不變。**

[單位] helper:display_labels    [層] L1    [穩定度] 實驗
[公開介面] DEFAULTS, GROUPS, NETPLAN_KEY, label, labels, register, status_text
[不變式] ①預設＝各畫面今天寫死的字（部署零行為變更）；設定讀不到、不合法 ⇒ 用預設，絕不丟例外；
    ②只換顯示名稱：狀態值（規劃中／已確認／已交付、suggested／ordered／received、per_night／per_person…）、轉換順序、查詢與權限一律用原值；
    ③名稱規則：必填、最多 12 字、只能用中文、英數字與少數符號；同一組內不可重複；不是預設值的名稱不可含官方用語（核准／批准／核可／已簽核…），
       以免一般狀態被看成『已核准』（沿用 status_display 的官方用語清單）；
    ④純顯示：沒有放寬／收緊之分，立即生效。
設計：設定群組寫在本檔 `register`（由 `settings_groups` 載入時呼叫，群組屬 core）；前端從既有的 `/api/settings-center/public` 取值（static/display-labels.js）。
[契約題] backend/tests/platform/test_display_labels_c7.py
"""
import re
import unicodedata

#: 組 → {欄位鍵: 今天的名稱}（順序＝設定中心顯示順序）。
DEFAULTS = {
    "netplan_labels": {"planning": "規劃中", "confirmed": "已確認", "delivered": "已交付"},
    "procurement_labels": {"suggested": "待下單", "ordered": "已下單", "received": "已到貨"},
    "lodging_labels": {"per_night": "每晚", "per_person": "每人", "phone": "電話", "website": "官網", "onsite": "現場", "other": "其他"},
}
GROUPS = tuple(DEFAULTS)
#: 網路規劃的狀態值（資料庫值）→ 欄位鍵
NETPLAN_KEY = {"規劃中": "planning", "已確認": "confirmed", "已交付": "delivered"}

_MAX = 12
_PUNCT = " ()/-_.:"
_MEMO = {}


def _chars_ok(text):
    for ch in unicodedata.normalize("NFKC", text):
        if "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿" or (ch.isascii() and ch.isalnum()) or ch in _PUNCT:
            continue
        return False
    return True


def _squash(text):
    return "".join(ch for ch in unicodedata.normalize("NFKC", text).casefold() if ch.isalnum())


def _official(text):
    from helpers import status_display as SD
    m = _squash(text)
    if any(_squash(w) in m for w in SD.OFFICIAL_WORDS if _squash(w)):
        return True
    tokens = re.findall(r"[a-z]+", unicodedata.normalize("NFKC", text).casefold())
    compact = "".join(tokens)
    return any(x in SD.ENGLISH_TOKENS for x in tokens) or compact in SD.ENGLISH_TOKENS or any(w in compact for w in ("approve", "granted", "accepted", "confirmed"))


def _problems(group, values):
    """⇒ 問題清單（空＝合格）。values＝{欄位鍵: 名稱}，缺的欄位用預設。"""
    base = DEFAULTS[group]
    out, seen = [], {}
    for k, dflt in base.items():
        v = values.get(k, dflt)
        if not isinstance(v, str) or not v.strip() or v != v.strip() or len(v) > _MAX or not _chars_ok(v):
            out.append("名稱必填、最多 %d 字、不可有前後空白；只能用中文、英數字與少數符號（空白 ( ) / - _ . :）。" % _MAX)
            continue
        if v != dflt and _official(v):
            out.append("『%s』含有官方用語（核准、批准、核可、已簽核…），一般狀態不可使用，以免被看成『已核准』。" % v)
        key = _squash(v)
        if key in seen:
            out.append("『%s』在同一組已被使用，名稱不可重複。" % v)
        seen[key] = k
    return out


def _stored(group, conn=None):
    try:
        from helpers import settings_registry as sr
        vals = sr.get_group(group, conn=conn)
        return {k: vals[k] for k in DEFAULTS[group] if isinstance(vals.get(k), str)}
    except Exception:                                                                    # noqa: BLE001 — 純顯示，讀不到不可影響頁面
        return {}


def labels(group, conn=None) -> dict:
    """某一組的 {欄位鍵: 名稱}。任何不合法 ⇒ 整組回今天的名稱（不是半套）。"""
    base = DEFAULTS[group]
    got = _stored(group, conn)
    if not got:
        return dict(base)
    mk = (group, tuple(sorted(got.items())))
    hit = _MEMO.get(mk)
    if hit is None:                                        # 歷史紀錄一頁幾百列都會問：同樣的值只驗一次
        hit = dict(base) if _problems(group, got) else {k: got.get(k, base[k]) for k in base}
        if len(_MEMO) > 64:
            _MEMO.clear()
        _MEMO[mk] = hit
    return dict(hit)


def label(group, key, conn=None) -> str:
    """單一名稱；找不到鍵 ⇒ 回原鍵字串。"""
    return labels(group, conn).get(key, key if isinstance(key, str) else "")


def status_text(value, conn=None) -> str:
    """網路規劃：資料庫狀態值 ⇒ 顯示名稱；不認得的值原樣回傳。"""
    k = NETPLAN_KEY.get(value)
    return label("netplan_labels", k, conn) if k else (value or "")


def _cross(group):
    def check(values):
        return _problems(group, values)
    return check


def register(S, _register_core):
    def f(group, key, question, label_, where):
        d = DEFAULTS[group][key]
        return S(key, "str", d, risk="none", recommended=d, question=question, label=label_,
                 help="%s目前的名稱是「%s」（＝畫面原本的字）。" % (where, d),
                 impact="影響範圍：%s只換畫面上看到的名稱，不改任何資料、狀態判斷、順序或權限；已存的資料不變，立即生效，可隨時改回。" % where)

    _register_core(
        "netplan_labels", "網路規劃：狀態名稱",
        [f("netplan_labels", "planning", "網路規劃書「剛建立、還在規劃」的狀態，要顯示成什麼名稱？", "「規劃中」的顯示名稱", "網路規劃清單、分頁統計與規劃書頁面上的第一個狀態。"),
         f("netplan_labels", "confirmed", "網路規劃書「客戶已確認、待交付」的狀態，要顯示成什麼名稱？", "「已確認」的顯示名稱", "網路規劃清單、分頁統計與規劃書頁面上的第二個狀態。"),
         f("netplan_labels", "delivered", "網路規劃書「已交付完成」的狀態，要顯示成什麼名稱？", "「已交付」的顯示名稱", "網路規劃清單、分頁統計與規劃書頁面上的第三個狀態。")],
        sensitive=False, risk="none", cross_check=_cross("netplan_labels"),
        help="網路規劃書三個狀態在畫面上的名稱。只改看到的字；狀態順序（規劃中→已確認→已交付）與可做的操作不變。",
    )
    _register_core(
        "procurement_labels", "採購建議：狀態名稱",
        [f("procurement_labels", "suggested", "採購建議「還沒下單」的狀態，要顯示成什麼名稱？", "「待下單」的顯示名稱", "庫存頁採購建議視窗的第一個狀態。"),
         f("procurement_labels", "ordered", "採購建議「已經下單、東西在路上」的狀態，要顯示成什麼名稱？", "「已下單」的顯示名稱", "庫存頁採購建議視窗的第二個狀態與「標記已下單」按鈕。"),
         f("procurement_labels", "received", "採購建議「已經到貨」的狀態，要顯示成什麼名稱？", "「已到貨」的顯示名稱", "庫存頁採購建議視窗的「標記已到貨」按鈕。")],
        sensitive=False, risk="none", cross_check=_cross("procurement_labels"),
        help="採購建議三個狀態在畫面上的名稱。只改看到的字；三個狀態必須依序經歷的規則不變。",
    )
    _register_core(
        "lodging_labels", "住宿紀錄：計價單位與詢價管道",
        [f("lodging_labels", "per_night", "住宿報價「每晚計價」要顯示成什麼名稱？", "「每晚」的顯示名稱", "住宿報價清單與詳細頁的計價單位。"),
         f("lodging_labels", "per_person", "住宿報價「每人計價」要顯示成什麼名稱？", "「每人」的顯示名稱", "住宿報價清單與詳細頁的計價單位。"),
         f("lodging_labels", "phone", "詢價管道「電話」要顯示成什麼名稱？", "「電話」的顯示名稱", "住宿報價清單與詳細頁的詢價管道。"),
         f("lodging_labels", "website", "詢價管道「官網」要顯示成什麼名稱？", "「官網」的顯示名稱", "住宿報價清單與詳細頁的詢價管道。"),
         f("lodging_labels", "onsite", "詢價管道「現場」要顯示成什麼名稱？", "「現場」的顯示名稱", "住宿報價清單與詳細頁的詢價管道。"),
         f("lodging_labels", "other", "詢價管道「其他」要顯示成什麼名稱？", "「其他」的顯示名稱", "住宿報價清單與詳細頁的詢價管道。")],
        sensitive=False, risk="none", cross_check=_cross("lodging_labels"),
        help="住宿報價的計價單位與詢價管道在畫面上的名稱。只改看到的字；已存的報價資料不變。",
    )
