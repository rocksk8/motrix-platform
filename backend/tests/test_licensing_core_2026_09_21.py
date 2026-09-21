"""2026-09-21 · 細線 1 第 1、2 步：授權金鑰核心（驗收測試）

對應 `docs/windows/STATE.md` §3 第 1 輪開發單的 **11 條**驗收條件（1～8、8b、9～11）。
**這份由視窗 C 寫，先寫成紅的。產品碼（`helpers/licensing.py`／`routers/licensing.py`）是 B 的。**

> 模組叫 **`licensing`** 不是 `license`（`license` 會遮蔽 Python 內建名稱，B 提出、A 裁決）。
> 但**檔名 `backend/license.key` 與端點路徑 `/api/license/status` 不改** —— 那是資料與對外介面，不是模組。

---

## B 需要提供的名字（這份測試釘住的契約）

`backend/helpers/licensing.py`

| 名字 | 形態 | 說明 |
|------|------|------|
| `_PUBKEY_DEV` | `bytes` | 開發用 Ed25519 公鑰（PEM）。**測試會 monkeypatch 它**，所以驗證時才載入，不可以在 import 時就把它解析成 key 物件存起來 |
| `_PUBKEY_PROD` | `bytes` | 正式公鑰。**本輪＝`b""`**（還沒產生），驗證時要略過它、不可以丟例外 |
| `LICENSE_PATH` | `str` | 金鑰檔路徑，預設 `backend/license.key`。**每次呼叫才讀**，不可以在啟動時讀完就快取 |
| `machine_fingerprint()` | `-> str` | 16 碼小寫 hex（sha256 前 16 碼） |
| `sign_license(payload, private_key_pem)` | `-> str` | 回傳 blob |
| `verify_license(blob=None)` | `-> LicenseStatus` | **`blob` 省略或 `None` → 改讀 `LICENSE_PATH`**（STATE 寫的是 `verify_license(blob: str)`，但條件 5「檔案不存在→missing」要有人負責讀檔；C 把它放在這裡，理由見 `docs/windows/C.md`〈給彙整〉） |

`LicenseStatus` 是 dict 或物件都可以 —— 本檔用 `_f()` 兩種都讀得到。
要有 `valid` / `reason` / **`env`** / `customer` / `modules` / `expires` / `days_left` **七個**欄位。

`env` 的語意（STATE §5〈本輪最終契約〉）：
- 用 `_PUBKEY_DEV` 驗過 → `"dev"`；用 `_PUBKEY_PROD` 驗過 → `"prod"`
- **簽章驗過但過期／機器不符 → `env` 仍然是 `"dev"`／`"prod"`**（知道是哪一把簽的，日後打包關卡要用）
- 兩把都驗不過、或根本沒走到驗簽章那一步（`missing`／`malformed`）→ `env` 為 `None`

檢查順序（B 照這個寫，測試才會剛好落在預期的 reason 上）：
`malformed → missing → bad_signature → machine_mismatch → expired`。

`backend/routers/licensing.py`：`GET /api/license/status`。

---

## 兩個會讓這份測試「假綠」的陷阱（已經處理掉，改這份時不要拆掉）

1. **`/api/license/status` 未登入回 401 這件事現在就已經成立了** ——
   `main.py::auth_middleware` 對**任何** `/api/` 開頭的路徑（包含根本不存在的路徑）
   都先回 401，route 有沒有註冊它不管。所以光驗 401 驗到的是 middleware，不是新端點。
   `test_08a` 因此同時檢查這條 route 真的掛上去了。

2. **第 2 題（竄改）不可以驗「簽章字串不一樣」** —— 那驗的是自己算的值。
   這裡一律驗 `verify_license()` 的 `reason`，而且**挑 `customer`／`tax_id` 這種
   沒有第二道檢查會擋的欄位**：若挑 `expires` 改成過去，就算簽章根本沒驗，
   也會因為「過期」而回 `expired`，看起來像有擋住，其實是別的檢查在擋。
   （`expires` 往**未來**延長那一格是刻意留的：那是真實的攻擊手法，
   而且簽章沒驗時它會回 `ok`，紅得出來。）
"""
import base64
import datetime as _dt
import json
import subprocess
import sys
from pathlib import Path

