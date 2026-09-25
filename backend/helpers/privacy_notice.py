# -*- coding: utf-8 -*-
"""L1 個資蒐集告知（R3；規格 CUSTOMIZATION-SPEC §9.3；個人資料保護法 §8 I）。

- 告知文字：`company_profile.privacy_notice`；空白 ⇒ 範本（公司名稱代入）。
- 已告知紀錄：伺服器蓋時間、人員與告知文字雜湊；**已記錄的不可覆蓋或清除**（`merge_ack`）。
  勞報單存在自己的 data_json；承攬商（contractors 表沒有 JSON 欄位，不改 schema）存在
  設定鍵 `privacy_notice_acks`（`"contractor:<id>"` → 紀錄）。
- 告知文字全文（稽核 S-5，2026-09-26）：紀錄只存 16 碼雜湊，公司改了告知文字就查不回當時告知的內容
  ⇒ 每次寫入新的已告知紀錄時，把那一版全文存進設定鍵 `privacy_notice_texts`（雜湊 → 全文），只增不改。
- 設定值讀不懂（稽核 S-3）：**拒絕寫入並記 ERROR**（`AcksCorrupted`），不可以當成空的再整份寫回——
  那會清掉其他人員的紀錄、連損毀的原始內容也蓋掉。
- 2026-09-26 擴大到其他蒐集自然人個資的表單（客戶／供應商聯絡人、承攬商、使用者帳號）：
  告知文字依用途（`PURPOSES`）分開，紀錄同樣存在 `privacy_notice_acks`
  （`customer_contact:<客戶id>:<聯絡人id>`、`supplier_contact:…`、`vendor_contractor:<id>`、`user:<id>`）。
  哪些表單蒐集個資 ⇒ 告知區塊的對應：`docs/platform/pii_forms.json`（守門 tests/platform/test_pii_forms_notice.py）。
"""
import hashlib
import json
import logging
import re
from datetime import datetime

from core.txn import write_txn
from db import get_db

ACKS_KEY = "privacy_notice_acks"
TEXTS_KEY = "privacy_notice_texts"

logger = logging.getLogger(__name__)
_HASH_RE = re.compile(r"^[0-9a-f]{16}$")


class AcksCorrupted(ValueError):
    """告知紀錄（或告知文字存檔）的設定值讀不懂 ⇒ 拒絕寫入；訊息可以直接給使用者。"""
COMPANY_PLACEHOLDER = "{公司名稱}"

#: 個資法 §8 I 應告知事項：①機關名稱 ②蒐集目的 ③個資類別 ④利用期間、地區、對象、方式
#: ⑤§3 當事人權利與行使方式 ⑥不提供對權益的影響。【】內由公司依實際情況填寫。
TEMPLATE = """個人資料蒐集告知事項（依個人資料保護法第 8 條第 1 項）

{公司名稱}（以下簡稱本公司）因與您成立承攬或勞務關係並給付報酬，蒐集您的個人資料，依法告知下列事項：

一、蒐集者名稱：{公司名稱}。

二、蒐集目的：履行承攬（勞務）契約、給付報酬、辦理所得稅扣繳與扣繳憑單申報、全民健康保險補充保險費扣繳與申報，以及會計帳務處理。

三、個人資料類別：姓名、身分證統一編號（或居留證、護照號碼）、國籍、聯絡電話、電子郵件、通訊地址、金融機構帳戶資料、身分證件與存摺影本、報酬金額與扣繳資料。

四、利用期間、地區、對象及方式：
（一）期間：自蒐集之日起，至契約關係消滅且法令規定的保存期間屆滿為止（例如扣繳與會計憑證的法定保存年限）。
（二）地區：中華民國境內，以及本公司資料備份所在地【請填寫】。
（三）對象：本公司、稅捐稽徵機關、衛生福利部中央健康保險署、受託辦理付款的金融機構，及其他依法令得要求提供的機關。
（四）方式：以書面或電子方式蒐集、處理及利用，包括列印、申報、付款與備份。

五、您的權利：依個人資料保護法第 3 條，您可以向本公司請求查詢或閱覽、製給複製本、補充或更正、停止蒐集處理或利用、刪除您的個人資料；但本公司依法令必須保存的資料（例如扣繳申報資料）不在此限。聯絡窗口與方式：【請填寫】。

六、不提供的影響：您可以自由選擇是否提供；不提供或提供不完整時，本公司將無法給付報酬、辦理所得扣繳及補充保險費申報，可能無法與您成立或履行契約。
"""


