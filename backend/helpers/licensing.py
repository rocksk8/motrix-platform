"""授權金鑰核心（2026-09-21，細線 1 第 1、2 步）。

賣給第二家公司的前提是「這套系統能認得出它裝在誰的機器上、買到什麼、到什麼時候」。
這一支負責的就是那件事，而且**完全離線**——不打任何伺服器、不進資料庫，金鑰是一個檔案。

## 形狀

金鑰 blob ＝ `base64( JSON )`，`sig` 這個欄位**就在那個 JSON 裡面**：

    {"customer": "...", "tax_id": "...", "machine": "...",
     "modules": [...], "issued": "YYYY-MM-DD", "expires": "YYYY-MM-DD",
     "sig": "<base64(Ed25519 簽章)>"}

因為簽章欄位在 JSON 內部，驗證端**必須自己把 payload 重新正規化序列化**才算得出
簽章原文（見 `_signing_bytes`）。這也代表 blob 的排版、鍵的順序、空白都不影響驗證，
只有**內容**影響——竄改任何一個有意義的欄位都會讓簽章對不上。

## 三個名字必須「呼叫時才讀」

`_PUBKEY_DEV`／`_PUBKEY_PROD`／`LICENSE_PATH` 都是模組層級的名字，而且**只能在函式
被呼叫的當下才去讀它們**，不可以在 import 時就解析成 key 物件或把檔案讀進來。

理由不是潔癖：測試要 monkeypatch 這三個名字。import 時就定死的話，測試就只能拿
**真的私鑰**來簽，而真私鑰在 `.gitignore` 裡——測試會變成「只有某一台機器跑得動」。

`verify_license()` 每次呼叫都重讀 `LICENSE_PATH`，**刻意不快取**：第 6 步「到期前
提醒」需要每天重新判定 `days_left`，啟動時快取的話服務不重啟就永遠不會提醒。
（⚠️ 第 3 步把驗證掛進 middleware 之後這裡會變成每個 request 讀一次檔，屆時若要加
快取，必須保留「測試能換掉 `LICENSE_PATH` 與公鑰」這個性質——用 mtime 判定重讀，
不要改成 import 時一次性載入。見 `docs/windows/STATE.md` §3〈第 3 步預先註記〉。）

## 雙公鑰與 `env`

開發金鑰跟正式金鑰簽出來的授權**長得一模一樣、行為一模一樣**，所以開發金鑰被帶進
出貨包的那一天不會有任何錯誤訊息。壞掉會被報修，降級不會。因此這裡內嵌兩把公鑰，
`verify_license()` 兩把都試，並在回傳值裡帶 `env`（`"dev"`／`"prod"`／`None`），
讓「這台機器裝的是開發金鑰」變成一個**查得到的事實**，而不是一個要記得的事。

本輪 `_PUBKEY_PROD` 是空的（正式金鑰尚未產生，保管方式待使用者決定），空的那把
**略過不驗、不丟例外**。
"""
import base64
import binascii
import hashlib
import json
import os
import stat as _stat
import subprocess
import sys
from datetime import date

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 金鑰檔路徑。per-installation 的資料（不是程式碼），已在 .gitignore 第 11 行。
LICENSE_PATH = os.path.join(_BACKEND_DIR, "license.key")

# 開發用公鑰。私鑰在 backend/tools/_license_private_key_dev.pem（.gitignore 第 13 行）。
_PUBKEY_DEV = (
    b"-----BEGIN PUBLIC KEY-----\n"
    b"MCowBQYDK2VwAyEAu7m0fiwC0aqhTBzZ5FkiYHqWK76JwmHgPdQbewYv50M=\n"
    b"-----END PUBLIC KEY-----\n"
)

# 正式公鑰。**本輪刻意留空**——正式私鑰還沒產生，保管方式是 STATE §4 第 1 項的未決事項。
# 空的時候 verify_license() 略過這一把，不丟例外。
# ⚠️ 這裡一天是空的，這套系統就一天不能真的賣出去。
_PUBKEY_PROD = b""

