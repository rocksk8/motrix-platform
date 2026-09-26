"""IP-2 voucher.draft／voucher.account_check、IP-3 accounting.settings（INTEGRATION-POINTS.md）。

M07 獎金不再 import M06 的私有函式；M06 不在時：
  獎金核准／標記已發放**照常成立**，不產生傳票，而且**明說**「未產生傳票：會計模組未安裝」
  （回傳 notice、明細的 voucherNotice、設定頁 problems）——不可以默默略過。

① 契約：三個提供者存在；voucher.draft 真的寫出草稿＋分錄；account_check／settings 形狀
② 反向控制：同一條流程，有 M06 時產生傳票（正對照），拿掉三個提供者後獎金照走、沒有傳票、有明確提示
③ 邊界：M07 不再 import M06 的函式
"""
import pytest

from core import registry
from modules.payroll.tests.test_bonus_case_api_2026_09_24 import (  # noqa: F401
    people, _seed_case, _create, _members_spec, _auth)
from modules.payroll.tests._bonus_insure import insure_all  # noqa: E402

CAPS = ("voucher.draft", "voucher.account_check", "accounting.settings")
MISSING = "未產生傳票：會計模組未安裝"


def _db():
    import db
    return db.get_db()


def _award(no):
    conn = _db()
    try:
        return dict(conn.execute("SELECT * FROM bonus_case_awards WHERE quote_no=?", (no,)).fetchone())
    finally:
        conn.close()


def _voucher_count():
    conn = _db()
    try:
        return conn.execute("SELECT COUNT(*) FROM vouchers_all").fetchone()[0]
    finally:
        conn.close()


def _to_payout(client, people, no):
    _seed_case(no, net=100000)
    assert _create(client, people["bc_sa"], no, members=_members_spec()).status_code == 200
    assert client.post("/api/bonus/cases/%s/submit" % no, headers=_auth(people["bc_sa"])).status_code == 200
    return client.post("/api/bonus/cases/%s/approve" % no, headers=_auth(people["bc_sa2"]))


def _drop_accounting(monkeypatch):
    monkeypatch.setattr(registry, "_LEGACY_PROVIDERS",
                        {k: v for k, v in registry._LEGACY_PROVIDERS.items() if k[0] not in CAPS})
    assert all(registry.single_provider(c) is None for c in CAPS)


# ── ① 契約 ──────────────────────────────────────────────────────────────────

def test_contract_providers_exist_and_draft_really_writes(client):
    for c in CAPS:
        assert registry.single_provider(c) is not None, c
    ok, err = registry.single_provider("voucher.account_check")(_db(), "6111")
    assert ok and err == ""
    bad_ok, bad_err = registry.single_provider("voucher.account_check")(_db(), "99999999")
    assert not bad_ok and bad_err
    s = registry.single_provider("accounting.settings")()
    assert set(s) == {"bankAccounts", "defaultBankAccountCode"}          # 只公開這一小塊
    conn = _db()
    try:
        v = registry.single_provider("voucher.draft")(
            conn, voucher_date="2026-09-25", summary="IP-2 契約", created_by="t", now="2026-09-25T00:00:00",
            lines=[{"account_code": "6111", "summary": "x", "debit": 100, "credit": 0},
                   {"account_code": "2191", "summary": "x", "debit": 0, "credit": 100}])
        assert set(v) == {"id", "voucher_no"}
        row = conn.execute("SELECT status, category FROM vouchers_all WHERE id=?", (v["id"],)).fetchone()
        assert (row["status"], row["category"]) == ("草稿", "轉")
        assert conn.execute("SELECT COUNT(*) FROM voucher_lines WHERE voucher_id=?", (v["id"],)).fetchone()[0] == 2
        conn.rollback()                                   # 契約：不 commit，由呼叫端決定
    finally:
        conn.close()


# ── ② 反向控制 ───────────────────────────────────────────────────────────────

def test_with_accounting_the_flow_makes_vouchers(client, people):
    """正對照：同一條流程在 M06 在時確實產生兩張草稿——否則「沒產生」的斷言沒有意義。"""
    insure_all()   # U4：撥付前名單上每個人都要有投保金額（tests/_bonus_insure.py）
    before = _voucher_count()
    r = _to_payout(client, people, "MQ-IP2-001")
    assert r.status_code == 200 and r.json()["voucher"], r.text
    d = client.get("/api/bonus/cases/MQ-IP2-001", headers=_auth(people["bc_cash"])).json()
    assert "voucherNotice" not in d
    r = client.post("/api/bonus/cases/MQ-IP2-001/mark-paid", headers=_auth(people["bc_cash"]))
    assert r.status_code == 200 and r.json()["voucher"], r.text
    assert _voucher_count() == before + 2