#: 客戶／供應商／承攬商（廠商）聯絡人：業務往來聯繫用（2026-09-26 擴大到其他表單）。
CONTACT_TEMPLATE = """個人資料蒐集告知事項（依個人資料保護法第 8 條第 1 項）

{公司名稱}（以下簡稱本公司）因與您或您所屬的公司有業務往來（報價、訂購、交貨、施工、請款與售後服務），蒐集您的個人資料，依法告知下列事項：

一、蒐集者名稱：{公司名稱}。

二、蒐集目的：客戶、供應商與協力廠商管理，業務聯繫，報價、訂單、交貨、施工與售後服務，以及帳務處理。

三、個人資料類別：姓名、職稱、所屬公司、聯絡電話、電子郵件、通訊軟體帳號、聯絡地址。

四、利用期間、地區、對象及方式：
（一）期間：自蒐集之日起，至業務往來結束且法令規定的保存期間屆滿為止。
（二）地區：中華民國境內，以及本公司資料備份所在地【請填寫】。
（三）對象：本公司，以及為履行業務而須提供的協力廠商、物流業者與依法令得要求提供的機關。
（四）方式：以書面或電子方式蒐集、處理及利用，包括聯繫、寄送單據、列印與備份。

五、您的權利：依個人資料保護法第 3 條，您可以向本公司請求查詢或閱覽、製給複製本、補充或更正、停止蒐集處理或利用、刪除您的個人資料；但本公司依法令必須保存的資料不在此限。聯絡窗口與方式：【請填寫】。

六、不提供的影響：您可以自由選擇是否提供；不提供或提供不完整時，本公司可能無法與您聯繫或提供報價、交貨與服務。
"""

#: 使用者帳號（員工）：系統帳號與內部管理用。
USER_TEMPLATE = """個人資料蒐集告知事項（依個人資料保護法第 8 條第 1 項）

{公司名稱}（以下簡稱本公司）因為您開設與管理本系統使用者帳號，蒐集您的個人資料，依法告知下列事項：

一、蒐集者名稱：{公司名稱}。

二、蒐集目的：系統帳號管理與身分驗證、內部通知與聯繫、工作指派與簽核、資訊安全與稽核紀錄。

三、個人資料類別：姓名、帳號、所屬部門、職務權限、電子郵件、聯絡電話，以及使用本系統產生的操作與登入紀錄。

四、利用期間、地區、對象及方式：
（一）期間：自帳號開設之日起，至帳號停用且內部稽核紀錄保存期間屆滿為止。
（二）地區：中華民國境內，以及本公司資料備份所在地【請填寫】。
（三）對象：本公司，及依法令得要求提供的機關。
（四）方式：以電子方式蒐集、處理及利用，包括寄送系統通知、登入驗證、稽核紀錄與備份。

五、您的權利：依個人資料保護法第 3 條，您可以向本公司請求查詢或閱覽、製給複製本、補充或更正、停止蒐集處理或利用、刪除您的個人資料；但本公司依法令或資訊安全稽核必須保存的紀錄不在此限。聯絡窗口與方式：【請填寫】。

六、不提供的影響：您可以自由選擇是否提供；不提供或提供不完整時，本公司將無法為您開設帳號或寄送系統通知。
"""

#: 告知的用途 ⇒ (範本, `company_profile` 裡公司自訂文字的鍵)。`contractor` 就是 R3 原本那一份。
PURPOSES = {
    "contractor": (TEMPLATE, "privacy_notice"),
    "contact": (CONTACT_TEMPLATE, "privacy_notice_contact"),
    "user": (USER_TEMPLATE, "privacy_notice_user"),
}


def template_for(company_name: str) -> str:
    return TEMPLATE.replace(COMPANY_PLACEHOLDER, (company_name or "").strip() or "本公司")


def notice_text(profile: dict) -> str:
    """公司自訂的告知文字；空白 ⇒ 範本。"""
    profile = profile or {}
    custom = str(profile.get("privacy_notice") or "").strip()
    return custom if custom else template_for(profile.get("name", ""))


def current_notice() -> str:
    from helpers.settings import _get_setting
    return notice_text(_get_setting("company_profile", {}) or {})


def purpose_template_for(purpose: str, company_name: str) -> str:
    """某一種用途的範本（公司名稱代入）。不認得的用途 ⇒ KeyError（不猜）。"""
    tmpl = PURPOSES[purpose][0]
    return tmpl.replace(COMPANY_PLACEHOLDER, (company_name or "").strip() or "本公司")


def purpose_notice_text(profile: dict, purpose: str) -> str:
    """某一種用途的告知文字：公司自訂的；空白 ⇒ 該用途的範本。"""
    profile = profile or {}
    key = PURPOSES[purpose][1]
    custom = str(profile.get(key) or "").strip()
    return custom if custom else purpose_template_for(purpose, profile.get("name", ""))


def current_purpose_notice(purpose: str) -> str:
    from helpers.settings import _get_setting
    return purpose_notice_text(_get_setting("company_profile", {}) or {}, purpose)


def notice_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def ack_record(user: dict, text: str, now: str = None) -> dict:
    return {
        "at": now or datetime.now().isoformat(timespec="seconds"),
        "by": user.get("display_name") or user.get("username", ""),
        "byUsername": user.get("username", ""),
        "noticeHash": notice_hash(text),
    }


