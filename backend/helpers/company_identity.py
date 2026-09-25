# -*- coding: utf-8 -*-
"""§9 QL · 一份單據要印的「公司身分」。

🔴 **為什麼這一段不在 `pdf_gen.py` 裡**：
`pdf_gen.py` 不可以知道 `company_profile` 的地址結構
（`test_br2b_changing_the_address_shape_cannot_break_the_pdfs`）——
☠️ 把「地址資料長什麼樣」綁進 PDF 產生器之後，**改一次據點結構就會改到
所有單據**，而那種相依看不出來。
⇒ PDF 層問的是「**這份單的抬頭是什麼**」，不是「`company_profile` 裡有什麼鍵」。
"""
import json
from datetime import datetime

from db import get_db
from helpers.settings import _get_setting


# ══════════════════════════════════════════════════════════════════════════════
# §9 QL · 單據抬頭從「據點」取值
# ══════════════════════════════════════════════════════════════════════════════
#
# 使用者 2026-09-22：「在地址的部分可增加複數選項，由使用者新增名稱跟位置，
# 我們有分公司」⇒ 分公司開的單，抬頭與匯款帳號要是分公司自己的。
#
# 🔴 為什麼一次改 8 種，不是先改報價單：
#    這 8 種的抬頭是**同一個模式的 32 行複製**。只改一部分的話，
#    ☠️ **同一個案子的報價單與請款單會印不同抬頭** ——
#    🔑 而那種不一致沒有任何地方會報錯，它只會印在寄給客戶的紙上。
#
# 🔑 **落空的順序是逐欄，不是整筆**（QL5）：
#    這一筆據點的欄 → 主要據點的同一欄 → `company_profile` 的同一欄 → 內建預設
#    ☠️ 「整筆有值就整筆用」會讓一個只想改銀行帳號的分公司，抬頭變成空白。
#
# ⚠️ **全部留空時要與改版前逐字相同**（QL6）——`DEFAULT_IDENTITY` 就是那組值，
#    它不是「範例資料」，它是**既有安裝的行為**。動它等於改所有人的單據。

#: 什麼都沒填時印的那一組。
#:
#: 🔴 `WL7` §5⓪：改版前這裡是**我們自己的公司資料**（寫死在 32 行 PDF 產生碼
#: 裡的值，搬進常數時原封不動搬了過來）——四層解析鏈落到這裡代表**客戶
#: 什麼都沒填**，而印出我們的公司會讓客戶拿著一份抬頭是別家公司的單據
#: 給他的客戶。改成空字串：什麼都沒填就印空白，**客戶會發現，而他會去填**
#: （〈一個看得見的失敗，比一個看不見的成功好〉）。
#: ⚠️ 我們自己這台的既有資料由 `db.py` 的
#: `_m106_company_profile_identity_backfill` 遷移搬進 `company_profile`
#: 的第三層——解析鏈在那裡就接住了，不會落到這裡的空字串。
DEFAULT_IDENTITY = {
    "company_name": "",
    "company_name_en": "",
    "tax_id": "",
    "phone": "",
    "email": "",
    "bank_name": "",
    "bank_branch": "",
    "bank_account_name": "",
    "bank_account_number": "",
}

#: `company_profile` 頂層那幾個欄位的對照（既有安裝已經在用的鍵）。
_PROFILE_ALIASES = {
    "company_name": ("companyName", "company_name"),
    "company_name_en": ("companyNameEn", "company_name_en"),
    "tax_id": ("taxId", "tax_id"),
    "phone": ("phone",),
    "email": ("email",),
    "bank_name": ("bankName", "bank_name"),
    "bank_branch": ("bankBranch", "bank_branch"),
    "bank_account_name": ("bankAccountName", "bank_account_name"),
    "bank_account_number": ("bankAccountNumber", "bank_account_number"),
}


