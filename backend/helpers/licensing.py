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
import copy
import hashlib
import json
import os
import re
import stat as _stat
import subprocess
import sys
import threading
import time
from datetime import date

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from core import paths as _paths

# 金鑰檔路徑。per-installation 的資料（不是程式碼），已在 .gitignore 第 11 行。
LICENSE_PATH = _paths.LICENSE_PATH

# 開發用公鑰。私鑰在 backend/tools/_license_private_key_dev.pem（.gitignore 第 13 行）。
_PUBKEY_DEV = (
    b"-----BEGIN PUBLIC KEY-----\n"
    b"MCowBQYDK2VwAyEAu7m0fiwC0aqhTBzZ5FkiYHqWK76JwmHgPdQbewYv50M=\n"
    b"-----END PUBLIC KEY-----\n"
)

# 正式公鑰（2026-11-12 產生，私鑰依 STATE §4 2026-09-21 裁示存密碼管理器，開發機上直接簽發，
# 不落地在任何 repo／worktree）。對應的正式機指紋與客戶資料不寫在這裡——這支會進出貨包，
# 不可以帶著任何一台客戶安裝的識別資料（test_no_our_company_literals 這類守門就是防這個）。
_PUBKEY_PROD = (
    b"-----BEGIN PUBLIC KEY-----\n"
    b"MCowBQYDK2VwAyEAdfv+I3XFU/ptNcjmFuQAk9ZufbS5JAXzLykMHgnbnMc=\n"
    b"-----END PUBLIC KEY-----\n"
)

# ── 總開關 ───────────────────────────────────────────────────────────────────
#
# **預設開（2026-11-11 起；原本預設關）。** False 時守門完全不介入的行為仍在，測試釘著。
#
# ── 預設值的沿革（稽核紀錄）──
#   fb329becb（2026-09-21）：做成預設 False，「第 2 輪的第一件事是總開關，不是 middleware」。
#   a63cc4978（同日）：掛 middleware，仍是預設不生效；STATE 另把「解凍的程式強制前置」
#       定為「補寫 backend/tests/test_licensing_gate_2026_09_21.py」（第 2 輪那十來條驗收條件
#       除了「關著時不介入」之外沒有任何一條被測試跑過——開著時的行為零覆蓋）。
#   2026-11-11：使用者裁示重新打開，認定當年關閉的理由（下一段）現在不成立。
#       這一版同時補了那份測試（test_licensing_gate_2026_09_21.py：沒金鑰／過期／無效／有效四種情境）、
#       並讓 conftest 對整個測試 session 提供一把測試金鑰（驗章走真的簽章路徑，只換公鑰與機器指紋）。
#   ⚠️ 這個 commit 只改程式與測試，**沒有部署**。截至 2026-11-11，正式機沒有 license.key，
#       `_PUBKEY_PROD` 仍是空的（正式私鑰尚未產生）⇒ 在簽發機制與正式機金鑰就緒之前，
#       不可以把這個預設值帶上正式機（見下一段與「上正式機的順序」）。
#
# 當年為什麼要預設關（A 於 2026-09-21 查證，非推論）：
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
# 上正式機的順序不可以顛倒（預設已是 True，所以「先放金鑰」變成**部署前**的條件）：
#   ① 簽出一把綁這台機器指紋、由 `_PUBKEY_PROD` 對應私鑰簽的金鑰（env 要是 "prod"）
#   ② 把 license.key 放進那台機器
#   ③ 確認 GET /api/license/status 回 valid:true，**之後**才部署這個版本並重啟
LICENSE_GATE_ENABLED = True

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
_LICENSE_FILE_CACHE = None   # (快取鍵, status 複本, 算出時的 time.monotonic()——machine_mismatch 的短TTL要用)


def _license_cache_key(path, st_result):
    return (
        path,
        st_result.st_mtime_ns,
        st_result.st_size,
        _PUBKEY_DEV,
        _PUBKEY_PROD,
        date.today().toordinal(),
    )


_MISMATCH_CACHE_TTL_S = 60  # T80稽核LG-M1：machine_mismatch只快取這麼久（見下方理由）


