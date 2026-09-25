# -*- coding: utf-8 -*-
"""L1 個資蒐集告知（R3；規格 CUSTOMIZATION-SPEC §7.3；個人資料保護法 §8 I）。

- 告知文字：`company_profile.privacy_notice`；空白 ⇒ 範本（公司名稱代入）。
- 已告知紀錄：伺服器蓋時間、人員與告知文字雜湊；**已記錄的不可覆蓋或清除**（`merge_ack`）。
  勞報單存在自己的 data_json；承攬商（contractors 表沒有 JSON 欄位，不改 schema）存在
  設定鍵 `privacy_notice_acks`（`"contractor:<id>"` → 紀錄）。
"""
import hashlib
import json
from datetime import datetime

from core.txn import write_txn
from db import get_db

ACKS_KEY = "privacy_notice_acks"
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


# ── 承攬商的紀錄（設定鍵） ─────────────────────────────────────────────────────

def get_ack(kind: str, key) -> dict:
    from helpers.settings import _get_setting
    acks = _get_setting(ACKS_KEY, {}) or {}
    return acks.get(f"{kind}:{key}") if isinstance(acks, dict) else None


def record_ack(kind: str, key, user: dict) -> tuple:
    """寫入一筆「已告知」；已經有就不動。回傳 (紀錄, 是否新寫入)。"""
    k = f"{kind}:{key}"
    text = current_notice()
    conn = get_db()
    with write_txn(conn):
        row = conn.execute("SELECT value_json FROM system_settings WHERE key=?", (ACKS_KEY,)).fetchone()
        try:
            acks = json.loads(row["value_json"]) if row else {}
        except ValueError:
            acks = {}
        if not isinstance(acks, dict):
            acks = {}
        if isinstance(acks.get(k), dict) and acks[k].get("at"):
            conn.rollback()
            conn.close()
            return acks[k], False
        acks[k] = ack_record(user, text)
        conn.execute(
            "INSERT INTO system_settings (key, value_json, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
            (ACKS_KEY, json.dumps(acks, ensure_ascii=False), datetime.now().isoformat()))
        conn.commit()
    conn.close()
    return acks[k], True
