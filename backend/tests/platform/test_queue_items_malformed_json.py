"""`approval.queue_items` 通用契約：一筆簽核 JSON 讀不出來的單，不可以讓整類待簽消失，也不可以被列出（c-queue-json，主持指派 2026-09-27）。

背景：
- 提供者在 SQL 用 `json_extract(data_json,'$.approval')` ⇒ 一筆 malformed JSON 讓整個查詢丟例外 ⇒ 那一類全部不列
  （比 500 更難發現：佇列照常開、只是少了一整類）。
- 簽核鏈存在獨立欄位（`approval_json`／`change_approval_json`）的提供者走 `tier_fields`，它把壞 JSON 吞成 {} ⇒
  列給每個 superadmin、計角標，核准時才丟例外（稽核 D QJ-M1）。列出了也簽不了。

契約（對**每一個已註冊**的提供者逐一驗，不用原始碼特徵挑；以後新增的提供者自動受保護）：
- 它讀的每張表中，**有簽核 JSON 的**（`data_json`，或 `approval_json`／`change_approval_json` 欄）各塞：
  好的一筆（有一層待簽）、壞的一筆（簽核 JSON 讀不出來）；簽核在 data_json 的另塞一筆能解析、沒有 approval 的（合法的「沒有設定流程」）
- 呼叫提供者 ⇒ 不丟例外；好的與沒有流程的照列；壞的不列；有 ERROR log 寫出壞的那一筆的單號
- §G5 #13：有詳情提供者的類型，項目的 linkedQuoteNo 必須等於詳情的 quoteNo（佇列與詳情的權限輸入是同一個）
正對照：驗到的提供者數＝註冊數（沒有被略過的）；已知的幾個一定在。
反向控制：同一個檢查套在用 json_extract 的合成提供者上 ⇒ 必須報「丟例外」。
"""
import inspect
import json
import logging
import re

import pytest
from fastapi import HTTPException

from core import registry, source_tree

GOOD, BAD, NOFLOW = "AQJ-GOOD", "AQJ-BAD", "AQJ-NOFLOW"
APPROVAL_COLS = ("approval_json", "change_approval_json")
APPR = {"requestedBy": "aqj_req", "requestedByDisplay": "aqj_req", "requestedAt": "2026-09-27T09:00:00", "currentTier": 0,
        "tiers": [{"approvers": [{"username": "aqj_x", "displayName": "aqj_x", "status": "pending"}]}]}
#: 已知的提供者（名稱 → 擁有模組；None＝L1）。正對照：少了就是掃描壞了
EXPECTED = {"case": "case", "invoice_voucher": "arap", "payment_request": "arap", "subcontract": "subcontract",
            "shipping_note": "supply", "payroll": "payroll", "voucher": "accounting", "custom_modules": None}


def _tables(fn):
    return sorted(set(re.findall(r"\bFROM\s+([a-z_]+)", inspect.getsource(fn))))


def _cols(conn, t):
    return {r[1] for r in conn.execute("PRAGMA table_info(%s)" % t)}


def _mode(conn, fn, t):
    """這張表的簽核 JSON 在哪：'data'（data_json.approval）、'column'（approval 欄）、None（沒有）。"""
    cols = _cols(conn, t)
    if not ({"status", "change_status"} & cols):
        return None
    if set(APPROVAL_COLS) & cols:
        return "column"
    if "data_json" in cols and "data_json" in inspect.getsource(fn):
        return "data"
    return None


_SEQ = [900000]


def _seed(conn, table, token, mode, kind):
    """通用種資料：TEXT 欄＝token、*_json 欄＝'{}'、status／change_status＝待審核；簽核 JSON 依 kind（good／bad／noflow）；
    沒有預設的必填數值欄給每列不同的號碼（可能有 UNIQUE，例：承攬商匯款申請的 dispatch_id）。"""
    _SEQ[0] += 1
    good = json.dumps(APPR, ensure_ascii=False)
    names, vals = [], []
    for c in conn.execute("PRAGMA table_info(%s)" % table).fetchall():
        name, typ, notnull, default, pk = c[1], (c[2] or "").upper(), c[3], c[4], c[5]
        if pk and "INT" in typ:
            continue
        if name == "data_json":
            v = {"good": json.dumps({"approval": APPR}, ensure_ascii=False), "bad": "{not json",
                 "noflow": '{"x": 1}'}[kind] if mode == "data" else "{}"
        elif name in APPROVAL_COLS:
            v = {"good": good, "bad": "{broken", "noflow": "{}"}[kind] if mode == "column" else "{}"
        elif name in ("status", "change_status"):
            v = "待審核"
        elif name.endswith("_json"):
            v = "{}"
        elif "CHAR" in typ or "TEXT" in typ or typ == "":
            v = token
        elif notnull and default is None:
            v = _SEQ[0]
        else:
            continue
        names.append(name)
        vals.append(v)
    conn.execute("INSERT INTO %s (%s) VALUES (%s)" % (table, ",".join(names), ",".join("?" * len(names))), vals)