def _copy_status(d):
    """狀態 dict 的複本，**連裡面的清單／字典一起複製**（T80稽核 LG-S3）。

    `dict(d)` 是淺拷貝：`modules` 這種清單會在快取與每個呼叫端之間共用，任何一個呼叫端對回傳值 `append`／`remove`
    就會污染快取、影響下一個請求拿到的授權範圍（授權模組清單被改＝別人的權限被改）。目前沒有呼叫端這樣做，是潛在風險。
    只複製容器型別的值：純量值是不可變的，不必花成本（這支在每個 /api 請求的熱路徑上）。"""
    out = dict(d)
    for k, v in out.items():
        if isinstance(v, (list, dict, set)):
            out[k] = copy.deepcopy(v)
    return out


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
        cached_status, cached_at = cached[1], cached[2]
        # T80稽核LG-M1：machine_mismatch的快取只活 _MISMATCH_CACHE_TTL_S 秒。快取鍵
        # 不含指紋（見上方①～⑤），硬體在開機初期讀不到／讀一半時會算出錯的指紋、判
        # mismatch；這個結果若像其他結果一樣整天／整個行程快取，硬體之後恢復正常，
        # 同一把金鑰仍會卡在「機器不符」直到檔案被碰、跨日或重啟——短TTL把這個停擺
        # 視窗從「不定期、可能整天」收斂成「最多一分鐘」，同時避免每一次請求都重算
        # （`machine_fingerprint()` 持續失敗時本身有重試，直接每個請求都跑代價不小，
        # 見 K審S6 `routers/licensing.py::_FP_FAIL_UNTIL` 同一類考量）。
        if cached_status.get("reason") != "machine_mismatch" or (time.monotonic() - cached_at) <= _MISMATCH_CACHE_TTL_S:
            # 回複本：呼叫端改了回傳值也不會污染下一個人拿到的東西（LG-S3：連 modules 清單也是複本）。
            return _copy_status(cached_status)

    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError):
        # 檔在、但讀不到（權限／磁碟／編碼）。這不是「沒有金鑰」是「金鑰壞了」，
        # 回 missing 會讓現場以為還沒裝，往錯的方向查。
        _LICENSE_FILE_CACHE = None
        return _unverified("malformed")

    status = _verify_blob(text)
    _LICENSE_FILE_CACHE = (key, _copy_status(status), time.monotonic())
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


def _open_blob(text, required=None):
    """blob 字串 → `(payload, env, None)`（簽章驗過）或 `(None, None, reason)`。

    **簽章驗過之前 payload 沒有任何一個欄位可信**，所以失敗時一律不回 payload。
    授權金鑰與緊急放行通行證（見下方）共用這一條驗章路徑，只差 `required`（必要欄位）。
    reason ∈ missing／malformed／bad_signature；檢查順序固定，與 `verify_license` 的契約一致。
    """
    if required is None:
        required = _REQUIRED_FIELDS
    if isinstance(text, (bytes, bytearray)):
        try:
            text = bytes(text).decode("utf-8")
        except UnicodeDecodeError:
            return None, None, "malformed"
    elif not isinstance(text, str):
        return None, None, "malformed"

    # 空字串／只有空白 ＝ 沒有金鑰，不是壞掉的金鑰。
    if not text.strip():
        return None, None, "missing"

    payload = _decode_blob(text)
    if payload is None:
        return None, None, "malformed"
    if any(k not in payload for k in required):
        return None, None, "malformed"

    sig_b64 = payload.get("sig")
    if not isinstance(sig_b64, str) or not sig_b64:
        return None, None, "malformed"
    try:
        signature = base64.b64decode(sig_b64.encode("ascii"), validate=True)
    except (binascii.Error, ValueError, UnicodeEncodeError):
        # 結構是對的，壞的是簽章本身 → 這是簽章問題不是格式問題。
        return None, None, "bad_signature"

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
        return None, None, "bad_signature"
    return payload, env, None


def _verify_blob(text):
    """驗一個已經拿到手的 blob 字串。不碰檔案系統。"""
    payload, env, why = _open_blob(text)
    if payload is None:
        return _unverified(why)

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