# ── 總開關 ───────────────────────────────────────────────────────────────────
#
# **預設關。要打開必須是刻意的動作。**
#
# 為什麼一定要有它（A 於 2026-09-21 查證，非推論）：
#   - build_deploy_package.ps1:394 用 `git archive` 打包 → 只含已追蹤且已 commit 的內容
#   - backend/license.key 在 .gitignore:11 → **金鑰永遠不會進部署包**（這是對的，
#     金鑰本來就是 per-installation）
#   - apply_update.ps1:351 是「只加不刪，絕不 /MIR」→ 正式機上本來就沒有 license.key
#   ⇒ 守門一上正式機，每一支業務 API 都回 402，**整個系統癱瘓**。客戶看到的是
#     「全部功能都壞了」而不是「授權過期」——連登入後第一個畫面都載不出來。
#
# False 時守門**完全不介入**：連 verify_license() 都不呼叫。不要有「算了但不擋」
# 的中間狀態——那會付出效能成本卻換不到任何好處。
#
# 打開的順序不可以顛倒：
#   ① 把 license.key 放進那台機器
#   ② 確認 GET /api/license/status 回 valid:true
#   ③ 才把這個開關打開並重啟
LICENSE_GATE_ENABLED = False

# ── 授權種類 ─────────────────────────────────────────────────────────────────
#
# 「賣年費還是賣永久」是還沒決定的商業問題（STATE §4 第 3 項）。做成金鑰裡的一個
# 欄位，兩種都支援，到時候要賣哪種就簽哪種，程式不用改。
LICENSE_KIND_SUBSCRIPTION = "subscription"   # 年費：過期就擋
LICENSE_KIND_PERPETUAL    = "perpetual"      # 永久：過期只提示，不擋

# ── 豁免路徑 ─────────────────────────────────────────────────────────────────
#
# 未授權時這幾支仍然要通，否則客戶連自救都做不到：進不去登入頁、查不到為什麼被擋。
# **寫成一個具名常數讓測試釘得住**，不要散在判斷式裡——散在判斷式裡的豁免清單，
# 少一條不會有人發現。
# 實際豁免範圍 ＝ 這個集合 ∪ main.py 的 _PUBLIC_API_PATHS。
LICENSE_EXEMPT_PATHS = frozenset({
    "/api/ping",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/license/status",
})

# 缺任何一個就不是一把金鑰（`sig` 另外檢查）。`{}` 與 `{"sig": "..."}` 都靠這關擋下來。
_REQUIRED_FIELDS = ("customer", "tax_id", "machine", "modules", "issued", "expires")

# 主機板 UUID 讀得到、但內容是這些的機器不算數（部分主機板／虛擬機回這種值，
# 全世界都一樣就不是識別）。
_USELESS_UUIDS = {
    "00000000-0000-0000-0000-000000000000",
    "ffffffff-ffff-ffff-ffff-ffffffffffff",
    "03000200-0400-0500-0006-000700080009",
}

_CREATE_NO_WINDOW = 0x08000000  # 服務裡跑不要閃黑窗


# ── LicenseStatus ────────────────────────────────────────────────────────────

def _status(valid, reason, env=None, customer=None, modules=None,
            expires=None, days_left=None, kind=None):
    """八個欄位固定都在。缺欄位在前端會變成 undefined，比錯的值更難查。

    第 1 輪是七個欄位，第 2 輪加上 `kind`（年費／永久）。
    """
    return {
        "valid":     valid,
        "reason":    reason,
        "env":       env,
        "customer":  customer,
        "modules":   modules,
        "expires":   expires,
        "days_left": days_left,
        "kind":      kind,
    }


def _unverified(reason):
    """簽章驗過之前，payload 沒有任何一個欄位可信——所以一律不回填。

    `env` 也是 None：這三種情況（missing／malformed／bad_signature）沒有任何一把
    公鑰驗過，講不出是誰簽的。日後打包關卡的判斷式是 `env != "prod"` 就擋，
    None 會被擋下來，那是安全的那一側。
    """
    return _status(False, reason)


def _normalise_kind(raw):
    """金鑰裡的 `kind` → 正規化後的種類。**只有明確寫著 perpetual 才算永久。**

    缺漏（第 1 輪簽出來的舊金鑰沒有這個欄位）、拼錯、型別不對、沒見過的值，
    一律當成 `subscription` ——也就是**過期會被擋住**那一邊。

    不確定的時候要往安全的那一邊倒：把不認得的值當永久授權，等於任何一個打錯字的
    金鑰都變成永不過期；反過來最壞只是誤擋，而誤擋看得見、會有人報修。
    """
    if isinstance(raw, str) and raw.strip().lower() == LICENSE_KIND_PERPETUAL:
        return LICENSE_KIND_PERPETUAL
    return LICENSE_KIND_SUBSCRIPTION


# ── 簽章原文（簽與驗都必須走這一支，不可以各寫各的）──────────────────────────