def _has(items, token):
    return [it for it in items if token in json.dumps(it, ensure_ascii=False)]


def _detail(prov, conn, item):
    """詳情用的 id：quoteNo，或項目上的 *Id（例：額外支出 extraExpenseId）——同 approval-queue.html itemPathId。"""
    for cand in [item.get("quoteNo")] + [v for k, v in item.items() if k.endswith("Id") and v]:
        try:
            d = prov(conn, str(cand))
        except HTTPException:
            d = None
        if d:
            return d
    return None


def check_provider(conn, name, fn, caplog, tables=None):
    """⇒ 問題清單（空＝符合契約）。"""
    tables = [(t, _mode(conn, fn, t)) for t in (tables or _tables(fn))]
    tables = [(t, m) for t, m in tables if m]
    if not tables:
        return ["%s：讀的表都沒有簽核 JSON 欄（沒有驗到任何東西）" % name]
    for t, m in tables:
        _seed(conn, t, "%s-%s" % (GOOD, t), m, "good")
        _seed(conn, t, "%s-%s" % (BAD, t), m, "bad")
        if m == "data":
            _seed(conn, t, "%s-%s" % (NOFLOW, t), m, "noflow")
    caplog.clear()
    try:
        items = fn(conn) or []
    except Exception as e:                                    # noqa: BLE001
        return ["%s：一筆壞簽核 JSON 讓整個提供者丟例外（%s: %s）⇒ 整類待簽消失" % (name, type(e).__name__, e)]
    out = []
    details = registry.providers("approval.detail")
    for it in _has(items, GOOD):
        if it.get("type") in details:
            d = _detail(details[it["type"]], conn, it)
            if not d or (d.get("quoteNo") or "") != (it.get("linkedQuoteNo") or ""):
                out.append("%s：%s 項目 linkedQuoteNo=%r 而詳情 quoteNo=%r（佇列與詳情的權限輸入不一致）"
                           % (name, it.get("quoteNo"), it.get("linkedQuoteNo"), (d or {}).get("quoteNo")))
    for t, m in tables:
        if not _has(items, "%s-%s" % (GOOD, t)):
            out.append("%s：%s 好的那一筆沒有列出" % (name, t))
        if m == "data" and not _has(items, "%s-%s" % (NOFLOW, t)):
            out.append("%s：%s 能解析、沒有流程的那一筆被跳過（它是合法的「沒有設定流程」）" % (name, t))
        if _has(items, "%s-%s" % (BAD, t)):
            out.append("%s：%s 壞的那一筆被列出（列出了也簽不了）" % (name, t))
        bad_nos = {"%s-%s" % (BAD, t)} | {str(r[0]) for r in conn.execute(
            "SELECT rowid FROM %s WHERE %s" % (t, " OR ".join("%s='%s-%s'" % (c, BAD, t)
                                                               for c in _cols(conn, t) if c not in ("data_json",) + APPROVAL_COLS
                                                               and not c.endswith("_json") and c not in ("status", "change_status"))
                                                or "0"))}
        if not any(r.levelno >= logging.ERROR and any(("%s " % no) in r.getMessage() or r.getMessage().endswith(no)
                                                      or ("%s-%s" % (BAD, t)) in r.getMessage() for no in bad_nos)
                   for r in caplog.records):
            out.append("%s：%s 壞的那一筆沒有 ERROR log（寫單號）" % (name, t))
    return out


@pytest.fixture
def custom_defs(monkeypatch):
    """自訂模組引擎要有已發布定義、而且狀態有簽核才會列；通用種資料不建定義 ⇒ 這裡給一份（只影響佇列提供者）。"""
    import helpers.custom_modules as cm
    monkeypatch.setattr(cm, "_load_def", lambda conn, key, ver: {"body": {"name": "契約題"}})
    monkeypatch.setattr(cm, "_state", lambda body, status: {"approval": True, "label": status})