# ── 緊急放行通行證（break-glass；2026-11-11，T80）────────────────────────────
#
# 為什麼要有：授權閘門沒有任何「程式以外」的出口時，正式機只要金鑰失效（最典型：換主機板／網卡造成機器指紋漂移，
# 這台機器有過 BSOD 0x124 記憶體 MCE 紀錄，換硬體不是假設）就是全站 402，唯一的解法是重新發版。
#
# 怎麼做（**不是「放一個檔案就放行」**——那個口本身會變成新的繞過漏洞）：
#   ① 通行證是**簽章過的**（與授權金鑰同一條驗章路徑、同兩把公鑰）：只有握有私鑰的簽發方做得出來，
#      伺服器管理員自己建檔、改日期、改內容都會 bad_signature。
#   ② `purpose` 必須是 "emergency_pass"：授權金鑰不能拿來當通行證，通行證也不是授權金鑰（缺 machine／modules ⇒ malformed）。
#   ③ **綁被救的那把授權金鑰**：不綁目標機器「現在」的指紋（指紋漂移正是它存在的理由）。綁 `tax_id` 與 `machine`
#      （授權金鑰裡那個值），都必須等於**驗章通過**的那把授權金鑰的值——別家客戶的、同客戶另一個安裝的通行證、
#      或沒有可信授權金鑰時，不放行（K 審 S5）。**簽發環境**（開發／正式）也必須與那把授權金鑰相同（K 審 M2：開發私鑰
#      不在受控保管下，正式公鑰一上線，這是唯一擋住「拿開發金鑰簽通行證」的東西）。擋不住的：把授權金鑰與通行證兩個檔
#      一起複製到別台——那台指紋也對不上，所以仍由 14 天上限兜底。
#   ④ **只救兩種狀況**：`machine_mismatch`（換硬體）、`expired`（續約作業來不及）。沒有金鑰／損毀／簽章不符
#      都不放行——那是「重新簽一把授權」的事，不是通行證該蓋掉的事。
#   ⑤ **有期限且上限寫死在驗證端**：`issued ≤ 今天 ≤ expires`，且 `expires − issued ≤ EMERGENCY_MAX_DAYS`。
#      簽發方多簽幾年也沒用。過期的通行證自動失效，不需要有人去刪。
#   ⑥ 放行時**不安靜**：log＋稽核（helpers/license_alerts.py）、每個 /api 回應帶 `X-Motrix-License: emergency;until=…`
#      （前端橫幅）、`GET /api/license/status` 的 `emergency` 欄位講出生效或不生效的原因。
#
# 位置：與授權金鑰同一個資料夾的 `license_emergency.key`（`emergency_path()`，跟著 `LICENSE_PATH` 走，測試換得掉）。
# 簽發：`python tools/issue_license.py emergency --license <被救的 license.key> --days 7 --reason "…" --out license_emergency.key`。
# 生效時間：業務 API 下一個請求就恢復；**但模組是否載入只在開機時決定一次**（core/loader.py）：服務若是在授權失效時
# 啟動的（換主機板後重開機最常見），被擋的模組要在放好通行證之後**重啟服務**才會載入（`/api/license/status` 的
# `modules_unlicensed` 列出它們；K 審 M1）。
# 〔上正式金鑰時的另一張票（K 審 nit）：`_PUBKEY_PROD` 填入之後，部署包不要再帶 `_PUBKEY_DEV`（build／git archive 那一步），
#   不要靠「這台是不是正式機」的猜測——那是唯一可靠的訊號。〕
EMERGENCY_FILE_NAME = "license_emergency.key"
EMERGENCY_PURPOSE = "emergency_pass"
EMERGENCY_MAX_DAYS = 14                                   # 驗證端的硬上限（簽發端再長也只認這麼久）
EMERGENCY_MAX_BYTES = 8192                                # 通行證是小檔；超過就不讀
EMERGENCY_COVERS = frozenset({"machine_mismatch", "expired"})
LICENSE_HEADER = "X-Motrix-License"                       # 前端橫幅用（notif.js）
_EMERGENCY_REQUIRED = ("purpose", "tax_id", "machine", "issued", "expires", "reason")
# date.fromisoformat（py3.11+）也收 20261111／週曆格式；通行證只收 YYYY-MM-DD
_ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def emergency_path():
    """通行證檔案位置：與授權金鑰同一個資料夾。**呼叫時才算**（測試會換 `LICENSE_PATH`）。"""
    return os.path.join(os.path.dirname(os.path.abspath(LICENSE_PATH)), EMERGENCY_FILE_NAME)


def _read_small_text(path, limit=None):
    """讀一個小檔 → `(text, None)` 或 `(None, 原因)`。原因：missing／unreadable／too_big。不丟例外。"""
    try:
        st_result = os.stat(path)
    except OSError:
        return None, "missing"
    if not _stat.S_ISREG(st_result.st_mode):
        return None, "missing"
    if st_result.st_size > (EMERGENCY_MAX_BYTES if limit is None else limit):
        return None, "too_big"
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read(), None
    except (OSError, UnicodeDecodeError):
        return None, "unreadable"


