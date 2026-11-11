# -*- coding: utf-8 -*-
"""授權閘門的三個追加項（T80，使用者 2026-11-11 裁示）：

  ① 緊急放行通行證（break-glass）——針對正式機硬體不穩定／機器指紋漂移：授權金鑰失效時，一張**簽章過、綁客戶統編、
     有期限（驗證端硬上限）**的通行證可以讓系統撐過去；放行時 log＋稽核、每個 /api 回應帶 `X-Motrix-License` 標頭、
     `/api/license/status` 講出生效或不生效的原因。
  ② env=dev 警告：驗章通過但簽發方是開發金鑰 ⇒ 不可以悄悄放過去（log＋稽核＋標頭）；啟動時也檢查一次、不擋啟動。
  ③ 前端 402 提示頁與橫幅——靜態面的守門在這裡，瀏覽器行為見 test_e2e_license_gate_2026_11_11.py。

這份檔案的重點是**反向**：通行證「不是」一個空檔案就放行的洞。每一種不該放行的情況都要仍然回 402。

⚠️ 沒有任何一題會呼叫真的 `machine_fingerprint`（見 conftest `license_test_key`）。
「指紋漂移」用 monkeypatch 把 `licensing.machine_fingerprint` 換成另一個值來模擬——金鑰簽給原本那個值。
"""
import datetime as _dt
import importlib.util
import json
import logging
from pathlib import Path

import pytest

from helpers import license_alerts as la
from helpers import licensing as lic

BUSINESS_API = "/api/customers"
TAX_ID = "00000000"                      # conftest 測試金鑰與下面 sign_license 預設的統編


@pytest.fixture(autouse=True)
def _no_external_commands(monkeypatch):
    def _boom(*a, **kw):
        pytest.fail("不該跑外部指令：%r" % (a,))
    monkeypatch.setattr(lic, "_run", _boom)


@pytest.fixture(autouse=True)
def _fresh_alert_state():
    la._ALERTED.clear()
    yield
    la._ALERTED.clear()


@pytest.fixture()
def hdr(client, make_user):
    username, password = make_user(role="admin")
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture()
def box(monkeypatch, tmp_path, license_test_key):
    """一個自己的「安裝目錄」：license.key 與 license_emergency.key 都在裡面（emergency_path 跟著 LICENSE_PATH 走）。"""
    d = tmp_path / "inst"
    d.mkdir()
    monkeypatch.setattr(lic, "LICENSE_PATH", str(d / "license.key"))

    class Box:
        dir = d
        license = d / "license.key"
        token = d / lic.EMERGENCY_FILE_NAME

        def sign(self, **over):
            p = {"customer": "測試用公司", "tax_id": TAX_ID, "machine": license_test_key["machine"],
                 "modules": ["*"], "issued": "2026-01-01",
                 "expires": (_dt.date.today() + _dt.timedelta(days=365)).isoformat(),
                 "kind": lic.LICENSE_KIND_SUBSCRIPTION}
            p.update(over)
            return lic.sign_license(p, license_test_key["priv_pem"])

        def install_license(self, **over):
            self.license.write_text(self.sign(**over), encoding="utf-8")

        def pass_blob(self, days=7, issued=None, priv=None, issued_offset=None, **over):
            issued_d = issued or _dt.date.today()
            if issued_offset is not None:                       # 收集期不可取系統時鐘（守門）⇒ 參數化用「距今幾天」，執行時才換算
                issued_d = _dt.date.today() + _dt.timedelta(days=issued_offset)
            p = {"purpose": lic.EMERGENCY_PURPOSE, "customer": "測試用公司", "tax_id": TAX_ID,
                 "machine": license_test_key["machine"],                    # 綁被救的那把授權金鑰的 machine 值（K 審 S5）
                 "issued": issued_d.isoformat(), "expires": (issued_d + _dt.timedelta(days=days)).isoformat(),
                 "reason": "換主機板，新指紋簽發中"}
            p.update(over)
            return lic.sign_license(p, priv or license_test_key["priv_pem"])

        def install_pass(self, **kw):
            self.token.write_text(self.pass_blob(**kw), encoding="utf-8")

    return Box()


@pytest.fixture()
def drifted(monkeypatch):
    """硬體換了：機器指紋變成另一個值（授權金鑰簽的是原本那個）。"""
    monkeypatch.setattr(lic, "machine_fingerprint", lambda: "deadbeefdeadbeef")
    monkeypatch.setattr(lic, "_LICENSE_FILE_CACHE", None)           # 快取鍵不含指紋（正式機指紋是行程常數）；測試換指紋要清它


