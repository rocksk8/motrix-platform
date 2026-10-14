# -*- coding: utf-8 -*-
"""狀態顯示名稱與顏色（S-X2）：一張受治理的表，報價／案件／出納共用。**只改『看到的字與色』，狀態的鍵（資料庫值）永遠不變。**

[單位] helper:status_display    [層] L1    [穩定度] 實驗（旗標 builder_status_display.enabled 關＝所有畫面與今天逐位元相同）
[公開介面] KIND, KEY, TONES, CONTEXTS, OFFICIAL_WORDS, STATUS_KEYS, defaults, validate_table, compare, effective_table, changed_fields, meta, public_payload, flag_on, enabled, ensure_registered, published_body
[不變式] ①**鍵集合由程式擁有**（`STATUS_KEYS`）：使用者不能新增或刪除鍵，也不能改鍵；表只存 `label`／`names`（各情境簡稱）／`tone`／`order`；
    ②顏色只能從固定調色盤選（`TONES`，對應 css `.st-chip--*` 語意 token），不收自由色碼；
    ③官方用語保護：非『已核准』語意的鍵，名稱不可含官方用語（核准／批准／核可／已簽核／簽核完成／審核通過）——預設值本身除外；
       已核准／已付款類（approved／paid 語意）的鍵只能用對應色調，其他鍵不能用『已核准』綠與『已付款』色；
    ④比較器：已核准／已付款語意的鍵改名或改色＝放寬（走第二位核准＋確認期間）；其餘改名改色＝中性；格式看不懂＝放寬；
    ⑤旗標關／表沒發布／讀不到 ⇒ 預設表（＝今天的名稱與色調，`status-chip.js` 的對照＋報價單列表既有的情境簡稱）；絕不丟例外；
    ⑥邏輯（SQL、x-show、權限、查詢）一律用鍵，不讀這張表。
[契約題] backend/tests/test_status_display_2026_10_14.py
"""
import logging
import unicodedata

from core import definitions as D
from core import spine as _spine

KIND = "status_display"
KEY = "default"                       # 整個公司一份
GROUP, FIELD = "builder_status_display", "enabled"
_log = logging.getLogger(__name__)

#: 色調調色盤 ⇒ 前端 class（`neutral` 只有基底 `st-chip`）。與 css/style.css:952-965 一致。
TONES = ("neutral", "draft", "pending", "signing", "approved", "rejected", "paid", "void")
#: 情境（各畫面用的簡稱槽）。`default` 就是 label 本身，不放在 names 裡。
CONTEXTS = ("quote_list", "quote_form", "case", "cashier", "report", "settlement")
OFFICIAL_WORDS = ("核准", "核準", "批准", "核可", "已簽核", "簽核完成", "簽核通過", "審核通過", "已通過", "通過", "生效", "確認", "已批", "批示", "已准", "准予", "ok")
#: 開頭是這些否定／等待字的名稱可以含官方用語（待核准、未通過、等待確認 都是『還沒』的意思）
_NEGATORS = ("待", "未", "尚未", "等待", "不")
#: 這些字元在畫面上看不見或看起來像空白，用來把官方用語拆開以躲過比對：一律拒絕
_HIDDEN = {0x3164, 0x115F, 0x1160, 0xFFA0, 0x2800, 0x034F}
_MAX_LABEL = 12

#: (鍵, 群組, 語意, 預設色調)；語意決定色調與用語限制：approved＝已核准與精算完結（結果已定案）、paid＝已付款／已匯款、其餘 plain。
_RAW = (
    ("草稿", "approval", "plain", "draft"), ("待審核", "approval", "plain", "pending"), ("待核准", "approval", "plain", "pending"),
    ("簽核中", "approval", "plain", "signing"), ("已核准", "approval", "approved", "approved"),
    ("已駁回", "approval", "plain", "rejected"), ("已退回", "approval", "plain", "rejected"), ("已拒絕", "approval", "plain", "rejected"),
    ("已付款", "approval", "paid", "paid"), ("已匯款", "approval", "paid", "paid"),
    ("已作廢", "approval", "plain", "void"), ("已取消", "approval", "plain", "void"), ("已撤回", "approval", "plain", "void"), ("已撤銷", "approval", "plain", "void"),
    ("已送出", "quote", "plain", "neutral"),
    ("未提供", "deal", "plain", "neutral"), ("已提供", "deal", "plain", "neutral"), ("未成案", "deal", "plain", "neutral"),
    ("已成案", "deal", "plain", "neutral"), ("已結案", "deal", "plain", "neutral"),
    ("draft", "settle", "plain", "draft"), ("finalized", "settle", "approved", "approved"),
)
STATUS_KEYS = tuple(r[0] for r in _RAW)
_SEMANTIC = {r[0]: r[2] for r in _RAW}
_GROUP = {r[0]: r[1] for r in _RAW}
_TONE0 = {r[0]: r[3] for r in _RAW}