def _emergency_judge(status, token_text):
    """通行證判定（純函式，不碰檔案系統除了讀授權金鑰）→ dict：present／active／why（＋ until／pass_id／note／env）。"""
    pass_id = hashlib.sha256(token_text.strip().encode("utf-8", "replace")).hexdigest()[:12]
    base = {"present": True, "active": False, "pass_id": pass_id}

    def no(why, extra=None):
        out = dict(base, why=why)
        out.update(extra or {})
        return out

    payload, env, why = _open_blob(token_text, _EMERGENCY_REQUIRED)
    if payload is None:
        return no("token_bad_signature" if why == "bad_signature" else "token_malformed")
    if payload.get("purpose") != EMERGENCY_PURPOSE:
        return no("token_wrong_purpose", {"env": env})

    issued, expires = payload.get("issued"), payload.get("expires")
    try:
        if not (_ISO_DATE.match(issued.strip()) and _ISO_DATE.match(expires.strip())):
            raise ValueError("not YYYY-MM-DD")
        d_issued = date.fromisoformat(issued.strip())
        d_expires = date.fromisoformat(expires.strip())
    except (AttributeError, ValueError):
        return no("token_bad_dates", {"env": env})
    until = d_expires.isoformat()
    note = payload.get("reason") if isinstance(payload.get("reason"), str) else ""
    info = {"until": until, "note": note, "env": env}
    if (d_expires - d_issued).days > EMERGENCY_MAX_DAYS or d_expires < d_issued:
        return no("token_span_too_long", info)
    today = date.today()
    if today < d_issued:
        return no("token_not_yet_valid", info)
    if today > d_expires:
        return no("token_expired", info)

    # ③④：只在授權金鑰「驗章通過、但機器不符或過期」時才有意義；綁的是那把金鑰的 tax_id。
    if not isinstance(status, dict) or status.get("reason") not in EMERGENCY_COVERS:
        return no("not_needed" if (status or {}).get("reason") == "ok" else "license_not_covered", info)
    if not license_blocks_request(status):       # 例：永久授權過期（reason=expired 但不擋）⇒ 沒有東西要放行，不可以報「生效」
        return no("not_needed", info)
    # 授權金鑰讀法與 verify_license 一致（不設 8 KB 上限，否則「驗得過卻救不了」）
    lic_text, err = _read_small_text(LICENSE_PATH, limit=1 << 30)
    lic_payload, lic_env, _why = _open_blob(lic_text) if lic_text is not None else (None, None, None)
    if lic_payload is None:
        return no("license_untrusted", info)
    # 簽發方環境必須相同：開發金鑰簽的通行證不能救正式金鑰的授權（反之亦然）。開發私鑰不在受控保管下，
    # 正式公鑰一進 _PUBKEY_PROD，這一條就是唯一擋住「拿開發金鑰簽通行證」的東西（K 審 M2）。
    if env != lic_env:
        return no("env_mismatch", info)
    if not _same_text(lic_payload.get("tax_id"), payload.get("tax_id"), lower=False):
        return no("tax_id_mismatch", info)
    # 通行證也綁被救的那把授權金鑰的 machine 值：只能救「那一個安裝」，不是客戶的任何一份授權（K 審 S5）。
    # （擋不住「同時複製授權金鑰與通行證到別台」——那台的指紋也對不上，所以仍是同一條 14 天上限在兜底。）
    if not _same_text(lic_payload.get("machine"), payload.get("machine"), lower=True):
        return no("machine_mismatch", info)

    out = dict(base, why="ok", active=True)
    out.update(info)
    return out


def _same_text(a, b, lower):
    """兩個欄位都是非空字串、去頭尾空白後相等（型別不對、空字串一律不相等）。"""
    if not isinstance(a, str) or not isinstance(b, str):
        return False
    a, b = a.strip(), b.strip()
    if lower:
        a, b = a.lower(), b.lower()
    return a != "" and a == b


def emergency_status(status):
    """給狀態端點用：沒有通行證檔 → None；有 → dict（active／why …）。**任何情況都不丟例外。**"""
    try:
        text, err = _read_small_text(emergency_path())
        if text is None:
            if err == "missing":
                return None
            return {"present": True, "active": False, "why": "token_" + err, "pass_id": None}
        return _emergency_judge(status, text)
    except Exception:  # noqa: BLE001 — 狀態端點不可以因為通行證壞掉而 500
        return {"present": True, "active": False, "why": "token_error", "pass_id": None}