def _first_filled(*values):
    """第一個非空字串。**逐欄落空用的，不是「整筆有值就整筆用」**（QL5）。"""
    for value in values:
        text = str(value).strip() if value is not None else ""
        if text:
            return text
    return ""


def location_identity(location_id=None) -> dict:
    """一筆單據要印的公司身分。

    `location_id` 給 `None` ⇒ **主要據點**（`locations[0]`，QL8 明著要的行為）。
    找不到那個 id ⇒ 一樣落到主要據點 ——
    ⚠️ 不要丟例外：一張綁著已刪據點的舊單據**仍然要印得出來**，
    ☠️ 而印不出來的那一刻，使用者手上就只剩一張紙。
    """
    profile = _get_setting("company_profile", {}) or {}
    locations = profile.get("locations") or []
    primary = locations[0] if locations else {}
    here = primary
    if location_id:
        for item in locations:
            if str(item.get("id") or "") == str(location_id):
                here = item
                break

    out = {}
    for field, default in DEFAULT_IDENTITY.items():
        out[field] = _first_filled(
            here.get(field),
            primary.get(field),
            *[profile.get(alias) for alias in _PROFILE_ALIASES.get(field, ())],
            default)
    return out


def company_name() -> str:
    """報表／匯出抬頭用的公司名（主要據點；ROADMAP A8：取代 reports／accounting_export／
    network_plan_export 各自寫死的 `_COMPANY`）。全部留空 ⇒ `""`。"""
    return location_identity()["company_name"]


def company_heading(text: str, sep: str = " — ") -> str:
    """`<公司名><sep><text>`；公司名是空的 ⇒ 只回 `text`（不印出孤立的分隔符）。"""
    name = company_name()
    return f"{name}{sep}{text}" if name else text


#: 頁尾短名要去掉的尾綴。**只有這幾種，不做更聰明的猜測。**（2026-09-25 A8c 自 pdf_gen 移來，唯一來源）
NAME_SUFFIXES = ("股份有限公司", "有限公司", "企業社", "工作室")


def short_name(name: str) -> str:
    for suffix in NAME_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def contact_line(sep: str = " ｜ ", tax_label: str = "統一編號 ", phone_label: str = "Tel: ",
                 ident: dict = None) -> str:
    """統編／電話／email 串成一行（ROADMAP A8c：取代 reports／network_plan_export 寫死的聯絡資料）。
    空的欄位整段略過，不留孤立的分隔符；全部空白 ⇒ `""`。"""
    ident = ident if ident is not None else location_identity()
    parts = []
    if ident.get("tax_id"):
        parts.append(tax_label + ident["tax_id"])
    if ident.get("phone"):
        parts.append(phone_label + ident["phone"])
    if ident.get("email"):
        parts.append(ident["email"])
    return sep.join(parts)


def name_pair(ident: dict = None) -> str:
    """`英文名 短名`（空的略過）。"""
    ident = ident if ident is not None else location_identity()
    return " ".join(x for x in (ident.get("company_name_en", ""), short_name(ident.get("company_name", ""))) if x)


def footer_line(ident: dict = None) -> str:
    """頁尾完整版：`英文名 短名 ｜ email ｜ Tel: 電話 ｜ 統一編號: 統編`（全部有值時與 pdf_gen 單據頁尾同格式）；
    空的欄位整段略過，不留孤立的分隔符。"""
    ident = ident if ident is not None else location_identity()
    parts = [name_pair(ident), ident.get("email", ""),
             ("Tel: " + ident["phone"]) if ident.get("phone") else "",
             ("統一編號: " + ident["tax_id"]) if ident.get("tax_id") else ""]
    return " ｜ ".join(x for x in parts if x)


