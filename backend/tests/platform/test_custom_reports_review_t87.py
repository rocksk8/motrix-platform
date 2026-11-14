# -*- coding: utf-8 -*-
"""T87 B2：h11 審查 c7c834664 的四項修正（①分享定義去識別 ②型別／範圍驗證 ③選項套列範圍＋快取 ④並行上限）與回收筒遮罩。

- ① 被分享者讀到的定義：沒有權限看的欄位連同它的篩選門檻、分組、彙總、排序都不回傳，只回 `partiallyHidden`；執行仍用讀者自己的權限。
- ② 任何型別錯誤的定義在建立／更新／複製／預覽都是 422，不是 500。
- ③ `/sources` 的列舉選項只含呼叫者看得到的列的值，且每人快取。
- ④ 預覽與匯出共用全程式庫並行名額，滿了 429。
"""
import json
import threading

import pytest

from db import get_db
from helpers import auth
from helpers import settings_registry as R
from modules.analytics.api import custom_reports as CR
from modules.case import report_source as CRS

BASE = "/api/custom-reports"
MAGIC = 5123456


def _login(client, make_user, name, role="sales", modules=None):
    kw = {"username": name, "role": role}
    if modules is not None:
        kw["modules"] = modules
    u, p = make_user(**kw)
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _set(**kv):
    c = get_db()
    try:
        R.publish("custom_reports", kv, reason="測試", user="sa_rv", conn=c)
    finally:
        c.close()
    R.invalidate()


@pytest.fixture(autouse=True)
def _on(client):
    CR.reset_rate_limit()
    CRS._OPT_CACHE.clear()
    _set(enabled=1, sharing=1)
    yield
    CRS._OPT_CACHE.clear()
    R.invalidate()


def _quote(**kw):
    row = {"quote_no": "RV-%s" % kw.pop("no", "1"), "status": "草稿", "customer_name": "RV客戶", "project_name": "專案", "total": 0, "pretax": 0,
           "data_json": "{}", "created_at": "2026-11-14T09:00:00", "updated_at": "2026-11-14T09:00:00", "deal_tag": "",
           "sales_person": "", "assigned_user_ids": "[]"}
    row.update(kw)
    c = get_db()
    try:
        cols = list(row)
        c.execute("INSERT INTO quotations (%s) VALUES (%s)" % (",".join(cols), ",".join("?" * len(cols))), [row[k] for k in cols])
        c.commit()
    finally:
        c.close()


def _rich():
    return {"version": 1, "source": "quotation", "columns": ["quote_no", "customer_name", "total"],
            "filters": [{"field": "total", "op": "gte", "value": MAGIC}, {"field": "customer_name", "op": "contains", "value": "RV"}],
            "sort": [{"field": "total", "dir": "desc"}]}


def _shared_pair(client, make_user, tag, definition=None):
    owner = _login(client, make_user, "rv_o_" + tag, role="superadmin")
    eng = _login(client, make_user, "rv_e_" + tag, role="engineer", modules=["quotation"])
    rep = client.post(BASE, json={"name": "共享", "definition": definition or _rich()}, headers=owner)
    assert rep.status_code == 201, rep.text
    rep = rep.json()
    r = client.put("%s/%d" % (BASE, rep["id"]), json={"sharedWith": ["rv_e_" + tag]}, headers=dict(owner, **{"If-Match": rep["etag"]}))
    assert r.status_code == 200, r.text
    return owner, eng, rep["id"]


# ── ① 分享定義去識別 ───────────────────────────────────────────────────────

def test_shared_reader_without_financial_access_never_receives_the_threshold_or_the_field(client, make_user):
    owner, eng, rid = _shared_pair(client, make_user, "a")
    mine = client.get("%s/%d" % (BASE, rid), headers=owner).json()
    assert str(MAGIC) in json.dumps(mine) and "partiallyHidden" not in mine                 # 正對照：擁有者看得到完整定義
    r = client.get("%s/%d" % (BASE, rid), headers=eng)
    assert r.status_code == 200
    body = r.json()
    assert str(MAGIC) not in r.text and body["partiallyHidden"] is True and body["isOwner"] is False
    d = body["definition"]
    assert d["columns"] == ["quote_no", "customer_name"]
    assert d["filters"] == [{"field": "customer_name", "op": "contains", "value": "RV"}]    # 看得到的欄位的條件照留
    assert d["sort"] == []
    assert "total" not in json.dumps(d)


def test_shared_reader_runs_with_own_permission_and_the_money_column_is_dropped(client, make_user):
    _quote(no="1", total=MAGIC, customer_name="RV客戶")
    owner, eng, rid = _shared_pair(client, make_user, "b", {"version": 1, "source": "quotation", "columns": ["quote_no", "total"]})
    ru = client.post(BASE + "/preview", json=client.get("%s/%d" % (BASE, rid), headers=eng).json()["definition"], headers=eng)
    assert ru.status_code == 200
    assert [c["label"] for c in ru.json()["columns"]] == ["報價單號"] and str(MAGIC) not in ru.text
    # 用原始定義（含金額欄）以讀者自己的權限跑：金額欄被拿掉並回報隱藏
    raw = client.post(BASE + "/preview", json={"version": 1, "source": "quotation", "columns": ["quote_no", "total"]}, headers=eng)
    assert raw.status_code == 200 and raw.json()["hiddenCount"] == 1 and str(MAGIC) not in raw.text
    # 有金額權限的擁有者：正對照，真的看得到
    ow = client.post(BASE + "/preview", json={"version": 1, "source": "quotation", "columns": ["quote_no", "total"]}, headers=owner)
    assert str(MAGIC) in ow.text