def emergency_blob_problem(blob):
    """簽發端自我複驗用：通行證 blob 的**簽章、用途、日期**都過 ⇒ None，否則原因碼（token_*）。
    不看授權金鑰綁定（那要在目標機器上、有那把授權金鑰才判得了）。"""
    why = _emergency_judge(None, blob)["why"]
    return None if why == "license_not_covered" else why


_EMERGENCY_CACHE = None   # (快取鍵, result 複本或 None)；結構與 _LICENSE_FILE_CACHE 同理（見上方①～⑤）


def _emergency_cache_key(status):
    def _stat_pair(path):
        try:
            st_result = os.stat(path)
        except OSError:
            return None
        return (st_result.st_mtime_ns, st_result.st_size)

    return (
        _stat_pair(emergency_path()),
        _stat_pair(LICENSE_PATH),
        _PUBKEY_DEV,
        _PUBKEY_PROD,
        date.today().toordinal(),
        (status or {}).get("reason"),  # _emergency_judge 的分支依賴它（見 EMERGENCY_COVERS 判斷）
    )


def emergency_pass(status):
    """這個（會被擋的）授權狀態有沒有生效中的通行證 → dict 或 None。**不丟例外；任何不確定都當沒有。**

    不確定就不放行：把「讀不懂」當成放行，是把鎖拆掉。

    T80稽核LG-M2：被擋期間**每個請求**（含公開端點、未登入）都會呼叫到這支，而且在
    exempt 判斷之前；沒有快取的話每次都是讀通行證檔＋讀授權金鑰檔＋兩次Ed25519驗章，
    被擋本來就是事故期間，不該再疊一個「每個請求多付近1ms」的放大器。快取比照
    `_LICENSE_FILE_CACHE`：鍵含兩個檔案的 stat、兩把公鑰、今天日期，外加 `status.reason`
    （判定邏輯會依它分支）。"""
    global _EMERGENCY_CACHE
    key = _emergency_cache_key(status)
    cached = _EMERGENCY_CACHE
    if cached is not None and cached[0] == key:
        return _copy_status(cached[1]) if cached[1] is not None else None

    info = emergency_status(status)
    result = info if info and info.get("active") else None
    _EMERGENCY_CACHE = (key, _copy_status(result) if result is not None else None)
    return result


def license_banner(status, emergency):
    """前端橫幅用的標頭值；沒有要提示的 → None。

    emergency ＝ 靠通行證撐著（最優先）；dev_key ＝ 驗章通過但簽發方是開發金鑰（env=dev）——
    正式機上裝了開發金鑰簽的東西，不可以悄悄放過去（開發私鑰不在受控保管下）。"""
    if emergency:
        return "emergency;until=%s" % emergency.get("until", "")
    if isinstance(status, dict) and status.get("valid") and status.get("env") == "dev":
        return "dev_key"
    return None


# ── 機器指紋 ─────────────────────────────────────────────────────────────────

# 同一個行程內算一次就好。**這個快取存的是從硬體讀出來的值**，所以換一個行程重算
# 也會得到同一個答案（見 test_07b）——不是啟動時產生的隨機值快取起來，那種做法能
# 通過「連呼叫兩次相同」，但客戶重啟服務之後金鑰就全部失效了。
_FINGERPRINT_CACHE = None  # None 或 (digest, is_stable, 算出時的time.monotonic(), 連續partial次數)
_FP_LOCK = threading.Lock()   # LG-S5：同一時間只有一條在探測硬體
_FP_ATTEMPTS = 0              # 已完成幾輪探測嘗試（成功或失敗都算）；排隊的執行緒靠它知道「我等的時候有人探完了」
_FP_LAST_ERROR = None         # 最近一輪嘗試若失敗：那個 RuntimeError；成功 ⇒ None


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