def test_every_provider_survives_one_malformed_row(client, caplog, custom_defs):
    import db
    caplog.set_level(logging.ERROR)
    provs = registry.providers("approval.queue_items")
    want = {n for n, key in EXPECTED.items() if key is None or source_tree.module_installed("modules/%s/" % key)}
    assert want <= set(provs), ("已知的提供者沒有註冊（正對照）", sorted(want - set(provs)))
    problems, checked = [], []
    for name, fn in sorted(provs.items()):
        conn = db.get_db()
        conn.execute("PRAGMA foreign_keys=OFF")    # 通用種資料不建上游列（例：承攬商匯款申請的派工單）；整批 rollback，不留資料
        try:
            problems += check_provider(conn, name, fn, caplog)
            checked.append(name)
        finally:
            conn.rollback()
            conn.close()
    assert len(checked) == len(provs), ("有提供者沒有驗到（正對照：驗到的數＝註冊數）", sorted(set(provs) - set(checked)))
    assert not problems, "\n".join(problems)


def test_reverse_control_json_extract_provider_is_caught(client, caplog):
    """反向控制：用 json_extract 的合成提供者 ⇒ 檢查必須報「丟例外」（檢查本身不是空的）。"""
    import db
    caplog.set_level(logging.ERROR)
    conn = db.get_db()
    try:
        table = next(t for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
                     if {"data_json", "status"} <= _cols(conn, t) and not (set(APPROVAL_COLS) & _cols(conn, t)))
        src = ("def fake(conn):\n"
               "    # data_json\n"
               "    rows = conn.execute(\"SELECT json_extract(data_json,'$.approval') AS a FROM %s "
               "WHERE status IN ('待審核','簽核中')\").fetchall()\n"
               "    return [{'quoteNo': 'x'} for r in rows]\n" % table)
        ns = {}
        exec(compile(src, "<json_extract 提供者>", "exec"), ns)
        fake = ns["fake"]
        orig = inspect.getsource
        inspect.getsource = lambda fn: src if fn is fake else orig(fn)       # exec 的函式讀不到源碼
        try:
            problems = check_provider(conn, "json_extract_fake", fake, caplog, tables=[table])
        finally:
            inspect.getsource = orig
    finally:
        conn.rollback()
        conn.close()
    assert problems and "丟例外" in problems[0], problems


def test_reverse_control_tier_fields_swallowing_is_caught(client, caplog):
    """反向控制（QJ-M1）：把壞的欄位 JSON 直接丟給 tier_fields 的合成提供者（壞的吞成沒有簽核層、照列）⇒ 檢查必須報「壞的被列出」。"""
    import db
    from helpers import approval_queue as aq
    caplog.set_level(logging.ERROR)
    conn = db.get_db()
    try:
        table = next(t for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
                     if {"approval_json", "status"} <= _cols(conn, t) and "change_status" not in _cols(conn, t))
        key = next(c for c in ("voucher_no", "record_no", "quote_no") if c in _cols(conn, table))

        def fake(conn):
            return [aq.base_item("fake", r[key], aq.tier_fields(r["approval_json"])) for r in conn.execute(
                "SELECT %s, approval_json FROM %s WHERE status IN ('待審核','簽核中')" % (key, table)).fetchall()]
        problems = check_provider(conn, "tier_fields_fake", fake, caplog, tables=[table])
    finally:
        conn.rollback()
        conn.close()
    assert any("壞的那一筆被列出" in p for p in problems), problems


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_expected_providers_read_approval_in_python(client, name):
    """靜態補強：已知的提供者源碼不可以出現**沒有 json_valid 保護**的 json_extract(data_json,…)。

    2026-09-30（W3 approval-freeze，主持裁示）：原本一律禁止；待簽佇列 200 張×60KB 時逐筆 json.loads 佔 441 ms，
    案件提供者改由 SQLite 取 `$.approval`——但**只有**巢狀 `CASE WHEN json_valid(data_json) THEN … json_extract(…)` 的形式：
    壞 JSON 得到 NULL 而不是例外，NULL 再退回 Python 逐筆解析（語意不變）。行為由本檔其他題（壞 JSON 不消失、壞的那一筆不被列出）
    與 test_approval_no_freeze 的逐形狀等價題守；這一題只擋「沒有保護的寫法」。登記見 json_extract_baseline_reasons.md。"""
    fn = registry.providers("approval.queue_items").get(name)
    if fn is None:
        pytest.skip("%s 的模組不在這個安裝包" % name)
    src = inspect.getsource(fn)
    for m in re.finditer(r"json_extract\(data_json", src):
        assert "json_valid(data_json)" in src[max(0, m.start() - 400):m.start()], (
            "%s：json_extract(data_json…) 前面沒有 json_valid(data_json) 的保護（壞一筆 JSON 會讓整個查詢丟例外、整類待簽消失）" % name)
