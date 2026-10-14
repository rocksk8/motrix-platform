# -*- coding: utf-8 -*-
"""附件插槽定義（BP-4 S2；kind `attachment_slot`，key＝`doc:<單據類型>`；設計 BP4-STORAGE-NOTIFY-DESIGN §3）。

[單位] helper:attachment_slots    [層] L1    [穩定度] 契約
[公開介面] KIND, SLOTTED_DOC_TYPES, catalog, compare, definition_problems, effective_slots, enabled, simulate, slot_policy
[不變式] ①旗標 `builder_slots.enabled` 關閉 ⇒ 沒有任何東西讀這份定義：`slot_policy` 只回內建政策、端點 404（定義文件庫本身仍可存草稿，
    但完全不起作用）。②插槽只能**縮小**：副檔名 ⊂ `storage_slots.HARD_EXTS`、單檔上限 ≤ 平台 `uploads.max_file_mb`、件數／合計有硬上限；
    位置代號由單據類型決定（`storage_slots.DOC_CODES`），不接受輸入。③子資料夾只在該位置代號的讀取提供者宣告 `SLOT_AWARE` 時才准用。
    ④插槽的 `uploaders` 只能收窄（實際權限＝端點既有守門 ∧ uploaders）；讀取授權仍是 `uploads.path_access` 提供者。
[契約題] backend/tests/test_attachment_slots_2026_10_14.py
"""
import os
import re
import unicodedata

from core import definitions as D
from helpers import storage_slots as SS
from helpers import uploads as U

KIND = "attachment_slot"
#: 可宣告插槽的單據類型 ⇒ 說明。程式登錄，新增一種＝開發加一行（並確認該位置代號的讀取提供者）。
SLOTTED_DOC_TYPES = {"completion_note": "完工單"}
BUILTIN_SLOT = "signed"                     # 內建預設插槽（= 今天的行為）；保留鍵，管理者不可重新定義
MAX_SLOTS = 10
MAX_FILES_CAP = 20
MAX_REQUEST_MB_CAP = 100
DEFAULT_MAX_FILES = 10
DEFAULT_MAX_REQUEST_MB = 50
_MAX_LABEL = 20
_KEYS = {"key", "label", "accept", "maxFileMb", "maxFiles", "maxRequestMb", "subfolder", "uploaders", "required", "disabled"}
_SLOT_KEY = re.compile(r"^[a-z][a-z0-9_]{0,23}$")
_SUBFOLDER = re.compile(r"^[A-Za-z0-9_\-一-鿿]{1,40}$")
_RESERVED = {"CON", "PRN", "AUX", "NUL", *("COM%d" % i for i in range(1, 10)), *("LPT%d" % i for i in range(1, 10))}
_BAD_LABEL = re.compile("[<>&\"'\\\\\\x00-\\x1f\\u200b-\\u200f\\u202a-\\u202e\\u2060-\\u2069\\ufeff]")      # 含控制字元、雙向控制與零寬字元
#: 插槽標籤不得出現的詞（附件種類不是金額欄位；也避免把成本／毛利等字樣放進任何人都看得到的上傳區）
_MONEY_WORDS = ("金額", "成本", "毛利", "利潤", "報價", "單價", "薪資", "獎金")


def enabled(conn=None) -> bool:
    """旗標（`builder_slots` 且 `builder_governance` 都開，見 `storage_slots.enabled`）。同時讓定義種類登記跟著旗標走（`_sync_kind`）。"""
    on = SS.enabled(conn)
    _sync_kind(on)
    return on


def _doc_type_of(key):
    m = re.match(r"^doc:([a-z][a-z0-9_]{0,39})$", key or "")
    return m.group(1) if m else None


def _roles():
    from helpers.mail_types import ROLES
    return tuple(ROLES)


def _provider_slot_aware(code) -> bool:
    """該位置代號的讀取提供者是否宣告 `SLOT_AWARE`（能處理多一層子資料夾的路徑）。沒有提供者 ⇒ False。"""
    from core import registry
    for _k, prov in registry.providers(U.PATH_ACCESS).items():
        if code in (getattr(prov, "FOLDERS", ()) or ()):
            return bool(getattr(prov, "SLOT_AWARE", False))
    return False