def test_without_accounting_bonus_still_works_and_says_so(client, people, monkeypatch):
    insure_all()   # U4：撥付前名單上每個人都要有投保金額（tests/_bonus_insure.py）
    _drop_accounting(monkeypatch)
    before = _voucher_count()

    r = _to_payout(client, people, "MQ-IP2-002")                      # 核准 ⇒ 待發放
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "待發放" and body["voucher"] is None
    assert MISSING in body["notice"], body                            # 明說，不默默略過
    assert not _award("MQ-IP2-002")["accrual_voucher_id"]

    d = client.get("/api/bonus/cases/MQ-IP2-002", headers=_auth(people["bc_cash"])).json()
    assert d["bankAccounts"] == [] and MISSING in d["voucherNotice"]   # 畫面上看得到

    r = client.post("/api/bonus/cases/MQ-IP2-002/mark-paid", headers=_auth(people["bc_cash"]),
                    json={"bank_account_code": "1113"})               # 帶了銀行也不擋發放
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "已發放" and r.json()["voucher"] is None and MISSING in r.json()["notice"]
    assert _voucher_count() == before                                 # 一張都沒寫

    g = client.get("/api/bonus/cases/voucher-accounts", headers=_auth(people["bc_sa"])).json()
    assert g["problems"] and all("會計模組未安裝" in v for v in g["problems"].values())
    p = client.put("/api/bonus/cases/voucher-accounts", headers=_auth(people["bc_sa"]), json={"expense": "6111"})
    assert p.status_code == 400 and "會計模組未安裝" in p.text        # 驗證不了就不寫，並說明


# ── ③ 邊界 ──────────────────────────────────────────────────────────────────

def _group_py_files(group):
    """modules.json 裡某一組的 router／helper 單位 → 檔案（稽核 Y-2：不寫死檔名，M07 新增檔案也掃得到）。"""
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[4]
    units = json.loads((root / "docs" / "platform" / "modules.json").read_text(encoding="utf-8"))["modules"][group]["units"]
    out = {}
    for u in units:
        kind, name = u.split(":", 1)
        if kind in ("router", "helper"):
            out["%ss.%s" % (kind, name)] = root / "backend" / ("routers" if kind == "router" else "helpers") / (name + ".py")
        elif kind == "mod":                                 # mod:<key>/<相對路徑>（模組搬進 modules/ 之後）
            key, rel = name.split("/", 1)
            path = root / "backend" / "modules" / key / (rel + ".py")
            dotted = ".".join(["modules", key] + rel.split("/"))
            mod = dotted[:-len(".__init__")] if dotted.endswith(".__init__") else dotted
            if path.is_file():
                out[mod] = path
    return out


def test_payroll_does_not_import_m06_anywhere():
    """M07 的每一支檔（modules.json 取）**任何一層**都不 import M06（2026-09-26：原本 bonus_pdf 在函式內延遲載入
    helpers.voucher／voucher_pdf，稽核 Y-2；現在那四樣都在 L1）。"""
    import ast
    m06 = set(_group_py_files("M06"))
    m07 = _group_py_files("M07")
    assert "modules.payroll.bonus_pdf" in m07 and "modules.payroll.api.bonus" in m07          # 正對照：真的掃到了
    bad = []
    for mod, path in m07.items():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module in m06:
                bad.append((mod, node.module))
            if isinstance(node, ast.Import):
                bad += [(mod, a.name) for a in node.names if a.name in m06]
    assert bad == [], bad


def test_the_page_shows_the_voucher_notice():
    """「畫面要明確告知」：API 帶了 voucherNotice，頁面必須真的綁上去，不然使用者看不到。"""
    from pathlib import Path
    html = (Path(__file__).resolve().parents[4] / "frontend" / "pages" / "bonus.html").read_text(encoding="utf-8")
    assert 'x-text="detail.voucherNotice"' in html


def test_payroll_pdf_parts_work_without_m06_files(tmp_path):
    """反向控制（實體缺席，不是只拿掉提供者）：子行程裡讓 M06 的兩個 helper 無法匯入，`modules.payroll.api.bonus` 照常載入，
    獎金分潤單預覽／PDF 用的四樣元件（L1）照樣拿得到（2026-09-26 之前這裡會說「會計模組未安裝」）。"""
    import subprocess
    import sys
    from pathlib import Path
    backend = Path(__file__).resolve().parents[3]
    code = (
        "import sys\n"
        "sys.modules['helpers.voucher'] = None\n"
        "sys.modules['helpers.voucher_pdf'] = None\n"
        "import modules.payroll.api.bonus as b\n"
        "from modules.payroll import bonus_pdf\n"
        "resolve, company, render, money = bonus_pdf._pdf_parts()\n"
        "print('PARTS:' + ','.join(f.__module__ for f in (resolve, company, render, money)))\n"
        "print('MONEY:' + money(1234) + '|' + money(0) + '|')\n"
        "print('ROUTES:%d' % len(b.router.routes))\n")
    r = subprocess.run([sys.executable, "-B", "-c", code], cwd=str(backend), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120,
                       env=dict(__import__("os").environ, PYTHONIOENCODING="utf-8"))
    assert r.returncode == 0, r.stderr[-2000:]
    assert "PARTS:helpers.tiered_approval,helpers.company_identity,pdf_gen,pdf_gen" in r.stdout, r.stdout
    assert "MONEY:1,234||" in r.stdout, r.stdout                          # 0 印空白（傳票同一條規則）
    assert int(r.stdout.split("ROUTES:")[1]) > 10


def test_preview_works_even_if_the_accounting_helpers_are_gone(client, people, monkeypatch):
    """M06 的 `helpers.voucher_pdf` 被拿掉（這裡以把它的函式換成會爆的替身模擬），獎金分潤單預覽照樣組得出來
    ——證明預覽走的是 L1，不是 M06。"""
    import helpers.voucher_pdf as vp
    from modules.payroll import bonus_pdf

    def _boom(*a, **k):
        raise AssertionError("不應該用到 M06 的 voucher_pdf")
    for name in ("_company_name", "_render", "_fmt_money"):
        monkeypatch.setattr(vp, name, _boom)
    html = bonus_pdf.build_award_html({"id": 1}, [], [], {}, "2026-09-25 00:00")
    assert isinstance(html, str) and html
