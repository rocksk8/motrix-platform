# -*- coding: utf-8 -*-
"""本公司資料設定閘門：「這個安裝的本公司資料有沒有人確認過」（docs/platform/COMPANY-SETUP-GATE.md §3、§4.3、§6）。

[單位] helper:company_setup    [層] L1    [穩定度] 契約（改介面照 PLAYBOOK §C-7 升版）
[公開介面] ALERT_DAY_SETTING, BACKFILL_DONE_SETTING, BACKFILL_WAITING_SETTING, CONFIGURED, CONFIRMATION_SETTING, ConfirmRefused, DELIVERY_PUBKEY_PEM,
    DEVELOPER_IDENTITY_FP, DEVELOPER_UNSIGNED, FIELDS_CHANGED, FIELDS_INVALID, GRACE_MAX_HOURS, GRACE_SEEN_SETTING,
    FILES_OVERRIDE, INSTALL_MISMATCH, NO_RECORD, PUBKEYS, PURPOSE, SIGNED_EXPIRED, SIGN_PREFIX, STATUS_ERROR, alert, allows,
    backfill_once, confirm, ensure_install_id, fields_hash, grace_state, identity_fp, install_hash,
    is_developer_identity, observe, required_problems, sign_confirmation, signed_file_state, startup_install_check,
    status, ubn_valid,
    CODE_REQUIRED, CODE_UNDETERMINED, GATE_GRACE, GATE_OK, GATE_REQUIRED, GATE_UNDETERMINED, HEADER, MSG_REQUIRED,
    MSG_UNDETERMINED, SETTINGS_URL, compile_allowed, gate, is_allowed, reset_cache,
    CompanySetupRequired, DEMO_INSTALL, DEMO_PROFILE, DEMO_WATERMARK, ERROR_CACHE_SECONDS, GRACE_EXPIRY_WARN_HOURS,
    SIGNED_EXPIRY_WARN_DAYS, observe_expiry, require, seed_demo, RESERVED_DEMO_UBN, payment_bank_missing, verified_doc
[不變式] status() 是純判斷（不寫庫、不寫檔）；只有 confirm()（設定頁「確認本公司資料」）與 backfill_once()（每庫一次）會寫確認紀錄；
    綁定＝安裝識別檔（不看硬體，主持裁示 CG-M1）；開發者身分需要開發者簽章確認檔；backfill_once／observe／ensure_install_id 不丟例外
[契約題] tests/test_company_setup_core_2026_09_28.py、tests/test_company_setup_cli_2026_09_28.py、
    tests/test_company_setup_gate_2026_09_28.py、tests/test_company_setup_output_gate_2026_09_28.py

威脅模型（§3.3，CG-S4）：防「沿用預設」與「疏忽」，不防會改程式碼或整包複製安裝目錄的客戶——這不是授權／防盜機制。
開發者指紋只存加鹽雜湊（DEVELOPER_IDENTITY_FP）：目的是不多一處字面值；統編 8 碼可暴力還原，而它本來就是公開登記資料。
"""
import base64
import hashlib
import json
import logging
import os
import re
import secrets
from datetime import datetime, timedelta

from core import paths as _paths

logger = logging.getLogger(__name__)

PURPOSE = "motrix-company-confirm-v1"
#: 簽章原文前綴（CG-S3 網域分隔：與交付包共用 Ed25519 金鑰，驗證端只認這個前綴＋purpose）
SIGN_PREFIX = b"motrix-company-confirm-v1\n"
#: 交付簽章公鑰（與 backend/tools/delivery.py 的 DELIVERY_PUBKEY_PEM 相同；題目比對兩者一致）
DELIVERY_PUBKEY_PEM = (
    b"-----BEGIN PUBLIC KEY-----\n"
    b"MCowBQYDK2VwAyEAmq8vwzNR4dJwhycE4bPdw/ecx4tpspqXPAKWO81QUho=\n"
    b"-----END PUBLIC KEY-----\n"
)
#: 驗簽章檔時試的公鑰（測試換掉這個名字；呼叫時才讀）
PUBKEYS = (DELIVERY_PUBKEY_PEM,)

#: 開發者公司指紋：sha256("motrix-devco-v1|<種類>|<正規化值>")。只放雜湊，字面值不寫進這裡（§3.3）。
DEVELOPER_IDENTITY_FP = frozenset({
    "fb56ec318ef55e75ec2599bcfc66589368fbac31f457bac596a7b39353146205",   # tax
    "f7f5636ac965a4fd060ff2464d36578611608427f30b10003548c644eade1d57",   # name
})
_FP_SALT = "motrix-devco-v1"
_NAME_SUFFIXES = ("股份有限公司", "有限公司", "企業社", "工作室")