def _location_of(payload) -> str:
    """這份單據屬於哪一個據點。回 `""` ⇒ 主要據點。

    ```
    ① payload 自己的 `locationId`     報價單表單直接送、測試也直接塞
    ② 用 `quoteNo` 去查 quotations    出貨單／三種憑單／完工單／結案報告
    ```
    🔴 **②不可以省。** `generate_pdf_bytes()` 這一族只 `SELECT data_json,…`，
    而 `location_id` 是**欄位不是 `data_json` 的鍵** ⇒ 少了②的話，
    ☠️ 8 支 builder 拿到的永遠是空字串，**每一份真實單據都印總公司抬頭**，
    🔑 而題目會全綠（測試自己塞 `locationId`）—— 接縫有，呼叫者沒有。

    ⚠️ 查不到就回 `""`，**不要丟例外**：一張單據印不出來比印錯抬頭更糟，
    而這裡最壞的情況是退回既有行為（主要據點）。
    """
    payload = payload or {}
    direct = str(payload.get("locationId") or "").strip()
    if direct:
        return direct
    quote_no = str(payload.get("quoteNo") or payload.get("quote_no") or "").strip()
    if not quote_no:
        return ""
    try:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT location_id FROM quotations WHERE quote_no=?",
                (quote_no,)).fetchone()
        finally:
            conn.close()
    except Exception:       # noqa: BLE001 —— 查不到就退回主要據點
        return ""
    return str((row["location_id"] if row else "") or "").strip()


# ══════════════════════════════════════════════════════════════════════════════
# `QL25` · 報價單的據點身分要在「送出」那一刻凍結
# ══════════════════════════════════════════════════════════════════════════════
#
# 使用者逐字：「預設據點的部分，會強制帶到已經成立或是未成立的報價單，
# 應該以報價單成立當下的據點為主」。A 裁：① 凍結時機＝按「送出」那一刻
# （草稿階段仍跟著設定走）② 舊單等使用者填完設定後一次補 ③ 存內容不只 id
# ④ 沒有快照的舊單落回即時查。
#
# 🔴 這不牴觸 `QL10`（請款單等付款類單據讀即時值，回答的是「現在該匯到
# 哪」）——判準是「這份文件回答的是哪一個問題」：報價單回答的是「當初
# 報的是什麼」，與已交給員工的薪資單（`QL16`）同一類，凍結。
#
# ⚠️ 只凍結**抬頭五欄**，銀行四欄永遠即時值——`QL10` 沒有被翻掉，它管的
# 是不同的欄位（報價單版型本來就沒有銀行帳號欄位，只有請款單有）。

#: 會被快照覆蓋的欄位。**銀行四欄刻意不在裡面**（`QL10`：帳號要回答
#: 「現在該匯到哪」，不可以是凍結的舊值）。
_SNAPSHOT_FIELDS = ("company_name", "company_name_en", "tax_id", "phone", "email")

#: `data_json` 裡放快照的鍵。**不開新資料庫欄位**——`location_id` 已經是
#: 欄位（`QL2`），快照是「內容」，與薪資單（`QL16`）的做法一致，放
#: `data_json`。
SNAPSHOT_KEY = "locationIdentity"


def snapshot_for(location_id) -> dict:
    """送出那一刻要存進 `data_json["locationIdentity"]` 的內容。

    ⚠️ 只存抬頭五欄——**不要整包存 `location_identity()` 的回傳**（它含
    四個銀行欄位）：存了就會有人去讀，那正是 `QL10` 要避免的。
    `_locationId`／`_frozenAt` 只為稽核，**不拿來重查**（重查就違反了
    「凍結」的意思）。
    """
    ident = location_identity(location_id)
    out = {f: ident.get(f, "") for f in _SNAPSHOT_FIELDS}
    out["_locationId"] = str(location_id or "").strip()
    out["_frozenAt"] = datetime.now().isoformat()
    return out


