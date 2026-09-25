"""2026-09-11：HTTPS 憑證到期告警（`routers/daily_tasks.py::_check_cert_expiry`）。

在此之前憑證到期完全沒有任何監控——目前服務中的 mkcert 自簽憑證 2028-12-10
到期（星期日），到期後第一個上班日全公司 Passkey 會一起失效。

這裡釘住五件事：
  1. 沒有憑證檔（純 HTTP 模式）時完全不動作，也不能拋例外
  2. **門檻依憑證總效期自動切換** ← 這一題是本檔的重點，理由見下
  3. 同一個門檻只寄一次，跨到更低的門檻才會再寄
  4. 已過期時每 7 天重寄
  5. guard key 會被收斂到最多 1 列

第 2 點為什麼重要：Let's Encrypt 憑證 90 天到期，而 Posh-ACME 在「剩 30 天」
時就會自動續期。若沿用給 mkcert（822 天）用的 60 天門檻，每一張 LE 憑證都會
在一切正常的情況下誤報一次——大約每 90 天一次。狼來了的告警等於沒有告警，
而這個告警存在的唯一目的就是在好幾百天後的某一天真的叫得動人。
"""
import datetime as _dt
import time

import pytest

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


# ── 造憑證 ────────────────────────────────────────────────────────────────────

def _write_cert(path, days_left: int, total_days: int, cn: str = "Test Issuer"):
    """產一張自簽憑證，精確控制「還剩幾天」與「總效期多長」。

    總效期是本功能用來判斷「這是手動簽的還是 ACME 自動續期的」的唯一依據，
    所以兩個維度都必須能獨立控制，不能只調到期日。
    """
    key = ec.generate_private_key(ec.SECP256R1())
    now = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
    not_after = now + _dt.timedelta(days=days_left)
    not_before = not_after - _dt.timedelta(days=total_days)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .sign(key, hashes.SHA256())
    )
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return path


MKCERT_DAYS = 822   # mkcert 實際簽出來的效期（2 年 3 個月）
LE_DAYS     = 90    # Let's Encrypt 的固定效期


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def sent(monkeypatch):
    """攔截寄信，只記呼叫參數——這裡測的是排程判斷邏輯，不是郵件內容。"""
    calls = []
    import helpers.system_checks as dt  # 2026-09-26 自 routers/daily_tasks 搬出（M12 搬遷前置）
    monkeypatch.setattr(dt, "notify_cert_expiry", lambda *a, **kw: calls.append(a))
    return calls


@pytest.fixture()
def cert_at(tmp_path, monkeypatch):
    """回傳一個「把憑證換成指定條件」的函式，並把 _CERT_PATH 指過去。"""
    import helpers.system_checks as dt  # 2026-09-26 自 routers/daily_tasks 搬出（M12 搬遷前置）
    path = tmp_path / "cert.pem"

    def _set(days_left, total_days=MKCERT_DAYS, cn="Test Issuer"):
        _write_cert(path, days_left, total_days, cn)
        monkeypatch.setattr(dt, "_CERT_PATH", str(path))
        return path

    monkeypatch.setattr(dt, "_CERT_PATH", str(path))
    return _set


@pytest.fixture()
def fake_cert(monkeypatch):
    """直接控制 `_read_serving_cert()` 的回傳值。

    ⚠️ 為什麼多次執行的 guard 測試不能靠「重簽一張憑證」來模擬時間經過：
    重簽會換掉 fingerprint，而 fingerprint 正是 guard key 的一部分——測試會
    因為「換了憑證」而通過，看起來在驗 7 天分桶，其實一點都沒驗到。本專案
    剛在 `4ffe190` 吃過同一種虧（斷言太寬鬆，真正的 bug 還在測試就先變綠）。

    真正要能分開的是兩件事：**同一張憑證變舊**（fingerprint 不變）vs
    **換了一張新憑證**（fingerprint 改變）。所以 fingerprint 在這裡是參數。
    """
    state = {}
    import helpers.system_checks as dt  # 2026-09-26 自 routers/daily_tasks 搬出（M12 搬遷前置）

    monkeypatch.setattr(dt, "_read_serving_cert",
                        lambda path=None: (dict(state) if state else None))

    def _set(days_left, total_days=MKCERT_DAYS, fingerprint="aaaabbbbccccdddd"):
        state.clear()
        state.update({
            "not_after":   (_dt.date.today() + _dt.timedelta(days=days_left)).isoformat(),
            "days_left":   days_left,
            "total_days":  total_days,
            "issuer_cn":   "Test Issuer",
            "fingerprint": fingerprint,
            "path":        "certs/cert.pem",
        })
    return _set


def _run():
    import helpers.system_checks as dt  # 2026-09-26 自 routers/daily_tasks 搬出（M12 搬遷前置）
    dt._check_cert_expiry()