import pytest


# ── 產品碼還不存在時，給每一題一個讀得懂的紅 ────────────────────────────────

try:
    from helpers import licensing as lic
except Exception as exc:  # noqa: BLE001 — 什麼原因都要變成下面那段說明
    lic = None
    _IMPORT_ERROR = repr(exc)

# `_PUBKEY_PROD` 的**出貨預設值**，在 import 當下拍下來。
# test_10 的絆線一定要讀這個：`keypair` fixture 會把它 monkeypatch 成 b""，
# 讀 patch 之後的值等於驗自己設的值——就是典型的假綠燈。
_PUBKEY_PROD_AT_IMPORT = getattr(lic, "_PUBKEY_PROD", None)


def _lic():
    """回傳 helpers.licensing；還沒寫出來就用固定訊息讓每一題各自紅一次。"""
    if lic is None:
        raise AssertionError(
            "backend/helpers/licensing.py 還不存在（或 import 失敗）："
            f"{_IMPORT_ERROR}。需要的名字見本檔開頭的契約表。"
        )
    return lic


def _need(name):
    """取模組屬性，缺了就講清楚缺哪一個。"""
    m = _lic()
    if not hasattr(m, name):
        raise AssertionError(f"helpers/licensing.py 缺少 `{name}`，見本檔開頭的契約表。")
    return getattr(m, name)


# ── LicenseStatus 存取（dict 或物件都支援）──────────────────────────────────

def _f(status, name):
    """讀 LicenseStatus 的欄位。B 用 dict 或 dataclass 都可以。"""
    if isinstance(status, dict):
        if name not in status:
            raise AssertionError(
                f"LicenseStatus 缺欄位 `{name}`；實際拿到 {sorted(status)}"
            )
        return status[name]
    if not hasattr(status, name):
        raise AssertionError(
            f"LicenseStatus 缺欄位 `{name}`；實際拿到 {type(status).__name__}"
        )
    return getattr(status, name)


# ── blob 格式（STATE §3 指定：JSON 內含 sig，整包再 base64）─────────────────

def _decode_blob(blob):
    """blob -> payload dict。標準 base64 與 urlsafe 都收。"""
    raw = blob.encode("ascii") if isinstance(blob, str) else blob
    for decoder in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            return json.loads(decoder(raw))
        except Exception:  # noqa: BLE001, PERF203
            continue
    raise AssertionError(
        "sign_license() 產出的 blob 不是「base64(JSON)」。"
        "STATE.md §3 指定金鑰內容是 JSON（sig 在裡面），整包再 base64。"
        f"實際開頭 40 字：{blob[:40]!r}"
    )