_FP_PROBE_RETRIES = 3    # T80稽核LG-M1：開機初期WMI／裝置列舉可能還沒就緒，重試幾次再定案
_FP_PROBE_DELAY_S = 1.5  # 只有「這次讀到的比上次還不完整」時才等；行程一輩子只在第一次冷啟動付這個代價
# T80稽核LG-M1b：重試完仍只拿到「一半」（uuid／mac 只有一項，不是走 _stable_machine_id 那條
# 穩定後路）時，不能跟「兩項都拿到」一樣直接快取到行程結束——那台機器可能是 WMI 持續偏慢，
# 之後終究會補齊。退避依序變長：60 秒、5 分鐘、1 小時（到最後一檔不再加長），愈久沒等到完整
# 結果，愈不急著重探；完整結果一旦拿到，照舊快取到行程結束（不會再退避）。
_FP_PARTIAL_BACKOFF_S = (60, 300, 3600)


def _probe_hardware_once():
    if sys.platform == "win32":
        return _windows_hardware()
    return _posix_hardware()


def machine_fingerprint():
    """這台機器的指紋：sha256 前 16 碼（小寫 hex）。

    來源是主機板 UUID ＋ 第一張實體網卡 MAC。**必須跨行程一致**——客戶重啟服務
    之後指紋變了，等於所有金鑰失效。

    一個硬體來源都讀不到就丟 `RuntimeError`：算不出來就什麼都不要回，不要回一個
    看起來像指紋的假值——那會讓「機器不符」這道鎖在不知不覺間失效。
    呼叫端（`verify_license`）接住它並拒絕該筆，不是放行。

    ⚠️ T80稽核LG-M1：第一次呼叫（通常是開機時）若兩項來源都讀到空的，或只讀到一項，
    **重試幾次**才把結果定案——開機初期 WMI／網卡列舉可能還沒就緒，不重試的話一個
    偶發的「這次讀一半」會被 `_FINGERPRINT_CACHE` 永遠鎖住（重啟才會重算）。硬體穩定
    的機器（絕大多數情況）每次重試都讀到同一個答案，只是多付幾次探測的時間，不會
    改變最終結果。

    ⚠️ T80稽核LG-M1b：重試完還是只有一半（既不是兩項齊全、也不是走 `_stable_machine_id`
    那條「本來就只有一個穩定來源」的後路）⇒ **不永久快取**，改用退避（`_FP_PARTIAL_BACKOFF_S`）：
    退避到期前直接回同一個殘缺值（契約仍然是「跨呼叫一致」），到期後才重新探測一次，愈探
    不到完整結果就愈慢重試。兩項齊全、或走 `_stable_machine_id` 後路的，一律快取到行程結束
    （跟原本一樣，不會退避、也不會因為之後 CPU 忙就被重新觸發）。
    """
    global _FP_ATTEMPTS, _FP_LAST_ERROR
    digest = _fingerprint_from_cache()
    if digest is not None:
        return digest

    # ⚠️ T80稽核LG-S5：single-flight。快取沒有答案（沒探過／殘缺值的退避剛到期／持續讀不到）時，
    # 以前每個並行請求都各自跑一輪探測——正式機上＝同時好幾個 PowerShell（每輪最多 3 次、每次最長 30 秒）。
    # 現在同一時間只有一條在探；**排隊的請求不再自己探**，直接拿「我排隊期間完成的那一次探測」的結果
    # （成功 ⇒ 快取裡的值；失敗 ⇒ 同樣的 RuntimeError）。沒有排隊（循序呼叫）時行為與以前完全相同：
    # 每次快取沒答案都探一次，不另外加時間窗（否則硬體恢復後要多等一個窗才認得到）。
    seen = _FP_ATTEMPTS
    with _FP_LOCK:
        if _FP_ATTEMPTS != seen:                       # 我排隊的時候，別的執行緒已經探完了一輪
            digest = _fingerprint_from_cache()
            if digest is not None:
                return digest
            if _FP_LAST_ERROR is not None:
                raise RuntimeError(str(_FP_LAST_ERROR))
        try:
            digest = _probe_fingerprint()
        except Exception as exc:                       # noqa: BLE001  任何失敗都讓排隊的人看到同一個結論
            _FP_LAST_ERROR = exc
            raise
        else:
            _FP_LAST_ERROR = None
            return digest
        finally:
            _FP_ATTEMPTS += 1


def _fingerprint_from_cache():
    """快取裡現在算數的指紋，沒有（沒探過、或殘缺值的退避到期）⇒ None。"""
    cached = _FINGERPRINT_CACHE
    if cached is None:
        return None
    digest, is_stable, cached_at, strikes = cached
    if is_stable:
        return digest
    backoff = _FP_PARTIAL_BACKOFF_S[min(strikes, len(_FP_PARTIAL_BACKOFF_S) - 1)]
    if (time.monotonic() - cached_at) <= backoff:
        return digest
    return None                                       # 退避到期：重探一次，見 _probe_fingerprint 的「沿用 strikes」