CONFIRMATION_SETTING = "company_identity_confirmation"
GRACE_SEEN_SETTING = "company_setup_grace_seen"
BACKFILL_DONE_SETTING = "company_setup_backfill_done"
#: backfill 在等開發者簽章檔（CGI2-M1）：記下「當時是開發者身分」，重試時身分已改 ⇒ 不自動確認
BACKFILL_WAITING_SETTING = "company_setup_backfill_waiting"
ALERT_DAY_SETTING = "company_setup_alerted"

GRACE_MAX_HOURS = 72
_FUTURE_TOLERANCE = timedelta(minutes=5)

# reason 代碼（§3.2）
NO_RECORD = "no_record"
INSTALL_MISMATCH = "install_mismatch"
FIELDS_CHANGED = "fields_changed"
FIELDS_INVALID = "fields_invalid"
DEVELOPER_UNSIGNED = "developer_identity_unsigned"
SIGNED_EXPIRED = "signed_file_expired"
STATUS_ERROR = "status_error"
CONFIGURED = "configured"


# ── 路徑（可指定安裝根目錄：CLI 預檢讀的是另一個目錄） ─────────────────────────

#: 執行中這一份安裝的三個檔改放別處（只給測試：xdist 每個 worker 各一份，不碰 repo 的 backend/）。None＝core.paths。
FILES_OVERRIDE = None


def _files(root=None):
    """(識別檔, 簽章檔, 放行檔)。root＝安裝根目錄；None ⇒ 執行中的這一份。"""
    if root is None:
        if FILES_OVERRIDE:
            return tuple(FILES_OVERRIDE)
        return _paths.INSTALL_IDENTITY_FILE, _paths.COMPANY_CONFIRMATION_FILE, _paths.COMPANY_SETUP_GRACE_FILE
    b = os.path.join(root, "backend")
    return (os.path.join(b, os.path.basename(_paths.INSTALL_IDENTITY_FILE)),
            os.path.join(b, os.path.basename(_paths.COMPANY_CONFIRMATION_FILE)),
            os.path.join(b, os.path.basename(_paths.COMPANY_SETUP_GRACE_FILE)))


def _read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None


# ── 欄位 ─────────────────────────────────────────────────────────────────────

def ubn_valid(tax_id) -> bool:
    """統一編號檢查碼（財政部 2023 起：加權和可被 5 整除；第 7 碼為 7 時另試 +1）。"""
    s = str(tax_id or "")
    if not re.fullmatch(r"\d{8}", s):
        return False
    weights = (1, 2, 1, 2, 1, 2, 4, 1)
    total = 0
    for d, w in zip(s, weights):
        p = int(d) * w
        total += p // 10 + p % 10
    if total % 5 == 0:
        return True
    return s[6] == "7" and (total + 1) % 5 == 0


def _norm_tax(v):
    return re.sub(r"\D", "", str(v or ""))


def _norm_name(v):
    s = re.sub(r"\s+", "", str(v or ""))
    for suffix in _NAME_SUFFIXES:
        if s.endswith(suffix):
            return s[: -len(suffix)]
    return s


def identity_fp(kind: str, value) -> str:
    v = _norm_tax(value) if kind == "tax" else _norm_name(value)
    return hashlib.sha256(("%s|%s|%s" % (_FP_SALT, kind, v)).encode("utf-8")).hexdigest()


def _identity(profile):
    from helpers.company_identity import identity_from_profile
    return identity_from_profile(profile or {})


#: demo 示範公司的統編（D E4S3-S2）：它**會**通過檢查碼 ⇒ 非 demo 庫一律拒收，否則一串 0 就能跳過「必要欄位」
RESERVED_DEMO_UBN = "00000000"


def required_problems(profile, demo=False) -> list:
    """必要欄位（Q6 裁示）：名稱＋統編（檢查碼；非 demo 庫不收保留值 00000000）＋電話或 email 擇一。回缺漏清單（空＝合格）。"""
    ident = _identity(profile)
    out = []
    if not ident.get("company_name"):
        out.append("公司名稱")
    tax = _norm_tax(ident.get("tax_id"))
    if not demo and tax == RESERVED_DEMO_UBN:
        out.append("統一編號（%s 是系統保留的示範統編）" % RESERVED_DEMO_UBN)
    elif not ubn_valid(tax):
        out.append("統一編號（8 碼且通過檢查碼）")
    if not (ident.get("phone") or ident.get("email")):
        out.append("電話或 email（至少一項）")
    return out