def _signing_bytes(payload):
    """payload（去掉 sig）→ 簽章原文 bytes。

    `sort_keys` ＋ 最緊湊的分隔符 ＝ 同樣內容永遠產生同樣的 bytes，
    所以 blob 怎麼排版都不影響驗證結果。
    `ensure_ascii=False` 是必要的：客戶名稱是中文，跟著 UTF-8 一起編碼才穩定。
    """
    body = {k: v for k, v in payload.items() if k != "sig"}
    return json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


# ── 簽發 ─────────────────────────────────────────────────────────────────────

def sign_license(payload, private_key_pem):
    """用 Ed25519 私鑰簽一把金鑰，回傳 blob（base64 字串）。

    `payload` 裡若已經有 `sig` 會被忽略（不會拿舊簽章去簽新簽章）。
    私鑰不是 Ed25519 就直接丟例外——簽發是離線動作，錯了要當場知道，不要產出一把
    驗不過的金鑰交給客戶。
    """
    priv = serialization.load_pem_private_key(private_key_pem, password=None)
    if not isinstance(priv, Ed25519PrivateKey):
        raise TypeError(
            f"授權金鑰只收 Ed25519 私鑰，拿到的是 {type(priv).__name__}"
        )

    body = {k: v for k, v in payload.items() if k != "sig"}
    signature = priv.sign(_signing_bytes(body))

    signed = dict(body)
    signed["sig"] = base64.b64encode(signature).decode("ascii")
    blob = json.dumps(
        signed, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return base64.b64encode(blob).decode("ascii")


# ── 驗證 ─────────────────────────────────────────────────────────────────────

def _decode_blob(text):
    """blob 字串 → payload dict。解不開或不是 JSON 物件一律回 None（＝ malformed）。"""
    try:
        raw = text.strip().encode("ascii")
    except UnicodeEncodeError:
        return None  # 非 ASCII 的字串根本不是 base64

    for decoder in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            obj = json.loads(decoder(raw))
        except Exception:  # noqa: BLE001 — 解不開的原因有十幾種，對外都是 malformed
            continue
        return obj if isinstance(obj, dict) else None
    return None


def _days_left(expires):
    """到期日字串 → 距今天數（今天到期 = 0，昨天到期 = -1）。算不出來回 None。"""
    if not isinstance(expires, str):
        return None
    try:
        return (date.fromisoformat(expires.strip()) - date.today()).days
    except ValueError:
        return None


# ── 金鑰檔快取 ───────────────────────────────────────────────────────────────
#
# 第 1 輪明文要求「每次呼叫才讀檔」，第 3 步把驗證掛進 middleware 之後那就是
# **每個 request 讀一次檔**。實測（本機，指紋已暖）：
#     verify_license() 含讀檔 0.90 ms／次 ── 其中純讀檔 0.36 ms
#     os.stat()                0.12 ms／次
# ⇒ 用 stat 判定重讀，一次省下約 7 倍。本專案有過簽核卡死 32.8 秒的前例，
#   「檔案很小所以沒差」不是可以假設的東西。
#
# 快取鍵刻意包含五樣東西，少任何一樣都會變成一個很難查的 bug：
#   ① 路徑      —— 測試會把 LICENSE_PATH 換掉
#   ② mtime_ns  —— 檔案被換掉要重讀（驗收條件 10）
#   ③ 大小      —— mtime 解析度的保險絲
#   ④ 兩把公鑰  —— 測試會 monkeypatch 它們；不放進鍵的話換了公鑰還會拿到舊答案
#   ⑤ **今天的日期** —— 見下面那一段，這一項是最容易漏掉的
#
# ⚠️ ⑤ 為什麼非有不可：`days_left` 是拿 `date.today()` 算的。不把日期放進鍵，
#    一台**不重啟的正式機**會永遠沿用第一次算出來的 days_left ——
#    今天算出「還有 1 天」，明天、後天、明年都還是「還有 1 天」，**永遠不會過期**。
#    年費授權會因此變成永久授權，而且不會有任何錯誤訊息。
#    `date.today()` 只要 0.76 微秒，這是這份快取裡最便宜也最重要的一項。
#
# 執行緒安全：uvicorn 的同步端點跑在 threadpool 裡。這裡只做「整個 tuple 一次指派」，
# GIL 底下是原子的；最壞情況是兩個執行緒各算一次、其中一個蓋掉另一個，無害。
# 不上鎖是刻意的——為了一個 0.1 ms 的東西引入鎖，風險比它省下來的多。
_LICENSE_FILE_CACHE = None   # (快取鍵, status 複本)


def _license_cache_key(path, st_result):
    return (
        path,
        st_result.st_mtime_ns,
        st_result.st_size,
        _PUBKEY_DEV,
        _PUBKEY_PROD,
        date.today().toordinal(),
    )


def _verify_license_file():
    """讀 `LICENSE_PATH` 並驗它。**在函式裡讀模組層級的名字**，所以測試換得掉。"""
    global _LICENSE_FILE_CACHE

    path = LICENSE_PATH
    try:
        st_result = os.stat(path)
    except OSError:
        _LICENSE_FILE_CACHE = None
        return _unverified("missing")
    if not _stat.S_ISREG(st_result.st_mode):
        _LICENSE_FILE_CACHE = None
        return _unverified("missing")

    key    = _license_cache_key(path, st_result)
    cached = _LICENSE_FILE_CACHE
    if cached is not None and cached[0] == key:
        # 回複本：呼叫端改了回傳值也不會污染下一個人拿到的東西。
        return dict(cached[1])

    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError):
        # 檔在、但讀不到（權限／磁碟／編碼）。這不是「沒有金鑰」是「金鑰壞了」，
        # 回 missing 會讓現場以為還沒裝，往錯的方向查。
        _LICENSE_FILE_CACHE = None
        return _unverified("malformed")

    status = _verify_blob(text)
    _LICENSE_FILE_CACHE = (key, dict(status))
    return status