#: 今天各畫面的情境簡稱（原樣保留）：quotations.html:653-664 `statusBadge()`。
_NAMES0 = {
    "待審核": {"quote_list": "審核中"}, "已拒絕": {"quote_list": "已退回"},
    "已成案": {"quote_list": "執行中"}, "已提供": {"quote_list": "待決定"},
    "finalized": {"report": "已結算", "case": "已定稿", "settlement": "精算完結"},     # reports.html:1251／case-management.html:2699／settlement.html:307
    "draft": {"settlement": "精算草稿"},
}
# 沒有情境簡稱時的預設標籤；其餘＝鍵本身（原值照印，與今天相同）
_LABEL0 = {"finalized": "已完結"}


def _tone_allowed(key, tone):
    sem = _SEMANTIC[key]
    if sem == "approved":
        return tone == "approved"
    if sem == "paid":
        return tone in ("paid", "approved")
    return tone not in ("approved", "paid")


def defaults() -> dict:
    """預設表 `{鍵: {label, names, tone, order}}`（今天的名稱與色調）。"""
    out = {}
    for i, k in enumerate(STATUS_KEYS):
        out[k] = {"label": _LABEL0.get(k, k), "names": dict(_NAMES0.get(k, {})), "tone": _TONE0[k], "order": (i + 1) * 10}
    return out


def _p(path, msg):
    return {"path": path, "message": msg}


def _hidden_chars(text):
    """文字裡有看不見／組合／格式／私用字元 ⇒ True（NFKC 與一般 strip 都不會移除它們）。"""
    for ch in text:
        cat = unicodedata.category(ch)
        if cat in ("Cc", "Cf", "Co", "Cn", "Mn", "Me") or ord(ch) in _HIDDEN or (cat.startswith("Z") and ch != " "):
            return True
    return False


def _norm(text):
    return unicodedata.normalize("NFKC", text).lower()


def _banned(key, text, default_text):
    """非核准語意的鍵，名稱不可使用官方用語（比對前先做 NFKC 與小寫；預設值本身與『待／未／等待』開頭的除外）。"""
    if _SEMANTIC[key] == "approved" or text == default_text:
        return False
    t = _norm(text)
    if t.startswith(_NEGATORS):
        return False
    return any(w in t for w in OFFICIAL_WORDS)


def _texts(table, k):
    """某鍵在每個情境實際顯示的字：{'default': label, ctx: names[ctx] or label}。"""
    e = table[k]
    out = {"default": e["label"]}
    for c in CONTEXTS:
        out[c] = e["names"].get(c) or e["label"]
    return out


def _conflicts(body_table):
    """名稱撞車：被改過的欄位，不可和『其他鍵』在同一情境顯示的字相同；非核准／付款語意的鍵更不可使用核准／付款類狀態在任何情境的字。⇒ 問題清單"""
    base = defaults()
    out = []
    reserved = set()
    for k in STATUS_KEYS:
        if _SEMANTIC[k] in ("approved", "paid"):
            reserved |= {_norm(t) for t in _texts(body_table, k).values()} | {_norm(t) for t in _texts(base, k).values()}
    for k in STATUS_KEYS:
        mine, dflt = _texts(body_table, k), _texts(base, k)
        for ctx, t in mine.items():
            if t == dflt[ctx]:
                continue                                              # 沒被改過的欄位不檢查（預設值本身有重複，例如 已退回）
            nt = _norm(t)
            if _SEMANTIC[k] not in ("approved", "paid") and nt in reserved:
                out.append(_p("statuses.%s" % k, "『%s』與核准／付款類狀態的名稱相同，不可使用" % t))
                continue
            for k2 in STATUS_KEYS:
                if k2 != k and _norm(_texts(body_table, k2)[ctx]) == nt:
                    out.append(_p("statuses.%s" % k, "『%s』在%s已被『%s』使用，名稱不可重複" % (t, "預設" if ctx == "default" else ctx, k2)))
                    break
    return out