def _audit_rows(prefix="license."):
    # 用到的題目都要帶 `client` 固件：它把 db.DB_PATH 指到「這一題自己的庫」；沒有它會寫進／讀到同 worker 共用的 session 庫
    import db
    la.flush()                      # 中介層的稽核寫入在背景執行緒（K 審 S1）；先等它們寫完
    conn = db.get_db()
    try:
        return [(r[0], json.loads(r[1])) for r in conn.execute(
            "SELECT action, detail FROM audit_log WHERE action LIKE ? ORDER BY id", (prefix + "%",)).fetchall()]
    finally:
        conn.close()


# ── ① 緊急放行通行證：生效 ───────────────────────────────────────────────────

def test_without_the_pass_a_drifted_machine_is_blocked(client, hdr, box, drifted):
    """基準：指紋漂移、沒有通行證 ⇒ 402（machine_mismatch）。下面每題都拿它當正對照。"""
    box.install_license()
    r = client.get(BUSINESS_API, headers=hdr)
    assert r.status_code == 402 and r.json()["reason"] == "machine_mismatch", r.text


def test_a_valid_pass_lets_a_drifted_machine_through_and_says_so(client, hdr, box, drifted):
    box.install_license()
    assert client.get(BUSINESS_API, headers=hdr).status_code == 402
    box.install_pass(days=7)
    r = client.get(BUSINESS_API, headers=hdr)
    assert r.status_code == 200, r.text
    until = (_dt.date.today() + _dt.timedelta(days=7)).isoformat()
    assert r.headers.get(lic.LICENSE_HEADER) == "emergency;until=" + until
    # 標頭只給「已登入」的請求（K 審 S4）：公開端點／未登入的呼叫者看不到這台靠通行證在跑
    assert lic.LICENSE_HEADER not in client.get("/api/ping").headers
    assert client.get("/api/ping", headers=hdr).headers.get(lic.LICENSE_HEADER) is None      # 公開端點即使帶了 token 也不算已登入
    s = client.get("/api/license/status", headers=hdr).json()
    assert s["valid"] is False and s["reason"] == "machine_mismatch" and s["blocked"] is True   # 授權本身仍是不通過
    e = s["emergency"]
    assert (e["present"], e["active"], e["why"], e["until"]) == (True, True, "ok", until), e
    assert e["note"] == "換主機板，新指紋簽發中" and len(e["pass_id"]) == 12
    assert s["machine"] == "deadbeefdeadbeef"                       # 簽發方要拿它重簽


def test_a_valid_pass_also_covers_an_expired_license(client, hdr, box):
    box.install_license(expires=(_dt.date.today() - _dt.timedelta(days=3)).isoformat())
    assert client.get(BUSINESS_API, headers=hdr).status_code == 402
    box.install_pass()
    assert client.get(BUSINESS_API, headers=hdr).status_code == 200


def test_using_the_pass_is_logged_and_audited_once_a_day(client, hdr, box, drifted, caplog):
    box.install_license()
    box.install_pass()
    with caplog.at_level(logging.ERROR, logger="helpers.license_alerts"):
        for _ in range(3):
            assert client.get(BUSINESS_API, headers=hdr).status_code == 200
    rows = _audit_rows()
    assert [a for a, _ in rows] == ["license.emergency_pass"], rows
    d = rows[0][1]
    assert d["note"] == "換主機板，新指紋簽發中" and d["until"] and d["pass_id"]
    assert sum("緊急放行通行證" in r.getMessage() for r in caplog.records) == 1


def test_the_pass_keeps_modules_loading_across_a_restart(box, drifted):
    """重啟時 core.loader 用 module_license_check 判模組：靠通行證撐著時不可以變成「所有模組都不載入」。"""
    box.install_license(modules=["case"])
    ok, why = lic.module_license_check({"key": "case"})
    assert ok is False and "未授權" in why                         # 沒有通行證：整體被擋
    box.install_pass()
    assert lic.module_license_check({"key": "case"})[0] is True
    ok, why = lic.module_license_check({"key": "payroll"})           # 通行證不放大授權範圍：金鑰沒列的模組仍然沒有
    assert ok is False and "未包含" in why


# ── ① 反向：這個口不是「放一個檔案就放行」 ──────────────────────────────────