def verify_license(blob=None):
    """驗一把金鑰，回 LicenseStatus（八個欄位）。**任何情況都不丟例外。**

    `blob` 省略或 None → 改讀 `LICENSE_PATH`（條件 5「檔案不存在 → missing」要有人
    負責讀檔，放在這裡才驗得到「服務起得來」這件事）。

    檢查順序固定：`malformed → missing → bad_signature → machine_mismatch → expired`。
    **簽章一定排在 machine／expires 之前**——簽章驗過之前 payload 沒有任何一個欄位
    可信，先看 `expires` 等於相信一個還沒驗過的數字。
    """
    if blob is None:
        return _verify_license_file()
    return _verify_blob(blob)


def _verify_blob(text):
    """驗一個已經拿到手的 blob 字串。不碰檔案系統。"""
    if isinstance(text, (bytes, bytearray)):
        try:
            text = bytes(text).decode("utf-8")
        except UnicodeDecodeError:
            return _unverified("malformed")
    elif not isinstance(text, str):
        return _unverified("malformed")

    # 空字串／只有空白 ＝ 沒有金鑰，不是壞掉的金鑰。
    if not text.strip():
        return _unverified("missing")

    payload = _decode_blob(text)
    if payload is None:
        return _unverified("malformed")
    if any(k not in payload for k in _REQUIRED_FIELDS):
        return _unverified("malformed")

    sig_b64 = payload.get("sig")
    if not isinstance(sig_b64, str) or not sig_b64:
        return _unverified("malformed")
    try:
        signature = base64.b64decode(sig_b64.encode("ascii"), validate=True)
    except (binascii.Error, ValueError, UnicodeEncodeError):
        # 結構是對的，壞的是簽章本身 → 這是簽章問題不是格式問題。
        return _unverified("bad_signature")

    signed_bytes = _signing_bytes(payload)
    env = None
    for name, pem in (("dev", _PUBKEY_DEV), ("prod", _PUBKEY_PROD)):
        if not pem or not pem.strip():
            continue  # _PUBKEY_PROD 是空的：略過，不丟例外
        try:
            pub = serialization.load_pem_public_key(pem)
            if not isinstance(pub, Ed25519PublicKey):
                continue
            pub.verify(signature, signed_bytes)
        except Exception:  # noqa: BLE001 — 驗不過就是驗不過，換下一把
            continue
        env = name
        break

    if env is None:
        return _unverified("bad_signature")

    # ── 到這裡 payload 才可信 ────────────────────────────────────────────────
    customer  = payload.get("customer")
    modules   = payload.get("modules")
    expires   = payload.get("expires")
    # `kind` 不在 _REQUIRED_FIELDS 裡是刻意的：第 1 輪簽出來的金鑰沒有這個欄位，
    # 把它列為必要會讓那些金鑰突然變成 malformed。缺漏交給 _normalise_kind 處理。
    # 它自動落在簽章範圍內（_signing_bytes 簽的是除 sig 以外的全部欄位），
    # 所以竄改 kind 會被 bad_signature 擋下來。
    kind      = _normalise_kind(payload.get("kind"))
    days_left = _days_left(expires)
    if days_left is None:
        # 簽章對、但到期日不是日期。簽發端出了錯，不是客戶竄改。
        # `env` 仍然回 None：契約明訂 malformed 一律不帶 env（即使這裡其實知道是誰簽的）。
        return _unverified("malformed")

    def _with(valid, reason):
        return _status(valid, reason, env=env, customer=customer,
                       modules=modules, expires=expires, days_left=days_left,
                       kind=kind)

    try:
        this_machine = machine_fingerprint()
    except Exception:  # noqa: BLE001
        # 算不出本機指紋 ＝ 無法確認這把金鑰是發給這台機器的。
        # 這種時候要拒絕，不是放行——「讀不到就當它對」是把鎖拆掉。
        this_machine = None

    licensed_to = payload.get("machine")
    if (not isinstance(licensed_to, str) or this_machine is None
            or licensed_to.strip().lower() != this_machine):
        return _with(False, "machine_mismatch")

    if days_left < 0:
        return _with(False, "expired")

    return _with(True, "ok")