def fields_hash(profile) -> str:
    ident = _identity(profile)
    body = {"name": _norm_name(ident.get("company_name")), "tax": _norm_tax(ident.get("tax_id")),
            "phone": str(ident.get("phone") or "").strip(), "email": str(ident.get("email") or "").strip().lower()}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def is_developer_identity(profile) -> bool:
    ident = _identity(profile)
    fps = set()
    if _norm_tax(ident.get("tax_id")):
        fps.add(identity_fp("tax", ident.get("tax_id")))
    if _norm_name(ident.get("company_name")):
        fps.add(identity_fp("name", ident.get("company_name")))
    return bool(fps & DEVELOPER_IDENTITY_FP)


# ── 安裝識別 ─────────────────────────────────────────────────────────────────

def _read_install_id(root=None):
    raw = _read_text(_files(root)[0])
    if raw is None:
        return None
    try:
        v = json.loads(raw).get("id")
    except (ValueError, AttributeError):
        return None
    return v if isinstance(v, str) and len(v) >= 32 else None


def install_hash(root=None):
    iid = _read_install_id(root)
    return hashlib.sha256(("motrix-install-v1|" + iid).encode("utf-8")).hexdigest() if iid else None


def ensure_install_id(root=None) -> tuple:
    """沒有就建（冪等）。回 (是否剛建, 安裝識別雜湊)；寫不進去 ⇒ (False, None)＋ERROR，不丟例外。"""
    try:
        h = install_hash(root)
        if h:
            return False, h
        path = _files(root)[0]
        body = {"id": secrets.token_hex(32), "created": datetime.now().isoformat(timespec="seconds")}
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(body, f)
        os.replace(tmp, path)
        return True, install_hash(root)
    except Exception:  # noqa: BLE001
        logger.exception("company_setup: 安裝識別檔建立失敗")
        return False, None


# ── 設定讀寫（指定連線） ─────────────────────────────────────────────────────

def _get(conn, key, default=None):
    row = conn.execute("SELECT value_json FROM system_settings WHERE key=?", (key,)).fetchone()
    if not row:
        return default
    return json.loads(row[0])


def _set(conn, key, value):
    conn.execute(
        "INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
        (key, json.dumps(value, ensure_ascii=False), datetime.now().isoformat()))


# ── 簽章確認檔 ────────────────────────────────────────────────────────────────