def _platform_file_mb() -> int:
    return max(1, U.max_file_bytes() // (1024 * 1024))


def _label_problem(label):
    if not isinstance(label, str) or not label.strip():
        return "插槽名稱不可以空白"
    if _BAD_LABEL.search(label):
        return "插槽名稱不可含 < > & 引號、反斜線或控制字元"
    if len(label.strip()) > _MAX_LABEL:
        return "插槽名稱最多 %d 字" % _MAX_LABEL
    if any(w in label for w in _MONEY_WORDS):
        return "插槽名稱不可使用金額相關字眼（%s）" % "、".join(_MONEY_WORDS)
    return None


def _subfolder_problem(sub, code):
    if not isinstance(sub, str):
        return "子資料夾必須是文字"
    s = unicodedata.normalize("NFC", sub)
    if s != sub:
        return "子資料夾請使用標準寫法（Unicode NFC）"
    if not _SUBFOLDER.match(s) or s.endswith((" ", ".")):
        return "子資料夾只能是 1～40 字的單層名稱（中英文、數字、底線、連字號）"
    if s.upper() in _RESERVED:
        return "子資料夾不可使用系統保留名稱"
    if not _provider_slot_aware(code):
        return "這個位置的讀取提供者還不支援子資料夾"
    return None


def definition_problems(key, body) -> list:
    """發布前驗證 ⇒ `[{path, message}]`（空＝通過）。kind 驗證器（`D.register_kind`）呼叫。"""
    doc = _doc_type_of(key)
    if doc is None or doc not in SLOTTED_DOC_TYPES:
        return [{"path": "", "message": "key 必須是 doc:<單據類型>，目前支援：%s" % "、".join(sorted(SLOTTED_DOC_TYPES))}]
    if not isinstance(body, dict):
        return [{"path": "", "message": "定義必須是物件"}]
    out = [{"path": k, "message": "不認得的鍵：%s" % k} for k in body if k != "slots"]
    slots = body.get("slots")
    if not isinstance(slots, list):
        return out + [{"path": "slots", "message": "slots 必須是清單"}]
    if len(slots) > MAX_SLOTS:
        out.append({"path": "slots", "message": "每種單據最多 %d 個附件種類" % MAX_SLOTS})
    code = SS.DOC_CODES[doc]
    seen_keys, seen_subs = set(), set()
    fmb = _platform_file_mb()
    for i, s in enumerate(slots):
        p = "slots[%d]" % i
        if not isinstance(s, dict):
            out.append({"path": p, "message": "附件種類必須是物件"})
            continue
        out += [{"path": "%s.%s" % (p, k), "message": "不認得的鍵：%s" % k} for k in s if k not in _KEYS]
        k = s.get("key")
        if not isinstance(k, str) or not _SLOT_KEY.match(k):
            out.append({"path": p + ".key", "message": "代號必須是小寫英文開頭、英數與底線（最多 24 字）"})
        elif k == BUILTIN_SLOT:
            out.append({"path": p + ".key", "message": "「%s」是內建附件種類，不能重新定義" % BUILTIN_SLOT})
        elif k in seen_keys:
            out.append({"path": p + ".key", "message": "代號重複：%s" % k})
        else:
            seen_keys.add(k)
        lp = _label_problem(s.get("label"))
        if lp:
            out.append({"path": p + ".label", "message": lp})
        acc = s.get("accept")
        if not isinstance(acc, list) or not acc or not all(isinstance(e, str) for e in acc):
            out.append({"path": p + ".accept", "message": "accept 必須是副檔名清單（至少一項）"})
        else:
            bad = sorted({e for e in acc if e not in SS.SLOT_EXTS})
            if bad:
                out.append({"path": p + ".accept", "message": "這些副檔名不在系統允許範圍：%s（只能從 %s 挑）" % ("、".join(bad), " ".join(sorted(SS.SLOT_EXTS)))})
            if len(set(acc)) != len(acc):
                out.append({"path": p + ".accept", "message": "副檔名重複"})
        for fld, lo, hi in (("maxFileMb", 1, fmb), ("maxFiles", 1, MAX_FILES_CAP), ("maxRequestMb", 1, MAX_REQUEST_MB_CAP)):
            v = s.get(fld)
            if v is not None and (isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi):
                out.append({"path": "%s.%s" % (p, fld), "message": "%s 必須是 %d～%d 的整數" % (fld, lo, hi)})
        sub = s.get("subfolder")
        if sub not in (None, ""):
            sp = _subfolder_problem(sub, code)
            if sp:
                out.append({"path": p + ".subfolder", "message": sp})
            elif sub.upper() in seen_subs:
                out.append({"path": p + ".subfolder", "message": "子資料夾重複（不分大小寫）：%s" % sub})
            else:
                seen_subs.add(sub.upper())
        up = s.get("uploaders")
        if up is not None:
            if not isinstance(up, dict) or set(up) - {"roles", "modules"}:
                out.append({"path": p + ".uploaders", "message": "uploaders 只能有 roles、modules"})
            else:
                rs, ms = up.get("roles", []), up.get("modules", [])
                if not isinstance(rs, list) or any(r not in _roles() for r in rs):
                    out.append({"path": p + ".uploaders.roles", "message": "角色必須是：%s" % "、".join(_roles())})
                if not isinstance(ms, list) or any(not isinstance(m, str) or not re.match(r"^[a-z][a-z0-9_]{0,39}$", m) for m in ms):
                    out.append({"path": p + ".uploaders.modules", "message": "模組必須是模組代號清單"})
        for fld in ("required", "disabled"):
            if fld in s and not isinstance(s[fld], bool):
                out.append({"path": "%s.%s" % (p, fld), "message": "%s 必須是 true／false" % fld})
    return out


def _kind_validator(body, key):
    return definition_problems(key, body)


def _sync_kind(on) -> None:
    """定義種類跟旗標走：開 ⇒ 登記（`/api/definition-kinds` 才會多出 `attachment_slot`）；關 ⇒ 撤掉，**旗標關閉時種類清單與先前逐位元相同**。
    登記發生在 `enabled()` 被呼叫時（本檔所有執行路徑與路由都會呼叫）；啟動時旗標若已開，import 當下會先登記一次（讀不到資料庫 ⇒ 當關，
    之後第一次進入本檔的路由時補登記——編輯器載入時會先打 catalog，早於任何草稿寫入）。"""
    if on and KIND not in D.kinds():
        D.register_kind(KIND, label="附件插槽", validator=_kind_validator)
    elif not on and KIND in D._EXTRA_KINDS:                          # noqa: SLF001  core.definitions 沒有 unregister；只動自己登記的這一種
        D._EXTRA_KINDS.pop(KIND, None)                               # noqa: SLF001
        D._VALIDATORS.pop(KIND, None)                                # noqa: SLF001


_sync_kind(SS.enabled())


# ── 寬嚴比較（`routers/def_pipeline.COMPARATORS` 使用）──────────────────────────────────
def _norm(s):
    s = s or {}
    up = s.get("uploaders") or {}
    return {"accept": set(s.get("accept") or []), "file": s.get("maxFileMb") or _platform_file_mb(),
            "files": s.get("maxFiles") or DEFAULT_MAX_FILES, "req": s.get("maxRequestMb") or DEFAULT_MAX_REQUEST_MB,
            "sub": s.get("subfolder") or "", "roles": set(up.get("roles") or []), "mods": set(up.get("modules") or []),
            "open": not (up.get("roles") or up.get("modules")), "disabled": bool(s.get("disabled"))}


def compare(old, new):
    """old_body → new_body ⇒ (`loosen`｜`tighten`｜`neutral`, reasons)。無法判斷 ⇒ 放寬。"""
    try:
        o = {s.get("key"): s for s in (old or {}).get("slots", []) if isinstance(s, dict)}
        n = {s.get("key"): s for s in (new or {}).get("slots", []) if isinstance(s, dict)}
    except AttributeError:
        return "loosen", ["無法解析，視為放寬"]
    base = SS.builtin_policy(SS.DOC_CODES[next(iter(SLOTTED_DOC_TYPES))])
    loosen, tighten = [], []
    for k, s in n.items():
        if k not in o:
            x = _norm(s)
            if x["disabled"]:
                continue
            if not x["accept"] <= set(base.accept):
                loosen.append("新增附件種類 %s，收今天沒有開放的檔案類型：%s" % (k, " ".join(sorted(x["accept"] - set(base.accept)))))
            elif x["sub"]:
                loosen.append("新增附件種類 %s，使用新的存放子資料夾" % k)
            continue
        a, b = _norm(o[k]), _norm(s)
        for what, cond in (("新增可上傳的檔案類型 " + " ".join(sorted(b["accept"] - a["accept"])), b["accept"] - a["accept"]),
                           ("單檔上限變大", b["file"] > a["file"]), ("件數上限變大", b["files"] > a["files"]),
                           ("合計上限變大", b["req"] > a["req"]), ("改了存放子資料夾", b["sub"] != a["sub"]),
                           ("重新啟用", a["disabled"] and not b["disabled"])):
            if cond:
                loosen.append("%s：%s" % (k, what))
        widened_up = (b["open"] and not a["open"]) or (not a["open"] and not b["open"] and (b["roles"] - a["roles"] or b["mods"] - a["mods"]))
        if widened_up:
            loosen.append("%s：擴大了可上傳的人" % k)
        if a["accept"] - b["accept"]:
            tighten.append("%s：移除檔案類型" % k)
        if b["file"] < a["file"] or b["files"] < a["files"] or b["req"] < a["req"]:
            tighten.append("%s：上限變小" % k)
        if (a["open"] and not b["open"]) or (not a["open"] and not b["open"] and (a["roles"] - b["roles"] or a["mods"] - b["mods"])):
            tighten.append("%s：縮小了可上傳的人" % k)
        if b["disabled"] and not a["disabled"]:
            tighten.append("%s：停用" % k)
        unknown = {x for x in set(o[k]) | set(s) if o[k].get(x) != s.get(x)} - {"label", "required", "key", "accept", "maxFileMb", "maxFiles",
                                                                                  "maxRequestMb", "subfolder", "uploaders", "disabled"}
        if unknown:
            loosen.append("%s：%s 變了（無法判斷寬嚴，視為放寬）" % (k, "、".join(sorted(unknown))))
    for k in o:
        if k not in n:
            tighten.append("移除附件種類 %s" % k)
    if loosen:
        return "loosen", loosen + tighten
    return ("tighten", tighten) if tighten else ("neutral", [])


# ── 執行期 ──────────────────────────────────────────────────────────────────────
def published_slots(conn, doc_type) -> list:
    """已發布定義裡的插槽（沒有 ⇒ []）。只在旗標開啟時有人呼叫。"""
    try:
        d = D.get(conn, KIND, "doc:%s" % doc_type, "company")
    except D.DefinitionError:
        return []
    return [s for s in ((d or {}).get("body") or {}).get("slots", []) if isinstance(s, dict)]


def _may_upload(conn, user, slot) -> bool:
    up = slot.get("uploaders") or {}
    rs, ms = up.get("roles") or [], up.get("modules") or []
    if not rs and not ms:
        return True
    if user.get("role") == "superadmin" or user.get("role") in rs:
        return True
    if ms:
        from helpers.auth import effective_modules
        have = set(effective_modules(user.get("role"), user.get("modules"), user_id=user.get("id"), conn=conn))
        return bool(have & set(ms))
    return False


def _policy_of(doc_type, slot) -> "SS.SlotPolicy":
    code = SS.DOC_CODES[doc_type]
    n = _norm(slot)
    return SS.SlotPolicy(code=code, folder=code, accept=frozenset(n["accept"]) & SS.SLOT_EXTS, max_files=int(n["files"]),
                         max_request_bytes=int(n["req"]) * 1024 * 1024, max_file_bytes=int(n["file"]) * 1024 * 1024,
                         subfolder=n["sub"], slot=slot.get("key") or "", builtin=False)


def effective_slots(conn, doc_type, user=None) -> list:
    """上傳區要顯示的附件種類（內建 `signed` 永遠在第一個）。旗標關閉 ⇒ 只有內建。`user` 給了就依 uploaders 過濾。"""
    b = SS.builtin_policy(SS.DOC_CODES[doc_type])
    out = [{"key": BUILTIN_SLOT, "label": "簽回單", "builtin": True, "accept": sorted(b.accept), "maxFiles": b.max_files or None,
            "maxFileMb": _platform_file_mb(), "required": False}]
    if not enabled(conn):
        return out
    for s in published_slots(conn, doc_type):
        if s.get("disabled") or (user is not None and not _may_upload(conn, user, s)):
            continue
        n = _norm(s)
        out.append({"key": s["key"], "label": s.get("label", s["key"]), "builtin": False, "accept": sorted(n["accept"]), "maxFiles": n["files"],
                    "maxFileMb": n["file"], "required": bool(s.get("required"))})
    return out


def slot_policy(conn, doc_type, slot_key, user):
    """⇒ 該插槽的 `SlotPolicy`。旗標關閉、內建鍵 ⇒ 內建政策；找不到／停用 ⇒ `LookupError`；使用者不在 uploaders ⇒ `PermissionError`。"""
    if slot_key in ("", BUILTIN_SLOT) or not enabled(conn):
        if slot_key not in ("", BUILTIN_SLOT):
            raise LookupError("附件種類未開放：%s" % slot_key)
        return SS.builtin_policy(SS.DOC_CODES[doc_type])
    s = next((x for x in published_slots(conn, doc_type) if x.get("key") == slot_key), None)
    if s is None or s.get("disabled"):
        raise LookupError("沒有這個附件種類：%s" % slot_key)
    if not _may_upload(conn, user, s):
        raise PermissionError("您沒有上傳這種附件的權限")
    return _policy_of(doc_type, s)


def catalog() -> dict:
    """編輯器的下拉資料：單據類型、位置代號（唯讀）、硬底線、平台上限、內建插槽、角色。"""
    return {"docTypes": [{"docType": t, "label": lbl, "code": SS.DOC_CODES[t], "owner": SS.LOCATION_CODES[SS.DOC_CODES[t]].owner,
                          "subfolderSupported": _provider_slot_aware(SS.DOC_CODES[t]), "key": "doc:%s" % t}
                         for t, lbl in sorted(SLOTTED_DOC_TYPES.items())],
            "hardExts": sorted(SS.HARD_EXTS), "slotExts": sorted(SS.SLOT_EXTS), "platform": {"maxFileMb": _platform_file_mb(), "maxFiles": MAX_FILES_CAP,
                                                           "maxRequestMb": MAX_REQUEST_MB_CAP, "maxSlots": MAX_SLOTS},
            "builtinSlot": BUILTIN_SLOT, "roles": list(_roles())}


# ── 模擬上傳（純函式、唯讀）────────────────────────────────────────────────────────
_HEADER_CHECKED = (".pdf", ".jpg", ".jpeg", ".png")


def _readers(conn, doc_type, rel) -> dict:
    """依該位置的讀取提供者，逐角色數「能讀的帳號 / 帳號總數」。只給人數，不給名單。"""
    out = {}
    for role in _roles():
        rows = conn.execute("SELECT id, username, display_name, role, modules, active FROM users WHERE role = ? AND active = 1", (role,)).fetchall()
        ok = 0
        for r in rows:
            try:
                if U.upload_readable(conn, rel, dict(r)):
                    ok += 1
            except Exception:                                   # noqa: BLE001
                pass
        out[role] = {"canRead": ok, "accounts": len(rows)}
    return out


def simulate(conn, definition, doc_type, slot_key, sample, doc_no=""):
    """在**不寫檔、不建資料夾**的前提下回答：這個附件種類收不收這個樣本檔、會存到哪、誰能讀。

    `definition`＝要試的定義 body（草稿）；`sample`＝`{filename, size, headerHex?, existing?}`；`doc_no`＝真實單據編號（選填，算「誰能讀」要用）。
    ⇒ dict；定義不合法 ⇒ `ValueError([problems])`。"""
    if doc_type not in SLOTTED_DOC_TYPES:
        raise LookupError("不支援的單據類型：%s" % doc_type)
    problems = definition_problems("doc:%s" % doc_type, definition)
    if problems:
        raise ValueError(problems)
    code = SS.DOC_CODES[doc_type]
    if slot_key in ("", BUILTIN_SLOT):
        pol, label = SS.builtin_policy(code), "簽回單"
        max_file = U.max_file_bytes()
    else:
        s = next((x for x in definition.get("slots", []) if x.get("key") == slot_key), None)
        if s is None:
            raise LookupError("定義裡沒有這個附件種類：%s" % slot_key)
        pol, label = _policy_of(doc_type, s), s.get("label", slot_key)
        max_file = min(pol.max_file_bytes or U.max_file_bytes(), U.max_file_bytes())
    name = str((sample or {}).get("filename") or "")
    size = int((sample or {}).get("size") or 0)
    existing = int((sample or {}).get("existing") or 0)
    ext = os.path.splitext(name)[1].lower()                      # 與上傳端同一支（".pdf" 這種隱藏檔名＝沒有副檔名）
    reasons = []
    inner = ["." + x for x in name.lower().split(".")[1:-1]]
    if any(e in SS.DANGEROUS_EXTS for e in inner):
        reasons.append("檔名含危險的雙重副檔名")
    allowed_now = set(pol.accept) & (SS.HARD_EXTS if pol.builtin else SS.SLOT_EXTS)
    if ext not in allowed_now:
        reasons.append("這種附件不收「%s」檔（可收：%s）" % (ext or "沒有副檔名", " ".join(sorted(allowed_now))))
    if size <= 0:
        reasons.append("檔案是空的")
    elif size > max_file:
        reasons.append("檔案過大（單檔上限 %dMB）" % (max_file // (1024 * 1024)))
    if pol.max_files and existing + 1 > pol.max_files:
        reasons.append("件數已滿（每張單據最多 %d 個，目前已有 %d 個）" % (pol.max_files, existing))
    if pol.max_request_bytes and size > pol.max_request_bytes:
        reasons.append("超過一次上傳的合計上限 %dMB" % (pol.max_request_bytes // (1024 * 1024)))
    head_note = ""
    hx = (sample or {}).get("headerHex")
    if hx:
        try:
            raw = bytes.fromhex(str(hx)[:128])
        except ValueError:
            raw = b""
            reasons.append("headerHex 不是十六進位")
        if raw and ext in _HEADER_CHECKED and not U._magic_matches(ext, raw):                # noqa: SLF001
            reasons.append("檔頭與副檔名不符（可能是改名的其他檔案）")
        elif raw and ext not in _HEADER_CHECKED:
            head_note = "此類檔案的檔頭要完整檔案才能檢查，這裡只示範 pdf／jpg／png"
    shown = "uploads/%s%s/%s/〈系統產生〉%s" % (pol.folder, ("/" + pol.subfolder) if pol.subfolder else "", doc_no or "〈單號〉", ext or "")
    out = {"ok": not reasons, "reasons": reasons, "headerNote": head_note, "slot": slot_key or BUILTIN_SLOT, "label": label,
           "displayPath": shown, "provider": SS.LOCATION_CODES[code].owner or "（專屬端點）",
           "subfolderUsable": (not pol.subfolder) or _provider_slot_aware(code),
           "limits": {"maxFileMb": max_file // (1024 * 1024), "maxFiles": pol.max_files or None, "maxRequestMb": (pol.max_request_bytes // (1024 * 1024)) or None},
           "existingFilesAffected": 0, "note": "只影響之後新上傳的檔案；已存的檔案不搬移、讀取權限不變。"}
    if doc_no and out["subfolderUsable"] and ext:
        rel = "%s%s/%s/sample%s" % (pol.folder, ("/" + pol.subfolder) if pol.subfolder else "", doc_no, ext)
        out["readers"] = _readers(conn, doc_type, rel)
    else:
        out["readers"] = None
    return out