def _assert_still_blocked(client, hdr, why=None):
    r = client.get(BUSINESS_API, headers=hdr)
    assert r.status_code == 402, f"不該放行，實際 {r.status_code}：{r.text}"
    if why:
        e = client.get("/api/license/status", headers=hdr).json()["emergency"]
        assert e and e["active"] is False and e["why"] == why, e


def test_an_empty_file_is_not_a_pass(client, hdr, box, drifted):
    box.install_license()
    box.token.write_text("", encoding="utf-8")
    _assert_still_blocked(client, hdr, "token_malformed")


@pytest.mark.parametrize("label,body", [
    ("純文字", "OK 放行"),
    ("沒簽章的 JSON", json.dumps({"purpose": "emergency_pass", "tax_id": TAX_ID, "issued": "2026-01-01",
                                  "expires": "2099-01-01", "reason": "自己寫的"})),
    ("簽章欄位亂填", json.dumps({"purpose": "emergency_pass", "tax_id": TAX_ID, "issued": "2026-01-01",
                                 "expires": "2099-01-01", "reason": "x", "sig": "AAAA"})),
])
def test_unsigned_or_garbage_files_are_not_a_pass(client, hdr, box, drifted, label, body):
    box.install_license()
    box.token.write_text(body, encoding="utf-8")
    r = client.get(BUSINESS_API, headers=hdr)
    assert r.status_code == 402, label
    e = client.get("/api/license/status", headers=hdr).json()["emergency"]
    assert e["active"] is False and e["why"] in ("token_malformed", "token_bad_signature"), e


def test_a_pass_signed_by_someone_else_is_not_a_pass(client, hdr, box, drifted):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    other = ed25519.Ed25519PrivateKey.generate().private_bytes(
        encoding=serialization.Encoding.PEM, format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption())
    box.install_license()
    box.token.write_text(box.pass_blob(priv=other), encoding="utf-8")
    _assert_still_blocked(client, hdr, "token_bad_signature")


@pytest.mark.parametrize("field,value", [
    ("expires", "2099-12-31"),                                       # 管理員自己把期限往後改
    ("tax_id", "11111111"),
    ("machine", "feedfacefeedface"),
    ("reason", "改過"),
])
def test_editing_a_signed_pass_breaks_it(client, hdr, box, drifted, field, value):
    import base64
    box.install_license()
    payload = json.loads(base64.b64decode(box.pass_blob()))
    payload[field] = value
    box.token.write_text(base64.b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode(), encoding="utf-8")
    _assert_still_blocked(client, hdr, "token_bad_signature")


def test_a_license_key_is_not_a_pass_and_a_pass_is_not_a_license(client, hdr, box, drifted):
    box.install_license()
    box.token.write_text(box.sign(), encoding="utf-8")               # 把授權金鑰當通行證
    _assert_still_blocked(client, hdr, "token_malformed")            # 缺 purpose／reason ⇒ 格式不符
    box.token.unlink()
    box.license.write_text(box.pass_blob(), encoding="utf-8")        # 反過來：通行證當授權金鑰
    r = client.get(BUSINESS_API, headers=hdr)
    assert r.status_code == 402 and r.json()["reason"] == "malformed"
    assert lic.verify_license()["valid"] is False


def test_a_signed_blob_with_another_purpose_is_not_a_pass(client, hdr, box, drifted):
    box.install_license()
    box.token.write_text(box.pass_blob(purpose="something_else"), encoding="utf-8")
    _assert_still_blocked(client, hdr, "token_wrong_purpose")


def test_a_pass_for_another_customer_is_not_a_pass(client, hdr, box, drifted):
    box.install_license()
    box.token.write_text(box.pass_blob(tax_id="99999999"), encoding="utf-8")
    _assert_still_blocked(client, hdr, "tax_id_mismatch")


@pytest.mark.parametrize("why,kw", [
    ("token_expired", {"issued_offset": -10, "days": 3}),
    ("token_not_yet_valid", {"issued_offset": 2, "days": 3}),
    ("token_span_too_long", {"days": lic.EMERGENCY_MAX_DAYS + 1}),    # 簽發方多簽幾天也沒用：上限在驗證端
    ("token_span_too_long", {"days": 3650}),
])
def test_dates_are_enforced_by_the_verifier(client, hdr, box, drifted, why, kw):
    box.install_license()
    box.install_pass(**kw)
    _assert_still_blocked(client, hdr, why)