def merge_ack(existing, requested: bool, user: dict, text: str):
    """已有紀錄 ⇒ 原封不動（不可覆蓋、不可清除）；沒有且這次勾選 ⇒ 新紀錄；否則 None。"""
    if isinstance(existing, dict) and existing.get("at"):
        return existing
    if requested:
        return ack_record(user, text)
    return None


# ── 設定值的讀取：讀不懂就拒絕（不當成空的） ─────────────────────────────────────

def _load_dict(conn, key: str) -> dict:
    """設定鍵的 dict。沒有這一列 ⇒ {}；有但讀不懂或不是 dict ⇒ AcksCorrupted（記 ERROR，原值不動）。"""
    row = conn.execute("SELECT value_json FROM system_settings WHERE key=?", (key,)).fetchone()
    if row is None or row[0] is None:
        return {}
    try:
        val = json.loads(row[0])
    except ValueError:
        val = None
    if not isinstance(val, dict):
        logger.error("個資告知設定值損毀，已拒絕寫入以免覆蓋：key=%s 前 80 字=%r", key, str(row[0])[:80])
        raise AcksCorrupted("個資告知紀錄的設定值（%s）損毀，系統已拒絕寫入以免覆蓋既有紀錄；"
                            "請聯絡系統管理者修復後再試" % key)
    return val


# ── 告知文字全文（雜湊 → 全文；只增不改） ───────────────────────────────────────

def archive_text(conn, text: str) -> str:
    """把這一版告知文字存進 `privacy_notice_texts`（已有同雜湊就不動）。回傳雜湊。
    🔴 呼叫端必須已經在這條連線上拿到寫鎖（begin_write／write_txn，或同一交易裡已寫過別的表），
    本函式不 commit（跟著呼叫端的交易一起提交或回滾）。"""
    h = notice_hash(text)
    texts = _load_dict(conn, TEXTS_KEY)
    if h not in texts:
        texts[h] = {"text": text or "", "firstAckAt": datetime.now().isoformat(timespec="seconds")}
        conn.execute(
            "INSERT INTO system_settings (key, value_json, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
            (TEXTS_KEY, json.dumps(texts, ensure_ascii=False), datetime.now().isoformat()))
    return h


def text_for_hash(h: str):
    """紀錄上的 noticeHash ⇒ 當時的告知全文（dict：text、firstAckAt）；查不到 ⇒ None。"""
    if not _HASH_RE.match(str(h or "")):
        return None
    conn = get_db()
    try:
        entry = _load_dict(conn, TEXTS_KEY).get(h)
    finally:
        conn.close()
    return entry if isinstance(entry, dict) else None


# ── 承攬商的紀錄（設定鍵） ─────────────────────────────────────────────────────

def get_ack(kind: str, key) -> dict:
    """讀不懂 ⇒ AcksCorrupted（不當成「沒有紀錄」：那會讓畫面顯示「尚未告知」而使用者重做一次）。"""
    conn = get_db()
    try:
        return _load_dict(conn, ACKS_KEY).get(f"{kind}:{key}")
    finally:
        conn.close()


def acks_with_prefix(kind: str, key_prefix) -> dict:
    """`<kind>:<key_prefix>:<子鍵>` 的所有紀錄 ⇒ {子鍵: 紀錄}（例：一家客戶底下每一位聯絡人）。
    讀不懂 ⇒ AcksCorrupted（同 get_ack：不當成「沒有紀錄」）。"""
    conn = get_db()
    try:
        acks = _load_dict(conn, ACKS_KEY)
    finally:
        conn.close()
    head = f"{kind}:{key_prefix}:"
    return {k[len(head):]: v for k, v in acks.items() if k.startswith(head) and isinstance(v, dict)}


def record_ack(kind: str, key, user: dict) -> tuple:
    """寫入一筆「已告知」；已經有就不動。回傳 (紀錄, 是否新寫入)。"""
    return _record(f"{kind}:{key}", current_notice(), user)


def record_purpose_ack(kind: str, key, user: dict, purpose: str) -> tuple:
    """同 `record_ack`，雜湊的是該用途（`PURPOSES`）當下的告知文字。"""
    return _record(f"{kind}:{key}", current_purpose_notice(purpose), user)


def _record(k: str, text: str, user: dict) -> tuple:
    conn = get_db()
    with write_txn(conn):
        acks = _load_dict(conn, ACKS_KEY)          # 讀不懂 ⇒ AcksCorrupted（write_txn 回滾並關連線）
        if isinstance(acks.get(k), dict) and acks[k].get("at"):
            conn.rollback()
            conn.close()
            return acks[k], False
        acks[k] = ack_record(user, text)
        archive_text(conn, text)
        conn.execute(
            "INSERT INTO system_settings (key, value_json, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
            (ACKS_KEY, json.dumps(acks, ensure_ascii=False), datetime.now().isoformat()))
        conn.commit()
    conn.close()
    return acks[k], True