def validate_table(body, key=KEY) -> list:
    """⇒ 問題清單（空＝合格）。body 只放『與預設不同』的鍵也可以（缺的鍵用預設）。不丟例外。"""
    try:
        return _validate(body, key)
    except Exception as e:                                           # noqa: BLE001
        return [_p("", "狀態表無法驗證（%s）" % type(e).__name__)]


def _validate(body, key):
    if key != KEY:
        return [_p("", "狀態顯示表只有一份，代號必須是 %s" % KEY)]
    if not isinstance(body, dict) or set(body) - {"statuses"}:
        return [_p("", "狀態顯示表必須是 {statuses: {…}}，不接受其他欄位")]
    st = body.get("statuses", {})
    if not isinstance(st, dict):
        return [_p("statuses", "statuses 必須是物件")]
    out, dflt = [], defaults()
    for k, v in st.items():
        path = "statuses.%s" % k
        if k not in STATUS_KEYS:
            out.append(_p(path, "未知的狀態鍵：%s（鍵由程式擁有，不能新增）" % k))
            continue
        if not isinstance(v, dict) or set(v) - {"label", "names", "tone", "order"}:
            out.append(_p(path, "每個狀態只接受 label／names／tone／order"))
            continue
        lab = v.get("label", dflt[k]["label"])
        if not isinstance(lab, str) or not lab.strip() or len(lab.strip()) > _MAX_LABEL or lab != lab.strip() or _hidden_chars(lab):
            out.append(_p(path + ".label", "名稱必填、不可有前後空白或看不見的字元、最多 %d 字" % _MAX_LABEL))
        elif _banned(k, lab, dflt[k]["label"]):
            out.append(_p(path + ".label", "非『已核准』語意的狀態不可使用官方用語（%s）" % "、".join(OFFICIAL_WORDS)))
        tone = v.get("tone", dflt[k]["tone"])
        if tone not in TONES:
            out.append(_p(path + ".tone", "色調必須是：%s" % "、".join(TONES)))
        elif not _tone_allowed(k, tone):
            out.append(_p(path + ".tone", "這個狀態不能使用該色調（綠色『已核准』與『已付款』色只留給對應狀態）"))
        order = v.get("order", dflt[k]["order"])
        if not isinstance(order, int) or isinstance(order, bool) or not 0 <= order <= 999:
            out.append(_p(path + ".order", "排序必須是 0～999 的整數"))
        names = v.get("names", {})
        if not isinstance(names, dict) or set(names) - set(CONTEXTS):
            out.append(_p(path + ".names", "情境簡稱只接受：%s" % "、".join(CONTEXTS)))
        else:
            for c, txt in names.items():
                if not isinstance(txt, str) or not txt.strip() or len(txt.strip()) > _MAX_LABEL or txt != txt.strip() or _hidden_chars(txt):
                    out.append(_p(path + ".names." + c, "簡稱必填、不可有前後空白或看不見的字元、最多 %d 字" % _MAX_LABEL))
                elif _banned(k, txt, dflt[k]["names"].get(c)):
                    out.append(_p(path + ".names." + c, "非『已核准』語意的狀態不可使用官方用語（%s）" % "、".join(OFFICIAL_WORDS)))
    if not out:
        out += _conflicts(effective_table(body))
    return out


def effective_table(body) -> dict:
    """把 body（可只含差異）疊在預設上 ⇒ 完整表。body 不合法的部分不會被採用（呼叫端已驗證；這裡再保守一次）。"""
    out = defaults()
    st = (body or {}).get("statuses") if isinstance(body, dict) else None
    if not isinstance(st, dict):
        return out
    for k, v in st.items():
        if k in out and isinstance(v, dict):
            cur = out[k]
            if isinstance(v.get("label"), str):
                cur["label"] = v["label"]
            if v.get("tone") in TONES:
                cur["tone"] = v["tone"]
            if isinstance(v.get("order"), int) and not isinstance(v.get("order"), bool):
                cur["order"] = v["order"]
            if isinstance(v.get("names"), dict):
                merged = dict(cur["names"])
                merged.update({c: t for c, t in v["names"].items() if c in CONTEXTS and isinstance(t, str)})
                cur["names"] = merged
    return out


