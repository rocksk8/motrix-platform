# -*- coding: utf-8 -*-
"""U0a 洩漏防線：單位鍵內部欄位（owner_unit_id／unit_id／legal_entity_id）不得出現在 JSON 回應、不得影響內容雜湊；org_units 啟用判斷嚴格（已宣告且 open）。"""
import asyncio
import json
import sqlite3

import pytest

from core import internal_cols as IC
from core import spine
from core import upgrade


# ── 剝除函式 ──────────────────────────────────────────────────────────────────────────

def test_constants_are_exactly_the_agreed_names():
    assert IC.INTERNAL_COLS == ("owner_unit_id", "unit_id", "legal_entity_id")


def test_strip_internal_cols_is_recursive_and_returns_same_object_when_clean():
    clean = {"a": 1, "b": [{"c": 2}], "d": (1, {"e": 3})}
    assert IC.strip_internal_cols(clean) is clean
    dirty = {"id": 1, "owner_unit_id": 1, "items": [{"id": 2, "unit_id": 1, "x": {"legal_entity_id": 9, "ok": 1}}], "t": ({"unit_id": 1},)}
    assert IC.strip_internal_cols(dirty) == {"id": 1, "items": [{"id": 2, "x": {"ok": 1}}], "t": ({},)}
    assert "owner_unit_id" in dirty                                  # 不改動原物件
    assert IC.strip_internal_cols([{"unit_id": 1}, 5, "unit_id"]) == [{}, 5, "unit_id"]       # 值（字串）不動，只動鍵


def test_strip_row_and_headers():
    assert IC.strip_row({"id": 1, "owner_unit_id": 1}) == {"id": 1}
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("create table t (id integer, owner_unit_id integer default 1, name text)")
    c.execute("insert into t (id, name) values (1, 'a')")
    assert IC.strip_row(c.execute("select * from t").fetchone()) == {"id": 1, "name": "a"}
    assert IC.strip_headers(["id", "unit_id", "名稱", "legal_entity_id"]) == ["id", "名稱"]
    assert IC.is_internal("unit_id") and not IC.is_internal("unit") and not IC.is_internal(None)


# ── 中介層（純 ASGI）─────────────────────────────────────────────────────────────────

def _run(app_fn, path="/x"):
    """用最小 ASGI 呼叫中介層，回 (status, headers dict, body bytes, 送出的 body 訊息數)。"""
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(m):
        sent.append(m)

    mw = IC.InternalColsMiddleware(app_fn)
    asyncio.run(mw({"type": "http", "path": path, "headers": []}, receive, send))
    start = sent[0]
    body = b"".join(m.get("body", b"") for m in sent[1:])
    return start["status"], {k.lower(): v for k, v in start["headers"]}, body, len(sent) - 1


def _app(body_parts, ctype=b"application/json", length=True, extra=()):
    async def app(scope, receive, send):
        total = b"".join(body_parts)
        h = [(b"content-type", ctype)] + list(extra)
        if length:
            h.append((b"content-length", str(len(total)).encode()))
        await send({"type": "http.response.start", "status": 200, "headers": h})
        for i, p in enumerate(body_parts):
            await send({"type": "http.response.body", "body": p, "more_body": i < len(body_parts) - 1})
    return app


