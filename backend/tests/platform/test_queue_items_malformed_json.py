"""`approval.queue_items` 通用契約：一筆壞掉的 data_json 不可以讓整類待簽消失（c-queue-json，主持指派 2026-09-27）。

背景：提供者在 SQL 用 `json_extract(data_json,'$.approval')` ⇒ 一筆 malformed JSON 讓整個查詢丟例外 ⇒ L1 只記一筆
exception、那一類全部不列（比 500 更難發現：佇列照常開、只是少了一整類）。

契約（對**每一個已註冊**、簽核鏈存在 data_json 的提供者，逐一驗；以後新增的提供者自動受保護）：
- 它讀的每張有 `data_json`＋`status` 的表，各塞一筆好的、一筆壞的（`{not json`），狀態「待審核」
- 呼叫提供者 ⇒ 不丟例外；好的那一筆照列；壞的那一筆不列；有一筆 ERROR log 寫出壞的那一筆的單號
反向控制：同一個檢查套在一個用 `json_extract` 的合成提供者上 ⇒ 必須報錯（檢查本身不是空的）。
正對照：實際掃到的提供者包含已安裝模組的那幾個（掃不到 ⇒ 這題永遠是空的綠）。
"""
import inspect
import logging
import re

import pytest

from core import registry, source_tree

GOOD, BAD = "AQJ-GOOD", "AQJ-BAD"
#: 已知簽核鏈在 data_json 的提供者（名稱 → 擁有模組；None＝L1）。正對照用：少了就是掃描壞了
EXPECTED = {"case": "case", "invoice_voucher": "arap", "payment_request": "arap",
            "subcontract": "subcontract", "shipping_note": "supply"}


def _tables(fn):
    return sorted(set(re.findall(r"\bFROM\s+([a-z_]+)", inspect.getsource(fn))))


def _reads_data_json(fn):
    src = inspect.getsource(fn)
    return "data_json" in src


def _seed(conn, table, token, data_json):
    """通用種資料：TEXT 欄＝token（*_json 欄＝'{}'）、status＝待審核、data_json＝指定值；數值欄用預設或 0。"""
    cols = conn.execute("PRAGMA table_info(%s)" % table).fetchall()
    names, vals = [], []
    for c in cols:
        name, typ, notnull, default, pk = c[1], (c[2] or "").upper(), c[3], c[4], c[5]
        if pk and "INT" in typ:
            continue
        if name == "data_json":
            v = data_json
        elif name == "status":
            v = "待審核"
        elif name.endswith("_json"):
            v = "{}"
        elif "CHAR" in typ or "TEXT" in typ or typ == "":
            v = token
        elif notnull and default is None:
            v = 0
        else:
            continue
        names.append(name)
        vals.append(v)
    conn.execute("INSERT INTO %s (%s) VALUES (%s)" % (table, ",".join(names), ",".join("?" * len(names))), vals)


def check_provider(conn, name, fn, caplog):
    """⇒ 問題清單（空＝符合契約）。"""
    tables = [t for t in _tables(fn)
              if {"data_json", "status"} <= {r[1] for r in conn.execute("PRAGMA table_info(%s)" % t)}]
    if not tables:
        return ["%s：讀的表沒有 data_json＋status（掃描沒有對象）" % name]
    for t in tables:
        _seed(conn, t, "%s-%s" % (GOOD, t), "{}")
        _seed(conn, t, "%s-%s" % (BAD, t), "{not json")
    caplog.clear()
    try:
        items = fn(conn) or []
    except Exception as e:                                    # noqa: BLE001
        return ["%s：一筆壞 data_json 讓整個提供者丟例外（%s: %s）⇒ 整類待簽消失" % (name, type(e).__name__, e)]
    got = {it.get("quoteNo") for it in items}
    out = []
    for t in tables:
        if "%s-%s" % (GOOD, t) not in got:
            out.append("%s：%s 好的那一筆沒有列出" % (name, t))
        if "%s-%s" % (BAD, t) in got:
            out.append("%s：%s 壞的那一筆被列出（當成沒有簽核層＝任一 superadmin 可簽，是降級）" % (name, t))
        if not any(r.levelno >= logging.ERROR and ("%s-%s" % (BAD, t)) in r.getMessage() for r in caplog.records):
            out.append("%s：%s 壞的那一筆沒有 ERROR log（寫單號）" % (name, t))
    return out


def _data_json_providers():
    return {n: f for n, f in registry.providers("approval.queue_items").items() if _reads_data_json(f)}


def test_every_data_json_provider_survives_one_malformed_row(client, caplog):
    import db
    caplog.set_level(logging.ERROR)
    provs = _data_json_providers()
    want = {n for n, key in EXPECTED.items() if source_tree.module_installed("modules/%s/" % key)}
    assert want <= set(provs), ("掃不到的提供者（正對照）", sorted(want - set(provs)))
    problems = []
    for name, fn in sorted(provs.items()):
        conn = db.get_db()
        try:
            problems += check_provider(conn, name, fn, caplog)
        finally:
            conn.rollback()
            conn.close()
    assert not problems, "\n".join(problems)


def test_reverse_control_json_extract_provider_is_caught(client, caplog):
    """反向控制：用 json_extract 的合成提供者（讀 L1 自己也有的 payment_requests 表結構無關——用 quotations 以外的一張：
    任一張有 data_json＋status 的表）⇒ 檢查必須報「丟例外」。"""
    import db
    caplog.set_level(logging.ERROR)
    conn = db.get_db()
    try:
        table = next(t for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
                     if {"data_json", "status"} <= {r[1] for r in conn.execute("PRAGMA table_info(%s)" % t)})
        src = ("def fake(conn):\n"
               "    rows = conn.execute(\"SELECT json_extract(data_json,'$.approval') AS a FROM %s "
               "WHERE status IN ('待審核','簽核中')\").fetchall()\n"
               "    return [{'quoteNo': 'x'} for r in rows]\n" % table)
        ns = {}
        exec(compile(src, "<json_extract 提供者>", "exec"), ns)
        fake = ns["fake"]
        # inspect.getsource 讀不到 exec 的函式 ⇒ 表名直接給
        orig = globals()["_tables"]
        globals()["_tables"] = lambda fn: [table] if fn is fake else orig(fn)
        try:
            problems = check_provider(conn, "json_extract_fake", fake, caplog)
        finally:
            globals()["_tables"] = orig
    finally:
        conn.rollback()
        conn.close()
    assert problems and "丟例外" in problems[0], problems


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_expected_providers_read_approval_in_python(client, name):
    """靜態補強：已知的提供者源碼不可以再出現 json_extract(data_json,'$.approval')。"""
    fn = registry.providers("approval.queue_items").get(name)
    if fn is None:
        pytest.skip("%s 的模組不在這個安裝包" % name)
    assert "json_extract(data_json" not in inspect.getsource(fn), name