def meta() -> dict:
    """編輯器用：每個鍵的群組、語意、允許的色調（與驗證器同一份規則）。不含任何金額或權限資訊。"""
    return {k: {"group": _GROUP[k], "semantic": _SEMANTIC[k], "allowedTones": [t for t in TONES if _tone_allowed(k, t)]} for k in STATUS_KEYS}


def changed_fields(table) -> dict:
    """完整表相對預設表的差異 ⇒ `{鍵: ["label", "tone", "order", "names.<情境>"…]}`（沒有差異的鍵不出現）。
    前端只對『有差異』的欄位覆寫畫面原本的字與色，沒差異的維持畫面自己的做法——所以旗標開了但沒改任何東西時，畫面與今天相同。"""
    base, out = defaults(), {}
    for k in STATUS_KEYS:
        fs = [f for f in ("label", "tone", "order") if table[k][f] != base[k][f]]
        fs += ["names." + c for c in sorted(set(table[k]["names"]) | set(base[k]["names"])) if table[k]["names"].get(c) != base[k]["names"].get(c)]
        if fs:
            out[k] = fs
    return out


def compare(old, new):
    """⇒ (class, reasons)；class ∈ loosen／neutral（顯示名稱與顏色沒有『收緊』）。已核准／已付款語意的鍵被改名或改色＝放寬；看不懂＝放寬。"""
    try:
        if validate_table(old) or validate_table(new):
            return "loosen", ["狀態表格式無法比較"]
        a, b = effective_table(old), effective_table(new)
        reasons = []
        for k in STATUS_KEYS:
            if a[k] == b[k]:
                continue
            if _SEMANTIC[k] in ("approved", "paid"):
                reasons.append("『%s』是核准／付款類狀態，名稱或顏色被改（%s → %s）" % (k, a[k]["label"], b[k]["label"]))
        return ("loosen", reasons) if reasons else ("neutral", [])
    except Exception:                                                # noqa: BLE001
        return "loosen", ["狀態表比較失敗，視為放寬"]


# ── 旗標、登記、讀取 ───────────────────────────────────────────────────────────────────────────
def flag_on(conn=None) -> bool:
    try:
        from helpers import settings_registry as SR
        return int(SR.get(GROUP, FIELD, conn=conn)) == 1
    except Exception:                                                # noqa: BLE001
        return False


def enabled(conn=None) -> bool:
    """旗標開 **且** 建構器治理開（否則放寬無法走待核准，不可編輯也不生效）。"""
    if not flag_on(conn):
        return False
    try:
        from routers import def_pipeline as P
        return bool(P.enabled(conn))
    except Exception:                                                # noqa: BLE001
        return False


def _validator(body, key):
    return validate_table(body, key)


def _default(key):
    return {"statuses": {}}


def _gate(key):
    return "open" if enabled() else "hidden"


def ensure_registered() -> None:
    try:
        if KIND not in D.kinds():
            D.register_kind(KIND, label="狀態顯示名稱與顏色", validator=_validator, default=_default)
        if not _spine.has_kind_gate(KIND):
            _spine.register_kind_gate(KIND, _gate)
    except ValueError:
        pass


def published_body(conn) -> dict:
    try:
        r = D.get(conn, KIND, KEY, "company")
        b = (r or {}).get("body")
        return b if isinstance(b, dict) and not validate_table(b) else {}
    except Exception:                                                # noqa: BLE001
        _log.warning("status_display: 讀取已發布的狀態表失敗，使用預設表", exc_info=True)
        return {}


def public_payload(conn=None) -> dict:
    """給前端的內容：旗標關 ⇒ `{"enabled": false}`（不帶表）；開 ⇒ `{"enabled": true, "tones": [...], "contexts": [...], "statuses": 完整表, "changed": {鍵: [有差異的欄位]}, "meta": {鍵: {group, semantic, allowedTones}}, "defaults": 預設表}`。永不丟例外。"""
    try:
        if not enabled(conn):
            return {"enabled": False}
        if conn is None:
            import db
            c = db.get_db()
            try:
                return public_payload(c)
            finally:
                c.close()
        ensure_registered()
        tbl = effective_table(published_body(conn))
        return {"enabled": True, "tones": list(TONES), "contexts": list(CONTEXTS), "statuses": tbl, "changed": changed_fields(tbl), "meta": meta(), "defaults": defaults()}
    except Exception:                                                # noqa: BLE001
        return {"enabled": False}
