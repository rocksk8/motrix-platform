# -*- coding: utf-8 -*-
"""簽核事件通知用語範本（S-X3 第一刀：報價單送審 `approval:submitted`；設計 docs/platform/plans/S-X3-NOTIFY-WORDING-DESIGN-T62.md）。

[單位] helper:notify_templates    [層] L1    [穩定度] 實作
[公開介面] EVENTS, EVENTS_LIMIT_REASON, FIELD, GROUP, KIND, OFF_REASON, RESERVED, RESERVED_EN, definition_problems, default_template, enabled, ensure_kind, mail_fields, preview, render_inapp, render_mail, resolve
[不變式] 設定 `builder_notify.enabled`（預設 0＝關；且必須同時開啟 `builder_governance.enabled`）關著、沒有已發布範本、範本不合法或任何錯誤時：
    `render_inapp()`／`render_mail()` 一律回 None ⇒ 呼叫端走今天寫死的字（站內訊息、信件主旨與內文逐位元相同）。
    範本只收宣告式純文字：占位符只能是該事件的白名單（`{單號}` 等），沒有運算式、沒有 HTML／標記、沒有隱形字元、沒有網址、沒有官方狀態字樣；
    信件主旨前綴【MOTRIX 系統通知】與分類固定（`mail_types.subject`），範本只改『事由』；信件版型、按鈕連結、發送時間與來源區段固定。
    站內訊息展開後仍由 `audit._notify` 逐收件人經 `_mask_money` 遮蔽；信件通道沒有金額占位符。
    **事件型與收件人不由範本決定**（誰收到、何時寄、核准冪等都是程式）。
[契約題] tests/platform/test_notify_templates_t62.py
[注意] 新增一個 kind `notify_template`（key＝事件代號，scope＝company），惰性登記（旗標關 ⇒ 不登記）；版本／差異／還原／帳本／發布前預覽沿用定義文件庫與治理層；
    任何文字變更＝放寬（需第二位最高管理者核准），拿掉＝收緊。
"""
import re
import unicodedata

from core import definitions as D

GROUP = "builder_notify"
FIELD = "enabled"
KIND = "notify_template"
OFF_REASON = "自訂通知用語尚未開放（設定中心：自訂通知用語）"

#: 事件登記：代號 ⇒ {label, fields: {通道.欄位: {default, limit, placeholders, need}}}。預設字＝今天寫死的字（逐位元）。
#: `need`＝必須出現的占位符（讓收件人能認出是哪一張單）。
EVENTS = {
    "approval:submitted": {
        "label": "報價單送審（通知當層簽核人）",
        "sample": {"單號": "MQ-202610-001", "對象": "範例客戶股份有限公司", "標記": ""},
        "fields": {
            "inapp.message": {"label": "站內訊息", "default": "報價單 {單號}{標記}（{對象}）需要您簽核", "limit": 100,
                              "placeholders": ("單號", "對象", "標記"), "need": ("單號",)},
            "mail.reason": {"label": "信件主旨（事由）", "default": "報價單待審核：{單號}（{對象}）", "limit": 60,
                            "placeholders": ("單號", "對象"), "need": ("單號",)},
            "mail.title": {"label": "信件標題", "default": "報價單簽核申請", "limit": 30, "placeholders": (), "need": ()},
            "mail.badge": {"label": "信件徽章字", "default": "待您審核", "limit": 12, "placeholders": (), "need": ()},
            "mail.intro": {"label": "信件引言", "default": "您好，以下報價單已進入簽核流程，敬請於系統中完成審核作業。", "limit": 120,
                           "placeholders": ("單號", "對象"), "need": ()},
            "mail.button": {"label": "信件按鈕字", "default": "前往審核報價單", "limit": 20, "placeholders": (), "need": ()},
        },
    },
}

EVENTS_LIMIT_REASON = 200                                    # 主旨事由展開後的長度上限（含客戶名稱；模板本身另有 60 字限制）
_PH = re.compile(r"\{([^{}]{1,12})\}")
#: 控制字元、雙向覆寫／隔離、零寬、BOM；尖括號、&、引號、反斜線一律不收（花括號只用在占位符，另行檢查）
_BAD = re.compile("[<>&\"'`\\\\\x00-\x1f\x7f​-‏‪-‮⁦-⁩﻿]")
_FILLERS = frozenset("ᅟᅠㅤﾠ⠀᠎͏؜឴឵­⁠")
#: 網址／連結的各種寫法（NFKC 之後比對，全形點與斜線也擋）：http(s)、://、www.、任何『英數.英數(2字以上)』（bit.ly、a.tw、line.me）、任何斜線
_URLISH = re.compile(r"https?|://|www\.|[A-Za-z0-9_]+\.[A-Za-z0-9_]{2,}|/", re.I)
#: 官方狀態詞：送審通知不得宣稱已核准／已通過／已付款等。中文比對在『只留字母與數字的骨架』上（NFKC＋casefold，插空白／全形／隱形字元都繞不過）；
#: 英文單字用字界比對（final／finally、paid／unpaid、void／avoid 不誤傷）。
RESERVED = ("正本", "副本", "已核准", "已核可", "核准", "核可", "簽核完成", "签核完成", "已付款", "已收款", "已簽回", "已簽收", "作廢", "作废",
            "已通過", "通過", "已通过", "通过", "批准", "審核通過", "审核通过", "簽核通過", "签核通过", "已簽核", "已签核", "已批", "已生效")