def _probe_fingerprint():
    """真的去探測硬體並更新 `_FINGERPRINT_CACHE`。**只准在持有 `_FP_LOCK` 時呼叫**（machine_fingerprint 保證）。"""
    global _FINGERPRINT_CACHE
    uuid_, mac = _probe_hardware_once()
    for _ in range(_FP_PROBE_RETRIES - 1):
        if uuid_ and mac:
            break  # 兩項都有了，不用再等
        time.sleep(_FP_PROBE_DELAY_S)
        next_uuid, next_mac = _probe_hardware_once()
        # 只採「更完整」的那次：已經拿到的那一半不會因為下一次探測讀到空值就被丟掉。
        uuid_ = uuid_ or next_uuid
        mac = mac or next_mac

    parts = []
    if uuid_:
        parts.append("uuid=" + uuid_)
    if mac:
        parts.append("mac=" + mac)
    is_stable = bool(uuid_ and mac)
    if not parts:
        fallback = _stable_machine_id()
        if fallback:
            parts.append("machineid=" + fallback)
            is_stable = True  # 只有這一個來源可用是這台機器本來的樣子，不是暫時讀一半
    if not parts:
        raise RuntimeError(
            "無法取得任何硬體識別（主機板 UUID／實體網卡 MAC／機器 ID 都讀不到），"
            "算不出機器指紋"
        )

    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]
    now = time.monotonic()
    if is_stable:
        _FINGERPRINT_CACHE = (digest, True, now, 0)
    else:
        prev = _FINGERPRINT_CACHE
        strikes = prev[3] + 1 if prev is not None else 0
        _FINGERPRINT_CACHE = (digest, False, now, strikes)
    return digest


# ── 模組授權（CORE-SPEC §9c ②，2026-09-25 裁示 (b)）──────────────────────────
#
# 授權的單位是「賣的東西」＝模組：金鑰的 `modules` 清單寫模組的 `license_key`
# （module.json；沒寫 ⇒ 資料夾名），`"*"` ＝ 全開。不用權限 key——那是模組內部更細的粒度。
# 開發模式照既有規則：`LICENSE_GATE_ENABLED` 為 False ⇒ 完全不介入（連 verify_license 都不呼叫）。

MODULE_LICENSE_NOT_CHECKED = "授權檢查未啟用"


def module_licensed(manifest, status, gate_enabled):
    """純函式：回 `(ok, reason)`。reason 是給人看的中文；ok 時 reason 可能是「授權檢查未啟用」。"""
    if not gate_enabled:
        return True, MODULE_LICENSE_NOT_CHECKED
    if license_blocks_request(status):
        return False, "未授權：" + license_block_message(status)
    key = (manifest or {}).get("license_key") or (manifest or {}).get("key") or ""
    mods = status.get("modules")
    if mods is None:
        mods = []
    # 只接受 list[str]：字串會讓 `key in mods` 變成子字串比對（'tender_radar' in 'xtender_radarx'）。
    # 金鑰有簽章、簽發端產的是 list，但驗證端不依賴簽發端永遠正確（AUDIT-X-9c B-2）。
    if not isinstance(mods, list) or not all(isinstance(m, str) for m in mods):
        return False, "未授權：授權金鑰的模組清單格式不正確（應為清單，實際是 %s）" % type(mods).__name__
    if "*" in mods or key in mods:
        return True, ""
    return False, "未授權：授權金鑰未包含此模組（%s）" % key


def module_license_check(manifest):
    """載入器用（main.py 注入 core.loader.load_all）。每次呼叫當下讀開關與金鑰。"""
    gate = LICENSE_GATE_ENABLED
    if not gate:
        return module_licensed(manifest, {}, False)
    status = verify_license()
    if license_blocks_request(status):
        # 靠緊急放行通行證撐著時，重啟也不能讓模組全部不載入（那等於「放行」只撐到下次重啟）。
        # 模組清單取自驗章通過的那把授權金鑰（machine_mismatch／expired 時 status.modules 仍是可信的）。
        if emergency_pass(status):
            status = dict(status, valid=True, reason="ok")
    return module_licensed(manifest, status, gate)