def test_copy_is_refused_when_conditions_would_be_dropped_but_allowed_for_display_only_loss(client, make_user):
    owner, eng, rid = _shared_pair(client, make_user, "c")
    r = client.post("%s/%d/copy" % (BASE, rid), headers=eng)
    assert r.status_code == 422 and r.json()["detail"]["reason"] == "partially_hidden" and str(MAGIC) not in r.text
    owner2, eng2, rid2 = _shared_pair(client, make_user, "d", {"version": 1, "source": "quotation", "columns": ["quote_no", "total"]})
    r2 = client.post("%s/%d/copy" % (BASE, rid2), headers=eng2)
    assert r2.status_code == 201 and r2.json()["definition"]["columns"] == ["quote_no"]


def test_reader_without_the_source_module_gets_only_the_source_id(client, make_user):
    owner, _eng, rid = _shared_pair(client, make_user, "e")
    nom = _login(client, make_user, "rv_nom_e", role="sales", modules=["dev_crm"])
    c = get_db()
    try:
        c.execute("INSERT INTO custom_report_shares (report_id, shared_with, created_at) VALUES (?,?,?)", (rid, "rv_nom_e", "2026-11-14T10:00:00"))
        c.commit()
    finally:
        c.close()
    r = client.get("%s/%d" % (BASE, rid), headers=nom)
    assert r.status_code == 200 and str(MAGIC) not in r.text and r.json()["definition"] == {"version": 1, "source": "quotation"}


# ── ② 型別與範圍驗證 ───────────────────────────────────────────────────────

BAD = [
    {"version": 1, "source": "quotation", "columns": ["quote_no"], "aggregates": [{"field": "total", "fn": ["sum"]}]},
    {"version": 1, "source": "quotation", "columns": ["quote_no"], "aggregates": [{"field": ["total"], "fn": "sum"}]},
    {"version": 1, "source": "quotation", "columns": ["quote_no"], "aggregates": [{"field": "total", "fn": {}}]},
    {"version": 1, "source": "quotation", "columns": ["quote_no"], "filters": [{"field": "total", "op": "gte", "value": 10 ** 30}]},
    {"version": 1, "source": "quotation", "columns": ["quote_no"], "filters": [{"field": "total", "op": ["gte"], "value": 1}]},
    {"version": 1, "source": "quotation", "columns": ["quote_no"], "filters": [{"field": "total", "op": "between", "value": [1, 10 ** 40]}]},
    {"version": 1, "source": "quotation", "columns": ["quote_no"], "groupBy": [{"field": ["customer_name"]}]},
    {"version": 1, "source": "quotation", "columns": ["quote_no"], "sort": [{"field": "quote_no", "dir": ["asc"]}]},
    {"version": 1, "source": "quotation", "columns": [["quote_no"]]},
    {"version": 1, "source": ["quotation"], "columns": ["quote_no"]},
    {"version": 1, "source": "quotation", "columns": ["quote_no"], "layout": ["detail"]},
    {"version": 1, "source": "quotation", "columns": ["quote_no"], "groupBy": [{"field": "quote_date", "bucket": ["month"]}]},
]


@pytest.mark.parametrize("bad", range(len(BAD)))
def test_malformed_definitions_are_422_on_create_update_copy_and_preview_never_500(client, make_user, bad):
    h = _login(client, make_user, "rv_bad_%d" % bad, role="superadmin")
    d = BAD[bad]
    assert client.post(BASE, json={"name": "壞", "definition": d}, headers=h).status_code == 422
    assert client.post(BASE + "/preview", json=d, headers=h).status_code == 422
    ok = client.post(BASE, json={"name": "好", "definition": {"version": 1, "source": "quotation", "columns": ["quote_no"]}}, headers=h).json()
    r = client.put("%s/%d" % (BASE, ok["id"]), json={"definition": d}, headers=dict(h, **{"If-Match": ok["etag"]}))
    assert r.status_code == 422, r.text


def test_error_messages_do_not_echo_user_supplied_identifiers(client, make_user):
    h = _login(client, make_user, "rv_echo", role="superadmin")
    secret = "SECRET_FIELD_77"
    for d in ({"version": 1, "source": "quotation", "columns": ["quote_no"], "filters": [{"field": secret, "op": "eq", "value": "x"}]},
              {"version": 1, "source": "quotation", "columns": ["quote_no"], "sort": [{"field": secret, "dir": "asc"}]},
              {"version": 1, "source": "quotation", "columns": ["quote_no", secret]},
              {"version": 1, "source": "quotation", "columns": ["quote_no"], "aggregates": [{"field": secret, "fn": "sum"}]}):
        r = client.post(BASE + "/preview", json=d, headers=h)
        assert secret not in r.text, r.text