def test_the_last_day_still_counts_and_the_day_after_does_not(client, hdr, box, drifted, monkeypatch):
    box.install_license()
    box.install_pass(days=2)
    real = lic.date

    def _on(offset):
        class _D(real):
            @classmethod
            def today(cls):
                return real.today() + _dt.timedelta(days=offset)
        monkeypatch.setattr(lic, "date", _D)
    _on(2)
    assert client.get(BUSINESS_API, headers=hdr).status_code == 200      # expires 當天仍有效
    _on(3)
    _assert_still_blocked(client, hdr, "token_expired")                    # 隔天自動失效，不需要有人去刪


@pytest.mark.parametrize("license_state", ["missing", "malformed", "bad_signature"])
def test_the_pass_only_covers_machine_mismatch_and_expired(client, hdr, box, drifted, license_state):
    """沒有金鑰／損毀／簽章不符是「重新簽一把授權」的事，不是通行證該蓋掉的事（也沒有可信的授權金鑰可以對統編）。"""
    if license_state == "malformed":
        box.license.write_text("garbage", encoding="utf-8")
    elif license_state == "bad_signature":
        import base64
        forged = json.loads(base64.b64decode(box.sign()))
        forged["expires"] = "2099-12-31"                                                  # 內容被動過、簽章不變
        box.license.write_text(base64.b64encode(json.dumps(forged, ensure_ascii=False).encode()).decode(),
                               encoding="utf-8")
    box.install_pass()
    r = client.get(BUSINESS_API, headers=hdr)
    assert r.status_code == 402 and r.json()["reason"] == license_state, r.text
    e = client.get("/api/license/status", headers=hdr).json()["emergency"]
    assert e["active"] is False and e["why"] == "license_not_covered", e


def test_an_oversized_file_is_not_read(client, hdr, box, drifted):
    box.install_license()
    box.token.write_text(box.pass_blob() + " " * (lic.EMERGENCY_MAX_BYTES + 1), encoding="utf-8")
    _assert_still_blocked(client, hdr, "token_too_big")


def test_a_directory_in_place_of_the_file_is_not_a_pass(client, hdr, box, drifted):
    box.install_license()
    box.token.mkdir()
    r = client.get(BUSINESS_API, headers=hdr)
    assert r.status_code == 402
    assert client.get("/api/license/status", headers=hdr).json()["emergency"] is None


def test_a_pass_does_nothing_while_the_license_is_fine(client, hdr, box):
    box.install_license()
    box.install_pass()
    r = client.get(BUSINESS_API, headers=hdr)
    assert r.status_code == 200 and r.headers.get(lic.LICENSE_HEADER) == "none"          # 已登入：沒有要提示 ⇒ none（前端據此移除橫幅）
    e = client.get("/api/license/status", headers=hdr).json()["emergency"]
    assert e["present"] is True and e["active"] is False and e["why"] == "not_needed", e
    assert _audit_rows() == []                                          # 沒用到就不留「使用」紀錄


def test_the_status_endpoint_never_500s_on_a_broken_pass(client, hdr, box, drifted, monkeypatch):
    box.install_license()
    box.install_pass()

    def _boom(*a, **kw):
        raise RuntimeError("boom")
    monkeypatch.setattr(lic, "_emergency_judge", _boom)
    s = client.get("/api/license/status", headers=hdr)
    assert s.status_code == 200 and s.json()["emergency"]["active"] is False
    assert client.get(BUSINESS_API, headers=hdr).status_code == 402    # 判不了 ⇒ 照擋


def test_a_pass_has_no_effect_when_the_gate_is_off_and_is_never_read(client, hdr, box, monkeypatch):
    monkeypatch.setattr(lic, "LICENSE_GATE_ENABLED", False)
    monkeypatch.setattr(lic, "emergency_pass", lambda s: pytest.fail("閘門關著不該看通行證"))
    assert client.get(BUSINESS_API, headers=hdr).status_code == 200