def _wait_calls(calls, expected, timeout=3.0):
    """通知是在背景執行緒寄出的，等它真的跑到再斷言。

    不這樣做就是一個典型的偶發失敗——執行緒還沒排到就先斷言，機器忙的時候
    才會紅，而那時候看起來會像產品壞了（見 QUICK.md 對 flaky e2e 的記載）。
    """
    deadline = time.time() + timeout
    while time.time() < deadline and len(calls) < expected:
        time.sleep(0.02)
    return calls


def _guard_keys():
    import db
    conn = db.get_db()
    try:
        return sorted(r["key"] for r in conn.execute(
            "SELECT key FROM system_settings WHERE key LIKE 'cert_notif.%'").fetchall())
    finally:
        conn.close()


# ── 1. 沒有憑證檔 ─────────────────────────────────────────────────────────────

def test_no_cert_file_is_silent(client, sent, tmp_path, monkeypatch):
    """純 HTTP 模式（certs/cert.pem 不存在）→ 什麼都不做，且不能拋例外。

    start.bat／autostart.bat 是 `if exist certs\\cert.pem` 才加 --ssl-* 參數，
    所以「沒有憑證檔」是一個合法且會實際發生的狀態（也是憑證出事時的緊急退路）。
    """
    import helpers.system_checks as dt  # 2026-09-26 自 routers/daily_tasks 搬出（M12 搬遷前置）
    monkeypatch.setattr(dt, "_CERT_PATH", str(tmp_path / "does_not_exist.pem"))
    _run()
    assert sent == []
    assert dt._read_serving_cert(str(tmp_path / "does_not_exist.pem")) is None


def test_unreadable_cert_is_silent(client, sent, tmp_path, monkeypatch):
    """檔案在但內容不是憑證 → 記 log、不寄信、不拋例外（不能讓整個每日排程掛掉）。"""
    import helpers.system_checks as dt  # 2026-09-26 自 routers/daily_tasks 搬出（M12 搬遷前置）
    bad = tmp_path / "cert.pem"
    bad.write_text("this is not a certificate")
    monkeypatch.setattr(dt, "_CERT_PATH", str(bad))
    _run()
    assert sent == []


# ── 2. 門檻依總效期自動切換（本檔重點）──────────────────────────────────────

def test_long_lived_cert_warns_at_60_days(client, sent, cert_at):
    """mkcert（822 天）剩 45 天 → 要示警。手動重產需要有人安排時間，得早點講。"""
    cert_at(days_left=45, total_days=MKCERT_DAYS)
    _run()
    assert len(_wait_calls(sent, 1)) == 1
    days_left, not_after, issuer_cn, path, is_acme = sent[0]
    assert 44 <= days_left <= 45
    assert is_acme is False


def test_acme_cert_does_not_warn_at_45_days(client, sent, cert_at):
    """⭐ Let's Encrypt（90 天）剩 45 天 → **不可以**示警。

    Posh-ACME 要到剩 30 天才續期，45 天是完全正常的狀態。若這裡誤報，
    等於每 90 天寄一次假警報，真的出事那次就不會有人當一回事。
    """
    cert_at(days_left=45, total_days=LE_DAYS)
    _run()
    time.sleep(0.15)          # 給背景執行緒機會跑（真的有寄的話會被抓到）
    assert sent == []
    assert _guard_keys() == []


def test_acme_cert_warns_at_21_days(client, sent, cert_at):
    """LE 剩 15 天 → 要示警：自動續期本該在剩 30 天時就完成，沒完成就是壞了。"""
    cert_at(days_left=15, total_days=LE_DAYS)
    _run()
    assert len(_wait_calls(sent, 1)) == 1
    assert sent[0][4] is True          # is_acme → 信裡給的是「查續期排程」那套指示


def test_long_lived_cert_silent_when_far_away(client, sent, cert_at):
    """mkcert 剩 800 天 → 不吵。"""
    cert_at(days_left=800, total_days=MKCERT_DAYS)
    _run()
    time.sleep(0.15)
    assert sent == []


# ── 3. 同一門檻只寄一次 ───────────────────────────────────────────────────────

def test_same_threshold_only_sends_once(client, sent, fake_cert):
    """同一張憑證、同一個門檻內連跑三次 → 只寄一次。"""
    fake_cert(days_left=45)
    _run()
    _wait_calls(sent, 1)
    fake_cert(days_left=44)      # 同一張憑證，隔天再跑
    _run()
    fake_cert(days_left=30)      # 仍在 60 天這個門檻內
    _run()
    time.sleep(0.15)
    assert len(sent) == 1