def test_definition_size_is_measured_in_bytes(client, make_user):
    h = _login(client, make_user, "rv_bytes", role="superadmin")
    d = {"version": 1, "source": "quotation", "columns": ["quote_no"],
         "filters": [{"field": "customer_name", "op": "in", "value": ["客" * 190] * 20}]}
    assert len(json.dumps(d, ensure_ascii=False)) < 8192 < len(json.dumps(d, ensure_ascii=False).encode("utf-8"))
    assert client.post(BASE + "/preview", json=d, headers=h).status_code == 422


# ── ③ 選項套列範圍＋快取 ───────────────────────────────────────────────────

def _opts(client, h, field="deal_tag"):
    src = next(s for s in client.get(BASE + "/sources", headers=h).json()["sources"] if s["id"] == "quotation")
    return [o[0] for o in next(f for f in src["fields"] if f["id"] == field)["options"]]


def test_enum_options_come_only_from_rows_the_caller_can_see(client, make_user):
    h = _login(client, make_user, "rv_opt_s", role="sales", modules=["quotation", "case_manage"])
    uid = auth._require_user(h["Authorization"])["id"]
    oh = _login(client, make_user, "rv_opt_other", role="sales", modules=["quotation", "case_manage"])
    other_id = auth._require_user(oh["Authorization"])["id"]
    _quote(no="o1", deal_tag="我的標記", sales_person_id=uid, status="我的狀態")
    _quote(no="o2", deal_tag="別人的機密標記", sales_person_id=other_id, status="別人的狀態")
    sa = _login(client, make_user, "rv_opt_sa", role="superadmin")
    assert "我的標記" in _opts(client, h) and "別人的機密標記" not in _opts(client, h)
    assert "別人的狀態" not in _opts(client, h, "status")
    assert "別人的機密標記" in _opts(client, sa)                                           # 正對照：能看全部的人看得到


def test_enum_options_are_cached_per_user_and_do_not_touch_data_json(client, make_user, monkeypatch):
    sa = _login(client, make_user, "rv_opt_c", role="superadmin")
    _quote(no="c1", deal_tag="快取A")
    assert "快取A" in _opts(client, sa)
    _quote(no="c2", deal_tag="快取B")
    assert "快取B" not in _opts(client, sa)                                               # TTL 內不重查
    CRS._OPT_CACHE.clear()
    assert "快取B" in _opts(client, sa)
    seen = []
    c = get_db()
    try:
        c.set_trace_callback(seen.append)
        CRS._distinct_options("deal_tag")(c, {"id": 1, "role": "superadmin", "username": "x"})
    finally:
        c.close()
    assert seen and not any("json_extract" in s or "data_json" in s for s in seen)


def test_options_without_a_user_fail_closed():
    assert CRS._distinct_options("deal_tag")(None, None) == []


# ── ④ 並行上限 ─────────────────────────────────────────────────────────────

def test_concurrent_run_cap_returns_429_with_a_plain_message_and_releases_the_slot(client, make_user, monkeypatch):
    h = _login(client, make_user, "rv_cap", role="superadmin")
    sem = threading.BoundedSemaphore(1)
    monkeypatch.setattr(CR, "_runs", sem)
    d = {"version": 1, "source": "quotation", "columns": ["quote_no"]}
    sem.acquire()
    r = client.post(BASE + "/preview", json=d, headers=h)
    assert r.status_code == 429 and r.json()["detail"]["reason"] == "busy" and "請等幾秒" in r.json()["detail"]["message"]
    sem.release()
    assert client.post(BASE + "/preview", json=d, headers=h).status_code == 200
    assert client.post(BASE + "/preview", json=d, headers=h).status_code == 200            # 歸還了：連續兩次都過（沒有洩漏名額）
    bad = dict(d, columns=["nope"])
    assert client.post(BASE + "/preview", json=bad, headers=h).status_code == 422
    assert sem.acquire(blocking=False) is True                                             # 失敗路徑也有歸還
    sem.release()


# ── 回收筒不顯示定義 ───────────────────────────────────────────────────────

def test_recycle_bin_detail_does_not_show_the_definition(client, make_user):
    _set(recycle_deleted=1)
    owner = _login(client, make_user, "rv_bin_o", role="superadmin")
    rep = client.post(BASE, json={"name": "含門檻", "definition": _rich()}, headers=owner).json()
    assert client.delete("%s/%d" % (BASE, rep["id"]), headers=owner).status_code == 200
    items = [x for x in client.get("/api/recycle-bin", headers=owner).json()["items"] if x["entityType"] == "custom_report"]
    det = client.get("/api/recycle-bin/%d" % items[0]["id"], headers=owner)
    assert det.status_code == 200 and str(MAGIC) not in det.text and "回收筒顯示" in det.text