def test_middleware_strips_json_keys_and_fixes_content_length():
    raw = json.dumps({"rows": [{"id": 1, "owner_unit_id": 1, "名稱": "甲"}], "unit_id": 3}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    st, h, body, _ = _run(_app([raw[:10], raw[10:]]))
    assert st == 200 and json.loads(body) == {"rows": [{"id": 1, "名稱": "甲"}]}
    assert int(h[b"content-length"]) == len(body) and b"unit_id" not in body


def test_middleware_fast_path_passes_clean_json_byte_for_byte():
    raw = '{"rows":[{"id":1,"名稱":"甲"}]}'.encode("utf-8")
    st, h, body, _ = _run(_app([raw]))
    assert body == raw and int(h[b"content-length"]) == len(raw)


@pytest.mark.parametrize("kw", [
    dict(ctype=b"application/pdf"), dict(ctype=b"text/csv"), dict(ctype=b"application/octet-stream"),
    dict(extra=[(b"content-encoding", b"gzip")]), dict(length=False)])
def test_middleware_leaves_non_json_compressed_and_unsized_bodies_alone(kw):
    raw = b'{"owner_unit_id":1}'                       # 即使內容長得像，非 JSON／壓縮／串流都不碰、不緩衝
    parts = [raw[:5], raw[5:]]
    st, h, body, nmsgs = _run(_app(parts, **kw))
    assert body == raw and nmsgs == 2                   # 逐塊原樣轉送（沒有被合併成一塊）


def test_middleware_oversize_json_is_passed_through_and_logged(monkeypatch, caplog):
    import logging
    monkeypatch.setattr(IC, "_MAX_BODY", 8)
    raw = b'{"owner_unit_id":1}'
    with caplog.at_level(logging.ERROR, logger="motrix.internal_cols"):
        st, h, body, _ = _run(_app([raw]))
    assert body == raw and any("無法緩衝" in r.getMessage() for r in caplog.records)


def test_middleware_unparsable_json_with_needle_passes_through():
    raw = b'{"owner_unit_id": 1, broken'
    st, h, body, _ = _run(_app([raw]))
    assert body == raw


def test_middleware_ignores_non_http_scopes():
    called = []

    async def app(scope, receive, send):
        called.append(scope["type"])
    asyncio.run(IC.InternalColsMiddleware(app)({"type": "websocket"}, None, None))
    assert called == ["websocket"]


def test_main_app_registers_the_middleware_last(client):
    """最後加入＝最外層，看到最終本文；正對照：若被拿掉，下一題的整合測試也會紅。（用 client 夾具，確保 main 在檔案路徑被隔離之後才匯入）"""
    import main
    assert main.app.user_middleware[0].cls is IC.InternalColsMiddleware


def test_real_app_never_returns_internal_columns(client, make_user):
    """整合：`/api/parts` 是 `SELECT * FROM parts` ＋ `dict(r)` 的真實路由。測試庫的 parts 暫時加欄位，中介層必須把它剝掉
    （正對照：同一庫直接查得到該欄，且把剝除換成恆等後同一路由會洩漏）。"""
    import db
    from tests.platform import _response_keys as RK
    u, p = make_user(username="ic_a", role="superadmin")
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    h = {"Authorization": "Bearer " + tok}
    c = db.get_db()
    try:
        RK.seed_every_table(c)
        if "owner_unit_id" not in [r[1] for r in c.execute("PRAGMA table_info(parts)")]:      # U0 遷移之後的樹上已經有；之前的樹上（基準錄製）才需要補
            c.execute("ALTER TABLE parts ADD COLUMN owner_unit_id INTEGER NOT NULL DEFAULT 1")
        c.commit()
        assert "owner_unit_id" in dict(c.execute("SELECT * FROM parts ORDER BY id DESC LIMIT 1").fetchone())      # 欄位真的存在
    finally:
        c.close()
    r = client.get("/api/parts", headers=h)
    assert r.status_code == 200 and r.json() and "owner_unit_id" not in r.text
    orig = IC.strip_internal_cols
    IC.strip_internal_cols = lambda o: o
    try:
        assert "owner_unit_id" in client.get("/api/parts", headers=h).text            # 正對照：不剝除就洩漏 ⇒ 上面的乾淨是中介層的功勞
    finally:
        IC.strip_internal_cols = orig


# ── table_digests ─────────────────────────────────────────────────────────────────────

def test_table_digests_ignore_internal_cols_by_default_but_explicit_columns_still_catch_missing(tmp_path):
    a, b = str(tmp_path / "a.db"), str(tmp_path / "b.db")
    for p, extra in ((a, ""), (b, ", owner_unit_id integer not null default 1")):
        c = sqlite3.connect(p)
        c.execute("create table t (id integer primary key, name text%s)" % extra)
        c.execute("insert into t (id, name) values (1, 'x')")
        c.commit()
        c.close()
    da, db_ = upgrade.table_digests(a), upgrade.table_digests(b)
    assert da["t"]["sha256"] == db_["t"]["sha256"] and db_["t"]["columns"] == ["id", "name"]
    miss = upgrade.table_digests(a, {"t": ["id", "name", "owner_unit_id"]})                 # 明列的欄位真的缺 ⇒ 仍然抓得到
    assert miss["t"]["sha256"] is None and miss["t"]["missing_columns"] == ["owner_unit_id"]
    both = upgrade.table_digests(b, {"t": ["id", "name", "owner_unit_id"]})                 # 明列且存在 ⇒ 算進去
    assert both["t"]["sha256"] != db_["t"]["sha256"]


# ── org_units 啟用判斷 ────────────────────────────────────────────────────────────────

@pytest.fixture
def sp():
    snap = spine.snapshot()
    spine.reset()
    yield spine
    spine.restore(snap)


def test_org_units_is_declared_hidden_in_core_and_disabled(sp):
    """U1 排定前不承諾任何版本：宣告為 hidden（不顯示卡片），啟用判斷為 False。"""
    assert spine.register_core_declarations() == []
    spine.validate_all()
    assert spine.feature_status("org_units") == "hidden" and spine.declared_and_open("org_units") is False
    assert "org_units" not in [c["code"] for c in spine.planned_cards()]


def test_declared_and_open_is_strict_in_every_direction(sp):
    assert spine.declared_and_open("zz_u0a") is False                          # 未宣告（feature_enabled 會是 True，這裡必須是 False）
    assert spine.feature_enabled("zz_u0a") is True
    spine.register_manifest({"features": [{"code": "zz_u0a", "label": "測試", "status": "open"}]}, "zz")
    assert spine.declared_and_open("zz_u0a") is False                          # 尚未 validate_all ⇒ 關
    spine.validate_all()
    assert spine.declared_and_open("zz_u0a") is True
    for st, extra in (("planned", {"planned_train": "MS4"}), ("hidden", {})):
        spine.reset()
        spine.register_manifest({"features": [dict({"code": "zz_u0a", "label": "測試", "status": st}, **extra)]}, "zz")
        spine.validate_all()
        assert spine.declared_and_open("zz_u0a") is False, st
    spine.reset()
    spine.register_manifest({"features": [{"code": "zz_u0a", "label": "測試", "mail": ["zz_nomail"]}]}, "zz")        # 驗證失敗
    spine.validate_all()
    assert spine.declared_and_open("zz_u0a") is False


def test_deleting_the_org_units_declaration_keeps_filters_off(sp, tmp_path):
    """0d S-b：刪掉 core/features_l1.json 裡的 org_units，啟用判斷仍為 False（不會因未宣告而 True）。"""
    data = json.loads(spine.CORE_FEATURES_FILE.read_text(encoding="utf-8"))
    data["features"] = [f for f in data["features"] if f["code"] != "org_units"]
    f = tmp_path / "features_l1.json"
    f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    spine.register_core_declarations(f)
    spine.validate_all()
    assert spine.feature_status("org_units") == "open" and spine.feature_enabled("org_units") is True      # 脊柱本身 fail-open
    assert spine.declared_and_open("org_units") is False                                                    # 單位強制必須用這個，不是上面那個