def test_crossing_into_lower_threshold_sends_again(client, sent, fake_cert):
    """45 天寄過之後，同一張憑證掉到 20 天（跨進 21 天門檻）要再寄一次。"""
    fake_cert(days_left=45)
    _run()
    _wait_calls(sent, 1)

    fake_cert(days_left=20)      # 同一張憑證（fingerprint 不變），只是變舊了
    _run()
    assert len(_wait_calls(sent, 2)) == 2
    assert sent[1][0] == 20


# ── 4. 已過期後每 7 天重寄 ────────────────────────────────────────────────────

def test_expired_cert_notifies(client, sent, fake_cert):
    fake_cert(days_left=-3)
    _run()
    assert len(_wait_calls(sent, 1)) == 1
    assert sent[0][0] < 0                      # 負數 → 信裡走「已過期」那個分支


def test_expired_within_same_week_does_not_resend(client, sent, fake_cert):
    """同一張過期憑證、還在同一個 7 天區間 → 不重寄（不能每天轟炸）。"""
    fake_cert(days_left=-2)
    _run()
    _wait_calls(sent, 1)
    fake_cert(days_left=-5)      # 同一張憑證，-2 與 -5 都落在 exp0
    _run()
    time.sleep(0.15)
    assert len(sent) == 1


def test_expired_next_week_resends(client, sent, fake_cert):
    """同一張過期憑證跨進下一個 7 天區間 → 再叫一次，直到有人處理。"""
    fake_cert(days_left=-2)      # exp0
    _run()
    _wait_calls(sent, 1)
    fake_cert(days_left=-9)      # exp1 —— fingerprint 沒變，純粹是又過了一週
    _run()
    assert len(_wait_calls(sent, 2)) == 2


# ── 5. guard key 收斂 ────────────────────────────────────────────────────────

def test_guard_keys_pruned_to_one(client, sent, fake_cert):
    """同一張憑證跑過好幾個門檻之後，system_settings 裡最多只留 1 列。

    這個專案已經為「只寫不刪」付過代價：module_versions 曾長到 626,725 列、
    約佔 301MB 資料庫裡的 270MB（見 db.py `_m035` 註解）。
    """
    for d in (45, 20, 5, -2, -9, -16):
        fake_cert(days_left=d)
        _run()
        time.sleep(0.05)
    assert len(_guard_keys()) <= 1


def test_new_cert_resets_guard(client, sent, fake_cert):
    """換上一張新憑證（fingerprint 變了）→ 舊 key 不會擋住新憑證的告警。

    續期之後如果還被舊 guard key 擋著，新憑證萬一又出問題就永遠不會叫。
    """
    fake_cert(days_left=15, total_days=LE_DAYS, fingerprint="1111111111111111")
    _run()
    _wait_calls(sent, 1)
    before = _guard_keys()
    assert len(before) == 1

    # 續期換上新憑證：剩餘天數刻意相同，唯一的差別就是 fingerprint
    fake_cert(days_left=15, total_days=LE_DAYS, fingerprint="2222222222222222")
    _run()
    assert len(_wait_calls(sent, 2)) == 2
    after = _guard_keys()
    assert len(after) == 1
    assert after != before                          # 確實換了一組 key，不是沿用


def test_far_away_run_prunes_old_cert_keys(client, sent, fake_cert):
    """續期成功、離到期還很遠時，上一張憑證留下的 key 要被收掉。

    否則那些 key 會一路留到下一次到期，而 prune 只在有示警時才跑。
    """
    fake_cert(days_left=-2, fingerprint="1111111111111111")
    _run()
    _wait_calls(sent, 1)
    assert len(_guard_keys()) == 1

    fake_cert(days_left=89, total_days=LE_DAYS, fingerprint="2222222222222222")
    _run()
    time.sleep(0.15)
    assert len(sent) == 1        # 89 天不該吵
    assert _guard_keys() == []   # 但舊 key 要清掉


# ── 6. 解析結果本身 ──────────────────────────────────────────────────────────

def test_reads_cert_fields(client, cert_at, tmp_path):
    import helpers.system_checks as dt  # 2026-09-26 自 routers/daily_tasks 搬出（M12 搬遷前置）
    cert_at(days_left=30, total_days=LE_DAYS, cn="R11")
    info = dt._read_serving_cert()
    assert info["issuer_cn"] == "R11"
    assert 89 <= info["total_days"] <= 90
    assert 29 <= info["days_left"] <= 30
    assert len(info["fingerprint"]) == 16
    assert info["not_after"] == (
        _dt.datetime.now(_dt.timezone.utc).date() + _dt.timedelta(days=30)).isoformat()


def test_event_key_is_registered():
    """`cert_expiry` 必須在 EVENT_GROUPS 裡，否則使用者永遠關不掉這個通知。

    這正是 case_project_overdue 當初漏掉的坑（見 notification_prefs.py 註解）。
    """
    from helpers.notification_prefs import EVENT_KEYS
    assert "cert_expiry" in EVENT_KEYS
