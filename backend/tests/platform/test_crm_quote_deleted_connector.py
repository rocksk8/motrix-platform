"""IP-13 `crm.quote_deleted` 取用方這一側（M01 刪報價單）：M02 不在時也要成立的題（M02 搬遷，2026-09-26）。

原本 M01 `modules/case/api/quotations.py` 直寫 `dev_cases`（table_write_exceptions 的 debt）⇒ 改由 M02 提供。
③ 反向控制：M02 不在 ⇒ 報價單照刪、案件不動、回應 notice 明說、記 WARNING
④ 產品碼除了 M02 與凍結 migration，沒有寫 dev_cases／dev_logs 的 SQL
提供方的登記與正對照在 `modules/crm/tests/test_crm_quote_deleted_provider.py`（隨模組搬走）。
"""
import logging
import re

import pytest

from core import registry
from core import source_tree  # noqa: E402

#: M01 ④(c)（主持裁示）：題目本身就是驗 M01（案件）的行為 ⇒ M01 不在的安裝包略過；理由逐題寫在 reason
def needs_case(reason):
    return pytest.mark.skipif(not source_tree.module_installed("modules/case/"),
                              reason="需要案件模組（M01）：" + reason)


QNO, OTHER = "MQ-IP11-0926", "MQ-IP11-OTHER"


def _login(client, make_user):
    u, p = make_user("ip11_super", "Conn-Pass-123", role="superadmin")[:2]
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _seed():
    import db
    conn = db.get_db()
    try:
        now = "2026-09-26T00:00:00"
        for q in (QNO, OTHER):
            conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
                         "data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                         (q, "草稿", "客", "案", 0, 0, "{}", now, now))
        for name, q in (("連到要刪的", QNO), ("連到別張", OTHER)):
            conn.execute("INSERT INTO dev_cases (case_name, customer_name, status, converted_quote_no, created_by, "
                         "created_at, updated_at) VALUES (?,?,?,?,?,?,?)", (name, "客", "成案", q, 1, now, now))
        conn.commit()
    finally:
        conn.close()


def _cases():
    import db
    conn = db.get_db()
    try:
        return {r["case_name"]: (r["converted_quote_no"], r["status"])
                for r in conn.execute("SELECT case_name, converted_quote_no, status FROM dev_cases")}
    finally:
        conn.close()


@needs_case('刪報價單的端點屬 M01')
def test_without_crm_the_quote_is_deleted_and_the_user_is_told(client, make_user, monkeypatch, caplog):
    h = _login(client, make_user)
    _seed()
    orig = registry.providers
    monkeypatch.setattr(registry, "providers", lambda cap: {} if cap == "crm.quote_deleted" else orig(cap))
    from modules.case.api import quotations
    with caplog.at_level(logging.WARNING):
        r = client.delete("/api/quotations/%s" % QNO, headers=h)
    assert r.status_code == 200 and r.json() == {"ok": True, "notice": quotations.QUOTE_DELETED_CRM_ABSENT}
    assert _cases() == {"連到要刪的": (QNO, "成案"), "連到別張": (OTHER, "成案")}
    assert any("業務開發模組未安裝" in rec.getMessage() for rec in caplog.records)
    assert client.get("/api/quotations/%s" % QNO, headers=h).status_code == 404


#: 正對照門檻（S1，2026-09-27）：~~一律 >50~~ ⇒ 依安裝狀態分兩個門檻。
#: 完整安裝實量 152 ⇒ 恢復嚴格的 >100（只放寬成 50 的話，掃描漏掉一半的模組檔照綠）；
#: 不是完整安裝（core-only 實量 85、單一模組產品介於兩者之間）⇒ >50。
SCAN_MIN_FULL, SCAN_MIN_PARTIAL = 100, 50