def _encode_blob(payload):
    """payload dict -> blob。刻意用預設 json.dumps：

    簽章欄位在 JSON 裡面，驗證端**一定**得自己把 payload 重新正規化序列化才算得出
    簽章原文，所以這裡怎麼排版都不影響驗證結果 —— 除非 B 把簽章算在原始位元組上，
    那種寫法本來就跟 STATE 指定的格式不相容。
    """
    return base64.b64encode(
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")


# ── fixtures ────────────────────────────────────────────────────────────────

TODAY = _dt.date(2026, 9, 21)
VALID_DAYS = 400  # 挑一個不是 365 的數字：365 剛好等於「一年」，算錯也看不出來


@pytest.fixture()
def keypair(monkeypatch):
    """自己產一把臨時 Ed25519 金鑰，並把公鑰換進 helpers.licensing。

    **不可以去讀 `backend/tools/_license_private_key.pem`** —— 那把私鑰在 .gitignore
    裡，換一台機器就不存在，測試會變成「在某些機器上才跑得動」。
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    m = _lic()
    priv = ed25519.Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    _need("_PUBKEY_DEV")
    _need("_PUBKEY_PROD")
    monkeypatch.setattr(m, "_PUBKEY_DEV", pub_pem)
    # 正式公鑰在測試裡一律清空：本輪它本來就是 b""，而且留著真的正式公鑰的話，
    # 「別人的私鑰簽的」那幾題會分不出擋下來的是哪一把。
    monkeypatch.setattr(m, "_PUBKEY_PROD", b"")
    return priv_pem, pub_pem


@pytest.fixture()
def make_blob(keypair):
    """簽一把金鑰出來。預設：本機指紋、400 天後到期、開兩個模組。"""
    priv_pem, _ = keypair
    sign_license = _need("sign_license")
    machine_fingerprint = _need("machine_fingerprint")

    def _make(**overrides):
        payload = {
            "customer": "第二家公司股份有限公司",
            "tax_id": "87654321",
            "machine": machine_fingerprint(),
            "modules": ["quotation", "case_manage"],
            "issued": TODAY.isoformat(),
            "expires": (TODAY + _dt.timedelta(days=VALID_DAYS)).isoformat(),
        }
        payload.update(overrides)
        return sign_license(payload, priv_pem)

    return _make


@pytest.fixture()
def no_license_file(monkeypatch, tmp_path):
    """把 LICENSE_PATH 指到一個保證不存在的路徑。

    開發過程中 B 一定會在 `backend/license.key` 放一把真的金鑰來手動試 —— 不隔離的話
    「檔案不存在」這一題會在 B 的機器上莫名其妙變綠。
    """
    m = _lic()
    _need("LICENSE_PATH")
    path = tmp_path / "no_such_dir" / "license.key"
    monkeypatch.setattr(m, "LICENSE_PATH", str(path))
    return path


# ── 條件 1：有效金鑰 ────────────────────────────────────────────────────────

def test_01_valid_license_verifies(make_blob):
    """STATE §3 驗收 1：簽一把有效金鑰 → valid=True, reason='ok'。"""
    verify_license = _need("verify_license")
    st = verify_license(make_blob())

    assert _f(st, "reason") == "ok"
    assert _f(st, "valid") is True
    assert _f(st, "customer") == "第二家公司股份有限公司"
    assert list(_f(st, "modules")) == ["quotation", "case_manage"]
    assert _f(st, "expires") == (TODAY + _dt.timedelta(days=VALID_DAYS)).isoformat()

    # days_left 要是「真的算出來的天數」，不是 True/1/0 這種能矇混過去的值。
    days_left = _f(st, "days_left")
    assert isinstance(days_left, int) and not isinstance(days_left, bool)
    expected = (TODAY + _dt.timedelta(days=VALID_DAYS) - _dt.date.today()).days
    assert abs(days_left - expected) <= 1, (
        f"days_left={days_left}，以今天算應該是 {expected} 左右"
    )


# ── 條件 2：竄改 payload → bad_signature（本檔重點）──────────────────────────

@pytest.mark.parametrize(
    "field, value",
    [
        # customer／tax_id：沒有第二道檢查會擋，所以擋下來的只可能是簽章本身。
        ("customer", "冒名的公司"),
        ("tax_id", "00000000"),
        # 真實攻擊手法：把模組清單改成全開、把到期日往後延。
        ("modules", ["*"]),
        ("expires", "2099-12-31"),
    ],
)
def test_02_tampered_payload_is_bad_signature(make_blob, field, value):
    """STATE §3 驗收 2：改動 payload 任何一個位元組 → reason == 'bad_signature'。

    ⚠️ 驗的是 `verify_license()` 的回傳值，不是「簽章字串有沒有變」——
    後者是自己算自己的，驗不到產品碼做了什麼。
    """
    verify_license = _need("verify_license")
    blob = make_blob()

    payload = _decode_blob(blob)
    assert payload.get(field) != value, "竄改值跟原值一樣，這一題等於沒改到東西"
    payload[field] = value          # 只改內容，sig 原封不動
    tampered = _encode_blob(payload)

    st = verify_license(tampered)
    assert _f(st, "reason") == "bad_signature", (
        f"竄改 `{field}` 之後 reason={_f(st, 'reason')!r}，應該是 'bad_signature'"
    )
    assert _f(st, "valid") is False
    assert _f(st, "env") is None


def test_02b_tampered_signature_is_bad_signature(make_blob):
    """補一格：sig 本身被換掉（改動的是簽章欄位，不是 payload 欄位）。"""
    verify_license = _need("verify_license")
    payload = _decode_blob(make_blob())
    assert "sig" in payload, (
        f"blob 的 JSON 裡沒有 `sig` 欄位（STATE §3 指定它在裡面）；實際欄位 {sorted(payload)}"
    )
    sig = payload["sig"]
    # 換掉第一個 base64 字元，長度不變 —— 讓它壞在「驗不過」而不是「解不開」。
    payload["sig"] = ("B" if sig[0] == "A" else "A") + sig[1:]

    st = verify_license(_encode_blob(payload))
    assert _f(st, "reason") == "bad_signature"
    assert _f(st, "valid") is False
    assert _f(st, "env") is None


def test_02c_license_signed_by_another_key_is_bad_signature(make_blob):
    """補一格：整把金鑰是別人（拿到原始碼的人）用自己的私鑰簽的。

    這一題跟 02／02b 不同：blob 本身完全自洽、簽章跟內容對得起來，
    只有「不是我們那把私鑰簽的」這一件事不對。驗的是公鑰真的被拿來用了。
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    verify_license = _need("verify_license")
    sign_license = _need("sign_license")
    machine_fingerprint = _need("machine_fingerprint")

    rogue = ed25519.Ed25519PrivateKey.generate()
    rogue_pem = rogue.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    blob = sign_license(
        {
            "customer": "自己簽的公司",
            "tax_id": "11111111",
            "machine": machine_fingerprint(),
            "modules": ["*"],
            "issued": TODAY.isoformat(),
            "expires": "2099-12-31",
        },
        rogue_pem,
    )

    st = verify_license(blob)
    assert _f(st, "reason") == "bad_signature"
    assert _f(st, "valid") is False
    assert _f(st, "env") is None


# ── 條件 3：機器指紋不符 ────────────────────────────────────────────────────

def test_03_other_machine_is_machine_mismatch(make_blob):
    """STATE §3 驗收 3：machine 換成別的指紋 → reason == 'machine_mismatch'。

    這把金鑰是**正常簽出來的**（簽章有效、沒過期），唯一不對的就是機器 ——
    否則會分不出擋住它的是哪一道檢查。
    """
    verify_license = _need("verify_license")
    machine_fingerprint = _need("machine_fingerprint")

    other = "0123456789abcdef"
    assert other != machine_fingerprint(), "假指紋剛好等於本機指紋，換一個"

    st = verify_license(make_blob(machine=other))
    assert _f(st, "reason") == "machine_mismatch", (
        f"換機器之後 reason={_f(st, 'reason')!r}，應該是 'machine_mismatch'"
    )
    assert _f(st, "valid") is False
    assert _f(st, "env") == "dev", (
        "簽章驗過了（擋下來的是別的檢查），所以 env 要說得出是哪一把簽的"
    )


# ── 條件 4：已過期 ──────────────────────────────────────────────────────────

def test_04_expired_license_reports_expired(keypair):
    """STATE §3 驗收 4：expires 設成昨天 → reason == 'expired' 且 days_left 為負。

    不用 make_blob 的預設值 —— 這一題的 expires 必須相對於**跑測試的當天**，
    寫死 2026-09-20 的話明年跑這支測試會變成另一個意思。
    """
    verify_license = _need("verify_license")
    sign_license = _need("sign_license")
    machine_fingerprint = _need("machine_fingerprint")
    priv_pem, _ = keypair

    yesterday = _dt.date.today() - _dt.timedelta(days=1)
    blob = sign_license(
        {
            "customer": "過期公司",
            "tax_id": "22222222",
            "machine": machine_fingerprint(),
            "modules": ["quotation"],
            "issued": (yesterday - _dt.timedelta(days=365)).isoformat(),
            "expires": yesterday.isoformat(),
        },
        priv_pem,
    )

    st = verify_license(blob)
    assert _f(st, "reason") == "expired"
    assert _f(st, "valid") is False
    assert _f(st, "env") == "dev", (
        "簽章驗過了（擋下來的是別的檢查），所以 env 要說得出是哪一把簽的"
    )

    days_left = _f(st, "days_left")
    assert isinstance(days_left, int) and not isinstance(days_left, bool)
    assert days_left < 0, f"昨天到期，days_left 應該是負數，實際 {days_left}"


# ── 條件 5：檔案不存在 ──────────────────────────────────────────────────────

def test_05_missing_license_file_is_missing(no_license_file):
    """STATE §3 驗收 5：檔案不存在 → reason == 'missing'，**不可以丟例外**。

    「服務要起得來」是這一題的全部意義：丟例外的話客戶第一次裝就開不了機，
    而且連授權頁都進不去 —— 那是第 3 步「擋住但起得來」的前提。
    """
    verify_license = _need("verify_license")
    assert not no_license_file.exists()

    try:
        st = verify_license()          # 不給 blob → 讀 LICENSE_PATH
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(
            f"檔案不存在時 verify_license() 丟了例外：{exc!r}。"
            "必須回 reason='missing'，服務要起得來。"
        ) from exc

    assert _f(st, "reason") == "missing"
    assert _f(st, "valid") is False
    assert _f(st, "env") is None


def test_05b_missing_blob_is_missing(no_license_file):
    """明確傳 None／空字串（沒有金鑰）也是 missing，同樣不可以丟例外。"""
    verify_license = _need("verify_license")
    for blob in (None, "", "   "):
        try:
            st = verify_license(blob)
        except Exception as exc:  # noqa: BLE001
            raise AssertionError(
                f"verify_license({blob!r}) 丟了例外：{exc!r}，應該回 reason='missing'"
            ) from exc
        assert _f(st, "reason") == "missing", f"blob={blob!r} 回了 {_f(st, 'reason')!r}"
        assert _f(st, "valid") is False
        assert _f(st, "env") is None


# ── 條件 6：亂碼／截斷 ──────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "label, blob",
    [
        ("純亂碼", "這不是金鑰"),
        ("非 base64", "!!!!not-base64!!!!"),
        ("base64 但不是 JSON", base64.b64encode(b"hello world").decode()),
        ("base64 的 JSON 但不是物件", base64.b64encode(b"[1, 2, 3]").decode()),
        ("JSON 物件但沒有任何欄位", base64.b64encode(b"{}").decode()),
        ("有 sig 但沒有其他欄位", base64.b64encode(b'{"sig": "AAAA"}').decode()),
    ],
)
def test_06_malformed_blob_is_malformed(label, blob):
    """STATE §3 驗收 6：亂碼／截斷的 blob → reason == 'malformed'，**不可以丟例外**。"""
    verify_license = _need("verify_license")
    try:
        st = verify_license(blob)
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(
            f"[{label}] verify_license() 丟了例外：{exc!r}，應該回 reason='malformed'"
        ) from exc
    assert _f(st, "reason") == "malformed", f"[{label}] 回了 {_f(st, 'reason')!r}"
    assert _f(st, "valid") is False
    assert _f(st, "env") is None