def _resolve(payload):
    """`(據點 id, 快照 dict)`。**一次查詢**，兩條路分別處理。

    ```
    甲 payload 自己有 locationId   報價單表單直送、測試直塞 => 不查 DB
    乙 payload 只有 quoteNo        下游 7 支 builder => 查 quotations
    ```
    """
    payload = payload or {}
    direct = str(payload.get("locationId") or "").strip()
    if direct:
        return direct, (payload.get(SNAPSHOT_KEY) or {})
    quote_no = str(payload.get("quoteNo") or payload.get("quote_no") or "").strip()
    if not quote_no:
        return "", (payload.get(SNAPSHOT_KEY) or {})
    try:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT location_id, data_json FROM quotations WHERE quote_no=?",
                (quote_no,)).fetchone()
        finally:
            conn.close()
    except Exception:       # noqa: BLE001 —— 查不到就退回主要據點＋無快照
        return "", {}
    if not row:
        return "", {}
    try:
        d = json.loads(row["data_json"] or "{}")
    except (TypeError, ValueError):
        d = {}
    return (str(row["location_id"] or "").strip(), d.get(SNAPSHOT_KEY) or {})


def apply_snapshot(ident: dict, payload) -> dict:
    """把 `payload` 的快照（若有）逐欄覆蓋到**已經算好的** `ident` 上。

    🔴 這支**不呼叫 `location_identity()`**——即時值由呼叫端自己先算好
    傳進來，這裡只做「快照覆蓋」這一步。

    ## 為什麼要拆成兩步，不像 §3b① 原案直接包成一支 `identity_for()`

    `pdf_gen.py` 的 8 支 builder 目前是 `location_identity(_location_of(x))`
    這個**看得見的呼叫**——既有的 `identity` 測試接縫
    （`test_quote_location_2026_09_22.py` 的 `identity` fixture）monkeypatch
    的正是 `pdf_gen.location_identity` 這個名字，用來驗「8 支 builder 有
    沒有真的去取值」。若把整段包進 `company_identity.py` 的一支函式，
    這支函式呼叫的 `location_identity` 是**它自己模組裡的原始名字**，
    monkeypatch 到 `pdf_gen.location_identity` 的假值完全攔不到——
    那道既有守門會變成一個誤報的假警報（它會說『8 支 builder 沒有真的去
    取值』，而它們其實有，只是繞過了測試盯著的那個名字）。
    ⇒ `pdf_gen.py` 的呼叫端仍然寫兩行：`location_identity(_location_of(x))`
    接 `apply_snapshot(_ident, x)`，即時值那一步留在**呼叫端自己的
    命名空間**裡可以被監控，快照覆蓋是**額外疊加**的第二步。
    `identity_for()`（下面）保留給 `pdf_gen.py` 以外、不受那道監控約束
    的呼叫端使用——兩支底層邏輯相同（都是 `apply_snapshot` 的疊法），
    不是兩條规则。

    ⚠️ **逐欄覆蓋，不是整組**（同 `QL22`「退階要逐欄」）——快照裡某欄
    是空的，就落回即時值那一欄，不要讓一個空的快照欄位把即時值蓋成空白。
    """
    snap = _snapshot_of(payload)
    out = dict(ident)
    for f in _SNAPSHOT_FIELDS:
        v = str(snap.get(f) or "").strip()
        if v:
            out[f] = v
    return out


def _snapshot_of(payload):
    """`payload` 的快照 dict——只回快照本身，不查即時值。"""
    _loc_id, snap = _resolve(payload)
    return snap


def identity_for(payload) -> dict:
    """一份單據要印的公司身分——**即時值當底，抬頭五欄被快照逐欄覆蓋**。

    🔴 銀行四欄永遠是即時值（`QL10` 沒有被翻掉，它管的是別的欄位）。
    ⚠️ 給 `pdf_gen.py` 以外的呼叫端用；`pdf_gen.py` 自己的 8 支 builder
    用 `location_identity(_location_of(x))` + `apply_snapshot(...)` 兩步
    （理由見 `apply_snapshot()` 的 docstring）。
    """
    loc_id, _snap = _resolve(payload)
    return apply_snapshot(location_identity(loc_id), payload)