def install_verdict(backend=None, modules_json=None):
    """獨立訊號（§G5 #15）：modules.json 登記的模組 key 逐一看 `backend/modules/<key>/module.json` 在不在
    （與 module_installed 同一個「在」的判準：只剩 __pycache__ 的資料夾不算）。不看 product_files() 的掃描結果——
    略過／放寬的條件不可以取自被檢查的東西本身。⇒ ("full"|"core-only"|"partial", 理由)。"""
    import json
    from pathlib import Path
    backend = Path(backend or source_tree.BACKEND)
    modules_json = Path(modules_json or backend.parent / "docs" / "platform" / "modules.json")
    data = json.loads(modules_json.read_text(encoding="utf-8"))
    keys = sorted(g.get("key") for g in data.get("modules", {}).values() if g.get("key"))
    if not keys:
        raise AssertionError("modules.json 沒有登記任何模組 key（設定本身有問題，不判定成 core-only）")
    present = [k for k in keys if (backend / "modules" / k / "module.json").is_file()]
    if len(present) == len(keys):
        return "full", "modules.json 登記的 %d 個模組都在" % len(keys)
    if not present:
        return "core-only", "modules.json 登記的 %d 個模組全部不在" % len(keys)
    return "partial", "在：%s；不在：%s" % ("、".join(present), "、".join(sorted(set(keys) - set(present))))


def scan_minimum(verdict):
    return SCAN_MIN_FULL if verdict == "full" else SCAN_MIN_PARTIAL


def test_no_writes_to_dev_cases_outside_crm():
    from core import source_tree
    pat = re.compile(r"(UPDATE|INSERT\s+INTO|DELETE\s+FROM)\s+dev_(cases|logs)\b", re.I)
    hits, scanned = [], 0
    for p in source_tree.product_files():
        rel = source_tree.rel(p)
        if rel.startswith("modules/crm/") or rel == "db.py":        # 擁有者；db.py 是凍結 migration（CORE-SPEC §6）
            continue
        scanned += 1
        hits += ["%s: %s" % (rel, m.group(0)) for m in pat.finditer(p.read_text(encoding="utf-8"))]
    # 門檻依安裝狀態（獨立訊號）：完整安裝 >100、其他 >50（第十三班列車：core-only 只剩 L1，實量 85）
    verdict, why = install_verdict()
    assert scanned > scan_minimum(verdict), "只掃到 %d 個產品檔（%s：%s，門檻 >%d）：掃描壞了？" % (
        scanned, verdict, why, scan_minimum(verdict))
    assert not hits, hits


def test_rc_install_verdict_uses_module_folders_not_the_scan(tmp_path):
    """反向控制（沙盒）：判定只看 modules.json 登記＋module.json 在不在——
    全部在 ⇒ full（嚴格門檻：掃描壞掉只掃到 85 也要紅）；全部不在 ⇒ core-only；部分在 ⇒ partial；
    只剩 __pycache__ 的資料夾不算在；modules.json 沒登記任何模組 ⇒ 不可以判成 core-only。"""
    import json
    mj = tmp_path / "docs" / "platform" / "modules.json"
    mj.parent.mkdir(parents=True)
    mj.write_text(json.dumps({"modules": {"A": {"key": "a"}, "B": {"key": "b"}}}), encoding="utf-8")
    be = tmp_path / "backend"
    (be / "modules").mkdir(parents=True)
    assert install_verdict(be, mj)[0] == "core-only"
    (be / "modules" / "a" / "__pycache__").mkdir(parents=True)
    assert install_verdict(be, mj)[0] == "core-only", "只剩 __pycache__ 不算在"
    (be / "modules" / "a" / "module.json").write_text("{}", encoding="utf-8")
    assert install_verdict(be, mj)[0] == "partial"
    (be / "modules" / "b").mkdir()
    (be / "modules" / "b" / "module.json").write_text("{}", encoding="utf-8")
    assert install_verdict(be, mj)[0] == "full"
    assert not 85 > scan_minimum("full"), "完整安裝時只掃到 core-only 的量（85）要紅"
    assert 85 > scan_minimum("core-only") and 85 > scan_minimum("partial")
    mj.write_text(json.dumps({"modules": {}}), encoding="utf-8")
    with pytest.raises(AssertionError):
        install_verdict(be, mj)