def test_06b_truncated_valid_blob_is_malformed(make_blob):
    """截斷一把**原本有效**的金鑰 —— 亂碼字串可能碰巧走到別的分支，
    從有效的那一把砍一半比較接近真實的「檔案傳壞了」。"""
    verify_license = _need("verify_license")
    blob = make_blob()
    truncated = blob[: len(blob) // 2]

    try:
        st = verify_license(truncated)
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(
            f"截斷的 blob 讓 verify_license() 丟了例外：{exc!r}，應該回 reason='malformed'"
        ) from exc
    assert _f(st, "reason") == "malformed"
    assert _f(st, "valid") is False
    assert _f(st, "env") is None


# ── 條件 7：機器指紋穩定 ────────────────────────────────────────────────────

def test_07_machine_fingerprint_is_stable_in_process():
    """STATE §3 驗收 7：同一台機器連呼叫兩次結果相同。"""
    machine_fingerprint = _need("machine_fingerprint")
    first = machine_fingerprint()
    second = machine_fingerprint()

    assert first == second
    # 格式也要釘住：STATE §3 指定是「sha256 前 16 碼」。
    assert isinstance(first, str)
    assert len(first) == 16, f"指紋長度應為 16，實際 {len(first)}：{first!r}"
    assert all(c in "0123456789abcdef" for c in first), f"指紋不是小寫 hex：{first!r}"


def test_07b_machine_fingerprint_is_stable_across_processes():
    """條件 7 的補強：換一個**全新行程**算出來的指紋要一樣。

    為什麼要多這一題：「連呼叫兩次相同」用一個 module-level 的快取就能滿足，
    而拿隨機值快取起來的實作會完整通過那一題 —— 但客戶重啟服務之後金鑰就失效了。
    這一題是唯一驗得到「指紋真的來自硬體」的方式。
    """
    m = _lic()
    machine_fingerprint = _need("machine_fingerprint")
    in_process = machine_fingerprint()

    backend_dir = Path(m.__file__).resolve().parent.parent
    proc = subprocess.run(
        [sys.executable, "-c",
         "from helpers.licensing import machine_fingerprint; print(machine_fingerprint())"],
        cwd=str(backend_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",      # 不給 encoding 的話中文輸出會在讀取執行緒解碼失敗，
        errors="replace",      # 例外不回主流程、returncode 仍是 0、stdout 變 None
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"子行程算指紋失敗（returncode={proc.returncode}）：\n{proc.stderr}"
    )
    assert proc.stdout.strip() == in_process, (
        f"換一個行程指紋就變了：行程內 {in_process!r}，子行程 {proc.stdout.strip()!r}。"
        "指紋必須來自硬體，不能是啟動時算一次的隨機值。"
    )


# ── 條件 8：GET /api/license/status ─────────────────────────────────────────

_STATUS_PATH = "/api/license/status"


def _route_exists(app, path):
    return any(getattr(r, "path", None) == path for r in app.routes)


def _login_token(client, make_user, username="tester"):
    u, pw = make_user(username=username)
    r = client.post("/api/auth/login", json={"username": u, "password": pw})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_08a_status_endpoint_requires_login(client):
    """STATE §3 驗收 8（前半）：未登入回 401。

    ⚠️ 光驗 401 是**假綠燈**：`main.py::auth_middleware` 對任何 `/api/` 開頭的路徑
    都先回 401，連根本沒註冊的路徑也一樣。所以這裡先確認 route 真的掛上去了。
    """
    assert _route_exists(client.app, _STATUS_PATH), (
        f"{_STATUS_PATH} 沒有註冊成 route。"
        "（注意：不註冊它也會回 401，因為 auth_middleware 擋在所有 /api/ 前面，"
        "所以只驗 401 驗不到東西。）"
    )
    r = client.get(_STATUS_PATH)
    assert r.status_code == 401, r.text


def test_08_status_returns_customer_and_days_left(client, make_user, no_license_file):
    """STATE §3 驗收 8（後半）：登入後回得到 customer 與 days_left。

    這裡刻意是**沒有安裝金鑰**的狀態（`no_license_file`）：六個欄位都要在
    （前端橫幅／授權頁靠它們，缺一個就變 undefined），而且**不可以 500**——
    沒金鑰的機器就是客戶第一次開機的樣子。

    `env` 那個鍵由 `test_11` 驗；狀態碼與 `customer` 為 null 由 `test_08b` 驗。
    """
    token = _login_token(client, make_user)
    r = client.get(_STATUS_PATH, headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()

    for key in ("valid", "reason", "customer", "modules", "expires", "days_left"):
        assert key in body, f"回應缺欄位 `{key}`；實際拿到 {sorted(body)}"
    assert body["valid"] is False
    assert body["reason"] == "missing"


def test_08c_status_endpoint_reports_installed_license(
    client, make_user, monkeypatch, tmp_path, make_blob
):
    """裝一把有效金鑰 → 端點回得到那把金鑰的 customer 與正數 days_left。

    ⚠️ 這一題要求 `verify_license()` **在每次呼叫時才讀 `LICENSE_PATH`**。
    若 B 把結果在啟動時就快取起來，這一題會紅 —— 那不是測試寫錯，是第 6 步
    「到期前提醒」本來就需要能重新判定（見 `docs/windows/C.md`〈給彙整〉）。
    """
    m = _lic()
    key_file = tmp_path / "license.key"
    key_file.write_text(make_blob(), encoding="utf-8")
    monkeypatch.setattr(m, "LICENSE_PATH", str(key_file))

    token = _login_token(client, make_user)
    r = client.get(_STATUS_PATH, headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["valid"] is True
    assert body["reason"] == "ok"
    assert body["customer"] == "第二家公司股份有限公司"
    assert body["days_left"] > 0
    assert list(body["modules"]) == ["quotation", "case_manage"]


# ── 條件 8b：沒有金鑰檔時 status 端點的行為 ─────────────────────────────────

def test_08b_status_without_license_is_200_and_null_customer(
    client, make_user, no_license_file
):
    """STATE §3 驗收 8b：沒有金鑰檔 → `200` ＋ `{valid:false, reason:"missing", customer:null}`。

    **不是 402 也不是 404。** 402 是第 3 步用來擋業務 API 的；status 端點本身必須
    永遠讀得到，否則現場沒授權時連「為什麼沒授權」都查不出來。

    `customer` 要是 **null 不是空字串**：前端要靠 `customer == null` 分辨
    「這台機器還沒裝金鑰」與「裝了但客戶名稱是空的」，空字串會把兩者混在一起。
    """
    token = _login_token(client, make_user)
    r = client.get(_STATUS_PATH, headers=_auth(token))

    assert r.status_code == 200, (
        f"沒有金鑰時 status 端點回了 {r.status_code}，應該是 200。"
        "（402 是第 3 步擋業務 API 用的，status 端點本身要永遠讀得到。）"
    )
    body = r.json()
    assert body["valid"] is False
    assert body["reason"] == "missing"
    assert body["customer"] is None, (
        f"customer 應該是 null，實際 {body['customer']!r}"
        "（空字串會讓前端分不出「沒裝金鑰」與「裝了但名稱是空的」）"
    )


# ── 條件 9：env 要說得出是哪一把公鑰驗過的 ──────────────────────────────────

def test_09_dev_signed_license_reports_env_dev(make_blob):
    """STATE §3 驗收 9：開發私鑰簽的金鑰 → `valid=True` 且 `env == "dev"`。

    `env` 存在的理由（STATE §4 第 1 項）：正式私鑰還沒決定保管方式，
    `_PUBKEY_PROD` 一天是空的就一天不能真的出貨。有了 `env`，
    「這台機器上裝的是開發金鑰」就變成**結構上偵測得到**的事，不靠人記得。
    """
    verify_license = _need("verify_license")
    st = verify_license(make_blob())

    assert _f(st, "valid") is True
    assert _f(st, "reason") == "ok"
    assert _f(st, "env") == "dev", (
        f"env={_f(st, 'env')!r}，用 _PUBKEY_DEV 驗過的金鑰應該回 'dev'"
    )


# ── 條件 10：_PUBKEY_PROD 是空的（本輪的真實狀態）───────────────────────────

def test_10_empty_prod_pubkey_does_not_raise(make_blob, keypair):
    """STATE §3 驗收 10：`_PUBKEY_PROD` 是空字串時，驗證要正常跑完、不丟例外。

    **這不是邊界情況，是本輪的真實狀態** —— 正式公鑰還沒產生。
    最容易踩的寫法是無條件 `load_pem_public_key(_PUBKEY_PROD)`：
    餵 `b""` 進去會丟 `ValueError`，於是**每一次驗證都炸**，服務起不來。
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    m = _lic()
    verify_license = _need("verify_license")
    sign_license = _need("sign_license")
    machine_fingerprint = _need("machine_fingerprint")

    # `keypair` 已經把 _PUBKEY_PROD 設成 b""，確認這一題真的跑在那個前提上。
    assert m._PUBKEY_PROD == b""

    rogue = ed25519.Ed25519PrivateKey.generate()
    rogue_pem = rogue.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    rogue_blob = sign_license(
        {
            "customer": "別人簽的",
            "tax_id": "33333333",
            "machine": machine_fingerprint(),
            "modules": ["*"],
            "issued": TODAY.isoformat(),
            "expires": "2099-12-31",
        },
        rogue_pem,
    )

    # 三條路都要跑得完：驗得過的、驗不過的、根本解不開的。
    for label, blob, expected in (
        ("dev 簽的有效金鑰", make_blob(), "ok"),
        ("別人私鑰簽的", rogue_blob, "bad_signature"),
        ("亂碼", "!!!!garbage!!!!", "malformed"),
    ):
        try:
            st = verify_license(blob)
        except Exception as exc:  # noqa: BLE001
            raise AssertionError(
                f"[{label}] _PUBKEY_PROD 是 b'' 時 verify_license() 丟了例外：{exc!r}。"
                "空的正式公鑰要略過，不可以拿去 load_pem_public_key()。"
            ) from exc
        assert _f(st, "reason") == expected, f"[{label}] 回了 {_f(st, 'reason')!r}"

    # 絆線：正式公鑰一旦產生，這一行會紅。**那是刻意的** ——
    # 紅了表示要回 STATE §4 第 1 項，把私鑰保管、備援、外洩處置流程一起定案，
    # 而不是有人默默塞一把公鑰進去就當作可以出貨了。
    assert _PUBKEY_PROD_AT_IMPORT == b"", (
        f"_PUBKEY_PROD 的出貨預設值已經不是 b'' 了（現在是 {_PUBKEY_PROD_AT_IMPORT!r}）。"
        "這一題紅了不是測試壞了——請回 STATE §4 第 1 項把私鑰保管流程定案，再改這一行。"
    )


# ── 條件 11：status 回傳要有 env 這個鍵 ─────────────────────────────────────

def test_11_status_response_includes_env_key(
    client, make_user, monkeypatch, tmp_path, make_blob
):
    """STATE §3 驗收 11：`GET /api/license/status` 的回傳裡有 `env` 這個鍵。

    **兩種狀態都要有**，不是只有裝了金鑰的時候：
      - 沒金鑰 → `env` 是 `None`（但鍵要在，否則前端拿到 undefined）
      - 裝了開發金鑰 → `env == "dev"`

    順帶驗到「每次呼叫才讀 `LICENSE_PATH`」：同一個行程裡換掉金鑰檔，
    第二次請求就要看得到新的結果。
    """
    m = _lic()
    token = _login_token(client, make_user)

    # ① 沒有金鑰檔
    monkeypatch.setattr(m, "LICENSE_PATH", str(tmp_path / "no_such_dir" / "license.key"))
    body = client.get(_STATUS_PATH, headers=_auth(token)).json()
    assert "env" in body, (
        f"沒金鑰時回應缺 `env` 鍵；實際拿到 {sorted(body)}。"
        "沒有它，日後打包關卡就沒有東西可以檢查。"
    )
    assert body["env"] is None, f"沒金鑰時 env 應該是 null，實際 {body['env']!r}"

    # ② 換上一把開發金鑰——同一個行程、不重啟服務
    key_file = tmp_path / "license.key"
    key_file.write_text(make_blob(), encoding="utf-8")
    monkeypatch.setattr(m, "LICENSE_PATH", str(key_file))

    body = client.get(_STATUS_PATH, headers=_auth(token)).json()
    assert "env" in body, f"裝了金鑰後回應缺 `env` 鍵；實際拿到 {sorted(body)}"
    assert body["env"] == "dev", (
        f"裝了開發金鑰，env 應該是 'dev'，實際 {body['env']!r}"
        "（若這裡還是 null，多半是 verify_license() 把結果快取了，沒有重讀 LICENSE_PATH）"
    )