# ── 簽發工具 ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def tool():
    spec = importlib.util.spec_from_file_location(
        "issue_license_t", Path(__file__).resolve().parents[1] / "tools" / "issue_license.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_the_issuing_tool_makes_a_pass_the_gate_accepts(client, hdr, box, drifted, tool, license_test_key, tmp_path):
    key = tmp_path / "priv.pem"
    key.write_bytes(license_test_key["priv_pem"])
    out = tmp_path / "pass.key"
    rc = tool.main(["emergency", "--tax-id", TAX_ID, "--machine", license_test_key["machine"], "--customer", "測試用公司",
                    "--days", "5", "--reason", "更換主機板", "--key", str(key), "--out", str(out)])
    assert rc == 0 and lic.emergency_blob_problem(out.read_text(encoding="utf-8").strip()) is None
    box.install_license()
    box.token.write_text(out.read_text(encoding="utf-8"), encoding="utf-8")
    assert client.get(BUSINESS_API, headers=hdr).status_code == 200


@pytest.mark.parametrize("argv_extra", [
    ["--days", str(lic.EMERGENCY_MAX_DAYS + 1)],       # 超過驗證端上限：簽發端就拒絕，不產出一張用不了的通行證
    ["--days", "0"],
    ["--reason", "   "],                               # 理由不可空（會進稽核）
])
def test_the_issuing_tool_refuses_unusable_or_unexplained_passes(tool, license_test_key, tmp_path, argv_extra):
    key = tmp_path / "priv.pem"
    key.write_bytes(license_test_key["priv_pem"])
    argv = ["emergency", "--tax-id", TAX_ID, "--machine", license_test_key["machine"], "--days", "3", "--reason", "x",
            "--key", str(key), "--out", str(tmp_path / "o.key")]
    for i in range(0, len(argv_extra), 2):
        argv[argv.index(argv_extra[i]) + 1] = argv_extra[i + 1]
    assert tool.main(argv) == 2
    assert not (tmp_path / "o.key").exists()


# ── ② env=dev 警告 ───────────────────────────────────────────────────────────

@pytest.fixture()
def dev_signed(monkeypatch, box, license_test_key):
    """驗章通過、但簽發方是開發金鑰（env=dev）：把測試公鑰當成『開發公鑰』、正式公鑰留空。"""
    monkeypatch.setattr(lic, "_PUBKEY_DEV", license_test_key["pub_pem"])
    monkeypatch.setattr(lic, "_PUBKEY_PROD", b"")
    box.install_license()
    assert lic.verify_license()["env"] == "dev"


def test_a_dev_signed_key_still_works_but_is_never_silent(client, hdr, dev_signed, caplog):
    with caplog.at_level(logging.WARNING, logger="helpers.license_alerts"):
        r = client.get(BUSINESS_API, headers=hdr)
        assert r.status_code == 200                                       # 只警告，不擋（理由見 license_alerts.py）
        assert r.headers.get(lic.LICENSE_HEADER) == "dev_key"
        assert client.get(BUSINESS_API, headers=hdr).headers.get(lic.LICENSE_HEADER) == "dev_key"
    assert [a for a, _ in _audit_rows()] == ["license.dev_key"]            # 稽核每天一次
    assert sum("開發金鑰" in r.getMessage() for r in caplog.records) == 1
    assert client.get("/api/license/status", headers=hdr).json()["env"] == "dev"


def test_a_prod_signed_key_has_no_banner_and_no_alert(client, hdr, box):
    box.install_license()
    r = client.get(BUSINESS_API, headers=hdr)
    assert r.status_code == 200 and r.headers.get(lic.LICENSE_HEADER) == "none"
    assert _audit_rows() == []


def test_startup_check_records_a_dev_key_and_does_not_refuse_to_start(client, dev_signed, caplog):
    with caplog.at_level(logging.WARNING, logger="helpers.license_alerts"):
        assert la.startup_check() == "dev_key"
    assert [a for a, _ in _audit_rows()] == ["license.dev_key"]
    assert any("開發金鑰" in r.getMessage() for r in caplog.records)


def test_startup_check_records_a_blocked_license_and_still_starts(client, box, caplog):
    with caplog.at_level(logging.ERROR, logger="helpers.license_alerts"):
        assert la.startup_check() == "blocked"                             # 沒有金鑰
    rows = _audit_rows()
    assert [a for a, _ in rows] == ["license.startup_blocked"] and rows[0][1]["reason"] == "missing"
    assert any("402" in r.getMessage() for r in caplog.records)


def test_startup_check_records_that_it_is_running_on_a_pass(client, box, drifted):
    box.install_license()
    box.install_pass()
    assert la.startup_check() == "emergency"
    assert [a for a, _ in _audit_rows()] == ["license.emergency_pass"]


def test_startup_check_is_silent_and_never_reads_the_key_when_the_gate_is_off(client, box, monkeypatch):
    monkeypatch.setattr(lic, "LICENSE_GATE_ENABLED", False)
    monkeypatch.setattr(lic, "verify_license", lambda blob=None: pytest.fail("閘門關著不該讀金鑰"))
    assert la.startup_check() is None and _audit_rows() == []


def test_startup_check_never_raises(client, monkeypatch):
    def _boom(blob=None):
        raise RuntimeError("boom")
    monkeypatch.setattr(lic, "verify_license", _boom)
    assert la.startup_check() is None                                      # 告警本身壞掉不可以讓服務起不來


# ── ③ 前端靜態面 ─────────────────────────────────────────────────────────────

_ROOT = Path(__file__).resolve().parents[2]


def test_the_explanation_page_exists_and_is_a_registered_core_page():
    from core import source_tree
    html = source_tree.page_file("license-required.html").read_text(encoding="utf-8")
    assert "data-license-required" in html and "/api/license/status" in html
    assert "license-required.html" in json.loads((_ROOT / "backend" / "core" / "l1_pages.json").read_text(encoding="utf-8"))
    # K 審 S3：登入已過期（status 回 401）⇒ 回登入頁，不是永遠停在泛用說明；M1：有模組在等重啟要講出來
    assert "r.status === 401" in html and "login.html" in html
    assert "modules_unlicensed" in html and "重啟服務" in html


def test_notif_js_handles_402_and_the_license_header():
    js = (_ROOT / "frontend" / "static" / "notif.js").read_text(encoding="utf-8")
    assert "r.status === 402" in js and "license_required" in js and "license-required.html" in js
    assert lic.LICENSE_HEADER in js and "motrix-license-banner" in js
    # S4：標頭只給已登入的請求；沒有標頭 ⇒ 不動橫幅，`none` ⇒ 移除（否則公開端點的回應會讓橫幅閃掉）
    assert "lh !== null" in js and "'none'" in js
    # 說明頁與登入頁自己不導，否則會無限重導
    assert "['license-required.html', 'login.html']" in js


# ── K 審（hichan-11，2026-11-11）追加的題 ────────────────────────────────────

def _other_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    k = ed25519.Ed25519PrivateKey.generate()
    return (k.private_bytes(encoding=serialization.Encoding.PEM, format=serialization.PrivateFormat.PKCS8,
                            encryption_algorithm=serialization.NoEncryption()),
            k.public_key().public_bytes(encoding=serialization.Encoding.PEM,
                                        format=serialization.PublicFormat.SubjectPublicKeyInfo))


def _dev_license(license_test_key, dev_priv):
    return lic.sign_license({"customer": "測試用公司", "tax_id": TAX_ID, "machine": license_test_key["machine"],
                             "modules": ["*"], "issued": "2026-01-01", "expires": "2099-12-31",
                             "kind": lic.LICENSE_KIND_SUBSCRIPTION}, dev_priv)


def test_kfix_m2_a_dev_signed_pass_cannot_rescue_a_prod_signed_license(client, hdr, box, drifted, monkeypatch):
    """M2：通行證的簽發環境必須等於授權金鑰的環境。開發私鑰不在受控保管下，正式公鑰一上線，這是唯一擋住它的東西。"""
    dev_priv, dev_pub = _other_key()
    monkeypatch.setattr(lic, "_PUBKEY_DEV", dev_pub)
    box.install_license()                                                      # 測試金鑰＝正式金鑰（env=prod）簽的授權
    assert lic.verify_license()["env"] == "prod"
    box.token.write_text(box.pass_blob(priv=dev_priv), encoding="utf-8")       # 開發金鑰簽的通行證
    _assert_still_blocked(client, hdr, "env_mismatch")


def test_kfix_m2_a_prod_signed_pass_cannot_rescue_a_dev_signed_license(client, hdr, box, drifted, monkeypatch, license_test_key):
    dev_priv, dev_pub = _other_key()
    monkeypatch.setattr(lic, "_PUBKEY_DEV", dev_pub)
    box.license.write_text(_dev_license(license_test_key, dev_priv), encoding="utf-8")
    assert lic.verify_license()["env"] == "dev"
    box.install_pass()                                                         # 正式金鑰簽的通行證
    _assert_still_blocked(client, hdr, "env_mismatch")


def test_kfix_m2_same_environment_is_honoured_dev_with_dev(client, hdr, box, drifted, monkeypatch, license_test_key):
    """正對照：同為 env=dev 的授權與通行證照常放行（環境相同就不是問題）。"""
    dev_priv, dev_pub = _other_key()
    monkeypatch.setattr(lic, "_PUBKEY_DEV", dev_pub)
    box.license.write_text(_dev_license(license_test_key, dev_priv), encoding="utf-8")
    box.token.write_text(box.pass_blob(priv=dev_priv), encoding="utf-8")
    assert client.get(BUSINESS_API, headers=hdr).status_code == 200


def test_kfix_s5_a_pass_is_bound_to_the_rescued_licenses_machine_value(client, hdr, box, drifted):
    """S5：同客戶統編、但被救的是『另一個安裝』的授權（machine 值不同）⇒ 不放行。"""
    box.install_license()
    box.token.write_text(box.pass_blob(machine="0000111122223333"), encoding="utf-8")
    _assert_still_blocked(client, hdr, "machine_mismatch")


def test_kfix_s5_a_pass_without_a_machine_value_is_malformed(client, hdr, box, drifted, license_test_key):
    import base64
    box.install_license()
    payload = json.loads(base64.b64decode(box.pass_blob()))
    payload.pop("machine")
    payload.pop("sig")
    # 少欄位的通行證：簽發工具不會產出；就算持私鑰者手簽一張，驗證端也要求這個欄位
    box.token.write_text(lic.sign_license(payload, license_test_key["priv_pem"]), encoding="utf-8")
    _assert_still_blocked(client, hdr, "token_malformed")


def test_kfix_s2_a_pass_is_not_reported_active_when_nothing_is_blocked(client, hdr, box):
    """S2：永久授權過期（reason=expired 但不擋）＋有效通行證 ⇒ 通行證不是『生效』，狀態端點不可以這樣講。"""
    box.install_license(kind=lic.LICENSE_KIND_PERPETUAL, expires=(_dt.date.today() - _dt.timedelta(days=30)).isoformat())
    box.install_pass()
    s = client.get("/api/license/status", headers=hdr).json()
    assert s["reason"] == "expired" and s["blocked"] is False
    assert s["emergency"]["active"] is False and s["emergency"]["why"] == "not_needed", s["emergency"]
    r = client.get(BUSINESS_API, headers=hdr)
    assert r.status_code == 200 and r.headers.get(lic.LICENSE_HEADER) == "none"


def test_nit_a_license_bigger_than_the_pass_cap_can_still_be_rescued(client, hdr, box, drifted):
    """nit：授權金鑰沒有 8 KB 上限（verify_license 不設），救援時讀它也不可以設，否則『驗得過卻救不了』。"""
    box.install_license(note="x" * (lic.EMERGENCY_MAX_BYTES + 500))
    assert lic.verify_license()["reason"] == "machine_mismatch"                # 驗得過章（只是機器不符）
    box.install_pass()
    assert client.get(BUSINESS_API, headers=hdr).status_code == 200


@pytest.mark.parametrize("issued", ["20261111", "2026-W46-3", "2026-11-1", " "])
def test_nit_pass_dates_must_be_strict_yyyy_mm_dd(client, hdr, box, drifted, license_test_key, issued):
    import base64
    box.install_license()
    payload = json.loads(base64.b64decode(box.pass_blob()))
    payload.pop("sig")
    payload["issued"] = issued                                                 # 簽發日格式不合（簽章是對的）
    box.token.write_text(lic.sign_license(payload, license_test_key["priv_pem"]), encoding="utf-8")
    _assert_still_blocked(client, hdr, "token_bad_dates")


def test_kfix_s4_unauthenticated_callers_never_see_the_license_banner_header(client, hdr, box, drifted):
    box.install_license()
    box.install_pass()
    for path in ("/api/ping", "/api/system/branding/favicon"):
        assert lic.LICENSE_HEADER not in client.get(path).headers, path
    r = client.get(BUSINESS_API)
    assert r.status_code == 401 and lic.LICENSE_HEADER not in r.headers        # 未登入：先 401，不是 402，也沒有標頭
    assert client.get(BUSINESS_API, headers=hdr).headers.get(lic.LICENSE_HEADER, "").startswith("emergency")


def test_kfix_s1_the_alert_is_written_off_the_event_loop(client, hdr, box, drifted, monkeypatch):
    """S1：中介層丟背景執行緒寫稽核（同步 SQLite 在事件迴圈裡遇到寫鎖會卡全站）；flush 之後確實寫進去。"""
    import threading
    box.install_license()
    box.install_pass()
    seen = []
    real_audit = la._audit

    def _spy(action, detail):
        seen.append(threading.current_thread().name)
        return real_audit(action, detail)
    monkeypatch.setattr(la, "_audit", _spy)
    assert client.get(BUSINESS_API, headers=hdr).status_code == 200
    la.flush()
    assert seen == ["license-audit"], seen
    assert [a for a, _ in _audit_rows()] == ["license.emergency_pass"]


def test_kfix_s1_the_audit_goes_to_the_main_db_even_when_the_request_is_a_demo_session(client):
    """S1：示範帳號碰巧是當天第一個請求時，授權告警不可以寫進示範庫。"""
    import db
    db.set_demo_mode(True)
    try:
        assert la.emergency_in_use({"pass_id": "abc123abc123", "until": "2099-01-01", "note": "n", "env": "prod"}) is True
    finally:
        db.set_demo_mode(False)
    assert [a for a, _ in _audit_rows()] == ["license.emergency_pass"]


def test_kfix_s6_status_endpoint_does_not_retry_an_unreadable_fingerprint_every_call(client, hdr, monkeypatch):
    """S6：指紋讀不到時 machine_fingerprint() 不快取（每次都跑硬體查詢）；狀態端點被前端反覆呼叫，不可以每次都打。"""
    import routers.licensing as rl
    calls = []

    def _fail():
        calls.append(1)
        raise RuntimeError("no hardware id")
    monkeypatch.setattr(lic, "machine_fingerprint", _fail)
    monkeypatch.setattr(lic, "_LICENSE_FILE_CACHE", None)
    monkeypatch.setattr(rl, "_FP_FAIL_UNTIL", 0.0)
    for _ in range(4):
        s = client.get("/api/license/status", headers=hdr)
        assert s.status_code == 200 and s.json()["machine"] is None
    assert len(calls) <= 2, calls         # 端點自己至多 1 次、verify_license 快取未命中至多 1 次；絕不是每次呼叫都來一次


def test_kfix_m1_modules_skipped_at_start_stay_unloaded_until_a_restart(client, hdr, box, drifted):
    """M1（如實記下行為）：載入器只在開機時決定模組要不要載入。開機時授權被擋（還沒有通行證）⇒ 模組登記為 unlicensed；
    之後才放通行證 ⇒ 業務 API 立刻恢復，但那些模組**沒有**變成已載入——要重啟。狀態端點要講出有哪些模組在等重啟。"""
    from core import registry
    snap = registry.snapshot()
    try:
        box.install_license(modules=["zz_probe_mod"])
        ok, why = lic.module_license_check({"key": "zz_probe_mod"})                    # 『開機』：被擋、沒有通行證
        assert ok is False
        registry.set_state("zz_probe_mod", registry.STATE_UNLICENSED, why, {"key": "zz_probe_mod"})   # 載入器看到 False 時做的事
        box.install_pass()                                                    # 開機之後才放通行證
        assert client.get(BUSINESS_API, headers=hdr).status_code == 200      # 業務 API 恢復
        s = client.get("/api/license/status", headers=hdr).json()
        assert s["modules_unlicensed"] == ["zz_probe_mod"], s                        # 但 case 還在等重啟
        assert registry.is_loaded("zz_probe_mod") is False                            # 沒有任何東西會自己把它載入
        assert lic.module_license_check({"key": "zz_probe_mod"})[0] is True           # 『重啟』時才會判成通過
    finally:
        registry.restore(snap)


def test_the_tool_reads_tax_id_and_machine_from_the_rescued_license(client, hdr, box, drifted, tool, license_test_key, tmp_path):
    key = tmp_path / "priv.pem"
    key.write_bytes(license_test_key["priv_pem"])
    box.install_license()
    out = tmp_path / "p.key"
    assert tool.main(["emergency", "--license", str(box.license), "--days", "3", "--reason", "換板", "--key", str(key),
                      "--out", str(out)]) == 0
    box.token.write_text(out.read_text(encoding="utf-8"), encoding="utf-8")
    assert client.get(BUSINESS_API, headers=hdr).status_code == 200


def test_the_tool_refuses_without_the_licenses_identity_or_with_a_license_that_does_not_verify(tool, license_test_key, tmp_path):
    key = tmp_path / "priv.pem"
    key.write_bytes(license_test_key["priv_pem"])
    base = ["emergency", "--days", "3", "--reason", "x", "--key", str(key), "--out", str(tmp_path / "o.key")]
    assert tool.main(base) == 2                                               # 沒給 --license 也沒給 --tax-id/--machine
    assert tool.main(base + ["--tax-id", TAX_ID]) == 2                         # 只給統編：缺 machine
    bad = tmp_path / "bad.key"
    bad.write_text("garbage", encoding="utf-8")
    assert tool.main(base + ["--license", str(bad)]) == 2                      # 授權金鑰驗不過：不替它簽通行證
    assert not (tmp_path / "o.key").exists()