# ── 守門判定（純函式，middleware 只負責呼叫）────────────────────────────────

_GATE_MESSAGES = {
    "missing":          "這台機器尚未安裝授權金鑰，請聯絡供應商取得。",
    "malformed":        "授權金鑰檔已損毀，請聯絡供應商重新取得。",
    "bad_signature":    "授權金鑰驗證失敗（簽章不符），請聯絡供應商重新取得。",
    "machine_mismatch": "這把授權金鑰不是發給這台機器的，換機請聯絡供應商重新簽發。",
    "expired":          "授權已到期，請聯絡供應商續約。",
}


def license_blocks_request(status):
    """這個授權狀態該不該擋住業務 API。**抽成純函式才測得到「換一種設定」。**

    - `ok` → 不擋
    - `expired` 且 `kind == perpetual` → **不擋**（永久授權過的是維護期，
      不是使用權；只在畫面上提示「可繼續使用但不再提供更新」）
    - 其餘一律擋：missing／malformed／bad_signature／machine_mismatch／
      `expired` 且非永久（含第 1 輪沒有 `kind` 的舊金鑰——見 _normalise_kind）
    """
    reason = status.get("reason")
    if reason == "ok":
        return False
    if reason == "expired" and status.get("kind") == LICENSE_KIND_PERPETUAL:
        return False
    return True


def license_block_message(status):
    """擋下來時要給人看的中文訊息。**402 不可以是空 body** ——
    客服現場要分得出「這個人沒權限（403）」與「這台機器沒買（402）」。
    """
    return _GATE_MESSAGES.get(
        status.get("reason"), "授權狀態異常，請聯絡供應商。"
    )


# ── 機器指紋 ─────────────────────────────────────────────────────────────────

# 同一個行程內算一次就好。**這個快取存的是從硬體讀出來的值**，所以換一個行程重算
# 也會得到同一個答案（見 test_07b）——不是啟動時產生的隨機值快取起來，那種做法能
# 通過「連呼叫兩次相同」，但客戶重啟服務之後金鑰就全部失效了。
_FINGERPRINT_CACHE = None


def _run(cmd, timeout=30):
    """跑外部指令拿 stdout。失敗一律回空字串，不丟例外。"""
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            # encoding 一定要給：不給的話中文輸出會在讀取執行緒解碼失敗，
            # 例外不回主流程、returncode 仍是 0、stdout 變 None。
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            **kwargs,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout or ""


_PS_HARDWARE = (
    "$ErrorActionPreference='SilentlyContinue';"
    "$u=(Get-CimInstance Win32_ComputerSystemProduct).UUID;"
    "if($u){'UUID'+[char]9+$u};"
    "Get-CimInstance Win32_NetworkAdapter -Filter 'PhysicalAdapter=true' |"
    " Where-Object {$_.MACAddress} |"
    " ForEach-Object {'NIC'+[char]9+$_.PNPDeviceID+[char]9+$_.MACAddress}"
)


def _normalise_mac(raw):
    """`B0:82:E2:5E:6A:75` → `b082e25e6a75`。不是 12 碼 hex 就回空字串。"""
    mac = "".join(c for c in (raw or "").lower() if c in "0123456789abcdef")
    if len(mac) != 12 or mac == "000000000000":
        return ""
    return mac