def _canonical(payload):
    return json.dumps({k: v for k, v in payload.items() if k != "sig"},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign_confirmation(payload: dict, private_pem: bytes) -> str:
    """開發者工具用：簽一份確認檔（回檔案內容字串）。產品執行時不會呼叫。"""
    from cryptography.hazmat.primitives import serialization
    key = serialization.load_pem_private_key(private_pem, password=None)
    body = dict(payload)
    body["purpose"] = PURPOSE   # 不寫成 dict(..., purpose=…)：case_summary 用途守門會把關鍵字參數誤認成用途
    sig = key.sign(SIGN_PREFIX + _canonical(body))
    return json.dumps(dict(body, sig=base64.b64encode(sig).decode("ascii")), ensure_ascii=False, indent=1)


def verified_doc(raw):
    """確認檔內容 ⇒ 簽章與用途都驗過的 dict；任何一項不對 ⇒ None。"""
    try:
        doc = json.loads(raw)
        sig = base64.b64decode(doc["sig"].encode("ascii"), validate=True)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(doc, dict) or doc.get("purpose") != PURPOSE:
        return None
    from cryptography.hazmat.primitives import serialization
    for pem in PUBKEYS:
        try:
            serialization.load_pem_public_key(pem).verify(sig, SIGN_PREFIX + _canonical(doc))
            return doc
        except Exception:  # noqa: BLE001
            continue
    return None


def signed_file_state(profile, root=None, today=None) -> str:
    """'valid'／'missing'／'invalid'／'expired'／'mismatch'（簽的是另一個安裝識別或另一個身分）。"""
    raw = _read_text(_files(root)[1])
    if raw is None:
        return "missing"
    doc = verified_doc(raw)
    if doc is None:
        return "invalid"
    ident = _identity(profile)
    if doc.get("install") != install_hash(root) or doc.get("identity_fp") != identity_fp("tax", ident.get("tax_id")):
        return "mismatch"
    today = (today or datetime.now().date()).isoformat()
    if not (str(doc.get("issued", "")) <= today <= str(doc.get("expires", ""))):
        return "expired"
    return "valid"


# ── 暫時放行 ─────────────────────────────────────────────────────────────────

def grace_state(conn, root=None, now=None) -> dict:
    """放行檔 ⇒ {active, until, content_hash, reason}。有效期＝min(until, first_seen＋72h)（CG2-S4）；
    first_seen 取庫裡的紀錄，沒有就以「現在」計（observe() 才會寫）。"""
    now = now or datetime.now()
    raw = _read_text(_files(root)[2])
    if raw is None:
        return {"active": False, "reason": "missing"}
    content_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    try:
        doc = json.loads(raw)
        created = datetime.fromisoformat(doc["created"])
        until = datetime.fromisoformat(doc["until"])
    except Exception:  # noqa: BLE001
        return {"active": False, "reason": "invalid", "content_hash": content_hash}
    if doc.get("install") != install_hash(root):
        return {"active": False, "reason": "install_mismatch", "content_hash": content_hash}
    if created > now + _FUTURE_TOLERANCE:
        return {"active": False, "reason": "created_in_future", "content_hash": content_hash}
    seen = (_get(conn, GRACE_SEEN_SETTING, {}) or {}).get(content_hash)
    first_seen = datetime.fromisoformat(seen) if seen else now
    effective = min(until, first_seen + timedelta(hours=GRACE_MAX_HOURS), created + timedelta(hours=GRACE_MAX_HOURS))
    return {"active": now < effective, "until": effective.isoformat(timespec="seconds"),
            "reason": "active" if now < effective else "expired", "content_hash": content_hash,
            "first_seen": first_seen.isoformat(timespec="seconds"), "note": doc.get("reason", "")}


# ── 判定 ─────────────────────────────────────────────────────────────────────

def status(conn, root=None, now=None, demo=False) -> dict:
    """純判斷（不寫庫、不寫檔）。conn＝要判定的那個庫。丟例外由呼叫端處理（§3.6，Q7＝C）。
    demo＝True（demo 庫）：確認紀錄的安裝識別改比對 DEMO_INSTALL（demo 種子寫的常數；正式庫永遠比對安裝識別檔
    ⇒ demo 紀錄被帶進正式庫也是 install_mismatch）。"""
    now = now or datetime.now()
    profile = _get(conn, "company_profile", {}) or {}
    grace = grace_state(conn, root, now)
    out = {"configured": False, "reason": NO_RECORD, "via": None, "missing": required_problems(profile, demo=demo),
           "developer": is_developer_identity(profile), "grace": grace if grace.get("active") else None}
    rec = _get(conn, CONFIRMATION_SETTING)
    if out["missing"]:
        out["reason"] = FIELDS_INVALID
        return out
    if not isinstance(rec, dict) or not rec.get("install") or not rec.get("fields_hash"):
        return out
    ih = DEMO_INSTALL if demo else install_hash(root)
    if not ih or rec["install"] != ih:
        out["reason"] = INSTALL_MISMATCH
        return out
    if rec["fields_hash"] != fields_hash(profile):
        out["reason"] = FIELDS_CHANGED
        return out
    if out["developer"]:
        sf = signed_file_state(profile, root, now.date())
        if sf != "valid":
            out["reason"] = SIGNED_EXPIRED if sf == "expired" else DEVELOPER_UNSIGNED
            return out
    out.update(configured=True, reason=CONFIGURED, via=rec.get("via"))
    return out


def payment_bank_missing(profile) -> list:
    """請款單匯款三欄（主要據點解析後；分公司逐欄落空到主要據點）缺哪些（D E4S3-S1：預檢只報不擋）。"""
    from helpers.company_identity import PAYMENT_BANK_FIELDS
    ident = _identity(profile)
    return [label for field, label in PAYMENT_BANK_FIELDS if not str(ident.get(field) or "").strip()]


def allows(st: dict) -> bool:
    """中介層／輸出端：已設定，或放行中。"""
    return bool(st.get("configured") or st.get("grace"))


# ── 寫入：確認、backfill、觀察 ─────────────────────────────────────────────────

class ConfirmRefused(Exception):
    """確認被拒（原因給人看）。"""


def confirm(conn, username: str, root=None, via="settings_page") -> dict:
    """設定頁「確認本公司資料」（最高管理員）。呼叫端負責權限、交易、commit 與稽核。"""
    profile = _get(conn, "company_profile", {}) or {}
    missing = required_problems(profile)
    if missing:
        raise ConfirmRefused("必要欄位未完成：" + "、".join(missing))
    if is_developer_identity(profile) and signed_file_state(profile, root) != "valid":
        raise ConfirmRefused("這是 MOTRIX 開發者的公司資料，請改成貴公司的名稱與統一編號")
    created, ih = ensure_install_id(root)
    if not ih:
        raise ConfirmRefused("無法建立安裝識別檔（安裝目錄無法寫入），請聯絡系統負責人")
    rec = {"confirmed_by": username, "confirmed_at": datetime.now().isoformat(timespec="seconds"),
           "fields_hash": fields_hash(profile), "install": ih, "via": via}
    _set(conn, CONFIRMATION_SETTING, rec)
    return rec


def backfill_once(conn, root=None) -> str:
    """既有安裝升級時（每庫只跑一次，§6.1）：必要欄位合格且（非開發者身分，或有有效簽章檔）⇒ 補確認紀錄。
    回結果代碼；**不丟例外**（CG-S2）：出錯 ⇒ 不寫紀錄、記 ERROR，交給預檢與暫時放行。呼叫端負責 commit。"""
    try:
        if _get(conn, BACKFILL_DONE_SETTING):
            return "already_done"
        result = "had_record"
        if not isinstance(_get(conn, CONFIRMATION_SETTING), dict):
            profile = _get(conn, "company_profile", {}) or {}
            waiting = _get(conn, BACKFILL_WAITING_SETTING)
            if required_problems(profile):
                result = "skipped_fields"          # 欄位不合格（含全新安裝）：之後由最高管理員在設定頁按確認
            elif is_developer_identity(profile) and signed_file_state(profile, root) != "valid":
                result = "waiting_signature"       # 開發者資料、簽章檔未到：先用暫時放行升級的那條路
                if not waiting:
                    _set(conn, BACKFILL_WAITING_SETTING, {"at": datetime.now().isoformat(timespec="seconds")})
            elif waiting and not is_developer_identity(profile):
                # 🔴 CGI2-M1（D 稽核）：等簽章期間有人把名稱／統編改成別家、沒按確認 ⇒ **不可以**自動確認
                #    （那等於「複製來的開發者庫改個欄位就過關」）；記做過、交設定頁確認
                result = "skipped_identity_changed"
            else:
                _created, ih = ensure_install_id(root)
                if not ih:
                    return "error"                 # 識別檔寫不進去：不記做過，下次啟動再試
                _set(conn, CONFIRMATION_SETTING, {
                    "confirmed_by": "", "confirmed_at": datetime.now().isoformat(timespec="seconds"),
                    "fields_hash": fields_hash(profile), "install": ih, "via": "upgrade_backfill"})
                result = "backfilled"
        if result != "waiting_signature" and _get(conn, BACKFILL_WAITING_SETTING):
            conn.execute("DELETE FROM system_settings WHERE key=?", (BACKFILL_WAITING_SETTING,))
        # 🔴 CGI-M1（D 稽核）：waiting_signature **不記做過** ⇒ 簽章檔到位後下次啟動再試一次（否則 status 永遠停在
        #    no_record、只能一再重建放行）。skipped_fields **要記**：全新安裝（欄位空）之後由最高管理員填好欄位時，
        #    不可以被下一次啟動自動確認——「有人決定過」必須是設定頁的確認。
        if result != "waiting_signature":
            _set(conn, BACKFILL_DONE_SETTING, {"at": datetime.now().isoformat(timespec="seconds"), "result": result})
        return result
    except Exception:  # noqa: BLE001
        logger.exception("company_setup: backfill 失敗（不寫確認紀錄，交給預檢與暫時放行）")
        return "error"


def startup_install_check(conn, root=None) -> str:
    """啟動時：識別檔不在 ⇒ 建。庫裡已有確認紀錄 ⇒ 重建＝改掉綁定 ⇒ ERROR＋告警（CG2-M1）；新裝 ⇒ WARN。不丟例外。"""
    try:
        created, ih = ensure_install_id(root)
        if not created:
            return "present" if ih else "error"
        if isinstance(_get(conn, CONFIRMATION_SETTING), dict):
            msg = ("安裝識別檔遺失，已重建；本公司資料確認紀錄失效，請最高管理員重新確認"
                   "（開發者正式機：需新的簽章確認檔或暫時放行）")
            logger.error("company_setup: %s", msg)
            alert(conn, "install_id_recreated", msg)
            return "recreated_with_record"
        logger.warning("company_setup: 安裝識別檔不存在，已建立（首次啟動）")
        return "created"
    except Exception:  # noqa: BLE001
        logger.exception("company_setup: 啟動檢查失敗")
        return "error"


def observe(conn, root=None, now=None) -> None:
    """伺服器端：第一次看到某份放行檔 ⇒ 記 first_seen＋稽核＋告警（CG2-S4）。不丟例外；呼叫端負責 commit。"""
    try:
        g = grace_state(conn, root, now)
        h = g.get("content_hash")
        if not h:
            return
        seen = _get(conn, GRACE_SEEN_SETTING, {}) or {}
        if h in seen:
            return
        seen[h] = (now or datetime.now()).isoformat(timespec="seconds")
        _set(conn, GRACE_SEEN_SETTING, seen)
        _audit_system(conn, "company_setup.grace_seen", {"reason": g.get("reason"), "note": g.get("note", ""),
                                                           "until": g.get("until")})
        alert(conn, "grace_active", "本公司資料尚未確認，已啟用暫時放行（至 %s）：%s" % (g.get("until"), g.get("note", "")))
    except Exception:  # noqa: BLE001
        logger.exception("company_setup: observe 失敗")


#: 簽章確認檔到期前幾天開始每日告警（§6.5）；暫時放行到期前幾小時提醒（§4.3）
#   〔2026-09-29 主持：使用者授權的確認檔有效期是 30 天 ⇒ ~~30 天~~ 改 7 天，否則一簽就開始每日告警〕
SIGNED_EXPIRY_WARN_DAYS = 7
GRACE_EXPIRY_WARN_HOURS = 6


def observe_expiry(conn, root=None, now=None) -> None:
    """到期提醒（COMPANY-SETUP-GATE §4.3、§6.5）：簽章確認檔剩 ≤ 7 天、暫時放行剩 ≤ 6 小時 ⇒ 告警（同一代碼每日一次）。
    不丟例外；呼叫端負責 commit。"""
    now = now or datetime.now()
    try:
        g = grace_state(conn, root, now)
        if g.get("active") and g.get("until"):
            left = datetime.fromisoformat(g["until"]) - now
            if left <= timedelta(hours=GRACE_EXPIRY_WARN_HOURS):
                alert(conn, "grace_expiring", "本公司資料暫時放行將於 %s 到期，請最高管理員儘快確認本公司資料" % g["until"])
    except Exception:  # noqa: BLE001
        logger.exception("company_setup: 放行到期檢查失敗")
    try:
        profile = _get(conn, "company_profile", {}) or {}
        if is_developer_identity(profile) and signed_file_state(profile, root, now.date()) == "valid":
            doc = json.loads(_read_text(_files(root)[1]))
            expires = datetime.fromisoformat(str(doc["expires"])).date()
            if (expires - now.date()).days <= SIGNED_EXPIRY_WARN_DAYS:
                alert(conn, "signed_file_expiring",
                      "開發者簽章確認檔將於 %s 到期，請聯絡開發者換發（過期後輸出暫停，可用暫時放行撐到新檔到位）" % expires)
    except Exception:  # noqa: BLE001
        logger.exception("company_setup: 簽章檔到期檢查失敗")


def _audit_system(conn, action, detail):
    try:
        conn.execute("INSERT INTO audit_log (at, user_id, username, display_name, action, target_type, target_id,"
                     " target_label, detail) VALUES (?,?,?,?,?,?,?,?,?)",
                     (datetime.now().isoformat(), None, "system", "系統", action, "settings", "company_setup", "",
                      json.dumps(detail, ensure_ascii=False)))
    except Exception:  # noqa: BLE001
        logger.exception("company_setup: 稽核寫入失敗")


_ALERTED_IN_PROCESS = {}


def alert(conn, code: str, text: str) -> bool:
    """系統告警（同備份告警：邊緣觸發、同一代碼每日一次）：ERROR log＋系統稽核＋寄超級管理員。回是否這次有發。"""
    today = datetime.now().date().isoformat()
    if _ALERTED_IN_PROCESS.get(code) == today:           # CG5-S2：庫讀不到節流紀錄時，行程內這一層仍擋得住
        return False
    _ALERTED_IN_PROCESS[code] = today
    try:
        marks = _get(conn, ALERT_DAY_SETTING, {}) or {}
    except Exception:  # noqa: BLE001
        marks = {}
    if marks.get(code) == today:
        return False
    logger.error("company_setup 告警（%s）：%s", code, text)
    try:
        marks[code] = today
        _set(conn, ALERT_DAY_SETTING, marks)
    except Exception:  # noqa: BLE001
        logger.exception("company_setup: 告警節流寫入失敗")
    _audit_system(conn, "company_setup.alert", {"code": code, "text": text})
    try:
        from helpers import email_notify
        from helpers import mail_types as _mt
        to = email_notify._group_emails("company_setup_alert")
        if to:
            body = email_notify._build_html("company_setup_alert", "本公司資料設定狀態", code, "#B91C1C",
                                            [("狀況", text)], "", email_notify._base_url(), intro=text)
            email_notify._send_raising(to, _mt.subject("company_setup_alert", text[:60]), body)
    except Exception:  # noqa: BLE001
        logger.exception("company_setup: 告警信寄送失敗")
    return True


# ── 中介層（第一道，COMPANY-SETUP-GATE §4.1；Q7＝C）────────────────────────────
#
# 判定結果快取在行程內：鍵＝三個相關設定的 updated_at＋三個檔的 mtime（任一變 ⇒ 重算）。
GATE_OK = "ok"
GATE_GRACE = "grace"
GATE_REQUIRED = "required"
GATE_UNDETERMINED = "undetermined"
HEADER = "X-Motrix-Company-Setup"
CODE_REQUIRED = "company_setup_required"
CODE_UNDETERMINED = "company_setup_undetermined"
MSG_REQUIRED = "尚未完成本公司資料設定"
MSG_UNDETERMINED = "本公司設定狀態無法判定，對外文件暫停輸出，請聯絡管理員"
SETTINGS_URL = "/pages/company-profile-settings.html?setup=1"
_GATE_CACHE = {"key": None, "value": None}
#: 判定失敗的短時快取（CG5-S2）：{demo: 到期時間}
_GATE_ERROR_UNTIL = {}
ERROR_CACHE_SECONDS = 60


def _cache_key(conn, root=None):
    rows = conn.execute("SELECT key, updated_at FROM system_settings WHERE key IN (?,?,?)",
                        ("company_profile", CONFIRMATION_SETTING, GRACE_SEEN_SETTING)).fetchall()
    mt = []
    for p in _files(root):
        try:
            mt.append(os.path.getmtime(p))
        except OSError:
            mt.append(None)
    return (tuple(sorted((r[0], r[1]) for r in rows)), tuple(mt), datetime.now().strftime("%Y-%m-%d %H:%M"))


def _is_demo():
    try:
        from db import is_demo_mode
        return bool(is_demo_mode())
    except Exception:  # noqa: BLE001
        return False


def gate(conn, root=None, demo=None) -> tuple:
    """中介層與輸出端共用：回 (kind, status 或 None)。**不丟例外**：status() 出錯 ⇒ GATE_UNDETERMINED（Q7＝C）。
    放行檔第一次出現時記 first_seen＋稽核（observe）。呼叫端負責 commit。
    demo＝None ⇒ 看目前請求是不是 demo（db.is_demo_mode）；demo 與正式分開快取（兩個庫）。
    判定失敗 ⇒ 之後 ERROR_CACHE_SECONDS 秒內直接回 GATE_UNDETERMINED，不重算、不重發告警（CG5-S2）。"""
    demo = _is_demo() if demo is None else bool(demo)
    now = datetime.now()
    err_until = _GATE_ERROR_UNTIL.get(demo)
    if err_until and now < err_until:
        return GATE_UNDETERMINED, None
    try:
        key = (demo, _cache_key(conn, root))
        if _GATE_CACHE["key"] == key and _GATE_CACHE["value"] is not None:
            return _GATE_CACHE["value"]
        if not demo:
            observe(conn, root)
            observe_expiry(conn, root)
        st = status(conn, root, demo=demo)
        kind = GATE_OK if st.get("configured") else (GATE_GRACE if st.get("grace") else GATE_REQUIRED)
        _GATE_CACHE.update(key=(demo, _cache_key(conn, root)), value=(kind, st))
        _GATE_ERROR_UNTIL.pop(demo, None)
        return kind, st
    except Exception:  # noqa: BLE001
        logger.exception("company_setup: 判定失敗（Q7＝C：一般功能放行、含本公司資料的輸出拒絕）")
        _GATE_ERROR_UNTIL[demo] = now + timedelta(seconds=ERROR_CACHE_SECONDS)
        try:
            alert(conn, "status_error", MSG_UNDETERMINED)
        except Exception:  # noqa: BLE001
            pass
        _GATE_CACHE.update(key=None, value=None)
        return GATE_UNDETERMINED, None


def reset_cache():
    _GATE_CACHE.update(key=None, value=None)
    _GATE_ERROR_UNTIL.clear()


def compile_allowed(allowed: dict) -> list:
    """{(方法, 路由樣板): 理由} ⇒ [(方法, 正規式, 樣板)]；用 Starlette 自己的樣板編譯（與路由比對同一套規則）。"""
    from starlette.routing import compile_path
    out = []
    for (method, template), _why in allowed.items():
        regex, _fmt, _conv = compile_path(template)
        out.append((method.upper(), regex, template))
    return out


def is_allowed(compiled: list, method: str, path: str):
    """回命中的樣板或 None。HEAD 視同 GET（Starlette 路由亦然）。"""
    m = "GET" if method.upper() == "HEAD" else method.upper()
    for meth, regex, template in compiled:
        if meth == m and regex.match(path):
            return template
    return None


# ── 輸出端第二道（COMPANY-SETUP-GATE §5；D CG5-M1）─────────────────────────────
#
# 第一道（中介層）在「判定失敗」時放行（Q7＝C），所以**含本公司資料的輸出必須自己再問一次**：
# 判定失敗 ⇒ 428 company_setup_undetermined；未設定（例：非 HTTP 的排程信、demo）⇒ 428 company_setup_required。
# 繼承 HTTPException：沒改到的呼叫端至少是 428 而不是 200；main.py 另掛專屬 handler 回與中介層同形的 JSON。
# ⚠ 端點裡的 `except Exception` 會吞掉它 ⇒ 輸出端點一律先 `except HTTPException: raise`（守門掃描）。

from fastapi import HTTPException as _HTTPException  # noqa: E402


class CompanySetupRequired(_HTTPException):
    """輸出被第二道擋下。code＝CODE_REQUIRED／CODE_UNDETERMINED。"""

    def __init__(self, code: str, detail: str = None, missing=None):
        self.code = code
        self.missing = list(missing or [])
        super().__init__(status_code=428, detail=detail or (MSG_UNDETERMINED if code == CODE_UNDETERMINED else MSG_REQUIRED))


def require(conn=None, demo=None) -> str:
    """輸出前呼叫：已設定或放行中 ⇒ 回 gate kind；否則丟 CompanySetupRequired。conn 省略 ⇒ 自己開（依 demo 情境取庫）。"""
    own = conn is None
    if own:
        from db import get_db
        conn = get_db()
    try:
        kind, _st = gate(conn, demo=demo)
        if own:
            try:
                conn.commit()                       # observe() 可能寫了 first_seen
            except Exception:  # noqa: BLE001
                pass
    finally:
        if own:
            conn.close()
    if kind == GATE_UNDETERMINED:
        raise CompanySetupRequired(CODE_UNDETERMINED)
    if kind == GATE_REQUIRED:
        raise CompanySetupRequired(CODE_REQUIRED)
    return kind


# ── demo（Q3 裁示：虛構示範公司＋浮水印）─────────────────────────────────────────
#
# demo 庫每次登入重建（system_settings 清空）⇒ 重建後種一份虛構公司＋確認紀錄 via "demo_seed"。
# 確認紀錄的 install 是 DEMO_INSTALL 常數：status(demo=True) 才認；正式庫比對安裝識別檔 ⇒ 帶進正式庫也無效。
# 〔更正 §4.1「統編 00000000 不過檢查碼」：它的加權和是 0，**會通過**檢查碼。
#   「不可能被當成真公司」改由三件事保證：名稱含「示範資料」、只在 demo 庫有效的確認紀錄、demo 輸出浮水印〕
DEMO_INSTALL = hashlib.sha256(b"motrix-demo-install-v1").hexdigest()
DEMO_WATERMARK = "示範資料"
DEMO_PROFILE = {
    "name": "示範資料科技股份有限公司",
    "companyNameEn": "Demo Data Co., Ltd. (Sample)",
    "tax_id": "00000000",
    "contact_info": "Tel: 00-0000-0000｜demo@example.com",
}


def seed_demo(conn) -> dict:
    """demo 庫重建後呼叫（routers/auth.py demo 登入）。只准寫 demo 庫：呼叫端給的 conn 必須是 demo 庫。"""
    _set(conn, "company_profile", dict(DEMO_PROFILE))
    rec = {"confirmed_by": "demo", "confirmed_at": datetime.now().isoformat(timespec="seconds"),
           "fields_hash": fields_hash(DEMO_PROFILE), "install": DEMO_INSTALL, "via": "demo_seed"}
    _set(conn, CONFIRMATION_SETTING, rec)
    return rec