RESERVED_EN = ("approve", "approved", "passed", "paid", "original", "void", "signed", "final")
_EN_RE = re.compile(r"(?<![a-z])(?:%s)(?![a-z])" % "|".join(RESERVED_EN))
_TOP = {"version", "inapp", "mail"}


def enabled(conn=None) -> bool:
    """fail-closed：讀不到設定 ⇒ 關。必須同時開啟『建構器治理』（放寬要靠第二位最高管理者核准與發布前預覽）。"""
    try:
        from helpers import settings_registry as SR
        if not bool(int(SR.get(GROUP, FIELD, conn=conn))):
            return False
        return int(SR.get("builder_governance", "enabled", conn=conn)) == 1
    except Exception:                                        # noqa: BLE001
        return False


def _skeleton(v):
    return "".join(ch for ch in unicodedata.normalize("NFKC", v).casefold() if ch.isalnum())


def _text_problems(text, spec):
    if not isinstance(text, str) or not text.strip():
        return "必須是不空白的文字"
    if len(text) > spec["limit"]:
        return "最多 %d 字" % spec["limit"]
    if any(unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp", "Co", "Cs") or ch in _FILLERS for ch in text):
        return "不可含控制、隱形、雙向或私用字元"
    if _BAD.search(text):
        return "不可含標記字元（< > & 引號 反斜線）"
    if _URLISH.search(unicodedata.normalize("NFKC", _PH.sub("", text))):
        return "不可含網址或連結（含斜線、網域寫法）"
    names = _PH.findall(text)
    for n in names:
        if n not in spec["placeholders"]:
            return "不認得的占位符 {%s}（可用：%s）" % (n, "、".join("{%s}" % p for p in spec["placeholders"]) or "無")
    if "{" in _PH.sub("", text) or "}" in _PH.sub("", text):
        return "大括號只能用在占位符"
    for n in spec["need"]:
        if n not in names:
            return "必須包含 {%s}（讓收件人認得是哪一張單）" % n
    flat = _PH.sub("", text)
    hit = [w for w in RESERVED if _skeleton(w) in _skeleton(flat)]
    hit += _EN_RE.findall(unicodedata.normalize("NFKC", flat).casefold())
    if hit:
        return "不可含官方狀態字樣：%s" % "、".join(hit)
    return ""


def definition_problems(key, body):
    """發布前驗證 ⇒ `[{path, message}]`（空＝通過）。"""
    ev = EVENTS.get(key)
    if ev is None:
        return [{"path": "", "message": "不認得的通知事件：%s" % (key,)}]
    if not isinstance(body, dict):
        return [{"path": "", "message": "範本必須是物件"}]
    out = []
    if body.get("version") != 1:
        out.append({"path": "version", "message": "版本必須是 1"})
    for k in body:
        if k not in _TOP:
            out.append({"path": k, "message": "不認得的設定：%s" % k})
    n_fields = 0
    for chan in ("inapp", "mail"):
        if chan not in body:
            continue
        sec = body[chan]
        if not isinstance(sec, dict):
            out.append({"path": chan, "message": "必須是物件"})
            continue
        for f, v in sec.items():
            spec = ev["fields"].get("%s.%s" % (chan, f))
            if spec is None:
                out.append({"path": "%s.%s" % (chan, f), "message": "不認得的欄位：%s" % f})
                continue
            n_fields += 1
            p = _text_problems(v, spec)
            if p:
                out.append({"path": "%s.%s" % (chan, f), "message": "%s：%s" % (spec["label"], p)})
    if n_fields == 0 and not out:
        out.append({"path": "", "message": "至少要設定一個欄位"})
    return out


def default_template(key) -> dict:
    ev = EVENTS[key]
    out = {"version": 1}
    for path, spec in ev["fields"].items():
        chan, f = path.split(".")
        out.setdefault(chan, {})[f] = spec["default"]
    return out


def _kind_validator(body, key):
    return definition_problems(key, body)


def _gate(key):
    """通用定義路由的功能狀態閘門（`spine.register_kind_gate`）：旗標或治理關閉 ⇒ hidden（404），已存的草稿也無法在管線之外被發布。"""
    return "open" if enabled() else "hidden"


from core import spine as _spine  # noqa: E402

_spine.register_kind_gate(KIND, _gate)


def ensure_kind():
    """惰性登記 kind（旗標關＝不登記，`/api/definition-kinds` 與今天相同）。"""
    if KIND not in D.kinds() and enabled():
        try:
            D.register_kind(KIND, label="通知用語", validator=_kind_validator)
        except ValueError:                                   # 並行登記 ⇒ 已存在
            pass
    return KIND in D.kinds()


def resolve(key, conn=None):
    """⇒ 已發布且仍合法的範本，或 None（旗標關、沒有已發布、不合法、任何錯誤 ⇒ None＝呼叫端走今天寫死的字）。"""
    if key not in EVENTS or not enabled(conn):
        return None
    ensure_kind()
    try:
        from db import get_db
        own = conn is None
        c = conn if conn is not None else get_db()
        try:
            r = D.get(c, KIND, key, "company")
        finally:
            if own:
                c.close()
        body = (r or {}).get("body")
        if not body or definition_problems(key, body):
            return None
        return body
    except Exception:                                        # noqa: BLE001
        return None


def _expand(text, ctx):
    return _PH.sub(lambda m: str(ctx.get(m.group(1), "")), text)


def _plain(v):
    """純文字欄位（信件主旨）用的占位符值：去掉換行與控制字元（防主旨被塞進換行）。"""
    return re.sub(r"[\x00-\x1f\x7f\u2028\u2029]+", " ", str(v)).strip()


def render_inapp(key, ctx, conn=None):
    """站內訊息 ⇒ 展開後的字串，或 None（走今天的寫法）。金額遮蔽由 `audit._notify` 逐收件人處理。"""
    body = resolve(key, conn)
    text = ((body or {}).get("inapp") or {}).get("message")
    if not text:
        return None
    try:
        return _expand(text, ctx)
    except Exception:                                        # noqa: BLE001
        return None


def mail_fields(key, ctx, conn=None):
    """信件欄位 ⇒ `{reason,title,badge,intro,button}`（只含範本有設定的欄位；**純文字**——主旨直接用，內文由 `_build_html` 逸出），或 None。"""
    body = resolve(key, conn)
    sec = (body or {}).get("mail")
    if not isinstance(sec, dict) or not sec:
        return None
    try:
        plain = {k: _plain(v) for k, v in ctx.items()}
        out = {}
        for f, t in sec.items():
            if f == "reason":                                # 信件主旨是純文字：只展開，不做 HTML 逸出（客戶名稱 A&B 不能變成 A&amp;B）
                out[f] = _expand(t, plain)[:EVENTS_LIMIT_REASON]
            else:                                            # 內文欄位：回傳純文字，由 `email_notify._build_html` 對簽核類信件統一逸出（不在這裡重複逸出）
                out[f] = _expand(t, ctx)
        return out
    except Exception:                                        # noqa: BLE001
        return None


def render_mail(key, ctx, conn=None):
    """同 `mail_fields`（別名，呼叫端語意較清楚）。"""
    return mail_fields(key, ctx, conn)


def preview(conn, caller, body, key):
    """唯讀預覽：樣本單據＋目前（已發布或預設）vs 草稿，兩個收件人視角（有／沒有財務權限）。不寫任何資料。"""
    ev = EVENTS.get(key)
    if ev is None:
        raise LookupError("沒有這個通知事件")
    problems = definition_problems(key, body)
    if problems:
        raise ValueError(problems)
    try:
        from helpers.audit import _MONEY_RE
        mask = lambda t: _MONEY_RE.sub("（金額略）", t)                   # noqa: E731  與 audit._mask_money 同一條規則
    except Exception:                                        # noqa: BLE001
        mask = lambda t: t                                    # noqa: E731
    cur = resolve(key, conn) or default_template(key)
    ctx = dict(ev["sample"])
    rows = []
    for path, spec in ev["fields"].items():
        chan, f = path.split(".")
        now = (cur.get(chan) or {}).get(f, spec["default"])
        new = (body.get(chan) or {}).get(f, spec["default"])
        row = {"field": path, "label": spec["label"], "current": _expand(now, ctx), "draft": _expand(new, ctx)}
        if chan == "inapp":
            row["draftNonFinance"] = mask(row["draft"])          # 沒有財務權限的收件人實際看到的樣子
        rows.append(row)
    return {"user": caller.get("username"), "role": caller.get("role"), "event": key, "label": ev["label"], "rows": rows,
            "warnings": ["站內訊息會依收件人權限遮蔽金額；信件沒有金額占位符。", "信件主旨前綴與分類固定，範本只改事由。"]}