def _windows_hardware():
    """回 (主機板 UUID, 主要實體網卡 MAC)，讀不到的那個是空字串。

    ⚠️ `PhysicalAdapter=true` **不等於實體網卡**：這台開發機上它同時包含
    TAP-Windows（OpenVPN）與藍牙 PAN。這兩個裝了／移除指紋就會漂，客戶的授權
    會莫名其妙失效。所以再用 `PNPDeviceID` 篩一層，只留 PCI／USB 掛上去的。
    """
    out = _run([
        "powershell", "-NoProfile", "-NonInteractive",
        "-ExecutionPolicy", "Bypass", "-Command", _PS_HARDWARE,
    ])

    uuid_ = ""
    real, any_mac = [], []
    for line in out.splitlines():
        parts = line.strip().split("\t")
        if parts[0] == "UUID" and len(parts) >= 2:
            candidate = parts[1].strip().lower()
            if candidate and candidate not in _USELESS_UUIDS:
                uuid_ = candidate
        elif parts[0] == "NIC" and len(parts) >= 3:
            mac = _normalise_mac(parts[2])
            if not mac:
                continue
            any_mac.append(mac)
            pnp = parts[1].strip().upper()
            if pnp.startswith("PCI\\") or pnp.startswith("USB\\"):
                real.append(mac)

    # 排序後取最小的，不是「列舉順序的第一個」——列舉順序會因為裝置增減而變動，
    # 排序過的最小值不會。
    pool = real or any_mac
    return uuid_, (sorted(pool)[0] if pool else "")


def _posix_hardware():
    """Linux／容器：DMI product_uuid（要 root）＋ 掛在真實裝置上的網卡 MAC。"""
    uuid_ = ""
    try:
        with open("/sys/class/dmi/id/product_uuid", "r", encoding="utf-8") as fh:
            candidate = fh.read().strip().lower()
        if candidate and candidate not in _USELESS_UUIDS:
            uuid_ = candidate
    except OSError:
        pass

    macs = []
    net = "/sys/class/net"
    try:
        for name in sorted(os.listdir(net)):
            if name == "lo":
                continue
            # 有 device 這個 symlink 才是掛在真實匯流排上的網卡，
            # 這關篩掉 docker0／veth／tun 這些會來會去的虛擬介面。
            if not os.path.exists(os.path.join(net, name, "device")):
                continue
            try:
                with open(os.path.join(net, name, "address"), "r",
                          encoding="utf-8") as fh:
                    mac = _normalise_mac(fh.read())
            except OSError:
                continue
            if mac:
                macs.append(mac)
    except OSError:
        pass

    return uuid_, (sorted(macs)[0] if macs else "")


def _stable_machine_id():
    """最後的退路：作業系統安裝時產生的機器 ID。

    它綁的是「這套 OS 安裝」而不是硬體，所以重灌會變——比硬體弱，但它是穩定的，
    而穩定正是指紋唯一不能妥協的性質。只有在硬體來源全部讀不到時才會用到。
    """
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
                0,
                winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
            ) as key:
                value, _ = winreg.QueryValueEx(key, "MachineGuid")
            return (value or "").strip().lower()
        except OSError:
            return ""

    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                value = fh.read().strip().lower()
            if value:
                return value
        except OSError:
            continue
    return ""


def machine_fingerprint():
    """這台機器的指紋：sha256 前 16 碼（小寫 hex）。

    來源是主機板 UUID ＋ 第一張實體網卡 MAC。**必須跨行程一致**——客戶重啟服務
    之後指紋變了，等於所有金鑰失效。

    一個硬體來源都讀不到就丟 `RuntimeError`：算不出來就什麼都不要回，不要回一個
    看起來像指紋的假值——那會讓「機器不符」這道鎖在不知不覺間失效。
    呼叫端（`verify_license`）接住它並拒絕該筆，不是放行。
    """
    global _FINGERPRINT_CACHE
    if _FINGERPRINT_CACHE is not None:
        return _FINGERPRINT_CACHE

    if sys.platform == "win32":
        uuid_, mac = _windows_hardware()
    else:
        uuid_, mac = _posix_hardware()

    parts = []
    if uuid_:
        parts.append("uuid=" + uuid_)
    if mac:
        parts.append("mac=" + mac)
    if not parts:
        fallback = _stable_machine_id()
        if fallback:
            parts.append("machineid=" + fallback)
    if not parts:
        raise RuntimeError(
            "無法取得任何硬體識別（主機板 UUID／實體網卡 MAC／機器 ID 都讀不到），"
            "算不出機器指紋"
        )

    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    _FINGERPRINT_CACHE = digest[:16]
    return _FINGERPRINT_CACHE
